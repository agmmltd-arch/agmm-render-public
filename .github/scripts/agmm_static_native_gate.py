#!/usr/bin/env python3
"""
gate.py -- the hard QA gate every AGMM V2 video must pass before a human sees it.

Usage:
  python3 gate.py <video.mp4> --script <script.txt> [--captions <captions.srt|.vtt|.json>]
                   [--onscreen <onscreen-text.json>] [--kind short|long] --out <dir>
                   [--compare-dir <dir>] [--window 10] [--register]
                   [--look <name>] [--platform <name>] [--bed <id>] [--format <name>]

Runs 10 checks (text lints, OCR lint, static-hold detector, loudness, hook, CTA, format,
contact sheets, Gemini critic, sameness-vs-approved), writes <dir>/GATE.json and
<dir>/GATE.md, and exits non-zero if any check FAILs.

Laptop safety (BRIEF-COMMON.md): one ffmpeg process at a time, all prefixed `nice -n 15`
with `-threads 2`, frame grabs at low res, no local Whisper/torch, no HyperFrames renders.
"""
import argparse
import base64
import datetime
import difflib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

try:
    import numpy as np
except ImportError:
    sys.exit("numpy is required (present on this box at /usr/bin/python3 -> confirm with "
              "`python3 -c \"import numpy\"`)")

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Thresholds (documented here, not buried) -----------------------------------
STATIC_DIFF_PCT_THRESHOLD = 0.4     # % of dynamic range; below this a frame-pair is "static"
STATIC_EXCEPTION_MIN_DRIFT_PCT = 1.5  # a listed read-beat must still move this much start-to-end (28 Sep)
STATIC_SAMPLE_FPS = 10              # decode rate for the static-hold detector
STATIC_SAMPLE_WIDTH = 320           # decode width for the static-hold detector
STATIC_MAX_SPAN = {"short": 1.5, "long": 2.5}   # seconds; FAIL above this

LUFS_TARGET = -14.0
LUFS_TOLERANCE = 1.0                # +/-1 LU
TRUE_PEAK_MAX_DBTP = -1.0
SILENCE_MAX_S = 1.0                 # audio may not be silent longer than this...
SILENCE_TAIL_EXCLUDE_S = 0.5        # ...except inside the last 0.5s of the video
SILENCE_NOISE_DB = "-30dB"

HOOK_WINDOW_S = 2.0
HOOK_SPEECH_MAX_START_S = 0.6

CTA_WINDOW_S = 8.0

SHORT_RES = (1080, 1920)
LONG_RES = (1920, 1080)
SHORT_DUR_PASS = (30, 60)
SHORT_DUR_WARN = (60, 90)
FPS_TARGET = 30.0
FPS_TOL = 0.6

CONTACT_SHEET_COLS = 8
CONTACT_SHEET_ROWS = 6
CONTACT_SHEET_FRAMES = CONTACT_SHEET_COLS * CONTACT_SHEET_ROWS

# ---------------------------------------------------------------------------
# Check 10: sameness vs. the approved/scheduled pool --------------------------
DEFAULT_COMPARE_DIR = os.path.join(HERE, "approved")
SAMENESS_WINDOW_DEFAULT = 10
SAMENESS_SAMPLE_FRAMES = 12
SAMENESS_SAMPLE_SIZE = 32            # px, square, for the hash/palette source frames
SAMENESS_HOOK_WINDOW_S = 3.0         # "first-3-seconds" per the card

# Calibrated in selftest_sameness.py against real ffmpeg clips (see README/report):
# a near-identical pair (same background colour + palette, one word changed in the
# overlay text -- exactly "reused template, tiny tweak") scored 0.993 combined
# similarity; a genuinely-different pair (different pattern, different palette,
# different text) scored 0.476. 0.80 sits roughly in the middle of that huge gap,
# biased toward catching template reuse rather than false-failing genuinely
# different content.
VISUAL_SIM_FAIL_THRESHOLD = 0.80
# Not given an explicit number by the card for the hook/structure comparison (only
# the visual check was asked to be "calibrated") -- 0.75 is a judgment call: it
# catches near-verbatim reused hooks/openers while tolerating two different videos
# that happen to share a few common words (numbers, "AI", "your business", etc).
HOOK_TEXT_SIM_FAIL_THRESHOLD = 0.75

GEMINI_WATCH = os.path.join(os.path.dirname(HERE), "tooling", "gemini_watch.py")
GEMINI_MAX_BYTES = 18_000_000

CTA_KEYWORDS = [
    "follow", "comment", "link in bio", "link below", "book a", "book your",
    "subscribe", "dm us", "dm me", "send a dm", "visit agmm", "agmm.co.uk",
    "get the", "download the", "click the link", "sign up", "learn more",
    # 25 Sep (o2 on C10): ten C-series cut-downs were scripted to end "Our full film on <company> is on YouTube", a
    # designed CTA to the long-form film (the audit link is on the closing card and in every caption), and failed here
    "full film", "on youtube", "watch the full",
    # 25 Sep (o2 on S33): "Save this for the next time you're hiring" is Instagram's own call to action
    "save this", "share this with", "send this to",
]

STAMP_PHRASES = [
    "fictional", "illustrative", "example scenario", "hypothetical", "made-up",
    "made up", "for illustration", "ai-generated", "ai generated", "placeholder",
    "todo", "lorem",
]

# Merged AI-tell vocabulary: card's built-in list + an-anti-ai-writing skill's
# vocab tells / bloated verbs / dead openings / dead transitions (deduped).
AI_TELL_PHRASES = sorted(set([
    "delve", "tapestry", "testament", "in today's fast-paced", "game-changer",
    "unlock the power", "navigate the landscape", "seamless", "leverage",
    "robust", "elevate", "harness", "in conclusion", "moreover", "furthermore",
    "realm", "unlock", "synergy", "streamline", "supercharge", "cutting-edge",
    "revolutionize", "transformative", "intricate", "crucial", "pivotal",
    "foster", "empower", "holistic", "frictionless", "unparalleled",
    "groundbreaking", "data-driven", "scalable", "intuitive", "disruptive",
    "serves as", "stands as", "marks a", "represents a", "boasts a",
    "plays a role in", "helps to", "aims to", "seeks to",
    "it's important to note", "let's dive in", "let's explore", "let's unpack",
    "at the end of the day", "nobody is talking about", "most people don't realize",
    "additionally", "that said", "with that in mind",
]))

# ---------------------------------------------------------------------------
# Check 2 EDGE-CLIP rule (root, 28 Sep 2026, after S39 r1 shipped kickers cut at "COMPAN" / "SANTO" and footers
# running off the right edge, and the gate passed it). Measured on the Vision boxes (kit/tools/ocr_vision, 540 px
# frames, scaled back to the video's width):
#   - small text (box height < EDGE_CLIP_BIG_H at full res): Vision's box is tight (S39 kicker set at x=54 reads 52;
#     a credit at 70 reads 68), so a box edge within EDGE_CLIP_PX of x=0 or x=W is text running off the frame.
#   - big display text: Vision pads the box by up to ~0.3x its height (S39 "+45%" set at x=44 reads 0; C37
#     "AUTOMATICALLY" set at x=55 reads -1), so the box alone cannot tell; the frame's own pixels must show the
#     text's colour in the outer EDGE_CLIP_BAND px on >= EDGE_CLIP_BIG_INK of the box's rows (+45% 0.00,
#     AUTOMATICALLY 0.11-0.15; C37's FALSE ACCOUNTING stamp that really runs off the edge 0.71).
#   - it must persist: the same line at the same place on >= EDGE_CLIP_MIN_SAMPLES consecutive samples (top and
#     cut edge within EDGE_CLIP_STABLE_PX, and either the inner edge too with text ratio >= 0.8, or one read ends
#     with the other at the cut, because Vision re-splits a line between frames). A ticket riding a rail off the frame, a 0.16 s slam
#     overshoot or one garbage read never persists, so deliberate motion across the frame edge is not reported.
#   - >= EDGE_CLIP_MIN_CHARS non-space characters. A deliberate static full-bleed line is exempted per short in
#     out/<ID>/lint-exceptions.json {"edge_clip": [{"text": <exact OCR string>, "reason": ...}]}.
# Blind spots (named, not hidden): a clip that lasts under ~0.5 s (2 fps sampling), and text OCR cannot read at all.
EDGE_CLIP_PX = 8                    # root asked for 6; tuned 28 Sep: Vision on 540-px frames reports boxes on a 4-px grid at
                                    # 1080 and drops a partly cut glyph, so S39's clipped hook footer ('...PYMNTS,' cut
                                    # mid-date, 0-6 s) reads 8 px from the edge and 6 missed it. Nothing unclipped in
                                    # S39/S44/C37 sits at <= 8 (nearest: S39 'MORE THAN 9 MILLION' mid-slam at 12).
EDGE_CLIP_MIN_CHARS = 3
EDGE_CLIP_BIG_H = 100
EDGE_CLIP_BAND = 3                  # px of the 540-wide OCR frame
EDGE_CLIP_BIG_INK = 0.25
EDGE_CLIP_STABLE_PX = 8
EDGE_CLIP_MIN_SAMPLES = 2

NEG_PARALLELISM_RE = re.compile(r"\bit'?s not (?:just )?.{0,80}?,?\s*(?:it'?s|but)\b", re.I)
DASH_SPACE_RE = re.compile(r"(?<!-) - (?!-)")


# ---------------------------------------------------------------------------
def sh(cmd, **kw):
    """Run a subprocess, return CompletedProcess. Never raises on non-zero."""
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)


def ffprobe_json(video):
    p = sh(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", video])
    return json.loads(p.stdout.decode("utf-8", "replace") or "{}")


def probe_info(video):
    d = ffprobe_json(video)
    vstream = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    astream = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = None
    fmt = d.get("format", {})
    if fmt.get("duration"):
        dur = float(fmt["duration"])
    elif vstream and vstream.get("duration"):
        dur = float(vstream["duration"])
    fps = None
    if vstream and vstream.get("r_frame_rate"):
        num, _, den = vstream["r_frame_rate"].partition("/")
        try:
            fps = float(num) / float(den or 1)
        except ZeroDivisionError:
            fps = None
    return {
        "width": vstream.get("width") if vstream else None,
        "height": vstream.get("height") if vstream else None,
        "fps": fps,
        "duration": dur,
        "has_audio": astream is not None,
        "audio_codec": astream.get("codec_name") if astream else None,
        "video_codec": vstream.get("codec_name") if vstream else None,
        "size_bytes": os.path.getsize(video) if os.path.exists(video) else None,
    }


def check_result(id_, name, status, summary, details=None, evidence=None):
    return {
        "id": id_, "name": name, "status": status, "summary": summary,
        "details": details or [], "evidence": evidence or [],
    }


# ---------------------------------------------------------------------------
# Timed-text parsing (script / srt / vtt / json) -----------------------------
def _ts_to_seconds(ts):
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts[-3], parts[-2], parts[-1]
    return h * 3600 + m * 60 + s


def parse_srt_or_vtt(path):
    """Returns list of {start, end, text} in seconds. Handles .srt and .vtt."""
    raw = open(path, encoding="utf-8", errors="replace").read()
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n").strip())
    out = []
    ts_re = re.compile(r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})")
    for b in blocks:
        m = ts_re.search(b)
        if not m:
            continue
        start, end = _ts_to_seconds(m.group(1)), _ts_to_seconds(m.group(2))
        text_lines = b[m.end():].strip().splitlines()
        text_lines = [l for l in text_lines if not l.strip().isdigit()]
        text = " ".join(l.strip() for l in text_lines if l.strip())
        text = re.sub(r"<[^>]+>", "", text)  # strip vtt tag markup
        if text:
            out.append({"start": start, "end": end, "text": text})
    return out


def parse_timed_json(path):
    data = json.load(open(path, encoding="utf-8"))
    out = []
    if isinstance(data, dict):
        data = data.get("captions") or data.get("items") or data.get("events") or []
    for item in data:
        text = item.get("text", "")
        if "start" in item:
            start = float(item["start"])
            end = float(item.get("end", start))
        elif "timestamp" in item:
            start = end = float(item["timestamp"])
        else:
            continue
        if text:
            out.append({"start": start, "end": end, "text": text})
    return out


def load_timed(path):
    if path is None:
        return []
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        return parse_timed_json(path)
    return parse_srt_or_vtt(path)


def load_script_lines(path):
    if path is None:
        return []
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    return [(i + 1, l) for i, l in enumerate(lines) if l.strip()]


