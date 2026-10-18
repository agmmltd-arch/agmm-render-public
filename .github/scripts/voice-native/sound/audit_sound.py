#!/usr/bin/env python3
"""audit_sound.py <master.mp4|wav> [--build DIR] [--out DIR] [--json FILE]      (kit gate check 15 SOUND AUDIT)

Measures a finished master against the 25 Sep sound rules and exits 1 on any breach:

  LOUDNESS      integrated -14 LUFS +-1 and true peak <= -1 dBTP (ffmpeg ebur128, 4x oversampled)
  BED_ROWS      every speech row: music bed >= 12 LU under the voice in every row, median 12-18 (target 15; Sam 25 Sep) (median of voice M - bed M over the row)
  SWELLS        the bed is lifted (> 1 dB over its ducked level) only inside a true pause of >= 0.4 s
  DENSITY       20 to 60 designed sound events a minute (P2, which Sam called immersive, runs ~60) (layers of one hit and a run of one gesture count once)
  OVERLAP       at most 3 sound events sounding at once
  ONSETS        every cue's measured onset (its peak for risers/swells) lands within 1 frame (33.3 ms) of its
                scene event; measured from the audio itself, never from library metadata
  STEREO        where the picture's motion at a cue is clearly off-centre, the cue's sound leans the same way
  BANNED        no glitch / zap / electrical-buzz sound anywhere (Sam, 25 Sep)

Stems: a mix2 build carries master-referred stems (audio/mix2/stems/*.wav) and its placement manifest, and those are
read directly. A legacy mix.py build is reconstructed exactly from its own inputs (voice, shaped bed, cue list and the
sidechain settings in cues.json); the common loudnorm gain cancels in every ratio this audit takes.

Discovery from the master's folder (kit/out/<ID>/FINAL.mp4 or pilot/build/<ID>/FINAL.mp4): audio/cues.json,
audio/mix2/, audio/voice-padded.wav (or audio/voice*.wav), audio/bed-shaped.wav, resolved.json (words + scene events).
Override any with --voice --bed --cues --words --stems.
"""
import argparse, json, math, os, re, subprocess, sys, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "v2"))
import audio_core as ac  # noqa: E402

LIBJSON = os.environ.get("AUDIT_SOUND_LIBJSON") or os.path.join(HERE, "library.json")
FPS = 30.0
FRAME = 1.0 / FPS
RULES = {"lufs": -14.0, "lufs_tol": 1.0, "tp_max": -1.0, "bed_under_voice_lu": 12.0, "bed_under_voice_lu_max": 18.0, "swell_min_pause_s": 0.4,
         "lift_db": 1.0, "density": (20.0, 60.0), "max_overlap": 3, "onset_tol_s": FRAME + 0.0005,
         "stereo_min_match": 0.7, "layer_s": 0.12, "gesture_s": 0.35, "audible_db": 30.0}
BANNED = re.compile(r"glitch|zap|electric|buzz", re.I)
PEAK_ANCHORED = ("riser", "reverse_swell", "reverse_cymbal")
SR = 48000
V1_REMEASURED_EPOCH = 1790369400   # 2026-09-25 21:50 BST: library.json v1 onsets re-measured (build_library_v3 --remeasure-v1)


def sh(cmd):
    return subprocess.run(["nice", "-n", "15"] + cmd, capture_output=True, text=True)


def pcm(path, sr=SR, ch=2):
    p = subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-threads", "2", "-i", path, "-vn", "-ac", str(ch),
                        "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(p.stdout, np.float32).reshape(-1, ch).astype(np.float64)


def write_wav(path, x, sr=SR):
    subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", str(x.shape[1]),
                    "-i", "-", "-c:a", "pcm_f32le", path], input=np.ascontiguousarray(x, np.float32).tobytes(), check=True)


def dur_of(path):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).stdout.strip())


# ------------------------------------------------------------------ clip facts, measured from the audio itself
_clip = {}


