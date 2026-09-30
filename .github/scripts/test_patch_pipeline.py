#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import shutil
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bind_patch_gate_receipts as binder
import download_patch_inputs as downloader
import patch_master_segments as patcher


REPOSITORY = "agmmltd-arch/agmm-render-public"


def make_request() -> dict:
    duration = 632.434
    return patcher.build_request(
        repository=REPOSITORY, film_id="F07", base_run_id="36760863361",
        base_tag="F07-r4-actions-full-landscape-4k-20260930194517-a1",
        output_tag="F07-r5-patched", duration=duration,
        segments_raw=patcher.legacy_segments(duration),
        patches_raw=[
            {"i": "01", "run_id": "36768428718", "tag": "F07-r4c2-patch-seg01-12-20260930205014"},
            {"i": "12", "run_id": "36768428718", "tag": "F07-r4c2-patch-seg01-12-20260930205014"},
            {"i": "28", "run_id": "36764766443", "tag": "F07-r4b-patch-seg28-29-v2-20260930201835"},
            {"i": "29", "run_id": "36764766443", "tag": "F07-r4b-patch-seg28-29-v2-20260930201835"},
            {"i": "43", "run_id": "36771687018", "tag": "F07-r4d2-patch-seg43-45-52-20260930211821"},
            {"i": "45", "run_id": "36771687018", "tag": "F07-r4d2-patch-seg43-45-52-20260930211821"},
            {"i": "52", "run_id": "36771687018", "tag": "F07-r4d2-patch-seg43-45-52-20260930211821"},
        ],
        source_release="F07-r4-actions-full-landscape-4k-20260930194517",
        source_asset="source.tar.gz", source_sha256="1" * 64,
        overlay_release="F07-overlay", overlay_asset="qa-overlay.tar.gz",
        overlay_sha256="2" * 64,
    )


def make_provenance(request: dict, *, base_conclusion: str = "failure") -> dict:
    repository_id = 1397641626
    patch_run_ids = {row["run_id"] for row in request["patches"]}
    run_ids = sorted({request["base"]["run_id"]} | patch_run_ids, key=int)
    runs = []
    for index, run_id in enumerate(run_ids, 1):
        conclusion = "success" if run_id in patch_run_ids else base_conclusion
        runs.append({
            "run_id": run_id, "status": "completed", "conclusion": conclusion,
            "head_sha": f"{index:x}" * 40, "head_repository": REPOSITORY,
            "head_repository_id": repository_id,
        })
    run_map = {row["run_id"]: row for row in runs}
    patches = {row["i"]: row for row in request["patches"]}
    artifacts = []
    files = []
    for index, segment in enumerate(request["segments"], 1):
        sid = segment["i"]
        patch = patches.get(sid)
        role = "patch_segment" if patch else "base_segment"
        run_id = patch["run_id"] if patch else request["base"]["run_id"]
        name = patch["artifact"] if patch else f"{request['base']['tag']}-SEG{sid}"
        members = [f"SEG{sid}.mp4", f"SEG{sid}.verify.json"]
        artifacts.append({
            "id": index, "name": name, "run_id": run_id,
            "run_head_sha": run_map[run_id]["head_sha"], "archive_sha256": f"{index % 16:x}" * 64,
            "size_in_bytes": index,
            "segment_id": sid, "role": role, "members": members,
        })
        for member in members:
            files.append({
                "role": role, "segment_id": sid, "run_id": run_id,
                "artifact": name, "filename": member, "bytes": index,
                "sha256": f"{(index + 1) % 16:x}" * 64,
            })
    audio_hash = "a" * 64
    files.append({
        "role": "source_audio", "segment_id": None, "run_id": None,
        "artifact": "source.tar.gz", "filename": "F07-SOURCE-MIX.flac",
        "bytes": 4, "sha256": audio_hash,
    })
    provenance = {
        "schema": 2, "kind": "hosted_master_patch_download_provenance",
        "request_sha256": request["request_sha256"],
        "repository": {"full_name": REPOSITORY, "id": repository_id},
        "runs": runs, "artifacts": artifacts,
        "source_audio": {
            "release": request["source_audio"]["release"],
            "release_id": 1,
            "asset": request["source_audio"]["asset"],
            "asset_id": 2,
            "asset_sha256": request["source_audio"]["sha256"],
            "asset_bytes": 100,
            "member": "./audio/mix.flac", "member_bytes": 4, "member_sha256": audio_hash,
        },
        "files": sorted(files, key=lambda row: (row["role"], row["segment_id"] or "", row["filename"])),
    }
    provenance["provenance_sha256"] = patcher.sha256_bytes(patcher.canonical_bytes(provenance))
    return provenance


