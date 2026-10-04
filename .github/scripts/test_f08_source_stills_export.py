import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

try:
    from candidate import f08_source_stills_export as exporter
except ModuleNotFoundError:
    script = Path(__file__).with_name("f08_source_stills_export.py")
    spec = importlib.util.spec_from_file_location("f08_source_stills_export", script)
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)


NOW = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
RUN_ID = exporter.SOURCE_RUN_ID
SOURCE_COMMIT = exporter.SOURCE_COMMIT


def sha(data):
    return hashlib.sha256(data).hexdigest()


def manifest_fixture():
    return json.loads(manifest_path().read_text())


def manifest_path():
    for base in Path(__file__).resolve().parents:
        for candidate in (base / exporter.MANIFEST_PATH, base / Path(exporter.MANIFEST_PATH).name):
            if candidate.is_file():
                return candidate
    raise FileNotFoundError("frozen source publication manifest fixture not found")


def manifest_raw():
    return manifest_path().read_bytes()


def plan_fixture():
    return {
        "status": "estimated-source-capture-plan",
        "clock_basis": "ESTIMATED_155_WPM",
        "canvas": {"width": 3840, "height": 2160, "fps": 30},
        "points": [{"name": name, "scene_id": scene, "at_s": seconds, "reason": "fixture purpose"}
                   for name, scene, seconds in exporter.POINTS],
    }


def png(width=3840, height=2160):
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height) + b"\x00"


def make_archive(path, *, mutate=None, missing=None, extra=None):
    plan = plan_fixture()
    inputs = exporter.validate_manifest(manifest_fixture(), exporter.SOURCE_MANIFEST_SHA256)
    frames = {name: png() for name in exporter.FRAME_NAMES}
    contact = b"synthetic contact sheet fixture"
    receipt = {
        "status": "SOURCE_STILLS_CAPTURED", "source_commit": SOURCE_COMMIT,
        "workflow_run_id": str(RUN_ID), "workflow_run_attempt": "1",
        "event": "workflow_dispatch", "publication_manifest_sha256": exporter.SOURCE_MANIFEST_SHA256,
        "inputs": inputs, "stills": {name: sha(data) for name, data in frames.items()},
        "contact_sheets": {"contact-sheet.jpg": sha(contact)},
    }
    if mutate:
        mutate(frames, receipt, plan)
    items = {f"captures/{name}": data for name, data in frames.items()}
    items.update({exporter.PLAN_MEMBER: json.dumps(plan).encode(),
                  exporter.SOURCE_RECEIPT_MEMBER: json.dumps(receipt).encode(),
                  exporter.CONTACT_MEMBER: contact})
    if missing:
        items.pop(missing, None)
    if extra:
        items[extra] = b"unexpected"

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in items.items():
            archive.writestr(name, data)
    return path


def native_metadata(archive_bytes=1234, artifact_digest=None, *, run_changes=None,
                    job_changes=None, artifacts_changes=None, observed_at=NOW):
    run = {
        "id": RUN_ID, "repository": {"full_name": exporter.REPO}, "path": exporter.WORKFLOW,
        "head_branch": "main",
        "name": exporter.WORKFLOW_NAME, "event": "workflow_dispatch", "status": "completed",
        "conclusion": "success", "head_sha": SOURCE_COMMIT, "run_attempt": 1,
        "created_at": "2026-10-04T21:03:33Z", "updated_at": "2026-10-04T21:04:12Z",
    }
    if run_changes:
        run.update(run_changes)
    job = {"id": exporter.SOURCE_JOB_ID, "name": exporter.JOB_NAME, "run_id": RUN_ID,
           "head_sha": SOURCE_COMMIT, "status": "completed", "conclusion": "success"}
    if job_changes:
        job.update(job_changes)
    artifact = {
        "id": 123456789, "name": f"{exporter.ARTIFACT_PREFIX}{RUN_ID}",
        "size_in_bytes": archive_bytes, "digest": artifact_digest or "sha256:" + "1" * 64,
        "expired": False, "created_at": "2026-10-04T21:04:09Z",
        "expires_at": "2026-10-07T21:04:08Z",
        "workflow_run": {"id": RUN_ID, "head_branch": "main", "head_sha": SOURCE_COMMIT,
                         "repository_id": exporter.REPOSITORY_ID, "head_repository_id": exporter.REPOSITORY_ID},
    }
    if artifacts_changes:
        artifact.update(artifacts_changes)
    return (
        {"full_name": exporter.REPO, "id": exporter.REPOSITORY_ID, "private": False, "visibility": "public"},
        run, {"total_count": 1, "jobs": [job]}, {"total_count": 1, "artifacts": [artifact]},
        manifest_fixture(), exporter.SOURCE_MANIFEST_SHA256,
    )


