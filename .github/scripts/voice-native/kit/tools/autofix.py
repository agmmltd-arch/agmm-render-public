#!/usr/bin/env python3
"""autofix.py <ID> [--dry] [--only stereo,img,widow,lint,hold]   (kit/ maker kit v3, 13 Oct 2026)

Deterministic repairs for the commonest precheck FAILs. Each fix is mechanical (no model, no guess); anything that needs judgment is REPORTED with the
exact place and left alone. Every file it changes is first copied to out/<ID>/spec-archive/<file>.<YYYY-MM-DD-HHMM> (outside specs/<ID>/, so the approval
hash is not disturbed by the archive). Nothing is rendered; after a change run `python3 produce.py <ID> --only build` (precheck_all does it) and re-check.

  stereo  gate check 15. If the newest GATE.json has failing stereo rows: runs tools/autostereo.py (it sets each cue's x to the picture position the gate
          measured). With no GATE.json yet (pre-render) it only SCANS spec.json: lists cues with no x/pan and cues with x in the dead zone 470..590
          (better_than_last counts those as unpanned); it cannot know an object's x, so it changes nothing.
  img     a card <img> drawn at the wrong aspect (polish_check `distort`, the S69/S71 squashed quote cards). For every item in specs/<ID>/sources.js
          (src + px) the built copies (out/<ID>/img, kit/media/<ID>/final) are compared with the clause PNG (specs/<ID>/media/<key>.png or
          kit/media/<ID>/clauses/<key>.png); a copy whose aspect differs by > 3% from `px` while the clause PNG matches `px` is replaced from it.
  widow   polish_check `widow` (a wrapped block ending on ONE word). If the block's text is a single string literal in specs/<ID>/*.js or spec.json,
          the gap before the last word becomes a no-break space (what AGP.motion.widow(el) does at run time). Otherwise reported with the text.
  lint    out/<ID>/lint-exceptions.json must be valid JSON {"lint":[{"text":..,"reason":..}]}; a truncated or list-shaped file is silently ignored by the gate.
          Recovers complete entries, drops exact duplicates, wraps a bare list, and reports entries with no reason / no lint hit (useless) / non-'source crop:' reason.
  hold    beats with "hold": 0.001 become "hold": 0 (the one-frame double exposure whenever k/30 lands inside [next.from, next.from+0.001)).

Library: run(ID, dry=False, only=None, kit=None) -> list of report dicts {fix, status: changed|would-change|ok|report|error, detail}.
Env AUTOFIX_KIT points at another kit root (the tests use it)."""
import argparse, glob, json, os, re, shutil, subprocess, sys, time

TOOLS = os.path.dirname(os.path.abspath(__file__))
DEFAULT_KIT = os.environ.get("AUTOFIX_KIT") or os.path.dirname(TOOLS)
NBSP = " "
FIXES = ["stereo", "img", "widow", "lint", "hold"]


class K:
    def __init__(self, sid, kit=None, dry=False):
        self.id = sid
        self.kit = kit or DEFAULT_KIT
        self.v2 = os.path.dirname(self.kit)
        self.spec = os.path.join(self.kit, "specs", sid)
        self.out = os.path.join(self.kit, "out", sid)
        self.dry = dry
        self.archive = os.path.join(self.out, "spec-archive")
        self.tag = time.strftime("%Y-%m-%d-%H%M")

    def backup(self, path):
        os.makedirs(self.archive, exist_ok=True)
        dest = os.path.join(self.archive, os.path.basename(path) + "." + self.tag)
        if not os.path.exists(dest):
            shutil.copy2(path, dest)
        return dest

    def write(self, path, data, binary=False):
        self.backup(path)
        tmp = path + ".autofix-tmp"
        with open(tmp, "wb" if binary else "w") as f:
            f.write(data)
        os.replace(tmp, path)

    def spec_files(self):
        """non-archived code/spec files of the short (the same ones storyboard.spec_hash looks at)."""
        rx = re.compile(r"(\.bak|_archive|^old-|^r\d+/|-returned\.)")
        out = []
        for f in sorted(glob.glob(os.path.join(self.spec, "*"))):
            rel = os.path.relpath(f, self.spec)
            if os.path.isfile(f) and f.endswith((".js", ".json")) and not rx.search(rel) and rel not in ("concept.json",):
                out.append(f)
        return out


def rep(fix, status, detail):
    return {"fix": fix, "status": status, "detail": detail}


