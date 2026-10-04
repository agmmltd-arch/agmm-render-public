#!/usr/bin/env python3
"""Fail-closed source gate for film-preview-export, including one pinned OCR-skip review path."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = "agmmltd-arch/agmm-render-public"
REPOSITORY_ID = 1397641626
F07 = {
    "run_id": 37189588628,
    "tag": "F07-full-63243-9bb0efdd-20261004",
    "fid": "F07",
    "head_sha": "513381b0defd09775cdd4abc17933ffe3d9b3760",
    "title": "AGMM film F07-full-63243-9bb0efdd-20261004",
    "attempt": 1,
    "artifacts": {
        "F07-full-63243-9bb0efdd-20261004-AUDIO-GAIN-RECEIPT": (11299340229, 531, "sha256:bacbb1b0093b38f009b46357bf957a4519b535ed0a33597836ee7224c4395d9d"),
        "F07-full-63243-9bb0efdd-20261004-REVIEW-1080": (11298771988, 531758195, "sha256:8cf7bc360165650b5f6f780c480a8d0d802e81dc6c3be6db0a412c9901ba7f0e"),
        "F07-full-63243-9bb0efdd-20261004-MASTER-4K": (11298443835, 2178845752, "sha256:837e8787427919e26c51b9d60ce7df4ab3f3b9cccbd1c4404a7775247cd8f886"),
        "F07-full-63243-9bb0efdd-20261004-AUDIO-GAIN-PROOF": (11297824882, 94547850, "sha256:133fdec46b96a720f3a63a4c54c237d4f90502fe335cd59d53eeb1b015473c71"),
    },
}


def validate_source(run: dict, jobs_doc: dict, artifacts_doc: dict, *, policy: str, run_id: str, tag: str, fid: str, now: datetime | None = None) -> None:
    if policy not in ("require", "needs_ocr_review_only"):
        raise ValueError("unknown OCR policy")
    if run.get("id") != int(run_id) or run.get("repository", {}).get("full_name") != REPO:
        raise ValueError("source run/repository mismatch")
    repo = run["repository"]
    if repo.get("id") != REPOSITORY_ID or repo.get("private") is not False:
        raise ValueError("source repository identity or visibility mismatch")
    if run.get("path") != ".github/workflows/agmm-film.yml" or run.get("event") != "workflow_dispatch":
        raise ValueError("source workflow/event mismatch")
    if run.get("status") != "completed" or run.get("display_title") != "AGMM film " + tag:
        raise ValueError("source run is not the expected completed film run")
    if not tag.startswith(fid + "-"):
        raise ValueError("tag/FID mismatch")
    jobs = jobs_doc.get("jobs", [])
    if jobs_doc.get("total_count") != len(jobs) or not jobs:
        raise ValueError("source job provenance missing or incomplete")
    if any(j.get("run_id") != run["id"] or j.get("head_sha") != run.get("head_sha") or j.get("status") != "completed" for j in jobs):
        raise ValueError("source job identity/status mismatch")
    by_name = {j.get("name"): j for j in jobs}
    if len(by_name) != len(jobs) or "assemble" not in by_name or "macos-ocr" not in by_name:
        raise ValueError("source job names are missing or duplicated")

    if policy == "needs_ocr_review_only":
        if (fid, tag, int(run_id), run.get("head_sha"), run.get("display_title"), run.get("run_attempt")) != (
            F07["fid"], F07["tag"], F07["run_id"], F07["head_sha"], F07["title"], F07["attempt"]
        ):
            raise ValueError("OCR-skip mode is pinned to the exact F07 source run")
        if run.get("conclusion") != "success" or set(by_name) != {"assemble", "render", "macos-ocr"}:
            raise ValueError("pinned F07 job set/conclusion mismatch")
        if by_name["assemble"].get("conclusion") != "success" or by_name["render"].get("conclusion") != "skipped" or by_name["macos-ocr"].get("conclusion") != "skipped":
            raise ValueError("pinned F07 must prove successful assembly with render and OCR skipped")
        if any(j.get("head_sha") != F07["head_sha"] for j in jobs):
            raise ValueError("pinned F07 job head mismatch")
        artifacts = artifacts_doc.get("artifacts", [])
        if artifacts_doc.get("total_count") != len(artifacts):
            raise ValueError("source artifact metadata is incomplete")
        by_artifact = {a.get("name"): a for a in artifacts}
        if len(by_artifact) != len(artifacts) or set(by_artifact) != set(F07["artifacts"]):
            raise ValueError("pinned F07 artifact set mismatch")
        now = now or datetime.now(timezone.utc)
        for name, (artifact_id, size, digest) in F07["artifacts"].items():
            a = by_artifact[name]
            wr = a.get("workflow_run", {})
            if (a.get("id"), a.get("size_in_bytes"), a.get("digest"), a.get("expired"), wr.get("id"), wr.get("repository_id"), wr.get("head_repository_id"), wr.get("head_sha")) != (
                artifact_id, size, digest, False, F07["run_id"], REPOSITORY_ID, REPOSITORY_ID, F07["head_sha"]
            ):
                raise ValueError("pinned F07 artifact identity/digest/expiry mismatch: " + name)
            expires = datetime.fromisoformat(a["expires_at"].replace("Z", "+00:00"))
            if expires <= now:
                raise ValueError("pinned F07 artifact expired: " + name)
        return

    if run.get("conclusion") == "success":
        if by_name["assemble"].get("conclusion") != "success" or by_name["macos-ocr"].get("conclusion") != "success":
            raise ValueError("default policy requires successful native OCR")
        if any(j.get("conclusion") != "success" for j in jobs):
            raise ValueError("source run contains an unsuccessful job")
    elif run.get("conclusion") == "failure":
        if by_name["assemble"].get("conclusion") != "success" or by_name["macos-ocr"].get("conclusion") != "failure":
            raise ValueError("failed-run preview must be an OCR-only failure after successful assembly")
        if any(j.get("conclusion") != "success" for j in jobs if j.get("name") != "macos-ocr"):
            raise ValueError("failed-run preview contains a non-OCR job failure")
    else:
        raise ValueError("source run conclusion is not eligible")
    artifacts = artifacts_doc.get("artifacts", [])
    if artifacts_doc.get("total_count") != len(artifacts):
        raise ValueError("source artifact metadata is incomplete")
    ocr_name = tag + "-MACOS-VISION-OCR"
    matches = [a for a in artifacts if a.get("name") == ocr_name]
    if len(matches) != 1:
        raise ValueError("default policy requires exactly one native OCR artifact")
    artifact = matches[0]
    wr = artifact.get("workflow_run", {})
    if artifact.get("expired") is not False or wr.get("id") != run["id"] or wr.get("head_sha") != run.get("head_sha") or wr.get("repository_id") != REPOSITORY_ID:
        raise ValueError("native OCR artifact identity/expiry mismatch")
    if not isinstance(artifact.get("digest"), str) or not artifact["digest"].startswith("sha256:"):
        raise ValueError("native OCR artifact digest missing")
    expires = datetime.fromisoformat(artifact["expires_at"].replace("Z", "+00:00"))
    if expires <= (now or datetime.now(timezone.utc)):
        raise ValueError("native OCR artifact expired")


def validate_existing_asset(existing: dict | None, *, expected_size: int, expected_sha256: str) -> None:
    """Permit idempotent reuse only; never overwrite a different published asset."""
    if existing is not None and (existing.get("size") != expected_size or existing.get("digest") != "sha256:" + expected_sha256):
        raise ValueError("existing asset differs; no overwrite")


def main() -> None:
    try:
        if not sys.platform.startswith("linux") or os.environ.get("GITHUB_ACTIONS") != "true":
            raise ValueError("hosted Linux GitHub Actions required")
        validate_source(
            json.loads(Path("source-run.json").read_text()),
            json.loads(Path("source-jobs.json").read_text()),
            json.loads(Path("source-artifacts.json").read_text()),
            policy=os.environ.get("OCR_POLICY", "require"),
            run_id=os.environ["RUN_ID"], tag=os.environ["TAG"], fid=os.environ["FID"],
        )
    except (KeyError, OSError, ValueError, TypeError) as exc:
        raise SystemExit("Refusal: " + str(exc)) from exc


if __name__ == "__main__":
    main()
