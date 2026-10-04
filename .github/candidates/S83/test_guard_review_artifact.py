import hashlib
import json
import pathlib
import tempfile
import unittest

from guard_review_artifact import validate_packet

PNG = b"\x89PNG\r\n\x1a\n" + b"test-payload"


def write_packet(root, *, full=False):
    source_ok = full
    capture_status = "SOURCE_CHECK_AND_STILLS_CAPTURED_NEEDS_INDEPENDENT_EYES" if full else "SOURCE_OR_STILLS_CAPTURE_FAILED"
    receipt = {
        "schema": "agmm-s83-hosted-source-capture-v1",
        "story_id": "S83",
        "status": "SOURCE_TEXT_AND_TRUST_LOGOS_CAPTURED_NEEDS_INDEPENDENT_EYES" if source_ok else "SOURCE_CAPTURE_FAILED",
        "rights": {"status": "NOT_ASSESSED"}
    }
    status = {
        "schema": "agmm-s83-capture-status-v1",
        "story_id": "S83",
        "status": capture_status,
        "source_step": "success" if source_ok else "failure",
        "check_step": "success" if full else "skipped",
        "stills_step": "success" if full else "skipped",
        "review_scope": "ONE_DAY_GITHUB_ACTIONS_ARTIFACT",
        "review_retention_days": 1,
        "artifact_access_limit": "Access follows the public repository's GitHub Actions artifact permissions; no private access restriction is asserted.",
        "rights_status": "NOT_ASSESSED",
        "public_review_copy_permission": "NOT_ASSESSED",
        "raw_assets_written_to_public_git": False,
        "release_approval": "NOT_GRANTED"
    }
    (root / "SOURCE-CAPTURE-RECEIPT.json").write_text(json.dumps(receipt))
    (root / "CAPTURE-STATUS.json").write_text(json.dumps(status))
    if source_ok:
        for name in ("rwt-mark.png", "wht-mark.png"):
            (root / name).write_bytes(PNG)
    if full:
        (root / "HYPERFRAMES-CHECK.json").write_text("{}")
        for i in range(37):
            (root / f"still-frame-{i:02d}.png").write_bytes(PNG)
    rows = []
    for item in sorted(root.iterdir()):
        rows.append(f"{hashlib.sha256(item.read_bytes()).hexdigest()}  {item.name}")
    (root / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n")


class ReviewArtifactGuardTests(unittest.TestCase):
    def test_accepts_exact_failure_packet_without_raw_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            write_packet(root)
            result = validate_packet(root)
            self.assertEqual(result["files"], 3)

    def test_accepts_exact_full_one_day_review_packet(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            write_packet(root, full=True)
            result = validate_packet(root)
            self.assertEqual(result["files"], 43)

    def test_rejects_unallowlisted_raw_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            write_packet(root)
            (root / "unreviewed-logo.png").write_bytes(PNG)
            with self.assertRaisesRegex(ValueError, "allowlist"):
                validate_packet(root)

    def test_rejects_partial_still_set(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            write_packet(root, full=True)
            (root / "still-frame-36.png").unlink()
            with self.assertRaisesRegex(ValueError, "37 stills"):
                validate_packet(root)

    def test_rejects_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            write_packet(root)
            status = json.loads((root / "CAPTURE-STATUS.json").read_text())
            status["artifact_access_limit"] = "Access follows the public repository artifact permissions; no private access restriction is asserted."
            (root / "CAPTURE-STATUS.json").write_text(json.dumps(status))
            with self.assertRaisesRegex(ValueError, "SHA256SUMS"):
                validate_packet(root)

    def test_rejects_rights_claim_or_release_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            write_packet(root)
            status = json.loads((root / "CAPTURE-STATUS.json").read_text())
            status["rights_status"] = "CLEARED"
            (root / "CAPTURE-STATUS.json").write_text(json.dumps(status))
            with self.assertRaisesRegex(ValueError, "rights"):
                validate_packet(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