# ---------------------------------------------------------------------------
# Check 1 + 2 shared: text linting -------------------------------------------
def lint_text(text):
    """Return list of {type, hit} for a single string of text."""
    hits = []
    if "\u2014" in text:
        hits.append({"type": "dash", "hit": "em dash (\u2014)"})
    if "\u2013" in text:
        hits.append({"type": "dash", "hit": "en dash (\u2013)"})
    if DASH_SPACE_RE.search(text):
        hits.append({"type": "dash", "hit": "' - ' used as a dash"})
    low = text.lower()
    for phrase in STAMP_PHRASES:
        if phrase in low:
            hits.append({"type": "stamp", "hit": phrase})
    for phrase in AI_TELL_PHRASES:
        if phrase in low:
            hits.append({"type": "ai-tell", "hit": phrase})
    if NEG_PARALLELISM_RE.search(text):
        hits.append({"type": "ai-tell", "hit": "negative-parallelism reframe (\"it's not X, it's Y\")"})
    return hits


def lint_source(source_name, script_path=None, timed_items=None):
    """script_path -> line-numbered scan; timed_items -> timestamped scan."""
    findings = []
    if script_path:
        for lineno, line in load_script_lines(script_path):
            for hit in lint_text(line):
                findings.append({
                    "source": source_name, "location": f"L{lineno}",
                    "text": line.strip()[:120], "full_text": line.strip(), **hit,
                })
    if timed_items:
        for item in timed_items:
            for hit in lint_text(item["text"]):
                findings.append({
                    "source": source_name,
                    "location": f"{item['start']:.2f}-{item['end']:.2f}s",
                    "text": item["text"][:120], "full_text": item["text"], **hit,
                })
    return findings


def run_check1_text_lints(script_path, captions_items, onscreen_items, exceptions=None):
    findings = []
    findings += lint_source("script", script_path=script_path)
    findings += lint_source("captions", timed_items=captions_items)
    findings += lint_source("onscreen(supplied)", timed_items=onscreen_items)
    # A verified quotation may contain a word which is normally an AI-writing tell.  The
    # exception remains narrow: one exact complete string and a recorded reason, shared
    # with check 2's OCR exception file.  Never exempt a phrase or a pattern globally.
    exc = exceptions or {"lint": [], "path": None}
    lint_allow = {a.get("text"): a.get("reason", "listed") for a in exc.get("lint", []) if a.get("text")}
    exempted = [f for f in findings if f.get("full_text") in lint_allow]
    findings = [f for f in findings if f not in exempted]
    status = "FAIL" if findings else "PASS"
    summary = f"{len(findings)} lint hit(s) across script/captions/onscreen" if findings else \
        "no dash/stamp/AI-tell hits in script, captions or supplied on-screen text"
    details = [f"[{f['source']} {f['location']}] {f['type']}: \"{f['hit']}\" in: {f['text']}" for f in findings]
    if exempted:
        details.append(f"lint exemptions from {exc.get('path')}:")
        details += [f"  exempted [{f['source']} {f['location']}] {f['type']}: \"{f['hit']}\" in: {f['text']} "
                    f"(reason: {lint_allow[f['full_text']]})" for f in exempted]
    return check_result("1", "TEXT LINTS (script/captions/onscreen)", status, summary, details)


# ---------------------------------------------------------------------------
# Check 2: OCR the rendered video's on-screen text ---------------------------
def try_vision_ocr(video, info, fps=2, width=480):
    """Best-effort macOS Vision OCR. Returns list of {start,end,text} or None if unavailable."""
    try:
        import Vision  # noqa
        import Quartz  # noqa
    except ImportError:
        return None
    # Not installed on this box (pyobjc-framework-Vision would need a native
    # build from source -- skipped deliberately, see README: laptop-safety).
    return None


def _edge_ink(png, box, side, band=EDGE_CLIP_BAND):
    """Fraction of the box's rows whose outer `band` px (on `side`) hold the text's own colour. Text colour = median of
    the pixels in the box's middle 60% that differ from the background just above/below the box."""
    try:
        from PIL import Image
    except ImportError:
        return 1.0          # cannot look: report rather than excuse
    im = np.asarray(Image.open(png).convert("RGB")).astype(float)
    H, W, _ = im.shape
    x0, x1 = int(max(0, box["x"])), int(min(W, box["x"] + box["w"]))
    y0, y1 = int(max(0, box["y"])), int(min(H, box["y"] + box["h"]))
    if y1 - y0 < 3 or x1 - x0 < 6:
        return 0.0
    region = im[y0:y1, x0:x1]
    ring = np.concatenate([im[max(0, y0 - 2):y0, x0:x1].reshape(-1, 3), im[y1:min(H, y1 + 2), x0:x1].reshape(-1, 3)])
    bg = np.median(ring, 0) if len(ring) else np.median(region.reshape(-1, 3), 0)
    mid = region[:, (x1 - x0) // 5:(x1 - x0) * 4 // 5].reshape(-1, 3)
    ink = mid[np.linalg.norm(mid - bg, axis=1) > 60]
    if len(ink) < 10:
        return 0.0
    tc = np.median(ink, 0)
    strip = im[y0:y1, 0:band] if side == "left" else im[y0:y1, W - band:W]
    return float((np.linalg.norm(strip - tc, axis=2) < 70).any(axis=1).mean())


def edge_clip_events(frames_rows, fps, frame_w, allow=()):
    """frames_rows: {n: (png, ocr_w, [line dicts with x,y,w,h,text,conf])}. Returns persistent edge-clip events."""
    cands = []
    for n in sorted(frames_rows):
        png, ow, lines = frames_rows[n]
        sc = frame_w / float(ow or frame_w)
        for l in lines:
            txt = l.get("text", "").strip()
            if l.get("conf", 0) < 0.3 or len(re.sub(r"\s", "", txt)) < EDGE_CLIP_MIN_CHARS:
                continue
            x0, x1, y, h = l["x"] * sc, (l["x"] + l["w"]) * sc, l["y"] * sc, l["h"] * sc
            for side, gap in (("left", x0), ("right", frame_w - x1)):
                if gap > EDGE_CLIP_PX + 0.5:     # Vision floats: 535.9999957 x 2 = 1071.99999 is the 8-px grid step
                    continue
                ink = None
                if h >= EDGE_CLIP_BIG_H:
                    ink = _edge_ink(png, l, side)
                    if ink < EDGE_CLIP_BIG_INK:
                        continue
                cands.append({"n": n, "t": (n - 1) / fps, "side": side, "text": txt, "x0": x0, "x1": x1, "y": y, "h": h,
                              "gap": gap, "ink": ink})
    tracks = []
    for c in cands:
        for tr in tracks:
            p = tr[-1]
            if p["n"] != c["n"] - 1 or p["side"] != c["side"] or abs(p["y"] - c["y"]) > EDGE_CLIP_STABLE_PX:
                continue
            outer, inner = ("x1", "x0") if c["side"] == "right" else ("x0", "x1")
            same_line = abs(p[inner] - c[inner]) <= EDGE_CLIP_STABLE_PX and \
                difflib.SequenceMatcher(None, p["text"], c["text"]).ratio() >= 0.8
            # Vision can split one clipped line differently frame to frame (S39 hook footer alternates between
            # "18 COUNTRIES IN LATIN AMERICA: PYMNTS," and "IN LATIN AMERICA: PYMNTS,"): same cut end = same line
            a, b = p["text"], c["text"]
            same_cut = (a.endswith(b) or b.endswith(a)) if c["side"] == "right" else (a.startswith(b) or b.startswith(a))
            if abs(p[outer] - c[outer]) <= EDGE_CLIP_STABLE_PX and (same_line or same_cut):
                tr.append(c)
                break
        else:
            tracks.append([c])
    events = []
    for tr in tracks:
        if len(tr) < EDGE_CLIP_MIN_SAMPLES:
            continue
        texts = [c["text"] for c in tr]
        exempt = next((a for a in allow if a.get("text") in texts), None)
        if exempt is None:   # root 29 Sep: a full-bleed document push (S29's FCA notice) clips body text by design; a listed
            # time span with a reason exempts only events wholly inside it, so a caption clipped elsewhere still fails
            t0, t1 = tr[0]["t"], tr[-1]["t"] + 1.0 / fps
            exempt = next((a for a in allow if a.get("span") and a["span"][0] <= t0 and t1 <= a["span"][1]), None)
        text = max(set(texts), key=texts.count)
        edge = min(c["gap"] for c in tr)
        events.append({"start": tr[0]["t"], "end": tr[-1]["t"] + 1.0 / fps, "side": tr[0]["side"], "text": text,
                       "gap_px": round(edge, 1), "x0": round(tr[0]["x0"]), "x1": round(tr[0]["x1"]),
                       "box_h": round(tr[0]["h"]), "samples": len(tr),
                       "ink": None if tr[0]["ink"] is None else round(tr[0]["ink"], 2),
                       "exempt": exempt.get("reason", "listed") if exempt else None})
    return events


def load_lint_exceptions(video, path=None):
    """out/<ID>/lint-exceptions.json beside the video (or --lint-exceptions): {"lint": [{"text", "reason"}],
    "edge_clip": [{"text", "reason"}]}. Exact OCR strings only: a narrow, per-short list, never a pattern."""
    p = path or os.path.join(os.path.dirname(os.path.abspath(video)), "lint-exceptions.json")
    if not os.path.exists(p):
        return {"lint": [], "edge_clip": [], "path": None}
    d = json.load(open(p))
    return {"lint": d.get("lint", []), "edge_clip": d.get("edge_clip", []), "path": p}


def vision_binary_ocr(video, fps=2, width=540, edge_out=None, edge_allow=(), boxes_out=None):
    """Local, free macOS Vision OCR through the kit's compiled kit/tools/ocr_vision binary (root, 28 Sep: the free Gemini
    quota ran out and check 2 failed on every short). Frames at `fps`, each line becomes {start,end,text}; consecutive
    identical lines merge. Returns None if the binary is missing or produced nothing.
    boxes_out (row 6, 29 Sep): optional callable(boxes, fps) run while the OCR frames still exist on disk; boxes is
    {n: (png, ocr_w, [line dicts x,y,w,h,text,conf])} in OCR-frame px. kit/tools/frame_check.py uses it."""
    import glob, tempfile
    kit = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit", "tools")
    binp = next((b for b in (os.path.join(kit, "ocr_vision"), os.path.join(kit, ".bin", "ocr_vision")) if os.path.isfile(b)), None)
    if not binp:
        return None
    # root 6 Oct: runs killed mid-way (usage limits, a stopped agent) left their scratch behind (1.3 GB gate-ocr, 0.9 GB snap
    # in /var/folders at 06:50). Clear this tool's OWN orphaned scratch, older than 3 h, before making a new one.
    import glob as _g, time as _t
    for _old in _g.glob(os.path.join(tempfile.gettempdir(), "gate-ocr-*")):
        if os.path.isdir(_old) and _t.time() - os.path.getmtime(_old) > 3 * 3600:
            shutil.rmtree(_old, ignore_errors=True)
    tmp = tempfile.mkdtemp(prefix="gate-ocr-")
    try:
        subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-threads", "2", "-i", video, "-vf",
                        f"fps={fps},scale={width}:-2", os.path.join(tmp, "f_%05d.png")], check=True, stdin=subprocess.DEVNULL)
        frames = sorted(glob.glob(os.path.join(tmp, "f_*.png")))
        if not frames:
            return None
        rows, boxes = {}, {}
        for i in range(0, len(frames), 20):
            # 20-frame batches with a retry: a batch that times out (e.g. its process was SIGSTOPped by the battery
            # guard while the clock ran, S59 28 Sep) is tried once more before the gate gives up on OCR.
            out = ""
            for _try in range(2):
                try:
                    out = subprocess.run([binp] + frames[i:i + 20], capture_output=True, text=True, timeout=900).stdout
                    break
                except subprocess.TimeoutExpired:
                    continue
            else:
                return None
            for line in out.splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                n = int(os.path.basename(d.get("file", "f_0.png"))[2:7])
                rows[n] = [l["text"] for l in d.get("lines", []) if l.get("conf", 0) >= 0.3 and l.get("text", "").strip()]
                boxes[n] = (d.get("file"), d.get("w"), [l for l in d.get("lines", []) if "x" in l and "w" in l])
        items, open_ = [], {}
        for n in sorted(rows):
            t = (n - 1) / fps
            cur = set(rows[n])
            for txt in list(open_):
                if txt not in cur:
                    items.append({"start": open_.pop(txt), "end": t, "text": txt})
            for txt in cur:
                open_.setdefault(txt, t)
        end = len(frames) / fps
        items += [{"start": st, "end": end, "text": txt} for txt, st in open_.items()]
        if edge_out is not None and boxes:
            fw = probe_info(video).get("width") or 1080
            edge_out.extend(edge_clip_events(boxes, fps, fw, edge_allow))
            edge_out.append({"measured": True, "frames": len(boxes), "frame_w": fw})
        if boxes_out is not None and boxes:
            boxes_out(boxes, fps)
        return sorted(items, key=lambda x: x["start"]) or None
    finally:
        for f in glob.glob(os.path.join(tmp, "*")):
            os.remove(f)
        os.rmdir(tmp)


