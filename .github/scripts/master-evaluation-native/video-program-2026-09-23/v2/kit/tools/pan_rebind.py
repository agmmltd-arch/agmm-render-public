#!/usr/bin/env python3
"""pan_rebind.py - the AUDIO-PAN-ONLY approval class (FINISHER for root, 13 Oct 2026).

Gate check 15 (stereo) and better_than_last's stereo_match hold shorts whose picture was approved and whose only defect is
that a sound cue sits on the wrong side. tools/autostereo.py resolves those deterministically (it sets a cue's x to the
picture position the gate measured). A cue's x is a pan: it changes the mix, never a pixel the reviewer approved. So the
approval may survive such a change, and ONLY such a change:

  check <old_dir> <new_dir>   the diff checker. PASS only when every hashed spec file is byte-identical except spec.json,
                              and spec.json differs ONLY in beats[i].sfx[j].x numeric values (an x added to a cue counts).
                              Any other change (one character of text, a timing, a cue added/removed, a new key, a file
                              added/removed) FAILS. Exit 0 PASS, 1 FAIL.
  apply <ID> [--no-build]     preconditions: storyboard approved and the spec on disk == approved_hash. Snapshots the spec
                              (out/<ID>/spec-archive/panrebind-<ts>/before, outside the reviewed tree), runs autostereo.py
                              (refuses if any failing event is unresolved), runs `check` on before vs now; on PASS rebinds
                              the approval (approved_hash/spec_hash -> new hash, approver unchanged, a `rebinds` entry with the
                              evidence), writes the evidence to out/<ID>/gate/autostereo-<ts>.json and specs/<ID>/STATE.md,
                              then rebuilds the package (produce.py --only build via heavy.py). On FAIL the spec is restored.
  verify <ID>                 re-checks the newest rebind: snapshot hash == its `from`, `to` == the spec on disk == approved_hash,
                              and `check` PASS between the snapshot and the spec on disk. machine_pass runs this.
No model decides anything here. Exit 0 ok, 1 refused, 2 usage."""
import copy
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from storyboard import ARCHIVE_RX  # noqa: E402

REG = os.path.join(KIT, "registry", "storyboards")
EXTS = (".json", ".js", ".css", ".html", ".svg")


def hashed_files(d):
    """the files storyboard.spec_hash covers (same filter), relpath -> abspath"""
    out = {}
    for f in sorted(glob.glob(os.path.join(d, "**", "*"), recursive=True)):
        rel = os.path.relpath(f, d)
        if os.path.isfile(f) and f.endswith(EXTS) and "receipt" not in f and os.path.basename(f) != "concept.json" \
                and not os.path.basename(f).startswith("ref-watch") and not ARCHIVE_RX.search(rel):
            out[rel] = f
    return out


def hash_dir(d):
    h = hashlib.sha256()
    for rel, f in sorted(hashed_files(d).items()):
        h.update(rel.encode()); h.update(open(f, "rb").read())
    return h.hexdigest()


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _walk(a, b, path, diffs, problems):
    allowed_x = len(path) == 5 and path[0] == "beats" and path[2] == "sfx" and path[4] == "x"
    if allowed_x:
        if (a is None or _num(a)) and _num(b) and 0 <= b <= 1080:
            if a != b:
                diffs.append({"path": "beats[%d].sfx[%d].x" % (path[1], path[3]), "old": a, "new": b})
            return
        problems.append("%s: %r -> %r is not a numeric pan within 0..1080" % (_p(path), a, b)); return
    if type(a) is not type(b) and not (_num(a) and _num(b)):
        problems.append("%s: type %s -> %s" % (_p(path), type(a).__name__, type(b).__name__)); return
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in b:
                problems.append("%s: key removed" % _p(path + [k]))
            elif k not in a:
                if len(path) == 4 and path[0] == "beats" and path[2] == "sfx" and k == "x":
                    _walk(None, b[k], path + [k], diffs, problems)
                else:
                    problems.append("%s: key added" % _p(path + [k]))
            else:
                _walk(a[k], b[k], path + [k], diffs, problems)
    elif isinstance(a, list):
        if len(a) != len(b):
            problems.append("%s: list length %d -> %d" % (_p(path), len(a), len(b))); return
        for i, (x, y) in enumerate(zip(a, b)):
            _walk(x, y, path + [i], diffs, problems)
    elif a != b:
        problems.append("%s: %r -> %r" % (_p(path), str(a)[:60], str(b)[:60]))


