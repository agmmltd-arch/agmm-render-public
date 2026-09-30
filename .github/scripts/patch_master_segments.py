#!/usr/bin/env python3
"""Replace reviewed F07 segment artifacts and remux the verified base-master audio."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assemble_verify as av  # noqa: E402


FPS = 30


def segments(duration: float) -> list[dict]:
    count = int(math.floor(duration / 8.6 + 1e-9))
    rows = []
    for k in range(count):
        t0 = round(k * 8.6, 3)
        length = round(8.6 if k < count - 1 else duration - t0, 3)
        rows.append({"i": f"{k + 1:02d}", "t0": t0, "len": length,
                     "frames": round(length * FPS)})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments-dir", required=True, type=Path)
    ap.add_argument("--base-master", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--duration", required=True, type=float)
    ap.add_argument("--base-run-id", required=True)
    ap.add_argument("--patch-runs-json", required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    patch_runs = json.loads(args.patch_runs_json)
    expected_patches = {"28", "29"}
    if set(patch_runs) != expected_patches:
        raise ValueError(f"patch receipt must identify exactly {sorted(expected_patches)}")

    rows = segments(args.duration)
    files, codec_keys, frame_sum, evidence = [], set(), 0, []
    for row in rows:
        sid = row["i"]
        video = args.segments_dir / f"SEG{sid}.mp4"
        receipt_path = args.segments_dir / f"SEG{sid}.verify.json"
        if not video.is_file() or not receipt_path.is_file():
            raise FileNotFoundError(f"missing segment or receipt: SEG{sid}")
        receipt = json.loads(receipt_path.read_text())
        info = av.probe(video)
        stream = av.video_stream(info)
        packets = int(stream.get("nb_read_packets", 0))
        digest = av.sha256(video)
        if (receipt.get("status") != "PASS" or receipt.get("full_decode") != "PASS"
                or receipt.get("sha256") != digest or receipt.get("frames") != packets):
            raise ValueError(f"hosted verification receipt does not cover SEG{sid}")
        if (stream.get("codec_name") != "h264" or stream.get("width") != av.W4K
                or stream.get("height") != av.H4K or stream.get("pix_fmt") != "yuv420p"
                or stream.get("r_frame_rate") != "30/1" or packets != row["frames"]):
            raise ValueError(f"SEG{sid} profile/frame mismatch: {stream}")
        codec_keys.add(av.codec_key(stream))
        files.append(video)
        frame_sum += packets
        evidence.append({"id": sid, "t0": row["t0"], "len": row["len"], "frames": packets,
                         "bytes": video.stat().st_size, "sha256": digest,
                         "source_run_id": str(patch_runs[sid]) if sid in expected_patches
                                          else str(args.base_run_id),
                         "hosted_receipt": receipt})
    if len(codec_keys) != 1 or frame_sum != round(args.duration * FPS):
        raise ValueError("patched segment set differs in codec or total frame count")

    base_probe = av.probe(args.base_master)
    base_audio = next((s for s in base_probe["streams"] if s.get("codec_type") == "audio"), None)
    if not base_audio or base_audio.get("codec_name") != "aac" or base_audio.get("sample_rate") != "48000":
        raise ValueError(f"base master audio is not the verified AAC/48k stream: {base_audio}")

    concat = args.out / "concat.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in files))
    video_only = args.out / "F07-PATCHED-VIDEO-ONLY.mp4"
    av.run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat), "-map", "0:v:0", "-an", "-c:v", "copy", str(video_only)])
    master = args.out / "F07-MASTER-4K.mp4"
    av.run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-y", "-i", str(video_only),
            "-i", str(args.base_master), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy",
            "-movflags", "+faststart", str(master)])
    master_probe = av.probe(master)
    master_video = av.video_stream(master_probe)
    master_frames = int(master_video.get("nb_read_packets", 0))
    if master_frames != frame_sum:
        raise ValueError(f"patched master has {master_frames} frames; expected {frame_sum}")
    av.decode(master)
    audio_metrics = av.measure_audio(master)
    audio_gate = av.audio_gate(audio_metrics)
    if audio_gate["status"] != "PASS":
        raise ValueError(f"copied base-master audio failed its release gate: {audio_metrics}")

    derived = args.out / "F07-MASTER-1080-from-4K.mp4"
    av.run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-y", "-i", str(master),
            "-vf", "scale=1920:1080:flags=lanczos", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
            "-x264-params", "threads=2", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
            str(derived)])
    derived_probe = av.probe(derived)
    derived_video = av.video_stream(derived_probe)
    if (int(derived_video.get("nb_read_packets", 0)) != frame_sum
            or derived_video.get("width") != 1920 or derived_video.get("height") != 1080):
        raise ValueError(f"patched review master probe mismatch: {derived_video}")
    av.decode(derived)

    sidecar = {"master": master.name, "master_bytes": master.stat().st_size,
               "master_sha256": av.sha256(master), "derived": derived.name,
               "derived_bytes": derived.stat().st_size, "segments": len(rows),
               "frames": frame_sum, "duration": args.duration,
               "base_master_sha256": av.sha256(args.base_master), "audio_metrics": audio_metrics,
               "patch_runs": patch_runs}
    (args.out / "F07-MASTER-1080-from-4K.mp4.derived.json").write_text(
        json.dumps(sidecar, indent=2) + "\n")
    report = {"kind": "mechanical_integrity_patched_master", "editorial_gate": "NOT_RUN",
              "release_approval": "NOT_GRANTED", "base_run_id": str(args.base_run_id),
              "patch_runs": patch_runs, "duration": args.duration, "fps": FPS,
              "segment_count": len(rows), "frame_count": frame_sum, "segments": evidence,
              "master_probe": master_probe, "derived_probe": derived_probe, "outputs": sidecar,
              "checks": {"all_hosted_segment_receipts": "PASS", "patched_segment_ids": ["28", "29"],
                         "master_full_decode": "PASS", "derived_full_decode": "PASS",
                         "base_audio_copied_without_reencode": "PASS",
                         "encoded_audio_loudness_and_true_peak": audio_gate["status"]}}
    (args.out / "REMOTE-INTEGRITY.json").write_text(json.dumps(report, indent=2) + "\n")
    sums = []
    for path in sorted(args.out.iterdir()):
        if path.is_file() and path.name not in {"SHA256SUMS.txt", "concat.txt", video_only.name}:
            sums.append(f"{av.sha256(path)}  {path.name}")
    (args.out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    print(json.dumps({"status": "PASS", "master_sha256": sidecar["master_sha256"],
                      "frames": frame_sum, "patches": patch_runs}))


if __name__ == "__main__":
    main()
