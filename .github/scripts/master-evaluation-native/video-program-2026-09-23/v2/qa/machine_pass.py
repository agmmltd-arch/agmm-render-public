#!/usr/bin/env python3
"""machine_pass.py <ID> [--check] [--prepare] [--arm] [--v2 ROOT] [--json]        (conductor card, root, 6 Oct 2026)

A MACHINE MASTER PASS: the review-log PASS that arming needs when no Claude reviewer is available to look at the finished master.

Why it is safe to issue one: the LOOK of a short is judged by a Claude reviewer at the STORYBOARD (registry approval by root / sonnet-* /
opus-*), and the master is a deterministic render of that approved spec (hosted Actions run, bound by hash). What is left after the
render is mechanical, and every piece of it is a check that can fail. This tool issues the pass ONLY when ALL of these hold, each
read from its own file and re-verified now (no trusting a summary, no cached verdict without its own sha):

   1 storyboard   state approved, approved by a KNOWN CLAUDE reviewer (validate_release.known_claude_reviewer: root, claude-root,
                  sonnet-*, opus-*; never a crew persona, never "machine:") who is not the short's maker; approved_hash == the spec
                  hash on disk; validate_release.master_from_approved_spec PASS
   2 package      the master's sha256 equals a COLLECTED.json of a hosted run whose REQUEST carries the approved hash and the sha of
                  build/source.tar.gz; that tarball is still the build the lint saw (member-by-member fingerprint of build/pkg)
   3 gate         newest GATE.json on THIS master (size, time, video sha): overall PASS, every one of the 15 checks PASS, except
                  check 9 (the advisory free-quota critic) may be UNJUDGED / quota, as root_pass.py has always allowed; any other
                  non-PASS only with a ROOT-WAIVER.json bound to that gate's bytes (validate_release.root_waived)
   4 voice        shorts/voice/<ID>/<ID>.voicelead.json verdict PASS, no fails, written after the take (wav, words.json, RESULT.json),
                  the mix built after the take, voice source bound to the script (voice_script_binding)
   5 dom_lint     out/<ID>/domlint/result.json 0 FAIL, and BOUND.json (written by this tool's lint wrapper) says the lint ran on the exact
                  build/pkg fingerprint that rendered this master
   6 sound        audit_sound.py on this master (through heavy.py, cached per master sha) PASS
   7 better       tools/better_than_last.py <ID> --strict PASS (no --exception-file)
   8 concept      concept_check library PASS (same call storyboard submit makes) or a recorded root waiver covering every failed rule
   9 release      captions item present for every platform, banned CTA absent from captions + script + resolved words + voice words,
                  script unchanged since the captions (or a root source_rebind chain ending at the current sha), bed not banned
  10 validator    the exact validate_release.reviewer_approval + check_row that arm_ready will run, on the proposed card + review entry

On success: RECEIPT.json (sealed, evidence path + sha for every check) in kit/out/<ID>/machine-pass/, the card "Ready to post", a review-log
PASS with reviewer "machine:<approver>" (same shape as root_pass.py), and with --arm the arm_ready pass for this short. Without a Claude approver
on the storyboard nothing is issued, ever. It never edits a video, a spec, or anyone else's card.

  --check     run checks 1-9 (+ the validator when a receipt exists) and print the table; write nothing except evidence caches
  --prepare   collect the slow evidence only (audit_sound through heavy.py, dom_lint on Actions with fingerprint binding), then exit
Exit 0 issued/ok, 1 refused (reasons printed), 2 usage.  Python 3.9 compatible."""
from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BANNED_BEDS = ("local-forecast", "airport-lounge")          # kit/build_short.py refuses them (Sam 6 Oct 02:30)
SKIP_NAMES = (".DS_Store", "__MACOSX")
CLAUDE_APPROVER_NOTE = "root, claude-root, sonnet-*, opus-*"


class Ctx(object):
    def __init__(self, v2=None):
        self.v2 = os.path.abspath(v2 or os.path.dirname(HERE))
        self.build = os.path.dirname(self.v2)
        self.kit = os.path.join(self.v2, "kit")
        self.qa = os.path.join(self.v2, "qa")
        self.ap = os.path.join(self.v2, "autoposter")

    def out(self, sid):
        return os.path.join(self.kit, "out", sid)

    def rel(self, p):
        return os.path.relpath(p, self.build)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jload(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def mt(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def dir_fingerprint(root):
    """sha256 over sorted (relative path, file sha256) of every regular file under root (build/pkg)."""
    rows = []
    for dp, dn, fn in os.walk(root):
        dn[:] = sorted(d for d in dn if d not in SKIP_NAMES and not d.startswith("._"))
        for f in sorted(fn):
            if f in SKIP_NAMES or f.startswith("._"):
                continue
            p = os.path.join(dp, f)
            if os.path.isfile(p) and not os.path.islink(p):
                rows.append((os.path.relpath(p, root).replace(os.sep, "/"), sha256(p)))
    return hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest(), len(rows)


def tar_fingerprint(tar_path):
    rows = []
    with tarfile.open(tar_path) as tf:
        for m in tf:
            if not m.isreg():
                continue
            name = m.name[2:] if m.name.startswith("./") else m.name
            base = name.rsplit("/", 1)[-1]
            if base in SKIP_NAMES or base.startswith("._"):
                continue
            h = hashlib.sha256()
            fh = tf.extractfile(m)
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
            rows.append((name, h.hexdigest()))
    return hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest(), len(rows)


class Report(object):
    def __init__(self, sid):
        self.sid = sid
        self.checks = []
        self.evidence = []
        self.notes = []

    def add(self, name, ok, detail, evidence=None, needs_prepare=False):
        # needs_prepare (FINISHER 13 Oct): True only when the check failed because its evidence is MISSING or STALE, which --prepare
        # can produce. A FAIL read from fresh evidence is a defect in the short; re-running --prepare cannot change it.
        self.checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:400], "needs_prepare": bool(needs_prepare) and not ok})
        for e in evidence or []:
            self.evidence.append(e)
        return bool(ok)

    @property
    def ok(self):
        return bool(self.checks) and all(c["ok"] for c in self.checks)

    def failed(self):
        return [c for c in self.checks if not c["ok"]]


