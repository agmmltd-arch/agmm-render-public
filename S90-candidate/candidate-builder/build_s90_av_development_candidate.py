#!/usr/bin/env python3
"""Stage an S90 full-AV review candidate on the explicitly hosted Ubuntu runner.

This isolated runner reuses the S90 source packager, v2/sound/v2/mix2.py, and
the existing short-package archive/parts validators to stage a review candidate.
It requires an external exact-hash admission for a development render. The
output remains explicitly unapproved, with listening, licensing and final AV
review open. Programme media is opened only on the explicitly enabled Ubuntu
GitHub Actions runner, after all text/admission checks pass.

The copied source packager adds only exact 30 fps grid validation and a clearly
proposed final-CTA hold. No canonical spec, card, release, or approval state is
written by this proposal.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

SHORT_ID = "S90"
WORDS_SHA256 = "a6d08fbb84c55f406457751213df0094561e55de1e1824faf66cd760845f3925"
SCRIPT_SHA256 = "a8006145cc4610be0abfd70f6e8355e6f6f64780064afe7a7834b49f33360055"
FRAME_RATE = 30
SOURCE_BUILDER_SHA256 = "cdf61d29429e1709f0005c00ee62b358bc695ee49e8a73b858ecc4df47ee30d4"
MIXER_FILE_SHA256 = {
    "mix2.py": "20607f3a9975a99883c5c87ee8b6ba6d0146fc7be24a0c1ffcacef1d63e4dbd4",
    "audio_core.py": "dec742a1db2732e112e3734e245357b0ef6d73415cd458030645fa6e5154f2fa",
    "audio_rules.json": "9aa2a571a34aa8f50b28d995227b581d788fd36d5d6b7c4db3e10866e7bbbb68",
    "voice_chain.py": "64d1ada82e18536228dd111979a5e80e886985513f1d56a8f8fbc66f1753dcb9",
}
MAX_VOICE_BYTES = 100_000_000
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class BuildRefusal(RuntimeError):
    pass


def require_hosted_linux() -> None:
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("S90_HOSTED_AV_CANDIDATE") != "1":
        raise BuildRefusal("refusing S90 media staging/mixing outside the explicitly enabled GitHub Actions Linux AV-development job")


def read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildRefusal(f"{label} is missing or unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise BuildRefusal(f"{label} must be a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_wav_properties(path: Path) -> dict:
    """Read the hosted input's WAV header/frame count; never infer them from metadata."""
    try:
        with wave.open(str(path), "rb") as wav:
            props = {
                "container": "WAV/PCM",
                "channels": wav.getnchannels(),
                "sample_rate_hz": wav.getframerate(),
                "sample_width_bytes": wav.getsampwidth(),
                "frame_count": wav.getnframes(),
                "comptype": wav.getcomptype(),
            }
    except (OSError, EOFError, wave.Error) as exc:
        raise BuildRefusal("hosted selected voice is not a readable PCM WAV") from exc
    rate = props["sample_rate_hz"]
    duration = props["frame_count"] / rate if rate else 0.0
    props["duration_s"] = duration
    if (props["comptype"] != "NONE" or props["channels"] not in (1, 2)
            or props["sample_width_bytes"] not in (2, 3, 4)
            or not (16_000 <= rate <= 96_000) or props["frame_count"] <= 0):
        raise BuildRefusal("hosted selected voice WAV properties are outside the supported PCM bounds")
    return props


