from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).parents[1]
CANDIDATE = ROOT / "candidate/f08_preview_export.py"
SCRIPT = CANDIDATE if CANDIDATE.is_file() else Path(__file__).with_name("f08_preview_export.py")
NATIVE = ROOT / "native-metadata"
spec = importlib.util.spec_from_file_location("f08_preview_export", SCRIPT)
exporter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = exporter
spec.loader.exec_module(exporter)


def fixture(name):
    captured = NATIVE / name
    if captured.is_file():
        return json.loads(captured.read_text(encoding="utf-8"))
    if name == "repository.json":
        return {"full_name": exporter.REPO, "id": exporter.REPOSITORY_ID,
                "private": False, "visibility": "public"}
    if name == "run.json":
        return {"id": exporter.RUN_ID, "repository": {"full_name": exporter.REPO},
                "path": exporter.RUN_WORKFLOW, "event": "workflow_dispatch",
                "status": "completed", "conclusion": "success", "head_sha": exporter.RUN_HEAD,
                "run_attempt": 1, "display_title": exporter.RUN_TITLE,
                "created_at": "2026-10-04T15:35:55Z", "updated_at": "2026-10-04T15:37:37Z"}
    if name == "jobs.json":
        return {"total_count": 1, "jobs": [{"id": exporter.JOB_ID, "name": exporter.JOB_NAME,
                "run_id": exporter.RUN_ID, "head_sha": exporter.RUN_HEAD,
                "status": "completed", "conclusion": "success"}]}
    if name == "artifacts.json":
        return {"total_count": 1, "artifacts": [{"id": exporter.ARTIFACT_ID,
                "name": exporter.ARTIFACT_NAME, "size_in_bytes": exporter.ARTIFACT_BYTES,
                "digest": exporter.ARTIFACT_DIGEST, "expired": False,
                "created_at": exporter.ARTIFACT_CREATED, "expires_at": exporter.ARTIFACT_EXPIRES,
                "workflow_run": {"id": exporter.RUN_ID, "head_sha": exporter.RUN_HEAD,
                                 "repository_id": exporter.REPOSITORY_ID}}]}
    raise AssertionError(f"unknown fixture {name}")


def source_receipt():
    return {
        "run_id": exporter.RUN_ID, "repository": exporter.REPO,
        "repository_id": exporter.REPOSITORY_ID, "workflow": exporter.RUN_WORKFLOW,
        "head_sha": exporter.RUN_HEAD, "job_id": exporter.JOB_ID,
        "job_name": exporter.JOB_NAME, "conclusion": "success", "run_attempt": 1,
        "artifact": {"id": exporter.ARTIFACT_ID, "name": exporter.ARTIFACT_NAME,
            "size_in_bytes": exporter.ARTIFACT_BYTES, "digest": exporter.ARTIFACT_DIGEST,
            "created_at": exporter.ARTIFACT_CREATED, "expires_at": exporter.ARTIFACT_EXPIRES},
    }


def fake_png(width, height):
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" +
            width.to_bytes(4, "big") + height.to_bytes(4, "big"))


def proof_manifest(video_bytes):
    return {
        "status": "HOSTED_RENDER_AND_DECODE_PASS",
        "scope": "silent 12-second 1920x1080 30 fps diagnostic preview; not full film or release approval",
        "repository": exporter.REPO, "source_commit": exporter.RUN_HEAD,
        "video_file": Path(exporter.VIDEO_PATH).name, "video_bytes": video_bytes,
        "video_hash": "not computed by request", "width": 1920, "height": 1080,
        "frame_rate": "30/1", "decoded_frame_count": 360, "duration_seconds": 12.0,
        "audio_streams": 0, "full_ffmpeg_decode": "PASS",
    }


def probe_doc():
    return {"streams": [{"codec_type": "video", "width": 1920, "height": 1080,
                         "r_frame_rate": "30/1", "nb_read_frames": "360"}],
            "format": {"duration": "12.000000"}}


def fake_tree(root, proof=None, probe=None):
    root.mkdir()
    video = b"\x00\x00\x00\x18ftypisom" + b"synthetic-preview-bytes" * 10
    for path in exporter.EXPECTED_ARTIFACT_FILES:
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path == exporter.VIDEO_PATH:
            dest.write_bytes(video)
        elif path == exporter.PROOF_PATH:
            dest.write_text(json.dumps(proof or proof_manifest(len(video))) + "\n")
        elif path == exporter.PROBE_PATH:
            dest.write_text(json.dumps(probe or probe_doc()) + "\n")
        elif path == exporter.CONTACT_PATH:
            dest.write_bytes(fake_png(1920, 1620))
        elif path in exporter.FRAME_PATHS:
            dest.write_bytes(fake_png(1920, 1080))
        elif path == exporter.LOG_PATH:
            dest.write_text("synthetic hosted render log\n")
        elif path == "node-version.txt":
            dest.write_text("v22.23.3\n")
        elif path == "hyperframes-version.txt":
            dest.write_text("0.8.71\n")
        elif path == "ffmpeg-version.txt":
            dest.write_text("ffmpeg version 6.1.1-3ubuntu5 Copyright ...\n")
        elif path == "python-version.txt":
            dest.write_text("Python 3.12.3\n")
    return video


