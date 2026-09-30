import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import render_short_package as short  # noqa: E402


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ShortPackageTests(unittest.TestCase):
    def valid_parts(self):
        return {
            "parts": [
                {"look": "short-a", "file": "index.html", "out": "S01-A", "off": 0, "dur": 1.0},
                {"look": "short-b", "file": "index.html", "out": "S01-B", "off": 1.0, "dur": 1.0},
            ],
            "frames": 60,
        }

    def test_caps_match_current_kit_contract(self):
        self.assertIn("slow", short.CAP_1080)
        self.assertIn("16", short.CAP_1080)
        self.assertIn("25M", short.CAP_1080)
        self.assertIn("medium", short.CAP_4K)
        self.assertIn("17", short.CAP_4K)
        self.assertIn("60M", short.CAP_4K)
        self.assertNotIn("threads=2", short.CAP_4K)
        self.assertEqual(short.CAP_1080[-2:], ["-movflags", "+faststart"])
        self.assertEqual(short.CAP_4K[-2:], ["-movflags", "+faststart"])

    def test_parts_are_contiguous_and_frame_bound(self):
        parsed = short.validate_parts(self.valid_parts())
        self.assertEqual(parsed["duration"], 2.0)
        self.assertEqual(parsed["frames"], 60)
        broken = self.valid_parts()
        broken["parts"][1]["off"] = 1.1
        with self.assertRaisesRegex(short.ContractError, "not contiguous"):
            short.validate_parts(broken)
        broken = self.valid_parts()
        broken["parts"][0]["look"] = "short-a\nrun: bad"
        with self.assertRaisesRegex(short.ContractError, "unsafe path component"):
            short.validate_parts(broken)

    def test_matrix_has_every_part_at_requested_resolutions(self):
        parsed = short.validate_parts(self.valid_parts())
        matrix = short.build_matrix(parsed["parts"], True)
        self.assertEqual(len(matrix["include"]), 4)
        self.assertEqual([row["resolution"] for row in matrix["include"]], ["1080", "4k", "1080", "4k"])
        self.assertEqual(matrix["include"][1]["suffix"], "-4K")

    def test_safe_extract_rejects_traversal_symlink_and_appledouble(self):
        for name, kind in (("../escape", "file"), ("look/link", "symlink"), ("look/._index.html", "file")):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as folder:
                    archive = Path(folder) / "source.tar.gz"
                    with tarfile.open(archive, "w:gz") as bundle:
                        member = tarfile.TarInfo(name)
                        if kind == "symlink":
                            member.type = tarfile.SYMTYPE
                            member.linkname = "index.html"
                            bundle.addfile(member)
                        else:
                            member.size = 1
                            bundle.addfile(member, io.BytesIO(b"x"))
                    with self.assertRaises(short.ContractError):
                        short.safe_extract(archive, Path(folder) / "out")

    def test_safe_extract_normalises_dot_prefix_and_checks_sha_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "source.tar.gz"
            body = b"<html></html>"
            sha_file = f"{digest(body)}  index.html\n".encode()
            with tarfile.open(archive, "w:gz") as bundle:
                root_member = tarfile.TarInfo("./")
                root_member.type = tarfile.DIRTYPE
                bundle.addfile(root_member)
                for name, data in (("./look/index.html", body), ("./look/static_check.py", b"pass\n"),
                                   ("./look/SHA256SUMS.txt", sha_file.replace(b"index.html", b"./index.html"))):
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    bundle.addfile(member, io.BytesIO(data))
            destination = root / "out"
            short.safe_extract(archive, destination)
            short.validate_sha_file(destination, "look")
            self.assertEqual((destination / "look/index.html").read_bytes(), body)

    def test_part_source_must_exist_inside_project(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for look in ("short-a", "short-b"):
                look_root = root / look
                look_root.mkdir()
                (look_root / "static_check.py").write_text("pass\n")
                (look_root / "index.html").write_text(look)
                (look_root / "SHA256SUMS.txt").write_text(
                    f"{short.sha256(look_root / 'index.html')}  index.html\n"
                )
            short.validate_parts(self.valid_parts(), root)
            (root / "short-b/index.html").unlink()
            with self.assertRaisesRegex(short.ContractError, "source is missing"):
                short.validate_parts(self.valid_parts(), root)

    def test_allowed_frame_counts_match_produce_explained_trailing_frame(self):
        self.assertEqual(short.allowed_frame_counts(14.433333333333334), {433, 434})
        self.assertEqual(short.allowed_frame_counts(14.0), {420, 421})

    def test_ebur128_parser_uses_final_summary(self):
        text = """Summary:\n  I: -70.0 LUFS\n  LRA: 0.0 LU\n  Peak: -20.0 dBFS\n\nSummary:\n  I: -14.2 LUFS\n  LRA: 3.4 LU\n  Peak: -1.3 dBFS\n"""
        self.assertEqual(short.parse_ebur128(text), {
            "integrated_lufs": -14.2, "lra_lu": 3.4, "true_peak_dbfs": -1.3,
        })

    def test_review_times_cover_hook_quarters_and_all_seams(self):
        parsed = short.validate_parts(self.valid_parts())
        times = short.review_times(parsed["parts"], parsed["duration"])
        self.assertEqual(times[0], 0.4)
        self.assertIn(0.96, times)
        self.assertIn(1.02, times)
        self.assertIn(1.06, times)
        self.assertIn(1.6, times)

    def test_exact_hash_rejects_wrong_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "asset"
            path.write_bytes(b"actual")
            with self.assertRaisesRegex(short.ContractError, "mismatch"):
                short.verify_hash(path, digest(b"other"), "asset_sha256")


if __name__ == "__main__":
    unittest.main()
