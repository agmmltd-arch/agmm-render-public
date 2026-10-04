#!/usr/bin/env python3
"""Build the exact public review allowlist from a hosted S83 source capture."""
import argparse
import hashlib
import json
import pathlib
import shutil

EXPECTED_ASSETS = {
    "rwt-mark.png",
    "wht-mark.png",
}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sources", required=True)
    p.add_argument("--stills", required=True)
    p.add_argument("--check", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--source-outcome", required=True)
    p.add_argument("--check-outcome", required=True)
    p.add_argument("--stills-outcome", required=True)
    a = p.parse_args()
    src, stills, check, out = map(pathlib.Path, (a.sources, a.stills, a.check, a.output))
    out.mkdir(parents=True, exist_ok=True)
    receipt_path = src / "SOURCE-CAPTURE-RECEIPT.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text())
    else:
        receipt = {"schema": "agmm-s83-hosted-source-capture-v1", "story_id": "S83",
                   "status": "SOURCE_CAPTURE_NOT_RUN", "failure": "Source capture did not produce its receipt.",
                   "rights": {"status": "NOT_ASSESSED", "restriction": "No Trust mark permission is inferred."}}
    status = receipt.get("status")
    (out / "SOURCE-CAPTURE-RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if check.is_file():
        try:
            json.loads(check.read_text())
            shutil.copyfile(check, out / "HYPERFRAMES-CHECK.json")
        except (UnicodeDecodeError, json.JSONDecodeError):
            shutil.copyfile(check, out / "HYPERFRAMES-CHECK-OUTPUT.txt")
    if status == "SOURCE_TEXT_AND_TRUST_LOGOS_CAPTURED_NEEDS_INDEPENDENT_EYES":
        actual = {p.name for p in (src / "assets").iterdir() if p.is_file()}
        if actual != EXPECTED_ASSETS:
            raise SystemExit("refusing unexpected source media allowlist: " + repr(sorted(actual)))
        for name in sorted(EXPECTED_ASSETS):
            shutil.copyfile(src / "assets" / name, out / name)
        if a.check_outcome == "success" and a.stills_outcome == "success":
            frames = [p for p in stills.iterdir() if p.is_file() and p.suffix.lower() == ".png"]
            if len(frames) != 37:
                raise SystemExit("expected 37 named/stitch-bound PNG captures, found " + str(len(frames)))
            for frame in sorted(frames):
                shutil.copyfile(frame, out / ("still-" + frame.name))
            final_status = "SOURCE_CHECK_AND_STILLS_CAPTURED_NEEDS_INDEPENDENT_EYES"
        else:
            final_status = "SOURCE_CAPTURED_CHECK_OR_STILLS_FAILED"
    else:
        final_status = "SOURCE_OR_STILLS_CAPTURE_FAILED"
    (out / "CAPTURE-STATUS.json").write_text(json.dumps({
        "schema": "agmm-s83-capture-status-v1",
        "story_id": "S83",
        "status": final_status,
        "source_step": a.source_outcome,
        "check_step": a.check_outcome,
        "stills_step": a.stills_outcome,
        "review_scope": "ONE_DAY_GITHUB_ACTIONS_ARTIFACT",
        "review_retention_days": 1,
        "artifact_access_limit": "Access follows the public repository's GitHub Actions artifact permissions; no private access restriction is asserted.",
        "rights_status": "NOT_ASSESSED",
        "public_review_copy_permission": "NOT_ASSESSED",
        "raw_assets_written_to_public_git": False,
        "render_approval": "NOT_GRANTED",
        "release_approval": "NOT_GRANTED"
    }, indent=2) + "\n")
    rows = []
    for f in sorted(out.iterdir()):
        if f.is_file():
            b = f.read_bytes()
            rows.append(f"{hashlib.sha256(b).hexdigest()}  {f.name}")
    (out / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n")

if __name__ == "__main__":
    main()
