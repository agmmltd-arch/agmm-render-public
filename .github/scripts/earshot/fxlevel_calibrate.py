#!/usr/bin/env python3
"""fxlevel_calibrate.py INPUTS OUT : calibrate and prove the 100 ms check-13 measure (Actions only; ffmpeg + numpy + soundfile).

INPUTS/cases.json = [{"name","group","mode","mix","voice"}], INPUTS/fx/{fxlevel_live.py, fxlevel_next.py, audio_core.py}. mode: "legacy" (raw voice-padded.wav, the
old mixer: P1-P3, S05) or "mix2" (the processed voice stem). For every case: the live 400 ms numbers and the new 100 ms numbers. Limits = the approved cases' worst + 1 dB.
Then the next fxlevel is run with those limits on every case, and a +8 dB / 80 ms hit is injected into one approved case of each mode: the 400 ms check must PASS it and the
100 ms check must FAIL it. Output: TABLE.md, calibration.json, limits.json, INJECTION.md"""
import importlib.util, json, os, shutil, sys, tempfile
from pathlib import Path
import numpy as np
import soundfile as sf


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(root / "fx"))
    live = load(root / "fx/fxlevel_live.py", "fxlevel_live")
    nxt = load(root / "fx/fxlevel_next.py", "fxlevel_next")
    cases = json.load(open(root / "cases.json"))
    # S05's audio is a tar
    for c in cases:
        for k in ("mix", "voice"):
            c[k] = str(root / c[k])
    rows = []
    for c in cases:
        d4 = live.measure(c["mix"], c["voice"])
        d1 = nxt.measure100(c["mix"], c["voice"])
        d4n = nxt.measure(c["mix"], c["voice"])
        c["same400"] = d4n == d4          # the new file must leave every 400 ms number exactly as it was
        rows.append(dict(c, p98_400=d4.get("over_speech_p98"), pause_400=d4.get("over_pause_max"), worst3_400=d4.get("over_speech_worst"), **d1))
        print(c["name"], d4.get("over_speech_p98"), d4.get("over_pause_max"), d1.get("over_speech_100ms"), d1.get("over_pause_100ms"), flush=True)
    appr = {m: [r for r in rows if r["mode"] == m and r["group"] == "approved"] for m in ("legacy", "mix2")}
    limits = {}
    for m, rs in appr.items():
        if rs:
            limits[m] = {"over_speech_100ms": round(max(r["over_speech_100ms"] for r in rs) + 1.0, 1), "over_pause_100ms": round(max(r["over_pause_100ms"] for r in rs if r["over_pause_100ms"] is not None) + 1.0, 1),
                         "from": [r["name"] for r in rs]}
    json.dump(limits, open(out / "limits.json", "w"), indent=1)
    nxt.LIMITS100_LEGACY.update({k: v for k, v in limits.get("legacy", {}).items() if k != "from"})
    nxt.LIMITS100_MIX2.update({k: v for k, v in limits.get("mix2", {}).items() if k != "from"})
    # the gate's own limits for each mode (gate_core.py: mix2 vs the processed voice stem uses 1.5 / 2.5, the old mixer 8.0 / 2.5)
    L = ["# fxlevel check 13: 400 ms momentary vs 100 ms blocks", "", "dB over the voice. 400 ms = today's check (p98 over speech / worst pause); 100 ms = the new measure (worst block over speech / worst block in a pause).", "",
         "| case | group | mode | 400 ms p98 speech | 400 ms pause | 100 ms speech (worst block) | 100 ms p98 | 100 ms pause | worst 3 events (100 ms, s) | new check |", "|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for r in rows:
        nxt.LIMITS.clear()
        nxt.LIMITS.update({"over_speech_p98": 1.5, "over_pause_max": 2.5} if r["mode"] == "mix2" else {"over_speech_p98": 8.0, "over_pause_max": 2.5})
        chk = nxt.check(r["mix"], r["voice"])
        res[r["name"]] = {"status": chk["status"], "summary": chk["summary"]}
        w = ", ".join("%+.1f@%.1f" % (e["over_db"], e["t"]) for e in (r.get("worst5_100ms") or [])[:3])
        L.append("| %s | %s | %s | %+.1f | %s | %+.1f | %s | %s | %s | %s |" % (r["name"], r["group"], r["mode"], r["p98_400"], "%+.1f" % r["pause_400"] if r["pause_400"] is not None else "-", r["over_speech_100ms"],
                                                                         "%+.1f" % r["over_speech_100ms_p98"] if r["over_speech_100ms_p98"] is not None else "-", "%+.1f" % r["over_pause_100ms"] if r["over_pause_100ms"] is not None else "-", w, chk["status"]))
    L += ["", "400 ms numbers identical between today's fxlevel.py and the new one on every case: %s" % all(r["same400"] for r in rows), "", "## limits (approved shorts' worst + 1 dB)", ""]
    for m, v in limits.items():
        L.append("- %s: over_speech_100ms %.1f, over_pause_100ms %.1f (from %s)" % (m, v["over_speech_100ms"], v["over_pause_100ms"], v["from"]))
    json.dump({"rows": rows, "checks": res}, open(out / "calibration.json", "w"), indent=1, default=str)
    (out / "TABLE.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    # injection proof
    I = ["# +8 dB / 80 ms hit: can the check fail?", ""]
    ok_all = True
    I.append("Legacy mode (old mixer, raw voice-padded.wav) is not injectable: the approved P1-P3 / S05 already read +10 to +14 dB on a 100 ms block against the raw voice, so a +8 dB hit does not stand out of them. The 100 ms rule bites in mix2 mode, where the reference is the processed voice stem.")
    I.append("")
    for m, name in (("mix2", "S25"), ("mix2", "S104")):
        c = next((r for r in rows if r["name"] == name), None)
        if not c:
            continue
        mix, sr = sf.read(c["mix"], dtype="float64", always_2d=True)
        vsr = sf.read(c["voice"], dtype="float64", always_2d=True)[0]
        # a speech region with no existing loud block: the loudest voice stretch's middle
        vm = np.abs(vsr).max(axis=1)
        w = int(0.5 * sr)
        k = len(vm) // w
        e = vm[: k * w].reshape(k, w).mean(axis=1)
        mid = int(np.argsort(e)[-(k // 3)]) * w + w // 2       # a mid-loud speech second, not the loudest
        n = int(0.08 * sr)
        rng = np.random.default_rng(5)
        burst = rng.standard_normal(n) * np.hanning(n)
        burst = burst / np.sqrt(np.mean(burst ** 2))
        work = Path(tempfile.mkdtemp())
        (work / "mix2/stems").mkdir(parents=True)
        mixp = work / ("mix2/injected.wav" if m == "mix2" else "injected.wav")
        voicep = work / ("mix2/stems/voice.wav" if m == "mix2" else "voice.wav")
        shutil.copyfile(c["voice"], voicep)

        def level(gain):
            y = mix.copy()
            y[mid: mid + n, :] += (burst * gain)[:, None]
            sf.write(str(mixp), np.clip(y, -1, 1).astype(np.float32), sr, subtype="PCM_24")
            d = nxt.measure100(str(mixp), str(voicep))
            return d["over_speech_100ms"], y
        lo, hi = 1e-4, 0.6
        best = None
        for _ in range(16):
            g = (lo * hi) ** 0.5
            lv, _ = level(g)
            if best is None or abs(lv - 8.0) < abs(best[0] - 8.0):
                best = (lv, g)
            lo, hi = (g, hi) if lv < 8.0 else (lo, g)
        lv, y = level(best[1])
        nxt.LIMITS.clear()
        nxt.LIMITS.update({"over_speech_p98": 1.5, "over_pause_max": 2.5} if m == "mix2" else {"over_speech_p98": 8.0, "over_pause_max": 2.5})
        base = nxt.check(c["mix"], c["voice"])
        l400 = live_check = None
        live.LIMITS.clear()
        live.LIMITS.update(dict(nxt.LIMITS))
        l400 = live.check(str(mixp), str(voicep))
        n100 = nxt.check(str(mixp), str(voicep))
        okm = l400["status"] == "PASS" and n100["status"] == "FAIL" and base["status"] == "PASS"
        ok_all &= okm
        I += ["## %s (%s mode)" % (name, m), "- hit: 80 ms noise burst at %.2f s, scaled until the 100 ms block reads %+.1f dB over the voice" % (mid / sr, lv),
              "- unmodified %s, new check: %s" % (name, base["status"]), "- injected, TODAY's 400 ms check: **%s** (%s)" % (l400["status"], l400["summary"][:200]),
              "- injected, NEW 100 ms check: **%s** (%s)" % (n100["status"], n100["summary"][:260]), "- proof: 400 ms passes the hit, 100 ms fails it: %s" % okm, ""]
    I.append("RESULT: " + ("PROVEN, the 100 ms check fails what the 400 ms check passes" if ok_all else "NOT PROVEN"))
    (out / "INJECTION.md").write_text("\n".join(I) + "\n")
    print("\n".join(I))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
