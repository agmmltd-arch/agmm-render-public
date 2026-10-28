#!/usr/bin/env python3
"""lane_short.py: a free lane makes a short end to end, plan -> fill -> compile -> look -> revise once, with no hand edits.

  python3 tools/lane_short.py --lane oc-nemotron-ultra --id X12 --script shorts/scripts-v2/S02.md --voice shorts/voice/S02 \
      --sources specs/X12/sources.js --route-as S02 [--scratch] [--no-review]

Steps (every lane reply is kept verbatim in specs/<ID>/lane/; the lane's JSON is never hand-fixed):
  1 PLAN   beats_brief.py plan -> lane -> plan.json -> compose.py --plan. If the plan fails, the lane gets its errors
           once and plans again (two plan calls at most).
  2 FILL   beats_brief.py fill (with the checked plan) -> lane -> beats.json -> compose.py. If it fails to compile,
           the lane gets compose's errors once and returns the whole file again.
  3 LOOK   build_short.py --skip-audio, then self_review.py (snap every beat start/+0.5 s, free Qwen vision).
  4 REVISE beats_brief.py revise (compose warnings + vision findings) -> lane -> beats-r2.json -> compose.py.
  5 KEEP   the better of the two by compose.py's own score (errors first, then fill, headline size, warnings);
           the kept one is specs/<ID>/beats.json + spec.json + scenes.js, built.
Lanes are one-shot (fleet spawn --wait); a lane that times out or returns no JSON ends the run, and says so.
Writes specs/<ID>/lane/RUN.json with every step's outcome."""
import argparse, json, os, re, shutil, subprocess, sys, time
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLEET = os.path.expanduser("~/.fleet/bin/fleet")


def sh(cmd, timeout=3600, env=None):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=KIT, env=env)
    return r.returncode, r.stdout, r.stderr


def lane_call(lane, prompt, tag, d, timeout):
    pf = os.path.join(d, tag + ".prompt.txt"); open(pf, "w").write(prompt)
    cwd = os.path.join(d, "cwd-" + tag); os.makedirs(cwd, exist_ok=True)
    env = dict(os.environ, FLEET_SPAWN_TIMEOUT=str(timeout))
    t0 = time.time()
    rc, out, err = sh([FLEET, "spawn", lane, "--prompt-file", pf, "--cwd", cwd, "--wait"], timeout=timeout + 120, env=env)
    runs = sorted([os.path.join(os.path.expanduser("~/.fleet/runs/adhoc"), f) for f in os.listdir(os.path.expanduser("~/.fleet/runs/adhoc"))
                   if f.startswith("run-%s-" % lane) and f.endswith(".out.json")], key=os.path.getmtime)
    res = json.load(open(runs[-1])) if runs and os.path.getmtime(runs[-1]) >= t0 - 5 else {}
    text = res.get("text") or ""
    open(os.path.join(d, tag + ".reply.txt"), "w").write(text)
    return text, {"secs": round(time.time() - t0), "usage": res.get("usage"), "is_error": res.get("is_error"), "rc": res.get("returncode")}