def zip_tree(tree, zip_path, symlink_name=None):
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(exporter.EXPECTED_ARTIFACT_FILES):
            if symlink_name == name:
                info = zipfile.ZipInfo(name)
                info.external_attr = 0o120777 << 16
                archive.writestr(info, (tree / name).read_bytes())
            else:
                archive.write(tree / name, arcname=name)


def patch_archive_metadata(archive, source):
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    source["artifact"]["size_in_bytes"] = archive.stat().st_size
    source["artifact"]["digest"] = "sha256:" + digest
    return patch.object(exporter, "ARTIFACT_BYTES", archive.stat().st_size), patch.object(
        exporter, "ARTIFACT_DIGEST", "sha256:" + digest)


class SourceMetadataTests(unittest.TestCase):
    def test_exact_public_run_job_artifact_metadata_passes(self):
        result = exporter.validate_source(
            fixture("repository.json"), fixture("run.json"), fixture("jobs.json"),
            fixture("artifacts.json"), datetime(2026, 10, 4, 15, 40, tzinfo=timezone.utc))
        self.assertEqual(result["run_id"], 37213603867)
        self.assertEqual(result["job_id"], 111469551150)
        self.assertEqual(result["artifact"]["digest"], exporter.ARTIFACT_DIGEST)

    def test_private_repo_wrong_source_commit_or_failed_run_refused(self):
        repo = fixture("repository.json"); repo["private"] = True
        with self.assertRaisesRegex(exporter.Refusal, "public repository"):
            exporter.validate_source(repo, fixture("run.json"), fixture("jobs.json"), fixture("artifacts.json"))
        for key, value in (("head_sha", "f" * 40), ("conclusion", "failure"), ("status", "in_progress")):
            run = fixture("run.json"); run[key] = value
            with self.subTest(key=key), self.assertRaises(exporter.Refusal):
                exporter.validate_source(fixture("repository.json"), run, fixture("jobs.json"), fixture("artifacts.json"))

    def test_changed_job_or_artifact_digest_refused(self):
        jobs = fixture("jobs.json"); jobs["jobs"][0]["id"] += 1
        with self.assertRaisesRegex(exporter.Refusal, "job"):
            exporter.validate_source(fixture("repository.json"), fixture("run.json"), jobs, fixture("artifacts.json"))
        artifacts = fixture("artifacts.json"); artifacts["artifacts"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(exporter.Refusal, "artifact"):
            exporter.validate_source(fixture("repository.json"), fixture("run.json"), fixture("jobs.json"), artifacts)

    def test_expired_source_artifact_refused(self):
        with self.assertRaisesRegex(exporter.Refusal, "expired"):
            exporter.validate_source(fixture("repository.json"), fixture("run.json"), fixture("jobs.json"),
                                     fixture("artifacts.json"), datetime(2026, 10, 8, tzinfo=timezone.utc))


class ArtifactContractTests(unittest.TestCase):
    def test_exact_28_file_contract_and_render_manifest_validate(self):
        self.assertEqual(len(exporter.EXPECTED_ARTIFACT_FILES), 28)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifact"
            video = fake_tree(root)
            files = exporter.regular_exact_tree(root, exporter.EXPECTED_ARTIFACT_FILES)
            self.assertEqual(files[exporter.VIDEO_PATH].stat().st_size, len(video))
            evidence = exporter.validate_render_evidence(files)
            self.assertEqual(evidence["proof"]["decoded_frame_count"], 360)
            self.assertEqual(evidence["versions"]["hyperframes"], "0.8.71")

    def test_missing_and_extra_files_refused(self):
        for mode in ("missing", "extra"):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "artifact"
                fake_tree(root)
                if mode == "missing": (root / exporter.FRAME_PATHS[0]).unlink()
                else: (root / "unexpected.txt").write_text("extra")
                with self.subTest(mode=mode), self.assertRaisesRegex(exporter.Refusal, "allowlist"):
                    exporter.regular_exact_tree(root, exporter.EXPECTED_ARTIFACT_FILES)

    def test_wrong_duration_audio_geometry_framecount_or_contact_dims_refused(self):
        mutations = ("duration", "audio", "geometry", "frames", "contact")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "artifact"
                fake_tree(root)
                if mutation == "contact": (root / exporter.CONTACT_PATH).write_bytes(fake_png(1918, 1620))
                elif mutation == "duration":
                    doc = probe_doc(); doc["format"]["duration"] = "58.3"
                    (root / exporter.PROBE_PATH).write_text(json.dumps(doc))
                elif mutation == "audio":
                    doc = probe_doc(); doc["streams"].append({"codec_type": "audio"})
                    (root / exporter.PROBE_PATH).write_text(json.dumps(doc))
                elif mutation == "geometry":
                    doc = probe_doc(); doc["streams"][0]["width"] = 1080
                    (root / exporter.PROBE_PATH).write_text(json.dumps(doc))
                elif mutation == "frames":
                    doc = probe_doc(); doc["streams"][0]["nb_read_frames"] = "359"
                    (root / exporter.PROBE_PATH).write_text(json.dumps(doc))
                with self.assertRaises(exporter.Refusal):
                    exporter.validate_render_evidence(exporter.regular_exact_tree(root, exporter.EXPECTED_ARTIFACT_FILES))

    def test_bad_archive_digest_or_link_member_refused_before_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); tree = root / "tree"; fake_tree(tree)
            archive = root / "proof.zip"; zip_tree(tree, archive)
            source = source_receipt()
            p_size, p_digest = patch_archive_metadata(archive, source)
            with patch.object(exporter, "require_hosted_runner"), p_size, p_digest:
                with self.assertRaisesRegex(exporter.Refusal, "digest"):
                    wrong = archive.with_name("wrong.zip"); changed = bytearray(archive.read_bytes()); changed[-1] ^= 1
                    wrong.write_bytes(changed)
                    exporter.extract_artifact_zip(wrong, source_receipt(), root / "out")
            symlink_archive = root / "symlink.zip"; zip_tree(tree, symlink_archive, exporter.FRAME_PATHS[0])
            source2 = source_receipt(); p_size, p_digest = patch_archive_metadata(symlink_archive, source2)
            with patch.object(exporter, "require_hosted_runner"), p_size, p_digest:
                with self.assertRaisesRegex(exporter.Refusal, "link"):
                    exporter.extract_artifact_zip(symlink_archive, source2, root / "symlink-out")

    def test_exact_artifact_extracts_then_prepares_durable_review_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); tree = root / "tree"; video = fake_tree(tree)
            archive = root / "proof.zip"; zip_tree(tree, archive)
            source = source_receipt(); size_patch, digest_patch = patch_archive_metadata(archive, source)
            with patch.object(exporter, "require_hosted_runner"), size_patch, digest_patch:
                result = exporter.extract_artifact_zip(archive, source, root / "extracted")
                receipt = exporter.prepare_export(root / "extracted", source, root / "release")
            self.assertEqual(len(result["members"]), 28)
            self.assertEqual(receipt["source"]["artifact_id"], exporter.ARTIFACT_ID)
            self.assertEqual(receipt["visual_review"], "OPEN")
            self.assertEqual(receipt["release_approval"], "NOT_GRANTED")
            self.assertFalse(receipt["library_pointer_updated"])
            release_files = {path.name for path in (root / "release").iterdir()}
            self.assertEqual(release_files, {exporter.VIDEO_NAME, exporter.CONTACT_NAME,
                *exporter.FRAME_NAMES, exporter.TECH_NAME, exporter.SUMS_NAME, exporter.RECEIPT_NAME})
            self.assertEqual((root / "release" / exporter.VIDEO_NAME).read_bytes(), video)
            self.assertNotIn("render.log", " ".join(release_files))
            sums = (root / "release" / exporter.SUMS_NAME).read_text()
            self.assertEqual(len(sums.splitlines()), len(release_files) - 1)
            self.assertTrue(receipt["preview_playback_url"].endswith("/" + exporter.VIDEO_NAME))

    def test_release_notes_link_direct_playback_contact_sheet_and_all_keyframes(self):
        notes = exporter.release_notes("preview-F08-W06-development-37213603867")
        self.assertIn(exporter.VIDEO_NAME, notes)
        self.assertIn(exporter.CONTACT_NAME, notes)
        self.assertIn("11.50s frame", notes)
        self.assertIn("not the complete film", notes)
        self.assertIn("not received visual", notes)

    def test_existing_release_asset_mismatch_and_unexpected_asset_refused(self):
        expected = {"x.png": {"size": 1, "sha256": "a" * 64}}
        good = {"name": "x.png", "size": 1, "digest": "sha256:" + "a" * 64,
                "browser_download_url": "https://github.com/agmmltd-arch/agmm-render-public/releases/download/tag/x.png"}
        self.assertIn("x.png", exporter.validate_release_assets(expected, [good], "tag"))
        with self.assertRaises(exporter.Refusal):
            exporter.validate_release_assets(expected, [{**good, "size": 2}], "tag")
        with self.assertRaisesRegex(exporter.Refusal, "unexpected"):
            exporter.validate_release_assets(expected, [{**good, "name": "other.png"}], "tag")

    def test_prepared_release_tree_rejects_extra_directory_before_release_lookup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); tree = root / "tree"; fake_tree(tree)
            source = source_receipt()
            with patch.object(exporter, "require_hosted_runner"):
                exporter.prepare_export(tree, source, root / "release")
            (root / "release" / "unexpected-dir").mkdir()
            with patch.object(exporter, "require_hosted_runner"), patch.object(exporter, "run_gh") as gh:
                with self.assertRaisesRegex(exporter.Refusal, "non-file"):
                    exporter.publish_export(root / "release")
                gh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
