#!/usr/bin/env python3
"""Hosted-only durable export of the exact Film 08 Wave06 diagnostic proof.

This exporter accepts only the pinned successful public Actions run and its
single exact artifact. It never changes the content-library pointer or review
status. Artifact download, media hashing, and release upload require hosted Linux.
"""
from __future__ import annotations

import argparse
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
RUN_ID = 37213603867
RUN_HEAD = "0e24eb4e932d54fee571e37338d3c9807edac922"
RUN_WORKFLOW = ".github/workflows/film08-wave06-proof.yml"
RUN_TITLE = f"Film 08 Wave 06 proof for {RUN_HEAD}"
JOB_ID = 111469551150
JOB_NAME = "proof"
ARTIFACT_ID = 11308040079
ARTIFACT_NAME = "F08-W06-hosted-motion-proof-37213603867"
ARTIFACT_BYTES = 25546926
ARTIFACT_DIGEST = "sha256:c2c4bd9aea01b4edffc0dc0fc38604a7febad3912f8f4277c2854ff15ced49d7"
ARTIFACT_CREATED = "2026-10-04T15:37:33Z"
ARTIFACT_EXPIRES = "2026-10-07T15:37:30Z"
VIDEO_PATH = "out/F08-W06-opening-proof-1080p.mp4"
PROOF_PATH = "out/hosted-proof-manifest.json"
PROBE_PATH = "out/ffprobe.json"
CONTACT_PATH = "out/contact-sheet-2fps.png"
LOG_PATH = "out/render.log"
FRAME_TIMES = ("0", "1.65", "1.72", "2.40", "3.20", "3.50", "3.55", "3.90", "4.50", "4.90", "5.10", "5.45", "5.95", "6.50", "7.60", "8.25", "9.05", "10.30", "11.50")
FRAME_PATHS = tuple(f"out/native-frames/frame-{time.replace('.', 'p')}.png" for time in FRAME_TIMES)
VERSION_PATHS = ("node-version.txt", "hyperframes-version.txt", "ffmpeg-version.txt", "python-version.txt")
EXPECTED_ARTIFACT_FILES = {VIDEO_PATH, PROOF_PATH, PROBE_PATH, CONTACT_PATH, LOG_PATH, *FRAME_PATHS, *VERSION_PATHS}
VIDEO_NAME = "F08-W06-opening-proof-1080p.mp4"
CONTACT_NAME = "F08-W06-contact-sheet-2fps.png"
FRAME_NAMES = tuple(f"F08-W06-frame-{time.replace('.', 'p')}.png" for time in FRAME_TIMES)
TECH_NAME = "F08-W06-TECHNICAL-EVIDENCE.json"
SUMS_NAME = "SHA256SUMS.txt"
RECEIPT_NAME = "F08-W06-PREVIEW-EXPORT.json"
MAX_VIDEO_BYTES = 200_000_000
MAX_UNZIPPED_BYTES = 150_000_000
MIN_FREE_BYTES = 1_000_000_000
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class Refusal(ValueError):
    pass


def parse_time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise Refusal("native metadata timestamp is malformed") from exc
    if result.tzinfo is None:
        raise Refusal("native metadata timestamp has no timezone")
    return result.astimezone(timezone.utc)