def _p(path):
    return "".join("[%d]" % x if isinstance(x, int) else ("." + x if i else x) for i, x in enumerate(path))


def check(old_dir, new_dir):
    """(ok, x_changes, problems)"""
    a, b = hashed_files(old_dir), hashed_files(new_dir)
    problems, diffs = [], []
    for rel in sorted(set(a) - set(b)):
        problems.append("file removed: %s" % rel)
    for rel in sorted(set(b) - set(a)):
        problems.append("file added: %s" % rel)
    for rel in sorted(set(a) & set(b)):
        ba, bb = open(a[rel], "rb").read(), open(b[rel], "rb").read()
        if ba == bb:
            continue
        if rel != "spec.json":
            problems.append("%s changed (only spec.json cue x may change)" % rel); continue
        try:
            ja, jb = json.loads(ba), json.loads(bb)
        except ValueError as e:
            problems.append("spec.json unparseable: %s" % e); continue
        _walk(ja, jb, [], diffs, problems)
    if not problems and not diffs and a.keys() == b.keys():
        problems.append("no change at all (nothing to rebind)")
    return (not problems), diffs, problems


def _rec(sid):
    return json.load(open(os.path.join(REG, sid + ".json")))


def _write_rec(sid, rec):
    p = os.path.join(REG, sid + ".json")
    tmp = p + ".tmp-panrebind"
    json.dump(rec, open(tmp, "w"), indent=1)
    os.replace(tmp, p)


def _state_note(sid, text):
    p = os.path.join(KIT, "specs", sid, "STATE.md")
    with open(p, "a") as fh:
        fh.write("\n\n## autostereo + audio-pan-only rebind, %s (pan_rebind.py, mechanical)\n%s\n" % (time.strftime("%Y-%m-%d %H:%M"), text))


