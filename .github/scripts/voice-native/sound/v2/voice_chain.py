#!/usr/bin/env python3
"""voice_chain.py: the studio voice stage, applied to the voice stem before the mix. Deterministic, parameterised
(audio_rules.json -> voice_chain), free tools only (ffmpeg filters + numpy).

  python3 voice_chain.py <in.wav> <out.wav> [--params '{"presence_db": 5}'] [--check]

Chain (in order):
  1. aresample to 48 kHz
  2. highpass  (hp_hz, 2-pole)                          rumble, plosive thump
  3. de-mud    bell at mud_hz, mud_db (1 octave)         our pilot voices sit +3-4 dB over the benchmark at 500 Hz
  4. presence  bell at presence_hz, presence_db          our voices sit 10-12 dB under the benchmark at 4 kHz
  5. air       high shelf at air_hz, air_db
  6. de-esser  ffmpeg deesser (i, m, f)                 holds the 5-9 kHz peaks the presence lift would raise
  7. compressor ffmpeg acompressor (light: ratio, threshold, knee, attack, release)
  8. sentence leveller (numpy): each speech run's median momentary moves toward the take's speech median, capped at
     +-level_max_db; the gain changes ONLY inside pauses (ramps), so emphasis inside a sentence is untouched
  9. pause expander (numpy): pause interiors (hold after speech, pre-roll before) dip by expander_db with ramps:
     the take's own hiss/room floor between sentences drops; breaths at the edges are kept
 10. static gain to out_lufs, then a true-peak safety limiter (alimiter with latency compensation) to tp_dbtp
Nothing time-stretches or pitch-shifts; --check proves it: same sample count, per-sentence waveform alignment within
1 ms, within-sentence loudness contour r >= 0.9, contrast kept >= 80%, stressed peak kept in >= 85% of sentences.
Laptop-safe: nice'd ffmpeg -threads 2, one process at a time.
"""
import argparse
import json
import math
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audio_core as ac  # noqa: E402

SR = 48000
BLK = 0.05


def params(over=None):
    p = dict(json.load(open(os.path.join(HERE, "audio_rules.json")))["voice_chain"])
    p.pop("_doc", None)
    if over:
        p.update(over)
    return p


def eq_filters(p):
    return ",".join([
        "aresample=%d" % SR,
        "highpass=f=%g:poles=2" % p["hp_hz"],
        "equalizer=f=%g:t=o:w=%g:g=%g" % (p["mud_hz"], p["mud_width_oct"], p["mud_db"]),
        "equalizer=f=%g:t=o:w=%g:g=%g" % (p["presence_hz"], p["presence_width_oct"], p["presence_db"]),
        "highshelf=f=%g:g=%g" % (p["air_hz"], p["air_db"]),
        "deesser=i=%g:m=%g:f=%g:s=o" % (p["deess_i"], p["deess_m"], p["deess_f"]),
        "acompressor=threshold=%gdB:ratio=%g:attack=%g:release=%g:knee=%g:makeup=1" % (
            p["comp_threshold_db"], p["comp_ratio"], p["comp_attack_ms"], p["comp_release_ms"], p["comp_knee_db"]),
    ])


def ff(args):
    ac.run(ac.ff_cmd(args))


