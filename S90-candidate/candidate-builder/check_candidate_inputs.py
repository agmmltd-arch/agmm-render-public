#!/usr/bin/env python3
"""Text-only S90 AV candidate preflight; optional checks stat media paths only."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_LIBRARY_SHA256 = "2744f53024d42208538675f8d27e24e3f06c4135b81e892af29e2f0538c56215"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def missing_sfx_paths(mix: dict, library: dict, library_root: Path, is_file=None) -> list[str]:
    """Return referenced absent asset paths; never opens any SFX bytes."""
    is_file = is_file or Path.is_file
    cues = (mix.get("sfx") or {}).get("cues")
    items = library.get("items")
    if not isinstance(cues, list) or len(cues) != 19:
        raise ValueError("mix candidate must retain exactly 19 SFX cues")
    if not isinstance(items, list):
        raise ValueError("sound library has no items list")
    by_id = {row.get("id"): row for row in items if isinstance(row, dict)}
    missing: list[str] = []
    for cue in cues:
        key = cue.get("sfx_id") if isinstance(cue, dict) else None
        entry = by_id.get(key)
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError(f"unknown SFX library ID: {key}")
        path = (library_root / entry["path"]).resolve()
        if not is_file(path):
            missing.append(f"{key}:{path}")
    return sorted(set(missing))


def check_text(candidate: Path, library_path: Path) -> dict:
    scene = candidate / "scenes.js"
    delta = candidate / "spec-delta.json"
    spec_path = candidate / "S90-spec-candidate.json"
    story_path = candidate / "S90-storyboard-candidate.json"
    mix_path = candidate / "S90-mix_spec.hosted-candidate.json"
    voice_identity = candidate / "HOSTED-VOICE-ASSET-IDENTITY.json"
    summary_path = candidate.parent / "FROZEN-INPUTS.json"
    for path in (scene, delta, spec_path, story_path, mix_path, voice_identity, summary_path, library_path):
        if not path.is_file():
            raise ValueError(f"required TEXT input is missing: {path}")
    spec, story, mix, summary = (json.loads(p.read_text()) for p in (spec_path, story_path, mix_path, summary_path))
    lib = json.loads(library_path.read_text())
    hashes = {
        "scene_sha256": digest(scene), "spec_delta_sha256": digest(delta),
        "spec_candidate_sha256": digest(spec_path), "storyboard_candidate_sha256": digest(story_path),
        "mix_spec_candidate_sha256": digest(mix_path), "voice_identity_sha256": digest(voice_identity),
    }
    if any(summary.get(key) != val for key, val in hashes.items()):
        raise ValueError("FROZEN-INPUTS binding differs from current candidate bytes")
    if spec.get("candidate_status") != "UNAPPROVED_SOURCE_CANDIDATE" or story.get("approval_state") != "NOT_APPROVED":
        raise ValueError("candidate source/storyboard must remain unapproved")
    if (spec.get("approval", {}).get("render_authorized") is not False
            or spec.get("approval", {}).get("release_authorized") is not False
            or mix.get("approval", {}).get("render_authorized") is not False
            or mix.get("approval", {}).get("release_authorized") is not False):
        raise ValueError("source and mix candidates must keep render/release disabled")
    if len((mix.get("sfx") or {}).get("cues", [])) != 19:
        raise ValueError("candidate must retain the exact 19-cue SFX plan")
    binding = mix.get("candidate_binding") or {}
    if (binding.get("scene_sha256") != hashes["scene_sha256"]
            or binding.get("spec_delta_sha256") != hashes["spec_delta_sha256"]
            or binding.get("spec_candidate_sha256") != hashes["spec_candidate_sha256"]
            or binding.get("storyboard_candidate_sha256") != hashes["storyboard_candidate_sha256"]):
        raise ValueError("mix candidate lineage differs from current scene/spec/storyboard bytes")
    if (spec.get("source_scene_sha256") != hashes["scene_sha256"]
            or story.get("scene_source", {}).get("source_scene_sha256") != hashes["scene_sha256"]):
        raise ValueError("spec/storyboard scene binding differs from current scene bytes")
    if digest(library_path) != EXPECTED_LIBRARY_SHA256:
        raise ValueError("sound library TEXT hash differs from the reviewed current library")
    if mix.get("candidate_binding", {}).get("sound_library_sha256_text_only") != EXPECTED_LIBRARY_SHA256:
        raise ValueError("mix candidate does not bind the reviewed sound library TEXT hash")
    return {**hashes, "sound_library_sha256_text_only": EXPECTED_LIBRARY_SHA256,
            "sfx_cue_count": 19, "status": "TEXT_BINDINGS_PASS; no media bytes read"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--check-assets", action="store_true", help="stat each selected SFX path; never open its bytes")
    args = parser.parse_args()
    try:
        result = check_text(args.candidate, args.library)
        if args.check_assets:
            lib = json.loads(args.library.read_text())
            mix = json.loads((args.candidate / "S90-mix_spec.hosted-candidate.json").read_text())
            missing = missing_sfx_paths(mix, lib, args.library.parent)
            result["missing_sfx_asset_paths"] = missing
            if missing:
                raise ValueError("hosted mixer/SFX preflight refused; missing selected asset files: " + ", ".join(missing))
        print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.exit(2, f"S90 AV candidate preflight refused: {exc}\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
