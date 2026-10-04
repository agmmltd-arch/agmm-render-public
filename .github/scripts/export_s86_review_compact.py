"""Linux-only export of one exact S86 run's compact JPEG and TEXT review evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import zipfile

REPO = "agmmltd-arch/agmm-render-public"
RENDER_RUN_ID = 37171852324
RENDER_HEAD_SHA = "fddd199eecae2a4774bfc9f7c041320619cfce0f"
SOURCE_SHA256 = "666a90579d57f2bd5c2abed41e55b5dad3fff790f93707d79b2929bddf1c93b6"
PARTS_SHA256 = "e995d9d0354b808714bf89e2a082a98200a8ef92733d1896181635dfecffbb88"
MIX_SHA256 = "0c252cdf6e412fc2ccadcdb29b940d6a23b7c527276ebf79da468b7f633df436"
INPUT_ARTIFACT_ID = 11291104171
INPUT_ARTIFACT_NAME = "S86-quote-final-20261004-EXACT-INPUT"
INPUT_ARTIFACT_SIZE = 27276224
INPUT_ARTIFACT_DIGEST = "sha256:b187a1c98a088b10cc6475cd95ec19a236cd7b86a1b58c2e41287918c50c3793"
COMPACT_ARTIFACT_NAME = "S86-quote-final-20261004-REVIEW-COMPACT"
COMPACT_ARTIFACT_ID = 11291958626
COMPACT_ARTIFACT_SIZE = 2507756
COMPACT_ARTIFACT_DIGEST = "sha256:2afd28726b6bd59e69c9b68ddfb2975312d90dbbe7cc69be76eb6c5c4186db69"
MASTERS_ARTIFACT_ID = 11292320586
MASTERS_ARTIFACT_NAME = "S86-quote-final-20261004-FINAL-MASTERS"
MASTERS_ARTIFACT_SIZE = 383964779
MASTERS_ARTIFACT_DIGEST = "sha256:940096ef373f68f7ec0515e005ec02cb1bacc6720e67a782fa029ea16c2483b3"
ALLOWED_COMPACT_TEXT = {"TECHNICAL-EVIDENCE.json", "SHA256SUMS.txt"}
MAX_COMPACT_ZIP_BYTES = 25_000_000
MAX_INPUT_ZIP_BYTES = 40_000_000
MAX_JPEGS = 120
MAX_JPEG_BYTES = 5_000_000
MAX_TOTAL_JPEG_BYTES = 15_000_000
MAX_TEXT_BYTES = 1_000_000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def hosted_guard():
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("GitHub Actions Linux required before file/archive IO")
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise RuntimeError("unexpected repository")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise RuntimeError("export workflow must run from main")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_member(name):
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ValueError("invalid archive member name")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("unsafe archive path")
    if path.as_posix() != name.rstrip("/"):
        raise ValueError("non-normalized archive path")
    return path


def check_repo(repo):
    if (repo.get("full_name") != REPO or repo.get("private") is not False
            or repo.get("visibility") != "public"):
        raise ValueError("repository must be the exact public review repository")


def check_render_run(run):
    if (run.get("id") != RENDER_RUN_ID or run.get("head_sha") != RENDER_HEAD_SHA
            or run.get("head_branch") != "main" or run.get("event") != "workflow_dispatch"
            or run.get("status") != "completed" or run.get("conclusion") != "success"):
        raise ValueError("native final-render run ID/head/status/conclusion mismatch")


def check_export_head(current_main, expected):
    expected_sha = expected.get("export_head_sha")
    if not isinstance(expected_sha, str) or not HEX40.fullmatch(expected_sha):
        raise ValueError("missing exact exporter commit SHA")
    if current_main.get("object", {}).get("sha") != expected_sha:
        raise ValueError("exporter commit is not the current public main head")
    if os.environ.get("GITHUB_SHA") != expected_sha:
        raise ValueError("workflow checkout SHA does not match current public main head")


def check_artifact(artifact, *, artifact_id, artifact_name, artifact_size, artifact_digest, label):
    if (artifact.get("id") != artifact_id or artifact.get("name") != artifact_name
            or artifact.get("size_in_bytes") != artifact_size
            or artifact.get("digest") != artifact_digest or artifact.get("expired") is not False):
        raise ValueError(label + " artifact ID/name/size/digest/expiry mismatch")
    workflow_run = artifact.get("workflow_run") or {}
    if (workflow_run.get("id") != RENDER_RUN_ID
            or workflow_run.get("head_sha") != RENDER_HEAD_SHA
            or workflow_run.get("head_branch") != "main"):
        raise ValueError(label + " artifact is not bound to the exact native render run")


def check_metadata(repo, run, compact_artifact, input_artifact, masters_artifact,
                   current_main, expected):
    check_repo(repo)
    check_render_run(run)
    check_export_head(current_main, expected)
    compact_id = expected.get("compact_artifact_id")
    compact_size = expected.get("compact_artifact_size")
    compact_digest = expected.get("compact_artifact_digest")
    if (compact_id != COMPACT_ARTIFACT_ID or compact_size != COMPACT_ARTIFACT_SIZE
            or compact_digest != COMPACT_ARTIFACT_DIGEST):
        raise ValueError("compact artifact does not match the pinned final-run artifact")
    check_artifact(compact_artifact, artifact_id=compact_id,
                   artifact_name=COMPACT_ARTIFACT_NAME, artifact_size=compact_size,
                   artifact_digest=compact_digest, label="compact")
    check_artifact(input_artifact, artifact_id=INPUT_ARTIFACT_ID,
                   artifact_name=INPUT_ARTIFACT_NAME, artifact_size=INPUT_ARTIFACT_SIZE,
                   artifact_digest=INPUT_ARTIFACT_DIGEST, label="exact-input")
    check_artifact(masters_artifact, artifact_id=MASTERS_ARTIFACT_ID,
                   artifact_name=MASTERS_ARTIFACT_NAME, artifact_size=MASTERS_ARTIFACT_SIZE,
                   artifact_digest=MASTERS_ARTIFACT_DIGEST, label="final-masters")


def _zip_entries(archive, *, max_zip_bytes, label, allowed_dirs=None):
    infos = archive.infolist()
    if not infos:
        raise ValueError(label + " ZIP is empty")
    seen = set()
    for entry in infos:
        path = safe_member(entry.filename)
        name = path.as_posix()
        if name in seen:
            raise ValueError(label + " ZIP has duplicate normalized paths")
        seen.add(name)
        mode = entry.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError(label + " ZIP contains a symlink")
        if entry.is_dir():
            if allowed_dirs is not None and name not in allowed_dirs:
                raise ValueError(label + " ZIP has an unexpected directory")
            continue
        if entry.file_size <= 0 or entry.file_size > max_zip_bytes:
            raise ValueError(label + " ZIP has an empty or oversized member")
    return {entry.filename: entry for entry in infos if not entry.is_dir()}


def read_bound_input_receipt(input_zip):
    if Path(input_zip).stat().st_size > MAX_INPUT_ZIP_BYTES:
        raise ValueError("exact-input artifact ZIP exceeds its bound")
    with zipfile.ZipFile(input_zip) as archive:
        entries = _zip_entries(archive, max_zip_bytes=MAX_INPUT_ZIP_BYTES, label="exact-input")
        receipts = [name for name in entries if PurePosixPath(name).name == "INPUT-RECEIPT.json"]
        if len(receipts) != 1:
            raise ValueError("exact-input artifact must contain exactly one INPUT-RECEIPT.json")
        name = receipts[0]
        info = entries[name]
        if info.file_size > MAX_TEXT_BYTES:
            raise ValueError("INPUT-RECEIPT.json must be a bounded TEXT file")
        receipt = json.loads(archive.read(info).decode("utf-8"))
    if (receipt.get("kind") != "agmm_short_exact_input_receipt"
            or receipt.get("source_sha256") != SOURCE_SHA256
            or receipt.get("parts_sha256") != PARTS_SHA256
            or receipt.get("mix_sha256") != MIX_SHA256):
        raise ValueError("source/parts/mix identity does not match the pinned S86 input")
    return receipt, archive_namelist_safe(input_zip)


def archive_namelist_safe(input_zip):
    with zipfile.ZipFile(input_zip) as archive:
        names = []
        for entry in archive.infolist():
            names.append(safe_member(entry.filename).as_posix())
    return sorted(names)


def parse_sums(data):
    sums = {}
    for number, line in enumerate(data.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        bits = line.split(maxsplit=1)
        if len(bits) != 2 or not HEX64.fullmatch(bits[0]):
            raise ValueError(f"malformed SHA256SUMS.txt line {number}")
        filename = bits[1].lstrip(" *")
        safe_member(filename)
        if filename in sums:
            raise ValueError("duplicate SHA256SUMS entry")
        sums[filename] = bits[0]
    if not sums:
        raise ValueError("SHA256SUMS.txt is empty")
    return sums


def check_technical_evidence(evidence, sums, input_receipt):
    if (evidence.get("kind") != "agmm_short_remote_technical_evidence"
            or evidence.get("technical_status") != "PASS"
            or evidence.get("editorial_status") != "NOT_REVIEWED"
            or evidence.get("publication_status") != "NOT_REQUESTED"):
        raise ValueError("technical receipt status/schema mismatch")
    masters = evidence.get("masters")
    if not isinstance(masters, list):
        raise ValueError("technical receipt has no master identity list")
    master_by_name = {}
    for row in masters:
        if not isinstance(row, dict) or not isinstance(row.get("file"), str):
            raise ValueError("malformed master identity row")
        name = PurePosixPath(row["file"]).name
        if name in master_by_name:
            raise ValueError("duplicate master name in technical receipt")
        digest = row.get("sha256")
        if not isinstance(digest, str) or not HEX64.fullmatch(digest):
            raise ValueError("invalid master SHA-256 in technical receipt")
        if row.get("full_decode") != "PASS":
            raise ValueError("master full-decode receipt is not PASS")
        master_by_name[name] = digest
    required_masters = {"FINAL.mp4", "FINAL-4K.mp4"}
    if set(master_by_name) != required_masters:
        raise ValueError("technical receipt must bind exactly the 1080 and 4K S86 masters")
    for name, digest in master_by_name.items():
        if sums.get(name) != digest:
            raise ValueError("master SHA-256 differs from SHA256SUMS.txt: " + name)
    review = evidence.get("review")
    if not isinstance(review, dict) or review.get("master") != "FINAL.mp4":
        raise ValueError("review sample receipt must name the 1080 master")
    if review.get("contact_sheet") != "CONTACT-SHEET.jpg":
        raise ValueError("review contact-sheet identity is missing")
    if not isinstance(review.get("contact_sheet_sha256"), str) or not HEX64.fullmatch(review["contact_sheet_sha256"]):
        raise ValueError("review contact-sheet SHA-256 is invalid")
    times = review.get("times")
    if not isinstance(times, list) or not times:
        raise ValueError("review sample times are missing")
    expected_jpegs = {"review/CONTACT-SHEET.jpg": review["contact_sheet_sha256"]}
    for row in times:
        if not isinstance(row, dict) or not isinstance(row.get("file"), str):
            raise ValueError("malformed review sample record")
        filename = row["file"]
        if PurePosixPath(filename).name != filename or not filename.lower().endswith(".jpg"):
            raise ValueError("unsafe review JPEG name")
        if filename == "CONTACT-SHEET.jpg":
            raise ValueError("contact sheet duplicated in review sample list")
        digest = row.get("sha256")
        if not isinstance(digest, str) or not HEX64.fullmatch(digest):
            raise ValueError("invalid review JPEG SHA-256")
        path = "review/" + filename
        if path in expected_jpegs:
            raise ValueError("duplicate review JPEG receipt name")
        expected_jpegs[path] = digest
    return expected_jpegs, master_by_name, review


def export(input_zip, compact_zip, repo_json, render_run_json, compact_meta_json,
           input_meta_json, masters_meta_json, current_main_json, expected_json, out_dir):
    hosted_guard()
    repo = read_json(repo_json)
    run = read_json(render_run_json)
    compact_meta = read_json(compact_meta_json)
    input_meta = read_json(input_meta_json)
    masters_meta = read_json(masters_meta_json)
    current_main = read_json(current_main_json)
    expected = read_json(expected_json)
    check_metadata(repo, run, compact_meta, input_meta, masters_meta, current_main, expected)

    compact_size = Path(compact_zip).stat().st_size
    if compact_size > MAX_COMPACT_ZIP_BYTES:
        raise ValueError("compact artifact ZIP exceeds its bound")
    if compact_size != expected["compact_artifact_size"]:
        raise ValueError("downloaded compact artifact byte size mismatch")
    if sha256_file(compact_zip) != expected["compact_artifact_digest"].removeprefix("sha256:"):
        raise ValueError("downloaded compact artifact digest mismatch")
    if Path(input_zip).stat().st_size != INPUT_ARTIFACT_SIZE:
        raise ValueError("downloaded exact-input artifact byte size mismatch")
    if sha256_file(input_zip) != INPUT_ARTIFACT_DIGEST.removeprefix("sha256:"):
        raise ValueError("downloaded exact-input artifact digest mismatch")
    input_receipt, input_members = read_bound_input_receipt(input_zip)

    with zipfile.ZipFile(compact_zip) as archive:
        entries = _zip_entries(archive, max_zip_bytes=MAX_COMPACT_ZIP_BYTES, label="compact",
                               allowed_dirs={"review"})
        images = {}
        texts = {}
        total_jpeg_bytes = 0
        for name, entry in entries.items():
            path = safe_member(name)
            if (len(path.parts) == 2 and path.parts[0] == "review"
                    and path.suffix.lower() == ".jpg"):
                if entry.file_size > MAX_JPEG_BYTES:
                    raise ValueError("oversized review JPEG")
                images[name] = entry
                total_jpeg_bytes += entry.file_size
            elif name in ALLOWED_COMPACT_TEXT:
                if entry.file_size > MAX_TEXT_BYTES:
                    raise ValueError("oversized compact TEXT receipt")
                texts[name] = entry
            else:
                raise ValueError("compact artifact contains a member outside the exact JPEG/TEXT allowlist")
        if not images or len(images) > MAX_JPEGS or total_jpeg_bytes > MAX_TOTAL_JPEG_BYTES:
            raise ValueError("compact JPEG set is empty or exceeds bounds")
        if set(texts) != ALLOWED_COMPACT_TEXT:
            raise ValueError("required compact TEXT receipts are missing")
        evidence_bytes = archive.read(texts["TECHNICAL-EVIDENCE.json"])
        sums_bytes = archive.read(texts["SHA256SUMS.txt"])
        evidence = json.loads(evidence_bytes.decode("utf-8"))
        sums = parse_sums(sums_bytes)
        expected_jpegs, master_by_name, review = check_technical_evidence(evidence, sums, input_receipt)
        if set(images) != set(expected_jpegs):
            raise ValueError("compact JPEG files differ from the technical review receipt")
        exported_images = []
        for name, entry in sorted(images.items()):
            data = archive.read(entry)
            if not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
                raise ValueError("review file is not a complete JPEG: " + name)
            digest = hashlib.sha256(data).hexdigest()
            if digest != expected_jpegs[name]:
                raise ValueError("review JPEG differs from technical receipt: " + name)
            exported_images.append((PurePosixPath(name).name, data, digest))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)
    review_dir = out / "review"
    review_dir.mkdir()
    exported = []
    for name, data, digest in exported_images:
        target = review_dir / name
        target.write_bytes(data)
        exported.append({"path": target.relative_to(out).as_posix(), "bytes": len(data), "sha256": digest})
    (out / "INPUT-RECEIPT.json").write_text(json.dumps(input_receipt, indent=2) + "\n", encoding="utf-8")
    (out / "TECHNICAL-EVIDENCE.json").write_bytes(evidence_bytes)
    (out / "SHA256SUMS.txt").write_bytes(sums_bytes)
    receipt = {
        "kind": "S86-hosted-final-review-compact-export",
        "repository": REPO,
        "render_run_id": RENDER_RUN_ID,
        "render_head_sha": RENDER_HEAD_SHA,
        "export_head_sha": expected["export_head_sha"],
        "source_sha256": input_receipt["source_sha256"],
        "source_identity_receipt": "INPUT-RECEIPT.json",
        "input_artifact": {"id": INPUT_ARTIFACT_ID, "name": INPUT_ARTIFACT_NAME,
                            "size_in_bytes": INPUT_ARTIFACT_SIZE, "digest": INPUT_ARTIFACT_DIGEST},
        "masters_artifact": {"id": MASTERS_ARTIFACT_ID, "name": MASTERS_ARTIFACT_NAME,
                              "size_in_bytes": MASTERS_ARTIFACT_SIZE, "digest": MASTERS_ARTIFACT_DIGEST,
                              "content_hash_verification": "artifact metadata pinned; inner master bytes not downloaded or rehashed by this compact exporter"},
        "compact_artifact": {"id": expected["compact_artifact_id"],
                              "name": COMPACT_ARTIFACT_NAME,
                              "size_in_bytes": expected["compact_artifact_size"],
                              "digest": expected["compact_artifact_digest"]},
        "master_identities": [{"file": name, "sha256": digest} for name, digest in sorted(master_by_name.items())],
        "review_master": review["master"],
        "review_sample_count": len(review["times"]),
        "input_artifact_members": input_members,
        "compact_artifact_members": sorted(list(images) + list(texts)),
        "exported_files": exported,
        "scope": "review JPEG samples and exact TEXT receipts only; no master or source archive exported",
        "full_master_review": "OPEN",
        "editorial_status": "NOT_REVIEWED",
        "release_approval": "NOT_GRANTED"
    }
    (out / "EXPORT-RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-metadata")
    validate.add_argument("repository_json")
    validate.add_argument("render_run_json")
    validate.add_argument("compact_artifact_json")
    validate.add_argument("input_artifact_json")
    validate.add_argument("masters_artifact_json")
    validate.add_argument("current_main_json")
    validate.add_argument("expected_json")
    run = sub.add_parser("export")
    run.add_argument("input_zip")
    run.add_argument("compact_zip")
    run.add_argument("repository_json")
    run.add_argument("render_run_json")
    run.add_argument("compact_artifact_json")
    run.add_argument("input_artifact_json")
    run.add_argument("masters_artifact_json")
    run.add_argument("current_main_json")
    run.add_argument("expected_json")
    run.add_argument("out_dir")
    args = parser.parse_args(argv)
    if args.command == "validate-metadata":
        hosted_guard()
        check_metadata(read_json(args.repository_json), read_json(args.render_run_json),
                       read_json(args.compact_artifact_json), read_json(args.input_artifact_json),
                       read_json(args.masters_artifact_json),
                       read_json(args.current_main_json), read_json(args.expected_json))
        print("native run, exporter head, public repository, compact, exact-input, and final-masters artifact bindings PASS")
        return 0
    receipt = export(args.input_zip, args.compact_zip, args.repository_json, args.render_run_json,
                     args.compact_artifact_json, args.input_artifact_json, args.masters_artifact_json,
                     args.current_main_json,
                     args.expected_json, args.out_dir)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
