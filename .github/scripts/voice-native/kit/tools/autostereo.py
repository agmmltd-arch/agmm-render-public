#!/usr/bin/env python3
"""autostereo.py <ID> [--dry]  (root, 7 Oct 2026)

Gate check 15 (STEREO) fails when an off-centre sound event leans away from where its picture is. The gate already
measures both: for every localised event it records t, picture_x (0..1) and the sound's lean. This tool reads the
failing rows from the newest GATE.json, finds the spec cue that fires at that time (its '@word' anchor resolved through
out/<ID>/resolved.json words), and sets the cue's x to the measured picture position. Deterministic, no model.
A cue is moved only when its recorded onset uniquely identifies it at the gate's 0.01 s precision, or when exactly
one cue is within the legacy 0.25 s window. Indistinguishable candidates are reported, not guessed.
Backups live in out/<ID>/spec-archive, outside the reviewed source tree. Unresolved events refuse the whole write;
already-mapped source is reported separately from repairs. Rebuild + resubmit afterwards; master PASS is a later gate.
"""
import glob, json, os, shutil, sys, time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def candidate_cues(cues, event_time):
    # audit_sound.py records round(event['t'], 2): this is the authored onset, not an inferred audio peak.
    # Nearby layers/gestures must not hide a uniquely recorded onset (S09 26.234, S87 31.231).
    exact = [(abs(t - event_time), bid, cue) for t, bid, cue in cues if round(t, 2) == round(event_time, 2)]
    return exact or [(abs(t - event_time), bid, cue) for t, bid, cue in cues if abs(t - event_time) <= 0.25]


def main():
    sid = sys.argv[1]; dry = "--dry" in sys.argv
    gates = sorted(glob.glob(os.path.join(KIT, "out", sid, "gate", "*", "GATE.json")), key=os.path.getmtime)
    if not gates:
        print("no GATE.json for", sid); return 2
    g = json.load(open(gates[-1]))
    c15 = [c for c in g.get("checks", []) if str(c.get("id")) == "15"]
    rows = [r for r in ((c15[0].get("details") or {}).get("stereo") or {}).get("rows", []) if not r.get("pass")] if c15 else []
    if not rows:
        print("%s: no failing stereo rows in %s" % (sid, gates[-1])); return 0
    res = json.load(open(os.path.join(KIT, "out", sid, "resolved.json")))
    # Use the build's resolver: numeric seconds, beat-relative offsets, indexed words
    # and word-end anchors must mean exactly what they mean in the render package.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from build_short import Resolver
    resolver = Resolver(res.get("words") or [])
    starts = {b.get("id"): b.get("from") for b in res.get("beats", [])}

    sp_path = os.path.join(KIT, "specs", sid, "spec.json")
    with open(sp_path, "rb") as fh:
        original = fh.read()
    spec = json.loads(original)
    cues = []
    for b in spec.get("beats", []):
        for cue in b.get("sfx", []) or []:
            try:
                t = resolver.t(cue.get("at"), starts.get(b.get("id")))
            except (SystemExit, ValueError, TypeError, IndexError, KeyError):
                continue
            cues.append((t, b.get("id"), cue))
    changed, already, unresolved = [], [], []
    for r in rows:
        near = candidate_cues(cues, r["t"])
        if len(near) != 1:
            print("  t=%.2f: %d cues within 0.25 s, not moved" % (r["t"], len(near)))
            unresolved.append(r["t"]); continue
        _, bid, cue = near[0]
        if "pan" in cue:
            print("  t=%.2f: explicit pan overrides x; manual resolution required, not moved" % r["t"])
            unresolved.append(r["t"]); continue
        if not 0 <= float(r["picture_x"]) <= 1:
            print("  t=%.2f: invalid picture_x, not moved" % r["t"])
            unresolved.append(r["t"]); continue
        new_x = int(round(float(r["picture_x"]) * 1080))
        if cue.get("x") == new_x:
            print("  t=%.2f beat %s: x already %d; old master still needs verification" % (r["t"], bid, new_x))
            already.append(r["t"]); continue
        print("  t=%.2f beat %s cue %s %s: x %s -> %d (picture_x %.2f, sound leaned %+.1f dB)"
              % (r["t"], bid, cue.get("kind"), cue.get("at"), cue.get("x"), new_x, r["picture_x"], r.get("sound_lean_db", 0)))
        if not dry:
            cue["x"] = new_x
        changed.append(r["t"])
    if unresolved and not dry:
        print("REFUSED: %d unresolved events; source not written; master PASS not established" % len(unresolved))
        return 1
    if changed and not dry:
        with open(sp_path, "rb") as fh:
            if fh.read() != original:
                print("REFUSED: source changed concurrently; nothing written"); return 1
        archive = os.path.join(KIT, "out", sid, "spec-archive", "autostereo-" + time.strftime("%Y%m%d-%H%M%S") + "-" + str(time.time_ns()))
        os.makedirs(archive)
        shutil.copy2(sp_path, os.path.join(archive, "spec.json"))
        with open(sp_path, "w") as fh:
            json.dump(spec, fh, indent=2, ensure_ascii=False)
    print("%s: %d changed, %d already mapped, %d unresolved of %d failing events%s; master PASS not established"
          % (sid, len(changed), len(already), len(unresolved), len(rows), " (dry)" if dry else ""))
    return 1 if unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
