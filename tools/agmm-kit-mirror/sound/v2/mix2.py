#!/usr/bin/env python3
"""mix2.py: build the final mix from 4 stems + a mix_spec.json, deterministically (AUDIO DESIGN SYSTEM v2).

  python3 mix2.py render  <mix_spec.json> --out <dir>        -> <dir>/master.wav, <dir>/stems/{voice,music,sfx,ambience}.wav,
                                                               <dir>/music_gain.json, <dir>/mix_manifest.json
  python3 mix2.py from-legacy --voice V --music M --cues cues.json --out spec.json [--id X]
                                                             -> a mix_spec.json from sound/mix.py-style inputs

Why v2 (Sam, 24 Sep): on P1 the music jumped up in the gaps between voice lines, and the F01 opening carried a
constant rain/white-noise bed. mix.py could not prevent either: its ducking is a signal-driven sidechain whose
release lifts the bed in every pause, and its single-pass loudnorm is dynamic (an AGC that also raises quiet
pauses). mix2 replaces both with rules:
  * Music under speech sits `music.under_voice_lu` (>= 14) below the voice. The ducked level IS the base level.
  * In a pause the bed may rise at most `ducking.gap_rise_db` (<= 3 dB, checked against rules), after a hold,
    along a release ramp, and it is already back down when the next word starts (offline lookahead: falls are
    computed backwards from the speech onset, rises forwards from the pause start).
  * Only declared swells may lift the bed further, each capped (`swells[].gain_db` <= rules swell_max_gain_db).
    Positive automation outside a declared swell is refused.
  * A gentle bed leveller holds the bed's own short-term loudness steady (quiet intros and loud choruses would
    otherwise break the 14 LU rule in one direction or the 3 dB rule in the other).
  * SFX keep mix.py's onset-correct placement (library.json onset_ms lands on the cue time). Each cue's peak is
    clamped to <= voice peak - 6 dB unless `designed_hit`, and a cue that lands within 150 ms of a stressed word is
    attenuated until it sits `sfx_mask_margin_db` under that word.
  * Ambience exists only in declared regions (<= rules ambience_max_region_s each), band-limited
    (highpass + double lowpass) and auto-levelled >= 30 dB under speech. There is no continuous ambience option.
  * Master: one static gain to the integrated target (-14 LUFS), then a true-peak safety limiter only if needed,
    re-measured until <= -1 dBTP. No dynamic loudnorm, so nothing pumps in the pauses.
Stems are written master-referred (the master gain applied, before the safety limiter), so the four stems sum to
the master except where the limiter acted; audio_report.py checks that.

Laptop-safe: sources are decoded one at a time by `nice -n 15 ffmpeg -threads 2` to raw files and mixed through
numpy memmaps in 10 s chunks, so a 20-minute film never sits in RAM.
"""
import argparse
import datetime
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audio_core as ac  # noqa: E402

SOUND = os.path.dirname(HERE)
DEFAULT_LIB = os.path.join(SOUND, "library.json")
RULES = os.path.join(HERE, "audio_rules.json")
CH = 2
BLK = 0.05  # envelope resolution (s)


def log(*a):
    print("[mix2]", *a, file=sys.stderr)


def load_rules():
    return json.load(open(RULES))


def ff_decode(src, out_raw, sr, af=None, dur=None, loop=False, ss=None):
    args = []
    if loop:
        args += ["-stream_loop", "-1"]
    if ss:
        args += ["-ss", "%.4f" % ss]
    args += ["-i", src, "-vn", "-map", "0:a:0"]
    if dur is not None:
        args += ["-t", "%.4f" % dur]
    if af:
        args += ["-af", af]
    args += ["-ac", str(CH), "-ar", str(sr), "-f", "f32le", "-y", out_raw]
    ac.run(ac.ff_cmd(args))
    return np.memmap(out_raw, dtype=np.float32, mode="r").reshape(-1, CH)


def ff_encode(raw, sr, out_wav, gain_lin=1.0, extra_af=None):
    af = []
    if gain_lin != 1.0:
        af.append("volume=%.10f" % gain_lin)
    if extra_af:
        af.append(extra_af)
    args = ["-f", "f32le", "-ar", str(sr), "-ac", str(CH), "-i", raw]
    if af:
        args += ["-af", ",".join(af)]
    args += ["-c:a", "pcm_s24le", "-y", out_wav]
    ac.run(ac.ff_cmd(args))


def ebur_raw(raw, sr):
    tmp = raw + ".wav"
    ac.run(ac.ff_cmd(["-f", "f32le", "-ar", str(sr), "-ac", str(CH), "-i", raw, "-c:a", "pcm_f32le", "-y", tmp]))
    r = ac.ffmpeg_ebur128(tmp)
    os.remove(tmp)
    return r


# ---------------------------------------------------------------------------------------------------------------
# envelope helpers (50 ms grid, dB)
def slew(u, up_db_per_s, down_db_per_s):
    """Offline lookahead slew: rises limited forwards in time, falls limited backwards (so a fall completes by the
    time the target drops, i.e. the bed is down before the word starts)."""
    up, dn = up_db_per_s * BLK, down_db_per_s * BLK
    f = u.copy()
    for i in range(1, len(f)):                      # rise no faster than `up` going forwards
        f[i] = min(f[i], f[i - 1] + up)
    b = u.copy()
    for i in range(len(b) - 2, -1, -1):             # fall no faster than `dn`: pre-empt drops
        b[i] = min(b[i], b[i + 1] + dn)
    return np.minimum(f, b)