def validate_fixture(*args, **kwargs):
    repo, run, jobs, artifacts, manifest, manifest_sha = native_metadata(*args, **kwargs)
    return exporter.validate_source(repo, run, jobs, artifacts, RUN_ID, SOURCE_COMMIT,
                                    manifest, manifest_sha, NOW)


class SourceStillsExportTests(unittest.TestCase):
    def test_exact_source_run_artifact_and_manifest_bind(self):
        source = validate_fixture()
        self.assertEqual(source["run_id"], RUN_ID)
        self.assertEqual(source["head_branch"], "main")
        self.assertEqual(source["artifact"]["id"], 123456789)
        self.assertEqual(source["input_hashes"][exporter.CAPTURE_SCRIPT_PATH], exporter.CAPTURE_SCRIPT_SHA256)

    def test_wrong_requested_commit_is_refused(self):
        repo, run, jobs, artifacts, manifest, digest = native_metadata()
        with self.assertRaisesRegex(exporter.Refusal, "frozen successful run/commit/manifest triple"):
            exporter.validate_source(repo, run, jobs, artifacts, RUN_ID, "b" * 40, manifest, digest, NOW)

    def test_non_main_source_run_branch_is_refused_by_native_metadata_guard(self):
        with self.assertRaisesRegex(exporter.Refusal, "exact completed successful Wave03 capture run"):
            validate_fixture(run_changes={"head_branch": "feature/unreviewed"})

    def test_failed_run_is_refused(self):
        with self.assertRaisesRegex(exporter.Refusal, "completed successful"):
            validate_fixture(run_changes={"conclusion": "failure"})

    def test_private_repository_is_refused(self):
        repo, run, jobs, artifacts, manifest, digest = native_metadata()
        repo["private"] = True
        with self.assertRaisesRegex(exporter.Refusal, "exact public repository"):
            exporter.validate_source(repo, run, jobs, artifacts, RUN_ID, SOURCE_COMMIT, manifest, digest, NOW)

    def test_extra_job_is_refused(self):
        repo, run, jobs, artifacts, manifest, digest = native_metadata()
        jobs["total_count"] = 2
        jobs["jobs"].append(dict(jobs["jobs"][0]))
        with self.assertRaisesRegex(exporter.Refusal, "one-job"):
            exporter.validate_source(repo, run, jobs, artifacts, RUN_ID, SOURCE_COMMIT, manifest, digest, NOW)

    def test_wrong_artifact_digest_or_name_is_refused(self):
        with self.assertRaisesRegex(exporter.Refusal, "artifact ID/name/size/digest"):
            validate_fixture(artifacts_changes={"digest": "sha256:bad"})
        with self.assertRaisesRegex(exporter.Refusal, "artifact ID/name/size/digest"):
            validate_fixture(artifacts_changes={"name": "another-run"})

    def test_expired_artifact_is_refused(self):
        with self.assertRaisesRegex(exporter.Refusal, "expired"):
            validate_fixture(artifacts_changes={"expires_at": "2026-10-03T21:00:00Z"})

    def test_manifest_must_bind_corrected_checker_and_storyboard(self):
        manifest = manifest_fixture()
        for entry in manifest["entries"]:
            if entry["target_path"] == f"{exporter.PACKAGE}/tools/rebind-clock.py":
                entry["sha256"] = "f" * 64
        with self.assertRaisesRegex(exporter.Refusal, "frozen reviewed 12 inputs"):
            exporter.validate_manifest(manifest, exporter.SOURCE_MANIFEST_SHA256)

    def test_recomputed_manifest_hash_with_changed_other_input_is_refused(self):
        repo, run, jobs, artifacts, manifest, _ = native_metadata()
        altered = json.loads(json.dumps(manifest))
        for entry in altered["entries"]:
            if entry["target_path"] == f"{exporter.PACKAGE}/tools/rebind-clock.py":
                entry["sha256"] = "f" * 64
        recomputed_digest = sha(json.dumps(altered, indent=2).encode() + b"\n")
        with self.assertRaisesRegex(exporter.Refusal, "frozen successful run/commit/manifest triple"):
            exporter.validate_source(repo, run, jobs, artifacts, RUN_ID, SOURCE_COMMIT,
                                     altered, recomputed_digest, NOW)

    def test_manifest_bytes_must_match_explicit_full_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_bytes(manifest_raw())
            loaded, digest = exporter.load_manifest(path, exporter.SOURCE_MANIFEST_SHA256)
            self.assertEqual(loaded["repository"], exporter.REPO)
            self.assertEqual(digest, exporter.SOURCE_MANIFEST_SHA256)
            with self.assertRaisesRegex(exporter.Refusal, "do not match"):
                path.write_bytes(path.read_bytes()+b" ")
                exporter.load_manifest(path, exporter.SOURCE_MANIFEST_SHA256)

    def test_validate_source_cli_uses_requested_run_commit_and_manifest_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, run, jobs, artifacts, _, _ = native_metadata()
            inputs = {
                "repository": repo, "run": run, "jobs": jobs, "artifacts": artifacts,
            }
            for name, value in inputs.items():
                (root / f"{name}.json").write_text(json.dumps(value))
            manifest_path = root / "manifest.json"
            manifest_path.write_bytes(manifest_raw())
            out_path = root / "validated-source.json"
            script = Path(exporter.__file__).resolve()
            base = [sys.executable, str(script), "validate-source",
                    "--repository", str(root / "repository.json"),
                    "--run", str(root / "run.json"), "--jobs", str(root / "jobs.json"),
                    "--artifacts", str(root / "artifacts.json"), "--manifest", str(manifest_path),
                    "--source-run-id", str(RUN_ID), "--source-commit", SOURCE_COMMIT,
                    "--manifest-sha256", exporter.SOURCE_MANIFEST_SHA256,
                    "--out", str(out_path)]
            valid = subprocess.run(base, text=True, capture_output=True)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(json.loads(out_path.read_text())["run_id"], RUN_ID)

            wrong_requests = (
                ("--source-run-id", str(RUN_ID + 1)),
                ("--source-commit", "b" * 40),
                ("--manifest-sha256", "f" * 64),
            )
            for flag, wrong_value in wrong_requests:
                with self.subTest(flag=flag):
                    arguments = list(base)
                    position = arguments.index(flag) + 1
                    arguments[position] = wrong_value
                    if out_path.exists():
                        out_path.unlink()
                    refused = subprocess.run(arguments, text=True, capture_output=True)
                    self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
                    self.assertIn("refused:", refused.stderr)
                    self.assertFalse(out_path.exists())

    def test_exact_native_zip_extracts_only_allowlisted_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = make_archive(Path(tmp) / "native.zip")
            source = validate_fixture(archive.stat().st_size, "sha256:" + sha(archive.read_bytes()))
            out = Path(tmp) / "extract"
            with patch.object(exporter, "require_hosted"):
                result = exporter.extract_archive(archive, source, out)
            self.assertEqual(set(result["members"]), exporter.ZIP_MEMBERS)
            self.assertEqual(len(list(out.rglob("*.png"))), 8)

    def test_native_zip_digest_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = make_archive(Path(tmp) / "native.zip")
            source = validate_fixture(archive.stat().st_size, "sha256:" + "0" * 64)
            with patch.object(exporter, "require_hosted"):
                with self.assertRaisesRegex(exporter.Refusal, "digest mismatch"):
                    exporter.extract_archive(archive, source, Path(tmp) / "extract")

    def test_missing_extra_or_unsafe_zip_member_is_refused(self):
        for kwargs in (
            {"missing": exporter.CONTACT_MEMBER},
            {"extra": "captures/unrequested.png"},
            {"extra": "../escape.txt"},
        ):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as tmp:
                archive = make_archive(Path(tmp) / "native.zip", **kwargs)
                source = validate_fixture(archive.stat().st_size, "sha256:" + sha(archive.read_bytes()))
                with patch.object(exporter, "require_hosted"):
                    with self.assertRaisesRegex(exporter.Refusal, "exact 8-PNG"):
                        exporter.extract_archive(archive, source, Path(tmp) / "extract")

    def test_prepare_exports_exact_eight_pngs_and_safe_text_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = make_archive(Path(tmp) / "native.zip")
            source = validate_fixture(archive.stat().st_size, "sha256:" + sha(archive.read_bytes()))
            extracted = Path(tmp) / "extract"
            payload = Path(tmp) / "payload"
            with patch.object(exporter, "require_hosted"):
                exporter.extract_archive(archive, source, extracted)
                receipt = exporter.prepare_export(extracted, source, payload)
            self.assertEqual(len(receipt["frames"]), 8)
            self.assertEqual({p.name for p in payload.iterdir()}, exporter.PUBLIC_NAMES)
            self.assertFalse(any(p.suffix.lower() in {".jpg", ".mp4", ".wav"} for p in payload.iterdir()))
            self.assertEqual(receipt["visual_review"], "OPEN")
            self.assertEqual(receipt["full_film_status"], "HELD")
            self.assertEqual(receipt["ready"], "NOT_GRANTED")

    def test_wrong_dimensions_and_wrong_producer_hash_are_refused(self):
        def dimensions(frames, receipt, plan):
            name = exporter.FRAME_NAMES[2]
            frames[name] = png(1920, 1080)
            receipt["stills"][name] = sha(frames[name])
        def hash_mismatch(frames, receipt, plan):
            receipt["stills"][exporter.FRAME_NAMES[0]] = "0" * 64
        for mutation, expected in ((dimensions, "dimensions mismatch"), (hash_mismatch, "hash differs")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                archive = make_archive(Path(tmp) / "native.zip", mutate=mutation)
                source = validate_fixture(archive.stat().st_size, "sha256:" + sha(archive.read_bytes()))
                extracted, payload = Path(tmp) / "extract", Path(tmp) / "payload"
                with patch.object(exporter, "require_hosted"):
                    exporter.extract_archive(archive, source, extracted)
                    with self.assertRaisesRegex(exporter.Refusal, expected):
                        exporter.prepare_export(extracted, source, payload)

    def test_wrong_plan_and_wrong_source_receipt_are_refused(self):
        def wrong_plan(frames, receipt, plan):
            plan["points"][0]["at_s"] = 2.0
        def wrong_source(frames, receipt, plan):
            receipt["source_commit"] = "c" * 40
        for mutation, expected in ((wrong_plan, "point order/name/scene/time"), (wrong_source, "producer receipt")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                archive = make_archive(Path(tmp) / "native.zip", mutate=mutation)
                source = validate_fixture(archive.stat().st_size, "sha256:" + sha(archive.read_bytes()))
                extracted = Path(tmp) / "extract"
                with patch.object(exporter, "require_hosted"):
                    exporter.extract_archive(archive, source, extracted)
                    with self.assertRaisesRegex(exporter.Refusal, expected):
                        exporter.prepare_export(extracted, source, Path(tmp) / "payload")

    def test_public_payload_refuses_extra_file_and_wrong_readiness_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = make_archive(Path(tmp) / "native.zip")
            source = validate_fixture(archive.stat().st_size, "sha256:" + sha(archive.read_bytes()))
            extracted, payload = Path(tmp) / "extract", Path(tmp) / "payload"
            with patch.object(exporter, "require_hosted"):
                exporter.extract_archive(archive, source, extracted)
                exporter.prepare_export(extracted, source, payload)
            (payload / "extra.mp4").write_bytes(b"not permitted")
            with self.assertRaisesRegex(exporter.Refusal, "exact 8 PNG"):
                exporter._payload(payload)

    def test_public_payload_refuses_promoted_readiness_or_expired_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = make_archive(Path(tmp) / "native.zip")
            source = validate_fixture(archive.stat().st_size, "sha256:" + sha(archive.read_bytes()))
            extracted, payload = Path(tmp) / "extract", Path(tmp) / "payload"
            with patch.object(exporter, "require_hosted"):
                exporter.extract_archive(archive, source, extracted)
                exporter.prepare_export(extracted, source, payload)
            receipt_path = payload / exporter.RECEIPT_NAME
            sums_path = payload / exporter.SUMS_NAME
            def reseal_receipt():
                names = sorted(exporter.PUBLIC_NAMES - {exporter.SUMS_NAME})
                sums_path.write_text("".join(f"{exporter.sha256(payload / name)}  {name}\n" for name in names))
            receipt = json.loads(receipt_path.read_text())
            receipt["ready"] = "GRANTED"
            receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            reseal_receipt()
            with self.assertRaisesRegex(exporter.Refusal, "mandatory OPEN/HELD"):
                exporter._payload(payload)
            receipt["ready"] = "NOT_GRANTED"
            receipt["source"]["artifact_expires_at"] = "2026-10-03T21:00:00Z"
            receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            reseal_receipt()
            with self.assertRaisesRegex(exporter.Refusal, "expired before public"):
                exporter._payload(payload)

    def test_run_scoped_release_create_and_readback_upload_only_exact_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = make_archive(Path(tmp) / "native.zip")
            source = validate_fixture(archive.stat().st_size, "sha256:" + sha(archive.read_bytes()))
            extracted, payload = Path(tmp) / "extract", Path(tmp) / "payload"
            with patch.object(exporter, "require_hosted"):
                exporter.extract_archive(archive, source, extracted)
                exporter.prepare_export(extracted, source, payload)
            tag = f"preview-F08-W03-source-stills-{RUN_ID}"
            state = {"created": False, "release": None, "uploads": []}

            def fake_gh(args):
                if args[:2] == ["api", f"repos/{exporter.REPO}/releases/tags/{tag}"]:
                    if not state["created"]:
                        return subprocess.CompletedProcess(args, 1, '{"status":"404","message":"Not Found"}', "gh: Not Found (HTTP 404)")
                    return subprocess.CompletedProcess(args, 0, json.dumps(state["release"]), "")
                if args[:3] == ["api", "--method", "POST"]:
                    state["created"] = True
                    state["release"] = {"tag_name": tag, "draft": False, "prerelease": True, "assets": []}
                    return subprocess.CompletedProcess(args, 0, "{}", "")
                if args[:2] == ["api", f"repos/{exporter.REPO}/commits/{tag}"]:
                    return subprocess.CompletedProcess(args, 0, json.dumps({"sha": SOURCE_COMMIT}), "")
                if args[:2] == ["release", "upload"]:
                    file = Path(args[3])
                    state["uploads"].append(file.name)
                    state["release"]["assets"].append({
                        "name": file.name, "size": file.stat().st_size,
                        "digest": "sha256:" + exporter.sha256(file),
                        "browser_download_url": f"https://github.com/{exporter.REPO}/releases/download/{tag}/{file.name}",
                    })
                    return subprocess.CompletedProcess(args, 0, "", "")
                self.fail(f"unexpected gh invocation: {args}")

            with patch.object(exporter, "require_hosted"), patch.object(exporter, "run_gh", side_effect=fake_gh):
                result = exporter.publish_export(payload)
            self.assertEqual(result["assets_verified"], 12)
            self.assertEqual(set(state["uploads"]), exporter.PUBLIC_NAMES)
            self.assertEqual(result["visual_review"], "OPEN")
            self.assertEqual(result["ready"], "NOT_GRANTED")

    def test_existing_run_scoped_tag_on_wrong_commit_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = make_archive(Path(tmp) / "native.zip")
            source = validate_fixture(archive.stat().st_size, "sha256:" + sha(archive.read_bytes()))
            extracted, payload = Path(tmp) / "extract", Path(tmp) / "payload"
            with patch.object(exporter, "require_hosted"):
                exporter.extract_archive(archive, source, extracted)
                exporter.prepare_export(extracted, source, payload)
            tag = f"preview-F08-W03-source-stills-{RUN_ID}"
            def fake_gh(args):
                if args[:2] == ["api", f"repos/{exporter.REPO}/releases/tags/{tag}"]:
                    return subprocess.CompletedProcess(args, 0, json.dumps({
                        "tag_name": tag, "draft": False, "prerelease": True, "assets": []}), "")
                if args[:2] == ["api", f"repos/{exporter.REPO}/commits/{tag}"]:
                    return subprocess.CompletedProcess(args, 0, json.dumps({"sha": "c" * 40}), "")
                self.fail(f"unexpected gh invocation before immutable commit check: {args}")
            with patch.object(exporter, "require_hosted"), patch.object(exporter, "run_gh", side_effect=fake_gh):
                with self.assertRaisesRegex(exporter.Refusal, "exact source commit"):
                    exporter.publish_export(payload)

    def test_local_host_refuses_artifact_operations(self):
        with patch.object(exporter.platform, "system", return_value="Darwin"), patch.dict(exporter.os.environ, {"GITHUB_ACTIONS": "false"}):
            with self.assertRaisesRegex(exporter.Refusal, "GitHub-hosted Ubuntu"):
                exporter.require_hosted()


if __name__ == "__main__":
    unittest.main(verbosity=2)
