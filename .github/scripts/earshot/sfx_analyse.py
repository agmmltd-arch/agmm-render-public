#!/usr/bin/env python3
"""sfx_analyse.py - judge Openverse sound-effect candidates for ONE role with earshot (MIT; CPU; no paid call). Runs on Actions only.

For each candidate in sfxlib/candidates.json[role]: download the provider's file (sha256 of the SOURCE bytes recorded), decode to 48 kHz mono,
find the real sound (earshot `find` on a long file, then onset / decay trimming), measure it (earshot `measure`: LUFS, true peak, onset / peak / end),
describe it (earshot `describe`: calibrated tags with z, AudioSet labels) and score it against every role's description (earshot `match`: z, cosine).
REJECT (reason recorded) a music bed, a voice, clipping, long silence, a noise bed, a sound that is too quiet, too sustained for the role, off-role,
undecodable or undownloadable. Accepted sounds are cut to the sound (4 ms before the attack, a 15 ms fade-out), peak-normalised to -1 dBFS, written as wav.
Rules and numbers: sfxlib/rules.json. Output: <out>/wav/<id>.wav, <out>/accepted.json, <out>/rejected.json, <out>/summary.json
"""
import argparse, hashlib, json, os, signal, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
LIB = HERE / "sfxlib"
RULES = json.load(open(LIB / "rules.json"))
UA = "AGMM-sfx-library/1.0 (agmm.co.uk; licence-gated sound effects; earshot analysis)"


def download(url, tries=6):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read(RULES["max_source_bytes"] + 1)
            if len(data) > RULES["max_source_bytes"]:
                return None, "too big"
            return data, None
        except Exception as e:      # noqa: BLE001
            last = str(e)[:80]
            time.sleep((12 + 10 * i) if "429" in last else (2 + 3 * i))      # providers throttle parallel runners: back off properly
    return None, last


def frames_db(x, sr, ms=1):
    n = max(1, int(sr * ms / 1000))
    k = len(x) // n
    r = np.sqrt((x[: k * n].reshape(k, n) ** 2).mean(axis=1) + 1e-14)
    return 20 * np.log10(r)


