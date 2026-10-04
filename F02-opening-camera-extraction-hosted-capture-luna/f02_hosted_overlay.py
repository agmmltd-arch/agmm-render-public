#!/usr/bin/env python3
"""Hosted-only, hash-bound F02 source overlay and source-frame receipt helper."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import tarfile
import urllib.error
import urllib.request

REPO = "agmmltd-arch/agmm-render-public"
PARENT_RELEASE = "F02-profit-qualifier-20261003"
PARENT_RELEASE_ID = 402632642
PARENT_ASSET_ID = 608285956
PARENT_BYTES = 37_951_315
PARENT_SHA256 = "b216a14d62b2b5430234a411a1913207b41642071fc5985a11bbf09913d21719"
OVERLAY_HASHES = {
    "film/film.js": "0507c2c652c9723e1478268db6a60b1244824782a694ba938c77cea9a1a43f63",
    "film/sets_a.js": "a95e9df7557ab62b9708556cbddc8a586118ad03441b9a69b9104e7f4ff5fbd5",
}
CANDIDATE_BUILDER_OWNER_HASHES = {
    "film/film.js": "e2358c4c6e1072bb6a81d362cc6a341b3d884765f011f20b291ebcc4bade997b",
    "film/sets_a.js": "cf8747c798844d01d458c7b4b6dd495beb208985cdc7d21f3a307b217f7aa19e",
}
CANDIDATE_CLASS = "isolated_source_candidate"
OWNER_ADOPTION = "NOT_ADOPTED"
REJECTED_DIAGNOSTIC_ONLY = {
    "release_id": 402725212,
    "asset_id": 608687529,
    "tag_name": "F02-source-overlay-db1e5e398ea2fcc14136554dbe54dea27f259178fdf30813bf144f32d1b3ad68",
    "sha256": "db1e5e398ea2fcc14136554dbe54dea27f259178fdf30813bf144f32d1b3ad68",
    "status": "REJECTED_BY_ROOT_SOURCE_CAPTURE_REVIEW",
    "role": "diagnostic_only_not_candidate_input",
}
OVERLAY_NAMES = set(OVERLAY_HASHES)
ALLOWED_CONTENT_CHANGES = OVERLAY_NAMES | {"SHA256SUMS.txt"}
MAX_ARCHIVE_MEMBERS = 30_000
MAX_MEMBER_BYTES = 250_000_000
MAX_TOTAL_BYTES = 2_000_000_000
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"
CAPTURES = [{'name': 'opening_source_headline_frame0', 'time': 0.0}, {'name': 'opening_date_word', 'time': 0.2}, {'name': 's01_pre_cut', 'time': 2.3666666667}, {'name': 's02_cut', 'time': 2.4}, {'name': 's02_post_cut', 'time': 2.4333333333}, {'name': 'paper_feed_prestart', 'time': 2.4666666667}, {'name': 'paper_feed_start', 'time': 2.5}, {'name': 'paper_feed_early', 'time': 2.5666666667}, {'name': 'paper_feed_mid', 'time': 4.9666666667}, {'name': 'paper_feed_mid_seam', 'time': 5.0}, {'name': 'paper_feed_late', 'time': 5.0666666667}, {'name': 'paper_feed_complete', 'time': 5.1}, {'name': 's03_pre_cut', 'time': 5.2666666667}, {'name': 's03_cut', 'time': 5.3}, {'name': 's03_post_cut', 'time': 5.3333333333}, {'name': 's04_pre_cut', 'time': 7.7666666667}, {'name': 's04_cut', 'time': 7.8}, {'name': 's04_post_cut', 'time': 7.8333333333}, {'name': 'assistant_ai_onset', 'time': 8.0666666667}, {'name': 'assistant_ai_next_frame', 'time': 8.1}, {'name': 'assistant_phrase_mid', 'time': 8.4}, {'name': 'assistant_phrase_end_pre', 'time': 9.4}, {'name': 'assistant_phrase_end_post', 'time': 9.4333333333}, {'name': 's05_pre_cut', 'time': 10.2666666667}, {'name': 's05_cut', 'time': 10.3}, {'name': 's05_post_cut', 'time': 10.3333333333}, {'name': 'doing_onset_pre', 'time': 10.9666666667}, {'name': 'doing_onset', 'time': 11.0}, {'name': 'work_word_pre', 'time': 11.6333333333}, {'name': 'work_word_onset', 'time': 11.6666666667}, {'name': 'work_word_post', 'time': 11.7}, {'name': 'of_word_pre', 'time': 12.1}, {'name': 'camera_hold_early', 'time': 12.1333333333}, {'name': 'camera_hold_mid', 'time': 12.1666666667}, {'name': 'camera_hold_late', 'time': 12.3}, {'name': 'source_hold_pre_stress', 'time': 12.3333333333}, {'name': 'source_hold_post_frame', 'time': 12.3666666667}, {'name': 'lift_pre_frame', 'time': 12.5333333333}, {'name': 'printed_700_first_stress', 'time': 12.5666666667}, {'name': 'printed_700_next_frame', 'time': 12.6}, {'name': 'printed_700_hold_early', 'time': 12.7}, {'name': 'printed_700_hold_mid', 'time': 12.8}, {'name': 'printed_700_hold_late', 'time': 12.9}, {'name': 'printed_700_last_frame_pre_cut', 'time': 13.0}, {'name': 'printed_700_hold_13_033', 'time': 13.0333333333}, {'name': 'printed_700_hold_13_067', 'time': 13.0666666667}, {'name': 'spoken_700_final_pre', 'time': 13.2333333333}, {'name': 'spoken_700_final_post', 'time': 13.2666666667}, {'name': 'floor_handoff_post', 'time': 13.3}, {'name': 'full_time_word_pre', 'time': 13.7666666667}, {'name': 'full_time_onset', 'time': 13.8}, {'name': 'full_time_post', 'time': 13.8333333333}, {'name': 'people_fade_pre', 'time': 15.1666666667}, {'name': 'people_fade_start', 'time': 15.2}, {'name': 'people_fade_post', 'time': 15.2333333333}, {'name': 'floor_second_shot_pre', 'time': 16.1333333333}, {'name': 'floor_second_shot_before', 'time': 16.1666666667}, {'name': 'floor_second_shot_cut', 'time': 16.2}, {'name': 'floor_second_shot_post', 'time': 16.2333333333}, {'name': 'klarna_name_pre', 'time': 18.1666666667}, {'name': 'klarna_wordmark_start', 'time': 18.2}, {'name': 'klarna_name_post', 'time': 18.2333333333}, {'name': 'klarna_name_end', 'time': 18.8}, {'name': 'segment51_40m_claim', 'time': 436.6666666667}, {'name': 'segment51_40m_clear', 'time': 437.0666666667}, {'name': 'profit_duplicate_pre', 'time': 439.4666666667}, {'name': 'profit_duplicate_exact_439_5', 'time': 439.5}, {'name': 'profit_duplicate_edge_a', 'time': 439.7666666667}, {'name': 'profit_duplicate_edge_b', 'time': 439.8}, {'name': 'segment51_52_transition', 'time': 440.6}, {'name': 'segment52_close', 'time': 443.5}, {'name': 'segment52_quality_line', 'time': 445.8}, {'name': 'forbes_headline_start', 'time': 447.0}, {'name': 'forbes_headline_to_next_shot', 'time': 451.4}]
SNAPSHOT_RE = re.compile(r"^frame-([0-9]+(?:\.[0-9]+)?)\.png$")
SNAPSHOT_AUXILIARY = {"contact-sheet.jpg"}
MAX_CAPTURE_BYTES = 15_000_000
MAX_CAPTURE_TOTAL_BYTES = 1_200_000_000


def hosted_guard() -> None:
    """Run before any path/archive operation in production commands."""
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("hosted Linux GitHub Actions required before filesystem/archive IO")
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise RuntimeError("unexpected repository before filesystem/archive IO")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_member(name: str, is_dir: bool) -> str:
    if is_dir:
        name = name.rstrip("/")
    if is_dir and name in ("", "."):
        return ""
    if "\\" in name or name.startswith("/"):
        raise ValueError(f"unsafe archive member: {name}")
    parts = name.split("/")
    while parts and parts[0] in ("", "."):
        parts.pop(0)
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"unsafe archive member: {name}")
    normalized = "/".join(parts)
    if not normalized and not is_dir:
        raise ValueError("archive root member must be a directory")
    return normalized


def read_archive(data: bytes) -> tuple[dict[str, bytes], dict[str, tarfile.TarInfo], set[str]]:
    if len(data) != PARENT_BYTES or digest(data) != PARENT_SHA256:
        raise ValueError("parent source archive size or SHA-256 mismatch")
    files: dict[str, bytes] = {}
    infos: dict[str, tarfile.TarInfo] = {}
    dirs: set[str] = set()
    seen: set[str] = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        members = tf.getmembers()
        if not members or len(members) > MAX_ARCHIVE_MEMBERS:
            raise ValueError("parent archive member count outside bounds")
        for info in members:
            is_dir = info.isdir()
            normalized = normalize_member(info.name, is_dir)
            if normalized in seen:
                raise ValueError("duplicate normalized archive member")
            seen.add(normalized)
            if normalized == "" and is_dir:
                continue  # The existing source package uses the conventional root `.` directory.
            if not (is_dir or info.isfile()):
                raise ValueError("links and special archive members are refused")
            if is_dir:
                dirs.add(normalized)
                infos[normalized] = info
                continue
            if info.size < 0 or info.size > MAX_MEMBER_BYTES:
                raise ValueError("archive member size outside bounds")
            total += info.size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("expanded source package exceeds size bound")
            stream = tf.extractfile(info)
            if stream is None:
                raise ValueError("unreadable regular archive member")
            body = stream.read(info.size + 1)
            if len(body) != info.size:
                raise ValueError("archive member length does not match header")
            files[normalized] = body
            infos[normalized] = info
    required = {"film/film.js", "film/sets_a.js", "film/index.html", "SHA256SUMS.txt", "static_check.py"}
    if not required <= set(files):
        raise ValueError("sealed F02 parent is missing required source members")
    return files, infos, dirs


def parse_checksums(data: bytes) -> dict[str, str]:
    result = {}
    for line in data.decode("utf-8").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (\./[^\n]+)", line)
        if not match:
            raise ValueError("source checksum manifest contains an unrecognized row")
        name = normalize_member(match.group(2), False)
        if name in result:
            raise ValueError("duplicate checksum path")
        result[name] = match.group(1)
    return result


def verify_parent_manifest(files: dict[str, bytes]) -> None:
    rows = parse_checksums(files["SHA256SUMS.txt"])
    if set(rows) != set(files) - {"SHA256SUMS.txt"}:
        raise ValueError("parent checksum manifest does not enumerate the source package")
    for name, expected in rows.items():
        if digest(files[name]) != expected:
            raise ValueError(f"parent source member disagrees with checksum manifest: {name}")


def apply_overlay(parent: bytes, overlay_files: dict[str, bytes]) -> tuple[dict[str, bytes], dict[str, tarfile.TarInfo], set[str]]:
    if set(overlay_files) != OVERLAY_NAMES:
        raise ValueError("overlay must contain exactly film/film.js and film/sets_a.js")
    for name, body in overlay_files.items():
        if digest(body) != OVERLAY_HASHES[name]:
            raise ValueError(f"overlay source hash mismatch: {name}")
    files, infos, dirs = read_archive(parent)
    verify_parent_manifest(files)
    before = dict(files)
    files.update(overlay_files)
    old_manifest = parse_checksums(before["SHA256SUMS.txt"])
    for name in OVERLAY_NAMES:
        old_manifest[name] = digest(files[name])
    files["SHA256SUMS.txt"] = "".join(
        f"{value}  ./{name}\n" for name, value in sorted(old_manifest.items())
    ).encode("utf-8")
    changed = {name for name in files if before.get(name) != files[name]}
    if changed != ALLOWED_CONTENT_CHANGES:
        raise ValueError(f"package content changed outside the two code members and derived checksums: {sorted(changed)}")
    return files, infos, dirs


def write_archive(files: dict[str, bytes], infos: dict[str, tarfile.TarInfo], dirs: set[str]) -> bytes:
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tf:
            root_info = tarfile.TarInfo(".")
            root_info.type = tarfile.DIRTYPE
            root_info.mode = 0o755
            root_info.uid = root_info.gid = 0
            root_info.mtime = 0
            tf.addfile(root_info)
            for name in sorted(dirs):
                old = infos[name]
                info = tarfile.TarInfo("./" + name)
                info.type = tarfile.DIRTYPE
                info.mode = stat.S_IMODE(old.mode) or 0o755
                info.uid = old.uid; info.gid = old.gid
                info.uname = old.uname; info.gname = old.gname
                info.mtime = old.mtime
                tf.addfile(info)
            for name in sorted(files):
                old = infos[name]
                info = tarfile.TarInfo("./" + name)
                info.size = len(files[name])
                info.mode = stat.S_IMODE(old.mode) or 0o644
                info.uid = old.uid; info.gid = old.gid
                info.uname = old.uname; info.gname = old.gname
                info.mtime = old.mtime
                tf.addfile(info, io.BytesIO(files[name]))
    return raw.getvalue()


def verify_repository_metadata(repo_path: Path, release_path: Path, asset_path: Path) -> None:
    repo = json.loads(repo_path.read_text(encoding="utf-8"))
    release = json.loads(release_path.read_text(encoding="utf-8"))
    asset = json.loads(asset_path.read_text(encoding="utf-8"))
    if (repo.get("full_name") != REPO or repo.get("private") is not False
            or repo.get("visibility") != "public"):
        raise ValueError("source transfer is allowed only for the verified public repository")
    if (release.get("id") != PARENT_RELEASE_ID or release.get("tag_name") != PARENT_RELEASE
            or release.get("draft") is not False):
        raise ValueError("parent release identity or publication status mismatch")
    if (asset.get("id") != PARENT_ASSET_ID or asset.get("name") != "source.tar.gz"
            or asset.get("size") != PARENT_BYTES or asset.get("state") != "uploaded"
            or asset.get("digest") != "sha256:" + PARENT_SHA256):
        raise ValueError("parent source asset identity mismatch")
    if not any(a.get("id") == PARENT_ASSET_ID and a.get("name") == "source.tar.gz"
               and a.get("size") == PARENT_BYTES and a.get("digest") == "sha256:" + PARENT_SHA256
               and a.get("state") == "uploaded" for a in release.get("assets", [])):
        raise ValueError("pinned source asset is not a member of the pinned parent release")


def seal(args: argparse.Namespace) -> dict:
    hosted_guard()
    verify_repository_metadata(args.repository_json, args.release_json, args.asset_json)
    parent = args.parent_archive.read_bytes()
    overlay = {}
    for name in sorted(OVERLAY_NAMES):
        path = args.overlay_root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("overlay member must be a regular checked-out file")
        overlay[name] = path.read_bytes()
    files, infos, dirs = apply_overlay(parent, overlay)
    # Rebuild the complete package on the hosted runner, then independently reopen and compare every member.
    output = write_archive(files, infos, dirs)
    reopened, _, _ = read_archive_for_rebuilt(output)
    if reopened != files:
        raise ValueError("rebuilt archive member bytes differ from the validated overlay tree")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    args.project_root.mkdir(parents=True, exist_ok=False)
    for name in sorted(dirs):
        (args.project_root / name).mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        target = args.project_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        target.chmod(stat.S_IMODE(infos[name].mode) or 0o644)
    package_sha = digest(output)
    release_tag = "F02-isolated-source-candidate-" + package_sha
    receipt = {
        "kind": "f02-hosted-isolated-source-candidate-overlay",
        "candidate_class": CANDIDATE_CLASS,
        "owner_adoption": OWNER_ADOPTION,
        "prior_db1e_source": REJECTED_DIAGNOSTIC_ONLY,
        "repository": REPO,
        "parent_release": PARENT_RELEASE,
        "parent_release_id": PARENT_RELEASE_ID,
        "parent_asset_id": PARENT_ASSET_ID,
        "parent_asset_bytes": PARENT_BYTES,
        "parent_source_sha256": PARENT_SHA256,
        "candidate_builder_owner_source": {name: {"sha256": value} for name, value in sorted(CANDIDATE_BUILDER_OWNER_HASHES.items())},
        "overlay_files": {name: {"bytes": len(overlay[name]), "sha256": digest(overlay[name])}
                           for name in sorted(overlay)},
        "changed_package_members": sorted(ALLOWED_CONTENT_CHANGES),
        "preserved_package_members_byte_identical": sorted(set(files) - ALLOWED_CONTENT_CHANGES),
        "source_archive_tag": release_tag,
        "source_archive_bytes": len(output),
        "source_archive_sha256": package_sha,
        "rendered_media_changed": False,
        "mix_logo_and_other_parent_members_byte_identical": True,
        "capture_class": "isolated_source_candidate_composition_only",
        "editorial_status": "NOT_REVIEWED",
        "release_approval": "NOT_GRANTED",
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def check_create_only_tag(tag: str) -> dict:
    hosted_guard()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required for protected release publication")
    headers = {"Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "F02-opening-camera-extraction-capture"}
    checks = [f"https://api.github.com/repos/{REPO}/releases/tags/{tag}",
              f"https://api.github.com/repos/{REPO}/git/ref/tags/{tag}"]
    for url in checks:
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status == 200:
                    raise RuntimeError("create-only source tag or release already exists")
                raise RuntimeError("unexpected GitHub API status while checking create-only tag")
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise RuntimeError(f"GitHub API could not verify create-only tag (HTTP {error.code})") from None
    return {"tag": tag, "release_absent": True, "git_ref_absent": True}


def verify_published(args: argparse.Namespace) -> dict:
    hosted_guard()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    release = json.loads(args.release_json.read_text(encoding="utf-8"))
    asset = json.loads(args.asset_json.read_text(encoding="utf-8"))
    tag = receipt.get("source_archive_tag")
    expected_sha = receipt.get("source_archive_sha256")
    expected_size = receipt.get("source_archive_bytes")
    if (receipt.get("kind") != "f02-hosted-isolated-source-candidate-overlay"
            or receipt.get("candidate_class") != CANDIDATE_CLASS
            or receipt.get("owner_adoption") != OWNER_ADOPTION
            or receipt.get("prior_db1e_source") != REJECTED_DIAGNOSTIC_ONLY):
        raise ValueError("published package is not the pinned isolated source candidate")
    if release.get("tag_name") != tag or release.get("draft") is not False:
        raise ValueError("new release tag or published state does not match the sealed receipt")
    if (asset.get("name") != "source.tar.gz" or asset.get("state") != "uploaded"
            or asset.get("size") != expected_size or asset.get("digest") != "sha256:" + expected_sha):
        raise ValueError("published source asset does not match sealed bytes and digest")
    if not any(a.get("id") == asset.get("id") and a.get("name") == "source.tar.gz"
               and a.get("size") == expected_size and a.get("digest") == "sha256:" + expected_sha
               and a.get("state") == "uploaded" for a in release.get("assets", [])):
        raise ValueError("published source asset is not a member of the new release")
    identity = {"repository": REPO, "release_id": release.get("id"), "release_tag": tag,
                "asset_id": asset.get("id"), "asset_name": asset.get("name"),
                "asset_bytes": asset.get("size"), "asset_sha256": expected_sha,
                "asset_state": asset.get("state"), "source_receipt_sha256": digest(args.receipt.read_bytes()),
                "create_only_tag_absence_preflight": True,
                "github_immutable_release_feature": "not asserted",
                "candidate_class": CANDIDATE_CLASS, "owner_adoption": OWNER_ADOPTION,
                "prior_db1e_source": REJECTED_DIAGNOSTIC_ONLY,
                "editorial_status": "NOT_REVIEWED", "release_approval": "NOT_GRANTED"}
    args.output.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return identity


def bind_plan(args: argparse.Namespace) -> dict:
    hosted_guard()
    plan = json.loads(args.template.read_text(encoding="utf-8"))
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    if (plan.get("schema") != "f02-isolated-source-candidate-capture-plan-v1"
            or plan.get("capture_class") != "isolated_source_candidate_composition_only"
            or plan.get("candidate_class") != CANDIDATE_CLASS
            or plan.get("owner_adoption") != OWNER_ADOPTION
            or plan.get("prior_db1e_source") != REJECTED_DIAGNOSTIC_ONLY
            or plan.get("candidate_builder_owner_source") != {name: {"sha256": value} for name, value in sorted(CANDIDATE_BUILDER_OWNER_HASHES.items())}
            or plan.get("captures") != CAPTURES
            or plan.get("film_js_sha256") != OVERLAY_HASHES["film/film.js"]
            or plan.get("sets_a_sha256") != OVERLAY_HASHES["film/sets_a.js"]
            or plan.get("parent_source_sha256") != PARENT_SHA256
            or receipt.get("kind") != "f02-hosted-isolated-source-candidate-overlay"
            or receipt.get("parent_source_sha256") != PARENT_SHA256
            or receipt.get("candidate_class") != CANDIDATE_CLASS
            or receipt.get("owner_adoption") != OWNER_ADOPTION
            or receipt.get("prior_db1e_source") != REJECTED_DIAGNOSTIC_ONLY
            or receipt.get("editorial_status") != "NOT_REVIEWED"
            or receipt.get("release_approval") != "NOT_GRANTED"):
        raise ValueError("capture template and sealed source receipt disagree")
    plan["source_archive_tag"] = receipt["source_archive_tag"]
    plan["source_archive_sha256"] = receipt["source_archive_sha256"]
    plan["source_archive_bytes"] = receipt["source_archive_bytes"]
    plan["overlay_files"] = receipt["overlay_files"]
    plan["candidate_class"] = CANDIDATE_CLASS
    plan["owner_adoption"] = OWNER_ADOPTION
    args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return plan


def read_archive_for_rebuilt(data: bytes) -> tuple[dict[str, bytes], dict[str, tarfile.TarInfo], set[str]]:
    # The fixed parent size/hash applies only to the input. Rebuilt bytes are checked structurally here.
    files: dict[str, bytes] = {}
    infos: dict[str, tarfile.TarInfo] = {}
    dirs: set[str] = set()
    seen: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for info in tf.getmembers():
            name = normalize_member(info.name, info.isdir())
            if name in seen:
                raise ValueError("rebuilt archive has duplicate normalized member")
            seen.add(name)
            if name == "" and info.isdir():
                continue
            if info.isdir():
                dirs.add(name)
            elif info.isfile():
                stream = tf.extractfile(info)
                if stream is None:
                    raise ValueError("rebuilt member unreadable")
                files[name] = stream.read()
            else:
                raise ValueError("rebuilt archive contains link or special member")
    return files, infos, dirs


def collect(args: argparse.Namespace) -> dict:
    hosted_guard()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    source_receipt = json.loads(args.source_receipt.read_text(encoding="utf-8"))
    identity = json.loads(args.source_identity.read_text(encoding="utf-8"))
    if (plan.get("schema") != "f02-isolated-source-candidate-capture-plan-v1"
            or plan.get("capture_class") != "isolated_source_candidate_composition_only"
            or plan.get("captures") != CAPTURES
            or plan.get("film_js_sha256") != OVERLAY_HASHES["film/film.js"]
            or plan.get("sets_a_sha256") != OVERLAY_HASHES["film/sets_a.js"]
            or plan.get("parent_source_sha256") != PARENT_SHA256
            or plan.get("candidate_class") != CANDIDATE_CLASS
            or plan.get("owner_adoption") != OWNER_ADOPTION
            or plan.get("prior_db1e_source") != REJECTED_DIAGNOSTIC_ONLY
            or plan.get("candidate_builder_owner_source") != {name: {"sha256": value} for name, value in sorted(CANDIDATE_BUILDER_OWNER_HASHES.items())}
            or plan.get("candidate_builder_owner_source") != source_receipt.get("candidate_builder_owner_source")):
        raise ValueError("capture plan does not match the frozen parent and two-file overlay")
    if (source_receipt.get("kind") != "f02-hosted-isolated-source-candidate-overlay"
            or source_receipt.get("capture_class") != "isolated_source_candidate_composition_only"
            or source_receipt.get("prior_db1e_source") != REJECTED_DIAGNOSTIC_ONLY
            or source_receipt.get("source_archive_sha256") != plan.get("source_archive_sha256")
            or source_receipt.get("source_archive_tag") != plan.get("source_archive_tag")
            or source_receipt.get("overlay_files") != plan.get("overlay_files")
            or source_receipt.get("candidate_class") != CANDIDATE_CLASS
            or source_receipt.get("owner_adoption") != OWNER_ADOPTION
            or source_receipt.get("editorial_status") != "NOT_REVIEWED"
            or source_receipt.get("release_approval") != "NOT_GRANTED"):
        raise ValueError("capture plan is not bound to the published source package receipt")
    if (identity.get("release_tag") != source_receipt.get("source_archive_tag")
            or identity.get("asset_sha256") != source_receipt.get("source_archive_sha256")
            or identity.get("asset_bytes") != source_receipt.get("source_archive_bytes")
            or identity.get("candidate_class") != CANDIDATE_CLASS
            or identity.get("owner_adoption") != OWNER_ADOPTION
            or identity.get("prior_db1e_source") != REJECTED_DIAGNOSTIC_ONLY
            or identity.get("editorial_status") != "NOT_REVIEWED"
            or identity.get("release_approval") != "NOT_GRANTED"):
        raise ValueError("capture is not bound to the independently verified published source asset")
    by_time = {f"{row['time']:.3f}": row for row in CAPTURES}
    entries = list(args.snapshots.iterdir())
    if any(p.is_symlink() or not p.is_file() for p in entries):
        raise ValueError("snapshot folder contains symlink or non-file")
    files = [p for p in entries if p.name not in SNAPSHOT_AUXILIARY]
    if len(files) != len(CAPTURES):
        raise ValueError("snapshot count differs from exact 74-frame plan")
    captured = {}
    captured_total = 0
    for path in files:
        match = SNAPSHOT_RE.fullmatch(path.name)
        if not match:
            raise ValueError("unexpected HyperFrames snapshot filename")
        stamp = f"{float(match.group(1)):.3f}"
        if stamp not in by_time or stamp in captured:
            raise ValueError("missing, duplicate or unplanned source snapshot time")
        body = path.read_bytes()
        if len(body) < 45 or len(body) > MAX_CAPTURE_BYTES or not body.startswith(PNG_SIGNATURE) or not body.endswith(PNG_IEND):
            raise ValueError("capture is not a complete PNG")
        captured_total += len(body)
        if captured_total > MAX_CAPTURE_TOTAL_BYTES:
            raise ValueError("74-frame source capture exceeds the 1.2 GB review-branch bound")
        width, height = int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big")
        if (width, height) != (1920, 1080):
            raise ValueError("snapshot dimensions differ from F02 source composition")
        captured[stamp] = (path, body)
    if set(captured) != set(by_time):
        raise ValueError("source capture timestamps do not match the plan")
    args.output.mkdir(parents=True, exist_ok=False)
    frames = args.output / "frames"
    frames.mkdir()
    records = []
    for stamp, row in sorted(by_time.items(), key=lambda pair: float(pair[0])):
        body = captured[stamp][1]
        name = row["name"] + ".png"
        (frames / name).write_bytes(body)
        records.append({"name": row["name"], "path": "frames/" + name,
                        "time": row["time"], "bytes": len(body), "sha256": digest(body)})
    receipt = {"kind": "f02-isolated-source-candidate-capture", "candidate_class": CANDIDATE_CLASS,
               "owner_adoption": OWNER_ADOPTION, "prior_db1e_source": REJECTED_DIAGNOSTIC_ONLY,
               "source_release": source_receipt["source_archive_tag"],
               "source_asset_sha256": source_receipt["source_archive_sha256"],
               "source_asset_id": identity["asset_id"], "source_release_id": identity["release_id"],
               "parent_source_sha256": PARENT_SHA256, "candidate_builder_owner_source": source_receipt["candidate_builder_owner_source"],
               "overlay_files": source_receipt["overlay_files"],
               "capture_class": "isolated_source_candidate_composition_only", "frames": records,
               "editorial_status": "NOT_REVIEWED", "release_approval": "NOT_GRANTED"}
    receipt_path = args.output / "CAPTURE-RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checks = [f"{r['sha256']}  {r['path']}" for r in records]
    checks.append(f"{digest(receipt_path.read_bytes())}  CAPTURE-RECEIPT.json")
    (args.output / "SHA256SUMS.txt").write_text("\n".join(checks) + "\n", encoding="utf-8")
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    seal_cmd = sub.add_parser("seal")
    seal_cmd.add_argument("--repository-json", type=Path, required=True)
    seal_cmd.add_argument("--release-json", type=Path, required=True)
    seal_cmd.add_argument("--asset-json", type=Path, required=True)
    seal_cmd.add_argument("--parent-archive", type=Path, required=True)
    seal_cmd.add_argument("--overlay-root", type=Path, required=True)
    seal_cmd.add_argument("--output", type=Path, required=True)
    seal_cmd.add_argument("--receipt", type=Path, required=True)
    seal_cmd.add_argument("--project-root", type=Path, required=True)
    tag_cmd = sub.add_parser("check-tag-free")
    tag_cmd.add_argument("--tag", required=True)
    verify_cmd = sub.add_parser("verify-published")
    verify_cmd.add_argument("--receipt", type=Path, required=True)
    verify_cmd.add_argument("--release-json", type=Path, required=True)
    verify_cmd.add_argument("--asset-json", type=Path, required=True)
    verify_cmd.add_argument("--output", type=Path, required=True)
    bind_cmd = sub.add_parser("bind-plan")
    bind_cmd.add_argument("--template", type=Path, required=True)
    bind_cmd.add_argument("--receipt", type=Path, required=True)
    bind_cmd.add_argument("--output", type=Path, required=True)
    collect_cmd = sub.add_parser("collect")
    collect_cmd.add_argument("--snapshots", type=Path, required=True)
    collect_cmd.add_argument("--plan", type=Path, required=True)
    collect_cmd.add_argument("--source-receipt", type=Path, required=True)
    collect_cmd.add_argument("--source-identity", type=Path, required=True)
    collect_cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "seal":
        result = seal(args)
    elif args.command == "check-tag-free":
        result = check_create_only_tag(args.tag)
    elif args.command == "verify-published":
        result = verify_published(args)
    elif args.command == "bind-plan":
        result = bind_plan(args)
    else:
        result = collect(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
