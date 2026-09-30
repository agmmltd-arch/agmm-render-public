#!/usr/bin/env python3
"""Build an exact, capture-only review pack for a sealed AGMM short package."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import struct
import sys
from pathlib import Path, PurePosixPath

import render_short_package as short


HYPERFRAMES_VERSION = short.HYPERFRAMES_VERSION
CAPTURE_PLAN_VERSION = 1
SEAM_OFFSETS = (-0.04, 0.02, 0.06)
MAX_NAMED_CAPTURES = 40
MEDIA_SUFFIXES = {
    ".aac", ".avif", ".flac", ".gif", ".jpeg", ".jpg", ".m4a", ".mov",
    ".mp3", ".mp4", ".ogg", ".png", ".svg", ".wav", ".webm", ".webp",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SNAPSHOT_RE = re.compile(r"^frame-(\d+)-at-([0-9]+(?:\.[0-9]+)?)s\.png$")


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finite_number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise short.ContractError(f"{label} must be a number") from None
    if not math.isfinite(number):
        raise short.ContractError(f"{label} must be finite")
    return number


def media_identities(project: Path, parts: list[dict]) -> list[dict]:
    """Return the media rows already authenticated by each look's SHA manifest."""
    rows: list[dict] = []
    for look in sorted({part["look"] for part in parts}):
        short.validate_sha_file(project, look)
        look_root = project / look
        declared: dict[str, str] = {}
        for number, raw in enumerate((look_root / "SHA256SUMS.txt").read_text().splitlines(), 1):
            if not raw.strip():
                continue
            match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", raw)
            if not match:
                raise short.ContractError(f"{look}/SHA256SUMS.txt:{number} is malformed")
            name = match.group(2).strip()
            while name.startswith("./"):
                name = name[2:]
            rel = short.safe_relative(name, f"{look} media checksum path")
            if PurePosixPath(rel).suffix.lower() not in MEDIA_SUFFIXES:
                continue
            if rel in declared:
                raise short.ContractError(f"{look}/SHA256SUMS.txt repeats media path: {rel}")
            declared[rel] = match.group(1).lower()
        actual = sorted(
            path.relative_to(look_root).as_posix()
            for path in look_root.rglob("*")
            if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES
        )
        if set(actual) != set(declared):
            missing = sorted(set(actual) - set(declared))
            extra = sorted(set(declared) - set(actual))
            raise short.ContractError(
                f"{look} media manifest mismatch: unlisted={missing}, missing={extra}"
            )
        for rel in actual:
            target = look_root / rel
            rows.append({
                "path": f"{look}/{rel}",
                "sha256": declared[rel],
                "bytes": target.stat().st_size,
            })
    if not rows:
        raise short.ContractError("sealed package declares no image, audio or video media identities")
    return rows


def media_identity_sha256(rows: list[dict]) -> str:
    return sha256_bytes(canonical_json(rows))


def part_for_global(parts: list[dict], global_time: float) -> dict:
    for part in parts:
        if part["off"] <= global_time < part["off"] + part["dur"] - 1e-9:
            return part
    raise short.ContractError(f"capture time {global_time:.6f}s is outside the declared timeline")


def capture_row(*, name: str, kind: str, global_time: float, part: dict) -> dict:
    local = global_time - part["off"]
    return {
        "name": name,
        "kind": kind,
        "global": round(global_time, 6),
        "local": round(local, 6),
        "part_index": part["index"],
        "part_out": part["out"],
        "look": part["look"],
        "file": part["file"],
    }


