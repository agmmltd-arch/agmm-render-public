#!/usr/bin/env python3
"""sfx_thin_check.py DIR OUT : "thin-vs-pilots", a check that can fail instead of a human listen (Actions only).

Reference = the library sounds in the approved pilots P1-P3 and the S05 mix (DIR/ref/*.wav, ref_roles.json id -> role). Every library sound (DIR/lib/**.wav,
id_roles.json "id@role" -> role) is trimmed the way the audit hears it (onset = first sample >= 6% of peak, end = 30 dB under the peak, <= 1.5 s) and measured:
  fullness   = energy share 80-1000 Hz (dB re the whole sound): body
  harshness  = energy share 3-10 kHz (dB re the whole sound): bite / hiss
  plus earshot `measure` (bandwidth, centroid, rolloff95, flatness = noise-vs-tone, tonal peak), centroid spread over 25 ms frames, attack (10-90 %), decay (-30 dB)
Rule: a sound is unusable when fullness < the reference's 10th percentile or harshness > its 90th ("thin-vs-pilots" / "harsh-vs-pilots").
Percentiles are per role when the reference has >= 8 sounds of that role, else pooled over all reference sounds.
Output: metrics.json, ref_stats.json, verdict.json {id@role: {usable, reason, fullness, harshness}}, SHOWCASE.md (3 thinnest sounds fail, 3 pilot sounds pass, with numbers)."""
import json, sys
from pathlib import Path
import numpy as np
import soundfile as sf

SR = 48000


def load_mono(p):
    x, sr = sf.read(str(p), dtype="float64", always_2d=True)
    x = x.mean(axis=1)
    if sr != SR:
        import soxr
        x = soxr.resample(x, sr, SR)
    return x


def trim(x):
    m = np.abs(x)
    pk = float(m.max()) if len(m) else 0.0
    if pk <= 0:
        return x
    on = int(np.argmax(m >= 0.06 * pk))
    w = int(0.005 * SR)
    k = len(x) // w
    e = 20 * np.log10(np.sqrt((x[: k * w].reshape(k, w) ** 2).mean(axis=1)) + 1e-12)
    ok = np.where(e >= e.max() - 30.0)[0]
    end = min(len(x), (int(ok[-1]) + 1) * w) if len(ok) else len(x)
    end = min(end, on + int(1.5 * SR))
    return x[on: max(end, on + int(0.02 * SR))]


def shares(x):
    n = 1 << 15
    X = np.abs(np.fft.rfft(x, n)) ** 2
    f = np.fft.rfftfreq(n, 1 / SR)
    tot = float(X.sum()) + 1e-30
    band = lambda a, b: 10 * np.log10(float(X[(f >= a) & (f < b)].sum()) / tot + 1e-12)
    return band(80, 1000), band(3000, 10000)


def frames_centroid_spread(x):
    w, h = int(0.025 * SR), int(0.0125 * SR)
    cs = []
    for s in range(0, max(1, len(x) - w), h):
        seg = x[s: s + w]
        if len(seg) < w // 2 or np.abs(seg).max() < 1e-4:
            continue
        P = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 2048)) ** 2
        f = np.fft.rfftfreq(2048, 1 / SR)
        cs.append(float((f * P).sum() / (P.sum() + 1e-30)))
    return float(np.std(cs)) if len(cs) > 1 else 0.0


def measure(x, features):
    t = trim(x)
    full, harsh = shares(t)
    xs = np.stack([t, t], axis=1).astype(np.float32)
    m = features.measure(xs, light=True)
    et = features.envelope_times(t)
    return {"duration_s": round(len(t) / SR, 3), "fullness_db": round(full, 2), "harshness_db": round(harsh, 2), "bandwidth_hz": m.get("bandwidth_hz"), "centroid_hz": m.get("centroid_hz"),
            "rolloff95_hz": m.get("rolloff95_hz"), "flatness": m.get("flatness"), "tonal_peak_ratio_db": m.get("tonal_peak_ratio_db"),
            "centroid_spread_hz": round(frames_centroid_spread(t), 1), "attack_ms": et.get("attack_ms"), "decay_ms": et.get("decay_ms")}


def pct(v, q):
    return float(np.percentile(v, q)) if len(v) else None


