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
    "hook-frame-zero", "portal-description", "openai-internal-evaluation", "unintended-actions-quote",
    "august-discovery", "september-email", "once-daily-monitoring",
    "albanese-response", "privacy-qualification", "lesson-route-fold", "cta-audit-link",
    "privacy-line-start", "privacy-qualification-settled", "cta-follow-start",
}


def png_rgb(path: Path, inspect_hero: bool = False) -> tuple[int, int, set[tuple[int, int, int]], int, int]:
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
    hero_ink_samples = 0
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
        # On the frame-zero hook only, count sparse 4px samples in the reserved
        # hero-title band. Navy grain cannot satisfy this high-contrast test.
        if inspect_hero and 175 <= y < 415:
            for px in range(0, width, 4):
                x = px * bpp
                rgb = (row[x], row[x+1], row[x+2])
                if min(rgb) >= 170 and max(rgb) - min(rgb) <= 90:
                    hero_ink_samples += 1
        prev = row
    return width, height, palette, nonpaper, hero_ink_samples


def validate_hook_source_text(source: str) -> None:
    marker = 'A.scenes["s81-evidence-route"] = function (ctx) {'
    if source.count(marker) != 1:
        raise ValueError("frame-zero hook source must define exactly one S81 scene")
    scene = source.split(marker, 1)[1]
    if "\n    var breach = world(" not in scene:
        raise ValueError("cannot isolate the actual S81 opening scene block")
    opening = scene.split("\n    var breach = world(", 1)[0]
    if re.search(r"enter\(tl,\s*hook,\s*0\s*,", opening):
        raise ValueError("frame-zero hook parent is hidden by a delayed entrance")
    if re.search(r"tl\.set\(hook,\s*\{\s*autoAlpha:\s*0\s*\},\s*0\)", opening):
        raise ValueError("frame-zero hook parent is hidden at time zero")
    if 'tl.set(hook, { autoAlpha: 1 }, 0);' not in opening:
        raise ValueError("frame-zero hook parent must be explicitly visible at time zero")
    required = (
        'bar(hook, "s81-title", "OPENAI AGENT\\nIN PORTAL");',
        'tl.fromTo(portal, { scaleY: .86, transformOrigin: "50% 100%" }',
        'tl.fromTo(hook.querySelector(".s81-title"), { y: 22, autoAlpha: 1 }',
        'tl.fromTo(hook.querySelector(".s81-mark"), { rotation: -7, scale: .92 }',
        'tl.to(hook, { autoAlpha: 0, duration: .22, ease: "power1.in" }, 8.38);',
    )
    missing = [snippet for snippet in required if snippet not in opening]
    if missing:
        raise ValueError(f"actual S81 opening timeline lacks visible-at-zero content or motion: {missing}")
    # Keep the approved opening visually present while its title, mark and portal move.
    for selector in ("portal", 'hook.querySelector(".s81-title")', 'hook.querySelector(".s81-mark")'):
        line = next((row for row in opening.splitlines() if f"tl.fromTo({selector}," in row), "")
        if not re.search(r",\s*0\);\s*$", line):
            raise ValueError(f"opening motion for {selector} must begin at timeline zero")
    title_rule = re.search(r"\.s81-title\{[^}]*font:700 (\d+)px", source)
    if not title_rule or int(title_rule.group(1)) < 120:
        raise ValueError("frame-zero hook title must use at least 120px type")


