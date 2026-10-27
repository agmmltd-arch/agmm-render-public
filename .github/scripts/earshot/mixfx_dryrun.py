#!/usr/bin/env python3
"""mixfx_dryrun.py SRC SID OUT : does the staged mix2 word-mask fix (loudest 100 ms block instead of a mean) change what the 100 ms check 13 sees? (Actions only)
SRC = a V2 subtree of one engine short's audio inputs (see audio_remix_audit.py) plus fx/{mix2_next.py,fxlevel_next.py}. Renders the SAME spec with today's mix2.py and with
mix2.py.next, then measures both masters against their voice stems with the 100 ms and 400 ms numbers, and counts the word-mask clamps each mixer applied."""
import importlib.util, json, os, subprocess, sys, shutil
from pathlib import Path


def main():
    src, sid, out = Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    v2 = src / "v2"
    spec_p = v2 / "kit/out" / sid / "audio/mix_spec.json"
    spec_p.write_text(spec_p.read_text().replace("/Users/samwall/alfred/builds/video-program-2026-09-23/v2", str(v2)))
    shutil.copyfile(src / "fx/mix2_next.py", v2 / "sound/v2/mix2_next.py")
    env = dict(os.environ, AGMM_SFX_SOURCE="openverse")
    res = {}
    for name, script in (("today", "mix2.py"), ("next", "mix2_next.py")):
        o = out / ("mix_" + name)
        r = subprocess.run([sys.executable, str(v2 / "sound/v2" / script), "render", str(spec_p), "--out", str(o)], capture_output=True, text=True, env=env)
        if r.returncode:
            print(name, "mix2 failed", r.stderr[-600:])
            return 2
        man = json.load(open(o / "mix_manifest.json"))
        res[name] = {"dir": o, "clamps": [c for c in man.get("clamps", []) if "word_mask" in c.get("rule", "")], "n_clamps": len(man.get("clamps", []))}
    sp = importlib.util.spec_from_file_location("fxn", src / "fx/fxlevel_next.py")
    fx = importlib.util.module_from_spec(sp)
    sys.path.insert(0, str(v2 / "sound/v2"))
    sp.loader.exec_module(fx)
    L = ["# mix2 word-mask fix (100 ms block instead of a mean), %s with the SFX library" % sid, "", "| mixer | word-mask clamps | 400 ms p98 over speech | 100 ms worst over speech | 100 ms worst in a pause | worst 3 events (100 ms) |", "|---|---|---|---|---|---|"]
    for name in ("today", "next"):
        d = res[name]["dir"]
        m4 = fx.measure(str(d / "master.wav"), str(d / "stems/voice.wav"))
        m1 = fx.measure100(str(d / "master.wav"), str(d / "stems/voice.wav"))
        res[name].update(m4=m4, m1=m1)
        L.append("| %s | %d | %+.1f | %+.1f | %s | %s |" % (name, len(res[name]["clamps"]), m4["over_speech_p98"], m1["over_speech_100ms"], "%+.1f" % m1["over_pause_100ms"] if m1["over_pause_100ms"] is not None else "-",
                                                         ", ".join("%+.1f@%.1f" % (e["over_db"], e["t"]) for e in m1["worst5_100ms"][:3])))
    a, b = res["today"]["m1"]["over_speech_100ms"], res["next"]["m1"]["over_speech_100ms"]
    L += ["", "100 ms worst over speech: today %+.1f, next %+.1f (%+.1f dB). Word-mask clamps: today %d, next %d." % (a, b, b - a, len(res["today"]["clamps"]), len(res["next"]["clamps"]))]
    (out / "MIXFX.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    for name in res:
        for k in ("dir",):
            res[name][k] = str(res[name][k])
    json.dump(res, open(out / "mixfx.json", "w"), indent=1, default=str)
    for name in ("today", "next"):
        shutil.rmtree(out / ("mix_" + name), ignore_errors=True)       # numbers only
    return 0


if __name__ == "__main__":
    sys.exit(main())