def main():
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    from earshot import features
    ref_roles = json.load(open(root / "ref_roles.json"))
    id_roles = json.load(open(root / "id_roles.json"))
    ref = {}
    for p in sorted((root / "ref").glob("*.wav")):
        ref[p.stem] = dict(measure(load_mono(p), features), role=ref_roles.get(p.stem))
    lib = {}
    for p in sorted((root / "lib").rglob("*.wav")):
        lib[p.stem] = measure(load_mono(p), features)
    pooled = {"fullness_p10": pct([r["fullness_db"] for r in ref.values()], 10), "harshness_p90": pct([r["harshness_db"] for r in ref.values()], 90), "n": len(ref)}
    stats = {"pooled": pooled, "roles": {}}
    for role in sorted({r["role"] for r in ref.values() if r["role"]}):
        rs = [r for r in ref.values() if r["role"] == role]
        stats["roles"][role] = {"n": len(rs), "fullness_p10": pct([r["fullness_db"] for r in rs], 10), "harshness_p90": pct([r["harshness_db"] for r in rs], 90),
                                "fullness_median": pct([r["fullness_db"] for r in rs], 50), "used": len(rs) >= 8}

    def limits(role):
        s = stats["roles"].get(role)
        return (s["fullness_p10"], s["harshness_p90"], role) if s and s["used"] else (pooled["fullness_p10"], pooled["harshness_p90"], "pooled")

    def judge(m, role):
        lo, hi, basis = limits(role)
        if m["fullness_db"] < lo:
            return False, "thin-vs-pilots", "fullness %.1f dB < pilot p10 %.1f dB (%s)" % (m["fullness_db"], lo, basis)
        if m["harshness_db"] > hi:
            return False, "harsh-vs-pilots", "harshness %.1f dB > pilot p90 %.1f dB (%s)" % (m["harshness_db"], hi, basis)
        return True, None, None
    verdict = {}
    for key, role in id_roles.items():
        sid = key.split("@")[0]
        if sid not in lib:
            continue
        ok, why, detail = judge(lib[sid], role)
        verdict[key] = {"usable": ok, "reason": why, "detail": detail, "fullness_db": lib[sid]["fullness_db"], "harshness_db": lib[sid]["harshness_db"]}
    pilot_v = {sid: judge(m, m["role"]) for sid, m in ref.items() if m["role"]}
    json.dump({"ref": ref, "lib": lib}, open(out / "metrics.json", "w"), indent=0)
    json.dump(stats, open(out / "ref_stats.json", "w"), indent=1)
    json.dump(verdict, open(out / "verdict.json", "w"), indent=0)
    bad = sorted([(v["fullness_db"], k) for k, v in verdict.items() if not v["usable"] and v["reason"] == "thin-vs-pilots"])[:3]
    good = [(sid, m) for sid, m in ref.items() if pilot_v.get(sid, (False,))[0]][:3]
    L = ["# thin-vs-pilots", "", "reference: %d pilot / S05 sounds; pooled p10 fullness %.1f dB, p90 harshness %.1f dB" % (len(ref), pooled["fullness_p10"], pooled["harshness_p90"]),
         "pilot sounds passing their own rule: %d of %d (10%% sit below their own p10 by construction)" % (sum(1 for v in pilot_v.values() if v[0]), len(pilot_v)),
         "library: %d sound-role pairs judged, %d unusable (%d thin, %d harsh)" % (len(verdict), sum(1 for v in verdict.values() if not v["usable"]), sum(1 for v in verdict.values() if v["reason"] == "thin-vs-pilots"), sum(1 for v in verdict.values() if v["reason"] == "harsh-vs-pilots")), "",
         "## three thinnest library sounds (the check fails them)"]
    for f, k in bad:
        m = lib[k.split("@")[0]]
        L.append("- %s: fullness %.1f dB, bandwidth %s Hz, centroid %s Hz, rolloff95 %s Hz, flatness %s -> %s" % (k, f, m["bandwidth_hz"], m["centroid_hz"], m["rolloff95_hz"], m["flatness"], verdict[k]["detail"]))
    L += ["", "## three pilot cues (the check passes them)"]
    for sid, m in good:
        L.append("- %s (%s): fullness %.1f dB, harshness %.1f dB, bandwidth %s Hz, centroid %s Hz -> pass" % (sid, m["role"], m["fullness_db"], m["harshness_db"], m["bandwidth_hz"], m["centroid_hz"]))
    (out / "SHOWCASE.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    print("REF STATS", json.dumps(stats))


if __name__ == "__main__":
    main()
