#!/usr/bin/env python3
"""Idempotent exact-package dispatcher for the public short render workflow.

This module never renders or decodes media.  It binds the approved storyboard,
sealed source archive, parts manifest and mix to one deterministic request ID,
then (only when explicitly enabled) creates/reuses a public release and invokes
the already-deployed GitHub Actions workflow.  Local state is written before a
workflow dispatch attempt so an interrupted tick cannot submit the same request
twice.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Optional


HERE = Path(__file__).resolve().parent
V2 = HERE.parent
DEFAULT_CONFIG = HERE / "short-cloud-dispatch.json"
DEFAULT_ADOPTIONS = HERE / "short-cloud-adoptions.json"
DEFAULT_REPOSITORY = "agmmltd-arch/agmm-render-public"
DEFAULT_WORKFLOW = "agmm-short-package.yml"
DEFAULT_REF = "main"
SID_RE = re.compile(r"^[SCP][0-9]{2,3}$")
ARCHIVE_RX = re.compile(r"(^|/)(_archive|archive|old-|r\d+/)|\.bak|\.r\d+-returned|-returned\.|scenes\.r\d")


class DispatchError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-%d" % os.getpid())
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DispatchError("%s is unreadable: %s" % (label, error)) from error
    if not isinstance(value, dict):
        raise DispatchError("%s must contain a JSON object" % label)
    return value


def _spec_hash(spec_dir: Path, *, skip_archives: bool) -> str:
    digest = hashlib.sha256()
    for path in sorted(spec_dir.rglob("*")):
        if not path.is_file() or path.suffix not in (".json", ".js", ".css", ".html", ".svg"):
            continue
        relative = path.relative_to(spec_dir).as_posix()
        if "receipt" in path.name or path.name.startswith("ref-watch"):
            continue
        if skip_archives and ARCHIVE_RX.search(relative):
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _clean_tar_name(name: str) -> str:
    while name.startswith("./"):
        name = name[2:]
    if not name:
        return "."
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise DispatchError("unsafe member in source.tar.gz: %r" % name)
    if any(part == "__MACOSX" or part.startswith("._") for part in path.parts):
        raise DispatchError("macOS metadata is forbidden in source.tar.gz: %r" % name)
    return path.as_posix()


def _validate_archive(source: Path, parts: list[dict]) -> int:
    names = set()
    try:
        with tarfile.open(source, "r:gz") as archive:
            members = archive.getmembers()
            if not members or len(members) > 10_000:
                raise DispatchError("source.tar.gz must contain 1..10000 members")
            expanded = 0
            for member in members:
                name = _clean_tar_name(member.name)
                if name in names:
                    raise DispatchError("duplicate source.tar.gz member: %s" % name)
                names.add(name)
                if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                    raise DispatchError("source.tar.gz contains a special member: %s" % name)
                if not (member.isfile() or member.isdir()):
                    raise DispatchError("source.tar.gz contains an unsupported member: %s" % name)
                if name == "." and not member.isdir():
                    raise DispatchError("source.tar.gz root marker must be a directory")
                expanded += member.size
                if expanded > 4_000_000_000:
                    raise DispatchError("source.tar.gz expands beyond 4 GB")
    except (OSError, tarfile.TarError) as error:
        raise DispatchError("source.tar.gz is unreadable: %s" % error) from error
    for part in parts:
        look = part["look"]
        for required in (part["file"], "SHA256SUMS.txt", "static_check.py"):
            member = "%s/%s" % (look, required)
            if member not in names:
                raise DispatchError("source.tar.gz is missing %s" % member)
    return len(members)


def _normalise_parts(sid: str, raw: dict, source_hash: str, source_bytes: int) -> tuple[list[dict], int]:
    if raw.get("sha256") != source_hash or raw.get("bytes") != source_bytes:
        raise DispatchError("parts.json is not bound to the exact source.tar.gz hash and byte count")
    rows = raw.get("parts")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise DispatchError("parts.json must contain 1..32 parts")
    clean = []
    prior = 0.0
    outputs = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise DispatchError("part %d is not an object" % index)
        look, source_file, output = row.get("look"), row.get("file"), row.get("out")
        for label, value in (("look", look), ("file", source_file), ("out", output)):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
                raise DispatchError("part %d %s is unsafe" % (index, label))
        if not output.startswith(sid + "-") or output in outputs:
            raise DispatchError("part %d output is not a unique %s part" % (index, sid))
        outputs.add(output)
        try:
            offset, duration = float(row.get("off")), float(row.get("dur"))
        except (TypeError, ValueError):
            raise DispatchError("part %d offset/duration is invalid" % index) from None
        if not math.isfinite(offset) or not math.isfinite(duration) or duration <= 0 or abs(offset - prior) > 1e-6:
            raise DispatchError("part %d is invalid or non-contiguous" % index)
        clean.append({"look": look, "file": source_file, "out": output, "off": offset, "dur": duration})
        prior = offset + duration
    frames = int(round(prior * 30))
    if raw.get("frames") != frames:
        raise DispatchError("parts.json frame total does not match its contiguous duration")
    return clean, frames


def exact_request(sid: str, *, root: Path = V2) -> dict:
    sid = sid.strip().upper()
    if not SID_RE.fullmatch(sid):
        raise DispatchError("invalid short ID: %r" % sid)
    kit = root / "kit"
    spec_dir = kit / "specs" / sid
    approval = _load_json(kit / "registry" / "storyboards" / (sid + ".json"), "storyboard approval")
    if approval.get("state") != "approved":
        raise DispatchError("%s storyboard is %r, not approved" % (sid, approval.get("state")))
    current_hash = _spec_hash(spec_dir, skip_archives=True)
    legacy_hash = _spec_hash(spec_dir, skip_archives=False)
    approved_hash = approval.get("approved_hash") or approval.get("spec_hash")
    if approved_hash not in (current_hash, legacy_hash):
        raise DispatchError("%s approved storyboard hash does not match the current spec" % sid)

    out = kit / "out" / sid
    source = out / "build" / "source.tar.gz"
    parts_path = out / "build" / "parts.json"
    mix = out / "audio" / "mix.wav"
    for path in (source, parts_path, mix):
        if not path.is_file():
            raise DispatchError("exact cloud input is missing: %s" % path)
    source_hash, parts_hash, mix_hash = sha256(source), sha256(parts_path), sha256(mix)
    raw_parts = _load_json(parts_path, "parts.json")
    parts, frames = _normalise_parts(sid, raw_parts, source_hash, source.stat().st_size)
    build = _load_json(out / "BUILD.json", "BUILD.json")
    if build.get("id") != sid or build.get("package_sha256") != source_hash or build.get("parts") != raw_parts["parts"]:
        raise DispatchError("BUILD.json is not bound to the exact short package")
    members = _validate_archive(source, parts)
    spec = _load_json(spec_dir / "spec.json", "spec.json")
    render_4k = bool((spec.get("render") or {}).get("res4k"))
    binding = {"source_sha256": source_hash, "parts_sha256": parts_hash, "mix_sha256": mix_hash}
    package_id = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    request_binding = {**binding, "approved_hash": approved_hash, "render_4k": render_4k, "workers": "2"}
    request_id = hashlib.sha256(
        json.dumps(request_binding, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    release = "short-%s-%s" % (sid.lower(), package_id)
    tag = "%s-%s" % (sid, request_id[:16])
    return {
        "kind": "agmm_short_cloud_dispatch_request",
        "schema": 1,
        "id": sid,
        "package_id": package_id,
        "request_id": request_id,
        "approval": {"state": "approved", "approved_hash": approved_hash, "current_hash": current_hash},
        "inputs": {
            "source": {"path": str(source), "sha256": source_hash, "bytes": source.stat().st_size},
            "parts": {"path": str(parts_path), "sha256": parts_hash, "bytes": parts_path.stat().st_size},
            "mix": {"path": str(mix), "sha256": mix_hash, "bytes": mix.stat().st_size},
        },
        "package": {"parts": len(parts), "frames": frames, "archive_members": members},
        "workflow_inputs": {
            "release": release,
            "source_sha256": source_hash,
            "parts_sha256": parts_hash,
            "mix_sha256": mix_hash,
            "tag": tag,
            "render_4k": render_4k,
            "workers": "2",
        },
        "editorial_status": "NOT_REVIEWED",
        "technical_status": "PENDING_HOSTED_RUN",
        "publication_status": "NOT_REQUESTED",
    }


def _default_runner(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True)


def _json_result(result: subprocess.CompletedProcess, label: str):
    if result.returncode:
        raise DispatchError("%s failed: %s" % (label, (result.stderr or result.stdout or "")[-500:]))
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise DispatchError("%s returned invalid JSON" % label) from error


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _find_run(runner, config: dict, title: str) -> dict | None:
    command = ["gh", "run", "list", "-R", config["repository"], "--workflow", config["workflow"],
               "--event", "workflow_dispatch", "--limit", "100", "--json",
               "databaseId,displayTitle,status,conclusion,url,createdAt,event"]
    rows = _json_result(runner(command), "workflow run lookup")
    matches = [row for row in rows if row.get("displayTitle") == title]
    if len(matches) > 1:
        raise DispatchError("multiple workflow runs exist for deterministic title %r" % title)
    return matches[0] if matches else None


def _release(runner, config: dict, request: dict) -> dict:
    repository, release = config["repository"], request["workflow_inputs"]["release"]
    api = "repos/%s/releases/tags/%s" % (repository, release)
    existing = runner(["gh", "api", api])
    paths = [request["inputs"][name]["path"] for name in ("source", "parts", "mix")]
    expected = {
        "source.tar.gz": request["inputs"]["source"],
        "parts.json": request["inputs"]["parts"],
        "mix.wav": request["inputs"]["mix"],
    }
    if existing.returncode == 0:
        release_json = _json_result(existing, "release lookup")
        if release_json.get("draft"):
            raise DispatchError("deterministic release exists as a draft")
        assets = {asset.get("name"): asset for asset in release_json.get("assets", [])}
        if set(assets) != set(expected):
            upload = runner(["gh", "release", "upload", release, *paths, "-R", repository, "--clobber"])
            if upload.returncode:
                raise DispatchError("release asset repair failed: %s" % (upload.stderr or upload.stdout or "")[-500:])
            return {"tag": release, "url": release_json.get("html_url"), "assets": "uploaded_exact", "mutated": True}
        exact = True
        for name, wanted in expected.items():
            asset = assets[name]
            digest = asset.get("digest")
            exact &= asset.get("size") == wanted["bytes"] and digest == "sha256:" + wanted["sha256"]
        if exact:
            return {"tag": release, "url": release_json.get("html_url"), "assets": "reused_verified", "mutated": False}
        upload = runner(["gh", "release", "upload", release, *paths, "-R", repository, "--clobber"])
        if upload.returncode:
            raise DispatchError("release asset replacement failed: %s" % (upload.stderr or upload.stdout or "")[-500:])
        return {"tag": release, "url": release_json.get("html_url"), "assets": "uploaded_exact", "mutated": True}
    missing = "HTTP 404" in (existing.stderr or "") or "release not found" in (existing.stderr or "").lower()
    if not missing:
        raise DispatchError("release lookup failed without a 404: %s" % (existing.stderr or existing.stdout or "")[-500:])
    notes = ("Exact AGMM short render input. Request %s. Editorial status NOT_REVIEWED; publication NOT_REQUESTED."
             % request["request_id"])
    create = runner(["gh", "release", "create", release, *paths, "-R", repository, "--target", config["ref"],
                     "--title", release, "--notes", notes, "--latest=false"])
    if create.returncode:
        raise DispatchError("release creation failed: %s" % (create.stderr or create.stdout or "")[-500:])
    return {"tag": release, "url": (create.stdout or "").strip() or None, "assets": "created_exact", "mutated": True}


def _config(path: Path) -> dict:
    value = _load_json(path, "short cloud dispatch config")
    config = {
        "enabled": value.get("enabled") is True,
        "repository": value.get("repository") or DEFAULT_REPOSITORY,
        "workflow": value.get("workflow") or DEFAULT_WORKFLOW,
        "ref": value.get("ref") or DEFAULT_REF,
        "workers": str(value.get("workers") or "2"),
    }
    if config["repository"] != DEFAULT_REPOSITORY or config["workflow"] != DEFAULT_WORKFLOW:
        raise DispatchError("short cloud dispatch must use the deployed public repository and workflow")
    if config["ref"] != DEFAULT_REF or config["workers"] != "2":
        raise DispatchError("short cloud dispatch ref/workers config is invalid")
    return config


def _adoptions(path: Path) -> dict:
    value = _load_json(path, "short cloud adoption map")
    if value.get("schema") != 1 or not isinstance(value.get("runs"), dict):
        raise DispatchError("short cloud adoption map has an invalid schema")
    return value


def _adoption_receipt(request: dict, *, root: Path, config: dict, entry: dict, runner) -> dict | None:
    """Bind one manually submitted run to the current exact package, without any remote mutation."""
    wanted_hashes = {key + "_sha256": request["workflow_inputs"][key + "_sha256"]
                     for key in ("source", "parts", "mix")}
    mapped_hashes = {key: entry.get(key) for key in wanted_hashes}
    if mapped_hashes != wanted_hashes:
        return None  # The package changed; this historical run does not cover the new exact inputs.
    if entry.get("repository") != config["repository"] or entry.get("workflow") != config["workflow"]:
        raise DispatchError("adopted run repository/workflow does not match the configured public route")
    if entry.get("head_branch") != config["ref"] or entry.get("render_4k") is not True:
        raise DispatchError("adopted run branch/render contract is invalid")
    if entry.get("workers") != "2" or not isinstance(entry.get("run_id"), int):
        raise DispatchError("adopted run worker/run identity is invalid")

    receipt_dir = root / "kit" / "out" / request["id"] / "cloud-dispatch" / request["request_id"]
    request_path, receipt_path = receipt_dir / "REQUEST.json", receipt_dir / "RECEIPT.json"
    if receipt_path.exists():
        receipt = _load_json(receipt_path, "cloud dispatch receipt")
        saved_request = _load_json(request_path, "cloud dispatch request")
        expected_workflow = {
            "repository": config["repository"], "path": entry["workflow_path"],
            "name": entry["workflow_name"], "head_branch": entry["head_branch"],
            "head_sha": entry["head_sha"], "event": "workflow_dispatch",
        }
        expected_invocation = {
            "release": entry["release"], "tag": entry["run_tag"],
            "render_4k": entry["render_4k"], "workers": entry["workers"],
        }
        expected_adoption = {
            "run_id": entry["run_id"], "release": entry["release"], "run_tag": entry["run_tag"],
            "render_4k": entry["render_4k"], "workers": entry["workers"],
        }
        expected_asset_evidence = {}
        for name, key in (("source.tar.gz", "source"), ("parts.json", "parts"), ("mix.wav", "mix")):
            item = request["inputs"][key]
            expected_asset_evidence[name] = {
                "bytes": item["bytes"], "sha256": item["sha256"],
                "digest": "sha256:" + item["sha256"], "state": "uploaded",
            }
        saved_identity = {key: saved_request.get(key) for key in ("id", "package_id", "request_id")}
        current_identity = {key: request[key] for key in ("id", "package_id", "request_id")}
        saved_inputs = saved_request.get("workflow_inputs") or {}
        receipt_run = receipt.get("run") or {}
        receipt_release = receipt.get("release") or {}
        if saved_identity != current_identity or saved_request.get("workflow") != request["workflow"] \
                or saved_request.get("adopted_existing") != expected_adoption \
                or {key: saved_inputs.get(key) for key in wanted_hashes} != wanted_hashes \
                or receipt.get("kind") != "agmm_short_cloud_dispatch_receipt" or receipt.get("schema") != 1 \
                or receipt.get("status") != "adopted_existing_run" \
                or receipt.get("id") != request["id"] or receipt.get("package_id") != request["package_id"] \
                or receipt.get("request_id") != request["request_id"] or receipt.get("binding") != wanted_hashes \
                or receipt.get("workflow") != expected_workflow \
                or receipt.get("manual_invocation") != expected_invocation \
                or receipt_run.get("id") != entry["run_id"] or receipt_run.get("url") != entry["run_url"] \
                or receipt_run.get("display_title") != "AGMM short " + entry["run_tag"] \
                or receipt_release.get("tag") != entry["release"] \
                or receipt_release.get("assets") != expected_asset_evidence \
                or receipt.get("editorial_status") != "NOT_REVIEWED" \
                or receipt.get("publication_status") != "NOT_REQUESTED":
            raise DispatchError("existing adopted receipt/request does not match the exact mapped run")
        return receipt

    run_fields = "databaseId,displayTitle,event,headBranch,headSha,status,conclusion,url,workflowName,createdAt,updatedAt"
    run = _json_result(runner(["gh", "run", "view", str(entry["run_id"]), "-R", config["repository"],
                               "--json", run_fields]), "adopted workflow run lookup")
    expected_run = {
        "databaseId": entry["run_id"],
        "displayTitle": "AGMM short " + entry["run_tag"],
        "event": "workflow_dispatch",
        "headBranch": entry["head_branch"],
        "headSha": entry["head_sha"],
        "url": entry["run_url"],
        "workflowName": entry["workflow_name"],
    }
    for key, expected in expected_run.items():
        if run.get(key) != expected:
            raise DispatchError("adopted run %s mismatch: expected %r, got %r" % (key, expected, run.get(key)))
    raw_run = _json_result(runner(["gh", "api", "repos/%s/actions/runs/%s" %
                                   (config["repository"], entry["run_id"])]), "adopted raw run lookup")
    if raw_run.get("path") != entry["workflow_path"] or raw_run.get("head_sha") != entry["head_sha"] \
            or raw_run.get("event") != "workflow_dispatch":
        raise DispatchError("adopted run raw workflow identity is invalid")

    release = _json_result(runner(["gh", "api", "repos/%s/releases/tags/%s" %
                                    (config["repository"], entry["release"])]), "adopted release lookup")
    if release.get("tag_name") != entry["release"] or release.get("draft") or release.get("target_commitish") != config["ref"]:
        raise DispatchError("adopted release identity is invalid")
    assets = {asset.get("name"): asset for asset in release.get("assets", [])}
    expected_assets = {
        "source.tar.gz": request["inputs"]["source"],
        "parts.json": request["inputs"]["parts"],
        "mix.wav": request["inputs"]["mix"],
    }
    if set(assets) != set(expected_assets):
        raise DispatchError("adopted release does not contain exactly the three short input assets")
    asset_evidence = {}
    for name, expected in expected_assets.items():
        asset = assets[name]
        if asset.get("state") != "uploaded" or asset.get("size") != expected["bytes"] \
                or asset.get("digest") != "sha256:" + expected["sha256"]:
            raise DispatchError("adopted release asset mismatch: %s" % name)
        asset_evidence[name] = {"bytes": asset["size"], "sha256": expected["sha256"],
                                "digest": asset["digest"], "state": asset["state"]}

    request_with_adoption = dict(request)
    request_with_adoption["adopted_existing"] = {
        "run_id": entry["run_id"], "release": entry["release"], "run_tag": entry["run_tag"],
        "render_4k": entry["render_4k"], "workers": entry["workers"],
    }
    receipt = {
        "kind": "agmm_short_cloud_dispatch_receipt",
        "schema": 1,
        "id": request["id"],
        "package_id": request["package_id"],
        "request_id": request["request_id"],
        "status": "adopted_existing_run",
        "adopted_at": _utc_now(),
        "binding": wanted_hashes,
        "workflow": {
            "repository": config["repository"], "path": entry["workflow_path"],
            "name": entry["workflow_name"], "head_branch": entry["head_branch"],
            "head_sha": entry["head_sha"], "event": "workflow_dispatch",
        },
        "manual_invocation": {
            "release": entry["release"], "tag": entry["run_tag"],
            "render_4k": entry["render_4k"], "workers": entry["workers"],
        },
        "release": {"tag": entry["release"], "url": release.get("html_url"), "assets": asset_evidence},
        "run": {
            "id": run["databaseId"], "display_title": run["displayTitle"], "url": run["url"],
            "status": run.get("status"), "conclusion": run.get("conclusion"),
            "created_at": run.get("createdAt"), "updated_at": run.get("updatedAt"),
        },
        "technical_status": "HOSTED_RUN_" + str(run.get("conclusion") or run.get("status") or "UNKNOWN").upper(),
        "editorial_status": "NOT_REVIEWED",
        "publication_status": "NOT_REQUESTED",
    }
    _atomic_json(request_path, request_with_adoption)
    _atomic_json(receipt_path, receipt)
    return receipt


def adopt_mapped(*, root: Path = V2, config_path: Path = DEFAULT_CONFIG,
                 adoptions_path: Optional[Path] = None, runner=None) -> list[dict]:
    """Verify and atomically record every current exact package in the manual-run adoption map."""
    runner = runner or _default_runner
    config = _config(config_path)
    adoptions_path = adoptions_path or (root / "crew" / DEFAULT_ADOPTIONS.name)
    mapping = _adoptions(adoptions_path)
    results = []
    lock_path = root / "crew" / "short-cloud-dispatch.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for sid in sorted(mapping["runs"]):
            request = exact_request(sid, root=root)
            request["workflow_inputs"]["workers"] = config["workers"]
            request["workflow"] = {key: config[key] for key in ("repository", "workflow", "ref")}
            receipt = _adoption_receipt(request, root=root, config=config,
                                        entry=mapping["runs"][sid], runner=runner)
            if receipt is None:
                raise DispatchError("mapped package hashes no longer match %s" % sid)
            results.append(receipt)
    return results


def route(sid: str, *, live: bool, root: Path = V2, config_path: Path = DEFAULT_CONFIG,
          adoptions_path: Optional[Path] = None, runner=None) -> dict:
    """Prepare or submit one exact request.  Returns a compact tick result."""
    runner = runner or _default_runner
    request = exact_request(sid, root=root)
    config = _config(config_path)
    request["workflow_inputs"]["workers"] = config["workers"]
    request["workflow"] = {key: config[key] for key in ("repository", "workflow", "ref")}
    adoptions_path = adoptions_path or (root / "crew" / DEFAULT_ADOPTIONS.name)
    receipt_dir = root / "kit" / "out" / request["id"] / "cloud-dispatch" / request["request_id"]
    request_path, receipt_path = receipt_dir / "REQUEST.json", receipt_dir / "RECEIPT.json"
    mapping = _adoptions(adoptions_path)
    entry = mapping["runs"].get(request["id"])
    if entry:
        lock_path = root / "crew" / "short-cloud-dispatch.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            adopted = _adoption_receipt(request, root=root, config=config, entry=entry, runner=runner)
        if adopted is not None:
            return {**adopted, "remote_mutation": False}
    if not config["enabled"]:
        return {"status": "disabled", "id": request["id"], "request_id": request["request_id"],
                "reason": "crew/short-cloud-dispatch.json enabled is false", "remote_mutation": False}
    if not live:
        return {"status": "dry_run", "id": request["id"], "request_id": request["request_id"],
                "release": request["workflow_inputs"]["release"], "remote_mutation": False}

    lock_path = root / "crew" / "short-cloud-dispatch.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = _load_json(receipt_path, "cloud dispatch receipt") if receipt_path.exists() else {
            "kind": "agmm_short_cloud_dispatch_receipt",
            "schema": 1,
            "id": request["id"],
            "request_id": request["request_id"],
            "status": "prepared",
            "editorial_status": "NOT_REVIEWED",
            "technical_status": "PENDING_HOSTED_RUN",
            "publication_status": "NOT_REQUESTED",
            "created_at": _utc_now(),
        }
        _atomic_json(request_path, request)
        if receipt.get("status") == "dispatched":
            return {**receipt, "remote_mutation": False}

        title = "AGMM short " + request["workflow_inputs"]["tag"]
        if receipt.get("status") in ("dispatching", "dispatch_submitted", "dispatch_uncertain"):
            run = _find_run(runner, config, title)
            if run:
                receipt.update(status="dispatched", run=run, reconciled_at=_utc_now())
                _atomic_json(receipt_path, receipt)
            return {**receipt, "remote_mutation": False}

        try:
            release = _release(runner, config, request)
        except DispatchError as error:
            receipt.update(status="release_failed", error=str(error), updated_at=_utc_now())
            _atomic_json(receipt_path, receipt)
            return {**receipt, "remote_mutation": True}
        receipt.update(status="release_ready", release=release, updated_at=_utc_now())
        _atomic_json(receipt_path, receipt)

        existing = _find_run(runner, config, title)
        if existing:
            receipt.update(status="dispatched", run=existing, reconciled_at=_utc_now())
            _atomic_json(receipt_path, receipt)
            return {**receipt, "remote_mutation": bool(release.get("mutated"))}

        receipt.update(status="dispatching", dispatch_attempted_at=_utc_now())
        _atomic_json(receipt_path, receipt)
        inputs = request["workflow_inputs"]
        command = ["gh", "workflow", "run", config["workflow"], "-R", config["repository"], "--ref", config["ref"]]
        for key in ("release", "source_sha256", "parts_sha256", "mix_sha256", "tag", "render_4k", "workers"):
            value = str(inputs[key]).lower() if isinstance(inputs[key], bool) else str(inputs[key])
            command += ["-f", "%s=%s" % (key, value)]
        submitted = runner(command)
        if submitted.returncode:
            run = _find_run(runner, config, title)
            if run:
                receipt.update(status="dispatched", run=run, reconciled_at=_utc_now())
            else:
                receipt.update(status="dispatch_uncertain",
                               error=(submitted.stderr or submitted.stdout or "")[-500:], updated_at=_utc_now())
            _atomic_json(receipt_path, receipt)
            return {**receipt, "remote_mutation": True}
        run = _find_run(runner, config, title)
        if run:
            receipt.update(status="dispatched", run=run, reconciled_at=_utc_now())
        else:
            receipt.update(status="dispatch_submitted", updated_at=_utc_now())
        _atomic_json(receipt_path, receipt)
        return {**receipt, "remote_mutation": True}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("id", nargs="?")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--adopt-mapped", action="store_true")
    args = parser.parse_args()
    if args.adopt_mapped:
        print(json.dumps(adopt_mapped(), indent=2))
    elif args.id:
        print(json.dumps(route(args.id, live=args.live), indent=2))
    else:
        parser.error("provide a short ID or --adopt-mapped")


if __name__ == "__main__":
    main()