def validate_source(repository: dict, run: dict, jobs_doc: dict, artifacts_doc: dict,
                    observed_at: datetime | None = None) -> dict:
    observed_at = observed_at or datetime.now(timezone.utc)
    if (repository.get("full_name") != REPO or repository.get("id") != REPOSITORY_ID
            or repository.get("private") is not False or repository.get("visibility") != "public"):
        raise Refusal("source repository is not the pinned public repository")
    if run.get("id") != RUN_ID or (run.get("repository") or {}).get("full_name") != REPO:
        raise Refusal("source run identity/repository mismatch")
    if (run.get("path") != RUN_WORKFLOW or run.get("event") != "workflow_dispatch"
            or run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("head_sha") != RUN_HEAD or run.get("run_attempt") != 1
            or run.get("display_title") != RUN_TITLE):
        raise Refusal("source is not the exact completed F08 Wave06 motion proof")
    run_start, run_end = parse_time(run.get("created_at")), parse_time(run.get("updated_at"))
    jobs = jobs_doc.get("jobs")
    if jobs_doc.get("total_count") != 1 or not isinstance(jobs, list) or len(jobs) != 1:
        raise Refusal("source job inventory changed")
    job = jobs[0]
    if (job.get("id") != JOB_ID or job.get("name") != JOB_NAME or job.get("run_id") != RUN_ID
            or job.get("head_sha") != RUN_HEAD or job.get("status") != "completed"
            or job.get("conclusion") != "success"):
        raise Refusal("F08 proof job is not the exact completed success")
    artifacts = artifacts_doc.get("artifacts")
    if artifacts_doc.get("total_count") != 1 or not isinstance(artifacts, list) or len(artifacts) != 1:
        raise Refusal("source artifact inventory changed")
    artifact = artifacts[0]
    workflow_run = artifact.get("workflow_run") or {}
    if (artifact.get("id") != ARTIFACT_ID or artifact.get("name") != ARTIFACT_NAME
            or artifact.get("size_in_bytes") != ARTIFACT_BYTES or artifact.get("digest") != ARTIFACT_DIGEST
            or artifact.get("expired") is not False or workflow_run.get("id") != RUN_ID
            or workflow_run.get("head_sha") != RUN_HEAD or workflow_run.get("repository_id") != REPOSITORY_ID):
        raise Refusal("source artifact ID/name/size/digest/run binding mismatch")
    created, expires = parse_time(artifact.get("created_at")), parse_time(artifact.get("expires_at"))
    if created != parse_time(ARTIFACT_CREATED) or expires != parse_time(ARTIFACT_EXPIRES):
        raise Refusal("source artifact creation/expiry metadata changed")
    if created < run_start or created > run_end or expires <= observed_at:
        raise Refusal("source artifact is outside its run window or expired")
    return {
        "run_id": RUN_ID, "repository": REPO, "repository_id": REPOSITORY_ID,
        "workflow": RUN_WORKFLOW, "head_sha": RUN_HEAD, "job_id": JOB_ID,
        "job_name": JOB_NAME, "conclusion": "success", "run_attempt": 1,
        "artifact": {"id": ARTIFACT_ID, "name": ARTIFACT_NAME,
                     "size_in_bytes": ARTIFACT_BYTES, "digest": ARTIFACT_DIGEST,
                     "created_at": ARTIFACT_CREATED, "expires_at": ARTIFACT_EXPIRES},
    }


def validate_source_receipt(source: dict, observed_at: datetime | None = None) -> None:
    if (source.get("run_id") != RUN_ID or source.get("repository") != REPO
            or source.get("repository_id") != REPOSITORY_ID or source.get("workflow") != RUN_WORKFLOW
            or source.get("head_sha") != RUN_HEAD or source.get("job_id") != JOB_ID
            or source.get("job_name") != JOB_NAME or source.get("conclusion") != "success"
            or source.get("run_attempt") != 1):
        raise Refusal("validated source receipt identity mismatch")
    artifact = source.get("artifact")
    if not isinstance(artifact, dict) or (artifact.get("id") != ARTIFACT_ID
            or artifact.get("name") != ARTIFACT_NAME or artifact.get("size_in_bytes") != ARTIFACT_BYTES
            or artifact.get("digest") != ARTIFACT_DIGEST or artifact.get("created_at") != ARTIFACT_CREATED
            or artifact.get("expires_at") != ARTIFACT_EXPIRES):
        raise Refusal("validated source receipt artifact binding mismatch")
    if parse_time(ARTIFACT_EXPIRES) <= (observed_at or datetime.now(timezone.utc)):
        raise Refusal("source artifact has expired")


def require_hosted_runner() -> None:
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise Refusal("artifact download, media hashing, and release require GitHub-hosted Linux")


