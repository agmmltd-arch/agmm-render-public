#!/usr/bin/env python3
"""Derive review media from the exact existing F03 r26 master, on Ubuntu only.

Uses the original assemble_verify owner for all media commands/probes/hashes.
Does not render a film, remix audio, approve, publish or alter the source master.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from fractions import Fraction
import platform
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

SCHEMA = "agmm-f03-r26-existing-review-v1"
PUBLIC = "agmmltd-arch/agmm-render-public"
PRIVATE = "agmmltd-arch/agmm-video-render"
MASTER_SHA = "ff920e9545f082a29e239c2543bd3df8ff096c325c93e9910179b020f949defe"
MASTER_BYTES = 2254415964
OWNER_SHA = "d129cb379aacca1967f6c5448abbc5f6dd01b4a0c673f3a1cad0a0abec4177ac"
CHUNK_BYTES = 4 * 1024 * 1024
SOURCE_PACKAGE = "777d36e0534286ec49f6b1fc0f3adae9c67f5f36aa59539ea5428aaf9c1631b8"
GATE_SHA = "f8fac87d55cd0813776cef03513ae155f7fd6c155e741967a42ba77cd7f8415b"
FILM_GATE_SHA = "71c6d12400f06b4d7643eb809d2c2fe2f776b01f9b757b750821d8e1d625ba57"


def need(ok, why):
    if not ok:
        raise ValueError(why)


def request_check(r):
    need(r.get("schema") == SCHEMA and r.get("id") == "F03", "exact F03 request required")
    need(r.get("master_sha256") == MASTER_SHA and r.get("master_bytes") == MASTER_BYTES,
         "selected original r26 master differs")
    for k in ("private_commit", "manifest_git_blob"):
        need(re.fullmatch(r"[0-9a-f]{40}", str(r.get(k, ""))), "exact private Git identity required")
    prefix = r.get("private_prefix", "")
    need(re.fullmatch(r"native-film-review-inputs/F03-r26-[a-z0-9-]{8,80}", prefix), "unsafe private prefix")
    need(r.get("intent") == "f03-r26-review-" + r["manifest_git_blob"], "intent is not manifest-bound")
    return r


def manifest_check(m):
    need(m.get("schema") == SCHEMA + "-inputs" and m.get("id") == "F03"
         and m.get("master_sha256") == MASTER_SHA and m.get("master_bytes") == MASTER_BYTES,
         "exact protected master manifest required")
    need(m.get("source_render_run_id") == 38437949183 and m.get("source_package_sha256") == SOURCE_PACKAGE
         and m.get("historical_run_body_binding") == "UNVERIFIED_EXPIRED_ARTIFACT"
         and m.get("source_package_body_binding") == "DOCUMENTED_NATIVE_PACKAGE_ASSOCIATION_NOT_PROVEN_FROM_MASTER"
         and re.fullmatch(r"[0-9a-f]{64}", str(m.get("root_qa_sha256", "")))
         and m.get("release_approved") is False and m.get("whole_film_approved") is False,
         "original source/QA provenance or review boundary differs")
    rows = m.get("chunks", [])
    need(len(rows) == (MASTER_BYTES + CHUNK_BYTES - 1) // CHUNK_BYTES, "incomplete chunk inventory")
    cursor = 0
    for i, r in enumerate(rows):
        length = min(CHUNK_BYTES, MASTER_BYTES - cursor)
        need(r.get("path") == "master-%03d.bin" % i and r.get("offset") == cursor
             and r.get("bytes") == length and type(r.get("bytes")) is int
             and re.fullmatch(r"[0-9a-f]{40}", str(r.get("git_blob_sha", ""))),
             "chunk path/offset/length/Git identity differs")
        cursor += length
    need(cursor == MASTER_BYTES, "chunk coverage differs")
    return rows


def require_hosted():
    need(platform.system() == "Linux" and os.environ.get("GITHUB_ACTIONS") == "true"
         and os.environ.get("GITHUB_REPOSITORY") == PUBLIC and os.environ.get("GITHUB_RUN_ATTEMPT") == "1",
         "first-attempt Ubuntu public Actions required before media IO")


def original_owner():
    p = Path(__file__).with_name("assemble_verify.py")
    need(hashlib.sha256(p.read_bytes()).hexdigest() == OWNER_SHA, "original assembly owner changed")
    spec = importlib.util.spec_from_file_location("original_film_assembly", p)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    return owner


def probe_check(info, width, height):
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    need(len(video) == len(audio) == 1, "one video and one audio stream required")
    v, a = video[0], audio[0]
    need((v.get("width"), v.get("height"), v.get("codec_name"), v.get("pix_fmt"),
          v.get("r_frame_rate"), int(v.get("nb_read_packets", 0)))
         == (width, height, "h264", "yuv420p", "30/1", 12372), "original geometry/frames differ")
    need(a.get("codec_name") == "aac" and a.get("sample_rate") == "48000"
         and abs(float(info["format"]["duration"]) - 412.4) < 0.002, "audio or duration differs")


def clock_int(value):
    need(type(value) is int or (isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value)),
         "integer packet/sample clock required")
    return int(value)


def proxy_check(info, packets, width, height, channels):
    """Proxy-only sample-clock proof; master/main probe_check is unchanged.

    Native AAC encoders emit 1,024-sample blocks. Only the incomplete last
    block may extend the exact video timeline; container duration alone is
    neither a video-frame count nor evidence of extra content.
    """
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    need(len(video) == len(audio) == 1, "proxy requires exactly one video/audio stream")
    v, a = video[0], audio[0]
    need((v.get("width"), v.get("height"), v.get("codec_name"), v.get("pix_fmt"),
          v.get("r_frame_rate"), v.get("avg_frame_rate"), clock_int(v.get("nb_read_packets", 0)))
         == (width, height, "h264", "yuv420p", "30/1", "30/1", 12372), "proxy geometry/frames differ")
    video_end = Fraction(12372, 30)
    vt = Fraction(v["time_base"])
    need(Fraction(v["start_time"]) == 0 and clock_int(v["start_pts"]) == 0
         and clock_int(v["duration_ts"]) * vt == video_end
         and abs(Fraction(v["duration"]) - video_end) <= Fraction(1, 1000000), "proxy video timeline differs")
    need(a.get("codec_name") == "aac" and a.get("profile") == "LC"
         and a.get("sample_rate") == "48000" and a.get("channels") == channels
         and Fraction(a["time_base"]) == Fraction(1, 48000)
         and Fraction(a["start_time"]) == 0 and clock_int(a["start_pts"]) == 0, "proxy AAC identity/start differs")
    rows = packets.get("packets", [])
    need(rows and len(rows) == clock_int(a["nb_read_packets"]) == clock_int(a["nb_frames"]), "proxy AAC packet inventory differs")
    previous_end = None
    effective_start = None
    effective_end = None
    for i, row in enumerate(rows):
        pts, dts, duration = (clock_int(row[k]) for k in ("pts", "dts", "duration"))
        need(pts == dts and 0 < duration <= 1024 and (i == len(rows)-1 or duration == 1024),
             "proxy AAC packet timing/block differs")
        need(previous_end is None or pts == previous_end, "proxy AAC gap/overlap")
        side = row.get("side_data_list", [])
        need(len(side) <= 1 and all(x.get("side_data_type") == "Skip Samples" for x in side),
             "proxy AAC unexpected side data")
        skip = clock_int(side[0].get("skip_samples", 0)) if side else 0
        discard = clock_int(side[0].get("discard_padding", 0)) if side else 0
        need((skip == 0 or (i == 0 and skip == 1024 and pts == -1024))
             and (discard == 0 or (i == len(rows)-1 and 0 < discard < duration)), "proxy AAC priming/discard differs")
        if i == 0:
            effective_start = pts + skip
        previous_end = pts + duration
        effective_end = previous_end - discard
    samples = video_end * 48000
    need(samples.denominator == 1 and effective_start == 0, "proxy AAC effective start differs")
    final_block_end = ((samples.numerator + 1023) // 1024) * 1024
    need(samples.numerator <= effective_end <= final_block_end, "proxy AAC is truncated or extends past the final packet block")
    need(clock_int(a["duration_ts"]) == effective_end
         and abs(Fraction(a["duration"]) - Fraction(effective_end, 48000)) <= Fraction(1, 1000000),
         "proxy AAC stream duration disagrees with actual packets")
    end = max(video_end, Fraction(effective_end, 48000))
    need(Fraction(info["format"]["start_time"]) == 0
         and abs(Fraction(info["format"]["duration"]) - end) <= Fraction(1, 1000000),
         "proxy container does not match measured stream endpoints")
    return {"contract": "EXACT_VIDEO_AND_AAC_FINAL_BLOCK_V1", "video_frames": 12372,
            "video_duration": "412.4", "sample_rate": 48000, "aac_block_samples": 1024,
            "audio_packets": len(rows), "audio_effective_samples": effective_end,
            "video_samples": samples.numerator, "final_block_end_samples": final_block_end,
            "padding_samples": effective_end-samples.numerator}


def fallback_command(source, master, small, v2):
    """The unchanged original film owner's literal fallback command, not a new encoder policy."""
    need(hashlib.sha256(source).hexdigest() == FILM_GATE_SHA, "original film gate source changed")
    nodes = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.List)
             and any(isinstance(e, ast.Constant) and e.value == "scale=-2:360" for e in n.elts)]
    need(len(nodes) == 1, "original film fallback command is ambiguous")
    return eval(compile(ast.Expression(nodes[0]), "original_gate_film_command", "eval"),
                {"__builtins__": {}}, {"os": os, "V2": str(v2), "a": SimpleNamespace(master=str(master)), "small": str(small)})