def validate_capture_plan(plan: object, parsed: dict, *, source_sha256: str,
                          parts_sha256: str, media_sha256: str) -> dict:
    if not isinstance(plan, dict) or plan.get("version") != CAPTURE_PLAN_VERSION:
        raise short.ContractError(f"capture plan version must be {CAPTURE_PLAN_VERSION}")
    short_id = plan.get("short_id")
    if not isinstance(short_id, str) or not short.OUT_RE.fullmatch(short_id):
        raise short.ContractError("capture plan short_id is not a safe label")
    expected = {
        "source_sha256": source_sha256,
        "parts_sha256": parts_sha256,
        "media_identity_sha256": media_sha256,
    }
    for key, value in expected.items():
        if plan.get(key) != value:
            raise short.ContractError(f"capture plan {key} does not match the exact input")
    if plan.get("include_part_seams") is not True:
        raise short.ContractError("capture plan must include all part seams")
    requested = plan.get("captures")
    if not isinstance(requested, list) or not 1 <= len(requested) <= MAX_NAMED_CAPTURES:
        raise short.ContractError(f"capture plan must contain 1..{MAX_NAMED_CAPTURES} named captures")

    captures: list[dict] = []
    names: set[str] = set()
    for index, item in enumerate(requested):
        if not isinstance(item, dict):
            raise short.ContractError(f"capture {index} must be an object")
        name, kind = item.get("name"), item.get("kind")
        if not isinstance(name, str) or not short.OUT_RE.fullmatch(name):
            raise short.ContractError(f"capture {index} name is not a safe label")
        if name in names:
            raise short.ContractError(f"duplicate capture name: {name}")
        names.add(name)
        if kind not in {"beat", "transition"}:
            raise short.ContractError(f"capture {name} kind must be beat or transition")
        global_time = finite_number(item.get("global"), f"capture {name} global")
        local = finite_number(item.get("local"), f"capture {name} local")
        part = part_for_global(parsed["parts"], global_time)
        if item.get("look") != part["look"]:
            raise short.ContractError(
                f"capture {name} look is {item.get('look')!r}; global time belongs to {part['look']!r}"
            )
        actual_local = global_time - part["off"]
        if abs(local - actual_local) > 0.001:
            raise short.ContractError(
                f"capture {name} local {local:.6f}s does not match global-to-local {actual_local:.6f}s"
            )
        captures.append(capture_row(
            name=name, kind=kind, global_time=global_time, part=part,
        ))

    parts = parsed["parts"]
    for index in range(1, len(parts)):
        previous, following = parts[index - 1], parts[index]
        seam = following["off"]
        for offset, suffix in zip(SEAM_OFFSETS, ("m040", "p020", "p060")):
            global_time = seam + offset
            part = part_for_global(parts, global_time)
            name = f"seam-{previous['out']}-to-{following['out']}-{suffix}"
            if len(name) > 128 or not short.OUT_RE.fullmatch(name):
                raise short.ContractError(f"generated seam name is unsafe: {name}")
            if name in names:
                raise short.ContractError(f"capture plan collides with generated seam name: {name}")
            names.add(name)
            captures.append(capture_row(
                name=name, kind="part_seam", global_time=global_time, part=part,
            ))

    seen_times: set[tuple[str, int]] = set()
    for item in captures:
        key = (item["look"], round(item["local"] * 1_000_000))
        if key in seen_times:
            raise short.ContractError(
                f"duplicate capture timestamp in {item['look']}: {item['local']:.6f}s"
            )
        seen_times.add(key)
    captures.sort(key=lambda item: (item["global"], item["name"]))

    by_look = []
    for look in sorted({item["look"] for item in captures}, key=lambda value: min(
            item["global"] for item in captures if item["look"] == value)):
        subset = sorted(
            (item for item in captures if item["look"] == look),
            key=lambda item: (item["local"], item["name"]),
        )
        files = {item["file"] for item in subset}
        if len(files) != 1:
            raise short.ContractError(f"look {look} resolves to more than one composition file")
        by_look.append({
            "look": look,
            "file": next(iter(files)),
            "times_csv": ",".join(f"{item['local']:.6f}" for item in subset),
            "capture_count": len(subset),
            "captures": subset,
        })
    return {
        "version": CAPTURE_PLAN_VERSION,
        "short_id": short_id,
        "duration": parsed["duration"],
        "capture_count": len(captures),
        "captures": captures,
        "by_look": by_look,
    }


def prepare(*, source: Path, parts_path: Path, plan_path: Path, output: Path,
            source_sha256: str, parts_sha256: str, plan_sha256: str,
            expected_media_sha256: str) -> dict:
    source_hash = short.verify_hash(source, source_sha256, "source_sha256")
    parts_hash = short.verify_hash(parts_path, parts_sha256, "parts_sha256")
    plan_hash = short.verify_hash(plan_path, plan_sha256, "capture_plan_sha256")
    expected_media_sha256 = short.require_hash(
        expected_media_sha256, "media_identity_sha256"
    )
    output.mkdir(parents=True, exist_ok=True)
    project = output / "project"
    if project.exists():
        raise short.ContractError(f"refusing to overlay existing extraction directory: {project}")
    members = short.safe_extract(source, project)
    raw_parts = short.load_json(parts_path, "parts.json")
    parsed = short.validate_parts(raw_parts, project)
    if not isinstance(raw_parts, dict) or raw_parts.get("sha256") not in (None, source_hash):
        raise short.ContractError("parts.json package sha256 does not match exact source.tar.gz")
    if raw_parts.get("bytes") not in (None, source.stat().st_size):
        raise short.ContractError("parts.json package byte count does not match exact source.tar.gz")
    media = media_identities(project, parsed["parts"])
    media_hash = media_identity_sha256(media)
    if media_hash != expected_media_sha256:
        raise short.ContractError(
            f"media_identity_sha256 mismatch: expected {expected_media_sha256}, got {media_hash}"
        )
    plan = validate_capture_plan(
        short.load_json(plan_path, "capture-plan.json"), parsed,
        source_sha256=source_hash, parts_sha256=parts_hash, media_sha256=media_hash,
    )
    binding = {
        "source_sha256": source_hash,
        "parts_sha256": parts_hash,
        "capture_plan_sha256": plan_hash,
        "media_identity_sha256": media_hash,
    }
    manifest = {
        "kind": "agmm_short_capture_manifest",
        "technical_status": "INPUT_IDENTITY_PASS",
        "editorial_status": "NOT_REVIEWED",
        "publication_status": "NOT_REQUESTED",
        "hyperframes_version": HYPERFRAMES_VERSION,
        "binding": binding,
        **plan,
    }
    receipt = {
        "kind": "agmm_short_capture_input_receipt",
        "technical_status": "INPUT_IDENTITY_PASS",
        "editorial_status": "NOT_REVIEWED",
        "publication_status": "NOT_REQUESTED",
        "archive_members": len(members),
        "source_bytes": source.stat().st_size,
        "parts_bytes": parts_path.stat().st_size,
        "capture_plan_bytes": plan_path.stat().st_size,
        "media_identity_count": len(media),
        "part_count": len(parsed["parts"]),
        "capture_count": plan["capture_count"],
        "binding": binding,
    }
    write_json(output / "CAPTURE-MANIFEST.json", manifest)
    write_json(output / "INPUT-RECEIPT.json", receipt)
    write_json(output / "MEDIA-IDENTITIES.json", {
        "kind": "agmm_short_media_identities",
        "sha256": media_hash,
        "files": media,
    })
    return manifest


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise short.ContractError(f"snapshot is not a valid PNG header: {path.name}")
    return struct.unpack(">II", header[16:24])


