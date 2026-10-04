#!/usr/bin/env python3
"""Bind the conditional scene board to actual word timings and exact script/voice bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def tokens(text: str) -> list[str]:
    return [t.casefold() for t in re.findall(r"[\w]+(?:['’][\w]+)*", text, flags=re.UNICODE)]


def rebind(board: dict, clock: dict, script_sha: str, voice_sha: str) -> dict:
    if board.get("status") != "conditional-estimated":
        raise ValueError("input storyboard must be conditional-estimated")
    if clock.get("status") != "measured":
        raise ValueError("clock status must be measured")
    if clock.get("script_sha256") != script_sha or clock.get("voice_sha256") != voice_sha:
        raise ValueError("measured clock must bind to the supplied script and voice hashes")
    if not clock.get("measurement_receipt"):
        raise ValueError("measurement_receipt is required")
    rows = clock.get("words")
    scenes = board.get("scenes")
    if not isinstance(rows, list) or not rows or not isinstance(scenes, list) or not scenes:
        raise ValueError("clock words and storyboard scenes must be nonempty arrays")
    expected_tokens = []
    for scene in scenes:
        expected_tokens.extend(tokens(scene.get("script", "")))
    clock_tokens = []
    last_end = 0.0
    by_scene: dict[str, list[tuple[float, float]]] = {}
    for i, row in enumerate(rows, 1):
        token = row.get("token")
        start, end = row.get("start_s"), row.get("end_s")
        sid = row.get("scene_id")
        if not isinstance(token, str) or not sid:
            raise ValueError(f"word row {i} needs token and scene_id")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or start < last_end or end <= start:
            raise ValueError(f"word row {i} has invalid or non-monotonic timings")
        clock_tokens.extend(tokens(token))
        if len(tokens(token)) != 1:
            raise ValueError(f"word row {i} must contain exactly one word token")
        last_end = float(end)
        by_scene.setdefault(sid, []).append((float(start), float(end)))
    if clock_tokens != expected_tokens:
        raise ValueError(f"measured words differ from storyboard narration ({len(clock_tokens)} vs {len(expected_tokens)} tokens)")
    if set(by_scene) != {scene["id"] for scene in scenes}:
        raise ValueError("clock scene IDs must exactly cover the storyboard")
    rebound = json.loads(json.dumps(board))
    for scene in rebound["scenes"]:
        times = by_scene[scene["id"]]
        scene["start_s"] = round(times[0][0], 3)
        scene["end_s"] = round(times[-1][1], 3)
        scene["duration_s"] = round(scene["end_s"] - scene["start_s"], 3)
        estimated_duration = len(tokens(scene["script"])) / float(board["clock_basis"]["words_per_minute"]) * 60
        for cue in scene.get("sound_cues", []):
            fraction = float(cue["offset_s"]) / estimated_duration
            if not 0 <= fraction <= 1:
                raise ValueError(f"sound cue for {scene['id']} lies outside its estimated scene")
            cue["offset_s"] = round(fraction * scene["duration_s"], 3)
    rebound["status"] = "measured-clock-bound"
    rebound["clock_basis"] = {
        "status": "MEASURED_FROM_APPROVED_VOICE",
        "script_sha256": script_sha,
        "voice_sha256": voice_sha,
        "clock_sha256": clock.get("clock_sha256") or "see clock input file",
        "measurement_receipt": clock["measurement_receipt"],
        "duration_s": round(last_end, 3),
    }
    return rebound


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--storyboard", type=Path, default=Path("inputs/storyboard-wave03.json"))
    p.add_argument("--script", type=Path, default=Path("SCRIPT-AND-SCENE-INPUTS-WAVE03.md"))
    p.add_argument("--voice", type=Path, required=True)
    p.add_argument("--clock", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("inputs/storyboard-measured.json"))
    args = p.parse_args()
    try:
        rebound = rebind(json.loads(args.storyboard.read_text()), json.loads(args.clock.read_text()), sha(args.script), sha(args.voice))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rebound, indent=2, ensure_ascii=False) + "\n")
        print(f"PASS: measured clock rebound {len(rebound['scenes'])} scenes to {rebound['clock_basis']['duration_s']:.3f}s; exact script and voice SHA-256 verified.")
        return 0
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