class PatchRequestTests(unittest.TestCase):
    def test_request_is_unique_normalized_and_hash_bound(self):
        request = make_request()
        self.assertEqual([row["i"] for row in request["patches"]],
                         ["01", "12", "28", "29", "43", "45", "52"])
        self.assertEqual(len(request["segments"]), 73)
        self.assertEqual(sum(row["frames"] for row in request["segments"]), 18973)
        self.assertEqual(request["source_audio"]["sha256"], "1" * 64)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.json"
            path.write_text(json.dumps(request))
            self.assertEqual(patcher.load_request(path), request)
            tampered = json.loads(path.read_text())
            tampered["base"]["run_id"] = "999"
            path.write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValueError, "SHA256"):
                patcher.load_request(path)

    def test_duplicate_patch_and_invalid_repository_are_rejected(self):
        request = make_request()
        raw_patches = [{key: row[key] for key in ("i", "run_id", "tag")}
                       for row in request["patches"]]
        arguments = {
            "repository": REPOSITORY, "film_id": "F07", "base_run_id": "36760863361",
            "base_tag": request["base"]["tag"], "output_tag": "F07-output",
            "duration": request["duration"], "segments_raw": patcher.legacy_segments(request["duration"]),
            "patches_raw": raw_patches + [raw_patches[0]],
            "source_release": request["source_audio"]["release"], "source_asset": "source.tar.gz",
            "source_sha256": "1" * 64, "overlay_release": "overlay", "overlay_asset": "overlay.tar.gz",
            "overlay_sha256": "2" * 64,
        }
        with self.assertRaisesRegex(ValueError, "duplicate patch"):
            patcher.build_request(**arguments)
        arguments["patches_raw"] = raw_patches
        arguments["repository"] = "not-a-repository"
        with self.assertRaisesRegex(ValueError, "repository"):
            patcher.build_request(**arguments)

    def test_provenance_accepts_failed_base_but_requires_successful_patch_runs(self):
        request = make_request()
        provenance = make_provenance(request)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "provenance.json"
            path.write_text(json.dumps(provenance))
            self.assertEqual(patcher.load_download_provenance(path, request), provenance)
            patch_run_id = request["patches"][0]["run_id"]
            next(row for row in provenance["runs"] if row["run_id"] == patch_run_id)["conclusion"] = "failure"
            content = {key: value for key, value in provenance.items() if key != "provenance_sha256"}
            provenance["provenance_sha256"] = patcher.sha256_bytes(patcher.canonical_bytes(content))
            path.write_text(json.dumps(provenance))
            with self.assertRaisesRegex(ValueError, "unverified source run"):
                patcher.load_download_provenance(path, request)

    def test_provenance_rejects_missing_selected_artifact(self):
        request = make_request()
        provenance = make_provenance(request)
        provenance["artifacts"].pop()
        content = {key: value for key, value in provenance.items() if key != "provenance_sha256"}
        provenance["provenance_sha256"] = patcher.sha256_bytes(patcher.canonical_bytes(content))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "provenance.json"
            path.write_text(json.dumps(provenance))
            with self.assertRaisesRegex(ValueError, "one selected artifact per segment"):
                patcher.load_download_provenance(path, request)


class ExactArtifactTests(unittest.TestCase):
    def _archive(self, root: Path, *, unexpected: bool = False) -> Path:
        archive = root / "artifact.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("SEG01.mp4", b"video")
            zf.writestr("SEG01.verify.json", b"{}")
            if unexpected:
                zf.writestr("SURPRISE.txt", b"no")
        return archive

    def test_archive_digest_and_members_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._archive(root)
            destination = root / "out"
            destination.mkdir()
            metadata = {"id": 1, "name": "TAG-SEG01", "archive_sha256": patcher.sha256(source),
                        "size_in_bytes": source.stat().st_size}

            def copy_archive(_command, output):
                shutil.copyfile(source, output)

            with mock.patch.object(downloader, "run_to_file", side_effect=copy_archive):
                paths = downloader.download_artifact(
                    "gh", REPOSITORY, metadata,
                    {"SEG01.mp4", "SEG01.verify.json"},
                    {"SEG01.mp4", "SEG01.verify.json", "SEG01.render.log"}, destination,
                )
            self.assertEqual([path.name for path in paths], ["SEG01.mp4", "SEG01.verify.json"])

            metadata["archive_sha256"] = "0" * 64
            with mock.patch.object(downloader, "run_to_file", side_effect=copy_archive):
                with self.assertRaisesRegex(ValueError, "archive digest/size mismatch"):
                    downloader.download_artifact(
                        "gh", REPOSITORY, metadata,
                        {"SEG01.mp4", "SEG01.verify.json"},
                        {"SEG01.mp4", "SEG01.verify.json"}, root / "unused",
                    )

    def test_unexpected_archive_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._archive(root, unexpected=True)
            destination = root / "out"
            destination.mkdir()
            metadata = {"id": 1, "name": "TAG-SEG01", "archive_sha256": patcher.sha256(source),
                        "size_in_bytes": source.stat().st_size}
            with mock.patch.object(downloader, "run_to_file", side_effect=lambda _c, o: shutil.copyfile(source, o)):
                with self.assertRaisesRegex(ValueError, "member mismatch"):
                    downloader.download_artifact(
                        "gh", REPOSITORY, metadata,
                        {"SEG01.mp4", "SEG01.verify.json"},
                        {"SEG01.mp4", "SEG01.verify.json", "SEG01.render.log"}, destination,
                    )