def qa_proxies(owner, derived, output):
    require_hosted()
    scripts = Path(__file__).parent
    gp = scripts / "master-evaluation-native/video-program-2026-09-23/v2/qa/gate.py"
    need(hashlib.sha256(gp.read_bytes()).hexdigest() == GATE_SHA, "exact original QA gate runtime changed")
    spec = importlib.util.spec_from_file_location("original_f03_qa_proxy_owner", gp)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    large = output / "downscaled_for_gemini.mp4"
    small = output / "film_for_gemini_360p.mp4"
    os.environ["GATE_DS_ENCODER"] = "libx264"  # unchanged original Linux path; no VideoToolbox on Ubuntu
    ok, log = gate.make_downscaled_copy(str(derived), str(large))
    need(ok and large.is_file() and large.stat().st_size > 0, "original720 QA proxy failed")
    owner.decode(large)
    film_source = scripts / "f03-review-native/gate_film.py"
    command = fallback_command(film_source.read_bytes(), derived, small, "ORIGINAL_NATIVE_V2")
    need(command[:3] == ["python3", "ORIGINAL_NATIVE_V2/kit/tools/heavy.py", "--"], "original heavy wrapper differs")
    # Original native heavy queue is replaced only by this job's single-workflow concurrency;
    # every original nice/FFmpeg encoder argument after '--' is unchanged.
    owner.run(command[3:])
    need(0 < small.stat().st_size <= gate.GEMINI_MAX_BYTES, "original360 QA fallback is over its original byte limit")
    owner.decode(small)
    rows, diagnostics = [], []
    for p, dims, channels in ((large, (1280, 720), 2), (small, (640, 360), 1)):
        info = owner.probe(p)
        packets = json.loads(owner.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_packets",
            "-show_entries", "packet=pts,dts,duration,side_data_list:packet_side_data=side_data_type,skip_samples,discard_padding",
            "-of", "json", str(p)], capture=True))
        row = {"path": p.name, "bytes": p.stat().st_size, "sha256": owner.sha256(p), "probe": info}
        rows.append(row)
        diagnostics.append(dict(row, audio_packets=packets, expected_dimensions=list(dims), expected_channels=channels))
    # Both complete actual probes/packet clocks are retained BEFORE either proxy qualifies.
    diagnostic_file = output / "QA-PROXY-DIAGNOSTICS.json"
    diagnostic_file.write_text(json.dumps({"schema": "f03-proxy-clock-diagnostics-v1", "proxies": diagnostics}, indent=2) + "\n")
    print(json.dumps({"qa_proxy_diagnostics_before_qualification": [
        {k: v for k, v in row.items() if k != "audio_packets"} | {
            "audio_packet_count": len(row["audio_packets"].get("packets", [])),
            "first_audio_packet": (row["audio_packets"].get("packets") or [None])[0],
            "last_audio_packet": (row["audio_packets"].get("packets") or [None])[-1]} for row in diagnostics]}), flush=True)
    for row, diagnostic in zip(rows, diagnostics):
        row["qualification"] = proxy_check(row["probe"], diagnostic["audio_packets"],
                                           *diagnostic["expected_dimensions"], diagnostic["expected_channels"])
    (output / "QA-PROXY-ENCODER-LOG.txt").write_text(log)
    return {"gate_source_sha256": GATE_SHA, "film_gate_source_sha256": FILM_GATE_SHA,
            "gemini_max_bytes": gate.GEMINI_MAX_BYTES, "proxies": rows,
            "diagnostics_sha256": owner.sha256(diagnostic_file),
            "proxy_contract": "EXACT_VIDEO_AND_AAC_FINAL_BLOCK_V1",
            "initial_proxy": large.name, "initial_proxy_exceeds_limit": large.stat().st_size > gate.GEMINI_MAX_BYTES,
            "fallback_proxy": small.name, "fallback_command_after_original_heavy_wrapper": command[3:],
            "selection": "UNCHANGED_NATIVE_OWNER_DECIDES_USING_ACTUAL_CHECK2_AND_CHECK9_RESULTS",
            "gate_checks_run": False, "audio_heard": False}


