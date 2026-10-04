#!/usr/bin/env python3
"""Pinned hosted-only export of the S90 AV development artifact for review.

The source artifact is fetched and inspected on GitHub-hosted Linux only. This
tool does not approve or update any canonical card or library pointer.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import zipfile

REPO = "agmmltd-arch/agmm-render-public"
REPOSITORY_ID = 1397641626
RUN_ID = 37209820801
RUN_HEAD = "c08601fccd68e7bd24d8b55bfb3fe95aadfbc4f4"
RUN_WORKFLOW = ".github/workflows/s90-av-development-candidate.yml"
RUN_TITLE = f"S90 AV development review at {RUN_HEAD}"
JOB_NAME = "render-review-candidate"
ARTIFACT_ID = 11306780655
ARTIFACT_NAME = "S90-HOSTED-AV-DEVELOPMENT-37209820801"
ARTIFACT_BYTES = 7236937
ARTIFACT_DIGEST = "sha256:24183c44a6debc1ef6bb866f580cef45e33fe1bee99eaf61451b02d0d1a5632f"
ARTIFACT_CREATED = "2026-10-04T14:42:07Z"
ARTIFACT_EXPIRES = "2026-10-05T14:42:07Z"
VIDEO_NAME = "FINAL.mp4"
SOURCE_TECH_NAME = "TECHNICAL-EVIDENCE.json"
SOURCE_SUMS_NAME = "SHA256SUMS.txt"
PUBLIC_TECH_NAME = "TECHNICAL-EVIDENCE.json"
PUBLIC_RECEIPT_NAME = "S90-PREVIEW-EXPORT.json"
PUBLIC_SUMS_NAME = "SHA256SUMS.txt"
MAX_VIDEO_BYTES = 200_000_000
MIN_FREE_BYTES = 1_000_000_000
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_SOURCE_SUM_NAMES = {VIDEO_NAME, SOURCE_TECH_NAME, "review/CONTACT-SHEET.jpg"}
EXPECTED_ARTIFACT_FILES = {VIDEO_NAME, SOURCE_TECH_NAME, SOURCE_SUMS_NAME}
MAX_UNZIPPED_BYTES = 210_000_000


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
    """Validate the exact successful public render run and its one artifact."""
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
        raise Refusal("source is not the exact completed S90 development render")
    run_start, run_end = parse_time(run.get("created_at")), parse_time(run.get("updated_at"))
    jobs = jobs_doc.get("jobs")
    if jobs_doc.get("total_count") != 1 or not isinstance(jobs, list) or len(jobs) != 1:
        raise Refusal("source job inventory changed")
    job = jobs[0]
    if (job.get("name") != JOB_NAME or job.get("run_id") != RUN_ID
            or job.get("head_sha") != RUN_HEAD or job.get("status") != "completed"
            or job.get("conclusion") != "success"):
        raise Refusal("S90 development render job is not an exact completed success")
    artifacts = artifacts_doc.get("artifacts")
    if artifacts_doc.get("total_count") != 1 or not isinstance(artifacts, list) or len(artifacts) != 1:
        raise Refusal("source artifact inventory changed")
    artifact = artifacts[0]
    wr = artifact.get("workflow_run") or {}
    if (artifact.get("id") != ARTIFACT_ID or artifact.get("name") != ARTIFACT_NAME
            or artifact.get("size_in_bytes") != ARTIFACT_BYTES or artifact.get("digest") != ARTIFACT_DIGEST
            or artifact.get("expired") is not False or wr.get("id") != RUN_ID
            or wr.get("head_sha") != RUN_HEAD or wr.get("repository_id") != REPOSITORY_ID):
        raise Refusal("source artifact ID/name/size/digest/run binding mismatch")
    created = parse_time(artifact.get("created_at"))
    expires = parse_time(artifact.get("expires_at"))
    if created != parse_time(ARTIFACT_CREATED) or expires != parse_time(ARTIFACT_EXPIRES):
        raise Refusal("source artifact creation/expiry metadata changed")
    if created < run_start or created > run_end or expires <= observed_at:
        raise Refusal("source artifact is outside its run window or expired")
    return {
        "run_id": RUN_ID, "repository": REPO, "repository_id": REPOSITORY_ID,
        "workflow": RUN_WORKFLOW, "head_sha": RUN_HEAD, "job_name": JOB_NAME,
        "conclusion": "success", "run_attempt": 1,
        "artifact": {"id": ARTIFACT_ID, "name": ARTIFACT_NAME,
                     "size_in_bytes": ARTIFACT_BYTES, "digest": ARTIFACT_DIGEST,
                     "created_at": ARTIFACT_CREATED, "expires_at": ARTIFACT_EXPIRES},
    }


def validate_source_receipt(source: dict, observed_at: datetime | None = None) -> None:
    if (source.get("run_id") != RUN_ID or source.get("repository") != REPO
            or source.get("repository_id") != REPOSITORY_ID
            or source.get("workflow") != RUN_WORKFLOW or source.get("head_sha") != RUN_HEAD
            or source.get("conclusion") != "success" or source.get("run_attempt") != 1
            or source.get("job_name") != JOB_NAME):
        raise Refusal("validated source receipt identity mismatch")
    art = source.get("artifact")
    if not isinstance(art, dict) or (art.get("id") != ARTIFACT_ID or art.get("name") != ARTIFACT_NAME
            or art.get("size_in_bytes") != ARTIFACT_BYTES or art.get("digest") != ARTIFACT_DIGEST
            or art.get("created_at") != ARTIFACT_CREATED or art.get("expires_at") != ARTIFACT_EXPIRES):
        raise Refusal("validated source receipt artifact binding mismatch")
    if parse_time(ARTIFACT_EXPIRES) <= (observed_at or datetime.now(timezone.utc)):
        raise Refusal("source artifact has expired")


def require_hosted_runner() -> None:
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise Refusal("artifact download, video hashing and release require GitHub-hosted Linux")


def require_capacity(path: Path = Path("."), minimum_bytes: int = MIN_FREE_BYTES) -> int:
    require_hosted_runner()
    if type(minimum_bytes) is not int or minimum_bytes <= 0:
        raise Refusal("free-space threshold must be a positive integer")
    free = shutil.disk_usage(path).free
    if free < minimum_bytes:
        raise Refusal(f"runner has {free} free bytes; requires {minimum_bytes}")
    return free


def extract_artifact_zip(archive_path: Path, source: dict, out_dir: Path) -> dict:
    """Verify native ZIP digest/size, then safely extract its exact 3-file contract."""
    require_hosted_runner()
    validate_source_receipt(source)
    if out_dir.exists():
        raise Refusal("refusing to overwrite an existing extracted source artifact")
    art = source["artifact"]
    if archive_path.is_symlink() or not archive_path.is_file() or archive_path.stat().st_size != art["size_in_bytes"]:
        raise Refusal("downloaded source ZIP is absent or differs from native artifact size")
    zip_sha = sha256(archive_path)
    if "sha256:" + zip_sha != art["digest"]:
        raise Refusal("downloaded source ZIP digest differs from native artifact digest")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != EXPECTED_ARTIFACT_FILES:
                raise Refusal("source ZIP members differ from the exact three-file artifact allowlist")
            expanded = 0
            for info in infos:
                mode = info.external_attr >> 16
                if (info.is_dir() or (mode and not (mode & 0o100000))
                        or info.flag_bits & 0x1 or info.file_size < 0):
                    raise Refusal("source ZIP contains a directory, link, encrypted, or non-regular member")
                path = Path(info.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                    raise Refusal("source ZIP contains an unsafe path")
                expanded += info.file_size
                if expanded > MAX_UNZIPPED_BYTES:
                    raise Refusal("source ZIP exceeds the expansion limit")
            out_dir.mkdir(parents=True)
            for info in infos:
                destination = out_dir / info.filename
                with archive.open(info) as src, destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=1 << 20)
                if destination.stat().st_size != info.file_size:
                    raise Refusal("extracted source artifact member size mismatch")
    except zipfile.BadZipFile as exc:
        raise Refusal("downloaded source artifact is not a valid ZIP") from exc
    return {"zip_sha256": zip_sha, "zip_bytes": archive_path.stat().st_size,
            "members": sorted(EXPECTED_ARTIFACT_FILES)}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refusal(f"missing or malformed {path.name}") from exc
    if not isinstance(value, dict):
        raise Refusal(f"{path.name} must contain a JSON object")
    return value


def parse_sum_file(path: Path, expected_names: set[str] = EXPECTED_SOURCE_SUM_NAMES) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._/-]+)", line)
        if not match:
            raise Refusal("source SHA256SUMS contains a malformed row")
        digest, name = match.groups()
        if name.startswith("/") or ".." in Path(name).parts or name in rows:
            raise Refusal("source SHA256SUMS contains an unsafe or duplicate path")
        rows[name] = digest
    if set(rows) != expected_names:
        raise Refusal("checksum manifest does not match its exact file contract")
    return rows


def _regular_exact_tree(root: Path) -> dict[str, Path]:
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
    if set(found) != EXPECTED_ARTIFACT_FILES:
        raise Refusal(f"artifact file allowlist mismatch: {sorted(found)}")
    return found


def validate_technical_evidence(evidence: dict, *, video_sha: str, video_bytes: int) -> dict:
    if (evidence.get("kind") != "agmm_short_remote_technical_evidence"
            or evidence.get("technical_status") != "PASS"
            or evidence.get("editorial_status") != "NOT_REVIEWED"
            or evidence.get("publication_status") != "NOT_REQUESTED"
            or type(evidence.get("duration")) not in (float, int)
            or evidence.get("duration") != 58.3
            or type(evidence.get("declared_frames")) is not int
            or evidence.get("declared_frames") != 1749):
        raise Refusal("technical evidence has wrong S90 development scope/status/grid")
    masters = evidence.get("masters")
    if not isinstance(masters, list) or len(masters) != 1:
        raise Refusal("technical evidence must contain exactly one 1080 master")
    master = masters[0]
    if (master.get("file") != VIDEO_NAME or master.get("sha256") != video_sha
            or master.get("bytes") != video_bytes or master.get("resolution") != "1080"
            or master.get("full_decode") != "PASS" or type(master.get("frames")) is not int
            or abs(master.get("frames") - 1749) > 1 or master.get("declared_frame_cap") != 1749):
        raise Refusal("technical evidence does not bind the exact final video bytes")
    parts = evidence.get("parts")
    if not isinstance(parts, dict) or set(parts) != {"1080"} or not isinstance(parts["1080"], list) or len(parts["1080"]) != 1:
        raise Refusal("technical evidence does not describe the one-part 1080 render")
    part = parts["1080"][0]
    if (part.get("sha256") is None or not isinstance(part.get("sha256"), str)
            or not SHA_RE.fullmatch(part["sha256"]) or type(part.get("bytes")) is not int
            or part["bytes"] <= 0 or type(part.get("frames")) is not int
            or abs(part.get("frames") - 1749) > 1):
        raise Refusal("technical evidence part digest/size/frame metadata is malformed")
    probe = master.get("probe")
    if not isinstance(probe, dict):
        raise Refusal("technical evidence master probe is missing")
    streams = probe.get("streams")
    if not isinstance(streams, list):
        raise Refusal("technical evidence stream list is missing")
    videos = [x for x in streams if x.get("codec_type") == "video"]
    audios = [x for x in streams if x.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise Refusal("S90 review video must retain exactly one video and one mixed audio stream")
    v = videos[0]
    if (v.get("width") != 1920 or v.get("height") != 1080
            or v.get("r_frame_rate") != "30/1"):
        raise Refusal("S90 technical evidence dimensions or frame rate mismatch")
    return {
        "kind": "s90_development_preview_technical_summary_v1",
        "source_technical_status": "PASS",
        "video_sha256": video_sha,
        "video_bytes": video_bytes,
        "resolution": "1920x1080",
        "frame_rate": "30/1",
        "declared_frames": 1749,
        "declared_duration_seconds": 58.3,
        "source_full_decode": "PASS_REPORTED_BY_PINNED_RUN",
        "audio_streams": 1,
        "editorial_status": "NOT_REVIEWED",
        "audio_listening": "NOT_PERFORMED_BY_EXPORTER",
        "full_av_review": "OPEN",
        "release_approval": "NOT_GRANTED",
        "ready": "NOT_GRANTED",
    }


def prepare_export(download_dir: Path, source: dict, out_dir: Path) -> dict:
    """Validate downloaded archive contents and create a sanitized release payload."""
    require_hosted_runner()
    validate_source_receipt(source)
    files = _regular_exact_tree(download_dir)
    sums = parse_sum_file(files[SOURCE_SUMS_NAME])
    # The producer hashes its contact sheet too, but the source Actions artifact
    # intentionally uploads only these three paths. Verify the two transferred
    # members and explicitly regenerate the public checksum file for this payload.
    video = files[VIDEO_NAME]
    tech_path = files[SOURCE_TECH_NAME]
    if type(video.stat().st_size) is not int or not 0 < video.stat().st_size <= MAX_VIDEO_BYTES:
        raise Refusal("S90 final video size is outside the bounded exporter limit")
    with video.open("rb") as stream:
        header = stream.read(16)
    if len(header) < 8 or header[4:8] != b"ftyp":
        raise Refusal("FINAL.mp4 does not have an ISO BMFF MP4 header")
    video_hash = sha256(video)
    if sha256(tech_path) != sums[SOURCE_TECH_NAME] or video_hash != sums[VIDEO_NAME]:
        raise Refusal("downloaded source artifact member does not match its producer checksum")
    evidence = _json(tech_path)
    safe_tech = validate_technical_evidence(evidence, video_sha=video_hash, video_bytes=video.stat().st_size)
    if out_dir.exists():
        raise Refusal("refusing to overwrite an existing prepared export directory")
    out_dir.mkdir(parents=True)
    shutil.copyfile(video, out_dir / VIDEO_NAME)
    (out_dir / PUBLIC_TECH_NAME).write_text(json.dumps(safe_tech, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tech_hash = sha256(out_dir / PUBLIC_TECH_NAME)
    (out_dir / PUBLIC_SUMS_NAME).write_text(
        f"{video_hash}  {VIDEO_NAME}\n{tech_hash}  {PUBLIC_TECH_NAME}\n", encoding="utf-8")
    receipt = {
        "kind": "s90_hosted_development_preview_export_v1",
        "source": source,
        "exported_video": {"name": VIDEO_NAME, "size_bytes": video.stat().st_size,
                           "sha256": video_hash},
        "public_text_assets": [
            {"name": PUBLIC_TECH_NAME, "size_bytes": (out_dir / PUBLIC_TECH_NAME).stat().st_size,
             "sha256": tech_hash},
            {"name": PUBLIC_SUMS_NAME, "size_bytes": (out_dir / PUBLIC_SUMS_NAME).stat().st_size,
             "sha256": sha256(out_dir / PUBLIC_SUMS_NAME)},
        ],
        "source_archive_digest_is_zip_digest_not_video_digest": True,
        "source_checksum_note": "Producer SHA256SUMS also lists an omitted review contact sheet; its transferred video and technical-text rows were verified, and the public sums were regenerated for the exact four-asset export.",
        "editorial_status": "NOT_REVIEWED", "audio_listening": "OPEN",
        "full_av_review": "OPEN", "release_approval": "NOT_GRANTED", "ready": "NOT_GRANTED",
        "library_pointer_updated": False,
        "release_tag": f"preview-S90-development-{RUN_ID}",
        "release_url": f"https://github.com/{REPO}/releases/tag/preview-S90-development-{RUN_ID}",
    }
    (out_dir / PUBLIC_RECEIPT_NAME).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], text=True, capture_output=True, check=False)


def validate_release_assets(expected: dict[str, dict], assets: list[dict], tag: str | None = None,
                            allow_unchecked: set[str] | None = None) -> dict[str, dict]:
    found: dict[str, dict] = {}
    allow_unchecked = allow_unchecked or set()
    for asset in assets:
        name = asset.get("name")
        if name in found or (name not in expected and name not in allow_unchecked):
            raise Refusal("release contains duplicate or unexpected assets; no overwrite")
        found[name] = asset
        if name in allow_unchecked and name not in expected:
            continue
        want = expected[name]
        if asset.get("size") != want["size"] or asset.get("digest") != "sha256:" + want["sha256"]:
            raise Refusal(f"existing release asset differs; no overwrite: {name}")
        if tag and asset.get("browser_download_url") != f"https://github.com/{REPO}/releases/download/{tag}/{name}":
            raise Refusal(f"release asset URL mismatch: {name}")
    return found


def confirmed_not_found(result: subprocess.CompletedProcess) -> bool:
    """Only the exact native gh HTTP 404 response authorizes release creation."""
    try:
        body = json.loads(result.stdout)
    except (ValueError, TypeError):
        body = {}
    return (result.returncode == 1 and result.stderr.strip() == "gh: Not Found (HTTP 404)"
            and body.get("status") == "404" and body.get("message") == "Not Found")


def publish_export(export_dir: Path) -> dict:
    require_hosted_runner()
    receipt_path = export_dir / PUBLIC_RECEIPT_NAME
    receipt = _json(receipt_path)
    validate_source_receipt(receipt.get("source") or {})
    if (receipt.get("kind") != "s90_hosted_development_preview_export_v1"
            or receipt.get("release_approval") != "NOT_GRANTED"
            or receipt.get("full_av_review") != "OPEN" or receipt.get("ready") != "NOT_GRANTED"
            or receipt.get("library_pointer_updated") is not False):
        raise Refusal("prepared S90 preview lost review-only/nonapproval status")
    tag = f"preview-S90-development-{RUN_ID}"
    if (receipt.get("release_tag") != tag
            or receipt.get("release_url") != f"https://github.com/{REPO}/releases/tag/{tag}"):
        raise Refusal("prepared receipt release identity is not pinned")
    paths = {VIDEO_NAME: export_dir / VIDEO_NAME,
             PUBLIC_TECH_NAME: export_dir / PUBLIC_TECH_NAME,
             PUBLIC_SUMS_NAME: export_dir / PUBLIC_SUMS_NAME,
             PUBLIC_RECEIPT_NAME: receipt_path}
    if any(not path.is_file() or path.is_symlink() for path in paths.values()):
        raise Refusal("prepared public export is missing a regular file")
    video_sha = sha256(paths[VIDEO_NAME])
    if (paths[VIDEO_NAME].stat().st_size != receipt.get("exported_video", {}).get("size_bytes")
            or video_sha != receipt.get("exported_video", {}).get("sha256")):
        raise Refusal("prepared video bytes no longer match the source-bound export receipt")
    tech_rows = receipt.get("public_text_assets")
    if not isinstance(tech_rows, list) or {r.get("name") for r in tech_rows if isinstance(r, dict)} != {PUBLIC_TECH_NAME, PUBLIC_SUMS_NAME}:
        raise Refusal("prepared public text asset receipt is incomplete")
    tech_by_name = {r["name"]: r for r in tech_rows}
    for name in (PUBLIC_TECH_NAME, PUBLIC_SUMS_NAME):
        if (paths[name].stat().st_size != tech_by_name[name].get("size_bytes")
                or sha256(paths[name]) != tech_by_name[name].get("sha256")):
            raise Refusal(f"prepared public text changed after verification: {name}")
    expected_sums = {VIDEO_NAME: video_sha, PUBLIC_TECH_NAME: sha256(paths[PUBLIC_TECH_NAME])}
    public_sums = parse_sum_file(paths[PUBLIC_SUMS_NAME], {VIDEO_NAME, PUBLIC_TECH_NAME})
    if public_sums != expected_sums:
        raise Refusal("public export checksum file does not bind exactly the released video and safe technical summary")
    actual_names = {p.name for p in export_dir.iterdir() if p.is_file() and not p.is_symlink()}
    if actual_names != set(paths):
        raise Refusal("prepared export directory has unexpected or missing release files")
    base_names = {VIDEO_NAME, PUBLIC_TECH_NAME, PUBLIC_SUMS_NAME}
    expected_base = {name: {"name": name, "path": str(paths[name]), "size": paths[name].stat().st_size,
                            "sha256": sha256(paths[name])} for name in base_names}
    looked = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"])
    if looked.returncode:
        if not confirmed_not_found(looked):
            raise Refusal("release lookup did not return confirmed native HTTP 404; no create attempted")
        created = run_gh(["release", "create", tag, "-R", REPO, "--target", RUN_HEAD,
                          "--title", f"S90 development preview {RUN_ID}",
                          "--notes", "Bounded hosted development preview only. Full audiovisual review OPEN; release approval NOT_GRANTED; Ready NOT_GRANTED.",
                          "--prerelease"])
        if created.returncode:
            raise Refusal("unique preview release creation failed")
        looked = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"])
        if looked.returncode:
            raise Refusal("created release could not be verified")
    release = json.loads(looked.stdout)
    if (release.get("tag_name") != tag or release.get("draft") is not False
            or release.get("prerelease") is not True):
        raise Refusal("release tag mismatch or target is not a published preview prerelease")
    commit = run_gh(["api", f"repos/{REPO}/commits/{tag}"])
    if commit.returncode or json.loads(commit.stdout).get("sha") != RUN_HEAD:
        raise Refusal("versioned S90 preview release does not resolve to the pinned source head")
    present = validate_release_assets(expected_base, release.get("assets", []), allow_unchecked={PUBLIC_RECEIPT_NAME})
    for name, spec in expected_base.items():
        if name not in present:
            uploaded = run_gh(["release", "upload", tag, spec["path"], "-R", REPO])
            if uploaded.returncode:
                raise Refusal(f"release upload failed: {name}")
    videos_query = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"])
    if videos_query.returncode:
        raise Refusal("uploaded preview assets could not be read back")
    videos_release = json.loads(videos_query.stdout)
    observed_video_assets = validate_release_assets(expected_base, videos_release.get("assets", []), tag,
                                                     allow_unchecked={PUBLIC_RECEIPT_NAME})
    if not base_names <= set(observed_video_assets):
        raise Refusal("one or more verified S90 video/text assets are missing")
    receipt["release_assets_verified"] = [
        {"name": name, "size": observed_video_assets[name]["size"], "digest": observed_video_assets[name]["digest"],
         "browser_download_url": observed_video_assets[name]["browser_download_url"]}
        for name in sorted(base_names)
    ]
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    expected = {**expected_base, PUBLIC_RECEIPT_NAME: {
        "name": PUBLIC_RECEIPT_NAME, "path": str(receipt_path),
        "size": receipt_path.stat().st_size, "sha256": sha256(receipt_path)}}
    present_final = validate_release_assets(expected, videos_release.get("assets", []), tag)
    if PUBLIC_RECEIPT_NAME not in present_final:
        uploaded = run_gh(["release", "upload", tag, str(receipt_path), "-R", REPO])
        if uploaded.returncode:
            raise Refusal("public S90 text receipt upload failed")
    final_query = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"])
    if final_query.returncode:
        raise Refusal("published S90 preview release cannot be read back")
    final_release = json.loads(final_query.stdout)
    observed = validate_release_assets(expected, final_release.get("assets", []), tag)
    if set(observed) != set(expected):
        raise Refusal("published S90 asset inventory is incomplete")
    return {"tag": tag, "assets_verified": [
                {"name": name, "size": observed[name]["size"], "digest": observed[name]["digest"],
                 "browser_download_url": observed[name]["browser_download_url"]}
                for name in sorted(observed)], "approval": "NOT_GRANTED",
            "full_av": "OPEN", "library_pointer_updated": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate-source")
    check.add_argument("--repository", type=Path, required=True)
    check.add_argument("--run", type=Path, required=True)
    check.add_argument("--jobs", type=Path, required=True)
    check.add_argument("--artifacts", type=Path, required=True)
    check.add_argument("--out", type=Path, required=True)
    cap = sub.add_parser("check-capacity")
    cap.add_argument("--minimum-bytes", type=int, default=MIN_FREE_BYTES)
    prep = sub.add_parser("prepare")
    prep.add_argument("--download-dir", type=Path, required=True)
    prep.add_argument("--source", type=Path, required=True)
    prep.add_argument("--out-dir", type=Path, required=True)
    pub = sub.add_parser("publish")
    pub.add_argument("--export-dir", type=Path, required=True)
    extract = sub.add_parser("extract-artifact")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--source", type=Path, required=True)
    extract.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-source":
            source = validate_source(_json(args.repository), _json(args.run), _json(args.jobs), _json(args.artifacts))
            args.out.write_text(json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print("exact S90 run/job/artifact metadata PASS; no artifact bytes fetched")
        elif args.command == "check-capacity":
            print(f"hosted runner free space PASS: {require_capacity(minimum_bytes=args.minimum_bytes)} bytes")
        elif args.command == "prepare":
            receipt = prepare_export(args.download_dir, _json(args.source), args.out_dir)
            print(f"prepared exact pinned S90 review payload; video sha256={receipt['exported_video']['sha256']}; approval NOT_GRANTED")
        elif args.command == "extract-artifact":
            result = extract_artifact_zip(args.archive, _json(args.source), args.out_dir)
            print(f"native source ZIP digest/size/member allowlist PASS: {result['zip_sha256']}")
        else:
            print(json.dumps(publish_export(args.export_dir), sort_keys=True))
        return 0
    except (Refusal, OSError, json.JSONDecodeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