def ev(ctx, path, immutable=True, what=""):
    try:
        return {"path": ctx.rel(path), "sha256": sha256(path), "immutable": immutable, "what": what}
    except OSError:
        return {"path": ctx.rel(path), "sha256": None, "immutable": False, "what": what + " (missing)"}


# ------------------------------------------------------------------------------------------------------------ the checks
def c_storyboard(ctx, vr, R, sid, master):
    sbp = os.path.join(ctx.kit, "registry", "storyboards", sid + ".json")
    sb = jload(sbp, {}) or {}
    by = str(sb.get("by") or "")
    q = jload(os.path.join(ctx.kit, "registry", "queue.json"), {}) or {}
    maker = str((q.get(sid) or {}).get("writer") or "")
    R.add("storyboard_approved", sb.get("state") == "approved" and bool(sb.get("approved_hash")),
          "state=%r approved_hash=%s" % (sb.get("state"), str(sb.get("approved_hash"))[:16]))
    plain = not by.lower().startswith("machine:")
    R.add("storyboard_approver_is_known_claude", plain and vr.known_claude_reviewer(by),
          "approved by %r: only %s may stand behind a machine pass (a crew persona, an unknown name or a machine pass may not)" % (by, CLAUDE_APPROVER_NOTE))
    R.add("storyboard_approver_is_not_maker", bool(by) and by.lower() != maker.lower(),
          "approver=%r maker(queue writer)=%r" % (by, maker))
    ok_spec, why = vr.master_from_approved_spec(sid, master)
    R.add("master_from_approved_spec", ok_spec, why)
    # the approved hash must equal the hash of the spec on disk right now (the validator also does this; show it with both values)
    try:
        sbm = load_module(os.path.join(ctx.kit, "tools", "storyboard.py"), "mp_storyboard")
        cur = sbm.spec_hash(sid)
        R.add("spec_hash_equals_approved_hash", cur == sb.get("approved_hash"), "disk %s approved %s" % (cur[:16], str(sb.get("approved_hash"))[:16]))
    except SystemExit:
        R.add("spec_hash_equals_approved_hash", False, "storyboard.spec_hash exited")
    except Exception as exc:  # noqa: BLE001
        R.add("spec_hash_equals_approved_hash", False, "cannot hash the spec: %s" % exc)
    # FINISHER 13 Oct: an approval rebound under the audio-pan-only class (kit/tools/pan_rebind.py) stands only while its evidence does:
    # the snapshot still hashes to the approved `from`, and the spec on disk differs from it only in cue x values.
    if sb.get("rebinds"):
        rv = subprocess.run([sys.executable, os.path.join(ctx.kit, "tools", "pan_rebind.py"), "verify", sid], capture_output=True, text=True, cwd=ctx.kit, timeout=120)
        R.add("pan_rebind_chain_verified", rv.returncode == 0, (rv.stdout + rv.stderr).strip()[-300:])
    return sb, by, maker


def c_no_hold(ctx, vr, R, sid, master):
    """A reviewer's later HOLD / RETURN / NOT FINAL on this master is never overridden by a machine."""
    rows = jload(os.path.join(ctx.qa, "review-log.json"), []) or []
    rows = rows if isinstance(rows, list) else rows.get("reviews", [])
    last = vr.latest_review(sid, rows)
    if not last:
        R.add("no_reviewer_hold_on_this_master", True, "no review-log entry for %s yet" % sid)
        return
    at = vr.parse_local(last.get("at"))
    from datetime import datetime
    changed = datetime.fromtimestamp(mt(master))
    held = (not vr.clean_pass(last.get("verdict"))) and at is not None and (at - changed).total_seconds() >= -90
    R.add("no_reviewer_hold_on_this_master", not held, ("latest review %s by %s at %s: %r is newer than the master" % (
        sid, last.get("reviewer"), last.get("at"), str(last.get("verdict"))[:80])) if held else
        "latest review: %s %r at %s (not a hold on this master)" % (last.get("reviewer"), str(last.get("verdict"))[:40], last.get("at")))


