#!/usr/bin/env python3
"""mix_gate.py - the final-mix audio gate for one rendered short (earshot, MIT; CPU; no paid call).

Input: the gate bundle root (<root>/v2/kit/out/<ID>/FINAL.mp4, audio/cues.json, audio/mix2/stems/{voice,music}.wav).
Runs earshot critique (launch-film scorecard + timestamped fixes) and timeline (listening transcript + sync of sound to the cut
and to the mix's own cue list), then FAILS on the three named majors:
  M1 body level by 1 s    critique first_sound_s above mix.first_sound_max_s
  M2 hits off the cut     cues (and picture cuts) whose answering sound is more than 80 ms off, above the allowed fraction
  M3 bed swelling in gaps an earshot swell on the music stem peaking inside a voice gap >= voice_gap_min_s
Everything else critique flags is recorded as WARN with its timestamped fix. --selftest injects each defect into the real inputs
and asserts the gate FAILS it (silent opening, cues shifted 120 ms, a swell planted in the first voice gap).
Mode warn: record, exit 0. Mode required: exit 1 on FAIL. Output: EARSHOT.json, EARSHOT.md (+ timeline.txt).
"""
import argparse, copy, json, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
TH = json.load(open(HERE / "thresholds.json"))["mix"]


def voice_gaps(voice_wav, min_gap, th=None):
    import soundfile as sf
    x, sr = sf.read(voice_wav, always_2d=False, dtype="float32")
    m = x.mean(axis=1) if x.ndim == 2 else x
    n = int(sr * 0.02)
    k = len(m) // n
    db = 20 * np.log10(np.sqrt((m[: k * n].reshape(k, n) ** 2).mean(axis=1)) + 1e-9)
    on = db > max(-55.0, float(np.percentile(db, 95)) - 32)
    idx = np.where(on)[0]
    if not len(idx):
        return []
    first, last = idx[0], idx[-1]
    gaps, i = [], first
    while i <= last:
        if not on[i]:
            j = i
            while j <= last and not on[j]:
                j += 1
            if (j - i) * n / sr >= min_gap:
                gaps.append((i * n / sr, j * n / sr))
            i = j
        else:
            i += 1
    return gaps


def bed_swells_in_gaps(music_wav, gaps, th=TH):
    from earshot import audio, timeline as T
    x = audio.load(music_wav)
    sw = [e for e in T._swells(x, [], min_rise_db=th["bed_swell_min_rise_db"]) if e["band"] == "full"]     # full band only: one band's beat is music, not a swell
    pad = th["bed_swell_gap_pad_s"]
    return [{"t": round(e["t"], 2), "rise_db": round(e["contrast_db"], 1), "gap": [round(a, 2), round(b, 2)]}
            for e in sw for a, b in gaps if a - pad <= e["t"] <= b + pad]


def bed_rise_in_gaps(music_wav, gaps, th=TH):
    """Sam's house rule (bed rises <= 3 dB in a voice gap), re-measured by earshot's K-weighted momentary curve on the music stem:
    rise = loudest 400 ms block fully inside the gap minus the median of the 0.8 s before the gap. Fails above bed_gap_rise_max_db (3 dB + 1 dB tolerance)."""
    from earshot import audio, features
    x = audio.load(music_wav)
    t, L = features.loudness_curve(x, 0.4, 0.05)
    out = []
    for a, b in gaps:
        pre, inn = L[(t >= a - 0.8) & (t <= a)], L[(t >= a + 0.2) & (t <= b - 0.2)]
        if len(pre) < 3 or not len(inn):
            continue
        out.append({"gap": [round(a, 2), round(b, 2)], "rise_db": round(float(inn.max() - np.median(pre)), 1)})
    return out


