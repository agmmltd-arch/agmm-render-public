"""Stage only S86 source-frame stills and hash-bound review receipts for a public branch."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import struct
from typing import Union

REPO = "agmmltd-arch/agmm-render-public"
SOURCE_SHA256 = "895e2d27d64ab24278de4b31fd5eb93686f23b96dc814e19ee1ad7f7bd2126f5"
PARTS_SHA256 = "1585e81e26e654aabc04ebe0f851a81f0cd13962069027557f1e29db2dadc02d"
PLAN_SHA256 = "92795eb311b2f189057601a039d576e2141703a94d70d77c6157cb7ddb607ef9"
MEDIA_SHA256 = "6f9464e534981c16d6e6a451d0759799347b553df468fe5ee6f74812dcbfe32c"
SOURCE_RELEASE = "S86-b-crop-overlay-37152228591"
NAMED = {
    "ico-entry-23p05", "ico-mid-25p70", "ico-exit-28p35",
    "scope-entry-49p841", "scope-mid-52p188", "scope-exit-54p545",
}
SEAMS = {
    f"seam-S86-{a}-to-S86-{b}-{s}"
    for a, b in (("A", "B"), ("B", "C"), ("C", "D"))
    for s in ("m040", "p020", "p060")
}
EXPECTED_NAMES = NAMED | SEAMS


def guard():
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("GitHub Actions Linux required before any capture-pack file IO")
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise RuntimeError("unexpected public review repository")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise RuntimeError("valid GitHub Actions run id required before any file IO")
    return int(run_id)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def exact_regular_tree(root: Path, expected: set[str], label: str) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"{label} must be a real directory")
    found = set()
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"{label} contains a symlink: {rel}")
        if path.is_dir():
            continue
        mode = os.stat(path, follow_symlinks=False).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError(f"{label} contains a non-regular file: {rel}")
        found.add(rel)
    if found != expected:
        raise ValueError(f"{label} file set differs from allowlist: missing={sorted(expected-found)} extra={sorted(found-expected)}")


def check_status(receipt: dict, kind: str, technical: str, binding: dict, label: str) -> None:
    if (receipt.get("kind") != kind or receipt.get("technical_status") != technical
            or receipt.get("editorial_status") != "NOT_REVIEWED"
            or receipt.get("publication_status") != "NOT_REQUESTED"
            or receipt.get("binding") != binding):
        raise ValueError(f"{label} kind/status/binding mismatch")


def publish_pack(capture_pack: Union[str, Path], output: Union[str, Path]) -> dict:
    run_id = guard()
    pack = Path(capture_pack)
    evidence_path = pack / "CAPTURE-EVIDENCE.json"
    input_path = pack / "INPUT-RECEIPT.json"
    sums_path = pack / "SHA256SUMS.txt"
    media_path = pack / "MEDIA-IDENTITIES.json"
    if pack.is_symlink() or not pack.is_dir():
        raise ValueError("capture pack must be a real directory")
    for path in (evidence_path, input_path, sums_path, media_path):
        if path.is_symlink() or not path.is_file():
            raise ValueError("capture pack is missing a regular required file")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    input_receipt = json.loads(input_path.read_text(encoding="utf-8"))
    media = json.loads(media_path.read_text(encoding="utf-8"))
    expected_binding = {
        "source_sha256": SOURCE_SHA256,
        "parts_sha256": PARTS_SHA256,
        "capture_plan_sha256": PLAN_SHA256,
        "media_identity_sha256": MEDIA_SHA256,
    }
    check_status(evidence, "agmm_short_hosted_capture_evidence", "CAPTURE_PASS", expected_binding, "capture evidence")
    check_status(input_receipt, "agmm_short_capture_input_receipt", "INPUT_IDENTITY_PASS", expected_binding, "input receipt")
    if media.get("kind") != "agmm_short_media_identities" or media.get("sha256") != MEDIA_SHA256:
        raise ValueError("media identity receipt differs from frozen binding")
    if (evidence.get("short_id") != "S86" or evidence.get("full_video_render") != "NOT_RUN"
        or evidence.get("full_video_decode") != "NOT_RUN"):
        raise ValueError("capture evidence scope mismatch")
    captures = evidence.get("captures")
    if not isinstance(captures, list) or len(captures) != 15:
        raise ValueError("expected six named captures and nine generated part seams")
    names = [row.get("name") for row in captures]
    if len(set(names)) != 15 or set(names) != EXPECTED_NAMES:
        raise ValueError("captured names differ from bounded proposal allowlist")
    for index, row in enumerate(captures, 1):
        if row.get("file") != f"frames/{index:02d}-{row['name']}.png":
            raise ValueError("capture frame names/order differ from actual bundle producer")
        if row.get("width") != 1080 or row.get("height") != 1920:
            raise ValueError(f"bundle evidence dimensions differ from contract: {row['name']}")
    by_name = {row["name"]: row for row in captures}
    exact_times = {
        "ico-entry-23p05": (23.05, "s86-b", 7.883333),
        "ico-mid-25p70": (25.7, "s86-b", 10.533333),
        "ico-exit-28p35": (28.35, "s86-b", 13.183333),
        "scope-entry-49p841": (49.841, "s86-d", 4.341),
        "scope-mid-52p188": (52.188, "s86-d", 6.688),
        "scope-exit-54p545": (54.545, "s86-d", 9.045),
    }
    for name, (global_time, look, local_time) in exact_times.items():
        row = by_name[name]
        if row.get("global") != global_time or row.get("look") != look or row.get("local") != local_time:
            raise ValueError(f"named capture timing differs from frozen plan: {name}")
    for previous, following, seam in (("S86-A", "S86-B", 15.166667),
                                      ("S86-B", "S86-C", 30.333333),
                                      ("S86-C", "S86-D", 45.5)):
        for suffix, delta in (("m040", -0.04), ("p020", 0.02), ("p060", 0.06)):
            name = f"seam-{previous}-to-{following}-{suffix}"
            row = by_name[name]
            if row.get("global") != round(seam + delta, 6):
                raise ValueError(f"generated seam timing differs from producer contract: {name}")

    sums = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            raise ValueError("invalid SHA256SUMS line")
        sha, name = line.split("  ", 1)
        if len(sha) != 64 or name in sums or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("invalid or duplicate checksum entry")
        sums[name] = sha
    frame_paths = {row.get("file") for row in captures}
    if (len(frame_paths) != 15 or any(not isinstance(name, str) or not re.fullmatch(r"frames/[A-Za-z0-9._-]+\.png", name) for name in frame_paths)
            or set(sums) != frame_paths | {"MEDIA-IDENTITIES.json"}):
        raise ValueError("capture bundle checksum entries differ from exact receipt set")
    if digest(media_path.read_bytes()) != sums["MEDIA-IDENTITIES.json"]:
        raise ValueError("media identity file does not match the producer checksum receipt")
    receipt_paths = {f"receipts/{look}.json" for look in ("s86-a", "s86-b", "s86-c", "s86-d")}
    expected_pack_files = frame_paths | receipt_paths | {
        "CAPTURE-EVIDENCE.json", "INPUT-RECEIPT.json", "MEDIA-IDENTITIES.json", "SHA256SUMS.txt",
    }
    exact_regular_tree(pack, expected_pack_files, "capture pack")
    for name, row in by_name.items():
        rel = row["file"]
        source = pack / rel
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"capture file is not a regular file: {name}")
        data = source.read_bytes()
        actual = digest(data)
        if actual != row.get("sha256") or actual != sums.get(rel):
            raise ValueError("PNG bytes do not match capture evidence and checksum receipt")
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise ValueError("capture file is not a PNG")
        if struct.unpack(">II", data[16:24]) != (1080, 1920):
            raise ValueError(f"PNG header dimensions differ from capture contract: {name}")
    for look in ("s86-a", "s86-b", "s86-c", "s86-d"):
        path = pack / "receipts" / f"{look}.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        check_status(receipt, "agmm_short_capture_part_receipt", "CAPTURE_PASS", expected_binding, f"{look} part receipt")
        if receipt.get("look") != look:
            raise ValueError(f"part receipt look mismatch: {look}")
        part_rows = receipt.get("captures")
        if not isinstance(part_rows, list) or {row.get("name") for row in part_rows} != {
                row["name"] for row in captures if row.get("look") == look}:
            raise ValueError(f"part receipt capture set mismatch: {look}")
        for part_row in part_rows:
            bundle_row = by_name[part_row["name"]]
            for key in ("kind", "global", "local", "look", "part_index", "part_out", "sha256", "bytes", "width", "height"):
                if part_row.get(key) != bundle_row.get(key):
                    raise ValueError(f"part receipt and bundle evidence differ: {part_row['name']} ({key})")
            if part_row.get("width") != 1080 or part_row.get("height") != 1920:
                raise ValueError(f"part receipt dimensions differ from source capture contract: {part_row['name']}")

    out = Path(output)
    if out.exists() or out.is_symlink():
        raise ValueError("review output path must not already exist")
    out.mkdir(parents=True, exist_ok=False)
    frames_dir = out / "frames"
    frames_dir.mkdir()
    rows = []
    for row in sorted(captures, key=lambda r: (r["global"], r["name"])):
        name = row.get("name")
        rel = row.get("file")
        if (name not in EXPECTED_NAMES or not isinstance(rel, str)
            or PurePosixPath(rel).parts[0] != "frames" or len(PurePosixPath(rel).parts) != 2
            or PurePosixPath(rel).suffix != ".png"):
            raise ValueError("unsafe capture file reference")
        source = pack / rel
        data = source.read_bytes()
        actual = digest(data)
        if actual != row.get("sha256") or actual != sums.get(rel):
            raise ValueError("PNG bytes do not match capture evidence and checksum receipt")
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("capture file is not a PNG")
        target = frames_dir / PurePosixPath(rel).name
        target.write_bytes(data)
        rows.append({"name": name, "global": row["global"], "look": row["look"],
                     "file": target.relative_to(out).as_posix(), "bytes": len(data),
                     "sha256": actual, "width": row["width"], "height": row["height"]})

    evidence_bytes = evidence_path.read_bytes()
    input_bytes = input_path.read_bytes()
    (out / "CAPTURE-EVIDENCE.json").write_bytes(evidence_bytes)
    (out / "INPUT-RECEIPT.json").write_bytes(input_bytes)
    branch = f"review-S86-source-frames-{run_id}"
    receipt = {
        "kind": "S86-public-source-frame-review-pack",
        "repository": REPO,
        "branch": branch,
        "run_id": int(run_id),
        "source_release": SOURCE_RELEASE,
        "source_sha256": SOURCE_SHA256,
        "parts_sha256": PARTS_SHA256,
        "capture_plan_sha256": PLAN_SHA256,
        "media_identity_sha256": MEDIA_SHA256,
        "capture_evidence_sha256": digest(evidence_bytes),
        "input_receipt_sha256": digest(input_bytes),
        "capture_count": len(rows),
        "captures": rows,
        "editorial_status": "NOT_REVIEWED",
        "release_approval": "NOT_GRANTED",
        "scope": "source composition PNG stills only; no assembled master, audio, source archive or media identities list",
    }
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    (out / "PUBLIC-REVIEW-RECEIPT.json").write_bytes(receipt_bytes)
    expected_output = {f"frames/{row['file'].split('/')[-1]}" for row in rows} | {
        "CAPTURE-EVIDENCE.json", "INPUT-RECEIPT.json", "PUBLIC-REVIEW-RECEIPT.json",
    }
    exact_regular_tree(out, expected_output, "public review output before checksum")
    checksum_rows = []
    for path in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "REVIEW-SHA256SUMS.txt"):
        checksum_rows.append(f"{digest(path.read_bytes())}  {path.relative_to(out).as_posix()}")
    (out / "REVIEW-SHA256SUMS.txt").write_text("\n".join(checksum_rows) + "\n", encoding="utf-8")
    exact_regular_tree(out, expected_output | {"REVIEW-SHA256SUMS.txt"}, "public review output")
    if len(checksum_rows) != 18:
        raise ValueError("public review output must contain exactly 18 hash-bound payload files")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_pack")
    parser.add_argument("output")
    args = parser.parse_args(argv)
    receipt = publish_pack(args.capture_pack, args.output)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
