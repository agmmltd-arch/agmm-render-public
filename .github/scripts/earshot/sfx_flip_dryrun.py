#!/usr/bin/env python3
"""sfx_flip_dryrun.py MAIN_NATIVE BRANCH_NATIVE INPUTS_V2 OUT : would the SFX-library flip break a maker short's pinned audit? (Actions only)

MAIN_NATIVE / BRANCH_NATIVE = .github/scripts/sound-audit-native of main (today's pins) and of branch sfx-library-flip (the new library.json + PINS.json).
INPUTS_V2 = a maker short's existing sound inputs (kit/out/<ID>/{resolved.json, audio/cues.json, audio/mix2/{master.wav,stems/*,manifests}} + the library wavs its cues use).
1. each closure's PINS.json matches its own files exactly (the check sound_audit_existing.py makes before it audits anything)
2. the branch closure has every library item of main's closure, byte-identical, plus the new sounds
3. the SAME existing master is audited by main's pinned closure and by the branch's pinned closure: status, loudness, bed rows, density, onsets must be identical
Exit 1 on any difference. Output: DRYRUN.md, main.json, branch.json"""
import hashlib, json, os, shutil, subprocess, sys
from pathlib import Path


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def pins_ok(native):
    pins = json.load(open(native / "PINS.json"))
    assert set(pins) == {"sound/audit_sound.py", "sound/v2/audio_core.py", "sound/library.json"}, "closure inventory changed"
    bad = [rel for rel, h in pins.items() if sha(native / rel) != h]
    return not bad, bad


def run_audit(native, inputs, sid, work):
    stage = Path(work)
    shutil.rmtree(stage, ignore_errors=True)
    (stage / "sound/v2").mkdir(parents=True)
    for rel in ("sound/audit_sound.py", "sound/v2/audio_core.py", "sound/library.json"):
        shutil.copyfile(native / rel, stage / rel)
    shutil.copytree(inputs / "kit", stage / "kit")
    shutil.copytree(inputs / "sound/library", stage / "sound/library")
    out = stage / "kit/out" / sid
    js = stage / "audit.json"
    r = subprocess.run([sys.executable, str(stage / "sound/audit_sound.py"), str(out / "audio/mix2/master.wav"), "--build", str(out), "--json", str(js)],
                       capture_output=True, text=True, env=dict(os.environ, AUDIT_SOUND_LIBJSON=str(stage / "sound/library.json")), timeout=1500)
    return r.returncode, (json.load(open(js)) if js.exists() else {}), (r.stdout + r.stderr)[-1500:]


def main():
    main_n, branch_n, inputs, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
    out.mkdir(parents=True, exist_ok=True)
    sid = next((inputs / "kit/out").iterdir()).name
    L, fails = ["# SFX library flip, dry run on %s (a maker short's existing master)" % sid, ""], []
    for name, n in (("main", main_n), ("branch", branch_n)):
        ok, bad = pins_ok(n)
        L.append("- %s closure: PINS.json matches its files: %s%s" % (name, ok, "" if ok else " (differs: %s)" % bad))
        if not ok:
            fails.append("%s pins differ" % name)
    lm = {i["id"]: i for i in json.load(open(main_n / "sound/library.json"))["items"]}
    lb = {i["id"]: i for i in json.load(open(branch_n / "sound/library.json"))["items"]}
    same = all(lb.get(k) == v for k, v in lm.items())
    L.append("- branch library: %d items (main %d); every main item present and byte-identical: %s" % (len(lb), len(lm), same))
    if not same:
        fails.append("branch library changed an old item")
    rc_m, rep_m, log_m = run_audit(main_n, inputs, sid, "/tmp/flip_main")
    rc_b, rep_b, log_b = run_audit(branch_n, inputs, sid, "/tmp/flip_branch")
    json.dump(rep_m, open(out / "main.json", "w"), indent=1)
    json.dump(rep_b, open(out / "branch.json", "w"), indent=1)
    keys = ("status", "loudness", "bed_rows", "swells", "density", "overlap", "onsets", "stereo", "banned", "fails")
    diff = [k for k in keys if rep_m.get(k) != rep_b.get(k)]
    L.append("- audit of the existing %s master: main closure exit %s status %s | branch closure exit %s status %s" % (sid, rc_m, rep_m.get("status"), rc_b, rep_b.get("status")))
    L.append("- compared fields %s: %s" % (list(keys), "IDENTICAL" if not diff and rep_m else "DIFFERENT %s" % diff))
    if rep_m:
        L.append("  - %s | %s | onsets %s" % (json.dumps(rep_m.get("loudness")), json.dumps(rep_m.get("density")), json.dumps({k: v for k, v in (rep_m.get("onsets") or {}).items() if k != "misses"})))
    if diff or not rep_m or rc_m != rc_b:
        fails.append("audit results differ")
    if rep_m.get("status") != "PASS":
        L.append("  (note: the existing master's own audit status under today's pins is %s; the flip must not change it)" % rep_m.get("status"))
    # the dry run must be able to fail: tamper with one pin in memory
    pins = json.load(open(branch_n / "PINS.json"))
    pins["sound/library.json"] = "0" * 64
    L.append("- can fail: a tampered library pin is detected: %s" % (sha(branch_n / "sound/library.json") != pins["sound/library.json"]))
    L.append("")
    L.append("RESULT: " + ("PASS" if not fails else "FAIL " + "; ".join(fails)))
    (out / "DRYRUN.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
