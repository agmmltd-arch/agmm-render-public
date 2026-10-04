#!/usr/bin/env python3
"""Reject blank or byte-identical active S81 source captures using stdlib PNG decoding."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path
from typing import Optional

ACTIVE = {
    "portal-description", "openai-internal-evaluation", "unintended-actions-quote",
    "august-discovery", "september-email", "once-daily-monitoring",
    "albanese-response", "privacy-qualification", "lesson-route-fold", "cta-audit-link",
}


def png_rgb(path: Path) -> tuple[int, int, set[tuple[int, int, int]], int]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"{path.name}: not a PNG")
    i = 8
    width = height = color = depth = interlace = None
    compressed = bytearray()
    while i < len(data):
        length = struct.unpack(">I", data[i:i+4])[0]
        kind = data[i+4:i+8]
        chunk = data[i+8:i+8+length]
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"IDAT":
            compressed.extend(chunk)
        elif kind == b"IEND":
            break
        i += 12 + length
    if not width or not height or depth != 8 or color not in (2, 6) or interlace != 0:
        raise ValueError(f"{path.name}: unsupported PNG encoding")
    bpp = 3 if color == 2 else 4
    stride = width * bpp
    raw = zlib.decompress(compressed)
    if len(raw) != (stride + 1) * height:
        raise ValueError(f"{path.name}: PNG pixel payload size mismatch")
    prev = bytearray(stride)
    palette: set[tuple[int, int, int]] = set()
    nonpaper = 0
    for y in range(height):
        base = y * (stride + 1)
        filt = raw[base]
        row = bytearray(raw[base+1:base+1+stride])
        for x in range(stride):
            a = row[x-bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x-bpp] if x >= bpp else 0
            if filt == 1: row[x] = (row[x] + a) & 255
            elif filt == 2: row[x] = (row[x] + b) & 255
            elif filt == 3: row[x] = (row[x] + ((a+b)//2)) & 255
            elif filt == 4:
                p = a + b - c
                pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
                row[x] = (row[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            elif filt != 0: raise ValueError(f"{path.name}: invalid PNG filter {filt}")
        # Seven-pixel sampling is sufficient for a blank-frame gate and bounds
        # hosted CPU time for ten full-resolution stills.
        sample_step = bpp * 7
        for x in range(0, stride, sample_step):
            rgb = (row[x], row[x+1], row[x+2])
            if len(palette) < 128: palette.add(rgb)
            if min(rgb) < 242: nonpaper += 7
        prev = row
    return width, height, palette, nonpaper


def verify(evidence_path: Path, snapshot_log: Optional[Path] = None) -> dict:
    evidence = json.loads(evidence_path.read_text())
    rows = {row.get("name"): row for row in evidence.get("captures", [])}
    missing = sorted(ACTIVE - rows.keys())
    if missing:
        raise ValueError(f"active source captures missing: {missing}")
    log_checked = False
    if snapshot_log:
        log = snapshot_log.read_text(errors="replace")
        fatal = re.search(r"unknown component|scene.{0,40}(?:not found|registration failed)|uncaught\s+(?:type|reference)?\s*error", log, re.I)
        if fatal:
            raise ValueError(f"snapshot log reports scene/runtime failure: {fatal.group(0)}")
        log_checked = True
    digests = set()
    checked = []
    base = evidence_path.parent
    for name in sorted(ACTIVE):
        row = rows[name]
        image = base / row["file"]
        if not image.is_file() or image.is_symlink():
            raise ValueError(f"{name}: capture file missing or symlinked")
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        if digest != row.get("sha256"):
            raise ValueError(f"{name}: PNG digest differs from capture evidence")
        if digest in digests:
            raise ValueError(f"{name}: active captures are byte-identical")
        digests.add(digest)
        width, height, colors, nonpaper = png_rgb(image)
        if (width, height) != (1080, 1920):
            raise ValueError(f"{name}: expected 1080x1920, got {width}x{height}")
        if len(colors) < 16 or nonpaper < 5000:
            raise ValueError(f"{name}: active frame appears blank (colors={len(colors)}, nonpaper_pixels={nonpaper})")
        checked.append({"name": name, "sha256": digest, "sampled_colors": len(colors), "nonpaper_pixels": nonpaper})
    return {"kind": "s81_active_frame_content_guard", "status": "PASS", "snapshot_log_checked": log_checked, "checked": checked}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--snapshot-log", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.evidence, args.snapshot_log)
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output: args.output.write_text(encoded)
    print(encoded, end="")


if __name__ == "__main__":
    main()
