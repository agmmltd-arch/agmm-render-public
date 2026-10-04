import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent / "scenes.js"
# Resolve the text-only word-clock through package-relative provenance. No local
# filesystem path or audio bytes are required by the test.
WORDS = next((path for path in (
    ROOT.parent / "voice-text/S81.words.json",
    ROOT.parent / "hosted-capture-proposal/payload/voice-text/S81.words.json",
) if path.is_file()), ROOT.parent / "voice-text/S81.words.json")

class StoryAndSoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = (ROOT / "scenes.js").read_text()
        cls.original = ORIGINAL.read_text()
        cls.plan = json.loads((ROOT / "capture-plan.json").read_text())
        cls.mix = json.loads((ROOT / "mix_spec.json").read_text())
        cls.assets = json.loads((ROOT / "selected-sound-assets.json").read_text())
        cls.words = json.loads(WORDS.read_text())["words"]

    def span(self, phrase):
        found = [w for w in self.words if w["word"].strip(".,!?\"'“”") in phrase.split()]
        self.assertTrue(found, phrase)
        return min(w["start"] for w in found), max(w["end"] for w in found)

    def test_original_source_mismatch_is_reproduced_and_candidate_corrects_it(self):
        self.assertIn("at(tl, statement, 18.40, 22.88)", self.original)
        self.assertIn("at(tl, context, 22.88, 29.20)", self.original)
        self.assertIn("at(tl, context, 18.40, 24.667)", self.scene)
        self.assertIn("at(tl, statement, 24.667, 29.20)", self.scene)
        self.assertIn("at(tl, guardian, 34.50, 37.753)", self.scene)
        self.assertIn("at(tl, consequences, 37.753, 42.64)", self.scene)
        self.assertIn("OpenAI said its models were looking up statistics about Australia during an internal evaluation.", self.scene)

    def test_voice_clock_binds_card_starts_and_review_captures(self):
        starts = {r["name"]: r["global_s"] for r in self.plan["named_captures"]}
        self.assertAlmostEqual(starts["unintended-actions-quote"], 24.75)
        self.assertAlmostEqual(starts["albanese-response"], 37.80)
        q = next(w for w in self.words if w["word"].lower() == "our" and w["start"] > 24)
        self.assertAlmostEqual(q["start"], 25.918)
        evaluation = next(w for w in self.words if w["word"].lower() == "internal")
        self.assertAlmostEqual(evaluation["start"], 22.895)
        albanese = next(w for w in self.words if w["word"].lower() == "albanese" and w["start"] > 35)
        self.assertAlmostEqual(albanese["start"], 37.753)

    def test_mix_is_bound_to_selected_voice_and_56_365_clock(self):
        self.assertEqual(self.mix["id"], "S81-evidence-route-candidate-v1")
        self.assertEqual(self.mix["voice"]["src"], "../media/voice/S81.wav")
        self.assertEqual(self.mix["words"], "../media/voice/S81.words.json")
        self.assertEqual(self.mix["music"]["src"], "../media/music/neon-noir.mp3")
        self.assertEqual(self.mix["sfx"]["library"], "../media/sfx/library-selected.json")
        self.assertEqual(self.mix["master"], {"integrated_lufs": -14.0, "true_peak_dbtp": -1.0})
        self.assertFalse((ROOT / "../media/voice/S81.wav").exists())

    def test_all_sfx_are_catalogued_licensed_and_clear_of_emphasis_windows(self):
        cues = self.mix["sfx"]["cues"]
        self.assertEqual(len(cues), 10)
        self.assertGreaterEqual(len(cues) / (56.365 / 60.0), 10.0)
        lib = {x["id"]: x for x in self.assets["sfx_items"]}
        words = self.words
        emph = [(w["start"] - 0.150, w["end"] + 0.150) for w in words if w.get("emphasis")]
        for cue in cues:
            item = lib[cue["sfx_id"]]
            self.assertEqual(item["hosted_package_path"], "media/sfx/" + item["path"])
            self.assertIn("Sonniss GDC bundle license", item["license"])
            self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
            onset = item.get("onset_ms", 0.0) / 1000.0
            clip_start = cue["t"] - onset
            clip_end = clip_start + item["duration_s"]
            self.assertTrue(0 <= clip_start < clip_end <= 56.365, cue)
            self.assertFalse(any(clip_start < b and clip_end > a for a, b in emph), cue)
            self.assertFalse(cue["designed_hit"])
        self.assertEqual(len(self.assets["sfx_items"]), 9)

    def test_music_rights_and_actual_audition_remain_explicit(self):
        self.assertEqual(self.assets["music"]["id"], "neon-noir")
        self.assertEqual(self.assets["music"]["license"], "CC BY 4.0")
        self.assertEqual(self.assets["music"]["artist"], "Shane Ivers")
        self.assertIn("not proof of staged asset bytes", self.assets["music_sha_semantics"])
        self.assertEqual(self.assets["status"], "PROVISIONAL_SELECTION_UNAUDITIONED_AND_NOT_STAGED")
        self.assertEqual(self.mix["ambience"]["regions"], [])

    def test_candidate_contains_no_media_payload(self):
        media_suffixes = {".wav", ".mp3", ".mp4", ".png", ".jpg", ".jpeg", ".webp"}
        found = [p.name for p in ROOT.rglob("*") if p.is_file() and p.suffix.lower() in media_suffixes]
        self.assertEqual(found, [])

if __name__ == "__main__":
    unittest.main(verbosity=2)
