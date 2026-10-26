#!/usr/bin/env python3
"""voice_take_check.py - listening check for sealed voice paragraph takes (earshot, MIT; CPU; no paid call).

For every *.wav in --dir (P01.wav ...; optional P01.words.json beside it) it measures with earshot and FAILS the take on:
  V1 loudness      integrated LUFS outside [lufs_min, lufs_max]                      (earshot measure)
  V2 true peak     true peak above true_peak_max_dbtp, or any clipped sample          (earshot measure)
  V3 click         a <=4 ms broadband transient inside speech (model-free d2 detector)
  V4 stray         an isolated sound blob <=350 ms in a pause, not at the edges       (model-free, words.json aware)
  V5 nonspeech     an earshot timeline event inside speech that is tagged as a non-voice sound, exposed and confident
  V6 breath        an earshot timeline event tagged 'a breath' over breath.min_peak_dbfs
Thresholds: thresholds.json (voice section). Mode: warn (record, exit 0) | required (exit 1 on any FAIL).
--selftest renders injected defects (click, clip, quiet, loud) from the first real take and asserts the check FAILS each for the
right reason; it exits 1 if the check misses one. --inject X adds the injected take X to the set under test (so a run can go red).
"""
import argparse, json, os, sys
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter

HERE = Path(__file__).resolve().parent
TH = json.load(open(HERE / "thresholds.json"))["voice"]


def to_mono(x):
    return x.mean(axis=1) if x.ndim == 2 else x