def clip_facts(path):
    """true onset (first sample >= 6% of peak), peak time (20 ms RMS max) and audible length (until it stays 30 dB
    under its peak), all from the file's samples."""
    if path in _clip:
        return _clip[path]
    x = pcm(path)
    m = np.abs(x).max(axis=1)
    pk = m.max() if len(m) else 0.0
    if pk <= 0:
        _clip[path] = {"onset": 0.0, "peak": 0.0, "audible": 0.0, "x": x}
        return _clip[path]
    on = int(np.argmax(m >= 0.06 * pk))
    w = int(0.02 * SR)
    rms = np.sqrt(np.convolve((x ** 2).mean(axis=1), np.ones(w) / w, mode="same"))
    pki = int(np.argmax(rms))
    above = np.where(rms >= rms.max() * 10 ** (-RULES["audible_db"] / 20))[0]
    _clip[path] = {"onset": on / SR, "peak": pki / SR, "audible": (above[-1] - on) / SR if len(above) else 0.0, "x": x}
    return _clip[path]


# ------------------------------------------------------------------ inputs
def discover(a):
    d = a.build or os.path.dirname(os.path.abspath(a.master))
    au = os.path.join(d, "audio")
    inp = {"dir": d, "master": os.path.abspath(a.master)}
    m2 = a.stems or os.path.join(au, "mix2", "stems")
    if os.path.isdir(m2) and os.path.exists(os.path.join(m2, "voice.wav")):
        inp["mode"] = "mix2"
        inp["stems"] = m2
        man = os.path.join(os.path.dirname(m2), "mix_manifest.json")
        inp["manifest"] = json.load(open(man)) if os.path.exists(man) else None
        mg = os.path.join(os.path.dirname(m2), "music_gain.json")
        inp["music_gain"] = json.load(open(mg)) if os.path.exists(mg) else None
    else:
        inp["mode"] = "legacy"
        v = a.voice or next((os.path.join(au, f) for f in ["voice-padded.wav"] + sorted(os.listdir(au)) if f.startswith("voice")
                             and f.endswith(".wav") and os.path.exists(os.path.join(au, f))), None) if os.path.isdir(au) else a.voice
        inp["voice"], inp["bed"] = v, a.bed or os.path.join(au, "bed-shaped.wav")
        be = os.path.join(au, "bed-envelope.json")
        inp["bed_envelope"] = json.load(open(be)) if os.path.exists(be) else None
    cues = a.cues or os.path.join(au, "cues.json")
    inp["cues_doc"] = json.load(open(cues)) if os.path.exists(cues) else {"cues": []}
    inp["cues_path"] = cues if os.path.exists(cues) else None
    words = a.words
    if not words and os.path.exists(os.path.join(d, "resolved.json")):
        words = os.path.join(d, "resolved.json")
    inp["words"] = None
    if words:
        w = json.load(open(words))
        w = w.get("words", w) if isinstance(w, dict) else w
        inp["words"] = [x for x in w if "start" in x and "end" in x]
    for k in ("voice", "bed"):
        if inp.get(k) and not os.path.exists(inp[k]):
            sys.exit("audit_sound: %s file not found: %s" % (k, inp[k]))
    return inp


def legacy_stems(inp, dur, tmp):
    """Rebuild mix.py's own pre-loudnorm stems: the voice, the bed through the same sidechaincompress settings, and
    every cue placed exactly as mix.py places it (file start = t - library onset_ms, clamped at 0)."""
    duck = inp["cues_doc"].get("duck", {})
    th, ra, at, rl, mk = (duck.get("threshold", 0.05), duck.get("ratio", 8), duck.get("attack", 5), duck.get("release", 250),
                          duck.get("makeup", 1.0))
    music = os.path.join(tmp, "music.wav")
    p = sh(["ffmpeg", "-v", "error", "-y", "-threads", "1", "-i", inp["voice"], "-i", inp["bed"], "-filter_complex",
            "[0:a]aformat=channel_layouts=stereo,aresample=%d[k];[1:a]aformat=channel_layouts=stereo,aresample=%d[b];"
            "[b][k]sidechaincompress=threshold=%.4f:ratio=%.2f:attack=%.1f:release=%.1f:makeup=%.2f[m]" % (SR, SR, th, ra, at, rl, mk),
            "-map", "[m]", "-t", "%.3f" % dur, "-c:a", "pcm_f32le", music])
    if p.returncode:
        sys.exit("audit_sound: could not rebuild the ducked bed: " + p.stderr[-400:])
    lib = {i["id"]: i for i in json.load(open(LIBJSON))["items"]}
    N = int(dur * SR) + 1
    sfx = np.zeros((N, 2))
    placed = []
    for c in inp["cues_doc"]["cues"]:
        e = lib.get(c["sfx_id"])
        if not e:
            continue
        path = os.path.join(HERE, e["path"])
        f = clip_facts(path)
        # mix.py placed each file with the onset_ms the library held WHEN that mix was made. The v1 values were
        # re-measured on 25 Sep 21:50 (22 were off by more than a frame); a mix built before then used onset_ms_v1.
        old_mix = os.path.getmtime(inp.get("cues_path") or LIBJSON) < V1_REMEASURED_EPOCH
        onset_used = e.get("onset_ms_v1") if (old_mix and "onset_ms_v1" in e) else e.get("onset_ms")
        start = max(0.0, float(c["t"]) - float(onset_used or 0) / 1000.0)
        a = int(round(start * SR))
        x = f["x"] * 10 ** (float(c.get("gain_db", -6)) / 20)
        L = min(len(x), N - a)
        if L > 0:
            sfx[a:a + L] += x[:L]
        placed.append({"t": float(c["t"]), "sfx_id": c["sfx_id"], "placed_at": start, "path": path,
                       "category": e.get("category", ""), "event": c.get("event", ""), "pan": c.get("pan", 0.0),
                       "event_t": c.get("event_t", c["t"]), "anchor": c.get("anchor")})
    sp = os.path.join(tmp, "sfx.wav")
    write_wav(sp, sfx)
    return {"voice": inp["voice"], "music": music, "sfx": sp}, placed


