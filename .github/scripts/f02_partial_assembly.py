#!/usr/bin/env python3
"""Hosted-Linux-only F02 partial reassembly and provenance guard.

This program deliberately refuses to process media on Darwin. Metadata-only validation
and --self-test are text/code operations; the download, source extraction, staging,
hashing and assembly paths are intended only for the ubuntu GitHub runner.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "F02-partial-assembly-contract.json"
EXPECTED_REPO = "agmmltd-arch/agmm-render-public"
EXPECTED_WORKFLOW = ".github/workflows/agmm-film.yml"
ARTIFACT_RETENTION_BUFFER = timedelta(hours=4)
MAX_ARCHIVE_FILES = 30_000
MAX_ARCHIVE_BYTES = 2_000_000_000
MAX_ARCHIVE_MEMBER_BYTES = 500_000_000
QA_OVERLAY_ALLOWLIST = {
    ".github/scripts/assemble_verify.py",
    ".github/scripts/run_existing_ocr_check.py",
    "qa/gate.py",
    "kit/tools/frame_check.py",
    "kit/tools/ocr_vision.swift",
    "kit/platforms/platforms.py",
    "kit/platforms/frames.json",
    "film/film.js",
    "film/film.css",
    "film/sets_studio.js",
    "film-overlay.sha256",
}
RENDER_JOB_RE = re.compile(r"^render \((\d{1,2}),\s*([0-9]+(?:\.[0-9]+)?),\s*([0-9]+(?:\.[0-9]+)?)\)$")


class Refusal(ValueError):
    """Fail-closed validation error."""


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text())


def parse_time(value: str) -> datetime:
    if not value:
        raise Refusal("timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise Refusal(f"timestamp has no timezone: {value}")
    return parsed.astimezone(timezone.utc)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json_or_jsonl(path: Path) -> Any:
    raw = path.read_text().strip()
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]


def collection(path: Path, key: str) -> list[dict[str, Any]]:
    obj = read_json_or_jsonl(path)
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict) and isinstance(obj.get(key), list):
        return obj[key]
    if isinstance(obj, dict) and isinstance(obj.get("artifacts"), list):
        return obj["artifacts"]
    if isinstance(obj, dict) and isinstance(obj.get("jobs"), list):
        return obj["jobs"]
    raise Refusal(f"{path.name} does not contain a {key} list")


def validate_contract(c: dict[str, Any]) -> None:
    if c.get("film_id") != "F02" or c.get("duration_seconds") != 651.6 or c.get("fps") != 30:
        raise Refusal("contract is not the pinned F02 651.6s/30fps composition")
    if c.get("expected_segments") != 75 or c.get("expected_frames") != 19548:
        raise Refusal("contract total count/frame guard changed")
    comp = c.get("composition", {})
    if comp.get("sealed_source_release") != "F02-profit-qualifier-20261003":
        raise Refusal("wrong final sealed source release")
    if comp.get("sealed_source_package_sha256") != "b216a14d62b2b5430234a411a1913207b41642071fc5985a11bbf09913d21719":
        raise Refusal("wrong final sealed source package hash")
    if comp.get("sealed_source_code_commit") != "088d62de686272206a52cc166307672bdf37ac55":
        raise Refusal("wrong final sealed source code commit")
    if comp.get("apply_source_overlay") is not False:
        raise Refusal("apply_source_overlay must be false")
    parent, replacement = c.get("parent", {}), c.get("replacement", {})
    pins = [
        (parent.get("run_id"), 37125818648),
        (parent.get("tag"), "F02-craft-repaired-full-20261003-1420"),
        (parent.get("code_commit"), "98e632224f2d436f251836c6e167f051aafd6078"),
        (replacement.get("run_id"), 37143394055),
        (replacement.get("tag"), "F02-profit-qualifier-seg51-52-20261003"),
        (replacement.get("code_commit"), "088d62de686272206a52cc166307672bdf37ac55"),
        (replacement.get("package_release"), "F02-profit-qualifier-20261003"),
        (replacement.get("package_sha256"), "b216a14d62b2b5430234a411a1913207b41642071fc5985a11bbf09913d21719"),
    ]
    for actual, expected in pins:
        if actual != expected:
            raise Refusal(f"contract pin mismatch: expected {expected!r}, got {actual!r}")
    segs = c.get("segments")
    if not isinstance(segs, list) or len(segs) != 75:
        raise Refusal("contract must contain exactly 75 segment rows")
    replacement_ids = []
    cursor = 0.0
    frame_total = 0
    seen = set()
    for index, row in enumerate(segs, 1):
        sid = f"{index:02d}"
        if row.get("i") != sid or sid in seen:
            raise Refusal(f"segment grid has missing, duplicate, or out-of-order ID {sid}")
        seen.add(sid)
        try:
            t0, length = float(row["t0"]), float(row["len"])
            frames = int(row["frames"])
        except (KeyError, TypeError, ValueError) as exc:
            raise Refusal(f"bad segment geometry for {sid}: {exc}") from exc
        if abs(t0 - cursor) > 0.002 or length <= 0 or frames != round(length * 30):
            raise Refusal(f"segment {sid} has invalid timing/frame geometry")
        cursor = round(t0 + length, 3)
        frame_total += frames
        expected_lineage = "replacement" if sid in {"51", "52"} else "parent"
        if row.get("lineage") != expected_lineage:
            raise Refusal(f"segment {sid} has unexpected lineage")
        parent_source = row.get("parent", {})
        if (parent_source.get("run_id") != parent["run_id"]
                or parent_source.get("tag") != parent["tag"]
                or parent_source.get("code_commit") != parent["code_commit"]
                or parent_source.get("package_release") != parent["package_release"]
                or parent_source.get("package_sha256") != parent["package_sha256"]
                or parent_source.get("artifact_name") != f"{parent['tag']}-SEG{sid}"):
            raise Refusal(f"segment {sid} parent artifact provenance mismatch")
        if expected_lineage == "replacement":
            replacement_source = row.get("replacement", {})
            if (replacement_source.get("run_id") != replacement["run_id"]
                    or replacement_source.get("tag") != replacement["tag"]
                    or replacement_source.get("code_commit") != replacement["code_commit"]
                    or replacement_source.get("package_release") != replacement["package_release"]
                    or replacement_source.get("package_sha256") != replacement["package_sha256"]
                    or replacement_source.get("artifact_name") != f"{replacement['tag']}-SEG{sid}"):
                raise Refusal(f"segment {sid} replacement artifact provenance mismatch")
            replacement_ids.append(sid)
        elif "replacement" in row:
            raise Refusal(f"segment {sid} has an unexpected replacement source")
        selected = row.get("selected", {})
        source = row.get(expected_lineage, {})
        if selected != source or row.get("artifact_name") != source.get("artifact_name"):
            raise Refusal(f"segment {sid} assembly selection does not match its pinned source")
        if (row.get("source_run") != source.get("run_id")
                or row.get("source_tag") != source.get("tag")
                or row.get("source_package_sha256") != source.get("package_sha256")
                or row.get("source_code_commit") != source.get("code_commit")):
            raise Refusal(f"segment {sid} selected source summary mismatch")
    if abs(cursor - 651.6) > 0.01 or frame_total != 19548:
        raise Refusal("segment grid does not cover exactly 651.6s/19548 frames")
    if replacement_ids != ["51", "52"]:
        raise Refusal(f"only segments 51 and 52 may be replacements; got {replacement_ids}")
    if (segs[50]["t0"], segs[50]["len"], segs[51]["t0"], segs[51]["len"]) != (430.0, 8.6, 438.6, 8.6):
        raise Refusal("replacement windows do not exactly match the sealed render input")
    overlay = c.get("qa_overlay", {})
    if (overlay.get("release") != "F02-r2c-landscape-4k-202609302152"
            or overlay.get("asset") != "qa-overlay-r4e-seg12.tar.gz"
            or overlay.get("sha256") != "76daca8d0d38c7bc26ca13dcc29a6e0da82f77f07c0f25028671b72f850e717f"):
        raise Refusal("QA overlay pin changed")


def render_jobs(jobs: list[dict[str, Any]], expected_rows: list[dict[str, Any]], run_id: int) -> None:
    found: dict[str, dict[str, Any]] = {}
    expected = {row["i"]: row for row in expected_rows}
    for job in jobs:
        name = job.get("name", "")
        match = RENDER_JOB_RE.fullmatch(name)
        if not match:
            continue
        sid = f"{int(match.group(1)):02d}"
        if sid not in expected:
            raise Refusal(f"unexpected render job SEG{sid} in run {run_id}")
        row = expected[sid]
        if abs(float(match.group(2)) - float(row["t0"])) > 0.001 or abs(float(match.group(3)) - float(row["len"])) > 0.001:
            raise Refusal(f"run {run_id} SEG{sid} job timing does not match sealed segment grid")
        if sid in found:
            raise Refusal(f"duplicate render job for SEG{sid} in run {run_id}")
        found[sid] = job
    if sorted(found) != sorted(expected):
        raise Refusal(f"run {run_id} render job set mismatch: got {sorted(found)}, expected {sorted(expected)}")
    for sid, job in found.items():
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            raise Refusal(f"run {run_id} SEG{sid} is not an exact successful completed render job")


def validate_run(run: dict[str, Any], jobs: list[dict[str, Any]], role: str,
                 c: dict[str, Any]) -> None:
    expected = c[role]
    if int(run.get("id", -1)) != expected["run_id"]:
        raise Refusal(f"{role} Actions run ID changed")
    if run.get("path") != EXPECTED_WORKFLOW:
        raise Refusal(f"{role} run did not execute the pinned film workflow")
    if run.get("event") != "workflow_dispatch" or run.get("status") != "completed":
        raise Refusal(f"{role} run is not a completed workflow_dispatch run")
    if run.get("head_sha") != expected["code_commit"]:
        raise Refusal(f"{role} run code commit mismatch")
    render_rows = ([row for row in c["segments"] if role == "parent"]
                   if role == "parent" else [row for row in c["segments"] if "replacement" in row])
    render_jobs(jobs, render_rows, expected["run_id"])
    by_name: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        by_name.setdefault(job.get("name", ""), []).append(job)
    if role == "parent":
        assembly = by_name.get("assemble", [])
        if len(assembly) != 1 or assembly[0].get("status") != "completed" or assembly[0].get("conclusion") != "success":
            raise Refusal("parent assemble job must be one completed success before segment reuse")
        failures = [j.get("name") for j in jobs if j.get("conclusion") == "failure"]
        if run.get("conclusion") == "failure":
            if failures != ["macos-ocr"]:
                raise Refusal(f"parent run failure is not isolated to the expected OCR job: {failures}")
        elif run.get("conclusion") != "success" or failures:
            raise Refusal(f"unexpected parent run conclusion/jobs: {run.get('conclusion')} {failures}")
        ocr = by_name.get("macos-ocr", [])
        if run.get("conclusion") == "failure" and (len(ocr) != 1 or ocr[0].get("conclusion") != "failure"):
            raise Refusal("parent overall failure lacks exact macos-ocr failure provenance")
    else:
        if run.get("conclusion") != "success":
            raise Refusal(f"replacement run must conclude success, got {run.get('conclusion')}")
        failures = [j.get("name") for j in jobs if j.get("conclusion") not in ("success", "skipped", None)]
        if failures:
            raise Refusal(f"replacement run has failed/cancelled jobs: {failures}")


def validate_artifacts(items: list[dict[str, Any]], role: str, c: dict[str, Any],
                       now: datetime | None = None) -> dict[str, dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    expected_rows = ([r for r in c["segments"] if role == "parent"]
                     if role == "parent" else [r for r in c["segments"] if "replacement" in r])
    expected_names = [r[role]["artifact_name"] for r in expected_rows]
    names = [a.get("name") for a in items]
    counts = Counter(names)
    out: dict[str, dict[str, Any]] = {}
    run_id = c[role]["run_id"]
    for row in expected_rows:
        name = row[role]["artifact_name"]
        if counts[name] != 1:
            raise Refusal(f"artifact {name} must occur exactly once, found {counts[name]}")
        art = next(a for a in items if a.get("name") == name)
        if art.get("expired") is not False:
            raise Refusal(f"artifact {name} is expired or expiration flag missing")
        if int(art.get("size_in_bytes", 0)) <= 0:
            raise Refusal(f"artifact {name} has empty/unknown size")
        if int(art.get("id", 0)) <= 0:
            raise Refusal(f"artifact {name} has no immutable artifact ID")
        expiry = parse_time(art.get("expires_at", ""))
        created = parse_time(art.get("created_at", ""))
        if expiry <= now + ARTIFACT_RETENTION_BUFFER:
            raise Refusal(f"artifact {name} expires inside 4-hour assembly window")
        run_ref = (art.get("workflow_run") or {}).get("id")
        if run_ref is None or int(run_ref) != run_id:
            raise Refusal(f"artifact {name} lacks exact workflow-run provenance")
        if created > now + timedelta(minutes=5):
            raise Refusal(f"artifact {name} creation time is in the future")
        out[name] = art
    ids = [a["id"] for a in out.values()]
    if len(ids) != len(set(ids)):
        raise Refusal(f"duplicate immutable artifact IDs in {role} set")
    if len(out) != len(expected_names):
        raise Refusal(f"{role} exact artifact set is incomplete")
    return out


def validate_release(release: dict[str, Any], tag: str, asset_name: str,
                     expected_sha: str | None = None) -> dict[str, Any]:
    if release.get("tag_name") != tag:
        raise Refusal(f"release tag mismatch: expected {tag}")
    assets = [a for a in release.get("assets", []) if a.get("name") == asset_name]
    if len(assets) != 1 or int(assets[0].get("size", 0)) <= 0:
        raise Refusal(f"release must contain exactly one nonempty {asset_name}")
    asset = assets[0]
    digest = asset.get("digest") or ""
    if expected_sha and digest and digest not in (expected_sha, f"sha256:{expected_sha}"):
        raise Refusal(f"release API asset digest mismatch for {asset_name}")
    return asset


def validate_metadata(c: dict[str, Any], snapshots: Path,
                      now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    records = {}
    all_artifact_ids = []
    for role in ("parent", "replacement"):
        role_dir = snapshots / role
        run = read_json_or_jsonl(role_dir / "run.json")
        jobs = collection(role_dir / "jobs.jsonl", "jobs")
        artifacts = collection(role_dir / "artifacts.jsonl", "artifacts")
        validate_run(run, jobs, role, c)
        selected = validate_artifacts(artifacts, role, c, now)
        all_artifact_ids.extend(str(a["id"]) for a in selected.values())
        records[role] = {"run": run, "jobs": jobs, "selected_artifacts": selected}
    if len(all_artifact_ids) != len(set(all_artifact_ids)):
        raise Refusal("artifact IDs overlap between parent and replacement runs")
    validate_release(read_json_or_jsonl(snapshots / "source-release.json"),
                     c["composition"]["sealed_source_release"], "source.tar.gz",
                     c["composition"]["sealed_source_package_sha256"])
    overlay = c["qa_overlay"]
    validate_release(read_json_or_jsonl(snapshots / "qa-overlay-release.json"),
                     overlay["release"], overlay["asset"], overlay["sha256"])
    return records


def gh_json(endpoint: str) -> dict[str, Any]:
    p = subprocess.run(["gh", "api", endpoint], check=False, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise Refusal(f"GitHub API request failed: {endpoint}: {p.stderr[-1000:]}")
    return json.loads(p.stdout)


def gh_jsonl(endpoint: str, key: str) -> None:
    p = subprocess.run(["gh", "api", "--paginate", endpoint, "--jq", f".{key}[]"],
                       check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise Refusal(f"GitHub API pagination failed: {endpoint}: {p.stderr[-1000:]}")
    Path(sys.argv[-1]).write_text(p.stdout)


def snapshot_metadata(repo: str, out: Path, c: dict[str, Any]) -> None:
    if repo != EXPECTED_REPO:
        raise Refusal(f"wrong GitHub repository {repo}")
    out.mkdir(parents=True, exist_ok=True)
    for role in ("parent", "replacement"):
        run_id = c[role]["run_id"]
        d = out / role
        d.mkdir(parents=True, exist_ok=True)
        (d / "run.json").write_text(json.dumps(gh_json(f"repos/{repo}/actions/runs/{run_id}"), indent=2) + "\n")
        for endpoint, key, filename in (
            (f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100", "jobs", "jobs.jsonl"),
            (f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100", "artifacts", "artifacts.jsonl"),
        ):
            p = subprocess.run(["gh", "api", "--paginate", endpoint, "--jq", f".{key}[]"],
                               check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p.returncode:
                raise Refusal(f"GitHub API pagination failed: {endpoint}: {p.stderr[-1000:]}")
            (d / filename).write_text(p.stdout)
    for tag, name in ((c["composition"]["sealed_source_release"], "source-release.json"),
                      (c["qa_overlay"]["release"], "qa-overlay-release.json")):
        (out / name).write_text(json.dumps(gh_json(f"repos/{repo}/releases/tags/{tag}"), indent=2) + "\n")


def safe_archive_members(tf: tarfile.TarFile, *, exact: set[str] | None = None) -> list[tarfile.TarInfo]:
    members = tf.getmembers()
    if len(members) > MAX_ARCHIVE_FILES:
        raise Refusal("archive has too many entries")
    names: set[str] = set()
    normalized_members: list[tarfile.TarInfo] = []
    root_seen = False
    total = 0
    for m in members:
        raw = m.name
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts:
            raise Refusal(f"unsafe archive member path: {raw}")
        if not (m.isfile() or m.isdir()):
            raise Refusal(f"archive member type forbidden: {raw}")
        # Conventional `tar -C package .` archives contain a harmless root directory.
        # Skip only that directory; a regular file named `.` is never accepted.
        if not path.parts:
            if not m.isdir():
                raise Refusal(f"archive root entry must be a directory: {raw}")
            if root_seen:
                raise Refusal(f"duplicate archive root directory: {raw}")
            root_seen = True
            continue
        normalized = PurePosixPath(*path.parts).as_posix()
        if normalized in names:
            raise Refusal(f"duplicate archive member after path normalization: {normalized}")
        names.add(normalized)
        # Use the normalized relative path for allowlist checks and extraction.
        m.name = normalized
        normalized_members.append(m)
        if m.size < 0 or m.size > MAX_ARCHIVE_MEMBER_BYTES:
            raise Refusal(f"archive member size out of bounds: {raw}")
        total += m.size
    if total > MAX_ARCHIVE_BYTES:
        raise Refusal("archive expanded size exceeds safety limit")
    if exact is not None and names != exact:
        raise Refusal(f"QA overlay member allowlist mismatch: {sorted(names ^ exact)}")
    return normalized_members


def safe_extract(tf: tarfile.TarFile, members: list[tarfile.TarInfo], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    base = destination.resolve()
    for m in members:
        target = (base / PurePosixPath(m.name)).resolve()
        if base not in target.parents and target != base:
            raise Refusal(f"archive member escapes destination: {m.name}")
        if m.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        src = tf.extractfile(m)
        if src is None:
            raise Refusal(f"archive member cannot be read: {m.name}")
        with src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)


def verify_package_checksums(package: Path) -> None:
    sums = package / "SHA256SUMS.txt"
    if not sums.is_file():
        raise Refusal("sealed source package lacks SHA256SUMS.txt")
    seen = set()
    for line_no, line in enumerate(sums.read_text().splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise Refusal(f"malformed package checksum line {line_no}")
        digest, name = match.groups()
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or name in seen:
            raise Refusal(f"unsafe/duplicate package checksum member {name}")
        seen.add(name)
        target = (package / path).resolve()
        if package.resolve() not in target.parents or not target.is_file():
            raise Refusal(f"package checksum target missing or escapes package: {name}")
        if sha256(target) != digest:
            raise Refusal(f"sealed package checksum mismatch: {name}")
    if not seen:
        raise Refusal("sealed package checksum manifest is empty")


def prepare_source(source_archive: Path, overlay_archive: Path, package_dir: Path,
                   overlay_dir: Path, c: dict[str, Any]) -> dict[str, Any]:
    if sys.platform == "darwin":
        raise Refusal("media/source extraction is forbidden on Darwin; hosted Ubuntu runner only")
    comp = c["composition"]
    source_hash = sha256(source_archive)
    if source_hash != comp["sealed_source_package_sha256"]:
        raise Refusal("downloaded sealed source archive hash mismatch")
    overlay_hash = sha256(overlay_archive)
    if overlay_hash != c["qa_overlay"]["sha256"]:
        raise Refusal("downloaded QA helper overlay hash mismatch")
    if comp.get("apply_source_overlay") is not False:
        raise Refusal("refusing to apply source overlay; contract must set false")
    if package_dir.exists() and any(package_dir.iterdir()):
        raise Refusal("package extraction destination is not empty")
    with tarfile.open(source_archive, "r:gz") as tf:
        members = safe_archive_members(tf)
        safe_extract(tf, members, package_dir)
    verify_package_checksums(package_dir)
    for rel, digest in comp["expected_repair_files"].items():
        file = package_dir / rel
        if not file.is_file() or sha256(file) != digest:
            raise Refusal(f"sealed repaired source file hash mismatch: {rel}")
    index = package_dir / "film" / "index.html"
    mix = package_dir / "audio" / "mix.flac"
    if not index.is_file() or not mix.is_file():
        raise Refusal("sealed source package lacks film/index.html or audio/mix.flac")
    duration_matches = re.findall(r'data-duration="([0-9.]+)"', index.read_text())
    if duration_matches != ["651.6"]:
        raise Refusal(f"source duration must be the single exact 651.6 value, got {duration_matches}")
    check = subprocess.run(["python3", "static_check.py"], cwd=package_dir,
                           check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check.returncode:
        raise Refusal(f"sealed source static check failed: {check.stdout[-3000:]}")
    if overlay_dir.exists() and any(overlay_dir.iterdir()):
        raise Refusal("QA helper extraction destination is not empty")
    with tarfile.open(overlay_archive, "r:gz") as tf:
        members = safe_archive_members(tf, exact=QA_OVERLAY_ALLOWLIST)
        # Extract only the verifier; source JS/CSS/studio files from the overlay are never applied.
        helper_members = [m for m in members if m.name == ".github/scripts/assemble_verify.py"]
        if len(helper_members) != 1:
            raise Refusal("QA overlay lacks a unique assemble_verify.py")
        safe_extract(tf, helper_members, overlay_dir)
    helper = overlay_dir / ".github" / "scripts" / "assemble_verify.py"
    if not helper.is_file():
        raise Refusal("verified assemble_verify helper did not extract")
    return {"sealed_source_sha256": source_hash, "sealed_source_bytes": source_archive.stat().st_size,
            "qa_overlay_sha256": overlay_hash, "qa_helper_sha256": sha256(helper),
            "source_static_check": "PASS", "apply_source_overlay": False,
            "source_member_count": len(members), "source_release": comp["sealed_source_release"],
            "source_package_sha256": comp["sealed_source_package_sha256"]}


def artifact_file(artifact_root: Path, sid: str, suffix: str) -> Path:
    target_name = f"SEG{sid}{suffix}"
    matches = [p for p in artifact_root.rglob(target_name) if p.is_file() and not p.is_symlink()]
    if len(matches) != 1:
        raise Refusal(f"expected one {target_name} beneath {artifact_root}, got {len(matches)}")
    resolved = matches[0].resolve()
    if artifact_root.resolve() not in resolved.parents:
        raise Refusal(f"artifact file path escaped its root: {target_name}")
    return matches[0]


def safe_download(run_id: int, artifact_name: str, dest: Path) -> None:
    if sys.platform == "darwin":
        raise Refusal("artifact media download is forbidden on Darwin; hosted Ubuntu runner only")
    dest.mkdir(parents=True, exist_ok=False)
    command = ["gh", "run", "download", str(run_id), "--repo", EXPECTED_REPO,
               "--name", artifact_name, "--dir", str(dest)]
    p = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise Refusal(f"artifact download failed for {artifact_name}: {p.stderr[-1200:]}; partial download preserved at {dest}")


def copy_artifact(artifact_root: Path, sid: str, destination: Path) -> dict[str, Any]:
    mp4 = artifact_file(artifact_root, sid, ".mp4")
    verify = artifact_file(artifact_root, sid, ".verify.json")
    if mp4.stat().st_size <= 0 or verify.stat().st_size <= 0:
        raise Refusal(f"empty media or verification receipt for SEG{sid}")
    actual_sha = sha256(mp4)
    receipt = json.loads(verify.read_text())
    row = next(r for r in load_contract()["segments"] if r["i"] == sid)
    if (receipt.get("status") != "PASS" or receipt.get("sha256") != actual_sha
            or receipt.get("frames") != row["frames"]
            or receipt.get("full_decode") != "PASS"
            or receipt.get("flicker", {}).get("status") != "PASS"):
        raise Refusal(f"SEG{sid} render verification receipt does not bind to the downloaded bytes")
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copy2(mp4, destination / f"SEG{sid}.mp4")
    shutil.copy2(verify, destination / f"SEG{sid}.verify.json")
    logs = [p for p in artifact_root.rglob(f"SEG{sid}.render.log") if p.is_file() and not p.is_symlink()]
    if len(logs) > 1:
        raise Refusal(f"multiple render logs for SEG{sid}")
    if logs:
        shutil.copy2(logs[0], destination / logs[0].name)
    return {"sha256": actual_sha, "bytes": mp4.stat().st_size,
            "verify_receipt": receipt, "artifact_files": sorted(p.name for p in destination.iterdir())}


def stage_segments(c: dict[str, Any], snapshots: Path, downloads: Path,
                   lineage_root: Path, assembly_segments: Path) -> dict[str, Any]:
    if sys.platform == "darwin":
        raise Refusal("media staging/hashing is forbidden on Darwin; hosted Ubuntu runner only")
    if lineage_root.exists() and any(lineage_root.iterdir()):
        raise Refusal("lineage output must be new/empty; parent parts are immutable inputs")
    if assembly_segments.exists() and any(assembly_segments.iterdir()):
        raise Refusal("assembly segment directory must be new/empty")
    lineage_root.mkdir(parents=True, exist_ok=True)
    assembly_segments.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for role in ("parent", "replacement"):
        role_dir = downloads / role
        art_map = validate_artifacts(collection(snapshots / role / "artifacts.jsonl", "artifacts"), role, c)
        for row in c["segments"]:
            if role == "replacement" and "replacement" not in row:
                continue
            source = row[role]
            sid, art_name = row["i"], source["artifact_name"]
            source_dir = role_dir / art_name
            if not source_dir.exists():
                raise Refusal(f"downloaded artifact directory missing: {art_name}")
            preserved = lineage_root / role / f"SEG{sid}"
            copied = copy_artifact(source_dir, sid, preserved)
            for suffix in (".mp4", ".verify.json"):
                src = preserved / f"SEG{sid}{suffix}"
                # Replacement files stay in their own lineage tree; only the assembly copy is overlaid.
                shutil.copy2(src, assembly_segments / src.name)
            art = art_map[art_name]
            records.append({"segment": sid, "t0": row["t0"], "len": row["len"],
                            "expected_frames": row["frames"], "provenance_role": role,
                            "run_id": source["run_id"], "tag": source["tag"],
                            "code_commit": source["code_commit"],
                            "package_release": source["package_release"],
                            "package_sha256": source["package_sha256"],
                            "artifact_name": art_name, "artifact_id": art["id"],
                            "artifact_created_at": art["created_at"], "artifact_expires_at": art["expires_at"],
                            "artifact_size_in_bytes": art["size_in_bytes"],
                            "hosted_media_sha256": copied["sha256"], "hosted_media_bytes": copied["bytes"],
                            "render_receipt": copied["verify_receipt"]})
    # Ensure exact composition names exist once and replacements are the working files for 51/52.
    expected_names = {f"SEG{r['i']}.mp4" for r in c["segments"]} | {f"SEG{r['i']}.verify.json" for r in c["segments"]}
    actual_names = {p.name for p in assembly_segments.iterdir()}
    if actual_names != expected_names:
        raise Refusal(f"assembled segment staging set mismatch: {sorted(actual_names ^ expected_names)}")
    prov = {"kind": "f02_segment_lineage_manifest", "schema": 1,
            "status": "STAGED_FOR_MECHANICAL_ASSEMBLY", "editorial_review": "NOT_PERFORMED",
            "release_approval": "NOT_GRANTED", "apply_source_overlay": False,
            "parent_run_id": c["parent"]["run_id"], "parent_tag": c["parent"]["tag"],
            "replacement_run_id": c["replacement"]["run_id"], "replacement_tag": c["replacement"]["tag"],
            "source_release": c["composition"]["sealed_source_release"],
            "source_package_sha256": c["composition"]["sealed_source_package_sha256"],
            "expected_segments": 75, "replacement_segments": ["51", "52"],
            "segment_provenance": records}
    out = lineage_root / "F02-LINEAGE.json"
    out.write_text(json.dumps(prov, indent=2) + "\n")
    return prov


def gh_snapshot_all(repo: str, out: Path, c: dict[str, Any]) -> None:
    snapshot_metadata(repo, out, c)


def refresh_sums(output_dir: Path) -> None:
    if sys.platform == "darwin":
        raise Refusal("final media checksum refresh is forbidden on Darwin; hosted Ubuntu runner only")
    sums = []
    for file in sorted(output_dir.iterdir()):
        if file.is_file() and file.name != "SHA256SUMS.txt":
            sums.append(f"{sha256(file)}  {file.name}")
    (output_dir / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    check = subprocess.run(["sha256sum", "-c", "SHA256SUMS.txt"], cwd=output_dir,
                           check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check.returncode:
        raise Refusal(f"final exported artifact checksum list failed: {check.stdout[-2000:]}")


def make_final_receipt(integrity_path: Path, lineage_path: Path, output_dir: Path) -> dict[str, Any]:
    if sys.platform == "darwin":
        raise Refusal("final media receipt hashing is forbidden on Darwin; hosted Ubuntu runner only")
    integrity = json.loads(integrity_path.read_text())
    lineage = json.loads(lineage_path.read_text())
    if (lineage.get("kind") != "f02_segment_lineage_manifest"
            or lineage.get("source_release") != load_contract()["composition"]["sealed_source_release"]
            or lineage.get("source_package_sha256") != load_contract()["composition"]["sealed_source_package_sha256"]):
        raise Refusal("segment lineage manifest source identity mismatch")
    provenance = lineage.get("segment_provenance")
    if (not isinstance(provenance, list) or len(provenance) != 77
            or sum(r.get("provenance_role") == "parent" for r in provenance) != 75
            or sum(r.get("provenance_role") == "replacement" for r in provenance) != 2
            or {r.get("segment") for r in provenance if r.get("provenance_role") == "replacement"} != {"51", "52"}):
        raise Refusal("segment lineage manifest must retain parent 75 plus separate replacements 51/52")
    if integrity.get("kind") != "mechanical_integrity_only" or integrity.get("release_approval") != "NOT_GRANTED":
        raise Refusal("assemble_verify did not produce the expected mechanical-only receipt")
    if (integrity.get("editorial_gate") != "NOT_RUN" or integrity.get("duration") != 651.6
            or integrity.get("segment_count") != 75 or integrity.get("frame_count") != 19548):
        raise Refusal("whole-master receipt scope/count mismatch")
    expected_checks = {"segment_decode", "segment_flicker", "master_full_decode",
                       "derived_full_decode", "encoded_audio_loudness_and_true_peak"}
    checks = integrity.get("checks")
    if not isinstance(checks, dict) or set(checks) != expected_checks or any(v != "PASS" for v in checks.values()):
        raise Refusal("whole-master receipt check schema/status mismatch")
    outputs = integrity.get("outputs")
    if not isinstance(outputs, dict) or outputs.get("master") != "F02-MASTER-4K.mp4" or outputs.get("derived") != "F02-MASTER-1080-from-4K.mp4":
        raise Refusal("whole-master receipt output paths mismatch")
    master_path = output_dir / outputs["master"]
    derived_path = output_dir / outputs["derived"]
    if (not master_path.is_file() or master_path.stat().st_size <= 0
            or master_path.stat().st_size != outputs.get("master_bytes")
            or sha256(master_path) != outputs.get("master_sha256")):
        raise Refusal("whole-master receipt master hash/byte mismatch")
    if (not derived_path.is_file() or derived_path.stat().st_size <= 0
            or derived_path.stat().st_size != outputs.get("derived_bytes")):
        raise Refusal("whole-master receipt derived proxy byte mismatch")
    outputs["derived_sha256"] = sha256(derived_path)
    receipt = {"kind": "F02-hosted-partial-assembly-receipt", "schema": 1,
               "status": "MECHANICAL_INTEGRITY_VERIFIED_ONLY", "editorial_status": "NOT_REVIEWED",
               "release_approval": "NOT_GRANTED", "armed": False,
               "source_release": lineage["source_release"], "source_package_sha256": lineage["source_package_sha256"],
               "duration_seconds": integrity["duration"], "segments": integrity["segment_count"],
               "frames": integrity["frame_count"], "checks": integrity["checks"],
               "master": outputs,
               "lineage_manifest": "F02-LINEAGE.json",
               "notes": "Technical decode/probe/audio integrity does not constitute whole-film editorial review or release approval."}
    path = output_dir / "F02-PARTIAL-ASSEMBLY-RECEIPT.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def self_test() -> None:
    c = load_contract()
    validate_contract(c)
    # All tests are synthetic metadata; this path opens no media.
    now = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)
    first = c["segments"][0]
    assert first["i"] == "01" and first["frames"] == 258
    assert c["segments"][50]["parent"]["artifact_name"].endswith("SEG51")
    assert c["segments"][51]["source_run"] == 37143394055
    for mutation in (
        lambda x: x["composition"].update(apply_source_overlay=True),
        lambda x: x["segments"].pop(),
        lambda x: x["segments"][50].update(source_run=37125818648),
    ):
        test = json.loads(json.dumps(c))
        mutation(test)
        try:
            validate_contract(test)
        except Refusal:
            pass
        else:
            raise AssertionError("negative contract test accepted invalid input")
    print("self-test PASS: exact 75-part grid, only 51/52 replaced; overlay refusal tested; no media opened")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["validate-contract", "snapshot", "preflight", "prepare-source",
                                        "download-and-stage", "print-segments-json", "final-receipt", "refresh-sums", "self-test"])
    ap.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    ap.add_argument("--repo", default=EXPECTED_REPO)
    ap.add_argument("--snapshots", type=Path, default=Path("metadata"))
    ap.add_argument("--downloads", type=Path, default=Path("downloads"))
    ap.add_argument("--source-archive", type=Path, default=Path("source.tar.gz"))
    ap.add_argument("--overlay-archive", type=Path, default=Path("qa-overlay.tar.gz"))
    ap.add_argument("--package-dir", type=Path, default=Path("package"))
    ap.add_argument("--overlay-dir", type=Path, default=Path("qa_overlay"))
    ap.add_argument("--lineage-dir", type=Path, default=Path("lineage"))
    ap.add_argument("--segments-dir", type=Path, default=Path("assembly/segments"))
    ap.add_argument("--output-dir", type=Path, default=Path("remote-final"))
    a = ap.parse_args()
    c = load_contract(a.contract)
    if a.command == "self-test":
        self_test()
    elif a.command == "validate-contract":
        validate_contract(c); print("contract PASS; no media opened")
    elif a.command == "snapshot":
        validate_contract(c); gh_snapshot_all(a.repo, a.snapshots, c)
    elif a.command == "preflight":
        validate_contract(c); validate_metadata(c, a.snapshots)
        print("preflight PASS; all source/run/artifact metadata pinned before media downloads")
    elif a.command == "prepare-source":
        validate_contract(c); print(json.dumps(prepare_source(a.source_archive, a.overlay_archive,
                                                              a.package_dir, a.overlay_dir, c), indent=2))
    elif a.command == "download-and-stage":
        validate_contract(c)
        if sys.platform == "darwin": raise Refusal("hosted Ubuntu runner only")
        a.downloads.mkdir(parents=True, exist_ok=False)
        for role in ("parent", "replacement"):
            (a.downloads / role).mkdir()
        records = validate_metadata(c, a.snapshots)
        tasks = []
        # Each archive is fetched to its own immutable directory. A bounded pool avoids API bursts.
        with ThreadPoolExecutor(max_workers=4) as pool:
            for role in ("parent", "replacement"):
                for row in c["segments"]:
                    if role == "replacement" and "replacement" not in row:
                        continue
                    source = row[role]
                    art_name = source["artifact_name"]
                    dest = a.downloads / role / art_name
                    tasks.append(pool.submit(safe_download, c[role]["run_id"], art_name, dest))
            for future in as_completed(tasks): future.result()
        stage_segments(c, a.snapshots, a.downloads, a.lineage_dir, a.segments_dir)
        print("segment provenance staged; originals retained separately")
    elif a.command == "print-segments-json":
        validate_contract(c)
        print(json.dumps([{k: r[k] for k in ("i", "t0", "len")} for r in c["segments"]], separators=(",", ":")))
    elif a.command == "final-receipt":
        make_final_receipt(a.output_dir / "REMOTE-INTEGRITY.json",
                           a.lineage_dir / "F02-LINEAGE.json", a.output_dir)
    elif a.command == "refresh-sums":
        refresh_sums(a.output_dir); print("final checksum list PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"REFUSED/FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