def cos_window(n, t, t0, t1, fade):
    """0..1 plateau between t0 and t1 with raised-cosine fades of `fade` s outside it."""
    w = np.zeros(n)
    for i, tt in enumerate(t):
        if t0 <= tt <= t1:
            w[i] = 1.0
        elif t0 - fade < tt < t0:
            w[i] = 0.5 - 0.5 * math.cos(math.pi * (tt - (t0 - fade)) / fade)
        elif t1 < tt < t1 + fade:
            w[i] = 0.5 + 0.5 * math.cos(math.pi * (tt - t1) / fade)
    return w


def build_music_curve(spec, rules, n, speech, pauses, music_st):
    """Returns (gain_db per 50 ms block relative to the bed's base gain, parts dict for the manifest)."""
    t = np.arange(n) * BLK
    duck = spec.get("ducking", {})
    mus = spec.get("music", {})
    rise = float(duck.get("gap_rise_db", 2.0))
    if rise > rules["music_gap_rise_max_db"]:
        raise SystemExit("ducking.gap_rise_db %.1f exceeds the rule (%.1f dB)" % (rise, rules["music_gap_rise_max_db"]))
    hold = float(duck.get("hold_ms", 150)) / 1000.0
    release = max(float(duck.get("release_ms", 600)) / 1000.0, 0.05)
    attack = max(float(duck.get("attack_ms", 120)) / 1000.0, 0.02)
    head_db = min(float(duck.get("head_db", 3.0)), rules["swell_max_gain_db"])
    tail_db = min(float(duck.get("tail_db", 3.0)), rules["swell_max_gain_db"])
    # 25 Sep sound upgrade: the bed may lift (gap rise or declared swell) only inside a TRUE pause, >= 0.4 s, or
    # before the first / after the last word. tp = 1 there, 0 under speech, with 0.1 s raised-cosine edges inside it.
    min_tp = float(rules.get("swell_min_pause_s", 0.4))
    tp = np.zeros(n)
    sp_idx0 = np.where(speech)[0]
    if len(sp_idx0):
        tp[:sp_idx0[0]] = 1.0
        tp[sp_idx0[-1] + 1:] = 1.0
    else:
        tp[:] = 1.0
    ed = 2
    for a, b in pauses:
        if b - a >= min_tp:
            ia, ib = int(round(a / BLK)), int(round(b / BLK))
            w = np.ones(max(ib - ia, 0))
            k = min(ed, len(w) // 2)
            if k:
                r = 0.5 - 0.5 * np.cos(np.pi * (np.arange(k) + 1) / (k + 1))
                w[:k] = r; w[len(w) - k:] = r[::-1]
            tp[ia:ib] = np.maximum(tp[ia:ib], w)
    # swell windows first: inside a swell the swell IS the lift (the duck release does not stack on top of it)
    sw_w = np.zeros(n)
    sw_cap = np.zeros(n)
    for s in spec.get("swells", []):
        wv = cos_window(n, t, float(s["t0"]), float(s["t1"]), float(s.get("fade_s", 0.8)))
        sw_w = np.maximum(sw_w, wv)
        sw_cap = np.maximum(sw_cap, float(s["gain_db"]) * ((t >= float(s["t0"]) - BLK) & (t <= float(s["t1"]) + BLK)))
    # 1. ducking target: 0 under speech, `rise` in a pause after the hold, head/tail outside the voice
    u = np.zeros(n)
    sp_idx = np.where(speech)[0]
    first, last = (sp_idx[0], sp_idx[-1]) if len(sp_idx) else (n, 0)
    for a, b in pauses:
        if b - a < min_tp:
            continue                                   # a breath, not a pause: the bed holds its ducked level
        ia, ib = int(round((a + hold) / BLK)), int(round(b / BLK))
        if ib > ia:
            u[ia:ib] = rise * (1.0 - sw_w[ia:ib])
    if first < n:
        u[:max(first - int(hold / BLK), 0)] = head_db
        u[min(last + 1 + int(hold / BLK), n):] = tail_db
    # rise at most `rise` dB per `release`, fall the full range within `attack`
    span = max(rise, head_db, tail_db, 1.0)
    duck_db = slew(u, span / release, span / attack)
    # 2. bed leveller: hold the bed's own short-term loudness near its median (+3 / -6 dB range, 2 s smoothing)
    lev = np.zeros(n)
    if mus.get("level_bed", True) and music_st is not None and len(music_st):
        st = np.asarray(music_st[:n], dtype=float)
        if len(st) < n:
            st = np.concatenate([st, np.full(n - len(st), st[-1] if len(st) else -70.0)])
        live = st > -60
        if live.any():
            ref = float(np.median(st[live]))
            lev = np.where(live, np.clip(ref - st, -6.0, 3.0), 0.0)
            k = int(2.0 / BLK)
            lev = np.convolve(np.pad(lev, (k, k), mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="same")[k:-k]
    # 3. designed swells (capped) and drops
    sw = np.zeros(n)
    for s in spec.get("swells", []):
        g = float(s["gain_db"])
        if g > rules["swell_max_gain_db"]:
            raise SystemExit("swell %r gain %.1f dB exceeds swell_max_gain_db %.1f" % (s.get("label"), g,
                                                                                        rules["swell_max_gain_db"]))
        sw = np.maximum(sw, g * cos_window(n, t, float(s["t0"]), float(s["t1"]), float(s.get("fade_s", 0.8))))
    dr = np.zeros(n)
    for d in spec.get("drops", []):
        g = float(d["gain_db"])
        if g > 0:
            raise SystemExit("drop %r has positive gain; use swells[] for lifts" % d.get("label"))
        dr = np.minimum(dr, g * cos_window(n, t, float(d["t0"]), float(d["t1"]), float(d.get("fade_s", 0.3))))
    # 4. free automation: negative anywhere, positive only inside a declared swell window
    auto = np.zeros(n)
    pts = mus.get("envelope_db") or []
    if pts:
        auto = np.interp(t, [p[0] for p in pts], [p[1] for p in pts])
        pos = auto > 0.05
        if pos.any():
            allowed = np.zeros(n, bool)
            for s in spec.get("swells", []):
                allowed |= (t >= float(s["t0"]) - BLK) & (t <= float(s["t1"]) + BLK)   # one-block edge tolerance
            if (pos & ~allowed).any():
                bad = t[pos & ~allowed]
                raise SystemExit("music.envelope_db lifts the bed outside any declared swell (%.2f-%.2fs); declare a "
                                 "swell or remove the lift" % (bad[0], bad[-1]))
    # positive automation only SHAPES a declared swell (capped by its declared gain); it never adds to it
    auto_pos, auto_neg = np.maximum(auto, 0.0), np.minimum(auto, 0.0)
    lift = np.where(auto_pos > 0.05, np.minimum(auto_pos, sw_cap), sw) * tp
    duck_db = np.minimum(duck_db, np.where(tp > 0, duck_db, 0.0))
    total = duck_db + lev + lift + dr + auto_neg
    return total, {"duck_db": duck_db, "level_db": lev, "swell_db": lift, "drop_db": dr, "auto_db": auto_neg}


# ---------------------------------------------------------------------------------------------------------------
def stressed_units(voice_feat, speech, words=None):
    """Stressed words as (start, end, level_db). With a words file (start/end seconds): numbers, currency, ALL CAPS,
    capitalised mid-sentence words, words before a >= 0.3 s pause, and the loudest quarter. Without one: the loudest
    quarter of voiced units split at energy dips."""
    fast = voice_feat.fast()
    t = voice_feat.t
    out = []
    if words:
        ws = [w for w in words if "start" in w and "end" in w]
        levels = []
        for w in ws:
            m = (t >= float(w["start"])) & (t <= float(w["end"]) + 1e-6)
            levels.append(float(fast[m].max()) if m.any() else -99.0)
        q = np.percentile(levels, 75) if levels else 0
        for i, w in enumerate(ws):
            txt = str(w.get("word", w.get("text", ""))).strip()
            core = txt.strip(".,!?;:\"'()")
            prev = str(ws[i - 1].get("word", ws[i - 1].get("text", ""))) if i else "."
            nxt_gap = float(ws[i + 1]["start"]) - float(w["end"]) if i + 1 < len(ws) else 1.0
            s = (any(ch.isdigit() for ch in core) or any(c in core for c in "$£€%") or (core.isupper() and len(core) > 1)
                 or (core[:1].isupper() and not prev.strip().endswith((".", "!", "?")) and i > 0)
                 or nxt_gap >= 0.3 or levels[i] >= q or w.get("stress") or w.get("emph"))
            if s and levels[i] > -70:          # a word with no measurable voice (off the take's end) is no anchor
                out.append((float(w["start"]), float(w["end"]), levels[i], txt))
        return out
    # no words: voiced units = speech runs split where the fast level dips >= 6 dB below its neighbours
    units = []
    for a, b in ac.runs_of(speech):
        seg = fast[a:b]
        cut = [a]
        for i in range(a + 2, b - 2):
            if fast[i] < min(fast[i - 2], fast[i + 2]) - 6 and i - cut[-1] >= 3:
                cut.append(i)
        cut.append(b)
        for x, y in zip(cut, cut[1:]):
            if y > x:
                units.append((x * ac.HOP_S, y * ac.HOP_S, float(fast[x:y].max()), ""))
    if not units:
        return []
    q = np.percentile([u[2] for u in units], 75)
    return [u for u in units if u[2] >= q]


def render(spec_path, out_dir, keep_tmp=False):
    rules = load_rules()["mixer"]
    spec = json.load(open(spec_path))
    base = os.path.dirname(os.path.abspath(spec_path))
    P = lambda p: p if (p is None or os.path.isabs(p)) else os.path.normpath(os.path.join(base, p))
    sr = int(spec.get("sample_rate", 48000))
    os.makedirs(os.path.join(out_dir, "stems"), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="mix2_", dir=out_dir)
    man = {"tool": "mix2.py", "spec": os.path.abspath(spec_path), "spec_sha256": ac.sha256(spec_path),
           "rules_sha256": ac.sha256(RULES), "inputs": {}, "clamps": [], "warnings": []}
    try:
        # ---- voice ------------------------------------------------------------------------------------------
        vsrc = P(spec["voice"]["src"])
        man["inputs"]["voice"] = {"path": vsrc, "sha256": ac.sha256(vsrc)}
        # (25 Sep sound upgrade: this stage appeared twice, so studio=true ran voice_chain twice on every voice. One now.)
        # studio voice stage (Sam, 24 Sep: "studio quality along with its great deliverability"): on by default;
        # voice.studio=false only for A/B work. The chain proves the delivery is unchanged (voice_chain.delivery_check).
        if spec["voice"].get("studio", True):
            import voice_chain
            studio = os.path.join(tmp, "voice_studio.wav")
            vinfo = voice_chain.process(vsrc, studio, spec["voice"].get("studio_params"))
            vinfo["delivery"] = voice_chain.delivery_check(vsrc, studio)
            if not vinfo["delivery"]["delivery_unchanged"]:
                raise SystemExit("studio voice chain changed the delivery: %s" % vinfo["delivery"])
            man["voice_studio"] = {k: vinfo[k] for k in ("params", "leveller_db", "static_gain_db", "delivery")}
            vsrc = studio
        vpre = ac.probe(vsrc)
        dur = float(spec.get("duration_s") or vpre["duration"])
        N = int(round(dur * sr))
        nb = int(math.ceil(dur / BLK))
        voff = float(spec["voice"].get("offset_s", 0.0))
        vraw = os.path.join(tmp, "voice_src.f32")
        v = ff_decode(vsrc, vraw, sr, af=("adelay=%d:all=1" % round(voff * 1000)) if voff > 0 else None)
        vf = ac.Features(vsrc)
        vfast = vf.fast()
        vblk = ac.lufs_from_power(vf.power())      # same 50 ms block VAD as audio_report.py (a 200 ms window smears pauses)
        speech, thr = ac.voice_activity(vblk, min_pause_s=rules["min_pause_s"])
        if voff > 0:
            sh = int(round(voff / BLK))
            speech = np.concatenate([np.zeros(sh, bool), speech])
        speech = np.concatenate([speech, np.zeros(max(0, nb - len(speech)), bool)])[:nb]
        pauses = ac.pauses_from_mask(speech, rules["min_pause_s"])
        v_i = ac.integrated_lufs(vf.power(), mask=None)
        target_v = float(spec["voice"].get("speech_lufs", rules["voice_premaster_lufs"]))
        v_gain_db = target_v - v_i + float(spec["voice"].get("trim_db", 0.0))
        man["voice"] = {"integrated_in": round(v_i, 2), "gain_db": round(v_gain_db, 2), "pauses": len(pauses),
                        "speech_threshold_db": round(thr, 1) if thr is not None else None}
        vg = 10 ** (v_gain_db / 20)
        # voice peak as audio_report.py measures it: 99.5th percentile of the 50 ms K-weighted block loudness in speech
        sp0 = speech[:len(vblk)] if not voff else np.ones(len(vblk), bool)
        voice_peak_db = float(np.percentile(vblk[sp0[:len(vblk)]] if sp0[:len(vblk)].any() else vblk, 99.5)) + v_gain_db

        # ---- music (one bed or several segments) -------------------------------------------------------------
        mus = spec.get("music") or {}
        segs = mus.get("segments") or ([{"src": mus["src"], "t0": 0.0, "t1": dur, "src_offset_s": mus.get("src_offset_s", 0)}]
                                       if mus.get("src") else [])
        mraw_path = os.path.join(tmp, "music_pre.f32")
        m_pre = np.memmap(mraw_path, dtype=np.float32, mode="w+", shape=(N, CH))
        man["inputs"]["music"] = []
        for k, s in enumerate(segs):
            src = P(s["src"])
            t0, t1 = float(s.get("t0", 0.0)), min(float(s.get("t1", dur)), dur)
            fi, fo = float(s.get("fade_in_s", 0.05)), float(s.get("fade_out_s", 0.5))
            af = "afade=t=in:st=0:d=%.3f,afade=t=out:st=%.3f:d=%.3f" % (fi, max(t1 - t0 - fo, 0), fo)
            seg = ff_decode(src, os.path.join(tmp, "m%d.f32" % k), sr, af=af, dur=t1 - t0, loop=True,
                            ss=float(s.get("src_offset_s", 0)) or None)
            a = int(round(t0 * sr))
            L = min(len(seg), N - a)
            m_pre[a:a + L] += seg[:L] * (10 ** (float(s.get("gain_db", 0.0)) / 20))
            man["inputs"]["music"].append({"path": src, "sha256": ac.sha256(src), "t0": t0, "t1": t1})
        m_pre.flush()
        m_gain_curve = np.zeros(nb)
        base_db = 0.0
        if segs:
            ff_encode(mraw_path, sr, os.path.join(tmp, "music_pre.wav"))
            mf = ac.Features(os.path.join(tmp, "music_pre.wav"))
            m_i = mf.integrated()
            under = float(mus.get("under_voice_lu", rules["music_under_voice_lu_default"]))
            if under < rules["music_under_voice_lu_min"]:
                raise SystemExit("music.under_voice_lu %.1f is below the rule minimum %.1f" % (under, rules["music_under_voice_lu_min"]))
            if under > rules.get("music_under_voice_lu_max", 99):
                # Sam 25 Sep: beds 24-27 LU under the voice were "a tiny bit too quiet". Clamp, never silently obey.
                print("mix2: music.under_voice_lu %.1f above the rule maximum %.1f; using %.1f" % (under, rules["music_under_voice_lu_max"], rules["music_under_voice_lu_max"]))
                under = float(rules["music_under_voice_lu_max"])
            base_db = (target_v - under) - m_i
            curve, parts = build_music_curve(spec, rules, nb, speech, pauses, mf.short_term())
            # guard: the mixer GUARANTEES the report's music rules instead of hoping the bed's own notes behave.
            # Predicted music momentary = bed momentary + gain; voice momentary after its gain. Where the margin to the
            # voice falls under the rule (+1 dB), trim the bed locally (fall within 100 ms, recover over 600 ms).
            mM_pre = np.concatenate([mf.momentary(), np.full(max(0, nb - mf.n), -120.0)])[:nb]
            vM_ = vf.momentary() + v_gain_db
            if voff > 0:
                vM_ = np.concatenate([np.full(int(round(voff / BLK)), -120.0), vM_])
            vM_ = np.concatenate([vM_, np.full(max(0, nb - len(vM_)), -120.0)])[:nb]
            sw_any = np.zeros(nb, bool)
            tt = np.arange(nb) * BLK
            for s_ in spec.get("swells", []):
                sw_any |= (tt >= float(s_["t0"]) - 0.8) & (tt <= float(s_["t1"]) + 0.8)
            # per speech run: trim the whole run by the amount its MEDIAN margin misses the rule (the statistic
            # audio_report.py judges); per pause: by the amount the bed's peak misses 10 LU under the local voice.
            deficit = np.zeros(nb)
            pred = mM_pre + base_db + curve
            for x0, x1 in ac.runs_of(speech):
                seg = np.arange(x0, x1)
                seg = seg[vM_[seg] > -60]
                if len(seg) < 3:
                    continue
                need_ = (rules["gap_under_voice_lu_min"] if sw_any[seg].mean() > 0.5 else rules["music_under_voice_lu_min"]) + 1.0
                d_ = need_ - float(np.median(vM_[seg] - pred[seg]))
                if d_ > 0:
                    deficit[x0:x1] = np.maximum(deficit[x0:x1], d_)
            for a_, b_ in pauses:
                ia, ib = int(a_ / BLK), int(math.ceil(b_ / BLK))
                ctx = np.r_[max(0, ia - 60):ia, ib:min(nb, ib + 60)]
                ctx = ctx[speech[ctx]] if len(ctx) else ctx
                if len(ctx) and ib > ia:
                    d_ = (rules["gap_under_voice_lu_min"] + 1.0) - (float(np.median(vM_[ctx])) - float(pred[ia:ib].max()))
                    if d_ > 0:
                        deficit[ia:ib] = np.maximum(deficit[ia:ib], d_)
            # the trim may deepen within 100 ms and releases over 600 ms (never a jump)
            g_ = deficit.copy()
            top = max(float(deficit.max()), 1.0)
            for i in range(1, nb):
                g_[i] = max(g_[i], g_[i - 1] - top * BLK / 0.6)
            for i in range(nb - 2, -1, -1):
                g_[i] = max(g_[i], g_[i + 1] - top * BLK / 0.1)
            parts["guard_db"] = -g_
            curve = curve - g_
            m_gain_curve = base_db + curve
            man["music"] = {"integrated_in": round(m_i, 2), "base_gain_db": round(base_db, 2), "under_voice_lu": under,
                            "guard_max_trim_db": round(float(g_.max()), 2), "guard_trimmed_s": round(float((g_ > 0.1).sum() * BLK), 2),
                            "max_rise_in_pauses_db": round(float(max([parts["duck_db"][int(a / BLK):int(b / BLK)].max()
                                                                      for a, b in pauses] or [0])), 2)}
            # gap_rule_db: only the parts that can LIFT the bed (duck release, positive automation, swells). Designed
            # drops and the slow leveller are excluded: a drop's recovery returns the bed to base, never above it.
            gap_rule = parts["duck_db"] + parts["swell_db"]   # guard_db and drops only lower the bed
            json.dump({"block_s": BLK, "base_gain_db": round(base_db, 3),
                       "gap_rule_db": [round(float(x), 3) for x in gap_rule],
                       "total_db": [round(float(x), 3) for x in m_gain_curve],
                       **{k: [round(float(x), 3) for x in vv] for k, vv in parts.items()}},
                      open(os.path.join(out_dir, "music_gain.json"), "w"))

        # ---- SFX -------------------------------------------------------------------------------------------
        sfx_spec = spec.get("sfx") or {}
        cues = list(sfx_spec.get("cues", []))
        if sfx_spec.get("cues_file"):
            cues += json.load(open(P(sfx_spec["cues_file"])))["cues"]
        lib_path = P(sfx_spec.get("library")) if sfx_spec.get("library") else DEFAULT_LIB
        lib = {i["id"]: i for i in json.load(open(lib_path))["items"]}
        lib_root = os.path.dirname(lib_path)
        words = None
        if spec.get("words"):
            wj = json.load(open(P(spec["words"])))
            words = wj["words"] if isinstance(wj, dict) else wj
        vsh = int(round(voff / BLK)) if voff > 0 else 0
        stressed = [(a0 + voff, a1 + voff, lv, wt) for (a0, a1, lv, wt) in
                    stressed_units(vf, speech[vsh:vsh + len(vfast)], words)]
        vlev = vf.fast()
        sraw_path = os.path.join(tmp, "sfx.f32")
        s_mix = np.memmap(sraw_path, dtype=np.float32, mode="w+", shape=(N, CH))
        placed = []
        cache = {}
        for ci, c in enumerate(sorted(cues, key=lambda c: float(c["t"]))):
            sid = c["sfx_id"]
            if sid not in lib:
                raise SystemExit("unknown sfx_id %s (not in %s)" % (sid, lib_path))
            e = lib[sid]
            path = e["path"] if os.path.isabs(e["path"]) else os.path.join(lib_root, e["path"])
            if sid not in cache:
                cache[sid] = np.array(ff_decode(path, os.path.join(tmp, "sfx_%s.f32" % sid), sr))
            clip = cache[sid]
            if sid + "#k" not in cache:            # the clip's loudest 50 ms K-weighted block (report's SFX_PEAK metric)
                cache[sid + "#k"] = float(ac.lufs_from_power(ac.Features(path).power()).max())
            onset = float(e.get("onset_ms") or 0.0) / 1000.0
            if c.get("anchor") == "peak" and e.get("anchor_ms") is not None:
                onset = float(e["anchor_ms"]) / 1000.0   # risers / reverse swells: their PEAK lands on the event
            start = float(c["t"]) - onset          # mix.py's onset-correct placement
            max_s = c.get("max_s")
            if max_s and len(clip) > float(max_s) * sr:  # a long file never runs on under the voice (S34's 19 s tick)
                clip = clip[:int(float(max_s) * sr)].copy()
                fo = int(0.08 * sr)
                clip[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)[:, None]
            late = 0.0
            if start < 0:
                late, start = -start, 0.0
                man["warnings"].append("cue t=%.3f %s: onset %.0f ms earlier than the clip allows; lands %.0f ms late"
                                       % (float(c["t"]), sid, onset * 1000, late * 1000))
            g = float(c.get("gain_db", -6.0))
            designed = bool(c.get("designed_hit"))
            pk = cache[sid + "#k"] + g
            # rule: SFX peak <= voice peak - 6 dB unless a designed hit (relative to the voice after its gain)
            lim = voice_peak_db - rules["sfx_peak_under_voice_peak_db"]
            if not designed and pk > lim:
                man["clamps"].append({"t": c["t"], "sfx_id": sid, "rule": "sfx_peak", "from_db": g, "to_db": round(g - (pk - lim), 2)})
                g -= (pk - lim)
            # rule: never mask a stressed word (within 150 ms). The protection is LOCAL: the clip is dipped only
            # across [word - 150 ms, word + 150 ms] (30 ms ramps), so a long clip (a ticking loop) is not silenced
            # everywhere because it crosses one word. Each dip is computed from the clip at its cue gain.
            env = None
            # no designed-hit exemption here: the card says SFX never mask a word (the slam may land WITH the word,
            # 10 dB under it); +1 dB mixer margin because the report measures the summed SFX stem, not one cue
            if sfx_spec.get("protect_words", True):
                w_ = rules["sfx_word_window_ms"] / 1000.0
                c_on, c_off = start, start + len(clip) / sr
                for (ws, we, wl, wt) in stressed:
                    if c_on <= we + w_ and c_off >= ws - w_:
                        a0 = int(max(ws - w_ - start, 0) * sr); a1 = int(min(max(we + w_ - start, 0), len(clip) / sr) * sr)
                        if a1 - a0 < int(0.01 * sr):
                            continue
                        seg = clip[a0:a1]
                        cue_db = 10 * math.log10(max(float(np.mean(seg.astype(np.float64) ** 2)) * 2, 1e-12)) - 0.691 + g
                        need = (wl + v_gain_db - rules["sfx_mask_margin_db"] - 1.0) - cue_db
                        if need < 0:
                            if env is None:
                                env = np.ones(len(clip), np.float32)
                            r_ = int(0.03 * sr)
                            dip = np.ones(len(clip), np.float32)
                            lo, hi = max(a0 - r_, 0), min(a1 + r_, len(clip))
                            dip[lo:hi] = 10 ** (need / 20)
                            if a0 > lo:
                                dip[lo:a0] = np.linspace(1.0, 10 ** (need / 20), a0 - lo)
                            if hi > a1:
                                dip[a1:hi] = np.linspace(10 ** (need / 20), 1.0, hi - a1)
                            env = np.minimum(env, dip)
                            man["clamps"].append({"t": c["t"], "sfx_id": sid, "rule": "word_mask", "word": wt,
                                                  "word_t": round(ws, 2), "local_dip_db": round(need, 2)})
            # stereo: constant-power pan to the element's place on screen (centre = unity on both sides)
            pan = max(-rules.get("pan_max", 0.7), min(rules.get("pan_max", 0.7), float(c.get("pan", 0.0) or 0.0)))
            th = (pan + 1.0) * math.pi / 4.0
            pg = np.array([math.cos(th), math.sin(th)], np.float32) * np.float32(math.sqrt(2.0))
            a = int(round(start * sr))
            L = min(len(clip), N - a)
            if L > 0:
                seg_ = clip[:L] * (10 ** (g / 20))
                if env is not None:
                    seg_ = seg_ * env[:L, None]
                s_mix[a:a + L] += seg_ * pg[None, :]
            placed.append({"t": float(c["t"]), "sfx_id": sid, "gain_db": round(g, 2), "placed_at": round(start, 4),
                           "onset_ms": round(onset * 1000, 1), "designed_hit": designed, "event": c.get("event", ""),
                           "pan": round(pan, 2), "anchor": c.get("anchor", "onset")})
        s_mix.flush()
        # summed-stem pass: several cues on one word add up even when each was protected alone. Measure the SFX stem
        # exactly as audio_report.py does (K-weighted 50 ms blocks, mean over word +-150 ms vs the word's fast peak)
        # and dip the stem locally where the sum is closer than the margin (+0.5 dB). Two passes.
        if sfx_spec.get("protect_words", True) and stressed:
            w_ = rules["sfx_word_window_ms"] / 1000.0
            r_ = int(0.03 * sr)
            for it_ in range(4):
                probe_wav = os.path.join(tmp, "sfx_probe.wav")
                ff_encode(sraw_path, sr, probe_wav)
                Pb = ac.Features(probe_wav).power()
                changed = 0
                for (ws, we, wl, wt) in stressed:
                    i0_, i1_ = int(max(ws - w_, 0) / BLK), int(math.ceil((we + w_) / BLK))
                    seg_p = Pb[i0_:min(i1_, len(Pb))]
                    if not len(seg_p):
                        continue
                    s_l = float(ac.lufs_from_power(np.mean(seg_p)))
                    need = (wl + v_gain_db - rules["sfx_mask_margin_db"] - 0.75) - s_l
                    if need < 0:
                        a0, a1 = int(max(ws - w_, 0) * sr), min(int((we + w_) * sr), N)
                        lo, hi = max(a0 - r_, 0), min(a1 + r_, N)
                        gdip = np.ones(hi - lo, np.float32) * (10 ** (need / 20))
                        if a0 > lo:
                            gdip[:a0 - lo] = np.linspace(1.0, 10 ** (need / 20), a0 - lo)
                        if hi > a1:
                            gdip[a1 - lo:] = np.linspace(10 ** (need / 20), 1.0, hi - a1)
                        s_mix[lo:hi] = s_mix[lo:hi] * gdip[:, None]
                        man["clamps"].append({"t": round(ws, 2), "rule": "word_mask_sum", "word": wt, "pass": it_ + 1,
                                              "dip_db": round(need, 2)})
                        changed += 1
                s_mix.flush()
                os.remove(probe_wav)
                if not changed:
                    break
        # sidechain duck of the SFX bus, keyed off the voice (25 Sep sound upgrade): while the voice speaks the whole
        # SFX bus sits sfx_duck_db lower (falls in 30 ms, recovers over 250 ms), so a hit in a true pause can speak up
        # and the same hit under a line tucks in. Offline and deterministic, like the music duck.
        sd = float(sfx_spec.get("duck_db", rules.get("sfx_duck_db", 3.0)))
        if sd > 0 and len(speech):
            u_ = np.where(speech[:nb], -sd, 0.0) if len(speech) >= nb else np.concatenate([np.where(speech, -sd, 0.0), np.zeros(nb - len(speech))])
            gdb = slew(u_, sd / 0.25, sd / 0.03)
            tb_ = (np.arange(nb) + 0.5) * BLK
            for a0 in range(0, N, sr * 10):
                b0 = min(a0 + sr * 10, N)
                s_mix[a0:b0] = s_mix[a0:b0] * (10 ** (np.interp(np.arange(a0, b0) / sr, tb_, gdb) / 20)).astype(np.float32)[:, None]
            s_mix.flush()
            man["sfx_duck"] = {"duck_db": sd, "attack_ms": 30, "release_ms": 250, "key": "voice speech mask"}
        man["sfx"] = {"library": lib_path, "cues": placed, "per_minute": round(len(placed) / (dur / 60.0), 1)}

        # ---- ambience: declared regions only -------------------------------------------------------------------
        araw_path = os.path.join(tmp, "amb.f32")
        a_mix = np.memmap(araw_path, dtype=np.float32, mode="w+", shape=(N, CH))
        amb_regions = (spec.get("ambience") or {}).get("regions", [])
        man["ambience"] = []
        for k, r in enumerate(amb_regions):
            t0, t1 = float(r["t0"]), min(float(r["t1"]), dur)
            if t1 - t0 > rules["ambience_max_region_s"]:
                raise SystemExit("ambience region %.1f-%.1fs is %.1fs long; the rule caps a region at %.0fs (no continuous beds)"
                                 % (t0, t1, t1 - t0, rules["ambience_max_region_s"]))
            lp = float(r.get("lowpass_hz", rules["ambience_default_lowpass_hz"]))
            if lp > rules["ambience_max_lowpass_hz"]:
                raise SystemExit("ambience lowpass %.0f Hz above the %.0f Hz cap" % (lp, rules["ambience_max_lowpass_hz"]))
            fade = float(r.get("fade_s", 0.6))
            af = ("highpass=f=%d,lowpass=f=%d,lowpass=f=%d,afade=t=in:st=0:d=%.2f,afade=t=out:st=%.3f:d=%.2f"
                  % (int(r.get("highpass_hz", 80)), lp, lp, fade, max(t1 - t0 - fade, 0), fade))
            src = P(r["src"])
            seg = np.array(ff_decode(src, os.path.join(tmp, "a%d.f32" % k), sr, af=af, dur=t1 - t0, loop=True))
            p = float(np.mean(seg.astype(np.float64) ** 2)) * 2
            seg_l = 10 * math.log10(max(p, 1e-12)) - 0.691   # unweighted approx; lowpassed content, K-weighting ~0
            under = max(float(r.get("under_speech_db", rules["ambience_under_speech_db_default"])),
                        rules["ambience_under_speech_db_min"])
            g = (target_v - under) - seg_l
            if "gain_db" in r:
                g = min(g, float(r["gain_db"]))
            a = int(round(t0 * sr))
            L = min(len(seg), N - a)
            a_mix[a:a + L] += seg[:L] * (10 ** (g / 20))
            man["ambience"].append({"src": src, "t0": t0, "t1": t1, "lowpass_hz": lp, "gain_db": round(g, 2),
                                    "under_speech_db": under, "label": r.get("label", "")})
        a_mix.flush()

        # ---- sum (pre-master) in chunks, applying the voice gain and the music curve -----------------------------
        vs_path, ms_path = os.path.join(tmp, "voice.f32"), os.path.join(tmp, "music.f32")
        v_st = np.memmap(vs_path, dtype=np.float32, mode="w+", shape=(N, CH))
        m_st = np.memmap(ms_path, dtype=np.float32, mode="w+", shape=(N, CH))
        pre_path = os.path.join(tmp, "premix.f32")
        pre = np.memmap(pre_path, dtype=np.float32, mode="w+", shape=(N, CH))
        tb = (np.arange(nb) + 0.5) * BLK
        step = sr * 10
        for a in range(0, N, step):
            b = min(a + step, N)
            ts = np.arange(a, b) / sr
            vv = np.zeros((b - a, CH), np.float32)
            L = max(0, min(len(v), b) - a)
            if L > 0:
                vv[:L] = v[a:a + L] * vg
            gm = (10 ** (np.interp(ts, tb, m_gain_curve) / 20)).astype(np.float32)[:, None]
            mm = m_pre[a:b] * gm
            v_st[a:b] = vv
            m_st[a:b] = mm
            pre[a:b] = vv + mm + s_mix[a:b] + a_mix[a:b]
        for x in (v_st, m_st, pre):
            x.flush()

        # ---- master: static gain to target, then a true-peak safety limiter only if needed ----------------------
        mst = spec.get("master", {})
        tgt_i = float(mst.get("integrated_lufs", rules["master_integrated_lufs"]))
        # the WAV is limited codec_margin_db below the delivery ceiling: P2's hits reached -0.3 dBTP after AAC from a
        # -1.5 dBTP WAV (24 Sep), so the ceiling must hold on the encoded file, not just the WAV
        tgt_tp = float(mst.get("true_peak_dbtp", rules["master_true_peak_dbtp"])) - float(rules.get("codec_margin_db", 1.0))
        m0 = ebur_raw(pre_path, sr)
        gain_db = tgt_i - m0["integrated_lufs"]
        g_lin = 10 ** (gain_db / 20)
        master_wav = os.path.join(out_dir, "master.wav")
        tp_pre = m0["true_peak_dbtp"] + gain_db
        limiter = None
        ff_encode(pre_path, sr, master_wav, g_lin)
        meas = ac.ffmpeg_ebur128(master_wav)
        lim_db = tgt_tp - 0.6
        tries = 0
        while meas["true_peak_dbtp"] is not None and meas["true_peak_dbtp"] > tgt_tp - 0.1 and tries < 6:
            limiter = "alimiter=level_in=1:level_out=1:limit=%.6f:attack=5:release=60:asc=1:level=0:latency=1" % (10 ** (lim_db / 20))
            ff_encode(pre_path, sr, master_wav, g_lin, extra_af=limiter)
            meas = ac.ffmpeg_ebur128(master_wav)
            tries += 1
            lim_db -= 0.4
        # the ceiling must hold on the DELIVERED encode: encode an AAC 320k proxy (what produce.py muxes), measure its
        # true peak, and pull the limiter down by the overshoot until it holds (P2: -2.3 dBTP WAV -> +0.4 dBTP AAC)
        deliv_tp = float(mst.get("true_peak_dbtp", rules["master_true_peak_dbtp"]))
        proxy = os.path.join(tmp, "proxy.m4a")
        codec_passes = []
        for k_ in range(8):
            ac.run(ac.ff_cmd(["-i", master_wav, "-c:a", "aac", "-b:a", "320k", "-ar", str(sr), "-y", proxy]))
            ptp = ac.ffmpeg_ebur128(proxy)["true_peak_dbtp"]
            codec_passes.append({"wav_tp": meas["true_peak_dbtp"], "aac_tp": ptp})
            if ptp is None or ptp <= deliv_tp - 0.2:
                break
            lim_db = min(lim_db, (meas["true_peak_dbtp"] or tgt_tp) - 0.6) - max(0.4, (ptp - (deliv_tp - 0.2)) / 3.0)
            limiter = "alimiter=level_in=1:level_out=1:limit=%.6f:attack=5:release=60:asc=1:level=0:latency=1" % (10 ** (lim_db / 20))
            ff_encode(pre_path, sr, master_wav, g_lin, extra_af=limiter)
            meas = ac.ffmpeg_ebur128(master_wav)
        man_codec = {"target_dbtp_on_aac320k": deliv_tp, "passes": codec_passes}
        # stems: master-referred (same static gain), before the limiter
        for name, raw in (("voice", vs_path), ("music", ms_path), ("sfx", sraw_path), ("ambience", araw_path)):
            ff_encode(raw, sr, os.path.join(out_dir, "stems", name + ".wav"), g_lin)
        man["master"] = {"premix": m0, "static_gain_db": round(gain_db, 3), "true_peak_before_limiter_dbtp": round(tp_pre, 2),
                         "limiter": limiter, "limiter_passes": tries, "final": meas, "codec_check": man_codec, "path": master_wav,
                         "sha256": ac.sha256(master_wav)}
        man["stems"] = {n: {"path": os.path.join(out_dir, "stems", n + ".wav"),
                            "sha256": ac.sha256(os.path.join(out_dir, "stems", n + ".wav"))}
                        for n in ("voice", "music", "sfx", "ambience")}
        man["duration_s"] = dur
        man["sample_rate"] = sr
        man["pauses"] = [[round(a, 3), round(b, 3)] for a, b in pauses]
        man["rendered_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        json.dump(man, open(os.path.join(out_dir, "mix_manifest.json"), "w"), indent=1)
        log("master %s  I %s LUFS  TP %s dBTP  (static gain %+.2f dB, limiter %s)" % (
            master_wav, meas["integrated_lufs"], meas["true_peak_dbtp"], gain_db, "on" if limiter else "off"))
        if man["clamps"]:
            log("%d SFX clamps applied (see mix_manifest.json)" % len(man["clamps"]))
        return man
    finally:
        if not keep_tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def from_legacy(a):
    cues = json.load(open(a.cues))
    spec = {
        "id": a.id or os.path.splitext(os.path.basename(a.out))[0],
        "voice": {"src": os.path.abspath(a.voice)},
        "music": {"src": os.path.abspath(a.music), "under_voice_lu": 16.0, "level_bed": True},
        "ducking": {"gap_rise_db": 2.0, "hold_ms": 150, "release_ms": 600, "attack_ms": 120, "head_db": 3.0, "tail_db": 3.0},
        "swells": [], "drops": [],
        "sfx": {"library": os.path.abspath(a.library), "cues": cues["cues"], "protect_words": True},
        "ambience": {"regions": []},
        "master": {"integrated_lufs": -14.0, "true_peak_dbtp": -1.0},
        "_converted_from": {"cues": os.path.abspath(a.cues), "legacy_duck": cues.get("duck")},
    }
    json.dump(spec, open(a.out, "w"), indent=1)
    print("wrote", a.out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("spec")
    r.add_argument("--out", required=True)
    r.add_argument("--keep-tmp", action="store_true")
    f = sub.add_parser("from-legacy")
    f.add_argument("--voice", required=True)
    f.add_argument("--music", required=True)
    f.add_argument("--cues", required=True)
    f.add_argument("--library", default=DEFAULT_LIB)
    f.add_argument("--out", required=True)
    f.add_argument("--id")
    a = ap.parse_args()
    if a.cmd == "render":
        render(a.spec, a.out, a.keep_tmp)
    else:
        from_legacy(a)


if __name__ == "__main__":
    main()
