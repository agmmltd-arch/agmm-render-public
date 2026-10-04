#!/usr/bin/env python3
"""Fetch and attest the already-selected S90 WAV on the hosted Linux runner.

This adapter does not synthesize or select audio. It resolves the exact
immutable GitHub release asset that root uploaded from RESULT.json's selected
WAV path, verifies GitHub's asset digest against the downloaded bytes, checks
the WAV container properties on Ubuntu, and emits the receipt format already
consumed by build_s90_hosted_review_candidate.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import shutil

REPOSITORY = "agmmltd-arch/agmm-render-public"
RELEASE_ID = 402989473
RELEASE_TAG = "S90-selected-voice-hosted-20261004"
ASSET_ID = 609728994
ASSET_NAME = "S90.wav"
ASSET_BYTES = 2_798_068
ASSET_SHA256 = "5f8ce5a135e0b81ba0623d801bb8047cd6a729f8abc1840d4f266ad5bf05cdd1"
SCRIPT_SHA256 = "a8006145cc4610be0abfd70f6e8355e6f6f64780064afe7a7834b49f33360055"
WORDS_SHA256 = "a6d08fbb84c55f406457751213df0094561e55de1e1824faf66cd760845f3925"
RESULT_SHA256 = "48d7e8c16737a97a92367605644873becf945fe0b6968242b58f2d24ca2db4cd"
VOICE_RECEIPT_SHA256 = "c201ecc4a46eddab67f9b9f1c58405e8fc3f2255e0992b1d6faa732f3c13d00b"
MIX_TEMPLATE_SHA256 = "99921ecd40dc797a76ef9786b75ebfedc6ccc48d8400e0136f89dd47ff7c8a3f"
RESULT_WAV_PATH = "/Users/samwall/alfred/builds/video-program-2026-09-23/v2/shorts/voice/S90/S90.wav"
SELECTED_TAKE_DIR = "/Users/samwall/alfred/builds/video-program-2026-09-23/v2/shorts/voice/S90/take-pass1"
EXPECTED_DURATION_S = 58.291
MAX_BYTES = 100_000_000
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class Refusal(RuntimeError):
    pass


def require_hosted_linux() -> None:
    if (platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("S90_HOSTED_REVIEW_BUILD") != "1"):
        raise Refusal("refusing S90 voice download or media inspection outside the explicitly enabled GitHub Actions Linux job")


def validate_native_release(repo: dict, release: dict, asset: dict) -> None:
    """Validate only public, immutable metadata before downloading the WAV."""
    if repo.get("full_name", "").lower() != REPOSITORY or repo.get("visibility") != "public" or repo.get("private") is not False:
        raise Refusal("voice asset repository identity/visibility does not match the pinned public repository")
    if (release.get("id") != RELEASE_ID or release.get("tag_name") != RELEASE_TAG
            or release.get("draft") is not False or release.get("prerelease") is not False):
        raise Refusal("hosted voice release is not the pinned published S90 selection release")
    if (asset.get("id") != ASSET_ID or asset.get("name") != ASSET_NAME
            or asset.get("state") != "uploaded" or asset.get("size") != ASSET_BYTES
            or asset.get("digest") != f"sha256:{ASSET_SHA256}"):
        raise Refusal("GitHub's native S90 voice asset metadata differs from the pinned upload receipt")
    rows = release.get("assets")
    if not isinstance(rows, list):
        raise Refusal("GitHub release metadata has no asset list")
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == ASSET_ID]
    same_name = [row for row in rows if isinstance(row, dict) and row.get("name") == ASSET_NAME]
    essential = ("id", "name", "size", "digest", "state")
    if (len(matches) != 1 or len(same_name) != 1
            or any(matches[0].get(key) != asset.get(key) for key in essential)):
        raise Refusal("release asset list does not uniquely bind the selected S90 WAV to the fetched asset record")


def validate_selection_binding() -> dict:
    """Frozen text-only binding to the already-selected pass1 result."""
    return {
        "result_sha256": RESULT_SHA256,
        "voice_receipt_sha256": VOICE_RECEIPT_SHA256,
        "selected_wav_path": RESULT_WAV_PATH,
        "selected_take_dir": SELECTED_TAKE_DIR,
        "attempt": 1,
        "label": "pass1",
        "selected": True,
        "duration_s": EXPECTED_DURATION_S,
        "words": 163,
        "full_asr_match": True,
        "model": "voxtral-mini-tts-2603",
        "script_sha256": SCRIPT_SHA256,
        "words_sha256": WORDS_SHA256,
    }


def run_json(args: list[str]) -> dict:
    try:
        result = subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True)
        value = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise Refusal("GitHub metadata request failed; no voice receipt was created") from exc
    if not isinstance(value, dict):
        raise Refusal("GitHub metadata response was not a JSON object")
    return value


def sha256_path(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            size += len(block)
            digest.update(block)
    return digest.hexdigest(), size


def inspect_wav(path: Path) -> dict:
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            rate = wav.getframerate()
            width = wav.getsampwidth()
            frames = wav.getnframes()
            comptype = wav.getcomptype()
    except (OSError, EOFError, wave.Error) as exc:
        raise Refusal("hosted selected asset is not a readable PCM WAV") from exc
    duration = frames / rate if rate else 0
    if (comptype != "NONE" or channels not in (1, 2) or width not in (2, 3, 4)
            or not (16_000 <= rate <= 96_000) or frames <= 0
            or abs(duration - EXPECTED_DURATION_S) > 0.05):
        raise Refusal("hosted selected WAV container properties do not match the selected 58.291-second PCM voice bounds")
    return {"container": "WAV/PCM", "channels": channels, "sample_rate_hz": rate,
            "sample_width_bytes": width, "frame_count": frames, "comptype": comptype,
            "duration_s": duration}


def build(args: argparse.Namespace) -> dict:
    require_hosted_linux()
    if not SHA_RE.fullmatch(ASSET_SHA256):
        raise Refusal("pinned selected voice digest is malformed")
    words_source = args.words_source
    mix_template = args.mix_spec_template
    if not words_source.is_file() or hashlib.sha256(words_source.read_bytes()).hexdigest() != WORDS_SHA256:
        raise Refusal("S90 locked word-timing JSON is missing or changed")
    if not mix_template.is_file() or hashlib.sha256(mix_template.read_bytes()).hexdigest() != MIX_TEMPLATE_SHA256:
        raise Refusal("S90 hosted mix-spec template is missing or changed")
    selection_binding = validate_selection_binding()

    repo = run_json([f"repos/{REPOSITORY}"])
    release = run_json([f"repos/{REPOSITORY}/releases/{RELEASE_ID}"])
    asset = run_json([f"repos/{REPOSITORY}/releases/assets/{ASSET_ID}"])
    validate_native_release(repo, release, asset)

    if args.output.exists():
        raise Refusal(f"refusing to overwrite existing hosted voice output: {args.output}")
    args.output.mkdir(parents=True)
    try:
        (args.output / "voice").mkdir()
        (args.output / "mix").mkdir()
        with tempfile.TemporaryDirectory(prefix="s90-selected-voice-") as temp:
            download_dir = Path(temp)
            try:
                subprocess.run(["gh", "release", "download", RELEASE_TAG, "--repo", REPOSITORY,
                                "--pattern", ASSET_NAME, "--dir", str(download_dir)],
                               check=True, capture_output=True, text=True)
            except (OSError, subprocess.CalledProcessError) as exc:
                raise Refusal("exact S90 release asset download failed on hosted Linux") from exc
            downloaded = download_dir / ASSET_NAME
            if not downloaded.is_file() or downloaded.is_symlink():
                raise Refusal("release download did not produce exactly the expected regular WAV asset")
            actual_sha, actual_bytes = sha256_path(downloaded)
            if actual_sha != ASSET_SHA256 or actual_bytes != ASSET_BYTES:
                raise Refusal("hosted WAV bytes do not match GitHub's pinned immutable asset digest and size")
            wav_properties = inspect_wav(downloaded)
            staged_voice = args.output / "voice" / ASSET_NAME
            # A same-runner hardlink avoids a second media copy while preserving
            # the single downloaded byte object used by the mixer/build step.
            try:
                os.link(downloaded, staged_voice)
            except OSError:
                shutil.copyfile(downloaded, staged_voice)
            if sha256_path(staged_voice) != (actual_sha, actual_bytes):
                raise Refusal("staged hosted voice changed after native asset verification")
            receipt = {
                "kind": "s90_selected_voice_asset_receipt",
                "selection_status": "SELECTED",
                "selection_source": selection_binding,
                "asset": {"repository": REPOSITORY, "release_id": RELEASE_ID,
                          "release_tag": RELEASE_TAG, "asset_id": ASSET_ID,
                          "name": ASSET_NAME, "sha256": actual_sha, "size": actual_bytes,
                          "native_digest": asset["digest"]},
                "sha256": actual_sha,
                "bytes": actual_bytes,
                "duration_s": EXPECTED_DURATION_S,
                "wav_properties": wav_properties,
                "script_sha256": SCRIPT_SHA256,
                "words_sha256": WORDS_SHA256,
                "verification": {"host": "GitHub Actions Linux", "asset_digest_verified": True,
                                  "downloaded_bytes_verified": True,
                                  "sampled_or_listened": False,
                                  "creative_or_av_approval": False},
            }
            receipt_path_out = args.output / "selected-voice-receipt.json"
            receipt_path_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            shutil.copyfile(words_source, args.output / "mix" / "S90.words.json")
            mix_spec = json.loads(mix_template.read_text(encoding="utf-8"))
            if not isinstance(mix_spec, dict) or mix_spec.get("id") != "S90":
                raise Refusal("hosted S90 mix-spec template has the wrong identity")
            if len((mix_spec.get("sfx") or {}).get("cues", [])) != 19:
                raise Refusal("hosted S90 mix-spec template no longer contains the reviewed 19 cue IDs")
            if mix_spec.get("voice", {}).get("src") != "../voice/S90.wav":
                raise Refusal("hosted S90 mix-spec template does not use the stable sibling voice path")
            binding = mix_spec.get("candidate_binding")
            if (not isinstance(binding, dict) or binding.get("voice_asset_sha256") != actual_sha
                    or binding.get("voice_asset_release_id") != RELEASE_ID
                    or binding.get("voice_asset_id") != ASSET_ID
                    or binding.get("voice_asset_bytes") != actual_bytes):
                raise Refusal("hosted mix-spec template does not bind the exact uploaded voice asset")
            shutil.copyfile(mix_template, args.output / "mix" / "mix_spec.json")
    except Exception:
        shutil.rmtree(args.output, ignore_errors=True)
        raise
    return {"voice": str(args.output / "voice" / ASSET_NAME), "voice_receipt": str(args.output / "selected-voice-receipt.json"),
            "mix_spec": str(args.output / "mix" / "mix_spec.json"),
            "words": str(args.output / "mix" / "S90.words.json"),
            "expected_voice_sha256": ASSET_SHA256, "voice_bytes": ASSET_BYTES,
            "selection_status": "SELECTED", "audio_visual_review": "NOT_PERFORMED"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words-source", type=Path, required=True)
    parser.add_argument("--mix-spec-template", type=Path, default=Path(__file__).with_name("S90-mix_spec.hosted-candidate.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args), indent=2, sort_keys=True))
    except Refusal as exc:
        print(f"S90 selected voice adapter refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
