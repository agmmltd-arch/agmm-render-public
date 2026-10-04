import hashlib
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rebind_clock", HERE / "rebind-clock.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class RebindClockTests(unittest.TestCase):
    def fixture(self):
        board = {"status": "conditional-estimated", "clock_basis": {"words_per_minute": 155}, "scenes": [
            {"id": "a", "script": "Hello there."}, {"id": "b", "script": "Goodbye now."}
        ]}
        words = [
            {"token": "Hello", "scene_id": "a", "start_s": 0.1, "end_s": 0.3},
            {"token": "there", "scene_id": "a", "start_s": 0.31, "end_s": 0.55},
            {"token": "Goodbye", "scene_id": "b", "start_s": 0.8, "end_s": 1.2},
            {"token": "now", "scene_id": "b", "start_s": 1.21, "end_s": 1.4},
        ]
        return board, {"status": "measured", "script_sha256": "s", "voice_sha256": "v", "measurement_receipt": "R1", "words": words}

    def test_rebinds_scene_boundaries_to_voice(self):
        board, clock = self.fixture()
        out = mod.rebind(board, clock, "s", "v")
        self.assertEqual(out["status"], "measured-clock-bound")
        self.assertEqual((out["scenes"][0]["start_s"], out["scenes"][0]["end_s"]), (0.1, 0.55))
        self.assertEqual((out["scenes"][1]["start_s"], out["scenes"][1]["end_s"]), (0.8, 1.4))

    def test_rejects_stale_voice_hash(self):
        board, clock = self.fixture()
        with self.assertRaisesRegex(ValueError, "bind"):
            mod.rebind(board, clock, "s", "different")

    def test_rejects_token_or_order_drift(self):
        board, clock = self.fixture()
        clock["words"][1]["token"] = "else"
        with self.assertRaisesRegex(ValueError, "differ"):
            mod.rebind(board, clock, "s", "v")

    def test_rejects_overlapping_or_reversed_words(self):
        board, clock = self.fixture()
        clock["words"][1]["start_s"] = 0.2
        with self.assertRaisesRegex(ValueError, "monotonic"):
            mod.rebind(board, clock, "s", "v")

    def test_rejects_missing_measurement_receipt(self):
        board, clock = self.fixture()
        clock["measurement_receipt"] = ""
        with self.assertRaisesRegex(ValueError, "measurement_receipt"):
            mod.rebind(board, clock, "s", "v")


if __name__ == "__main__":
    unittest.main(verbosity=2)
