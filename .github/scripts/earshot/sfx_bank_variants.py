#!/usr/bin/env python3
"""sfx_bank_variants.py - many unique takes of earshot's code-made bank for the roles the format engine cues (Actions only; no models for rendering).

Sam: every video unique. A licensed Openverse pool alone is too small for a hard "no file in more than one of five shorts" cap on dense roles (ticks), so the
bank is rendered on many seeds (same character, new noise / micro-timing: bank.render(id, seed=N)), each take audited by earshot (`sfx check`), peak-normalised
to -1 dBTP, measured (onset / peak / end), and scored against every role phrase with earshot `match` (z, cosine) exactly like the Openverse sounds.
Output: <out>/wav/<id>.wav, <out>/accepted.json (schema of sfx_analyse.py + "roles"), <out>/summary.json. Licence: MIT (earshot), made in code.
"""
import hashlib, json, re, sys
from pathlib import Path
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
ROLES = json.load(open(HERE / "sfxlib" / "roles.json"))
# role -> (bank id prefixes, takes wanted, roles it serves)
PLAN = {
    "tick": (["pro_hover_tick/", "pro_click/", "tap/", "click/", "knock/"], 220, ["tick"]),
    "whoosh": (["whoosh_fast/", "swish/", "whoosh_big/"], 70, ["whoosh"]),
    "pop": (["ui_pop/", "pro_pop_in/"], 70, ["pop"]),
    "hit": (["cut_hit/", "knock/", "pro_impact/"], 120, ["stamp", "impact"]),
    "ding": (["notify/", "mallet/glock"], 60, ["ding"]),
    "typing": (["typing_key/"], 90, ["typing"]),
    "riser": (["riser/"], 45, ["riser"]),
}


def main():
    out = Path(sys.argv[1])
    (out / "wav").mkdir(parents=True, exist_ok=True)
    from earshot import api, features
    from earshot.forge import bank
    phrases = sorted({q for v in ROLES.values() for q in [v["desc"]] + list(v.get("alt") or [])})
    role_q = {k: [v["desc"]] + list(v.get("alt") or []) for k, v in ROLES.items()}
    acc, skipped = [], {"audit": 0, "none": 0}
    for key, (prefixes, want, serves) in PLAN.items():
        members = [e["id"] for e in bank.list() if any(e["id"].startswith(p) for p in prefixes)]
        members = sorted(members)[:8]
        if not members:
            skipped["none"] += 1
            print("no bank member for", key)
            continue
        per = max(1, -(-want // len(members)))
        n = 0
        for mid in members:
            for seed in range(1, per + 1):
                try:
                    y, meta = bank.render(mid, seed=1000 + seed)
                except Exception as e:      # noqa: BLE001
                    skipped["audit"] += 1
                    continue
                if meta.get("checks"):
                    skipped["audit"] += 1
                    continue
                y = np.asarray(y, np.float64)
                y = y if y.ndim == 1 else y.mean(axis=1)
                tp = features.true_peak_dbtp(np.stack([y, y], axis=1).astype(np.float32))
                if tp > -1.0:
                    y = y * 10 ** ((-1.0 - tp) / 20)
                sid = "es2_%s_%s_%04d" % (key, re.sub(r"[^a-z0-9]+", "", mid.lower())[:18], seed)
                wav = out / "wav" / (sid + ".wav")
                sf.write(str(wav), y.astype(np.float32), 48000, subtype="PCM_24")
                m = api.measure(str(wav), light=True)
                et = features.envelope_times(y)
                xs = np.stack([y, y], axis=1).astype(np.float32)
                _, L50 = features.loudness_curve(xs, 0.05, 0.005)
                ms = api.match(str(wav), phrases)
                rows = {r["query"]: r for r in ms["results"]}
                scores = {}
                for k, qs in role_q.items():
                    bq = max(qs, key=lambda q: rows[q]["z"])
                    scores[k] = {"z": rows[bq]["z"], "cosine": rows[bq]["cosine"], "query": bq, "verdict": rows[bq]["verdict"]}
                for role in serves:
                    acc.append({"id": sid, "role": role, "roles": serves, "file": sid + ".wav", "duration_s": round(len(y) / 48000, 4), "onset_ms": round(et["attack_at"] * 1000, 1),
                                "peak_ms": round(et["peak_at"] * 1000, 1), "end_ms": round(len(y) / 48000 * 1000, 1), "lufs": m.get("lufs"), "l50_lufs": round(float(L50.max()), 1),
                                "true_peak_db": m.get("true_peak_dbtp"), "role_match": {"query": scores[role]["query"], "z": scores[role]["z"], "cosine": scores[role]["cosine"], "verdict": scores[role]["verdict"]},
                                "scores": scores, "sha256_trim": hashlib.sha256(wav.read_bytes()).hexdigest(), "bank_member": mid, "seed": 1000 + seed,
                                "source": {"licence_slug": "mit", "licence": "MIT (earshot 0.4.0), made in code", "provider": "earshot-bank", "title": mid}})
                n += 1
        print("%-7s %d takes from %d members" % (key, n, len(members)), flush=True)
    json.dump(acc, open(out / "accepted.json", "w"), indent=1)
    json.dump({"takes": len({a["id"] for a in acc}), "entries": len(acc), "skipped": skipped}, open(out / "summary.json", "w"))
    print("SUMMARY", len({a["id"] for a in acc}), "takes,", len(acc), "role entries,", skipped)


if __name__ == "__main__":
    main()
