#!/usr/bin/env python3
"""Frame snapshots of an exact AGMM short package on a hosted runner (kit/tools/snap.py AGMM_SNAP=actions).

prepare: verify source.tar.gz against its hash, safely extract it, validate the snapshot plan and write groups.tsv.
convert: turn the runner's PNG frames into JPG q92 (the same conversion snap.py applies to codespace frames) and write
         a receipt.  This helper never renders video, approves, arms or publishes anything.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_short_package as short  # noqa: E402

LABEL_RE = short.OUT_RE
MAX_LOOKS = 32
MAX_TIMES_PER_LOOK = 400
MAX_TIMES_TOTAL = 800


def parse_plan(raw: str) -> list[dict]:
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as error:
        raise short.ContractError(f"plan is not JSON: {error}") from error
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_LOOKS:
        raise short.ContractError(f"plan must be a list of 1..{MAX_LOOKS} jobs")
    clean, parts, total = [], set(), 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise short.ContractError(f"job {index} is not an object")
        look, part, times = row.get("look"), row.get("part"), row.get("times")
        for label, value in (("look", look), ("part", part)):
            if not isinstance(value, str) or not LABEL_RE.fullmatch(value):
                raise short.ContractError(f"job {index} {label} is unsafe")
        if part in parts:
            raise short.ContractError(f"job {index} repeats part {part}")
        parts.add(part)
        if not isinstance(times, list) or not 1 <= len(times) <= MAX_TIMES_PER_LOOK:
            raise short.ContractError(f"job {index} needs 1..{MAX_TIMES_PER_LOOK} times")
        ts = []
        for value in times:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 3600:
                raise short.ContractError(f"job {index} has an invalid time {value!r}")
            ts.append(round(float(value), 2))
        total += len(ts)
        clean.append({"look": look, "part": part, "times": ts})
    if total > MAX_TIMES_TOTAL:
        raise short.ContractError(f"plan has {total} frames, more than {MAX_TIMES_TOTAL}")
    return clean


def prepare(args: argparse.Namespace) -> None:
    source = Path(args.source)
    short.verify_hash(source, args.source_sha256, "source.tar.gz")
    out = Path(args.output)
    short.safe_extract(source, out / "project")
    plan = parse_plan(args.plan)
    for job in plan:
        index = out / "project" / job["look"] / "index.html"
        if not index.is_file():
            raise short.ContractError(f"package has no {job['look']}/index.html")
    (out / "PLAN.json").write_text(json.dumps(plan, indent=1) + "\n")
    with (out / "groups.tsv").open("w") as handle:
        for job in plan:
            handle.write("%s\t%s\t%s\n" % (job["look"], job["part"], ",".join("%.2f" % t for t in job["times"])))
    print("prepared %d looks, %d frames" % (len(plan), sum(len(j["times"]) for j in plan)))


def convert(args: argparse.Namespace) -> None:
    from PIL import Image
    raw, dest = Path(args.raw), Path(args.dest)
    plan = json.loads((Path(args.prepared) / "PLAN.json").read_text())
    receipt = {"kind": "agmm_short_snap_receipt", "hyperframes": short.HYPERFRAMES_VERSION, "run_id": args.run_id,
               "source_sha256": args.source_sha256, "parts": {}}
    for job in plan:
        src = raw / job["part"]
        pngs = sorted(src.glob("*.png"))
        frames = [p for p in pngs if p.name.startswith("frame-")]
        if len(frames) < len(set(job["times"])):
            raise short.ContractError("%s: expected %d frames, snapshot produced %d" % (job["part"], len(set(job["times"])), len(frames)))
        target = dest / job["part"]
        target.mkdir(parents=True, exist_ok=True)
        names = []
        for png in pngs:
            jpg = target / (png.stem + ".jpg")
            Image.open(png).convert("RGB").save(jpg, quality=92)
            names.append(jpg.name)
        receipt["parts"][job["part"]] = names
    (dest / "SNAP-RECEIPT.json").write_text(json.dumps(receipt, indent=1) + "\n")
    print("converted %d frames" % sum(len(v) for v in receipt["parts"].values()))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--source", required=True); p.add_argument("--source-sha256", required=True)
    p.add_argument("--plan", required=True); p.add_argument("--output", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--raw", required=True); c.add_argument("--prepared", required=True); c.add_argument("--dest", required=True)
    c.add_argument("--run-id", default=""); c.add_argument("--source-sha256", default="")
    args = ap.parse_args()
    try:
        {"prepare": prepare, "convert": convert}[args.cmd](args)
    except short.ContractError as error:
        print("CONTRACT ERROR: %s" % error, file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