def frames_db(m, sr, ms):
    n = max(1, int(sr * ms / 1000))
    k = len(m) // n
    r = np.sqrt((m[: k * n].reshape(k, n) ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(r), n / sr


def speech_regions(m, sr, th=TH):
    db, step = frames_db(m, sr, th["speech_frame_ms"])
    thr = max(th["speech_floor_dbfs"], float(np.percentile(db, 95)) - th["speech_below_p95_db"])
    on = db > thr
    gap = int(round(th["speech_merge_gap_ms"] / 1000 / step))
    idx = np.where(on)[0]
    regs = []
    for i in idx:
        if regs and i - regs[-1][1] <= gap:
            regs[-1][1] = int(i)
        else:
            regs.append([int(i), int(i)])
    mn = th["speech_min_ms"] / 1000
    return [(a * step, (b + 1) * step) for a, b in regs if (b + 1 - a) * step >= mn], thr


def in_regions(t, regs, margin=0.0):
    return any(a + margin <= t <= b - margin for a, b in regs)


def find_clicks(m, sr, regs, th=TH["click"]):
    """model-free: 1 ms frames of the second difference (a click is a broadband step); a click is a frame far above its 81 ms
    median, whose width (frames above 35% of its height) is at most max_width_frames, with a real sample peak, inside speech"""
    d2 = np.diff(m, 2)
    fr = max(1, int(sr * 0.001))
    k = len(d2) // fr
    if k < 100:
        return [], 0.0
    e = np.sqrt((d2[: k * fr].reshape(k, fr) ** 2).mean(axis=1))
    pk = np.abs(m[: k * fr]).reshape(k, fr).max(axis=1)
    ref = median_filter(e, size=81, mode="nearest") + 1e-7
    ratio = e / ref
    out, best = [], 0.0
    for i in np.where(ratio >= 3.0)[0]:
        lo, hi = max(0, i - 6), min(k, i + 7)
        if e[i] < e[lo:hi].max():
            continue
        width = int((e[max(0, i - 8): i + 9] >= 0.35 * e[i]).sum())
        t = i * fr / sr
        if pk[i] < th["floor_peak"] or width > th["max_width_frames"]:
            continue
        if not in_regions(t, regs, th["interior_margin_ms"] / 1000):
            continue
        best = max(best, float(ratio[i]))
        out.append({"t": round(t, 3), "ratio": round(float(ratio[i]), 1), "peak": round(float(pk[i]), 3), "width_frames": width})
    return out, best


def find_strays(regs, dur, words, th=TH["stray"]):
    out = []
    if len(regs) < 2:
        return out
    for j, (a, b) in enumerate(regs):
        if (b - a) * 1000 > th["max_ms"]:
            continue
        if a < th["edge_margin_ms"] / 1000 or b > dur - th["edge_margin_ms"] / 1000:
            continue
        before = a - regs[j - 1][1] if j > 0 else 9
        after = regs[j + 1][0] - b if j + 1 < len(regs) else 9
        if before * 1000 >= th["isolation_ms"] and after * 1000 >= th["isolation_ms"]:
            if words and any(w[0] - 0.05 <= (a + b) / 2 <= w[1] + 0.05 for w in words):
                continue      # the aligned transcript says a real word is there
            out.append({"t": round(a, 3), "ms": int((b - a) * 1000)})
    return out


def load_words(wav):
    p = Path(wav).with_suffix(".words.json")
    if not p.exists():
        return None
    try:
        j = json.load(open(p))
        segs = j.get("segments") or j.get("words") or []
        return [(float(s["start"]), float(s["end"])) for s in segs if "start" in s and "end" in s]
    except Exception:
        return None


def check_take(path, api, th=TH):
    x, sr = sf.read(path, always_2d=False, dtype="float32")
    m = to_mono(x)
    dur = len(m) / sr
    meas = api.measure(path, light=True)
    regs, thr = speech_regions(m, sr, th)
    clicks, best_ratio = find_clicks(m, sr, regs, th["click"])
    strays = find_strays(regs, dur, load_words(path), th["stray"])
    tl = api.timeline(path, detail="normal")
    nonspeech, breaths = [], []
    ns, br = th["nonspeech_event"], th["breath"]
    for e in tl["events"]:
        tags = e.get("tags") or []
        if not tags:
            continue
        z0 = tags[0]["z"]
        if e.get("kind") != "VOICE":
            if (in_regions(e["t"], regs) and e.get("prominence_db", 0) >= ns["min_prominence_db"] and z0 >= ns["min_z"]
                    and e.get("length_ms", 0) <= ns["max_length_ms"]):
                nonspeech.append({"t": e["t"], "label": e.get("label"), "z": z0, "prominence_db": e["prominence_db"], "length_ms": e["length_ms"]})
        elif tags[0]["tag"] == "a breath" and z0 >= br["min_z"] and e.get("peak_dbfs", -99) >= br["min_peak_dbfs"]:
            breaths.append({"t": e["t"], "z": z0, "peak_dbfs": e["peak_dbfs"], "prominence_db": e["prominence_db"]})
    fails = []
    lufs, tp = meas.get("lufs"), meas.get("true_peak_dbtp")
    if lufs is None or not (th["lufs_min"] <= lufs <= th["lufs_max"]):
        fails.append("V1 loudness %s LUFS outside [%s, %s]" % (lufs, th["lufs_min"], th["lufs_max"]))
    if tp is not None and tp > th["true_peak_max_dbtp"]:
        fails.append("V2 true peak %.1f dBTP above %.1f" % (tp, th["true_peak_max_dbtp"]))
    if meas.get("clipped_samples", 0) > th["clipped_samples_max"]:
        fails.append("V2 clipping: %d samples at full scale" % meas["clipped_samples"])
    if len(clicks) > th["click"]["max_clicks"]:
        fails.append("V3 click inside speech at %s" % ", ".join("%.2fs (x%.0f)" % (c["t"], c["ratio"]) for c in clicks[:4]))
    if len(strays) > th["stray"]["max_strays"]:
        fails.append("V4 stray sound in a pause at %s" % ", ".join("%.2fs (%d ms)" % (s["t"], s["ms"]) for s in strays[:4]))
    if len(nonspeech) > ns["max_events"]:
        fails.append("V5 non-speech event inside speech: %s" % ", ".join("%.2fs %s" % (e["t"], e["label"]) for e in nonspeech[:4]))
    if len(breaths) > br["max_breaths"]:
        fails.append("V6 breath over %.0f dBFS at %s" % (br["min_peak_dbfs"], ", ".join("%.2fs" % b["t"] for b in breaths[:4])))
    return {"take": os.path.basename(path), "duration_s": round(dur, 2), "verdict": "FAIL" if fails else "PASS", "fails": fails,
            "lufs": lufs, "true_peak_dbtp": tp, "clipped_samples": meas.get("clipped_samples"), "noise_floor_dbfs": meas.get("noise_floor_dbfs"),
            "speech_regions": len(regs), "speech_thr_dbfs": round(thr, 1), "click_max_ratio": round(best_ratio, 1), "clicks": clicks, "strays": strays,
            "nonspeech_events": nonspeech, "breaths": breaths, "n_events": len(tl["events"]), "timeline_summary": tl.get("summary")}


def inject(src, kind, dst):
    x, sr = sf.read(src, always_2d=False, dtype="float32")
    y = x.copy().astype(np.float64)
    m = to_mono(y)
    regs, _ = speech_regions(m.astype(np.float32), sr)
    if kind == "click":
        a, b = max(regs, key=lambda r: r[1] - r[0])
        t = int(((a + b) / 2) * sr)
        n = int(0.0015 * sr)
        rng = np.random.default_rng(7)
        burst = rng.standard_normal(n) * np.hanning(n) * 0.35
        if y.ndim == 2:
            y[t: t + n, :] += burst[:, None]
        else:
            y[t: t + n] += burst
    elif kind == "clip":
        y = np.clip(y * 6.0, -1.0, 1.0)
    elif kind == "quiet":
        y = y * 10 ** (-14 / 20)
    elif kind == "loud":
        y = y * 10 ** (9 / 20)
        y = np.tanh(y * 0.9) * 0.97 if np.abs(y).max() > 0.98 else y
    sf.write(dst, np.clip(y, -1, 1).astype(np.float32), sr, subtype="PCM_24")


EXPECT = {"click": "V3", "clip": "V2", "quiet": "V1", "loud": "V1"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=("warn", "required"), default="warn")
    ap.add_argument("--inject", default="none", help="none | click | clip | quiet | loud | all : add injected copies of the first take to the set")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    from earshot import api
    takes = sorted(Path(a.dir).rglob("*.wav"))
    takes = [t for t in takes if "injected" not in t.parts]
    if not takes:
        print("no .wav takes under", a.dir)
        return 2
    inj_dir = out / "injected"
    inj_dir.mkdir(exist_ok=True)
    kinds = list(EXPECT) if a.inject == "all" or a.selftest else ([] if a.inject == "none" else [a.inject])
    injected = []
    for k in kinds:
        d = inj_dir / ("%s__inj_%s.wav" % (takes[0].stem, k))
        inject(str(takes[0]), k, str(d))
        injected.append((k, d))
    rows = []
    for t in takes if not a.selftest else takes[:1]:
        rows.append(check_take(str(t), api))
    inj_rows = []
    for k, d in injected:
        r = check_take(str(d), api)
        r["injected"] = k
        r["expected"] = EXPECT[k]
        r["caught"] = any(f.startswith(EXPECT[k]) for f in r["fails"])
        inj_rows.append(r)
    selftest_ok = all(r["caught"] for r in inj_rows) if a.selftest else None
    # only injected takes asked for with --inject count against the verdict; --selftest ones are asserted instead
    counted = rows + ([] if a.selftest else inj_rows)
    n_fail = sum(1 for r in counted if r["verdict"] == "FAIL")
    res = {"mode": a.mode, "thresholds": TH, "takes": rows, "injected": inj_rows, "selftest_ok": selftest_ok,
           "failed_takes": n_fail, "overall": "FAIL" if n_fail else "PASS"}
    json.dump(res, open(out / "voice_check.json", "w"), indent=1)
    lines = ["| take | s | LUFS | dBTP | clicks | strays | nonspeech | breaths | verdict |", "|---|---|---|---|---|---|---|---|---|"]
    for r in counted + (inj_rows if a.selftest else []):
        lines.append("| %s | %s | %s | %s | %d (max x%s) | %d | %d | %d | %s |" % (
            r["take"], r["duration_s"], r["lufs"], r["true_peak_dbtp"], len(r["clicks"]), r["click_max_ratio"], len(r["strays"]), len(r["nonspeech_events"]),
            len(r["breaths"]), r["verdict"] + ("; " + "; ".join(r["fails"]) if r["fails"] else "")))
    (out / "voice_check.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("CALIBRATION click_max_ratio per clean take:", [r["click_max_ratio"] for r in rows])
    print("CALIBRATION injected:", [(r["injected"], r["caught"], r["fails"]) for r in inj_rows])
    if a.selftest:
        print("SELFTEST", "OK: every injected defect was caught" if selftest_ok else "FAILED: the check missed an injected defect")
        return 0 if selftest_ok else 1
    if n_fail:
        print("::%s::voice take check: %d of %d takes FAIL" % ("error" if a.mode == "required" else "warning", n_fail, len(counted)))
        return 1 if a.mode == "required" else 0
    print("voice take check: all %d takes PASS" % len(counted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
