#!/usr/bin/env python3
"""craft_metrics.py: the per-short numbers the scoreboard and better_than_last.py share (one definition, two users).

READ-ONLY on the kit. Every number comes from a file the kit or a reviewer already wrote, or from the short's own
storyboard snap frames (read, never written):
  pre-render (exists once `produce.py <ID> --only build` and `storyboard.py submit` ran):
    beats            out/<ID>/resolved.json beats: count, median and max length (s), beats a minute
    snap density     out/<ID>/snap/<ID>-*/frame-*.png|jpg (the storyboard frames): median / 10th-percentile / min
                     coverage (share of pixels > 18 grey levels from the frame median, check 14's measure) and detail
    cues             out/<ID>/audio/cues.json: cues a minute, share of cues panned off centre (|pan| >= 0.1)
    voice            shorts/voice/<ID>/RESULT.json final: naturalness, flow, pace, emphasis (3-run listen), wpm
  post-render (once gated):
    critic           latest GATE.json check 9 scores (hook, clarity, story, pacing, visuals, sound, cta)
    density          latest GATE.json check 14 coverage / detail (1 frame per 2 s of the master)
    static           latest GATE.json check 3 longest static span
    sound            latest GATE.json check 15 (or out/<ID>/audio audit json): bed worst row LU, events a minute,
                     stereo matched / localised
    seams            out/<ID>/seam_check.json if a writer or reviewer ran tools/seam_check.py --json
"""
import glob
import json
import os
import re

V2 = os.path.expanduser("~/alfred/builds/video-program-2026-09-23/v2")
KIT = os.path.join(V2, "kit")

CRITIC_KEYS = [("hook_strength_first_3s", "hook"), ("clarity_no_context_needed", "clarity"), ("story", "story"),
               ("pacing", "pacing"), ("visual_quality_and_variety", "visuals"), ("sound_design", "sound"), ("cta", "cta")]


def _load(p, default=None):
    try:
        return json.load(open(p))
    except Exception:
        return default


