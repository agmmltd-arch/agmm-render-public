#!/usr/bin/env python3
"""Terminal pitch lift per paragraph, measured with Praat (parselmouth). Run with ~/alfred/venvs/pitch/bin/python (a separate venv:
the yt-engine venv has no pitch tracker and must not be changed). root 6 Oct 2026, voice-perf card.

  voice_pitch.py <wav> '<json [[para, start_s, end_s], ...]>'   ->   JSON {para: {...}} on stdout

Per paragraph (voiced frames from Praat's autocorrelation tracker, 10 ms hop, 70-330 Hz, octave-jump frames removed):
  last_minus_med    last voiced frame minus the paragraph's median pitch, in semitones   (the lift the listener hears on the last word)
  final_slope_st_s  least-squares slope of the final 0.2 s of voiced contour, semitones per second
  final_minus_pre   median of the last 0.25 s minus the median of the 0.55 s before it
  final_max_minus_med  highest point of the last 0.25 s above the median
What it showed (report fix-voice-perf.md): Sam's S02 old CTA "Follow, we track this every week." has last_minus_med +6.8 st and slope
+71 st/s, ranking first of 43 CTA-length takes (next 4.4 / +43); its replacement is -7.6 / -59. Only ONE take is confirmed bad by Sam,
the other 11 old-CTA takes are unconfirmed, so this is a WARN signal, never a FAIL.
"""
import json, sys
import numpy as np
import parselmouth


def feats(snd):
    p = snd.to_pitch_ac(time_step=0.01, pitch_floor=70, pitch_ceiling=330, very_accurate=True, silence_threshold=0.03, voicing_threshold=0.5)
    f = np.where(p.selected_array["frequency"] > 0, p.selected_array["frequency"], np.nan)
    v = 12 * np.log2(f / 100.0)
    idx = np.where(np.isfinite(v))[0]
    if len(idx) < 20:
        return None
    v2 = v.copy()
    for i in idx:
        w = v[max(0, i - 5): i + 6]; w = w[np.isfinite(w)]
        if len(w) >= 4 and abs(v[i] - np.median(w)) > 5:
            v2[i] = np.nan
    v = v2; ok = np.isfinite(v); idx = np.where(ok)[0]
    if len(idx) < 20:
        return None
    last = idx[-1]; med = np.nanmedian(v)
    fin = v[max(0, last - 25): last + 1]; fin = fin[np.isfinite(fin)]
    pre = v[max(0, last - 80): max(0, last - 25)]; pre = pre[np.isfinite(pre)]
    seg = np.arange(max(0, last - 20), last + 1); sv = v[seg]; m = np.isfinite(sv)
    slope = float(np.polyfit(seg[m] * 0.01, sv[m], 1)[0]) if m.sum() >= 6 else None
    return {"median_hz": round(float(100 * 2 ** (med / 12)), 1), "last_minus_med": round(float(v[last] - med), 2),
            "final_slope_st_s": None if slope is None else round(slope, 1),
            "final_minus_pre": round(float(np.median(fin) - np.median(pre)), 2) if len(fin) > 3 and len(pre) > 5 else None,
            "final_max_minus_med": round(float(fin.max() - med), 2) if len(fin) else None, "voiced_frames": int(ok.sum())}


def main():
    snd = parselmouth.Sound(sys.argv[1])
    out = {}
    for para, t0, t1 in json.loads(sys.argv[2]):
        part = snd.extract_part(from_time=max(0.0, t0 - 0.05), to_time=min(snd.xmax, t1 + 0.10), preserve_times=False)
        out[para] = feats(part)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
