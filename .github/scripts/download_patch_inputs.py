#!/usr/bin/env python3
"""Download the exact selected segment archives and sealed source audio."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import patch_master_segments as patcher


HEAD_SHA_RE = re.compile(r"[0-9a-f]{40}")
API_DIGEST_RE = re.compile(r"sha256:([0-9a-f]{64})")
AUDIO_MEMBERS = {"audio/mix.flac", "./audio/mix.flac"}


def run(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command[:6])}\n"
            f"{completed.stderr[-4000:]}"
        )
    return completed.stdout


def run_to_file(command: list[str], output: Path) -> None:
    with output.open("wb") as handle:
        completed = subprocess.run(command, check=False, stdout=handle, stderr=subprocess.PIPE)
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"binary command failed ({completed.returncode}): {' '.join(command[:6])}\n{detail}")


def api_json(gh: str, endpoint: str) -> Any:
    return json.loads(run([gh, "api", endpoint]))


def require_empty_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise ValueError(f"download destination must start empty: {path}")


def repository_metadata(gh: str, repository: str) -> dict[str, Any]:
    raw = api_json(gh, f"repos/{repository}")
    if raw.get("full_name") != repository or not isinstance(raw.get("id"), int):
        raise ValueError(f"GitHub API returned a different repository: {raw.get('full_name')!r}")
    return {"full_name": repository, "id": raw["id"]}


def run_metadata(gh: str, repository: str, repository_id: int, run_id: str,
                 *, require_success: bool) -> dict[str, Any]:
    raw = api_json(gh, f"repos/{repository}/actions/runs/{run_id}")
    observed_id = str(raw.get("id", ""))
    head_sha = str(raw.get("head_sha", ""))
    head_repository = raw.get("head_repository") or {}
    conclusion_ok = (raw.get("conclusion") == "success" if require_success
                     else raw.get("conclusion") in {"success", "failure"})
    if (observed_id != run_id or raw.get("status") != "completed" or not conclusion_ok
            or not HEAD_SHA_RE.fullmatch(head_sha)
            or head_repository.get("full_name") != repository
            or head_repository.get("id") != repository_id):
        raise ValueError(f"source run identity/status is not accepted: requested={run_id}, observed={raw}")
    return {
        "run_id": observed_id,
        "status": raw["status"],
        "conclusion": raw["conclusion"],
        "head_sha": head_sha,
        "head_repository": repository,
        "head_repository_id": repository_id,
        "html_url": raw.get("html_url"),
        "workflow_id": raw.get("workflow_id"),
        "event": raw.get("event"),
    }


def artifact_metadata(gh: str, repository: str, repository_id: int,
                      run_row: dict[str, Any], artifact_name: str) -> dict[str, Any]:
    pages = json.loads(run([
        gh, "api", "--paginate", "--slurp",
        f"repos/{repository}/actions/runs/{run_row['run_id']}/artifacts?per_page=100",
    ]))
    if not isinstance(pages, list) or any(not isinstance(page, dict) for page in pages):
        raise ValueError("Actions artifacts response is malformed")
    artifacts = [artifact for page in pages for artifact in page.get("artifacts", [])]
    if any(not isinstance(artifact, dict) for artifact in artifacts):
        raise ValueError("Actions artifacts response contains a malformed row")
    matches = [row for row in artifacts if row.get("name") == artifact_name]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one artifact named {artifact_name!r}; observed {len(matches)}")
    artifact = matches[0]
    workflow_run = artifact.get("workflow_run") or {}
    digest_match = API_DIGEST_RE.fullmatch(str(artifact.get("digest", "")))
    if (not isinstance(artifact.get("id"), int) or artifact.get("expired") is not False
            or not isinstance(artifact.get("size_in_bytes"), int)
            or artifact["size_in_bytes"] <= 0
            or str(workflow_run.get("id")) != run_row["run_id"]
            or workflow_run.get("head_sha") != run_row["head_sha"]
            or workflow_run.get("repository_id") != repository_id
            or workflow_run.get("head_repository_id") != repository_id
            or not digest_match):
        raise ValueError(f"artifact metadata is not bound to the exact run/repository/digest: {artifact}")
    return {
        "id": artifact["id"],
        "name": artifact_name,
        "run_id": run_row["run_id"],
        "run_head_sha": run_row["head_sha"],
        "archive_sha256": digest_match.group(1),
        "size_in_bytes": artifact.get("size_in_bytes"),
        "created_at": artifact.get("created_at"),
    }


def _safe_zip_name(name: str) -> bool:
    pure = PurePosixPath(name)
    return bool(name) and not pure.is_absolute() and ".." not in pure.parts and "\\" not in name


def download_artifact(gh: str, repository: str, metadata: dict[str, Any],
                      expected: set[str], allowed: set[str], destination: Path) -> list[Path]:
    with tempfile.TemporaryDirectory(prefix="agmm-patch-artifact-") as temporary:
        archive = Path(temporary) / "artifact.zip"
        run_to_file([gh, "api", f"repos/{repository}/actions/artifacts/{metadata['id']}/zip"], archive)
        archive_hash = patcher.sha256(archive)
        if (archive_hash != metadata["archive_sha256"]
                or archive.stat().st_size != metadata["size_in_bytes"]):
            raise ValueError(f"artifact archive digest/size mismatch for {metadata['name']}")
        with zipfile.ZipFile(archive) as zf:
            members = zf.infolist()
            names = [member.filename for member in members]
            if (len(names) != len(set(names)) or any(member.is_dir() for member in members)
                    or any(stat.S_ISLNK(member.external_attr >> 16) for member in members)
                    or any(not _safe_zip_name(name) for name in names)
                    or any(member.file_size <= 0 or member.file_size > 20_000_000_000 for member in members)
                    or sum(member.file_size for member in members) > 30_000_000_000):
                raise ValueError(f"artifact {metadata['name']} contains unsafe or duplicate members")
            if not expected.issubset(names) or not set(names).issubset(allowed):
                raise ValueError(
                    f"artifact {metadata['name']} member mismatch: expected={sorted(expected)}, observed={sorted(names)}"
                )
            copied = []
            for member in members:
                if member.filename not in expected:
                    continue
                target = destination / member.filename
                if target.exists():
                    raise ValueError(f"artifact would overwrite an existing exact input: {target}")
                with zf.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                copied.append(target)
    return sorted(copied)


def release_asset_metadata(gh: str, repository: str, release_tag: str,
                           asset_name: str, expected_sha256: str) -> dict[str, Any]:
    release = api_json(gh, f"repos/{repository}/releases/tags/{release_tag}")
    if (release.get("tag_name") != release_tag or release.get("draft") is not False
            or release.get("prerelease") is not False or not isinstance(release.get("id"), int)):
        raise ValueError("source-audio release is not the exact published release")
    pages = json.loads(run([
        gh, "api", "--paginate", "--slurp",
        f"repos/{repository}/releases/{release['id']}/assets?per_page=100",
    ]))
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ValueError("release assets response is malformed")
    assets = [asset for page in pages for asset in page]
    matches = [asset for asset in assets if asset.get("name") == asset_name]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one release asset named {asset_name!r}")
    asset = matches[0]
    digest_match = API_DIGEST_RE.fullmatch(str(asset.get("digest", "")))
    if (not isinstance(asset.get("id"), int) or not digest_match
            or not isinstance(asset.get("size"), int) or asset["size"] <= 0
            or digest_match.group(1) != expected_sha256 or asset.get("state") != "uploaded"):
        raise ValueError("release asset metadata does not match the declared exact digest/state")
    return {
        "release": release_tag,
        "release_id": release["id"],
        "asset": asset_name,
        "asset_id": asset["id"],
        "asset_sha256": expected_sha256,
        "asset_bytes": asset.get("size"),
        "published_at": release.get("published_at"),
    }


def download_source_audio(gh: str, repository: str, metadata: dict[str, Any],
                          destination: Path, film_id: str) -> tuple[Path, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="agmm-patch-source-") as temporary:
        archive = Path(temporary) / metadata["asset"]
        run_to_file([
            gh, "api", "-H", "Accept: application/octet-stream",
            f"repos/{repository}/releases/assets/{metadata['asset_id']}",
        ], archive)
        if (patcher.sha256(archive) != metadata["asset_sha256"]
                or archive.stat().st_size != metadata["asset_bytes"]):
            raise ValueError("downloaded source archive digest/size differs from the release asset metadata")
        with tarfile.open(archive, "r:gz") as tf:
            matches = [member for member in tf.getmembers() if member.name in AUDIO_MEMBERS]
            if len(matches) != 1:
                raise ValueError(f"source archive must contain exactly one accepted audio member; observed {len(matches)}")
            member = matches[0]
            if not member.isfile() or member.size <= 0 or member.size > 2_000_000_000:
                raise ValueError("source audio member is not a bounded regular file")
            source = tf.extractfile(member)
            if source is None:
                raise ValueError("source audio member is unreadable")
            target = destination / f"{film_id}-SOURCE-MIX.flac"
            with target.open("wb") as output:
                shutil.copyfileobj(source, output)
    details = {**metadata, "member": member.name, "member_bytes": target.stat().st_size,
               "member_sha256": patcher.sha256(target)}
    return target, details


def file_rows(paths: list[Path], *, role: str, segment_id: str | None,
              run_id: str | None, artifact: str) -> list[dict[str, Any]]:
    return [{
        "role": role,
        "segment_id": segment_id,
        "run_id": run_id,
        "artifact": artifact,
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": patcher.sha256(path),
    } for path in paths]


def download_all(*, request_path: Path, repository: str, base_segments_dir: Path,
                 patch_segments_dir: Path, source_audio_dir: Path,
                 provenance_out: Path, gh: str) -> dict[str, Any]:
    request = patcher.load_request(request_path)
    if repository != request["repository"]:
        raise ValueError("workflow repository differs from the exact repository in the request")
    for destination in (base_segments_dir, patch_segments_dir, source_audio_dir):
        require_empty_directory(destination)

    repository_row = repository_metadata(gh, repository)
    patch_run_ids = {row["run_id"] for row in request["patches"]}
    run_ids = sorted({request["base"]["run_id"]} | patch_run_ids, key=int)
    runs = [run_metadata(gh, repository, repository_row["id"], run_id,
                         require_success=run_id in patch_run_ids) for run_id in run_ids]
    runs_by_id = {row["run_id"]: row for row in runs}
    patches = {row["i"]: row for row in request["patches"]}
    files: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    for segment in request["segments"]:
        sid = segment["i"]
        patch = patches.get(sid)
        run_id = patch["run_id"] if patch else request["base"]["run_id"]
        artifact_name = patch["artifact"] if patch else f"{request['base']['tag']}-SEG{sid}"
        role = "patch_segment" if patch else "base_segment"
        destination = patch_segments_dir if patch else base_segments_dir
        metadata = artifact_metadata(
            gh, repository, repository_row["id"], runs_by_id[run_id], artifact_name)
        expected = {f"SEG{sid}.mp4", f"SEG{sid}.verify.json"}
        allowed = expected | {f"SEG{sid}.render.log"}
        copied = download_artifact(gh, repository, metadata, expected, allowed, destination)
        artifacts.append({**metadata, "segment_id": sid, "role": role,
                          "members": sorted(path.name for path in copied)})
        files.extend(file_rows(copied, role=role, segment_id=sid,
                               run_id=run_id, artifact=artifact_name))

    source_request = request["source_audio"]
    source_metadata = release_asset_metadata(
        gh, repository, source_request["release"], source_request["asset"],
        source_request["sha256"])
    audio_path, source_audio = download_source_audio(
        gh, repository, source_metadata, source_audio_dir, request["film_id"])
    files.extend(file_rows([audio_path], role="source_audio", segment_id=None,
                           run_id=None, artifact=source_request["asset"]))

    if len(artifacts) != len(request["segments"]):
        raise ValueError("selected artifact count does not equal the complete segment manifest")
    provenance: dict[str, Any] = {
        "schema": 2,
        "kind": "hosted_master_patch_download_provenance",
        "request_sha256": request["request_sha256"],
        "repository": repository_row,
        "runs": runs,
        "artifacts": sorted(artifacts, key=lambda row: row["segment_id"]),
        "source_audio": source_audio,
        "files": sorted(files, key=lambda row: (row["role"], row["segment_id"] or "", row["filename"])),
    }
    provenance["provenance_sha256"] = patcher.sha256_bytes(patcher.canonical_bytes(provenance))
    provenance_out.write_text(json.dumps(provenance, indent=2) + "\n")
    return provenance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base-segments-dir", required=True, type=Path)
    parser.add_argument("--patch-segments-dir", required=True, type=Path)
    parser.add_argument("--source-audio-dir", required=True, type=Path)
    parser.add_argument("--provenance-out", required=True, type=Path)
    parser.add_argument("--gh", default="gh")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = download_all(
        request_path=args.request, repository=args.repository,
        base_segments_dir=args.base_segments_dir, patch_segments_dir=args.patch_segments_dir,
        source_audio_dir=args.source_audio_dir,
        provenance_out=args.provenance_out, gh=args.gh,
    )
    print(json.dumps({"status": "PASS", "runs": len(result["runs"]),
                      "artifacts": len(result["artifacts"]), "files": len(result["files"]),
                      "provenance_sha256": result["provenance_sha256"]}))


if __name__ == "__main__":
    main()
