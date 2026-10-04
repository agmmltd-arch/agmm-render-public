#!/usr/bin/env python3
"""Fail closed if a public payload contains any selected raw S90 SFX input.

This guard is for payloads destined for a public Git branch, release, or
artifact. It compares byte digests on hosted Linux and inspects tar member names;
it never extracts archives. A synchronized finished project is a separate
licensed use and is not approved by this helper.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import tarfile
from pathlib import Path, PurePosixPath

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PRIVATE_COMMIT = "b2c1ead7c7c55fceaaa3229adfa1b4fdc77f1d2d"


class Refusal(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def raw_identity_set(receipt: dict) -> tuple[set[str], set[str]]:
    if receipt.get("kind") != "s90_hosted_private_sfx_input_verification_v1":
        raise Refusal("private SFX receipt kind is not recognized")
    if receipt.get("private_commit") != PRIVATE_COMMIT:
        raise Refusal("private SFX receipt commit is not the reviewed S90 source")
    rows = receipt.get("sfx")
    if not isinstance(rows, list) or len(rows) != 16:
        raise Refusal("private SFX receipt must bind exactly 16 selected assets")
    digests, names = set(), set()
    for row in rows:
        digest = row.get("sha256_ubuntu") if isinstance(row, dict) else None
        path = row.get("library_path") if isinstance(row, dict) else None
        if not isinstance(digest, str) or not SHA_RE.fullmatch(digest) or not isinstance(path, str):
            raise Refusal("private SFX receipt has a missing digest/path")
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or not path.startswith("library/"):
            raise Refusal("private SFX receipt contains an unsafe library path")
        if digest in digests or pure.name in names:
            raise Refusal("private SFX receipt contains duplicate asset identity")
        digests.add(digest)
        names.add(pure.name)
    return digests, names


def validate_public_payload(paths: list[Path], receipt: dict) -> dict:
    raw_digests, raw_names = raw_identity_set(receipt)
    checked = []
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise Refusal(f"public payload member is absent or not a regular file: {path.name}")
        # Keep isolated WAV inputs (raw SFX, voice, and the intermediate mix)
        # out of public Actions artifacts. The finished synchronized video is
        # the review object; an intermediate waveform is not.
        if path.suffix.lower() == ".wav":
            raise Refusal(f"waveform input/intermediate is forbidden in public payload: {path.name}")
        if path.name in raw_names:
            raise Refusal(f"raw selected SFX filename is forbidden in public payload: {path.name}")
        digest = sha256_file(path)
        if digest in raw_digests:
            raise Refusal(f"public payload contains bytes identical to a selected raw SFX file: {path.name}")
        if tarfile.is_tarfile(path):
            try:
                with tarfile.open(path, "r:*") as archive:
                    members = archive.getmembers()
                    if not members or len(members) > 10_000:
                        raise Refusal(f"public archive has an unsafe member count: {path.name}")
                    expanded = 0
                    for member in members:
                        normalized = PurePosixPath(member.name.replace("\\", "/"))
                        if (normalized.is_absolute() or ".." in normalized.parts
                                or "\x00" in member.name or member.issym() or member.islnk()
                                or member.isdev() or member.isfifo()
                                or not (member.isfile() or member.isdir())):
                            raise Refusal(f"public archive has an unsafe member: {member.name}")
                        if normalized.suffix.lower() == ".wav":
                            raise Refusal(f"public archive contains a waveform member: {normalized.name}")
                        if normalized.name in raw_names:
                            raise Refusal(f"public archive contains a selected raw SFX member: {normalized.name}")
                        expanded += member.size
                        if expanded > 4_000_000_000:
                            raise Refusal(f"public archive expands beyond the inspection bound: {path.name}")
                        if member.isfile():
                            source = archive.extractfile(member)
                            if source is None:
                                raise Refusal(f"public archive member cannot be read safely: {member.name}")
                            member_hash = hashlib.sha256()
                            for block in iter(lambda: source.read(1 << 20), b""):
                                member_hash.update(block)
                            if member_hash.hexdigest() in raw_digests:
                                raise Refusal(f"public archive contains bytes identical to a selected raw SFX file: {member.name}")
            except tarfile.TarError as exc:
                raise Refusal(f"public archive could not be safely inspected: {path.name}") from exc
        checked.append({"name": path.name, "sha256": digest, "bytes": path.stat().st_size})
    if not checked:
        raise Refusal("public payload manifest is empty")
    return {"kind": "s90_public_payload_raw_sfx_exclusion_check_v1",
            "checked_count": len(checked), "raw_selected_sfx_count": 16,
            "raw_sfx_found": False, "members": checked,
            "license_decision": "NOT_MADE; synchronized finished-project permission and per-asset provenance remain separate review gates"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-sfx-receipt", type=Path, required=True)
    parser.add_argument("--payload-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    try:
        if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("S90_HOSTED_AV_CANDIDATE") != "1":
            raise Refusal("public payload SFX exclusion check runs only on the explicitly enabled hosted Linux job")
        receipt = json.loads(args.private_sfx_receipt.read_text(encoding="utf-8"))
        root = args.payload_root.resolve()
        paths = []
        for raw in args.paths:
            rel = PurePosixPath(raw)
            if rel.is_absolute() or ".." in rel.parts:
                raise Refusal("payload member path traversal refused")
            target = (root / Path(*rel.parts)).resolve()
            if root not in target.parents:
                raise Refusal("payload member escapes payload root")
            paths.append(target)
        result = validate_public_payload(paths, receipt)
        if args.manifest.exists():
            raise Refusal("refusing to overwrite an existing public-payload verification manifest")
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": "RAW_SFX_ABSENCE_CHECK_PASS", "members_checked": len(paths),
                          "raw_sfx_included": False, "licensing_clearance": "OPEN"}, sort_keys=True))
    except (OSError, json.JSONDecodeError, Refusal, tarfile.TarError) as exc:
        print(f"S90 public payload refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