def c_package(ctx, R, sid, master, msha, sb):
    out = ctx.out(sid)
    cols = glob.glob(os.path.join(out, "cloud-dispatch", "*", "COLLECTED.json"))
    hit = None
    for c in cols:
        d = jload(c, {}) or {}
        if d.get("sha256") == msha:
            hit = c
            break
    if not hit:
        R.add("master_from_hosted_run_of_this_package", False,
              "no COLLECTED.json with sha256 == this master (%s): the master was not collected from a hosted run of an approved request" % msha[:16])
        return None, None
    req = jload(os.path.join(os.path.dirname(hit), "REQUEST.json"), {}) or {}
    appr = ((req.get("approval") or {}).get("approved_hash"))
    src = os.path.join(out, "build", "source.tar.gz")
    pkg = os.path.join(out, "build", "pkg")
    problems = []
    if appr != sb.get("approved_hash"):
        problems.append("request approved_hash %s != storyboard %s" % (str(appr)[:16], str(sb.get("approved_hash"))[:16]))
    want = ((req.get("inputs") or {}).get("source") or {}).get("sha256")
    fp = None
    if not os.path.isfile(src):
        problems.append("build/source.tar.gz is gone")
    elif sha256(src) != want:
        problems.append("build/source.tar.gz has changed since this master's request (rebuilt after the render)")
    elif not os.path.isdir(pkg):
        problems.append("build/pkg is gone")
    else:
        fp_tar, n_tar = tar_fingerprint(src)
        fp_dir, n_dir = dir_fingerprint(pkg)
        if fp_tar != fp_dir:
            problems.append("build/pkg (%d files) is not the tarball that rendered the master (%d files)" % (n_dir, n_tar))
        fp = fp_dir
    R.add("master_from_hosted_run_of_this_package", not problems,
          "; ".join(problems) or "COLLECTED run %s -> request %s approved_hash %s; source tarball sha %s; build/pkg fingerprint %s" % (
              (jload(hit, {}) or {}).get("run"), os.path.basename(os.path.dirname(hit))[:12], str(appr)[:12], str(want)[:12], str(fp)[:12]),
          [ev(ctx, hit, True, "collected"), ev(ctx, os.path.join(os.path.dirname(hit), "REQUEST.json"), True, "request")])
    return fp, hit


def c_gate(ctx, vr, R, sid, master):
    out = ctx.out(sid)
    gates = sorted(glob.glob(os.path.join(out, "gate", "*", "GATE.json")), key=mt)
    if not gates:
        R.add("gate_15_of_15", False, "no GATE.json")
        return None
    gp = gates[-1]
    g = jload(gp, {}) or {}
    checks = g.get("checks") or []
    waived = vr.root_waived(gp)
    probs, notes = [], []
    for c in checks:
        st, cid = c.get("status"), str(c.get("id"))
        if st == "PASS":
            continue
        if cid in waived:
            notes.append("%s %s waived by root (ROOT-WAIVER.json bound to this gate)" % (cid, st))
        elif cid == "9" and (st == "UNJUDGED" or (st == "FAIL" and re.search(r"429|quota|rate.?limit|tokens per day|TPD", str(c.get("summary", "")), re.I))):
            notes.append("9 %s (advisory free-quota critic, never a craft FAIL: root 28 Sep)" % st)
        else:
            probs.append("%s %s: %s" % (cid, st, str(c.get("summary"))[:70]))
    if len(checks) < 15:
        probs.append("only %d checks recorded" % len(checks))
    if not vr.gate_passes(g, gp):
        probs.append("overall=%s" % g.get("overall"))
    size = (g.get("probe") or {}).get("size_bytes")
    if size != os.path.getsize(master):
        probs.append("gate probed %s bytes, the master is %d" % (size, os.path.getsize(master)))
    if mt(gp) < mt(master) - 60:
        probs.append("GATE.json is older than the master")
    gv = vr.resolve_gate_video(__import__("pathlib").Path(gp), str(g.get("video", "")))
    if gv is not None and not os.path.samefile(str(gv), master) and sha256(str(gv)) != sha256(master):
        probs.append("the gate's video %s is a different file" % gv)
    n_pass = sum(1 for c in checks if c.get("status") == "PASS")
    R.add("gate_15_of_15", not probs, ("; ".join(probs)) or "%d/%d PASS%s; %s" % (n_pass, len(checks), (" (" + "; ".join(notes) + ")") if notes else "", ctx.rel(gp)),
          [ev(ctx, gp, True, "gate")])
    if waived:
        R.notes.append("gate waivers by root: %s" % sorted(waived))
    return gp


def c_voice(ctx, R, sid):
    vdir = os.path.join(ctx.v2, "shorts", "voice", sid)
    vp = os.path.join(vdir, sid + ".voicelead.json")
    d = jload(vp, None)
    probs = []
    if d is None:
        R.add("voicelead_pass_fresh", False, "no %s" % ctx.rel(vp))
        return
    if d.get("verdict") != "PASS" or d.get("fails"):
        probs.append("verdict=%r fails=%s" % (d.get("verdict"), str(d.get("fails"))[:120]))
    take = [os.path.join(vdir, sid + ".wav"), os.path.join(vdir, sid + ".words.json"), os.path.join(vdir, "RESULT.json")]
    for t in take:
        if not os.path.isfile(t):
            probs.append("take file missing: %s" % os.path.basename(t))
        elif mt(vp) + 1 < mt(t):
            probs.append("voicelead is older than %s (take re-recorded or re-scored after the check)" % os.path.basename(t))
    mix = os.path.join(ctx.out(sid), "audio", "mix.wav")
    mix2 = os.path.join(ctx.out(sid), "audio", "mix2")
    built = max(mt(mix), mt(mix2)) if (os.path.exists(mix) or os.path.exists(mix2)) else 0
    if built and built + 1 < mt(take[0]):
        probs.append("the mix was built before the take")
    try:
        sys.path.insert(0, ctx.kit)
        vsb = load_module(os.path.join(ctx.kit, "voice_script_binding.py"), "mp_vsb")
        from pathlib import Path
        verdict, why = vsb.check_voice_script_binding(sid, Path(vdir), Path(ctx.v2))
        if verdict == "REFUSE":
            probs.append("voice is not bound to the script: %s" % why)
    except Exception as exc:  # noqa: BLE001
        probs.append("voice/script binding unreadable: %s" % exc)
    R.add("voicelead_pass_fresh", not probs, "; ".join(probs) or "PASS, 0 fails, written %s after the take %s" % (
        time.strftime("%H:%M", time.localtime(mt(vp))), time.strftime("%H:%M", time.localtime(mt(take[0])))),
        [ev(ctx, vp, True, "voicelead")])


