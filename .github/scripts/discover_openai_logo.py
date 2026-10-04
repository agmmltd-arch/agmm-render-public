#!/usr/bin/env python3
"""Discover a unique structurally suitable SVG from the official OpenAI ZIP.

Production access is restricted to the explicitly enabled public Linux Actions
job. The discovery receipt lists sanitized ZIP member names and metadata only;
SVG bytes are read only to inspect the root and viewBox, then the source builder
revalidates/extracts the unique member.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import platform
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

MAX_ARCHIVE_BYTES = 25_000_000
MAX_MEMBERS = 2_000
MAX_UNCOMPRESSED_BYTES = 80_000_000
MAX_SVG_BYTES = 1_000_000
SQUARE_MIN = 0.98
SQUARE_MAX = 1.02

class Refusal(Exception):
    pass

def require_hosted_linux() -> None:
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("S81_HOSTED_SOURCE_CAPTURE") != "1":
        raise Refusal("official brand ZIP inspection is restricted to the guarded Ubuntu GitHub Actions source-capture job")

def safe_member(name: str) -> str:
    if not name or any(ord(c) < 32 or ord(c) == 127 for c in name) or "\\" in name:
        raise Refusal("official package contains a member name that cannot be safely reported")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != name.rstrip("/"):
        raise Refusal("official package contains a non-canonical or unsafe member path")
    return name

def _viewbox_candidate(data: bytes) -> tuple[bool, dict]:
    if not data or len(data) > MAX_SVG_BYTES:
        return False, {"reason": "svg_outside_size_bound"}
    if b"<!doctype" in data.lower() or b"<!entity" in data.lower():
        return False, {"reason": "xml_declarations_refused"}
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return False, {"reason": "invalid_xml"}
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        return False, {"reason": "root_not_svg"}
    raw = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if not raw:
        return False, {"reason": "viewbox_missing"}
    try:
        values = [float(v) for v in re.split(r"[\s,]+", raw.strip())]
    except ValueError:
        return False, {"reason": "viewbox_invalid"}
    if len(values) != 4 or not all(math.isfinite(v) for v in values) or values[2] <= 0 or values[3] <= 0:
        return False, {"reason": "viewbox_invalid"}
    ratio = values[2] / values[3]
    is_square = SQUARE_MIN <= ratio <= SQUARE_MAX
    return is_square, {"reason": "square_viewbox" if is_square else "not_square_viewbox",
                       "view_box": values, "aspect_ratio": round(ratio, 6)}

def discover_bytes(data: bytes) -> dict:
    if not data or len(data) > MAX_ARCHIVE_BYTES:
        raise Refusal("official brand ZIP is empty or exceeds the 25 MB bound")
    try:
        zf = zipfile.ZipFile(__import__("io").BytesIO(data))
    except zipfile.BadZipFile:
        raise Refusal("official brand download is not a valid ZIP") from None
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise Refusal("official brand ZIP has too many members")
        seen: set[str] = set()
        total = 0
        members = []
        square_svgs = []
        for info in infos:
            name = safe_member(info.filename)
            if name in seen:
                raise Refusal("official brand ZIP contains duplicate member names")
            seen.add(name)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise Refusal("official brand ZIP contains a symbolic link")
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise Refusal("official brand ZIP exceeds the uncompressed inspection bound")
            is_dir = info.is_dir()
            row = {"name": name, "kind": "directory" if is_dir else "file", "bytes": info.file_size}
            members.append(row)
            if is_dir or not name.lower().endswith(".svg"):
                continue
            if info.file_size > MAX_SVG_BYTES:
                row["svg_candidate"] = "refused_size_bound"
                continue
            with zf.open(info) as stream:
                svg_data = stream.read(MAX_SVG_BYTES + 1)
            candidate, metadata = _viewbox_candidate(svg_data)
            row["svg_candidate"] = "square_svg" if candidate else "not_eligible"
            row["svg_metadata"] = metadata
            if candidate:
                square_svgs.append(name)
        status = "UNIQUE_SQUARE_SVG_DISCOVERED" if len(square_svgs) == 1 else "REFUSED_NO_UNIQUE_SQUARE_SVG"
        return {"kind": "s81_official_logo_zip_metadata_discovery", "status": status,
                "package_sha256": hashlib.sha256(data).hexdigest(), "package_bytes": len(data),
                "candidate_rule": {"source": "official OpenAI Logos 2025 ZIP", "required_root": "svg",
                                   "view_box_aspect_ratio": [SQUARE_MIN, SQUARE_MAX],
                                   "reason": "S81 candidate uses an OpenAI company-identification mark in a square image slot",
                                   "human_visual_review": "OPEN"},
                "selected_member": square_svgs[0] if len(square_svgs) == 1 else None,
                "eligible_members": square_svgs, "members": members,
                "rights": {"guidelines_url": "https://openai.com/brand/", "review": "OPEN",
                           "use": "unmodified company identification only; no endorsement or permission claim"}}

def discover_archive(path: Path) -> dict:
    require_hosted_linux()
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_ARCHIVE_BYTES:
            raise Refusal("official brand ZIP is empty or exceeds the 25 MB bound")
        return discover_bytes(path.read_bytes())
    except OSError:
        raise Refusal("official brand ZIP is unavailable to the hosted discovery step") from None

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        receipt = discover_archive(args.archive)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (Refusal, OSError, ValueError, zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        print(f"S81 logo discovery refusal: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
