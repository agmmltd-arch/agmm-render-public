#!/usr/bin/env python3
"""Fail closed when a published Wave03 source target is missing or altered."""
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath


def blob_sha1(data: bytes) -> str:
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data).hexdigest()


def verify(manifest_path: Path) -> tuple[int, int]:
    manifest_path = manifest_path.resolve(strict=True)
    package_root = manifest_path.parent
    checkout_root = package_root.parent
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("entries"), list) or not manifest["entries"]:
        raise ValueError("manifest schema or entries are invalid")
    seen = set()
    total = 0
    for item in manifest["entries"]:
        target = item.get("target_path")
        if not isinstance(target, str) or not target or "\\" in target:
            raise ValueError("each entry needs a POSIX repository target_path")
        rel = PurePosixPath(target)
        if rel.is_absolute() or ".." in rel.parts or target in seen:
            raise ValueError(f"unsafe or duplicate target path: {target}")
        seen.add(target)
        path = (checkout_root / Path(*rel.parts)).resolve(strict=True)
        try:
            path.relative_to(checkout_root)
        except ValueError as error:
            raise ValueError(f"target escapes checkout: {target}") from error
        if not path.is_file():
            raise ValueError(f"target is not a file: {target}")
        data = path.read_bytes()
        expected_bytes = item.get("bytes")
        expected_sha256 = item.get("sha256")
        expected_blob = item.get("git_blob_sha1")
        if len(data) != expected_bytes:
            raise ValueError(f"byte count mismatch for {target}: expected {expected_bytes}, got {len(data)}")
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ValueError(f"SHA-256 mismatch for {target}")
        if blob_sha1(data) != expected_blob:
            raise ValueError(f"Git blob SHA-1 mismatch for {target}")
        total += len(data)
    return len(seen), total


if __name__ == "__main__":
    try:
        count, total_bytes = verify(Path(__file__).resolve().parents[1] / "SOURCE-CAPTURE-PUBLICATION-MANIFEST-WAVE03.json")
    except Exception as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        raise SystemExit(2)
    print(f"PASS: {count} published source files verified ({total_bytes} bytes; SHA-256 and Git blob IDs match)")
