#!/usr/bin/env python3
"""Hosted-only, pinned F06 Wave05 silent-picture review exporter.

The source Actions ZIP is fetched, checked, extracted and hashed only on a
GitHub-hosted Ubuntu runner. The public release contains the finished silent
picture plus the declared contact sheets and selected frames. Private source
plates, the protected base archive and the private source receipt are excluded.
No editorial, AV, Ready, release or library-pointer approval is made here.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import zipfile

REPO = "agmmltd-arch/agmm-render-public"
REPOSITORY_ID = 1397641626
RUN_ID = 37212158991
RUN_HEAD = "ecdd898910b725c326472f3b5adc6ca98f51a138"
RUN_WORKFLOW = ".github/workflows/f06-wave05-hosted-picture-capture.yml"
RUN_TITLE = f"F06 Wave05 picture capture {RUN_HEAD}"
JOB_ID = 111465371595
JOB_NAME = "capture"
ARTIFACT_ID = 11306729127
ARTIFACT_NAME = "F06-WAVE05-HOSTED-PICTURE-37212158991"
ARTIFACT_BYTES = 314614996
ARTIFACT_DIGEST = "sha256:459bd9c24ce695ecd5e22957e41953f7c2283fe69edc9625caa7254e88068e94"
ARTIFACT_CREATED = "2026-10-04T15:14:26Z"
ARTIFACT_EXPIRES = "2026-10-05T15:14:24Z"
PRIVATE_MEDIA_HEAD = "d75f21511e9603506f9cc934a0f430db6d75d172"
PRIVATE_IMAGE_GIT_BLOB = "86d888704c5e7633c6207b5930b836755e126107"
BASE_ARCHIVE_SHA256 = "82802d929d8b04f4fabec0d29da3148861b3d1cd6c28bdb9f1b7b7d21c9b935c"

VIDEO_NAME = "F06-WAVE05-SILENT-PICTURE.mp4"
FRAME_INDEX_NAME = "FRAME-REVIEW-INDEX.csv"
BOUNDARY_MAP_NAME = "BOUNDARY-FRAME-MAP.csv"
FRAME_COUNT_NAME = "FRAME-COUNT.txt"
TECH_NAME = "TECHNICAL-EVIDENCE.json"
SUMS_NAME = "SHA256SUMS.txt"
RECEIPT_NAME = "F06-PREVIEW-EXPORT.json"
PUBLIC_TAG = f"preview-F06-wave05-development-{RUN_ID}"
PUBLIC_TITLE = f"F06 Wave05 silent picture development preview {RUN_ID}"

EVIDENCE_ROOT = "agmm-render-public/agmm-render-public/remote-output/evidence"
VIDEO_MEMBER = "_temp/f06-wave05/F06-WAVE05-SILENT-PICTURE.mp4"
EVIDENCE_FIXED_FILES = {
    "check.json",
    "ffprobe.json",
    "video-frames.framemd5",
    "black-freeze-scan.txt",
    "render.log",
    FRAME_INDEX_NAME,
    BOUNDARY_MAP_NAME,
    FRAME_COUNT_NAME,
    "SOURCE-RECEIPT.json",
}
CONTACT_NAMES = {f"contact-{i:03d}.jpg" for i in range(1, 7)}
NATIVE_NAMES = {f"native-{i:03d}.png" for i in range(1, 102)}
EXPECTED_ZIP_MEMBERS = {
    f"{EVIDENCE_ROOT}/{name}" for name in EVIDENCE_FIXED_FILES | CONTACT_NAMES | NATIVE_NAMES
} | {VIDEO_MEMBER}

PUBLIC_FRAME_NAMES = CONTACT_NAMES | NATIVE_NAMES
PUBLIC_FIXED_NAMES = {
    VIDEO_NAME,
    FRAME_INDEX_NAME,
    BOUNDARY_MAP_NAME,
    FRAME_COUNT_NAME,
    TECH_NAME,
    SUMS_NAME,
    RECEIPT_NAME,
}
EXPECTED_PUBLIC_NAMES = PUBLIC_FRAME_NAMES | PUBLIC_FIXED_NAMES

MAX_ARCHIVE_BYTES = ARTIFACT_BYTES
MAX_EXPANDED_BYTES = 850_000_000
MAX_VIDEO_BYTES = 314_614_996
MIN_FREE_BYTES = 2_000_000_000
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class Refusal(ValueError):
    """Fail-closed refusal with a user-safe diagnostic."""


def parse_time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise Refusal("native timestamp is malformed") from exc
    if result.tzinfo is None:
        raise Refusal("native timestamp has no timezone")
    return result.astimezone(timezone.utc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_source(repository: dict, run: dict, jobs_doc: dict, artifacts_doc: dict,
                    observed_at: datetime | None = None) -> dict:
    """Bind the export to one exact successful F06 picture run and ZIP."""
    now = observed_at or datetime.now(timezone.utc)
    if (repository.get("full_name") != REPO or repository.get("id") != REPOSITORY_ID
            or repository.get("private") is not False or repository.get("visibility") != "public"):
        raise Refusal("source repository is not the pinned public repository")
    if run.get("id") != RUN_ID or (run.get("repository") or {}).get("full_name") != REPO:
        raise Refusal("source run identity or repository mismatch")
    if (run.get("path") != RUN_WORKFLOW or run.get("event") != "workflow_dispatch"
            or run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("head_sha") != RUN_HEAD or run.get("run_attempt") != 1
            or run.get("display_title") != RUN_TITLE):
        raise Refusal("source is not the exact completed F06 picture run")
    started, finished = parse_time(run.get("created_at")), parse_time(run.get("updated_at"))
    jobs = jobs_doc.get("jobs")
    if jobs_doc.get("total_count") != 1 or not isinstance(jobs, list) or len(jobs) != 1:
        raise Refusal("native source job inventory changed")
    job = jobs[0]
    if (job.get("id") != JOB_ID or job.get("name") != JOB_NAME or job.get("run_id") != RUN_ID
            or job.get("head_sha") != RUN_HEAD or job.get("status") != "completed"
            or job.get("conclusion") != "success"):
        raise Refusal("native F06 capture job is not the exact completed success")
    artifacts = artifacts_doc.get("artifacts")
    if artifacts_doc.get("total_count") != 1 or not isinstance(artifacts, list) or len(artifacts) != 1:
        raise Refusal("native source artifact inventory changed")
    artifact = artifacts[0]
    workflow_run = artifact.get("workflow_run") or {}
    if (artifact.get("id") != ARTIFACT_ID or artifact.get("name") != ARTIFACT_NAME
            or artifact.get("size_in_bytes") != ARTIFACT_BYTES
            or artifact.get("digest") != ARTIFACT_DIGEST or artifact.get("expired") is not False
            or workflow_run.get("id") != RUN_ID or workflow_run.get("head_sha") != RUN_HEAD
            or workflow_run.get("repository_id") != REPOSITORY_ID):
        raise Refusal("native artifact ID/name/size/digest/run binding mismatch")
    created, expires = parse_time(artifact.get("created_at")), parse_time(artifact.get("expires_at"))
    if created != parse_time(ARTIFACT_CREATED) or expires != parse_time(ARTIFACT_EXPIRES):
        raise Refusal("native artifact creation/expiry metadata changed")
    if created < started or created > finished or expires <= now:
        raise Refusal("native artifact is outside its run window or expired")
    return {
        "repository": REPO,
        "repository_id": REPOSITORY_ID,
        "run_id": RUN_ID,
        "run_head": RUN_HEAD,
        "workflow": RUN_WORKFLOW,
        "job_id": JOB_ID,
        "job_name": JOB_NAME,
        "run_attempt": 1,
        "conclusion": "success",
        "artifact": {
            "id": ARTIFACT_ID,
            "name": ARTIFACT_NAME,
            "size_in_bytes": ARTIFACT_BYTES,
            "digest": ARTIFACT_DIGEST,
            "created_at": ARTIFACT_CREATED,
            "expires_at": ARTIFACT_EXPIRES,
        },
    }


def validate_source_receipt(source: dict, observed_at: datetime | None = None) -> None:
    if (source.get("repository") != REPO or source.get("repository_id") != REPOSITORY_ID
            or source.get("run_id") != RUN_ID or source.get("run_head") != RUN_HEAD
            or source.get("workflow") != RUN_WORKFLOW or source.get("job_id") != JOB_ID
            or source.get("job_name") != JOB_NAME or source.get("run_attempt") != 1
            or source.get("conclusion") != "success"):
        raise Refusal("validated source receipt identity mismatch")
    art = source.get("artifact")
    if not isinstance(art, dict) or (
        art.get("id") != ARTIFACT_ID or art.get("name") != ARTIFACT_NAME
        or art.get("size_in_bytes") != ARTIFACT_BYTES or art.get("digest") != ARTIFACT_DIGEST
        or art.get("created_at") != ARTIFACT_CREATED or art.get("expires_at") != ARTIFACT_EXPIRES
    ):
        raise Refusal("validated source receipt artifact binding mismatch")
    if parse_time(ARTIFACT_EXPIRES) <= (observed_at or datetime.now(timezone.utc)):
        raise Refusal("native source artifact has expired")


def require_hosted_runner() -> None:
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise Refusal("artifact download, media hashing and public export require hosted Ubuntu")


def require_capacity(path: Path = Path("."), minimum_bytes: int = MIN_FREE_BYTES) -> int:
    require_hosted_runner()
    if type(minimum_bytes) is not int or minimum_bytes < ARTIFACT_BYTES * 4:
        raise Refusal("hosted free-space threshold must reserve at least four artifact sizes")
    free = shutil.disk_usage(path).free
    if free < minimum_bytes:
        raise Refusal(f"hosted runner free space {free} is below required {minimum_bytes} bytes")
    return free


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refusal(f"missing or malformed {path.name}") from exc
    if not isinstance(value, dict):
        raise Refusal(f"{path.name} must be a JSON object")
    return value


def _member_names() -> list[str]:
    return sorted(EXPECTED_ZIP_MEMBERS)


def extract_artifact_zip(archive_path: Path, source: dict, out_dir: Path) -> dict:
    """Verify native ZIP bytes and exact member contract before safe extraction."""
    require_hosted_runner()
    validate_source_receipt(source)
    if out_dir.exists():
        raise Refusal("refusing to overwrite an extracted artifact directory")
    if (archive_path.is_symlink() or not archive_path.is_file()
            or archive_path.stat().st_size != ARTIFACT_BYTES
            or archive_path.stat().st_size > MAX_ARCHIVE_BYTES):
        raise Refusal("downloaded native ZIP is absent or differs from its pinned size")
    archive_sha = sha256(archive_path)
    if "sha256:" + archive_sha != ARTIFACT_DIGEST:
        raise Refusal("downloaded native ZIP SHA-256 differs from GitHub artifact digest")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != EXPECTED_ZIP_MEMBERS:
                missing = sorted(EXPECTED_ZIP_MEMBERS - set(names))
                extra = sorted(set(names) - EXPECTED_ZIP_MEMBERS)
                raise Refusal(f"native F06 ZIP member contract mismatch; missing={missing}; extra={extra}")
            total = 0
            for info in infos:
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                parts = PurePosixPath(info.filename).parts
                if (info.is_dir() or (file_type and file_type != stat.S_IFREG)
                        or info.flag_bits & 0x1 or info.file_size < 0):
                    raise Refusal("native ZIP contains a directory, link, encrypted, or special member")
                if (PurePosixPath(info.filename).is_absolute() or ".." in parts
                        or "\\" in info.filename or (parts and ":" in parts[0])):
                    raise Refusal("native ZIP contains an unsafe path")
                total += info.file_size
                if total > MAX_EXPANDED_BYTES:
                    raise Refusal("native ZIP exceeds the bounded expansion limit")
            out_dir.mkdir(parents=True)
            for info in infos:
                destination = out_dir.joinpath(*PurePosixPath(info.filename).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=1 << 20)
                if destination.stat().st_size != info.file_size:
                    raise Refusal("extracted F06 artifact member size mismatch")
    except zipfile.BadZipFile as exc:
        raise Refusal("native source artifact is not a valid ZIP") from exc
    return {"zip_sha256": archive_sha, "zip_bytes": archive_path.stat().st_size,
            "member_count": len(EXPECTED_ZIP_MEMBERS), "members": _member_names()}


def regular_exact_tree(root: Path, expected: set[str]) -> dict[str, Path]:
    if not root.is_dir() or root.is_symlink():
        raise Refusal("artifact directory is absent or unsafe")
    found: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise Refusal("artifact contains a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise Refusal("artifact contains a non-regular entry")
        rel = path.relative_to(root).as_posix()
        if rel in found:
            raise Refusal("artifact contains a duplicate path")
        found[rel] = path
    if set(found) != expected:
        raise Refusal(f"artifact file allowlist mismatch; missing={sorted(expected-set(found))}; extra={sorted(set(found)-expected)}")
    return found


def native_frame_numbers() -> list[int]:
    seams = [27, 40, 51, 57, 69, 116, 132, 204]
    events = [79, 83, 88, 96, 142, 150, 166, 184, 210, 233, 234, 266]
    selected = ({n for boundary in seams for n in range(max(0, boundary - 2), min(288, boundary + 3))}
                 | {n for event in events for n in range(max(0, event - 2), min(288, event + 3))}
                 | {0, 1, 2, 285, 286, 287})
    return sorted(selected)


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise Refusal(f"review frame is not a PNG with IHDR: {path.name}")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def jpeg_dimensions(path: Path) -> tuple[int, int]:
    # Read only JPEG headers on the hosted exporter runner.
    with path.open("rb") as stream:
        data = stream.read(1_000_000)
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise Refusal(f"contact sheet is not a JPEG: {path.name}")
    i = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        while i < len(data) and data[i] == 0xFF:
            i += 1
        if i >= len(data):
            break
        marker = data[i]
        i += 1
        if marker in {0xD8, 0xD9, 0x01, *range(0xD0, 0xD8)}:
            continue
        if i + 2 > len(data):
            break
        length = int.from_bytes(data[i:i+2], "big")
        if length < 2 or i + length > len(data):
            break
        if marker in sof and length >= 7:
            height = int.from_bytes(data[i+3:i+5], "big")
            width = int.from_bytes(data[i+5:i+7], "big")
            return width, height
        if marker == 0xDA:
            break
        i += length
    raise Refusal(f"contact sheet JPEG dimensions are unreadable: {path.name}")


def frame_index_rows() -> list[list[str]]:
    rows = [["frame", "time_seconds", "contact_sheet", "tile_1_based"]]
    for frame in range(288):
        rows.append([str(frame), f"{frame/30:.6f}", f"contact-{frame//48+1:03d}.jpg", str(frame % 48 + 1)])
    return rows


def boundary_rows() -> list[list[str]]:
    rows = [["output_png", "source_frame", "time_seconds"]]
    rows.extend([f"native-{i:03d}.png", str(frame), f"{frame/30:.6f}"]
                for i, frame in enumerate(native_frame_numbers(), start=1))
    return rows


def validate_csv(path: Path, expected_rows: list[list[str]], label: str) -> None:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            actual = list(csv.reader(stream))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise Refusal(f"{label} is missing or malformed") from exc
    if actual != expected_rows:
        raise Refusal(f"{label} differs from the pinned F06 frame/time contract")


def validate_source_receipt_file(path: Path) -> dict:
    receipt = _json(path)
    exact_keys = {
        "private_media_commit", "new_image_git_blob_sha", "base_source_archive_sha256",
        "host_rebuilt_source_lock_sha256", "compute", "release_approval",
        "fully_decoded_video_frames", "contact_sheets", "native_review_frames",
    }
    if set(receipt) != exact_keys:
        raise Refusal("producer SOURCE-RECEIPT schema changed")
    if (receipt.get("private_media_commit") != PRIVATE_MEDIA_HEAD
            or receipt.get("new_image_git_blob_sha") != PRIVATE_IMAGE_GIT_BLOB
            or receipt.get("base_source_archive_sha256") != BASE_ARCHIVE_SHA256
            or not isinstance(receipt.get("host_rebuilt_source_lock_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", receipt["host_rebuilt_source_lock_sha256"])
            or receipt.get("compute") != "GitHub-hosted Ubuntu 24.04"
            or receipt.get("release_approval") != "NOT_GRANTED"
            or receipt.get("fully_decoded_video_frames") != 288
            or receipt.get("contact_sheets") != 6
            or receipt.get("native_review_frames") != 101):
        raise Refusal("producer SOURCE-RECEIPT does not bind the exact private inputs and frame counts")
    return receipt


def parse_framemd5_count(path: Path) -> int:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise Refusal("decoded-frame receipt is missing or malformed") from exc
    rows = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if any(len(line.split(",")) != 6 for line in rows):
        raise Refusal("decoded-frame receipt has malformed framemd5 rows")
    return len(rows)


def validate_technical_outputs(files: dict[str, Path]) -> dict:
    """Check exact producer receipts, silent 1080p/30fps picture, and review maps."""
    frame_count = files[f"{EVIDENCE_ROOT}/{FRAME_COUNT_NAME}"].read_text(encoding="utf-8")
    expected_count = (
        "288 fully decoded frames; 6 chronological sheets; 101 native cut/event frames; "
        "silent picture proof only; release approval not granted.\n"
    )
    if frame_count != expected_count:
        raise Refusal("producer FRAME-COUNT receipt differs from the pinned source output")
    if parse_framemd5_count(files[f"{EVIDENCE_ROOT}/video-frames.framemd5"]) != 288:
        raise Refusal("framemd5 does not report exactly 288 decoded frames")
    validate_csv(files[f"{EVIDENCE_ROOT}/{FRAME_INDEX_NAME}"], frame_index_rows(), FRAME_INDEX_NAME)
    validate_csv(files[f"{EVIDENCE_ROOT}/{BOUNDARY_MAP_NAME}"], boundary_rows(), BOUNDARY_MAP_NAME)

    ffprobe = _json(files[f"{EVIDENCE_ROOT}/ffprobe.json"])
    streams = ffprobe.get("streams")
    if not isinstance(streams, list):
        raise Refusal("ffprobe stream list is missing")
    video = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(video) != 1 or audio:
        raise Refusal("hosted picture must have exactly one video stream and no audio")
    v = video[0]
    fmt = ffprobe.get("format") or {}
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError) as exc:
        raise Refusal("ffprobe duration is missing or malformed") from exc
    if ((v.get("width"), v.get("height"), v.get("r_frame_rate")) != (1920, 1080, "30/1")
            or abs(duration - 9.6) >= 0.06):
        raise Refusal("ffprobe result differs from the pinned silent 1080p/30fps/9.6s scope")
    if v.get("nb_frames") not in (None, "", "288", 288):
        raise Refusal("ffprobe nb_frames differs from the exact 288-frame contract")

    video_path = files[VIDEO_MEMBER]
    video_bytes = video_path.stat().st_size
    if not 0 < video_bytes <= MAX_VIDEO_BYTES:
        raise Refusal("silent review MP4 exceeds its bounded size")
    with video_path.open("rb") as stream:
        header = stream.read(16)
    if len(header) < 8 or header[4:8] != b"ftyp":
        raise Refusal("hosted review video does not have an ISO BMFF MP4 header")

    for name in sorted(CONTACT_NAMES):
        if jpeg_dimensions(files[f"{EVIDENCE_ROOT}/{name}"]) != (1920, 1440):
            raise Refusal(f"contact sheet dimensions differ from six-by-eight 320x180 grid: {name}")
    for name in sorted(NATIVE_NAMES):
        if png_dimensions(files[f"{EVIDENCE_ROOT}/{name}"]) != (1920, 1080):
            raise Refusal(f"native selected frame is not 1920x1080: {name}")
    validate_source_receipt_file(files[f"{EVIDENCE_ROOT}/SOURCE-RECEIPT.json"])
    return {
        "video_path": video_path,
        "video_bytes": video_bytes,
        "video_sha256": sha256(video_path),
        "duration_seconds": duration,
        "ffprobe": {"width": v["width"], "height": v["height"], "r_frame_rate": v["r_frame_rate"]},
    }


def safe_technical_summary(source: dict, video: dict) -> dict:
    return {
        "kind": "f06_hosted_picture_preview_technical_summary_v1",
        "source": {
            "repository": REPO,
            "run_id": RUN_ID,
            "run_head": RUN_HEAD,
            "workflow": RUN_WORKFLOW,
            "job_id": JOB_ID,
            "artifact_id": ARTIFACT_ID,
            "artifact_name": ARTIFACT_NAME,
            "artifact_zip_bytes": ARTIFACT_BYTES,
            "artifact_zip_sha256": ARTIFACT_DIGEST.removeprefix("sha256:"),
            "artifact_zip_digest_is_video_digest": False,
        },
        "exported_silent_picture": {
            "name": VIDEO_NAME,
            "sha256": video["video_sha256"],
            "bytes": video["video_bytes"],
            "resolution": "1920x1080",
            "frame_rate": "30/1",
            "duration_seconds": video["duration_seconds"],
            "audio_streams": 0,
            "fully_decoded_frames": 288,
            "full_decode_status": "PASS_REPORTED_BY_PINNED_HOSTED_RUN",
        },
        "review_frames": {
            "contact_sheets": {"count": 6, "name_pattern": "contact-NNN.jpg", "dimensions": "1920x1440", "grid": "6x8 chronological frames"},
            "native_selected_frames": {"count": 101, "name_pattern": "native-NNN.png", "dimensions": "1920x1080", "scope": "cut boundaries, motion events, endpoints"},
            "frame_index": FRAME_INDEX_NAME,
            "boundary_map": BOUNDARY_MAP_NAME,
            "frame_count": FRAME_COUNT_NAME,
        },
        "technical_status": "PASS_REPORTED_AND_RECHECKED_BY_HOSTED_EXPORTER",
        "picture_review_status": "NOT_REVIEWED",
        "motion_review_status": "NOT_REVIEWED",
        "editorial_status": "NOT_APPROVED",
        "full_av_review": "OPEN",
        "ready": "NOT_GRANTED",
        "release_approval": "NOT_GRANTED",
        "library_pointer_updated": False,
    }


def public_release_tag() -> str:
    return PUBLIC_TAG


def prepare_export(download_dir: Path, source: dict, out_dir: Path) -> dict:
    """Validate the native artifact and stage only the explicit public preview allowlist."""
    require_hosted_runner()
    validate_source_receipt(source)
    files = regular_exact_tree(download_dir, EXPECTED_ZIP_MEMBERS)
    video = validate_technical_outputs(files)
    if out_dir.exists():
        raise Refusal("refusing to overwrite an existing prepared F06 preview payload")
    out_dir.mkdir(parents=True)

    shutil.copyfile(video["video_path"], out_dir / VIDEO_NAME)
    for name in sorted(PUBLIC_FRAME_NAMES):
        shutil.copyfile(files[f"{EVIDENCE_ROOT}/{name}"], out_dir / name)
    for name in (FRAME_INDEX_NAME, BOUNDARY_MAP_NAME, FRAME_COUNT_NAME):
        shutil.copyfile(files[f"{EVIDENCE_ROOT}/{name}"], out_dir / name)
    tech = safe_technical_summary(source, video)
    (out_dir / TECH_NAME).write_text(json.dumps(tech, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    hashed_names = sorted(EXPECTED_PUBLIC_NAMES - {SUMS_NAME, RECEIPT_NAME})
    asset_rows = []
    for name in hashed_names:
        path = out_dir / name
        asset_rows.append({"name": name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    receipt = {
        "kind": "f06_wave05_development_preview_export_v1",
        "source": source,
        "source_zip_digest_is_not_video_digest": True,
        "exported_video": {"name": VIDEO_NAME, "bytes": video["video_bytes"], "sha256": video["video_sha256"]},
        "public_preview_assets": asset_rows,
        "public_preview_asset_count_excluding_receipt_and_sums": len(asset_rows),
        "release_tag": PUBLIC_TAG,
        "release_url": f"https://github.com/{REPO}/releases/tag/{PUBLIC_TAG}",
        "preview_scope": "9.6-second silent F06 Wave05 hosted picture proof and review frames only",
        "picture_review": "NOT_REVIEWED",
        "motion_review": "NOT_REVIEWED",
        "full_av_review": "OPEN",
        "editorial_approval": "NOT_GRANTED",
        "ready": "NOT_GRANTED",
        "release_approval": "NOT_GRANTED",
        "library_pointer_updated": False,
    }
    (out_dir / RECEIPT_NAME).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sum_names = sorted(EXPECTED_PUBLIC_NAMES - {SUMS_NAME, RECEIPT_NAME})
    (out_dir / SUMS_NAME).write_text(
        "".join(f"{sha256(out_dir/name)}  {name}\n" for name in sum_names), encoding="utf-8"
    )
    if {p.name for p in out_dir.iterdir() if p.is_file()} != EXPECTED_PUBLIC_NAMES:
        raise Refusal("prepared public payload differs from its exact media/text allowlist")
    return receipt


def parse_sum_file(path: Path, expected_names: set[str]) -> dict[str, str]:
    rows: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise Refusal("public SHA256SUMS is missing or malformed") from exc
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._/-]+)", line)
        if not match:
            raise Refusal("public SHA256SUMS contains a malformed row")
        digest, name = match.groups()
        if name.startswith("/") or ".." in PurePosixPath(name).parts or name in rows:
            raise Refusal("public SHA256SUMS contains an unsafe or duplicate path")
        rows[name] = digest
    if set(rows) != expected_names:
        raise Refusal("public SHA256SUMS does not match exact release allowlist")
    return rows


def validate_prepared_export(export_dir: Path) -> tuple[dict, dict[str, dict]]:
    files = regular_exact_tree(export_dir, EXPECTED_PUBLIC_NAMES)
    receipt = _json(files[RECEIPT_NAME])
    source = receipt.get("source") or {}
    validate_source_receipt(source)
    if (receipt.get("kind") != "f06_wave05_development_preview_export_v1"
            or receipt.get("source_zip_digest_is_not_video_digest") is not True
            or receipt.get("release_tag") != PUBLIC_TAG
            or receipt.get("release_url") != f"https://github.com/{REPO}/releases/tag/{PUBLIC_TAG}"
            or receipt.get("picture_review") != "NOT_REVIEWED"
            or receipt.get("motion_review") != "NOT_REVIEWED"
            or receipt.get("full_av_review") != "OPEN"
            or receipt.get("editorial_approval") != "NOT_GRANTED"
            or receipt.get("ready") != "NOT_GRANTED"
            or receipt.get("release_approval") != "NOT_GRANTED"
            or receipt.get("library_pointer_updated") is not False):
        raise Refusal("prepared F06 export has lost pinned preview-only status")
    video_path = files[VIDEO_NAME]
    video_row = receipt.get("exported_video") or {}
    if (video_row.get("name") != VIDEO_NAME or video_row.get("bytes") != video_path.stat().st_size
            or video_row.get("sha256") != sha256(video_path)):
        raise Refusal("prepared silent picture bytes differ from the export receipt")
    rows = receipt.get("public_preview_assets")
    if (not isinstance(rows, list) or len(rows) != len(EXPECTED_PUBLIC_NAMES - {SUMS_NAME, RECEIPT_NAME})
            or {r.get("name") for r in rows if isinstance(r, dict)} != EXPECTED_PUBLIC_NAMES - {SUMS_NAME, RECEIPT_NAME}):
        raise Refusal("prepared public asset receipt differs from its exact allowlist")
    by_name = {r["name"]: r for r in rows}
    expected_rows: dict[str, dict] = {}
    for name in sorted(EXPECTED_PUBLIC_NAMES - {SUMS_NAME, RECEIPT_NAME}):
        path = files[name]
        row = by_name[name]
        digest = sha256(path)
        if row.get("bytes") != path.stat().st_size or row.get("sha256") != digest:
            raise Refusal(f"prepared public asset changed after validation: {name}")
        expected_rows[name] = {"name": name, "path": str(path), "size": path.stat().st_size, "sha256": digest}
    sums = parse_sum_file(files[SUMS_NAME], set(expected_rows))
    if sums != {name: row["sha256"] for name, row in expected_rows.items()}:
        raise Refusal("public SHA256SUMS does not bind exact video and review-frame bytes")
    expected_rows[SUMS_NAME] = {"name": SUMS_NAME, "path": str(files[SUMS_NAME]),
                                "size": files[SUMS_NAME].stat().st_size, "sha256": sha256(files[SUMS_NAME])}
    expected_rows[RECEIPT_NAME] = {"name": RECEIPT_NAME, "path": str(files[RECEIPT_NAME]),
                                   "size": files[RECEIPT_NAME].stat().st_size, "sha256": sha256(files[RECEIPT_NAME])}
    return receipt, expected_rows


def run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], text=True, capture_output=True, check=False)


def confirmed_not_found(result: subprocess.CompletedProcess) -> bool:
    """Only the exact native GitHub CLI HTTP 404 response permits prerelease creation."""
    try:
        body = json.loads(result.stdout)
    except (ValueError, TypeError):
        body = {}
    return (result.returncode == 1 and result.stderr.strip() == "gh: Not Found (HTTP 404)"
            and body.get("status") == "404" and body.get("message") == "Not Found")


def validate_release_assets(expected: dict[str, dict], assets: list[dict], tag: str) -> dict[str, dict]:
    observed: dict[str, dict] = {}
    for asset in assets:
        name = asset.get("name")
        if name not in expected or name in observed:
            raise Refusal("release contains an unexpected or duplicate asset; no overwrite")
        want = expected[name]
        if (asset.get("size") != want["size"]
                or asset.get("digest") != "sha256:" + want["sha256"]
                or asset.get("browser_download_url") != f"https://github.com/{REPO}/releases/download/{tag}/{name}"):
            raise Refusal(f"existing release asset differs from prepared bytes; no overwrite: {name}")
        observed[name] = asset
    return observed


def publish_export(export_dir: Path) -> dict:
    """Create/verify a public unapproved prerelease, but only on native 404."""
    require_hosted_runner()
    receipt, expected = validate_prepared_export(export_dir)
    lookup = run_gh(["api", f"repos/{REPO}/releases/tags/{PUBLIC_TAG}"])
    if lookup.returncode:
        if not confirmed_not_found(lookup):
            raise Refusal("release lookup was not the exact native GitHub 404; no release create attempted")
        created = run_gh([
            "release", "create", PUBLIC_TAG, "-R", REPO, "--target", RUN_HEAD,
            "--title", PUBLIC_TITLE,
            "--notes", (
                "Hosted F06 Wave05 silent-picture development proof and review frames only. "
                "Picture/motion review remains open; full AV review OPEN; approval NOT_GRANTED; Ready NOT_GRANTED."
            ),
            "--prerelease",
        ])
        if created.returncode:
            raise Refusal("public F06 preview prerelease creation failed")
        lookup = run_gh(["api", f"repos/{REPO}/releases/tags/{PUBLIC_TAG}"])
        if lookup.returncode:
            raise Refusal("created F06 prerelease could not be read back")
    try:
        release = json.loads(lookup.stdout)
    except json.JSONDecodeError as exc:
        raise Refusal("release lookup returned malformed JSON") from exc
    if (release.get("tag_name") != PUBLIC_TAG or release.get("draft") is not False
            or release.get("prerelease") is not True):
        raise Refusal("existing F06 tag is not the exact public preview prerelease")
    commit = run_gh(["api", f"repos/{REPO}/commits/{PUBLIC_TAG}"])
    if commit.returncode:
        raise Refusal("F06 preview tag commit could not be verified")
    try:
        tagged_sha = json.loads(commit.stdout).get("sha")
    except json.JSONDecodeError as exc:
        raise Refusal("F06 preview tag commit response is malformed") from exc
    if tagged_sha != RUN_HEAD:
        raise Refusal("F06 prerelease tag does not resolve to the pinned picture proof head")

    present = validate_release_assets(expected, release.get("assets", []), PUBLIC_TAG)
    missing = [expected[name]["path"] for name in sorted(set(expected) - set(present))]
    for path in missing:
        uploaded = run_gh(["release", "upload", PUBLIC_TAG, path, "-R", REPO])
        if uploaded.returncode:
            raise Refusal(f"F06 preview asset upload failed: {Path(path).name}")

    final_query = run_gh(["api", f"repos/{REPO}/releases/tags/{PUBLIC_TAG}"])
    if final_query.returncode:
        raise Refusal("F06 preview prerelease could not be read back after upload")
    try:
        final_release = json.loads(final_query.stdout)
    except json.JSONDecodeError as exc:
        raise Refusal("F06 final release metadata is malformed") from exc
    final_assets = validate_release_assets(expected, final_release.get("assets", []), PUBLIC_TAG)
    if set(final_assets) != EXPECTED_PUBLIC_NAMES:
        raise Refusal("published F06 preview asset inventory is incomplete")
    return {
        "tag": PUBLIC_TAG,
        "release_url": f"https://github.com/{REPO}/releases/tag/{PUBLIC_TAG}",
        "assets_verified": [
            {"name": name, "size": final_assets[name]["size"],
             "digest": final_assets[name]["digest"],
             "browser_download_url": final_assets[name]["browser_download_url"]}
            for name in sorted(final_assets)
        ],
        "editorial_approval": "NOT_GRANTED",
        "full_av_review": "OPEN",
        "ready": "NOT_GRANTED",
        "library_pointer_updated": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-source")
    for flag in ("repository", "run", "jobs", "artifacts", "out"):
        validate.add_argument(f"--{flag}", type=Path, required=True)
    capacity = commands.add_parser("check-capacity")
    capacity.add_argument("--minimum-bytes", type=int, default=MIN_FREE_BYTES)
    extract = commands.add_parser("extract-artifact")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--source", type=Path, required=True)
    extract.add_argument("--out-dir", type=Path, required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--download-dir", type=Path, required=True)
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--out-dir", type=Path, required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--export-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-source":
            value = validate_source(_json(args.repository), _json(args.run), _json(args.jobs), _json(args.artifacts))
            args.out.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print("exact F06 public run/job/artifact binding PASS; no media bytes downloaded")
        elif args.command == "check-capacity":
            print(f"hosted runner capacity PASS: {require_capacity(minimum_bytes=args.minimum_bytes)} free bytes")
        elif args.command == "extract-artifact":
            result = extract_artifact_zip(args.archive, _json(args.source), args.out_dir)
            print(f"native F06 ZIP digest, size and exact {result['member_count']}-member contract PASS")
        elif args.command == "prepare":
            receipt = prepare_export(args.download_dir, _json(args.source), args.out_dir)
            print(f"prepared F06 silent-picture preview, assets={receipt['public_preview_asset_count_excluding_receipt_and_sums']}; approval NOT_GRANTED")
        else:
            print(json.dumps(publish_export(args.export_dir), sort_keys=True))
        return 0
    except (Refusal, OSError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