def process(src, dst, over=None, keep=False):
    p = params(over)
    tmp = tempfile.mkdtemp(prefix="vchain_")
    try:
        a = os.path.join(tmp, "a.f32")
        # mono in, mono out (the mix upmixes); the filter graph single-threaded for repeatability
        ff(["-i", src, "-vn", "-filter_threads", "1", "-af", eq_filters(p), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-y", a])
        y = np.fromfile(a, dtype=np.float32).astype(np.float64)
        # analysis on the ORIGINAL take (so the leveller/expander follow the delivery, not the processed tone)
        F = ac.Features(src)
        blk = ac.lufs_from_power(F.power())
        speech, _ = ac.voice_activity(blk, min_pause_s=0.25)
        M = F.momentary()
        nb = len(speech)
        g_db = np.zeros(nb)
        # 8. sentence leveller: per speech run, toward the take's speech median; gain moves only in pauses
        runs = [(x0, x1) for x0, x1 in ac.runs_of(speech)]
        meds = [float(np.median(M[x0:x1])) for x0, x1 in runs]
        long_meds = [m for (x0, x1), m in zip(runs, meds) if (x1 - x0) * BLK >= 0.8]
        ref = float(np.median(long_meds)) if long_meds else (float(np.median(meds)) if meds else 0.0)
        target = np.zeros(nb)
        for (x0, x1), m in zip(runs, meds):
            if (x1 - x0) * BLK < 0.4:
                continue          # a lone word keeps its own level (a deliberate dramatic beat)
            target[x0:x1] = float(np.clip(ref - m, -p["level_max_db"], p["level_max_db"]))
        # fill pauses by ramping between neighbouring runs' gains inside the pause only
        lev = target.copy()
        idx = np.where(speech)[0]
        if len(idx):
            lev[:idx[0]] = target[idx[0]]
            lev[idx[-1]:] = target[idx[-1]]
            for x0, x1 in ac.runs_of(~speech):
                if x0 == 0 or x1 >= nb:
                    continue
                lev[x0:x1] = np.linspace(target[x0 - 1], target[x1], x1 - x0 + 2)[1:-1]
        g_db += lev
        # 9. pause expander: interiors of pauses only (hold after speech, pre-roll before the next word)
        hold, pre = int(p["expander_hold_ms"] / 1000 / BLK), int(p["expander_preroll_ms"] / 1000 / BLK)
        exp_ = np.zeros(nb)
        for x0, x1 in ac.runs_of(~speech):
            a0, a1 = x0 + hold, x1 - pre
            if a1 - a0 >= 2:
                ramp = max(1, int(p["expander_ramp_ms"] / 1000 / BLK))
                seg = np.full(a1 - a0, p["expander_db"])
                r = min(ramp, (a1 - a0) // 2)
                if r:
                    seg[:r] = np.linspace(0, p["expander_db"], r + 1)[1:]
                    seg[-r:] = np.linspace(p["expander_db"], 0, r + 1)[:-1]
                exp_[a0:a1] = seg
        g_db += exp_
        t_blk = (np.arange(nb) + 0.5) * BLK
        t = np.arange(len(y)) / SR
        y *= 10 ** (np.interp(t, t_blk, g_db) / 20)
        b = os.path.join(tmp, "b.f32")
        y.astype(np.float32).tofile(b)
        # 10. static gain to out_lufs, then the true-peak limiter
        wav = os.path.join(tmp, "b.wav")
        ff(["-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", b, "-c:a", "pcm_f32le", "-y", wav])
        I = ac.ffmpeg_ebur128(wav)["integrated_lufs"]
        gain = p["out_lufs"] - I
        lim = "alimiter=level_in=1:level_out=1:limit=%.6f:attack=3:release=50:asc=1:level=0:latency=1" % (10 ** ((p["tp_dbtp"] - 0.5) / 20))
        ff(["-i", wav, "-filter_threads", "1", "-af", "volume=%.4fdB,%s" % (gain, lim), "-c:a", "pcm_s24le", "-y", dst])
        return {"params": p, "leveller_db": {"min": round(float(lev.min()), 2), "max": round(float(lev.max()), 2)},
                "expander_db": p["expander_db"], "static_gain_db": round(gain, 2)}
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def delivery_check(src, dst):
    """Timing and emphasis must not change.
    timing:   same sample count; per sentence, the lag that best aligns the input and output speech envelopes
              (waveform cross-correlation, sample resolution, +-10 ms search) must be within 1 ms everywhere
    emphasis: within each sentence (speech run >= 0.8 s) the 50 ms loudness contour correlates with the input
              (median r >= 0.9) and keeps its contrast (std out / std in >= 0.8), and the loudest unit of the
              sentence is still within 1 dB of its loudest (stress preserved in >= 85% of sentences)"""
    a = ac.read_pcm(src, sr=SR, channels=1)[:, 0]
    b = ac.read_pcm(dst, sr=SR, channels=1)[:, 0]
    same_len = abs(len(a) - len(b)) <= 1
    n = min(len(a), len(b))
    h = SR // 200                       # 5 ms envelope
    m5 = n // h
    ea = np.sqrt(np.mean(a[:m5 * h].reshape(m5, h) ** 2, axis=1))
    eb = np.sqrt(np.mean(b[:m5 * h].reshape(m5, h) ** 2, axis=1))
    la_ = 20 * np.log10(ea + 1e-9); lb_ = 20 * np.log10(eb + 1e-9)
    Fa, Fb = ac.Features(src), ac.Features(dst)
    spa, _ = ac.voice_activity(ac.lufs_from_power(Fa.power()), min_pause_s=0.25)
    runs = [(x0, x1) for x0, x1 in ac.runs_of(spa) if (x1 - x0) * BLK >= 0.8]
    lags, rs, contrast, stress = [], [], [], []
    fa, fb = Fa.fast(), Fb.fast()
    W = int(0.010 * SR)                 # +-10 ms search, sample resolution, on the waveform (FFT correlation)
    for x0, x1 in runs:
        s0, s1 = int(x0 * BLK * SR), min(int(x1 * BLK * SR), n)
        u, v = a[s0:s1], b[s0:s1]
        L = len(u) + len(v)
        cc = np.fft.irfft(np.fft.rfft(v, L) * np.conj(np.fft.rfft(u, L)), L)
        cand = np.r_[cc[:W + 1], cc[-W:]]
        lg = int(np.argmax(cand))
        lg = lg if lg <= W else lg - len(cand)
        lags.append(round(1000.0 * lg / SR, 3))
        u2, v2 = fa[x0:x1] - np.median(fa[x0:x1]), fb[x0:x1] - np.median(fb[x0:x1])
        if np.std(u2) > 0 and np.std(v2) > 0:
            rs.append(float(np.corrcoef(u2, v2)[0, 1]))
            contrast.append(float(np.std(v2) / np.std(u2)))
        # the input's most stressed moment is still (within 1 dB) the loudest moment of the sentence in the output
        ia = int(np.argmax(fa[x0:x1]))
        stress.append(float(fb[x0:x1].max() - fb[x0 + ia]) <= 1.0)   # EQ tilt shifts bright vs dark syllables slightly
    r_med = float(np.median(rs)) if rs else None
    c_med = float(np.median(contrast)) if contrast else None
    st = float(np.mean(stress)) if stress else None
    ok = (same_len and lags and max(abs(x) for x in lags) <= 1.0 and r_med is not None and r_med >= 0.9
          and c_med >= 0.8 and st >= 0.85)
    return {"same_length": same_len, "samples_in": len(a), "samples_out": len(b), "sentences": len(runs),
            "sentence_lag_ms_max_abs": max(abs(x) for x in lags) if lags else None,
            "emphasis_contour_r_median": round(r_med, 3) if r_med is not None else None,
            "emphasis_contrast_ratio_median": round(c_med, 3) if c_med is not None else None,
            "stressed_peak_kept_fraction": round(st, 3) if st is not None else None,
            "delivery_unchanged": bool(ok)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--params")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    info = process(a.src, a.dst, json.loads(a.params) if a.params else None)
    if a.check:
        info["delivery"] = delivery_check(a.src, a.dst)
    print(json.dumps(info, indent=1))
    sys.exit(0 if (not a.check or info["delivery"]["delivery_unchanged"]) else 1)
