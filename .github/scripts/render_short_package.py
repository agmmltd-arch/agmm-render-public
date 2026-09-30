#!/usr/bin/env python3
"""Validate, render-check and assemble an exact AGMM short package.

This helper is intentionally media-host agnostic.  The public Actions workflow
uses it on GitHub runners; unit tests exercise the deterministic validation
without rendering or decoding video on the operator's Mac.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import tarfile
from pathlib import Path, PurePosixPath


FPS = 30
HYPERFRAMES_VERSION = "0.8.71"
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_BYTES = 4_000_000_000
MAX_PARTS = 32
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
OUT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"
)

# These are the current kit delivery caps.  1080 is produce.py CAP_1080;
# portrait 4K is the paired agmm-kit-render setting used by produce.py.
CAP_1080 = [
    "-map", "0:v:0", "-an", "-c:v", "libx264", "-profile:v", "high",
    "-preset", "slow", "-crf", "16", "-maxrate", "25M", "-bufsize", "50M",
    "-level:v", "4.2", "-pix_fmt", "yuv420p", "-r", "30", "-g", "60",
    "-video_track_timescale", "15360", "-x264-params", "threads=2",
    "-movflags", "+faststart",
]
CAP_4K = [
    "-map", "0:v:0", "-an", "-c:v", "libx264", "-profile:v", "high",
    "-preset", "medium", "-crf", "17", "-maxrate", "60M", "-bufsize", "120M",
    "-level:v", "5.1", "-pix_fmt", "yuv420p", "-r", "30", "-g", "60",
    "-video_track_timescale", "15360", "-movflags", "+faststart",
]


class ContractError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hash(value: str, label: str) -> str:
    value = value.strip().lower()
    if not HASH_RE.fullmatch(value):
        raise ContractError(f"{label} must be exactly 64 lowercase hexadecimal characters")
    return value


def verify_hash(path: Path, expected: str, label: str) -> str:
    expected = require_hash(expected, label)
    actual = sha256(path)
    if actual != expected:
        raise ContractError(f"{label} mismatch for {path.name}: expected {expected}, got {actual}")
    return actual


def normalise_member(name: str) -> PurePosixPath:
    while name.startswith("./"):
        name = name[2:]
    if not name:
        return PurePosixPath(".")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ContractError(f"unsafe archive path: {name!r}")
    if any(part == "__MACOSX" or part.startswith("._") for part in path.parts):
        raise ContractError(f"macOS metadata is forbidden in sealed packages: {name!r}")
    return path


def safe_extract(archive: Path, destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    seen: set[str] = set()
    total = 0
    names: list[str] = []
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if not members or len(members) > MAX_ARCHIVE_MEMBERS:
            raise ContractError(f"archive must contain 1..{MAX_ARCHIVE_MEMBERS} members")
        for member in members:
            rel = normalise_member(member.name)
            key = rel.as_posix().rstrip("/")
            if key in seen:
                raise ContractError(f"duplicate archive member after normalisation: {key}")
            seen.add(key)
            names.append(key)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ContractError(f"archive contains a forbidden special member: {member.name!r}")
            if not (member.isfile() or member.isdir()):
                raise ContractError(f"archive contains an unsupported member: {member.name!r}")
            if rel == PurePosixPath("."):
                if not member.isdir():
                    raise ContractError("archive root marker must be a directory")
                continue
            total += member.size
            if total > MAX_ARCHIVE_BYTES:
                raise ContractError("archive expanded size exceeds 4 GB")
            target = (root / Path(*rel.parts)).resolve()
            if target != root and root not in target.parents:
                raise ContractError(f"archive path escapes destination: {member.name!r}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise ContractError(f"archive member is unreadable: {member.name!r}")
            with target.open("wb") as output:
                shutil.copyfileobj(source, output)
    return names


def safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{label} must be a nonempty string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.startswith("./"):
        raise ContractError(f"{label} must be a clean relative path")
    if not path.parts or any(not OUT_RE.fullmatch(part) for part in path.parts):
        raise ContractError(f"{label} contains an unsafe path component")
    return value


def allowed_frame_counts(duration: float) -> set[int]:
    wanted = int(round(duration * FPS))
    return {wanted, int(math.ceil(duration * FPS - 1e-9)), wanted + 1}


def master_frame_contract(duration: float, part_counts: list[int]) -> dict:
    """Keep seam-inclusive part counts as evidence, but judge the full timeline itself."""
    return {
        "part_frame_sum": sum(part_counts),
        "expected_master_frames": sorted(allowed_frame_counts(duration)),
    }


def validate_sha_file(project: Path, look: str) -> None:
    look_root = (project / look).resolve()
    sha_file = look_root / "SHA256SUMS.txt"
    if not sha_file.is_file():
        raise ContractError(f"{look}/SHA256SUMS.txt is missing")
    checked = 0
    for number, raw in enumerate(sha_file.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", raw)
        if not match:
            raise ContractError(f"{look}/SHA256SUMS.txt:{number} is malformed")
        checksum_path = match.group(2).strip()
        while checksum_path.startswith("./"):
            checksum_path = checksum_path[2:]
        rel = safe_relative(checksum_path, f"{look} checksum path")
        target = (look_root / rel).resolve()
        if look_root not in target.parents or not target.is_file():
            raise ContractError(f"{look} checksum target is missing or escapes the look: {rel}")
        if sha256(target) != match.group(1).lower():
            raise ContractError(f"{look} checksum mismatch: {rel}")
        checked += 1
    if not checked:
        raise ContractError(f"{look}/SHA256SUMS.txt contains no file checksums")


def validate_parts(data: object, project: Path | None = None) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("parts"), list):
        raise ContractError("parts.json must be an object containing a parts list")
    rows = data["parts"]
    if not 1 <= len(rows) <= MAX_PARTS:
        raise ContractError(f"parts.json must declare 1..{MAX_PARTS} parts")
    out_names: set[str] = set()
    looks: set[str] = set()
    normalised = []
    previous_end = 0.0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ContractError(f"part {index} must be an object")
        look = safe_relative(row.get("look"), f"part {index} look")
        file_name = safe_relative(row.get("file"), f"part {index} file")
        out = row.get("out")
        if not isinstance(out, str) or not OUT_RE.fullmatch(out):
            raise ContractError(f"part {index} out is not a safe artifact name")
        if out in out_names:
            raise ContractError(f"duplicate part output: {out}")
        out_names.add(out)
        try:
            offset, duration = float(row.get("off")), float(row.get("dur"))
        except (TypeError, ValueError):
            raise ContractError(f"part {index} off and dur must be numbers") from None
        if not math.isfinite(offset) or not math.isfinite(duration) or offset < 0 or duration <= 0:
            raise ContractError(f"part {index} has an invalid offset or duration")
        if abs(offset - previous_end) > 1e-6:
            raise ContractError(
                f"part {index} is not contiguous: offset {offset:.9f}, expected {previous_end:.9f}"
            )
        previous_end = offset + duration
        clean = {"index": index, "look": look, "file": file_name, "out": out,
                 "off": offset, "dur": duration}
        normalised.append(clean)
        if project is not None:
            project_root = project.resolve()
            look_root = (project_root / look).resolve()
            source = (look_root / file_name).resolve()
            if project_root not in look_root.parents or look_root not in source.parents:
                raise ContractError(f"part {out} escapes the extracted project")
            if not source.is_file():
                raise ContractError(f"part {out} source is missing: {look}/{file_name}")
            if not (look_root / "static_check.py").is_file():
                raise ContractError(f"part {out} is missing {look}/static_check.py")
            if look not in looks:
                validate_sha_file(project_root, look)
                looks.add(look)
    intended_frames = int(round(previous_end * FPS))
    if "frames" in data and data["frames"] != intended_frames:
        raise ContractError(
            f"parts.json frames is {data['frames']!r}; contiguous duration requires {intended_frames}"
        )
    return {"parts": normalised, "duration": previous_end, "frames": intended_frames}


def build_matrix(parts: list[dict], render_4k: bool) -> dict:
    include = []
    for part in parts:
        include.append({**part, "resolution": "1080", "suffix": ""})
        if render_4k:
            include.append({**part, "resolution": "4k", "suffix": "-4K"})
    return {"include": include}


def run(command: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    process = subprocess.run(command, text=True, capture_output=capture)
    if process.returncode:
        output = ((process.stdout or "") + (process.stderr or ""))[-3000:]
        raise ContractError(f"{command[0]} failed with exit {process.returncode}: {output}")
    return process


def ffprobe(path: Path, *, count_frames: bool = False) -> dict:
    command = ["ffprobe", "-v", "error"]
    if count_frames:
        command += ["-count_frames"]
    command += ["-show_format", "-show_streams", "-of", "json", str(path)]
    return json.loads(run(command).stdout)


def stream_of(probe: dict, kind: str) -> dict:
    rows = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == kind]
    if len(rows) != 1:
        raise ContractError(f"expected exactly one {kind} stream, found {len(rows)}")
    return rows[0]


def fraction(value: str) -> float:
    numerator, denominator = value.split("/", 1)
    return float(numerator) / float(denominator)


def verify_video(path: Path, *, width: int, height: int, duration: float,
                 expect_audio: bool, expected_frames: set[int] | None = None) -> dict:
    probe = ffprobe(path, count_frames=True)
    video = stream_of(probe, "video")
    if (int(video.get("width", 0)), int(video.get("height", 0))) != (width, height):
        raise ContractError(f"{path.name} is {video.get('width')}x{video.get('height')}, expected {width}x{height}")
    if abs(fraction(video.get("avg_frame_rate", "0/1")) - FPS) > 0.001:
        raise ContractError(f"{path.name} is not {FPS} fps")
    frames = int(video.get("nb_read_frames") or video.get("nb_frames") or 0)
    allowed = expected_frames or allowed_frame_counts(duration)
    if frames not in allowed:
        raise ContractError(f"{path.name} decoded {frames} frames; expected one of {sorted(allowed)}")
    audio_rows = [item for item in probe.get("streams", []) if item.get("codec_type") == "audio"]
    if expect_audio and len(audio_rows) != 1:
        raise ContractError(f"{path.name} must contain exactly one audio stream")
    if not expect_audio and audio_rows:
        raise ContractError(f"{path.name} part must be silent before assembly")
    decode = run([
        "ffmpeg", "-hide_banner", "-v", "error", "-threads", "2", "-i", str(path),
        "-map", "0:v:0", *( ["-map", "0:a:0"] if expect_audio else ["-an"] ),
        "-f", "null", "-",
    ])
    return {"probe": probe, "frames": frames, "decode_stderr": decode.stderr or ""}


def parse_ebur128(text: str) -> dict:
    summaries = text.rsplit("Summary:", 1)
    if len(summaries) != 2:
        raise ContractError("ffmpeg ebur128 output has no final Summary block")
    summary = summaries[1]
    integrated = re.search(r"I:\s*([-+]?\d+(?:\.\d+)?) LUFS", summary)
    lra = re.search(r"LRA:\s*([-+]?\d+(?:\.\d+)?) LU", summary)
    peak = re.search(r"Peak:\s*([-+]?\d+(?:\.\d+)?) dBFS", summary)
    if not (integrated and lra and peak):
        raise ContractError("ffmpeg ebur128 final Summary is incomplete")
    return {"integrated_lufs": float(integrated.group(1)), "lra_lu": float(lra.group(1)),
            "true_peak_dbfs": float(peak.group(1))}


def audio_evidence(path: Path, *, expected_duration: float, codec: str | None = None) -> dict:
    probe = ffprobe(path)
    audio = stream_of(probe, "audio")
    if codec and audio.get("codec_name") != codec:
        raise ContractError(f"{path.name} audio codec is {audio.get('codec_name')}, expected {codec}")
    if int(audio.get("sample_rate", 0)) != 48_000:
        raise ContractError(f"{path.name} audio sample rate is not 48000 Hz")
    if int(audio.get("channels", 0)) != 2:
        raise ContractError(f"{path.name} audio is not stereo")
    duration = float(probe["format"]["duration"])
    if abs(duration - expected_duration) > 0.25:
        raise ContractError(
            f"{path.name} duration {duration:.3f}s differs from picture {expected_duration:.3f}s by more than 0.25s"
        )
    run(["ffmpeg", "-hide_banner", "-v", "error", "-threads", "2", "-i", str(path),
         "-map", "0:a:0", "-vn", "-f", "null", "-"])
    measured = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
                    "-af", "ebur128=peak=true", "-f", "null", "-"])
    metrics = parse_ebur128(measured.stderr)
    if not -15.0 <= metrics["integrated_lufs"] <= -13.0:
        raise ContractError(f"{path.name} integrated loudness is {metrics['integrated_lufs']} LUFS, expected -14 ±1")
    if metrics["true_peak_dbfs"] > -1.0:
        raise ContractError(f"{path.name} true peak is {metrics['true_peak_dbfs']} dBFS, must be <= -1.0")
    return {"probe": probe, "duration": duration, **metrics}


def cap_part(source: Path, output: Path, resolution: str) -> dict:
    cap = CAP_1080 if resolution == "1080" else CAP_4K
    before = source.stat().st_size
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), *cap, str(output)])
    return {"resolution": resolution, "bytes_before": before, "bytes_after": output.stat().st_size,
            "ffmpeg_arguments": cap}


def locate_unique(root: Path, basename: str) -> Path:
    matches = [path for path in root.rglob(basename) if path.is_file()]
    if len(matches) != 1:
        raise ContractError(f"expected exactly one {basename} under {root}, found {len(matches)}")
    return matches[0]


def load_json(path: Path, label: str) -> object:
    if not path.is_file():
        raise ContractError(f"{label} is missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ContractError(f"{label} is not valid JSON: {error}") from error


def verify_retry_source(*, run_data: object, jobs_data: object, artifacts_data: object,
                        release_data: object, exact_input: Path, repository: str,
                        source_run_id: int, source_head_sha: str, release_tag: str,
                        tag: str, source_sha256: str, parts_sha256: str,
                        mix_sha256: str, render_4k: bool) -> dict:
    """Fail closed unless a completed source run owns one exact, complete render set."""
    if not REPOSITORY_RE.fullmatch(repository):
        raise ContractError("repository must be an owner/name slug")
    if not OUT_RE.fullmatch(release_tag) or not OUT_RE.fullmatch(tag):
        raise ContractError("release and tag must be safe workflow labels")
    source_head_sha = source_head_sha.lower()
    if not re.fullmatch(r"[0-9a-f]{40}", source_head_sha):
        raise ContractError("source_head_sha must be exactly 40 lowercase hexadecimal characters")
    source_sha256 = require_hash(source_sha256, "source_sha256")
    parts_sha256 = require_hash(parts_sha256, "parts_sha256")
    mix_sha256 = require_hash(mix_sha256, "mix_sha256")

    if not isinstance(run_data, dict):
        raise ContractError("source run metadata must be an object")
    expected_run = {
        "id": source_run_id,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": source_head_sha,
        "status": "completed",
        "conclusion": "failure",
        "path": ".github/workflows/agmm-short-package.yml",
        "display_title": f"AGMM short {tag}",
    }
    for key, expected in expected_run.items():
        if run_data.get(key) != expected:
            raise ContractError(
                f"source run {key} mismatch: expected {expected!r}, got {run_data.get(key)!r}"
            )
    for key in ("repository", "head_repository"):
        value = run_data.get(key)
        if not isinstance(value, dict) or value.get("full_name") != repository:
            raise ContractError(f"source run {key} is not {repository}")

    source_path = exact_input / "source.tar.gz"
    parts_path = exact_input / "parts.json"
    mix_path = exact_input / "mix.wav"
    verify_hash(source_path, source_sha256, "source_sha256")
    verify_hash(parts_path, parts_sha256, "parts_sha256")
    verify_hash(mix_path, mix_sha256, "mix_sha256")
    raw_parts = load_json(parts_path, "parts.json")
    parsed = validate_parts(raw_parts)
    if not isinstance(raw_parts, dict) or raw_parts.get("sha256") not in (None, source_sha256):
        raise ContractError("parts.json package sha256 does not match exact source.tar.gz")
    if raw_parts.get("bytes") not in (None, source_path.stat().st_size):
        raise ContractError("parts.json package byte count does not match exact source.tar.gz")

    input_receipt = load_json(exact_input / "INPUT-RECEIPT.json", "INPUT-RECEIPT.json")
    if not isinstance(input_receipt, dict) or input_receipt.get("kind") != "agmm_short_exact_input_receipt":
        raise ContractError("INPUT-RECEIPT.json has the wrong kind")
    expected_receipt = {
        "source_sha256": source_sha256,
        "parts_sha256": parts_sha256,
        "mix_sha256": mix_sha256,
        "source_bytes": source_path.stat().st_size,
        "parts_bytes": parts_path.stat().st_size,
        "mix_bytes": mix_path.stat().st_size,
        "duration": parsed["duration"],
        "frames": parsed["frames"],
        "part_count": len(parsed["parts"]),
        "render_4k": render_4k,
        "hyperframes_version": HYPERFRAMES_VERSION,
    }
    for key, expected in expected_receipt.items():
        if input_receipt.get(key) != expected:
            raise ContractError(
                f"input receipt {key} mismatch: expected {expected!r}, got {input_receipt.get(key)!r}"
            )
    if load_json(exact_input / "NORMALISED-PARTS.json", "NORMALISED-PARTS.json") != parsed:
        raise ContractError("NORMALISED-PARTS.json does not match exact parts.json")
    if load_json(exact_input / "MATRIX.json", "MATRIX.json") != build_matrix(parsed["parts"], render_4k):
        raise ContractError("MATRIX.json does not match exact parts and render_4k identity")

    if not isinstance(jobs_data, dict) or not isinstance(jobs_data.get("jobs"), list):
        raise ContractError("source jobs metadata must contain a jobs list")
    jobs = jobs_data["jobs"]
    preflight = [row for row in jobs if row.get("name") == "preflight"]
    assemble = [row for row in jobs if row.get("name") == "assemble"]
    renders = [row for row in jobs if isinstance(row.get("name"), str) and row["name"].startswith("render (")]
    expected_render_count = len(parsed["parts"]) * (2 if render_4k else 1)
    if len(preflight) != 1 or preflight[0].get("conclusion") != "success":
        raise ContractError("source run must have exactly one successful preflight job")
    if len(assemble) != 1 or assemble[0].get("conclusion") != "failure":
        raise ContractError("source run must have exactly one failed assemble job")
    if len(renders) != expected_render_count or any(row.get("conclusion") != "success" for row in renders):
        raise ContractError(
            f"source run must have exactly {expected_render_count} successful render jobs"
        )
    if len(jobs) != 2 + expected_render_count:
        raise ContractError("source run contains an unexpected job")
    for row in jobs:
        if row.get("run_id") != source_run_id or row.get("head_sha") != source_head_sha:
            raise ContractError(f"source job identity mismatch: {row.get('name')!r}")

    if not isinstance(release_data, dict) or release_data.get("tag_name") != release_tag:
        raise ContractError("release metadata tag does not match the declared release")
    if release_data.get("draft") is not False or release_data.get("prerelease") is not False:
        raise ContractError("source release must be published and non-prerelease")
    release_assets = release_data.get("assets")
    if not isinstance(release_assets, list):
        raise ContractError("release metadata must contain an assets list")
    expected_release = {
        "source.tar.gz": (source_sha256, source_path.stat().st_size),
        "parts.json": (parts_sha256, parts_path.stat().st_size),
        "mix.wav": (mix_sha256, mix_path.stat().st_size),
    }
    if len(release_assets) != len(expected_release) \
            or {row.get("name") for row in release_assets} != set(expected_release):
        raise ContractError("source release must contain exactly source.tar.gz, parts.json and mix.wav")
    for row in release_assets:
        expected_hash, expected_size = expected_release[row["name"]]
        if (row.get("state"), row.get("digest"), row.get("size")) != (
                "uploaded", f"sha256:{expected_hash}", expected_size):
            raise ContractError(f"source release asset identity mismatch: {row['name']}")

    expected_artifacts = {f"{tag}-EXACT-INPUT"}
    for part in parsed["parts"]:
        expected_artifacts.add(f"{tag}-{part['out']}")
        if render_4k:
            expected_artifacts.add(f"{tag}-{part['out']}-4K")
    if not isinstance(artifacts_data, dict) or not isinstance(artifacts_data.get("artifacts"), list):
        raise ContractError("source artifacts metadata must contain an artifacts list")
    artifacts = artifacts_data["artifacts"]
    names = [row.get("name") for row in artifacts]
    if len(names) != len(set(names)) or set(names) != expected_artifacts:
        raise ContractError("source artifact names do not exactly match the expected input and part set")
    if artifacts_data.get("total_count") != len(expected_artifacts):
        raise ContractError("source artifact total_count does not match the expected set")
    artifact_receipts = []
    for row in artifacts:
        workflow_run = row.get("workflow_run")
        digest_value = row.get("digest")
        if row.get("expired") is not False or not isinstance(workflow_run, dict):
            raise ContractError(f"source artifact is expired or unbound: {row.get('name')!r}")
        if workflow_run.get("id") != source_run_id or workflow_run.get("head_sha") != source_head_sha:
            raise ContractError(f"source artifact run identity mismatch: {row.get('name')!r}")
        if not isinstance(digest_value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest_value):
            raise ContractError(f"source artifact digest is missing or malformed: {row.get('name')!r}")
        if not isinstance(row.get("id"), int) or row["id"] <= 0 \
                or not isinstance(row.get("size_in_bytes"), int) or row["size_in_bytes"] <= 0:
            raise ContractError(f"source artifact id or size is invalid: {row.get('name')!r}")
        artifact_receipts.append({
            "id": row.get("id"), "name": row["name"], "digest": digest_value,
            "size_in_bytes": row.get("size_in_bytes"),
        })

    return {
        "kind": "agmm_short_assembly_source_receipt",
        "technical_status": "SOURCE_IDENTITY_PASS",
        "editorial_status": "NOT_REVIEWED",
        "publication_status": "NOT_REQUESTED",
        "repository": repository,
        "source_run": {
            "id": source_run_id, "head_sha": source_head_sha,
            "workflow": expected_run["path"], "tag": tag,
            "status": "completed", "conclusion": "failure",
        },
        "release": {"tag": release_tag, "assets": sorted(expected_release)},
        "binding": {
            "source_sha256": source_sha256, "parts_sha256": parts_sha256,
            "mix_sha256": mix_sha256, "render_4k": render_4k,
        },
        "artifacts": sorted(artifact_receipts, key=lambda row: row["name"]),
    }


def concat_list(paths: list[Path], destination: Path) -> None:
    for path in paths:
        if "'" in str(path):
            raise ContractError("render path contains an apostrophe and cannot be represented safely in ffconcat")
    destination.write_text("".join(f"file '{path.resolve()}'\n" for path in paths), encoding="utf-8")


def review_times(parts: list[dict], duration: float) -> list[float]:
    times = {min(0.4, duration / 2), duration * 0.25, duration * 0.5, duration * 0.75,
             max(0.0, duration - 0.4)}
    for part in parts[1:]:
        seam = part["off"]
        times.update({max(0.0, seam - 0.04), min(duration - 0.001, seam + 0.02),
                      min(duration - 0.001, seam + 0.06)})
    return sorted(round(value, 3) for value in times if 0 <= value < duration)


def make_review(video: Path, parts: list[dict], duration: float, output: Path) -> dict:
    from PIL import Image, ImageDraw

    output.mkdir(parents=True, exist_ok=True)
    stills = []
    for index, timestamp in enumerate(review_times(parts, duration), 1):
        target = output / f"frame-{index:02d}-{timestamp:07.3f}s.jpg"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{timestamp:.3f}",
             "-i", str(video), "-frames:v", "1", "-vf", "scale=720:-2:flags=lanczos",
             "-q:v", "2", str(target)])
        stills.append({"file": target.name, "time": timestamp, "sha256": sha256(target)})
    opened = [Image.open(output / row["file"]).convert("RGB") for row in stills]
    thumb_w = 270
    thumb_h = round(opened[0].height * thumb_w / opened[0].width)
    label_h, columns = 32, 4
    rows = math.ceil(len(opened) / columns)
    sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), "#10141d")
    draw = ImageDraw.Draw(sheet)
    for index, (image, row) in enumerate(zip(opened, stills)):
        image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        x, y = (index % columns) * thumb_w, (index // columns) * (thumb_h + label_h)
        sheet.paste(image, (x, y))
        draw.text((x + 8, y + thumb_h + 7), f"{row['time']:.3f}s", fill="white")
    contact = output / "CONTACT-SHEET.jpg"
    sheet.save(contact, quality=90, optimize=True)
    for image in opened:
        image.close()
    return {"master": video.name, "times": stills, "contact_sheet": contact.name,
            "contact_sheet_sha256": sha256(contact)}


def command_prepare(args: argparse.Namespace) -> None:
    source, parts_path, mix = Path(args.source), Path(args.parts), Path(args.mix)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    source_hash = verify_hash(source, args.source_sha256, "source_sha256")
    parts_hash = verify_hash(parts_path, args.parts_sha256, "parts_sha256")
    mix_hash = verify_hash(mix, args.mix_sha256, "mix_sha256")
    project = output / "project"
    if project.exists():
        raise ContractError(f"refusing to overlay existing extraction directory: {project}")
    members = safe_extract(source, project)
    raw_parts = json.loads(parts_path.read_text(encoding="utf-8"))
    parsed = validate_parts(raw_parts, project)
    if raw_parts.get("sha256") not in (None, source_hash):
        raise ContractError("parts.json package sha256 does not match exact source.tar.gz")
    if raw_parts.get("bytes") not in (None, source.stat().st_size):
        raise ContractError("parts.json package byte count does not match exact source.tar.gz")
    audio = audio_evidence(mix, expected_duration=parsed["duration"])
    matrix = build_matrix(parsed["parts"], args.render_4k)
    receipt = {
        "kind": "agmm_short_exact_input_receipt", "source_sha256": source_hash,
        "parts_sha256": parts_hash, "mix_sha256": mix_hash, "source_bytes": source.stat().st_size,
        "parts_bytes": parts_path.stat().st_size, "mix_bytes": mix.stat().st_size,
        "archive_members": len(members), "duration": parsed["duration"], "frames": parsed["frames"],
        "part_count": len(parsed["parts"]), "render_4k": args.render_4k,
        "hyperframes_version": HYPERFRAMES_VERSION, "audio": audio,
    }
    (output / "MATRIX.json").write_text(json.dumps(matrix, separators=(",", ":")) + "\n")
    (output / "NORMALISED-PARTS.json").write_text(json.dumps(parsed, indent=2) + "\n")
    (output / "INPUT-RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")


def command_cap(args: argparse.Namespace) -> None:
    source, output = Path(args.input), Path(args.output)
    receipt = cap_part(source, output, args.resolution)
    Path(args.receipt).write_text(json.dumps(receipt, indent=2) + "\n")


def command_verify_part(args: argparse.Namespace) -> None:
    video = Path(args.video)
    width, height = ((1080, 1920) if args.resolution == "1080" else (2160, 3840))
    checked = verify_video(video, width=width, height=height, duration=args.duration,
                           expect_audio=False)
    evidence = {"kind": "agmm_short_part_technical_evidence", "file": video.name,
                "sha256": sha256(video), "bytes": video.stat().st_size,
                "resolution": args.resolution, "frames": checked["frames"],
                "allowed_frames": sorted(allowed_frame_counts(args.duration)), "probe": checked["probe"],
                "full_decode": "PASS"}
    Path(args.output).write_text(json.dumps(evidence, indent=2) + "\n")


def command_verify_retry_source(args: argparse.Namespace) -> None:
    receipt = verify_retry_source(
        run_data=load_json(Path(args.run_json), "source run metadata"),
        jobs_data=load_json(Path(args.jobs_json), "source jobs metadata"),
        artifacts_data=load_json(Path(args.artifacts_json), "source artifacts metadata"),
        release_data=load_json(Path(args.release_json), "source release metadata"),
        exact_input=Path(args.exact_input), repository=args.repository,
        source_run_id=args.source_run_id, source_head_sha=args.source_head_sha,
        release_tag=args.release, tag=args.tag, source_sha256=args.source_sha256,
        parts_sha256=args.parts_sha256, mix_sha256=args.mix_sha256,
        render_4k=args.render_4k,
    )
    Path(args.output).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def command_assemble(args: argparse.Namespace) -> None:
    parts_path, mix, renders, output = Path(args.parts), Path(args.mix), Path(args.renders), Path(args.output)
    verify_hash(parts_path, args.parts_sha256, "parts_sha256")
    verify_hash(mix, args.mix_sha256, "mix_sha256")
    parsed = validate_parts(json.loads(parts_path.read_text(encoding="utf-8")))
    output.mkdir(parents=True, exist_ok=True)
    source_audio = audio_evidence(mix, expected_duration=parsed["duration"])
    resolutions = [("1080", "", 1080, 1920, "FINAL.mp4")]
    if args.render_4k:
        resolutions.append(("4k", "-4K", 2160, 3840, "FINAL-4K.mp4"))
    masters = []
    all_part_evidence = {}
    for resolution, suffix, width, height, master_name in resolutions:
        paths, counts, part_rows = [], [], []
        for part in parsed["parts"]:
            path = locate_unique(renders, part["out"] + suffix + ".mp4")
            check = verify_video(path, width=width, height=height, duration=part["dur"], expect_audio=False)
            paths.append(path)
            counts.append(check["frames"])
            part_rows.append({"out": part["out"], "file": str(path), "sha256": sha256(path),
                              "bytes": path.stat().st_size, "frames": check["frames"],
                              "allowed_frames": sorted(allowed_frame_counts(part["dur"]))})
        concat = output / f"parts-{resolution}.ffconcat"
        concat_list(paths, concat)
        master = output / master_name
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-threads", "2",
             "-f", "concat", "-safe", "0", "-i", str(concat), "-i", str(mix),
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
             "-b:a", "320k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(master)])
        frame_contract = master_frame_contract(parsed["duration"], counts)
        verified = verify_video(master, width=width, height=height, duration=parsed["duration"],
                                expect_audio=True,
                                expected_frames=set(frame_contract["expected_master_frames"]))
        master_audio = audio_evidence(master, expected_duration=parsed["duration"], codec="aac")
        record = {"file": master.name, "sha256": sha256(master), "bytes": master.stat().st_size,
                  "resolution": resolution, "frames": verified["frames"], **frame_contract,
                  "full_decode": "PASS", "probe": verified["probe"], "audio": master_audio}
        masters.append(record)
        all_part_evidence[resolution] = part_rows
    review = make_review(output / "FINAL.mp4", parsed["parts"], parsed["duration"], output / "review")
    evidence = {"kind": "agmm_short_remote_technical_evidence", "technical_status": "PASS",
                "editorial_status": "NOT_REVIEWED", "publication_status": "NOT_REQUESTED",
                "duration": parsed["duration"], "declared_frames": parsed["frames"],
                "source_audio": source_audio, "parts": all_part_evidence, "masters": masters,
                "review": review}
    source_receipt_target = None
    if args.source_receipt:
        source_receipt_path = Path(args.source_receipt)
        source_receipt = load_json(source_receipt_path, "assembly source receipt")
        if not isinstance(source_receipt, dict) or source_receipt.get("kind") != "agmm_short_assembly_source_receipt":
            raise ContractError("assembly source receipt has the wrong kind")
        binding = source_receipt.get("binding")
        if not isinstance(binding, dict) or binding.get("parts_sha256") != args.parts_sha256.lower() \
                or binding.get("mix_sha256") != args.mix_sha256.lower() \
                or binding.get("render_4k") is not args.render_4k:
            raise ContractError("assembly source receipt does not match this assembly")
        source_run = source_receipt.get("source_run")
        if not isinstance(source_run, dict) or not isinstance(source_run.get("id"), int) \
                or not OUT_RE.fullmatch(source_run.get("tag", "")):
            raise ContractError("assembly source receipt has an invalid source run identity")
        source_receipt_target = output / "SOURCE-RUN-RECEIPT.json"
        shutil.copyfile(source_receipt_path, source_receipt_target)
        evidence["assembly_source"] = {
            "file": source_receipt_target.name,
            "sha256": sha256(source_receipt_target),
            "source_run_id": source_run["id"],
            "tag": source_run["tag"],
        }
    (output / "TECHNICAL-EVIDENCE.json").write_text(json.dumps(evidence, indent=2) + "\n")
    hash_targets = [output / row["file"] for row in masters]
    hash_targets += [output / "TECHNICAL-EVIDENCE.json", output / "review" / "CONTACT-SHEET.jpg"]
    if source_receipt_target is not None:
        hash_targets.append(source_receipt_target)
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(path)}  {path.relative_to(output)}\n" for path in hash_targets), encoding="utf-8"
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source", required=True)
    prepare.add_argument("--parts", required=True)
    prepare.add_argument("--mix", required=True)
    prepare.add_argument("--source-sha256", required=True)
    prepare.add_argument("--parts-sha256", required=True)
    prepare.add_argument("--mix-sha256", required=True)
    prepare.add_argument("--render-4k", action="store_true")
    prepare.add_argument("--output", required=True)
    prepare.set_defaults(func=command_prepare)
    cap = commands.add_parser("cap-part")
    cap.add_argument("--input", required=True)
    cap.add_argument("--output", required=True)
    cap.add_argument("--resolution", choices=("1080", "4k"), required=True)
    cap.add_argument("--receipt", required=True)
    cap.set_defaults(func=command_cap)
    verify = commands.add_parser("verify-part")
    verify.add_argument("--video", required=True)
    verify.add_argument("--resolution", choices=("1080", "4k"), required=True)
    verify.add_argument("--duration", type=float, required=True)
    verify.add_argument("--output", required=True)
    verify.set_defaults(func=command_verify_part)
    retry = commands.add_parser("verify-retry-source")
    retry.add_argument("--run-json", required=True)
    retry.add_argument("--jobs-json", required=True)
    retry.add_argument("--artifacts-json", required=True)
    retry.add_argument("--release-json", required=True)
    retry.add_argument("--exact-input", required=True)
    retry.add_argument("--repository", required=True)
    retry.add_argument("--source-run-id", type=int, required=True)
    retry.add_argument("--source-head-sha", required=True)
    retry.add_argument("--release", required=True)
    retry.add_argument("--tag", required=True)
    retry.add_argument("--source-sha256", required=True)
    retry.add_argument("--parts-sha256", required=True)
    retry.add_argument("--mix-sha256", required=True)
    retry.add_argument("--render-4k", action="store_true")
    retry.add_argument("--output", required=True)
    retry.set_defaults(func=command_verify_retry_source)
    assemble = commands.add_parser("assemble")
    assemble.add_argument("--parts", required=True)
    assemble.add_argument("--mix", required=True)
    assemble.add_argument("--parts-sha256", required=True)
    assemble.add_argument("--mix-sha256", required=True)
    assemble.add_argument("--renders", required=True)
    assemble.add_argument("--render-4k", action="store_true")
    assemble.add_argument("--source-receipt")
    assemble.add_argument("--output", required=True)
    assemble.set_defaults(func=command_assemble)
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        args.func(args)
    except (ContractError, json.JSONDecodeError, tarfile.TarError) as error:
        raise SystemExit(f"CONTRACT FAIL: {error}") from error


if __name__ == "__main__":
    main()
