import hashlib
import io
import json
import struct
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import capture_short_package as capture  # noqa: E402
import render_short_package as short  # noqa: E402


def png(width=1080, height=1920):
    return capture.PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height)


class CaptureShortPackageTests(unittest.TestCase):
    def fixture(self, root: Path):
        source_tree = root / "source-tree"
        media_rows = []
        for look in ("short-a", "short-b"):
            look_root = source_tree / look
            (look_root / "img").mkdir(parents=True)
            files = {
                "index.html": f'<main data-composition-id="{look}" data-width="1080" '
                              'data-height="1920" data-duration="1"></main>'.encode(),
                "static_check.py": b"print('ok')\n",
                "img/evidence.png": (look + "-evidence").encode(),
            }
            for name, data in files.items():
                path = look_root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            checksums = "".join(
                f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files.items()
            )
            (look_root / "SHA256SUMS.txt").write_text(checksums)
            media_rows.append({
                "path": f"{look}/img/evidence.png",
                "sha256": hashlib.sha256(files["img/evidence.png"]).hexdigest(),
                "bytes": len(files["img/evidence.png"]),
            })
        source = root / "source.tar.gz"
        with tarfile.open(source, "w:gz") as bundle:
            for path in sorted(source_tree.rglob("*")):
                if path.is_file():
                    bundle.add(path, arcname=path.relative_to(source_tree), recursive=False)
        source_hash = short.sha256(source)
        parts_data = {
            "parts": [
                {"look": "short-a", "file": "index.html", "out": "S01-A", "off": 0, "dur": 1},
                {"look": "short-b", "file": "index.html", "out": "S01-B", "off": 1, "dur": 1},
            ],
            "sha256": source_hash,
            "bytes": source.stat().st_size,
            "frames": 60,
        }
        parts = root / "parts.json"
        parts.write_text(json.dumps(parts_data))
        parts_hash = short.sha256(parts)
        media_hash = capture.media_identity_sha256(media_rows)
        plan_data = {
            "version": 1,
            "short_id": "S01",
            "source_sha256": source_hash,
            "parts_sha256": parts_hash,
            "media_identity_sha256": media_hash,
            "include_part_seams": True,
            "captures": [
                {"name": "named-beat", "kind": "beat", "global": 0.5,
                 "look": "short-a", "local": 0.5},
            ],
        }
        plan = root / "capture-plan.json"
        plan.write_text(json.dumps(plan_data))
        return {
            "source": source,
            "parts_path": parts,
            "plan_path": plan,
            "source_sha256": source_hash,
            "parts_sha256": parts_hash,
            "plan_sha256": short.sha256(plan),
            "expected_media_sha256": media_hash,
        }

    def prepare_fixture(self, root: Path):
        args = self.fixture(root)
        args["output"] = root / "prepared"
        manifest = capture.prepare(**args)
        return args, manifest

    def test_prepare_binds_source_parts_plan_and_media_and_adds_all_part_seams(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args, manifest = self.prepare_fixture(root)
            self.assertEqual(manifest["technical_status"], "INPUT_IDENTITY_PASS")
            self.assertEqual(manifest["editorial_status"], "NOT_REVIEWED")
            self.assertEqual(manifest["publication_status"], "NOT_REQUESTED")
            self.assertEqual(manifest["capture_count"], 4)
            self.assertEqual(
                [row["global"] for row in manifest["captures"]],
                [0.5, 0.96, 1.02, 1.06],
            )
            self.assertEqual(
                manifest["binding"]["media_identity_sha256"], args["expected_media_sha256"]
            )

    def test_prepare_rejects_media_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = self.fixture(root)
            args["output"] = root / "prepared"
            args["expected_media_sha256"] = "0" * 64
            with self.assertRaisesRegex(short.ContractError, "media_identity_sha256 mismatch"):
                capture.prepare(**args)

    def test_media_identity_contract_rejects_unlisted_media(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = self.fixture(root)
            project = root / "project"
            short.safe_extract(args["source"], project)
            parsed = short.validate_parts(json.loads(args["parts_path"].read_text()), project)
            (project / "short-a/img/unlisted.png").write_bytes(b"unlisted")
            with self.assertRaisesRegex(short.ContractError, "media manifest mismatch"):
                capture.media_identities(project, parsed["parts"])

    def test_prepare_uses_shared_safe_extraction_and_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = self.fixture(root)
            with tarfile.open(args["source"], "w:gz") as bundle:
                member = tarfile.TarInfo("../escape")
                member.size = 1
                bundle.addfile(member, io.BytesIO(b"x"))
            args["source_sha256"] = short.sha256(args["source"])
            args["output"] = root / "prepared"
            with self.assertRaisesRegex(short.ContractError, "unsafe archive path"):
                capture.prepare(**args)

    def test_plan_rejects_wrong_global_to_local_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = self.fixture(root)
            plan = json.loads(args["plan_path"].read_text())
            plan["captures"][0]["local"] = 0.7
            args["plan_path"].write_text(json.dumps(plan))
            args["plan_sha256"] = short.sha256(args["plan_path"])
            args["output"] = root / "prepared"
            with self.assertRaisesRegex(short.ContractError, "does not match global-to-local"):
                capture.prepare(**args)

    def test_plan_rejects_duplicate_named_and_automatic_seam_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = self.fixture(root)
            plan = json.loads(args["plan_path"].read_text())
            plan["captures"][0].update({"global": 0.96, "local": 0.96})
            args["plan_path"].write_text(json.dumps(plan))
            args["plan_sha256"] = short.sha256(args["plan_path"])
            args["output"] = root / "prepared"
            with self.assertRaisesRegex(short.ContractError, "duplicate capture timestamp"):
                capture.prepare(**args)

    def make_raw_snapshots(self, manifest: dict, root: Path):
        raw_roots = {}
        for group in manifest["by_look"]:
            raw = root / "raw" / group["look"]
            raw.mkdir(parents=True)
            for index, point in enumerate(group["captures"]):
                (raw / f"frame-{index:02d}-at-{point['local']:.3f}s.png").write_bytes(png())
            raw_roots[group["look"]] = raw
        return raw_roots

    def collect_all(self, manifest_path: Path, manifest: dict, raw_roots: dict, root: Path):
        captured = root / "captured"
        for group in manifest["by_look"]:
            capture.collect(
                manifest_path=manifest_path,
                look=group["look"],
                snapshots=raw_roots[group["look"]],
                output=captured / group["look"],
            )
        return captured

    def test_collect_requires_exact_count_time_and_native_dimensions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args, manifest = self.prepare_fixture(root)
            raw = self.make_raw_snapshots(manifest, root)
            first_group = manifest["by_look"][0]
            receipt = capture.collect(
                manifest_path=args["output"] / "CAPTURE-MANIFEST.json",
                look=first_group["look"], snapshots=raw[first_group["look"]],
                output=root / "one",
            )
            self.assertEqual(receipt["technical_status"], "CAPTURE_PASS")
            self.assertEqual(receipt["editorial_status"], "NOT_REVIEWED")
            frame = next(raw[first_group["look"]].glob("frame-*.png"))
            frame.write_bytes(png(720, 1280))
            with self.assertRaisesRegex(short.ContractError, "expected 1080x1920"):
                capture.collect(
                    manifest_path=args["output"] / "CAPTURE-MANIFEST.json",
                    look=first_group["look"], snapshots=raw[first_group["look"]],
                    output=root / "wrong-size",
                )

    def test_bundle_is_capture_only_and_rejects_tampered_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args, manifest = self.prepare_fixture(root)
            raw = self.make_raw_snapshots(manifest, root)
            captured = self.collect_all(
                args["output"] / "CAPTURE-MANIFEST.json", manifest, raw, root
            )
            evidence = capture.bundle(
                manifest_path=args["output"] / "CAPTURE-MANIFEST.json",
                media_path=args["output"] / "MEDIA-IDENTITIES.json",
                captured=captured, output=root / "bundle",
            )
            self.assertEqual(evidence["full_video_render"], "NOT_RUN")
            self.assertEqual(evidence["full_video_decode"], "NOT_RUN")
            self.assertEqual(evidence["editorial_status"], "NOT_REVIEWED")
            self.assertEqual(len(list((root / "bundle/frames").glob("*.png"))), 4)
            target = next((captured / manifest["by_look"][0]["look"] / "frames").glob("*.png"))
            target.write_bytes(png() + b"tamper")
            with self.assertRaisesRegex(short.ContractError, "capture bytes differ"):
                capture.bundle(
                    manifest_path=args["output"] / "CAPTURE-MANIFEST.json",
                    media_path=args["output"] / "MEDIA-IDENTITIES.json",
                    captured=captured, output=root / "tampered-bundle",
                )

    def test_workflow_is_snapshot_only_and_uploads_one_compact_artifact(self):
        workflow = (SCRIPTS.parent / "workflows/agmm-short-capture.yml").read_text()
        self.assertIn("hyperframes@0.8.71 snapshot", workflow)
        self.assertIn("--no-end", workflow)
        self.assertIn("--describe false", workflow)
        self.assertNotIn("hyperframes@0.8.71 render", workflow)
        self.assertNotIn("FINAL.mp4", workflow)
        self.assertEqual(workflow.count("actions/upload-artifact@"), 1)
        self.assertIn("editorial status remains NOT_REVIEWED", workflow)


if __name__ == "__main__":
    unittest.main()
