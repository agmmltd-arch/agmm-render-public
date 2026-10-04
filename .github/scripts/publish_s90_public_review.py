#!/usr/bin/env python3
"""Publish only 37 hosted S90 stills and small hash-bound text receipts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import struct
from pathlib import Path


REPO = "agmmltd-arch/agmm-render-public"
SCENE_SHA256 = "2e92ff94e6764379e941a2f924e21974c69dc7b8064013a6c3d0f9a8534269f7"
FRAME_NAMES = ({f"B{i:02d}-{part}" for i in range(1, 17) for part in ("incoming", "late")} | {
    "B01-frame-zero", "B02-pre-reveal", "B02-reveal-onset",
    "B02-post-onset", "B02-reveal-complete",
})
INPUT_FIXED = {
    "CAPTURE-EVIDENCE.json", "INPUT-RECEIPT.json", "MEDIA-IDENTITIES.json",
    "SHA256SUMS.txt", "STAGING-RECEIPT.json", "receipts/s90-preview-a.json",
}
OUTPUT_JSON = {
    "CAPTURE-EVIDENCE.json", "INPUT-RECEIPT.json", "STAGING-RECEIPT.json",
    "PUBLIC-REVIEW-RECEIPT.json",
}


class Refusal(RuntimeError):
    pass


def guard() -> int:
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("S90_HOSTED_PREVIEW") != "1":
        raise Refusal("GitHub Actions Linux required before any capture-pack file IO")
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise Refusal("unexpected public review repository")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise Refusal("valid GitHub Actions run id required before any capture-pack file IO")
    return int(run_id)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> bytes:
    data = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    path.write_bytes(data)
    return data


def exact_tree(root: Path, expected: set[str], label: str) -> None:
    if root.is_symlink() or not root.is_dir():
        raise Refusal(f"{label} must be a real directory")
    actual: set[str] = set()
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise Refusal(f"{label} contains a symlink: {rel}")
        if path.is_dir():
            continue
        if not stat.S_ISREG(os.stat(path, follow_symlinks=False).st_mode):
            raise Refusal(f"{label} contains a non-regular file: {rel}")
        actual.add(rel)
    if actual != expected:
        raise Refusal(f"{label} file set mismatch: missing={sorted(expected-actual)} extra={sorted(actual-expected)}")


def validate_capture_receipts(evidence: dict, input_receipt: dict, staging: dict, media: dict) -> list[dict]:
    binding = evidence.get("binding")
    if (evidence.get("kind") != "agmm_short_hosted_capture_evidence" or evidence.get("technical_status") != "CAPTURE_PASS"
            or evidence.get("editorial_status") != "NOT_REVIEWED" or evidence.get("publication_status") != "NOT_REQUESTED"
            or evidence.get("short_id") != "S90-silent-development" or evidence.get("full_video_render") != "NOT_RUN"
            or evidence.get("full_video_decode") != "NOT_RUN" or evidence.get("duration") != 58.133):
        raise Refusal("capture evidence identity/scope/status mismatch")
    if (input_receipt.get("kind") != "agmm_short_capture_input_receipt" or input_receipt.get("technical_status") != "INPUT_IDENTITY_PASS"
            or input_receipt.get("editorial_status") != "NOT_REVIEWED" or input_receipt.get("publication_status") != "NOT_REQUESTED"
            or input_receipt.get("binding") != binding):
        raise Refusal("capture input receipt does not match evidence binding/status")
    if (media.get("kind") != "agmm_short_media_identities" or media.get("sha256") != binding.get("media_identity_sha256")):
        raise Refusal("capture media identity receipt does not match evidence binding")
    if (staging.get("kind") != "s90_silent_development_staging_receipt"
            or staging.get("technical_status") != "STAGED_ON_HOSTED_LINUX_FOR_CAPTURE_ONLY"
            or staging.get("source_sha256") != binding.get("source_sha256")
            or staging.get("parts_sha256") != binding.get("parts_sha256")
            or staging.get("capture_plan_sha256") != binding.get("capture_plan_sha256")
            or staging.get("media_identity_sha256") != binding.get("media_identity_sha256")
            or staging.get("storyboard") != "NOT_APPROVED" or staging.get("rights") != "NOT_ASSESSED"
            or staging.get("production_or_release_approval") != "NOT_GRANTED"):
        raise Refusal("staging receipt scope or exact input binding mismatch")
    captures = evidence.get("captures")
    if staging.get("candidate_scene_sha256") != SCENE_SHA256:
        raise Refusal("staging receipt candidate scene SHA256 does not match the exact reviewed scene")
    if not isinstance(captures, list) or len(captures) != 37:
        raise Refusal("expected exactly 37 named stills: 32 beat windows plus five unique reveal samples")
    if {row.get("name") for row in captures} != FRAME_NAMES or len({row.get("name") for row in captures}) != 37:
        raise Refusal("capture names differ from the exact 37-name source-review set")
    by_name = {row["name"]: row for row in captures}
    expected_times = {
        "B01-frame-zero": 0.0, "B02-incoming": 3.833,
        "B02-pre-reveal": 7.633, "B02-reveal-onset": 7.644,
        "B02-post-onset": 7.667, "B02-reveal-complete": 7.933,
    }
    if any(by_name[name].get("global") != when for name, when in expected_times.items()):
        raise Refusal("frame-zero/setup/reveal timing samples differ from the locked voice word clock")
    if len({round(float(row.get("local", -1)) * 1_000_000) for row in captures}) != 37:
        raise Refusal("capture receipt contains duplicate timestamps")
    if any(row.get("look") != "s90-preview-a" or row.get("width") != 1080 or row.get("height") != 1920 for row in captures):
        raise Refusal("capture look or dimensions differ from the bounded native composition")
    return captures


def expected_output_paths(rows: list[dict]) -> set[str]:
    if len(rows) != 37:
        raise Refusal("public review output requires exactly 37 captures")
    frames = set()
    for row in rows:
        rel = row.get("file")
        if not isinstance(rel, str) or not re.fullmatch(r"frames/[A-Za-z0-9._-]+\.png", rel):
            raise Refusal("unsafe output capture path")
        frames.add(rel)
    if len(frames) != 37:
        raise Refusal("public review frame paths are duplicated")
    return frames | OUTPUT_JSON | {"REVIEW-SHA256SUMS.txt"}


def publish_pack(capture_pack: Path, output: Path) -> dict:
    run_id = guard()
    if capture_pack.is_symlink() or not capture_pack.is_dir():
        raise Refusal("capture pack must be a real directory")
    evidence_path = capture_pack / "CAPTURE-EVIDENCE.json"
    input_path = capture_pack / "INPUT-RECEIPT.json"
    stage_path = capture_pack / "STAGING-RECEIPT.json"
    media_path = capture_pack / "MEDIA-IDENTITIES.json"
    sums_path = capture_pack / "SHA256SUMS.txt"
    evidence = json.loads(evidence_path.read_text())
    input_receipt = json.loads(input_path.read_text())
    staging = json.loads(stage_path.read_text())
    media = json.loads(media_path.read_text())
    captures = validate_capture_receipts(evidence, input_receipt, staging, media)
    ordered_captures = sorted(captures, key=lambda row: (row["global"], row["name"]))
    expected_frames = {f"frames/{i:02d}-{row['name']}.png" for i, row in enumerate(ordered_captures, 1)}
    if any(row.get("file") != f"frames/{i:02d}-{row['name']}.png" for i, row in enumerate(ordered_captures, 1)):
        raise Refusal("capture bundle frame names/order differ from the native producer contract")
    exact_tree(capture_pack, expected_frames | INPUT_FIXED, "capture pack")
    sum_rows = {}
    for line in sums_path.read_text().splitlines():
        if "  " not in line:
            raise Refusal("capture bundle checksum line is malformed")
        checksum, name = line.split("  ", 1)
        if not re.fullmatch(r"[0-9a-f]{64}", checksum) or name in sum_rows:
            raise Refusal("capture bundle checksum is malformed or duplicated")
        sum_rows[name] = checksum
    expected_sum_names = {row["file"] for row in captures} | {"MEDIA-IDENTITIES.json"}
    if set(sum_rows) != expected_sum_names or digest(media_path.read_bytes()) != sum_rows["MEDIA-IDENTITIES.json"]:
        raise Refusal("capture bundle checksum list includes unexpected files or wrong media identity digest")
    part_receipt = json.loads((capture_pack / "receipts/s90-preview-a.json").read_text())
    if (part_receipt.get("kind") != "agmm_short_capture_part_receipt" or part_receipt.get("look") != "s90-preview-a"
            or part_receipt.get("binding") != evidence.get("binding") or part_receipt.get("technical_status") != "CAPTURE_PASS"):
        raise Refusal("single-part receipt does not match exact capture evidence")
    part_captures = part_receipt.get("captures")
    if not isinstance(part_captures, list) or {row.get("name") for row in part_captures} != FRAME_NAMES:
        raise Refusal("single-part receipt does not contain all 37 named captures")
    part_by_name = {row["name"]: row for row in part_captures}
    for row in captures:
        part_row = part_by_name[row["name"]]
        if any(part_row.get(key) != row.get(key) for key in ("kind", "global", "local", "look", "part_index", "part_out", "sha256", "bytes", "width", "height")):
            raise Refusal(f"part receipt and evidence differ for {row['name']}")
    for row in captures:
        rel = row.get("file")
        if not isinstance(rel, str) or not re.fullmatch(r"frames/[A-Za-z0-9._-]+\.png", rel):
            raise Refusal("unsafe capture file reference")
        path = capture_pack / rel
        data = path.read_bytes()
        if digest(data) != row.get("sha256") or digest(data) != sum_rows.get(rel):
            raise Refusal(f"capture still bytes do not match both source-bound receipts: {row['name']}")
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR" or struct.unpack(">II", data[16:24]) != (1080, 1920):
            raise Refusal(f"capture still is not a 1080x1920 PNG: {row['name']}")
    if output.exists() or output.is_symlink():
        raise Refusal("public review output must not already exist")
    output.mkdir(parents=True, exist_ok=False)
    frame_dir = output / "frames"
    frame_dir.mkdir()
    rows = []
    for row in sorted(captures, key=lambda x: (x["global"], x["name"])):
        source = capture_pack / row["file"]
        data = source.read_bytes()
        dest = frame_dir / Path(row["file"]).name
        dest.write_bytes(data)
        rows.append({"name": row["name"], "global": row["global"], "look": row["look"], "file": f"frames/{dest.name}", "bytes": len(data), "sha256": digest(data), "width": 1080, "height": 1920})
    (output / "CAPTURE-EVIDENCE.json").write_bytes(evidence_path.read_bytes())
    (output / "INPUT-RECEIPT.json").write_bytes(input_path.read_bytes())
    (output / "STAGING-RECEIPT.json").write_bytes(stage_path.read_bytes())
    branch = f"review-S90-silent-preview-{run_id}"
    review = {
        "kind": "S90-public-silent-storyboard-development-review-pack",
        "repository": REPO,
        "branch": branch,
        "run_id": run_id,
        "source_sha256": evidence["binding"]["source_sha256"],
        "parts_sha256": evidence["binding"]["parts_sha256"],
        "capture_plan_sha256": evidence["binding"]["capture_plan_sha256"],
        "media_identity_sha256": evidence["binding"]["media_identity_sha256"],
        "capture_evidence_sha256": digest(evidence_path.read_bytes()),
        "input_receipt_sha256": digest(input_path.read_bytes()),
        "staging_receipt_sha256": digest(stage_path.read_bytes()),
        "capture_count": len(rows), "captures": rows,
        "editorial_status": "NOT_REVIEWED", "storyboard_approval": "NOT_GRANTED",
        "rights_status": "NOT_ASSESSED", "production_release": "NOT_AUTHORIZED",
        "scope": "37 hosted PNG stills and bound text receipts only; no source archive, source PNGs, media identity list, audio, or assembled master",
    }
    write_json(output / "PUBLIC-REVIEW-RECEIPT.json", review)
    exact_output = expected_output_paths(rows)
    exact_tree(output, exact_output - {"REVIEW-SHA256SUMS.txt"}, "public review output before checksum")
    sums = []
    for path in sorted(p for p in output.rglob("*") if p.is_file()):
        sums.append(f"{digest(path.read_bytes())}  {path.relative_to(output).as_posix()}")
    (output / "REVIEW-SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    exact_tree(output, exact_output, "public review output")
    if len(sums) != 41:
        raise Refusal("public review payload must contain exactly 37 PNGs and four JSON receipts")
    return review


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_pack", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        review = publish_pack(args.capture_pack, args.output)
    except Refusal as exc:
        raise SystemExit(f"S90 public review refusal: {exc}")
    print(json.dumps({"branch": review["branch"], "capture_count": review["capture_count"], "scope": review["scope"]}, sort_keys=True))


if __name__ == "__main__":
    main()