def gemini_ocr(downscaled_path, out_dir):
    # Retry once when a flash pass returns nothing usable (root, 24 Sep: an empty OCR pass also failed the hook check).
    norm, err = _gemini_ocr_once(downscaled_path, out_dir)
    if not norm:
        norm2, err2 = _gemini_ocr_once(downscaled_path, out_dir)
        if norm2:
            return norm2, None
        return norm, err or err2
    return norm, err


def _gemini_ocr_once(downscaled_path, out_dir):
    prompt = (
        "Watch this video closely. List EVERY piece of on-screen text, caption, "
        "label, stamp or graphic overlay that appears anywhere in the frame, in "
        "order. Return ONLY a JSON array, no prose, no markdown fences. Each "
        "element: {\"start\": <seconds float>, \"end\": <seconds float>, \"text\": "
        "\"<exact text as shown>\"}. If on-screen text runs the whole video, still "
        "give discrete entries per distinct piece of text. Be exhaustive; include "
        "tiny corner labels and stamps."
    )
    out_txt = os.path.join(out_dir, "gemini_ocr_raw.txt")
    cmd = ["python3", GEMINI_WATCH, downscaled_path, prompt, "--json", "--out", out_txt]
    p = sh(cmd)
    stdout = p.stdout.decode("utf-8", "replace")
    stderr = p.stderr.decode("utf-8", "replace")
    if p.returncode != 0:
        return None, f"gemini_watch.py exited {p.returncode}: {stderr[-400:] or stdout[-400:]}"
    raw = stdout.strip()
    raw = re.sub(r"^```json\s*|\s*```$", "", raw.strip(), flags=re.I | re.M)
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"gemini OCR response was not valid JSON ({e}); raw saved to {out_txt}"
    norm = []
    for it in items:
        try:
            start = float(it.get("start", 0))
            end = float(it.get("end", start))
            text = str(it.get("text", ""))
        except (TypeError, ValueError):
            continue
        if text:
            norm.append({"start": start, "end": end, "text": text})
    return norm, None


