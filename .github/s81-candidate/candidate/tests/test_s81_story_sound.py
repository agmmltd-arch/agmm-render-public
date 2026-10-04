import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENE = (ROOT / "scenes.js").read_text()
PLAN = json.loads((ROOT / "capture-plan-source.json").read_text())
WORDS = json.loads((ROOT.parent / "voice-text/S81.words.json").read_text())["words"]
MIX = json.loads((ROOT / "mix_spec.json").read_text())
ASSETS = json.loads((ROOT / "selected-sound-assets.json").read_text())


def word_span(token):
    rows = [w for w in WORDS if w["word"].strip(".,!?\"'“”").lower() == token.lower()]
    if not rows:
        raise AssertionError(f"missing authenticated word: {token}")
    return min(w["start"] for w in rows), max(w["end"] for w in rows)


class StoryAndSoundTests(unittest.TestCase):
    def test_scene_transitions_bind_to_voice_and_privacy_card_leads_narration(self):
        self.assertIn("enter(tl, context, 18.40, 24.667", SCENE)
        self.assertIn("enter(tl, statement, 24.667, 29.20", SCENE)
        self.assertIn("enter(tl, guardian, 34.50, 37.753", SCENE)
        self.assertIn("enter(tl, consequences, 37.753, 41.927", SCENE)
        self.assertIn("41.827);", SCENE)
        self.assertEqual(word_span("No")[0], 42.027)
        self.assertEqual(word_span("consequences")[1], 41.506)
        self.assertEqual(word_span("Follow")[0], 51.834)
        self.assertIn("enter(tl, lesson, 46.60, 51.60", SCENE)
        self.assertIn("duration: .23, ease: \"back.out(1.05)\" }, 51.56);", SCENE)
        self.assertLess(51.56 + .23, word_span("Follow")[0])
        captures = {r["name"]: r["global_s"] for r in PLAN["named_captures"]}
        self.assertEqual(len(captures), 19)
        self.assertEqual(captures["privacy-line-start"], 42.027)
        self.assertEqual(captures["privacy-qualification"], 42.65)
        self.assertEqual(captures["privacy-qualification-settled"], 43.5)
        self.assertEqual(captures["cta-follow-start"], 51.834)
        self.assertEqual(captures["cta-audit-link"], 52.4)
        self.assertEqual(captures["cta-follow-start"], 51.834)
        self.assertEqual(captures["cta-audit-link"], 52.4)

    def test_source_copy_and_attribution_are_retained(self):
        for text in (
            "The agent ‘infiltrated’ a statistics portal containing ‘non-sensitive’ Medicare data.",
            "OpenAI said its models were looking up statistics about Australia during an internal evaluation.",
            "In the course of that, our models took actions we did not intend.",
            "No personal information is believed to have been accessed ‘at this stage’, but investigations are ongoing.",
            "Source: BBC News · 24 Sep 2026",
            "Source: The Guardian · 24 Sep 2026",
        ):
            self.assertIn(text, SCENE)

    def test_distinct_story_objects_and_labeled_controls_replace_repeat_card(self):
        for obj in ("s81-portal", "s81-boundary", "s81-file", "s81-evaluation", "s81-calendar", "s81-mailbox", "s81-letter", "s81-shield", "s81-control"):
            self.assertIn(obj, SCENE)
        self.assertIn("Can an agent reach it?", SCENE)
        self.assertIn("Who hears within the day?", SCENE)
        self.assertIn("AGMM ILLUSTRATION · NOT A QUOTE", SCENE)
        self.assertNotIn("s81-sheet", SCENE)

    def test_existing_provisional_mix_and_rights_are_unchanged(self):
        self.assertEqual(MIX["voice"]["src"], "../media/voice/S81.wav")
        self.assertEqual(MIX["music"]["src"], "../media/music/neon-noir.mp3")
        self.assertEqual(MIX["master"], {"integrated_lufs": -14.0, "true_peak_dbtp": -1.0})
        self.assertFalse(MIX["ambience"]["regions"])
        self.assertEqual(ASSETS["status"], "PROVISIONAL_SELECTION_UNAUDITIONED_AND_NOT_STAGED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
