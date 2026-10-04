#!/usr/bin/env python3
"""Fail closed on the exact one-day S83 review artifact allowlist."""
import hashlib
import json
import pathlib
import sys

BASE_FILES = {"SOURCE-CAPTURE-RECEIPT.json", "CAPTURE-STATUS.json", "SHA256SUMS.txt"}
LOGO_FILES = {"rwt-mark.png", "wht-mark.png"}
OPTIONAL_TEXT = {"SOURCE-CLOCK-RECEIPT.json", "MIX-QUALITY-RECEIPT.json", "PROTECTED-INPUT-VERIFICATION.json", "RUNTIME-RECEIPT.json"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FULL_STATUS = "SOURCE_CHECK_AND_STILLS_CAPTURED_NEEDS_INDEPENDENT_EYES"
SOURCE_STATUS = "SOURCE_TEXT_AND_TRUST_LOGOS_CAPTURED_NEEDS_INDEPENDENT_EYES"


def validate_packet(directory):
    root = pathlib.Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("review packet path must be a real directory")
    entries = list(root.iterdir())
    if any(p.is_symlink() or not p.is_file() for p in entries):
        raise ValueError("review packet must contain regular files only")
    actual = {p.name for p in entries}
    if len(actual) != len(entries):
        raise ValueError("duplicate packet entries")
    if not BASE_FILES <= actual:
        raise ValueError("review packet is missing a required receipt")

    receipt = json.loads((root / "SOURCE-CAPTURE-RECEIPT.json").read_text())
    status = json.loads((root / "CAPTURE-STATUS.json").read_text())
    if receipt.get("story_id") != "S83" or status.get("story_id") != "S83":
        raise ValueError("review packet story identity mismatch")
    if receipt.get("rights", {}).get("status") != "NOT_ASSESSED":
        raise ValueError("raw Trust marks must retain the explicit NOT_ASSESSED rights status")
    if status.get("rights_status") != "NOT_ASSESSED" or status.get("release_approval") != "NOT_GRANTED":
        raise ValueError("capture status must keep rights and release gates open")
    if status.get("review_scope") != "ONE_DAY_GITHUB_ACTIONS_ARTIFACT" or status.get("review_retention_days") != 1:
        raise ValueError("review packet must state its one-day artifact retention")
    if status.get("public_review_copy_permission") != "NOT_ASSESSED" or status.get("raw_assets_written_to_public_git") is not False:
        raise ValueError("public-copy permission must remain open and raw assets must stay out of Git")
    if "public repository" not in status.get("artifact_access_limit", ""):
        raise ValueError("artifact access limits must be stated accurately for this public repository")

    source_ok = receipt.get("status") == SOURCE_STATUS
    full_ok = status.get("status") == FULL_STATUS
    present_text = actual & OPTIONAL_TEXT
    if present_text and present_text != OPTIONAL_TEXT:
        raise ValueError("production packet must contain all four text receipts")
    allowed = set(BASE_FILES) | present_text
    for name in present_text:
        try:
            json.loads((root / name).read_text())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("optional production receipt is not valid JSON: " + name) from exc
    if present_text:
        protected = json.loads((root / "PROTECTED-INPUT-VERIFICATION.json").read_text())
        mix = json.loads((root / "MIX-QUALITY-RECEIPT.json").read_text())
        clock = json.loads((root / "SOURCE-CLOCK-RECEIPT.json").read_text())
        if protected.get("asset_count") != 18 or protected.get("status") != "PASS_18_EXACT_INPUTS":
            raise ValueError("production packet lacks exact protected-input verification")
        if mix.get("audio_review") != "NOT_PERFORMED" or mix.get("approval") != "NOT_GRANTED" or mix.get("protected_master_or_stems_in_artifact") is not False:
            raise ValueError("mix receipt must keep audio review and approval open and exclude media")
        if clock.get("audio_review") != "NOT_PERFORMED_BY_VALIDATOR":
            raise ValueError("source-clock receipt must not claim audio review")
    if "HYPERFRAMES-CHECK.json" in actual:
        try:
            json.loads((root / "HYPERFRAMES-CHECK.json").read_text())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("HyperFrames check receipt is not valid JSON") from exc
        allowed.add("HYPERFRAMES-CHECK.json")
    if "HYPERFRAMES-CHECK-OUTPUT.txt" in actual:
        if "HYPERFRAMES-CHECK.json" in actual:
            raise ValueError("packet cannot contain both check JSON and raw check output")
        allowed.add("HYPERFRAMES-CHECK-OUTPUT.txt")
    if source_ok:
        allowed |= LOGO_FILES
    if full_ok:
        if not source_ok or status.get("check_step") != "success" or status.get("stills_step") != "success":
            raise ValueError("full-capture status lacks successful source/check/stills outcomes")
        if "HYPERFRAMES-CHECK.json" not in actual:
            raise ValueError("full capture requires the valid HyperFrames check receipt")
        frames = {name for name in actual if name.startswith("still-frame-") and name.endswith(".png")}
        if len(frames) != 37:
            raise ValueError(f"full review packet needs exactly 37 stills; found {len(frames)}")
        allowed |= frames
    elif any(name.startswith("still-") for name in actual):
        raise ValueError("partial/failed capture must not include a partial still set")
    if actual != allowed:
        raise ValueError("review packet file allowlist mismatch: " + repr(sorted(actual ^ allowed)))

    for name in LOGO_FILES | {n for n in actual if n.startswith("still-frame-") and n.endswith(".png")}:
        if name in actual and not (root / name).read_bytes().startswith(PNG_SIGNATURE):
            raise ValueError(f"invalid PNG payload: {name}")

    sums = {}
    for line in (root / "SHA256SUMS.txt").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if name in sums:
            raise ValueError("duplicate SHA256 row: " + name)
        sums[name] = digest
    expected_sums = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                     for name in actual - {"SHA256SUMS.txt"}}
    if sums != expected_sums:
        raise ValueError("SHA256SUMS does not exactly bind all packet files")
    return {"files": len(actual), "bytes": sum(p.stat().st_size for p in entries),
            "source_status": receipt.get("status"), "capture_status": status.get("status")}


def main():
    result = validate_packet(sys.argv[1])
    print("REVIEW_PACKET_VALID " + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