def domlint_target(ctx, sid):
    platforms = load_module(os.path.join(ctx.kit, "platforms", "platforms.py"), "mp_domlint_platforms")
    return (platforms.for_short(sid) or platforms.profile("instagram"))["key"]


def domlint_routing_fingerprint(ctx, sid):
    routing = jload(os.path.join(ctx.v2, "jev-v2", "fit", "routing.json"), {}) or {}
    override = (routing.get("manual_overrides") or {}).get(sid) or {}
    if override.get("class") != "assign-unrouted":
        return None
    data = {"assignment": (routing.get("assignment") or {}).get(sid), "manual_override": override}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def bind_existing_domlint(ctx, sid, request_path, runtime_commit):
    """JSON-only hosted lint owner path: never enters evaluate/prepare or local media IO."""
    if not re.fullmatch(r"[0-9a-f]{40}", runtime_commit or ""):
        return 2, "an exact published hosted runtime commit is required"
    target = domlint_target(ctx, sid)
    hosted = load_module(os.path.join(ctx.kit, "tools", "dom_lint_hosted.py"), "mp_hosted_domlint")
    return hosted.bind_existing(ctx, sid, request_path, target, runtime_commit)


def c_domlint(ctx, R, sid, pkg_fp):
    ddir = os.path.join(ctx.out(sid), "domlint")
    rp, bp = os.path.join(ddir, "result.json"), os.path.join(ddir, "BOUND.json")
    res, bound = jload(rp, None), jload(bp, None)
    probs, stale = [], False
    if res is None:
        probs.append("no domlint/result.json"); stale = True
    else:
        target = domlint_target(ctx, sid)
        if res.get("platform") != target:
            probs.append("the lint ran on platform %s, current target is %s" % (res.get("platform"), target)); stale = True
        fails = [f for f in res.get("findings", []) if f.get("sev") == "FAIL"]
        if fails or (res.get("stats") or {}).get("FAIL"):
            probs.append("%d FAIL finding(s), first: %s %s" % (len(fails), fails[0].get("rule") if fails else "?", str(fails[0].get("detail"))[:60] if fails else ""))
    if bound is None:
        probs.append("no domlint/BOUND.json (the lint has not run through the binding wrapper)"); stale = True
    else:
        route_fp = domlint_routing_fingerprint(ctx, sid)
        if route_fp is not None and bound.get("routing_fingerprint") != route_fp:
            probs.append("the routing decision changed after the lint was bound; fresh target-bound lint required"); stale = True
        if res is not None and bound.get("result_sha256") != sha256(rp):
            probs.append("result.json changed after the lint was bound"); stale = True
        if pkg_fp is None or bound.get("pkg_fingerprint") != pkg_fp:
            probs.append("the lint ran on package %s, the master was rendered from %s" % (str(bound.get("pkg_fingerprint"))[:12], str(pkg_fp)[:12])); stale = True
    R.add("dom_lint_0_fail_on_this_package", not probs, "; ".join(probs) or "0 FAIL on package fingerprint %s (%s samples, %d WARN)" % (
        str(pkg_fp)[:12], (res.get("stats") or {}).get("samples"), (res.get("stats") or {}).get("WARN", 0)),
        [ev(ctx, rp, True, "dom_lint result"), ev(ctx, bp, True, "dom_lint binding")] if os.path.isfile(bp) else [], needs_prepare=stale)


def prepare_sound_hosted(ctx, sid):
    try:
        helper = load_module(os.path.join(ctx.kit, "tools", "sound_audit_hosted.py"), "mp_sound_hosted")
        return helper.prepare_existing(ctx, sid)
    except (OSError, ImportError, AttributeError) as exc:
        return 2, "hosted sound helper unavailable: %s; no Mac media fallback" % exc


def audit_cache_path(ctx, sid, msha):
    return os.path.join(ctx.out(sid), "machine-pass", "audit_sound-%s.json" % msha[:16])