def mix2_placed(inp):
    lib = {i["id"]: i for i in json.load(open(LIBJSON))["items"]}
    src = {(round(float(c["t"]), 3), c["sfx_id"]): c for c in inp["cues_doc"]["cues"]}
    out = []
    for c in (inp["manifest"] or {}).get("sfx", {}).get("cues", []):
        e = lib.get(c["sfx_id"], {})
        o = src.get((round(float(c["t"]), 3), c["sfx_id"]), {})
        out.append({"t": float(c["t"]), "sfx_id": c["sfx_id"], "placed_at": float(c["placed_at"]),
                    "path": os.path.join(HERE, e.get("path", "")), "category": e.get("category", ""),
                    "event": c.get("event", o.get("event", "")), "pan": float(c.get("pan", o.get("pan", 0.0))),
                    "event_t": float(o.get("event_t", c["t"])), "anchor": o.get("anchor", c.get("anchor"))})
    return out


# ------------------------------------------------------------------ helpers
def speech_rows(words, vf, dur):
    """rows = runs of speech: words joined across gaps < 0.3 s (or the voice VAD when no words), >= 0.8 s long."""
    rows = []
    if words:
        for w in sorted(words, key=lambda w: w["start"]):
            if rows and w["start"] - rows[-1][1] < 0.3:
                rows[-1][1] = max(rows[-1][1], w["end"])
            else:
                rows.append([w["start"], w["end"]])
    else:
        sp, _ = ac.voice_activity(ac.lufs_from_power(vf.power()))
        rows = [[a * ac.HOP_S, b * ac.HOP_S] for a, b in ac.runs_of(sp)]
    return [r for r in rows if r[1] - r[0] >= 0.8 and r[0] < dur]


def pauses(words, vf):
    sp, _ = ac.voice_activity(ac.lufs_from_power(vf.power()), min_pause_s=0.1)
    return sp


def group_events(placed):
    """designed sound events: cues whose onsets sit within 0.12 s are layers of one hit; a run of the same category
    with gaps <= 0.35 s is one gesture (a typing run, a paper riffle)."""
    ev = []
    for c in sorted(placed, key=lambda c: c["t"]):
        cat = c["category"]
        if ev and (c["t"] - ev[-1]["last_t"] <= RULES["layer_s"] or
                   (cat == ev[-1]["cat"] and c["t"] - ev[-1]["last_t"] <= RULES["gesture_s"])):
            ev[-1]["cues"].append(c); ev[-1]["last_t"] = c["t"]
        else:
            ev.append({"t": c["t"], "last_t": c["t"], "cat": cat, "cues": [c]})
    return ev


def audible_span(c):
    f = clip_facts(c["path"])
    s = c["placed_at"] + f["onset"]
    return s, s + max(f["audible"], 0.03)