def judge(c, role, spec, api, work, role_descs):
    """-> (accepted record | None, reason | None, detail)"""
    from earshot import features
    cid = "ov_%s_%s" % (role, c["openverse_id"][:8])
    data, err = download(c["source_url"])
    if data is None:
        return None, "download-failed", err
    src = Path(work) / ("src." + (c.get("filetype") or "mp3"))
    src.write_bytes(data)
    sha_src = hashlib.sha256(data).hexdigest()
    full = Path(work) / "full.wav"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-ac", "1", "-ar", "48000", "-c:a", "pcm_s24le", str(full)], capture_output=True, text=True)
    if r.returncode or not full.exists():
        return None, "undecodable", r.stderr[-80:]
    x, sr = sf.read(str(full), dtype="float64")
    dur = len(x) / sr
    if dur < 0.04:
        return None, "too-short", "%.0f ms" % (dur * 1000)
    if np.abs(x).max() < 10 ** (RULES["min_peak_dbfs"] / 20):
        return None, "too-quiet", "peak %.0f dBFS" % (20 * np.log10(np.abs(x).max() + 1e-12))
    # 1. where is the sound: earshot `find` on a long file, else the whole file
    a0, b0 = 0.0, dur
    found = None
    if dur > RULES["find_over_factor"] * spec["max_s"]:
        try:
            fr = api.find(str(full), spec["desc"], top=1)
            if fr["segments"]:
                found = fr["segments"][0]
                a0, b0 = max(0.0, found["start"] - 0.05), min(dur, found["end"] + 0.05)
        except Exception as e:      # noqa: BLE001
            return None, "find-failed", str(e)[:80]
    seg = x[int(a0 * sr): int(b0 * sr)]
    env = frames_db(seg, sr, 1)
    pk_db = float(env.max())
    on_i = int(np.argmax(env >= pk_db - 20.0))                 # first ms within 20 dB of the loudest
    start = a0 + max(0.0, on_i / 1000 - 0.004)
    # 2. end of the sound: last ms within 30 dB of the peak, capped at the role's longest one-shot
    end_i = len(env) - 1 - int(np.argmax(env[::-1] >= pk_db - 30.0))
    end = a0 + (end_i + 1) / 1000
    if end - start > spec["max_s"]:
        cap = start + spec["max_s"]
        tail = frames_db(x[int(max(start, cap - 0.05) * sr): int(cap * sr)], sr, 5)
        if len(tail) and float(tail.mean()) > pk_db - RULES["sustained_db"]:
            return None, "sustained", "still %.0f dB under peak at the %.1f s cap" % (pk_db - float(tail.mean()), spec["max_s"])
        end = cap
    if end - start < 0.04:
        return None, "too-short", "%.0f ms of sound" % ((end - start) * 1000)
    # 3. bed: the level around the sound must be far under it (a continuous background is not a one-shot)
    pre = frames_db(x[int(max(0, start - 0.35) * sr): int(max(0, start - 0.02) * sr)], sr, 10)
    post = frames_db(x[int(end * sr): int(min(dur, end + 0.35) * sr)], sr, 10)
    around = np.concatenate([pre, post]) if len(pre) + len(post) else np.array([-120.0])
    if len(around) >= 6 and pk_db - float(np.median(around)) < RULES["bed_margin_db"]:
        return None, "noise-bed", "only %.0f dB over its surroundings" % (pk_db - float(np.median(around)))
    clip = x[int(start * sr): int(end * sr)]
    # 4. clipping on the source (before normalising)
    n_clip = int(np.sum(np.abs(clip) >= 0.999))
    tp = features.true_peak_dbtp(clip.astype(np.float32).reshape(-1, 1).repeat(2, axis=1)) if len(clip) > 8 else -99
    if n_clip > RULES["max_clipped_samples"] or tp > RULES["max_source_true_peak_dbtp"]:
        return None, "clipping", "%d samples at full scale, %.1f dBTP" % (n_clip, tp)
    # 5. long silence inside the sound
    e5 = frames_db(clip, sr, 5)
    run = best = 0
    for v in (e5 < pk_db - RULES["silence_db"]):
        run = run + 1 if v else 0
        best = max(best, run)
    if best * 0.005 > RULES["max_inner_silence_s"]:
        return None, "long-silence", "%.2f s of silence inside" % (best * 0.005)
    # 6. write the trimmed, peak-normalised sound
    g = 10 ** ((RULES["peak_target_dbfs"] - 20 * np.log10(np.abs(clip).max() + 1e-12)) / 20)
    y = clip * g
    tp1 = features.true_peak_dbtp(y.astype(np.float32).reshape(-1, 1).repeat(2, axis=1))
    if tp1 > RULES["peak_target_dbfs"]:                      # normalise the TRUE peak (inter-sample) to the target, not just the sample peak
        g *= 10 ** ((RULES["peak_target_dbfs"] - tp1) / 20)
        y = clip * g
    fo = min(len(y) // 4, int(0.015 * sr))
    y[-fo:] *= np.linspace(1, 0, fo)
    wav = Path(work) / (cid + ".wav")
    sf.write(str(wav), y.astype(np.float32), sr, subtype="PCM_24")
    # 7. earshot ears on the trimmed sound
    m = api.measure(str(wav), light=True)
    xs = np.stack([y, y], axis=1).astype(np.float32)
    t50, L50 = features.loudness_curve(xs, 0.05, 0.005)
    d = api.describe(str(wav))
    audioset = d.get("audioset") or []

    def ap(names):
        return max([a["p"] for a in audioset if any(n in a["label"].lower() for n in names)] or [0.0])
    p_music, p_voice = ap(["music"]), ap(["speech", "narration", "conversation", "singing", "voice", "talk"])
    if p_music >= RULES["max_music_p"]:
        return None, "music-bed", "AudioSet music %.2f" % p_music
    if p_voice >= RULES["max_voice_p"]:
        return None, "voice", "AudioSet speech/voice %.2f" % p_voice
    phrases = sorted({q for v in role_descs.values() for q in v})
    ms = api.match(str(wav), phrases)
    rows = {r_["query"]: r_ for r_ in ms["results"]}
    scores = {}
    for k, v in role_descs.items():
        best_q = max(v, key=lambda q: rows[q]["z"])
        scores[k] = {"z": rows[best_q]["z"], "cosine": rows[best_q]["cosine"], "query": best_q, "verdict": rows[best_q]["verdict"]}
    own = {"z": scores[role]["z"], "cosine": scores[role]["cosine"], "verdict": scores[role]["verdict"]}
    if own["z"] < RULES["role_min_z"]:
        return None, "off-role", "best role phrase '%s' z %.1f (%s)" % (scores[role]["query"], own["z"], own["verdict"])
    env_t = features.envelope_times(y)
    rec = {"id": cid, "role": role, "file": cid + ".wav", "duration_s": round(len(y) / sr, 4), "onset_ms": round(env_t["attack_at"] * 1000, 1),
           "peak_ms": round(env_t["peak_at"] * 1000, 1), "end_ms": round(len(y) / sr * 1000, 1), "attack_ms": env_t.get("attack_ms"), "decay_ms": env_t.get("decay_ms"),
           "lufs": m.get("lufs"), "l50_lufs": round(float(L50.max()), 1), "true_peak_db": m.get("true_peak_dbtp"), "peak_dbfs": m.get("peak_dbfs"),
           "gain_applied_db": round(20 * np.log10(g), 2), "trim": {"from_s": round(start, 3), "to_s": round(end, 3), "source_s": round(dur, 3),
                                                                   "found_z": found and found["z"], "found_verdict": found and found["verdict"]},
           "description": d.get("summary", "")[:400], "top_tags": [{"term": t["term"], "z": t["z"]} for t in (d.get("top_tags") or [])[:3]],
           "audioset": audioset[:4], "role_match": {"query": scores[role]["query"], "z": own["z"], "cosine": own["cosine"], "verdict": own["verdict"]},
           "scores": scores, "p_music": round(p_music, 3), "p_voice": round(p_voice, 3), "sha256_source": sha_src, "sha256_trim": hashlib.sha256(wav.read_bytes()).hexdigest(),
           "source": {k: c[k] for k in ("openverse_id", "title", "source_url", "landing_url", "provider", "licence_slug", "licence", "licence_url", "creator", "attribution", "query", "duration_ms")}}
    return (rec, wav), None, None


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--role", required=True)
    ap_.add_argument("--out", required=True)
    ap_.add_argument("--limit", type=int, default=0)
    a = ap_.parse_args()
    roles = json.load(open(LIB / "roles.json"))
    cands = json.load(open(LIB / "candidates.json")).get(a.role, [])
    cands = [c for c in cands if c["licence_slug"] in ("cc0", "pdm", "by", "by-sa")]       # never NC / ND / unknown, checked again here
    if a.limit:
        cands = cands[: a.limit]
    spec = roles[a.role]
    role_descs = {k: [v["desc"]] + list(v.get("alt") or []) for k, v in roles.items()}
    out = Path(a.out)
    (out / "wav").mkdir(parents=True, exist_ok=True)
    from earshot import api
    acc, rej = [], []
    for i, c in enumerate(cands):
        with tempfile.TemporaryDirectory() as work:
            signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("candidate took over 180 s")))
            signal.alarm(180)       # one stuck download / decode never holds the role job
            try:
                res, why, detail = judge(c, a.role, spec, api, work, role_descs)
            except BaseException as e:      # noqa: BLE001
                res, why, detail = None, "error", "%s: %s" % (type(e).__name__, str(e)[:100])
            finally:
                signal.alarm(0)
            if res:
                rec, wav = res
                (out / "wav" / wav.name).write_bytes(wav.read_bytes())
                acc.append(rec)
            else:
                rej.append({"id": "ov_%s_%s" % (a.role, c["openverse_id"][:8]), "reason": why, "detail": detail, "title": c.get("title"), "landing_url": c.get("landing_url"), "licence": c.get("licence")})
        print("[%s %d/%d] %s %s" % (a.role, i + 1, len(cands), "ACCEPT" if res else "reject", (res[0]["id"] if res else "%s (%s)" % (why, detail))), flush=True)
    reasons = {}
    for r in rej:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    json.dump(acc, open(out / "accepted.json", "w"), indent=1)
    json.dump(rej, open(out / "rejected.json", "w"), indent=1)
    json.dump({"role": a.role, "candidates": len(cands), "accepted": len(acc), "rejected": len(rej), "reasons": reasons}, open(out / "summary.json", "w"), indent=1)
    print("SUMMARY", a.role, len(cands), "candidates,", len(acc), "accepted,", reasons)
    return 0


if __name__ == "__main__":
    sys.exit(main())
