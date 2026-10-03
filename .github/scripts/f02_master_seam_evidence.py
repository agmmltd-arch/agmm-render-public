#!/usr/bin/env python3
"""Hosted-only, source-pinned F02 seam-context evidence (not editorial approval)."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Optional

REPO = "agmmltd-arch/agmm-render-public"
RUN = 37146440125
HEAD = "3be0bf2c26e2186710002796a80b1eda115c1d3f"
WORKFLOW = ".github/workflows/agmm-f02-partial-assembly.yml"
TAG = "preview-F02-37146440125"
RECEIPT_NAME = "HOSTED-PREVIEW.json"
RECEIPT_SHA = "cc0d364aae718266ca2a955adfacdffa46fff02e12e6cbe3442f236fb9cbff5f"
MASTER_NAME = "F02-MASTER-4K.mp4"
MASTER_SIZE = 2_849_432_872
MASTER_SHA = "276ae17ca24d46c9b08508dc2cfaec00bc89ad6c1d3e4b96fd7d490e64c7c51e"
PARTS = (
    ("F02-MASTER-4K.mp4.part0001", 1_500_000_000,
     "71d1464f48993059055934ee6de03380e458a4085a00929236c5e236a1d6087d"),
    ("F02-MASTER-4K.mp4.part0002", 1_349_432_872,
     "7d26cc866178dd5a7628429c6187256d1c352ce2359905bf69f7b5e4b452dfc3"),
)
FPS = 30
FRAME_COUNT = 19_548
WIDTH, HEIGHT = 3840, 2160
REPAIR_CENTER = 439.5 * FPS  # Original crop requested for direct corrected-master recheck.
REPAIR_RADIUS = 2
MIN_FREE_BYTES = 12 * 1024**3
MAX_EVIDENCE_BYTES = 2 * 1024**3
MAX_PNG_BYTES = 80 * 1024**2  # Below GitHub's per-file hard limit, with margin.


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Cannot read JSON {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"Expected JSON object at {path}")
    return value


def verify_source(repo: dict, run: dict, release: dict, receipt_bytes: bytes,
                  pinned_receipt_sha: str = RECEIPT_SHA) -> tuple[dict, list[dict]]:
    """Validate public metadata + exact schema-3 receipt before media transfer."""
    if repo.get("full_name") != REPO or repo.get("private") is not False:
        fail("Expected the exact public source repository")
    if repo.get("default_branch") != "main":
        fail("Unexpected source repository default branch")
    if (run.get("id") != RUN or run.get("status") != "completed"
            or run.get("conclusion") != "success" or run.get("head_sha") != HEAD
            or run.get("path") != WORKFLOW
            or run.get("repository", {}).get("full_name") != REPO):
        fail("Source workflow run identity/conclusion mismatch")
    if (release.get("tag_name") != TAG or release.get("draft") is not False
            or release.get("prerelease") is not False
            or release.get("target_commitish") != HEAD):
        fail("Source release identity/state mismatch")

    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    if receipt_sha != pinned_receipt_sha:
        fail("Hosted receipt bytes differ from the pinned receipt")
    try:
        proof = json.loads(receipt_bytes)
    except json.JSONDecodeError as exc:
        fail(f"Receipt is invalid JSON: {exc}")
    if not isinstance(proof, dict):
        fail("Receipt must be a JSON object")
    required_identity = {
        "schema_version": 3, "source_run_id": RUN, "repository": REPO,
        "source_workflow": WORKFLOW, "source_workflow_commit": HEAD,
        "source_conclusion": "success", "release_tag": TAG,
        "review_status": "NOT_REVIEWED", "ocr_status": "NOT_RUN",
        "release_approval": "NOT_GRANTED", "armed": False,
    }
    for key, expected in required_identity.items():
        if proof.get(key) != expected:
            fail(f"Receipt field {key!r} does not match pinned source")

    files = proof.get("files")
    if not isinstance(files, list):
        fail("Receipt files must be an array")
    by_name = {item.get("name"): item for item in files if isinstance(item, dict)}
    if len(by_name) != len(files):
        fail("Receipt contains invalid or duplicate file entries")
    for name, size, digest in PARTS:
        item = by_name.get(name)
        if (not item or item.get("size") != size or item.get("sha256") != digest
                or item.get("url") != f"https://github.com/{REPO}/releases/download/{TAG}/{name}"):
            fail(f"Receipt part identity mismatch for {name}")
    if sum(item[1] for item in PARTS) != MASTER_SIZE:
        fail("Pinned master size does not equal the ordered part sizes")
    master = proof.get("master")
    if (not isinstance(master, dict) or master.get("name") != MASTER_NAME
            or master.get("size") != MASTER_SIZE or master.get("sha256") != MASTER_SHA
            or master.get("parts") != [part[0] for part in PARTS]):
        fail("Receipt master identity or part ordering mismatch")

    integrity = proof.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("kind") != "mechanical_integrity_only":
        fail("Missing mechanical-only integrity receipt")
    if (integrity.get("editorial_gate") != "NOT_RUN"
            or integrity.get("release_approval") != "NOT_GRANTED"
            or integrity.get("fps") != FPS or integrity.get("frame_count") != FRAME_COUNT
            or integrity.get("segment_count") != 75 or integrity.get("duration") != 651.6):
        fail("Integrity summary differs from the exact expected assembly")
    outputs = integrity.get("outputs", {})
    if (outputs.get("master") != MASTER_NAME or outputs.get("master_bytes") != MASTER_SIZE
            or outputs.get("master_sha256") != MASTER_SHA
            or outputs.get("segments") != 75 or outputs.get("frames") != FRAME_COUNT):
        fail("Integrity outputs do not bind the expected master")
    assembly = proof.get("assembly", {})
    assembly_master = assembly.get("master") if isinstance(assembly, dict) else None
    if (not isinstance(assembly, dict) or assembly.get("release_approval") != "NOT_GRANTED"
            or assembly.get("armed") is not False or assembly.get("editorial_status") != "NOT_REVIEWED"
            or not isinstance(assembly_master, dict)
            or assembly_master.get("master_sha256") != MASTER_SHA
            or assembly_master.get("master_bytes") != MASTER_SIZE):
        fail("Native partial assembly nested authority/master identity mismatch")

    segments = integrity.get("segments")
    if not isinstance(segments, list) or len(segments) != 75:
        fail("Expected exact 75-segment native receipt")
    previous_end = 0
    boundaries = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or segment.get("id") != f"{index + 1:02d}":
            fail("Segment IDs are not contiguous and ordered")
        t0 = segment.get("t0")
        nframes = segment.get("frames")
        if (not isinstance(t0, (int, float)) or isinstance(t0, bool)
                or not isinstance(nframes, int) or isinstance(nframes, bool) or nframes <= 0):
            fail("Segment timing/frame metadata is malformed")
        start = t0 * FPS
        start_frame = round(start)
        if not math.isclose(start, start_frame, rel_tol=0.0, abs_tol=1e-6) or start_frame != previous_end:
            fail(f"Segment {segment['id']} is not contiguous at a 30 fps frame boundary")
        proof_segment = segment.get("hosted_receipt", {})
        if (proof_segment.get("full_decode") != "PASS"
                or proof_segment.get("status") != "PASS"
                or proof_segment.get("frames") != nframes):
            fail(f"Segment {segment['id']} lacks the producer's full-decode receipt")
        if index:
            boundaries.append({"left_segment": f"{index:02d}",
                               "right_segment": segment["id"],
                               "boundary_frame": start_frame})
        previous_end = start_frame + nframes
    if previous_end != FRAME_COUNT:
        fail("Segment receipt does not cover the exact complete frame range")

    repair_center = int(REPAIR_CENTER)
    if REPAIR_CENTER != repair_center or not 0 <= repair_center < FRAME_COUNT:
        fail("Pinned repair-check timestamp is outside the master")
    frame_roles: dict[int, list[str]] = {}
    for boundary in boundaries:
        frame = boundary["boundary_frame"]
        for index in range(frame - 2, frame + 3):
            if not 0 <= index < FRAME_COUNT:
                fail("A seam context frame falls outside the master")
            frame_roles.setdefault(index, []).append(
                f"seam:{boundary['left_segment']}-{boundary['right_segment']}"
            )
    for index in range(repair_center - REPAIR_RADIUS, repair_center + REPAIR_RADIUS + 1):
        frame_roles.setdefault(index, []).append("repair-context:439.5s")
    frame_plan = [
        {"index": index, "time_s": index / FPS, "roles": sorted(roles),
         "filename": f"frame-{index:05d}.png"}
        for index, roles in sorted(frame_roles.items())
    ]
    if len(boundaries) != 74 or len(frame_plan) != 375:
        fail("Expected 74 seams plus five repair-context frames (375 unique frames)")

    assets = release.get("assets")
    if not isinstance(assets, list):
        fail("Release assets are missing")
    asset_map = {asset.get("name"): asset for asset in assets if isinstance(asset, dict)}
    if len(asset_map) != len(assets):
        fail("Release contains invalid or duplicate asset names")
    receipt_asset = asset_map.get(RECEIPT_NAME)
    if (not receipt_asset or receipt_asset.get("size") != len(receipt_bytes)
            or receipt_asset.get("digest") != f"sha256:{pinned_receipt_sha}"):
        fail("Release metadata does not bind the exact receipt asset")
    for name, size, digest in PARTS:
        asset = asset_map.get(name)
        expected_url = f"https://github.com/{REPO}/releases/download/{TAG}/{name}"
        if (not asset or asset.get("size") != size or asset.get("digest") != f"sha256:{digest}"
                or asset.get("browser_download_url") != expected_url
                or asset.get("state") != "uploaded"):
            fail(f"Public release asset metadata mismatch for {name}")
    return proof, frame_plan


def guard_hosted_identity() -> None:
    if (platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != REPO):
        fail("Hosted Linux Actions runner for the exact public repository required")


def check_hosted_runner(capacity_out: Optional[Path] = None) -> dict:
    guard_hosted_identity()
    usage = shutil.disk_usage(os.environ.get("RUNNER_TEMP", "/tmp"))
    if usage.free < MIN_FREE_BYTES:
        fail(f"Need at least 12 GiB free before media transfer; observed {usage.free} bytes")
    result = {"runner_os": platform.platform(), "scratch_free_bytes": usage.free,
              "minimum_scratch_bytes": MIN_FREE_BYTES}
    if capacity_out:
        capacity_out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return result


def verify_and_join_parts(parts_dir: Path, output: Path,
                          expected_parts=PARTS, expected_size=MASTER_SIZE,
                          expected_sha=MASTER_SHA) -> str:
    """Hash each downloaded part and the ordered concatenation in one bounded pass."""
    output.parent.mkdir(parents=True, exist_ok=True)
    whole = hashlib.sha256()
    total = 0
    with output.open("wb") as destination:
        for name, part_expected_size, part_expected_sha in expected_parts:
            path = parts_dir / name
            part_hash = hashlib.sha256()
            part_size = 0
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    destination.write(chunk)
                    part_hash.update(chunk)
                    whole.update(chunk)
                    part_size += len(chunk)
            if part_size != part_expected_size or part_hash.hexdigest() != part_expected_sha:
                output.unlink(missing_ok=True)
                fail(f"Downloaded part failed size/SHA check: {name}")
            total += part_size
        destination.flush()
        os.fsync(destination.fileno())
    if total != expected_size or output.stat().st_size != expected_size or whole.hexdigest() != expected_sha:
        output.unlink(missing_ok=True)
        fail("Ordered part concatenation does not match the pinned complete master")
    return whole.hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        fail(f"Invalid PNG output: {path.name}")
    return struct.unpack(">II", header[16:24])


def extract(master: Path, frame_plan: list[dict], out: Path, proof: dict, master_sha: str,
            capacity_info: dict) -> dict:
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height,r_frame_rate,nb_frames", "-of", "json", str(master),
    ]))
    streams = probe.get("streams", [])
    if len(streams) != 1:
        fail("Exact master must contain one selected video stream")
    video_stream = streams[0]
    if (video_stream.get("width"), video_stream.get("height"), video_stream.get("r_frame_rate"),
            int(video_stream.get("nb_frames", 0))) != (WIDTH, HEIGHT, "30/1", FRAME_COUNT):
        fail("Reassembled master probe differs from the pinned 4K/30 fps/frame-count source")
    out.mkdir(parents=True, exist_ok=False)
    indexes = [item["index"] for item in frame_plan]
    expression = "+".join(f"eq(n\\,{index})" for index in indexes)
    # No -frames:v cap: ffmpeg decodes through EOF once, extracting the exact selected frames.
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-threads", "2", "-i", str(master),
        "-map", "0:v:0", "-vf", f"select='{expression}'", "-fps_mode", "vfr",
        "-start_number", "0", str(out / "decoded-%03d.png"),
    ], check=True)
    outputs = sorted(out.glob("decoded-*.png"))
    if len(outputs) != len(frame_plan):
        fail(f"Decoded {len(outputs)} selected frames; expected {len(frame_plan)}")
    frames = []
    total = 0
    for plan, temporary in zip(frame_plan, outputs):
        size = temporary.stat().st_size
        if size <= 0 or size > MAX_PNG_BYTES:
            fail(f"PNG out of per-file bounds: {temporary.name} ({size} bytes)")
        if png_dimensions(temporary) != (WIDTH, HEIGHT):
            fail(f"Unexpected decoded image dimensions: {temporary.name}")
        digest = hashlib.sha256()
        with temporary.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        target = out / plan["filename"]
        temporary.rename(target)
        total += size
        frames.append({**plan, "size": size, "sha256": digest.hexdigest()})
    if total > MAX_EVIDENCE_BYTES:
        fail(f"Evidence PNG set exceeds 2 GiB bound ({total} bytes)")
    receipt = {
        "schema_version": 1, "kind": "F02_EXACT_MASTER_SEAM_CONTEXT_SAMPLE",
        "source_repository": REPO, "source_run_id": RUN, "source_workflow": WORKFLOW,
        "source_workflow_head": HEAD, "source_release_tag": TAG,
        "source_receipt_sha256": RECEIPT_SHA, "master_filename": MASTER_NAME,
        "master_size": MASTER_SIZE, "master_sha256": master_sha,
        "source_fps": FPS, "source_frame_count": FRAME_COUNT,
        "source_resolution": [WIDTH, HEIGHT], "boundary_count": 74,
        "hosted_runner_capacity": capacity_info,
        "seam_context_frames": 370, "repair_context": {"center_frame": int(REPAIR_CENTER),
            "center_time_s": 439.5, "radius_frames": REPAIR_RADIUS},
        "unique_png_count": len(frames), "png_bytes_total": total,
        "producer_segment_full_decode_receipt": "PASS (source-bound receipt; 75 segments)",
        "reassembled_master_probe": {"width": video_stream["width"], "height": video_stream["height"],
            "r_frame_rate": video_stream["r_frame_rate"], "nb_frames": int(video_stream["nb_frames"])},
        "combined_master_single_ffmpeg_decode_and_extract": "PASS",
        "scope": "375 selected 4K frame PNGs: five frames around each of 74 joins plus five at 439.5s. Not a full-film human review.",
        "ocr_status": "NOT_RUN", "full_visual_review": "NOT_RUN",
        "motion_review": "NOT_RUN", "audio_review": "NOT_RUN",
        "pilot_comparison": "NOT_RUN", "thumbnail_review": "NOT_RUN",
        "review_status": "NOT_REVIEWED", "release_approval": "NOT_GRANTED",
        "frames": frames,
    }
    (out / "SEAM-EVIDENCE.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (out / "README.txt").write_text(
        "F02 exact corrected-master seam context sample.\n"
        f"Source master SHA-256: {master_sha}\n"
        "375 decoded 4K PNGs: 370 frames around all 74 joins plus five frames at 439.5 seconds.\n"
        "This is a selected-frame sample, not full-film visual/motion/audio review or approval.\n"
        "OCR NOT_RUN; review NOT_REVIEWED; release approval NOT_GRANTED.\n"
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-source", action="store_true")
    parser.add_argument("--check-runner", action="store_true")
    parser.add_argument("--capacity-out", type=Path)
    parser.add_argument("--capacity-json", type=Path)
    parser.add_argument("--repo-json", type=Path)
    parser.add_argument("--run-json", type=Path)
    parser.add_argument("--release-json", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--plan-out", type=Path)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--parts-dir", type=Path)
    parser.add_argument("--master-out", type=Path)
    parser.add_argument("--evidence-out", type=Path)
    args = parser.parse_args()
    if args.validate_source:
        if not all((args.repo_json, args.run_json, args.release_json, args.receipt, args.plan_out)):
            parser.error("--validate-source requires repo/run/release/receipt/plan paths")
        proof, frames = verify_source(load_json(args.repo_json), load_json(args.run_json),
                                      load_json(args.release_json), args.receipt.read_bytes())
        plan = {"proof": {"run": RUN, "head": HEAD, "tag": TAG,
                           "receipt_sha256": RECEIPT_SHA, "master_sha256": MASTER_SHA},
                "frames": frames}
        args.plan_out.write_text(json.dumps(plan, indent=2) + "\n")
        print(f"source PASS; frames={len(frames)}; OCR={proof['ocr_status']}; approval={proof['release_approval']}")
    elif args.check_runner:
        check_hosted_runner(args.capacity_out)
    elif args.extract:
        if not all((args.repo_json, args.run_json, args.receipt, args.release_json,
                    args.capacity_json, args.parts_dir, args.master_out, args.evidence_out)):
            parser.error("--extract requires repo/run/receipt/release/capacity/parts/master/evidence paths")
        guard_hosted_identity()
        receipt_bytes = args.receipt.read_bytes()
        proof, frame_plan = verify_source(load_json(args.repo_json), load_json(args.run_json),
                                          load_json(args.release_json), receipt_bytes)
        digest = verify_and_join_parts(args.parts_dir, args.master_out)
        if digest != MASTER_SHA:
            fail("Master identity changed before extraction")
        capacity_info = load_json(args.capacity_json)
        if capacity_info.get("scratch_free_bytes", 0) < MIN_FREE_BYTES:
            fail("Recorded runner scratch capacity is missing or below the 12 GiB minimum")
        result = extract(args.master_out, frame_plan, args.evidence_out, proof, digest, capacity_info)
        print(json.dumps({"png_count": result["unique_png_count"],
                          "png_bytes_total": result["png_bytes_total"],
                          "master_sha256": digest, "approval": result["release_approval"]}))
    else:
        parser.error("Choose --validate-source or --extract")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