def sync_stats(items, off_ms, strict=False):
    """strict: every item that is not answered by an onset within off_ms counts as off (use on the SFX-only stem, where nothing else makes onsets);
    default: only answered items count (picture cuts, where silence at a cut is normal)"""
    ans = [i for i in items if i.get("offset_ms") is not None and i["status"] in ("OK", "near", "off")]
    off = [i for i in ans if abs(i["offset_ms"]) > off_ms]
    if strict:
        off = [i for i in items if not (i.get("offset_ms") is not None and i["status"] in ("OK", "near") and abs(i["offset_ms"]) <= off_ms)]
        ans = items
    return {"n": len(items), "answered": len(ans), "off": len(off), "off_fraction": round(len(off) / len(ans), 3) if ans else 0.0,
            "off_items": [{"t": i["t"], "offset_ms": i["offset_ms"], "id": i.get("id"), "event": i.get("event")} for i in off[:12]]}


def gate(final, cues, voice_wav, music_wav, use_realness=True, th=TH, sfx_wav=None):
    from earshot import api
    crit = api.critique(final, video=final, use_realness=use_realness)
    cj = json.load(open(cues)) if isinstance(cues, str) else cues
    onset_cues = [c for c in cj["cues"] if c.get("anchor", "onset") != "peak"]     # a peak-anchored riser / swell lands its PEAK on the event: onset timing does not apply
    cue_list = [{"t": c["t"], "kind": c.get("category") or c.get("event") or "cue", "id": c.get("sfx_id")} for c in onset_cues]
    tl = api.timeline(final, video=final, cues=cue_list)
    stem_tl = api.timeline(sfx_wav, cues=cue_list, detail="low") if sfx_wav and os.path.exists(sfx_wav) else None
    rules = []
    fs = next((r for r in crit["metrics"] if r["metric"] == "first_sound_s"), None)
    v = fs and fs.get("value")
    ok = v is not None and v <= th["first_sound_max_s"]
    rules.append({"id": "M1", "name": "body level by %.1f s" % th["first_sound_max_s"], "status": "PASS" if ok else ("WARN" if v is None else "FAIL"),
                  "detail": "first_sound_s = %s (critique: %s)" % (v, fs and fs.get("status"))})
    sy = tl.get("sync", {})
    if stem_tl is not None:
        cue_s = sync_stats((stem_tl.get("sync", {}).get("cues") or {}).get("items", []), th["cue_offset_max_ms"], strict=True)
        cue_src = "the SFX-only stem"
    else:
        cue_s = sync_stats((sy.get("cues") or {}).get("items", []), th["cue_offset_max_ms"])
        cue_src = "the final mix (no SFX stem: weak, dense mixes answer almost anything)"
    cut_s = sync_stats((sy.get("cuts") or {}).get("items", []), th["cut_offset_max_ms"])
    rules.append({"id": "M2a", "name": "cue hits within %d ms of the cue" % th["cue_offset_max_ms"],
                  "status": "PASS" if cue_s["off_fraction"] <= th["cue_off_fraction_max"] else "FAIL",
                  "detail": "%d of %d onset cues not answered within %d ms on %s (%.0f%%, allowed %.0f%%)" % (
                      cue_s["off"], cue_s["answered"], th["cue_offset_max_ms"], cue_src, 100 * cue_s["off_fraction"], 100 * th["cue_off_fraction_max"]), "items": cue_s["off_items"]})
    rules.append({"id": "M2b", "name": "hits within %d ms of the picture cut" % th["cut_offset_max_ms"],
                  "status": "PASS" if cut_s["off_fraction"] <= th["cut_off_fraction_warn"] else ("WARN" if cut_s["off_fraction"] <= th["cut_off_fraction_max"] else "FAIL"),
                  "detail": "%d of %d answered cuts off by more than %d ms (%.0f%%, warn above %.0f%%, fail above %.0f%%; picture cuts are frame-difference events, fuzzy on animated HTML)" % (
                      cut_s["off"], cut_s["answered"], th["cut_offset_max_ms"], 100 * cut_s["off_fraction"], 100 * th["cut_off_fraction_warn"], 100 * th["cut_off_fraction_max"]), "items": cut_s["off_items"]})
    gaps = voice_gaps(voice_wav, th["voice_gap_min_s"]) if voice_wav and os.path.exists(voice_wav) else []
    rises = bed_rise_in_gaps(music_wav, gaps, th) if music_wav and os.path.exists(music_wav) else []
    bad = [r for r in rises if r["rise_db"] > th["bed_gap_rise_max_db"]]
    sw = bed_swells_in_gaps(music_wav, gaps, th) if music_wav and os.path.exists(music_wav) else []
    rules.append({"id": "M3", "name": "bed does not swell in voice gaps", "status": "PASS" if len(bad) <= th["max_bed_swells_in_gaps"] else "FAIL",
                  "detail": "%d voice gaps >= %.2f s, %d with the bed rising more than %.1f dB (worst %+.1f dB); earshot full-band swells >= %.0f dB inside gaps (info): %d" % (
                      len(gaps), th["voice_gap_min_s"], len(bad), th["bed_gap_rise_max_db"], max([r["rise_db"] for r in rises] or [0.0]), th["bed_swell_min_rise_db"], len(sw)), "items": bad[:12]})
    fails = [r for r in rules if r["status"] == "FAIL"]
    overall = "FAIL" if fails else ("WARN" if crit.get("major_issues") or crit.get("critical_issues") or any(r["status"] == "WARN" for r in rules) else "PASS")
    return {"overall": overall, "rules": rules, "critique": crit, "timeline": tl, "gaps": [[round(a, 2), round(b, 2)] for a, b in gaps]}