def apply(sid, build=True):
    rec = _rec(sid)
    spec_dir = os.path.join(KIT, "specs", sid)
    if rec.get("state") != "approved":
        print("REFUSED: %s storyboard is %r, not approved" % (sid, rec.get("state"))); return 1
    before_hash = hash_dir(spec_dir)
    if before_hash != rec.get("approved_hash"):
        print("REFUSED: %s spec on disk %s is not the approved spec %s (only an approved spec can be rebound)" % (
            sid, before_hash[:12], str(rec.get("approved_hash"))[:12])); return 1
    ts = time.strftime("%Y%m%d-%H%M%S")
    arch = os.path.join(KIT, "out", sid, "spec-archive", "panrebind-" + ts)
    snap = os.path.join(arch, "before")
    for rel, f in hashed_files(spec_dir).items():
        os.makedirs(os.path.dirname(os.path.join(snap, rel)), exist_ok=True)
        shutil.copy2(f, os.path.join(snap, rel))
    if hash_dir(snap) != before_hash:
        print("REFUSED: snapshot hash differs from the spec it copied"); return 1
    r = subprocess.run([sys.executable, os.path.join(KIT, "tools", "autostereo.py"), sid], capture_output=True, text=True, cwd=KIT)
    log = (r.stdout + r.stderr).strip()
    print(log)
    if r.returncode != 0:
        _state_note(sid, "autostereo could not resolve every failing stereo event, so nothing was written and the short stays with the maker:\n```\n%s\n```" % log)
        return 1
    after_hash = hash_dir(spec_dir)
    if after_hash == before_hash:
        print("%s: autostereo changed nothing; no rebind" % sid); return 1
    ok, diffs, problems = check(snap, spec_dir)
    if not ok:
        shutil.copy2(os.path.join(snap, "spec.json"), os.path.join(spec_dir, "spec.json"))   # restore the approved spec (autostereo kept its own backup too)
        print("REFUSED: the change is not audio-pan-only; the approved spec.json was restored:\n  " + "\n  ".join(problems)); return 1
    ev = {"id": sid, "class": "audio-pan-only", "from": before_hash, "to": after_hash, "snapshot": os.path.relpath(snap, KIT),
          "x_changes": diffs, "autostereo": log.splitlines(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
          "by": "pan_rebind.py (mechanical, no model)", "approver_kept": rec.get("by")}
    rec.setdefault("rebinds", []).append(ev)
    rec["approved_hash"] = after_hash
    rec["spec_hash"] = after_hash
    rec.setdefault("history", []).append({"at": time.strftime("%H:%M:%S"), "date": time.strftime("%Y-%m-%d"), "state": "approved",
                                          "rebind": "audio-pan-only %s -> %s" % (before_hash[:12], after_hash[:12])})
    _write_rec(sid, rec)
    os.makedirs(os.path.join(KIT, "out", sid, "gate"), exist_ok=True)
    json.dump(ev, open(os.path.join(KIT, "out", sid, "gate", "autostereo-%s.json" % ts), "w"), indent=1)
    json.dump(ev, open(os.path.join(arch, "REBIND.json"), "w"), indent=1)
    _state_note(sid, "Approval kept under the audio-pan-only class (approver %s): %s -> %s. Cue x changes: %s. Evidence: out/%s/gate/autostereo-%s.json. "
                "Next: rebuilt package, Actions render, gate, machine pass." % (
                    rec.get("by"), before_hash[:12], after_hash[:12], "; ".join("%s %s->%s" % (d["path"], d["old"], d["new"]) for d in diffs), sid, ts))
    print("REBOUND %s audio-pan-only %s -> %s (%d x changes)" % (sid, before_hash[:12], after_hash[:12], len(diffs)))
    if build:
        b = subprocess.run([sys.executable, os.path.join(KIT, "tools", "heavy.py"), "--lane", "build", "--", sys.executable, "produce.py", sid, "--only", "build"],
                           capture_output=True, text=True, cwd=KIT)
        print((b.stdout + b.stderr).strip()[-600:])
        if b.returncode:
            print("BUILD FAILED rc=%s (the rebind stands; re-run produce.py %s --only build)" % (b.returncode, sid)); return 1
    return 0


def verify(sid):
    rec = _rec(sid)
    rb = (rec.get("rebinds") or [])
    if not rb:
        print("%s: no rebinds" % sid); return 0
    last = rb[-1]
    snap = os.path.join(KIT, last["snapshot"])
    probs = []
    if not os.path.isdir(snap) or hash_dir(snap) != last["from"]:
        probs.append("snapshot missing or its hash is not the rebind's `from`")
    cur = hash_dir(os.path.join(KIT, "specs", sid))
    if not (last["to"] == cur == rec.get("approved_hash")):
        probs.append("rebind `to` %s, spec on disk %s, approved_hash %s disagree" % (last["to"][:12], cur[:12], str(rec.get("approved_hash"))[:12]))
    if os.path.isdir(snap):
        ok, _d, p2 = check(snap, os.path.join(KIT, "specs", sid))
        if not ok:
            probs += p2
    prev = rb[-2]["to"] if len(rb) > 1 else None
    if prev and prev != last["from"]:
        probs.append("rebind chain broken: previous `to` %s != this `from` %s" % (prev[:12], last["from"][:12]))
    print("verify %s: %s" % (sid, "PASS" if not probs else "FAIL: " + "; ".join(probs)))
    return 0 if not probs else 1


def main(a):
    if len(a) >= 3 and a[0] == "check":
        ok, diffs, problems = check(a[1], a[2])
        for d in diffs:
            print("  pan %s: %s -> %s" % (d["path"], d["old"], d["new"]))
        print("audio-pan-only check: %s" % ("PASS (%d x change(s))" % len(diffs) if ok else "FAIL\n  " + "\n  ".join(problems)))
        return 0 if ok else 1
    if len(a) >= 2 and a[0] == "apply":
        return apply(a[1].upper(), build="--no-build" not in a)
    if len(a) >= 2 and a[0] == "verify":
        return verify(a[1].upper())
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