# ------------------------------------------------------------------------------------------------------------- stereo
def fix_stereo(k):
    gates = sorted(glob.glob(os.path.join(k.out, "gate", "*", "GATE.json")), key=os.path.getmtime)
    spec_p = os.path.join(k.spec, "spec.json")
    if gates:
        try:
            g = json.load(open(gates[-1]))
            c15 = [c for c in g.get("checks", []) if str(c.get("id")) == "15"]
            rows = [r for r in ((c15[0].get("details") or {}).get("stereo") or {}).get("rows", []) if not r.get("pass")] if c15 else []
        except (OSError, ValueError) as e:
            return [rep("stereo", "error", "cannot read %s: %s" % (gates[-1], e))]
        if rows:
            cmd = [sys.executable, os.path.join(TOOLS, "autostereo.py"), k.id] + (["--dry"] if k.dry else [])
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=k.kit)
            txt = (p.stdout + p.stderr).strip()
            mm = re.search(r"(\d+) changed", txt)
            n_changed = int(mm.group(1)) if mm else 0
            status = "report" if (p.returncode or not n_changed) else ("would-change" if k.dry else "changed")
            return [rep("stereo", status, "autostereo (%d failing gate rows in %s, rc %d): %s" % (len(rows), os.path.relpath(gates[-1], k.kit), p.returncode, txt[-600:]))]
    try:
        spec = json.load(open(spec_p))
    except (OSError, ValueError) as e:
        return [rep("stereo", "error", "cannot read spec.json: %s" % e)]
    nox, centre, total = [], [], 0
    for b in spec.get("beats", []):
        for c in b.get("sfx", []) or []:
            total += 1
            if c.get("x") is None and c.get("pan") is None:
                nox.append("%s:%s@%s" % (b.get("id"), c.get("kind") or c.get("id"), c.get("at")))
            elif c.get("x") is not None and 470 <= float(c["x"]) <= 590:
                centre.append("%s:%s x=%s" % (b.get("id"), c.get("kind") or c.get("id"), c["x"]))
    if not nox and not centre:
        return [rep("stereo", "ok", "%d authored cues, every one has an x/pan outside the dead zone (no failing gate rows: pre-render scan only)" % total)]
    d = "pre-render scan of %d cues (no failing GATE rows yet, so nothing is moved: only the object's real x on screen can fix these): " % total
    if nox:
        d += "%d with no x/pan: %s%s; " % (len(nox), ", ".join(nox[:8]), " ..." if len(nox) > 8 else "")
    if centre:
        d += "%d with x in 470..590 (counted as unpanned; use 330/760 for cards, the object's real x otherwise): %s%s" % (len(centre), ", ".join(centre[:8]), " ..." if len(centre) > 8 else "")
    return [rep("stereo", "report", d)]