def validate_picture_source_text(source: str) -> None:
    """Static design gates for the exact S81 correction candidate source."""
    required = (
        ".s81-illustration-note{position:absolute;left:64px;right:64px;top:108px;",
        ".s81-credit{position:absolute;left:64px;right:64px;bottom:20px;height:220px;",
        ".ag2-card .row{background:",
        ".ag2-card .row .ag2-w{opacity:1!important;",
        'enter(tl, context, 18.40, 24.667',
        'enter(tl, guardian, 34.50, 37.753',
        'enter(tl, lesson, 46.60, 51.60',
        'document.createTextNode("The general Australian government email address ")',
        'el("strong", "", monitorquote, "“is monitored once a day.”");',
        'el("div", "s81-monthname", m3, "EMAIL NOTICE")',
        'el("div", "s81-file private", gate, "NON-\\nPUBLIC\\nFILES")',
        'var lessonEntryX = Math.min(24, 64 - 20);',
        'tl.fromTo(control1, { x: -lessonEntryX, autoAlpha: 1 }',
        'tl.fromTo(node, { autoAlpha: 1, x: x || 0, y: y || 0 }',
        'bottom:760px',
    )
    if 'el("div", "s81-file private", gate, "NON‑PUBLIC\\nFILES")' in source:
        raise ValueError("NON-PUBLIC must break at its hyphen, not inside the word")
    if 'el("div", "s81-monthname", m3, "NOTIFICATION")' in source:
        raise ValueError("notification heading must wrap between whole words")
    entry = re.search(r"var lessonEntryX = Math\.min\((\d+),\s*64\s*-\s*(\d+)\);", source)
    if not entry or int(entry.group(2)) < 20 or int(entry.group(1)) > 44:
        raise ValueError("lesson entrance must be statically bounded within the 64px safe inset")
    missing = [snippet for snippet in required if snippet not in source]
    if missing:
        raise ValueError(f"S81 source misses caption/header/subject-safe-zone correction: {missing}")
    if 'background:"+C.paper+"!important;color:"+C.ink+"!important' not in source:
        raise ValueError("S81 phrase captions must use the fixed high-contrast paper/ink palette")
    if 'el("div", "s81-monitorquote", guardian, "The general Australian government email address <strong>' in source:
        raise ValueError("Guardian quote must construct a real strong element, not display markup text")
    # All authored readable CSS text is 42px or larger, excluding the 124px hero rule.
    sizes = [int(value) for value in re.findall(r"font:700\s+(\d+)px", source)]
    if not sizes or min(sizes) < 42:
        raise ValueError(f"S81 text falls below the 42px floor: {min(sizes) if sizes else 'no text rules'}")
    # Story objects must end above the caption band; fixed y positions in this CSS
    # are guarded separately for the two known exceptions (opening route / CTA).
    for selector in ("s81-evidence", "s81-evaluation", "s81-statement", "s81-calendar", "s81-response", "s81-privacy", "s81-controls"):
        rule = re.search(rf"\.{selector}\{{[^}}]*bottom:(\d+)px", source)
        if not rule or int(rule.group(1)) < 700:
            raise ValueError(f"{selector} does not reserve the caption-safe lower band")


def verify_hook_source(path: Path) -> None:
    source = path.read_text()
    validate_hook_source_text(source)
    validate_picture_source_text(source)


def verify(evidence_path: Path, snapshot_log: Optional[Path] = None, scene_source: Optional[Path] = None) -> dict:
    if scene_source is None:
        raise ValueError("exact scene source is required for the frame-zero hook guard")
    verify_hook_source(scene_source)
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
        width, height, colors, nonpaper, hero_ink = png_rgb(image, inspect_hero=(name == "hook-frame-zero"))
        if (width, height) != (1080, 1920):
            raise ValueError(f"{name}: expected 1080x1920, got {width}x{height}")
        if len(colors) < 16 or nonpaper < 5000:
            raise ValueError(f"{name}: active frame appears blank (colors={len(colors)}, nonpaper_pixels={nonpaper})")
        if name == "hook-frame-zero" and hero_ink < 300:
            raise ValueError(f"{name}: no legible high-contrast hook subject in title band (samples={hero_ink})")
        checked.append({"name": name, "sha256": digest, "sampled_colors": len(colors), "nonpaper_pixels": nonpaper, "hero_ink_samples": hero_ink if name == "hook-frame-zero" else None})
    return {"kind": "s81_active_frame_content_guard", "status": "PASS", "snapshot_log_checked": log_checked, "checked": checked}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--snapshot-log", type=Path)
    parser.add_argument("--scene-source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.evidence, args.snapshot_log, args.scene_source)
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output: args.output.write_text(encoded)
    print(encoded, end="")


if __name__ == "__main__":
    main()
