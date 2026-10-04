import json
import os
import re
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import source_capture

ROOT = Path(__file__).resolve().parents[1]
BOARD = json.loads((ROOT / "inputs/storyboard-wave03.json").read_text())
SCRIPT = (ROOT / "SCRIPT-AND-SCENE-INPUTS-WAVE03.md").read_text()
SOUND = json.loads((ROOT / "inputs/sound-manifest-wave03.json").read_text())


class StoryboardContractTests(unittest.TestCase):
    def test_conditional_board_has_eight_unique_scenes_and_explicit_estimate(self):
        scenes = BOARD["scenes"]
        self.assertEqual(len(scenes), 8)
        self.assertEqual(len({s["id"] for s in scenes}), 8)
        self.assertEqual(BOARD["status"], "conditional-estimated")
        self.assertEqual(BOARD["clock_basis"]["status"], "ESTIMATED_155_WPM")
        self.assertTrue(BOARD["clock_basis"]["measured_clock_required_for_production"])
        self.assertEqual(BOARD["canvas_basis"]["status"], "conditional-source-target")
        self.assertEqual((BOARD["canvas_basis"]["width"], BOARD["canvas_basis"]["height"], BOARD["canvas_basis"]["fps"]), (3840, 2160, 30))
        self.assertEqual(BOARD["canvas_basis"]["review_downscale"], "1920x1080")
        self.assertTrue(BOARD["canvas_basis"]["production_profile_must_be_owner_approved"])

    def test_hook_starts_with_question_and_bespoke_selection_action(self):
        first = BOARD["scenes"][0]
        self.assertTrue(first["script"].startswith("What does 81 per cent actually mean?"))
        self.assertEqual(first["visual_type"], "selection_aperture")
        self.assertIn("question field moves toward the aperture", first["visual_actions"])

    def test_markdown_script_matches_scene_payload_and_cues_fit_estimate(self):
        blocks = re.findall(r"^### Scene \d+ — [^\n]+\n\n(.*?)(?=\n### Scene|\n## Storyboard direction)", SCRIPT, re.S | re.M)
        self.assertEqual(len(blocks), len(BOARD["scenes"]))
        for text, scene in zip(blocks, BOARD["scenes"]):
            self.assertEqual(" ".join(text.split()), " ".join(scene["script"].split()))
            estimated_duration = len(scene["script"].split()) / BOARD["clock_basis"]["words_per_minute"] * 60
            for cue in scene.get("sound_cues", []):
                self.assertLess(cue["offset_s"], estimated_duration)

    def test_irrelevant_2022_financial_paragraph_is_removed(self):
        self.assertNotIn("1,109.7", SCRIPT)
        self.assertNotIn("221.4", SCRIPT)
        self.assertNotIn("not needed to make this film", SCRIPT.casefold())

    def test_each_audio_cue_has_a_visual_cause_and_manifest_asset(self):
        assets = {a["id"]: a for a in SOUND["assets"]}
        for scene in BOARD["scenes"]:
            events = {e["id"]: e for e in scene["motion_events"]}
            for cue in scene.get("sound_cues", []):
                self.assertIn(cue["asset"], assets)
                self.assertTrue(cue["cause"].strip())
                self.assertGreaterEqual(cue["offset_s"], 0)
                self.assertIn(cue["event_id"], events)
                self.assertEqual(cue["pan_object"], events[cue["event_id"]]["label"])
                self.assertGreaterEqual(abs(cue["pan"]), 0.3)

    def test_persistent_objects_are_story_specific_and_never_fade_out(self):
        source = (ROOT / "tools/build-draft.mjs").read_text()
        self.assertIn("motion-object motion-", source)
        self.assertNotIn("tl.to(item,{opacity:0", source)
        self.assertIn("font-size:84px", source)
        self.assertIn(".svg-token{font:700 31px", source)
        self.assertNotIn("max-height:620px", source)
        for scene in BOARD["scenes"]:
            for event in scene["motion_events"]:
                self.assertNotIn("token", event["label"].casefold())
                self.assertGreater(len(event["label"]), 10)
        chronology = next(scene for scene in BOARD["scenes"] if scene["id"] == "scene-07-company-chronology")
        labels = {event["label"] for event in chronology["motion_events"]}
        self.assertIn("2021 · proposed ~$4.2bn equity value", labels)
        self.assertIn("2023 · MindMaze transfer did not proceed", labels)
        self.assertIn("${esc(m.label)}", source)

    def test_source_capture_plan_and_workflow_are_bounded_and_separate(self):
        plan = json.loads(subprocess.run(["python3", str(ROOT / "tools/source_capture.py")], check=True, capture_output=True, text=True).stdout)
        self.assertEqual(plan["status"], "estimated-source-capture-plan")
        self.assertEqual(len(plan["points"]), 8)
        self.assertEqual(len({p["name"] for p in plan["points"]}), 8)
        self.assertEqual([p["scene_id"] for p in plan["points"]], [s["id"] for s in BOARD["scenes"]])
        workflow_path = Path(os.environ.get("F08_SOURCE_CAPTURE_WORKFLOW", ".github/workflows/f08-babylon-wave03-source-capture.yml"))
        workflow = (ROOT / workflow_path).read_text()
        self.assertIn("agmmltd-arch/agmm-render-public", workflow)
        self.assertIn("^[0-9a-f]{40}$", workflow)
        self.assertIn("confirm_source_capture", workflow)
        self.assertIn("verify_source_manifest.py", workflow)
        self.assertIn("F08_SOURCE_CAPTURE_WORKFLOW", workflow)
        self.assertIn('"v22.23.3"', workflow)
        self.assertIn("npm run build:draft", workflow)
        self.assertIn("hyperframes snapshot", workflow)
        self.assertIn("python3 -m unittest tools.test_storyboard_contract tools.test_rebind_clock", workflow)
        self.assertNotIn("unittest discover", workflow)
        self.assertNotIn("approval-lock.json", workflow)
        self.assertNotIn("hyperframes render", workflow)
        self.assertNotIn("voice_path", workflow)

    def test_native_png_validator_matches_hyperframes_zero_padded_names(self):
        plan = source_capture.source_points()
        def run_fixture(*, rename_first=False, omit_last=False, extra=False, bad_dimensions=False):
            temporary = tempfile.TemporaryDirectory()
            self.addCleanup(temporary.cleanup)
            root = Path(temporary.name)
            captures = root / "captures"
            captures.mkdir()
            for index, point in enumerate(plan["points"]):
                if omit_last and index == len(plan["points"]) - 1:
                    continue
                timestamp = f"{point['at_s']:.3f}".rstrip("0").rstrip(".") + "s"
                name = f"frame-{index:02d}-at-{timestamp}.png"
                if rename_first and index == 0:
                    name = f"frame-{index}-at-{timestamp}.png"
                width, height = (3840, 1080) if bad_dimensions and index == 3 else (3840, 2160)
                header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
                (captures / name).write_bytes(header + struct.pack(">II", width, height))
            if extra:
                timestamp = f"{plan['points'][-1]['at_s']:.3f}s"
                header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
                (captures / f"frame-99-at-{timestamp}.png").write_bytes(header + struct.pack(">II", 3840, 2160))
            with patch.object(source_capture, "ROOT", root):
                source_capture.check_pngs(plan)

        run_fixture()
        with self.assertRaisesRegex(SystemExit, "missing frame-00-at-12.372s.png"):
            run_fixture(rename_first=True)
        with self.assertRaisesRegex(SystemExit, "found 9"):
            run_fixture(extra=True)
        with self.assertRaisesRegex(SystemExit, "missing frame-07-at-258.286s.png"):
            run_fixture(omit_last=True)
        with self.assertRaisesRegex(SystemExit, "frame-03-at-111.019s.png: expected 3840x2160, got 3840x1080"):
            run_fixture(bad_dimensions=True)

    def test_sound_density_is_ten_to_twenty_cues_per_estimated_minute(self):
        cue_count = sum(len(s["sound_cues"]) for s in BOARD["scenes"])
        seconds = sum(len(s["script"].split()) for s in BOARD["scenes"]) / BOARD["clock_basis"]["words_per_minute"] * 60
        self.assertGreaterEqual(cue_count / seconds * 60, 10)
        self.assertLessEqual(cue_count / seconds * 60, 20)

    def test_sound_selection_is_cc0_and_no_bed_is_selected(self):
        self.assertIsNone(SOUND["music"])
        self.assertEqual(SOUND["licence_evidence"]["catalog_policy"], "Kenney Interface Sounds; CC0 1.0; attribution not required")
        self.assertFalse(SOUND["licence_evidence"]["bytes_copied_or_opened_on_mac"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