def collect(*, manifest_path: Path, look: str, snapshots: Path, output: Path,
            log_path: Path | None = None) -> dict:
    manifest = short.load_json(manifest_path, "CAPTURE-MANIFEST.json")
    if not isinstance(manifest, dict) or manifest.get("kind") != "agmm_short_capture_manifest":
        raise short.ContractError("capture manifest has the wrong kind")
    rows = [row for row in manifest.get("by_look", []) if row.get("look") == look]
    if len(rows) != 1:
        raise short.ContractError(f"manifest must contain exactly one capture group for {look}")
    group = rows[0]
    expected = group["captures"]
    found = []
    for path in snapshots.glob("frame-*.png"):
        match = SNAPSHOT_RE.fullmatch(path.name)
        if not match:
            raise short.ContractError(f"unexpected snapshot filename: {path.name}")
        found.append((int(match.group(1)), float(match.group(2)), path))
    found.sort()
    if [row[0] for row in found] != list(range(len(expected))):
        raise short.ContractError("snapshot indices are incomplete or non-contiguous")
    if len(found) != len(expected):
        raise short.ContractError(
            f"{look} produced {len(found)} snapshots; expected {len(expected)}"
        )
    frames_dir = output / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    captures = []
    for point, (_, actual_time, source) in zip(expected, found):
        if abs(actual_time - point["local"]) > 0.001:
            raise short.ContractError(
                f"{look} snapshot time {actual_time:.6f}s does not match {point['local']:.6f}s"
            )
        width, height = png_dimensions(source)
        if (width, height) != (1080, 1920):
            raise short.ContractError(
                f"{source.name} is {width}x{height}; expected 1080x1920"
            )
        target = frames_dir / f"{point['name']}.png"
        shutil.copyfile(source, target)
        captures.append({
            **point,
            "file": f"frames/{target.name}",
            "sha256": short.sha256(target),
            "bytes": target.stat().st_size,
            "width": width,
            "height": height,
        })
    if log_path is not None and log_path.is_file():
        shutil.copyfile(log_path, output / "snapshot.log")
    receipt = {
        "kind": "agmm_short_capture_part_receipt",
        "technical_status": "CAPTURE_PASS",
        "editorial_status": "NOT_REVIEWED",
        "publication_status": "NOT_REQUESTED",
        "capture_route": f"hyperframes snapshot {HYPERFRAMES_VERSION}",
        "look": look,
        "binding": manifest["binding"],
        "captures": captures,
    }
    write_json(output / "CAPTURE-RECEIPT.json", receipt)
    return receipt


