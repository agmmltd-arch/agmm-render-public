#!/usr/bin/env python3
"""Pinned, hosted-only durable export of one F02 mechanical review preview.

Metadata validators and synthetic tests are local-safe. The prepare/publish commands
refuse outside GitHub-hosted Linux before opening artifact files or calling gh.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

REPO = "agmmltd-arch/agmm-render-public"
REPOSITORY_ID = 1397641626
RUN_ID = 37146440125
RUN_HEAD = "3be0bf2c26e2186710002796a80b1eda115c1d3f"
RUN_WORKFLOW = ".github/workflows/agmm-f02-partial-assembly.yml"
RUN_TITLE = "F02 partial mechanical assembly · 37146440125"
SOURCE_PACKAGE_SHA = "b216a14d62b2b5430234a411a1913207b41642071fc5985a11bbf09913d21719"
MASTER_SHA = "276ae17ca24d46c9b08508dc2cfaec00bc89ad6c1d3e4b96fd7d490e64c7c51e"
EXPECTED_ARTIFACTS = {
    11283198428: ("F02-PARTIAL-MASTER-4K-37146440125", 2849598139, "2026-10-04T19:36:03Z"),
    11283018672: ("F02-PARTIAL-SEGMENT-LINEAGE-37146440125", 2894181372, "2026-10-04T19:35:44Z"),
    11282993573: ("F02-PARTIAL-REVIEW-1080-37146440125", 737476170, "2026-10-04T19:36:22Z"),
}
MASTER_ARTIFACT_ID = 11283198428
REVIEW_ARTIFACT_ID = 11282993573
MASTER_NAME = "F02-MASTER-4K.mp4"
REVIEW_NAME = "F02-MASTER-1080-from-4K.mp4"
MAX_RELEASE_ASSET_BYTES = 1_500_000_000
MIN_RUNNER_FREE_BYTES = 12_000_000_000
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
CHECKS = {"segment_decode", "segment_flicker", "master_full_decode", "derived_full_decode",
          "encoded_audio_loudness_and_true_peak"}


class Refusal(ValueError):
    pass


def parse_time(value: str) -> datetime:
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise Refusal("source metadata timestamp is malformed") from exc
    if out.tzinfo is None:
        raise Refusal("source metadata timestamp has no timezone")
    return out.astimezone(timezone.utc)


def validate_source(repository: dict, run: dict, jobs_doc: dict, artifacts_doc: dict,
                    observed_at: datetime | None = None) -> dict:
    """Check the exact completed run, sole assembly job, and complete artifact inventory."""
    observed_at = observed_at or datetime.now(timezone.utc)
    if (repository.get("full_name") != REPO or repository.get("id") != REPOSITORY_ID
            or repository.get("private") is not False):
        raise Refusal("source repository is not the pinned public repository")
    if run.get("id") != RUN_ID or (run.get("repository") or {}).get("full_name") != REPO:
        raise Refusal("source run identity/repository mismatch")
    if (run.get("path") != RUN_WORKFLOW or run.get("event") != "workflow_dispatch"
            or run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("head_sha") != RUN_HEAD or run.get("run_attempt") != 1
            or run.get("display_title") != RUN_TITLE):
        raise Refusal("source run is not the pinned completed-success F02 assembly")
    run_start = parse_time(run.get("created_at"))
    run_end = parse_time(run.get("updated_at"))
    jobs = jobs_doc.get("jobs")
    if jobs_doc.get("total_count") != 1 or not isinstance(jobs, list) or len(jobs) != 1:
        raise Refusal("source workflow job set changed")
    job = jobs[0]
    if (job.get("name") != "assemble" or job.get("run_id") != RUN_ID
            or job.get("head_sha") != RUN_HEAD or job.get("status") != "completed"
            or job.get("conclusion") != "success"):
        raise Refusal("source assemble job is not an exact completed success")
    arts = artifacts_doc.get("artifacts")
    if artifacts_doc.get("total_count") != len(EXPECTED_ARTIFACTS) or not isinstance(arts, list):
        raise Refusal("source artifact inventory changed")
    by_id = {a.get("id"): a for a in arts}
    if len(by_id) != len(arts) or set(by_id) != set(EXPECTED_ARTIFACTS):
        raise Refusal("source artifact IDs do not match pinned inventory")
    for aid, (name, size, expires) in EXPECTED_ARTIFACTS.items():
        a = by_id[aid]
        wr = a.get("workflow_run") or {}
        if (a.get("name") != name or a.get("size_in_bytes") != size or a.get("expired") is not False
                or a.get("expires_at") != expires
                or wr.get("id") != RUN_ID or wr.get("head_sha") != RUN_HEAD
                or wr.get("repository_id") != REPOSITORY_ID):
            raise Refusal(f"pinned source artifact metadata mismatch: {aid}")
        created_at = parse_time(a.get("created_at"))
        if created_at < run_start or created_at > run_end:
            raise Refusal(f"source artifact creation time falls outside its run: {aid}")
        if parse_time(expires) <= observed_at:
            raise Refusal(f"pinned source artifact expired: {aid}")
    return {"run_id": RUN_ID, "repository": REPO, "workflow": RUN_WORKFLOW,
            "head_sha": RUN_HEAD, "conclusion": "success", "run_attempt": 1,
            "artifacts": [{"id": aid, "name": EXPECTED_ARTIFACTS[aid][0],
                           "size_in_bytes": EXPECTED_ARTIFACTS[aid][1],
                           "expires_at": EXPECTED_ARTIFACTS[aid][2],
                           "created_at": by_id[aid]["created_at"]}
                          for aid in sorted(EXPECTED_ARTIFACTS)]}


def validate_source_receipt(source_run: dict) -> None:
    if (source_run.get("run_id") != RUN_ID or source_run.get("repository") != REPO
            or source_run.get("workflow") != RUN_WORKFLOW or source_run.get("head_sha") != RUN_HEAD
            or source_run.get("conclusion") != "success" or source_run.get("run_attempt") != 1):
        raise Refusal("validated source receipt identity mismatch")
    artifacts = source_run.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(EXPECTED_ARTIFACTS):
        raise Refusal("validated source receipt artifact set mismatch")
    by_id = {a.get("id"): a for a in artifacts}
    if len(by_id) != len(artifacts) or set(by_id) != set(EXPECTED_ARTIFACTS):
        raise Refusal("validated source receipt artifact IDs mismatch")
    for aid, (name, size, expires) in EXPECTED_ARTIFACTS.items():
        a = by_id[aid]
        if (a.get("name") != name or a.get("size_in_bytes") != size
                or a.get("expires_at") != expires):
            raise Refusal(f"validated source receipt metadata mismatch: {aid}")


def require_hosted_runner() -> None:
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise Refusal("artifact export and hashing require hosted GitHub Linux")


def require_runner_capacity(path: Path = Path("."), minimum_bytes: int = MIN_RUNNER_FREE_BYTES) -> int:
    require_hosted_runner()
    if type(minimum_bytes) is not int or minimum_bytes <= 0:
        raise Refusal("runner free-space threshold must be a positive integer")
    available = shutil.disk_usage(path).free
    if available < minimum_bytes:
        raise Refusal(f"runner has {available} free bytes; requires at least {minimum_bytes} before artifact download")
    return available


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def checksum_map(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9._-]+)", line)
        if not match or match.group(2) in result:
            raise Refusal("SHA256SUMS is malformed or contains duplicate names")
        result[match.group(2)] = match.group(1)
    if not result:
        raise Refusal("SHA256SUMS is empty")
    return result


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise Refusal(f"required receipt is missing or malformed: {path.name}") from exc
    if not isinstance(data, dict):
        raise Refusal(f"receipt root must be an object: {path.name}")
    return data


def validate_lineage(lineage: dict) -> None:
    if (lineage.get("kind") != "f02_segment_lineage_manifest"
            or lineage.get("source_release") != "F02-profit-qualifier-20261003"
            or lineage.get("source_package_sha256") != SOURCE_PACKAGE_SHA
            or lineage.get("parent_run_id") != 37125818648
            or lineage.get("replacement_run_id") != 37143394055
            or lineage.get("apply_source_overlay") is not False
            or lineage.get("release_approval") != "NOT_GRANTED"):
        raise Refusal("lineage source or approval metadata mismatch")
    rows = lineage.get("segment_provenance")
    if not isinstance(rows, list) or len(rows) != 77:
        raise Refusal("lineage must retain 75 parent entries and 2 replacements")
    parent = [r for r in rows if r.get("provenance_role") == "parent"]
    replacement = [r for r in rows if r.get("provenance_role") == "replacement"]
    if (len(parent) != 75 or len(replacement) != 2
            or {r.get("segment") for r in parent} != {f"{n:02d}" for n in range(1, 76)}
            or {r.get("segment") for r in replacement} != {"51", "52"}):
        raise Refusal("lineage does not prove 75 parent segments plus replacements 51/52")


def validate_integrity(master_dir: Path, review_dir: Path,
                       expected_master_sha: str = MASTER_SHA) -> tuple[dict, dict, dict]:
    integrity = _json(master_dir / "REMOTE-INTEGRITY.json")
    if integrity != _json(review_dir / "REMOTE-INTEGRITY.json"):
        raise Refusal("master and review artifact integrity receipts differ")
    if (integrity.get("kind") != "mechanical_integrity_only"
            or integrity.get("editorial_gate") != "NOT_RUN"
            or integrity.get("release_approval") != "NOT_GRANTED"
            or integrity.get("duration") != 651.6 or integrity.get("fps") != 30
            or integrity.get("segment_count") != 75 or integrity.get("frame_count") != 19548):
        raise Refusal("mechanical-only integrity receipt scope/status mismatch")
    checks = integrity.get("checks")
    if not isinstance(checks, dict) or set(checks) != CHECKS or any(v != "PASS" for v in checks.values()):
        raise Refusal("mechanical check schema/status mismatch")
    outputs = integrity.get("outputs")
    if not isinstance(outputs, dict) or outputs.get("master") != MASTER_NAME or outputs.get("derived") != REVIEW_NAME:
        raise Refusal("integrity receipt output names mismatch")
    for key in ("master_bytes", "derived_bytes"):
        if type(outputs.get(key)) is not int or outputs[key] <= 0:
            raise Refusal(f"integrity receipt has invalid {key}")
    if not isinstance(outputs.get("master_sha256"), str) or not SHA_RE.fullmatch(outputs["master_sha256"]):
        raise Refusal("integrity receipt has invalid master_sha256")
    if outputs["master_sha256"] != expected_master_sha:
        raise Refusal("F02 master hash differs from the terminal hosted receipt")
    master_receipt = _json(master_dir / "F02-PARTIAL-ASSEMBLY-RECEIPT.json")
    review_receipt = _json(review_dir / "F02-PARTIAL-ASSEMBLY-RECEIPT.json")
    if master_receipt != review_receipt:
        raise Refusal("partial assembly receipts differ across artifacts")
    if (master_receipt.get("kind") != "F02-hosted-partial-assembly-receipt"
            or master_receipt.get("status") != "MECHANICAL_INTEGRITY_VERIFIED_ONLY"
            or master_receipt.get("editorial_status") != "NOT_REVIEWED"
            or master_receipt.get("release_approval") != "NOT_GRANTED"
            or master_receipt.get("armed") is not False
            or master_receipt.get("source_release") != "F02-profit-qualifier-20261003"
            or master_receipt.get("source_package_sha256") != SOURCE_PACKAGE_SHA
            or master_receipt.get("segments") != 75 or master_receipt.get("frames") != 19548
            or master_receipt.get("checks") != checks):
        raise Refusal("partial assembly receipt is not the exact unapproved mechanical result")
    assembled_outputs = master_receipt.get("master")
    if (not isinstance(assembled_outputs, dict)
            or assembled_outputs.get("master") != MASTER_NAME
            or assembled_outputs.get("master_bytes") != outputs["master_bytes"]
            or assembled_outputs.get("master_sha256") != outputs["master_sha256"]
            or assembled_outputs.get("derived") != REVIEW_NAME
            or assembled_outputs.get("derived_bytes") != outputs["derived_bytes"]
            or not isinstance(assembled_outputs.get("derived_sha256"), str)
            or not SHA_RE.fullmatch(assembled_outputs["derived_sha256"])):
        raise Refusal("partial assembly receipt lacks exact master/proxy size and digest metadata")
    lineage = _json(master_dir / "F02-LINEAGE.json")
    if lineage != _json(review_dir / "F02-LINEAGE.json"):
        raise Refusal("lineage manifests differ across artifacts")
    validate_lineage(lineage)
    master_sums = checksum_map(master_dir / "SHA256SUMS.txt")
    review_sums = checksum_map(review_dir / "SHA256SUMS.txt")
    if master_sums != review_sums:
        raise Refusal("checksums differ across master and review artifact manifests")
    required = {MASTER_NAME, REVIEW_NAME, "F02-LINEAGE.json", "F02-PARTIAL-ASSEMBLY-RECEIPT.json",
                "REMOTE-INTEGRITY.json", "AUDIO-GAIN-RECEIPT.json"}
    if not required <= set(master_sums):
        raise Refusal("checksum manifest omits a required master/proxy/lineage receipt")
    for folder, name, expected_size, expected_sha in (
        (master_dir, MASTER_NAME, outputs["master_bytes"], outputs["master_sha256"]),
        (review_dir, REVIEW_NAME, outputs["derived_bytes"], assembled_outputs["derived_sha256"]),
    ):
        path = folder / name
        if not path.is_file() or path.stat().st_size != expected_size:
            raise Refusal(f"downloaded output size mismatch: {name}")
        actual = sha256(path)
        if actual != expected_sha or master_sums.get(name) != actual:
            raise Refusal(f"downloaded output digest mismatch: {name}")
    for folder in (master_dir, review_dir):
        for name in ("F02-LINEAGE.json", "F02-PARTIAL-ASSEMBLY-RECEIPT.json",
                     "REMOTE-INTEGRITY.json", "AUDIO-GAIN-RECEIPT.json"):
            if sha256(folder / name) != master_sums[name]:
                raise Refusal(f"downloaded receipt digest mismatch: {name}")
    sidecar = _json(review_dir / f"{REVIEW_NAME}.derived.json")
    if (sidecar.get("master") != MASTER_NAME
            or sidecar.get("master_sha256") != outputs["master_sha256"]
            or sidecar.get("derived") != REVIEW_NAME
            or sidecar.get("derived_bytes") != outputs["derived_bytes"]
            or sha256(review_dir / f"{REVIEW_NAME}.derived.json") != master_sums.get(f"{REVIEW_NAME}.derived.json")):
        raise Refusal("derived proxy sidecar does not bind to the pinned master/proxy")
    audio = _json(master_dir / "AUDIO-GAIN-RECEIPT.json")
    if audio.get("status") != "PASS":
        raise Refusal("encoded audio mechanical check is not PASS")
    return integrity, master_receipt, lineage


def split_master(source: Path, out_dir: Path, limit: int = MAX_RELEASE_ASSET_BYTES) -> list[dict]:
    if type(limit) is not int or limit <= 0 or limit >= 2_000_000_000:
        raise Refusal("release part limit must be a positive integer below 2 GB")
    out_dir.mkdir(parents=True, exist_ok=True)
    total_size = source.stat().st_size
    if total_size <= limit:
        digest = sha256(source)
        return [{"name": source.name, "path": str(source), "size": total_size, "sha256": digest}]
    pieces = []
    full = hashlib.sha256()
    total = 0
    with source.open("rb") as incoming:
        idx = 1
        while True:
            first = incoming.read(min(1024 * 1024, limit))
            if not first:
                break
            target = out_dir / f"{source.name}.part{idx:04d}"
            part_hash = hashlib.sha256()
            part_size = 0
            with target.open("xb") as outgoing:
                chunk = first
                while chunk:
                    if part_size + len(chunk) > limit:
                        raise Refusal("splitter read exceeded part limit")
                    if not chunk:
                        break
                    outgoing.write(chunk)
                    part_hash.update(chunk)
                    full.update(chunk)
                    part_size += len(chunk)
                    total += len(chunk)
                    if part_size == limit:
                        break
                    chunk = incoming.read(min(1024 * 1024, limit - part_size))
            if part_size == 0:
                target.unlink()
                break
            pieces.append({"name": target.name, "path": str(target), "size": part_size,
                           "sha256": part_hash.hexdigest()})
            idx += 1
            if part_size < limit:
                break
    if total != total_size or full.hexdigest() != sha256(source):
        raise Refusal("split master parts do not reconstruct original size and SHA-256")
    if any(p["size"] > limit or p["size"] >= 2_000_000_000 for p in pieces):
        raise Refusal("split master part exceeds the release asset bound")
    return pieces


def prepare_export(master_dir: Path, review_dir: Path, source_run: dict, out_dir: Path,
                   *, part_limit: int = MAX_RELEASE_ASSET_BYTES, observed_at: str | None = None,
                   expected_master_sha: str = MASTER_SHA) -> dict:
    require_hosted_runner()
    validate_source_receipt(source_run)
    integrity, assembly, lineage = validate_integrity(master_dir, review_dir, expected_master_sha)
    out_dir.mkdir(parents=True, exist_ok=False)
    original = master_dir / MASTER_NAME
    pieces = split_master(original, out_dir / "master-parts", part_limit)
    proxy = review_dir / REVIEW_NAME
    derived_info = assembly["master"]
    assets = pieces + [{"name": REVIEW_NAME, "path": str(proxy),
                        "size": proxy.stat().st_size, "sha256": sha256(proxy)}]
    record = {
        "schema_version": 3,
        "source_run_id": RUN_ID,
        "repository": REPO,
        "source_workflow": RUN_WORKFLOW,
        "source_workflow_commit": RUN_HEAD,
        "source_conclusion": "success",
        "source_artifacts": source_run["artifacts"],
        "files": assets,
        "integrity": integrity,
        "assembly": assembly,
        "lineage": lineage,
        "master": {"name": MASTER_NAME, "size": integrity["outputs"]["master_bytes"],
                   "sha256": integrity["outputs"]["master_sha256"],
                   "parts": [p["name"] for p in pieces],
                   "reassembly": "Concatenate listed parts in order on a hosted runner; verify full size and SHA-256 before use. No re-encoding."},
        "derived": {"name": REVIEW_NAME, "size": derived_info["derived_bytes"],
                    "sha256": derived_info["derived_sha256"]},
        "preview_status": "NOT_REVIEWED",
        "review_status": "NOT_REVIEWED",
        "ocr_status": "NOT_RUN",
        "ocr": {"status": "NOT_RUN", "reason": "Pinned partial-assembly workflow does not run OCR."},
        "release_approval": "NOT_GRANTED",
        "armed": False,
    }
    (out_dir / "HOSTED-PREVIEW.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def run_gh(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], text=True, capture_output=capture, check=False)


def validate_existing_release_assets(expected: dict[str, dict], assets: list[dict]) -> dict[str, dict]:
    existing = {}
    for asset in assets:
        name = asset.get("name")
        if name in existing or name not in expected:
            raise Refusal("versioned preview release contains duplicate or unexpected assets")
        existing[name] = asset
        spec = expected[name]
        if asset.get("size") != spec["size"] or asset.get("digest") != "sha256:" + spec["sha256"]:
            raise Refusal(f"existing release asset differs; no overwrite: {name}")
    return existing


def validate_published_release_assets(expected: dict[str, dict], assets: list[dict], tag: str) -> dict[str, dict]:
    existing = validate_existing_release_assets(expected, assets)
    if set(existing) != set(expected):
        raise Refusal("published release asset set differs from manifest")
    for name, spec in expected.items():
        asset = existing[name]
        expected_url = f"https://github.com/{REPO}/releases/download/{tag}/{name}"
        if asset.get("browser_download_url") != expected_url:
            raise Refusal(f"published release asset URL mismatch: {name}")
    return existing


def publish_preview(preview_dir: Path) -> dict:
    """Create a unique release and verify every asset before exposing its text receipt."""
    require_hosted_runner()
    manifest_path = preview_dir / "HOSTED-PREVIEW.json"
    record = _json(manifest_path)
    if (record.get("source_run_id") != RUN_ID or record.get("source_workflow_commit") != RUN_HEAD
            or record.get("release_approval") != "NOT_GRANTED"
            or record.get("preview_status") != "NOT_REVIEWED"
            or record.get("ocr_status") != "NOT_RUN"):
        raise Refusal("preview manifest lost exact source or unapproved status")
    tag = f"preview-F02-{RUN_ID}"
    release_url = f"https://github.com/{REPO}/releases/tag/{tag}"
    asset_paths = {}
    for spec in record["files"]:
        asset_paths[spec["name"]] = spec.pop("path")
        spec["url"] = f"https://github.com/{REPO}/releases/download/{tag}/{spec['name']}"
    receipt_name = "HOSTED-PREVIEW.json"
    record["release_tag"] = tag
    record["release_url"] = release_url
    record["receipt_asset"] = {"name": receipt_name,
                               "url": f"https://github.com/{REPO}/releases/download/{tag}/{receipt_name}",
                               "purpose": "public text-only export receipt; root adopts metadata separately"}
    manifest_path.write_text(json.dumps(record, indent=2) + "\n")
    receipt_size = manifest_path.stat().st_size
    receipt_sha = sha256(manifest_path)
    release_query = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"], capture=True)
    if release_query.returncode:
        created = run_gh(["release", "create", tag, "-R", REPO, "--target", RUN_HEAD,
                          "--title", f"F02 partial review preview {RUN_ID}",
                          "--notes", "Hosted mechanical verification only. Human audiovisual review NOT_REVIEWED; OCR NOT_RUN; release approval NOT_GRANTED."], capture=True)
        if created.returncode:
            raise Refusal("could not create the versioned preview release")
        release_query = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"], capture=True)
        if release_query.returncode:
            raise Refusal("created preview release could not be read back")
    release = json.loads(release_query.stdout)
    if release.get("tag_name") != tag:
        raise Refusal("preview release tag mismatch; refusing overwrite")
    commit_query = run_gh(["api", f"repos/{REPO}/commits/{tag}"], capture=True)
    if commit_query.returncode or json.loads(commit_query.stdout).get("sha") != RUN_HEAD:
        raise Refusal("versioned preview tag does not resolve to the pinned source commit")
    expected = {a["name"]: a for a in record["files"]}
    expected_with_receipt = {**expected, receipt_name: {"name": receipt_name, "size": receipt_size,
                                                         "sha256": receipt_sha,
                                                         "url": record["receipt_asset"]["url"]}}
    existing = validate_existing_release_assets(expected_with_receipt, release.get("assets", []))
    for name, spec in expected.items():
        if name not in existing:
            uploaded = run_gh(["release", "upload", tag, asset_paths[name], "-R", REPO], capture=True)
            if uploaded.returncode:
                raise Refusal(f"release upload failed for {name}")
    # Verify video assets before the public text receipt is attached. An interrupted
    # export therefore cannot make an unverified receipt look authoritative.
    video_query = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"], capture=True)
    if video_query.returncode:
        raise Refusal("uploaded preview assets could not be read back")
    video_release = json.loads(video_query.stdout)
    before_receipt = validate_existing_release_assets(expected_with_receipt,
                                                       video_release.get("assets", []))
    if not set(expected) <= set(before_receipt):
        raise Refusal("one or more video preview assets are not yet present")
    if receipt_name not in existing:
        uploaded = run_gh(["release", "upload", tag, str(manifest_path), "-R", REPO], capture=True)
        if uploaded.returncode:
            raise Refusal("public text receipt upload failed")
    release_query = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"], capture=True)
    if release_query.returncode:
        raise Refusal("published preview release could not be verified")
    release = json.loads(release_query.stdout)
    assets = validate_published_release_assets(expected_with_receipt, release.get("assets", []), tag)
    for name, spec in expected.items():
        asset = assets[name]
        if (asset.get("size") != spec["size"] or asset.get("digest") != "sha256:" + spec["sha256"]
                or asset.get("browser_download_url") != spec["url"]):
            raise Refusal(f"published release asset digest/size/url verification failed: {name}")
    receipt_asset = assets[receipt_name]
    if (receipt_asset.get("size") != receipt_size or receipt_asset.get("digest") != "sha256:" + receipt_sha
            or receipt_asset.get("browser_download_url") != record["receipt_asset"]["url"]):
        raise Refusal("public text receipt asset digest/size/url verification failed")
    # The existing status/F02-preview.json pointer stays untouched. Root can
    # adopt this verified public receipt atomically, preserving the prior preview.
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate-source")
    check.add_argument("--run", type=Path, required=True)
    check.add_argument("--repository", type=Path, required=True)
    check.add_argument("--jobs", type=Path, required=True)
    check.add_argument("--artifacts", type=Path, required=True)
    check.add_argument("--out", type=Path, required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--master-dir", type=Path, required=True)
    prep.add_argument("--review-dir", type=Path, required=True)
    prep.add_argument("--source", type=Path, required=True)
    prep.add_argument("--out-dir", type=Path, required=True)
    pub = sub.add_parser("publish")
    pub.add_argument("--preview-dir", type=Path, required=True)
    capacity = sub.add_parser("check-capacity")
    capacity.add_argument("--minimum-bytes", type=int, default=MIN_RUNNER_FREE_BYTES)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-source":
            source = validate_source(_json(args.repository), _json(args.run), _json(args.jobs), _json(args.artifacts))
            args.out.write_text(json.dumps(source, indent=2) + "\n")
            print("source run/jobs/artifact inventory PASS; metadata only")
        elif args.command == "prepare":
            require_hosted_runner()
            source = _json(args.source)
            rec = prepare_export(args.master_dir, args.review_dir, source, args.out_dir)
            print(f"prepared {len(rec['files'])} verified preview asset(s); NOT_REVIEWED; OCR NOT_RUN; no approval")
        elif args.command == "publish":
            rec = publish_preview(args.preview_dir)
            print(f"public preview assets and text receipt verified: {rec['release_tag']}; "
                  "NOT_REVIEWED; OCR NOT_RUN; prior page/status pointer unchanged")
        elif args.command == "check-capacity":
            available = require_runner_capacity(minimum_bytes=args.minimum_bytes)
            print(f"hosted runner capacity PASS: {available} free bytes; no artifacts opened")
        return 0
    except (Refusal, OSError, json.JSONDecodeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
