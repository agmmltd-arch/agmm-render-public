#!/usr/bin/env python3
"""Fail closed on changed, extra, missing, non-text, or unpinned Film05 patch inputs."""
from __future__ import annotations
import hashlib
from pathlib import Path
import re
import sys

EXPECTED = {
    "ASSET-LEDGER.md", "BRIEF.md", "CUT-MAP.md", "PREIMAGE-GATE.md",
    "README.md", "SOURCE-MANIFEST.json", "STORYBOARD.md", "index.html",
    "package.json", "static_check.py",
}
HEX = re.compile(r"^[0-9a-f]{64}$")

def verify(patch: Path, manifest: Path, expected_manifest_sha: str) -> None:
    patch = patch.resolve(strict=True)
    manifest = manifest.resolve(strict=True)
    actual_manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    if actual_manifest_sha != expected_manifest_sha:
        raise ValueError("SHA manifest digest differs from the workflow-pinned value")
    files = list(patch.iterdir())
    if any(p.is_symlink() or not p.is_file() for p in files):
        raise ValueError("patch contains a directory, symlink, or special file")
    names = {p.name for p in files}
    if names != EXPECTED or len(files) != 10:
        raise ValueError(f"patch set mismatch: expected exactly 10 text inputs, got {sorted(names)}")
    rows = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if not m:
            raise ValueError("malformed SHA manifest row")
        digest, name = m.groups()
        if name in rows:
            raise ValueError(f"duplicate manifest name: {name}")
        rows[name] = digest
    if set(rows) != EXPECTED or len(rows) != 10:
        raise ValueError("manifest does not cover exactly the ten expected patch files")
    for name in sorted(EXPECTED):
        raw = (patch / name).read_bytes()
        if len(raw) > 2_000_000 or b"\x00" in raw:
            raise ValueError(f"patch file is too large or contains NUL bytes: {name}")
        raw.decode("utf-8")
        if hashlib.sha256(raw).hexdigest() != rows[name]:
            raise ValueError(f"source hash mismatch: {name}")
    print("PATCH_SHA256_GATE_PASS: exact 10 UTF-8 text files match the workflow-pinned SHA manifest")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: verify_text_patch.py PATCH_DIR SHA256SUMS EXPECTED_MANIFEST_SHA256")
    verify(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
