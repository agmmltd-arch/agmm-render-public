#!/usr/bin/env python3
"""Inventory only the four text spec.js members from the sealed S86 r2 package."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tarfile
from pathlib import Path, PurePosixPath

EXPECTED_REPOSITORY = "agmmltd-arch/agmm-render-public"
EXPECTED_RELEASE = "S86-r2-source-202610010547"
EXPECTED_SOURCE_ASSET = {
    "id": 602456631,
    "name": "source.tar.gz",
    "size": 9_830_053,
    "digest": "sha256:c8fa6aea8bc904de1183ef648188de4d7ec2ab0d432be623f6b165fd7ac4408b",
    "state": "uploaded",
}
EXPECTED_SIDECAR_ASSETS = [
    {
        "id": 602456630,
        "name": "parts.json",
        "size": 617,
        "digest": "sha256:1585e81e26e654aabc04ebe0f851a81f0cd13962069027557f1e29db2dadc02d",
        "state": "uploaded",
    },
    {
        "id": 602456632,
        "name": "mix.wav",
        "size": 17_452_902,
        "digest": "sha256:0c252cdf6e412fc2ccadcdb29b940d6a23b7c527276ebf79da468b7f633df436",
        "state": "uploaded",
    },
]
EXPECTED_SOURCE_SHA256 = EXPECTED_SOURCE_ASSET["digest"].removeprefix("sha256:")
SOURCE_PATHS = {f"s86-{part}/spec.js": f"s86-{part}/spec.js" for part in "abcd"}
TEXT_ALLOWLIST = [
    "inventory.json",
    *[f"source/s86-{part}/spec.js" for part in "abcd"],
]


def check_repository(metadata_path: Path, expected_repository: str) -> None:
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected = {"full_name": expected_repository, "private": False, "visibility": "public"}
    if expected_repository != EXPECTED_REPOSITORY or data != expected:
        raise ValueError("Unexpected repository identity or visibility.")


def check_release(metadata_path: Path, release_tag: str) -> None:
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    if release_tag != EXPECTED_RELEASE or data.get("tag_name") != EXPECTED_RELEASE:
        raise ValueError("Only the pinned S86 r2 release is allowed.")
    assets = sorted(data.get("assets", []), key=lambda row: row.get("id", -1))
    expected = sorted([EXPECTED_SOURCE_ASSET, *EXPECTED_SIDECAR_ASSETS], key=lambda row: row["id"])
    if assets != expected:
        raise ValueError("S86 release asset metadata differs from the sealed source/sidecar receipts.")


def safe_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    seen: set[str] = set()
    for member in archive.getmembers():
        raw = member.name
        if "\\" in raw:
            raise ValueError(f"Unsafe archive path spelling: {raw!r}")
        path = PurePosixPath(raw)
        normalized = str(path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe archive path: {raw!r}")
        if normalized in seen:
            raise ValueError(f"Duplicate archive path: {normalized}")
        seen.add(normalized)
        if normalized == "." and member.isdir() and raw in (".", "./"):
            continue
        if normalized in ("", "."):
            raise ValueError(f"Unsafe archive path: {raw!r}")
        if member.isdir():
            continue
        if not member.isfile():
            raise ValueError(f"Non-regular archive entry refused: {normalized}")
        members[normalized] = member
    return members


def inventory(archive_path: Path, expected_sha256: str, release_tag: str, output: Path) -> dict[str, object]:
    if platform.system() == "Darwin":
        raise RuntimeError("S86 source inventory is hosted-Linux-only; refusing archive I/O on macOS.")
    if release_tag != EXPECTED_RELEASE or expected_sha256 != EXPECTED_SOURCE_SHA256:
        raise ValueError("Only the reviewed immutable S86 source release is allowed.")
    archive_data = archive_path.read_bytes()
    archive_sha256 = hashlib.sha256(archive_data).hexdigest()
    if archive_sha256 != expected_sha256:
        raise ValueError("Downloaded source archive SHA-256 mismatch.")
    if len(archive_data) != EXPECTED_SOURCE_ASSET["size"]:
        raise ValueError("Downloaded source archive byte count mismatch.")

    output.mkdir(parents=True, exist_ok=False)
    source_root = output / "source"
    source_root.mkdir()
    with tarfile.open(archive_path, mode="r:gz") as tar:
        members = safe_members(tar)
        missing = sorted(set(SOURCE_PATHS) - members.keys())
        if missing:
            raise ValueError(f"Sealed S86 package is missing required source text members: {missing}")
        extracted: dict[str, bytes] = {}
        for archive_name, output_name in SOURCE_PATHS.items():
            member = members[archive_name]
            if member.size > 2_000_000:
                raise ValueError(f"Source text unexpectedly large: {archive_name}")
            stream = tar.extractfile(member)
            if stream is None:
                raise ValueError(f"Could not read source text member: {archive_name}")
            content = stream.read(2_000_001)
            if len(content) > 2_000_000 or len(content) != member.size:
                raise ValueError(f"Source text size mismatch: {archive_name}")
            content.decode("utf-8", errors="strict")
            extracted[archive_name] = content
            destination = source_root / output_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)

    media_name_hints = sorted(
        name for name in members
        if any(part in name.lower() for part in ("voice", "audio", "mix", "logo", "clearview"))
    )
    result: dict[str, object] = {
        "schema": "s86-hosted-source-inventory-v1",
        "status": "INVENTORY_ONLY_NOT_APPROVAL",
        "release_tag": release_tag,
        "source_asset": {
            "name": EXPECTED_SOURCE_ASSET["name"],
            "asset_id": EXPECTED_SOURCE_ASSET["id"],
            "size_bytes": len(archive_data),
            "sha256": archive_sha256,
            "sha256_source": "GitHub release asset digest matched to local source receipt",
        },
        "source_text": {
            path: {
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "copied_to_review_branch": True,
            }
            for path, content in extracted.items()
        },
        "source_archive_name_only_media_hints": media_name_hints,
        "media_member_content_opened": False,
        "media_member_sha256_recomputed": False,
        "release_sidecar_assets": [
            {
                "name": asset["name"],
                "asset_id": asset["id"],
                "size_bytes": asset["size"],
                "sha256_from_release_api": asset["digest"].removeprefix("sha256:"),
                "downloaded_by_inventory": False,
                "copied_to_review_branch": False,
            }
            for asset in EXPECTED_SIDECAR_ASSETS
        ],
        "branch_content_allowlist": TEXT_ALLOWLIST,
        "media_uploaded_to_review_branch": False,
        "release_approval": False,
    }
    (output / "inventory.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    repository = sub.add_parser("check-repository")
    repository.add_argument("--metadata", type=Path, required=True)
    repository.add_argument("--expected-repository", required=True)
    release = sub.add_parser("check-release")
    release.add_argument("--metadata", type=Path, required=True)
    release.add_argument("--release-tag", required=True)
    run = sub.add_parser("inventory")
    run.add_argument("--archive", type=Path, required=True)
    run.add_argument("--expected-sha256", required=True)
    run.add_argument("--release-tag", required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "check-repository":
        check_repository(args.metadata, args.expected_repository)
        print("PASS: expected public S86 repository confirmed.")
    elif args.command == "check-release":
        check_release(args.metadata, args.release_tag)
        print("PASS: pinned S86 release assets match sealed receipts.")
    else:
        result = inventory(args.archive, args.expected_sha256, args.release_tag, args.output)
        print(f"PASS: authenticated S86 archive; inventoried {len(result['source_text'])} source-text members.")


if __name__ == "__main__":
    main()
