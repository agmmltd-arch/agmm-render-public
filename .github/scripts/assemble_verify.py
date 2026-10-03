#!/usr/bin/env python3
"""Hosted-runner-only mechanical join/probe/decode for the existing AGMM film matrix workflow.

No editorial gate is run here. Exit 0 means only that segment set, stream-copy join,
1080 derived copy, probes and full decode checks passed. It is not release approval.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys

FLICKER_LIMIT = 5.0
LOUDNESS_MIN_LUFS = -15.0
LOUDNESS_MAX_LUFS = -13.0

FPS = 30
W4K, H4K = 3840, 2160

# Film-specific settings - only F02 and F07 explicitly allowed
# TRUE_PEAK_MAX_DBTP: both use -1.0 unless authoritative source contract overrides
# MASTER_GAIN_DB: must come from authoritative package contract, not invented
FID_SPECIFIC_SETTINGS = {
    "F02": {"TRUE_PEAK_MAX_DBTP": -1.0, "MASTER_GAIN_DB": 0.0},
    "F07": {"TRUE_PEAK_MAX_DBTP": -1.0, "MASTER_GAIN_DB": -0.5},
}


def require_hosted_media() -> None:
    """Refuse before any media read/write or subprocess on the operator's Mac."""
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("media IO requires Linux GitHub Actions; no local workaround")


def run(cmd: list[str], *, capture: bool = False) -> str:
    require_hosted_media()
    p = subprocess.run(cmd, check=False, text=True, stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None)
    if p.returncode:
        err = (p.stderr or "")[-4000:] if capture else ""
        raise RuntimeError(f"command failed ({p.returncode}): {cmd[0]} {' '.join(cmd[1:5])}\n{err}")
    return p.stdout if capture else ""


def manifest(raw: str, duration: float) -> list[dict]:
    segs = json.loads(raw)
    if not isinstance(segs, list) or not segs:
        raise ValueError("segments must be a non-empty JSON list")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0 or not math.isfinite(duration):
        raise ValueError("duration must be finite")
    expected_n = int(math.floor(duration / 8.6 + 1e-9))
    if len(segs) != expected_n:
        raise ValueError(f"segment count {len(segs)} != expected {expected_n} from duration {duration}")
    cursor = 0.0
    out = []
    for index, row in enumerate(segs, 1):
        sid = f"{index:02d}"
        if not isinstance(row, dict) or row.get("i") != sid:
            raise ValueError(f"segment IDs must be contiguous: expected {sid}")
        if any(isinstance(row.get(k), bool) or not isinstance(row.get(k), (int, float)) for k in ("t0", "len")):
            raise ValueError(f"segment {sid} t0/len must be actual numbers, not bools or strings")
        t0, length = float(row["t0"]), float(row["len"])
        if not math.isfinite(t0) or not math.isfinite(length):
            raise ValueError(f"segment {sid} t0/len must be finite")
        if abs(t0 - cursor) > 0.002 or length <= 0:
            raise ValueError(f"segment {sid} has a gap/overlap or invalid length")
        frames = int(round(length * FPS))
        if frames <= 0:
            raise ValueError(f"segment {sid} has no expected frames")
        out.append({"i": sid, "t0": t0, "len": length, "frames": frames})
        cursor = round(t0 + length, 3)
    if abs(cursor - duration) > 0.01:
        raise ValueError(f"segments cover {cursor}s, composition is {duration}s")
    if sum(x["frames"] for x in out) != int(round(duration * FPS)):
        raise ValueError("rounded segment frame totals do not match full composition")
    return out


def sha256(path: Path) -> str:
    require_hosted_media()
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def probe(path: Path, *, count: bool = True) -> dict:
    require_hosted_media()
    args = ["ffprobe", "-v", "error"]
    if count:
        args += ["-count_packets"]
    args += ["-show_streams", "-show_format", "-of", "json", str(path)]
    return json.loads(run(args, capture=True))


