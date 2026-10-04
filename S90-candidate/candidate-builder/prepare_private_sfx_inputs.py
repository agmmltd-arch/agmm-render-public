#!/usr/bin/env python3
"""Verify/stage the exact S90 SFX subset on the hosted Ubuntu runner only.

The source is a private, pinned checkout. This helper checks the commit tree
before reading any WAV, then verifies the 16 selected files against native Git
blob IDs/sizes and the reviewed library's recorded SHA-256 values where those
exist. It writes per-file SHA-256 only on the hosted runner. It never publishes
the source assets or the verification receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

PRIVATE_REPOSITORY = "agmmltd-arch/agmm-video-render"
PRIVATE_COMMIT = "b2c1ead7c7c55fceaaa3229adfa1b4fdc77f1d2d"
SFX_MAP_SHA256 = "a5e0174ed8dc1e38a7163746f6048345c65417c3b16d7f0dbd9a52817a0a23f3"
ROOT_PRIVATE_MANIFEST_SHA256 = "1f7295498ac8cb9c3c4cb47765c879ff56c5df73c0ddd03354bd2d429345622f"
LIBRARY_SHA256 = "2744f53024d42208538675f8d27e24e3f06c4135b81e892af29e2f0538c56215"
MIX_SHA256 = "99921ecd40dc797a76ef9786b75ebfedc6ccc48d8400e0136f89dd47ff7c8a3f"
MIXER_FILES = {
    "mix2.py": "20607f3a9975a99883c5c87ee8b6ba6d0146fc7be24a0c1ffcacef1d63e4dbd4",
    "audio_core.py": "dec742a1db2732e112e3734e245357b0ef6d73415cd458030645fa6e5154f2fa",
    "audio_rules.json": "9aa2a571a34aa8f50b28d995227b581d788fd36d5d6b7c4db3e10866e7bbbb68",
    "voice_chain.py": "64d1ada82e18536228dd111979a5e80e886985513f1d56a8f8fbc66f1753dcb9",
}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_BLOB_RE = re.compile(r"^[0-9a-f]{40}$")


class Refusal(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def require_hosted_linux() -> None:
    if (platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("S90_HOSTED_AV_CANDIDATE") != "1"):
        raise Refusal("private SFX staging is allowed only in the explicitly enabled Ubuntu Actions job")


def read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refusal(f"{label} is missing or invalid") from exc
    if not isinstance(value, dict):
        raise Refusal(f"{label} must be a JSON object")
    return value


def validate_inputs(asset_map: dict, mix: dict, library: dict) -> list[dict]:
    assets = asset_map.get("distinct_assets")
    cues = (mix.get("sfx") or {}).get("cues")
    items = library.get("items")
    if not isinstance(assets, list) or len(assets) != 16:
        raise Refusal("the pinned S90 asset map must contain exactly 16 distinct assets")
    if not isinstance(cues, list) or len(cues) != 19:
        raise Refusal("the pinned S90 mix must contain exactly 19 cues")
    if not isinstance(items, list):
        raise Refusal("the sound library must contain an items list")
    private_input = asset_map.get("protected_private_input")
    if (not isinstance(private_input, dict)
            or private_input.get("repository") != PRIVATE_REPOSITORY
            or private_input.get("pinned_commit") != PRIVATE_COMMIT
            or private_input.get("root_native_manifest_sha256") != ROOT_PRIVATE_MANIFEST_SHA256
            or private_input.get("ubuntu_sha256") != "NOT_COMPUTED; required by hosted input helper"):
        raise Refusal("asset map is not bound to the root-authenticated private source manifest")
    ids = [row.get("sfx_id") for row in assets if isinstance(row, dict)]
    if len(ids) != 16 or len(set(ids)) != 16:
        raise Refusal("the pinned S90 map contains missing or duplicate SFX IDs")
    cue_ids = {row.get("sfx_id") for row in cues if isinstance(row, dict)}
    if len(cue_ids) != 16 or cue_ids != set(ids):
        raise Refusal("the 19-cue plan must reference exactly the 16 mapped assets")
    by_id = {row.get("id"): row for row in items if isinstance(row, dict)}
    if len(by_id) != len(items):
        raise Refusal("the library contains duplicate or malformed IDs")
    for row in assets:
        if not isinstance(row, dict):
            raise Refusal("malformed SFX map row")
        sfx_id = row.get("sfx_id")
        rel = row.get("canonical_library_entry_path")
        stat = row.get("stat") or {}
        if (not isinstance(sfx_id, str) or not isinstance(rel, str)
                or PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts
                or not rel.endswith(".wav") or stat.get("exists") is not True
                or isinstance(stat.get("bytes"), bool) or not isinstance(stat.get("bytes"), int)
                or stat["bytes"] <= 0):
            raise Refusal(f"invalid source path/size for selected SFX ID {sfx_id}")
        librow = by_id.get(sfx_id)
        if not isinstance(librow, dict) or librow.get("path") != rel:
            raise Refusal(f"sound library path does not match the pinned asset map for {sfx_id}")
        recorded_sha = row.get("catalogue_sha256")
        if recorded_sha is not None and (not isinstance(recorded_sha, str) or not SHA_RE.fullmatch(recorded_sha)):
            raise Refusal(f"invalid recorded library SHA-256 for {sfx_id}")
        if recorded_sha and librow.get("sha256") != recorded_sha:
            raise Refusal(f"asset-map/library recorded SHA-256 mismatch for {sfx_id}")
        if row.get("license_claim") != librow.get("license"):
            raise Refusal(f"asset-map/library licence claim mismatch for {sfx_id}")
    return sorted(assets, key=lambda row: row["sfx_id"])


def parse_tree_listing(output: str) -> dict[str, dict]:
    """Parse `git ls-tree -r -l` without reading blob contents."""
    found: dict[str, dict] = {}
    for line in output.splitlines():
        if not line:
            continue
        try:
            metadata, path = line.split("\t", 1)
            mode, kind, blob, size = metadata.split()
            size_value = int(size)
        except (ValueError, TypeError) as exc:
            raise Refusal("private SFX Git tree listing is malformed") from exc
        if path in found:
            raise Refusal("private SFX Git tree contains a duplicate path")
        if mode != "100644" or kind != "blob" or not GIT_BLOB_RE.fullmatch(blob) or size_value < 1:
            raise Refusal("private SFX tree contains a non-regular asset or invalid blob metadata")
        found[path] = {"git_blob_sha1": blob, "bytes": size_value}
    return found


def validate_tree(asset_rows: list[dict], tree: dict[str, dict]) -> list[dict]:
    expected: dict[str, dict] = {}
    for row in asset_rows:
        path = "source-inputs/S90/" + row["canonical_library_entry_path"]
        if path in expected:
            raise Refusal("two selected SFX IDs map to the same private source path")
        expected[path] = row
    if set(tree) != set(expected):
        missing = sorted(set(expected) - set(tree))
        extra = sorted(set(tree) - set(expected))
        raise Refusal(f"private S90 asset subtree must contain exactly the 16 selected files (missing={missing}; extra={extra})")
    verified = []
    for path, row in expected.items():
        native = tree[path]
        if native["bytes"] != row["stat"]["bytes"]:
            raise Refusal(f"private Git tree byte count differs from the recorded source stat for {row['sfx_id']}")
        if row.get("private_source_path") != path or row.get("private_source_git_blob_sha1") != native["git_blob_sha1"]:
            raise Refusal(f"private Git blob/path differs from the root-authenticated SFX manifest for {row['sfx_id']}")
        verified.append({**row, "private_path": path, **native})
    return sorted(verified, key=lambda row: row["sfx_id"])


def verify_checkout(private_root: Path, commit: str, expected_assets: list[dict]) -> dict[str, dict]:
    if commit != PRIVATE_COMMIT:
        raise Refusal("private SFX commit differs from the reviewed immutable commit")
    def git(*args: str) -> str:
        try:
            return subprocess.run(["git", "-C", str(private_root), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise Refusal("private SFX Git metadata verification failed") from exc
    if git("rev-parse", "HEAD") != PRIVATE_COMMIT:
        raise Refusal("private SFX checkout HEAD differs from the reviewed commit")
    origin = git("remote", "get-url", "origin")
    if origin not in (f"git@github.com:{PRIVATE_REPOSITORY}.git", f"https://github.com/{PRIVATE_REPOSITORY}.git"):
        raise Refusal("private checkout origin does not match the reviewed repository")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise Refusal("private SFX checkout has tracked modifications")
    try:
        listing = subprocess.run(["git", "-C", str(private_root), "ls-tree", "-r", "-l",
                                  "--full-tree", PRIVATE_COMMIT, "--", "source-inputs/S90/library"],
                                 check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Refusal("cannot read the pinned private SFX Git tree") from exc
    tree = parse_tree_listing(listing)
    return {row["private_path"]: row for row in validate_tree(expected_assets, tree)}


def stage_assets(*, verified: dict[str, dict], private_root: Path,
                 library_root: Path, output_receipt: Path) -> dict:
    if output_receipt.exists():
        raise Refusal("refusing to overwrite an existing SFX verification receipt")
    library_path = library_root / "library.json"
    library_path.parent.mkdir(parents=True, exist_ok=True)
    if not library_path.is_file() or sha256_file(library_path) != LIBRARY_SHA256:
        raise Refusal("hosted staged sound library JSON is missing or changed")
    staged: list[tuple[Path, Path, dict]] = []
    temp_root = library_root.parent / ".s90-sfx-verify"
    if temp_root.exists():
        raise Refusal("refusing to reuse an existing SFX verification staging directory")
    temp_root.mkdir(parents=True)
    try:
        for private_path, row in sorted(verified.items()):
            src = private_root / private_path
            if src.is_symlink() or not src.is_file():
                raise Refusal(f"selected SFX source is absent or not a regular file: {row['sfx_id']}")
            target_rel = PurePosixPath(row["canonical_library_entry_path"])
            if target_rel.is_absolute() or ".." in target_rel.parts:
                raise Refusal("SFX library path traversal refused")
            git_blob = subprocess.run(["git", "-C", str(private_root), "hash-object", str(src)],
                                      check=True, capture_output=True, text=True).stdout.strip()
            if git_blob != row["git_blob_sha1"]:
                raise Refusal(f"private SFX file differs from its pinned native Git blob: {row['sfx_id']}")
            size = src.stat().st_size
            if size != row["bytes"]:
                raise Refusal(f"private SFX file differs from its native Git tree size: {row['sfx_id']}")
            actual_sha = sha256_file(src)
            expected_sha = row.get("catalogue_sha256")
            if expected_sha is not None and actual_sha != expected_sha:
                raise Refusal(f"private SFX file differs from the sound-library recorded digest: {row['sfx_id']}")
            copy = temp_root / target_rel.name
            shutil.copyfile(src, copy)
            if copy.stat().st_size != size or sha256_file(copy) != actual_sha:
                raise Refusal(f"hosted SFX temporary copy changed during staging: {row['sfx_id']}")
            staged.append((copy, library_root / Path(*target_rel.parts), {**row, "sha256_ubuntu": actual_sha}))
        created: list[Path] = []
        try:
            for source, target, row in staged:
                if target.exists() or target.is_symlink():
                    raise Refusal(f"refusing to overwrite an existing mixer input for {row['sfx_id']}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open("rb") as inp, target.open("xb") as out:
                    shutil.copyfileobj(inp, out)
                created.append(target)
                if target.stat().st_size != row["bytes"] or sha256_file(target) != row["sha256_ubuntu"]:
                    raise Refusal(f"staged mixer input failed its post-copy SHA/size check: {row['sfx_id']}")
        except Exception:
            for target in reversed(created):
                if target.is_file() and not target.is_symlink():
                    target.unlink()
            raise
        receipt = {
            "kind": "s90_hosted_private_sfx_input_verification_v1",
            "repository": PRIVATE_REPOSITORY,
            "private_commit": PRIVATE_COMMIT,
            "asset_map_sha256": SFX_MAP_SHA256,
            "root_native_manifest_sha256": ROOT_PRIVATE_MANIFEST_SHA256,
            "library_sha256": LIBRARY_SHA256,
            "mix_spec_sha256": MIX_SHA256,
            "asset_count": len(staged),
            "cue_count": 19,
            "bytes_total": sum(row["bytes"] for _, _, row in staged),
            "sfx": [{"sfx_id": row["sfx_id"], "private_path": row["private_path"],
                     "library_path": row["canonical_library_entry_path"], "bytes": row["bytes"],
                     "git_blob_sha1": row["git_blob_sha1"], "sha256_ubuntu": row["sha256_ubuntu"],
                     "license_claim": row["license_claim"], "license_evidence_status": row.get("license_evidence_status"),
                     "distribution_status": row.get("distribution_status")} for _, _, row in staged],
            "verification": {"host": "GitHub Actions Ubuntu", "private_checkout_commit_verified": True,
                             "native_git_blob_and_size_verified": True, "ubuntu_sha256_verified": True,
                             "copied_only_selected_16": True, "raw_sfx_published": False,
                             "sound_licence_clearance": "OPEN", "mix_audition": "OPEN",
                             "final_av_approval": "OPEN"},
        }
        output_receipt.parent.mkdir(parents=True, exist_ok=True)
        with output_receipt.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
        return receipt
    except Exception:
        # Preserve source checkout; remove only files this helper created.
        for target in reversed(locals().get("created", [])):
            if target.is_file() and not target.is_symlink():
                target.unlink()
        raise
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("--asset-map", "--mix-spec", "--library", "--private-root", "--private-commit", "--library-root", "--receipt"):
        parser.add_argument(name, type=Path if name != "--private-commit" else str, required=True)
    args = parser.parse_args()
    try:
        require_hosted_linux()
        if sha256_file(args.asset_map) != SFX_MAP_SHA256:
            raise Refusal("S90 selected SFX map hash differs from the reviewed text inventory")
        if sha256_file(args.mix_spec) != MIX_SHA256:
            raise Refusal("S90 mix plan hash differs from the reviewed 19-cue candidate")
        if sha256_file(args.library) != LIBRARY_SHA256:
            raise Refusal("S90 sound-library text hash differs from the reviewed library")
        asset_map, mix, library = (read_json(path, label) for path, label in (
            (args.asset_map, "SFX asset map"), (args.mix_spec, "S90 mix spec"), (args.library, "sound library")))
        rows = validate_inputs(asset_map, mix, library)
        if (asset_map.get("cue_count") != 19 or asset_map.get("distinct_asset_count") != 16
                or mix.get("candidate_binding", {}).get("sound_library_sha256_text_only") != LIBRARY_SHA256):
            raise Refusal("S90 mix/map/library identity mismatch")
        tree = verify_checkout(args.private_root, args.private_commit, rows)
        receipt = stage_assets(verified=tree, private_root=args.private_root,
                               library_root=args.library_root, output_receipt=args.receipt)
        print(json.dumps({"status": "HOSTED_PRIVATE_SFX_INPUTS_VERIFIED; licensing/AV approval OPEN",
                          "private_commit": PRIVATE_COMMIT, "asset_count": receipt["asset_count"],
                          "cue_count": receipt["cue_count"], "bytes_total": receipt["bytes_total"],
                          "sha256_computed_on": "GitHub Actions Ubuntu"}, sort_keys=True))
    except (OSError, Refusal, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"S90 private SFX staging refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
