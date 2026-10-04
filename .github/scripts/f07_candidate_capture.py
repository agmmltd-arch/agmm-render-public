#!/usr/bin/env python3
"""Hosted-only F07 text-candidate verification and bounded source-frame collector."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re

REPO = "agmmltd-arch/agmm-render-public"
SOURCE_RELEASE = "F07-r4-actions-full-landscape-4k-20260930194517"
SOURCE_ASSET_ID = 601625680
SOURCE_BYTES = 43_650_580
SOURCE_SHA256 = "10394b58dad8f1e6131486edb2d9d310b82a923fef2ca6aea50f229cb165bfd7"
SOURCE_ASSET_NAME = "source.tar.gz"
OWNER_BASE_FILM_SHA256 = "24930d3fb1d62ce5de6fcfdd1c061054ab67c69de70e81f4fc4ebabd4da1148c"
PRIOR_TEXT_OVERLAY_RELEASE = "F07-code-overlay-6c3ec29f09a5e22eff2a3061ea737c50b8d02438a4877671096d82301076e2cc"
PRIOR_TEXT_OVERLAY_RELEASE_ID = 402696548
PRIOR_TEXT_OVERLAY_ASSET_ID = 608555583
PRIOR_TEXT_OVERLAY_SHA256 = "6c3ec29f09a5e22eff2a3061ea737c50b8d02438a4877671096d82301076e2cc"
FILM_JS_SHA256 = "cf6ddc29bf0e23ca50173773e43ee2d33ef3af8a1400f4ea3b375077adc3c3aa"
OVERLAY_FILES = {
    "film/film.js": "film/film.js",
    "film/film.css": "film/film.css",
    "film/sets_studio.js": "film/sets_studio.js",
}
EXPECTED_SOURCE_HASHES = {
    "film/film.js": "cf6ddc29bf0e23ca50173773e43ee2d33ef3af8a1400f4ea3b375077adc3c3aa",
    "film/film.css": "0d17eea12ed4ecac45b5207c35939334549ae970fe047b5e9fb3da9b4435fa07",
    "film/sets_studio.js": "988a0d98b5eb71c3bac0777ee5b02a161ef9e744d7c8bb0e3bcff40385ddea2c",
}
CAPTURES = [
    {"name":"investment_1b","composition_time":239.2667,"film_time":245.250},
    {"name":"investment_card_full","composition_time":239.4167,"film_time":245.400},
    {"name":"investment_card_during_phrase","composition_time":241.0000,"film_time":246.983},
    {"name":"investment_card_outro","composition_time":241.9167,"film_time":247.900},
    {"name":"bridge_which_valued","composition_time":242.6167,"film_time":248.600},
    {"name":"valuation_8_65","composition_time":244.2867,"film_time":250.270},
    {"name":"valuation_seam_pre_1f","composition_time":244.2667,"film_time":250.250},
    {"name":"valuation_seam_exact","composition_time":244.3000,"film_time":250.283},
    {"name":"valuation_seam_post_1f","composition_time":244.3333,"film_time":250.317},
    {"name":"valuation_billion","composition_time":245.7167,"film_time":251.700},
    {"name":"valuation_card_outro","composition_time":246.1167,"film_time":252.100},
    {"name":"next_shot_pre_cut","composition_time":246.8997,"film_time":252.883},
]
SNAPSHOT_RE = re.compile(r"^frame-(\d+)-at-([0-9]+(?:\.[0-9]+)?)s\.png$")
# HyperFrames 0.8.71 writes these native review aids beside requested frames.
# Accept only the observed basename set; the collector never copies or hashes
# these auxiliaries into the public review branch.
SNAPSHOT_AUXILIARY_FILES = {"contact-sheet.jpg", "contact-sheet-1.jpg", "contact-sheet-2.jpg"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"
MAX_CAPTURE_BYTES = 10_000_000
MAX_CAPTURE_TOTAL_BYTES = 40_000_000


def hosted_guard() -> None:
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("hosted Linux GitHub Actions required before file/archive IO")
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise RuntimeError("unexpected repository before file/archive IO")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_regular(root: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise ValueError(f"unsafe path: {relative}")
    path = root.joinpath(*rel.parts)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected regular file: {relative}")
    if root.resolve() not in path.resolve().parents:
        raise ValueError(f"path escapes root: {relative}")
    return path


def parse_manifest(path: Path) -> dict[str, str]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})\s+(film/film\.js|film/film\.css|film/sets_studio\.js)", line)
        if not match or match.group(2) in rows:
            raise ValueError("overlay manifest is malformed or contains duplicate/unapproved paths")
        rows[match.group(2)] = match.group(1)
    if set(rows) != set(OVERLAY_FILES):
        raise ValueError("overlay manifest does not bind exactly the three approved film files")
    return rows


def validate_plan(plan: dict) -> list[dict]:
    if plan.get("schema") != "f07-source-composition-capture-plan-v2":
        raise ValueError("capture plan schema mismatch")
    if plan.get("source_asset_sha256") != SOURCE_SHA256:
        raise ValueError("capture plan is not bound to the exact sealed parent")
    if plan.get("source_release") != SOURCE_RELEASE or plan.get("source_asset_id") != SOURCE_ASSET_ID:
        raise ValueError("capture plan is not bound to the exact parent release and asset")
    if plan.get("overlay_film_js_sha256") != FILM_JS_SHA256:
        raise ValueError("capture plan is not bound to the verified current film.js")
    if plan.get("overlay_candidate_sha256") != "d2fdaf282e233a9d9691a11b216361b108dff7228a9dcbd0459b29649fb01962":
        raise ValueError("capture plan is not bound to this text-only candidate overlay provenance")
    if plan.get("capture_class") != "source_composition_not_final_master":
        raise ValueError("source snapshots may not be represented as final-master review")
    rows = plan.get("captures")
    if rows != CAPTURES:
        raise ValueError("capture times differ from the verified composition-to-film clock plan")
    for row in rows:
        if abs((row["composition_time"] + 5.9833) - row["film_time"]) > 0.0005:
            raise ValueError("film-clock time does not invert the verified current warp mapping")
    return rows


def verify_candidate(candidate_root: Path, receipt_path: Path, parent_release_path: Path) -> dict:
    """Verify text overlay bytes and their parent release metadata; no archive is claimed."""
    hosted_guard()
    expected_receipt_path = safe_regular(candidate_root, "candidate-source-receipt.json")
    if receipt_path.resolve() != expected_receipt_path.resolve():
        raise ValueError("candidate receipt must be the exact regular file inside candidate root")
    receipt = json.loads(expected_receipt_path.read_text(encoding="utf-8"))
    if (receipt.get("schema") != "f07-overlay-candidate-text-provenance-v1"
            or receipt.get("kind") != "source-candidate-overlay-text-only"
            or receipt.get("candidate_status") != "ISOLATED_NOT_ADOPTED"
            or receipt.get("capture_class") != "source_composition_not_final_master"
            or receipt.get("approval") != "NOT_GRANTED"
            or receipt.get("archive_release") is not None
            or receipt.get("published_overlay_archive_identity") is not None):
        raise ValueError("candidate receipt is not honest text-only provenance")
    lineage = receipt.get("candidate_lineage", {})
    if (lineage.get("owner_base_film_js_sha256") != OWNER_BASE_FILM_SHA256
            or lineage.get("candidate_film_js_sha256") != FILM_JS_SHA256
            or lineage.get("change") != "Restore default document fade to 0.12s; keep the genuine source headline as one full-cut card across the two valuation shots."):
        raise ValueError("candidate receipt does not bind the reviewed owner-base to candidate change")
    prior = receipt.get("unchanged_text_source", {})
    if (prior.get("release") != PRIOR_TEXT_OVERLAY_RELEASE
            or prior.get("release_id") != PRIOR_TEXT_OVERLAY_RELEASE_ID
            or prior.get("asset_id") != PRIOR_TEXT_OVERLAY_ASSET_ID
            or prior.get("asset_sha256") != PRIOR_TEXT_OVERLAY_SHA256):
        raise ValueError("unchanged film.css/sets_studio.js lineage differs from the verified prior text overlay")
    expected_parent = {"release": SOURCE_RELEASE, "asset_id": SOURCE_ASSET_ID,
                       "asset_name": SOURCE_ASSET_NAME, "bytes": SOURCE_BYTES, "sha256": SOURCE_SHA256}
    if any(receipt.get("parent_source", {}).get(k) != v for k, v in expected_parent.items()):
        raise ValueError("candidate receipt does not bind the exact sealed parent source")
    parent_release = json.loads(parent_release_path.read_text(encoding="utf-8"))
    parent_asset = next((a for a in parent_release.get("assets", []) if a.get("id") == SOURCE_ASSET_ID), None)
    if (parent_release.get("tag_name") != SOURCE_RELEASE or parent_release.get("draft") is not False
            or not parent_asset or parent_asset.get("name") != SOURCE_ASSET_NAME
            or parent_asset.get("state") != "uploaded" or parent_asset.get("size") != SOURCE_BYTES
            or parent_asset.get("digest") != "sha256:" + SOURCE_SHA256
            or not any(a.get("id") == SOURCE_ASSET_ID and a.get("name") == SOURCE_ASSET_NAME
                       and a.get("size") == SOURCE_BYTES and a.get("digest") == "sha256:" + SOURCE_SHA256
                       for a in parent_release.get("assets", []))):
        raise ValueError("parent release metadata does not authenticate the exact source asset")
    expected_names = set(OVERLAY_FILES.values()) | {"film-overlay.sha256", "candidate-source-receipt.json"}
    if any(p.is_symlink() for p in candidate_root.rglob("*")):
        raise ValueError("candidate text overlay contains a symlink")
    found = {p.relative_to(candidate_root).as_posix() for p in candidate_root.rglob("*") if p.is_file()}
    if found != expected_names:
        raise ValueError("candidate overlay has missing or unexpected files")
    manifest = parse_manifest(safe_regular(candidate_root, "film-overlay.sha256"))
    rows = {}
    for name in OVERLAY_FILES:
        data = safe_regular(candidate_root, name).read_bytes()
        row = {"bytes": len(data), "sha256": sha256(data)}
        if manifest.get(name) != row["sha256"] or receipt.get("files", {}).get(name) != row:
            raise ValueError("candidate file differs from both its checksum manifest and receipt: " + name)
        if row["sha256"] != EXPECTED_SOURCE_HASHES[name]:
            raise ValueError("candidate source hash differs from the reviewed exact text: " + name)
        rows[name] = row
    canonical = json.dumps({name: rows[name] for name in sorted(rows)}, sort_keys=True, separators=(",", ":")).encode()
    candidate_hash = sha256(canonical)
    if receipt.get("candidate_sha256") != candidate_hash:
        raise ValueError("candidate composite text hash does not match the receipt")
    return {"candidate_sha256": candidate_hash, "files": rows,
            "candidate_receipt_sha256": sha256(expected_receipt_path.read_bytes()),
            "parent_release_id": parent_release.get("id"), "parent_asset_id": SOURCE_ASSET_ID}


def collect_snapshots(snapshot_dir: Path, plan_path: Path, candidate_root: Path,
                      candidate_receipt_path: Path, parent_release_path: Path, output_dir: Path) -> dict:
    hosted_guard()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    rows = validate_plan(plan)
    candidate = verify_candidate(candidate_root, candidate_receipt_path, parent_release_path)
    if plan.get("overlay_candidate_sha256") != candidate["candidate_sha256"]:
        raise ValueError("capture plan and text candidate overlay hashes differ")
    by_time = {f"{row['film_time']:.3f}": row for row in rows}
    entries = list(snapshot_dir.iterdir())
    if any(p.is_symlink() or not p.is_file() for p in entries):
        raise ValueError("snapshot folder contains a symlink or non-regular file")
    files = [p for p in entries if p.name not in SNAPSHOT_AUXILIARY_FILES]
    if any(p.suffix.lower() != ".png" for p in files):
        raise ValueError("snapshot folder contains a non-PNG/unapproved file")
    if len(files) != len(rows):
        raise ValueError("snapshot set is symlinked or differs from the exact capture plan")
    parsed = {}
    for path in files:
        match = SNAPSHOT_RE.fullmatch(path.name)
        if not match:
            raise ValueError("unexpected HyperFrames snapshot name")
        timestamp = f"{float(match.group(2)):.3f}"
        if timestamp not in by_time or timestamp in parsed:
            raise ValueError("snapshot timestamp is missing, duplicate or outside the plan")
        data = path.read_bytes()
        if len(data) < 45 or len(data) > MAX_CAPTURE_BYTES or not data.startswith(PNG_SIGNATURE) or not data.endswith(PNG_IEND):
            raise ValueError("snapshot is not a PNG")
        width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if (width, height) != (1920, 1080):
            raise ValueError("source snapshot dimensions differ from the film composition")
        parsed[timestamp] = (path, data)
    if set(parsed) != set(by_time):
        raise ValueError("not all exact planned timestamps were captured")
    if sum(len(data) for _, data in parsed.values()) > MAX_CAPTURE_TOTAL_BYTES:
        raise ValueError("snapshot pack exceeds bounded public review size")
    output_dir.mkdir(parents=True, exist_ok=False)
    frame_dir = output_dir / "frames"
    frame_dir.mkdir()
    (output_dir / "CANDIDATE-SOURCE-RECEIPT.json").write_bytes(candidate_receipt_path.read_bytes())
    frame_receipts = []
    for time in sorted(parsed, key=float):
        row = by_time[time]
        source_path, data = parsed[time]
        dest = frame_dir / f"{row['name']}.png"
        dest.write_bytes(data)
        frame_receipts.append({"name":row["name"],"path":f"frames/{dest.name}",
            "composition_time":row["composition_time"],"film_time":row["film_time"],
            "bytes":len(data),"sha256":sha256(data)})
    receipt = {"kind":"f07-source-composition-review-capture","source_release":SOURCE_RELEASE,
        "source_release_id":candidate["parent_release_id"],"source_asset_id":SOURCE_ASSET_ID,
        "source_sha256":SOURCE_SHA256,"capture_class":"source_composition_not_final_master",
        "overlay_candidate_sha256":candidate["candidate_sha256"],
        "candidate_receipt_sha256":candidate["candidate_receipt_sha256"],
        "overlay_files":candidate["files"],"overlay_archive_release":None,
        "editorial_status":"NOT_REVIEWED","release_approval":"NOT_GRANTED",
        "frames":frame_receipts}
    (output_dir / "CAPTURE-RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    checks = [f"{r['sha256']}  {r['path']}" for r in frame_receipts]
    checks.append(f"{candidate['candidate_receipt_sha256']}  CANDIDATE-SOURCE-RECEIPT.json")
    checks.append(f"{sha256((output_dir/'CAPTURE-RECEIPT.json').read_bytes())}  CAPTURE-RECEIPT.json")
    (output_dir / "SHA256SUMS.txt").write_text("\n".join(checks)+"\n", encoding="utf-8")
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("--snapshots", type=Path, required=True)
    collect.add_argument("--plan", type=Path, required=True)
    collect.add_argument("--candidate-root", type=Path, required=True)
    collect.add_argument("--candidate-receipt", type=Path, required=True)
    collect.add_argument("--parent-release", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify-candidate")
    verify.add_argument("--candidate-root", type=Path, required=True)
    verify.add_argument("--candidate-receipt", type=Path, required=True)
    verify.add_argument("--parent-release", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "verify-candidate":
        receipt = verify_candidate(args.candidate_root, args.candidate_receipt, args.parent_release)
    else:
        receipt = collect_snapshots(args.snapshots, args.plan, args.candidate_root,
                                    args.candidate_receipt, args.parent_release, args.output)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
