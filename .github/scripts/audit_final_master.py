#!/usr/bin/env python3
"""Audit an existing hosted F07 review master without retaining the video.

Mirrors the production long-form static-hold detector exactly: 10 fps,
320-pixel greyscale frames, <0.4% frame delta is static, >2.5 seconds fails.
The workflow uploads only the JSON report and small evidence stills.
"""
import argparse
import json
import re
import statistics
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


FPS = 10
WIDTH = 320
HEIGHT = 180
DIFF_THRESHOLD_PCT = 0.4
MAX_STATIC_SECONDS = 2.5


def run(cmd, *, check=True):
    p = subprocess.run(cmd, text=True, capture_output=True)
    if check and p.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr[-2000:]}")
    return p


def probe(video):
    p = run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,pix_fmt,r_frame_rate,channels,sample_rate",
        "-of", "json", str(video),
    ])
    return json.loads(p.stdout)


def decode_static_frames(video):
    cmd = [
        "ffmpeg", "-hide_banner", "-v", "error", "-threads", "2", "-i", str(video),
        "-an", "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}:flags=area,format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frames = []
    frame_bytes = WIDTH * HEIGHT
    while True:
        raw = p.stdout.read(frame_bytes)
        if not raw:
            break
        if len(raw) != frame_bytes:
            p.kill()
            raise RuntimeError(f"truncated raw frame: {len(raw)} of {frame_bytes} bytes")
        frames.append(np.frombuffer(raw, dtype=np.uint8).reshape(HEIGHT, WIDTH).copy())
    stderr = p.stderr.read().decode("utf-8", "replace")
    if p.wait() != 0:
        raise RuntimeError(f"static decode failed: {stderr[-2000:]}")
    if len(frames) < 2:
        raise RuntimeError("static decode returned fewer than two frames")
    return np.stack(frames)


def static_spans(frames):
    a = frames.astype(np.int16)
    diffs = [float(np.abs(a[i] - a[i - 1]).mean() / 255.0 * 100.0)
             for i in range(1, len(a))]
    spans, start = [], None
    for i, delta in enumerate(diffs):
        t = i / FPS
        if delta < DIFF_THRESHOLD_PCT:
            if start is None:
                start = t
        elif start is not None:
            spans.append((start, t, t - start))
            start = None
    if start is not None:
        end = len(diffs) / FPS
        spans.append((start, end, end - start))
    return spans, diffs


def loudness(video):
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-threads", "2", "-i", str(video),
             "-af", "ebur128=peak=true", "-f", "null", "-"], check=False)
    text = p.stderr
    summaries = list(re.finditer(r"Summary:\s*(.*?)(?=\n\s*Summary:|\Z)", text, re.S))
    block = summaries[-1].group(1) if summaries else text[-8000:]
    im = re.search(r"I:\s*(-?[0-9.]+)\s*LUFS", block)
    pm = re.search(r"Peak:\s*(-?[0-9.]+)\s*dBFS", block)
    return {"integrated_lufs": float(im.group(1)) if im else None,
            "true_peak_dbtp": float(pm.group(1)) if pm else None,
            "ffmpeg_exit": p.returncode}


def still(video, at, out):
    run(["ffmpeg", "-hide_banner", "-v", "error", "-ss", f"{at:.3f}", "-i", str(video),
         "-frames:v", "1", "-vf", "scale=1280:720:flags=lanczos", "-q:v", "3", "-y", str(out)])


def contact_sheet(paths, out):
    if not paths:
        return None
    cols = 3
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 640, rows * 390), "#101820")
    draw = ImageDraw.Draw(sheet)
    for i, path in enumerate(paths):
        im = Image.open(path).convert("RGB").resize((640, 360))
        x, y = (i % cols) * 640, (i // cols) * 390
        sheet.paste(im, (x, y + 30))
        draw.text((x + 10, y + 8), path.stem, fill="white")
    sheet.save(out, quality=90, optimize=True)
    return out.name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--expected-duration", required=True, type=float)
    ap.add_argument("--source-run-id", required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    info = probe(a.video)
    duration = float(info["format"]["duration"])
    streams = info["streams"]
    video_stream = next(s for s in streams if s.get("codec_type") == "video")
    audio_stream = next(s for s in streams if s.get("codec_type") == "audio")
    profile_ok = (video_stream.get("codec_name") == "h264" and video_stream.get("width") == 1920
                  and video_stream.get("height") == 1080 and video_stream.get("pix_fmt") == "yuv420p"
                  and video_stream.get("r_frame_rate") == "30/1" and audio_stream.get("codec_name") == "aac")
    duration_ok = abs(duration - a.expected_duration) <= 0.08
    run(["ffmpeg", "-hide_banner", "-v", "error", "-threads", "2", "-i", str(a.video), "-f", "null", "-"])
    frames = decode_static_frames(a.video)
    spans, diffs = static_spans(frames)
    bad = [s for s in spans if s[2] > MAX_STATIC_SECONDS]
    evidence = []
    for i, (start, end, length) in enumerate(bad):
        path = a.out / f"static-{i + 1:02d}-{start:.1f}-{end:.1f}.jpg"
        still(a.video, (start + end) / 2, path)
        evidence.append(path)
    loud = loudness(a.video)
    loud_ok = (loud["ffmpeg_exit"] == 0 and loud["integrated_lufs"] is not None
               and -15.0 <= loud["integrated_lufs"] <= -13.0
               and loud["true_peak_dbtp"] is not None and loud["true_peak_dbtp"] <= -1.0)
    report = {
        "kind": "hosted_existing_master_audit", "source_run_id": a.source_run_id,
        "video_retained_in_artifact": False, "probe": info, "duration_seconds": duration,
        "expected_duration_seconds": a.expected_duration, "profile_pass": profile_ok,
        "duration_pass": duration_ok, "full_decode_pass": True,
        "static_detector": {
            "sample_fps": FPS, "sample_width": WIDTH,
            "diff_threshold_pct": DIFF_THRESHOLD_PCT, "max_span_seconds": MAX_STATIC_SECONDS,
            "decoded_frames": len(frames), "span_count": len(spans),
            "bad_spans": [{"start": round(x, 2), "end": round(y, 2), "duration": round(z, 2)}
                          for x, y, z in bad],
            "diff_pct": {"min": round(min(diffs), 4), "median": round(statistics.median(diffs), 4),
                         "max": round(max(diffs), 4)}, "pass": not bad,
        },
        "audio": {**loud, "pass": loud_ok},
        "evidence_stills": [p.name for p in evidence],
        "contact_sheet": contact_sheet(evidence, a.out / "STATIC-FAIL-CONTACT-SHEET.jpg"),
        "technical_pass": bool(profile_ok and duration_ok and not bad and loud_ok),
        "editorial_gate": "NOT_RUN", "release_approval": "NOT_GRANTED",
    }
    (a.out / "FINAL-MASTER-AUDIT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"technical_pass": report["technical_pass"], "bad_static_spans": len(bad),
                      "duration": duration, "loudness": loud}))
    return 0 if report["technical_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