def import_dispatcher(path: Path):
    spec = importlib.util.spec_from_file_location("s90_fullav_dispatch_contract", path)
    if spec is None or spec.loader is None:
        raise BuildRefusal(f"cannot load existing short-package contract: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_development_admission(*, candidate: Path, spec_candidate_path: Path,
                                   storyboard_candidate_path: Path, admission_path: Path,
                                   mix_spec_path: Path) -> tuple[dict, dict, str, str, float, int, bool]:
    """Require an external, exact-hash admission for a development render only."""
    for path, label in ((spec_candidate_path, "S90 spec candidate"),
                        (storyboard_candidate_path, "S90 storyboard candidate"),
                        (admission_path, "independent development admission"),
                        (mix_spec_path, "S90 mix candidate")):
        if not path.is_file():
            raise BuildRefusal(f"{label} is absent: {path}")
    scene_path = candidate / "scenes.js"
    delta_path = candidate / "spec-delta.json"
    if not scene_path.is_file() or not delta_path.is_file():
        raise BuildRefusal("exact S90 scene and spec-delta candidate files are required")
    spec_data = read_json(spec_candidate_path, "S90 spec candidate")
    storyboard = read_json(storyboard_candidate_path, "S90 storyboard candidate")
    admission = read_json(admission_path, "independent development admission")
    mix_spec = read_json(mix_spec_path, "S90 mix candidate")
    if spec_data.get("id") != SHORT_ID or spec_data.get("candidate_status") != "UNAPPROVED_SOURCE_CANDIDATE":
        raise BuildRefusal("S90 spec must remain an unapproved source candidate")
    if storyboard.get("story_id") != SHORT_ID or storyboard.get("approval_state") != "NOT_APPROVED":
        raise BuildRefusal("S90 storyboard must remain explicitly unapproved")
    if spec_data.get("script", {}).get("sha256") != SCRIPT_SHA256:
        raise BuildRefusal("S90 spec candidate is not bound to the locked script")
    words_path = candidate / "S90.words.json"
    if not words_path.is_file() or sha256_file(words_path) != WORDS_SHA256:
        raise BuildRefusal("S90 candidate words file does not match the locked word timing")
    scene_sha = sha256_file(scene_path)
    delta_sha = sha256_file(delta_path)
    spec_sha = sha256_file(spec_candidate_path)
    storyboard_sha = sha256_file(storyboard_candidate_path)
    mix_sha = sha256_file(mix_spec_path)
    runtime_proof_sha = sha256_file(candidate / "preview-inputs/ROOT-RUNTIME-PARENT-PROOF.json")
    source_manifest_sha = sha256_file(candidate / "preview-inputs/ROOT-SUCCESS-manifest.json")
    source_review_sha = sha256_file(candidate / "preview-inputs/ROOT-SOURCE-ASSET-REVIEW.json")
    identity_path = candidate / "HOSTED-VOICE-ASSET-IDENTITY.json"
    identity_sha = sha256_file(identity_path)
    binding = mix_spec.get("candidate_binding")
    if not isinstance(binding, dict):
        raise BuildRefusal("mix candidate has no candidate_binding")
    exact = {
        "scene_sha256": scene_sha, "spec_delta_sha256": delta_sha,
        "spec_candidate_sha256": spec_sha, "storyboard_candidate_sha256": storyboard_sha,
        "mix_spec_candidate_sha256": mix_sha, "voice_identity_sha256": identity_sha,
        "locked_words_sha256": WORDS_SHA256, "locked_script_sha256": SCRIPT_SHA256,
        "runtime_parent_proof_sha256": runtime_proof_sha,
        "source_manifest_sha256": source_manifest_sha, "source_review_sha256": source_review_sha,
    }
    for key in ("scene_sha256", "spec_delta_sha256", "spec_candidate_sha256", "storyboard_candidate_sha256"):
        if binding.get(key) != exact[key]:
            raise BuildRefusal(f"mix candidate binding mismatch: {key}")
    if binding.get("voice_words_sha256") != WORDS_SHA256 or binding.get("voice_asset_sha256") != "5f8ce5a135e0b81ba0623d801bb8047cd6a729f8abc1840d4f266ad5bf05cdd1":
        raise BuildRefusal("mix candidate binding does not match the exact locked words and uploaded voice")
    if binding.get("voice_asset_release_id") != 402989473 or binding.get("voice_asset_id") != 609728994:
        raise BuildRefusal("mix candidate voice asset IDs differ from the immutable selected release asset")
    if (storyboard.get("scene_source", {}).get("source_scene_sha256") != scene_sha
            or spec_data.get("source_scene_sha256") != scene_sha):
        raise BuildRefusal("draft storyboard/spec do not bind the exact candidate scene")
    if admission.get("kind") != "s90_development_render_admission_v1" or admission.get("decision") != "ADMITTED_FOR_DEVELOPMENT_RENDER":
        raise BuildRefusal("a genuine external ADMITTED_FOR_DEVELOPMENT_RENDER receipt is required")
    reviewer = admission.get("reviewer")
    if (not isinstance(reviewer, dict) or not isinstance(reviewer.get("identity"), str)
            or not reviewer["identity"].strip() or reviewer.get("role") != "independent"):
        raise BuildRefusal("development admission must identify an independent reviewer")
    mix_approval = mix_spec.get("approval")
    if (not isinstance(mix_approval, dict) or mix_approval.get("render_authorized") is not False
            or mix_approval.get("release_authorized") is not False):
        raise BuildRefusal("mix candidate must retain its explicit no-render/no-release state")
    if admission.get("candidate_hashes") != exact:
        raise BuildRefusal("development admission does not bind every exact S90 candidate input hash")
    timing = admission.get("timing")
    candidate_timing = storyboard.get("timing_candidate")
    if not isinstance(timing, dict) or not isinstance(candidate_timing, dict):
        raise BuildRefusal("development admission and storyboard must both bind the candidate timing")
    duration = timing.get("duration_s")
    frames = timing.get("frame_count")
    if (duration != 58.3 or frames != 1749 or timing.get("frame_rate") != FRAME_RATE
            or candidate_timing.get("duration_s") != duration or candidate_timing.get("frame_count") != frames):
        raise BuildRefusal("development admission must bind the exact candidate 58.3s/1749-frame grid")
    delta = read_json(delta_path, "S90 candidate spec delta")
    beats = delta.get("beats")
    if not isinstance(beats, list) or len(beats) != 16:
        raise BuildRefusal("S90 candidate must retain all 16 story beats")
    try:
        final_end = float(beats[-1].get("to", -1))
    except (TypeError, ValueError):
        raise BuildRefusal("candidate final beat end is invalid") from None
    hold = timing.get("final_cta_hold")
    needs_hold = duration > final_end + 1e-7
    if needs_hold:
        if (not isinstance(hold, dict) or hold.get("status") != "PROPOSED_FOR_DEVELOPMENT_ONLY"
                or hold.get("from_s") != final_end or hold.get("to_s") != duration):
            raise BuildRefusal("the 58.3s development grid must bind the exact non-approved CTA hold")
    elif hold is not None:
        raise BuildRefusal("candidate CTA hold is inconsistent with the 30 fps grid")
    if abs(float(mix_spec.get("duration_s", -1)) - duration) > 1e-9:
        raise BuildRefusal("mix candidate duration differs from the admitted development grid")
    if len((mix_spec.get("sfx") or {}).get("cues", [])) != 19:
        raise BuildRefusal("mix candidate must retain its exact 19 SFX cue design")
    return spec_data, admission, spec_sha, scene_sha, duration, frames, needs_hold