def _frame_rule(rows_holder, video, platform, video_id):
    """Check 2 PER-PLATFORM FRAME rule (row 6, 29 Sep 2026, Sam's Instagram screenshot of S33: text cut at the phone's side
    crop and hidden under the Reels header). kit/tools/frame_check.py tests every OCR text box against the ROUTED
    platform's profile in kit/platforms/frames.json (routing: jev-v2/fit/routing.json, else --platform):
      FAIL  text > 8 px outside the platform's visible rect, where that rect is measured (Instagram) or derived (Facebook Reels)
      WARN  (details only) text under the platform's UI overlays, touching the crop, or outside an ESTIMATED visible rect.
    A WARN never changes check 2's status: produce.py and root_pass.py need overall PASS, so a status WARN would block
    every short. Returns (fail_events, warn_events, detail_lines)."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit", "tools"))
        import frame_check
        import platforms as _pf
    except Exception as e:     # never pass silently
        return [], [], ["frame rule NOT RUN: cannot import kit/tools/frame_check.py (%s)" % e]
    vid = video_id
    if not vid:
        m = re.search(r"/(?:out|items)/([A-Z]\d+)/", os.path.abspath(video))
        vid = m.group(1) if m else None
    name = (_pf.routed_platform(vid) if vid else None) or platform
    if not name:
        return [], [], ["frame rule NOT RUN: no routed platform for %s and no --platform" % (vid or video)]
    if "rows" not in rows_holder:
        return [], [], ["frame rule NOT RUN: no OCR boxes (Gemini fallback)"]
    try:
        p = _pf.profile(name)
    except KeyError as e:
        return [], [], ["frame rule NOT RUN: %s" % e]
    a = frame_check.analyse(rows_holder["rows"], rows_holder["fps"], p, frame_check.load_allow(video))
    live = [e for e in a["events"] if not e["exempt"]]
    fails = [e for e in live if e["severity"] == "FAIL"]
    warns = [e for e in live if e["severity"] == "WARN"]
    d = ["frame rule: %s -> %s (visible x %d-%d, y %d-%d, %s): FAIL %.1f s of video, WARN %.1f s (routing: %s)" % (
        vid or "?", p["key"], p["visible"]["x0"], p["visible"]["x1"], p["visible"]["y0"], p["visible"]["y1"],
        p["visible"]["evidence"], a["fail_video_s"], a["warn_video_s"], "routing.json" if vid and _pf.routed_platform(vid) else "--platform")]
    for e in a["events"]:
        tag = "EXEMPT (%s) " % e["exempt"] if e["exempt"] else ""
        d.append("[OCR %.2f-%.2fs] %sframe %s %s: %s in: %s" % (e["start"], e["end"], tag, e["severity"], e["kind"], e["detail"], e["text"][:100]))
    return fails, warns, d


def run_check2_ocr(video, info, downscaled_path, out_dir, onscreen_supplied, exceptions_path=None, platform=None, video_id=None):
    vision_items = try_vision_ocr(video, info)
    method = None
    items = None
    error = None
    exc = load_lint_exceptions(video, exceptions_path)
    edge = []
    if vision_items is None:
        frame_rows = {}

        def _keep_boxes(boxes, fps_):
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit", "tools"))
                import frame_check
                fw, fh = info.get("width") or 1080, info.get("height") or 1920
                frame_rows["rows"] = frame_check.boxes_to_master(boxes, fw, fh)
                frame_rows["fps"] = fps_
            except Exception as e:
                frame_rows["error"] = str(e)
        vision_items = vision_binary_ocr(video, edge_out=edge, edge_allow=exc["edge_clip"], boxes_out=_keep_boxes)
        if vision_items is not None:
            method = "macOS Vision (kit/tools/ocr_vision, local)"
    if vision_items is not None:
        method = method or "macOS Vision (pyobjc)"
        items = vision_items
    else:
        method = "gemini_watch.py fallback (Vision unavailable: pyobjc not installed -- " \
                 "native build skipped for laptop safety, see README)"
        items, error = gemini_ocr(downscaled_path, out_dir)

    if items is None:
        return check_result(
            "2", "OCR ON-SCREEN TEXT LINT", "FAIL",
            f"no OCR method produced usable output ({method}); blocker: {error}",
            [f"method attempted: {method}", f"error: {error}"],
        ), []

    findings = lint_source("onscreen(OCR)", timed_items=items)
    # narrow per-short exemptions: exact OCR strings (e.g. a verbatim source quote on screen), each with a reason
    lint_allow = {a.get("text"): a.get("reason", "listed") for a in exc["lint"]}
    exempted = [f for f in findings if f["text"] in lint_allow or any(f["text"] == t[:120] for t in lint_allow)]
    findings = [f for f in findings if f not in exempted]
    measured = next((e for e in edge if e.get("measured")), None)
    clips = [e for e in edge if not e.get("measured")]
    clips_fail = [e for e in clips if not e["exempt"]]
    status = "FAIL" if (findings or clips_fail) else "PASS"
    if not measured and status == "PASS":
        status = "WARN"     # no Vision boxes (Gemini fallback): the edge-clip rule could not run; say so, never pass silently
    summary = (f"OCR via {method}: {len(items)} text event(s) found, {len(findings)} lint hit(s), "
               f"{len(clips_fail)} edge-clip(s)" + ("" if measured else " (edge-clip NOT MEASURED: no OCR boxes)"))
    details = [f"method: {method}", f"onscreen text events detected: {len(items)}"]
    details += [f"[OCR {f['location']}] {f['type']}: \"{f['hit']}\" in: {f['text']}" for f in findings]
    for e in clips:
        where = f"{e['side']} edge {e['gap_px']} px from the frame edge (box x {e['x0']}-{e['x1']}, h {e['box_h']}" + \
                (f", edge ink {e['ink']}" if e["ink"] is not None else "") + f", {e['samples']} samples)"
        tag = f"EXEMPT ({e['exempt']}) " if e["exempt"] else ""
        details.append(f"[OCR {e['start']:.2f}-{e['end']:.2f}s] {tag}edge-clip: {where} in: {e['text'][:120]}")
    if exempted:
        details.append(f"lint exemptions from {exc['path']}:")
        details += [f"  exempted [OCR {f['location']}] {f['type']}: \"{f['hit']}\" in: {f['text']} (reason: "
                    f"{lint_allow.get(f['text']) or next(v for k, v in lint_allow.items() if k[:120] == f['text'])})" for f in exempted]
    if measured:
        details.append(f"edge-clip rule: {measured['frames']} frames measured at width {measured['frame_w']}, "
                       f"edge <= {EDGE_CLIP_PX} px, >= {EDGE_CLIP_MIN_CHARS} chars, persists >= {EDGE_CLIP_MIN_SAMPLES} samples")
    fr_fail, fr_warn, fr_details = _frame_rule(locals().get("frame_rows") or {}, video, platform, video_id)
    if fr_fail:
        status = "FAIL"
    summary += ", %d frame cut(s) on the routed platform, %d frame warning(s)" % (len(fr_fail), len(fr_warn))
    details += fr_details
    return check_result("2", "OCR ON-SCREEN TEXT LINT", status, summary, details), items


# ---------------------------------------------------------------------------
# Check 3: static-hold detector ----------------------------------------------
def decode_gray_frames(video, width=STATIC_SAMPLE_WIDTH, fps=STATIC_SAMPLE_FPS):
    """Decode video to grayscale raw frames at low res/fps. Yields numpy arrays (h,w)."""
    logf = video + ".ffmpeg_stderr.tmp.log"
    cmd = ["nice", "-n", "15", "ffmpeg", "-threads", "2", "-i", video,
           "-vf", f"scale={width}:-2,fps={fps},format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    with open(logf, "wb") as lf:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=lf)
        raw = proc.stdout.read()
        proc.wait()
    stderr_text = open(logf, encoding="utf-8", errors="replace").read()
    os.remove(logf)
    # ffmpeg prints the INPUT stream's dims too (e.g. the source 640x360), so we
    # must anchor on the "Video: rawvideo" line specifically (the decoder's
    # output, after our scale filter) and only then look for "WxH [SAR" on that
    # same line -- never a bare (\d+)x(\d+) search, which would grab the wrong
    # stream or a hex codec tag like "0x30303859".
    m = None
    for line in stderr_text.splitlines():
        if "Video: rawvideo" in line:
            m = re.search(r"(\d+)x(\d+)\s*\[SAR", line)
            if m:
                break
    if not m:
        return None, stderr_text
    w, h = int(m.group(1)), int(m.group(2))
    frame_bytes = w * h
    n = len(raw) // frame_bytes
    frames = np.frombuffer(raw[: n * frame_bytes], dtype=np.uint8).reshape(n, h, w)
    return frames, None


def static_hold_spans(frames, threshold_pct=STATIC_DIFF_PCT_THRESHOLD, sample_fps=STATIC_SAMPLE_FPS):
    """Return list of (start_s, end_s, duration_s) static spans, plus per-transition diffs."""
    if frames is None or len(frames) < 2:
        return [], []
    dt = 1.0 / sample_fps
    diffs = []
    a = frames.astype(np.int16)
    for i in range(1, len(a)):
        d = np.abs(a[i] - a[i - 1]).mean() / 255.0 * 100.0
        diffs.append(d)
    spans = []
    run_start = None
    for i, d in enumerate(diffs):
        t = i * dt  # time of the transition (frame i-1 -> frame i), start of frame i-1
        if d < threshold_pct:
            if run_start is None:
                run_start = t
        else:
            if run_start is not None:
                spans.append((run_start, t, t - run_start))
                run_start = None
    if run_start is not None:
        end_t = len(diffs) * dt
        spans.append((run_start, end_t, end_t - run_start))
    return spans, diffs


def run_check3_static_hold(video, kind, out_dir):
    frames, err = decode_gray_frames(video)
    if frames is None:
        return check_result("3", "STATIC-HOLD DETECTOR", "FAIL",
                             f"could not decode frames for static-hold analysis: {err}")
    # root 29 Sep: a per-platform REFRAME (kit/tools/reframe.py) shrinks the picture and adds a still, blurred border,
    # which dilutes the whole-frame diff (S39: a 1.40 s hold measured 1.60 s after the reframe, same motion). Measure
    # inside the content rect when a sidecar bound to these exact bytes (out_bytes) says the master was reframed.
    reframe_note = ""
    try:
        import glob as _g
        vsize = os.path.getsize(video)
        for sc in _g.glob(os.path.join(os.path.dirname(os.path.abspath(video)), "*.reframe.json")):
            info = json.load(open(sc))
            if info.get("out_bytes") == vsize:
                h, w = frames.shape[1], frames.shape[2]
                fx, fy = w / 1080.0, h / 1920.0
                (ox, oy), (sw, sh) = info["offset"], info["size"]
                x0, y0 = int(round(ox * fx)) + 1, int(round(oy * fy)) + 1
                x1, y1 = int((ox + sw) * fx) - 1, int((oy + sh) * fy) - 1
                frames = frames[:, y0:y1, x0:x1]
                reframe_note = " (measured inside the reframed content rect %s)" % os.path.basename(sc)
                break
    except Exception as ex:
        reframe_note = " (reframe sidecar unreadable: %s)" % ex
    spans, diffs = static_hold_spans(frames)
    max_span = STATIC_MAX_SPAN[kind]
    bad_spans = [s for s in spans if s[2] > max_span]
    # Designed slow read beats (root, 28 Sep: F01 r10's Arup quote, 256.9-264.2 s, where the camera drifts and the
    # underline draws below the 0.4%-per-frame threshold). A long span is excused ONLY if a reviewer listed it in
    # static-exceptions.json (next to the video or up to three folders above out_dir) AND the span's first and last
    # frames differ by at least STATIC_EXCEPTION_MIN_DRIFT_PCT, so a genuinely frozen frame still fails.
    excused = []
    exc = []
    for base in [os.path.dirname(os.path.abspath(video))] + [os.path.abspath(os.path.join(out_dir, *[".."] * k)) for k in range(4)]:
        p = os.path.join(base, "static-exceptions.json")
        if os.path.isfile(p):
            exc = json.load(open(p)).get("spans", [])
            break
    for s in list(bad_spans):
        for e in exc:
            if float(e["start"]) - 0.5 <= s[0] and s[1] <= float(e["end"]) + 0.5 and e.get("by") and e.get("reason"):
                i0, i1 = int(round(s[0] * STATIC_SAMPLE_FPS)), min(len(frames) - 1, int(round(s[1] * STATIC_SAMPLE_FPS)))
                drift = np.abs(frames[i1].astype(np.int16) - frames[i0].astype(np.int16)).mean() / 255.0 * 100.0
                if drift >= STATIC_EXCEPTION_MIN_DRIFT_PCT:
                    excused.append((s, drift, e))
                    bad_spans.remove(s)
                break
    status = "FAIL" if bad_spans else "PASS"
    summary = (f"decoded {len(frames)} frames @ {STATIC_SAMPLE_FPS}fps/{STATIC_SAMPLE_WIDTH}w; "
               f"{len(spans)} static span(s), {len(bad_spans)} exceed {max_span}s ({kind})")
    details = [f"threshold: frame-to-frame mean abs diff < {STATIC_DIFF_PCT_THRESHOLD}% of dynamic range "
               f"counts as 'no meaningful change'; FAIL span > {max_span}s ({kind})"]
    for s in spans:
        flag = " <== FAIL" if s in bad_spans else (" (excused, see below)" if s[2] > max_span else "")
        details.append(f"static span {s[0]:.2f}s-{s[1]:.2f}s ({s[2]:.2f}s){flag}")
    for s, drift, e in excused:
        details.append(f"EXCUSED {s[0]:.2f}s-{s[1]:.2f}s: moves {drift:.2f}% start-to-end (min {STATIC_EXCEPTION_MIN_DRIFT_PCT}%); "
                       f"listed by {e['by']}: {e['reason'][:120]}")
    if diffs:
        details.append(f"min/median/max frame-diff%: {min(diffs):.3f}/{sorted(diffs)[len(diffs)//2]:.3f}/{max(diffs):.3f}")
    return check_result("3", "STATIC-HOLD DETECTOR", status, summary + reframe_note, details)


# ---------------------------------------------------------------------------
# Check 4: loudness -----------------------------------------------------------
def run_ebur128(video):
    cmd = ["nice", "-n", "15", "ffmpeg", "-threads", "2", "-i", video,
           "-af", "ebur128=peak=true", "-f", "null", "-"]
    p = sh(cmd)
    return p.stderr.decode("utf-8", "replace")


def parse_ebur128(text):
    # Parse only the final Summary block: ffmpeg also prints running per-frame "I: -70.0 LUFS" lines,
    # and the first of those (silence before gating) was being read as the integrated loudness.
    if "Summary:" not in text:
        return None, None
    text = text.rsplit("Summary:", 1)[1]
    i = re.search(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", text)
    tp = re.search(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", text)
    integrated = float(i.group(1)) if i else None
    peak = float(tp.group(1)) if tp else None
    return integrated, peak


def run_silencedetect(video, noise=SILENCE_NOISE_DB, min_dur=SILENCE_MAX_S, extra=None):
    cmd = ["nice", "-n", "15", "ffmpeg", "-threads", "2"] + (extra or []) + ["-i", video,
           "-af", f"silencedetect=noise={noise}:d={min_dur}", "-f", "null", "-"]
    p = sh(cmd)
    text = p.stderr.decode("utf-8", "replace")
    starts = [float(m.group(1)) for m in re.finditer(r"silence_start:\s*(-?\d+(?:\.\d+)?)", text)]
    ends = [float(m.group(1)) for m in re.finditer(r"silence_end:\s*(-?\d+(?:\.\d+)?)", text)]
    periods = []
    for st in starts:
        matching_end = next((e for e in ends if e > st), None)
        periods.append((st, matching_end))
    return periods, text


def run_check4_loudness(video, info, out_dir):
    if not info["has_audio"]:
        return check_result("4", "LOUDNESS", "FAIL", "no audio track present in the file")
    ebur_text = run_ebur128(video)
    integrated, peak = parse_ebur128(ebur_text)
    details = []
    fails = []
    if integrated is None:
        fails.append("could not parse integrated LUFS from ffmpeg ebur128 output")
    else:
        lo, hi = LUFS_TARGET - LUFS_TOLERANCE, LUFS_TARGET + LUFS_TOLERANCE
        ok = lo <= integrated <= hi
        details.append(f"integrated loudness: {integrated:.1f} LUFS (target {LUFS_TARGET}\u00b1{LUFS_TOLERANCE})"
                        + ("" if ok else " <== FAIL"))
        if not ok:
            fails.append(f"integrated loudness {integrated:.1f} LUFS outside {lo}..{hi} LUFS")
    if peak is None:
        fails.append("could not parse true peak from ffmpeg ebur128 output")
    else:
        ok = peak <= TRUE_PEAK_MAX_DBTP
        details.append(f"true peak: {peak:.1f} dBTP (max {TRUE_PEAK_MAX_DBTP})" + ("" if ok else " <== FAIL"))
        if not ok:
            fails.append(f"true peak {peak:.1f} dBTP exceeds {TRUE_PEAK_MAX_DBTP} dBTP")

    duration = info["duration"] or 0.0
    periods, _ = run_silencedetect(video)
    tail_cutoff = max(0.0, duration - SILENCE_TAIL_EXCLUDE_S)
    long_silences = []
    for st, en in periods:
        en = en if en is not None else duration
        overlap_start, overlap_end = st, min(en, tail_cutoff)
        overlap = max(0.0, overlap_end - overlap_start)
        if overlap > SILENCE_MAX_S:
            long_silences.append((st, en, overlap))
    if long_silences:
        for st, en, ov in long_silences:
            details.append(f"silence {st:.2f}s-{en:.2f}s ({ov:.2f}s outside the last "
                            f"{SILENCE_TAIL_EXCLUDE_S}s tail) <== FAIL")
        fails.append(f"{len(long_silences)} silent span(s) > {SILENCE_MAX_S}s outside the tail")
    else:
        details.append(f"no silent span > {SILENCE_MAX_S}s outside the last {SILENCE_TAIL_EXCLUDE_S}s tail")

    status = "FAIL" if fails else "PASS"
    summary = "; ".join(fails) if fails else "loudness, true peak and silence all within spec"
    return check_result("4", "LOUDNESS", status, summary, details)


# ---------------------------------------------------------------------------
# Check 5: hook ---------------------------------------------------------------
STOPWORDS = {"the", "a", "an", "this", "that", "here", "how", "why", "what", "when",
             "i", "we", "you", "it", "and", "but", "so", "if", "in", "on", "at", "to"}


def looks_like_named_subject(text):
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
    for idx, w in enumerate(words):
        if idx == 0:
            continue  # skip sentence-initial capital, not evidence of a proper noun
        if w[0].isupper() and w.lower() not in STOPWORDS and len(w) > 1:
            return True, w
    # also treat a number/stat as a strong open ("$700m", "10,000 staff")
    if re.search(r"[$£€]\s?\d|\b\d[\d,]*\s?(m|bn|k|million|billion|thousand|%)\b", text, re.I):
        return True, "number/stat"
    return False, None


def run_check5_hook(video, info, captions_items, onscreen_items, ocr_items):
    duration = info["duration"] or 0.0
    window_items = [i for i in (captions_items + onscreen_items + ocr_items)
                     if i["start"] < HOOK_WINDOW_S]
    text_in_window = " ".join(i["text"] for i in window_items)
    has_onscreen = bool(window_items)
    named, named_word = looks_like_named_subject(text_in_window) if text_in_window else (False, None)

    periods, _ = run_silencedetect(video, min_dur=0.1, extra=["-t", "3"])
    speech_start = 0.0
    if periods and periods[0][0] is not None and periods[0][0] <= 0.05:
        end = periods[0][1]
        speech_start = end if end is not None else HOOK_SPEECH_MAX_START_S + 1
    speech_ok = speech_start <= HOOK_SPEECH_MAX_START_S

    visual_ok = has_onscreen or named
    status = "PASS" if (visual_ok and speech_ok) else "FAIL"
    details = [
        f"on-screen text/caption event(s) starting before {HOOK_WINDOW_S}s: {len(window_items)}",
        f"named subject or number detected in first {HOOK_WINDOW_S}s text: {named} ({named_word})"
        if text_in_window else f"no caption/onscreen text available inside first {HOOK_WINDOW_S}s to judge named subject",
        f"speech onset: {speech_start:.2f}s (must be \u2264 {HOOK_SPEECH_MAX_START_S}s)"
        + ("" if speech_ok else " <== FAIL"),
    ]
    if not visual_ok:
        details.append(f"no readable on-screen text and no named subject/number in first {HOOK_WINDOW_S}s <== FAIL")
    summary = "hook passes: onscreen/named-subject + speech-by-0.6s" if status == "PASS" else \
        "hook FAILS: " + ("late speech onset" if not speech_ok else "") + \
        ("; " if not speech_ok and not visual_ok else "") + \
        ("no readable text/named subject in frame" if not visual_ok else "")
    return check_result("5", "HOOK (first 2s)", status, summary, details)


# ---------------------------------------------------------------------------
# Check 6: CTA -----------------------------------------------------------------
def run_check6_cta(info, script_path, captions_items):
    duration = info["duration"] or 0.0
    window_start = max(0.0, duration - CTA_WINDOW_S)
    window_items = [i for i in captions_items if i["end"] >= window_start]
    if window_items:
        text = " ".join(i["text"] for i in window_items).lower()
        basis = f"captions in last {CTA_WINDOW_S}s ({window_start:.1f}s-{duration:.1f}s), {len(window_items)} entr(y/ies)"
    else:
        lines = [l for _, l in load_script_lines(script_path)] if script_path else []
        tail = lines[-3:] if len(lines) >= 3 else lines
        text = " ".join(tail).lower()
        basis = ("no timed captions given; approximated the last-8s window as the script's " +
                 f"final {len(tail)} line(s) (no timing data available)")
    hits = [kw for kw in CTA_KEYWORDS if kw in text]
    status = "PASS" if hits else "FAIL"
    summary = f"CTA keyword(s) found: {hits}" if hits else "no CTA keyword found in the closing window"
    details = [basis, f"window text: \"{text.strip()[:200]}\""]
    return check_result("6", "CTA (last 8s)", status, summary, details)


# ---------------------------------------------------------------------------
# Check 7: format ---------------------------------------------------------------
def run_check7_format(info, kind):
    fails, warns, details = [], [], []
    w, h, fps, dur = info["width"], info["height"], info["fps"], info["duration"]
    details.append(f"detected: {w}x{h}, {fps:.3f}fps, {dur:.2f}s" if fps and dur else f"detected: {w}x{h}")
    if kind == "short":
        if (w, h) != SHORT_RES:
            fails.append(f"resolution {w}x{h} != required {SHORT_RES[0]}x{SHORT_RES[1]}")
        if dur is not None:
            if SHORT_DUR_PASS[0] <= dur <= SHORT_DUR_PASS[1]:
                pass
            elif SHORT_DUR_PASS[1] < dur <= SHORT_DUR_WARN[1]:
                warns.append(f"duration {dur:.1f}s is in the 60-90s warn band")
            else:
                fails.append(f"duration {dur:.1f}s outside 30-90s")
        if fps is not None and abs(fps - FPS_TARGET) > FPS_TOL:
            fails.append(f"fps {fps:.2f} != required {FPS_TARGET}")
    else:
        if (w, h) != LONG_RES:
            fails.append(f"resolution {w}x{h} != required {LONG_RES[0]}x{LONG_RES[1]}")
    status = "FAIL" if fails else ("WARN" if warns else "PASS")
    summary = "; ".join(fails + warns) if (fails or warns) else f"format OK for kind={kind}"
    return check_result("7", "FORMAT", status, summary, details + fails + warns)


# ---------------------------------------------------------------------------
# Check 8: contact sheets -------------------------------------------------------
def run_check8_contact_sheets(video, info, out_dir):
    sheets_dir = os.path.join(out_dir, "contact-sheets")
    os.makedirs(sheets_dir, exist_ok=True)
    fps = info["fps"] or FPS_TARGET
    duration = info["duration"] or 0.0
    total_frames_est = max(1, round(fps * duration))
    pattern = os.path.join(sheets_dir, "sheet-%03d.jpg")
    cmd = ["nice", "-n", "15", "ffmpeg", "-threads", "2", "-i", video,
           "-vf", f"scale=iw/4:ih/4,tile={CONTACT_SHEET_COLS}x{CONTACT_SHEET_ROWS}",
           "-qscale:v", "5", "-vsync", "0", "-y", pattern]
    p = sh(cmd)
    sheet_files = sorted(f for f in os.listdir(sheets_dir) if f.startswith("sheet-"))
    if not sheet_files:
        return check_result("8", "CONTACT SHEETS", "FAIL",
                             f"ffmpeg produced no contact sheets: {p.stderr.decode('utf-8','replace')[-400:]}")
    manifest = []
    for idx, fname in enumerate(sheet_files, start=1):
        start_frame = (idx - 1) * CONTACT_SHEET_FRAMES + 1
        end_frame = min(idx * CONTACT_SHEET_FRAMES, total_frames_est if idx == len(sheet_files) else idx * CONTACT_SHEET_FRAMES)
        manifest.append({"sheet": fname, "frames": [start_frame, end_frame]})
    manifest_path = os.path.join(sheets_dir, "manifest.json")
    json.dump({"total_frames_estimate": total_frames_est, "fps_used_for_estimate": fps,
               "frames_per_sheet": CONTACT_SHEET_FRAMES, "sheets": manifest},
              open(manifest_path, "w"), indent=1)
    status = "PASS"
    summary = f"{len(sheet_files)} sheet(s) covering an estimated {total_frames_est} frames " \
              f"({CONTACT_SHEET_FRAMES}/sheet, {CONTACT_SHEET_COLS}x{CONTACT_SHEET_ROWS})"
    details = [f"sheets dir: {sheets_dir}", f"manifest: {manifest_path}"]
    return check_result("8", "CONTACT SHEETS", status, summary, details)


# ---------------------------------------------------------------------------
# Check 9: gemini critic ---------------------------------------------------------
CRITIC_PROMPT = """You are a blunt creative director reviewing a short-form/long-form marketing video for
AGMM, a UK AI-automation agency. The audience is a busy, sceptical owner or MD of a UK business
turning over GBP 1m-50m. Watch AND listen to the whole video, then score it.