def require_capacity(path: Path = Path("."), minimum_bytes: int = MIN_FREE_BYTES) -> int:
    require_hosted_runner()
    if type(minimum_bytes) is not int or minimum_bytes <= 0:
        raise Refusal("free-space threshold must be a positive integer")
    free = shutil.disk_usage(path).free
    if free < minimum_bytes:
        raise Refusal(f"runner has {free} free bytes; requires {minimum_bytes}")
    return free


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def extract_artifact_zip(archive_path: Path, source: dict, out_dir: Path) -> dict:
    require_hosted_runner()
    validate_source_receipt(source)
    art = source["artifact"]
    if out_dir.exists():
        raise Refusal("refusing to overwrite an existing extracted source artifact")
    if archive_path.is_symlink() or not archive_path.is_file() or archive_path.stat().st_size != art["size_in_bytes"]:
        raise Refusal("downloaded source ZIP is absent or differs from native artifact size")
    zip_hash = sha256(archive_path)
    if "sha256:" + zip_hash != art["digest"]:
        raise Refusal("downloaded source ZIP digest differs from native artifact digest")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != EXPECTED_ARTIFACT_FILES:
                raise Refusal("source ZIP members differ from the exact 28-file artifact allowlist")
            expanded = 0
            for info in infos:
                mode = info.external_attr >> 16
                path = PurePosixPath(info.filename)
                if (info.is_dir() or (mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG)) or info.flag_bits & 1
                        or path.is_absolute() or ".." in path.parts or "\\" in info.filename):
                    raise Refusal("source ZIP contains a directory, link, encrypted, or unsafe member")
                expanded += info.file_size
                if expanded > MAX_UNZIPPED_BYTES:
                    raise Refusal("source ZIP exceeds the expansion limit")
            out_dir.mkdir(parents=True)
            for info in infos:
                destination = out_dir.joinpath(*PurePosixPath(info.filename).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=1 << 20)
                if destination.stat().st_size != info.file_size:
                    raise Refusal("extracted artifact member size mismatch")
    except zipfile.BadZipFile as exc:
        raise Refusal("downloaded source artifact is not a valid ZIP") from exc
    return {"zip_sha256": zip_hash, "zip_bytes": archive_path.stat().st_size,
            "members": sorted(EXPECTED_ARTIFACT_FILES)}