# ------------------------------------------------------------------------------------------------------------- img aspect
def png_size(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


def fix_img(k):
    sp = os.path.join(k.spec, "sources.js")
    if not os.path.exists(sp):
        return [rep("img", "ok", "no sources.js")]
    txt = open(sp).read()
    m = re.search(r"=\s*(\{.*\})\s*;?\s*$", txt, re.S)
    try:
        data = json.loads(m.group(1)) if m else {}
    except ValueError as e:
        return [rep("img", "error", "sources.js is not plain JSON after '=': %s" % e)]
    items = data.get("items") or {}
    out, checked = [], 0
    for key, it in items.items():
        src, px = it.get("src"), it.get("px")
        if not src or not px or len(px) != 2 or not px[1]:
            continue
        base = os.path.basename(src)
        suffix = base.split("real-%s-" % k.id.lower(), 1)[-1]
        truth = [p for p in (os.path.join(k.spec, "media", suffix), os.path.join(k.spec, "media", "clauses", suffix),
                             os.path.join(k.kit, "media", k.id, "clauses", suffix)) if os.path.exists(p)]
        targets = [p for p in (os.path.join(k.out, "img", base), os.path.join(k.kit, "media", k.id, "final", base)) if os.path.exists(p)]
        want = px[0] / float(px[1])
        good = None
        for t in truth:
            sz = png_size(t)
            if sz and abs(sz[0] / float(sz[1]) / want - 1) <= 0.03:
                good = t
                break
        for t in targets:
            sz = png_size(t)
            if not sz:
                continue
            checked += 1
            have = sz[0] / float(sz[1])
            if abs(have / want - 1) <= 0.03:
                continue
            what = "%s is %dx%d (aspect %.2f) but sources.js px %s says %.2f" % (os.path.relpath(t, k.kit), sz[0], sz[1], have, px, want)
            if not good:
                out.append(rep("img", "report", what + "; no clause PNG with the right aspect found (re-run crop_clause --install)"))
                continue
            if k.dry:
                out.append(rep("img", "would-change", what + "; would copy %s over it" % os.path.relpath(good, k.kit)))
            else:
                k.backup(t)
                shutil.copyfile(good, t)
                out.append(rep("img", "changed", what + "; replaced from %s (old copy in out/%s/spec-archive)" % (os.path.relpath(good, k.kit), k.id)))
    return out or [rep("img", "ok", "%d built image copies checked against sources.js px, all within 3%% of their aspect" % checked)]


# ------------------------------------------------------------------------------------------------------------- widow
def latest_widows(k):
    """-> list of text strings from the newest polish findings with rule widow."""
    texts = []
    for p in (os.path.join(k.out, "polish", "result.json"),):
        if os.path.exists(p):
            try:
                d = json.load(open(p))
                fl = d.get("findings") if isinstance(d, dict) else d
                for f in fl or []:
                    if f.get("rule") == "widow" and f.get("text"):
                        texts.append(f["text"])
            except (OSError, ValueError):
                pass
    log = os.path.join(k.out, "precheck", "polish.log")
    if not texts and os.path.exists(log):
        for l in open(log, errors="replace"):
            if " widow " in l:
                m = re.search(r"'([^']{8,})'", l)
                if m:
                    texts.append(m.group(1))
    seen, out = set(), []
    for t in texts:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def fix_widow(k):
    texts = latest_widows(k)
    if not texts:
        return [rep("widow", "ok", "no widow finding in out/%s/polish (run polish_check / precheck_all first)" % k.id)]
    files = k.spec_files()
    blobs = {f: open(f).read() for f in files}
    res = []
    for t in texts:
        words = t.split()
        if len(words) < 4 or NBSP in t:
            continue
        pat = re.compile(r"""(["'`])(%s[^"'`\n\\]*)\1""" % re.escape(t))
        hits = [(f, m) for f, b in blobs.items() for m in pat.finditer(b)]
        # a truncated finding text may be a prefix of a longer literal: accept a unique literal that STARTS with it
        hits = [(f, m) for f, m in hits if " " in m.group(2).strip()]
        if len(hits) != 1:
            res.append(rep("widow", "report", "'%s': %s string literals in specs/%s (needs exactly 1); use AGP.motion.widow(el) where the element is made" % (t[:50], len(hits), k.id)))
            continue
        f, m = hits[0]
        lit = m.group(2)
        i = lit.rstrip().rfind(" ")
        if i < 0:
            continue
        new = lit[:i] + NBSP + lit[i + 1:]
        b = blobs[f]
        blobs[f] = b[:m.start(2)] + new + b[m.end(2):]
        if f.endswith(".json"):
            try:
                json.loads(blobs[f])
            except ValueError:
                blobs[f] = b
                res.append(rep("widow", "report", "'%s': edit would break %s" % (t[:50], os.path.basename(f))))
                continue
        res.append(rep("widow", "would-change" if k.dry else "changed", "%s: '...%s' -> no-break space before '%s'" % (os.path.basename(f), lit[max(0, i - 24):i], lit[i + 1:])))
    if not k.dry:
        for f, b in blobs.items():
            if open(f).read() != b:
                k.write(f, b)
    return res or [rep("widow", "ok", "no widow needs a fix")]


# ------------------------------------------------------------------------------------------------------------- lint exceptions
def fix_lint(k):
    p = os.path.join(k.out, "lint-exceptions.json")
    if not os.path.exists(p):
        return [rep("lint", "ok", "no out/%s/lint-exceptions.json (nothing to validate)" % k.id)]
    raw = open(p, errors="replace").read()
    entries, problems, notes, rewritten = [], [], [], False
    try:
        d = json.loads(raw)
        if isinstance(d, list):
            entries, rewritten = d, True
            problems.append("bare list: wrapped as {\"lint\": [...]}")
        elif isinstance(d, dict) and isinstance(d.get("lint"), list):
            entries = d["lint"]
        else:
            problems.append("valid JSON but no \"lint\" list: the gate ignores it")
    except ValueError as e:
        problems.append("INVALID JSON (%s): the gate silently ignores a truncated file" % str(e)[:60])
        for m in re.finditer(r'\{\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"reason"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}', raw):
            try:
                entries.append({"text": json.loads('"%s"' % m.group(1)), "reason": json.loads('"%s"' % m.group(2))})
            except ValueError:
                pass
        rewritten = bool(entries)
    clean, seen = [], set()
    gate = None
    try:
        sys.path.insert(0, os.path.join(k.v2, "qa"))
        import gate as gate  # noqa: E402
    except Exception:
        gate = None
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get("text"), str) or not e["text"].strip():
            problems.append("entry without text dropped: %s" % json.dumps(e)[:60])
            rewritten = True
            continue
        if e["text"] in seen:
            problems.append("duplicate '%s' dropped" % e["text"][:40])
            rewritten = True
            continue
        seen.add(e["text"])
        if not (e.get("reason") or "").strip():
            problems.append("'%s' has no reason (the reviewer needs the outlet; cannot be invented)" % e["text"][:40])
        elif not e["reason"].lower().startswith("source crop"):
            notes.append("'%s': reason does not start 'source crop: <outlet>' (only a publisher's own wording inside a real crop is excusable; a fader label read as a dash is the other legitimate case)" % e["text"][:40])
        if gate is not None:
            try:
                if not gate.lint_text(e["text"]):
                    problems.append("'%s' triggers no lint hit: useless exception (the OCR line is not exact, or it is not needed)" % e["text"][:40])
            except Exception:
                pass
        clean.append(e)
    if rewritten and clean:
        body = json.dumps({"lint": clean}, indent=1, ensure_ascii=False) + "\n"
        if k.dry:
            return [rep("lint", "would-change", "%d entries kept; %s" % (len(clean), "; ".join(problems)))]
        k.write(p, body)
        return [rep("lint", "changed", "rewrote valid JSON with %d entries; %s" % (len(clean), "; ".join(problems)))]
    if rewritten and not clean:
        return [rep("lint", "report", "unrecoverable, nothing rewritten: %s" % "; ".join(problems))]
    if problems:
        return [rep("lint", "report", "; ".join(problems + notes))]
    return [rep("lint", "ok", "valid, %d exact entries, each with a reason and a real lint hit%s" % (len(clean), ("; note: " + "; ".join(notes)) if notes else ""))]


