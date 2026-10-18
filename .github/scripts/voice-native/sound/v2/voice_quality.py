#!/usr/bin/env python3
"""voice_quality.py: measurable studio-voice checks on a voice-only track (Sam, 24 Sep: "the voice needs to sound
studio quality along with its great deliverability").

  python3 voice_quality.py <voice.wav> [--json out.json]
  python3 voice_quality.py --target <benchmark masters...>      (derive the spectral target curve, see below)

Measures (thresholds in audio_rules.json -> report.rules.VOICE_*):
  noise floor      speech level (median momentary while speaking) minus the level in the interior of pauses (dB)
  sibilance        p99 of the 5-9 kHz band (50 ms blocks) relative to the 1-4 kHz band's p99 while speaking (dB)
  spectral balance long-term average spectrum while speaking in octave bands 125 Hz-8 kHz, normalised to 1 kHz,
                   against the target curve; worst band deviation (dB)
  consistency      spread of the per-sentence (speech run >= 0.8 s) median momentary loudness: p90 - p10 (LU),
                   and short-term (3 s) p90 - p10 while speaking
  clipping         runs of >= 3 samples at full scale (native rate)
The target curve is not invented: it is the median speech-time octave LTAS of the three 0x100x benchmark reels
(mid channel while their voice speaks, music ducked ~10 LU under), stored in audio_rules.json with how it was made.
Laptop-safe: one nice'd ffmpeg decode per file.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audio_core as ac  # noqa: E402

OCT = [125, 250, 500, 1000, 2000, 4000, 8000]
SR = 24000


def octave_ltas(x, mask_blocks):
    """x mono float at SR; mask per 50 ms block. Returns dB per octave band normalised to the 1 kHz band."""
    hop = int(SR * ac.HOP_S)
    n = min(len(x) // hop, len(mask_blocks))
    f = np.fft.rfftfreq(4096, 1.0 / SR)
    acc = np.zeros(len(f))
    w = np.hanning(hop)
    cnt = 0
    for i in np.where(mask_blocks[:n])[0]:
        seg = x[i * hop:(i + 1) * hop]
        acc += np.abs(np.fft.rfft(seg * w, n=4096)) ** 2
        cnt += 1
    if not cnt:
        return None
    acc /= cnt
    out = {}
    for fc in OCT:
        b = (f >= fc / math.sqrt(2)) & (f < fc * math.sqrt(2))
        out[fc] = 10 * math.log10(acc[b].sum() + 1e-20)
    ref = out[1000]
    return {str(k): round(v - ref, 2) for k, v in out.items()}


def band_levels(x, lo, hi):
    hop = int(SR * ac.HOP_S)
    n = len(x) // hop
    f = np.fft.rfftfreq(2048, 1.0 / SR)
    b = (f >= lo) & (f <= hi)
    w = np.hanning(hop)
    out = np.empty(n)
    for i in range(n):
        s = np.abs(np.fft.rfft(x[i * hop:(i + 1) * hop] * w, n=2048)) ** 2
        out[i] = 10 * math.log10(s[b].sum() + 1e-20)
    return out


def measure(path, target=None):
    F = ac.Features(path)
    x = ac.read_pcm(path, sr=SR, channels=1)[:, 0]
    blk = ac.lufs_from_power(F.power())
    speech, thr = ac.voice_activity(blk, min_pause_s=0.25)
    pauses = ac.pauses_from_mask(speech, 0.25)
    M = F.momentary()
    inn = speech.copy()
    for s in (1, 2, 3, 4):
        inn[:-s] &= speech[s:]
        inn[s:] &= speech[:-s]
    if not inn.any():
        inn = speech
    speak = float(np.median(M[inn])) if inn.any() else None
    # noise floor: interior of pauses (0.1 s in from each edge), 50 ms block level (K-weighted)
    pv = []
    for a, b in pauses:
        i0, i1 = int((a + 0.1) / ac.HOP_S), int((b - 0.1) / ac.HOP_S)
        if i1 > i0:
            pv.extend(blk[i0:i1].tolist())
    floor = float(np.median(pv)) if pv else None
    floor_p90 = float(np.percentile(pv, 90)) if pv else None
    # sibilance: 5-9 kHz band p99 vs 1-4 kHz band p99 while speaking
    s59 = band_levels(x, 5000, 9000)
    s14 = band_levels(x, 1000, 4000)
    n = min(len(s59), len(speech))
    sp = speech[:n]
    sib = float(np.percentile(s59[:n][sp], 99) - np.percentile(s14[:n][sp], 99)) if sp.any() else None
    sib_med = float(np.median(s59[:n][sp] - s14[:n][sp])) if sp.any() else None
    ltas = octave_ltas(x, speech)
    dev = None
    if target and ltas:
        dev = {k: round(ltas[k] - target["curve"][k], 2) for k in ltas if k in target["curve"]}
    runs = [(a, b) for a, b in ac.runs_of(speech) if (b - a) * ac.HOP_S >= 0.8]
    run_meds = [float(np.median(M[a:b])) for a, b in runs]
    ST = F.short_term()
    st_in = ST[inn] if inn.any() else ST
    clip = ac.clipping_runs(path)
    return {"path": os.path.abspath(path), "speech_level_lufs": round(speak, 2) if speak is not None else None,
            "pauses": len(pauses),
            "noise_floor_lufs": round(floor, 2) if floor is not None else None,
            "noise_floor_under_speech_db": round(speak - floor, 2) if (speak is not None and floor is not None) else None,
            "noise_floor_p90_under_speech_db": round(speak - floor_p90, 2) if (speak is not None and floor_p90 is not None) else None,
            "sibilance_p99_db": round(sib, 2) if sib is not None else None,
            "sibilance_median_db": round(sib_med, 2) if sib_med is not None else None,
            "ltas_octave_re_1k_db": ltas, "ltas_dev_from_target_db": dev,
            "ltas_worst_dev_db": round(max(abs(v) for v in dev.values()), 2) if dev else None,
            "sentence_spread_lu": round(float(np.percentile(run_meds, 90) - np.percentile(run_meds, 10)), 2) if len(run_meds) >= 3 else None,
            "short_term_spread_lu": round(float(np.percentile(st_in, 90) - np.percentile(st_in, 10)), 2),
            "sentences": len(run_meds), "clipped_runs": clip["clipped_runs"], "sample_peak_dbfs": clip["sample_peak_dbfs"],
            "true_peak_dbtp": ac.ffmpeg_ebur128(path)["true_peak_dbtp"]}


def verdict(m, rules):
    """PASS/FAIL per studio-voice rule, with the SAME thresholds audio_report.py applies
    (audio_rules.json report.rules: VOICE_NOISE_FLOOR, VOICE_SIBILANCE, VOICE_BALANCE, VOICE_CONSISTENCY, VOICE_CLIPPING).
    True peak is not judged on a stem (the master's TRUE_PEAK rule owns it)."""
    dev = m.get("ltas_dev_from_target_db") or {}
    judged = {k: v for k, v in dev.items() if int(k) in rules["VOICE_BALANCE"]["bands"]}
    worst = max((abs(v) for v in judged.values()), default=None)
    subs = {"noise_floor": (m["noise_floor_under_speech_db"], ">=", rules["VOICE_NOISE_FLOOR"]["min_under_speech_db"]),
            "sibilance": (m["sibilance_p99_db"], "<=", rules["VOICE_SIBILANCE"]["max_db"]),
            "balance": (worst, "<=", rules["VOICE_BALANCE"]["max_dev_db"]),
            "consistency": (m["sentence_spread_lu"], "<=", rules["VOICE_CONSISTENCY"]["max_sentence_spread_lu"]),
            "clipping": (m["clipped_runs"], "<=", rules["VOICE_CLIPPING"]["max_runs"])}
    out = {}
    for k, (v, op, th) in subs.items():
        ok = v is None or (v >= th if op == ">=" else v <= th)
        out[k] = {"value": v, "threshold": "%s %s" % (op, th), "pass": bool(ok)}
    return out


def derive_target(masters):
    """Median octave LTAS (re 1 kHz) of benchmark masters while their voice speaks (mid channel, master-only VAD
    from the mid/side split as in audio_report.py)."""
    curves = []
    for m in masters:
        F = ac.Features(m)
        km, ks = F.km, F.ks
        live = F.fast() > -50
        pz = (ks > 1e-12) & live
        k = float(np.percentile(km[pz] / ks[pz], 10))
        vp = np.maximum(2.0 * (km - k * ks), 1e-14)
        vl = ac.lufs_from_power(vp)
        sp, _ = ac.voice_activity(vl, rel_db=20.0)
        st = ac.read_pcm(m, sr=SR, channels=2)
        mid = st.mean(axis=1)
        c = octave_ltas(mid, sp)
        curves.append(c)
        print(os.path.basename(m), c)
    med = {str(fc): round(float(np.median([c[str(fc)] for c in curves])), 2) for fc in OCT}
    spread = {str(fc): round(float(max(c[str(fc)] for c in curves) - min(c[str(fc)] for c in curves)), 2) for fc in OCT}
    return {"curve": med, "benchmark_spread_db": spread, "sources": [os.path.basename(m) for m in masters],
            "method": "median octave LTAS re 1 kHz of the mid channel while the voice speaks (mid/side VAD); music under "
                      "the voice contaminates the low bands, so 125 Hz carries a wider tolerance"}


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--target":
        print(json.dumps(derive_target(a[1:]), indent=1))
        sys.exit(0)
    rules = json.load(open(os.path.join(HERE, "audio_rules.json")))
    tgt = rules.get("voice_target")
    r = measure(a[0], tgt)
    r["verdict"] = verdict(r, rules["report"]["rules"])
    r["status"] = "PASS" if all(v["pass"] for v in r["verdict"].values()) else "FAIL"
    if "--json" in a:
        json.dump(r, open(a[a.index("--json") + 1], "w"), indent=1)
    print(json.dumps(r, indent=1))
    sys.exit(0 if r["status"] == "PASS" else 1)
