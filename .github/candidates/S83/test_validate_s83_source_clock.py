import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from typing import Optional
from pathlib import Path

SCRIPT = Path(__file__).with_name("validate_s83_source_clock.py")


def write_manifest(path: Path, audio_path: Path, sha_override: Optional[str] = None) -> None:
    import hashlib
    data = audio_path.read_bytes()
    doc = {"schema": "agmm-s83-protected-inputs-v1", "repository": "agmmltd-arch/agmm-video-render", "release_id": 1, "assets": [{"id": 2, "name": "S83.wav", "size": len(data), "digest": "sha256:" + (sha_override or hashlib.sha256(data).hexdigest())}]}
    path.write_text(json.dumps(doc))


def wav_file(path: Path, seconds: float = 1.0) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\0\0" * int(16000 * seconds))


class SourceClockValidatorTests(unittest.TestCase):
    def test_synthetic_wav_emits_bound_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_file(root / "fixture.wav")
            timings = root / "timings.json"
            timings.write_text(json.dumps({"words": [{"word": "fixture", "start": 0.1, "end": 0.9}]}))
            write_manifest(root / "protected.json", root / "fixture.wav")
            env = dict(os.environ, GITHUB_ACTIONS="true", RUNNER_OS="Linux", RUNNER_ENVIRONMENT="github-hosted")
            result = subprocess.run([sys.executable, str(SCRIPT), "--wav", str(root / "fixture.wav"), "--timings", str(timings), "--protected-inputs", str(root / "protected.json"), "--expected-duration", "1", "--duration-tolerance", "0", "--output", str(root / "receipt.json")], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads((root / "receipt.json").read_text())
            self.assertEqual(receipt["status"], "TECHNICAL_SOURCE_BINDING_PASS_AUDIO_REVIEW_REQUIRED")
            self.assertEqual(receipt["audio"]["duration_seconds"], 1.0)
            self.assertEqual(len(receipt["audio"]["sha256"]), 64)
            self.assertEqual(receipt["audio_review"], "NOT_PERFORMED_BY_VALIDATOR")

    def test_refuses_non_runner_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_file(root / "fixture.wav")
            timings = root / "timings.json"
            timings.write_text(json.dumps({"words": [{"word": "fixture", "start": 0.1, "end": 0.9}]}))
            write_manifest(root / "protected.json", root / "fixture.wav")
            env = dict(os.environ)
            env.pop("GITHUB_ACTIONS", None)
            env.pop("RUNNER_OS", None)
            env.pop("RUNNER_ENVIRONMENT", None)
            result = subprocess.run([sys.executable, str(SCRIPT), "--wav", str(root / "fixture.wav"), "--timings", str(timings), "--protected-inputs", str(root / "protected.json"), "--expected-duration", "1", "--duration-tolerance", "0", "--output", str(root / "receipt.json")], capture_output=True, text=True, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing programme-media validation", result.stderr)

    def test_digest_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_file(root / "fixture.wav")
            timings = root / "timings.json"
            timings.write_text(json.dumps({"words": [{"word": "fixture", "start": 0.1, "end": 0.9}]}))
            write_manifest(root / "protected.json", root / "fixture.wav", "0" * 64)
            env = dict(os.environ, GITHUB_ACTIONS="true", RUNNER_OS="Linux", RUNNER_ENVIRONMENT="github-hosted")
            result = subprocess.run([sys.executable, str(SCRIPT), "--wav", str(root / "fixture.wav"), "--timings", str(timings), "--protected-inputs", str(root / "protected.json"), "--expected-duration", "1", "--duration-tolerance", "0", "--output", str(root / "receipt.json")], capture_output=True, text=True, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SHA256 does not match", result.stderr)

    def test_wrong_synthetic_duration_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_file(root / "fixture.wav", 2)
            timings = root / "timings.json"
            timings.write_text(json.dumps({"words": [{"word": "fixture", "start": 0.1, "end": 0.9}]}))
            write_manifest(root / "protected.json", root / "fixture.wav")
            env = dict(os.environ, GITHUB_ACTIONS="true", RUNNER_OS="Linux", RUNNER_ENVIRONMENT="github-hosted")
            result = subprocess.run([sys.executable, str(SCRIPT), "--wav", str(root / "fixture.wav"), "--timings", str(timings), "--protected-inputs", str(root / "protected.json"), "--expected-duration", "1", "--duration-tolerance", "0", "--output", str(root / "receipt.json")], capture_output=True, text=True, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside expected window", result.stderr)


if __name__ == "__main__":
    unittest.main()
