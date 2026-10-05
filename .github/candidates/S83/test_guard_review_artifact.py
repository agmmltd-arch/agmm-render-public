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
        frames=[]
        for i in range(37):
            name=f"still-frame-{i:02d}.png"; p=root/name
            frames.append({"name":name,"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
        canonical="".join(f"{x['sha256']}  {x['name']}\n" for x in frames).encode()
        binding={"schema":"agmm-s83-source-frames-binding-v1","story_id":"S83","candidate_manifest_sha256":"a"*64,"source_public_head_sha":"b"*40,
                 "frame_count":37,"frames_sha256":hashlib.sha256(canonical).hexdigest(),"frames":frames}
        (root/"SOURCE-FRAMES-BINDING.json").write_text(json.dumps(binding,sort_keys=True))
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
            self.assertEqual(result["files"], 44)

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

    def test_rejects_extra_source_frame(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp); write_packet(root,full=True)
            (root/"still-frame-37.png").write_bytes(PNG); refresh_sums(root)
            with self.assertRaisesRegex(ValueError,"37 stills"):
                validate_packet(root)

    def test_rejects_changed_source_frame_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp); write_packet(root,full=True)
            (root/"still-frame-17.png").write_bytes(PNG+b"changed")
            refresh_sums(root)
            with self.assertRaisesRegex(ValueError,"source-frame binding differs"):
                validate_packet(root)

    def test_source_frame_binding_is_stable_when_run_metadata_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp); write_packet(root,full=True)
            binding=json.loads((root/"SOURCE-FRAMES-BINDING.json").read_text())
            status=json.loads((root/"CAPTURE-STATUS.json").read_text()); status["source_capture_run_id"]=987654321
            (root/"CAPTURE-STATUS.json").write_text(json.dumps(status)); refresh_sums(root)
            result=validate_packet(root)
            self.assertEqual(result["source_frames_sha256"],binding["frames_sha256"])

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

    def test_valid_diagnostic_failure_packet_does_not_green_failed_capture_job(self):
        import subprocess, textwrap
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp); write_packet(root)
            self.assertEqual(validate_packet(root)["capture_status"],"SOURCE_OR_STILLS_CAPTURE_FAILED")
            workflow=pathlib.Path(__file__).with_name("s83-source-capture.workflow.yml").read_text()
            block=workflow.split("name: Fail closed on source check or still-capture outcomes after saving diagnostics",1)[1].split("\n      - name:",1)[0]
            script=textwrap.dedent(block.split("run: |\n",1)[1])
            script=script.replace("${{ steps.source_capture.outcome }}","success").replace("${{ steps.hfcheck.outcome }}","failure").replace("${{ steps.hfstills.outcome }}","skipped")
            result=subprocess.run(["bash","-euo","pipefail","-c",script],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)


    def test_source_packet_builder_normalizes_snapshot_names_without_double_prefix(self):
        import subprocess, sys
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td); sources=root/'source'; (sources/'assets').mkdir(parents=True)
            stills=root/'stills';stills.mkdir();diag=root/'diag';diag.mkdir();out=root/'out'
            receipt={"schema":"agmm-s83-hosted-source-capture-v1","story_id":"S83","status":"SOURCE_TEXT_AND_TRUST_LOGOS_CAPTURED_NEEDS_INDEPENDENT_EYES","rights":{"status":"NOT_ASSESSED"}}
            (sources/'SOURCE-CAPTURE-RECEIPT.json').write_text(json.dumps(receipt))
            for name in ("rwt-mark.png","wht-mark.png"): (sources/'assets'/name).write_bytes(PNG)
            (root/'check.json').write_text('{}')
            manifest=root/'manifest.json';manifest.write_text('{"schema":"synthetic source text manifest"}')
            for i in range(37): (stills/f"frame-{i:02d}-time.png").write_bytes(PNG)
            script=pathlib.Path(__file__).with_name('hosted_receipt.py')
            subprocess.run([sys.executable,str(script),'--sources',str(sources),'--stills',str(stills),'--check',str(root/'check.json'),'--manifest',str(manifest),'--head','b'*40,'--diagnostics',str(diag),'--output',str(out),'--source-outcome','success','--check-outcome','success','--stills-outcome','success'],check=True,capture_output=True,text=True)
            self.assertEqual(len(list(out.glob('still-frame-*.png'))),37)
            self.assertEqual(len(list(out.glob('still-still-frame-*'))),0)
            self.assertEqual(validate_packet(out)['files'],42)

def refresh_sums(root):
    rows=[]
    for p in sorted(root.iterdir()):
        if p.name!="SHA256SUMS.txt": rows.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}")
    (root/"SHA256SUMS.txt").write_text("\n".join(rows)+"\n")

if __name__ == "__main__":
    unittest.main(verbosity=2)