class SourceAudioTests(unittest.TestCase):
    def _source_archive(self, path: Path, members: list[str]) -> None:
        with tarfile.open(path, "w:gz") as tf:
            for name in members:
                info = tarfile.TarInfo(name)
                info.size = 4
                tf.addfile(info, io.BytesIO(b"FLAC"))

    def test_dot_prefixed_audio_member_is_accepted_and_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.tar.gz"
            self._source_archive(source, ["./audio/mix.flac"])
            destination = root / "out"
            destination.mkdir()
            metadata = {"asset": "source.tar.gz", "asset_id": 7,
                        "asset_sha256": patcher.sha256(source), "asset_bytes": source.stat().st_size}
            with mock.patch.object(downloader, "run_to_file", side_effect=lambda _c, o: shutil.copyfile(source, o)):
                path, receipt = downloader.download_source_audio(
                    "gh", REPOSITORY, metadata, destination, "F07")
            self.assertEqual(path.read_bytes(), b"FLAC")
            self.assertEqual(receipt["member"], "./audio/mix.flac")
            self.assertEqual(receipt["member_sha256"], patcher.sha256(path))

    def test_both_accepted_audio_spellings_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.tar.gz"
            self._source_archive(source, ["audio/mix.flac", "./audio/mix.flac"])
            destination = root / "out"
            destination.mkdir()
            metadata = {"asset": "source.tar.gz", "asset_id": 7,
                        "asset_sha256": patcher.sha256(source), "asset_bytes": source.stat().st_size}
            with mock.patch.object(downloader, "run_to_file", side_effect=lambda _c, o: shutil.copyfile(source, o)):
                with self.assertRaisesRegex(ValueError, "exactly one accepted audio member"):
                    downloader.download_source_audio("gh", REPOSITORY, metadata, destination, "F07")


class GateReceiptTests(unittest.TestCase):
    def test_patch_gate_receipt_binds_passes_to_exact_outputs(self):
        request = make_request()
        provenance = make_provenance(request)
        patch_provenance = {
            "kind": "hosted_master_patch_provenance", "request": request,
            "request_sha256": request["request_sha256"],
            "download_provenance_sha256": provenance["provenance_sha256"],
            "base_integrity_sha256": None, "base_master_sha256": None,
            "source_audio": provenance["source_audio"], "patches": request["patches"],
        }
        patch_provenance["provenance_sha256"] = patcher.sha256_bytes(
            patcher.canonical_bytes(patch_provenance))
        checks = {
            "patch_request_format_and_uniqueness": "PASS",
            "exact_repository_and_source_runs": "PASS",
            "selected_artifact_archives_and_members": "PASS",
            "sealed_source_audio_hash_binding": "PASS",
            "all_hosted_segment_receipts": "PASS",
            "patched_segment_ids": ["01", "12", "28", "29", "43", "45", "52"],
            "master_full_decode": "PASS", "derived_full_decode": "PASS",
            "source_audio_gain_and_aac_encode": "PASS",
            "encoded_audio_loudness_and_true_peak": "PASS",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {name: root / name for name in
                     ("request", "download", "integrity", "patch_provenance", "master", "review", "audit", "out")}
            paths["request"].write_text(json.dumps(request))
            paths["download"].write_text(json.dumps(provenance))
            paths["patch_provenance"].write_text(json.dumps(patch_provenance))
            paths["master"].write_bytes(b"master")
            paths["review"].write_bytes(b"review")
            integrity = {
                "patch_request_sha256": request["request_sha256"],
                "download_provenance_sha256": provenance["provenance_sha256"],
                "patch_provenance_sha256": patch_provenance["provenance_sha256"],
                "outputs": {"master_sha256": patcher.sha256(paths["master"]),
                            "derived_sha256": patcher.sha256(paths["review"])},
                "checks": checks,
            }
            paths["integrity"].write_text(json.dumps(integrity))
            paths["audit"].write_text(json.dumps({
                "technical_pass": True, "full_decode_pass": True, "profile_pass": True,
                "duration_pass": True, "static_detector": {"pass": True},
                "audio": {"pass": True}, "source_run_id": "36779999999",
                "video_sha256": patcher.sha256(paths["review"]),
            }))
            receipt = binder.patch_receipt(SimpleNamespace(
                request=paths["request"], download_provenance=paths["download"],
                integrity=paths["integrity"], patch_provenance=paths["patch_provenance"],
                master=paths["master"], review=paths["review"], audit=paths["audit"],
                workflow_run_id="36779999999", workflow_commit="e" * 40, out=paths["out"],
            ))
            self.assertEqual(receipt["checks"]["full_duration_static_audit"], "PASS")
            paths["review"].write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "output hashes differ"):
                binder.patch_receipt(SimpleNamespace(
                    request=paths["request"], download_provenance=paths["download"],
                    integrity=paths["integrity"], patch_provenance=paths["patch_provenance"],
                    master=paths["master"], review=paths["review"], audit=paths["audit"],
                    workflow_run_id="36779999999", workflow_commit="e" * 40, out=paths["out"],
                ))


if __name__ == "__main__":
    unittest.main()