def motion(master, dur):
    """per-frame motion energy and its horizontal centroid (0 = left edge, 1 = right) at 30 fps, 108 x 192 grey."""
    W, H = 108, 192
    p = subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-threads", "2", "-i", master, "-an", "-vf",
                        "fps=%d,scale=%d:%d,format=gray" % (FPS, W, H), "-f", "rawvideo", "-"], capture_output=True)
    fr = np.frombuffer(p.stdout, np.uint8)
    n = len(fr) // (W * H)
    if n < 2:
        return None
    fr = fr[:n * W * H].reshape(n, H, W).astype(np.float32)
    d = np.abs(np.diff(fr, axis=0))
    col = d.sum(axis=1)                              # (n-1, W)
    tot = col.sum(axis=1) + 1e-9
    xs = (np.arange(W) + 0.5) / W
    cx = (col * xs).sum(axis=1) / tot
    third = W // 3
    conc = np.array([max(col[k, :third].sum(), col[k, third:2 * third].sum(), col[k, 2 * third:].sum()) for k in range(len(col))]) / tot
    energy = tot / (W * H)
    return {"energy": np.concatenate([[0.0], energy]), "cx": np.concatenate([[0.5], cx]), "conc": np.concatenate([[0.0], conc]),
            "col": np.concatenate([np.zeros((1, W)), col])}


