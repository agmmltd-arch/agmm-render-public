#!/usr/bin/env python3
"""audio_report.py: the audio report card (AUDIO DESIGN SYSTEM v2). A hard FAIL blocks release (exit 1).

  python3 audio_report.py <video|master.wav> [--stems DIR] [--voice V.wav] [--words words.json] [--spec mix_spec.json]
                          [--music-gain music_gain.json] [--out DIR] [--kind short|long] [--no-gemini] [--label X]

Measures, with numbers and timestamps, and judges each rule in audio_rules.json (one config file):
  * integrated / LRA / true peak (ffmpeg ebur128) and momentary / short-term series per stem and for the mix
  * voice-to-music ratio over time (PNG) and per speech run (MUSIC_UNDER_SPEECH)
  * every voice pause: music rise in dB and the bed's level vs the voice (GAP_RISE, GAP_UNDER_VOICE, SWELL_CAP),
    noise floor and 2-10 kHz spectral flatness in the pause (NOISE_IN_PAUSES), plus the programme noise floor
    (NOISE_FLOOR): hiss / rain / room tone
  * SFX count per minute, SFX peaks vs the voice peak, any SFX within 150 ms of a stressed word (SFX_*)
  * ambience level, coverage, band-limit (AMBIENCE_*); clipping, true peak, silence gaps
  * a Gemini listening pass on the voice stem and on the full mix separately, 2 passes each averaged (qa/gate.py)

Evidence basis, stated on every rule:
  stems        --stems DIR with voice.wav + music.wav (+ sfx.wav, ambience.wav), master-referred and aligned, as
               written by mix2.py (or legacy_stems.py for old mix.py mixes). Exact. Release decisions need this.
  voice-ref    master + --voice (or --words): pauses exact; music estimated from the stereo side channel.
  master-only  pauses and music both estimated from mid/side (voice is centred, beds are stereo). For benchmarks.
Laptop-safe: nice'd ffmpeg, -threads 2, one process at a time, streamed decodes.
"""
import argparse
import datetime
import json
import math
import os
import re
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audio_core as ac  # noqa: E402

V2 = os.path.dirname(os.path.dirname(HERE))
GEMINI_WATCH = os.path.join(V2, "tooling", "gemini_watch.py")
RULES_PATH = os.path.join(HERE, "audio_rules.json")
B = ac.HOP_S
REUSE_GEMINI = False


def pdb(p):
    return ac.lufs_from_power(p)


