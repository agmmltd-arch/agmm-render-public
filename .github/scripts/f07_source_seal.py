#!/usr/bin/env python3
"""Build a hosted-only, non-approved F07 source candidate from the exact public parent.

Production CLI refuses to read archives outside the designated public GitHub Actions
Ubuntu runner. Unit tests use tiny synthetic text-only tar fixtures and call pure
helpers directly; no programme media is opened on the Mac.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import platform
import re
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

REPO = "agmmltd-arch/agmm-render-public"
PARENT_TAG = "F07-r4-actions-full-landscape-4k-20260930194517"
PARENT_RELEASE_ID = 400360556
PARENT_ASSET_ID = 601625680
PARENT_ASSET_NAME = "source.tar.gz"
PARENT_BYTES = 43_650_580
PARENT_SHA256 = "10394b58dad8f1e6131486edb2d9d310b82a923fef2ca6aea50f229cb165bfd7"
CANDIDATE_SHA256 = "d2fdaf282e233a9d9691a11b216361b108dff7228a9dcbd0459b29649fb01962"
REVIEW_RUN_ID = 37168229518
REVIEW_CANDIDATE_SHA256 = CANDIDATE_SHA256
REVIEW_VERDICT = "ACCEPTED_BOUNDED_SOURCE_STILL_CORRECTIONS_ONLY"
CAPTURE_RECEIPT_SHA256 = "6c9f1fb62f5f2bee47cf18158fad8f8e1311a587815d25033771398b2d199cdc"
CAPTURE_CANDIDATE_RECEIPT_SHA256 = "6293f4a39ee2833f258213c02bc2fb540a57dc647430642834b8f27f1f444b9b"
REVIEW_RECEIPT_SHA256 = "f7629c2771ecc158d1d348e6708d61875c2fae7f6a36402affd821ac80c38e11"
OVERLAY = {
    "film/film.js": "cf6ddc29bf0e23ca50173773e43ee2d33ef3af8a1400f4ea3b375077adc3c3aa",
    "film/film.css": "0d17eea12ed4ecac45b5207c35939334549ae970fe047b5e9fb3da9b4435fa07",
    "film/sets_studio.js": "988a0d98b5eb71c3bac0777ee5b02a161ef9e744d7c8bb0e3bcff40385ddea2c",
}
PARENT_PRESERVE = {
    "audio/mix.flac": "5dde65a9a4ee8fb22ade88fcba4167fcc0f4a9b976e0ecd7a29645acc142a49a",
    "film/index.html": "110a1588af73c82f870dbda1e29741123b9ea5c1eacaba798e3f803616d714d5",
    "film/words.js": "c3477711d1fd765c2e519fb0694b9d2ad1bfd55b1e649eea73012b8d4fe7ec54",
    "film/img/octopus-logo-white.svg": "22118fc92c6642202c64f49a20a7ac07765f596bf0052ea213a6c0bd0d79cca7",
    "film/img/octopus-logo.svg": "75935ef3e9f6cd80d0980c7cf2a2228d2dc1121fd65266dc7db17bea1418c112",
}
MAX_MEMBERS = 10_000
MAX_EXPANDED = 8 * 1024**3
CHUNK = 1024 * 1024
FPS = 30
SEGMENT_SECONDS = 8.6
SEGMENTER_SOURCE = "video-autonomy-2026-10-02/v2/films/tools/render_codespace_film.py::segments (lines 95-102)"
SEGMENTER_SOURCE_SHA256 = "8c5fa848a5845080733a6f9e76c67b54cf799a9941d31f553af0ee3b939a3398"


def sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(CHUNK)
            if not block:
                break
            size += len(block)
            h.update(block)
    return h.hexdigest(), size


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hosted_guard() -> None:
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("refusing archive IO outside public GitHub Actions Ubuntu")
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise RuntimeError("refusing IO in an unexpected repository")


def validate_public_repo(meta: dict) -> None:
    if (meta.get("full_name") != REPO or meta.get("private") is not False
            or meta.get("visibility") != "public" or meta.get("default_branch") != "main"):
        raise ValueError("expected exact public repository metadata before source download")


def validate_parent_release(release: dict) -> dict:
    if (release.get("id") != PARENT_RELEASE_ID or release.get("tag_name") != PARENT_TAG
            or release.get("draft") is not False or release.get("prerelease") is not False):
        raise ValueError("release identity/status differs from the exact retained F07 parent")
    matches = [a for a in release.get("assets", []) if a.get("id") == PARENT_ASSET_ID]
    named = [a for a in release.get("assets", []) if a.get("name") == PARENT_ASSET_NAME]
    if len(matches) != 1 or len(named) != 1 or named[0].get("id") != PARENT_ASSET_ID:
        raise ValueError("parent source asset ID is missing or duplicated")
    asset = matches[0]
    if (asset.get("name") != PARENT_ASSET_NAME or asset.get("state") != "uploaded"
            or asset.get("size") != PARENT_BYTES or asset.get("digest") != "sha256:" + PARENT_SHA256):
        raise ValueError("parent source asset metadata differs from the pinned receipt")
    return asset


def _normal_member(name: str) -> str:
    if not name or name.startswith("/") or "\\" in name:
        raise ValueError(f"unsafe archive member path: {name[:160]}")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"archive traversal path: {name[:160]}")
    if not parts:
        return "."
    return "/".join(parts)


def safe_extract_and_hash(archive: Path, root: Path) -> dict[str, dict]:
    """Extract regular files only, streaming each file; return exact file hashes."""
    root.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    files: dict[str, dict] = {}
    total = 0
    try:
        with tarfile.open(archive, "r:gz") as tf:
            members = tf.getmembers()
            if not members or len(members) > MAX_MEMBERS:
                raise ValueError("parent archive is empty or exceeds member limit")
            for member in members:
                name = _normal_member(member.name)
                if name in seen:
                    raise ValueError(f"duplicate normalized archive member: {name}")
                seen.add(name)
                if name == ".":
                    if not member.isdir():
                        raise ValueError("archive root is not a directory")
                    continue
                if not (member.isdir() or member.isfile()):
                    raise ValueError(f"non-regular archive member rejected: {name}")
                if member.isfile():
                    if member.size < 0:
                        raise ValueError(f"negative member length: {name}")
                    total += member.size
                    if total > MAX_EXPANDED:
                        raise ValueError("expanded archive exceeds 8 GiB limit")
            for member in members:
                name = _normal_member(member.name)
                if name == ".":
                    continue
                dest = root.joinpath(*PurePosixPath(name).parts)
                if root.resolve() not in dest.resolve().parents:
                    raise ValueError(f"archive destination escapes root: {name}")
                if member.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(member)
                if src is None:
                    raise ValueError(f"cannot read archive member: {name}")
                h = hashlib.sha256()
                count = 0
                with src, dest.open("xb") as out:
                    while True:
                        block = src.read(CHUNK)
                        if not block:
                            break
                        count += len(block)
                        if count > member.size:
                            raise ValueError(f"member larger than header: {name}")
                        h.update(block)
                        out.write(block)
                if count != member.size:
                    raise ValueError(f"member shorter than header: {name}")
                os.chmod(dest, stat.S_IMODE(member.mode) & 0o755)
                files[name] = {"sha256": h.hexdigest(), "bytes": count}
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise ValueError(f"parent archive cannot be safely extracted: {exc}") from exc
    if not files:
        raise ValueError("parent archive contains no files")
    return files


def parse_sha_manifest(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?([A-Za-z0-9._/-]+)", line)
        if not m or ".." in PurePosixPath(m.group(2)).parts or m.group(2) in entries:
            raise ValueError("parent SHA256SUMS.txt is malformed or unsafe")
        entries[m.group(2)] = m.group(1)
    if not entries:
        raise ValueError("parent SHA256SUMS.txt has no entries")
    return entries


def verify_parent_manifest(root: Path, files: dict[str, dict]) -> dict[str, str]:
    manifest_name = "SHA256SUMS.txt"
    if manifest_name not in files:
        raise ValueError("parent package is missing SHA256SUMS.txt")
    manifest = parse_sha_manifest(root / manifest_name)
    actual_paths = set(files) - {manifest_name}
    if set(manifest) != actual_paths:
        raise ValueError("parent checksum manifest does not cover the exact extracted file set")
    for name, digest in manifest.items():
        if files[name]["sha256"] != digest:
            raise ValueError("parent internal checksum mismatch: " + name)
    for name, expected in PARENT_PRESERVE.items():
        if name not in files or files[name]["sha256"] != expected:
            raise ValueError("pinned parent preservation hash mismatch: " + name)
    return manifest


def validate_candidate(candidate_dir: Path, candidate_receipt: dict, capture: dict,
                       capture_bytes: bytes, review: dict, review_bytes: bytes) -> dict[str, dict]:
    if (candidate_receipt.get("schema") != "f07-overlay-candidate-text-provenance-v1"
            or candidate_receipt.get("kind") != "source-candidate-overlay-text-only"
            or candidate_receipt.get("candidate_status") != "ISOLATED_NOT_ADOPTED"
            or candidate_receipt.get("capture_class") != "source_composition_not_final_master"
            or candidate_receipt.get("approval") != "NOT_GRANTED"
            or candidate_receipt.get("archive_release") is not None
            or candidate_receipt.get("published_overlay_archive_identity") is not None):
        raise ValueError("candidate receipt does not truthfully describe isolated, unapproved text")
    parent = candidate_receipt.get("parent_source", {})
    if (parent.get("repository") != REPO or parent.get("release") != PARENT_TAG
            or parent.get("asset_id") != PARENT_ASSET_ID or parent.get("asset_name") != PARENT_ASSET_NAME
            or parent.get("bytes") != PARENT_BYTES or parent.get("sha256") != PARENT_SHA256):
        raise ValueError("candidate receipt does not bind exact parent archive identity")
    if (review.get("kind") != "F07-isolated-source-still-review"
            or review.get("run_id") != REVIEW_RUN_ID or review.get("candidate_sha256") != CANDIDATE_SHA256
            or review.get("verdict") != REVIEW_VERDICT
            or review.get("viewed_required") != 12 or review.get("viewed_done") != 12
            or review.get("production_release_approval") != "NOT_GRANTED"
            or review.get("owner_adoption") != "NOT_PERFORMED"):
        raise ValueError("source-review receipt is not the exact bounded still-only review")
    if sha256_bytes(review_bytes) != REVIEW_RECEIPT_SHA256:
        raise ValueError("independent source-still review receipt bytes differ from the reviewed receipt")
    if (sha256_bytes(capture_bytes) != CAPTURE_RECEIPT_SHA256
            or review.get("capture_receipt_sha256") != CAPTURE_RECEIPT_SHA256
            or review.get("film_sha256") != OVERLAY["film/film.js"]
            or capture.get("kind") != "f07-source-composition-review-capture"
            or capture.get("editorial_status") != "NOT_REVIEWED"
            or capture.get("release_approval") != "NOT_GRANTED"
            or capture.get("candidate_receipt_sha256") != CAPTURE_CANDIDATE_RECEIPT_SHA256
            or capture.get("overlay_candidate_sha256") != CANDIDATE_SHA256
            or capture.get("source_release") != PARENT_TAG
            or capture.get("source_release_id") != PARENT_RELEASE_ID
            or capture.get("source_asset_id") != PARENT_ASSET_ID
            or capture.get("source_sha256") != PARENT_SHA256):
        raise ValueError("review is not bound to the exact unapproved hosted source-capture receipt")
    if review.get("frames") != capture.get("frames"):
        raise ValueError("reviewed frame rows differ from the authenticated capture receipt")
    if sha256_file(candidate_dir / "candidate-source-receipt.json")[0] != CAPTURE_CANDIDATE_RECEIPT_SHA256:
        raise ValueError("capture receipt does not bind the candidate source receipt on disk")
    if set(candidate_receipt.get("files", {})) != set(OVERLAY):
        raise ValueError("candidate receipt must bind exactly three source files")
    manifest = parse_sha_manifest(candidate_dir / "film-overlay.sha256")
    if set(manifest) != set(OVERLAY):
        raise ValueError("candidate manifest must bind exactly the three approved paths")
    expected_files = set(OVERLAY) | {"film-overlay.sha256", "candidate-source-receipt.json"}
    actual_files = {p.relative_to(candidate_dir).as_posix() for p in candidate_dir.rglob("*") if p.is_file()}
    if actual_files != expected_files or any(p.is_symlink() for p in candidate_dir.rglob("*")):
        raise ValueError("candidate folder contains missing, extra, or linked content")
    rows = {}
    for rel, expected_sha in OVERLAY.items():
        path = candidate_dir / rel
        digest, size = sha256_file(path)
        claimed = candidate_receipt["files"].get(rel)
        if digest != expected_sha or manifest.get(rel) != digest or claimed != {"bytes": size, "sha256": digest}:
            raise ValueError("candidate source bytes do not match exact manifest/receipt: " + rel)
        rows[rel] = {"sha256": digest, "bytes": size}
    if capture.get("overlay_files") != rows:
        raise ValueError("capture receipt source bytes differ from the candidate overlay")
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    if sha256_bytes(canonical) != CANDIDATE_SHA256 or candidate_receipt.get("candidate_sha256") != CANDIDATE_SHA256:
        raise ValueError("candidate composite digest mismatch")
    return rows


def native_segments(duration: float, seglen: float = SEGMENT_SECONDS) -> list[dict]:
    """Exact `render_codespace_film.segments` rule; do not round-trip through a duration guess."""
    n = int(math.floor(duration / seglen + 1e-9))
    out = []
    for k in range(n):
        t0 = round(k * seglen, 3)
        length = round(seglen if k < n - 1 else duration - t0, 3)
        out.append({"i": "%02d" % (k + 1), "t0": t0, "len": length,
                    "frames": int(round(length * FPS))})
    if not out or out[0]["t0"] != 0 or abs(out[-1]["t0"] + out[-1]["len"] - duration) > 0.001:
        raise ValueError("native segmentation failed to cover the exact composition duration")
    return out


def derive_part_plan(root: Path, parent_sha_manifest: dict[str, str], package_sha: str) -> dict:
    index = root / "film/index.html"
    if parent_sha_manifest.get("film/index.html") != PARENT_PRESERVE["film/index.html"]:
        raise ValueError("part grid is not bound to the known parent index hash")
    index_sha, _ = sha256_file(index)
    if index_sha != PARENT_PRESERVE["film/index.html"]:
        raise ValueError("extracted source index differs from parent checksum")
    html = index.read_text(encoding="utf-8")
    dur = re.search(r'data-duration="([0-9]+(?:\.[0-9]+)?)"', html)
    segvar = re.search(r"window\.(F07_SEG) = null;", html)
    if not dur or not segvar or 'data-composition-id="f07"' not in html:
        raise ValueError("exact source index lacks F07 duration or F07_SEG contract")
    duration = float(dur.group(1))
    segments = native_segments(duration)
    return {
        "schema": "f07-native-render-part-plan-v1",
        "status": "PLAN_ONLY_NOT_DISPATCHED",
        "source_package_sha256": package_sha,
        "source_index_sha256": index_sha,
        "composition": "film",
        "composition_id": "f07",
        "segvar": segvar.group(1),
        "duration_seconds": duration,
        "segment_seconds": SEGMENT_SECONDS,
        "fps": FPS,
        "segment_count": len(segments),
        "expected_total_frames": sum(s["frames"] for s in segments),
        "segments": segments,
        "renderer_contract": {
            "workflow": ".github/workflows/agmm-film.yml",
            "segmenter_source": SEGMENTER_SOURCE,
            "segmenter_source_sha256": SEGMENTER_SOURCE_SHA256,
            "workflow_inputs": ["release", "package_sha256", "comp", "segvar", "segs", "res", "workers", "tag", "remote_only", "assemble_full", "apply_source_overlay", "fid"],
            "source_overlay_after_seal": False,
            "reuse_status": "NOT_ASSESSED_SOURCE_LINEAGE_UNVERIFIED",
            "previous_preview": "6_of_73_artifacts_expired_2026-10-01",
            "later_segment_patch_runs": [36771687018, 36772600213],
        },
        "approval": "NOT_GRANTED",
        "editorial_review": "NOT_PERFORMED_BY_SEAL",
    }


def _write_checksums(root: Path) -> dict[str, dict]:
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.relative_to(root).as_posix() != "SHA256SUMS.txt")
    rows = {}
    lines = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        digest, size = sha256_file(path)
        rows[rel] = {"sha256": digest, "bytes": size}
        lines.append(f"{digest}  ./{rel}")
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


def write_deterministic_tar(root: Path, output: Path) -> None:
    """Write stable tar/gzip metadata so identical input bytes produce the same seal SHA/tag."""
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tf:
                root_info = tarfile.TarInfo(".")
                root_info.type = tarfile.DIRTYPE
                root_info.mode = 0o755
                root_info.uid = root_info.gid = 0
                root_info.uname = root_info.gname = ""
                root_info.mtime = 0
                tf.addfile(root_info)
                entries = sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix())
                for path in entries:
                    rel = "./" + path.relative_to(root).as_posix()
                    if path.is_symlink():
                        raise ValueError(f"symlink in sealed package: {rel}")
                    info = tarfile.TarInfo(rel)
                    info.mode = stat.S_IMODE(path.stat().st_mode) & 0o777
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    if path.is_dir():
                        info.type = tarfile.DIRTYPE
                        info.size = 0
                        tf.addfile(info)
                    elif path.is_file():
                        info.type = tarfile.REGTYPE
                        info.size = path.stat().st_size
                        with path.open("rb") as source:
                            tf.addfile(info, source)
                    else:
                        raise ValueError(f"non-regular path in sealed package: {rel}")


def make_sealed_package(parent_archive: Path, repo_meta: dict, release_meta: dict,
                        candidate_dir: Path, capture: dict, capture_bytes: bytes,
                        review: dict, review_bytes: bytes, out_dir: Path) -> dict:
    """Build the candidate package on the hosted runner; testable with synthetic text archives."""
    validate_public_repo(repo_meta)
    validate_parent_release(release_meta)
    parent_sha, parent_bytes = sha256_file(parent_archive)
    if parent_sha != PARENT_SHA256 or parent_bytes != PARENT_BYTES:
        raise ValueError("downloaded parent package differs from pinned bytes/SHA256")
    candidate_receipt = json.loads((candidate_dir / "candidate-source-receipt.json").read_text(encoding="utf-8"))
    candidate_files = validate_candidate(candidate_dir, candidate_receipt, capture, capture_bytes, review, review_bytes)
    out_dir.mkdir(parents=True, exist_ok=False)
    package_dir = out_dir / "package"
    parent_files = safe_extract_and_hash(parent_archive, package_dir)
    old_manifest = verify_parent_manifest(package_dir, parent_files)
    for rel, digest in OVERLAY.items():
        path = package_dir / rel
        if rel not in parent_files:
            raise ValueError("parent source is missing overlay target: " + rel)
        before = parent_files[rel]["sha256"]
        shutil.copyfile(candidate_dir / rel, path)
        after, n = sha256_file(path)
        if after != digest or n != candidate_files[rel]["bytes"]:
            raise ValueError("copied source candidate did not preserve exact bytes: " + rel)
    new_files = _write_checksums(package_dir)
    if set(new_files) != set(parent_files) - {"SHA256SUMS.txt"}:
        raise ValueError("seal changed package file membership")
    changed = {name for name in new_files if parent_files[name]["sha256"] != new_files[name]["sha256"]}
    if changed != set(OVERLAY):
        raise ValueError("sealed package changed files outside the exact three-file overlay")
    for name, digest in PARENT_PRESERVE.items():
        if new_files[name]["sha256"] != digest:
            raise ValueError("sealed source/media preservation check failed: " + name)
    static = package_dir / "static_check.py"
    if not static.is_file():
        raise ValueError("parent package has no static_check.py")
    # Text-only syntax/static checks; actual film rendering is not performed here.
    import subprocess
    for path in (package_dir / "film/film.js", package_dir / "film/sets_studio.js"):
        p = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        if p.returncode:
            raise ValueError(f"node syntax check failed for {path.name}: {p.stderr[-500:]}")
    p = subprocess.run(["python3", str(static)], cwd=package_dir, capture_output=True, text=True)
    if p.returncode:
        raise ValueError("package static_check failed: " + (p.stderr or p.stdout)[-500:])
    # Verify the just-written checksum manifest against every regular file.
    for name, row in new_files.items():
        digest, size = sha256_file(package_dir / name)
        if digest != row["sha256"] or size != row["bytes"]:
            raise ValueError("post-seal package recheck failed: " + name)
    new_manifest = parse_sha_manifest(package_dir / "SHA256SUMS.txt")
    if set(new_manifest) != set(new_files) or any(new_manifest[n] != new_files[n]["sha256"] for n in new_files):
        raise ValueError("regenerated package checksum manifest does not match exact output files")
    archive_out = out_dir / PARENT_ASSET_NAME
    write_deterministic_tar(package_dir, archive_out)
    package_sha, package_bytes = sha256_file(archive_out)
    plan = derive_part_plan(package_dir, old_manifest, package_sha)
    part_plan_path = out_dir / "part-plan.json"
    part_plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt = {
        "schema": "f07-full-source-candidate-seal-v1",
        "kind": "f07-source-package-candidate",
        "status": "SEALED_CANDIDATE_NOT_APPROVED",
        "parent": {"repository": REPO, "release_id": PARENT_RELEASE_ID, "release_tag": PARENT_TAG,
                   "asset_id": PARENT_ASSET_ID, "asset_name": PARENT_ASSET_NAME,
                   "bytes": parent_bytes, "sha256": parent_sha},
        "candidate": {"composite_sha256": CANDIDATE_SHA256, "files": candidate_files,
                      "capture_review_run_id": REVIEW_RUN_ID,
                      "capture_receipt_sha256": CAPTURE_RECEIPT_SHA256,
                      "capture_review_receipt_sha256": sha256_bytes(review_bytes),
                      "bounded_still_verdict": REVIEW_VERDICT,
                      "owner_adoption": "NOT_PERFORMED", "production_release_approval": "NOT_GRANTED"},
        "sealed_package": {"asset_name": PARENT_ASSET_NAME, "bytes": package_bytes, "sha256": package_sha,
                           "changed_file_paths": sorted(changed), "package_file_count": len(new_files) + 1},
        "preservation": {name: new_files[name] for name in sorted(PARENT_PRESERVE)},
        "part_plan": {"path": part_plan_path.name, "sha256": sha256_bytes(part_plan_path.read_bytes()),
                      "status": plan["status"], "segment_count": plan["segment_count"],
                      "reuse_status": plan["renderer_contract"]["reuse_status"]},
        "approval": "NOT_GRANTED",
        "render_dispatched": False,
        "media_decoded_or_rendered": False,
        "release_tag": f"F07-source-candidate-{package_sha[:16]}",
    }
    receipt_path = out_dir / "source-seal-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    m = sub.add_parser("check-metadata", help="authenticate exact public parent before source download")
    m.add_argument("--repo-json", type=Path, required=True)
    m.add_argument("--release-json", type=Path, required=True)
    c = sub.add_parser("check-candidate", help="authenticate text-only candidate/receipts before source download")
    c.add_argument("--candidate-dir", type=Path, required=True)
    c.add_argument("--capture-receipt", type=Path, required=True)
    c.add_argument("--review-json", type=Path, required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--parent-archive", type=Path, required=True)
    p.add_argument("--repo-json", type=Path, required=True)
    p.add_argument("--release-json", type=Path, required=True)
    p.add_argument("--candidate-dir", type=Path, required=True)
    p.add_argument("--capture-receipt", type=Path, required=True)
    p.add_argument("--review-json", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args()
    hosted_guard()
    if a.command == "check-metadata":
        validate_public_repo(json.loads(a.repo_json.read_text()))
        validate_parent_release(json.loads(a.release_json.read_text()))
        print("exact public repository and retained parent release/asset metadata verified")
        return 0
    if a.command == "check-candidate":
        candidate_receipt_path = a.candidate_dir / "candidate-source-receipt.json"
        capture_bytes = a.capture_receipt.read_bytes()
        review_bytes = a.review_json.read_bytes()
        validate_candidate(a.candidate_dir, json.loads(candidate_receipt_path.read_text()),
                           json.loads(a.capture_receipt.read_text()), capture_bytes,
                           json.loads(a.review_json.read_text()), review_bytes)
        print("exact isolated three-file candidate and bounded source-still receipts verified")
        return 0
    receipt = make_sealed_package(a.parent_archive, json.loads(a.repo_json.read_text()),
                                  json.loads(a.release_json.read_text()), a.candidate_dir,
                                  json.loads(a.capture_receipt.read_text()), a.capture_receipt.read_bytes(),
                                  json.loads(a.review_json.read_text()), a.review_json.read_bytes(), a.out_dir)
    print(json.dumps({"status": receipt["status"], "release_tag": receipt["release_tag"],
                      "package_sha256": receipt["sealed_package"]["sha256"],
                      "segments": receipt["part_plan"]["segment_count"],
                      "approval": receipt["approval"], "render_dispatched": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
