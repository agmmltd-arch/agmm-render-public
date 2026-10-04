#!/usr/bin/env python3
"""Fail-closed hosted motion proof verifier; records metadata, never hashes media."""
import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def reject(message):
    raise SystemExit(f"FAIL {message}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--probe", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    if a.repo != "agmmltd-arch/agmm-render-public":
        reject("wrong repository")
    if not re.fullmatch(r"[0-9a-f]{40}", a.source_sha):
        reject("source commit is missing or malformed")
    video = Path(a.video)
    if not video.is_file() or video.stat().st_size == 0:
        reject("render output is missing or empty")
    data = json.loads(Path(a.probe).read_text())
    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if len(video_streams) != 1 or audio_streams:
        reject("expected exactly one video stream and no audio stream")
    stream = video_streams[0]
    if (stream.get("width"), stream.get("height")) != (1920, 1080):
        reject("expected 1920x1080")
    if stream.get("r_frame_rate") != "30/1":
        reject("expected exactly 30 fps")
    if int(stream.get("nb_read_frames", "-1")) != 360:
        reject("expected a full 360 decoded frames")
    duration = float(data.get("format", {}).get("duration", "0"))
    if abs(duration - 12.0) > 0.04:
        reject(f"expected 12-second duration, got {duration}")
    decode = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-i", str(video), "-f", "null", "-"], capture_output=True, text=True)
    if decode.returncode:
        reject("full decode reported errors")
    manifest = {
        "status": "HOSTED_RENDER_AND_DECODE_PASS",
        "scope": "silent 12-second 1920x1080 30 fps diagnostic preview; not full film or release approval",
        "repository": a.repo,
        "source_commit": a.source_sha,
        "video_file": video.name,
        "video_bytes": video.stat().st_size,
        "video_hash": "not computed by request",
        "width": stream["width"],
        "height": stream["height"],
        "frame_rate": stream["r_frame_rate"],
        "decoded_frame_count": int(stream["nb_read_frames"]),
        "duration_seconds": duration,
        "audio_streams": len(audio_streams),
        "full_ffmpeg_decode": "PASS",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    Path(a.output).write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