# ------------------------------------------------------------------------------------------------------------- hold
def fix_hold(k):
    p = os.path.join(k.spec, "spec.json")
    try:
        txt = open(p).read()
        spec = json.loads(txt)
    except (OSError, ValueError) as e:
        return [rep("hold", "error", "cannot read spec.json: %s" % e)]
    n = len(re.findall(r'"hold"\s*:\s*0\.001\b', txt))
    unset = [b.get("id") for b in spec.get("beats", []) if "hold" not in b]
    out = []
    if n:
        new = re.sub(r'("hold"\s*:\s*)0\.001\b', r"\g<1>0", txt)
        json.loads(new)
        if k.dry:
            out.append(rep("hold", "would-change", "%d beats with \"hold\": 0.001 would become 0" % n))
        else:
            k.write(p, new)
            out.append(rep("hold", "changed", "%d beats \"hold\": 0.001 -> 0 (one-frame double exposure at k/30 inside [from, from+0.001))" % n))
    if unset and spec.get("kit_defaults") != "2026-09-28":
        out.append(rep("hold", "report", "%d beats have no hold and kit_defaults is %r: the old default hold is 0.5 s (outgoing scene stays 0.5 s under the next); set kit_defaults \"2026-09-28\" and \"hold\": 0" % (len(unset), spec.get("kit_defaults"))))
    return out or [rep("hold", "ok", "no beat has hold 0.001")]


RUN = {"stereo": fix_stereo, "img": fix_img, "widow": fix_widow, "lint": fix_lint, "hold": fix_hold}


def run(sid, dry=False, only=None, kit=None):
    k = K(sid, kit, dry)
    out = []
    for name in FIXES:
        if only and name not in only:
            continue
        try:
            out += RUN[name](k)
        except Exception as e:      # a fixer bug must never look like "nothing wrong"
            out.append(rep(name, "error", "%s: %s" % (type(e).__name__, e)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("id")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--only")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    bad = (only or set()) - set(FIXES)
    if bad:
        ap.error("unknown fix %s (have %s)" % (",".join(sorted(bad)), ",".join(FIXES)))
    res = run(a.id, a.dry, only)
    changed = 0
    for r in res:
        print("%-12s %-7s %s" % (r["status"].upper(), r["fix"], r["detail"]))
        changed += r["status"] == "changed"
    errs = [r for r in res if r["status"] == "error"]
    reports = [r for r in res if r["status"] == "report"]
    print("autofix %s%s: %d changed, %d need a hand, %d errors%s" % (a.id, " (dry)" if a.dry else "", changed, len(reports), len(errs),
          ("  -> next: python3 produce.py %s --only build, then python3 tools/precheck_all.py %s" % (a.id, a.id)) if changed else ""))
    sys.exit(2 if errs else 0)


if __name__ == "__main__":
    main()