def validate_voice_and_mix(*, voice: Path, voice_receipt_path: Path, expected_voice_sha256: str,
                           mix_spec_path: Path, render_duration_s: float) -> tuple[dict, dict]:
    """Validate text bindings before any voice bytes are opened."""
    if not isinstance(expected_voice_sha256, str) or not SHA_RE.fullmatch(expected_voice_sha256):
        raise BuildRefusal("--expected-voice-sha256 is required and must be 64 lowercase hex characters")
    if not voice_receipt_path.is_file():
        raise BuildRefusal(f"hosted selected-voice receipt is missing: {voice_receipt_path}")
    if not mix_spec_path.is_file():
        raise BuildRefusal(f"S90 mix candidate is missing: {mix_spec_path}")
    if not voice.is_file():
        raise BuildRefusal(f"hosted selected voice WAV is missing: {voice}")

    receipt = read_json(voice_receipt_path, "hosted selected-voice receipt")
    mix_spec = read_json(mix_spec_path, "S90 mix_spec.json")
    if receipt.get("kind") != "s90_selected_voice_asset_receipt" or receipt.get("selection_status") != "SELECTED":
        raise BuildRefusal("voice receipt does not identify an already selected S90 voice asset")
    asset = receipt.get("asset")
    if not isinstance(asset, dict) or not isinstance(asset.get("release_id"), int) or isinstance(asset.get("release_id"), bool) or asset["release_id"] <= 0 or not isinstance(asset.get("asset_id"), int) or isinstance(asset.get("asset_id"), bool) or asset["asset_id"] <= 0:
        raise BuildRefusal("voice receipt is not bound to an immutable hosted release asset ID")
    if not isinstance(asset.get("repository"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", asset["repository"]) or not isinstance(asset.get("name"), str) or not asset["name"].lower().endswith(".wav"):
        raise BuildRefusal("voice receipt must name the hosted repository and exact WAV release asset")
    if receipt.get("sha256") != expected_voice_sha256 or asset.get("sha256") != expected_voice_sha256:
        raise BuildRefusal("external expected voice SHA-256 does not match the selected hosted asset receipt")
    voice_bytes = receipt.get("bytes")
    if isinstance(voice_bytes, bool) or not isinstance(voice_bytes, int) or not (1 <= voice_bytes <= MAX_VOICE_BYTES) or asset.get("size") != voice_bytes:
        raise BuildRefusal("voice receipt byte count is missing, inconsistent, or outside the 100 MB bound")
    if receipt.get("script_sha256") != SCRIPT_SHA256 or receipt.get("words_sha256") != WORDS_SHA256:
        raise BuildRefusal("selected voice receipt is not bound to the locked S90 script and word timings")
    duration = receipt.get("duration_s")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(float(duration)) or duration <= 0:
        raise BuildRefusal("selected voice receipt lacks a positive duration")
    minimum_voice_frames = math.ceil(float(duration) * FRAME_RATE - 1e-9)
    if minimum_voice_frames > round(render_duration_s * FRAME_RATE):
        raise BuildRefusal("selected voice exceeds the admitted development frame grid; voice cannot be trimmed")
    claimed_wav = receipt.get("wav_properties")
    if (not isinstance(claimed_wav, dict) or claimed_wav.get("container") != "WAV/PCM"
            or claimed_wav.get("channels") not in (1, 2)
            or claimed_wav.get("sample_rate_hz") not in range(16_000, 96_001)
            or claimed_wav.get("sample_width_bytes") not in (2, 3, 4)
            or isinstance(claimed_wav.get("frame_count"), bool)
            or not isinstance(claimed_wav.get("frame_count"), int)
            or claimed_wav.get("frame_count", 0) <= 0):
        raise BuildRefusal("hosted voice receipt lacks bounded WAV container properties")
    claimed_duration = claimed_wav.get("duration_s")
    if (isinstance(claimed_duration, bool) or not isinstance(claimed_duration, (int, float))
            or not math.isfinite(float(claimed_duration))
            or abs(float(claimed_duration) - float(duration)) > 0.05):
        raise BuildRefusal("hosted WAV properties do not agree with the selected voice duration receipt")

    if mix_spec.get("id") != SHORT_ID or isinstance(mix_spec.get("duration_s"), bool) or not isinstance(mix_spec.get("duration_s"), (int, float)) or abs(float(mix_spec["duration_s"]) - render_duration_s) > 1e-9:
        raise BuildRefusal("mix_spec id/duration must match S90 and the exact development render frame grid")
    voice_cfg = mix_spec.get("voice")
    if not isinstance(voice_cfg, dict) or not isinstance(voice_cfg.get("src"), str):
        raise BuildRefusal("mix_spec.voice.src is required")
    voice_src = Path(voice_cfg["src"])
    if not voice_src.is_absolute():
        voice_src = (mix_spec_path.parent / voice_src).resolve()
    if voice_src.resolve() != voice.resolve():
        raise BuildRefusal("mix_spec.voice.src must point to the exact externally pinned hosted voice input")
    words_ref = mix_spec.get("words")
    if not isinstance(words_ref, str):
        raise BuildRefusal("mix_spec.words must point to the locked S90 word-timing JSON")
    words_path = Path(words_ref)
    if not words_path.is_absolute():
        words_path = (mix_spec_path.parent / words_path).resolve()
    if not words_path.is_file() or sha256_file(words_path) != WORDS_SHA256:
        raise BuildRefusal("mix_spec.words does not resolve to the exact locked S90 word-timing file")
    if not isinstance(mix_spec.get("master"), dict):
        raise BuildRefusal("mix_spec.master is required by the existing mix2 contract")
    binding = mix_spec.get("candidate_binding")
    if not isinstance(binding, dict) or binding.get("voice_asset_sha256") != expected_voice_sha256:
        raise BuildRefusal("hosted mix spec is not bound to the selected immutable voice asset digest")
    if binding.get("voice_asset_id") != asset["asset_id"] or binding.get("voice_asset_release_id") != asset["release_id"]:
        raise BuildRefusal("hosted mix spec asset IDs do not match the selected voice receipt")
    return receipt, mix_spec


def validate_mix_tools(mixer_dir: Path) -> tuple[Path, Path]:
    mix2 = mixer_dir / "mix2.py"
    required = (mix2, mixer_dir / "audio_core.py", mixer_dir / "audio_rules.json",
                mixer_dir / "voice_chain.py", mixer_dir.parent / "library.json")
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise BuildRefusal("hosted v2 mixer bundle is incomplete: " + ", ".join(missing))
    changed = [name for name, expected in MIXER_FILE_SHA256.items()
               if sha256_file(mixer_dir / name) != expected]
    if changed:
        raise BuildRefusal("hosted v2 mixer code differs from the reviewed exact source pins: " + ", ".join(changed))
    if sha256_file(mixer_dir.parent / "library.json") != "2744f53024d42208538675f8d27e24e3f06c4135b81e892af29e2f0538c56215":
        raise BuildRefusal("hosted v2 mixer library text differs from the reviewed S90 sound-library pin")
    return mix2, mixer_dir


def validate_mix_asset_paths(mix_spec: dict, mix_spec_path: Path, mixer_dir: Path) -> list[Path]:
    """Require every declared sound input to exist in the hosted staged inputs."""
    def resolve(value: object, label: str) -> Path:
        if not isinstance(value, str) or not value:
            raise BuildRefusal(f"{label} path is missing from the S90 mix candidate")
        path = Path(value)
        return path.resolve() if path.is_absolute() else (mix_spec_path.parent / path).resolve()

    inputs: list[Path] = []
    music = mix_spec.get("music") or {}
    if isinstance(music, dict):
        if music.get("src"):
            inputs.append(resolve(music["src"], "music"))
        for index, row in enumerate(music.get("segments") or []):
            if not isinstance(row, dict):
                raise BuildRefusal(f"mix_spec.music.segments[{index}] is not an object")
            inputs.append(resolve(row.get("src"), f"music segment {index}"))
    else:
        raise BuildRefusal("mix_spec.music must be an object when present")

    ambience = mix_spec.get("ambience") or {}
    if isinstance(ambience, dict):
        for index, row in enumerate(ambience.get("regions") or []):
            if not isinstance(row, dict):
                raise BuildRefusal(f"mix_spec.ambience.regions[{index}] is not an object")
            inputs.append(resolve(row.get("src"), f"ambience region {index}"))
    else:
        raise BuildRefusal("mix_spec.ambience must be an object when present")

    sfx = mix_spec.get("sfx") or {}
    if not isinstance(sfx, dict):
        raise BuildRefusal("mix_spec.sfx must be an object when present")
    library_path = resolve(sfx.get("library"), "SFX library")
    expected_library = (mixer_dir.parent / "library.json").resolve()
    if library_path != expected_library:
        raise BuildRefusal("mix_spec.sfx.library must use the supplied hosted v2 mixer library")
    library_sha = (mix_spec.get("candidate_binding") or {}).get("sound_library_sha256_text_only")
    if library_sha is not None and (not isinstance(library_sha, str) or sha256_file(library_path) != library_sha):
        raise BuildRefusal("hosted mixer library text differs from the S90 candidate binding")
    library = read_json(library_path, "hosted mixer library")
    items = library.get("items")
    if not isinstance(items, list):
        raise BuildRefusal("hosted mixer library has no items list")
    by_id = {item.get("id"): item for item in items if isinstance(item, dict)}
    cues = list(sfx.get("cues") or [])
    if sfx.get("cues_file"):
        cues_path = resolve(sfx["cues_file"], "SFX cues file")
        cues_doc = read_json(cues_path, "mix_spec SFX cues file")
        if not isinstance(cues_doc.get("cues"), list):
            raise BuildRefusal("mix_spec SFX cues file has no cues list")
        cues.extend(cues_doc["cues"])
        inputs.append(cues_path)
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict) or cue.get("sfx_id") not in by_id:
            raise BuildRefusal(f"mix_spec SFX cue {index} refers to an unknown library id")
        entry = by_id[cue["sfx_id"]]
        sound_path = Path(entry.get("path", ""))
        if not sound_path.is_absolute():
            sound_path = library_path.parent / sound_path
        inputs.append(sound_path.resolve())

    unique = sorted(set(inputs))
    missing = [str(path) for path in unique if not path.is_file()]
    if missing:
        raise BuildRefusal("approved mix references sound files absent from the hosted asset bundle: " + ", ".join(missing[:8]))
    return unique


def normalize_parts(parts: dict, source_sha256: str, source_bytes: int, dispatcher,
                    render_duration_s: float, render_frames: int) -> dict:
    """Use the renderer's actual validator, changing only its required S90 output ID."""
    if parts.get("sha256") != source_sha256 or parts.get("bytes") != source_bytes:
        raise BuildRefusal("silent packager parts.json is not bound to the exact source archive")
    rows = parts.get("parts")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise BuildRefusal("S90 source package must contain exactly one package part")
    row = dict(rows[0])
    try:
        part_duration = float(row.get("dur", -1))
        part_offset = float(row.get("off", -1))
    except (TypeError, ValueError):
        raise BuildRefusal("silent packager part duration/offset is invalid") from None
    if row.get("look") != "s90-preview-a" or row.get("file") != "index.html" or part_offset != 0 or not math.isfinite(part_duration) or abs(part_duration - render_duration_s) > 1e-6 or parts.get("frames") != render_frames:
        raise BuildRefusal("source packager part duration/frame grid does not match the independently admitted S90 development timing")
    # The existing helper emits lowercase s90-preview-a as the output ID. The
    # dispatcher requires S90-...; retain the look/path and normalize only out.
    row["out"] = "S90-main"
    clean = dict(parts)
    clean["parts"] = [row]
    try:
        dispatcher._normalise_parts(SHORT_ID, clean, source_sha256, source_bytes)
    except dispatcher.DispatchError as exc:
        raise BuildRefusal(f"normalized S90 package fails the real renderer contract: {exc}") from exc
    return clean


def build(args: argparse.Namespace) -> dict:
    require_hosted_linux()
    # Validate all candidate text bindings/admission before hashing selected voice bytes.
    spec_data, admission, spec_sha, scene_sha, render_duration_s, render_frames, hold_final_cta = validate_development_admission(
        candidate=args.candidate, spec_candidate_path=args.spec_candidate,
        storyboard_candidate_path=args.storyboard_candidate, admission_path=args.development_admission,
        mix_spec_path=args.mix_spec)
    voice_receipt, mix_spec = validate_voice_and_mix(
        voice=args.voice, voice_receipt_path=args.voice_receipt,
        expected_voice_sha256=args.expected_voice_sha256, mix_spec_path=args.mix_spec,
        render_duration_s=render_duration_s)
    mix2, _ = validate_mix_tools(args.mixer_dir)
    validate_mix_asset_paths(mix_spec, args.mix_spec, args.mixer_dir)
    if args.output.exists():
        raise BuildRefusal(f"refusing to overwrite existing output: {args.output}")
    expected_source_builder = (Path(__file__).parent / "s90_grid_packager_development.py").resolve()
    if args.source_builder.resolve() != expected_source_builder or not args.source_builder.is_file():
        raise BuildRefusal(f"source builder must be the isolated pinned duration-aware proposal copy: {expected_source_builder}")
    if sha256_file(args.source_builder) != SOURCE_BUILDER_SHA256:
        raise BuildRefusal("isolated duration-aware source-packager SHA-256 differs from this reviewed proposal")

    actual_voice_bytes = args.voice.stat().st_size
    if actual_voice_bytes != voice_receipt["bytes"] or sha256_file(args.voice) != args.expected_voice_sha256:
        raise BuildRefusal("hosted voice bytes do not match the external SHA/size receipt")
    actual_wav = inspect_wav_properties(args.voice)
    claimed_wav = voice_receipt["wav_properties"]
    if any(actual_wav.get(key) != claimed_wav.get(key) for key in
           ("container", "channels", "sample_rate_hz", "sample_width_bytes", "frame_count", "comptype")):
        raise BuildRefusal("hosted WAV properties differ from the independently generated asset receipt")
    if abs(actual_wav["duration_s"] - float(claimed_wav["duration_s"])) > 1e-9:
        raise BuildRefusal("hosted WAV duration differs from the independently generated asset receipt")
    if actual_wav["duration_s"] > render_duration_s + 1e-9:
        raise BuildRefusal("hosted selected voice exceeds development render duration; voice cannot be trimmed")

    dispatcher = import_dispatcher(args.dispatcher)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix=".s90-review-build-", dir=args.output.parent))
    try:
        staged = temp_root / "silent-stage"
        stage_cmd = [sys.executable, str(args.source_builder), "stage",
                     "--parent-release-metadata", str(args.parent_release_metadata),
                     "--parent-archive", str(args.parent_archive),
                     "--candidate", str(args.candidate), "--output", str(staged),
                     "--duration-s", str(render_duration_s)]
        if hold_final_cta:
            hold = admission["timing"]["final_cta_hold"]
            stage_cmd.extend(["--development-final-cta-hold", "--final-cta-hold-from-s", str(hold["from_s"]),
                              "--final-cta-hold-to-s", str(hold["to_s"])])
        hosted_env = os.environ.copy()
        hosted_env["S90_HOSTED_PREVIEW"] = "1"
        stage_result = subprocess.run(stage_cmd, text=True, capture_output=True, env=hosted_env)
        if stage_result.returncode:
            detail = (stage_result.stderr or stage_result.stdout)[-1200:]
            raise BuildRefusal(f"existing S90 source packager failed: {detail}")

        source = staged / "source.tar.gz"
        source_bytes = source.stat().st_size
        source_sha = sha256_file(source)
        raw_parts = read_json(staged / "parts.json", "silent packager parts.json")
        parts = normalize_parts(raw_parts, source_sha, source_bytes, dispatcher,
                                render_duration_s, render_frames)

        mix_out = temp_root / "mix2-output"
        mix_cmd = [sys.executable, str(mix2), "render", str(args.mix_spec), "--out", str(mix_out)]
        mix_result = subprocess.run(mix_cmd, text=True, capture_output=True)
        if mix_result.returncode:
            detail = (mix_result.stderr or mix_result.stdout)[-1200:]
            raise BuildRefusal(f"existing v2 mix2 renderer failed: {detail}")
        manifest_path = mix_out / "mix_manifest.json"
        manifest = read_json(manifest_path, "mix2 mix_manifest.json")
        master = mix_out / "master.wav"
        expected_master_sha = (manifest.get("master") or {}).get("sha256")
        actual_master_sha = sha256_file(master) if master.is_file() else None
        if not isinstance(expected_master_sha, str) or actual_master_sha != expected_master_sha:
            raise BuildRefusal("mix2 master.wav is missing or differs from its native manifest digest")
        input_voice_sha = (((manifest.get("inputs") or {}).get("voice") or {}).get("sha256"))
        if input_voice_sha != args.expected_voice_sha256:
            raise BuildRefusal("mix2 did not consume the externally selected voice bytes")
        manifest_duration = manifest.get("duration_s")
        if isinstance(manifest_duration, bool) or not isinstance(manifest_duration, (int, float)) or not math.isfinite(float(manifest_duration)) or abs(float(manifest_duration) - render_duration_s) > 1e-6:
            raise BuildRefusal("mix2 output duration does not match the development render frame grid")

        final = temp_root / "package"
        (final / "build").mkdir(parents=True)
        (final / "audio").mkdir()
        shutil.copyfile(source, final / "build/source.tar.gz")
        parts_bytes = (json.dumps(parts, sort_keys=True, indent=2) + "\n").encode()
        (final / "build/parts.json").write_bytes(parts_bytes)
        shutil.copyfile(master, final / "audio/mix.wav")
        shutil.copyfile(manifest_path, final / "audio/mix_manifest.json")
        (final / "audio/selected-voice-receipt.json").write_text(
            json.dumps(voice_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        package_sha = sha256_file(final / "build/source.tar.gz")
        (final / "BUILD.json").write_text(json.dumps({
            "id": SHORT_ID,
            "package_sha256": package_sha,
            "parts": parts["parts"],
            "development_admission": {
                         "decision": admission["decision"],
                         "receipt_sha256": sha256_file(args.development_admission),
                         "candidate_hashes": admission["candidate_hashes"],
                         "duration_s": render_duration_s, "frame_rate": FRAME_RATE,
                         "frame_count": render_frames,
                         "final_cta_hold": admission["timing"].get("final_cta_hold"),
                         "final_av_review": "OPEN", "audio_listening": "OPEN",
                         "licensing_review": "OPEN", "release_approval": "OPEN"},
            "voice": {"sha256": args.expected_voice_sha256,
                      "receipt_sha256": sha256_file(args.voice_receipt),
                      "asset_id": voice_receipt["asset"]["asset_id"]},
            "mix": {"sha256": sha256_file(final / "audio/mix.wav"),
                    "mix_spec_sha256": sha256_file(args.mix_spec),
                    "manifest_sha256": sha256_file(final / "audio/mix_manifest.json")},
            "status": "HOSTED_FULL_AV_DEVELOPMENT_CANDIDATE_NOT_APPROVED",
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        # Exercise the same archive and part validators used by the dispatcher.
        try:
            parsed, frames = dispatcher._normalise_parts(SHORT_ID, parts, package_sha,
                                                           (final / "build/source.tar.gz").stat().st_size)
            dispatcher._validate_archive(final / "build/source.tar.gz", parsed)
        except dispatcher.DispatchError as exc:
            raise BuildRefusal(f"finished S90 candidate fails the existing dispatcher package checks: {exc}") from exc
        os.replace(final, args.output)
        return {"status": "HOSTED_AV_DEVELOPMENT_CANDIDATE_STAGED", "output": str(args.output),
                "package_sha256": package_sha, "parts": len(parts["parts"]),
            "frames": frames, "render_duration_s": render_duration_s,
            "voice_sha256": args.expected_voice_sha256,
                "mix_sha256": sha256_file(args.output / "audio/mix.wav"),
                "development_admission": admission["decision"], "editorial_status": "NOT_REVIEWED",
                "audio_visual_status": "NOT_REVIEWED", "release_status": "NOT_REQUESTED"}
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _path_arg(parser: argparse.ArgumentParser, name: str, help_text: str) -> None:
    parser.add_argument(name, type=Path, required=True, help=help_text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name, help_text in (
        ("--spec-candidate", "unapproved S90 spec candidate JSON"),
        ("--storyboard-candidate", "unapproved S90 storyboard candidate JSON"),
        ("--development-admission", "external exact-hash ADMITTED_FOR_DEVELOPMENT_RENDER receipt"),
        ("--candidate", "checked-out S90 source candidate directory"),
        ("--voice", "immutable hosted selected-voice WAV"),
        ("--voice-receipt", "hosted voice selection/asset receipt JSON with release/asset IDs and exact SHA/size"),
        ("--mix-spec", "exact 19-cue S90 mix candidate specification"),
        ("--mixer-dir", "hosted sound/v2 directory with mix2.py/audio_core.py/audio_rules.json/voice_chain.py and sibling library.json"),
        ("--source-builder", "isolated duration-aware copy of the pinned S90 source packager"),
        ("--parent-release-metadata", "verified source runtime parent release JSON"),
        ("--parent-archive", "verified source runtime parent archive"),
        ("--dispatcher", "existing v2/crew/short_cloud_dispatch.py"),
        ("--output", "new package directory; it must not already exist"),
    ):
        _path_arg(parser, name, help_text)
    parser.add_argument("--expected-voice-sha256", required=True,
                        help="64-hex digest supplied independently of the hosted voice artifact")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args), indent=2, sort_keys=True))
    except BuildRefusal as exc:
        print(f"S90 hosted review builder refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