def run_audit(ctx, sid, master, msha, timeout=1500):
    cp = audit_cache_path(ctx, sid, msha)
    if os.path.isfile(os.path.join(ctx.out(sid), "machine-pass", "sound-inputs", "TRANSPORT.json")):
        return prepare_sound_hosted(ctx, sid)[0]
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    cmd = [sys.executable, os.path.join(ctx.kit, "tools", "heavy.py"), "--", sys.executable, os.path.join(ctx.v2, "sound", "audit_sound.py"),
           master, "--json", cp + ".tmp"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if os.path.isfile(cp + ".tmp"):
        d = jload(cp + ".tmp", {}) or {}
        d["_master_sha256"] = msha
        d["_rc"] = r.returncode
        d["_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(cp, "w") as fh:
            json.dump(d, fh, indent=1)
        os.remove(cp + ".tmp")
    return r.returncode


def c_audit(ctx, R, sid, master, msha, do_run):
    cp = audit_cache_path(ctx, sid, msha)
    if not os.path.isfile(cp) and do_run:
        run_audit(ctx, sid, master, msha)
    d = jload(cp, None)
    if os.path.isfile(cp.replace(".json", ".hosted.json")) or os.path.isfile(os.path.join(ctx.out(sid), "machine-pass", "sound-inputs", "TRANSPORT.json")):
        try:
            helper = load_module(os.path.join(ctx.kit, "tools", "sound_audit_hosted.py"), "mp_sound_cached")
            d = helper.validate_cached(ctx.v2, sid)
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            R.add("audit_sound_pass", False, "missing/stale exact-master hosted sound audit: %s (run --sound-audit-hosted)" % exc, needs_prepare=True)
            return
    if d is None:
        R.add("audit_sound_pass", False, "no audit_sound result for this master yet (run --prepare)", needs_prepare=True)
        return
    probs, stale = [], False
    if d.get("_master_sha256") != msha:
        probs.append("cached audit is for another master"); stale = True
    if d.get("status") != "PASS" or d.get("fails") or d.get("_rc") not in (0, None):
        probs.append("status=%r fails=%s rc=%s" % (d.get("status"), str(d.get("fails"))[:100], d.get("_rc")))
    R.add("audit_sound_pass", not probs, "; ".join(probs) or "PASS: %s, %s" % (
        str(d.get("loudness"))[:60], str((d.get("density") or {}).get("events_per_min", ""))), [ev(ctx, cp, True, "audit_sound")], needs_prepare=stale)


def c_better(ctx, R, sid):
    r = subprocess.run([sys.executable, os.path.join(ctx.kit, "tools", "better_than_last.py"), sid, "--strict"], capture_output=True, text=True,
                       cwd=ctx.kit, timeout=600)
    last = [l for l in (r.stdout or "").splitlines() if l.startswith("STRICT ")]
    ok = r.returncode == 0 and bool(last) and last[-1].rstrip().endswith("PASS")
    why = [l.strip() for l in (r.stdout or "").splitlines() if l.strip().startswith("! ")]   # the HOLD reasons (conductor routes stereo-only holds to autostereo)
    R.add("better_than_last_strict_pass", ok, (last[-1] if last else ("rc=%s %s" % (r.returncode, (r.stdout + r.stderr)[-160:]))) + ("" if ok or not why else " | " + " ".join(why)))


def c_concept(ctx, R, sid, sb):
    try:
        cc = load_module(os.path.join(ctx.kit, "tools", "concept_check.py"), "mp_concept")
        ok, text, rep = cc.check_for_submit(sid)
        if ok:
            R.add("concept_check_pass", True, "PASS vs window %s" % " ".join(w["id"] for w in rep.get("window", [])))
            return
        failed = [str(f) for f in rep.get("failed", [])]
        # root 6 Oct 20:40: the concept was JUDGED by the Claude reviewer who approved this storyboard (the gate ran at submit,
        # and its waiver, if any, sat in front of that reviewer). If concept.json has not changed since that approval, the
        # window moving on afterwards must not un-approve it (S102/S52 held on R6/R2 against today's window).
        import datetime as _dt
        appr = [h for h in (sb.get("history") or []) if isinstance(h, dict) and h.get("state") == "approved"]
        cpath = os.path.join(ctx.kit, "specs", sid, "concept.json")
        by = str(sb.get("by", ""))
        if appr and os.path.exists(cpath) and (by in ("root", "claude-root") or by.startswith(("sonnet-", "opus-"))):
            at = "%sT%s" % (appr[-1].get("date"), appr[-1].get("at"))
            mt = _dt.datetime.fromtimestamp(os.path.getmtime(cpath)).strftime("%Y-%m-%dT%H:%M:%S")
            if sb.get("state") == "approved" and mt <= at:
                R.add("concept_check_pass", True, "concept unchanged since %s approved it at %s (today's window: FAIL %s)" %
                      (sb.get("by"), at, ",".join(n[:2] for n in failed)))
                return
        rows = [h for h in (sb.get("history") or []) if isinstance(h, dict) and h.get("concept_waiver")]
        w = rows[-1]["concept_waiver"] if rows else None
        if w and str(w.get("by")) in ("root", "claude-root") and len(str(w.get("reason", ""))) >= 40 and set(failed) <= set(str(x) for x in w.get("failed", [])):
            R.add("concept_check_pass", True, "FAIL %s covered by a recorded root waiver: %s" % (",".join(n[:2] for n in failed), str(w.get("reason"))[:100]))
        else:
            R.add("concept_check_pass", False, "FAIL %s and no recorded root waiver covers it (waiver=%s)" % (",".join(n[:2] for n in failed), (w or {}).get("by")))
    except SystemExit:
        R.add("concept_check_pass", False, "concept_check exited")
    except Exception as exc:  # noqa: BLE001
        R.add("concept_check_pass", False, "concept_check could not run: %s" % exc)


def banned_scan(ctx, sid, master):
    sa = load_module(os.path.join(ctx.ap, "tools", "strict_arming.py"), "mp_strict")
    texts = {}
    item = os.path.join(ctx.ap, "items", sid)
    caps = jload(os.path.join(item, "captions.json"), {}) or {}
    for p, c in caps.items():
        texts["caption:%s" % p] = " ".join(str(v) for v in (c.values() if isinstance(c, dict) else [c]))
    sp = os.path.join(ctx.v2, "shorts", "scripts-v2", sid + ".md")
    if os.path.isfile(sp):
        texts["script"] = open(sp, encoding="utf-8").read()
    rj = jload(os.path.join(ctx.out(sid), "resolved.json"), None)
    if rj is not None:
        words = rj.get("words") if isinstance(rj, dict) else None
        if words:
            texts["resolved words"] = " ".join(str(w.get("word", w) if isinstance(w, dict) else w) for w in words)
    wj = jload(os.path.join(ctx.v2, "shorts", "voice", sid, sid + ".words.json"), None)
    if wj is not None:
        arr = wj if isinstance(wj, list) else (wj.get("words") or [])
        texts["voice words"] = " ".join(str(w.get("word", w) if isinstance(w, dict) else w) for w in arr)
    hits = []
    for k, t in texts.items():
        h = sa.banned_phrase_in(t)
        if h:
            hits.append("%s: %r" % (k, h))
    return hits, sorted(texts)


def c_release(ctx, vr, R, sid, master):
    item = os.path.join(ctx.ap, "items", sid, "item.json")
    capf = os.path.join(ctx.ap, "items", sid, "captions.json")
    probs = []
    row = None
    try:
        row = vr.load_item(__import__("pathlib").Path(item))
    except Exception as exc:  # noqa: BLE001
        probs.append("item/captions unreadable: %s" % exc)
    if row is not None:
        plats = row.get("platforms") or {}
        empty = [p for p, c in plats.items() if not str((c or {}).get("caption", "")).strip()]
        if not plats or empty:
            probs.append("captions missing for %s" % (empty or "every platform"))
    R.add("captions_item_present", not probs, "; ".join(probs) or "%d platform captions in %s" % (len((row or {}).get("platforms") or {}), ctx.rel(capf)),
          [ev(ctx, capf, False, "captions")] if os.path.isfile(capf) else [])
    hits, scanned = banned_scan(ctx, sid, master)
    R.add("banned_cta_absent", not hits and bool(scanned), ("; ".join(hits)) or "no banned phrase in %s" % ", ".join(scanned))
    probs = []
    if row is not None:
        sfile = row.get("source_file") or os.path.join(ctx.v2, "shorts", "scripts-v2", sid + ".md")
        now = sha256(sfile) if os.path.isfile(sfile) else ""
        if now != row.get("source_sha256"):
            probs.append("script sha %s != the sha the captions were written from %s" % (now[:12], str(row.get("source_sha256"))[:12]))
        rb = row.get("source_rebinds") or []
        if rb:
            last = rb[-1]
            if last.get("new") != row.get("source_sha256") or str(last.get("by")) not in ("root", "claude-root"):
                probs.append("source_rebind chain does not end at the current sha, signed by root")
    R.add("script_unchanged_since_captions", not probs and row is not None, "; ".join(probs) or "script sha == captions' sha%s" % (
        " (root source_rebind on record)" if row and row.get("source_rebinds") else ""))
    beds = []
    try:
        beds = vr.recorded_beds(__import__("pathlib").Path(master))
    except Exception:  # noqa: BLE001
        pass
    spec = jload(os.path.join(ctx.kit, "specs", sid, "spec.json"), {}) or {}
    sb = (spec.get("music") or {}).get("bed")
    allb = [b for b in beds + ([sb] if sb else []) if b]
    bad = [b for b in allb if b in BANNED_BEDS]
    R.add("bed_not_banned", bool(allb) and not bad, "bed(s) %s%s" % (allb, (" BANNED: %s" % bad) if bad else ""))
    return row


# -------------------------------------------------------------------------------------------------------- dom_lint wrapper
def lint_and_bind(ctx, sid, timeout=1700):
    """Full native DOM lint on the existing hosted package; JSON-only local binding, no Mac media fallback."""
    try:
        hosted = load_module(os.path.join(ctx.kit, "tools", "dom_lint_hosted.py"), "mp_hosted_domlint")
        return hosted.prepare_existing(ctx, sid, timeout=timeout)
    except (OSError, ImportError, AttributeError) as exc:
        return 2, "hosted DOM preparation unavailable (%s); local media fallback refused" % type(exc).__name__


def prepare(ctx, sid, log=print):
    rc, why = lint_and_bind(ctx, sid)
    log(why)
    if rc == 0 and os.path.isfile(os.path.join(ctx.out(sid), "machine-pass", "sound-inputs", "TRANSPORT.json")):
        rc, why = prepare_sound_hosted(ctx, sid)
        log(why)
    return rc


# --------------------------------------------------------------------------------------------------------------- evaluate
def evaluate(ctx, sid, run_slow=False):
    """Checks 1-9 for one short. Returns (Report, facts). Writes only evidence caches (audit result) when run_slow."""
    R = Report(sid)
    vr = load_module(os.path.join(ctx.ap, "tools", "validate_release.py"), "mp_validate_release")
    master = os.path.join(ctx.out(sid), "FINAL.mp4")
    if not os.path.isfile(master):
        R.add("master_exists", False, "no %s" % ctx.rel(master))
        return R, {}
    msha = sha256(master)
    R.add("master_exists", True, "%s %d bytes sha %s" % (ctx.rel(master), os.path.getsize(master), msha[:16]))
    from pathlib import Path
    sb, by, maker = c_storyboard(ctx, vr, R, sid, Path(master))
    c_no_hold(ctx, vr, R, sid, Path(master))
    fp, _ = c_package(ctx, R, sid, master, msha, sb)
    c_gate(ctx, vr, R, sid, master)
    c_voice(ctx, R, sid)
    c_domlint(ctx, R, sid, fp)
    c_audit(ctx, R, sid, master, msha, run_slow)
    c_better(ctx, R, sid)
    c_concept(ctx, R, sid, sb)
    row = c_release(ctx, vr, R, sid, master)
    return R, {"vr": vr, "master": master, "msha": msha, "sb": sb, "approver": by, "maker": maker, "row": row}


# ------------------------------------------------------------------------------------------------------------------- issue
def atomic_json(path, obj):
    tmp = path + ".tmp-%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def issue(ctx, sid, arm=False, log=print):
    R, F = evaluate(ctx, sid, run_slow=True)
    mdir = os.path.join(ctx.out(sid), "machine-pass")
    os.makedirs(mdir, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    atomic_json(os.path.join(mdir, "LAST-CHECK.json"), {"id": sid, "at": stamp, "ok": R.ok, "checks": R.checks})
    if not R.ok:
        return 1, R, "REFUSED %s: %s" % (sid, "; ".join("%s (%s)" % (c["name"], c["detail"][:140]) for c in R.failed()))
    vr, master, msha, sb, approver, maker, row = F["vr"], F["master"], F["msha"], F["sb"], F["approver"], F["maker"], F["row"]
    body = {"kind": "agmm_machine_pass_receipt", "schema": 1, "id": sid, "verdict": "PASS", "at": stamp, "master": ctx.rel(master),
            "master_sha256": msha, "master_bytes": os.path.getsize(master), "approver": approver, "approver_decided": sb.get("decided"),
            "approved_hash": sb.get("approved_hash"), "maker": maker, "checks": R.checks, "evidence": R.evidence, "notes": R.notes,
            "issued_by": "qa/machine_pass.py"}
    body["seal"] = vr.machine_receipt_seal(body)
    rp = os.path.join(mdir, vr.MACHINE_RECEIPT)
    if os.path.exists(rp):
        os.replace(rp, os.path.join(mdir, "RECEIPT-superseded-%s.json" % stamp.replace(":", "")))
    atomic_json(rp, body)
    # 10: the exact validator arming runs, on the proposed card and review entry (in memory), with the receipt in place
    gp = sorted(glob.glob(os.path.join(ctx.out(sid), "gate", "*", "GATE.json")), key=mt)[-1]
    web = os.path.join(ctx.out(sid), "%s-web.mp4" % sid)
    cards = jload(os.path.join(ctx.qa, "cards.json"), []) or []
    card = next((dict(c) for c in cards if c.get("id") == sid), None)
    if card is None:
        itemj = jload(os.path.join(ctx.ap, "items", sid, "item.json"), {}) or {}
        card = {"id": sid, "section": "shortform", "title": itemj.get("title") or itemj.get("headline") or sid,
                "platform": itemj.get("platform") or "routed by Jev", "platform_why": itemj.get("platform_why") or "Jev routing (v2/jev-v2/fit/routing.json)",
                "reference": "P1-P3 pilots (the approved bar)", "reference_url": "https://agmm.co.uk", "type": "video/mp4"}
    card.update({"status": "Ready to post", "master": ctx.rel(master), "gate_json": ctx.rel(gp), "reviewed_master_sha256": msha,
                 "src": ctx.rel(web) if os.path.isfile(web) else ctx.rel(master)})
    poster = os.path.join(ctx.out(sid), "poster.jpg")
    if os.path.isfile(poster):
        card["poster"] = ctx.rel(poster)
    card.setdefault("poster", card["src"])
    reviewer = "machine:" + approver
    reason = ("MACHINE PASS (no Claude reviewer at the master): look judged at the storyboard by %s (decided %s, hash %s); master %s sha %s is a hosted "
              "render of exactly that approved package; %d mechanical checks re-verified from their own files: %s. Receipt %s."
              % (approver, sb.get("decided"), str(sb.get("approved_hash"))[:12], ctx.rel(master), msha[:16], len(R.checks),
                 ", ".join(c["name"] for c in R.checks), ctx.rel(rp)))
    entry = {"id": sid, "verdict": "PASS", "reviewer": reviewer, "maker": maker or "writer", "at": time.strftime("%Y-%m-%dT%H:%M"),
             "master_sha256": msha, "reason": reason,
             "detail": "machine pass: gate %s PASS on FINAL (%d bytes, sha256 %s); receipt %s sealed %s" % (
                 ctx.rel(gp), os.path.getsize(master), msha, ctx.rel(rp), body["seal"][:16])}
    log_rows = jload(os.path.join(ctx.qa, "review-log.json"), []) or []
    rows = log_rows if isinstance(log_rows, list) else log_rows.get("reviews", [])
    cards2 = [c for c in cards if c.get("id") != sid] + [card]
    approval, rchecks = vr.reviewer_approval(sid, cards2, list(rows) + [entry])
    result = None
    if approval is not None:
        catalogue = {i["id"]: i for i in jload(os.path.join(ctx.v2, "sound", "music.json"), {}).get("items", [])}
        idx = {r["id"]: r for r in (jload(os.path.join(ctx.ap, "script-index.json"), {}) or {}).get("rows", [])}
        row["_numbers"] = idx.get(sid, {}).get("numbers_in_file", [])      # exactly what arm_ready adds before check_row
        result = vr.check_row(row, approval, catalogue)
        try:                                                                 # and its promise check, on every platform's rendered caption
            pc = load_module(os.path.join(ctx.ap, "tools", "promise_check.py"), "mp_promise")
            cr = load_module(os.path.join(ctx.ap, "tools", "credits.py"), "mp_credits")
            for plat, c in (row.get("platforms") or {}).items():
                cap = cr.render_caption(c["caption"], approval.get("music_beds") or [], catalogue, vr.PLACEHOLDER)
                pr = pc.check(sid, cap, approval.get("gate_json"))
                if not pr.get("ok"):
                    result["releasable"] = False
                    result.setdefault("failed", []).append("promise_%s: %s" % (plat, str((pr.get("undelivered") or [{}])[0].get("line"))[:80]))
        except Exception as exc:  # noqa: BLE001
            result["releasable"] = False
            result.setdefault("failed", []).append("promise_check could not run: %s" % exc)
    if approval is None or not result or not result.get("releasable"):
        bad = [c["code"] for c in rchecks if not c["ok"]] if approval is None else result.get("failed")
        os.replace(rp, os.path.join(mdir, "RECEIPT-REJECTED-%s.json" % stamp.replace(":", "")))
        return 1, R, "REFUSED %s by the arming validator (not written): failed %s" % (sid, bad)
    r = subprocess.run([sys.executable, os.path.join(ctx.qa, "card.py"), "upsert", json.dumps(card, ensure_ascii=False)], capture_output=True, text=True)
    if r.returncode:
        os.replace(rp, os.path.join(mdir, "RECEIPT-REJECTED-%s.json" % stamp.replace(":", "")))
        return 1, R, "card.py refused: " + (r.stdout + r.stderr)[-500:]
    logp = os.path.join(ctx.qa, "review-log.json")          # re-read immediately before writing: other agents append here
    cur = jload(logp, []) or []
    rr = cur if isinstance(cur, list) else cur.setdefault("reviews", [])
    rr.append(entry)
    atomic_json(logp, cur)
    msg = "READY %s: machine pass issued (reviewer %s, receipt %s); card Ready to post; PASS logged" % (sid, reviewer, ctx.rel(rp))
    if arm:
        a = subprocess.run([sys.executable, os.path.join(ctx.ap, "tools", "arm_ready.py"), "--execute", "--only", sid], capture_output=True, text=True, timeout=1800)
        msg += "\n" + (a.stdout[-1500:] or a.stderr[-800:])
    return 0, R, msg


def table(R):
    return "\n".join("  [%s] %-42s %s" % ("ok  " if c["ok"] else "FAIL", c["name"], c["detail"][:170]) for c in R.checks)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("id")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--hosted-master-transport", help="collect a JSON-only native hosted evaluation/proposal; never issue locally")
    ap.add_argument("--sound-audit-hosted", action="store_true", help="collect the full native exact-master audit from protected inputs on Ubuntu; JSON-only owner, no review/issue")
    ap.add_argument("--domlint-existing-request", help="bind a fresh hosted full native DOM report from an existing exact render request; JSON-only client")
    ap.add_argument("--domlint-runtime-commit", help="exact published commit of the full hosted native DOM runtime")
    ap.add_argument("--arm", action="store_true")
    ap.add_argument("--v2", help="evaluate a mirror of the tree (tests): every path resolves under this v2 root")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    ctx = Ctx(a.v2)
    if a.hosted_master_transport:
        if a.id != "S87" or a.prepare or a.check or a.arm or a.domlint_existing_request or a.domlint_runtime_commit or getattr(a, "sound_audit_hosted", False):
            ap.error("hosted master evaluation is standalone, S87-bound, and grants no approval")
        hosted = load_module(os.path.join(ctx.kit, "tools", "master_evaluation_hosted.py"), "mp_hosted_master_evaluation")
        rc, why = hosted.collect(ctx.v2, a.hosted_master_transport, expected_sid=a.id)
        print(why)
        sys.exit(rc)
    if a.sound_audit_hosted:
        if a.prepare or a.check or a.arm or a.domlint_existing_request or a.domlint_runtime_commit:
            ap.error("--sound-audit-hosted is a standalone evidence owner command")
        rc, why = prepare_sound_hosted(ctx, a.id)
        print(why)
        sys.exit(rc)
    if a.domlint_existing_request or a.domlint_runtime_commit:
        if not (a.domlint_existing_request and a.domlint_runtime_commit) or a.prepare or a.check or a.arm:
            ap.error("hosted DOM binding requires both --domlint-existing-request and --domlint-runtime-commit, and cannot combine with --prepare/--check/--arm")
        rc, why = bind_existing_domlint(ctx, a.id, a.domlint_existing_request, a.domlint_runtime_commit)
        print(why)
        sys.exit(rc)
    if a.prepare:
        sys.exit(prepare(ctx, a.id))
    if a.check:
        R, F = evaluate(ctx, a.id, run_slow=False)
        print(json.dumps({"id": a.id, "ok": R.ok, "checks": R.checks}, indent=1) if a.json else ("machine_pass --check %s: %s\n%s" % (a.id, "ALL OK" if R.ok else "NOT YET", table(R))))
        sys.exit(0 if R.ok else 1)
    rc, R, msg = issue(ctx, a.id, arm=a.arm)
    print(table(R))
    print(msg)
    sys.exit(rc)


if __name__ == "__main__":
    main()
