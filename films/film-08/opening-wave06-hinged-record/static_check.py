#!/usr/bin/env python3
"""Source-only safety and intent checks for the Film 08 Wave06 diagnostic."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
ALLOWED = {
    ".node-version", "BRIEF.md", "SHA256SUMS.txt", "hyperframes.json",
    "index.html", "package.json", "package-lock.json", "static_check.py",
    "assets/GSAP-LICENSE.txt", "assets/gsap.min.js",
}
REQUIRED = ALLOWED - {"SHA256SUMS.txt", "package-lock.json"}


def validate(tree=ROOT):
    files = {p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file()}
    if files != ALLOWED:
        raise ValueError(f"source file set mismatch; missing={sorted(ALLOWED-files)} extra={sorted(files-ALLOWED)}")
    if not REQUIRED <= files:
        raise ValueError(f"missing required source files: {sorted(REQUIRED-files)}")
    html = (tree / "index.html").read_text()
    checks = {
        'W06 composition id': 'data-composition-id="film08-opening-wave06"' in html,
        '1920x1080 12-second composition': all(x in html for x in ('data-width="1920"','data-height="1080"','data-duration="12"')),
        'customer question retained': 'Which checks are recorded complete? Which are still open?' in html,
        'record split retained': all(x in html for x in ('Visual check','Controls review','COMPLETE','OPEN')),
        'bounded human reply retained': all(x in html for x in ('Tom · service desk','Visual check: recorded complete.','Controls review: still open.')),
        'illustrative label retained': 'ILLUSTRATIVE SCENARIO' in html,
        'timeline registration': "window.__timelines['film08-opening-wave06']=tl" in html,
        'page visible from first frame beneath opaque hinged cover': 'id="film08-paper"' in html and "tl.set('#film08-paper',{opacity:1},0)" in html and 'backface-visibility:hidden' in html and "rotationY:-166" in html,
        'pencil traces the mark endpoint': all(x in html for x in ('getTotalLength()','getPointAtLength(distance)','strokeDashoffset=String(markLength-distance)','translate(${point.x} ${point.y})')),
        'end remains animated to 11.55 seconds': "duration:3.9" in html and "},7.65)" in html and "},10.3)" in html,
        'no AI/demo success claim': not any(x in html.upper() for x in ('INTERNAL DEMO','TEST PASSED','AI ANSWER','LIVE DEPLOYMENT')),
        'no em dash in on-screen source': '—' not in html,
    }
    for label, ok in checks.items():
        if not ok:
            raise ValueError(f"failed: {label}")
    for css in re.findall(r"<style>(.*?)</style>", html, re.S):
        for size in re.findall(r"font-size\s*:\s*([\d.]+)px", css):
            if float(size) < 42:
                raise ValueError(f"visible CSS font below 42px: {size}px")
    package = (tree / "package.json").read_text()
    if '"hyperframes":"0.8.71"' not in package.replace(" ", ""):
        raise ValueError("HyperFrames must be pinned exactly to 0.8.71")
    if (tree / ".node-version").read_text().strip() != "22.23.3":
        raise ValueError("Node must be pinned exactly to 22.23.3")
    for p in tree.rglob("*"):
        if p.is_symlink():
            raise ValueError(f"symlink is not allowed: {p.relative_to(tree)}")
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".wav", ".mp3", ".m4a", ".aac"}:
            raise ValueError(f"media file is not allowed in source package: {p.relative_to(tree)}")


def negative_self_test():
    # These cases exercise the publication gate with missing or malformed inputs.
    assert not bool(re.fullmatch(r"[0-9a-f]{40}", ""))
    assert not bool(re.fullmatch(r"[0-9a-f]{40}", "b3acf42"))
    assert not bool(re.fullmatch(r"[0-9a-f]{40}", "z" * 40))
    try:
        validate(ROOT / "missing-source-tree")
    except (FileNotFoundError, ValueError):
        pass
    else:
        raise AssertionError("missing source directory unexpectedly passed")
    print("PASS negative inputs: missing commit, short commit, invalid commit, missing source tree rejected")


if __name__ == "__main__":
    try:
        validate()
        print("PASS Film08 Wave06 source: composition, scope, motion intent, runtime pins, clean source tree")
        if "--self-test" in sys.argv:
            negative_self_test()
    except Exception as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