def bundle(*, manifest_path: Path, media_path: Path, captured: Path, output: Path) -> dict:
    manifest = short.load_json(manifest_path, "CAPTURE-MANIFEST.json")
    media = short.load_json(media_path, "MEDIA-IDENTITIES.json")
    if not isinstance(manifest, dict) or manifest.get("kind") != "agmm_short_capture_manifest":
        raise short.ContractError("capture manifest has the wrong kind")
    if not isinstance(media, dict) or media.get("sha256") != manifest["binding"]["media_identity_sha256"]:
        raise short.ContractError("media identities do not match the capture manifest")
    if output.exists() and any(output.iterdir()):
        raise short.ContractError(f"refusing to overlay nonempty bundle directory: {output}")
    (output / "frames").mkdir(parents=True, exist_ok=True)
    (output / "receipts").mkdir(parents=True, exist_ok=True)
    expected = {row["name"]: row for row in manifest["captures"]}
    collected: dict[str, dict] = {}
    for group in manifest["by_look"]:
        look = group["look"]
        source_root = captured / look
        receipt = short.load_json(source_root / "CAPTURE-RECEIPT.json", f"{look} receipt")
        if not isinstance(receipt, dict) or receipt.get("kind") != "agmm_short_capture_part_receipt":
            raise short.ContractError(f"{look} receipt has the wrong kind")
        if receipt.get("look") != look or receipt.get("binding") != manifest["binding"]:
            raise short.ContractError(f"{look} receipt identity does not match the manifest")
        for row in receipt.get("captures", []):
            name = row.get("name")
            if name not in expected or name in collected:
                raise short.ContractError(f"unexpected or duplicate capture in {look}: {name!r}")
            if any(row.get(key) != expected[name].get(key) for key in
                   ("kind", "global", "local", "look", "part_index", "part_out")):
                raise short.ContractError(f"capture metadata differs from manifest: {name}")
            source = source_root / row["file"]
            if not source.is_file() or short.sha256(source) != row.get("sha256"):
                raise short.ContractError(f"capture bytes differ from receipt: {name}")
            if png_dimensions(source) != (1080, 1920):
                raise short.ContractError(f"capture dimensions differ from contract: {name}")
            collected[name] = row
        shutil.copyfile(source_root / "CAPTURE-RECEIPT.json", output / "receipts" / f"{look}.json")
    if set(collected) != set(expected):
        missing = sorted(set(expected) - set(collected))
        raise short.ContractError(f"capture bundle is incomplete: {missing}")

    final_rows = []
    for index, point in enumerate(manifest["captures"], 1):
        source = captured / point["look"] / collected[point["name"]]["file"]
        target = output / "frames" / f"{index:02d}-{point['name']}.png"
        shutil.copyfile(source, target)
        final_rows.append({
            **point,
            "file": f"frames/{target.name}",
            "sha256": short.sha256(target),
            "bytes": target.stat().st_size,
            "width": 1080,
            "height": 1920,
        })
    write_json(output / "MEDIA-IDENTITIES.json", media)
    evidence = {
        "kind": "agmm_short_hosted_capture_evidence",
        "technical_status": "CAPTURE_PASS",
        "editorial_status": "NOT_REVIEWED",
        "publication_status": "NOT_REQUESTED",
        "full_video_render": "NOT_RUN",
        "full_video_decode": "NOT_RUN",
        "capture_route": f"hyperframes snapshot {HYPERFRAMES_VERSION}",
        "short_id": manifest["short_id"],
        "duration": manifest["duration"],
        "binding": manifest["binding"],
        "captures": final_rows,
    }
    write_json(output / "CAPTURE-EVIDENCE.json", evidence)
    checksum_rows = []
    for path in sorted((output / "frames").glob("*.png")):
        checksum_rows.append(f"{short.sha256(path)}  frames/{path.name}")
    checksum_rows.append(
        f"{short.sha256(output / 'MEDIA-IDENTITIES.json')}  MEDIA-IDENTITIES.json"
    )
    (output / "SHA256SUMS.txt").write_text("\n".join(checksum_rows) + "\n", encoding="utf-8")
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    for name in ("source", "parts", "plan", "output", "source-sha256", "parts-sha256",
                 "capture-plan-sha256", "media-identity-sha256"):
        prepare_parser.add_argument(f"--{name}", required=True)
    collect_parser = commands.add_parser("collect")
    for name in ("manifest", "look", "snapshots", "output"):
        collect_parser.add_argument(f"--{name}", required=True)
    collect_parser.add_argument("--log")
    bundle_parser = commands.add_parser("bundle")
    for name in ("manifest", "media-identities", "captured", "output"):
        bundle_parser.add_argument(f"--{name}", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "prepare":
            prepare(
                source=Path(args.source), parts_path=Path(args.parts), plan_path=Path(args.plan),
                output=Path(args.output), source_sha256=args.source_sha256,
                parts_sha256=args.parts_sha256, plan_sha256=args.capture_plan_sha256,
                expected_media_sha256=args.media_identity_sha256,
            )
        elif args.command == "collect":
            collect(
                manifest_path=Path(args.manifest), look=args.look,
                snapshots=Path(args.snapshots), output=Path(args.output),
                log_path=Path(args.log) if args.log else None,
            )
        else:
            bundle(
                manifest_path=Path(args.manifest), media_path=Path(args.media_identities),
                captured=Path(args.captured), output=Path(args.output),
            )
    except short.ContractError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