def derive(r, private_root, work, output):
    require_hosted()  # precedes any media/input/owner access
    request_check(r)
    need(subprocess.check_output(["git", "-C", str(private_root), "rev-parse", "HEAD"], text=True).strip()
         == r["private_commit"], "actual protected checkout differs")
    prefix = private_root / r["private_prefix"]
    need(private_root.is_dir() and not private_root.is_symlink() and prefix.is_dir() and not prefix.is_symlink(),
         "protected input namespace must be a real directory")
    mp = prefix / "MANIFEST.json"
    need(mp.is_file() and not mp.is_symlink(), "protected manifest missing")
    raw = mp.read_bytes()
    need(hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
         == r["manifest_git_blob"], "protected manifest Git identity differs")
    m = json.loads(raw)
    rows = manifest_check(m)
    need({p.name for p in prefix.iterdir()} == {"MANIFEST.json"} | {x["path"] for x in rows},
         "protected namespace contains foreign input")
    need(not work.exists() and not output.exists(), "fresh work/output directories required")
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    need(shutil.disk_usage(work).free > MASTER_BYTES + 1536 * 1024 * 1024,
         "runner free-space guard before master reconstruction")
    owner = original_owner()
    master = work / "F03-MASTER-4K.mp4"
    with master.open("xb") as target:
        for row in rows:
            p = prefix / row["path"]
            need(p.is_file() and not p.is_symlink() and p.stat().st_size == row["bytes"], "input chunk changed")
            blob = hashlib.sha1(b"blob " + str(row["bytes"]).encode() + b"\0")
            with p.open("rb") as source:
                for block in iter(lambda: source.read(1 << 20), b""):
                    blob.update(block)
                    target.write(block)
            need(blob.hexdigest() == row["git_blob_sha"], "private chunk Git body differs")
    need(master.stat().st_size == MASTER_BYTES and owner.sha256(master) == MASTER_SHA, "reassembled r26 master differs")
    before = owner.probe(master)
    probe_check(before, 3840, 2160)
    owner.decode(master)
    audio_metrics = owner.measure_audio(master)
    audio_gate = owner.audio_gate(audio_metrics, owner.get_fid_settings("F03")["TRUE_PEAK_MAX_DBTP"])
    need(audio_gate["status"] == "PASS", "exact original encoded master audio fails the original mechanical gate")
    derived = output / "F03-MASTER-1080-from-4K.mp4"
    # Exact original assemble_verify.assemble review-derivation command.
    owner.run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-y", "-i", str(master),
               "-vf", "scale=1920:1080:flags=lanczos", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
               "-x264-params", "threads=2", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(derived)])
    after = owner.probe(derived)
    probe_check(after, 1920, 1080)
    owner.decode(derived)
    audio_hashes = [owner.run(["ffmpeg", "-v", "error", "-i", str(p), "-map", "0:a:0", "-c:a", "copy",
                              "-f", "hash", "-hash", "sha256", "-"], capture=True).strip() for p in (master, derived)]
    need(audio_hashes[0] == audio_hashes[1] and audio_hashes[0].startswith("SHA256="), "AAC packet payload changed")
    need(owner.sha256(master) == MASTER_SHA, "original master changed during QA")
    receipt = {"schema": SCHEMA + "-receipt", "id": "F03", "status": "DERIVED_REVIEW_MECHANICALLY_VERIFIED",
               "master": master.name, "master_sha256": MASTER_SHA, "master_bytes": MASTER_BYTES,
               "derived": derived.name, "derived_bytes": derived.stat().st_size, "derived_sha256": owner.sha256(derived),
               "frames": 12372, "duration": 412.4, "fps": 30, "segments": 47,
               "audio_packet_sha256": audio_hashes[0].split("=", 1)[1], "audio_mode": "AAC_STREAM_COPY",
               "audio_metrics": audio_metrics, "audio_gate": audio_gate,
               "source_render_run_id": 38437949183, "derivation_run_id": os.environ["GITHUB_RUN_ID"],
               "historical_run_body_binding": "UNVERIFIED_EXPIRED_ARTIFACT",
               "source_package_sha256": SOURCE_PACKAGE,
               "source_package_body_binding": "DOCUMENTED_NATIVE_PACKAGE_ASSOCIATION_NOT_PROVEN_FROM_MASTER",
               "derivation_runtime_commit": os.environ["GITHUB_SHA"], "request": r,
               "original_owner_sha256": OWNER_SHA, "private_input_files": len(rows),
               "source_master_changed": False, "film_rendered": False, "audio_mixed": False,
               "full_decode": "PASS", "audio_heard": False, "whole_film_approved": False, "release_approved": False}
    receipt["runtime_versions"] = {name: owner.run([name, "-version"], capture=True).splitlines()[0]
                                   for name in ("ffmpeg", "ffprobe")}
    receipt["qa_proxies"] = qa_proxies(owner, derived, output)
    # Genuine owner-produced provenance from this actual derivation; never labels the separate r26 1080 render as derived.
    Path(str(derived) + ".derived.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (output / "DERIVATION-RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (output / "PROBES.json").write_text(json.dumps({"master": before, "derived": after}, indent=2) + "\n")
    return receipt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", type=Path, required=True)
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--private-root", type=Path)
    ap.add_argument("--work", type=Path)
    ap.add_argument("--output", type=Path)
    a = ap.parse_args()
    if not a.preflight:
        require_hosted()
    r = request_check(json.loads(a.request.read_text()))
    if a.preflight:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("private_commit=" + r["private_commit"] + "\nprivate_prefix=" + r["private_prefix"] + "\n")
        return
    need(all((a.private_root, a.work, a.output)), "explicit private/work/output paths required")
    print(json.dumps(derive(r, a.private_root, a.work, a.output), indent=2))


if __name__ == "__main__":
    main()