def video_stream(info: dict) -> dict:
    return next(s for s in info["streams"] if s.get("codec_type") == "video")


def codec_key(s: dict) -> tuple:
    return (s.get("codec_name"), s.get("profile"), s.get("width"), s.get("height"),
            s.get("pix_fmt"), s.get("r_frame_rate"), s.get("time_base"), s.get("level"))


def flicker_from_means(means: list[float]) -> tuple[int, float]:
    isolated = sum(1 for i in range(1, len(means)-1)
                   if (means[i]-means[i-1])*(means[i]-means[i+1]) > 0
                   and min(abs(means[i]-means[i-1]), abs(means[i]-means[i+1])) > 8)
    return isolated, 100.0 * isolated / max(1, len(means))


def flicker_from_decoded_video(path: Path, expected_frames: int) -> dict:
    # Same metric and 64x36 grayscale scale as render_codespace_film.flicker, streamed on the runner.
    require_hosted_media()
    p = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-i", str(path),
                        "-vf", "scale=64:36,format=gray", "-f", "rawvideo", "-"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(f"full video decode failed for {path.name}: {p.stderr.decode(errors='replace')[-2000:]}")
    frame_bytes = 64 * 36
    if len(p.stdout) % frame_bytes:
        raise ValueError(f"partial decoded frame output for {path.name}")
    means = [sum(p.stdout[i:i+frame_bytes]) / frame_bytes for i in range(0, len(p.stdout), frame_bytes)]
    if len(means) != expected_frames:
        raise ValueError(f"decoded {len(means)} frames from {path.name}, expected {expected_frames}")
    isolated, pct = flicker_from_means(means)
    return {"decoded_frames": len(means), "isolated_frames": isolated,
            "isolated_pct": round(pct, 2), "limit_pct": FLICKER_LIMIT,
            "status": "PASS" if pct <= FLICKER_LIMIT else "FAIL"}


def check_segment(path: Path, expected_frames: int) -> dict:
    require_hosted_media()
    info = probe(path)
    v = video_stream(info)
    packets = int(v.get("nb_read_packets", 0))
    if (v.get("codec_name") != "h264" or v.get("width") != W4K or v.get("height") != H4K
            or v.get("pix_fmt") != "yuv420p" or v.get("r_frame_rate") != "30/1" or packets != expected_frames):
        raise ValueError(f"segment failed 4K/frame probe: {v}; expected {expected_frames}")
    flicker = flicker_from_decoded_video(path, expected_frames)
    if flicker["status"] != "PASS":
        raise ValueError(f"segment flicker failed: {flicker}")
    return {"status": "PASS", "width": W4K, "height": H4K, "fps": "30/1", "frames": packets,
            "bytes": path.stat().st_size, "sha256": sha256(path), "full_decode": "PASS", "flicker": flicker}


def decode(path: Path) -> None:
    # -xerror makes any decode warning fatal. Null mux decodes all mapped audio/video without writing media.
    require_hosted_media()
    run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-i", str(path),
         "-map", "0:v:0", "-map", "0:a:0?", "-f", "null", "-"])


def measure_audio(path: Path) -> dict:
    """Read integrated loudness and true peak from an audio stream with FFmpeg loudnorm analysis."""
    require_hosted_media()
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", str(path),
                        "-map", "0:a:0", "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
                        "-f", "null", "-"], check=False, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(f"audio measurement failed for {path.name}: {p.stderr[-2000:]}")
    matches = re.findall(r'\{\s*"input_i".*?\}', p.stderr, flags=re.DOTALL)
    if not matches:
        raise ValueError(f"FFmpeg loudnorm did not return input measurements for {path.name}")
    data = json.loads(matches[-1])
    integrated = float(data["input_i"])
    true_peak = float(data["input_tp"])
    if not math.isfinite(integrated) or not math.isfinite(true_peak):
        raise ValueError(f"non-finite loudness/true-peak measurement for {path.name}: {data}")
    return {"integrated_lufs": integrated, "true_peak_dbtp": true_peak,
            "analyzer": "ffmpeg loudnorm input_i/input_tp"}


