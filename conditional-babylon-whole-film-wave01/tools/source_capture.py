#!/usr/bin/env python3
"""Return bounded, explicitly estimated HyperFrames source-capture times."""
import argparse
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POINTS = [
    ("opening-claim", "scene-01-number", 0.68, "81% claim enters its selected-question aperture"),
    ("sample-boundary", "scene-02-sample", 0.56, "Source types and unselected examination boundary"),
    ("separate-comparator", "scene-03-comparator", 0.58, "81% sample result and 72% historical pass-mark remain separate"),
    ("separate-study", "scene-04-separate-study", 0.56, "Company vignettes, prospective paper, and 81% sample remain distinct"),
    ("service-profile", "scene-05-gp-at-hand", 0.55, "Patient-selection context and QOF comparator"),
    ("dated-service-count", "scene-06-service-count", 0.55, "September 2023 date beside London service count"),
    ("chronology-seam", "scene-07-company-chronology", 0.6, "Dated corporate events with no causal line to the 2018 score"),
    ("closing-questions", "scene-08-takeaway", 0.68, "Four benchmark questions and audit CTA"),
]


def source_points():
    board = json.loads((ROOT / "inputs/storyboard-wave03.json").read_text())
    wpm = board["clock_basis"]["words_per_minute"]
    offset = 0.0
    result = []
    by_id = {scene["id"]: scene for scene in board["scenes"]}
    for name, scene_id, fraction, reason in POINTS:
        scene = by_id[scene_id]
        duration = len(scene["script"].split()) / wpm * 60
        result.append({"name": name, "scene_id": scene_id, "at_s": round(offset + duration * fraction, 3), "scene_offset_s": round(duration * fraction, 3), "reason": reason})
        offset += duration
    return {"status": "estimated-source-capture-plan", "clock_basis": board["clock_basis"]["status"], "canvas": board["canvas_basis"], "points": result}


def check_pngs(plan):
    failures = []
    expected_names = []
    for index, point in enumerate(plan["points"]):
        timestamp = f"{point['at_s']:.3f}".rstrip("0").rstrip(".") + "s"
        # HyperFrames snapshot numbers every frame with a two-digit index.
        expected_names.append(f"frame-{index:02d}-at-{timestamp}.png")
        path = ROOT / "captures" / expected_names[-1]
        if not path.is_file():
            failures.append(f"missing {path.name}")
            continue
        with path.open("rb") as image:
            data = image.read(24)
        if len(data) != 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
            failures.append(f"invalid PNG {path.name}")
            continue
        width, height = struct.unpack(">II", data[16:24])
        if (width, height) != (3840, 2160):
            failures.append(f"{path.name}: expected 3840x2160, got {width}x{height}")
    actual_names = sorted(path.name for path in (ROOT / "captures").glob("frame-*.png"))
    if actual_names != expected_names:
        failures.append(f"expected exactly {len(expected_names)} ordered frame PNGs, found {len(actual_names)}")
    if failures:
        raise SystemExit("BLOCKED: " + "; ".join(failures))
    print(f"PASS: {len(plan['points'])} bounded native PNG stills are 3840x2160")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--times", action="store_true", help="print comma-separated estimated timestamps for HyperFrames snapshot")
    parser.add_argument("--write-plan", type=Path, help="write the source-capture plan JSON")
    parser.add_argument("--check-pngs", action="store_true", help="verify all expected PNG names and native dimensions")
    args = parser.parse_args(argv)
    plan = source_points()
    if args.times:
        print(",".join(str(point["at_s"]) for point in plan["points"]))
    if args.write_plan:
        args.write_plan.write_text(json.dumps(plan, indent=2) + "\n")
    if args.check_pngs:
        check_pngs(plan)
    if not (args.times or args.write_plan or args.check_pngs):
        print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
