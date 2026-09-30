#!/usr/bin/env python3
"""Build a hash-bound hosted master from exact base and replacement segments.

The generic path consumes a normalized request written by ``--prepare-request``
and a download-provenance receipt written by ``download_patch_inputs.py``. The
legacy F07 arguments remain supported for the already-deployed two-segment
workflow, but new callers should use the request/provenance path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


FPS = 30
W4K, H4K = 3840, 2160
MASTER_GAIN_DB = -0.5
LOUDNESS_MIN_LUFS = -15.0
LOUDNESS_MAX_LUFS = -13.0
TRUE_PEAK_MAX_DBTP = -1.0
TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
FILM_ID_RE = re.compile(r"[A-Z][A-Z0-9_-]{1,31}")
RUN_ID_RE = re.compile(r"[1-9][0-9]*")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(command: list[str], *, capture: bool = False) -> str:
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if completed.returncode:
        detail = (completed.stderr or "")[-4000:] if capture else ""
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command[:5])}\n{detail}")
    return completed.stdout if capture else ""


def validate_run_id(value: Any, label: str = "run_id") -> str:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive numeric GitHub Actions run id")
    text = str(value)
    if not RUN_ID_RE.fullmatch(text):
        raise ValueError(f"{label} must be a positive numeric GitHub Actions run id: {value!r}")
    return text


def validate_tag(value: Any, label: str) -> str:
    if not isinstance(value, str) or not TAG_RE.fullmatch(value):
        raise ValueError(f"{label} must match {TAG_RE.pattern!r}: {value!r}")
    return value


def validate_film_id(value: Any) -> str:
    if not isinstance(value, str) or not FILM_ID_RE.fullmatch(value):
        raise ValueError(f"film_id must match {FILM_ID_RE.pattern!r}: {value!r}")
    return value


def finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite JSON number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def legacy_segments(duration: float) -> list[dict[str, Any]]:
    """Preserve the existing F07 8.6-second grid for legacy callers."""
    count = int(math.floor(duration / 8.6 + 1e-9))
    rows = []
    for index in range(count):
        t0 = round(index * 8.6, 3)
        length = round(8.6 if index < count - 1 else duration - t0, 3)
        rows.append({"i": f"{index + 1:02d}", "t0": t0, "len": length})
    return rows


def normalize_segments(raw: Any, duration: float) -> list[dict[str, Any]]:
    rows = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(rows, list) or not rows:
        raise ValueError("segments_json must be a non-empty JSON list")
    if len(rows) > 99:
        raise ValueError("the SEGnn artifact contract supports at most 99 segments")
    cursor = 0.0
    normalized = []
    for position, row in enumerate(rows, 1):
        if not isinstance(row, dict) or set(row) != {"i", "t0", "len"}:
            raise ValueError("each segment must contain exactly i, t0 and len")
        expected_id = f"{position:02d}"
        if row.get("i") != expected_id:
            raise ValueError(f"segment IDs must be unique and contiguous: expected {expected_id}")
        t0 = finite_number(row.get("t0"), f"SEG{expected_id}.t0")
        length = finite_number(row.get("len"), f"SEG{expected_id}.len")
        if length <= 0 or abs(t0 - cursor) > 0.002:
            raise ValueError(f"SEG{expected_id} has a gap, overlap or non-positive length")
        frames = round(length * FPS)
        if frames <= 0:
            raise ValueError(f"SEG{expected_id} has no expected frames")
        normalized.append({"i": expected_id, "t0": t0, "len": length, "frames": frames})
        cursor = round(t0 + length, 3)
    if abs(cursor - duration) > 0.01:
        raise ValueError(f"segments cover {cursor}s but expected_duration is {duration}s")
    if sum(row["frames"] for row in normalized) != round(duration * FPS):
        raise ValueError("rounded segment frame totals do not match expected_duration")
    return normalized


def normalize_patches(raw: Any, segment_ids: set[str]) -> list[dict[str, str]]:
    rows = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(rows, list) or not rows:
        raise ValueError("patches_json must be a non-empty JSON list")
    seen: set[str] = set()
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"i", "run_id", "tag"}:
            raise ValueError("each patch must contain exactly i, run_id and tag")
        sid = row.get("i")
        if not isinstance(sid, str) or not re.fullmatch(r"[0-9]{2}", sid):
            raise ValueError(f"patch segment id must be a two-digit string: {sid!r}")
        if sid not in segment_ids:
            raise ValueError(f"patch identifies a segment outside the base manifest: SEG{sid}")
        if sid in seen:
            raise ValueError(f"duplicate patch segment id: SEG{sid}")
        seen.add(sid)
        run_id = validate_run_id(row.get("run_id"), f"SEG{sid}.run_id")
        tag = validate_tag(row.get("tag"), f"SEG{sid}.tag")
        normalized.append({"i": sid, "run_id": run_id, "tag": tag,
                           "artifact": f"{tag}-SEG{sid}"})
    return sorted(normalized, key=lambda item: item["i"])


def normalize_overlay(release: Any, asset: Any, digest: Any) -> dict[str, str]:
    release_tag = validate_tag(release, "overlay_release")
    asset_name = validate_tag(asset, "overlay_asset")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ValueError("overlay_sha256 must be 64 lowercase hexadecimal characters")
    return {"release": release_tag, "asset": asset_name, "sha256": digest}


def normalize_source_audio(release: Any, asset: Any, digest: Any) -> dict[str, str]:
    release_tag = validate_tag(release, "source_release")
    asset_name = validate_tag(asset, "source_asset")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ValueError("source_sha256 must be 64 lowercase hexadecimal characters")
    return {"release": release_tag, "asset": asset_name, "sha256": digest}


def validate_repository(value: Any) -> str:
    if not isinstance(value, str) or not REPOSITORY_RE.fullmatch(value):
        raise ValueError(f"repository must be an exact owner/name identity: {value!r}")
    return value


def build_request(*, repository: Any, film_id: Any, base_run_id: Any, base_tag: Any, output_tag: Any,
                  duration: Any, segments_raw: Any, patches_raw: Any,
                  source_release: Any, source_asset: Any, source_sha256: Any,
                  overlay_release: Any, overlay_asset: Any, overlay_sha256: Any) -> dict[str, Any]:
    film = validate_film_id(film_id)
    length = finite_number(duration, "expected_duration")
    if length <= 0:
        raise ValueError("expected_duration must be positive")
    segments = normalize_segments(segments_raw, length)
    patches = normalize_patches(patches_raw, {row["i"] for row in segments})
    base_tag_value = validate_tag(base_tag, "base_tag")
    output_tag_value = validate_tag(output_tag, "output_tag")
    request: dict[str, Any] = {
        "schema": 2,
        "kind": "hosted_master_patch_request",
        "repository": validate_repository(repository),
        "film_id": film,
        "duration": length,
        "fps": FPS,
        "base": {
            "run_id": validate_run_id(base_run_id, "base_run_id"),
            "tag": base_tag_value,
        },
        "segments": segments,
        "patches": patches,
        "output_tag": output_tag_value,
        "source_audio": normalize_source_audio(source_release, source_asset, source_sha256),
        "qa_overlay": normalize_overlay(overlay_release, overlay_asset, overlay_sha256),
    }
    request["request_sha256"] = sha256_bytes(canonical_bytes(request))
    return request


def load_request(path: Path) -> dict[str, Any]:
    supplied = json.loads(path.read_text())
    if not isinstance(supplied, dict):
        raise ValueError("patch request must be a JSON object")
    recorded_hash = supplied.get("request_sha256")
    content = {key: value for key, value in supplied.items() if key != "request_sha256"}
    if not isinstance(recorded_hash, str) or sha256_bytes(canonical_bytes(content)) != recorded_hash:
        raise ValueError("patch request SHA256 does not cover its canonical content")
    rebuilt = build_request(
        repository=content.get("repository"),
        film_id=content.get("film_id"), base_run_id=content.get("base", {}).get("run_id"),
        base_tag=content.get("base", {}).get("tag"), output_tag=content.get("output_tag"),
        duration=content.get("duration"),
        segments_raw=[{key: row[key] for key in ("i", "t0", "len")}
                      for row in content.get("segments", [])],
        patches_raw=[{key: row[key] for key in ("i", "run_id", "tag")}
                     for row in content.get("patches", [])],
        source_release=content.get("source_audio", {}).get("release"),
        source_asset=content.get("source_audio", {}).get("asset"),
        source_sha256=content.get("source_audio", {}).get("sha256"),
        overlay_release=content.get("qa_overlay", {}).get("release"),
        overlay_asset=content.get("qa_overlay", {}).get("asset"),
        overlay_sha256=content.get("qa_overlay", {}).get("sha256"),
    )
    if rebuilt != supplied:
        raise ValueError("patch request is not in its unique normalized form")
    return supplied


def load_download_provenance(path: Path, request: dict[str, Any]) -> dict[str, Any]:
    supplied = json.loads(path.read_text())
    if not isinstance(supplied, dict):
        raise ValueError("download provenance must be a JSON object")
    recorded_hash = supplied.get("provenance_sha256")
    content = {key: value for key, value in supplied.items() if key != "provenance_sha256"}
    if not isinstance(recorded_hash, str) or sha256_bytes(canonical_bytes(content)) != recorded_hash:
        raise ValueError("download provenance SHA256 does not cover its canonical content")
    if supplied.get("request_sha256") != request["request_sha256"]:
        raise ValueError("download provenance is bound to a different patch request")
    if (supplied.get("schema") != 2
            or supplied.get("kind") != "hosted_master_patch_download_provenance"):
        raise ValueError("download provenance schema/kind is not accepted")
    repository = supplied.get("repository")
    if (not isinstance(repository, dict) or repository.get("full_name") != request["repository"]
            or not isinstance(repository.get("id"), int)):
        raise ValueError("download provenance repository differs from the request")
    expected_runs = {request["base"]["run_id"]} | {row["run_id"] for row in request["patches"]}
    run_rows = supplied.get("runs")
    if (not isinstance(run_rows, list) or len(run_rows) != len(expected_runs)
            or {str(row.get("run_id")) for row in run_rows} != expected_runs):
        raise ValueError("download provenance run set differs from the request")
    patch_run_ids = {row["run_id"] for row in request["patches"]}
    runs_by_id: dict[str, dict[str, Any]] = {}
    for row in run_rows:
        conclusion_ok = (row.get("conclusion") == "success" if str(row.get("run_id")) in patch_run_ids
                         else row.get("conclusion") in {"success", "failure"})
        if (str(row.get("run_id")) not in expected_runs or row.get("status") != "completed"
                or not conclusion_ok or row.get("head_repository") != request["repository"]
                or row.get("head_repository_id") != repository["id"]
                or not re.fullmatch(r"[0-9a-f]{40}", str(row.get("head_sha", "")))):
            raise ValueError(f"download provenance has an unverified source run: {row}")
        runs_by_id[str(row["run_id"])] = row

    patches = {row["i"]: row for row in request["patches"]}
    expected_artifacts: dict[str, dict[str, Any]] = {}
    for segment in request["segments"]:
        sid = segment["i"]
        patch = patches.get(sid)
        expected_artifacts[sid] = {
            "role": "patch_segment" if patch else "base_segment",
            "run_id": patch["run_id"] if patch else request["base"]["run_id"],
            "name": patch["artifact"] if patch else f"{request['base']['tag']}-SEG{sid}",
            "members": [f"SEG{sid}.mp4", f"SEG{sid}.verify.json"],
        }
    artifact_rows = supplied.get("artifacts")
    if (not isinstance(artifact_rows, list) or len(artifact_rows) != len(expected_artifacts)
            or {str(row.get("segment_id")) for row in artifact_rows} != set(expected_artifacts)):
        raise ValueError("download provenance does not contain exactly one selected artifact per segment")
    for row in artifact_rows:
        sid = str(row.get("segment_id"))
        expected = expected_artifacts[sid]
        run_row = runs_by_id[expected["run_id"]]
        if (row.get("role") != expected["role"] or row.get("name") != expected["name"]
                or str(row.get("run_id")) != expected["run_id"]
                or row.get("run_head_sha") != run_row["head_sha"]
                or not isinstance(row.get("id"), int)
                or not isinstance(row.get("size_in_bytes"), int) or row["size_in_bytes"] <= 0
                or not SHA256_RE.fullmatch(str(row.get("archive_sha256", "")))
                or row.get("members") != expected["members"]):
            raise ValueError(f"download provenance selected artifact mismatch for SEG{sid}")
    audio = supplied.get("source_audio")
    expected_audio = request["source_audio"]
    if (not isinstance(audio, dict) or audio.get("release") != expected_audio["release"]
            or audio.get("asset") != expected_audio["asset"]
            or audio.get("asset_sha256") != expected_audio["sha256"]
            or not isinstance(audio.get("release_id"), int)
            or not isinstance(audio.get("asset_id"), int)
            or not isinstance(audio.get("asset_bytes"), int) or audio["asset_bytes"] <= 0
            or audio.get("member") not in {"audio/mix.flac", "./audio/mix.flac"}
            or not isinstance(audio.get("member_bytes"), int) or audio["member_bytes"] <= 0
            or not SHA256_RE.fullmatch(str(audio.get("member_sha256", "")))):
        raise ValueError("download provenance does not cover the exact sealed source audio")
    file_rows = supplied.get("files")
    expected_file_keys = {
        (artifact["role"], sid, filename)
        for sid, artifact in expected_artifacts.items()
        for filename in artifact["members"]
    }
    expected_file_keys.add(("source_audio", None, f"{request['film_id']}-SOURCE-MIX.flac"))
    if (not isinstance(file_rows, list) or len(file_rows) != len(expected_file_keys)
            or {(row.get("role"), row.get("segment_id"), row.get("filename"))
                for row in file_rows} != expected_file_keys):
        raise ValueError("download provenance file set differs from the selected segment/audio inputs")
    for row in file_rows:
        if (not isinstance(row.get("bytes"), int) or row["bytes"] <= 0
                or not SHA256_RE.fullmatch(str(row.get("sha256", "")))):
            raise ValueError(f"download provenance has an invalid file receipt: {row}")
        sid = row.get("segment_id")
        if sid is not None:
            expected = expected_artifacts[str(sid)]
            if (str(row.get("run_id")) != expected["run_id"]
                    or row.get("artifact") != expected["name"]):
                raise ValueError(f"download provenance file source mismatch: {row}")
    audio_files = [row for row in file_rows if row.get("role") == "source_audio"]
    if len(audio_files) != 1 or audio_files[0].get("sha256") != audio["member_sha256"]:
        raise ValueError("source audio file receipt differs from the extracted tar member")
    return supplied


def provenance_file_hash(provenance: dict[str, Any], role: str, sid: str | None,
                         filename: str) -> str:
    matches = [row for row in provenance.get("files", [])
               if row.get("role") == role and row.get("segment_id") == sid
               and row.get("filename") == filename]
    if len(matches) != 1 or not SHA256_RE.fullmatch(str(matches[0].get("sha256", ""))):
        raise ValueError(f"download provenance does not uniquely cover {role} {sid or ''} {filename}")
    return str(matches[0]["sha256"])


def probe(path: Path, *, count: bool = True) -> dict[str, Any]:
    command = ["ffprobe", "-v", "error"]
    if count:
        command.append("-count_packets")
    command += ["-show_streams", "-show_format", "-of", "json", str(path)]
    return json.loads(run(command, capture=True))


def video_stream(info: dict[str, Any]) -> dict[str, Any]:
    return next(stream for stream in info["streams"] if stream.get("codec_type") == "video")


def source_audio_rate(streams: list[dict[str, Any]]) -> int:
    """Validate the sealed lossless source before the controlled 48 kHz delivery encode."""
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if (len(audio) != 1 or audio[0].get("codec_name") != "flac"
            or int(audio[0].get("sample_rate", 0)) not in (44100, 48000)
            or int(audio[0].get("channels", 0)) != 2):
        raise ValueError(f"sealed source audio is not exactly one stereo FLAC at 44.1/48 kHz: {audio}")
    return int(audio[0]["sample_rate"])


def codec_key(stream: dict[str, Any]) -> tuple[Any, ...]:
    return (stream.get("codec_name"), stream.get("profile"), stream.get("width"),
            stream.get("height"), stream.get("pix_fmt"), stream.get("r_frame_rate"),
            stream.get("time_base"), stream.get("level"))


def decode(path: Path) -> None:
    run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-i", str(path),
         "-map", "0:v:0", "-map", "0:a:0?", "-f", "null", "-"])


def measure_audio(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", str(path),
         "-map", "0:a:0", "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
         "-f", "null", "-"],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if completed.returncode:
        raise RuntimeError(f"audio measurement failed for {path.name}: {completed.stderr[-2000:]}")
    matches = re.findall(r'\{\s*"input_i".*?\}', completed.stderr, flags=re.DOTALL)
    if not matches:
        raise ValueError(f"FFmpeg loudnorm returned no input measurements for {path.name}")
    measured = json.loads(matches[-1])
    integrated = float(measured["input_i"])
    true_peak = float(measured["input_tp"])
    if not math.isfinite(integrated) or not math.isfinite(true_peak):
        raise ValueError(f"non-finite audio measurement for {path.name}")
    return {"integrated_lufs": integrated, "true_peak_dbtp": true_peak,
            "analyzer": "ffmpeg loudnorm input_i/input_tp"}


def audio_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    loudness_ok = LOUDNESS_MIN_LUFS <= metrics["integrated_lufs"] <= LOUDNESS_MAX_LUFS
    peak_ok = metrics["true_peak_dbtp"] <= TRUE_PEAK_MAX_DBTP
    return {
        "status": "PASS" if loudness_ok and peak_ok else "FAIL",
        "integrated_range_lufs": [LOUDNESS_MIN_LUFS, LOUDNESS_MAX_LUFS],
        "true_peak_max_dbtp": TRUE_PEAK_MAX_DBTP,
        "loudness_status": "PASS" if loudness_ok else "FAIL",
        "true_peak_status": "PASS" if peak_ok else "FAIL",
    }


def verify_base_integrity(path: Path, base_master: Path, provenance: dict[str, Any] | None) -> dict[str, Any]:
    report = json.loads(path.read_text())
    actual = sha256(base_master)
    recorded = report.get("outputs", {}).get("master_sha256")
    checks = report.get("checks", {})
    if recorded != actual:
        raise ValueError("base REMOTE-INTEGRITY master hash differs from the exact base master")
    if checks.get("master_full_decode") != "PASS" or checks.get("encoded_audio_loudness_and_true_peak") != "PASS":
        raise ValueError("base REMOTE-INTEGRITY does not record passed decode and audio gates")
    if provenance is not None:
        expected = provenance_file_hash(provenance, "base_master", None, base_master.name)
        if expected != actual:
            raise ValueError("download provenance base-master hash differs from the downloaded file")
        expected_integrity = provenance_file_hash(provenance, "base_master", None, path.name)
        if expected_integrity != sha256(path):
            raise ValueError("download provenance base-integrity hash differs from the downloaded file")
    return report


def assemble(*, request: dict[str, Any], base_segments_dir: Path, patch_segments_dir: Path | None,
             base_master: Path | None, base_integrity: Path | None, source_audio: Path | None,
             out: Path, provenance_path: Path | None,
             legacy_patch_runs: dict[str, str] | None = None) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    provenance = load_download_provenance(provenance_path, request) if provenance_path else None
    generic = provenance is not None
    if generic and (not source_audio or base_master or base_integrity):
        raise ValueError("generic assembly requires sealed --source-audio and forbids a base master")
    if not generic and not base_master:
        raise ValueError("legacy assembly requires --base-master")
    base_integrity_report = (verify_base_integrity(base_integrity, base_master, provenance)
                             if base_integrity and base_master else None)
    source_audio_sha256 = None
    if generic:
        assert source_audio is not None and provenance is not None
        if (not source_audio.is_file() or source_audio.is_symlink()
                or source_audio.stat().st_size <= 0):
            raise FileNotFoundError("sealed source audio is missing, empty or symlinked")
        expected_audio_hash = provenance_file_hash(
            provenance, "source_audio", None, source_audio.name)
        source_audio_sha256 = sha256(source_audio)
        if (expected_audio_hash != source_audio_sha256
                or expected_audio_hash != provenance["source_audio"]["member_sha256"]):
            raise ValueError("sealed source audio hash differs from download provenance")
    patches = {row["i"]: row for row in request["patches"]}
    rows = request["segments"]
    film_id = request["film_id"]
    selected_files: list[Path] = []
    codec_keys: set[tuple[Any, ...]] = set()
    frame_sum = 0
    evidence = []
    total_segment_bytes = 0
    for row in rows:
        sid = row["i"]
        is_patch = sid in patches
        source_dir = patch_segments_dir if is_patch and patch_segments_dir else base_segments_dir
        video = source_dir / f"SEG{sid}.mp4"
        receipt_path = source_dir / f"SEG{sid}.verify.json"
        if not video.is_file() or not receipt_path.is_file() or video.is_symlink() or receipt_path.is_symlink():
            raise FileNotFoundError(f"missing, non-regular or symlinked segment evidence: SEG{sid}")
        if provenance is not None:
            role = "patch_segment" if is_patch else "base_segment"
            for path in (video, receipt_path):
                if provenance_file_hash(provenance, role, sid, path.name) != sha256(path):
                    raise ValueError(f"download provenance hash differs for {path.name}")
        receipt = json.loads(receipt_path.read_text())
        info = probe(video)
        stream = video_stream(info)
        packets = int(stream.get("nb_read_packets", 0))
        digest = sha256(video)
        if (receipt.get("status") != "PASS" or receipt.get("full_decode") != "PASS"
                or receipt.get("flicker", {}).get("status") != "PASS"
                or receipt.get("sha256") != digest or receipt.get("frames") != packets):
            raise ValueError(f"hosted verification receipt does not cover SEG{sid}")
        if (stream.get("codec_name") != "h264" or stream.get("width") != W4K
                or stream.get("height") != H4K or stream.get("pix_fmt") != "yuv420p"
                or stream.get("r_frame_rate") != "30/1" or packets != row["frames"]):
            raise ValueError(f"SEG{sid} profile/frame mismatch: {stream}")
        codec_keys.add(codec_key(stream))
        selected_files.append(video)
        frame_sum += packets
        total_segment_bytes += video.stat().st_size
        source = patches.get(sid)
        source_run_id = source["run_id"] if source else request["base"]["run_id"]
        source_artifact = source["artifact"] if source else f"{request['base']['tag']}-SEG{sid}"
        if legacy_patch_runs and sid in legacy_patch_runs:
            source_run_id = legacy_patch_runs[sid]
        evidence.append({
            "id": sid, "t0": row["t0"], "len": row["len"], "frames": packets,
            "bytes": video.stat().st_size, "sha256": digest,
            "source_kind": "patch" if is_patch else "base",
            "source_run_id": source_run_id, "source_artifact": source_artifact,
            "hosted_receipt_sha256": sha256(receipt_path), "hosted_receipt": receipt,
        })
    if len(codec_keys) != 1 or frame_sum != round(request["duration"] * FPS):
        raise ValueError("patched segment set differs in codec or total frame count")

    free = shutil.disk_usage(out).free
    audio_input = source_audio if generic else base_master
    assert audio_input is not None
    minimum_free = int(total_segment_bytes * 2.5 + audio_input.stat().st_size + 1.5 * 1024**3)
    if free < minimum_free:
        raise OSError(f"runner disk guard: free={free} bytes, required>{minimum_free}")

    adjusted_mix: Path | None = None
    adjusted_mix_metrics: dict[str, Any] | None = None
    adjusted_mix_sha256: str | None = None
    source_sample_rate: int | None = None
    if generic:
        assert source_audio is not None
        source_probe = probe(source_audio, count=False)
        source_sample_rate = source_audio_rate(source_probe.get("streams", []))
        adjusted_mix = out / f"{film_id}-MIX-GAIN-ADJUSTED.flac"
        run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-y", "-i", str(source_audio),
             "-map", "0:a:0", "-af", f"volume={MASTER_GAIN_DB}dB", "-sample_fmt", "s32",
             "-c:a", "flac", "-compression_level", "8", str(adjusted_mix)])
        adjusted_mix_metrics = measure_audio(adjusted_mix)
        adjusted_mix_sha256 = sha256(adjusted_mix)
    else:
        assert base_master is not None
        base_probe = probe(base_master)
        base_audio = next((stream for stream in base_probe["streams"]
                           if stream.get("codec_type") == "audio"), None)
        if (not base_audio or base_audio.get("codec_name") != "aac"
                or base_audio.get("sample_rate") != "48000"):
            raise ValueError(f"base master audio is not the verified AAC/48k stream: {base_audio}")

    concat = out / "concat.txt"
    concat.write_text("".join(f"file '{path.resolve()}'\n" for path in selected_files))
    video_only = out / f"{film_id}-PATCHED-VIDEO-ONLY.mp4"
    run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-y", "-f", "concat", "-safe", "0",
         "-i", str(concat), "-map", "0:v:0", "-an", "-c:v", "copy", str(video_only)])
    master = out / f"{film_id}-MASTER-4K.mp4"
    if generic:
        assert adjusted_mix is not None
        run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-y", "-i", str(video_only),
             "-i", str(adjusted_mix), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-shortest",
             "-movflags", "+faststart", str(master)])
    else:
        assert base_master is not None
        run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-y", "-i", str(video_only),
             "-i", str(base_master), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
             "-c:a", "copy", "-movflags", "+faststart", str(master)])
    master_probe = probe(master)
    master_video = video_stream(master_probe)
    master_frames = int(master_video.get("nb_read_packets", 0))
    output_audio = next((stream for stream in master_probe["streams"]
                         if stream.get("codec_type") == "audio"), None)
    if (master_frames != frame_sum or master_video.get("width") != W4K
            or master_video.get("height") != H4K or not output_audio
            or output_audio.get("codec_name") != "aac" or output_audio.get("sample_rate") != "48000"):
        raise ValueError(f"patched master probe mismatch: video={master_video}, audio={output_audio}")
    decode(master)
    audio_metrics = measure_audio(master)
    audio_result = audio_gate(audio_metrics)
    if audio_result["status"] != "PASS":
        raise ValueError(f"encoded master audio failed its release gate: {audio_metrics}")

    audio_receipt: dict[str, Any]
    if generic:
        audio_receipt = {
            "original_mix": source_audio.name if source_audio else None,
            "original_mix_sha256": source_audio_sha256,
            "source_release": request["source_audio"]["release"],
            "source_asset": request["source_audio"]["asset"],
            "source_asset_sha256": request["source_audio"]["sha256"],
            "source_member": provenance["source_audio"]["member"] if provenance else None,
            "source_sample_rate": source_sample_rate,
            "delivery_sample_rate": 48000,
            "adjusted_mix": adjusted_mix.name if adjusted_mix else None,
            "adjusted_mix_sha256": adjusted_mix_sha256,
            "gain_db": MASTER_GAIN_DB,
            "adjusted_mix_metrics": adjusted_mix_metrics,
            "encoded_master_metrics": audio_metrics,
            "encoded_master_gate": audio_result,
            "status": audio_result["status"],
        }
    else:
        audio_receipt = {
            "base_master": base_master.name if base_master else None,
            "base_master_sha256": sha256(base_master) if base_master else None,
            "gain_db": None,
            "encoded_master_metrics": audio_metrics,
            "encoded_master_gate": audio_result,
            "status": audio_result["status"],
        }
    audio_receipt_path = out / "AUDIO-GAIN-RECEIPT.json"
    audio_receipt_path.write_text(json.dumps(audio_receipt, indent=2) + "\n")

    derived = out / f"{film_id}-MASTER-1080-from-4K.mp4"
    run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-y", "-i", str(master),
         "-vf", "scale=1920:1080:flags=lanczos", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
         "-x264-params", "threads=2", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
         str(derived)])
    derived_probe = probe(derived)
    derived_video = video_stream(derived_probe)
    if (int(derived_video.get("nb_read_packets", 0)) != frame_sum
            or derived_video.get("width") != 1920 or derived_video.get("height") != 1080
            or derived_video.get("codec_name") != "h264"):
        raise ValueError(f"patched review master probe mismatch: {derived_video}")
    decode(derived)

    sidecar = {
        "master": master.name, "master_bytes": master.stat().st_size,
        "master_sha256": sha256(master), "derived": derived.name,
        "derived_bytes": derived.stat().st_size, "derived_sha256": sha256(derived),
        "segments": len(rows), "frames": frame_sum, "duration": request["duration"],
        "base_master_sha256": sha256(base_master) if base_master else None,
        "source_audio_sha256": source_audio_sha256,
        "adjusted_mix_sha256": adjusted_mix_sha256, "audio_metrics": audio_metrics,
    }
    sidecar_path = out / f"{derived.name}.derived.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n")
    provenance_receipt = {
        "kind": "hosted_master_patch_provenance", "request": request,
        "request_sha256": request["request_sha256"],
        "download_provenance_sha256": (provenance.get("provenance_sha256") if provenance else None),
        "base_integrity_sha256": sha256(base_integrity) if base_integrity else None,
        "base_master_sha256": sha256(base_master) if base_master else None,
        "source_audio": ({**provenance["source_audio"], "local_sha256": source_audio_sha256}
                         if provenance else None),
        "patches": [{**patch, "segment_sha256": next(row["sha256"] for row in evidence
                                                       if row["id"] == patch["i"])}
                    for patch in request["patches"]],
    }
    provenance_receipt["provenance_sha256"] = sha256_bytes(canonical_bytes(provenance_receipt))
    provenance_receipt_path = out / "PATCH-PROVENANCE.json"
    provenance_receipt_path.write_text(json.dumps(provenance_receipt, indent=2) + "\n")
    report = {
        "kind": "mechanical_integrity_patched_master", "editorial_gate": "NOT_RUN",
        "release_approval": "NOT_GRANTED", "film_id": film_id,
        "base_run_id": request["base"]["run_id"],
        "patch_request_sha256": request["request_sha256"],
        "download_provenance_sha256": provenance_receipt["download_provenance_sha256"],
        "patch_provenance_sha256": provenance_receipt["provenance_sha256"],
        "patches": request["patches"], "duration": request["duration"], "fps": FPS,
        "segment_count": len(rows), "frame_count": frame_sum, "segments": evidence,
        "video_codec_key": list(next(iter(codec_keys))), "base_integrity": base_integrity_report,
        "master_probe": master_probe, "derived_probe": derived_probe, "outputs": sidecar,
        "audio_mix": audio_receipt,
        "checks": {
            "patch_request_format_and_uniqueness": "PASS",
            "exact_repository_and_source_runs": "PASS" if provenance else "LEGACY_NOT_RECORDED",
            "selected_artifact_archives_and_members": "PASS" if provenance else "LEGACY_NOT_RECORDED",
            "sealed_source_audio_hash_binding": "PASS" if provenance else "LEGACY_NOT_RECORDED",
            "all_hosted_segment_receipts": "PASS",
            "patched_segment_ids": [row["i"] for row in request["patches"]],
            "master_full_decode": "PASS", "derived_full_decode": "PASS",
            "source_audio_gain_and_aac_encode": "PASS" if provenance else "LEGACY_NOT_RECORDED",
            "base_audio_copied_without_reencode": "LEGACY_PASS" if not provenance else "NOT_APPLICABLE",
            "encoded_audio_loudness_and_true_peak": audio_result["status"],
        },
    }
    integrity_path = out / "REMOTE-INTEGRITY.json"
    integrity_path.write_text(json.dumps(report, indent=2) + "\n")
    sums = []
    excluded = {"SHA256SUMS.txt", "concat.txt", video_only.name}
    for path in sorted(out.iterdir()):
        if path.is_file() and path.name not in excluded:
            sums.append(f"{sha256(path)}  {path.name}")
    (out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    return report


def legacy_request(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, str]]:
    patch_runs = json.loads(args.patch_runs_json)
    if not isinstance(patch_runs, dict) or not patch_runs:
        raise ValueError("legacy --patch-runs-json must be a non-empty object")
    normalized_runs: dict[str, str] = {}
    patches = []
    for sid, run_id in patch_runs.items():
        if not isinstance(sid, str) or not re.fullmatch(r"[0-9]{2}", sid):
            raise ValueError(f"invalid legacy patch segment id: {sid!r}")
        normalized_runs[sid] = validate_run_id(run_id, f"SEG{sid}.run_id")
        patches.append({"i": sid, "run_id": normalized_runs[sid], "tag": "LEGACY"})
    request = build_request(
        repository="legacy/legacy", film_id=args.film_id,
        base_run_id=args.base_run_id, base_tag="LEGACY",
        output_tag="LEGACY", duration=args.duration,
        segments_raw=legacy_segments(args.duration), patches_raw=patches,
        source_release="LEGACY", source_asset="LEGACY", source_sha256="0" * 64,
        overlay_release="LEGACY", overlay_asset="LEGACY", overlay_sha256="0" * 64,
    )
    return request, normalized_runs


def self_test() -> None:
    duration = 632.434
    rows = legacy_segments(duration)
    patches = [
        {"i": "01", "run_id": 36760000001, "tag": "F07-hook-fix"},
        {"i": "12", "run_id": "36760000012", "tag": "F07-bridge-fix"},
        {"i": "28", "run_id": 36764766443, "tag": "F07-kraken-fix"},
        {"i": "29", "run_id": 36764766443, "tag": "F07-kraken-fix"},
        {"i": "43", "run_id": 36771687018, "tag": "F07-typography-fix"},
        {"i": "45", "run_id": 36771687018, "tag": "F07-typography-fix"},
        {"i": "52", "run_id": 36771687018, "tag": "F07-typography-fix"},
    ]
    request = build_request(
        repository="agmmltd-arch/agmm-render-public", film_id="F07",
        base_run_id="36760863361", base_tag="F07-r4-full",
        output_tag="F07-r4-patched", duration=duration, segments_raw=rows,
        patches_raw=patches, source_release="F07-source", source_asset="source.tar.gz",
        source_sha256="b" * 64, overlay_release="F07-overlay", overlay_asset="qa-overlay.tar.gz",
        overlay_sha256="a" * 64,
    )
    assert [row["i"] for row in request["patches"]] == ["01", "12", "28", "29", "43", "45", "52"]
    assert len(request["segments"]) == 73 and sum(row["frames"] for row in request["segments"]) == 18973
    assert request["patches"][2]["artifact"] == "F07-kraken-fix-SEG28"
    try:
        build_request(
            repository="agmmltd-arch/agmm-render-public", film_id="F07",
            base_run_id="36760863361", base_tag="F07-r4-full",
            output_tag="F07-r4-patched", duration=duration, segments_raw=rows,
            patches_raw=patches + [patches[0]], source_release="F07-source",
            source_asset="source.tar.gz", source_sha256="b" * 64, overlay_release="F07-overlay",
            overlay_asset="qa-overlay.tar.gz", overlay_sha256="a" * 64,
        )
    except ValueError as error:
        assert "duplicate patch" in str(error)
    else:
        raise AssertionError("duplicate patch segment was accepted")
    assert audio_gate({"integrated_lufs": -14.8, "true_peak_dbtp": -1.3})["status"] == "PASS"
    assert audio_gate({"integrated_lufs": -14.8, "true_peak_dbtp": -0.9})["status"] == "FAIL"
    assert source_audio_rate([{"codec_type": "audio", "codec_name": "flac", "sample_rate": "44100", "channels": 2}]) == 44100
    assert source_audio_rate([{"codec_type": "audio", "codec_name": "flac", "sample_rate": "48000", "channels": 2}]) == 48000
    try:
        source_audio_rate([{"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100", "channels": 2}])
    except ValueError:
        pass
    else:
        raise AssertionError("lossy source audio was accepted")
    print("self-test PASS: generic 7-patch request, coverage, source audio rates and delivery audio gate")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare-request", action="store_true")
    parser.add_argument("--request-out", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--film-id", default="F07")
    parser.add_argument("--base-run-id")
    parser.add_argument("--base-tag")
    parser.add_argument("--output-tag")
    parser.add_argument("--segments-json")
    parser.add_argument("--patches-json")
    parser.add_argument("--source-release")
    parser.add_argument("--source-asset")
    parser.add_argument("--source-sha256")
    parser.add_argument("--overlay-release")
    parser.add_argument("--overlay-asset")
    parser.add_argument("--overlay-sha256")
    parser.add_argument("--segments-dir", type=Path)
    parser.add_argument("--base-segments-dir", type=Path)
    parser.add_argument("--patch-segments-dir", type=Path)
    parser.add_argument("--base-master", type=Path)
    parser.add_argument("--base-integrity", type=Path)
    parser.add_argument("--source-audio", type=Path)
    parser.add_argument("--download-provenance", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--patch-runs-json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        self_test()
        return
    if args.prepare_request:
        required = {
            "request_out": args.request_out, "repository": args.repository,
            "base_run_id": args.base_run_id,
            "base_tag": args.base_tag, "output_tag": args.output_tag,
            "segments_json": args.segments_json, "patches_json": args.patches_json,
            "duration": args.duration, "source_release": args.source_release,
            "source_asset": args.source_asset, "source_sha256": args.source_sha256,
            "overlay_release": args.overlay_release,
            "overlay_asset": args.overlay_asset, "overlay_sha256": args.overlay_sha256,
        }
        missing = sorted(key for key, value in required.items() if value is None)
        if missing:
            raise ValueError(f"missing prepare-request arguments: {missing}")
        request = build_request(
            repository=args.repository, film_id=args.film_id,
            base_run_id=args.base_run_id, base_tag=args.base_tag,
            output_tag=args.output_tag, duration=args.duration, segments_raw=args.segments_json,
            patches_raw=args.patches_json, source_release=args.source_release,
            source_asset=args.source_asset, source_sha256=args.source_sha256,
            overlay_release=args.overlay_release,
            overlay_asset=args.overlay_asset, overlay_sha256=args.overlay_sha256,
        )
        args.request_out.write_text(json.dumps(request, indent=2) + "\n")
        print(json.dumps({"status": "PASS", "request_sha256": request["request_sha256"],
                          "patches": [row["i"] for row in request["patches"]]}))
        return

    if not args.out:
        raise ValueError("--out is required for assembly")
    if args.request:
        request = load_request(args.request)
        if not args.base_segments_dir or not args.patch_segments_dir:
            raise ValueError("generic assembly requires --base-segments-dir and --patch-segments-dir")
        if not args.download_provenance or not args.source_audio:
            raise ValueError("generic assembly requires download provenance and sealed source audio")
        report = assemble(
            request=request, base_segments_dir=args.base_segments_dir,
            patch_segments_dir=args.patch_segments_dir, base_master=None,
            base_integrity=None, source_audio=args.source_audio, out=args.out,
            provenance_path=args.download_provenance,
        )
    else:
        if (not args.segments_dir or not args.base_master or args.duration is None
                or not args.base_run_id or not args.patch_runs_json):
            raise ValueError("legacy assembly arguments are incomplete")
        request, patch_runs = legacy_request(args)
        report = assemble(
            request=request, base_segments_dir=args.segments_dir, patch_segments_dir=None,
            base_master=args.base_master, base_integrity=None, source_audio=None, out=args.out,
            provenance_path=None, legacy_patch_runs=patch_runs,
        )
    print(json.dumps({"status": "PASS", "master_sha256": report["outputs"]["master_sha256"],
                      "frames": report["frame_count"],
                      "patches": [row["i"] for row in report["patches"]]}))


if __name__ == "__main__":
    main()
