#!/usr/bin/env python3
"""Ubuntu runner utility: bind an exact PCM WAV to frozen S83 word timing JSON."""
import argparse
import hashlib
import json
import os
import wave
from pathlib import Path


def inspect_wav(path: Path) -> tuple[str, float, int, int, int, int]:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    with wave.open(str(path), "rb") as audio:
        frames = audio.getnframes()
        rate = audio.getframerate()
        channels = audio.getnchannels()
        width = audio.getsampwidth()
        compression = audio.getcomptype()
        if frames <= 0 or rate <= 0 or channels <= 0 or width <= 0:
            raise ValueError("WAV has invalid stream parameters")
        if compression != "NONE" or channels not in (1, 2) or width not in (2, 3, 4) or not 16000 <= rate <= 96000:
            raise ValueError("source WAV must be 16–96 kHz, mono/stereo, 16/24/32-bit PCM")
        return digest.hexdigest(), frames / rate, frames, rate, channels, width


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", required=True, type=Path)
    parser.add_argument("--timings", type=Path, default=Path("CANONICAL-WORD-TIMINGS.json"))
    parser.add_argument("--protected-inputs", type=Path, default=Path("PROTECTED-INPUTS.json"))
    parser.add_argument("--expected-duration", type=float, default=56.523)
    parser.add_argument("--duration-tolerance", type=float, default=0.050)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit("refusing programme-media validation outside a GitHub-hosted Linux Actions runner")

    protected = json.loads(args.protected_inputs.read_text())
    if protected.get("schema") != "agmm-s83-protected-inputs-v1" or protected.get("repository") != "agmmltd-arch/agmm-video-render":
        raise ValueError("protected input manifest identity mismatch")
    voice_rows = [x for x in protected.get("assets", []) if x.get("name") == "S83.wav"]
    if len(voice_rows) != 1:
        raise ValueError("protected input manifest must bind exactly one S83.wav")
    voice = voice_rows[0]
    expected_sha = str(voice.get("digest", "")).removeprefix("sha256:")
    expected_size = voice.get("size")
    if len(expected_sha) != 64 or any(c not in "0123456789abcdef" for c in expected_sha) or not isinstance(expected_size, int):
        raise ValueError("protected voice asset digest/size is invalid")

    timing_bytes = args.timings.read_bytes()
    timing_sha = hashlib.sha256(timing_bytes).hexdigest()
    timing_doc = json.loads(timing_bytes)
    words = timing_doc.get("words")
    if not isinstance(words, list) or not words:
        raise ValueError("timing JSON must contain a non-empty words list")
    last_end = 0.0
    for i, item in enumerate(words, 1):
        if not isinstance(item, dict) or not isinstance(item.get("word"), str):
            raise ValueError(f"word entry {i} has invalid shape")
        start, end = item.get("start"), item.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise ValueError(f"word entry {i} has non-numeric bounds")
        if start < 0 or end <= start or start > args.expected_duration or end > args.expected_duration + args.duration_tolerance:
            raise ValueError(f"word entry {i} falls outside the expected source clock")
        last_end = max(last_end, float(end))

    audio_sha, duration, frames, rate, channels, width = inspect_wav(args.wav)
    actual_size = args.wav.stat().st_size
    if audio_sha != expected_sha:
        raise ValueError("WAV SHA256 does not match protected release asset digest")
    if actual_size != expected_size:
        raise ValueError("WAV byte length does not match protected release asset size")
    if abs(duration - args.expected_duration) > args.duration_tolerance:
        raise ValueError(f"WAV duration {duration:.6f}s outside expected window")
    if last_end > duration + args.duration_tolerance:
        raise ValueError("timed words extend past decoded WAV duration")
    receipt = {
        "schema": "agmm-s83-hosted-source-clock-receipt-v1",
        "status": "TECHNICAL_SOURCE_BINDING_PASS_AUDIO_REVIEW_REQUIRED",
        "runner_policy": "Ubuntu GitHub Actions only; do not invoke on Mac programme media",
        "audio": {"logical_path": "inputs/S83.wav", "protected_release_id": protected["release_id"], "input_asset_id": voice["id"], "bytes": actual_size, "sha256": audio_sha, "duration_seconds": round(duration, 6), "frames": frames, "sample_rate_hz": rate, "channels": channels, "sample_width_bytes": width, "encoding": "PCM"},
        "timings": {"logical_path": args.timings.name, "sha256": timing_sha, "word_count": len(words), "last_word_end_seconds": round(last_end, 6)},
        "expected_duration_seconds": args.expected_duration,
        "duration_tolerance_seconds": args.duration_tolerance,
        "audio_review": "NOT_PERFORMED_BY_VALIDATOR",
        "timing_anomalies": "Preserve and review; validator does not repair word labels or times"
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
