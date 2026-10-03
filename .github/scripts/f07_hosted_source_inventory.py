#!/usr/bin/env python3
"""Inventory four text sources from a pinned F07 parent archive on hosted Linux."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import tarfile
from pathlib import Path, PurePosixPath

EXPECTED_ASSET_SHA256 = "10394b58dad8f1e6131486edb2d9d310b82a923fef2ca6aea50f229cb165bfd7"
EXPECTED_ASSET_BYTES = 43_650_580
EXPECTED_RELEASE = "F07-r4-actions-full-landscape-4k-20260930194517"
EXPECTED_REPOSITORY = "agmmltd-arch/agmm-render-public"
SOURCE_PATHS = {
    "film.js": "film/film.js",
    "words.js": "film/words.js",
    "film.css": "film/film.css",
    "sets_studio.js": "film/sets_studio.js",
}
# These child digests come from the package's text-only SHA256SUMS receipt. The
# archive digest above binds the unchanged parent package; media bytes are never
# extracted, opened, or copied to the review branch by this inventory.
PRESERVED_ASSETS = {
    "audio/mix.flac": "5dde65a9a4ee8fb22ade88fcba4167fcc0f4a9b976e0ecd7a29645acc142a49a",
    "film/img/octopus-logo-white.svg": "22118fc92c6642202c64f49a20a7ac07765f596bf0052ea213a6c0bd0d79cca7",
    "film/img/octopus-logo.svg": "75935ef3e9f6cd80d0980c7cf2a2228d2dc1121fd65266dc7db17bea1418c112",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_release(metadata_path: Path, asset_id: int, asset_name: str, size: int, sha256: str) -> None:
    rows = json.loads(metadata_path.read_text(encoding="utf-8"))
    if len(rows) != 1:
        raise ValueError("Pinned release must resolve to exactly one asset.")
    row = rows[0]
    expected = {
        "id": asset_id,
        "name": asset_name,
        "size": size,
        "digest": f"sha256:{sha256}",
        "state": "uploaded",
    }
    if row != expected:
        raise ValueError("GitHub release asset metadata differs from the sealed receipt.")


def check_repository(metadata_path: Path, expected_repository: str) -> None:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected = {"full_name": expected_repository, "private": False, "visibility": "public"}
    if expected_repository != EXPECTED_REPOSITORY or metadata != expected:
        raise ValueError("Workflow repository identity/public visibility differs from the reviewed public source host.")


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
        # A common tar root entry is "." or "./". Permit exactly one such
        # directory; no file or alternate spelling may target the extraction root.
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


def parse_word_timing(source: str) -> tuple[float, list[list[object]]]:
    match = re.fullmatch(
        r"\s*window\.F07_WORDS\s*=\s*(\[.*?\])\s*;\s*window\.F07_DUR\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*;?\s*",
        source,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError("words.js does not match the expected data-only F07 format.")
    rows = json.loads(match.group(1))
    duration = float(match.group(2))
    if not isinstance(rows, list) or not rows:
        raise ValueError("F07 word timing array is empty or invalid.")
    expected_index = 0
    for row in rows:
        if (not isinstance(row, list) or len(row) != 5 or row[0] != expected_index
                or not isinstance(row[1], (int, float)) or not isinstance(row[2], (int, float))
                or row[1] < 0 or row[2] < row[1] or row[2] > duration
                or not isinstance(row[3], str) or not isinstance(row[4], str)):
            raise ValueError(f"Invalid word-timing entry at index {expected_index}.")
        expected_index += 1
    return duration, rows


def inventory(archive_path: Path, expected_sha256: str, release_tag: str, output: Path) -> dict[str, object]:
    if platform.system() == "Darwin":
        raise RuntimeError("F07 source inventory is hosted-Linux-only; refusing archive I/O on macOS.")
    if release_tag != EXPECTED_RELEASE or expected_sha256 != EXPECTED_ASSET_SHA256:
        raise ValueError("Only the reviewed immutable F07 release/tag digest is allowed.")
    archive_bytes_digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if archive_bytes_digest != expected_sha256:
        raise ValueError("Downloaded archive SHA-256 mismatch.")
    if archive_path.stat().st_size != EXPECTED_ASSET_BYTES:
        raise ValueError("Downloaded archive byte count mismatch.")

    output.mkdir(parents=True, exist_ok=False)
    source_dir = output / "source"
    source_dir.mkdir()
    with tarfile.open(archive_path, mode="r:gz") as tar:
        members = safe_members(tar)
        required = set(SOURCE_PATHS.values()) | set(PRESERVED_ASSETS)
        missing = sorted(required - members.keys())
        if missing:
            raise ValueError(f"Pinned F07 package is missing required source/media paths: {missing}")
        extracted: dict[str, bytes] = {}
        for output_name, archive_name in SOURCE_PATHS.items():
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
            extracted[output_name] = content
            (source_dir / output_name).write_bytes(content)

    words_source = extracted["words.js"].decode("utf-8")
    duration, timing_rows = parse_word_timing(words_source)
    source_details = {
        output_name: {
            "archive_path": archive_name,
            "sha256": digest(extracted[output_name]),
            "bytes": len(extracted[output_name]),
        }
        for output_name, archive_name in SOURCE_PATHS.items()
    }
    result: dict[str, object] = {
        "schema": "f07-hosted-source-inventory-v1",
        "status": "INVENTORY_ONLY_NOT_APPROVAL",
        "release_tag": release_tag,
        "source_asset": {
            "name": "source.tar.gz",
            "size_bytes": archive_path.stat().st_size,
            "sha256": archive_bytes_digest,
            "sha256_source": "GitHub release-asset digest, independently matched to renders/r3/source.sha256",
        },
        "source_text": source_details,
        "narration_timing": {
            "duration_seconds": duration,
            "entry_count": len(timing_rows),
            "entries": [
                {"index": row[0], "start": row[1], "end": row[2], "paragraph": row[3], "text": row[4]}
                for row in timing_rows
            ],
        },
        "preserved_parent_assets": [
            {
                "archive_path": path,
                "sha256_from_parent_text_receipt": sha,
                "present_in_sealed_archive": True,
                "member_content_opened": False,
                "member_sha256_recomputed": False,
                "bound_by_verified_parent_archive_sha256": True,
                "copied_to_review_branch": False,
            }
            for path, sha in PRESERVED_ASSETS.items()
        ],
        "branch_content_allowlist": [
            "inventory.json",
            "source/film/film.js",
            "source/film/words.js",
            "source/film/film.css",
            "source/film/sets_studio.js",
        ],
        "media_uploaded_to_review_branch": False,
        "release_approval": False,
    }
    (output / "inventory.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-release")
    check.add_argument("--metadata", type=Path, required=True)
    check.add_argument("--asset-id", type=int, required=True)
    check.add_argument("--asset-name", required=True)
    check.add_argument("--size", type=int, required=True)
    check.add_argument("--sha256", required=True)
    repository = sub.add_parser("check-repository")
    repository.add_argument("--metadata", type=Path, required=True)
    repository.add_argument("--expected-repository", required=True)
    run = sub.add_parser("inventory")
    run.add_argument("--archive", type=Path, required=True)
    run.add_argument("--expected-sha256", required=True)
    run.add_argument("--release-tag", required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "check-release":
        check_release(args.metadata, args.asset_id, args.asset_name, args.size, args.sha256)
        print("PASS: pinned GitHub release asset metadata matches.")
    elif args.command == "check-repository":
        check_repository(args.metadata, args.expected_repository)
        print("PASS: expected public repository identity and visibility confirmed.")
    else:
        result = inventory(args.archive, args.expected_sha256, args.release_tag, args.output)
        print(f"PASS: authenticated source archive; inventoried {len(result['source_text'])} text files and {result['narration_timing']['entry_count']} word-timing entries.")


if __name__ == "__main__":
    main()