def json_of(text):
    m = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    raw = m[-1] if m else (text[text.find("{"):text.rfind("}") + 1] if "{" in text else "")
    return raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", required=True); ap.add_argument("--id", required=True); ap.add_argument("--script", required=True)
    ap.add_argument("--voice", required=True); ap.add_argument("--sources", required=True); ap.add_argument("--route-as")
    ap.add_argument("--scratch", action="store_true"); ap.add_argument("--no-review", action="store_true"); ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--truth-sources", help="dir of <label>.txt source texts for tools/text_truth.py")
    ap.add_argument("--tries", type=int, default=3, help="lane calls per stage (plan, fill); each retry carries the compiler errors")
    ap.add_argument("--halves", action="store_true", help="fill in two calls (for lanes that run out of output tokens)")
    a = ap.parse_args()
    sd = os.path.join(KIT, "specs", a.id); d = os.path.join(sd, "lane"); os.makedirs(d, exist_ok=True)
    base = ["--id", a.id, "--script", a.script, "--voice", a.voice, "--sources", a.sources] + (["--route-as", a.route_as] if a.route_as else []) + (["--scratch"] if a.scratch else [])
    RUN = {"lane": a.lane, "id": a.id, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": []}

    def step(name, **kw):
        kw["step"] = name; RUN["steps"].append(kw); json.dump(RUN, open(os.path.join(d, "RUN.json"), "w"), indent=1)
        print("[%s] %s" % (name, json.dumps({k: v for k, v in kw.items() if k != "step"})[:400]), flush=True)

    # 1 PLAN
    rc, brief, err = sh(["python3", "tools/beats_brief.py", "plan"] + base)
    if rc:
        sys.exit("brief failed: " + err[-400:])
    plan_ok, extra = False, ""
    for attempt in range(1, a.tries + 1):
        text, meta = lane_call(a.lane, brief + extra, "plan%d" % attempt, d, a.timeout)
        raw = json_of(text)
        if not raw:
            step("plan", attempt=attempt, result="no JSON in the reply", **meta); break
        pp = os.path.join(sd, "plan.json"); open(pp, "w").write(raw)
        rc, out, _ = sh(["python3", "tools/compose.py", "--plan", pp, "--voice", a.voice] + (["--route-as", a.route_as] if a.route_as else []))
        try:
            res = json.loads(out)
        except ValueError:
            res = {"errors": [out[-300:]]}
        step("plan", attempt=attempt, errors=res.get("errors"), **meta)
        if not res.get("errors"):
            plan_ok = True; break
        extra = "\n\n=========== YOUR LAST PLAN FAILED THESE CHECKS; RETURN THE WHOLE PLAN AGAIN, FIXED ===========\n%s\n\nYour plan was:\n%s" % (
            "\n".join("- " + e for e in res["errors"]), raw)
    if not plan_ok:
        step("stop", reason="no valid plan after %d calls" % a.tries); sys.exit(1)

    # 2 FILL
    rc, brief, err = sh(["python3", "tools/beats_brief.py", "fill"] + base + ["--plan", "specs/%s/plan.json" % a.id])
    extra, ok, rep = "", False, None
    for attempt in range(1, a.tries + 1):
        if a.halves and attempt == 1:
            # a lane that runs out of output tokens (Mimo: 32,000 on one fill) writes the short in two halves
            plan = json.load(open(os.path.join(sd, "plan.json")))
            ids = [b["id"] for b in plan["beats"]]; k = (len(ids) + 1) // 2
            t1, m1 = lane_call(a.lane, brief + "\n\nWRITE ONLY THE FIRST HALF NOW: the whole file with \"beats\" holding only %s. Keep it short." % ids[:k], "fill1a", d, a.timeout)
            t2, m2 = lane_call(a.lane, brief + "\n\nWRITE ONLY THE SECOND HALF NOW: return {\"beats\": [...]} holding only %s, using ONLY these world station ids: %s." % (ids[k:], [w.get("id") for w in plan.get("world", [])]), "fill1b", d, a.timeout)
            try:
                A = json.loads(json_of(t1)); Bh = json.loads(json_of(t2))
                A["beats"] = [b for b in A.get("beats", []) if b.get("id") in ids[:k]] + [b for b in Bh.get("beats", []) if b.get("id") in ids[k:]]
                text, meta = "```json\n" + json.dumps(A) + "\n```", {"secs": m1["secs"] + m2["secs"], "usage": [m1["usage"], m2["usage"]], "halves": True}
            except (ValueError, TypeError) as e:
                step("fill", attempt=attempt, result="halves did not parse: %s" % e); text, meta = "", {}
        else:
            text, meta = lane_call(a.lane, brief + extra, "fill%d" % attempt, d, a.timeout)
        raw = json_of(text)
        if not raw:
            step("fill", attempt=attempt, result="no JSON in the reply", **meta); break
        bp = os.path.join(sd, "beats.json"); open(bp, "w").write(raw)
        shutil.copyfile(bp, os.path.join(d, "beats-fill%d.json" % attempt))
        rc, out, _ = sh(["python3", "tools/compose.py", bp, "--json", "--stage"])
        try:
            rep = json.loads(out)
        except ValueError:
            rep = {"errors": [out[-300:]], "warnings": []}
        step("fill", attempt=attempt, errors=rep.get("errors"), n_warn=len(rep.get("warnings", [])), score=rep.get("score"), **meta)
        if not rep.get("errors"):
            ok = True; break
        extra = "\n\n=========== THE COMPILER REFUSED YOUR beats.json; RETURN THE WHOLE FILE AGAIN, FIXED ===========\n%s\n\nYour file was:\n%s" % (
            "\n".join("- " + e for e in rep["errors"]), raw)
    if not ok:
        step("stop", reason="beats.json did not compile after %d calls" % a.tries); sys.exit(1)
    shutil.copyfile(os.path.join(sd, "beats.json"), os.path.join(d, "beats-r1.json"))
    rc, out, err = sh(["python3", "build_short.py", "specs/%s/spec.json" % a.id, "--skip-audio"])
    step("build", rc=rc, tail=(out + err)[-300:])
    import glob as _g
    perr = []
    for html in sorted(_g.glob(os.path.join(KIT, "out", a.id, "build", "pkg", "*", "index.html"))):
        r_, o_, e_ = sh([os.path.expanduser("~/.local/node/bin/node"), "tools/page_errors.js", html], timeout=180)
        perr += [l for l in (o_ + e_).splitlines() if l.startswith("PAGEERROR")]
    step("page_errors", errors=perr[:6])
    if a.no_review:
        step("done", kept="r1"); return
    # 3 LOOK: the compiler's own warnings plus the on-screen text meaning check (root round 3: Qwen dropped, 30/30 noise)
    truth = {"fails": [], "pass": None}
    if a.truth_sources:
        rc, out, err = sh(["python3", "tools/text_truth.py", "specs/%s/spec.json" % a.id, "--sources", a.truth_sources, "--script", a.script], timeout=1800)
        tp = os.path.join(KIT, "out", a.id, "text-truth.json")
        truth = json.load(open(tp)) if os.path.exists(tp) else {"fails": ["text-truth did not run: " + (out + err)[-200:]], "pass": False}
        shutil.copyfile(tp, os.path.join(d, "text-truth-r1.json")) if os.path.exists(tp) else None
        step("truth", passed=truth.get("pass"), fails=truth.get("fails")[:12])
    findings = {"compiler_warnings": rep.get("warnings", []), "fill_per_beat": {b["id"]: b["fill"] for b in rep.get("beats", [])},
                "on_screen_text_not_supported_by_the_sources": truth.get("fails", [])}
    fp = os.path.join(d, "findings-r1.json"); json.dump(findings, open(fp, "w"), indent=1)
    # 4 REVISE
    rc, brief, err = sh(["python3", "tools/beats_brief.py", "revise"] + base + ["--beats", "specs/%s/beats.json" % a.id, "--findings", fp])
    text, meta = lane_call(a.lane, brief, "revise", d, a.timeout)
    raw = json_of(text)
    rep2 = None
    if raw:
        b2 = os.path.join(d, "beats-r2.json"); open(b2, "w").write(raw)
        tmp = os.path.join(sd, "beats.json"); shutil.copyfile(b2, tmp)
        rc, out, _ = sh(["python3", "tools/compose.py", tmp, "--json", "--check"])
        try:
            rep2 = json.loads(out)
        except ValueError:
            rep2 = {"errors": [out[-300:]], "score": -1e6}
    step("revise", errors=(rep2 or {}).get("errors"), score=(rep2 or {}).get("score"), **meta)
    # 5 KEEP the better by compose's own score
    truth2 = {"fails": []}
    if rep2 and not rep2.get("errors") and a.truth_sources:
        sh(["python3", "tools/compose.py", "specs/%s/beats.json" % a.id])
        rc, out, err = sh(["python3", "tools/text_truth.py", "specs/%s/spec.json" % a.id, "--sources", a.truth_sources, "--script", a.script], timeout=1800)
        tp = os.path.join(KIT, "out", a.id, "text-truth.json")
        truth2 = json.load(open(tp)) if os.path.exists(tp) else {"fails": ["did not run"]}
        shutil.copyfile(tp, os.path.join(d, "text-truth-r2.json")) if os.path.exists(tp) else None
        step("truth2", passed=truth2.get("pass"), fails=truth2.get("fails")[:12])
    s1 = rep.get("score", -1e6) - 100 * len(truth.get("fails", []))
    s2 = ((rep2 or {}).get("score", -1e6) - 100 * len(truth2.get("fails", []))) if rep2 and not rep2.get("errors") else -1e6
    kept = "r2" if s2 > s1 else "r1"
    shutil.copyfile(os.path.join(d, "beats-%s.json" % kept), os.path.join(sd, "beats.json"))
    rc, out, _ = sh(["python3", "tools/compose.py", "specs/%s/beats.json" % a.id, "--stage"])
    rc2, out2, err2 = sh(["python3", "build_short.py", "specs/%s/spec.json" % a.id, "--skip-audio"])
    step("keep", kept=kept, score_r1=s1, score_r2=s2, build=(out2 + err2)[-200:])


if __name__ == "__main__":
    main()