def beats(ID):
    r = _load(os.path.join(KIT, "out", ID, "resolved.json"))
    if not r or not r.get("beats"):
        return {}
    lens = sorted(float(b["to"]) - float(b["from"]) for b in r["beats"])
    dur = float(r.get("dur") or (r["beats"][-1]["to"]))
    return {"beats": len(lens), "beat_len_median_s": round(lens[len(lens) // 2], 2), "beat_len_max_s": round(lens[-1], 2),
            "beats_per_min": round(len(lens) / dur * 60, 1) if dur else None, "duration_s": round(dur, 1)}


def snap_frames(ID):
    base = os.path.join(KIT, "out", ID, "snap")
    out = []
    for d in sorted(glob.glob(os.path.join(base, ID + "-*"))):
        if not os.path.isdir(d):
            continue
        fs = sorted(glob.glob(os.path.join(d, "frame-*.png")) + glob.glob(os.path.join(d, "frame-*.jpg")))
        out += fs
    return out


def snap_density(ID, max_frames=48):
    """check 14's coverage/detail measure over the storyboard frames (what the art director judged)."""
    fs = snap_frames(ID)
    if not fs:
        return {}
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return {"snap_error": "numpy/PIL missing"}
    if len(fs) > max_frames:
        step = len(fs) / float(max_frames)
        fs = [fs[int(i * step)] for i in range(max_frames)]
    cov, det = [], []
    for f in fs:
        try:
            im = Image.open(f).convert("L").resize((270, 480))
        except Exception:
            continue
        x = np.asarray(im, dtype=np.int16)
        cov.append(float((np.abs(x - np.median(x)) > 18).mean()))
        det.append(float(np.abs(np.diff(x, axis=1)).mean()))
    if not cov:
        return {}
    c = sorted(cov)
    return {"snap_frames": len(cov), "snap_cov_median": round(c[len(c) // 2], 3),
            "snap_cov_p10": round(c[max(0, int(len(c) * 0.1) - 0)], 3) if len(c) >= 10 else round(c[0], 3),
            "snap_cov_min": round(c[0], 3), "snap_detail_median": round(sorted(det)[len(det) // 2], 2),
            "snap_share_cov_ge_0.25": round(sum(1 for v in cov if v >= 0.25) / len(cov), 2)}


def cues(ID):
    d = _load(os.path.join(KIT, "out", ID, "audio", "cues.json"))
    if not d or not d.get("cues"):
        return {}
    cs = sorted(d["cues"], key=lambda c: float(c.get("t") or 0))
    dur = beats(ID).get("duration_s") or 60.0
    # Claude 5 Oct: count DISTINCT sound events, not raw cues. Makers were adding a 'companion' cue 0.13 s after every cue,
    # panned the other way, to lift cues_per_min (S83 hit 200/min): metric gaming, not foley (the craft standard: one designed
    # sound per on-screen event, panned TOWARD its object). Cues starting within 0.25 s of the previous event's first cue merge
    # into that event; pan share is judged on each event's first cue; a mirrored pair (opposite pan within 0.25 s) is counted.
    events, mirrored = [], 0
    for c in cs:
        t = float(c.get("t") or 0)
        if events and t - events[-1]["t"] < 0.25:
            first = events[-1]["first"]
            p0, p1 = float(first.get("pan") or 0), float(c.get("pan") or 0)
            if abs(p0) >= 0.1 and abs(p1) >= 0.1 and (p0 > 0) != (p1 > 0):
                mirrored += 1
            continue
        events.append({"t": t, "first": c})
    n = len(events) or 1
    panned = sum(1 for e in events if abs(float(e["first"].get("pan") or 0)) >= 0.1)
    return {"cues": len(cs), "sound_events": len(events), "cues_per_min": round(len(events) / dur * 60, 1),
            "cue_pan_share": round(panned / n, 2), "mirrored_pairs": mirrored}


def voice(ID):
    r = _load(os.path.join(V2, "shorts", "voice", ID, "RESULT.json"))
    if not r or not r.get("final"):
        return {}
    f = r["final"]
    out = {}
    for k in ("naturalness", "flow", "pace", "emphasis"):
        if isinstance(f.get(k), (int, float)):
            out["voice_" + k] = f[k]
    if f.get("wpm_speaking_final"):
        out["voice_wpm"] = f["wpm_speaking_final"]
    vals = [out[k] for k in ("voice_naturalness", "voice_flow", "voice_pace", "voice_emphasis") if k in out]
    if vals:
        out["voice_mean"] = round(sum(vals) / len(vals), 2)
    return out


def gate_list(ID):
    seen = {}
    d = os.path.join(KIT, "out", ID)
    for f in glob.glob(os.path.join(d, "gate", "r*", "GATE.json")) + [os.path.join(d, "GATE.json")]:
        g = _load(f)
        if not g:
            continue
        seen.setdefault(g.get("generated_at") or f, (f, g))
    return [v for _, v in sorted(seen.items(), key=lambda kv: kv[0] or "")]


def critic_from(g):
    for c in g.get("checks", []):
        if str(c.get("id")) == "9":
            sc = {}
            for line in c.get("details", []):
                m = re.match(r"(\w+):\s*([\d.]+)$", str(line).strip())
                if m:
                    sc[m.group(1)] = float(m.group(2))
            out = {"critic_" + short: sc[k] for k, short in CRITIC_KEYS if k in sc}
            if out:
                out["critic_mean"] = round(sum(out.values()) / len(out), 2)
            return out
    return {}


def gate_metrics(ID):
    gl = gate_list(ID)
    if not gl:
        return {}
    out = {"gate_rounds": len(gl), "gate_first_pass": gl[0][1].get("overall") == "PASS",
           "gate_last": gl[-1][1].get("overall"), "gate_last_at": gl[-1][1].get("generated_at")}
    # critic: the latest round that has scores (quota-outs leave none)
    for f, g in reversed(gl):
        c = critic_from(g)
        if c:
            out.update(c)
            out["critic_at"] = g.get("generated_at")
            break
    g = gl[-1][1]
    for c in g.get("checks", []):
        cid, summ = str(c.get("id")), c.get("summary", "")
        if cid == "14":
            m = re.search(r"coverage ([\d.]+), detail ([\d.]+)", summ)
            if m:
                out["density_cov"], out["density_detail"] = float(m.group(1)), float(m.group(2))
        elif cid == "3":
            spans = [float(x) for x in re.findall(r"\(([\d.]+)s\)", " ".join(map(str, c.get("details", []))))]
            if spans:
                out["static_max_s"] = max(spans)
        elif cid == "15":
            m = re.search(r"bed worst row ([\d.]+) LU", summ)
            if m:
                out["bed_worst_lu"] = float(m.group(1))
            m = re.search(r"([\d.]+) events/min", summ)
            if m:
                out["sfx_events_per_min"] = float(m.group(1))
            m = re.search(r"stereo (\d+)/(\d+)", summ)
            if m and int(m.group(2)):
                out["stereo_match"] = round(int(m.group(1)) / int(m.group(2)), 2)
                out["stereo_n"] = int(m.group(2))
        elif cid == "11":
            m = re.search(r"median lapvar ([\d.]+)", summ)
            if m:
                out["sharpness"] = float(m.group(1))
    return out


def seam_metrics(ID):
    d = _load(os.path.join(KIT, "out", ID, "seam_check.json"))
    if not d:
        return {}
    bad = d.get("fails") or d.get("bad") or []
    n = d.get("seams") or d.get("checked")
    out = {"seam_fail_frames": len(bad) if isinstance(bad, list) else bad}
    if isinstance(n, int):
        out["seams_checked"] = n
    return out


def all_metrics(ID, with_snap=True):
    m = {}
    m.update(beats(ID))
    if with_snap:
        m.update(snap_density(ID))
    m.update(cues(ID))
    m.update(voice(ID))
    m.update(gate_metrics(ID))
    m.update(seam_metrics(ID))
    return m


# direction: +1 higher is better, -1 lower is better; tolerance for "behind"
DIRECTIONS = {
    "beats_per_min": (1, 1.0), "beat_len_max_s": (-1, 0.5),
    "snap_cov_median": (1, 0.03), "snap_cov_p10": (1, 0.03), "snap_share_cov_ge_0.25": (1, 0.05),
    "snap_detail_median": (1, 0.3),
    "cues_per_min": (1, 3.0), "cue_pan_share": (1, 0.1),
    # Claude 5 Oct: single model-scored dimensions get the measured judge noise as tolerance (orchestrator wisdom Part 8:
    # free-lane critic scores moved +-0.5..2 across identical runs); 0.3 let noise hold S40 at voice_emphasis 8.0 vs 8.33.
    # The averaged critic_mean keeps 0.2.
    # root 5 Oct 19:20: the Gemini listening critic scores identical audio 6/9/6 (S36) and 9/7/7 (S92); a 3-run mean moves ~1
    # point on noise alone, so 0.5 held voices on noise. Single dims 1.25, the 4-dim mean 1.0. Absolute 6.5 floor, robotic
    # votes and voice_lead_check (ASR, pace, stutter) stay hard. Decision: 06-Decisions/content/2026-10-05 Voice critic tolerance.
    "voice_naturalness": (1, 1.25), "voice_flow": (1, 1.25), "voice_emphasis": (1, 1.25), "voice_mean": (1, 1.0),
    "critic_hook": (1, 0.5), "critic_clarity": (1, 0.5), "critic_story": (1, 0.5), "critic_pacing": (1, 0.5),
    "critic_visuals": (1, 0.5), "critic_sound": (1, 0.5), "critic_cta": (1, 0.5), "critic_mean": (1, 0.2),
    "density_cov": (1, 0.03), "density_detail": (1, 0.3), "static_max_s": (-1, 0.2),
    "stereo_match": (1, 0.1), "seam_fail_frames": (-1, 0.5),
}
LABELS = {
    "beats_per_min": "beats a minute (P1: 16 in 59 s = 16.3)", "beat_len_max_s": "longest beat (s)",
    "snap_cov_median": "storyboard frame fill, median", "snap_cov_p10": "storyboard frame fill, emptiest 10%",
    "snap_share_cov_ge_0.25": "share of storyboard frames >= 25% filled", "snap_detail_median": "storyboard detail",
    "cues_per_min": "sound cues a minute", "cue_pan_share": "share of cues panned toward an object",
    "voice_naturalness": "voice naturalness", "voice_flow": "voice flow", "voice_emphasis": "voice emphasis",
    "voice_mean": "voice listen mean", "critic_hook": "critic: hook", "critic_clarity": "critic: clarity",
    "critic_story": "critic: story", "critic_pacing": "critic: pacing", "critic_visuals": "critic: visuals",
    "critic_sound": "critic: sound", "critic_cta": "critic: CTA", "critic_mean": "critic mean",
    "density_cov": "master frame fill (check 14)", "density_detail": "master detail (check 14)",
    "static_max_s": "longest static span (check 3)", "stereo_match": "stereo cues matching picture (check 15)",
    "seam_fail_frames": "seam_check low frames",
}
