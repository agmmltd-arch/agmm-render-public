#!/usr/bin/env python3
"""Hosted-only F07 code-overlay packaging and bounded source-frame receipt helper."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import tarfile

REPO = "agmmltd-arch/agmm-render-public"
BASE_COMMIT = "5e511639891bceae531e0fcb0d10866f42edb414"
SOURCE_RELEASE = "F07-r4-actions-full-landscape-4k-20260930194517"
SOURCE_ASSET_ID = 601625680
SOURCE_BYTES = 43_650_580
SOURCE_SHA256 = "10394b58dad8f1e6131486edb2d9d310b82a923fef2ca6aea50f229cb165bfd7"
FILM_JS_SHA256 = "338774796521aafe7f784441d0a07dac7e1ed9486985483d3f6ab8324708e8b1"
OVERLAY_FILES = {
    "film/film.js": "film/film.js",
    "film/film.css": "film/film.css",
    "film/sets_studio.js": "film/sets_studio.js",
}
EXPECTED_SOURCE_HASHES = {
    "film/film.js": "338774796521aafe7f784441d0a07dac7e1ed9486985483d3f6ab8324708e8b1",
    "film/film.css": "0d17eea12ed4ecac45b5207c35939334549ae970fe047b5e9fb3da9b4435fa07",
    "film/sets_studio.js": "988a0d98b5eb71c3bac0777ee5b02a161ef9e744d7c8bb0e3bcff40385ddea2c",
}
HELPER_FILES = {
    ".github/scripts/assemble_verify.py",
    ".github/scripts/run_existing_ocr_check.py",
    "qa/gate.py",
    "kit/tools/frame_check.py",
    "kit/tools/ocr_vision.swift",
    "kit/platforms/platforms.py",
    "kit/platforms/frames.json",
}
ALLOWED_MEMBERS = set(OVERLAY_FILES) | HELPER_FILES | {"film-overlay.sha256"}
CAPTURES = [
    {"name":"investment_1b","composition_time":239.2667,"film_time":245.250},
    {"name":"investment_card_full","composition_time":239.4167,"film_time":245.400},
    {"name":"investment_card_during_phrase","composition_time":241.0000,"film_time":246.983},
    {"name":"investment_card_outro","composition_time":241.9167,"film_time":247.900},
    {"name":"bridge_which_valued","composition_time":242.6167,"film_time":248.600},
    {"name":"valuation_8_65","composition_time":244.2867,"film_time":250.270},
    {"name":"valuation_billion","composition_time":245.7167,"film_time":251.700},
    {"name":"valuation_card_outro","composition_time":246.1167,"film_time":252.100},
    {"name":"next_shot","composition_time":246.9000,"film_time":252.883},
]
SNAPSHOT_RE = re.compile(r"^frame-(\d+)-at-([0-9]+(?:\.[0-9]+)?)s\.png$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"
MAX_OVERLAY_FILE_BYTES = 2_000_000
MAX_OVERLAY_TOTAL_BYTES = 8_000_000
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


def canonical_tar(members: dict[str, bytes], output: Path) -> str:
    if set(members) != ALLOWED_MEMBERS:
        raise ValueError("overlay archive member set differs from the existing consumer's 11-file allowlist")
    if any(len(body) > MAX_OVERLAY_FILE_BYTES for body in members.values()):
        raise ValueError("overlay archive contains a file over the existing consumer's per-file limit")
    if sum(map(len, members.values())) > MAX_OVERLAY_TOTAL_BYTES:
        raise ValueError("overlay archive exceeds the existing consumer's expanded-size limit")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for name in sorted(members):
                    if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                        raise ValueError("unsafe archive path")
                    body = members[name]
                    info = tarfile.TarInfo(name)
                    info.size = len(body)
                    info.mode = 0o644
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    import io
                    tar.addfile(info, io.BytesIO(body))
    return sha256(output.read_bytes())


def build_overlay(source_root: Path, helper_root: Path, output: Path) -> dict:
    hosted_guard()
    if any(path.is_symlink() for path in source_root.rglob("*")):
        raise ValueError("overlay source contains a symlink")
    expected_source_names = set(OVERLAY_FILES.values()) | {"film-overlay.sha256"}
    found = {p.relative_to(source_root).as_posix() for p in source_root.rglob("*") if p.is_file()}
    if found != expected_source_names:
        raise ValueError("overlay source directory must contain exactly the three files and checksum manifest")
    manifest = parse_manifest(safe_regular(source_root, "film-overlay.sha256"))
    members = {}
    source_rows = {}
    for archive_name, source_name in OVERLAY_FILES.items():
        data = safe_regular(source_root, source_name).read_bytes()
        if sha256(data) != manifest[archive_name] or manifest[archive_name] != EXPECTED_SOURCE_HASHES[archive_name]:
            raise ValueError(f"overlay source does not match manifest: {archive_name}")
        members[archive_name] = data
        source_rows[archive_name] = {"sha256": sha256(data), "bytes": len(data)}
    members["film-overlay.sha256"] = safe_regular(source_root, "film-overlay.sha256").read_bytes()
    for name in HELPER_FILES:
        members[name] = safe_regular(helper_root, name).read_bytes()
    digest = canonical_tar(members, output)
    return {"kind":"f07-code-only-qa-overlay","archive_sha256":digest,
            "archive_bytes":output.stat().st_size,"member_names":sorted(members),
            "source_files":source_rows,"parent_release":SOURCE_RELEASE,
            "parent_source_sha256":SOURCE_SHA256,
            "scope":"film.js/css/sets_studio.js and existing QA helper text only; parent assets untouched"}


def validate_plan(plan: dict) -> list[dict]:
    if plan.get("schema") != "f07-source-composition-capture-plan-v1":
        raise ValueError("capture plan schema mismatch")
    if plan.get("source_asset_sha256") != SOURCE_SHA256:
        raise ValueError("capture plan is not bound to the exact sealed parent")
    if plan.get("overlay_film_js_sha256") != FILM_JS_SHA256:
        raise ValueError("capture plan is not bound to the verified current film.js")
    if plan.get("capture_class") != "source_composition_not_final_master":
        raise ValueError("source snapshots may not be represented as final-master review")
    rows = plan.get("captures")
    if rows != CAPTURES:
        raise ValueError("capture times differ from the verified composition-to-film clock plan")
    for row in rows:
        if abs((row["composition_time"] + 5.9833) - row["film_time"]) > 0.0005:
            raise ValueError("film-clock time does not invert the verified current warp mapping")
    return rows


def collect_snapshots(snapshot_dir: Path, plan_path: Path, overlay_release_path: Path, output_dir: Path) -> dict:
    hosted_guard()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    rows = validate_plan(plan)
    overlay_release = json.loads(overlay_release_path.read_text(encoding="utf-8"))
    overlay_asset = next((a for a in overlay_release.get("assets", [])
                          if a.get("name") == "f07-qa-overlay.tar.gz"), None)
    if (not overlay_asset or overlay_asset.get("digest") != "sha256:" + overlay_release.get("overlay_sha256", "")
            or overlay_asset.get("id") != overlay_release.get("asset_id")
            or overlay_asset.get("size") != overlay_release.get("asset_bytes")):
        raise ValueError("overlay release receipt does not bind the published archive asset")
    by_time = {f"{row['film_time']:.3f}": row for row in rows}
    entries = list(snapshot_dir.iterdir())
    if any(p.is_symlink() or not p.is_file() or p.suffix.lower() != ".png" for p in entries):
        raise ValueError("snapshot folder contains a symlink or a non-PNG/unapproved file")
    files = entries
    if len(files) != len(rows):
        raise ValueError("snapshot set is symlinked or differs from the exact nine-frame plan")
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
        "source_sha256":SOURCE_SHA256,"capture_class":"source_composition_not_final_master",
        "overlay_release_tag":overlay_release.get("tag_name"),
        "overlay_release_asset_id":overlay_asset["id"],
        "overlay_release_asset_bytes":overlay_asset["size"],
        "overlay_sha256":overlay_release["overlay_sha256"],
        "github_immutable_release":overlay_release.get("immutable"),
        "repo_immutable_releases_enabled":overlay_release.get("repo_immutable_releases_enabled"),
        "editorial_status":"NOT_REVIEWED","release_approval":"NOT_GRANTED",
        "frames":frame_receipts}
    (output_dir / "CAPTURE-RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    checks = [f"{r['sha256']}  {r['path']}" for r in frame_receipts]
    checks.append(f"{sha256((output_dir/'CAPTURE-RECEIPT.json').read_bytes())}  CAPTURE-RECEIPT.json")
    (output_dir / "SHA256SUMS.txt").write_text("\n".join(checks)+"\n", encoding="utf-8")
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pack = sub.add_parser("package")
    pack.add_argument("--source-root", type=Path, required=True)
    pack.add_argument("--helper-root", type=Path, required=True)
    pack.add_argument("--output", type=Path, required=True)
    pack.add_argument("--receipt", type=Path, required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("--snapshots", type=Path, required=True)
    collect.add_argument("--plan", type=Path, required=True)
    collect.add_argument("--overlay-release", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "package":
        receipt = build_overlay(args.source_root, args.helper_root, args.output)
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    else:
        receipt = collect_snapshots(args.snapshots, args.plan, args.overlay_release, args.output)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
