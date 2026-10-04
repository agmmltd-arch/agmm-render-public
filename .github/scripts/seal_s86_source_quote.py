#!/usr/bin/env python3
"""Hosted-only one-field S86-B source reseal; no provider or render calls."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
from typing import Mapping

REPOSITORY = "agmmltd-arch/agmm-render-public"
PARENT_RELEASE = "S86-r2-source-202610010547"
PARENT_SHA256 = "c8fa6aea8bc904de1183ef648188de4d7ec2ab0d432be623f6b165fd7ac4408b"
PARENT_BYTES = 9_830_053
PARENT_ASSET_ID = 602456631
PARTS_SHA256 = "1585e81e26e654aabc04ebe0f851a81f0cd13962069027557f1e29db2dadc02d"
PARTS_BYTES = 617
PARTS_ASSET_ID = 602456630
MIX_SHA256 = "0c252cdf6e412fc2ccadcdb29b940d6a23b7c527276ebf79da468b7f633df436"
MIX_BYTES = 17_452_902
MIX_ASSET_ID = 602456632
OLD_B_SHA256 = "4bff6e6d723f23f481c552abcc6c3b052acc6061117a6a2497ca4bafac7772c2"
NEW_B_SHA256 = "bec37316e3a6fb670b4efa1b60713613144bcd2a54aac81e652de5eeb37d340d"
ACD_SHA256 = "48efe5272944b5d44d922b4d4e52e1acde0dc0f7c49d7c2ba485004a711766a7"
OWNER_SPEC_SHA256 = "ee9d43e526baf0a83cef45dbda1df4608255348749c0f6732db653a8840a37e0"
OLD_FIELD = b'"cropLeft": 215.0'
NEW_FIELD = b'"cropLeft": 13.3'
MAX_MEMBERS = 8192
MAX_TOTAL_BYTES = 1024**3


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_hosted_linux(env: Mapping[str, str], system: str) -> None:
    """Call before opening any input path or archive."""
    if system != "Linux" or env.get("RUNNER_OS") != "Linux" or env.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("S86-B source sealing is hosted-Linux-only; refusing all archive I/O.")
    if env.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise RuntimeError("Unexpected repository; refusing release and archive access.")


def check_repository(metadata: Mapping[str, object]) -> None:
    if metadata != {"full_name": REPOSITORY, "private": False, "visibility": "public"}:
        raise ValueError("Expected the public agmm-render-public repository.")


def check_parent_release(metadata: Mapping[str, object]) -> None:
    expected = {
        PARENT_ASSET_ID: ("source.tar.gz", PARENT_BYTES, f"sha256:{PARENT_SHA256}"),
        PARTS_ASSET_ID: ("parts.json", PARTS_BYTES, f"sha256:{PARTS_SHA256}"),
        MIX_ASSET_ID: ("mix.wav", MIX_BYTES, f"sha256:{MIX_SHA256}"),
    }
    if metadata.get("tag_name") != PARENT_RELEASE:
        raise ValueError("Unexpected immutable parent release.")
    rows = metadata.get("assets")
    if not isinstance(rows, list):
        raise ValueError("Parent release asset metadata is missing.")
    actual = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed release asset metadata.")
        asset_id = row.get("id")
        if asset_id in actual:
            raise ValueError("Duplicate parent release asset ID.")
        if asset_id in expected:
            actual[asset_id] = (row.get("name"), row.get("size"), row.get("digest"), row.get("state"))
    want = {i: (*v, "uploaded") for i, v in expected.items()}
    if actual != want:
        raise ValueError("Pinned S86 parent asset metadata does not match the recorded receipt.")


def safe_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    seen: set[str] = set()
    total = 0
    entries = archive.getmembers()
    if len(entries) > MAX_MEMBERS:
        raise ValueError("Source archive member limit exceeded.")
    for member in entries:
        raw = member.name
        if "\\" in raw:
            raise ValueError(f"Unsafe archive path spelling: {raw!r}")
        path = PurePosixPath(raw)
        normalized = str(path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe archive path: {raw!r}")
        if normalized in seen:
            raise ValueError(f"Duplicate normalized archive path: {normalized}")
        seen.add(normalized)
        if normalized == "." and member.isdir() and raw in (".", "./"):
            members[normalized] = member
            continue
        if normalized in ("", "."):
            raise ValueError(f"Unsafe archive path: {raw!r}")
        if not (member.isfile() or member.isdir()):
            raise ValueError(f"Non-regular archive entry refused: {normalized}")
        if member.isfile():
            total += member.size
            if member.size < 0 or total > MAX_TOTAL_BYTES:
                raise ValueError("Source archive expanded-size limit exceeded.")
        members[normalized] = member
    return members


def _read_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"Cannot read regular member {member.name!r}.")
    data = stream.read(member.size + 1)
    if len(data) != member.size:
        raise ValueError(f"Member size mismatch: {member.name!r}.")
    return data


def _checksum_patch(data: bytes, old_sha: str, new_sha: str) -> bytes:
    lines = data.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if re.search(rb"  \./spec\.js(?:\r?\n)?$", line)]
    if len(matches) != 1:
        raise ValueError("B checksum manifest must contain exactly one ./spec.js row.")
    index = matches[0]
    if not lines[index].startswith(old_sha.encode("ascii") + b"  ./spec.js"):
        raise ValueError("B checksum manifest does not bind the authenticated parent spec.js.")
    lines[index] = lines[index].replace(old_sha.encode("ascii"), new_sha.encode("ascii"), 1)
    return b"".join(lines)


def _rebind_parts(
    data: bytes,
    *,
    parent_sha256: str,
    parent_bytes: int,
    sealed_sha256: str,
    sealed_bytes: int,
) -> tuple[bytes, str]:
    """Rebind only the package identity fields; preserve all timeline/frame values."""
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Parent parts.json is not valid UTF-8 JSON.") from exc
    if not isinstance(value, dict) or not isinstance(value.get("parts"), list):
        raise ValueError("Parent parts.json must contain a top-level parts array.")
    if value.get("sha256") != parent_sha256 or value.get("bytes") != parent_bytes:
        raise ValueError("Parent parts.json does not bind the authenticated parent source bytes.")
    semantic = {key: item for key, item in value.items() if key not in {"sha256", "bytes"}}
    timeline_digest = sha(json.dumps(semantic, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8"))
    rebound = dict(value)
    rebound["sha256"] = sealed_sha256
    rebound["bytes"] = sealed_bytes
    preserved = {key: item for key, item in rebound.items() if key not in {"sha256", "bytes"}}
    if preserved != semantic:
        raise ValueError("Rebinding changed part timeline or frame values.")
    return (json.dumps(rebound, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), timeline_digest


def seal_archive_bytes(
    archive_bytes: bytes,
    parts_bytes: bytes,
    mix_bytes: bytes,
    *,
    env: Mapping[str, str],
    system: str,
    contract: Mapping[str, object] | None = None,
) -> tuple[bytes, bytes, dict[str, object]]:
    """Authenticate inputs, patch B, rebind parts.json, and return sealed bytes plus receipt."""
    require_hosted_linux(env, system)
    c = dict(contract or {})
    expected_parent = str(c.get("parent_sha256", PARENT_SHA256))
    expected_parent_bytes = int(c.get("parent_bytes", PARENT_BYTES))
    expected_parts = str(c.get("parts_sha256", PARTS_SHA256))
    expected_mix = str(c.get("mix_sha256", MIX_SHA256))
    old_b = str(c.get("old_b_sha256", OLD_B_SHA256))
    new_b = str(c.get("new_b_sha256", NEW_B_SHA256))
    acd = str(c.get("acd_sha256", ACD_SHA256))
    if len(archive_bytes) != expected_parent_bytes or sha(archive_bytes) != expected_parent:
        raise ValueError("Parent source archive byte count or SHA-256 mismatch.")
    if sha(parts_bytes) != expected_parts or sha(mix_bytes) != expected_mix:
        raise ValueError("Original parts.json or mix.wav SHA-256 mismatch.")
    try:
        parent_parts = json.loads(parts_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Parent parts.json is not valid UTF-8 JSON.") from exc
    if not isinstance(parent_parts, dict) or parent_parts.get("sha256") != expected_parent or parent_parts.get("bytes") != expected_parent_bytes:
        raise ValueError("Parent parts.json does not bind the authenticated parent source bytes.")

    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as parent:
        members = safe_members(parent)
        required = {f"s86-{part}/spec.js" for part in "abcd"}
        required |= {f"s86-{part}/SHA256SUMS.txt" for part in "abcd"}
        required |= {f"s86-{part}/static_check.py" for part in "abcd"}
        missing = sorted(required - members.keys())
        if missing:
            raise ValueError(f"Parent package is missing required part contract files: {missing}")
        before: dict[str, bytes] = {}
        for name, member in members.items():
            if member.isfile():
                before[name] = _read_member(parent, member)
        for part in "acd":
            if sha(before[f"s86-{part}/spec.js"]) != acd:
                raise ValueError(f"Authenticated {part.upper()} spec hash mismatch.")
        b_path = "s86-b/spec.js"
        b_data = before[b_path]
        if sha(b_data) != old_b or b_data.count(OLD_FIELD) != 1:
            raise ValueError("Authenticated B source or one-field crop precondition mismatch.")
        candidate = Path(".github/candidates/S86-source-quote/spec.js").read_bytes()
        branch = Path(".github/candidates/S86-source-quote/clip-quote-branch.txt").read_bytes()
        if sha(branch) != "5edae81941dcbba1225279cc45d49b6aba79d8f9f722387460dcd50cfc35d08b":
            raise ValueError("Source quotation handler identity mismatch")
        after_b = candidate
        scene_path = "s86-b/scenes.js"
        scene_before = before[scene_path]
        marker = b"  IT.clip = function (ctx, S, it, B) {\n"
        if scene_before.count(marker) != 1 or b"if (it.quoteText)" in scene_before:
            raise ValueError("Native source quotation handler insertion precondition failed")
        scene_after = scene_before.replace(marker, marker + branch, 1)
        # Preserve all semantic spec fields except the selected source presentation.
        def spec_json(data):
            text = data.decode("utf-8")
            return json.loads(text[text.index("{"):text.rindex("}")+1])
        parent_j, candidate_j = spec_json(b_data), spec_json(after_b)
        target = candidate_j["beats"][3]["props"]["items"][2]
        original = parent_j["beats"][3]["props"]["items"][2]
        if target.get("quoteText") != "Last year, Clearview AI was fined more than £7.5m by the Information Commissioner's Office (ICO) for unlawfully storing facial images.":
            raise ValueError("Exact verified BBC quotation changed")
        candidate_j["beats"][3]["props"]["items"][2] = original
        if candidate_j != parent_j:
            raise ValueError("Non-target story/spec changes refused")
        if sha(after_b) != new_b:
            raise ValueError("Proposed B source hash differs from reviewed exact patch.")
        b_sum_path = "s86-b/SHA256SUMS.txt"
        after_sums = _checksum_patch(before[b_sum_path], old_b, new_b)
        scene_row = sha(scene_before).encode() + b"  ./scenes.js"
        if after_sums.count(scene_row) != 1:
            raise ValueError("Native scene checksum row absent or ambiguous")
        after_sums = after_sums.replace(scene_row, sha(scene_after).encode() + b"  ./scenes.js", 1)

        with tempfile.TemporaryDirectory(prefix="s86-b-seal-") as temp_name:
            root = Path(temp_name)
            for name, member in members.items():
                if name == "." or member.isdir():
                    (root / name).mkdir(parents=True, exist_ok=True)
                else:
                    destination = root / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(after_b if name == b_path else after_sums if name == b_sum_path else scene_after if name == scene_path else before[name])
            for part in "abcd":
                result = subprocess.run(
                    [sys.executable, "static_check.py"],
                    cwd=root / f"s86-{part}", capture_output=True, text=True, check=False,
                )
                if result.returncode:
                    raise ValueError(f"Existing {part.upper()} static_check.py failed: {result.stderr[-500:]}")

        changed = {b_path, b_sum_path, scene_path}
        output_buffer = io.BytesIO()
        with tarfile.open(fileobj=output_buffer, mode="w:gz", format=tarfile.PAX_FORMAT) as sealed:
            for name, member in members.items():
                info = copy.copy(member)
                if member.isfile():
                    data = after_b if name == b_path else after_sums if name == b_sum_path else scene_after if name == scene_path else before[name]
                    info.size = len(data)
                    sealed.addfile(info, io.BytesIO(data))
                else:
                    sealed.addfile(info)
        new_archive = output_buffer.getvalue()
    with tarfile.open(fileobj=io.BytesIO(new_archive), mode="r:gz") as verify:
        sealed_members = safe_members(verify)
        after: dict[str, bytes] = {n: _read_member(verify, m) for n, m in sealed_members.items() if m.isfile()}
    if set(members) != set(sealed_members):
        raise ValueError("Resealed source archive member set changed.")
    if after[b_path] != after_b or after[b_sum_path] != after_sums:
        raise ValueError("Resealed B source or checksum manifest differs from reviewed patch.")
    for name in before:
        if name not in changed and before[name] != after[name]:
            raise ValueError(f"Unexpected source package member changed: {name}")
    sealed_source_sha = sha(new_archive)
    sealed_parts_bytes, parts_semantic_sha = _rebind_parts(
        parts_bytes,
        parent_sha256=expected_parent,
        parent_bytes=expected_parent_bytes,
        sealed_sha256=sealed_source_sha,
        sealed_bytes=len(new_archive),
    )
    if json.loads(sealed_parts_bytes).get("sha256") != sealed_source_sha or json.loads(sealed_parts_bytes).get("bytes") != len(new_archive):
        raise ValueError("Resealed parts.json does not bind the exact new source archive.")
    receipt = {
        "schema": "s86-b-hosted-source-seal-v1",
        "status": "SOURCE_SEALED_NOT_RENDERED_OR_APPROVED",
        "repository": REPOSITORY,
        "parent_release": PARENT_RELEASE,
        "parent_source_asset_id": PARENT_ASSET_ID,
        "parent_source_sha256": sha(archive_bytes),
        "parent_source_bytes": len(archive_bytes),
        "owner_spec_sha256": OWNER_SPEC_SHA256,
        "patch": {"path": b_path, "field": "verified source quotation presentation", "old": "native cropped strip", "new": "exact guarded quotation panel",
                  "old_sha256": old_b, "new_sha256": sha(after_b), "occurrences": 1},
        "checksum_manifest_path": b_sum_path,
        "unchanged_source_parts": {f"s86-{p}/spec.js": sha(after[f"s86-{p}/spec.js"]) for p in "acd"},
        "unchanged_other_archive_files": len(before) - 3,
        "scene_patch": {"path":scene_path,"before_sha256":sha(scene_before),"after_sha256":sha(scene_after),"handler_sha256":sha(branch)},
        "archive_member_count": len(members),
        "member_sha256_before": {name: sha(data) for name, data in sorted(before.items())},
        "member_sha256_after": {name: sha(data) for name, data in sorted(after.items())},
        "source_sha256": sealed_source_sha,
        "source_bytes": len(new_archive),
        "parent_parts_sha256": sha(parts_bytes),
        "sealed_parts_sha256": sha(sealed_parts_bytes),
        "parts_binding_before": {"sha256": expected_parent, "bytes": expected_parent_bytes},
        "parts_binding_after": {"sha256": sealed_source_sha, "bytes": len(new_archive)},
        "parts_timeline_frames_semantic_sha256": parts_semantic_sha,
        "parts_timeline_frames_preserved": True,
        "mix_sha256": sha(mix_bytes),
        "workflow_run_id": env.get("GITHUB_RUN_ID"),
        "workflow_commit": env.get("GITHUB_SHA"),
        "hosted_only": True,
        "release_approval": "NOT_GRANTED",
        "visual_review": "REQUIRED_AFTER_HOSTED_CAPTURE",
    }
    return new_archive, sealed_parts_bytes, receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    repo = sub.add_parser("check-repository")
    repo.add_argument("--metadata", type=Path, required=True)
    release = sub.add_parser("check-parent-release")
    release.add_argument("--metadata", type=Path, required=True)
    seal = sub.add_parser("seal")
    seal.add_argument("--source", type=Path, required=True)
    seal.add_argument("--parts", type=Path, required=True)
    seal.add_argument("--parts-output", type=Path, required=True)
    seal.add_argument("--mix", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)
    seal.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "check-repository":
        check_repository(json.loads(args.metadata.read_text(encoding="utf-8")))
        print("PASS: expected public repository confirmed.")
        return
    if args.command == "check-parent-release":
        check_parent_release(json.loads(args.metadata.read_text(encoding="utf-8")))
        print("PASS: immutable parent asset metadata confirmed.")
        return
    require_hosted_linux(os.environ, platform.system())
    output, parts_output, receipt = seal_archive_bytes(args.source.read_bytes(), args.parts.read_bytes(), args.mix.read_bytes(),
                                                       env=os.environ, system=platform.system())
    args.output.write_bytes(output)
    args.parts_output.write_bytes(parts_output)
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
