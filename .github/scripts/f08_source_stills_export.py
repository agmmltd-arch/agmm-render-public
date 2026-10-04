#!/usr/bin/env python3
"""Hosted-only, run-scoped public export of F08 Wave03 source PNGs.

The source artifact is fetched, hashed and inspected only on GitHub-hosted
Ubuntu. The public prerelease contains eight PNGs and safe text receipts only.
It cannot set visual approval, Ready, AV approval or production status.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import zipfile

REPO = "agmmltd-arch/agmm-render-public"
REPOSITORY_ID = 1397641626
SOURCE_RUN_ID = 37234526723
SOURCE_COMMIT = "650a184b76f2e5bbd9541a5eb03b500a376d26be"
SOURCE_JOB_ID = 111530890406
SOURCE_MANIFEST_SHA256 = "257fbef54f2274919901fbc08b7ea01a8e06724296e7ab72c5b0e931620a7297"
WORKFLOW = ".github/workflows/f08-babylon-wave03-source-capture.yml"
WORKFLOW_NAME = "F08 Babylon Wave03 bounded source stills"
JOB_NAME = "source-stills"
PACKAGE = "conditional-babylon-whole-film-wave01"
ARTIFACT_PREFIX = "F08-Babylon-Wave03-source-stills-"
MANIFEST_PATH = f"{PACKAGE}/SOURCE-CAPTURE-PUBLICATION-MANIFEST-WAVE03.json"
CAPTURE_SCRIPT_PATH = f"{PACKAGE}/tools/source_capture.py"
STORYBOARD_PATH = f"{PACKAGE}/inputs/storyboard-wave03.json"
CAPTURE_SCRIPT_SHA256 = "e7174dd713d48db0990d6022aed21dce68658e402c30892be5cae287fc58bb07"
EXPECTED_INPUT_HASHES = {
    f"{PACKAGE}/package.json": "3a0bf4eae3c28223a92e3b61ea4fd869ae9c20ae1a650645a39a7ae9a0c66753",
    f"{PACKAGE}/package-lock.json": "4eb6ec610444fa454c2d81b7fe9c0e0aabca9c3ae804fee84d6b78c77910ec78",
    f"{PACKAGE}/tools/build-draft.mjs": "a9863ff38bff833f5ed7093fa2c903e5e052dd1df55d5f087bdd045171fcbd4f",
    STORYBOARD_PATH: "7e8fb8f638742ed0c7b7cf6d7defc4f452f733e38481e9cbf6217682ba4413a4",
    CAPTURE_SCRIPT_PATH: CAPTURE_SCRIPT_SHA256,
    f"{PACKAGE}/tools/verify_source_manifest.py": "97f47da23a5b991b41a1a53fc18a36c0bb521461d3cfec328dbc8237de9a88e0",
    f"{PACKAGE}/tools/test_storyboard_contract.py": "efcf817017657b7c8294ccebf0797dc54878ed73bae8649ef7e3ca9b2478d9bd",
    f"{PACKAGE}/tools/test_rebind_clock.py": "e1b7561e750045f483f92406219bd1b30e29fd8e94e6a9ae9d50bea20cce6f70",
    f"{PACKAGE}/tools/rebind-clock.py": "021681500c5fd581ac9e06e2e0fd0427eff8bf385470d90605fcf5dbef661808",
    f"{PACKAGE}/SCRIPT-AND-SCENE-INPUTS-WAVE03.md": "edd39fa64f2030ad755a5c86b7371c73ea4b50710e04221228d5b415c1a6312c",
    f"{PACKAGE}/inputs/sound-manifest-wave03.json": "80cb7099b17320a270220b4b63789f4f4967ac6e177f09197faba5d40f06a292",
    ".github/workflows/f08-babylon-wave03-source-capture.yml": "f04e342b538c0fdc815d20606863263f3c7d001090896fb39cbfad0692f7f76c",
}
EXPECTED_INPUT_PATHS = set(EXPECTED_INPUT_HASHES)
POINTS = (
    ("opening-claim", "scene-01-number", 12.372),
    ("sample-boundary", "scene-02-sample", 37.270),
    ("separate-comparator", "scene-03-comparator", 73.138),
    ("separate-study", "scene-04-separate-study", 111.019),
    ("service-profile", "scene-05-gp-at-hand", 148.703),
    ("dated-service-count", "scene-06-service-count", 173.632),
    ("chronology-seam", "scene-07-company-chronology", 212.594),
    ("closing-questions", "scene-08-takeaway", 258.286),
)
FRAME_NAMES = tuple(
    f"frame-{index:02d}-at-{str(seconds).rstrip('0').rstrip('.')}s.png"
    for index, (_, _, seconds) in enumerate(POINTS)
)
FRAME_MEMBERS = {f"captures/{name}" for name in FRAME_NAMES}
PLAN_MEMBER = "source-capture-plan.json"
SOURCE_RECEIPT_MEMBER = "source-capture-receipt.json"
CONTACT_MEMBER = "captures/contact-sheet.jpg"
ZIP_MEMBERS = FRAME_MEMBERS | {PLAN_MEMBER, SOURCE_RECEIPT_MEMBER, CONTACT_MEMBER}
PLAN_NAME = "F08-W03-ESTIMATED-SOURCE-CAPTURE-PLAN.json"
RECEIPT_NAME = "F08-W03-SOURCE-STILLS-REVIEW-RECEIPT.json"
SUMMARY_NAME = "README.txt"
SUMS_NAME = "SHA256SUMS.txt"
PUBLIC_NAMES = {*FRAME_NAMES, PLAN_NAME, RECEIPT_NAME, SUMMARY_NAME, SUMS_NAME}
MAX_ARCHIVE_BYTES = 250_000_000
MAX_EXPANDED_BYTES = 700_000_000
MAX_FRAME_BYTES = 100_000_000
MIN_FREE_BYTES = 2_500_000_000
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class Refusal(ValueError):
    pass


def parse_time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise Refusal("native timestamp is malformed") from exc
    if result.tzinfo is None:
        raise Refusal("native timestamp has no timezone")
    return result.astimezone(timezone.utc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refusal(f"missing or malformed {path.name}") from exc
    if not isinstance(value, dict):
        raise Refusal(f"{path.name} must contain one JSON object")
    return value


def load_manifest(path: Path, expected_sha256: str) -> tuple[dict, str]:
    if not SHA_RE.fullmatch(expected_sha256):
        raise Refusal("expected source manifest SHA-256 must be 64 lowercase hex characters")
    if expected_sha256 != SOURCE_MANIFEST_SHA256:
        raise Refusal("source manifest SHA-256 is not the frozen reviewed manifest")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise Refusal("source manifest bytes do not match the requested digest")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Refusal("source manifest JSON is malformed") from exc
    if not isinstance(value, dict):
        raise Refusal("source manifest must contain one JSON object")
    return value, digest


def validate_manifest(manifest: dict, expected_sha256: str) -> dict[str, str]:
    if not SHA_RE.fullmatch(expected_sha256):
        raise Refusal("expected source manifest SHA-256 must be 64 lowercase hex characters")
    if expected_sha256 != SOURCE_MANIFEST_SHA256:
        raise Refusal("source manifest SHA-256 is not the frozen reviewed manifest")
    if manifest.get("schema_version") != 1 or manifest.get("repository") != REPO:
        raise Refusal("source publication manifest identity mismatch")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or len(entries) != 12:
        raise Refusal("source manifest must contain exactly the reviewed 12 targets")
    by_path = {}
    for entry in entries:
        target, digest = entry.get("target_path"), entry.get("sha256")
        if (not isinstance(target, str) or not target or "\\" in target
                or PurePosixPath(target).is_absolute() or ".." in PurePosixPath(target).parts
                or not SHA_RE.fullmatch(str(digest)) or target in by_path):
            raise Refusal("source manifest entry is malformed or duplicated")
        by_path[target] = digest
    if by_path != EXPECTED_INPUT_HASHES or MANIFEST_PATH in by_path:
        raise Refusal("source manifest target/hash map differs from the frozen reviewed 12 inputs")
    return by_path


def validate_source(repository: dict, run: dict, jobs_doc: dict, artifacts_doc: dict,
                    source_run_id: int, source_commit: str,
                    manifest: dict, manifest_raw_sha256: str,
                    observed_at: datetime | None = None) -> dict:
    """Bind a public export to one exact successful run, commit and artifact."""
    now = observed_at or datetime.now(timezone.utc)
    if (repository.get("full_name") != REPO or repository.get("id") != REPOSITORY_ID
            or repository.get("private") is not False or repository.get("visibility") != "public"):
        raise Refusal("source repository is not the exact public repository")
    if (source_run_id != SOURCE_RUN_ID or source_commit != SOURCE_COMMIT
            or manifest_raw_sha256 != SOURCE_MANIFEST_SHA256):
        raise Refusal("source selection is not the frozen successful run/commit/manifest triple")
    if not FULL_SHA_RE.fullmatch(source_commit) or run.get("head_sha") != source_commit:
        raise Refusal("source run head does not match the frozen full commit")
    if (run.get("id") != SOURCE_RUN_ID or run.get("head_branch") != "main"
            or (run.get("repository") or {}).get("full_name") != REPO
            or run.get("path") != WORKFLOW or run.get("name") != WORKFLOW_NAME
            or run.get("event") != "workflow_dispatch" or run.get("status") != "completed"
            or run.get("conclusion") != "success" or run.get("run_attempt") != 1):
        raise Refusal("source is not the exact completed successful Wave03 capture run")
    run_start, run_end = parse_time(run.get("created_at")), parse_time(run.get("updated_at"))
    jobs = jobs_doc.get("jobs")
    if jobs_doc.get("total_count") != 1 or not isinstance(jobs, list) or len(jobs) != 1:
        raise Refusal("source job inventory differs from the one-job capture workflow")
    job = jobs[0]
    if (job.get("id") != SOURCE_JOB_ID or job.get("name") != JOB_NAME or job.get("run_id") != SOURCE_RUN_ID
            or job.get("head_sha") != source_commit or job.get("status") != "completed"
            or job.get("conclusion") != "success"):
        raise Refusal("native source-stills job is not the exact completed success")
    artifacts = artifacts_doc.get("artifacts")
    if artifacts_doc.get("total_count") != 1 or not isinstance(artifacts, list) or len(artifacts) != 1:
        raise Refusal("source run must contain exactly one native artifact")
    artifact = artifacts[0]
    expected_name = f"{ARTIFACT_PREFIX}{SOURCE_RUN_ID}"
    workflow_run = artifact.get("workflow_run") or {}
    digest = artifact.get("digest")
    size = artifact.get("size_in_bytes")
    if (type(artifact.get("id")) is not int or artifact.get("id") <= 0
            or artifact.get("name") != expected_name
            or type(size) is not int or size <= 0 or size > MAX_ARCHIVE_BYTES
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(digest))
            or artifact.get("expired") is not False
            or workflow_run.get("head_branch") != "main"
            or workflow_run.get("head_repository_id") != REPOSITORY_ID
            or workflow_run.get("id") != SOURCE_RUN_ID
            or workflow_run.get("head_sha") != source_commit
            or workflow_run.get("repository_id") != REPOSITORY_ID):
        raise Refusal("source artifact ID/name/size/digest/run binding mismatch")
    created, expires = parse_time(artifact.get("created_at")), parse_time(artifact.get("expires_at"))
    if (created < run_start or created > run_end or expires <= now):
        raise Refusal("source artifact is outside its run window or expired")
    inputs = validate_manifest(manifest, manifest_raw_sha256)
    return {
        "repository": REPO, "repository_id": REPOSITORY_ID,
        "run_id": SOURCE_RUN_ID, "head_branch": "main", "head_sha": SOURCE_COMMIT, "workflow": WORKFLOW,
        "job_id": job.get("id"), "job_name": JOB_NAME, "run_attempt": 1,
        "conclusion": "success", "publication_manifest_sha256": manifest_raw_sha256,
        "input_hashes": inputs,
        "artifact": {"id": artifact["id"], "name": artifact["name"],
            "size_in_bytes": artifact["size_in_bytes"], "digest": digest,
            "created_at": artifact["created_at"], "expires_at": artifact["expires_at"]},
    }


def validate_source_receipt(source: dict, observed_at: datetime | None = None) -> None:
    if (source.get("repository") != REPO or source.get("repository_id") != REPOSITORY_ID
            or source.get("workflow") != WORKFLOW or source.get("conclusion") != "success"
            or source.get("run_id") != SOURCE_RUN_ID or source.get("head_branch") != "main"
            or source.get("head_sha") != SOURCE_COMMIT or source.get("job_id") != SOURCE_JOB_ID
            or source.get("job_name") != JOB_NAME or source.get("run_attempt") != 1
            or source.get("publication_manifest_sha256") != SOURCE_MANIFEST_SHA256
            or not FULL_SHA_RE.fullmatch(str(source.get("head_sha")))):
        raise Refusal("validated source receipt identity mismatch")
    art = source.get("artifact")
    if not isinstance(art, dict) or (type(art.get("id")) is not int or art.get("id") <= 0
            or art.get("name") != f"{ARTIFACT_PREFIX}{SOURCE_RUN_ID}"
            or type(art.get("size_in_bytes")) is not int or not 0 < art.get("size_in_bytes") <= MAX_ARCHIVE_BYTES
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(art.get("digest")))
            or not isinstance(art.get("created_at"), str) or not isinstance(art.get("expires_at"), str)):
        raise Refusal("validated source artifact binding is malformed")
    if (parse_time(art.get("created_at")) > parse_time(art.get("expires_at"))
            or parse_time(art.get("expires_at")) <= (observed_at or datetime.now(timezone.utc))):
        raise Refusal("source artifact has expired")


def require_hosted() -> None:
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise Refusal("artifact download, PNG hashing and public export require GitHub-hosted Ubuntu")


def check_capacity(path: Path = Path(".")) -> int:
    require_hosted()
    free = shutil.disk_usage(path).free
    if free < MIN_FREE_BYTES:
        raise Refusal(f"hosted runner free space {free} is below required {MIN_FREE_BYTES} bytes")
    return free


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise Refusal(f"invalid PNG header: {path.name}")
    import struct
    return struct.unpack(">II", header[16:24])


def extract_archive(archive_path: Path, source: dict, out_dir: Path) -> dict:
    require_hosted()
    validate_source_receipt(source)
    art = source["artifact"]
    if out_dir.exists() or archive_path.is_symlink() or not archive_path.is_file():
        raise Refusal("refusing to overwrite extraction or read an unsafe/missing artifact")
    if archive_path.stat().st_size != art["size_in_bytes"]:
        raise Refusal("native artifact ZIP size mismatch")
    digest = sha256(archive_path)
    if art["digest"] != "sha256:" + digest:
        raise Refusal("native artifact ZIP digest mismatch")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != ZIP_MEMBERS:
                raise Refusal("artifact ZIP differs from exact 8-PNG and 3-receipt-member allowlist")
            expanded = 0
            for info in infos:
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                path = PurePosixPath(info.filename)
                if (info.is_dir() or (kind and kind != stat.S_IFREG) or info.flag_bits & 1
                        or path.is_absolute() or ".." in path.parts or "\\" in info.filename):
                    raise Refusal("artifact ZIP contains a directory, link, encrypted or unsafe member")
                expanded += info.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise Refusal("artifact exceeds bounded extracted size")
            out_dir.mkdir(parents=True)
            for info in infos:
                path = out_dir.joinpath(*PurePosixPath(info.filename).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, path.open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=1 << 20)
                if path.stat().st_size != info.file_size:
                    raise Refusal("extracted member size mismatch")
    except zipfile.BadZipFile as exc:
        raise Refusal("native artifact is not a valid ZIP") from exc
    return {"zip_bytes": archive_path.stat().st_size, "zip_sha256": digest,
            "members": sorted(ZIP_MEMBERS)}


def expected_names(plan: dict) -> tuple[str, ...]:
    if plan.get("status") != "estimated-source-capture-plan" or plan.get("clock_basis") != "ESTIMATED_155_WPM":
        raise Refusal("source capture plan is not the reviewed estimated-clock plan")
    canvas = plan.get("canvas") or {}
    if canvas.get("width") != 3840 or canvas.get("height") != 2160:
        raise Refusal("source plan canvas is not 3840x2160")
    points = plan.get("points")
    if not isinstance(points, list) or len(points) != len(POINTS):
        raise Refusal("source plan must contain the exact eight named review points")
    names = []
    for index, (point, expected) in enumerate(zip(points, POINTS)):
        name, scene, seconds = expected
        if (point.get("name") != name or point.get("scene_id") != scene
                or float(point.get("at_s", -1)) != seconds):
            raise Refusal("source plan point order/name/scene/time differs from the reviewed eight-point plan")
        timestamp = f"{float(point['at_s']):.3f}".rstrip("0").rstrip(".") + "s"
        names.append(f"frame-{index:02d}-at-{timestamp}.png")
    return tuple(names)


def _regular_tree(root: Path) -> dict[str, Path]:
    found = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise Refusal("artifact extraction contains a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise Refusal("artifact extraction contains a non-regular file")
        found[path.relative_to(root).as_posix()] = path
    if set(found) != ZIP_MEMBERS:
        raise Refusal("extracted artifact file inventory differs from exact allowlist")
    return found


def prepare_export(download_dir: Path, source: dict, out_dir: Path) -> dict:
    require_hosted()
    validate_source_receipt(source)
    files = _regular_tree(download_dir)
    plan = _json(files[PLAN_MEMBER])
    names = expected_names(plan)
    source_receipt = _json(files[SOURCE_RECEIPT_MEMBER])
    if (source_receipt.get("status") != "SOURCE_STILLS_CAPTURED"
            or source_receipt.get("source_commit") != source["head_sha"]
            or source_receipt.get("workflow_run_id") != str(source["run_id"])
            or source_receipt.get("workflow_run_attempt") != str(source["run_attempt"])
            or source_receipt.get("event") != "workflow_dispatch"
            or source_receipt.get("publication_manifest_sha256") != source["publication_manifest_sha256"]
            or source_receipt.get("inputs") != source["input_hashes"]):
        raise Refusal("producer receipt does not bind the exact source run, manifest and inputs")
    still_receipt = source_receipt.get("stills")
    contacts = source_receipt.get("contact_sheets")
    if (not isinstance(still_receipt, dict) or set(still_receipt) != set(names)
            or not isinstance(contacts, dict) or set(contacts) != {"contact-sheet.jpg"}):
        raise Refusal("producer receipt PNG/contact-sheet inventory differs from the exact capture set")
    for name in names:
        path = files[f"captures/{name}"]
        if path.stat().st_size <= 24 or path.stat().st_size > MAX_FRAME_BYTES:
            raise Refusal(f"native PNG size is outside limits: {name}")
        if _png_dimensions(path) != (3840, 2160):
            raise Refusal(f"native PNG dimensions mismatch: {name}")
        if sha256(path) != still_receipt[name]:
            raise Refusal(f"native PNG hash differs from producer receipt: {name}")
    if sha256(files[CONTACT_MEMBER]) != contacts["contact-sheet.jpg"]:
        raise Refusal("producer contact-sheet hash differs from native receipt")
    if out_dir.exists():
        raise Refusal("refusing to overwrite an existing public review payload")
    out_dir.mkdir(parents=True)
    for name in names:
        shutil.copyfile(files[f"captures/{name}"], out_dir / name)
    public_plan = {
        "status": "estimated-source-capture-plan",
        "clock_basis": "ESTIMATED_155_WPM",
        "canvas": {"width": 3840, "height": 2160, "fps": 30},
        "points": [{key: point[key] for key in ("name", "scene_id", "at_s", "reason")}
                   for point in plan["points"]],
        "source_run_id": source["run_id"], "source_commit": source["head_sha"],
        "publication_manifest_sha256": source["publication_manifest_sha256"],
    }
    (out_dir / PLAN_NAME).write_text(json.dumps(public_plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    image_rows = [{"name": name, "bytes": (out_dir / name).stat().st_size,
                   "sha256": sha256(out_dir / name), "at_seconds": point[2],
                   "point": point[0], "scene_id": point[1]}
                  for name, point in zip(names, POINTS)]
    receipt = {
        "kind": "f08_wave03_source_stills_public_review_v1",
        "scope": "eight estimated-clock native source stills; not a film render",
        "source": {"repository": REPO, "repository_id": REPOSITORY_ID,
                   "workflow": WORKFLOW, "run_id": source["run_id"],
                   "head_branch": source["head_branch"],
                   "job_id": source["job_id"], "job_name": source["job_name"],
                   "run_attempt": source["run_attempt"], "conclusion": source["conclusion"],
                   "artifact_id": source["artifact"]["id"],
                   "artifact_name": source["artifact"]["name"],
                   "artifact_bytes": source["artifact"]["size_in_bytes"],
                   "artifact_zip_sha256": source["artifact"]["digest"].removeprefix("sha256:"),
                   "artifact_created_at": source["artifact"]["created_at"],
                   "artifact_expires_at": source["artifact"]["expires_at"],
                   "source_commit": source["head_sha"],
                   "publication_manifest_sha256": source["publication_manifest_sha256"]},
        "frames": image_rows,
        "release_tag": f"preview-F08-W03-source-stills-{source['run_id']}",
        "public_assets": sorted(PUBLIC_NAMES),
        "visual_review": "OPEN", "full_film_status": "HELD",
        "av_approval": "NOT_GRANTED", "ready": "NOT_GRANTED",
        "release_approval": "NOT_GRANTED", "library_pointer_updated": False,
    }
    receipt_path = out_dir / RECEIPT_NAME
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = (
        "F08 Babylon Wave03 estimated source stills\n"
        f"Source capture run: {source['run_id']} (successful, attempt {source['run_attempt']})\n"
        f"Source commit: {source['head_sha']}\n"
        "Eight 3840x2160 stills, sampled from an estimated 155 wpm storyboard plan.\n"
        "These images are source review evidence, not a rendered film or approval.\n"
        "Visual review: OPEN. Full film: HELD. AV approval, Ready and release approval: NOT GRANTED.\n"
        "See F08-W03-SOURCE-STILLS-REVIEW-RECEIPT.json for artifact and SHA-256 bindings.\n"
    )
    (out_dir / SUMMARY_NAME).write_text(summary, encoding="utf-8")
    hashed = [*names, PLAN_NAME, RECEIPT_NAME, SUMMARY_NAME]
    (out_dir / SUMS_NAME).write_text("".join(f"{sha256(out_dir / name)}  {name}\n" for name in hashed), encoding="utf-8")
    return receipt


def run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], text=True, capture_output=True, check=False)


def safe_detail(result: subprocess.CompletedProcess) -> str:
    detail = (result.stderr or result.stdout or "no CLI detail").strip()
    detail = re.sub(r"(?i)(authorization:\s*bearer\s+)\S+", r"\1[redacted]", detail)
    detail = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b", "[redacted]", detail)
    return detail[:800]


def _payload(export_dir: Path) -> dict[str, Path]:
    if not export_dir.is_dir() or export_dir.is_symlink():
        raise Refusal("public review payload directory is absent or unsafe")
    paths = {}
    for path in export_dir.iterdir():
        if path.is_symlink() or not path.is_file() or path.name in paths:
            raise Refusal("public payload contains a symlink, non-file or duplicate")
        paths[path.name] = path
    if set(paths) != PUBLIC_NAMES:
        raise Refusal("public payload differs from exact 8 PNG plus 4 safe-text allowlist")
    receipt = _json(paths[RECEIPT_NAME])
    if (receipt.get("visual_review") != "OPEN" or receipt.get("full_film_status") != "HELD"
            or receipt.get("av_approval") != "NOT_GRANTED" or receipt.get("ready") != "NOT_GRANTED"
            or receipt.get("release_approval") != "NOT_GRANTED"
            or receipt.get("library_pointer_updated") is not False):
        raise Refusal("review receipt does not retain mandatory OPEN/HELD status")
    source = receipt.get("source") or {}
    if (source.get("repository") != REPO or source.get("repository_id") != REPOSITORY_ID
            or source.get("workflow") != WORKFLOW or source.get("run_id") != SOURCE_RUN_ID
            or source.get("head_branch") != "main" or source.get("source_commit") != SOURCE_COMMIT
            or source.get("publication_manifest_sha256") != SOURCE_MANIFEST_SHA256
            or type(source.get("job_id")) is not int or source.get("job_name") != JOB_NAME
            or source.get("run_attempt") != 1 or source.get("conclusion") != "success"
            or not FULL_SHA_RE.fullmatch(str(source.get("source_commit")))
            or not SHA_RE.fullmatch(str(source.get("artifact_zip_sha256")))
            or not SHA_RE.fullmatch(str(source.get("publication_manifest_sha256")))
            or source.get("artifact_name") != f"{ARTIFACT_PREFIX}{SOURCE_RUN_ID}"
            or type(source.get("artifact_id")) is not int or source.get("artifact_id") <= 0
            or type(source.get("artifact_bytes")) is not int or not 0 < source.get("artifact_bytes") <= MAX_ARCHIVE_BYTES
            or not SHA_RE.fullmatch(str(source.get("artifact_zip_sha256")))
            or not isinstance(source.get("artifact_created_at"), str)
            or not isinstance(source.get("artifact_expires_at"), str)
            or source.get("job_id") != SOURCE_JOB_ID
            or receipt.get("release_tag") != f"preview-F08-W03-source-stills-{source.get('run_id')}"
            or receipt.get("public_assets") != sorted(PUBLIC_NAMES)):
        raise Refusal("public receipt does not bind the exact run, artifact, commit and payload inventory")
    if (parse_time(source.get("artifact_created_at")) > parse_time(source.get("artifact_expires_at"))
            or parse_time(source.get("artifact_expires_at")) <= datetime.now(timezone.utc)):
        raise Refusal("native source artifact expired before public review export")
    frames = receipt.get("frames")
    if not isinstance(frames, list) or len(frames) != len(FRAME_NAMES):
        raise Refusal("public receipt frame list differs from the exact eight stills")
    for row, (name, point) in zip(frames, zip(FRAME_NAMES, POINTS)):
        path = paths[name]
        if (row.get("name") != name or row.get("bytes") != path.stat().st_size
                or row.get("sha256") != sha256(path) or row.get("at_seconds") != point[2]
                or row.get("point") != point[0] or row.get("scene_id") != point[1]):
            raise Refusal(f"public receipt frame binding mismatch: {name}")
    sums = {}
    for line in paths[SUMS_NAME].read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if not match or match.group(2) in sums:
            raise Refusal("public checksum file is malformed")
        sums[match.group(2)] = match.group(1)
    expected = {name: sha256(path) for name, path in paths.items() if name != SUMS_NAME}
    if sums != expected:
        raise Refusal("public checksum file does not bind the exact payload")
    return paths


def release_notes(tag: str, names: tuple[str, ...]) -> str:
    base = f"https://github.com/{REPO}/releases/download/{tag}"
    links = "\n".join(f"- [{name}]({base}/{name})" for name in names)
    return (
        "# F08 Babylon Wave03 source stills — review pending\n\n"
        "Eight estimated-clock 4K source stills. They are not a rendered film.\n\n"
        f"## Native PNGs\n\n{links}\n\n"
        f"[Safe review receipt]({base}/{RECEIPT_NAME}) · "
        f"[Estimated capture plan]({base}/{PLAN_NAME}) · "
        f"[SHA-256 list]({base}/{SUMS_NAME})\n\n"
        "Visual review remains OPEN. The full film remains HELD; AV approval, Ready and release approval are NOT GRANTED."
    )


def publish_export(export_dir: Path) -> dict:
    require_hosted()
    paths = _payload(export_dir)
    receipt = _json(paths[RECEIPT_NAME])
    source = receipt["source"]
    run_id = source["run_id"]
    tag = f"preview-F08-W03-source-stills-{run_id}"
    expected = {name: {"size": path.stat().st_size, "sha256": sha256(path)} for name, path in paths.items()}
    lookup = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"])
    if lookup.returncode:
        try:
            body = json.loads(lookup.stdout)
        except json.JSONDecodeError:
            body = {}
        if not (lookup.returncode == 1 and lookup.stderr.strip() == "gh: Not Found (HTTP 404)"
                and body.get("status") == "404" and body.get("message") == "Not Found"):
            raise Refusal("release lookup did not return confirmed HTTP 404; no create attempted")
        notes = release_notes(tag, tuple(FRAME_NAMES))
        created = run_gh(["api", "--method", "POST", f"repos/{REPO}/releases",
                          "-f", f"tag_name={tag}", "-f", f"target_commitish={source['source_commit']}",
                          "-f", f"name=F08 Wave03 source-stills review {run_id}",
                          "-f", f"body={notes}", "-F", "draft=false", "-F", "prerelease=true"])
        if created.returncode:
            raise Refusal(f"review release metadata creation failed: {safe_detail(created)}")
        lookup = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"])
        if lookup.returncode:
            raise Refusal("created source-review release could not be read back")
    release = json.loads(lookup.stdout)
    if (release.get("tag_name") != tag or release.get("draft") is not False
            or release.get("prerelease") is not True):
        raise Refusal("existing run-scoped release has wrong tag or review-only state")
    commit = run_gh(["api", f"repos/{REPO}/commits/{tag}"])
    if commit.returncode or json.loads(commit.stdout).get("sha") != source["source_commit"]:
        raise Refusal("run-scoped review tag does not resolve to the exact source commit")
    assets = release.get("assets", [])
    present = {}
    for asset in assets:
        name = asset.get("name")
        if name not in expected or name in present:
            raise Refusal("existing review release has an unexpected or duplicate asset")
        if (asset.get("size") != expected[name]["size"]
                or asset.get("digest") != "sha256:" + expected[name]["sha256"]
                or asset.get("browser_download_url") != f"https://github.com/{REPO}/releases/download/{tag}/{name}"):
            raise Refusal(f"existing review asset differs; overwrite refused: {name}")
        present[name] = asset
    for name, path in paths.items():
        if name not in present:
            upload = run_gh(["release", "upload", tag, str(path), "-R", REPO])
            if upload.returncode:
                raise Refusal(f"public review asset upload failed for {name}: {safe_detail(upload)}")
        fresh = run_gh(["api", f"repos/{REPO}/releases/tags/{tag}"])
        if fresh.returncode:
            raise Refusal("review release readback failed during upload")
        release = json.loads(fresh.stdout)
        present = {item.get("name"): item for item in release.get("assets", [])}
    if set(present) != PUBLIC_NAMES:
        raise Refusal("published review release asset inventory differs from allowlist")
    for name, record in expected.items():
        asset = present[name]
        if asset.get("size") != record["size"] or asset.get("digest") != "sha256:" + record["sha256"]:
            raise Refusal(f"published review asset failed final readback: {name}")
    return {"tag": tag, "release_url": f"https://github.com/{REPO}/releases/tag/{tag}",
            "assets_verified": len(present), "visual_review": "OPEN",
            "full_film_status": "HELD", "ready": "NOT_GRANTED"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-source")
    for key in ("repository", "run", "jobs", "artifacts", "manifest", "out"):
        validate.add_argument(f"--{key}", type=Path, required=True)
    validate.add_argument("--source-run-id", type=int, required=True)
    validate.add_argument("--source-commit", required=True)
    validate.add_argument("--manifest-sha256", required=True)
    sub.add_parser("check-capacity")
    extract = sub.add_parser("extract")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--source", type=Path, required=True)
    extract.add_argument("--out-dir", type=Path, required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--download-dir", type=Path, required=True)
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--out-dir", type=Path, required=True)
    publish = sub.add_parser("publish")
    publish.add_argument("--export-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-source":
            manifest, actual = load_manifest(args.manifest, args.manifest_sha256)
            source = validate_source(_json(args.repository), _json(args.run), _json(args.jobs),
                                     _json(args.artifacts), args.source_run_id, args.source_commit,
                                     manifest, actual)
            args.out.write_text(json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"PASS: exact successful run/artifact and source commit bound; ZIP bytes not fetched")
        elif args.command == "check-capacity":
            print(f"PASS: hosted runner has {check_capacity()} bytes free")
        elif args.command == "extract":
            result = extract_archive(args.archive, _json(args.source), args.out_dir)
            print(f"PASS: native ZIP {result['zip_bytes']} bytes SHA-256 {result['zip_sha256']}; exact 8 PNG inputs")
        elif args.command == "prepare":
            receipt = prepare_export(args.download_dir, _json(args.source), args.out_dir)
            print(f"PASS: prepared {len(receipt['frames'])} public PNGs and safe text receipts; visual review OPEN")
        else:
            print(json.dumps(publish_export(args.export_dir), sort_keys=True))
        return 0
    except (Refusal, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
