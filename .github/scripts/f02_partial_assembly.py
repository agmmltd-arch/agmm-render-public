#!/usr/bin/env python3
"""Hosted-Linux-only F02 partial reassembly and provenance guard.

This program deliberately refuses to process media on Darwin. Metadata-only validation
and --self-test are text/code operations; the download, source extraction, staging,
hashing and assembly paths are intended only for the ubuntu GitHub runner.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CONTRACT_PATH = HERE / "F02-partial-assembly-contract.json"
EXPECTED_REPO = "agmmltd-arch/agmm-render-public"
EXPECTED_WORKFLOW = ".github/workflows/agmm-film.yml"
ARTIFACT_RETENTION_BUFFER = timedelta(hours=4)
EXPECTED_SOURCE_CAPTURE_RUN_ID = 37197470531
EXPECTED_SOURCE_HEAD_SHA = "e67188f26c2afeaf7ebb01b2696a756062d8c63c"
EXPECTED_SOURCE_ARCHIVE_SHA256 = "3f072ce0281b195f69b945cf7b76279e5e95efe71b794356953dbd51320c91d5"
EXPECTED_SOURCE_RELEASE_ID = 402977719
EXPECTED_SOURCE_ASSET_ID = 609677772
EXPECTED_SOURCE_ASSET_BYTES = 37971142
EXPECTED_SOURCE_RECEIPT_ASSET_ID = 609677771
EXPECTED_SOURCE_RECEIPT_BYTES = 2843
EXPECTED_SOURCE_RECEIPT_SHA256 = "304c17e0182daecc74d9584e948737b1ca922341ae210d345daa3408906f4c1a"
EXPECTED_CAPTURE_RECEIPT_SHA256 = "51578e3963be0d20cac0d5761b1487c5c490b2d9e9eec9768264f6f7ecd8e122"
EXPECTED_REVIEW_RECEIPT_SHA256 = "86a79db1595ecff8f26dffbbf453cc91066bb7d44c5c25392a858277cd5558ef"
EXPECTED_FRAME_TREE_SHA256 = "d365b76f5ffba9955897b9df15c6e38b53786177107b7614023f65f2d9ca02bb"
EXPECTED_FRAME_BRANCH = "review-F02-opening-camera-extraction-candidate-37197470531"
EXPECTED_FRAME_BRANCH_TIP = "7698be0e4c9b92446ea699488b456256fa71e041"
EXPECTED_FRAME_INVENTORY_SHA256 = "9e9b51c97d2b5e0fcf4d0de75c3ed714656b7d2f848c3be601a7dff903ac68cd"
EXPECTED_QA_OVERLAY_RELEASE = "F02-r2c-landscape-4k-202609302152"
EXPECTED_QA_OVERLAY_RELEASE_ID = 400428198
EXPECTED_QA_OVERLAY_ASSET = "qa-overlay-r4e-seg12.tar.gz"
EXPECTED_QA_OVERLAY_ASSET_ID = 601787380
EXPECTED_QA_OVERLAY_ASSET_BYTES = 77973
EXPECTED_QA_OVERLAY_SHA256 = "76daca8d0d38c7bc26ca13dcc29a6e0da82f77f07c0f25028671b72f850e717f"
MAX_ARCHIVE_FILES = 30_000
MAX_ARCHIVE_BYTES = 2_000_000_000
MAX_ARCHIVE_MEMBER_BYTES = 500_000_000
AUTHORITATIVE_HELPER_SHA256 = "eac69b56c018c3b1b122d5e48a1ed962c3334e3ab91d04d155db6402e8f1dac6"
RENDER_JOB_RE = re.compile(r"^render \((\d{1,2}),\s*([0-9]+(?:\.[0-9]+)?),\s*([0-9]+(?:\.[0-9]+)?)\)$")


class Refusal(ValueError):
    """Fail-closed validation error."""


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text())


def parse_time(value: str) -> datetime:
    if not value:
        raise Refusal("timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise Refusal(f"timestamp has no timezone: {value}")
    return parsed.astimezone(timezone.utc)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json_or_jsonl(path: Path) -> Any:
    raw = path.read_text().strip()
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]


def collection(path: Path, key: str) -> list[dict[str, Any]]:
    obj = read_json_or_jsonl(path)
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict) and isinstance(obj.get(key), list):
        return obj[key]
    if isinstance(obj, dict) and isinstance(obj.get("artifacts"), list):
        return obj["artifacts"]
    if isinstance(obj, dict) and isinstance(obj.get("jobs"), list):
        return obj["jobs"]
    raise Refusal(f"{path.name} does not contain a {key} list")


def validate_public_repository(obj: dict[str, Any]) -> None:
    if obj.get("full_name") != EXPECTED_REPO or obj.get("private") is not False:
        raise Refusal("GitHub repository must be the exact public renderer repository")


def validate_source_review_receipts(c: dict[str, Any]) -> None:
    review = c["source_capture_review"]
    comp = c["composition"]
    expected_paths = {
        "receipt_path": ".github/receipts/F02-source-candidate-review.json",
        "capture_receipt_path": ".github/receipts/F02-source-candidate-capture.json",
        "source_receipt_path": ".github/receipts/F02-source-candidate-source-receipt.json",
        "frame_publication_path": ".github/receipts/F02-source-candidate-frame-publication.json",
    }
    expected_digests = {
        "receipt_sha256": EXPECTED_REVIEW_RECEIPT_SHA256,
        "capture_receipt_sha256": EXPECTED_CAPTURE_RECEIPT_SHA256,
        "source_receipt_sha256": EXPECTED_SOURCE_RECEIPT_SHA256,
        "frame_publication_sha256": EXPECTED_FRAME_TREE_SHA256,
    }
    paths: dict[str, Path] = {}
    for key, expected_path in expected_paths.items():
        if review.get(key) != expected_path:
            raise Refusal(f"source review evidence path changed: {key}")
        rel = Path(expected_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise Refusal(f"source review evidence path is unsafe: {key}")
        path = REPO_ROOT / rel
        if path.is_symlink() or not path.is_file():
            raise Refusal(f"source review evidence file is missing or unsafe: {key}")
        paths[key] = path
    for key, expected_digest in expected_digests.items():
        path_key = {"receipt_sha256": "receipt_path", "capture_receipt_sha256": "capture_receipt_path",
                    "source_receipt_sha256": "source_receipt_path", "frame_publication_sha256": "frame_publication_path"}[key]
        digest = sha256(paths[path_key])
        if review.get(key) != expected_digest or digest != expected_digest:
            raise Refusal(f"source capture/review evidence digest mismatch: {key}")
    accepted = json.loads(paths["receipt_path"].read_text())
    captured = json.loads(paths["capture_receipt_path"].read_text())
    source_receipt = json.loads(paths["source_receipt_path"].read_text())
    publication = json.loads(paths["frame_publication_path"].read_text())
    verdict = accepted.get("verdict", {})
    run = accepted.get("workflow_run", {})
    browser = accepted.get("browser_visual_check", {})
    pub_review = accepted.get("frame_publication", {})
    if (accepted.get("kind") != "independent_source_candidate_visual_still_review"
            or accepted.get("repository") != EXPECTED_REPO
            or run.get("id") != EXPECTED_SOURCE_CAPTURE_RUN_ID
            or run.get("id") != review.get("capture_run_id")
            or run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("run_head_sha") != EXPECTED_SOURCE_HEAD_SHA
            or review.get("source_head_sha") != EXPECTED_SOURCE_HEAD_SHA
            or verdict.get("source_still_review") != "ACCEPT_WITH_SCOPE_LIMITATIONS"
            or verdict.get("full_av_review") != "OPEN"
            or verdict.get("whole_video_approval") != "NOT_GRANTED"
            or verdict.get("release_approval") != "NOT_GRANTED"
            or verdict.get("owner_adoption") != "NOT_ADOPTED"):
        raise Refusal("review receipt is not the exact limited-scope independent source-still acceptance")
    if (review.get("status") != "ACCEPT_WITH_SCOPE_LIMITATIONS"
            or review.get("source_sha256") != EXPECTED_SOURCE_ARCHIVE_SHA256
            or review.get("source_sha256") != comp.get("sealed_source_package_sha256")
            or review.get("full_av_review") != "OPEN"
            or review.get("whole_video_approval") != "NOT_GRANTED"
            or review.get("release_approval") != "NOT_GRANTED"
            or review.get("owner_adoption") != "NOT_ADOPTED"):
        raise Refusal("contract source-review scope or current source binding changed")
    if (browser.get("unique_images_opened") != 74 or browser.get("image_complete") is not True
            or browser.get("current_src_matched_expected_raw_url") is not True
            or browser.get("natural_dimensions") != "1920x1080 for all 74"):
        raise Refusal("review receipt lacks complete browser verification for all 74 stills")
    if (captured.get("kind") != "f02-isolated-source-candidate-capture"
            or captured.get("candidate_class") != "isolated_source_candidate"
            or captured.get("capture_class") != "isolated_source_candidate_composition_only"
            or captured.get("source_asset_sha256") != EXPECTED_SOURCE_ARCHIVE_SHA256
            or captured.get("source_asset_sha256") != comp.get("sealed_source_package_sha256")
            or captured.get("source_release") != comp.get("sealed_source_release")
            or captured.get("source_release_id") != EXPECTED_SOURCE_RELEASE_ID
            or captured.get("source_asset_id") != EXPECTED_SOURCE_ASSET_ID
            or comp.get("sealed_source_release_id") != EXPECTED_SOURCE_RELEASE_ID
            or comp.get("sealed_source_asset_id") != EXPECTED_SOURCE_ASSET_ID
            or comp.get("sealed_source_package_bytes") != EXPECTED_SOURCE_ASSET_BYTES
            or captured.get("owner_adoption") != "NOT_ADOPTED"
            or captured.get("editorial_status") != "NOT_REVIEWED"
            or captured.get("release_approval") != "NOT_GRANTED"):
        raise Refusal("capture receipt does not bind the current unadopted source candidate")
    if (source_receipt.get("kind") != "f02-hosted-isolated-source-candidate-overlay"
            or source_receipt.get("source_archive_sha256") != EXPECTED_SOURCE_ARCHIVE_SHA256
            or source_receipt.get("source_archive_tag") != comp.get("sealed_source_release")
            or source_receipt.get("source_archive_bytes") != comp.get("sealed_source_package_bytes")
            or source_receipt.get("parent_source_sha256") != c["parent_lineage"].get("source_package_sha256")
            or source_receipt.get("mix_logo_and_other_parent_members_byte_identical") is not True
            or source_receipt.get("rendered_media_changed") is not False
            or source_receipt.get("changed_package_members") != ["SHA256SUMS.txt", "film/film.js", "film/sets_a.js"]
            or source_receipt.get("overlay_files") != captured.get("overlay_files")
            or {k: v.get("sha256") for k, v in source_receipt.get("overlay_files", {}).items()} != comp.get("expected_repair_files")
            or source_receipt.get("release_approval") != "NOT_GRANTED"
            or source_receipt.get("owner_adoption") != "NOT_ADOPTED"):
        raise Refusal("sealed source receipt does not prove the exact code-only parent overlay")
    if (pub_review.get("branch") != EXPECTED_FRAME_BRANCH
            or pub_review.get("branch_tip_sha") != EXPECTED_FRAME_BRANCH_TIP
            or pub_review.get("frame_count") != 74
            or pub_review.get("frame_inventory_sha256") != EXPECTED_FRAME_INVENTORY_SHA256
            or review.get("frame_publication_branch") != EXPECTED_FRAME_BRANCH
            or review.get("frame_publication_tip_sha") != EXPECTED_FRAME_BRANCH_TIP
            or review.get("frame_inventory_sha256") != EXPECTED_FRAME_INVENTORY_SHA256):
        raise Refusal("independent review does not bind the exact current frame-publication branch and tip")
    if (publication.get("repository") != EXPECTED_REPO
            or publication.get("branch") != EXPECTED_FRAME_BRANCH
            or publication.get("branch_tip_sha") != EXPECTED_FRAME_BRANCH_TIP
            or publication.get("source_run_id") != EXPECTED_SOURCE_CAPTURE_RUN_ID
            or publication.get("run_head_sha") != EXPECTED_SOURCE_HEAD_SHA
            or publication.get("frame_count") != 74
            or publication.get("frame_inventory_sha256") != EXPECTED_FRAME_INVENTORY_SHA256):
        raise Refusal("saved public GitHub frame tree does not bind the reviewed capture and branch tip")
    capture_frames = captured.get("frames", [])
    reviewed_frames = accepted.get("frames", [])
    tree_frames = publication.get("frames", [])
    if any(not isinstance(xs, list) or len(xs) != 74 for xs in (capture_frames, reviewed_frames, tree_frames)):
        raise Refusal("capture, independent review, and published frame tree must each contain all 74 stills")
    cap_by_name = {}
    for row in capture_frames:
        path = Path(row.get("path") or "")
        if (path.parent != Path("frames") or path.suffix != ".png" or path.stem != row.get("name")
                or row.get("name") in cap_by_name or not re.fullmatch(r"[0-9a-f]{64}", row.get("sha256") or "")
                or not isinstance(row.get("bytes"), int) or row["bytes"] <= 0):
            raise Refusal("capture frame name/path/SHA-256 inventory is malformed or duplicated")
        cap_by_name[path.name] = row
    rev_by_name = {row.get("name"): row for row in reviewed_frames}
    tree_by_name = {Path(row.get("path") or "").name: row for row in tree_frames}
    if len(rev_by_name) != 74 or len(tree_by_name) != 74 or set(rev_by_name) != set(cap_by_name) or set(tree_by_name) != set(cap_by_name):
        raise Refusal("reviewed, captured, and published frame name inventories differ")
    for name, capture_row in cap_by_name.items():
        review_row, tree_row = rev_by_name[name], tree_by_name[name]
        if (review_row.get("size") != capture_row["bytes"]
                or not re.fullmatch(r"[0-9a-f]{40}", review_row.get("sha") or "")
                or tree_row.get("path") != "public-review/frames/" + name
                or tree_row.get("sha") != review_row.get("sha")
                or tree_row.get("size") != review_row.get("size")):
            raise Refusal(f"reviewed frame Git blob SHA/size does not match current published frame: {name}")


def bind_replacement(c: dict[str, Any], run_id: int, head_sha: str) -> dict[str, Any]:
    if not isinstance(run_id, int) or run_id <= 0:
        raise Refusal("replacement run ID must be a positive integer")
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha or ""):
        raise Refusal("replacement head SHA must be a 40-character lowercase commit ID")
    c["replacement"]["run_id"] = run_id
    c["replacement"]["head_sha"] = head_sha
    return c


def validate_contract(c: dict[str, Any]) -> None:
    if c.get("film_id") != "F02" or c.get("duration_seconds") != 651.6 or c.get("fps") != 30:
        raise Refusal("contract is not the pinned F02 651.6s/30fps composition")
    if c.get("expected_segments") != 75 or c.get("expected_frames") != 19548:
        raise Refusal("contract total count/frame guard changed")
    comp = c.get("composition", {})
    review=c.get("source_capture_review", {})
    if (review.get("schema") != "independent_source_candidate_visual_still_review"
            or review.get("status") != "ACCEPT_WITH_SCOPE_LIMITATIONS"
            or not re.fullmatch(r"[0-9a-f]{64}",review.get("receipt_sha256") or "")
            or review.get("capture_run_id") != EXPECTED_SOURCE_CAPTURE_RUN_ID
            or review.get("source_sha256") != comp.get("sealed_source_package_sha256")
            or review.get("source_head_sha") != EXPECTED_SOURCE_HEAD_SHA
            or review.get("source_release_id") != EXPECTED_SOURCE_RELEASE_ID
            or review.get("source_asset_id") != EXPECTED_SOURCE_ASSET_ID
            or review.get("source_asset_bytes") != EXPECTED_SOURCE_ASSET_BYTES
            or review.get("full_av_review") != "OPEN"
            or review.get("whole_video_approval") != "NOT_GRANTED"
            or review.get("release_approval") != "NOT_GRANTED"
            or review.get("owner_adoption") != "NOT_ADOPTED"):
        raise Refusal("matching limited-scope independent 74-frame source-still review required before assembly")
    validate_source_review_receipts(c)
    if (not re.fullmatch(r"F02-isolated-source-candidate-[0-9a-f]{64}", comp.get("sealed_source_release") or "")
            or not re.fullmatch(r"[0-9a-f]{64}", comp.get("sealed_source_package_sha256") or "")
            or comp.get("sealed_source_release") != "F02-isolated-source-candidate-" + comp.get("sealed_source_package_sha256", "")
            or comp.get("sealed_source_package_sha256") != EXPECTED_SOURCE_ARCHIVE_SHA256
            or comp.get("sealed_source_release_id") != EXPECTED_SOURCE_RELEASE_ID
            or comp.get("sealed_source_asset_id") != EXPECTED_SOURCE_ASSET_ID
            or comp.get("sealed_source_package_bytes") != EXPECTED_SOURCE_ASSET_BYTES
            or not isinstance(comp.get("sealed_source_package_bytes"), int) or comp["sealed_source_package_bytes"] <= 0
            or not isinstance(comp.get("sealed_source_asset_id"), int) or comp["sealed_source_asset_id"] <= 0):
        raise Refusal("new source release/package/asset binding is missing or invalid")
    if comp.get("apply_source_overlay") is not False:
        raise Refusal("apply_source_overlay must be false")
    expected_files = comp.get("expected_repair_files")
    if (not isinstance(expected_files, dict) or set(expected_files) != {"film/film.js", "film/sets_a.js"}
            or any(not re.fullmatch(r"[0-9a-f]{64}", value or "") for value in expected_files.values())):
        raise Refusal("reviewed source receipt must bind exactly film.js and sets_a.js hashes")
    qa_overlay = comp.get("qa_overlay", {})
    if (qa_overlay.get("release") != EXPECTED_QA_OVERLAY_RELEASE
            or qa_overlay.get("release_id") != EXPECTED_QA_OVERLAY_RELEASE_ID
            or qa_overlay.get("asset") != EXPECTED_QA_OVERLAY_ASSET
            or qa_overlay.get("asset_id") != EXPECTED_QA_OVERLAY_ASSET_ID
            or qa_overlay.get("asset_bytes") != EXPECTED_QA_OVERLAY_ASSET_BYTES
            or qa_overlay.get("sha256") != EXPECTED_QA_OVERLAY_SHA256):
        raise Refusal("QA overlay is not the exact previously verified F02 dispatch artifact")
    helper = c.get("authoritative_assembler", {})
    if helper.get("path") != ".github/scripts/assemble_verify.py" or helper.get("sha256") != AUTHORITATIVE_HELPER_SHA256:
        raise Refusal("authoritative assembler path/hash pin changed")
    parent = c.get("parent_lineage", {})
    parent_pins = {
        "run_id": 37146440125,
        "workflow_path": ".github/workflows/agmm-f02-partial-assembly.yml",
        "head_sha": "3be0bf2c26e2186710002796a80b1eda115c1d3f",
        "conclusion": "success",
        "master_sha256": "276ae17ca24d46c9b08508dc2cfaec00bc89ad6c1d3e4b96fd7d490e64c7c51e",
        "source_package_sha256": "b216a14d62b2b5430234a411a1913207b41642071fc5985a11bbf09913d21719",
        "artifact_id": 11283018672,
        "artifact_name": "F02-PARTIAL-SEGMENT-LINEAGE-37146440125",
        "artifact_size_in_bytes": 2894181372,
        "artifact_created_at": "2026-10-03T19:36:03Z",
        "artifact_digest": "sha256:f5ba866e104bda570ba1337a7a88cd256d7415e906e60fafd71fbf3c21b3c5b5",
        "artifact_expires_at": "2026-10-04T19:35:44Z",
        "preview_release_tag": "preview-F02-37146440125",
        "preview_release_asset_id": 608451867,
        "preview_release_asset_name": "HOSTED-PREVIEW.json",
        "preview_release_asset_size": 176100,
        "preview_release_asset_digest": "sha256:cc0d364aae718266ca2a955adfacdffa46fff02e12e6cbe3442f236fb9cbff5f",
        "preview_master_sha256": "276ae17ca24d46c9b08508dc2cfaec00bc89ad6c1d3e4b96fd7d490e64c7c51e",
        "preview_master_bytes": 2849432872,
        "preview_proxy_bytes": 737310196,
        "preview_proxy_sha256": "c916c2e1b9a35853b3a355718aec83ce83787a5bc151088b29eea8878bbf85ce",
        "expected_prior_lineage_parent_run_id": 37125818648,
        "expected_prior_lineage_replacement_run_id": 37143394055,
        "expected_prior_replacement_segments": ["51", "52"],
    }
    if any(parent.get(k) != v for k, v in parent_pins.items()):
        raise Refusal("current master lineage artifact/release pin changed")
    replacement = c.get("replacement", {})
    if (replacement.get("run_id") is None or replacement.get("head_sha") is None
            or not isinstance(replacement.get("run_id"), int) or replacement["run_id"] <= 0
            or not re.fullmatch(r"[0-9a-f]{40}", replacement["head_sha"] or "")):
        raise Refusal("bind the exact successful replacement run ID and head SHA before validation")
    replacement_pins = {
        "tag": f"F02-source-{comp['sealed_source_package_sha256'][:12]}-seg01-02-51-52-20261004-r2",
        "workflow_path": ".github/workflows/agmm-film.yml",
        "package_release": comp["sealed_source_release"],
        "package_sha256": comp["sealed_source_package_sha256"],
        "segments": ["01", "02", "51", "52"],
    }
    if any(replacement.get(k) != v for k, v in replacement_pins.items()):
        raise Refusal("replacement render tag, source, workflow or segment set changed")
    rows = c.get("segments")
    if not isinstance(rows, list) or len(rows) != 75:
        raise Refusal("contract must contain exactly 75 segment rows")
    replacement_ids, seen, cursor, frame_total = [], set(), 0.0, 0
    for index, row in enumerate(rows, 1):
        sid = f"{index:02d}"
        if row.get("i") != sid or sid in seen:
            raise Refusal(f"segment grid has missing, duplicate, or out-of-order ID {sid}")
        seen.add(sid)
        try:
            t0, length, frames = float(row["t0"]), float(row["len"]), int(row["frames"])
        except (KeyError, TypeError, ValueError) as exc:
            raise Refusal(f"bad segment geometry for {sid}: {exc}") from exc
        if abs(t0-cursor) > .002 or length <= 0 or frames != round(length*30):
            raise Refusal(f"segment {sid} has invalid timing/frame geometry")
        cursor = round(t0+length, 3); frame_total += frames
        changed = sid in {"01", "02", "51", "52"}
        if row.get("lineage") != ("replacement" if changed else "parent"):
            raise Refusal(f"segment {sid} has unexpected active lineage role")
        if not re.fullmatch(r"[0-9a-f]{64}", row.get("expected_current_sha256", "")):
            raise Refusal(f"segment {sid} lacks a valid current-master SHA-256")
        if not isinstance(row.get("expected_current_bytes"), int) or row["expected_current_bytes"] <= 0:
            raise Refusal(f"segment {sid} lacks positive current-master byte count")
        prior_role = "replacement" if sid in {"51", "52"} else "parent"
        if row.get("previous_provenance_role") != prior_role:
            raise Refusal(f"segment {sid} current-master lineage source role changed")
        if row.get("previous_run_id") != (37143394055 if prior_role == "replacement" else 37125818648):
            raise Refusal(f"segment {sid} previous source run mismatch")
        if changed:
            replacement_ids.append(sid)
            if row.get("replacement_artifact_name") != f"{replacement['tag']}-SEG{sid}":
                raise Refusal(f"replacement artifact name mismatch for segment {sid}")
        elif row.get("replacement_artifact_name") is not None:
            raise Refusal(f"unexpected replacement artifact for unchanged segment {sid}")
    if abs(cursor-651.6) > .01 or frame_total != 19548:
        raise Refusal("segment grid does not cover exactly 651.6s/19548 frames")
    if replacement_ids != ["01", "02", "51", "52"]:
        raise Refusal(f"only 01/02/51/52 may be replacements; got {replacement_ids}")
    if [(rows[i-1]["t0"], rows[i-1]["len"]) for i in (1,2,51,52)] != [(0.0,8.6),(8.6,8.6),(430.0,8.6),(438.6,8.6)]:
        raise Refusal("replacement segment timing does not match exact render grid")


def render_jobs(jobs: list[dict[str, Any]], expected_rows: list[dict[str, Any]], run_id: int) -> None:
    found: dict[str, dict[str, Any]] = {}
    expected = {row["i"]: row for row in expected_rows}
    for job in jobs:
        name = job.get("name", "")
        match = RENDER_JOB_RE.fullmatch(name)
        if not match:
            continue
        sid = f"{int(match.group(1)):02d}"
        if sid not in expected:
            raise Refusal(f"unexpected render job SEG{sid} in run {run_id}")
        row = expected[sid]
        if abs(float(match.group(2)) - float(row["t0"])) > 0.001 or abs(float(match.group(3)) - float(row["len"])) > 0.001:
            raise Refusal(f"run {run_id} SEG{sid} job timing does not match sealed segment grid")
        if sid in found:
            raise Refusal(f"duplicate render job for SEG{sid} in run {run_id}")
        found[sid] = job
    if sorted(found) != sorted(expected):
        raise Refusal(f"run {run_id} render job set mismatch: got {sorted(found)}, expected {sorted(expected)}")
    for sid, job in found.items():
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            raise Refusal(f"run {run_id} SEG{sid} is not an exact successful completed render job")


def validate_run(run: dict[str, Any], jobs: list[dict[str, Any]], role: str,
                 c: dict[str, Any]) -> None:
    if role != "replacement":
        raise Refusal(f"unsupported render run role {role}")
    expected = c["replacement"]
    if int(run.get("id", -1)) != expected["run_id"]:
        raise Refusal("replacement Actions run ID changed")
    if run.get("path") != expected["workflow_path"]:
        raise Refusal("replacement run did not execute the pinned film workflow")
    if run.get("head_branch") != "main" or run.get("head_sha") != expected["head_sha"]:
        raise Refusal("replacement run branch/head SHA mismatch")
    if run.get("event") != "workflow_dispatch" or run.get("status") != "completed":
        raise Refusal("replacement run is not a completed workflow_dispatch run")
    if run.get("conclusion") != "success":
        raise Refusal(f"replacement run must conclude success, got {run.get('conclusion')}")
    expected_rows = [r for r in c["segments"] if r["lineage"] == "replacement"]
    render_jobs(jobs, expected_rows, expected["run_id"])
    failures = [j.get("name") for j in jobs if j.get("conclusion") not in ("success", "skipped", None)]
    if failures:
        raise Refusal(f"replacement run has failed/cancelled jobs: {failures}")


def validate_artifacts(items: list[dict[str, Any]], role: str, c: dict[str, Any],
                       now: datetime | None = None) -> dict[str, dict[str, Any]]:
    if role != "replacement":
        raise Refusal(f"unsupported artifact role {role}")
    now = now or datetime.now(timezone.utc)
    rows = [r for r in c["segments"] if r["lineage"] == "replacement"]
    expected_names = [r["replacement_artifact_name"] for r in rows]
    counts = Counter(a.get("name") for a in items)
    out = {}
    run_id = c["replacement"]["run_id"]
    for row in rows:
        name = row["replacement_artifact_name"]
        if counts[name] != 1:
            raise Refusal(f"artifact {name} must occur exactly once, found {counts[name]}")
        art = next(a for a in items if a.get("name") == name)
        if art.get("expired") is not False:
            raise Refusal(f"artifact {name} is expired or expiration flag missing")
        if int(art.get("size_in_bytes", 0)) <= 0 or int(art.get("id", 0)) <= 0:
            raise Refusal(f"artifact {name} has empty size or no immutable artifact ID")
        if parse_time(art.get("expires_at", "")) <= now + ARTIFACT_RETENTION_BUFFER:
            raise Refusal(f"artifact {name} expires inside 4-hour assembly window")
        created = parse_time(art.get("created_at", ""))
        if created > now + timedelta(minutes=5):
            raise Refusal(f"artifact {name} creation time is in the future")
        if int((art.get("workflow_run") or {}).get("id", -1)) != run_id:
            raise Refusal(f"artifact {name} lacks exact replacement run provenance")
        out[name] = art
    if len(out) != 4 or len({a["id"] for a in out.values()}) != 4:
        raise Refusal("replacement artifact set is incomplete or reuses artifact IDs")
    if set(out) != set(expected_names):
        raise Refusal("replacement artifact names differ from the four pinned segment IDs")
    return out


def validate_release(release: dict[str, Any], tag: str, asset_name: str,
                     expected_sha: str | None = None) -> dict[str, Any]:
    if release.get("tag_name") != tag:
        raise Refusal(f"release tag mismatch: expected {tag}")
    assets = [a for a in release.get("assets", []) if a.get("name") == asset_name]
    if len(assets) != 1 or int(assets[0].get("size", 0)) <= 0:
        raise Refusal(f"release must contain exactly one nonempty {asset_name}")
    asset = assets[0]
    digest = asset.get("digest") or ""
    if expected_sha and digest and digest not in (expected_sha, f"sha256:{expected_sha}"):
        raise Refusal(f"release API asset digest mismatch for {asset_name}")
    return asset


def validate_parent_lineage_run(run: dict[str, Any], c: dict[str, Any]) -> None:
    pin = c["parent_lineage"]
    if (run.get("id") != pin["run_id"] or run.get("path") != pin["workflow_path"]
            or run.get("head_sha") != pin["head_sha"] or run.get("head_branch") != "main"
            or run.get("event") != "workflow_dispatch" or run.get("status") != "completed"
            or run.get("conclusion") != "success"):
        raise Refusal("current parent master run identity/status changed")
    if run.get("repository", {}).get("private") is not False or run.get("repository", {}).get("full_name") != EXPECTED_REPO:
        raise Refusal("parent master run repository identity/public status mismatch")


def validate_lineage_artifact_metadata(artifact: dict[str, Any], c: dict[str, Any],
                                       now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc); pin=c["parent_lineage"]
    if (artifact.get("id") != pin["artifact_id"] or artifact.get("name") != pin["artifact_name"]
            or artifact.get("size_in_bytes") != pin["artifact_size_in_bytes"]
            or artifact.get("created_at") != pin["artifact_created_at"]
            or artifact.get("expires_at") != pin["artifact_expires_at"]
            or artifact.get("digest") != pin["artifact_digest"]
            or artifact.get("expired") is not False
            or int((artifact.get("workflow_run") or {}).get("id", -1)) != pin["run_id"]):
        raise Refusal("current master lineage artifact metadata mismatch/expired")
    if parse_time(artifact.get("expires_at", "")) <= now + ARTIFACT_RETENTION_BUFFER:
        raise Refusal("current master lineage artifact expires inside the 4-hour assembly window")


def validate_source_release_metadata(release: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    if (release.get("draft") is not False or release.get("prerelease") is not False
            or release.get("id") != EXPECTED_SOURCE_RELEASE_ID):
        raise Refusal("sealed source release is not a published public release")
    comp=c["composition"]
    asset=validate_release(release,comp["sealed_source_release"],"source.tar.gz",comp["sealed_source_package_sha256"])
    if (asset.get("id")!=comp["sealed_source_asset_id"] or asset.get("size")!=comp["sealed_source_package_bytes"]
            or asset.get("digest")!="sha256:"+comp["sealed_source_package_sha256"]):
        raise Refusal("new sealed source asset ID/size/digest mismatch")
    receipts=[a for a in release.get("assets",[]) if a.get("name")=="source-receipt.json"]
    if (len(receipts)!=1 or receipts[0].get("id")!=EXPECTED_SOURCE_RECEIPT_ASSET_ID
            or receipts[0].get("size")!=EXPECTED_SOURCE_RECEIPT_BYTES
            or receipts[0].get("digest")!="sha256:"+EXPECTED_SOURCE_RECEIPT_SHA256
            or receipts[0].get("state")!="uploaded"):
        raise Refusal("published source-receipt.json release membership/digest mismatch")
    return asset


def validate_preview_release_metadata(release: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    pin=c["parent_lineage"]
    asset=validate_release(release, pin["preview_release_tag"], pin["preview_release_asset_name"])
    if (release.get("draft") is not False or release.get("prerelease") is not False
            or asset.get("id") != pin["preview_release_asset_id"]
            or asset.get("size") != pin["preview_release_asset_size"]
            or asset.get("digest") != pin["preview_release_asset_digest"]):
        raise Refusal("current durable preview receipt release asset changed")
    return asset


def validate_parent_preview_receipt(receipt: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    pin=c["parent_lineage"]
    if (receipt.get("schema_version") != 3 or receipt.get("source_run_id") != pin["run_id"]
            or receipt.get("repository") != EXPECTED_REPO
            or receipt.get("source_workflow") != pin["workflow_path"]
            or receipt.get("source_workflow_commit") != pin["head_sha"]
            or receipt.get("source_conclusion") != "success"):
        raise Refusal("durable parent preview receipt provenance mismatch")
    integrity=receipt.get("integrity", {})
    outputs=integrity.get("outputs", {})
    if (integrity.get("kind") != "mechanical_integrity_only"
            or integrity.get("release_approval") != "NOT_GRANTED"
            or integrity.get("editorial_gate") != "NOT_RUN"
            or integrity.get("duration") != 651.6 or integrity.get("fps") != 30
            or integrity.get("segment_count") != 75 or integrity.get("frame_count") != 19548
            or outputs.get("master_sha256") != pin["master_sha256"]
            or outputs.get("master_bytes") != pin["preview_master_bytes"]
            or outputs.get("derived_bytes") != pin["preview_proxy_bytes"]):
        raise Refusal("durable parent receipt is not the exact 75/19548 mechanical-only master")
    preview_files=receipt.get("files",[])
    proxy=next((f for f in preview_files if f.get("name")=="F02-MASTER-1080-from-4K.mp4"),None)
    if (proxy is None or proxy.get("size")!=pin["preview_proxy_bytes"]
            or proxy.get("sha256")!=pin["preview_proxy_sha256"]):
        raise Refusal("durable parent proxy size/digest mismatch")
    source_artifacts=receipt.get("source_artifacts",[])
    lineage_artifacts=[a for a in source_artifacts if a.get("id")==pin["artifact_id"]]
    if (len(lineage_artifacts)!=1 or lineage_artifacts[0].get("name")!=pin["artifact_name"]
            or lineage_artifacts[0].get("size_in_bytes")!=pin["artifact_size_in_bytes"]
            or lineage_artifacts[0].get("expires_at")!=pin["artifact_expires_at"]):
        raise Refusal("durable preview receipt does not bind the exact retained segment-lineage artifact")
    file_rows=integrity.get("segments")
    if not isinstance(file_rows,list) or len(file_rows)!=75:
        raise Refusal("durable parent receipt lacks 75 segment hashes")
    by_id={r.get("id"):r for r in file_rows}
    if len(by_id)!=75:
        raise Refusal("durable parent receipt segment IDs are missing or duplicated")
    for row in c["segments"]:
        observed=by_id.get(row["i"])
        hosted=observed.get("hosted_receipt",{}) if observed else {}
        if (not observed or observed.get("t0") != row["t0"] or observed.get("len") != row["len"]
                or observed.get("frames") != row["frames"]
                or observed.get("bytes") != row["expected_current_bytes"]
                or observed.get("sha256") != row["expected_current_sha256"]
                or hosted.get("status") != "PASS" or hosted.get("width") != 3840 or hosted.get("height") != 2160
                or hosted.get("fps") != "30/1" or hosted.get("frames") != row["frames"]
                or hosted.get("bytes") != row["expected_current_bytes"] or hosted.get("sha256") != row["expected_current_sha256"]
                or hosted.get("full_decode") != "PASS" or hosted.get("flicker",{}).get("status") != "PASS"):
            raise Refusal(f"durable parent segment hash/geometry/verification mismatch for {row['i']}")
    lineage=receipt.get("lineage", {})
    validate_prior_lineage(lineage,c)
    return lineage


def validate_prior_lineage(lineage: dict[str, Any], c: dict[str, Any]) -> dict[str, dict[str, Any]]:
    pin=c["parent_lineage"]
    if (lineage.get("kind") != "f02_segment_lineage_manifest" or lineage.get("schema") != 1
            or lineage.get("source_release") != pin["source_release"]
            or lineage.get("source_package_sha256") != pin["source_package_sha256"]
            or lineage.get("parent_run_id") != pin["expected_prior_lineage_parent_run_id"]
            or lineage.get("replacement_run_id") != pin["expected_prior_lineage_replacement_run_id"]
            or lineage.get("replacement_segments") != pin["expected_prior_replacement_segments"]
            or lineage.get("expected_segments") != 75 or lineage.get("status") != "STAGED_FOR_MECHANICAL_ASSEMBLY"
            or lineage.get("release_approval") != "NOT_GRANTED" or lineage.get("apply_source_overlay") is not False):
        raise Refusal("prior F02-LINEAGE.json identity/status mismatch")
    rows=lineage.get("segment_provenance")
    if not isinstance(rows,list) or len(rows)!=77:
        raise Refusal("prior lineage must contain 75 parent rows and 2 previous replacements")
    indexed={}
    for r in rows:
        sid=r.get("segment")
        allowed_roles={"parent","replacement"} if sid in {"51","52"} else {"parent"}
        if sid not in {f"{i:02}" for i in range(1,76)} or r.get("provenance_role") not in allowed_roles:
            raise Refusal("prior lineage contains unexpected or invalid segment role")
        roles=indexed.setdefault(sid,{})
        if r["provenance_role"] in roles:
            raise Refusal(f"prior lineage duplicates segment {sid} role")
        roles[r["provenance_role"]]=r
    if set(indexed)!={f"{i:02}" for i in range(1,76)} or any(set(v)!=( {"parent","replacement"} if k in {"51","52"} else {"parent"}) for k,v in indexed.items()):
        raise Refusal("prior lineage does not have exact 75 parent plus 51/52 replacement records")
    for row in c["segments"]:
        sid=row["i"]; role="replacement" if sid in {"51","52"} else "parent"
        prov=indexed[sid][role]
        if (prov.get("hosted_media_sha256") != row["expected_current_sha256"]
                or prov.get("hosted_media_bytes") != row["expected_current_bytes"]
                or prov.get("expected_frames") != row["frames"]
                or prov.get("t0") != row["t0"] or prov.get("len") != row["len"]
                or prov.get("run_id") != row["previous_run_id"] or prov.get("tag") != row["previous_tag"]
                or prov.get("package_sha256") != row["previous_package_sha256"]
                or prov.get("artifact_id",0) <= 0
                or prov.get("render_receipt",{}).get("sha256") != row["expected_current_sha256"]
                or prov.get("render_receipt",{}).get("bytes") != row["expected_current_bytes"]):
            raise Refusal(f"prior lineage hash/geometry mismatch for segment {sid}")
    return {sid:vals["replacement"] if sid in {"51","52"} else vals["parent"] for sid,vals in indexed.items()}


def validate_metadata(c: dict[str, Any], snapshots: Path,
                      now: datetime | None = None) -> dict[str, Any]:
    now=now or datetime.now(timezone.utc)
    validate_public_repository(read_json_or_jsonl(snapshots/"repository.json"))
    parent_run=read_json_or_jsonl(snapshots/"parent-lineage"/"run.json")
    parent_artifact=read_json_or_jsonl(snapshots/"parent-lineage"/"artifact.json")
    validate_parent_lineage_run(parent_run,c); validate_lineage_artifact_metadata(parent_artifact,c,now)
    replacement_dir=snapshots/"replacement"
    run=read_json_or_jsonl(replacement_dir/"run.json")
    jobs=collection(replacement_dir/"jobs.jsonl","jobs")
    artifacts=collection(replacement_dir/"artifacts.jsonl","artifacts")
    validate_run(run,jobs,"replacement",c)
    selected=validate_artifacts(artifacts,"replacement",c,now)
    source=validate_source_release_metadata(read_json_or_jsonl(snapshots/"source-release.json"),c)
    preview=validate_preview_release_metadata(read_json_or_jsonl(snapshots/"preview-release.json"),c)
    receipt_path=snapshots/"parent-preview-receipt.json"
    if not receipt_path.is_file() or receipt_path.is_symlink(): raise Refusal("hash-pinned current parent preview receipt is missing")
    receipt_sha=sha256(receipt_path)
    expected_receipt_sha=c["parent_lineage"]["preview_release_asset_digest"].removeprefix("sha256:")
    if receipt_sha != expected_receipt_sha: raise Refusal("downloaded current parent preview receipt SHA-256 mismatch")
    preview_receipt=json.loads(receipt_path.read_text())
    validate_parent_preview_receipt(preview_receipt,c)
    ids=[str(parent_artifact["id"]),*[str(a["id"]) for a in selected.values()],str(source["id"]),str(preview["id"])]
    if len(ids)!=len(set(ids)):
        raise Refusal("current-lineage, replacement or release asset IDs overlap")
    return {"parent_lineage":{"run":parent_run,"artifact":parent_artifact},
            "replacement":{"run":run,"jobs":jobs,"selected_artifacts":selected},
            "source_asset":source,"preview_receipt_asset":preview}


def gh_json(endpoint: str) -> dict[str, Any]:
    p = subprocess.run(["gh", "api", endpoint], check=False, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise Refusal(f"GitHub API request failed: {endpoint}: {p.stderr[-1000:]}")
    return json.loads(p.stdout)


def gh_jsonl(endpoint: str, key: str) -> None:
    p = subprocess.run(["gh", "api", "--paginate", endpoint, "--jq", f".{key}[]"],
                       check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise Refusal(f"GitHub API pagination failed: {endpoint}: {p.stderr[-1000:]}")
    Path(sys.argv[-1]).write_text(p.stdout)


def snapshot_metadata(repo: str, out: Path, c: dict[str, Any]) -> None:
    if repo != EXPECTED_REPO:
        raise Refusal(f"wrong GitHub repository {repo}")
    validate_contract(c)
    out.mkdir(parents=True, exist_ok=True)
    public_repo=gh_json(f"repos/{repo}")
    validate_public_repository(public_repo)
    (out/"repository.json").write_text(json.dumps(public_repo,indent=2)+"\n")
    pin=c["parent_lineage"]; parent_dir=out/"parent-lineage"; parent_dir.mkdir(exist_ok=True)
    (parent_dir/"run.json").write_text(json.dumps(gh_json(f"repos/{repo}/actions/runs/{pin['run_id']}"),indent=2)+"\n")
    (parent_dir/"artifact.json").write_text(json.dumps(gh_json(f"repos/{repo}/actions/artifacts/{pin['artifact_id']}"),indent=2)+"\n")
    replacement=c["replacement"]; d=out/"replacement"; d.mkdir(exist_ok=True)
    (d/"run.json").write_text(json.dumps(gh_json(f"repos/{repo}/actions/runs/{replacement['run_id']}"),indent=2)+"\n")
    for endpoint,key,filename in (
        (f"repos/{repo}/actions/runs/{replacement['run_id']}/jobs?per_page=100","jobs","jobs.jsonl"),
        (f"repos/{repo}/actions/runs/{replacement['run_id']}/artifacts?per_page=100","artifacts","artifacts.jsonl")):
        q=subprocess.run(["gh","api","--paginate",endpoint,"--jq",f".{key}[]"],check=False,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if q.returncode: raise Refusal(f"GitHub API pagination failed: {endpoint}: {q.stderr[-1000:]}")
        (d/filename).write_text(q.stdout)
    for key,tag in (("source-release.json",c["composition"]["sealed_source_release"]),
                    ("preview-release.json",pin["preview_release_tag"])):
        (out/key).write_text(json.dumps(gh_json(f"repos/{repo}/releases/tags/{tag}"),indent=2)+"\n")


def safe_archive_members(tf: tarfile.TarFile, *, exact: set[str] | None = None) -> list[tarfile.TarInfo]:
    members = tf.getmembers()
    if len(members) > MAX_ARCHIVE_FILES:
        raise Refusal("archive has too many entries")
    names: set[str] = set()
    normalized_members: list[tarfile.TarInfo] = []
    root_seen = False
    total = 0
    for m in members:
        raw = m.name
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts:
            raise Refusal(f"unsafe archive member path: {raw}")
        if not (m.isfile() or m.isdir()):
            raise Refusal(f"archive member type forbidden: {raw}")
        # Conventional `tar -C package .` archives contain a harmless root directory.
        # Skip only that directory; a regular file named `.` is never accepted.
        if not path.parts:
            if not m.isdir():
                raise Refusal(f"archive root entry must be a directory: {raw}")
            if root_seen:
                raise Refusal(f"duplicate archive root directory: {raw}")
            root_seen = True
            continue
        normalized = PurePosixPath(*path.parts).as_posix()
        if normalized in names:
            raise Refusal(f"duplicate archive member after path normalization: {normalized}")
        names.add(normalized)
        # Use the normalized relative path for allowlist checks and extraction.
        m.name = normalized
        normalized_members.append(m)
        if m.size < 0 or m.size > MAX_ARCHIVE_MEMBER_BYTES:
            raise Refusal(f"archive member size out of bounds: {raw}")
        total += m.size
    if total > MAX_ARCHIVE_BYTES:
        raise Refusal("archive expanded size exceeds safety limit")
    if exact is not None and names != exact:
        raise Refusal(f"QA overlay member allowlist mismatch: {sorted(names ^ exact)}")
    return normalized_members


def safe_extract(tf: tarfile.TarFile, members: list[tarfile.TarInfo], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    base = destination.resolve()
    for m in members:
        target = (base / PurePosixPath(m.name)).resolve()
        if base not in target.parents and target != base:
            raise Refusal(f"archive member escapes destination: {m.name}")
        if m.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        src = tf.extractfile(m)
        if src is None:
            raise Refusal(f"archive member cannot be read: {m.name}")
        with src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)


def verify_package_checksums(package: Path) -> None:
    sums = package / "SHA256SUMS.txt"
    if not sums.is_file():
        raise Refusal("sealed source package lacks SHA256SUMS.txt")
    seen = set()
    for line_no, line in enumerate(sums.read_text().splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise Refusal(f"malformed package checksum line {line_no}")
        digest, name = match.groups()
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or name in seen:
            raise Refusal(f"unsafe/duplicate package checksum member {name}")
        seen.add(name)
        target = (package / path).resolve()
        if package.resolve() not in target.parents or not target.is_file():
            raise Refusal(f"package checksum target missing or escapes package: {name}")
        if sha256(target) != digest:
            raise Refusal(f"sealed package checksum mismatch: {name}")
    if not seen:
        raise Refusal("sealed package checksum manifest is empty")


def verify_authoritative_helper(helper_path: Path, c: dict[str, Any]) -> dict[str, Any]:
    expected = c["authoritative_assembler"]["sha256"]
    if not helper_path.is_file() or helper_path.is_symlink():
        raise Refusal(f"authoritative assembler missing or symlinked: {helper_path}")
    actual = sha256(helper_path)
    if actual != expected:
        raise Refusal(f"authoritative assembler SHA-256 mismatch: expected {expected}, got {actual}")
    commit=os.environ.get("GITHUB_SHA","")
    if not re.fullmatch(r"[0-9a-f]{40}",commit): raise Refusal("GITHUB_SHA is missing/invalid for assembler-source provenance")
    return {"path": c["authoritative_assembler"]["path"], "sha256": actual,
            "source_commit": commit, "status": "PASS"}


def prepare_source(source_archive: Path, package_dir: Path,
                   c: dict[str, Any]) -> dict[str, Any]:
    if sys.platform == "darwin":
        raise Refusal("media/source extraction is forbidden on Darwin; hosted Ubuntu runner only")
    comp = c["composition"]
    source_hash = sha256(source_archive)
    if source_hash != comp["sealed_source_package_sha256"]:
        raise Refusal("downloaded sealed source archive hash mismatch")
    if comp.get("apply_source_overlay") is not False:
        raise Refusal("refusing to apply source overlay; contract must set false")
    if package_dir.exists() and any(package_dir.iterdir()):
        raise Refusal("package extraction destination is not empty")
    with tarfile.open(source_archive, "r:gz") as tf:
        members = safe_archive_members(tf)
        safe_extract(tf, members, package_dir)
    verify_package_checksums(package_dir)
    for rel, digest in comp["expected_repair_files"].items():
        file = package_dir / rel
        if not file.is_file() or sha256(file) != digest:
            raise Refusal(f"sealed repaired source file hash mismatch: {rel}")
    index = package_dir / "film" / "index.html"
    mix = package_dir / "audio" / "mix.flac"
    if not index.is_file() or not mix.is_file():
        raise Refusal("sealed source package lacks film/index.html or audio/mix.flac")
    duration_matches = re.findall(r'data-duration="([0-9.]+)"', index.read_text())
    if duration_matches != ["651.6"]:
        raise Refusal(f"source duration must be the single exact 651.6 value, got {duration_matches}")
    check = subprocess.run(["python3", "static_check.py"], cwd=package_dir,
                           check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check.returncode:
        raise Refusal(f"sealed source static check failed: {check.stdout[-3000:]}")
    return {"sealed_source_sha256": source_hash, "sealed_source_bytes": source_archive.stat().st_size,
            "source_static_check": "PASS", "apply_source_overlay": False,
            "source_member_count": len(members), "source_release": comp["sealed_source_release"],
            "source_package_sha256": comp["sealed_source_package_sha256"]}


def artifact_file(artifact_root: Path, sid: str, suffix: str) -> Path:
    target_name = f"SEG{sid}{suffix}"
    matches = [p for p in artifact_root.rglob(target_name) if p.is_file() and not p.is_symlink()]
    if len(matches) != 1:
        raise Refusal(f"expected one {target_name} beneath {artifact_root}, got {len(matches)}")
    resolved = matches[0].resolve()
    if artifact_root.resolve() not in resolved.parents:
        raise Refusal(f"artifact file path escaped its root: {target_name}")
    return matches[0]


def safe_download(run_id: int, artifact_name: str, dest: Path) -> None:
    if sys.platform == "darwin":
        raise Refusal("artifact media download is forbidden on Darwin; hosted Ubuntu runner only")
    dest.mkdir(parents=True, exist_ok=False)
    command = ["gh", "run", "download", str(run_id), "--repo", EXPECTED_REPO,
               "--name", artifact_name, "--dir", str(dest)]
    p = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise Refusal(f"artifact download failed for {artifact_name}: {p.stderr[-1200:]}; partial download preserved at {dest}")


def copy_artifact(artifact_root: Path, sid: str, destination: Path) -> dict[str, Any]:
    if sys.platform == "darwin": raise Refusal("segment media copy/hash is forbidden on Darwin; hosted Ubuntu runner only")
    mp4 = artifact_file(artifact_root, sid, ".mp4")
    verify = artifact_file(artifact_root, sid, ".verify.json")
    if mp4.stat().st_size <= 0 or verify.stat().st_size <= 0:
        raise Refusal(f"empty media or verification receipt for SEG{sid}")
    actual_sha = sha256(mp4)
    receipt = json.loads(verify.read_text())
    row = next(r for r in load_contract()["segments"] if r["i"] == sid)
    if (receipt.get("status") != "PASS" or receipt.get("sha256") != actual_sha
            or receipt.get("frames") != row["frames"]
            or receipt.get("full_decode") != "PASS"
            or receipt.get("flicker", {}).get("status") != "PASS"):
        raise Refusal(f"SEG{sid} render verification receipt does not bind to the downloaded bytes")
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copy2(mp4, destination / f"SEG{sid}.mp4")
    shutil.copy2(verify, destination / f"SEG{sid}.verify.json")
    logs = [p for p in artifact_root.rglob(f"SEG{sid}.render.log") if p.is_file() and not p.is_symlink()]
    if len(logs) > 1:
        raise Refusal(f"multiple render logs for SEG{sid}")
    if logs:
        shutil.copy2(logs[0], destination / logs[0].name)
    return {"sha256": actual_sha, "bytes": mp4.stat().st_size,
            "verify_receipt": receipt, "artifact_files": sorted(p.name for p in destination.iterdir())}


def parent_lineage_manifest(artifact_root: Path) -> tuple[Path, dict[str, Any]]:
    matches=[p for p in artifact_root.rglob("F02-LINEAGE.json") if p.is_file() and not p.is_symlink()]
    if len(matches)!=1: raise Refusal(f"expected exactly one F02-LINEAGE.json in current lineage artifact, got {len(matches)}")
    path=matches[0].resolve()
    if artifact_root.resolve() not in path.parents: raise Refusal("lineage manifest escaped artifact root")
    return path,json.loads(path.read_text())


def verify_current_lineage_segment(artifact_root: Path, sid: str, row: dict[str, Any],
                                   destination: Path) -> dict[str, Any]:
    if sys.platform == "darwin": raise Refusal("media hashing/copy is forbidden on Darwin")
    mp4=artifact_file(artifact_root,sid,".mp4"); verify=artifact_file(artifact_root,sid,".verify.json")
    if mp4.stat().st_size != row["expected_current_bytes"]: raise Refusal(f"current lineage SEG{sid} byte count changed")
    digest=sha256(mp4)
    receipt=json.loads(verify.read_text())
    if (digest != row["expected_current_sha256"] or receipt.get("sha256") != digest
            or receipt.get("bytes") != row["expected_current_bytes"] or receipt.get("frames") != row["frames"]
            or receipt.get("status") != "PASS" or receipt.get("full_decode") != "PASS"
            or receipt.get("flicker",{}).get("status") != "PASS"):
        raise Refusal(f"current master lineage SEG{sid} hash or render receipt mismatch")
    destination.mkdir(parents=True,exist_ok=False)
    shutil.copy2(mp4,destination/f"SEG{sid}.mp4"); shutil.copy2(verify,destination/f"SEG{sid}.verify.json")
    logs=[p for p in artifact_root.rglob(f"SEG{sid}.render.log") if p.is_file() and not p.is_symlink()]
    if len(logs)>1: raise Refusal(f"multiple retained render logs for SEG{sid}")
    if logs: shutil.copy2(logs[0],destination/logs[0].name)
    return {"sha256":digest,"bytes":mp4.stat().st_size,"verify_receipt":receipt,
            "artifact_files":sorted(p.name for p in destination.iterdir())}


def stage_segments(c: dict[str, Any], snapshots: Path, downloads: Path,
                   lineage_root: Path, assembly_segments: Path) -> dict[str, Any]:
    if sys.platform == "darwin": raise Refusal("media staging/hashing is forbidden on Darwin; hosted Ubuntu runner only")
    if lineage_root.exists() and any(lineage_root.iterdir()): raise Refusal("lineage output must be new/empty")
    if assembly_segments.exists() and any(assembly_segments.iterdir()): raise Refusal("assembly segment directory must be new/empty")
    prior_root=downloads/"current-lineage"
    manifest_path,prior=parent_lineage_manifest(prior_root)
    prior_rows=validate_prior_lineage(prior,c)
    preview=json.loads((snapshots/"parent-preview-receipt.json").read_text())
    validated_prior=validate_parent_preview_receipt(preview,c)
    if validated_prior != prior: raise Refusal("downloaded lineage manifest differs from hash-pinned durable parent receipt")
    lineage_root.mkdir(parents=True,exist_ok=True); assembly_segments.mkdir(parents=True,exist_ok=True)
    rows_by_id={r["i"]:r for r in c["segments"]}; records=[]; superseded=[]
    for row in c["segments"]:
        sid=row["i"]
        if row["lineage"] == "parent":
            prior_record=prior_rows[sid]
            target=lineage_root/"parent"/f"SEG{sid}"
            copied=verify_current_lineage_segment(prior_root,sid,row,target)
            shutil.copy2(target/f"SEG{sid}.mp4",assembly_segments/f"SEG{sid}.mp4")
            shutil.copy2(target/f"SEG{sid}.verify.json",assembly_segments/f"SEG{sid}.verify.json")
            record={**prior_record,"segment":sid,"provenance_role":"parent",
                    "preserved_from_master_run_id":c["parent_lineage"]["run_id"],
                    "preserved_from_lineage_artifact_id":c["parent_lineage"]["artifact_id"],
                    "hosted_media_sha256":copied["sha256"],"hosted_media_bytes":copied["bytes"],
                    "render_receipt":copied["verify_receipt"]}
        else:
            old=prior_rows[sid]
            superseded.append({"segment":sid,"prior_sha256":old["hosted_media_sha256"],
                               "prior_bytes":old["hosted_media_bytes"],"prior_run_id":old["run_id"],
                               "prior_artifact_id":old["artifact_id"],"prior_tag":old["tag"]})
            art_name=row["replacement_artifact_name"]
            source_dir=downloads/"replacement"/art_name
            copied=copy_artifact(source_dir,sid,lineage_root/"replacement"/f"SEG{sid}")
            for suffix in (".mp4",".verify.json"):
                shutil.copy2(lineage_root/"replacement"/f"SEG{sid}"/f"SEG{sid}{suffix}",assembly_segments/f"SEG{sid}{suffix}")
            artifact=next(a for a in collection(snapshots/"replacement"/"artifacts.jsonl","artifacts") if a.get("name")==art_name)
            record={"segment":sid,"t0":row["t0"],"len":row["len"],"expected_frames":row["frames"],
                    "provenance_role":"replacement","run_id":c["replacement"]["run_id"],
                    "tag":c["replacement"]["tag"],"code_commit":c["replacement"]["head_sha"],
                    "package_release":c["replacement"]["package_release"],"package_sha256":c["replacement"]["package_sha256"],
                    "artifact_name":art_name,"artifact_id":artifact["id"],"artifact_created_at":artifact["created_at"],
                    "artifact_expires_at":artifact["expires_at"],"artifact_size_in_bytes":artifact["size_in_bytes"],
                    "hosted_media_sha256":copied["sha256"],"hosted_media_bytes":copied["bytes"],
                    "render_receipt":copied["verify_receipt"],"supersedes_current_master_sha256":old["hosted_media_sha256"]}
        records.append(record)
    expected_names={f"SEG{r['i']}.mp4" for r in c["segments"]}|{f"SEG{r['i']}.verify.json" for r in c["segments"]}
    if {p.name for p in assembly_segments.iterdir()} != expected_names: raise Refusal("staged assembly set is not exactly 75 segment/receipt pairs")
    prov={"kind":"f02_segment_lineage_manifest","schema":2,"status":"STAGED_FOR_MECHANICAL_ASSEMBLY",
          "editorial_review":"NOT_PERFORMED","release_approval":"NOT_GRANTED","apply_source_overlay":False,
          "parent_master_run_id":c["parent_lineage"]["run_id"],"parent_master_sha256":c["parent_lineage"]["master_sha256"],
          "parent_lineage_artifact_id":c["parent_lineage"]["artifact_id"],
          "replacement_run_id":c["replacement"]["run_id"],"replacement_tag":c["replacement"]["tag"],
          "source_release":c["composition"]["sealed_source_release"],"source_package_sha256":c["composition"]["sealed_source_package_sha256"],
          "expected_segments":75,"expected_frames":19548,"replacement_segments":["01","02","51","52"],
          "segment_provenance":records,"superseded_current_master_segments":superseded}
    (lineage_root/"F02-LINEAGE.json").write_text(json.dumps(prov,indent=2)+"\n")
    return prov


def gh_snapshot_all(repo: str, out: Path, c: dict[str, Any]) -> None:
    snapshot_metadata(repo, out, c)


def refresh_sums(output_dir: Path) -> None:
    if sys.platform == "darwin":
        raise Refusal("final media checksum refresh is forbidden on Darwin; hosted Ubuntu runner only")
    sums = []
    for file in sorted(output_dir.iterdir()):
        if file.is_file() and file.name != "SHA256SUMS.txt":
            sums.append(f"{sha256(file)}  {file.name}")
    (output_dir / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    check = subprocess.run(["sha256sum", "-c", "SHA256SUMS.txt"], cwd=output_dir,
                           check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check.returncode:
        raise Refusal(f"final exported artifact checksum list failed: {check.stdout[-2000:]}")


def validate_staged_lineage(lineage: dict[str, Any], c: dict[str, Any]) -> None:
    if (lineage.get("kind")!="f02_segment_lineage_manifest" or lineage.get("schema")!=2
            or lineage.get("status")!="STAGED_FOR_MECHANICAL_ASSEMBLY"
            or lineage.get("release_approval")!="NOT_GRANTED" or lineage.get("apply_source_overlay") is not False
            or lineage.get("source_release")!=c["composition"]["sealed_source_release"]
            or lineage.get("source_package_sha256")!=c["composition"]["sealed_source_package_sha256"]
            or lineage.get("parent_master_run_id")!=c["parent_lineage"]["run_id"]
            or lineage.get("parent_master_sha256")!=c["parent_lineage"]["master_sha256"]
            or lineage.get("parent_lineage_artifact_id")!=c["parent_lineage"]["artifact_id"]
            or lineage.get("replacement_run_id")!=c["replacement"]["run_id"]
            or lineage.get("replacement_tag")!=c["replacement"]["tag"]
            or lineage.get("expected_segments")!=75 or lineage.get("expected_frames")!=19548
            or lineage.get("replacement_segments")!=["01","02","51","52"]):
        raise Refusal("staged lineage identity/status/grid mismatch")
    rows=lineage.get("segment_provenance")
    if not isinstance(rows,list) or len(rows)!=75: raise Refusal("staged lineage must contain exactly 75 active rows")
    expected={r["i"]:r for r in c["segments"]}; found={}
    for entry in rows:
        sid=entry.get("segment")
        if sid not in expected or sid in found: raise Refusal("staged lineage has unknown/duplicate segment ID")
        spec=expected[sid]; role="replacement" if spec["lineage"]=="replacement" else "parent"
        rec=entry.get("render_receipt",{})
        if (entry.get("provenance_role")!=role or entry.get("t0")!=spec["t0"] or entry.get("len")!=spec["len"]
                or entry.get("expected_frames")!=spec["frames"] or entry.get("hosted_media_bytes")<=0
                or not re.fullmatch(r"[0-9a-f]{64}",entry.get("hosted_media_sha256", ""))
                or rec.get("status")!="PASS" or rec.get("sha256")!=entry.get("hosted_media_sha256")
                or rec.get("bytes")!=entry.get("hosted_media_bytes") or rec.get("frames")!=spec["frames"]
                or rec.get("full_decode")!="PASS" or rec.get("flicker",{}).get("status")!="PASS"):
            raise Refusal(f"staged lineage row validation failed for SEG{sid}")
        if role=="parent":
            if (entry.get("preserved_from_master_run_id")!=c["parent_lineage"]["run_id"]
                    or entry.get("preserved_from_lineage_artifact_id")!=c["parent_lineage"]["artifact_id"]
                    or entry.get("hosted_media_sha256")!=spec["expected_current_sha256"]
                    or entry.get("hosted_media_bytes")!=spec["expected_current_bytes"]):
                raise Refusal(f"preserved SEG{sid} no longer matches current master lineage")
        else:
            if (entry.get("run_id")!=c["replacement"]["run_id"] or entry.get("code_commit")!=c["replacement"]["head_sha"]
                    or entry.get("tag")!=c["replacement"]["tag"]
                    or entry.get("package_sha256")!=c["replacement"]["package_sha256"]
                    or entry.get("artifact_name")!=spec["replacement_artifact_name"]
                    or entry.get("supersedes_current_master_sha256")!=spec["expected_current_sha256"]):
                raise Refusal(f"replacement SEG{sid} provenance/superseded hash mismatch")
        found[sid]=entry
    if set(found)!=set(expected): raise Refusal("staged lineage is missing one or more segments")
    superseded=lineage.get("superseded_current_master_segments")
    if not isinstance(superseded,list) or {r.get("segment") for r in superseded}!={"01","02","51","52"}:
        raise Refusal("lineage manifest lacks the exact superseded source-part set")
    for row in superseded:
        spec=expected[row["segment"]]
        if (row.get("prior_sha256")!=spec["expected_current_sha256"]
                or row.get("prior_bytes")!=spec["expected_current_bytes"]
                or row.get("prior_run_id")!=spec["previous_run_id"]):
            raise Refusal("superseded current-master part provenance mismatch")


def make_final_receipt(integrity_path: Path, lineage_path: Path, output_dir: Path, c: dict[str, Any] | None = None) -> dict[str, Any]:
    if sys.platform == "darwin":
        raise Refusal("final media receipt hashing is forbidden on Darwin; hosted Ubuntu runner only")
    integrity = json.loads(integrity_path.read_text())
    lineage = json.loads(lineage_path.read_text())
    c=c or load_contract()
    validate_staged_lineage(lineage,c)
    if integrity.get("kind") != "mechanical_integrity_only" or integrity.get("release_approval") != "NOT_GRANTED":
        raise Refusal("assemble_verify did not produce the expected mechanical-only receipt")
    if (integrity.get("editorial_gate") != "NOT_RUN" or integrity.get("duration") != 651.6
            or integrity.get("segment_count") != 75 or integrity.get("frame_count") != 19548):
        raise Refusal("whole-master receipt scope/count mismatch")
    expected_checks = {"segment_decode", "segment_flicker", "master_full_decode",
                       "derived_full_decode", "encoded_audio_loudness_and_true_peak"}
    checks = integrity.get("checks")
    if not isinstance(checks, dict) or set(checks) != expected_checks or any(v != "PASS" for v in checks.values()):
        raise Refusal("whole-master receipt check schema/status mismatch")
    outputs = integrity.get("outputs")
    if not isinstance(outputs, dict) or outputs.get("master") != "F02-MASTER-4K.mp4" or outputs.get("derived") != "F02-MASTER-1080-from-4K.mp4":
        raise Refusal("whole-master receipt output paths mismatch")
    master_path = output_dir / outputs["master"]
    derived_path = output_dir / outputs["derived"]
    if (not master_path.is_file() or master_path.stat().st_size <= 0
            or master_path.stat().st_size != outputs.get("master_bytes")
            or sha256(master_path) != outputs.get("master_sha256")):
        raise Refusal("whole-master receipt master hash/byte mismatch")
    if (not derived_path.is_file() or derived_path.stat().st_size <= 0
            or derived_path.stat().st_size != outputs.get("derived_bytes")):
        raise Refusal("whole-master receipt derived proxy byte mismatch")
    outputs["derived_sha256"] = sha256(derived_path)
    receipt = {"kind": "F02-hosted-partial-assembly-receipt", "schema": 1,
               "status": "MECHANICAL_INTEGRITY_VERIFIED_ONLY", "editorial_status": "NOT_REVIEWED",
               "release_approval": "NOT_GRANTED", "armed": False,
               "source_release": lineage["source_release"], "source_package_sha256": lineage["source_package_sha256"],
               "parent_master_run_id": lineage["parent_master_run_id"],
               "parent_master_sha256": lineage["parent_master_sha256"],
               "replacement_segments": lineage["replacement_segments"],
               "duration_seconds": integrity["duration"], "segments": integrity["segment_count"],
               "frames": integrity["frame_count"], "checks": integrity["checks"],
               "master": outputs,
               "lineage_manifest": "F02-LINEAGE.json",
               "notes": "Technical decode/probe/audio integrity does not constitute whole-film editorial review or release approval."}
    path = output_dir / "F02-PARTIAL-ASSEMBLY-RECEIPT.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def self_test() -> None:
    c=load_contract()
    bind_replacement(c,900000001,"b"*40); validate_contract(c)
    assert len(c["segments"])==75 and sum(r["frames"] for r in c["segments"])==19548
    assert [r["i"] for r in c["segments"] if r["lineage"]=="replacement"]==["01","02","51","52"]
    print("self-test PASS: exact 75-part/19,548-frame grid; replacements 01/02/51/52; no media opened")


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=["validate-contract","snapshot","preflight","verify-authoritative-helper","prepare-source","print-source-release",
                                        "download-and-stage","print-segments-json","final-receipt","refresh-sums","self-test"])
    ap.add_argument("--contract",type=Path,default=CONTRACT_PATH)
    ap.add_argument("--repo",default=EXPECTED_REPO)
    ap.add_argument("--snapshots",type=Path,default=Path("metadata"))
    ap.add_argument("--downloads",type=Path,default=Path("downloads"))
    ap.add_argument("--source-archive",type=Path,default=Path("source.tar.gz"))
    ap.add_argument("--helper",type=Path,default=Path(".github/scripts/assemble_verify.py"))
    ap.add_argument("--package-dir",type=Path,default=Path("package"))
    ap.add_argument("--lineage-dir",type=Path,default=Path("lineage"))
    ap.add_argument("--segments-dir",type=Path,default=Path("assembly/segments"))
    ap.add_argument("--output-dir",type=Path,default=Path("remote-final"))
    ap.add_argument("--replacement-run-id",type=int)
    ap.add_argument("--replacement-head-sha")
    a=ap.parse_args(); c=load_contract(a.contract)
    if a.command=="self-test": self_test(); return 0
    if a.command != "refresh-sums":
        if a.replacement_run_id is None or a.replacement_head_sha is None:
            raise Refusal("exact replacement run ID and head SHA inputs are required")
        bind_replacement(c,a.replacement_run_id,a.replacement_head_sha)
    if a.command=="validate-contract":
        validate_contract(c); print("contract PASS; no media opened")
    elif a.command=="snapshot":
        snapshot_metadata(a.repo,a.snapshots,c)
    elif a.command=="preflight":
        validate_contract(c); validate_metadata(c,a.snapshots)
        print("preflight PASS; exact current master lineage, source release, replacement run/artifacts, preview receipt and expiry verified before media download")
    elif a.command=="verify-authoritative-helper":
        validate_contract(c); print(json.dumps(verify_authoritative_helper(a.helper,c),indent=2))
    elif a.command=="prepare-source":
        validate_contract(c); print(json.dumps(prepare_source(a.source_archive,a.package_dir,c),indent=2))
    elif a.command=="download-and-stage":
        validate_contract(c)
        if sys.platform=="darwin": raise Refusal("hosted Ubuntu runner only")
        a.downloads.mkdir(parents=True,exist_ok=False)
        validate_metadata(c,a.snapshots)
        work=[]
        with ThreadPoolExecutor(max_workers=3) as pool:
            parent=c["parent_lineage"]
            work.append(pool.submit(safe_download,parent["run_id"],parent["artifact_name"],a.downloads/"current-lineage"))
            for row in c["segments"]:
                if row["lineage"]!="replacement": continue
                name=row["replacement_artifact_name"]
                work.append(pool.submit(safe_download,c["replacement"]["run_id"],name,a.downloads/"replacement"/name))
            for future in as_completed(work): future.result()
        stage_segments(c,a.snapshots,a.downloads,a.lineage_dir,a.segments_dir)
        print("segment provenance staged: 71 exact current-master lineage parts plus four hash-verified replacements")
    elif a.command=="print-segments-json":
        validate_contract(c); print(json.dumps([{k:r[k] for k in ("i","t0","len")} for r in c["segments"]],separators=(",",":")))
    elif a.command=="print-source-release":
        validate_contract(c); print(c["composition"]["sealed_source_release"])
    elif a.command=="final-receipt":
        validate_contract(c)
        make_final_receipt(a.output_dir/"REMOTE-INTEGRITY.json",a.lineage_dir/"F02-LINEAGE.json",a.output_dir,c)
    elif a.command=="refresh-sums":
        refresh_sums(a.output_dir); print("final checksum list PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"REFUSED/FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
