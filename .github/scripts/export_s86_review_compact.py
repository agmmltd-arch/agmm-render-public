"""Export only existing S86 r2 compact review JPEGs and two text receipts.

Intended to run only on the pinned public GitHub Actions Linux runner. Never render.
"""
import argparse
import hashlib
import json
import os
from pathlib import PurePosixPath
import platform
import stat
import zipfile

REPO = "agmmltd-arch/agmm-render-public"
RUN_ID = 36816767405
ARTIFACT_ID = 11142017440
ARTIFACT_NAME = "S86-r2-4k-REVIEW-COMPACT"
ALLOWED_TEXT = {"TECHNICAL-EVIDENCE.json", "SHA256SUMS.txt"}
MAX_IMAGES = 120
MAX_TOTAL_BYTES = 15_000_000
MAX_MEMBER_BYTES = 5_000_000


def hosted_guard():
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("GitHub Actions Linux required before any archive/file IO")
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise RuntimeError("unexpected repository")


def safe_member(name):
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ValueError("invalid archive member name")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("unsafe archive path")
    if path.as_posix() != name.rstrip("/"):
        raise ValueError("non-normalized archive path")
    return path


def export(artifact_zip, artifact_metadata, repository_metadata, out_dir):
    hosted_guard()
    import pathlib
    artifact = json.loads(pathlib.Path(artifact_metadata).read_text(encoding="utf-8"))
    repo = json.loads(pathlib.Path(repository_metadata).read_text(encoding="utf-8"))
    if repo.get("full_name") != REPO or repo.get("private") is not False or repo.get("visibility") != "public":
        raise ValueError("repository must be the exact public review repository")
    run = artifact.get("workflow_run") or {}
    if (artifact.get("id") != ARTIFACT_ID or artifact.get("name") != ARTIFACT_NAME
        or artifact.get("expired") is not False or run.get("id") != RUN_ID
        or artifact.get("size_in_bytes") != 2507581):
        raise ValueError("artifact identity, expiry, or size mismatch")

    with zipfile.ZipFile(artifact_zip) as archive:
        entries = archive.infolist()
        seen = set()
        archive_members = []
        images = []
        texts = {}
        total = 0
        for entry in entries:
            path = safe_member(entry.filename)
            if entry.is_dir():
                continue
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("symlink in archive")
            name = path.as_posix()
            archive_members.append(name)
            if name in seen:
                raise ValueError("duplicate normalized archive path")
            seen.add(name)
            if entry.file_size <= 0 or entry.file_size > MAX_MEMBER_BYTES:
                raise ValueError("empty or oversized archive member")
            if path.parts[0] == "review" and len(path.parts) == 2 and path.suffix.lower() == ".jpg":
                images.append(entry)
                total += entry.file_size
            elif name in ALLOWED_TEXT:
                texts[name] = entry
            else:
                raise ValueError("archive contains a member outside the JPEG/text allowlist")
        if not images or len(images) > MAX_IMAGES or total > MAX_TOTAL_BYTES:
            raise ValueError("review image set is empty or exceeds bounds")
        if set(texts) != ALLOWED_TEXT:
            raise ValueError("required technical text receipts missing")

        # Read metadata first; validate receipt is for this render and never approval.
        evidence = json.loads(archive.read(texts["TECHNICAL-EVIDENCE.json"]))
        if (evidence.get("kind") != "agmm_short_remote_technical_evidence"
            or evidence.get("technical_status") != "PASS"
            or evidence.get("editorial_status") != "NOT_REVIEWED"
            or evidence.get("publication_status") != "NOT_REQUESTED"):
            raise ValueError("technical receipt identity/status mismatch")
        review_proof = evidence.get("review")
        if not isinstance(review_proof, dict) or review_proof.get("contact_sheet") != "CONTACT-SHEET.jpg":
            raise ValueError("technical receipt review section is missing the producer's contact-sheet fields")
        expected_images = {"review/CONTACT-SHEET.jpg": review_proof.get("contact_sheet_sha256")}
        review_times = review_proof.get("times")
        if not isinstance(review_times, list) or not review_times:
            raise ValueError("technical receipt has no review still records")
        for row in review_times:
            if not isinstance(row, dict) or not isinstance(row.get("file"), str):
                raise ValueError("malformed producer review still record")
            filename = row["file"]
            if PurePosixPath(filename).name != filename or not filename.lower().endswith(".jpg"):
                raise ValueError("unsafe producer review still name")
            if filename in ("CONTACT-SHEET.jpg",) or filename in {PurePosixPath(k).name for k in expected_images}:
                raise ValueError("duplicate producer review still name")
            expected_images["review/" + filename] = row.get("sha256")
        actual_images = {entry.filename: entry for entry in images}
        if set(actual_images) != set(expected_images):
            raise ValueError("archive JPEG set differs from producer review receipt")
        for name, entry in actual_images.items():
            data = archive.read(entry)
            if not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
                raise ValueError("allowlisted image is not a complete JPEG")
            if hashlib.sha256(data).hexdigest() != expected_images[name]:
                raise ValueError("review JPEG does not match producer receipt hash")

        import pathlib
        out = pathlib.Path(out_dir)
        out.mkdir(parents=True, exist_ok=False)
        review = out / "review"
        review.mkdir()
        files = []
        for entry in sorted(images, key=lambda e: e.filename):
            data = archive.read(entry)
            target = review / PurePosixPath(entry.filename).name
            target.write_bytes(data)
            files.append({"path": target.relative_to(out).as_posix(), "bytes": len(data),
                          "sha256": hashlib.sha256(data).hexdigest()})
        for name, entry in texts.items():
            data = archive.read(entry)
            if len(data) > 1_000_000:
                raise ValueError("oversized text receipt")
            (out / name).write_bytes(data)
    receipt = {
        "kind": "S86-hosted-review-compact-export",
        "repository": REPO,
        "source_run_id": RUN_ID,
        "source_run_head_sha": "9e34bc8aca7786583c771a2e203232071c8ddf5d",
        "artifact_id": ARTIFACT_ID,
        "artifact_name": ARTIFACT_NAME,
        "artifact_sha256": _sha256(artifact_zip),
        "scope": "existing compact review JPEGs and two text receipts only; no rerender",
        "archive_members": sorted(archive_members),
        "editorial_status": "NOT_REVIEWED",
        "release_approval": "NOT_GRANTED",
        "files": files,
    }
    (out / "EXPORT-RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_zip")
    parser.add_argument("artifact_metadata")
    parser.add_argument("repository_metadata")
    parser.add_argument("out_dir")
    args = parser.parse_args(argv)
    receipt = export(args.artifact_zip, args.artifact_metadata, args.repository_metadata, args.out_dir)
    print(json.dumps(receipt, sort_keys=True))
    return 0


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