def event_x(mo, t):
    """Where the NEW motion is at time t: the columns' motion over the 4 frames from the event, minus each column's
    own running motion before it (timecodes, scanlines and loops cancel out). Returns (x 0..1, share of that new
    motion inside its densest fifth of the width, strength vs the frame's background) or None."""
    col = mo["col"]
    k = int(round(t * FPS))
    if k < 12 or k + 4 >= len(col):
        return None
    new = np.clip(col[k:k + 4].max(axis=0) - np.median(col[k - 12:k - 1], axis=0), 0, None)
    tot = new.sum()
    if tot <= 0:
        return None
    W = len(new)
    xs = (np.arange(W) + 0.5) / W
    cx = float((new * xs).sum() / tot)
    f = max(W // 5, 1)
    c = np.convolve(new, np.ones(f), mode="valid")
    conc = float(c.max() / tot)
    strength = float(tot / (np.median(col[k - 12:k - 1].sum(axis=1)) + 1e-6))
    return cx, conc, strength


def check_result(status, summary, details):
    return {"id": "15", "name": "SOUND AUDIT", "status": status, "summary": summary, "details": details}


# ------------------------------------------------------------------ the audit
def audit(a):
    inp = discover(a)
    master = inp["master"]
    dur = dur_of(master)
    tmp = tempfile.mkdtemp(prefix="audit_sound_")
    R, fails = {}, []

    # LOUDNESS
    eb = ac.ffmpeg_ebur128(master)
    I, lra, tp = eb["integrated_lufs"], eb["lra_lu"], eb["true_peak_dbtp"]
    R["loudness"] = {"integrated_lufs": I, "true_peak_dbtp": tp, "lra": lra}
    if I is None or abs(I - RULES["lufs"]) > RULES["lufs_tol"]:
        fails.append("LOUDNESS: integrated %s LUFS, target -14 +-1" % I)
    if tp is None or tp > RULES["tp_max"]:
        fails.append("TRUE PEAK: %s dBTP, ceiling -1.0" % tp)

    # stems + placements
    if inp["mode"] == "mix2":
        stems = {k: os.path.join(inp["stems"], k + ".wav") for k in ("voice", "music", "sfx")}
        placed = mix2_placed(inp)
    else:
        stems, placed = legacy_stems(inp, dur, tmp)
    vf, mf = ac.Features(stems["voice"]), ac.Features(stems["music"])
    vM, mM = vf.momentary(), mf.momentary()
    n = min(len(vM), len(mM))

    # BED_ROWS
    rows = []
    for r0, r1 in speech_rows(inp["words"], vf, dur):
        i0, i1 = int(r0 / ac.HOP_S), min(int(math.ceil(r1 / ac.HOP_S)), n)
        seg = np.arange(i0, i1)
        seg = seg[vM[seg] > -60]
        if len(seg) < 4:
            continue
        lu = float(np.median(vM[seg] - mM[seg]))
        rows.append({"row": [round(float(r0), 2), round(float(r1), 2)], "voice_M": round(float(np.median(vM[seg])), 1),
                     "bed_M": round(float(np.median(mM[seg])), 1), "bed_under_voice_lu": round(lu, 1),
                     "pass": lu >= RULES["bed_under_voice_lu"]})
    bad = [r for r in rows if not r["pass"]]
    R["bed_rows"] = {"rows": rows, "worst_lu": min([r["bed_under_voice_lu"] for r in rows], default=None),
                     "median_lu": round(float(np.median([r["bed_under_voice_lu"] for r in rows])), 1) if rows else None}
    if rows and R["bed_rows"]["median_lu"] > RULES["bed_under_voice_lu_max"]:
        fails.append("BED_TOO_QUIET: bed sits a median %.1f LU under the voice (max %.0f; Sam heard medians of 24-27 as too quiet)"
                     % (R["bed_rows"]["median_lu"], RULES["bed_under_voice_lu_max"]))
    if not rows:
        fails.append("BED_ROWS: no speech rows found to measure")
    elif bad:
        fails.append("BED_ROWS: %d of %d speech rows have the bed less than 12 LU below the voice (worst %.1f LU at %s)"
                     % (len(bad), len(rows), min(r["bed_under_voice_lu"] for r in bad), min(bad, key=lambda r: r["bed_under_voice_lu"])["row"]))

    # SWELLS: lifts of the bed's gain curve must sit inside true pauses (>= 0.4 s) or outside the voice
    # speech is what the voice stem physically does (50 ms VAD, the mixer's own detector), not ASR word stamps
    sp = pauses(inp["words"], vf)
    tt = np.arange(len(sp)) * ac.HOP_S
    ok_lift = np.zeros(len(sp), bool)
    idx = np.where(sp)[0]
    if len(idx):
        ok_lift[:idx[0]] = True; ok_lift[idx[-1] + 1:] = True
    for a0, a1 in ac.runs_of(~sp):
        if (a1 - a0) * ac.HOP_S >= RULES["swell_min_pause_s"]:
            ok_lift[max(0, a0 - 2):a1 + 2] = True       # 0.1 s ramp tolerance either side
    lift = None
    if inp["mode"] == "mix2" and inp.get("music_gain"):
        lift = np.asarray(inp["music_gain"].get("gap_rule_db") or [], float)
    elif inp.get("bed_envelope"):
        be = inp["bed_envelope"]
        if be.get("envelope_db"):
            pts = np.asarray(be["envelope_db"], float)
            lift = np.interp(tt, pts[:, 0], pts[:, 1]) - float(be.get("base_gain_db", np.median(pts[:, 1])))
            lift = lift - float(np.median(lift[sp[:len(lift)]])) if sp.any() else lift
        elif be.get("envelope"):
            pts = np.asarray(be["envelope"], float)
            g = np.interp(tt, pts[:, 0], pts[:, 1])
            lift = 20 * np.log10(np.maximum(g, 1e-4))
    if lift is not None and len(lift):
        L = min(len(lift), len(ok_lift))
        badb = np.where((lift[:L] > RULES["lift_db"]) & ~ok_lift[:L])[0]
        spans = [(round(float(a0 * ac.HOP_S), 2), round(float(a1 * ac.HOP_S), 2)) for a0, a1 in ac.runs_of(np.isin(np.arange(L), badb))]
        R["swells"] = {"lifted_s": round(float((lift[:L] > RULES["lift_db"]).sum() * ac.HOP_S), 2),
                       "lift_outside_true_pause_s": round(len(badb) * ac.HOP_S, 2), "spans": spans[:12],
                       "max_lift_db": round(float(lift[:L].max()), 2)}
        if len(badb):
            fails.append("SWELLS: the bed lifts > 1 dB outside a true pause (>= 0.4 s) for %.2f s, e.g. %s"
                         % (len(badb) * ac.HOP_S, spans[:3]))
    else:
        R["swells"] = {"note": "no gain curve found; not measured"}
        fails.append("SWELLS: no bed gain curve (music_gain.json / bed-envelope.json) to audit")

    # BANNED
    banned = [c["sfx_id"] for c in placed if BANNED.search(c["sfx_id"]) or BANNED.search(c["category"]) or BANNED.search(str(c["event"]))]
    R["banned"] = banned
    if banned:
        fails.append("BANNED: %d glitch/zap/buzz cue(s): %s" % (len(banned), sorted(set(banned))[:5]))

    # DENSITY / OVERLAP
    ev = group_events(placed)
    epm = len(ev) / (dur / 60.0)
    spans = []
    for e in ev:
        ss = [audible_span(c) for c in e["cues"]]
        spans.append((min(s for s, _ in ss), max(t for _, t in ss)))
    pts = sorted([(s, 1) for s, _ in spans] + [(t, -1) for _, t in spans], key=lambda x: (x[0], x[1]))
    cur = peak = 0
    peak_t = None
    for t, dlt in pts:
        cur += dlt
        if cur > peak:
            peak, peak_t = cur, t
    R["density"] = {"cues": len(placed), "events": len(ev), "events_per_min": round(epm, 1),
                    "cues_per_min": round(len(placed) / (dur / 60), 1), "layered_events": sum(1 for e in ev if len(e["cues"]) > 1),
                    "max_overlap": peak, "max_overlap_at_s": round(peak_t, 2) if peak_t is not None else None}
    lo, hi = RULES["density"]
    if not lo <= epm <= hi:
        fails.append("DENSITY: %.1f sound events a minute (rule 20 to 60, P2 runs ~60; %d cues grouped into %d events)" % (epm, len(placed), len(ev)))
    if peak > RULES["max_overlap"]:
        fails.append("OVERLAP: %d sound events sounding at once at %.2f s (rule: at most 3)" % (peak, peak_t))

    # ONSETS: measured landing vs the scene event, frame-exact
    sfx_x = pcm(stems["sfx"]) if inp["mode"] == "mix2" else None
    offs = []
    for c in placed:
        f = clip_facts(c["path"])
        peak_anch = c.get("anchor") == "peak" or any(k in c["category"] for k in PEAK_ANCHORED)
        land = c["placed_at"] + (f["peak"] if peak_anch else f["onset"])
        xc_lag = None
        if sfx_x is not None:                          # confirm on the rendered stem by cross-correlating the clip head
            head = f["x"][int(f["onset"] * SR):int(f["onset"] * SR) + int(0.05 * SR)].mean(axis=1)
            a0 = int((c["placed_at"] + f["onset"] - 0.06) * SR)
            if a0 >= 0 and len(head) > 64 and a0 + len(head) + int(0.12 * SR) < len(sfx_x):
                seg = sfx_x[a0:a0 + len(head) + int(0.12 * SR)].mean(axis=1)
                cc = np.correlate(seg, head, mode="valid")
                xc_lag = (int(np.argmax(np.abs(cc))) - int(0.06 * SR)) / SR
                land += xc_lag
        ev_t = round(float(c["event_t"]) * FPS) / FPS
        off = land - ev_t
        offs.append({"t": round(c["t"], 3), "sfx_id": c["sfx_id"], "event_frame": int(round(ev_t * FPS)),
                     "landed_s": round(land, 4), "offset_ms": round(off * 1000, 1), "anchor": "peak" if peak_anch else "onset",
                     "stem_xcorr_ms": round(xc_lag * 1000, 1) if xc_lag is not None else None,
                     "pass": abs(off) <= RULES["onset_tol_s"]})
    badon = [o for o in offs if not o["pass"]]
    R["onsets"] = {"cues": len(offs), "within_1_frame": len(offs) - len(badon),
                   "worst_ms": max((abs(o["offset_ms"]) for o in offs), default=None), "misses": badon[:15],
                   "median_abs_ms": round(float(np.median([abs(o["offset_ms"]) for o in offs])), 1) if offs else None}
    if badon:
        fails.append("ONSETS: %d of %d cues land more than 1 frame from their scene event (worst %s ms: %s)"
                     % (len(badon), len(offs), max(abs(o["offset_ms"]) for o in badon), max(badon, key=lambda o: abs(o["offset_ms"]))["sfx_id"]))

    # STEREO: picture position vs the sound's lean
    mo = None if a.no_video else motion(master, dur)
    st = []
    if mo is not None:
        # mix2: the SFX stem itself. legacy: the master, baseline-subtracted (the sound's lean = what it adds to each
        # channel over the 250 ms before it), since a legacy build has no rendered SFX stem to read
        au_x = sfx_x if sfx_x is not None else pcm(master)
        for e in ev:
            c = max(e["cues"], key=lambda c: 0 if "sub" in c["category"] else 1)
            ex = event_x(mo, float(c["event_t"]))
            if ex is None or ex[1] < 0.55 or ex[2] < 0.3 or abs(ex[0] - 0.5) < 0.15:
                continue                              # no clearly localised, off-centre new motion at this cue
            s0 = int(audible_span(c)[0] * SR)
            w = au_x[s0:s0 + int(0.12 * SR)]
            if len(w) < 100:
                continue
            eL, eR = float((w[:, 0] ** 2).sum()), float((w[:, 1] ** 2).sum())
            if sfx_x is None:
                pre = au_x[max(0, s0 - int(0.25 * SR)):max(0, s0 - int(0.13 * SR))]
                eL, eR = max(eL - float((pre[:, 0] ** 2).sum()), 0.0), max(eR - float((pre[:, 1] ** 2).sum()), 0.0)
            if eL + eR < 1e-7:
                continue
            bal = 10 * math.log10(max(eR, 1e-12) / max(eL, 1e-12))     # + = leans right
            want = 1 if ex[0] > 0.5 else -1
            st.append({"t": round(e["t"], 2), "picture_x": round(ex[0], 2), "sound_lean_db": round(bal, 1),
                       "pass": (bal * want) >= 1.0})
    good = sum(1 for s in st if s["pass"])
    R["stereo"] = {"localised_events": len(st), "matching": good, "rows": st}
    if len(st) >= 3 and good / len(st) < RULES["stereo_min_match"]:
        fails.append("STEREO: only %d of %d off-centre events lean toward their picture position (rule >= 70%%)" % (good, len(st)))

    R["mode"], R["master"], R["duration_s"] = inp["mode"], master, round(dur, 2)
    R["rules"] = {k: list(v) if isinstance(v, tuple) else v for k, v in RULES.items()}
    R["fails"] = fails
    R["status"] = "FAIL" if fails else "PASS"
    summ = ("; ".join(fails) if fails else
            "I %.1f LUFS, TP %.1f dBTP; bed worst row %.1f LU under voice; %.1f events/min, max overlap %d; %d/%d onsets within 1 frame; stereo %d/%d"
            % (I, tp, R["bed_rows"]["worst_lu"], epm, peak, len(offs) - len(badon), len(offs), good, len(st)))
    return R, summ


def check(master, build=None):
    """gate entry point for produce.py (kit check 15)."""
    ns = argparse.Namespace(master=master, build=build, voice=None, bed=None, cues=None, words=None, stems=None, no_video=False)
    try:
        R, summ = audit(ns)
    except SystemExit as e:
        return check_result("FAIL", "audit could not run: %s" % e, {})
    return check_result(R["status"], summ, R)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("master")
    ap.add_argument("--build")
    ap.add_argument("--voice"); ap.add_argument("--bed"); ap.add_argument("--cues"); ap.add_argument("--words"); ap.add_argument("--stems")
    ap.add_argument("--no-video", action="store_true", help="skip the picture-based stereo check (wav masters)")
    ap.add_argument("--json", help="write the full report here")
    a = ap.parse_args()
    if a.master.endswith(".wav"):
        a.no_video = True
    R, summ = audit(a)
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        json.dump(R, open(a.json, "w"), indent=1)
    L = R["loudness"]; D = R["density"]; O = R["onsets"]; B = R["bed_rows"]; S = R["stereo"]
    print("SOUND AUDIT (%s) %s" % (R["mode"], R["master"]))
    print("  loudness   I %s LUFS  TP %s dBTP" % (L["integrated_lufs"], L["true_peak_dbtp"]))
    print("  bed rows   %d rows, worst %s LU, median %s LU under the voice (rows >= 12, median 12-18, target 15)" % (len(B["rows"]), B["worst_lu"], B["median_lu"]))
    print("  swells     %s" % json.dumps({k: v for k, v in R["swells"].items() if k != "spans"}))
    print("  density    %s cues -> %s events, %s events/min (rule 20-60), %s layered; max overlap %s at %ss (rule <= 3)"
          % (D["cues"], D["events"], D["events_per_min"], D["layered_events"], D["max_overlap"], D["max_overlap_at_s"]))
    print("  onsets     %s/%s within 1 frame; median |off| %s ms, worst %s ms" % (O["within_1_frame"], O["cues"], O["median_abs_ms"], O["worst_ms"]))
    print("  stereo     %s/%s off-centre events lean the right way" % (S["matching"], S["localised_events"]))
    print("  banned     %s" % (R["banned"] or "none"))
    for f in R["fails"]:
        print("  FAIL  " + f)
    print("OVERALL %s" % R["status"])
    sys.exit(1 if R["status"] == "FAIL" else 0)


if __name__ == "__main__":
    main()
