#!/usr/bin/env python3
"""Create compact still/audio review assets from hosted segment artifacts; never copies MP4 outputs."""
import argparse
import json
import re
import subprocess
from pathlib import Path


def run(cmd):
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(f"command failed: {cmd[0]} {p.stderr[-1000:]}")
    return p.stdout


def probe(path):
    raw = run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
               "-show_entries", "stream=codec_name,width,height,pix_fmt,r_frame_rate,nb_read_packets",
               "-of", "json", str(path)])
    info = json.loads(raw)["streams"][0]
    if (info.get("codec_name") != "h264" or info.get("width") != 3840 or info.get("height") != 2160
            or info.get("pix_fmt") != "yuv420p" or info.get("r_frame_rate") != "30/1"):
        raise ValueError(f"unexpected segment profile {path.name}: {info}")
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments-json", required=True, type=Path)
    ap.add_argument("--segments-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--mix", type=Path)
    ap.add_argument("--source-run-id", required=True)
    a = ap.parse_args()
    segs = json.loads(a.segments_json.read_text())
    if not segs or len(segs) > 12:
        raise ValueError("review request must contain 1..12 segments")
    a.out.mkdir(parents=True, exist_ok=True)
    rows, thumbs = [], []
    for seg in segs:
        sid = str(seg["i"])
        if not re.fullmatch(r"\d{2}", sid):
            raise ValueError(f"invalid segment id: {sid}")
        video = a.segments_dir / f"SEG{sid}.mp4"
        receipt = a.segments_dir / f"SEG{sid}.verify.json"
        if not video.is_file() or not receipt.is_file():
            raise FileNotFoundError(f"segment or hosted verification receipt missing: SEG{sid}")
        proof = json.loads(receipt.read_text())
        if proof.get("status") != "PASS" or proof.get("full_decode") != "PASS":
            raise ValueError(f"hosted segment gate did not pass for SEG{sid}")
        info = probe(video)
        if int(info.get("nb_read_packets", 0)) != int(proof.get("frames", -1)):
            raise ValueError(f"segment probe frame count differs from hosted receipt: SEG{sid}")
        duration = float(seg["len"])
        expected_t0 = round((int(sid) - 1) * 8.6, 3)
        if abs(float(seg["t0"]) - expected_t0) > 0.002 or int(proof.get("frames", 0)) != round(duration * 30):
            raise ValueError(f"segment manifest timing differs from expected F07 grid: SEG{sid}")
        points = {"start": min(0.04, duration / 4), "middle": duration / 2,
                  "end": max(0.0, duration - 0.04)}
        row = {"segment": sid, "global_t0": float(seg["t0"]), "duration": duration,
               "native_frame_paths": {}, "hosted_segment_receipt": proof,
               "video_probe": info, "audio_excerpt": None}
        for label, ts in points.items():
            if label == "middle":
                path = a.out / f"SEG{sid}-middle-640x360.jpg"
                run(["ffmpeg", "-hide_banner", "-v", "error", "-ss", f"{ts:.3f}", "-i", str(video),
                     "-frames:v", "1", "-vf", "scale=640:360:flags=lanczos", "-q:v", "3", "-y", str(path)])
                thumbs.append(path)
            else:
                path = a.out / f"SEG{sid}-{label}-native-4k.jpg"
                run(["ffmpeg", "-hide_banner", "-v", "error", "-ss", f"{ts:.3f}", "-i", str(video),
                     "-frames:v", "1", "-q:v", "2", "-y", str(path)])
                row["native_frame_paths"][label] = path.name
        if a.mix:
            if not a.mix.is_file():
                raise FileNotFoundError("provided verified source mix is missing")
            audio = a.out / f"SEG{sid}-audio-5s.m4a"
            run(["ffmpeg", "-hide_banner", "-v", "error", "-ss", f"{float(seg['t0']) + 0.25:.3f}",
                 "-i", str(a.mix), "-t", "5", "-vn", "-c:a", "aac", "-b:a", "96k", "-movflags",
                 "+faststart", "-y", str(audio)])
            row["audio_excerpt"] = audio.name
        rows.append(row)
    # One small thumbnail contact sheet; native-resolution edge stills remain separate for zoom review.
    from PIL import Image, ImageDraw
    cols = min(3, len(thumbs)); rows_n = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 640, rows_n * 390), "#101820")
    draw = ImageDraw.Draw(sheet)
    for i, path in enumerate(thumbs):
        im = Image.open(path).convert("RGB")
        x, y = (i % cols) * 640, (i // cols) * 390
        sheet.paste(im, (x, y + 30))
        draw.text((x + 12, y + 8), path.name.replace("-middle-640x360.jpg", ""), fill="white")
    sheet.save(a.out / "CONTACT-SHEET.jpg", quality=90, optimize=True)
    manifest = {"kind": "remote_segment_review_assets", "source_run_id": a.source_run_id,
                "segments": rows, "contact_sheet": "CONTACT-SHEET.jpg",
                "audio_source_available": bool(a.mix),
                "audio_note": "Excerpts are from the hash-verified source mix." if a.mix else
                             "Unavailable: prior segment artifacts contain no audio; source mix was not provided.",
                "mp4_downloaded_to_mac": False, "editorial_gate": "NOT_RUN", "release_approval": "NOT_GRANTED"}
    (a.out / "REVIEW-ASSET-MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"segments": len(rows), "native_stills": 2*len(rows), "contact": "CONTACT-SHEET.jpg",
                      "audio_excerpts": sum(bool(r["audio_excerpt"]) for r in rows),
                      "manifest": "REVIEW-ASSET-MANIFEST.json"}))

if __name__ == "__main__":
    main()