def fmt_t(t):
    return "%d:%05.2f" % (int(t // 60), t - 60 * int(t // 60))


class Rule:
    def __init__(self, rid, cfg):
        self.id, self.cfg = rid, cfg
        self.severity = cfg.get("severity", "hard")
        self.status, self.value, self.threshold, self.summary, self.basis, self.details = "NA", None, None, "", "", []

    def set(self, ok, value, threshold, summary, basis, details=None, na=False):
        self.status = "NA" if na else ("PASS" if ok else ("FAIL" if self.severity == "hard" else "WARN"))
        self.value, self.threshold, self.summary, self.basis = value, threshold, summary, basis
        self.details = details or []
        return self

    def as_dict(self):
        return {"id": self.id, "status": self.status, "severity": self.severity, "basis": self.basis,
                "value": self.value, "threshold": self.threshold, "summary": self.summary, "why": self.cfg.get("why", ""),
                "details": self.details}


def load_words(path):
    j = json.load(open(path))
    ws = j["words"] if isinstance(j, dict) and "words" in j else j
    out = []
    for w in ws:
        s = w.get("start", w.get("t0", w.get("s")))
        e = w.get("end", w.get("t1", w.get("e")))
        if s is None or e is None:
            continue
        out.append({"start": float(s), "end": float(e), "word": w.get("word", w.get("text", "")),
                    "emph": bool(w.get("emph") or w.get("stress"))})
    return out


def fit(x, n, fill=0.0):
    x = np.asarray(x)
    if len(x) >= n:
        return x[:n]
    pad = np.full((n - len(x),) + x.shape[1:], fill, dtype=x.dtype if x.dtype != bool else bool)
    return np.concatenate([x, pad])


def interior(mask, k=3):
    """Blocks inside speech with k blocks of speech on both sides (so 400 ms windows do not straddle a pause)."""
    m = np.asarray(mask, bool)
    out = m.copy()
    for s in range(1, k + 1):
        out[:-s] &= m[s:]
        out[s:] &= m[:-s]
    return out


def detrended_flatness(rows):
    """Flatness of the Welch spectrum after dividing out its own smoothed shape: ~1 for any smooth (noise-like)
    spectrum whatever its colour, low for tonal/harmonic content (music notes, voice harmonics)."""
    if len(rows) == 0:
        return None
    s = np.mean(np.asarray(rows, dtype=np.float64), axis=0) + 1e-20
    k = 9
    sm = np.convolve(np.pad(s, (k, k), mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="same")[k:-k]
    r = s / sm
    return float(np.exp(np.mean(np.log(r))) / np.mean(r))


# ---------------------------------------------------------------------------------------------------------------
GEM_VOICE = """You are auditing the VOICE-ONLY stem of a video narration (there is no music and there are no sound
effects on this track; if you hear any, report it as a problem). Listen to all of it, then return ONLY JSON:
{"scores": {"clarity": <1-10>, "naturalness": <1-10>, "warmth": <1-10>, "presence": <1-10>,
            "artefacts": <1-10, 10 = none: no metallic, robotic, phasey, lisping, room or hiss artefacts>,
            "pacing": <1-10>, "pronunciation": <1-10>},
 "problems": [{"timestamp": "<m:ss>", "issue": "<what exactly>", "severity": "low|medium|high"}],
 "annoying": ["<anything a listener would find annoying>"],
 "notes": "<2-3 sentences, direct>"}
Clarity = every word intelligible. Naturalness = sounds like a person speaking with real intonation, not a flat or
choppy synthetic read. Report clicks, cut-off word endings, doubled words, odd breaths, hiss or room noise with
timestamps. Score honestly: 5 means mediocre and unfinished, not a passing grade."""

GEM_MIX = """You are a broadcast sound mixer auditing the FULL MIX of a short video (narration, a music bed and
sound effects). Judge ONLY the sound; ignore the picture (it is black). Listen to all of it, then return ONLY JSON:
{"scores": {"voice_clarity": <1-10>, "music_fit": <1-10>, "music_in_pauses": <1-10>, "sfx_fit": <1-10>,
            "noise_free": <1-10>, "overall_mix": <1-10>},
 "problems": [{"timestamp": "<m:ss>", "issue": "<what exactly>", "severity": "low|medium|high"}],
 "annoying": ["<anything a viewer would find annoying>"],
 "sfx_count_estimate": <integer number of distinct sound effects you heard>,
 "notes": "<2-3 sentences, direct>"}
music_in_pauses: 10 = the music stays steady under the voice and never jumps up in the gaps between lines;
1 = it surges up in every pause. sfx_fit: 10 = every effect lands on a moment and never covers a word.
noise_free: 10 = no hiss, rain, static, crackle, room tone or white-noise bed anywhere; 1 = a constant noise bed.
Score honestly: 5 means mediocre and unfinished, not a passing grade."""


def gemini_pass(audio_path, prompt, out_dir, tag, model, passes):
    """2 passes averaged, like qa/gate.py check 9. Audio is wrapped in a tiny black-frame MP4 (gemini_watch.py sends
    video/mp4). Hallucination guard: skipped when the audio is below -50 LUFS."""
    prev = os.path.join(out_dir, "gemini_%s.json" % tag)
    if REUSE_GEMINI and os.path.exists(prev):
        old = json.load(open(prev))
        if old.get("averaged_scores"):
            old["reused"] = True
            return old
    if audio_path.startswith("http"):
        mp4 = audio_path          # a YouTube URL: Gemini fetches it itself (used for benchmarks we cannot download)
    else:
        lufs = ac.ffmpeg_ebur128(audio_path)["integrated_lufs"]
        if lufs is None or lufs <= -50:
            return {"skipped": "audio below -50 LUFS (critic hallucination guard)", "lufs": lufs}
        dur = ac.probe(audio_path)["duration"]
        mp4 = os.path.join(out_dir, "gemini_%s.mp4" % tag)
        abr = "96k" if dur <= 600 else "48k"
        ac.run(ac.ff_cmd(["-f", "lavfi", "-i", "color=c=black:s=128x128:r=2", "-i", audio_path, "-map", "0:v", "-map", "1:a",
                          "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", "-crf", "40",
                          "-c:a", "aac", "-b:a", abr, "-y", mp4]))
    runs, errs = [], []
    for i in range(passes):
        raw = os.path.join(out_dir, "gemini_%s_run%d.json" % (tag, i + 1))
        p = subprocess.run(["python3", GEMINI_WATCH, mp4, prompt, "--json", "--model", model, "--out", raw],
                           capture_output=True, text=True)
        if p.returncode != 0:
            errs.append(p.stderr[-300:])
            continue
        txt = re.sub(r"^```json\s*|\s*```$", "", p.stdout.strip(), flags=re.I | re.M)
        try:
            runs.append(json.loads(txt))
        except json.JSONDecodeError as e:
            errs.append("bad JSON: %s" % e)
    if not runs:
        return {"error": "; ".join(errs) or "no run"}
    keys = set().union(*[set((r.get("scores") or {}).keys()) for r in runs])
    avg = {}
    for k in sorted(keys):
        vals = [r["scores"][k] for r in runs if isinstance((r.get("scores") or {}).get(k), (int, float))]
        if vals:
            avg[k] = round(sum(vals) / len(vals), 2)
    res = {"model": model, "passes": len(runs), "averaged_scores": avg,
           "per_pass": [r.get("scores") for r in runs],
           "problems": sum([r.get("problems", []) or [] for r in runs], []),
           "annoying": sum([r.get("annoying", []) or [] for r in runs], []),
           "notes": [r.get("notes") for r in runs if r.get("notes")], "errors": errs}
    se = [r.get("sfx_count_estimate") for r in runs if isinstance(r.get("sfx_count_estimate"), (int, float))]
    if se:
        res["sfx_count_estimate"] = round(sum(se) / len(se), 1)
    json.dump(res, open(os.path.join(out_dir, "gemini_%s.json" % tag), "w"), indent=1)
    if not mp4.startswith("http"):
        try:
            os.remove(mp4)
        except OSError:
            pass
    return res


# ---------------------------------------------------------------------------------------------------------------
def analyse(a):
    cfg = json.load(open(RULES_PATH))
    rc = cfg["report"]
    R = {k: Rule(k, v) for k, v in rc["rules"].items()}
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.input)), "audio-report")
    os.makedirs(out, exist_ok=True)
    spec = json.load(open(a.spec)) if a.spec else {}
    res = {"input": os.path.abspath(a.input), "label": a.label or os.path.basename(a.input),
           "generated": datetime.datetime.now().isoformat(timespec="seconds"), "rules_version": cfg["version"],
           "rules_sha256": ac.sha256(RULES_PATH)}
    pr = ac.probe(a.input)
    if not pr["has_audio"]:
        sys.exit("no audio stream in %s" % a.input)
    dur = pr["duration"]
    kind = a.kind or ("short" if dur <= rc["short_max_s"] else "long")
    res["duration_s"], res["kind"] = round(dur, 3), kind

    # ---- master ---------------------------------------------------------------------------------------------
    M = ac.Features(a.input, "mix")
    n = M.n
    t = M.t
    ebu = ac.ffmpeg_ebur128(a.input)
    clip = ac.clipping_runs(a.input)
    mM, mF, mS = M.momentary(), M.fast(), M.short_term()
    loud = {"mix": {"integrated_lufs": ebu["integrated_lufs"], "lra_lu": ebu["lra_lu"], "true_peak_dbtp": ebu["true_peak_dbtp"],
                    "momentary_max_lufs": round(float(mM.max()), 2), "short_term_max_lufs": round(float(mS.max()), 2),
                    "sample_peak_dbfs": clip["sample_peak_dbfs"]}}

    # ---- stems ------------------------------------------------------------------------------------------------
    stems = {}
    if a.stems:
        for k in ("voice", "music", "sfx", "ambience"):
            p = os.path.join(a.stems, k + ".wav")
            if os.path.exists(p):
                stems[k] = ac.Features(p, k)
        if "voice" not in stems:
            sys.exit("--stems %s has no voice.wav" % a.stems)
    for k, f in stems.items():
        e = ac.ffmpeg_ebur128(f.path)
        loud[k] = {"integrated_lufs": e["integrated_lufs"], "lra_lu": e["lra_lu"], "true_peak_dbtp": e["true_peak_dbtp"],
                   "momentary_max_lufs": round(float(f.momentary().max()), 2),
                   "short_term_max_lufs": round(float(f.short_term().max()), 2)}
    res["loudness"] = loud
    Pz = lambda f: fit(f.power(), n)
    mg_path = a.music_gain or (os.path.join(os.path.dirname(os.path.normpath(a.stems)), "music_gain.json") if a.stems else None)
    music_gain = None
    if mg_path and os.path.exists(mg_path):
        mgj = json.load(open(mg_path))
        key_ = "gap_rule_db" if "gap_rule_db" in mgj else "total_db"
        res["music_gain_curve"] = {"path": os.path.abspath(mg_path), "series": key_}
        music_gain = fit(np.array([np.nan if x is None else x for x in mgj[key_]], dtype=float), n, fill=np.nan)

    # ---- speech / pauses ------------------------------------------------------------------------------------------
    words = load_words(a.words) if a.words else (load_words(spec["words"]) if spec.get("words") and os.path.exists(spec["words"]) else None)
    side_ok = False
    km, ks = fit(M.km, n), fit(M.ks, n)
    live = mF > -50
    if live.any():
        side_ok = float(np.median(ks[live] / np.maximum(km[live], 1e-14))) > 10 ** (-30 / 10)
    # voice activity from the raw 50 ms block level (a 200 ms window would smear 0.3 s pauses away)
    if "voice" in stems:
        basis = "stems"
        vblk = pdb(fit(stems["voice"].power(), n, 0.0))
        speech, thr = ac.voice_activity(vblk, min_pause_s=rc["min_pause_s"])
    elif a.voice:
        basis = "voice-ref"
        VF = ac.Features(a.voice, "voice-ref")
        vblk = pdb(fit(VF.power(), n, 0.0))
        speech, thr = ac.voice_activity(vblk, min_pause_s=rc["min_pause_s"])
    elif words:
        basis = "words"
        speech = np.zeros(n, bool)
        for w in words:
            speech[int(w["start"] / B):int(math.ceil(w["end"] / B))] = True
        for x0, x1 in ac.runs_of(~speech):
            if 0 < x0 and x1 < n and (x1 - x0) * B < rc["min_pause_s"]:
                speech[x0:x1] = True
        thr = None
    else:
        basis = "master-only"
        thr = None
        speech = np.zeros(n, bool)
    # music estimate from the side channel (used whenever there is no music stem)
    kk = None
    if side_ok:
        if basis in ("voice-ref", "words"):
            pz = (~speech) & (ks > 1e-12) & live
            kk = float(np.median(km[pz] / ks[pz])) if pz.sum() > 10 else None
        if kk is None:
            pz = (ks > 1e-12) & live
            kk = float(np.percentile(km[pz] / ks[pz], 10)) if pz.sum() > 10 else None
    if basis == "master-only":
        if kk is not None:
            vp = np.maximum(2.0 * (km - kk * ks), 1e-14)
            c = np.concatenate([[0.0], np.cumsum(vp)])
            i = np.arange(n)
            lo, hi = np.clip(i - 2, 0, n), np.clip(i + 2, 0, n)
            vlev = pdb((c[hi] - c[lo]) / np.maximum(hi - lo, 1))
            speech, thr = ac.voice_activity(vlev, rel_db=20.0, min_pause_s=rc["min_pause_s"])
        else:
            speech = None
    # a words file on the wrong clock would put every stress check in the wrong place: require >= 80% of word
    # midpoints inside detected speech, else ignore it (and say so)
    if words and speech is not None and basis != "words":
        mids = [int(((w["start"] + w["end"]) / 2) / B) for w in words]
        inside = float(np.mean([speech[min(max(i, 0), n - 1)] for i in mids])) if mids else 0.0
        res["words_alignment"] = round(inside, 3)
        if inside < 0.8:
            res["words_ignored"] = "only %.0f%% of word midpoints fall inside detected speech: wrong clock?" % (100 * inside)
            words = None
    res["evidence_basis"] = basis
    res["side_channel"] = {"usable": side_ok, "k_mid_over_side": round(kk, 3) if kk else None}
    if speech is not None:
        speech = fit(speech, n, False)
    pauses = ac.pauses_from_mask(speech, rc["min_pause_s"]) if speech is not None else []
    res["speech_fraction"] = round(float(speech.mean()), 3) if speech is not None else None

    # ---- level tracks --------------------------------------------------------------------------------------------
    if "voice" in stems:
        V = stems["voice"]
        vM = fit(V.momentary(), n, -120.0)
        vF = fit(V.fast(), n, -120.0)
    elif speech is not None:
        vM, vF = mM, mF   # voice-dominated during speech
    else:
        vM = vF = None
    if "music" in stems:
        mu = stems["music"]
        muM, muF = fit(mu.momentary(), n, -120.0), fit(mu.fast(), n, -120.0)
        mus_basis = "stems"
    elif kk is not None:
        mp = 2.0 * (kk + 1.0) * ks
        tmp = ac.Features.__new__(ac.Features)
        muM = pdb(ac.Features.windowed(tmp, 8, mp))
        muF = pdb(ac.Features.windowed(tmp, 4, mp))
        mus_basis = "side-channel estimate"
    else:
        muM = muF = None
        mus_basis = "unavailable (mono mix)"
    bedF = None
    if stems:
        p = np.zeros(n)
        for k in ("music", "sfx", "ambience"):
            if k in stems:
                p = p + ac.Features.windowed(stems[k], 4, Pz(stems[k]))
        bedF = pdb(p)

    # ---- STEM_INTEGRITY --------------------------------------------------------------------------------------------
    if stems:
        psum = np.zeros(n)
        for k, f in stems.items():
            psum = psum + ac.Features.windowed(f, 4, Pz(f))
        dev = mF - pdb(psum)
        m_ = mF > -45
        med = float(np.median(np.abs(dev[m_]))) if m_.any() else 99
        R["STEM_INTEGRITY"].set(med <= R["STEM_INTEGRITY"].cfg["max_median_dev_db"], round(med, 2),
                                R["STEM_INTEGRITY"].cfg["max_median_dev_db"],
                                "stems' power sum vs the master: median |deviation| %.2f dB (p95 %.2f dB)" % (
                                    med, float(np.percentile(np.abs(dev[m_]), 95)) if m_.any() else 99), "stems")
    else:
        R["STEM_INTEGRITY"].set(True, None, None, "no stems supplied", basis, na=True)

    # ---- master rules --------------------------------------------------------------------------------------------
    c = R["LOUD_INTEGRATED"].cfg
    I = ebu["integrated_lufs"]
    R["LOUD_INTEGRATED"].set(I is not None and abs(I - c["target_lufs"]) <= c["tolerance_lu"], I,
                             "%.1f +- %.1f" % (c["target_lufs"], c["tolerance_lu"]), "integrated %s LUFS (ffmpeg ebur128)" % I, "master")
    c = R["TRUE_PEAK"].cfg
    tp = ebu["true_peak_dbtp"]
    R["TRUE_PEAK"].set(tp is not None and tp <= c["max_dbtp"], tp, "<= %.1f" % c["max_dbtp"], "true peak %s dBTP" % tp, "master")
    c = R["CLIPPING"].cfg
    R["CLIPPING"].set(clip["clipped_runs"] <= c["max_runs"], clip["clipped_runs"], "<= %d" % c["max_runs"],
                      "%d runs of >= 3 full-scale samples; sample peak %.2f dBFS at %d Hz" % (
                          clip["clipped_runs"], clip["sample_peak_dbfs"], clip["native_sr"]), "master")
    c = R["SILENCE"].cfg
    sil = []
    for x0, x1 in ac.runs_of(mF < c["floor_lufs"]):
        s0, s1 = x0 * B, x1 * B
        s0, s1 = max(s0, c["ignore_head_s"]), min(s1, dur - c["ignore_tail_s"])
        if s1 - s0 > c["max_s"]:
            sil.append([round(s0, 2), round(s1, 2)])
    R["SILENCE"].set(not sil, len(sil), "no stretch < %.0f LUFS longer than %.1fs" % (c["floor_lufs"], c["max_s"]),
                     "%d silent stretches%s" % (len(sil), (": " + ", ".join("%s-%s" % (fmt_t(p[0]), fmt_t(p[1])) for p in sil[:8])) if sil else ""),
                     "master", sil)

    # ---- swells / designed hits from the spec ------------------------------------------------------------------------
    swells = spec.get("swells", []) if spec else []
    def in_swell(t0, t1):
        for s in swells:
            if t0 <= float(s["t1"]) + float(s.get("fade_s", 0.8)) and t1 >= float(s["t0"]) - float(s.get("fade_s", 0.8)):
                return s
        return None

    # ---- VOICE_LEVEL ----------------------------------------------------------------------------------------------
    c = R["VOICE_LEVEL"].cfg
    if speech is not None and vM is not None and speech.any():
        inn = interior(speech, 4)
        if not inn.any():
            inn = speech
        v_med = float(np.median(vM[inn]))
        vb = "stems (voice stem)" if "voice" in stems else "master during speech (" + basis + ")"
        R["VOICE_LEVEL"].set(c["min_lufs"] <= v_med <= c["max_lufs"], round(v_med, 2),
                             "%.1f..%.1f (spec %.0f..%.0f)" % (c["min_lufs"], c["max_lufs"], c["spec_min_lufs"], c["spec_max_lufs"]),
                             "voice momentary during speech: median %.2f LUFS, p10 %.2f, p90 %.2f" % (
                                 v_med, float(np.percentile(vM[inn], 10)), float(np.percentile(vM[inn], 90))), vb)
    else:
        R["VOICE_LEVEL"].set(True, None, None, "no speech detected", basis, na=True)
    voice_ref_level = float(np.median(vM[interior(speech, 4) if interior(speech, 4).any() else speech])) \
        if speech is not None and vM is not None and speech.any() else None

    # ---- MUSIC_UNDER_SPEECH -----------------------------------------------------------------------------------------
    c = R["MUSIC_UNDER_SPEECH"].cfg
    seg_rows = []
    vmr = None
    if speech is not None and muM is not None and vM is not None and speech.any():
        vmr = np.where(speech, vM - muM, np.nan)
        worst = None
        for x0, x1 in ac.runs_of(speech):
            if (x1 - x0) * B < c["segment_min_s"]:
                continue
            med = float(np.nanmedian(vmr[x0:x1]))
            sw = in_swell(x0 * B, x1 * B)
            need = R["SWELL_CAP"].cfg["min_under_voice_lu"] if sw else c["min_lu"]
            row = {"t0": round(x0 * B, 2), "t1": round(x1 * B, 2), "median_vmr_lu": round(med, 2), "min_required": need,
                   "in_swell": sw.get("label", True) if sw else False, "ok": med >= need}
            seg_rows.append(row)
            if worst is None or med - need < worst["median_vmr_lu"] - worst["min_required"]:
                worst = row
        bad = [r for r in seg_rows if not r["ok"]]
        R["MUSIC_UNDER_SPEECH"].set(not bad, worst["median_vmr_lu"] if worst else None, ">= %.0f LU (>= %.0f in a declared swell)" % (
            c["min_lu"], R["SWELL_CAP"].cfg["min_under_voice_lu"]),
            "%d speech runs; worst median %.1f LU at %s-%s; %d below threshold; all-speech p5 %.1f LU" % (
                len(seg_rows), worst["median_vmr_lu"] if worst else float("nan"), fmt_t(worst["t0"]) if worst else "-",
                fmt_t(worst["t1"]) if worst else "-", len(bad), float(np.nanpercentile(vmr, 5))),
            mus_basis, bad[:20])
    else:
        R["MUSIC_UNDER_SPEECH"].set(True, None, None, "not measurable: " + mus_basis, basis, na=True)

    # ---- pauses: GAP_RISE / GAP_UNDER_VOICE / SWELL_CAP / NOISE_IN_PAUSES -------------------------------------------------
    trim = rc["pause_edge_trim_s"]
    ctx = R["GAP_RISE"].cfg["context_s"]
    sp_band = None
    if speech is not None and speech.any():
        inn = interior(speech, 2)
        sp_band = float(np.median(M.band_lvl[:n][inn if inn.any() else speech]))
    rows = []
    for (p0, p1) in pauses:
        i0, i1 = int(round(p0 / B)), int(round(p1 / B))
        row = {"t0": round(p0, 2), "t1": round(p1, 2), "dur_s": round(p1 - p0, 2)}
        # reference = the bed's ducked level in the speech BEFORE the pause (Sam: "rise at most ~3 dB from its ducked
        # level"; the method the approved P1 r7 was signed off with). Both-sides figure kept as music_gain_rise_both_db.
        bidx = np.r_[max(0, i0 - int(ctx / B)):i0]
        bidx = bidx[speech[bidx]] if len(bidx) else bidx
        aidx = np.r_[i1:min(n, i1 + int(ctx / B))]
        aidx = aidx[speech[aidx]] if len(aidx) else aidx
        cidx = bidx if len(bidx) >= 3 else np.r_[bidx, aidx]
        both = np.r_[bidx, aidx]
        lidx = np.r_[max(0, i0 - int(3 / B)):i0, i1:min(n, i1 + int(3 / B))]
        lidx = lidx[speech[lidx]] if len(lidx) else lidx
        v_loc = float(np.median(vM[lidx])) if (vM is not None and len(lidx)) else voice_ref_level
        row["voice_local_lufs"] = round(v_loc, 2) if v_loc is not None else None
        if muF is not None and len(cidx):
            gi = np.arange(i0, max(i1, i0 + 1))
            if mus_basis != "stems":   # master-derived: keep off the word tails
                gi2 = np.arange(int(round((p0 + trim) / B)), int(round((p1 - trim / 2) / B)))
                gi = gi2 if len(gi2) else gi
            g_lvl = float(np.percentile(muF[gi], 90))
            c_lvl = float(np.median(muF[cidx]))
            if mus_basis != "stems":
                # no music stem: in a pause the voice is absent, so the master IS the bed. Measure the margin to the
                # voice directly from the master (validated: see calibration/ESTIMATORS.json), not from mid/side.
                g_direct = float(np.percentile(mF[gi], 90))
            row["music_gap_lufs"] = round(g_lvl, 2)
            row["music_speech_lufs"] = round(c_lvl, 2)
            row["music_rise_p90_db"] = round(g_lvl - c_lvl, 2)
            # mean-power rise: gap vs the speech around it (less sensitive to one drum hit than the P90)
            mp_ = 10 ** ((muF + 0.691) / 10)
            row["music_rise_db"] = round(float(pdb(np.mean(mp_[gi])) - pdb(np.mean(mp_[cidx]))), 2)
            if music_gain is not None:
                mg_g = music_gain[gi]
                mg_c = music_gain[cidx]
                if np.isfinite(mg_g).any() and np.isfinite(mg_c).any():
                    row["music_gain_rise_db"] = round(float(np.nanmax(mg_g) - np.nanmedian(mg_c)), 2)
                    if len(both) and np.isfinite(music_gain[both]).any():
                        row["music_gain_rise_both_db"] = round(float(np.nanmax(mg_g) - np.nanmedian(music_gain[both])), 2)
            if v_loc is not None:
                row["music_under_voice_lu"] = round(v_loc - (g_lvl if mus_basis == "stems" else g_direct), 2)
            if bedF is not None:
                row["bed_total_under_voice_lu"] = round(v_loc - float(np.percentile(bedF[gi], 90)), 2)
        sw = in_swell(p0, p1)
        row["in_swell"] = (sw.get("label") or True) if sw else False
        # noise in the pause (master): Welch flatness of the 2-10 kHz band and its level vs speech
        ni = np.arange(int(round((p0 + trim) / B)), int(round((p1 - trim / 2) / B)))
        if len(ni) >= 2:
            rows_spec = M.band_spec[ni]
            row["flatness_2_10k"] = round(ac.welch_flatness(rows_spec), 3)
            row["detrended_flatness_2_10k"] = round(detrended_flatness(rows_spec), 3)
            bl = float(pdb(np.mean(10 ** ((M.band_lvl[ni] + 0.691) / 10))) + 0.691)
            row["band_2_10k_dbfs"] = round(bl, 2)
            if sp_band is not None:
                row["band_vs_speech_db"] = round(bl - sp_band, 2)
            row["floor_dbfs"] = round(float(np.percentile(M.full_lvl[ni], 10)), 2)
            row["band_std_db"] = round(float(np.std(M.band_lvl[ni])), 2) if len(ni) >= 3 else None
            cN = R["NOISE_IN_PAUSES"].cfg
            row["noise_est_lufs"] = round(bl + cN["noise_band_to_lufs_db"], 2)
            if v_loc is not None:
                row["noise_under_voice_db"] = round(v_loc - row["noise_est_lufs"], 2)
            row["pause_lufs"] = round(float(pdb(np.mean(fit(M.power(), n)[ni]))), 2)
            if stems:   # which stem carries the pause's 2-10 kHz content
                srcs = {k: float(10 * np.log10(np.mean(10 ** (fit(f.band_lvl, n, -120.0)[ni] / 10)))) for k, f in stems.items()}
                row["hf_source"] = max(srcs, key=srcs.get)
                row["hf_by_stem_dbfs"] = {k: round(v, 1) for k, v in srcs.items()}
        rows.append(row)
    # judge the pause rules
    gr, gu, sc = R["GAP_RISE"], R["GAP_UNDER_VOICE"], R["SWELL_CAP"]
    swell_max = cfg["mixer"]["swell_max_gain_db"]
    # GAP_RISE judges the bed's gain curve when one exists (mix2.py and legacy_stems.py write music_gain.json):
    # that isolates what the MIX did in the pause from the music's own notes and drum hits. Without one it falls
    # back to the mean-power level rise.
    rise_key = "music_gain_rise_db" if rows and all("music_gain_rise_db" in r for r in rows) else "music_rise_db"
    res["gap_rise_basis"] = "music gain curve" if rise_key == "music_gain_rise_db" else "music level (mean power)"
    if rows and all(rise_key in r for r in rows):
        bad_r, bad_u, bad_s = [], [], []
        for r in rows:
            sw = in_swell(r["t0"], r["t1"])
            rise = r[rise_key]
            if sw:
                cap = min(float(sw["gain_db"]), swell_max) + sc.cfg["tolerance_db"]
                r["rise_cap_db"] = round(cap, 2)
                ok_s = rise <= cap and r.get("music_under_voice_lu", 99) >= sc.cfg["min_under_voice_lu"]
                r["ok_swell"] = ok_s
                if not ok_s:
                    bad_s.append(r)
            else:
                r["rise_cap_db"] = gr.cfg["max_db"]
                r["ok_rise"] = rise <= gr.cfg["max_db"]
                if not r["ok_rise"]:
                    bad_r.append(r)
                if "music_under_voice_lu" in r:
                    r["ok_under"] = r["music_under_voice_lu"] >= gu.cfg["min_lu"]
                    if not r["ok_under"]:
                        bad_u.append(r)
        plain = [r for r in rows if not r["in_swell"]]
        worst_r = max(plain, key=lambda r: r[rise_key]) if plain else None
        worst_u = min([r for r in plain if "music_under_voice_lu" in r], key=lambda r: r["music_under_voice_lu"], default=None)
        gr.set(not bad_r, worst_r[rise_key] if worst_r else None, "<= %.1f dB" % gr.cfg["max_db"],
               "%d pauses (%d in swells); largest rise %+.1f dB at %s-%s; %d over the cap" % (
                   len(rows), len(rows) - len(plain), worst_r[rise_key] if worst_r else 0,
                   fmt_t(worst_r["t0"]) if worst_r else "-", fmt_t(worst_r["t1"]) if worst_r else "-", len(bad_r)),
               mus_basis + ", " + res["gap_rise_basis"], [{k: r[k] for k in ("t0", "t1", rise_key, "music_under_voice_lu") if k in r} for r in bad_r[:25]])
        gu.set(not bad_u, worst_u["music_under_voice_lu"] if worst_u else None, ">= %.1f LU" % gu.cfg["min_lu"],
               "smallest margin %.1f LU at %s-%s; %d pauses under %.0f LU" % (
                   worst_u["music_under_voice_lu"] if worst_u else float("nan"), fmt_t(worst_u["t0"]) if worst_u else "-",
                   fmt_t(worst_u["t1"]) if worst_u else "-", len(bad_u), gu.cfg["min_lu"]),
               mus_basis, [{k: r[k] for k in ("t0", "t1", rise_key, "music_under_voice_lu") if k in r} for r in bad_u[:25]])
        if swells:
            sc.set(not bad_s, len(bad_s), "rise <= declared gain (+%.1f), >= %.0f LU under voice" % (
                sc.cfg["tolerance_db"], sc.cfg["min_under_voice_lu"]), "%d pauses inside declared swells, %d breach" % (
                len(rows) - len(plain), len(bad_s)), mus_basis, bad_s[:10])
        else:
            sc.set(True, None, None, "no swells declared (no spec, or none in it): every pause held to the 3 dB rule",
                   mus_basis, na=True)
    else:
        why = "no pauses found" if speech is not None and not rows else "pauses or music level not measurable (%s; %s)" % (basis, mus_basis)
        for r_ in (gr, gu, sc):
            r_.set(True, None, None, why, basis, na=True)
    # NOISE_IN_PAUSES
    c = R["NOISE_IN_PAUSES"].cfg
    meas = [r for r in rows if r.get("band_std_db") is not None and "noise_under_voice_db" in r]
    for r in meas:
        r["noisy"] = bool(r["band_std_db"] <= c["stationary_max_db"] and r["detrended_flatness_2_10k"] >= c["flatness_min"]
                          and r["noise_under_voice_db"] < c["min_under_voice_db"])
    noisy = [r for r in meas if r["noisy"]]
    if meas:
        frac = len(noisy) / len(meas)
        fail = len(noisy) >= c["min_noisy_count"] and frac >= c["max_noisy_fraction"]
        R["NOISE_IN_PAUSES"].set(not fail, round(frac, 3), "noisy pauses < %d or < %.0f%%" % (c["min_noisy_count"], 100 * c["max_noisy_fraction"]),
                                 "%d of %d pauses carry a steady noise bed < %.0f dB under the voice (2-10 kHz std <= %.1f dB, detrended flatness >= %.2f); median pause std %.2f dB; median implied noise %.1f dB under the voice" % (
                                     len(noisy), len(meas), c["min_under_voice_db"], c["stationary_max_db"], c["flatness_min"],
                                     float(np.median([r["band_std_db"] for r in meas])),
                                     float(np.median([r["noise_under_voice_db"] for r in meas]))),
                                 "master in voice pauses (" + basis + ")",
                                 [{k: r[k] for k in ("t0", "t1", "band_std_db", "detrended_flatness_2_10k", "noise_under_voice_db", "hf_source") if k in r} for r in noisy[:25]])
    else:
        R["NOISE_IN_PAUSES"].set(True, None, None, "no measurable pauses", basis, na=True)
    # NOISE_FLOOR: the programme's quietest 1 s windows. A noise bed is the one thing that stays put there.
    c = R["NOISE_FLOOR"].cfg
    w = int(c["window_s"] / B)
    lv = M.full_lvl[:n]
    starts = np.arange(0, max(n - w, 0), max(w // 4, 1))
    if len(starts) > 8 and voice_ref_level is not None:
        wl = np.array([float(np.mean(lv[s0:s0 + w])) for s0 in starts])
        ok_w = wl > -90
        q = np.percentile(wl[ok_w], c["quiet_percentile"])
        qs = starts[ok_w & (wl <= q)]
        stds = [float(np.std(M.band_lvl[s0:s0 + w])) for s0 in qs]
        fls = [detrended_flatness(M.band_spec[s0:s0 + w]) for s0 in qs]
        lvls = [float(pdb(np.mean(M.power()[s0:s0 + w]))) for s0 in qs]
        st_med, fl_med, lv_med = float(np.median(stds)), float(np.median(fls)), float(np.median(lvls))
        within = voice_ref_level - lv_med
        bq = float(np.median([10 * np.log10(np.mean(10 ** (M.band_lvl[s0:s0 + w] / 10))) for s0 in qs]))
        noise_under = voice_ref_level - (bq + c["noise_band_to_lufs_db"])
        fail = st_med <= c["stationary_max_db"] and fl_med >= c["flatness_min"] and noise_under < c["min_under_voice_db"]
        R["NOISE_FLOOR"].set(not fail, round(st_med, 2), "not (2-10 kHz std <= %.1f dB and flatness >= %.2f and implied noise < %.0f dB under the voice)" % (
            c["stationary_max_db"], c["flatness_min"], c["min_under_voice_db"]),
            "quietest %d%% of %.0f s windows: %.1f LUFS (%.1f dB under the voice), 2-10 kHz std %.2f dB, detrended flatness %.2f, implied noise %.1f dB under the voice" % (
                c["quiet_percentile"], c["window_s"], lv_med, within, st_med, fl_med, noise_under), "master")
        res["noise_floor"] = {"quiet_windows_lufs": round(lv_med, 2), "under_voice_db": round(within, 2),
                              "implied_noise_under_voice_db": round(noise_under, 2),
                              "band_std_db": round(st_med, 2), "detrended_flatness": round(fl_med, 3),
                              "all_windows_band_std_p10_db": round(float(np.percentile(
                                  [np.std(M.band_lvl[s0:s0 + w]) for s0 in starts], 10)), 2)}
    else:
        R["NOISE_FLOOR"].set(True, None, None, "not measurable (no speech level or too short)", basis, na=True)

    # ---- SFX ------------------------------------------------------------------------------------------------------
    sfx_rows = []
    if "sfx" in stems:
        S = stems["sfx"]
        Pb = fit(S.power(), n)
        Lb = pdb(Pb)
        pk = fit(S.peak, n)
        on = []
        last = -99
        for i in range(3, n):
            if Lb[i] > -55 and Lb[i] - Lb[max(0, i - 3):i].min() >= 9 and i - last >= 3:
                on.append(i)
                last = i
        vpk = 20 * math.log10(max(float(np.percentile(stems["voice"].peak, 99.5)), 1e-9))
        vb_ = pdb(fit(stems["voice"].power(), n, 0.0))
        v_fast_pk = float(np.percentile(vb_[speech], 99.5)) if speech.any() else float(vb_.max())
        designed = [float(x) for x in (a.designed_hits.split(",") if a.designed_hits else []) if x.strip()]
        for cue in (spec.get("sfx", {}) or {}).get("cues", []) if spec else []:
            if cue.get("designed_hit"):
                designed.append(float(cue["t"]))
        res["designed_hits"] = designed
        import mix2  # stressed-word logic shared with the mixer
        stressed = mix2.stressed_units(stems["voice"], speech[:stems["voice"].n], words)
        mask_cfg = R["SFX_WORD_MASK"].cfg
        for j, i in enumerate(on):
            e = i
            top = Lb[i]
            while e + 1 < n and e - i < 30 and Lb[e + 1] > top - 20 and (e + 1) not in on[j + 1:j + 2]:
                e += 1
                top = max(top, Lb[e])
            ev = {"t": round(i * B, 2), "end": round((e + 1) * B, 2), "peak_dbfs": round(20 * math.log10(max(float(pk[i:e + 1].max()), 1e-9)), 2),
                  "level_lufs": round(float(top), 2)}
            ev["fast_peak_vs_voice_db"] = round(float(top) - v_fast_pk, 2)
            # a detected event can be a stack of cues: it is designed if a designed cue lands inside its span
            ev["designed_hit"] = any(ev["t"] - 0.3 <= d <= ev["end"] for d in designed)
            ev["peak_vs_voice_peak_db"] = round(ev["peak_dbfs"] - vpk, 2)
            ov = []
            w_ = mask_cfg["window_ms"] / 1000.0
            for (ws, we, wl, wt) in stressed:
                if ev["t"] <= we + w_ and ev["end"] >= ws - w_:
                    wi = np.arange(int(max(ws - w_, 0) / B), int(math.ceil((we + w_) / B)))
                    wi = wi[wi < n]
                    s_l = float(pdb(np.mean(Pb[wi]))) if len(wi) else -120
                    margin = wl - s_l
                    ov.append({"word": wt, "word_t": round(ws, 2), "word_lufs": round(wl, 2), "sfx_lufs": round(s_l, 2),
                               "margin_db": round(margin, 2), "masking": margin < mask_cfg["margin_db"]})
            ev["stressed_overlaps"] = ov
            sfx_rows.append(ev)
        per_min = len(sfx_rows) / (dur / 60.0)
        rng = R["SFX_DENSITY"].cfg["short_per_min" if kind == "short" else "long_per_min"]
        R["SFX_DENSITY"].set(rng[0] <= per_min <= rng[1], round(per_min, 1), "%d..%d per min (%s)" % (rng[0], rng[1], kind),
                             "%d SFX events detected on the sfx stem (%.1f/min)%s" % (
                                 len(sfx_rows), per_min, ("; spec lists %d cues" % len(spec["sfx"]["cues"])) if spec and spec.get("sfx", {}).get("cues") else ""),
                             "stems")
        lim = R["SFX_PEAK"].cfg["under_voice_peak_db"]
        key = "fast_peak_vs_voice_db" if R["SFX_PEAK"].cfg.get("metric") == "fast_loudness" else "peak_vs_voice_peak_db"
        badp = [e for e in sfx_rows if not e["designed_hit"] and e[key] > -lim]
        R["SFX_PEAK"].set(not badp, max([e[key] for e in sfx_rows], default=None),
                          "<= -%.0f dB vs voice peak (designed hits exempt)" % lim,
                          "voice 50 ms peak %.1f LUFS; loudest SFX %s dB vs it (sample peaks: voice %.1f dBFS, loudest SFX %s dB vs it); %d over" % (
                              v_fast_pk, max([e[key] for e in sfx_rows], default=float("nan")), vpk,
                              max([e["peak_vs_voice_peak_db"] for e in sfx_rows], default=float("nan")), len(badp)),
                          "stems", [{k: e[k] for k in ("t", "peak_dbfs", "peak_vs_voice_peak_db", "fast_peak_vs_voice_db")} for e in badp[:20]])
        allov = [dict(o, sfx_t=e["t"], designed_hit=e["designed_hit"]) for e in sfx_rows for o in e["stressed_overlaps"]]
        badm = [o for o in allov if o["masking"]]          # card: never masking a word (no designed-hit exemption)
        R["SFX_WORD_MASK"].set(not badm, len(badm), "0 masking overlaps (margin >= %.0f dB)" % mask_cfg["margin_db"],
                               "%d stressed words; %d SFX within %d ms of one; %d closer than %.0f dB to the word%s" % (
                                   len(stressed), len(allov), mask_cfg["window_ms"], len(badm), mask_cfg["margin_db"],
                                   "" if words else " (stress from voice energy: no words file)"),
                               "stems", badm[:25])
    else:
        for k in ("SFX_DENSITY", "SFX_PEAK", "SFX_WORD_MASK"):
            R[k].set(True, None, None, "needs an sfx stem", basis, na=True)

    # ---- FX_OVER_VOICE: check 13's two numbers, level-consistent (voice stem is master-referred) -----------------
    if "voice" in stems:
        c = R["FX_OVER_VOICE"].cfg
        vv = fit(stems["voice"].momentary(), n, -120.0)[::2]
        mm = mM[::2]
        spk = np.sort(vv[vv > -35])
        if len(spk):
            spk_l = float(spk[len(spk) // 2])
            sd = np.sort(mm[vv > spk_l - 10] - vv[vv > spk_l - 10])
            pdd = np.sort(mm[vv < spk_l - 20] - spk_l)
            o_s = float(sd[int(len(sd) * 0.98)]) if len(sd) else None
            o_p = float(pdd[-1]) if len(pdd) else None
            ok = (o_s is None or o_s <= c["over_speech_p98_max"]) and (o_p is None or o_p <= c["over_pause_max"])
            R["FX_OVER_VOICE"].set(ok, [round(o_s, 1) if o_s is not None else None, round(o_p, 1) if o_p is not None else None],
                                   "check 13 limits %.1f / %.1f (the kit gate decides)" % (c["over_speech_p98_max"], c["over_pause_max"]),
                                   "effects+music over the voice while speaking p98 %+.1f dB; loudest pause %+.1f dB vs speaking level (voice stem at its master level)" % (
                                       o_s if o_s is not None else float("nan"), o_p if o_p is not None else float("nan")), "stems")
    else:
        R["FX_OVER_VOICE"].set(True, None, None, "needs a voice stem (kit check 13 runs in produce.py)", basis, na=True)

    # ---- AMBIENCE -------------------------------------------------------------------------------------------------
    if "ambience" in stems and voice_ref_level is not None and float(stems["ambience"].power().max()) > 1e-10:
        A = stems["ambience"]
        aM, aF = fit(A.momentary(), n, -120.0), fit(A.fast(), n, -120.0)
        c = R["AMBIENCE_CONTINUITY"].cfg
        act = aF > voice_ref_level - c["active_under_speech_db"]
        runs = [((x1 - x0) * B, x0 * B, x1 * B) for x0, x1 in ac.runs_of(act)]
        longest = max(runs, default=(0, 0, 0))
        cov = float(act.mean())
        # band-limit check above 5 kHz (a 3 kHz low-pass legitimately keeps 2-3 kHz, so 2-10 kHz is the wrong band)
        hi = A.band_f >= 5000
        df_ = ac.SR / ac.NFFT * 4
        p5k = fit(np.sum(A.band_spec[:, hi], axis=1) * df_, n, 0.0)
        pfull = fit(10 ** (A.full_lvl / 10), n, 1e-12)
        hf = ac.db(p5k) - ac.db(pfull)
        hf_share = float(np.median(hf[act])) if act.any() else -99
        okc = longest[0] <= c["max_region_s"] and cov <= c["max_coverage"] and hf_share <= c["max_hf_share_db"]
        R["AMBIENCE_CONTINUITY"].set(okc, round(longest[0], 2), "region <= %.0fs, coverage <= %.0f%%, >5 kHz share <= %.0f dB" % (
            c["max_region_s"], 100 * c["max_coverage"], c["max_hf_share_db"]),
            "active %.0f%% of the runtime; longest run %.1fs (%s-%s); energy above 5 kHz %.1f dB re full band" % (
                100 * cov, longest[0], fmt_t(longest[1]), fmt_t(longest[2]), hf_share), "stems")
        c = R["AMBIENCE_LEVEL"].cfg
        under = voice_ref_level - float(aM.max())
        R["AMBIENCE_LEVEL"].set(under >= c["min_under_speech_db"], round(under, 2), ">= %.0f dB" % c["min_under_speech_db"],
                                "ambience momentary max %.1f LUFS = %.1f dB under the voice's speech level" % (float(aM.max()), under), "stems")
    else:
        for k in ("AMBIENCE_LEVEL", "AMBIENCE_CONTINUITY"):
            R[k].set(True, None, None, "no ambience stem / silent ambience (the master-level noise rules still apply)",
                     basis, na=True)

    # ---- studio voice quality (voice stem, or the --voice reference) -------------------------------------------------------
    vq_src = stems["voice"].path if "voice" in stems else a.voice
    if vq_src:
        import voice_quality
        vq = voice_quality.measure(vq_src, cfg.get("voice_target"))
        res["voice_quality"] = vq
        vb_ = "voice stem" if "voice" in stems else "voice reference"
        c = R["VOICE_NOISE_FLOOR"].cfg
        v_ = vq["noise_floor_under_speech_db"]
        R["VOICE_NOISE_FLOOR"].set(v_ is None or v_ >= c["min_under_speech_db"], v_, ">= %.0f dB" % c["min_under_speech_db"],
                                   "voice floor in pauses %s dB under its speech (p90 of pause blocks: %s dB under)" % (
                                       v_, vq["noise_floor_p90_under_speech_db"]), vb_, na=v_ is None)
        c = R["VOICE_SIBILANCE"].cfg
        v_ = vq["sibilance_p99_db"]
        R["VOICE_SIBILANCE"].set(v_ is not None and v_ <= c["max_db"], v_, "<= %.1f dB" % c["max_db"],
                                 "5-9 kHz p99 %s dB vs 1-4 kHz p99 (median %s dB)" % (v_, vq["sibilance_median_db"]), vb_)
        c = R["VOICE_BALANCE"].cfg
        dev = vq.get("ltas_dev_from_target_db") or {}
        judged = {k: v for k, v in dev.items() if int(k) in c["bands"]}
        worst = max(judged.items(), key=lambda kv: abs(kv[1])) if judged else None
        R["VOICE_BALANCE"].set(worst is None or abs(worst[1]) <= c["max_dev_db"], worst[1] if worst else None,
                               "|dev| <= %.0f dB at %s Hz" % (c["max_dev_db"], c["bands"]),
                               "octave LTAS minus the benchmark voice curve: %s (worst %s Hz)" % (dev, worst[0] if worst else "-"),
                               vb_, na=worst is None)
        c = R["VOICE_CONSISTENCY"].cfg
        v_ = vq["sentence_spread_lu"]
        R["VOICE_CONSISTENCY"].set(v_ is None or v_ <= c["max_sentence_spread_lu"], v_, "<= %.1f LU" % c["max_sentence_spread_lu"],
                                   "per-sentence level spread %s LU over %d sentences; short-term spread %s LU" % (
                                       v_, vq["sentences"], vq["short_term_spread_lu"]), vb_, na=v_ is None)
        c = R["VOICE_CLIPPING"].cfg
        R["VOICE_CLIPPING"].set(vq["clipped_runs"] <= c["max_runs"], vq["clipped_runs"], "<= %d" % c["max_runs"],
                                "%d clipped runs; voice sample peak %s dBFS" % (vq["clipped_runs"], vq["sample_peak_dbfs"]), vb_)
    else:
        for k in ("VOICE_NOISE_FLOOR", "VOICE_SIBILANCE", "VOICE_BALANCE", "VOICE_CONSISTENCY", "VOICE_CLIPPING"):
            R[k].set(True, None, None, "needs a voice stem or --voice", basis, na=True)

    # ---- Gemini listening passes ---------------------------------------------------------------------------------------
    gem = {}
    if not a.no_gemini:
        gv, gm = R["GEMINI_VOICE"], R["GEMINI_MIX"]
        if "voice" in stems:
            gem["voice"] = gemini_pass(stems["voice"].path, GEM_VOICE, out, "voice", gv.cfg["model"], gv.cfg["passes"])
        elif a.voice:
            gem["voice"] = gemini_pass(a.voice, GEM_VOICE, out, "voice", gv.cfg["model"], gv.cfg["passes"])
        gem["mix"] = gemini_pass(a.input, GEM_MIX, out, "mix", gm.cfg["model"], gm.cfg["passes"])
        for key, rule in (("voice", gv), ("mix", gm)):
            g = gem.get(key)
            if not g:
                rule.set(True, None, None, "no %s track to judge" % key, basis, na=True)
            elif "averaged_scores" not in g:
                rule.set(False, None, None, "listening pass failed: %s" % (g.get("skipped") or g.get("error")), "gemini")
            else:
                sc_ = g["averaged_scores"]
                low = {k: v for k, v in sc_.items() if v <= rule.cfg["fail_at_or_below"]}
                under_t = {k: v for k, v in sc_.items() if v < rule.cfg["target"]}
                hi = [p for p in g["problems"] if str(p.get("severity", "")).lower() == "high"]
                rule.set(not low, min(sc_.values()) if sc_ else None, "> %.1f (target %.1f)" % (rule.cfg["fail_at_or_below"], rule.cfg["target"]),
                         "%s averaged over %d passes; below target: %s; %d high-severity problems" % (
                             sc_, g["passes"], under_t or "none", len(hi)),
                         "gemini (%s)" % g["model"], hi[:10] + [{"annoying": x} for x in g["annoying"][:8]])
    else:
        for k in ("GEMINI_VOICE", "GEMINI_MIX"):
            R[k].set(True, None, None, "skipped (--no-gemini)", "gemini", na=True)
    res["gemini"] = gem

    # ---- plot ---------------------------------------------------------------------------------------------------------
    png = os.path.join(out, "vmr.png")
    ser, bands = [], []
    if "voice" in stems:
        ser.append(("voice M", vM, (30, 90, 200)))
    else:
        ser.append(("mix M", mM, (60, 60, 60)))
    if muM is not None:
        ser.append(("music M" + ("" if "music" in stems else " (est.)"), muM, (220, 120, 20)))
    if "sfx" in stems:
        ser.append(("sfx M", fit(stems["sfx"].momentary(), n, -120.0), (150, 60, 170)))
    if "ambience" in stems:
        ser.append(("ambience M", fit(stems["ambience"].momentary(), n, -120.0), (40, 160, 120)))
    for r in rows:
        bad = r.get("ok_rise") is False or r.get("ok_under") is False or r.get("ok_swell") is False or r.get("noisy")
        bands.append((r["t0"], r["t1"], (255, 200, 200) if bad else (215, 240, 215)))
    p2 = None
    if vmr is not None:
        p2 = {"title": "voice minus music (LU) during speech; lines at 14 LU (under speech) and 10 LU (pauses)",
              "series": [("voice - music", np.where(np.isnan(vmr), np.nan, vmr), (30, 90, 200))],
              "hlines": [(R["MUSIC_UNDER_SPEECH"].cfg["min_lu"], (200, 40, 40), "14 LU under-speech minimum"),
                         (R["GAP_UNDER_VOICE"].cfg["min_lu"], (230, 140, 0), "10 LU pause minimum")],
              "ylim": (0, 45), "bands": bands}
    ac.plot_png(png, "%s: momentary loudness per stem (LUFS); pauses green = pass, red = fail" % res["label"], t, ser, bands,
                None, p2, dur)
    res["plot"] = png

    # ---- assemble -------------------------------------------------------------------------------------------------------
    # rules that rest on the mid/side music ESTIMATE cannot block a release (their error is measured in
    # calibration/ESTIMATORS.json and is large); they report WARN. Release decisions need stems.
    if "music" not in stems:
        for k in ("MUSIC_UNDER_SPEECH", "GAP_RISE", "SWELL_CAP", "GAP_UNDER_VOICE"):
            if R[k].status == "FAIL":
                R[k].status = "WARN"
                R[k].summary = "[no stems: advisory only] " + R[k].summary
        if R["GAP_UNDER_VOICE"].status in ("PASS", "WARN"):
            R["GAP_UNDER_VOICE"].basis = "master in pauses = music + SFX + ambience (" + basis + ")"
    res["rules"] = [R[k].as_dict() for k in rc["rules"]]
    hard_fail = [r["id"] for r in res["rules"] if r["status"] == "FAIL"]
    res["overall"] = "FAIL" if hard_fail else "PASS"
    res["failed_rules"] = hard_fail
    rows_sorted = sorted(rows, key=lambda r: -r["dur_s"])
    res["pauses"] = rows
    res["three_longest_pauses"] = rows_sorted[:3]
    res["speech_runs"] = seg_rows
    res["sfx_events"] = sfx_rows
    json.dump(res, open(os.path.join(out, "AUDIO-REPORT.json"), "w"), indent=1, default=float)
    write_md(res, os.path.join(out, "AUDIO-REPORT.md"))
    return res


def write_md(res, path):
    L = ["# Audio report card: %s" % res["label"], "",
         "- Input: `%s`" % res["input"], "- Duration %.1fs (%s); evidence basis: **%s**; generated %s; rules %s" % (
             res["duration_s"], res["kind"], res["evidence_basis"], res["generated"], res["rules_version"]),
         "- **OVERALL: %s**%s" % (res["overall"], (" (failed: %s)" % ", ".join(res["failed_rules"])) if res["failed_rules"] else ""),
         "- Plot: `%s`" % res["plot"], "", "## Rules", "", "| Rule | Status | Basis | Value | Threshold | Summary |", "|---|---|---|---|---|---|"]
    for r in res["rules"]:
        L.append("| %s | **%s** | %s | %s | %s | %s |" % (r["id"], r["status"], r["basis"], r["value"], r["threshold"],
                                                          str(r["summary"]).replace("|", "/")))
    L += ["", "## Loudness", "", "| Track | Integrated LUFS | LRA LU | True peak dBTP | Momentary max | Short-term max |", "|---|---|---|---|---|---|"]
    for k, v in res["loudness"].items():
        L.append("| %s | %s | %s | %s | %s | %s |" % (k, v.get("integrated_lufs"), v.get("lra_lu"), v.get("true_peak_dbtp"),
                                                   v.get("momentary_max_lufs"), v.get("short_term_max_lufs")))
    L += ["", "## Every voice pause", "", "| Pause | Dur | Music rise dB | Gain rise dB | Music under voice LU | Bed (all) under voice LU | 2-10k std dB | Flatness (detr.) | 2-10k vs speech dB | Swell | Verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["pauses"]:
        bad = []
        if r.get("ok_rise") is False: bad.append("RISE")
        if r.get("ok_under") is False: bad.append("UNDER")
        if r.get("ok_swell") is False: bad.append("SWELL")
        if r.get("noisy"): bad.append("NOISE")
        L.append("| %s-%s | %.2f | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            fmt_t(r["t0"]), fmt_t(r["t1"]), r["dur_s"], r.get("music_rise_db"), r.get("music_gain_rise_db", "-"),
            r.get("music_under_voice_lu"), r.get("bed_total_under_voice_lu", "-"), r.get("band_std_db"), r.get("detrended_flatness_2_10k"),
            r.get("band_vs_speech_db"), r.get("in_swell") or "", ",".join(bad) or "ok"))
    if res.get("sfx_events"):
        L += ["", "## SFX events (sfx stem)", "", "| t | peak dBFS | vs voice peak dB | designed | stressed-word overlaps |", "|---|---|---|---|---|"]
        for e in res["sfx_events"]:
            ov = "; ".join("%s@%s margin %.1f dB%s" % (o["word"] or "unit", o["word_t"], o["margin_db"], " MASK" if o["masking"] else "")
                           for o in e["stressed_overlaps"])
            L.append("| %s | %s | %s | %s | %s |" % (fmt_t(e["t"]), e["peak_dbfs"], e["peak_vs_voice_peak_db"], e["designed_hit"], ov or "-"))
    if res.get("gemini"):
        L += ["", "## Gemini listening passes", ""]
        for k, g in res["gemini"].items():
            L.append("- **%s**: %s" % (k, json.dumps(g.get("averaged_scores") or g)))
            for p in (g.get("problems") or [])[:12]:
                L.append("  - %s [%s] %s" % (p.get("timestamp"), p.get("severity"), p.get("issue")))
            for x in (g.get("annoying") or [])[:6]:
                L.append("  - annoying: %s" % x)
    L += ["", "## Failing details", ""]
    for r in res["rules"]:
        if r["status"] in ("FAIL", "WARN") and r["details"]:
            L.append("- **%s**: `%s`" % (r["id"], json.dumps(r["details"][:12], default=float)))
    open(path, "w").write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--stems")
    ap.add_argument("--voice")
    ap.add_argument("--words")
    ap.add_argument("--spec")
    ap.add_argument("--music-gain")
    ap.add_argument("--out")
    ap.add_argument("--kind", choices=["short", "long"])
    ap.add_argument("--no-gemini", action="store_true")
    ap.add_argument("--label")
    ap.add_argument("--designed-hits", help="comma-separated cue times (s) of designed hits, for mixes whose cue format "
                                            "cannot declare them (legacy mix.py); mix2 specs use sfx.cues[].designed_hit")
    ap.add_argument("--no-exit-code", action="store_true", help="always exit 0 (calibration / benchmarks)")
    ap.add_argument("--reuse-gemini", action="store_true", help="reuse gemini_<tag>.json already in --out (no new calls)")
    a = ap.parse_args()
    global REUSE_GEMINI
    REUSE_GEMINI = a.reuse_gemini
    res = analyse(a)
    for r in res["rules"]:
        print("%-20s %-5s %s" % (r["id"], r["status"], r["summary"]))
    print("OVERALL", res["overall"], "->", os.path.join(os.path.dirname(res["plot"]), "AUDIO-REPORT.md"))
    sys.exit(0 if (res["overall"] == "PASS" or a.no_exit_code) else 1)


if __name__ == "__main__":
    main()