Today's date is {TODAY}. The video covers real, recent events; every factual claim in it has already been
verified against published sources by an independent fact-checker. Your training data may predate these events:
do NOT mark a claim as false, future-dated or outdated, and do not lower any score for that reason. Judge only
craft: hook, clarity, story, pacing, visuals, sound and CTA. If something is unclear to a viewer, say so as a
clarity problem, not a factual one.

Return ONLY a JSON object, no markdown fences, no prose outside the JSON:
{
  "scores": {
    "hook_strength_first_3s": <1-10>,
    "clarity_no_context_needed": <1-10>,
    "story": <1-10>,
    "pacing": <1-10>,
    "visual_quality_and_variety": <1-10>,
    "sound_design": <1-10>,
    "cta": <1-10>
  },
  "problems": [ {"timestamp": "<mm:ss>", "issue": "<what is wrong>"}, ... ],
  "notes": "<2-4 sentences, direct>"
}
Score honestly; a 5 means mediocre and unfinished, not a passing grade."""


def make_downscaled_copy(video, out_path, target_bytes=GEMINI_MAX_BYTES):
    info = probe_info(video)
    duration = max(1.0, info["duration"] or 1.0)
    # 25 Sep (Jev's scorer found it): "scale=-2:480" made a vertical 1080x1920 short 270x480, so every Gemini check
    # (OCR, critic, judge) graded 42 px text and micro-detail on a thumbnail. The SHORT side is now 720 (720x1280 for
    # a short, 1280x720 for a film), bitrate still sized to stay under the inline byte limit. Threads are capped on
    # the output side: "-threads 2" before -i does not limit libx264 (measured 1173% CPU, 24 Sep).
    target_kbps = max(150, min(2500, int((target_bytes * 8 / 1000) / duration * 0.85)))
    cmd = ["nice", "-n", "15", "ffmpeg", "-y", "-i", video,
           "-vf", "scale='if(gt(ih,iw),720,-2)':'if(gt(ih,iw),-2,720)'", "-b:v", f"{target_kbps}k",
           "-x264-params", "threads=2", "-c:a", "aac", "-b:a", "96k",
           out_path]
    p = sh(cmd)
    ok = os.path.exists(out_path) and os.path.getsize(out_path) > 0
    return ok, p.stderr.decode("utf-8", "replace")


# Check 9 fallback (28 Sep 2026, 18:35): the free Gemini quota ran out until ~08:00 BST and gemini_watch.py then spends
# ~2 min per free model in 429 sleep-retries (9 models, 2 runs: ~36 min per short), so every gate stalled or FAILED at
# check 9 and no short could post. When BOTH Gemini runs fail on quota / 429 / rate limit / ">18MB" (or stall past
# GATE_GEMINI_TIMEOUT), check 9 falls back to the proven free vision model, Qwen 3.8 27B on Groq (lane l7-groq, same
# call as kit/tools/vision_check.py), shown 8 still frames in ONE request. It cannot hear, so sound is UNJUDGED and the
# summary says so; nobody should read a fallback pass as a Gemini pass. GATE_CRITIC=qwen forces the fallback,
# GATE_CRITIC=gemini disables it. A quota fallback is cached for 45 min so the next gate skips the stall.
#
# Critic chain (28 Sep 2026, 23:30, critics subagent for root; measured in
# ~/alfred/builds/craft-learning-2026-09-28/critics-2026-09-28/): at 16 posts a day Groq's 200k tokens/day ran out by
# mid-afternoon and check 9 went UNJUDGED. The chain after the primary Gemini key is now, in measured order:
#   1. Gemini on the SECOND free AI Studio project (GEMINI_API_KEY_OLD_ACCOUNT, closed-trial account = free tier only;
#      its quota is separate: KEY_B 429 PerDay on gemini-3.6/3.5-flash while this key answered the same models 200).
#      Same gemini_watch.py call, same two runs, and it HEARS the video, so it is a real Gemini verdict, not a fallback.
#   2. FRAME_CRITICS, frames-only, in order: Qwen 3.8 on Groq, then the same Qwen 3.8 weights as OpenRouter ":free"
#      (the unfunded OPENROUTER_KEY_OLD_ACCOUNT first, 50 free requests/day, then OPENROUTER_KEY's free pool).
#   3. UNJUDGED only when every critic above is out of quota or unavailable; FAIL when one gave a broken answer.
# Each frames critic has its own lock + stamp file (one request at a time machine-wide, gap_s apart) and its own
# "exhausted" mark (~/.cache/gate_critic_exhausted.json) so a daily cap costs one probe, not an 8 x 70 s stall per gate.
# Refused by construction: any model id that is not ":free" on OpenRouter (the funded key must never pay) and
# GEMINI_API_KEY (the prepay project) as the second Gemini key. No GPT model anywhere.
QWEN_CRITIC_MODEL = "qwen/qwen3.8-27b"
QWEN_CRITIC_WIDTH = 540
QWEN_CRITIC_EVEN_FRAMES = 6
QWEN_CRITIC_MAX_IMAGES = 3              # Groq, measured 28 Sep: "This model supports up to 3 images" (HTTP 400 at 8 and 5)
QWEN_PACE_S = 25.0                       # Groq's per-minute image limit; shared across gate processes via a stamp file
QWEN_PACE_FILE = os.path.expanduser("~/.cache/gate_qwen_critic_last_call")
GEMINI_CRITIC_TIMEOUT_S = int(os.environ.get("GATE_GEMINI_TIMEOUT", "360"))
GEMINI_QUOTA_CACHE = os.path.expanduser("~/.cache/gate_gemini_critic_quota")
GEMINI_QUOTA_CACHE_S = 2700
GEMINI_FALLBACK_RE = re.compile(r"429|quota|rate.?limit|RESOURCE_EXHAUSTED|too many requests|>18MB", re.I)
QWEN_FALLBACK_LABEL = "critic: Qwen 3.8 frames-only fallback"
GEMINI2_KEY_NAME = "GEMINI_API_KEY_OLD_ACCOUNT"
GEMINI2_QUOTA_CACHE = os.path.expanduser("~/.cache/gate_gemini2_critic_quota")
GEMINI2_LABEL = "critic: Gemini on the second free AI Studio key (%s)" % GEMINI2_KEY_NAME
CRITIC_EXHAUSTED_FILE = os.path.expanduser("~/.cache/gate_critic_exhausted.json")
CRITIC_EXHAUSTED_S = 1800                # a daily-cap 429 benches that critic for 30 min (Groq's TPD is a rolling window)
CRITIC_DAILY_RE = re.compile(r"tokens per day|\(TPD\)|per.?day|free-models-per-day|daily free allocation", re.I)
CRITIC_UNAVAILABLE_RE = re.compile(r"429|quota|rate.?limit|tokens per day|TPD|RESOURCE_EXHAUSTED|too many requests|"
                                   r"HTTP 50[234]|unavailable|high demand|overloaded|timed? ?out|RemoteDisconnected|"
                                   r"URLError|Connection|no base URL or key|exhausted", re.I)
FRAME_CRITICS = [
    {"id": "qwen-groq", "label": QWEN_FALLBACK_LABEL, "model": QWEN_CRITIC_MODEL, "route": "groq",
     "max_images": 3, "gap_s": 65.0, "stamp": QWEN_PACE_FILE, "max_tokens": 900, "extra": {},
     "attempts": 8, "retry_sleep_s": 70},
    {"id": "qwen-openrouter-free", "label": QWEN_FALLBACK_LABEL + " via OpenRouter :free", "model": "qwen/qwen3.8-27b:free",
     "route": "openrouter-free", "max_images": 3, "gap_s": 5.0,
     "stamp": os.path.expanduser("~/.cache/gate_critic_openrouter_free_last_call"), "max_tokens": 900,
     "extra": {"reasoning": {"enabled": False}}, "attempts": 5, "retry_sleep_s": 25},
]


def _parse_critic_json(text):
    """Same parse as the Gemini path (strip ```json fences, json.loads); also drops a <think> block and, failing
    that, takes the outermost {...} so a chatty open model still parses."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I).strip()
    raw = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.I | re.M)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        a, b = raw.find("{"), raw.rfind("}")
        if a >= 0 and b > a:
            return json.loads(raw[a:b + 1])
        raise


def _gemini_critic_runs(downscaled_path, prompt, raw_out, key_name=None):
    """Two Gemini passes. Returns (runs, errors, fallback_reason); fallback_reason is set only when a failure is of the
    kind the Qwen fallback exists for (quota / 429 / rate limit / >18MB / stall). key_name picks the ~/alfred/.env key
    gemini_watch.py uses (GEMINI_WATCH_KEY); None = its default, GEMINI_KEY_B."""
    runs, errs, reason = [], [], None
    env = dict(os.environ)
    if key_name:
        env["GEMINI_WATCH_KEY"] = key_name
    for i in range(2):
        cmd = ["python3", GEMINI_WATCH, downscaled_path, prompt, "--json", "--out", raw_out + (".run%d" % (i + 1))]
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=GEMINI_CRITIC_TIMEOUT_S, env=env)
        except subprocess.TimeoutExpired as e:
            se = (e.stderr or b"").decode("utf-8", "replace")
            errs.append(f"gemini_watch.py stalled > {GEMINI_CRITIC_TIMEOUT_S}s and was killed; stderr: {se[-300:]}")
            reason = "Gemini quota exhausted" if GEMINI_FALLBACK_RE.search(se) else "Gemini stalled"
            break
        stdout = p.stdout.decode("utf-8", "replace")
        stderr = p.stderr.decode("utf-8", "replace")
        if p.returncode != 0:
            err = f"gemini_watch.py exited {p.returncode}: {stderr[-500:] or stdout[-500:]}"
            errs.append(err)
            if ">18MB" in err:
                reason = "Gemini refused file >18MB"
                break
            if GEMINI_FALLBACK_RE.search(err):
                reason = "Gemini quota exhausted"
                break                    # the second run would hit the same quota: do not spend another stall on it
            continue
        try:
            runs.append(_parse_critic_json(stdout))
        except json.JSONDecodeError as e:
            errs.append(f"critic response was not valid JSON ({e})")
    return runs, errs, reason


def _groq_lane():
    """Base URL + first key of lane l7-groq, parsed in-process from `fleet env l7-groq`. Values are never printed."""
    import shlex
    p = subprocess.run([os.path.expanduser("~/.fleet/bin/fleet"), "env", "l7-groq"], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=60)
    env = {}
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        try:
            parts = shlex.split(v)
            v = parts[0] if parts else ""
        except ValueError:
            v = v.strip().strip("'\"")
        env[k.strip()] = v
    base = env.get("FLEET_OPENAI_BASE_URL", "").rstrip("/")
    key = (env.get("FLEET_OPENAI_KEYS", "").split(",") or [""])[0].strip()
    return base, key


def _dotenv_values(names):
    """Values of the named ~/alfred/.env keys (CRLF-safe), in order, skipping missing ones. Never printed."""
    e = {}
    try:
        for line in open(os.path.expanduser("~/alfred/.env"), encoding="utf-8", errors="ignore"):
            line = line.strip().replace("\r", "")
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                e[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return [e[n] for n in names if e.get(n)]


def _critic_route(critic):
    """(base_url, [keys]) for a frames critic. Keys are tried in order; values are never printed."""
    if critic["route"] == "groq":
        base, key = _groq_lane()
        return base, [key] if key else []
    if critic["route"] == "openrouter-free":
        if not critic["model"].endswith(":free"):
            raise ValueError("refused: OpenRouter critic model %r is not a :free id (the funded key must never pay)"
                             % critic["model"])
        return "https://openrouter.ai/api/v1", _dotenv_values(["OPENROUTER_KEY_OLD_ACCOUNT", "OPENROUTER_KEY"])
    raise ValueError("unknown critic route %r" % critic["route"])


def _critic_exhausted(cid):
    try:
        d = json.load(open(CRITIC_EXHAUSTED_FILE))
        if time.time() < float(d.get(cid, {}).get("until", 0)):
            return d[cid]
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _mark_critic_exhausted(cid, why):
    try:
        os.makedirs(os.path.dirname(CRITIC_EXHAUSTED_FILE), exist_ok=True)
        try:
            d = json.load(open(CRITIC_EXHAUSTED_FILE))
        except (OSError, ValueError):
            d = {}
        d[cid] = {"until": time.time() + CRITIC_EXHAUSTED_S, "why": why[:200],
                  "at": datetime.datetime.now().isoformat(timespec="seconds")}
        tmp = CRITIC_EXHAUSTED_FILE + ".tmp%d" % os.getpid()
        json.dump(d, open(tmp, "w"), indent=1)
        os.replace(tmp, CRITIC_EXHAUSTED_FILE)
    except OSError:
        pass


def _qwen_frame_times(duration):
    d = max(0.5, float(duration or 0.5))
    ts = [min(0.3, d / 2)] + [d * (i + 0.5) / QWEN_CRITIC_EVEN_FRAMES for i in range(QWEN_CRITIC_EVEN_FRAMES)] \
        + [max(0.0, d - 1.5)]
    return sorted(round(t, 2) for t in ts)


def _mmss(t):
    return "%02d:%04.1f" % (int(t // 60), t % 60)


def _qwen_critic_prompt(groups):
    """groups: one list of frame times per image; each image is a left-to-right strip of those frames."""
    times = [t for g in groups for t in g]
    p = CRITIC_PROMPT.replace("{TODAY}", datetime.date.today().strftime("%d %B %Y"))
    p = p.replace("Watch AND listen to the whole video, then score it.",
                  "You cannot watch or hear this video: you are shown %d still frames sampled from it, in order. "
                  "Score it from those frames." % len(times))
    p = p.replace('"sound_design": <1-10>', '"sound_design": null')
    layout = "; ".join("image %d holds, left to right, the frames at %s" % (i + 1, ", ".join(_mmss(t) for t in g))
                       for i, g in enumerate(groups))
    p += ("\n\nFRAMES-ONLY MODE. You see still frames only: no motion and no audio. Each image is a horizontal strip of "
          "consecutive full frames of the vertical video placed side by side (the seams between frames are not part of "
          "the video): " + layout + ". "
          "Score hook_strength_first_3s, clarity_no_context_needed, story, pacing, visual_quality_and_variety and cta "
          "from what the frames show; judge pacing from how much the picture changes between frames. sound_design MUST "
          "be null because you cannot hear the video. Use these timestamps in problems. Return ONLY the JSON object.")
    return p


def _critic_request(critic, base, key, prompt, jpgs):
    content = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," +
                base64.b64encode(open(j, "rb").read()).decode()}} for j in jpgs]
    content.append({"type": "text", "text": prompt})
    body = {"model": critic["model"], "max_tokens": critic["max_tokens"], "temperature": 0.2,
            "messages": [{"role": "user", "content": content}]}
    body.update(critic.get("extra") or {})
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "content-type": "application/json", "authorization": "Bearer " + key, "user-agent": "alfred-fleet/1.0"})
    # One request per critic at a time machine-wide, gap_s apart (root 28 Sep: 5 gates at once blew Groq's 7,000
    # input-tokens-per-minute limit and S03's check 9 failed on 429 five times). The lock serialises gates.
    import fcntl
    stamp = critic["stamp"]
    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    with open(stamp + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            wait = critic["gap_s"] - (time.time() - os.path.getmtime(stamp))
            if 0 < wait <= critic["gap_s"]:
                time.sleep(wait)
        except OSError:
            pass
        try:
            d = json.load(urllib.request.urlopen(req, timeout=180))
            if "error" in d and not d.get("choices"):
                raise RuntimeError("error body: %s" % str(d["error"])[:300])
            return d["choices"][0]["message"]["content"] or ""
        finally:
            try:
                open(stamp, "w").write(str(time.time()))
            except OSError:
                pass


def _qwen_request(base, key, prompt, jpgs):
    """Kept for callers of the 28 Sep API: the Groq Qwen critic request."""
    return _critic_request(FRAME_CRITICS[0], base, key, prompt, jpgs)


def frames_critic(video, out_dir, reason, critic):
    """Frames-only critic. Returns (parsed_json or None, error or '', meta)."""
    raw_out = os.path.join(out_dir, "%s_critic_raw.txt" % ("qwen" if critic["id"] == "qwen-groq" else critic["id"]))
    duration = probe_info(video).get("duration") or 0
    times = _qwen_frame_times(duration)
    meta = {"critic": critic["id"], "label": critic["label"], "model": critic["model"], "reason": reason,
            "frame_times_s": times, "width_px": QWEN_CRITIC_WIDTH, "raw": raw_out}
    bench = _critic_exhausted(critic["id"])
    if bench:
        return None, "%s benched until %s: out of quota (%s)" % (critic["id"], time.strftime(
            "%H:%M", time.localtime(bench["until"])), bench.get("why", "")), meta
    try:
        base, keys = _critic_route(critic)
    except ValueError as e:
        return None, str(e), meta
    if not base or not keys:
        return None, "%s unavailable: no base URL or key" % critic["id"], meta
    tmp = tempfile.mkdtemp(prefix="frames_critic_")
    try:
        jpgs = []
        for i, t in enumerate(times):
            j = os.path.join(tmp, "f%02d.jpg" % i)
            sh(["ffmpeg", "-v", "error", "-y", "-ss", "%.2f" % t, "-i", video, "-frames:v", "1",
                "-vf", "scale=%d:-2" % QWEN_CRITIC_WIDTH, "-q:v", "4", j])
            if os.path.exists(j) and os.path.getsize(j) > 0:
                jpgs.append((t, j))
        if len(jpgs) < 3:
            return None, "%s: could only extract %d frames from %s" % (critic["id"], len(jpgs), video), meta
        # Groq takes at most 3 images per request, so the 8 frames go as 3 strips (3+3+2), each frame kept 540 px wide,
        # still ONE request. The strip layout is spelled out in the prompt. Every critic gets the identical request.
        k = min(critic["max_images"], len(jpgs))
        sizes = [len(jpgs) // k + (1 if i < len(jpgs) % k else 0) for i in range(k)]
        groups, strips, pos = [], [], 0
        for gi, n in enumerate(sizes):
            part = jpgs[pos:pos + n]; pos += n
            strip = os.path.join(tmp, "strip%d.jpg" % gi)
            if n == 1:
                shutil.copy(part[0][1], strip)
            else:
                cmd = ["ffmpeg", "-v", "error", "-y"]
                for _, j in part:
                    cmd += ["-i", j]
                fc = "".join("[%d:v]scale=%d:-2,pad=iw+8:ih:0:0:white[v%d];" % (x, QWEN_CRITIC_WIDTH, x) for x in range(n)) \
                    + "".join("[v%d]" % x for x in range(n)) + "hstack=inputs=%d[o]" % n
                sh(cmd + ["-filter_complex", fc, "-map", "[o]", "-q:v", "4", strip])
            if not (os.path.exists(strip) and os.path.getsize(strip) > 0):
                return None, "%s: could not build frame strip %d" % (critic["id"], gi), meta
            groups.append([t for t, _ in part]); strips.append(strip)
        attempts, text, last, ki = 0, None, "", 0
        while attempts < critic["attempts"] and text is None and ki < len(keys):
            attempts += 1
            try:
                text = _critic_request(critic, base, keys[ki], _qwen_critic_prompt(groups), strips)
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "replace")[:300]
                last = "HTTP %d: %s" % (e.code, msg)
                if e.code == 429 and CRITIC_DAILY_RE.search(msg):
                    ki += 1              # this key's daily cap: next key at once, never a sleep-retry on a daily cap
                elif e.code in (429, 502, 503, 504):
                    time.sleep(critic["retry_sleep_s"])
                else:
                    break
            except Exception as e:  # network / timeout / bad body
                last = "%s: %s" % (type(e).__name__, str(e)[:300])
                time.sleep(10)
        meta["frames_sent_s"] = [t for g in groups for t in g]
        meta["images_sent"] = [len(g) for g in groups]
        meta["attempts"] = attempts
        meta["key_index"] = ki
        if text is None:
            if ki >= len(keys):
                _mark_critic_exhausted(critic["id"], last)
            return None, "%s failed after %d attempt(s): %s" % (critic["id"], attempts, last), meta
        with open(raw_out, "w") as fh:
            fh.write(text)
        try:
            return _parse_critic_json(text), "", meta
        except json.JSONDecodeError as e:
            return None, "%s critic response was not valid JSON (%s); raw saved to %s" % (critic["id"], e, raw_out), meta
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def qwen_critic(video, out_dir, reason="Gemini quota exhausted"):
    """Frames-only critic on Groq (kept for callers of the 28 Sep API). Returns (parsed_json or None, error, meta)."""
    return frames_critic(video, out_dir, reason, FRAME_CRITICS[0])


def run_check9_gemini_critic(downscaled_path, out_dir):
    raw_out = os.path.join(out_dir, "gemini_critic_raw.txt")
    prompt = CRITIC_PROMPT.replace("{TODAY}", datetime.date.today().strftime("%d %B %Y"))
    # Two independent passes, scores averaged (root, 24 Sep): under gemini-2.5-flash a single pass is
    # noisy (a Sam-approved short's CTA scored 8 under pro and 4 in one flash pass).
    mode = os.environ.get("GATE_CRITIC", "").strip().lower()
    runs, errs, reason = [], [], None
    cached = None
    try:
        age = time.time() - os.path.getmtime(GEMINI_QUOTA_CACHE)
        if age < GEMINI_QUOTA_CACHE_S:
            cached = "Gemini critic hit its quota %d min ago (cache %s); skipped to avoid the retry stall" % (
                age // 60, GEMINI_QUOTA_CACHE)
    except OSError:
        pass
    if mode == "qwen":
        errs, reason = ["GATE_CRITIC=qwen: Gemini not called"], "Gemini quota exhausted"
    elif cached and mode != "gemini":
        errs, reason = [cached], "Gemini quota exhausted"
    else:
        runs, errs, reason = _gemini_critic_runs(downscaled_path, prompt, raw_out)
        if not runs and reason in ("Gemini quota exhausted", "Gemini stalled"):
            try:
                os.makedirs(os.path.dirname(GEMINI_QUOTA_CACHE), exist_ok=True)
                open(GEMINI_QUOTA_CACHE, "w").write(" | ".join(errs)[-600:])
            except OSError:
                pass
    last_err = errs[-1] if errs else ""
    fallback, gemini2 = None, None
    # Chain step 1: Gemini on the second free project. Skipped for GATE_CRITIC=qwen and for a >18MB copy (same cap).
    if not runs and reason in ("Gemini quota exhausted", "Gemini stalled") and mode != "qwen":
        cached2 = None
        try:
            age2 = time.time() - os.path.getmtime(GEMINI2_QUOTA_CACHE)
            if age2 < GEMINI_QUOTA_CACHE_S:
                cached2 = "second Gemini key hit its quota %d min ago (cache %s)" % (age2 // 60, GEMINI2_QUOTA_CACHE)
        except OSError:
            pass
        if cached2:
            errs.append("gemini2: " + cached2)
        elif GEMINI2_KEY_NAME == "GEMINI_API_KEY" or not _dotenv_values([GEMINI2_KEY_NAME]):
            errs.append("gemini2: %s missing from ~/alfred/.env (or refused: GEMINI_API_KEY is the prepay project)"
                        % GEMINI2_KEY_NAME)
        else:
            runs2, errs2, reason2 = _gemini_critic_runs(downscaled_path, prompt, raw_out + ".key2", GEMINI2_KEY_NAME)
            errs.extend("gemini2: " + e for e in errs2)
            if runs2:
                runs, gemini2 = runs2, {"reason": reason}
            elif reason2 in ("Gemini quota exhausted", "Gemini stalled"):
                try:
                    open(GEMINI2_QUOTA_CACHE, "w").write(" | ".join(errs2)[-600:])
                except OSError:
                    pass
    if not runs:
        if not reason or mode == "gemini":
            return check_result("9", "GEMINI CRITIC", "FAIL", last_err or "critic produced no usable run", errs)
        # Chain step 2: the frames-only critics, in measured order. First usable answer wins.
        tried, broken = [], []
        for critic in FRAME_CRITICS:
            parsed_q, qerr, meta = frames_critic(downscaled_path, out_dir, reason, critic)
            if parsed_q is not None:
                runs = [parsed_q]
                fallback = {"reason": reason, "meta": meta, "gemini_errors": errs, "critic": critic,
                            "tried": tried}
                raw_out = meta["raw"]
                break
            tried.append("%s: %s" % (critic["id"], qerr))
            if not CRITIC_UNAVAILABLE_RE.search(qerr or ""):
                broken.append((critic, qerr, meta))
        if fallback is None:
            if not broken:
                # root 28 Sep: every free critic out of quota. Check 9 is an ADVISORY craft opinion; it becomes UNJUDGED
                # (not a pass, not a block). The reviewer's own look decides (craft standard), and root_pass records it.
                g2 = "not called" if mode == "qwen" else next((e[len("gemini2: "):][:80] for e in errs
                                                               if e.startswith("gemini2: ")), "not called")
                return check_result("9", "GEMINI CRITIC", "UNJUDGED",
                                    f"critic UNJUDGED: Gemini ({reason}), second Gemini key ({g2}) and all "
                                    f"{len(FRAME_CRITICS)} frames critics ({', '.join(c['id'] for c in FRAME_CRITICS)}) out "
                                    f"of free quota or unavailable; the reviewer's look decides",
                                    ["gemini: " + e for e in errs] + tried)
            critic, qerr, meta = broken[0]
            return check_result("9", "GEMINI CRITIC", "FAIL",
                                f"Gemini unusable ({reason}) and the frames critics failed: {qerr}",
                                ["gemini: " + e for e in errs] + tried + [f"{critic['id']} meta: {meta}"],
                                evidence=[meta["raw"]] if os.path.exists(meta["raw"]) else [])
    parsed = runs[0]
    keys = set().union(*[set((r.get("scores") or {}).keys()) for r in runs])
    scores = {}
    for k in keys:
        vals = [r["scores"][k] for r in runs if isinstance((r.get("scores") or {}).get(k), (int, float))]
        if vals:
            scores[k] = round(sum(vals) / len(vals), 1)
    parsed["problems"] = sum([r.get("problems", []) for r in runs], [])
    parsed["notes"] = " | ".join(str(r.get("notes", "")) for r in runs if r.get("notes"))
    if fallback is None:
        with open(raw_out, "w") as fh:
            json.dump({"runs": runs, "averaged_scores": scores}, fh, indent=1)
    # Hallucination guard (root, 24 Sep): Gemini scored a silent demo 9/10 for sound and "heard"
    # a robotic TTS voice on another silent file. Only keep sound/voice/audio scores when the
    # file has an audible audio stream with real programme loudness.
    audible = False
    if probe_info(downscaled_path).get("has_audio"):
        lufs, _ = parse_ebur128(run_ebur128(downscaled_path))
        audible = lufs is not None and lufs > -50.0
    discarded = {}
    if not audible or fallback is not None:      # the frames-only fallback never hears anything: sound stays unjudged
        for k in list(scores):
            if re.search(r"sound|audio|voice|music|mix", k, re.I):
                discarded[k] = scores.pop(k)
    low = {k: v for k, v in scores.items() if isinstance(v, (int, float)) and v <= 5}
    status = "FAIL" if low else "PASS"
    details = [f"{k}: {v}" for k, v in scores.items()]
    if gemini2 is not None:
        details.insert(0, f"{GEMINI2_LABEL}: the primary key was unusable ({gemini2['reason']}); a real Gemini watch-and-"
                          f"listen verdict, {len(runs)} run(s) averaged; raw {raw_out}.key2.run*")
        details.extend("gemini: " + e for e in errs)
    if fallback is not None:
        c = fallback["critic"]
        details.insert(0, f"{c['label']} ({fallback['reason']}); sound UNJUDGED; critic {c['id']}, model {c['model']}; "
                          f"frames at {fallback['meta'].get('frames_sent_s')} s, {QWEN_CRITIC_WIDTH} px wide, as {fallback['meta'].get('images_sent')} frames per strip image, one request")
        details.append("sound_design: UNJUDGED (frames-only critic cannot hear the video)")
        details.extend("gemini: " + e for e in fallback["gemini_errors"])
        details.extend("skipped critic " + t for t in fallback["tried"])
    if discarded:
        details.append(f"sound scores discarded ({'frames-only critic' if fallback else 'file has no audible audio'}; "
                       f"critic hallucination guard): {discarded}")
    for prob in parsed.get("problems", [])[:20]:
        details.append(f"problem @ {prob.get('timestamp')}: {prob.get('issue')}")
    if parsed.get("notes"):
        details.append(f"notes: {parsed['notes']}")
    summary = (f"scores ≤ 5 (FAIL threshold): {low}" if low else
               f"all scores > 5 (advisory pass); scores: {scores}")
    if gemini2 is not None:
        summary = f"{GEMINI2_LABEL} (primary: {gemini2['reason']}); " + summary
    if fallback is not None:
        summary = f"{fallback['critic']['label']} ({fallback['reason']}); sound UNJUDGED; " + summary
    return check_result("9", "GEMINI CRITIC", status, summary, details, evidence=[raw_out])


# ---------------------------------------------------------------------------
# Check 10: sameness vs. approved/scheduled videos -----------------------------
# No heavy deps: dHash + a from-scratch DCT-based pHash + a colour histogram,
# all built on ffmpeg (frame extraction) + numpy (everything else) + difflib
# (stdlib, for hook-text similarity).

def sample_frames_rgb(video, n=SAMENESS_SAMPLE_FRAMES, size=SAMENESS_SAMPLE_SIZE):
    """One ffmpeg pass -> exactly n small RGB frames, evenly spaced across the
    video's own duration (fps = n/duration), as (n, size, size, 3) uint8."""
    info = probe_info(video)
    duration = info["duration"] or 1.0
    fps = max(n / duration, 0.1)
    cmd = ["nice", "-n", "15", "ffmpeg", "-threads", "2", "-i", video,
           "-vf", f"fps={fps},scale={size}:{size},format=rgb24",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = sh(cmd)
    raw = p.stdout
    frame_bytes = size * size * 3
    total = len(raw) // frame_bytes
    if total == 0:
        return None
    frames = np.frombuffer(raw[: total * frame_bytes], dtype=np.uint8).reshape(total, size, size, 3)
    if total < n:
        pad = np.repeat(frames[-1:], n - total, axis=0)
        frames = np.concatenate([frames, pad], axis=0)
    elif total > n:
        idx = np.linspace(0, total - 1, n).round().astype(int)
        frames = frames[idx]
    return frames


def _resize_gray_nn(img, out_h, out_w):
    h, w = img.shape
    ys = np.linspace(0, h - 1, out_h).round().astype(int)
    xs = np.linspace(0, w - 1, out_w).round().astype(int)
    return img[np.ix_(ys, xs)]


def dhash_bits(gray):
    """Classic dHash: 9x8 downsample, compare adjacent columns -> 64 bits."""
    small = _resize_gray_nn(gray, 8, 9).astype(np.int16)
    diff = (small[:, 1:] > small[:, :-1]).flatten()
    val = 0
    for b in diff:
        val = (val << 1) | int(b)
    return val


_DCT_CACHE = {}


def _dct_matrix(n):
    if n not in _DCT_CACHE:
        idx = np.arange(n)
        k = idx.reshape(-1, 1)
        _DCT_CACHE[n] = np.cos(np.pi / n * (idx + 0.5) * k)
    return _DCT_CACHE[n]


def phash_bits(gray):
    """From-scratch pHash: 2D DCT-II via matrix multiplication (no scipy/PIL),
    keep the top-left 8x8 low-frequency block, threshold vs. its own median
    (excluding the DC term) -> 64 bits. Consistency across images (same
    transform applied identically) is what matters for Hamming comparison,
    not perfect orthonormal DCT scaling."""
    img = gray.astype(np.float64)
    m = _dct_matrix(img.shape[0])
    d = m @ img @ m.T
    block = d[:8, :8].flatten()
    median = np.median(block[1:])  # exclude DC (index 0) from the threshold
    bits = block > median
    val = 0
    for b in bits:
        val = (val << 1) | int(b)
    return val


def hamming(a, b):
    return bin(a ^ b).count("1")


def palette_hist(frame_rgb, bins=4):
    idx = (frame_rgb.astype(np.int32) * bins // 256).clip(0, bins - 1)
    flat = idx[..., 0] * bins * bins + idx[..., 1] * bins + idx[..., 2]
    hist = np.bincount(flat.flatten(), minlength=bins ** 3).astype(np.float64)
    total = hist.sum()
    return (hist / total) if total > 0 else hist


def video_visual_signature(video):
    frames = sample_frames_rgb(video)
    if frames is None:
        return None
    grays = frames.astype(np.float64).mean(axis=3)
    dhashes = [int(dhash_bits(g)) for g in grays]
    phashes = [int(phash_bits(g)) for g in grays]
    hists = [palette_hist(f) for f in frames]
    avg_hist = np.mean(hists, axis=0)
    return {"dhashes": dhashes, "phashes": phashes, "palette": avg_hist.tolist()}


def compare_visual(sig_a, sig_b):
    n = min(len(sig_a["dhashes"]), len(sig_b["dhashes"]))
    dh = float(np.mean([hamming(sig_a["dhashes"][i], sig_b["dhashes"][i]) / 64.0 for i in range(n)]))
    ph = float(np.mean([hamming(sig_a["phashes"][i], sig_b["phashes"][i]) / 64.0 for i in range(n)]))
    pa_raw = float(np.linalg.norm(np.array(sig_a["palette"]) - np.array(sig_b["palette"])))
    pa = min(pa_raw / math.sqrt(2), 1.0)  # sqrt(2) = max L2 distance between two disjoint unit histograms
    combined_dist = 0.4 * dh + 0.4 * ph + 0.2 * pa
    return {"dhash_dist": dh, "phash_dist": ph, "palette_dist": pa, "similarity": 1.0 - combined_dist}


def text_similarity(a, b):
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def derive_hook_text(script_path, timed_sources, window_s=SAMENESS_HOOK_WINDOW_S):
    """Spoken hook (script's first non-empty line) + all on-screen/caption text
    starting inside the first `window_s` seconds, concatenated into one string."""
    lines = [l for _, l in load_script_lines(script_path)] if script_path else []
    spoken = lines[0] if lines else ""
    onscreen = []
    for items in timed_sources:
        onscreen += [i["text"] for i in items if i["start"] < window_s]
    return " ".join([spoken] + onscreen).strip()


def sidecar_path_for(video_path):
    return os.path.splitext(video_path)[0] + ".sidecar.json"


def list_window_approved(compare_dir, window):
    os.makedirs(compare_dir, exist_ok=True)
    entries = []
    for f in os.listdir(compare_dir):
        if not f.lower().endswith(".mp4"):
            continue
        vp = os.path.join(compare_dir, f)
        sc_path = sidecar_path_for(vp)
        sidecar = {}
        if os.path.exists(sc_path):
            try:
                sidecar = json.load(open(sc_path, encoding="utf-8"))
            except json.JSONDecodeError:
                sidecar = {}
        entries.append({"video": vp, "mtime": os.path.getmtime(vp), "sidecar": sidecar})
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return entries[:window]


def run_check10_sameness(video, script_path, captions_items, onscreen_items, ocr_items, args):
    compare_dir = args.compare_dir
    os.makedirs(compare_dir, exist_ok=True)
    window_entries = list_window_approved(compare_dir, args.window)

    # Always derive the candidate's own signature/hook, even when the approved
    # pool is empty -- --register needs both regardless of whether check10 had
    # anything to compare against (a video's own sidecar must never be blank
    # just because it happened to be the first one registered).
    candidate_sig = video_visual_signature(video)
    candidate_hook = derive_hook_text(script_path, [captions_items, onscreen_items, ocr_items])

    if not window_entries:
        return check_result(
            "10", "SAMENESS (vs approved/scheduled)", "PASS",
            f"no approved videos yet in {compare_dir} -- nothing to compare against",
            [f"compare-dir: {compare_dir}", f"window: {args.window}"],
        ), candidate_sig, candidate_hook

    visual_matches = []
    for e in window_entries:
        sig = e["sidecar"].get("signature")
        if not sig:
            sig = video_visual_signature(e["video"])  # older/manually-added approved video, no sidecar signature
        if not sig or candidate_sig is None:
            continue
        visual_matches.append((os.path.basename(e["video"]), compare_visual(candidate_sig, sig)))
    visual_matches.sort(key=lambda m: -m[1]["similarity"])
    closest_name, closest_cmp = visual_matches[0] if visual_matches else (None, None)

    hook_matches = [(os.path.basename(e["video"]), text_similarity(candidate_hook, e["sidecar"].get("hook", "")))
                     for e in window_entries]
    hook_matches.sort(key=lambda m: -m[1])
    closest_hook_name, closest_hook_sim = hook_matches[0] if hook_matches else (None, 0.0)

    last3 = window_entries[:3]
    bed_fail = None
    if args.bed:
        for e in last3:
            if e["sidecar"].get("music_bed") and e["sidecar"]["music_bed"] == args.bed:
                bed_fail = os.path.basename(e["video"])
                break

    look_fail = None
    prev_same_platform = None
    if args.platform:
        for e in window_entries:  # most-recent-first
            if e["sidecar"].get("platform") == args.platform:
                prev_same_platform = e
                break
        if prev_same_platform and args.look and prev_same_platform["sidecar"].get("look") == args.look:
            look_fail = os.path.basename(prev_same_platform["video"])

    fails = []
    if closest_cmp and closest_cmp["similarity"] > VISUAL_SIM_FAIL_THRESHOLD:
        fails.append(f"visual similarity to {closest_name} = {closest_cmp['similarity']:.3f} "
                      f"> {VISUAL_SIM_FAIL_THRESHOLD} threshold")
    if closest_hook_sim > HOOK_TEXT_SIM_FAIL_THRESHOLD:
        fails.append(f"hook-text similarity to {closest_hook_name} = {closest_hook_sim:.3f} "
                      f"> {HOOK_TEXT_SIM_FAIL_THRESHOLD} threshold")
    if bed_fail:
        fails.append(f"same music bed '{args.bed}' as {bed_fail} (within the last 3 approved)")
    if look_fail:
        fails.append(f"same look '{args.look}' as the immediately previous approved video "
                      f"on platform '{args.platform}' ({look_fail})")

    status = "FAIL" if fails else "PASS"
    details = [
        f"compare-dir: {compare_dir} | window: {args.window} | approved videos found: {len(window_entries)}",
        f"visual similarity threshold (calibrated, see selftest_sameness.py): {VISUAL_SIM_FAIL_THRESHOLD}",
        (f"closest visual match: {closest_name} -> similarity {closest_cmp['similarity']:.3f} "
         f"(dhash_dist={closest_cmp['dhash_dist']:.3f} phash_dist={closest_cmp['phash_dist']:.3f} "
         f"palette_dist={closest_cmp['palette_dist']:.3f})") if closest_cmp else "no visual signatures available to compare",
        f"candidate hook text: \"{candidate_hook[:150]}\"",
        (f"closest hook-text match: {closest_hook_name} -> similarity {closest_hook_sim:.3f} "
         f"(threshold {HOOK_TEXT_SIM_FAIL_THRESHOLD})") if closest_hook_name else "no stored hooks to compare",
        ("music bed check (last 3): FAIL vs " + bed_fail) if bed_fail else
        ("music bed check (last 3): no match" if args.bed else "music bed check: no --bed given, skipped"),
        ("look check (immediately-previous, same platform): FAIL vs " + look_fail) if look_fail else
        ("look check (immediately-previous, same platform): no match" if (args.platform and prev_same_platform)
         else "look check: no --platform/--look given or no prior approved video on that platform, skipped"),
    ]
    summary = "; ".join(fails) if fails else "no sameness violations vs. the approved window"
    return check_result("10", "SAMENESS (vs approved/scheduled)", status, summary, details), candidate_sig, candidate_hook


def register_approved(video, args, candidate_sig, candidate_hook):
    os.makedirs(args.compare_dir, exist_ok=True)
    # unique name per video (root fix, 24 Sep: every pilot is FINAL.mp4, so basenames overwrote each other)
    vid_id = getattr(args, "video_id", None) or os.path.basename(os.path.dirname(os.path.abspath(video)))
    dest_video = os.path.join(args.compare_dir, "%s__%s" % (vid_id, os.path.basename(video)))
    shutil.copy2(video, dest_video)
    if candidate_sig is None:
        candidate_sig = video_visual_signature(video)
    sidecar = {
        "video": os.path.basename(dest_video),
        "id": vid_id,
        "hook": candidate_hook or "",
        "look": args.look or "",
        "music_bed": args.bed or "",
        "format": args.format or "",
        "platform": args.platform or "",
        "registered_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "signature": candidate_sig,
    }
    json.dump(sidecar, open(sidecar_path_for(dest_video), "w"), indent=1)
    return dest_video


# ---------------------------------------------------------------------------
def write_markdown(out_dir, video, kind, results, overall):
    path = os.path.join(out_dir, "GATE.md")
    lines = [f"# GATE report: {os.path.basename(video)}", "",
             f"- kind: {kind}",
             f"- generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- overall: **{overall}**", "",
             "| # | Check | Status | Summary |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {r['name']} | {r['status']} | {r['summary']} |")
    lines.append("")
    for r in results:
        lines.append(f"## {r['id']}. {r['name']} — {r['status']}")
        lines.append(r["summary"])
        for d in r["details"]:
            lines.append(f"- {d}")
        lines.append("")
    open(path, "w").write("\n".join(lines))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--script", required=True)
    ap.add_argument("--captions")
    ap.add_argument("--onscreen")
    ap.add_argument("--kind", choices=["short", "long"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--compare-dir", dest="compare_dir", default=DEFAULT_COMPARE_DIR,
                     help=f"pool of approved/scheduled videos to check sameness against "
                          f"(default: {DEFAULT_COMPARE_DIR}, created if missing)")
    ap.add_argument("--window", type=int, default=SAMENESS_WINDOW_DEFAULT,
                     help="compare against the last N approved videos by modified time")
    ap.add_argument("--register", action="store_true",
                     help="after gating, copy this video + a sidecar (hook/look/bed/format) "
                          "into --compare-dir so future runs compare against it")
    ap.add_argument("--video-id", dest="video_id", default=None, help="unique id used when registering into the approved pool")
    ap.add_argument("--look", help="this video's look/art-direction name (for sameness check 10d + sidecar)")
    ap.add_argument("--platform", help="this video's target platform (for sameness check 10d + sidecar)")
    ap.add_argument("--bed", help="this video's music bed id (for sameness check 10c + sidecar)")
    ap.add_argument("--format", help="this video's format/template name (stored in the sidecar)")
    ap.add_argument("--lint-exceptions", dest="lint_exceptions", default=None,
                     help="per-short exemptions (exact OCR strings + reason); default: lint-exceptions.json beside the video")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    # One gate per out dir. On 26 Sep an orphaned S20 gate and its restart wrote into the same r3 for 30 minutes,
    # and a GATE.json from either could have described a mix of both runs.
    lock = os.path.join(args.out, ".gate.lock")
    try:
        other = int(open(lock).read().strip() or 0)
        os.kill(other, 0)
        if other != os.getpid():
            sys.exit(f"gate.py: another gate (pid {other}) is writing {args.out}; wait for it or stop it first")
    except (FileNotFoundError, ValueError, ProcessLookupError):
        pass
    open(lock, "w").write(str(os.getpid()))
    import atexit
    atexit.register(lambda: os.path.exists(lock) and open(lock).read().strip() == str(os.getpid()) and os.remove(lock))
    info = probe_info(args.video)

    kind = args.kind
    if not kind:
        kind = "short" if (info["width"] and info["height"] and info["height"] > info["width"]) else "long"

    captions_items = load_timed(args.captions) if args.captions else []
    onscreen_supplied = load_timed(args.onscreen) if args.onscreen else []

    downscaled_path = os.path.join(args.out, "downscaled_for_gemini.mp4")
    ds_ok, ds_err = make_downscaled_copy(args.video, downscaled_path)

    results = []
    r2, ocr_items = ([], [])
    if ds_ok:
        r2, ocr_items = run_check2_ocr(args.video, info, downscaled_path, args.out, onscreen_supplied, args.lint_exceptions,
                                       platform=args.platform, video_id=args.video_id)
    else:
        r2 = check_result("2", "OCR ON-SCREEN TEXT LINT", "FAIL", f"could not build downscaled copy for OCR: {ds_err[-300:]}")

    results.append(run_check1_text_lints(
        args.script, captions_items, onscreen_supplied,
        load_lint_exceptions(args.video, args.lint_exceptions),
    ))
    results.append(r2)
    results.append(run_check3_static_hold(args.video, kind, args.out))
    results.append(run_check4_loudness(args.video, info, args.out))
    results.append(run_check5_hook(args.video, info, captions_items, onscreen_supplied, ocr_items))
    results.append(run_check6_cta(info, args.script, captions_items))
    results.append(run_check7_format(info, kind))
    results.append(run_check8_contact_sheets(args.video, info, args.out))
    if ds_ok:
        results.append(run_check9_gemini_critic(downscaled_path, args.out))
    else:
        results.append(check_result("9", "GEMINI CRITIC", "FAIL", f"could not build downscaled copy for critic: {ds_err[-300:]}"))

    r10, candidate_sig, candidate_hook = run_check10_sameness(
        args.video, args.script, captions_items, onscreen_supplied, ocr_items, args)
    results.append(r10)

    overall = "FAIL" if any(r["status"] == "FAIL" for r in results) else \
              ("WARN" if any(r["status"] == "WARN" for r in results) else "PASS")

    if args.register:
        dest = register_approved(args.video, args, candidate_sig, candidate_hook)
        print(f"registered {dest} + sidecar into {args.compare_dir}")

    payload = {
        "video": args.video, "kind": kind, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "probe": info, "overall": overall, "checks": results,
    }
    json.dump(payload, open(os.path.join(args.out, "GATE.json"), "w"), indent=1)
    md_path = write_markdown(args.out, args.video, kind, results, overall)

    print(f"overall: {overall}")
    print(f"wrote {os.path.join(args.out, 'GATE.json')} and {md_path}")
    sys.exit(0 if overall != "FAIL" else 1)


if __name__ == "__main__":
    main()
