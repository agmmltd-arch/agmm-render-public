#!/usr/bin/env python3
"""frame_precheck.py <ID> [--at 1.0,5.5,55.2] [--every 2] [--platform P]   (root, 30 Sep 2026: teach Forge to catch it BEFORE a render)

Why: on 29-30 Sep most returns (S59, S03, S52, S56 on Instagram; S40, S02 labels) were text under a platform's UI or off the frame,
found only after a 1-2 h render. This snaps the COMPOSITION (kit/tools/snap.py, headless, minutes), reads every text line with the
gate's own OCR (kit/tools/ocr_vision) and tests each line against the ROUTED platform's measured profile (kit/platforms/frames.json),
with exactly the gate's rules (platforms.box_problems: outside the visible rect, >= 5% under a measured overlay).
Prints one line per problem with the snap time and the text, and exits 1 if any FAIL. Run it after every fix, before submit.
Blind spots (named): stacked text between two layers is NOT detected (OCR boxes cannot tell it; look at the snaps), nor emptiness."""
import argparse, glob, json, math, os, re, subprocess, sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "platforms"))
import platforms  # noqa: E402


def tool_error(message):
    print(message, file=sys.stderr)
    raise SystemExit(2)


def valid_number(value, positive=False):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value)) and (not positive or value > 0)
    except (OverflowError, ValueError):
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id"); ap.add_argument("--at"); ap.add_argument("--every", default="2"); ap.add_argument("--platform")
    a = ap.parse_args()
    p = platforms.profile(a.platform) if a.platform else platforms.for_short(a.id)
    if p is None:  # unrouted short (6 Oct: TypeError on S67/S69/S92/S73/S71/S09): judge against Instagram, the strictest overlays
        p = platforms.profile("instagram"); print("note: %s has no routed platform; checking against instagram_reels" % a.id)
    import time
    t_start = time.time()
    at = a.at
    if not at:   # snap.py --every is per part; build an explicit list every N s over the whole short from the parts' durations
        tot = 0.0
        for h in sorted(glob.glob(os.path.join(KIT, "out", a.id, "build", "pkg", "*", "index.html"))):
            m = re.search(r'data-duration="([\d.]+)"', open(h).read())
            tot += float(m.group(1)) if m else 0
        step = float(a.every)
        at = ",".join("%.2f" % (0.5 + i * step) for i in range(int(max(tot - 0.6, 0) / step) + 1)) if tot else None
    cmd = ["python3", os.path.join(KIT, "tools", "snap.py"), a.id] + (["--at", at] if at else ["--every", a.every])
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=KIT)
    if r.returncode:
        tool_error("TOOL ERROR (snap.py rc %d): %s" % (r.returncode, (r.stdout + r.stderr)[-400:]))
    # frames written by THIS run (snap.py overwrites same-named files, so a set difference misses re-runs); never contact-sheet.jpg
    shots = sorted(f for f in glob.glob(os.path.join(KIT, "out", a.id, "snap", "**", "frame-*.jpg"), recursive=True)
                   if os.path.getmtime(f) >= t_start - 1)
    if not shots:
        tool_error("TOOL ERROR (no snaps; snap.py said: %s)" % (r.stdout + r.stderr)[-400:])
    fails = warns = 0
    sys.path.insert(0, os.path.join(os.path.dirname(KIT), "qa"))
    import gate as _gate   # noqa: E402
    _exc = os.path.join(KIT, "out", a.id, "lint-exceptions.json")
    _allow = {x.get("text") for x in (json.load(open(_exc)).get("lint", []) if os.path.exists(_exc) else [])}
    for f in shots:
        r = subprocess.run([os.path.join(KIT, "tools", "ocr_vision"), f], capture_output=True, text=True)
        if r.returncode or not r.stdout.strip():
            tool_error("TOOL ERROR (OCR rc %d for %s): %s" % (r.returncode, os.path.basename(f), (r.stderr or r.stdout)[-300:]))
        try:
            o = json.loads(r.stdout)
        except (TypeError, ValueError) as e:
            tool_error("TOOL ERROR (invalid OCR JSON for %s): %s" % (os.path.basename(f), e))
        if not isinstance(o, dict) or not valid_number(o.get("w"), positive=True) or not valid_number(o.get("h"), positive=True) or not isinstance(o.get("lines"), list):
            tool_error("TOOL ERROR (OCR result missing valid dimensions/lines for %s)" % os.path.basename(f))
        w, h = o["w"], o["h"]
        sc = 1080.0 / w
        m = re.search(r"at-([\d.]+)s", f)
        t = m.group(1) if m else os.path.basename(f)
        for l in o.get("lines", []):
            if not isinstance(l, dict) or not isinstance(l.get("text"), str) or any(not valid_number(l.get(k)) for k in ("conf", "x", "y", "w", "h")) or l["w"] <= 0 or l["h"] <= 0:
                tool_error("TOOL ERROR (invalid OCR line schema for %s)" % os.path.basename(f))
            if l.get("conf", 0) < 0.3 or len(re.sub(r"\s", "", l.get("text", ""))) < 3:
                continue
            # root 6 Oct: gate check 2 failed S82/S72/S65 on dashes and AI-tell words in on-screen text. Run the gate's own
            # lint on the same OCR text the gate will see, honouring out/<ID>/lint-exceptions.json (exact strings).
            hits = [x for x in _gate.lint_text(l["text"]) if l["text"] not in _allow]
            if hits:
                print("FAIL %6ss %-15s %s | %s" % (t, "text-lint", "; ".join(x.get("hit", "") for x in hits)[:60], l["text"][:70]))
                fails += 1
            box = {"x0": l["x"] * sc, "x1": (l["x"] + l["w"]) * sc, "y0": l["y"] * sc, "y1": (l["y"] + l["h"]) * sc}
            for sev, kind, detail in platforms.box_problems(p, box):
                print("%s %6ss %-15s %s | %s" % (sev, t, kind, detail, l["text"][:70]))
                fails += sev == "FAIL"; warns += sev == "WARN"
    lab = []
    for f in shots:
        m = re.search(r"at-([\d.]+)s", os.path.basename(f))
        if m:
            lab.append("%s@%ss" % (os.path.basename(os.path.dirname(f)).split("-")[-1], m.group(1)))   # part letter @ local time
    print("checked at (part@local time): " + ", ".join(sorted(lab)))
    print("frame_precheck %s -> %s: %d snaps, %d FAIL, %d WARN (snaps: out/%s/snap/)" % (a.id, p["key"], len(shots), fails, warns, a.id))
    # root 6 Oct (dom-lint card): the DOM-level lint (text under 42 px, stacked text, empty cut frames, text lint) sees what this OCR pass
    # cannot. It runs on GitHub Actions in its own tool, so this is ONLY an advisory pointer at its last result; it never changes the exit code.
    try:
        rj = os.path.join(KIT, "out", a.id, "domlint", "result.json")
        bj = os.path.join(KIT, "out", a.id, "build", "parts.json")
        if os.path.exists(rj) and os.path.getmtime(rj) >= os.path.getmtime(bj):
            r = json.load(open(rj)); st = r.get("stats", {})
            print("dom_lint (advisory, last run for this build): %d FAIL, %d WARN -> python3 tools/dom_lint.py %s for a fresh one; required before submit" % (st.get("FAIL", 0), st.get("WARN", 0), a.id))
        else:
            print("dom_lint (advisory): no result for this build yet -> run `python3 tools/dom_lint.py %s` (Actions, about 2 min, no Mac load); 0 FAIL is required before submit" % a.id)
    except (OSError, ValueError):
        pass
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
