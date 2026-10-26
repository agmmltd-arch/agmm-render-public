#!/usr/bin/env python3
"""sfx_render.py - render earshot's code-made 'launch' kit once on an ubuntu runner and write the measured registry.

earshot (MIT) makes every sound in code (no recordings, no models for this step). The kit lock carries each take's measured onset /
peak / end; this adds true peak and integrated loudness (earshot measure) and a sha256, so the format engine can place a cue by its
measured onset, never by the file start. Output: <out>/takes/*.wav + <out>/earshot-sfx-registry.json
"""
import hashlib, json, shutil, sys
from pathlib import Path


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    from earshot import api
    import earshot
    kit_json = out / "kit.json"
    api.kit_init("launch", str(kit_json), force=True)
    r = api.kit_render(str(kit_json), str(out / "kit"))
    lock = json.load(open(out / "kit" / "kit.lock.json"))
    takes_dir = out / "takes"
    takes_dir.mkdir(exist_ok=True)
    reg = {"source": "earshot %s (MIT, https://github.com/Leonxlnx/earshot), bank %s, kit preset launch" % (earshot.__version__, lock.get("bank")),
           "licence": "MIT (code); every sound is synthesised in code, no recording", "sr": lock.get("sr"), "mix": lock.get("mix"), "roles": {}}
    n = 0
    for role, spec in lock["roles"].items():
        if not spec:
            continue
        row = {k: v for k, v in spec.items() if k != "takes"}
        row["takes"] = []
        for t in spec["takes"]:
            src = out / "kit" / t["file"]
            dst = takes_dir / t["file"]
            shutil.copyfile(src, dst)
            m = api.measure(str(dst), light=True)
            row["takes"].append({"file": t["file"], "pitch": t.get("pitch"), "seed": t.get("seed"), "onset_s": t["onset_s"], "peak_s": t["peak_s"],
                                 "end_s": t["end_s"], "dur_s": t["dur_s"], "peak_db": t.get("peak_db"), "l50_lufs": t.get("l50_lufs"),
                                 "lufs": m.get("lufs"), "true_peak_dbtp": m.get("true_peak_dbtp"), "checks": t.get("checks") or [],
                                 "sha256": hashlib.sha256(open(dst, "rb").read()).hexdigest()})
            n += 1
        reg["roles"][role] = row
    json.dump(reg, open(out / "earshot-sfx-registry.json", "w"), indent=1)
    shutil.rmtree(out / "kit", ignore_errors=True)
    print("rendered %d takes in %d roles" % (n, len(reg["roles"])))
    bad = [(ro, t["file"], t["checks"]) for ro, v in reg["roles"].items() for t in v["takes"] if t["checks"]]
    print("takes with audit flags:", bad)
    for ro, v in reg["roles"].items():
        t = v["takes"][0]
        print("%-14s %-26s align %-5s onset %6.1f ms peak %6.1f ms end %6.1f ms  %s dBTP %s LUFS" % (
            ro, v["sound"], v.get("align"), t["onset_s"] * 1000, t["peak_s"] * 1000, t["end_s"] * 1000, t["true_peak_dbtp"], t["lufs"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