def json_file(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refusal(f"missing or malformed {path.name}") from exc
    if not isinstance(value, dict):
        raise Refusal(f"{path.name} must contain a JSON object")
    return value


def regular_exact_tree(root: Path, expected: set[str]) -> dict[str, Path]:
    if not root.is_dir() or root.is_symlink():
        raise Refusal("downloaded artifact directory is absent or unsafe")
    found: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise Refusal("downloaded artifact contains a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise Refusal("downloaded artifact contains a non-regular entry")
        rel = path.relative_to(root).as_posix()
        if rel in found:
            raise Refusal("downloaded artifact has a duplicate path")
        found[rel] = path
    if set(found) != expected:
        raise Refusal(f"artifact file allowlist mismatch; found={sorted(found)}")
    return found


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise Refusal(f"invalid PNG header: {path.name}")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def validate_render_evidence(files: dict[str, Path]) -> dict:
    if files[LOG_PATH].stat().st_size > 2_000_000:
        raise Refusal("render log exceeds the bounded artifact size")
    proof = json_file(files[PROOF_PATH])
    if (proof.get("status") != "HOSTED_RENDER_AND_DECODE_PASS"
            or proof.get("scope") != "silent 12-second 1920x1080 30 fps diagnostic preview; not full film or release approval"
            or proof.get("repository") != REPO or proof.get("source_commit") != RUN_HEAD
            or proof.get("video_file") != Path(VIDEO_PATH).name
            or proof.get("video_bytes") != files[VIDEO_PATH].stat().st_size
            or proof.get("video_hash") != "not computed by request"
            or proof.get("width") != 1920 or proof.get("height") != 1080
            or proof.get("frame_rate") != "30/1" or proof.get("decoded_frame_count") != 360
            or proof.get("duration_seconds") != 12.0 or proof.get("audio_streams") != 0
            or proof.get("full_ffmpeg_decode") != "PASS"):
        raise Refusal("hosted proof manifest does not bind the exact 12-second silent F08 diagnostic")
    probe = json_file(files[PROBE_PATH])
    streams = probe.get("streams")
    video_streams = [s for s in streams or [] if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams or [] if s.get("codec_type") == "audio"]
    if len(video_streams) != 1 or audio_streams:
        raise Refusal("ffprobe must show exactly one video stream and no audio")
    stream = video_streams[0]
    if (stream.get("width") != 1920 or stream.get("height") != 1080
            or stream.get("r_frame_rate") != "30/1"
            or int(stream.get("nb_read_frames", "-1")) != 360):
        raise Refusal("ffprobe video dimensions, rate, or decoded frame count mismatch")
    try:
        duration = float(probe.get("format", {}).get("duration", "0"))
    except (TypeError, ValueError) as exc:
        raise Refusal("ffprobe duration is malformed") from exc
    if duration != 12.0:
        raise Refusal("ffprobe duration mismatch")
    video = files[VIDEO_PATH]
    if not 0 < video.stat().st_size <= MAX_VIDEO_BYTES:
        raise Refusal("video file size outside bounded preview limit")
    with video.open("rb") as stream_in:
        header = stream_in.read(16)
    if len(header) < 8 or header[4:8] != b"ftyp":
        raise Refusal("preview does not have an ISO BMFF MP4 header")
    if png_dimensions(files[CONTACT_PATH]) != (1920, 1620):
        raise Refusal("contact sheet dimensions mismatch")
    for frame_path in FRAME_PATHS:
        if png_dimensions(files[frame_path]) != (1920, 1080):
            raise Refusal(f"native frame dimensions mismatch: {frame_path}")
    versions = {
        "node": files[VERSION_PATHS[0]].read_text().strip(),
        "hyperframes": files[VERSION_PATHS[1]].read_text().strip(),
        "ffmpeg": files[VERSION_PATHS[2]].read_text().strip(),
        "python": files[VERSION_PATHS[3]].read_text().strip(),
    }
    if versions["node"] != "v22.23.3" or versions["hyperframes"] != "0.8.71":
        raise Refusal("render runtime version evidence mismatch")
    if not versions["ffmpeg"].startswith("ffmpeg version ") or not versions["python"].startswith("Python 3."):
        raise Refusal("runner version evidence malformed")
    return {"proof": proof, "probe": probe, "versions": versions}


def prepare_export(download_dir: Path, source: dict, out_dir: Path) -> dict:
    require_hosted_runner()
    validate_source_receipt(source)
    files = regular_exact_tree(download_dir, EXPECTED_ARTIFACT_FILES)
    evidence = validate_render_evidence(files)
    video_sha = sha256(files[VIDEO_PATH])
    published = {VIDEO_NAME: files[VIDEO_PATH], CONTACT_NAME: files[CONTACT_PATH]}
    published.update({name: files[path] for name, path in zip(FRAME_NAMES, FRAME_PATHS)})
    if out_dir.exists():
        raise Refusal("refusing to overwrite an existing prepared preview")
    out_dir.mkdir(parents=True)
    for name, path in published.items():
        shutil.copyfile(path, out_dir / name)
    technical = {
        "kind": "f08_wave06_hosted_picture_proof_v1",
        "scope": "silent 12-second opening diagnostic; not full film or release approval",
        "source_run_id": RUN_ID, "source_job_id": JOB_ID, "source_artifact_id": ARTIFACT_ID,
        "source_commit": RUN_HEAD, "render": {"width": 1920, "height": 1080,
        "fps": 30, "frames": 360, "duration_seconds": 12.0, "audio_streams": 0,
        "full_decode": "PASS_REPORTED_BY_PINNED_HOSTED_RUN"},
        "runtime": evidence["versions"],
        "editorial_review": "NOT_PERFORMED_BY_EXPORTER",
        "visual_review": "OPEN", "release_approval": "NOT_GRANTED", "ready": "NOT_GRANTED",
        "library_pointer_updated": False,
    }
    (out_dir / TECH_NAME).write_text(json.dumps(technical, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    media_records = []
    for name in [VIDEO_NAME, CONTACT_NAME, *FRAME_NAMES]:
        path = out_dir / name
        media_records.append({"name": name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    tech_path = out_dir / TECH_NAME
    tech_record = {"name": TECH_NAME, "bytes": tech_path.stat().st_size, "sha256": sha256(tech_path)}
    tag = f"preview-F08-W06-development-{RUN_ID}"
    direct = f"https://github.com/{REPO}/releases/download/{tag}"
    receipt = {
        "kind": "f08_wave06_durable_review_preview_export_v1",
        "source": {"repository": REPO, "repository_id": REPOSITORY_ID,
            "run_id": RUN_ID, "job_id": JOB_ID, "artifact_id": ARTIFACT_ID,
            "artifact_name": ARTIFACT_NAME, "artifact_size_bytes": ARTIFACT_BYTES,
            "artifact_zip_sha256": ARTIFACT_DIGEST.removeprefix("sha256:"),
            "artifact_expires_at": ARTIFACT_EXPIRES, "head_sha": RUN_HEAD},
        "preview_video": {"name": VIDEO_NAME, **media_records[0]},
        "contact_sheet": {"name": CONTACT_NAME, **media_records[1]},
        "native_review_frames": media_records[2:],
        "technical_evidence": tech_record,
        "source_artifact_digest_is_zip_digest_not_video_digest": True,
        "release_tag": tag, "release_url": f"https://github.com/{REPO}/releases/tag/{tag}",
        "preview_playback_url": f"{direct}/{VIDEO_NAME}",
        "contact_sheet_url": f"{direct}/{CONTACT_NAME}",
        "content_assets_expected": [
            {"name": name, "bytes": out_dir.joinpath(name).stat().st_size,
             "sha256": sha256(out_dir / name), "browser_download_url": f"{direct}/{name}"}
            for name in [VIDEO_NAME, CONTACT_NAME, *FRAME_NAMES, TECH_NAME]
        ],
        "visual_review": "OPEN", "release_approval": "NOT_GRANTED", "ready": "NOT_GRANTED",
        "library_pointer_updated": False,
    }
    receipt_path = out_dir / RECEIPT_NAME
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    content_paths = [out_dir / name for name in [VIDEO_NAME, CONTACT_NAME, *FRAME_NAMES, TECH_NAME, RECEIPT_NAME]]
    (out_dir / SUMS_NAME).write_text("".join(f"{sha256(path)}  {path.name}\n" for path in content_paths), encoding="utf-8")
    return receipt


def run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], text=True, capture_output=True, check=False)


def safe_cli_detail(result: subprocess.CompletedProcess) -> str:
    detail = (result.stderr or result.stdout or "no CLI detail").strip()
    detail = re.sub(r"(?i)(authorization:\s*bearer\s+)\S+", r"\1[redacted]", detail)
    detail = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b", "[redacted]", detail)
    return detail[:800]


def validate_release_assets(expected: dict[str, dict], assets: list[dict], tag: str) -> dict[str, dict]:
    found = {}
    for asset in assets:
        name = asset.get("name")
        if name in found or name not in expected:
            raise Refusal("release contains duplicate or unexpected assets; no overwrite")
        found[name] = asset
        want = expected[name]
        if asset.get("size") != want["size"] or asset.get("digest") != "sha256:" + want["sha256"]:
            raise Refusal(f"existing release asset differs; no overwrite: {name}")
        if asset.get("browser_download_url") != f"https://github.com/{REPO}/releases/download/{tag}/{name}":
            raise Refusal(f"release asset URL mismatch: {name}")
    return found


def confirmed_not_found(result: subprocess.CompletedProcess) -> bool:
    try:
        body = json.loads(result.stdout)
    except (ValueError, TypeError):
        body = {}
    return (result.returncode == 1 and result.stderr.strip() == "gh: Not Found (HTTP 404)"
            and body.get("status") == "404" and body.get("message") == "Not Found")


def release_notes(tag: str) -> str:
    base = f"https://github.com/{REPO}/releases/download/{tag}"
    links = "\n".join(f"- [{time}s frame]({base}/{name})" for time, name in zip(FRAME_TIMES, FRAME_NAMES))
    return (
        "# F08 Wave06 silent opening diagnostic — review pending\n\n"
        f"[Play the 12-second hosted diagnostic]({base}/{VIDEO_NAME}) · "
        f"[Open the contact sheet]({base}/{CONTACT_NAME})\n\n"
        f"![F08 Wave06 contact sheet]({base}/{CONTACT_NAME})\n\n"
        "This is a silent opening-picture diagnostic at 1920×1080 and 30 fps. "
        "It is not the complete film and has not received visual, editorial, or release approval.\n\n"
        "## Native frame review points\n\n" + links + "\n\n"
        "Review the cover turn at 1.65–3.20s, pencil and mark at 3.50–4.90s, "
        "record reply at 5.10–6.50s, and the continuing ending motion at 7.60–11.50s. "
        "`F08-W06-PREVIEW-EXPORT.json` carries the source run and artifact binding; "
        "`F08-W06-TECHNICAL-EVIDENCE.json` reports only hosted technical facts."
    )


def publish_export(export_dir: Path) -> dict:
    require_hosted_runner()
    tag = f"preview-F08-W06-development-{RUN_ID}"
    receipt_path = export_dir / RECEIPT_NAME
    receipt = json_file(receipt_path)
    source = receipt.get("source") or {}
    if (receipt.get("kind") != "f08_wave06_durable_review_preview_export_v1"
            or source.get("repository") != REPO or source.get("repository_id") != REPOSITORY_ID
            or source.get("run_id") != RUN_ID or source.get("job_id") != JOB_ID
            or source.get("artifact_id") != ARTIFACT_ID or source.get("artifact_name") != ARTIFACT_NAME
            or source.get("artifact_size_bytes") != ARTIFACT_BYTES
            or source.get("artifact_zip_sha256") != ARTIFACT_DIGEST.removeprefix("sha256:")
            or source.get("head_sha") != RUN_HEAD
            or receipt.get("release_tag") != tag or receipt.get("visual_review") != "OPEN"
            or receipt.get("release_approval") != "NOT_GRANTED" or receipt.get("ready") != "NOT_GRANTED"
            or receipt.get("library_pointer_updated") is not False):
        raise Refusal("prepared receipt lost its exact source or review-only status")
    expected_names = {VIDEO_NAME, CONTACT_NAME, *FRAME_NAMES, TECH_NAME, RECEIPT_NAME, SUMS_NAME}
    entries = list(export_dir.iterdir())
    if any(not path.is_file() or path.is_symlink() for path in entries):
        raise Refusal("prepared preview directory contains a non-file or symlink")
    paths = {p.name: p for p in entries}
    if set(paths) != expected_names:
        raise Refusal("prepared preview asset inventory differs from exact allowlist")
    for record in [receipt["preview_video"], receipt["contact_sheet"], *receipt["native_review_frames"], receipt["technical_evidence"]]:
        path = paths.get(record.get("name"))
        if path is None or path.stat().st_size != record.get("bytes") or sha256(path) != record.get("sha256"):
            raise Refusal("prepared media or technical summary changed after verification")
    sum_rows = {}
    for line in paths[SUMS_NAME].read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if not match or match.group(2) in sum_rows:
            raise Refusal("prepared public checksum file malformed")
        sum_rows[match.group(2)] = match.group(1)
    want_rows = {name: sha256(paths[name]) for name in expected_names - {SUMS_NAME}}
    if sum_rows != want_rows:
        raise Refusal("public checksum file does not bind the exact release payload")
    expected = {name: {"size": path.stat().st_size, "sha256": sha256(path)} for name, path in paths.items()}
    looked = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"])
    if looked.returncode:
        if not confirmed_not_found(looked):
            raise Refusal("release lookup did not return confirmed native HTTP 404; no create attempted")
        # Keep release metadata outside the exact payload directory so a
        # successful run can be safely retried against the same prepared tree.
        notes_text = release_notes(tag) + "\n"
        created = run_gh(["api", "--method", "POST", f"repos/{REPO}/releases",
                          "-f", f"tag_name={tag}", "-f", f"target_commitish={RUN_HEAD}",
                          "-f", f"name=F08 Wave06 hosted opening diagnostic {RUN_ID}",
                          "-f", f"body={notes_text}",
                          "-F", "draft=false", "-F", "prerelease=true"])
        if created.returncode:
            raise Refusal(f"metadata-only F08 preview release creation failed: {safe_cli_detail(created)}")
        created_release = json.loads(created.stdout)
        if (created_release.get("tag_name") != tag or created_release.get("draft") is not False
                or created_release.get("prerelease") is not True):
            raise Refusal("metadata-only release creation returned an unexpected tag or review state")
        looked = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"])
        if looked.returncode:
            raise Refusal("created F08 preview release could not be verified")
    release = json.loads(looked.stdout)
    if (release.get("tag_name") != tag or release.get("draft") is not False
            or release.get("prerelease") is not True):
        raise Refusal("release tag mismatch or target is not a published prerelease")
    commit = run_gh(["api", f"repos/{REPO}/commits/{tag}"])
    if commit.returncode or json.loads(commit.stdout).get("sha") != RUN_HEAD:
        raise Refusal("versioned F08 preview tag does not resolve to the pinned source commit")
    present = validate_release_assets(expected, release.get("assets", []), tag)
    for name, path in paths.items():
        if name not in present:
            upload = run_gh(["release", "upload", tag, str(path), "-R", REPO])
            if upload.returncode:
                raise Refusal(f"release upload failed for {name}: {safe_cli_detail(upload)}")
        current = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"])
        if current.returncode:
            raise Refusal("preview release could not be read back after upload")
        observed_release = json.loads(current.stdout)
        present = validate_release_assets(expected, observed_release.get("assets", []), tag)
    if set(present) != expected_names:
        raise Refusal("published preview release asset inventory incomplete")
    observed = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"])
    if observed.returncode:
        raise Refusal("published F08 preview release cannot be read back")
    final = json.loads(observed.stdout)
    final_assets = validate_release_assets(expected, final.get("assets", []), tag)
    if set(final_assets) != expected_names:
        raise Refusal("published F08 release changed during final readback")
    return {"tag": tag, "release_url": f"https://github.com/{REPO}/releases/tag/{tag}",
            "playback_url": receipt["preview_playback_url"], "assets_verified": len(present),
            "visual_review": "OPEN", "release_approval": "NOT_GRANTED", "library_pointer_updated": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-source")
    for arg in ("repository", "run", "jobs", "artifacts", "out"):
        validate.add_argument(f"--{arg}", type=Path, required=True)
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
            source = validate_source(json_file(args.repository), json_file(args.run),
                                     json_file(args.jobs), json_file(args.artifacts))
            args.out.write_text(json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print("exact F08 Wave06 run/job/artifact metadata PASS; artifact bytes not fetched")
        elif args.command == "check-capacity":
            print(f"hosted free space PASS: {require_capacity(minimum_bytes=args.minimum_bytes)} bytes")
        elif args.command == "extract-artifact":
            result = extract_artifact_zip(args.archive, json_file(args.source), args.out_dir)
            print(f"exact native artifact ZIP digest/size/28-member contract PASS: {result['zip_sha256']}")
        elif args.command == "prepare":
            receipt = prepare_export(args.download_dir, json_file(args.source), args.out_dir)
            print(f"prepared exact 12s silent F08 review preview; media stays on hosted runner; visual approval OPEN")
        else:
            print(json.dumps(publish_export(args.export_dir), sort_keys=True))
        return 0
    except (Refusal, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