def evidence(res, ID, mode):
    c, tl = res["critique"], res["timeline"]
    ev = {"id": ID, "mode": mode, "overall": res["overall"], "rules": res["rules"], "voice_gaps": res["gaps"],
          "critique": {"verdict": c.get("verdict"), "score": c.get("score"), "in_range": c.get("in_range"), "scored": c.get("scored"),
                       "critical_issues": c.get("critical_issues"), "major_issues": c.get("major_issues"), "summary": c.get("summary"),
                       "fixes": c.get("actions", [])[:15],
                       "metrics": [{k: r.get(k) for k in ("metric", "value", "unit", "range", "status", "weight")} for r in c["metrics"] if r["status"] not in ("n.a.",)]},
          "timeline": {"summary": tl.get("summary"), "loudness": tl.get("loudness"), "sync_stats": {k: v.get("stats") for k, v in (tl.get("sync") or {}).items()},
                       "n_events": len(tl.get("events", [])), "n_cuts": len(tl.get("cuts", []))}}
    return ev


def write(res, out, ID, mode):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ev = evidence(res, ID, mode)
    json.dump(ev, open(out / "EARSHOT.json", "w"), indent=1, default=str)
    (out / "timeline.txt").write_text(res["timeline"].get("text", ""))
    L = ["# earshot final-mix gate %s: %s (mode %s)" % (ID, res["overall"], mode), ""]
    for r in res["rules"]:
        L.append("- %s %s: %s. %s" % (r["id"], r["status"], r["name"], r["detail"]))
        for it in r.get("items", [])[:6]:
            L.append("    - %s" % json.dumps(it))
    c = res["critique"]
    L += ["", "critique: %s, %s of %s metrics in range, %s critical, %s major" % (c.get("verdict"), c.get("in_range"), c.get("scored"), c.get("critical_issues"), c.get("major_issues")), "", "timestamped fixes (critique):"]
    L += ["- [%s] %s: %s" % (a["weight"], a["metric"], a["action"]) for a in c.get("actions", [])[:15]] or ["- none"]
    (out / "EARSHOT.md").write_text("\n".join(L) + "\n")
    return "\n".join(L)