def audio_gate(metrics: dict, true_peak_max_dbtp: float) -> dict:
    integrated = metrics["integrated_lufs"]
    true_peak = metrics["true_peak_dbtp"]
    loudness_ok = LOUDNESS_MIN_LUFS <= integrated <= LOUDNESS_MAX_LUFS
    peak_ok = true_peak <= true_peak_max_dbtp
    return {"status": "PASS" if loudness_ok and peak_ok else "FAIL",
            "integrated_range_lufs": [LOUDNESS_MIN_LUFS, LOUDNESS_MAX_LUFS],
            "true_peak_max_dbtp": true_peak_max_dbtp,
            "loudness_status": "PASS" if loudness_ok else "FAIL",
            "true_peak_status": "PASS" if peak_ok else "FAIL"}


def get_fid_settings(fid: str) -> dict:
    """Get film-specific settings, raising if FID not explicitly allowed."""
    if fid not in FID_SPECIFIC_SETTINGS:
        raise ValueError(f"FID '{fid}' not in explicit allowlist: {sorted(FID_SPECIFIC_SETTINGS.keys())}")
    return FID_SPECIFIC_SETTINGS[fid]


def assemble(segdir: Path, pkg: Path, out: Path, segs: list[dict], duration: float, fid: str) -> dict:
    require_hosted_media()
    settings = get_fid_settings(fid)
    true_peak_max = settings["TRUE_PEAK_MAX_DBTP"]
    master_gain_db = settings["MASTER_GAIN_DB"]

    out.mkdir(parents=True, exist_ok=True)
    mix = pkg / "audio" / "mix.flac"
    index = pkg / "film" / "index.html"
    if not mix.is_file() or not index.is_file():
        raise FileNotFoundError("sealed package is missing film/index.html or audio/mix.flac")
    required = sum((segdir / f"SEG{s['i']}.mp4").stat().st_size for s in segs if (segdir / f"SEG{s['i']}.mp4").is_file())
    free = shutil.disk_usage(out).free
    if free < int(required * 2.5 + mix.stat().st_size + (1.5 * 1024**3)):
        raise OSError(f"runner disk guard: free={free} bytes, required>{int(required * 2.5 + mix.stat().st_size + 1.5 * 1024**3)}")
    original_mix_sha256 = sha256(mix)
    adjusted_mix = out / f"{fid}-MIX-GAIN-ADJUSTED.flac"
    run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-y", "-i", str(mix),
         "-map", "0:a:0", "-af", f"volume={master_gain_db}dB", "-sample_fmt", "s32",
         "-c:a", "flac", "-compression_level", "8", str(adjusted_mix)])
    adjusted_mix_metrics = measure_audio(adjusted_mix)
    adjusted_mix_sha256 = sha256(adjusted_mix)
    observed_keys = set()
    frame_sum = 0
    files = []
    segment_rows = []
    for s in segs:
        p = segdir / f"SEG{s['i']}.mp4"
        if not p.is_file() or p.stat().st_size == 0:
            raise FileNotFoundError(f"missing segment {p.name}")
        receipt_path = segdir / f"SEG{s['i']}.verify.json"
        if not receipt_path.is_file():
            raise FileNotFoundError(f"missing hosted verification receipt {receipt_path.name}")
        receipt = json.loads(receipt_path.read_text())
        if (receipt.get("status") != "PASS" or receipt.get("sha256") != sha256(p)
                or receipt.get("full_decode") != "PASS"
                or receipt.get("flicker", {}).get("status") != "PASS"):
            raise ValueError(f"segment verification receipt failed or hash differs: {receipt_path.name}")
        info = probe(p)
        v = video_stream(info)
        packets = int(v.get("nb_read_packets", 0))
        if (v.get("codec_name") != "h264" or v.get("width") != W4K or v.get("height") != H4K
                or v.get("pix_fmt") != "yuv420p" or v.get("r_frame_rate") != "30/1"
                or packets != s["frames"] or receipt.get("frames") != packets):
            raise ValueError(f"segment {p.name} failed 4K/frame probe: {v}")
        key = codec_key(v)
        observed_keys.add(key)
        frame_sum += packets
        files.append(p)
        segment_rows.append({"id": s["i"], "t0": s["t0"], "len": s["len"], "frames": packets,
                             "bytes": p.stat().st_size, "sha256": sha256(p), "hosted_receipt": receipt})
    if len(observed_keys) != 1 or frame_sum != int(round(duration * FPS)):
        raise ValueError("segment codec set differs or total frame count does not cover composition")

    concat = out / "concat.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in files))
    master = out / f"{fid}-MASTER-4K.mp4"
    run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-y", "-f", "concat", "-safe", "0",
         "-i", str(concat), "-i", str(adjusted_mix), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(master)])
    master_probe = probe(master)
    mv = video_stream(master_probe)
    master_frames = int(mv.get("nb_read_packets", 0))
    audio = next((s for s in master_probe["streams"] if s.get("codec_type") == "audio"), None)
    if (master_frames != frame_sum or mv.get("width") != W4K or mv.get("height") != H4K
            or not audio or audio.get("codec_name") != "aac" or audio.get("sample_rate") != "48000"):
        raise ValueError(f"4K master probe mismatch: video={mv}, audio={audio}, expected_frames={frame_sum}")
    master_audio_metrics = measure_audio(master)
    master_audio_gate = audio_gate(master_audio_metrics, true_peak_max)
    mix_receipt = {"original_mix": mix.name, "original_mix_sha256": original_mix_sha256,
                   "adjusted_mix": adjusted_mix.name, "adjusted_mix_sha256": adjusted_mix_sha256,
                   "gain_db": master_gain_db, "adjusted_mix_metrics": adjusted_mix_metrics,
                   "encoded_master_metrics": master_audio_metrics, "encoded_master_gate": master_audio_gate,
                   "status": "PASS" if master_audio_gate["status"] == "PASS" else "FAIL"}
    (out / "AUDIO-GAIN-RECEIPT.json").write_text(json.dumps(mix_receipt, indent=2) + "\n")
    if master_audio_gate["status"] != "PASS":
        raise ValueError(f"encoded master audio remains outside gate; refusing 1080 derivation/review artifact: {mix_receipt}")
    decode(master)

    derived = out / f"{fid}-MASTER-1080-from-4K.mp4"
    run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-y", "-i", str(master),
         "-vf", "scale=1920:1080:flags=lanczos", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
         "-x264-params", "threads=2", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(derived)])
    derived_probe = probe(derived)
    dv = video_stream(derived_probe)
    derived_frames = int(dv.get("nb_read_packets", 0))
    if (derived_frames != frame_sum or dv.get("width") != 1920 or dv.get("height") != 1080
            or dv.get("codec_name") != "h264"):
        raise ValueError(f"1080-derived probe mismatch: {dv}, expected_frames={frame_sum}")
    decode(derived)
    sidecar = {"master": master.name, "master_bytes": master.stat().st_size,
               "master_sha256": sha256(master), "derived": derived.name,
               "derived_bytes": derived.stat().st_size, "segments": len(segs),
               "frames": frame_sum, "duration": duration,
               "adjusted_mix_sha256": adjusted_mix_sha256,
               "audio_metrics": master_audio_metrics}
    (out / f"{fid}-MASTER-1080-from-4K.mp4.derived.json").write_text(json.dumps(sidecar, indent=2) + "\n")
    report = {"kind": "mechanical_integrity_only", "editorial_gate": "NOT_RUN",
              "release_approval": "NOT_GRANTED", "duration": duration, "fps": FPS,
              "segment_count": len(segs), "frame_count": frame_sum, "segments": segment_rows,
              "video_codec_key": list(next(iter(observed_keys))), "master_probe": master_probe,
              "derived_probe": derived_probe, "outputs": sidecar, "audio_mix": mix_receipt,
              "checks": {"segment_decode": "PASS", "segment_flicker": "PASS",
                         "master_full_decode": "PASS", "derived_full_decode": "PASS",
                         "encoded_audio_loudness_and_true_peak": master_audio_gate["status"]}}
    (out / "REMOTE-INTEGRITY.json").write_text(json.dumps(report, indent=2) + "\n")
    sums = []
    for p in sorted(out.iterdir()):
        if p.is_file() and p.name != "SHA256SUMS.txt":
            sums.append(f"{sha256(p)}  {p.name}")
    (out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    return report


def self_test() -> None:
    duration = 632.43
    # Same segmentation as render_codespace_film.segments(duration, 8.6).
    segs = []
    for k in range(int(math.floor(duration / 8.6 + 1e-9))):
        t0 = round(k * 8.6, 3)
        ln = round(8.6 if k < int(math.floor(duration / 8.6 + 1e-9)) - 1 else duration - t0, 3)
        segs.append({"i": f"{k+1:02d}", "t0": t0, "len": ln})
    got = manifest(json.dumps(segs), duration)
    assert len(got) == 73 and sum(s["frames"] for s in got) == 18973
    assert got[-1]["len"] == 13.23 and got[-1]["frames"] == 397
    assert flicker_from_means([10.0, 10.0, 10.0]) == (0, 0.0)
    assert flicker_from_means([0.0, 0.0, 20.0, 0.0, 0.0]) == (1, 20.0)
    # Test with F07 settings (TRUE_PEAK_MAX_DBTP = -1.0)
    assert audio_gate({"integrated_lufs": -14.8, "true_peak_dbtp": -1.3}, -1.0)["status"] == "PASS"
    assert audio_gate({"integrated_lufs": -14.8, "true_peak_dbtp": -0.9}, -1.0)["status"] == "FAIL"
    assert audio_gate({"integrated_lufs": -15.1, "true_peak_dbtp": -1.3}, -1.0)["status"] == "FAIL"
    try:
        manifest(json.dumps(segs[:-1]), duration)
    except ValueError:
        pass
    else:
        raise AssertionError("missing final segment was accepted")
    print("self-test PASS: 73 contiguous segments, 18,973 expected frames, missing-tail refusal")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--segments-json", default=os.environ.get("SEGS_JSON", ""))
    ap.add_argument("--check-segment", type=Path, default=None)
    ap.add_argument("--expected-frames", type=int, default=None)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--segments-dir", type=Path, default=Path("segments"))
    ap.add_argument("--package-dir", type=Path, default=Path("package"))
    ap.add_argument("--output-dir", type=Path, default=Path("remote-final"))
    ap.add_argument("--fid", type=str, default=None, help="Film ID (e.g., F02, F07)")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return 0

    if args.check_segment is not None:
        if args.expected_frames is None:
            ap.error("--expected-frames required with --check-segment")
        if args.fid is None:
            ap.error("--fid required with --check-segment")
        settings = get_fid_settings(args.fid)
        true_peak_max = settings["TRUE_PEAK_MAX_DBTP"]
        receipt = check_segment(args.check_segment, args.expected_frames)
        receipt_path = args.check_segment.with_suffix(".verify.json")
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt, indent=2))
        return 0

    if not args.segments_json or args.duration is None:
        ap.error("--segments-json and --duration are required")
    if args.fid is None:
        ap.error("--fid is required")
    segs = manifest(args.segments_json, args.duration)
    rep = assemble(args.segments_dir, args.package_dir, args.output_dir, segs, args.duration, args.fid)
    print(json.dumps({"kind": rep["kind"], "segment_count": rep["segment_count"], "frame_count": rep["frame_count"],
                      "checks": rep["checks"], "outputs": rep["outputs"]}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"REMOTE ASSEMBLY REFUSED/FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        raise SystemExit(1)