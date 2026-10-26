#!/usr/bin/env python3
"""sfx_cue_proof.py - do the format engine's SFX cues land on their beats? (earshot timeline sync; Actions only)

Input dir: cues.json ({"cues":[{"t","sfx_id","anchor"}]}), library.json ({"items":[{"id","onset_ms","anchor_ms","anchor","path"}]}) and the wav files.
Renders an SFX-only track twice with mix2's own rule (start = cue time - the sound's measured onset; peak-anchored sounds use anchor_ms):
  A measured  every sound placed by its MEASURED onset
  B naive     every sound placed by its FILE START
and has earshot `timeline` find the onset that answers each cue (offset_ms, negative = early). Pass = A: >= 90% of onset-anchored cues within 40 ms and
median |offset| <= 15 ms, and B visibly worse (the measurement is what makes it land). Output: sfx_cue_proof.json / .md
"""
import json, sys
from pathlib import Path
import numpy as np
import soundfile as sf

SR = 48000


def render(cues, lib, root, key, total):
    y = np.zeros(int(total * SR) + SR)
    for c in cues:
        it = lib[c["sfx_id"]]
        x, sr = sf.read(str(root / it["path"]), dtype="float64")
        x = x if x.ndim == 1 else x.mean(axis=1)
        if sr != SR:
            import soxr
            x = soxr.resample(x, sr, SR)
        off = (it["anchor_ms"] if c.get("anchor") == "peak" and it.get("anchor_ms") is not None else it["onset_ms"]) / 1000 if key == "measured" else 0.0
        s = int(round((c["t"] - off) * SR))
        g = 10 ** (c.get("gain_db", -12) / 20)
        a, b = max(0, s), min(len(y), s + len(x))
        if b > a:
            y[a:b] += x[a - s: b - s] * g
    return y


def main():
    root = Path(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    cj = json.load(open(root / "cues.json"))["cues"]
    lib = {i["id"]: i for i in json.load(open(root / "library.json"))["items"]}
    onset_cues = [c for c in cj if c.get("anchor", "onset") != "peak"]
    total = max(c["t"] for c in cj) + 2.0
    from earshot import api
    res = {"n_cues": len(cj), "n_onset_cues": len(onset_cues), "n_distinct_files": len({c["sfx_id"] for c in cj}), "tracks": {}}
    cue_list = [{"t": c["t"], "kind": c.get("category") or "cue", "id": c["sfx_id"]} for c in onset_cues]
    for key in ("measured", "naive"):
        y = render(cj, lib, root, key, total)
        pk = float(np.abs(y).max()) or 1.0
        y = y / pk * 0.9
        p = out / ("sfx_track_%s.wav" % key)
        sf.write(str(p), y.astype(np.float32), SR)
        tl = api.timeline(str(p), cues=cue_list, detail="low")
        items = tl["sync"]["cues"]["items"]
        offs = [i["offset_ms"] for i in items if i.get("offset_ms") is not None and i["status"] in ("OK", "near")]
        within = [i for i in items if i.get("offset_ms") is not None and i["status"] in ("OK", "near") and abs(i["offset_ms"]) <= 40]
        res["tracks"][key] = {"within_40ms": round(len(within) / len(items), 3), "median_abs_offset_ms": round(float(np.median(np.abs(offs))), 1) if offs else None,
                              "answered": len(offs), "n": len(items), "worst": sorted([[i["t"], i["offset_ms"], i.get("id")] for i in items if i.get("offset_ms") is not None], key=lambda r: -abs(r[1]))[:6],
                              "stats": tl["sync"]["cues"]["stats"]}
        (out / ("sfx_track_%s.wav" % key)).unlink()      # the track holds licensed sounds: keep numbers only
    A, B = res["tracks"]["measured"], res["tracks"]["naive"]
    res["pass"] = bool(A["within_40ms"] >= 0.90 and A["median_abs_offset_ms"] is not None and A["median_abs_offset_ms"] <= 15 and (B["median_abs_offset_ms"] or 0) > (A["median_abs_offset_ms"] or 0))
    json.dump(res, open(out / "sfx_cue_proof.json", "w"), indent=1)
    lines = ["# SFX cue onset proof (earshot timeline sync)", "", "%d cues (%d onset-anchored), %d distinct files" % (res["n_cues"], res["n_onset_cues"], res["n_distinct_files"])]
    for k, v in res["tracks"].items():
        lines.append("- %s: %.0f%% of cues within 40 ms, median |offset| %s ms (%d answered of %d); worst %s" % (k, 100 * v["within_40ms"], v["median_abs_offset_ms"], v["answered"], v["n"], v["worst"][:3]))
    lines.append("PASS" if res["pass"] else "FAIL")
    (out / "sfx_cue_proof.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