def selftest(final, cues, voice_wav, music_wav, work, sfx_wav=None):
    from earshot import api
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    results = {}
    # 1. silent opening: delay the whole audio 1.6 s, picture untouched
    late = work / "silent_open.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", final, "-af", "adelay=1600|1600", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(late)], check=True)
    r = gate(str(late), cues, voice_wav, music_wav, use_realness=False, sfx_wav=sfx_wav)
    results["silent_open"] = ("M1", any(x["id"] == "M1" and x["status"] == "FAIL" for x in r["rules"]))
    # 2. cues shifted 120 ms late: the mix's own cue list no longer matches the sound
    j = json.load(open(cues))
    frac0 = None
    for c in j["cues"]:
        c["t"] = round(c["t"] + 0.12, 4)
    sh = work / "cues_shifted.json"
    json.dump(j, open(sh, "w"))
    r = gate(final, str(sh), voice_wav, music_wav, use_realness=False, sfx_wav=sfx_wav)
    results["cues_shifted_120ms"] = ("M2a", any(x["id"] == "M2a" and x["status"] == "FAIL" for x in r["rules"]))
    results["cues_shifted_120ms_detail"] = [x["detail"] for x in r["rules"] if x["id"] == "M2a"]
    # 3. a swell planted in the first voice gap of the music stem
    import soundfile as sf
    gaps = voice_gaps(voice_wav, TH["voice_gap_min_s"])
    x, sr = sf.read(music_wav, always_2d=False, dtype="float32")
    if gaps:
        a, b = gaps[0]
        n0, n1 = int(max(0, a - 0.05) * sr), int(min(len(x) / sr, b) * sr)
        env = np.linspace(0.0, 1.0, n1 - n0) ** 2 * np.hanning(2 * (n1 - n0))[: n1 - n0] * 2
        rng = np.random.default_rng(3)
        nz = rng.standard_normal(n1 - n0).astype(np.float32) * 0.25 * env
        y = x.copy()
        if y.ndim == 2:
            y[n0:n1] += nz[:, None]
        else:
            y[n0:n1] += nz
        sw = work / "music_swell.wav"
        sf.write(str(sw), np.clip(y, -1, 1), sr)
        found = [r_ for r_ in bed_rise_in_gaps(str(sw), gaps) if r_["rise_db"] > TH["bed_gap_rise_max_db"]]
        results["bed_swell_in_gap"] = ("M3", len(found) > TH["max_bed_swells_in_gaps"])
        results["bed_swell_in_gap_detail"] = found[:3]
    else:
        results["bed_swell_in_gap"] = ("M3", False)
    ok = all(v[1] for k, v in results.items() if not k.endswith("_detail"))
    print("SELFTEST", json.dumps(results), "OK" if ok else "FAILED")
    return ok, results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="dir holding FINAL.mp4 and audio/ (kit/out/<ID>)")
    ap.add_argument("--id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=("warn", "required"), default="warn")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    root = Path(a.root)
    final, cues = str(root / "FINAL.mp4"), str(root / "audio" / "cues.json")
    stems = root / "audio" / "mix2" / "stems"
    voice = str(stems / "voice.wav") if (stems / "voice.wav").exists() else str(root / "audio" / "voice-padded.wav")
    music = str(stems / "music.wav") if (stems / "music.wav").exists() else None
    sfx = str(stems / "sfx.wav") if (stems / "sfx.wav").exists() else None
    res = gate(final, cues, voice, music, sfx_wav=sfx)
    txt = write(res, a.out, a.id, a.mode)
    print(txt)
    if res["overall"] == "WARN" or res["overall"] == "FAIL":
        print("::%s::earshot final-mix gate %s: %s" % ("error" if (res["overall"] == "FAIL" and a.mode == "required") else "warning", a.id, res["overall"]))
    rc = 0
    if a.selftest:
        ok, results = selftest(final, cues, voice, music, Path(a.out) / "selftest", sfx_wav=sfx)
        json.dump(results, open(Path(a.out) / "selftest.json", "w"))
        rc = 0 if ok else 1
    if res["overall"] == "FAIL" and a.mode == "required":
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
