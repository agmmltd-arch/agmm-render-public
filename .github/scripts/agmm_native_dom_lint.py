#!/usr/bin/env python3
"""dom_lint.py <ID> [--every 0.1] [--platform P] [--backend actions|local] [--raw raw.json] [--json out.json]
(root cards 6 Oct 2026, "dom-lint"; maker-decomposition.md section 4 fix #1)

A deterministic DOM-level lint of a short's BUILT package. Scenes are DOM and pure functions of time, so the part's own GSAP
timeline is seeked headlessly (the mechanism hyperframes' gsap adapter and specs/S01/tools/fsnap.py use) and at every sample time
the runner (tools/dom_lint_runner.mjs) records every visible text element's final on-screen box (after camera transforms, at
1080x1920 master px), its effective opacity (product up the tree) and its rendered font px. This file turns those facts into
FAIL/WARN lines, per (time, element):

  legibility     rendered text under 42 px (opacity > 0.5, on screen for >= 0.4 s). Also text drawn INSIDE an <img> (a captured
                 source strip): its line height is read from the image's own pixels and multiplied by the displayed scale.
  frame          text box outside the routed platform's visible rect, or >= 5% under a measured overlay
                 (platforms.box_problems, the gate's own rules; unrouted shorts are judged as instagram)
  stacked        two visible text boxes overlapping each other by > 15% of the smaller box
  empty-on-cut   a cut frame (beat start + 0.04 s) with no visible text and no non-background element covering >= 20% of the frame
  text-lint      the gate's own lint_text (dashes, AI-tell phrases, banned CTA ...) on the actual strings, honouring
                 out/<ID>/lint-exceptions.json

WHERE IT RUNS: headless Chrome is heavy for this Mac, so by default it runs on GitHub Actions (workflow agmm-short-domlint.yml in
agmmltd-arch/agmm-render-public, the sibling of agmm-short-snap.yml; same package tarball, same secret scan, same release, same
polling discipline: every ~15 s with jitter). --backend local (or DOM_LINT=local) runs the same runner through tools/heavy.py
(3 machine-wide slots). --raw FILE re-judges a saved raw JSON with no browser at all (rule tuning, calibration).

Blind spots (named): text painted into a <canvas> or baked into an image that is not a clean text card is invisible to the DOM
(emptiness counts canvases as content); the 42 px floor is the DOM font size x the camera scale, the OCR line height that reviewers
quote is about 1.0-1.1 x that for the same font; perspective (3D) distortion is ignored; clip-path / mask reveals are flagged but
not modelled. Exit code 1 if any FAIL, 2 on a tool error, else 0."""
import argparse, glob, json, math, os, random, re, shutil, subprocess, sys, tempfile, time

TOOLS = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(TOOLS)
V2 = os.path.dirname(KIT)
sys.path.insert(0, os.path.join(KIT, "platforms"))
sys.path.insert(0, os.path.join(V2, "qa"))
import platforms  # noqa: E402

FW, FH = 1080.0, 1920.0
FLOOR_PX = 42.0          # reviewers' legibility floor (craft standard: nothing under 42 px at 1080 wide)
FLOOR_TOL = 1.0          # measurement tolerance: a 42 px font under a 0.98 camera scale (41.3) is not a defect
OPACITY_MIN = 0.5        # text below this is not "visible" for the legibility rule (card)
MIN_RUN_S = 0.4          # card: on screen >= 0.4 s
STACK_OPACITY = 0.8      # both texts must be nearly solid to count as stacked
OVERLAP_FRAC = 0.15      # card: stacked text if overlap > 15% of the smaller box
SPARSE_COVER = 0.10      # a cut frame whose text and objects together fill under this share of the frame is WARNed as sparse
EMPTY_COVER = 0.20       # card: a cut frame needs text or an element covering >= 20% of the frame
IMG_OCR_RATIO = 1.0      # OCR line height / ink-row height of a text image: 1.09 on S102's strips, 1.0 on C13's, so 1.0 (no inflation)
TEXTURE_PX = 24.0        # below this a string is texture (a dial's tick numerals, a micro label), nobody is meant to read it: counted, not reported
READ_FAIL_PX = 38.0      # READING text (>= 3 words) under this is a FAIL; 38 to 41 and every short label under 41 is a WARN (see CALIBRATION in the report)
IMG_FAIL_PX = 37.0       # text inside an image: the ink-row measure carries about +-10% error against OCR, so FAIL only when clearly under
ONFRAME_MIN = 0.25       # a text box with less than this share inside the frame is parked off-canvas, not "on screen"
OCC_HIDE = 0.6           # a text whose probe points are >= 60% under an opaque painter is hidden, not stacked
ACTIONS_REPO = "agmmltd-arch/agmm-render-public"
ACTIONS_WF = "agmm-short-domlint.yml"
LEDGER = os.path.join(KIT, "registry", "actions-domlint-usage.jsonl")


def log(msg):
    print("dom_lint: " + msg, file=sys.stderr, flush=True)


def tool_error(msg):
    print("TOOL ERROR: " + msg, file=sys.stderr)
    raise SystemExit(2)


# ------------------------------------------------------------------------------------------------- plan
def load_build(sid, build_dir=None):
    out = os.path.join(KIT, "out", sid)
    bd = build_dir or os.path.join(out, "build")
    try:
        parts = json.load(open(os.path.join(bd, "parts.json")))["parts"]
    except (OSError, ValueError, KeyError) as e:
        tool_error("no readable %s/parts.json (build the package first: produce.py %s --only build): %s" % (bd, sid, e))
    beats = []
    try:
        r = json.load(open(os.path.join(out, "resolved.json")))
        beats = r.get("beats", r) if isinstance(r, dict) else r
        beats = [float(b["from"]) for b in beats]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return out, bd, parts, beats


def sample_times(parts, beats, every):
    """Story-time samples: a grid every `every` s, plus at each beat start f: the cut frame f+0.04 and the seam probes f-0.04,
    f+0.02, f+0.06 (the same instants the craft standard asks reviewers to look at). Returns {T: kind}."""
    total = parts[-1]["off"] + parts[-1]["dur"]
    T = {}
    n = int(total / every + 1e-9)
    for i in range(n + 1):
        t = round(i * every, 3)
        if t < total - 0.02:
            T[t] = "grid"
    last = round(total - 0.05, 3)
    T.setdefault(last, "grid")
    for f in beats:
        for d, kind in ((0.04, "cut"), (-0.04, "seam"), (0.02, "seam"), (0.06, "seam")):
            t = round(f + d, 3)
            if 0 <= t < total - 0.02:
                if kind == "cut" or t not in T:
                    T[t] = kind if T.get(t) != "cut" else "cut"
    return T


def make_plan(parts, T):
    """Snap-format plan [{look, part, times}] (part-local seconds, 2 decimals: that is the workflow's own precision) and the lookup
    {(part, local): (story time, kind)} that maps every sample back to the story clock (parts do not start on round seconds)."""
    plan, look = [], {}
    for p in parts:
        loc = set()
        for t, kind in sorted(T.items()):
            if p["off"] - 1e-9 <= t < p["off"] + p["dur"]:
                l = round(min(t - p["off"], p["dur"] - 0.02), 2)
                loc.add(l)
                prev = look.get((p["out"], l))
                if prev is None or kind == "cut" or (kind == "seam" and prev[1] == "grid"):
                    look[(p["out"], l)] = (t, kind)
        if loc:
            plan.append({"look": p["look"], "part": p["out"], "times": sorted(loc)})
    return plan, look


# ------------------------------------------------------------------------------------------------- backends
def local_runner_cmd():
    node = os.path.expanduser("~/.local/node/bin/node")
    if not os.path.exists(node):
        node = shutil.which("node") or tool_error("no node on this Mac (~/.local/node/bin/node)")
    ppt = os.environ.get("DOM_LINT_PUPPETEER")
    if not ppt:
        cands = sorted(glob.glob(os.path.expanduser("~/.npm/_npx/*/node_modules/puppeteer-core")), key=os.path.getmtime)
        ppt = cands[-1] if cands else tool_error("no puppeteer-core in ~/.npm/_npx (run `npx hyperframes@0.8.71 --version` once)")
    chrome = os.environ.get("DOM_LINT_CHROME") or next(iter(sorted(glob.glob(os.path.expanduser(
        "~/.cache/hyperframes/chrome/chrome-headless-shell/*/*/chrome-headless-shell")))), None)
    if not chrome:
        tool_error("no headless chrome (set DOM_LINT_CHROME)")
    return node, ppt, chrome


def run_local(sid, root, plan, prof_json, raw_path, css=None):
    """The only local route: tools/heavy.py (3 machine-wide slots, load-aware), never a bare Chrome."""
    node, ppt, chrome = local_runner_cmd()
    tmp = tempfile.mkdtemp(prefix="agmm-domlint-")
    try:
        pj, prj = os.path.join(tmp, "plan.json"), os.path.join(tmp, "profile.json")
        json.dump(plan, open(pj, "w")); json.dump(prof_json, open(prj, "w"))
        cmd = [sys.executable, os.path.join(TOOLS, "heavy.py"), "--", node, os.path.join(TOOLS, "dom_lint_runner.mjs"), "--root", root,
               "--plan", pj, "--out", raw_path, "--chrome", chrome, "--puppeteer", ppt, "--profile", prj] + (["--css", css] if css else [])
        log("local runner via heavy.py (%d samples over %d parts)" % (sum(len(j["times"]) for j in plan), len(plan)))
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1900)
        if r.returncode:
            tool_error("local runner rc %d: %s" % (r.returncode, (r.stdout + r.stderr)[-600:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_actions(sid, parts, plan, prof_json, raw_path, prebuilt=None):
    sys.path.insert(0, TOOLS)
    import snap  # noqa: E402  (reuse its package tar, secret scan, content-hashed release and gh wrapper: one mechanism, not two)
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix="agmm-domlint-actions-")
    run_id = None
    try:
        if prebuilt:   # an archived package that already is a content-hashed release of the public repo (--release)
            release, sha = prebuilt
            how = "archived"
        else:
            tarball, sha, size = snap._package_tar(sid, [p["look"] for p in parts], tmp)
            snap._secret_scan(tarball)
            release, how = snap._snap_release(sid, tarball, sha, size)
        label = "%s-dl-%s-%d-%d" % (sid, sha[:8], int(time.time()), os.getpid())
        r = snap._gh(["workflow", "run", ACTIONS_WF, "-R", ACTIONS_REPO, "--ref", "main", "-f", "release=" + release, "-f", "source_sha256=" + sha,
                      "-f", "tag=" + label, "-f", "plan=" + json.dumps(plan, separators=(",", ":")),
                      "-f", "profile=" + json.dumps(prof_json, separators=(",", ":"))])
        m = re.search(r"/actions/runs/(\d+)", (r.stdout or "") + (r.stderr or ""))
        run_id = m.group(1) if m else None
        t_end = time.time() + float(os.environ.get("AGMM_DOMLINT_WAIT", "1500"))
        title = "AGMM short DOM lint " + label
        while run_id is None and time.time() < t_end:
            rows = json.loads(snap._gh(["run", "list", "-R", ACTIONS_REPO, "--workflow", ACTIONS_WF, "--event", "workflow_dispatch",
                                        "--limit", "30", "--json", "databaseId,displayTitle"]).stdout)
            hit = [x for x in rows if x.get("displayTitle") == title]
            if hit:
                run_id = str(hit[0]["databaseId"])
            else:
                time.sleep(12 + random.random() * 6)
        if run_id is None:
            raise RuntimeError("the workflow run never appeared")
        log("actions run %s (package %s %s, %.0f s to dispatch)" % (run_id, release, how, time.time() - t0))
        status = conclusion = ""
        t_wait = time.time(); qwait = float(os.environ.get("AGMM_SNAP_QUEUE_WAIT", "600"))
        while time.time() < t_end:
            v = json.loads(snap._gh(["run", "view", run_id, "-R", ACTIONS_REPO, "--json", "status,conclusion"], check=False).stdout or "{}")
            status, conclusion = v.get("status", ""), v.get("conclusion", "")
            if status == "completed":
                break
            if status != "in_progress" and time.time() - t_wait > qwait:
                snap._gh(["run", "cancel", run_id, "-R", ACTIONS_REPO], check=False)
                raise RuntimeError("run %s still %s after %.0f s (no hosted runner); cancelled it" % (run_id, status or "queued", qwait))
            if status == "in_progress":
                t_wait = time.time()
            time.sleep(12 + random.random() * 6)   # GitHub's secondary rate limit (6 Oct 08:55): never faster than ~15 s with jitter
        if status != "completed":
            raise RuntimeError("workflow run %s did not finish within the wait (status %r)" % (run_id, status))
        if conclusion != "success":
            tail = (snap._gh(["run", "view", run_id, "-R", ACTIONS_REPO, "--log-failed"], check=False, timeout=120).stdout or "")[-900:]
            raise RuntimeError("workflow run %s ended %s: %s" % (run_id, conclusion, tail))
        name = label + "-DOMLINT"
        last = ""
        for _ in range(6):
            d = snap._gh(["run", "download", run_id, "-R", ACTIONS_REPO, "-n", name, "-D", os.path.join(tmp, "dl")], check=False, timeout=600)
            if d.returncode == 0:
                break
            last = (d.stderr or d.stdout)[-300:]
            time.sleep(3)
        else:
            raise RuntimeError("artifact %s did not download: %s" % (name, last))
        src = os.path.join(tmp, "dl", "raw.json")
        if not os.path.exists(src):
            raise RuntimeError("artifact has no raw.json: %s" % os.listdir(os.path.join(tmp, "dl")))
        os.makedirs(os.path.dirname(raw_path), exist_ok=True)
        shutil.copyfile(src, raw_path)
        log("actions done in %.0f s (run %s)" % (time.time() - t0, run_id))
        try:
            with open(LEDGER, "a") as fh:
                fh.write(json.dumps({"id": sid, "kind": "domlint-actions", "run": run_id, "release": how, "wall_s": round(time.time() - t0),
                                     "samples": sum(len(j["times"]) for j in plan), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        except OSError:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------------------------------------- archived packages
def load_release(tag, tmp):
    """--release snap-<id>-<sha16>: lint an ARCHIVED package (the content-hashed releases snap.py and dom_lint.py upload, one per
    build, kept forever) instead of the current build, e.g. the version a reviewer returned after a maker has already rebuilt.
    Returns (root dir holding one folder per look, parts, beat starts, tarball sha256)."""
    import hashlib, tarfile
    sys.path.insert(0, TOOLS)
    import snap  # noqa: E402
    if not re.fullmatch(r"snap-[a-z0-9]+-[0-9a-f]{16}", tag):
        tool_error("not a snap release tag: %r" % tag)
    snap._gh(["release", "download", tag, "-R", ACTIONS_REPO, "-p", "source.tar.gz", "-D", tmp, "--clobber"], timeout=600)
    tarp = os.path.join(tmp, "source.tar.gz")
    h = hashlib.sha256(open(tarp, "rb").read()).hexdigest()
    root = os.path.join(tmp, "pkg")
    os.makedirs(root)
    with tarfile.open(tarp) as tf:
        for m in tf.getmembers():
            if m.name.startswith("/") or ".." in m.name.split("/") or not (m.isreg() or m.isdir()):
                tool_error("unsafe member in the archived package: %r" % m.name)
        tf.extractall(root)
    parts, beats = [], []
    for look in sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))):
        html = open(os.path.join(root, look, "index.html"), errors="replace").read()
        m = re.search(r"AGK_PART\s*=\s*\{\s*off:\s*([\d.]+),\s*dur:\s*([\d.]+)", html)
        if not m:
            continue
        parts.append({"look": look, "out": look.upper(), "off": float(m.group(1)), "dur": float(m.group(2))})
        if not beats:
            try:
                sp = open(os.path.join(root, look, "spec.js")).read()
                beats = [float(b["from"]) for b in json.loads(re.search(r"=\s*(\{.*\})\s*;?\s*$", sp, re.S).group(1))["beats"]]
            except Exception:
                beats = []
    if not parts:
        tool_error("the archived package has no parts (no AGK_PART in any index.html)")
    parts.sort(key=lambda p: p["off"])
    return root, parts, beats, h


# ------------------------------------------------------------------------------------------------- geometry
def area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def inter_area(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def onframe_frac(boxes):
    tot = sum(area(b) for b in boxes) or 1.0
    return sum(inter_area(b, (0, 0, FW, FH)) for b in boxes) / tot


def words(s):
    return len(re.findall(r"[A-Za-z0-9\u00c0-\u024f][^\s]*", s or ""))


def is_reading(s):
    """Text a viewer is meant to READ (a sentence fragment), as against a chip, a tick number or a label."""
    return words(s) >= 3 and alnum(s) >= 12


def alnum(s):
    return len(re.findall(r"[A-Za-z0-9À-ɏ]", s or ""))


def shown(T, need_op=OPACITY_MIN):
    """A text element a viewer can see: opaque enough, not clipped away by a mask, partly on the frame, not buried under a card."""
    if T["op"] <= need_op or T["vis"] < 0.5 or alnum(T["t"]) < 1:
        return False
    if T.get("occ") is not None and T["occ"] >= OCC_HIDE:
        return False
    return onframe_frac(T["ink"]) >= ONFRAME_MIN


def lines_of(texts):
    """Rebuild the visible LINES (what OCR would read) from per-element strings, so a phrase split across word spans is linted whole."""
    items = []
    for T in texts:
        for r in T["ink"]:
            items.append((((r[1] + r[3]) / 2.0), r, T["t"]))
    items.sort(key=lambda x: (round(x[0] / 6.0), x[1][0]))
    out, cur = [], []
    for cy, r, t in items:
        h = max(4.0, r[3] - r[1])
        if cur and abs(cur[-1][0] - cy) < 0.5 * h and r[0] - cur[-1][1][2] < 1.2 * h:
            cur.append((cy, r, t))
        else:
            if cur:
                out.append(cur)
            cur = [(cy, r, t)]
    if cur:
        out.append(cur)
    return [" ".join(x[2] for x in ln) for ln in out]


# ------------------------------------------------------------------------------------------------- rotated boxes
def quad(box, rot):
    """The four corners of a text box. A tilted object (a tag, a stamp) reports the axis-aligned bounding box of its tilted line, which is
    bigger than the text (S01's 'PART OF AN' over '£800M' overlapped as boxes and not as glyphs). With the element's cumulative rotation the
    bbox is turned back into the rectangle it came from: Wb = W cos + H sin, Hb = H cos + W sin."""
    x0, y0, x1, y1 = box
    wb, hb = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    c, sn = abs(math.cos(rot)), abs(math.sin(rot))
    den = c * c - sn * sn
    if abs(rot) < 0.0087 or den < 0.2:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    w = (wb * c - hb * sn) / den
    h = (hb * c - wb * sn) / den
    if w <= 1 or h <= 1:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    ct, st = math.cos(rot), math.sin(rot)
    return [(cx + px * ct - py * st, cy + px * st + py * ct) for px, py in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]


def poly_area(p):
    return abs(sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))) / 2.0


def poly_clip(subject, clip):
    """Sutherland-Hodgman: the part of convex polygon `subject` inside convex polygon `clip`."""
    def inside(pt, a, b):
        return (b[0] - a[0]) * (pt[1] - a[1]) - (b[1] - a[1]) * (pt[0] - a[0]) >= 0
    def cross(p1, p2, a, b):
        x1, y1, x2, y2, x3, y3, x4, y4 = p1[0], p1[1], p2[0], p2[1], a[0], a[1], b[0], b[1]
        d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(d) < 1e-9:
            return p2
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    # make both polygons clockwise-consistent
    def orient(p):
        return p if sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p))) > 0 else p[::-1]
    out = orient(subject); cl = orient(clip)
    for i in range(len(cl)):
        a, b = cl[i], cl[(i + 1) % len(cl)]
        inp, out = out, []
        if not inp:
            break
        s0 = inp[-1]
        for e in inp:
            if inside(e, a, b):
                if not inside(s0, a, b):
                    out.append(cross(s0, e, a, b))
                out.append(e)
            elif inside(s0, a, b):
                out.append(cross(s0, e, a, b))
            s0 = e
    return out


def box_overlap_frac(ra, rota, rb, rotb):
    """overlap area / area of the smaller of two (possibly tilted) text boxes."""
    if abs(rota) < 0.0087 and abs(rotb) < 0.0087:
        ov = inter_area(ra, rb)
        return ov / max(1.0, min(area(ra), area(rb))) if ov > 0 else 0.0
    if inter_area(ra, rb) <= 0:
        return 0.0
    qa, qb = quad(ra, rota), quad(rb, rotb)
    clipped = poly_clip(qa, qb)
    ov = poly_area(clipped) if len(clipped) >= 3 else 0.0
    return ov / max(1.0, min(poly_area(qa), poly_area(qb)))


# ------------------------------------------------------------------------------------------------- image text (a source strip is text too)
_IMG_CACHE = {}


def image_text_height(path):
    """Median ink-line height in natural px of a clean text card image (dark text on a flat light/dark ground), else None.
    Row-projection of the ink mask; this is what Vision's line box height measures, with no OCR and no metadata."""
    if path in _IMG_CACHE:
        return _IMG_CACHE[path]
    res = None
    try:
        import numpy as np
        from PIL import Image
        im = Image.open(path).convert("L")
        if im.width > 1800:
            sc = 1800.0 / im.width; im = im.resize((1800, max(1, int(im.height * sc))))
        else:
            sc = 1.0
        a = np.asarray(im, dtype=np.int16)
        hist = np.bincount(a.ravel(), minlength=256)
        bg = int(np.argmax(hist))
        flat = hist[max(0, bg - 14):bg + 15].sum() / float(a.size)
        if flat >= 0.55:
            ink = np.abs(a - bg) > 70
            rows = ink.mean(axis=1)
            on = rows > 0.004
            segs, i, n = [], 0, len(on)
            while i < n:
                if on[i]:
                    j = i
                    while j + 1 < n and (on[j + 1] or (j + 3 < n and on[j + 2]) or (j + 4 < n and on[j + 3])):
                        j += 1
                    segs.append((i, j))
                    i = j + 1
                else:
                    i += 1
            hs = [(b - a_ + 1) / sc for a_, b in segs if (b - a_ + 1) / sc >= 9]
            if len(hs) >= 1:
                hs.sort()
                res = {"h": hs[len(hs) // 2], "n": len(hs), "min": hs[0], "max": hs[-1]}
    except Exception:
        res = None
    _IMG_CACHE[path] = res
    return res


# ------------------------------------------------------------------------------------------------- image cards as frame items
def card_items(raw_part, s, pkg_dir):
    """A source strip is an <img> whose pixels are text: the platform rules (visible rect, overlays) apply to it exactly as to a text
    box (S01, 6 Oct: the standfirst card entered from below the frame and sat under the caption bar; it is an image, so no text element
    existed). Returns pseudo text items for the images that are clean text cards, one per visible image window."""
    look = raw_part.get("look", "")
    out = []
    for im in s["imgs"]:
        win = im.get("cut") or im["box"]
        if im["op"] <= OPACITY_MIN or area(win) < 0.012 * FW * FH:
            continue
        fpath = os.path.join(pkg_dir, look, im["src"].split("?")[0])
        if not os.path.exists(fpath) or not image_text_height(fpath):
            continue
        out.append({"id": "img%s" % im["id"], "e": im["e"] + "[" + os.path.basename(im["src"]) + "]", "t": "(text card image)", "fpx": 99.0, "op": im["op"], "vis": 1.0, "cp": False,
                    "ink": [win], "cut": [win], "occ": None, "card": True})
    return out


def card_problems(probs, t):
    """A card image is mostly text but has padding: only a big share under an overlay counts (the gate's 5% is for tight text boxes)."""
    if not t.get("card"):
        return probs
    keep = []
    for sev, kind, detail in probs:
        if kind == "under_overlay":
            m = re.match(r"(\d+)%", detail)
            if m and int(m.group(1)) < 25:
                continue
        keep.append((sev, kind, detail))
    return keep


# ------------------------------------------------------------------------------------------------- the rules
def merge_runs(items, step):
    """items: list of (T, payload) for ONE (element, rule); consecutive samples (gap <= 1.6 x step) become one run."""
    items = sorted(items, key=lambda x: x[0])
    runs, cur = [], []
    for t, p in items:
        if cur and t - cur[-1][0] <= 1.6 * step + 1e-6:
            cur.append((t, p))
        else:
            if cur:
                runs.append(cur)
            cur = [(t, p)]
    if cur:
        runs.append(cur)
    return runs


def analyze(raw, sid, prof, step, kinds, parts, out_dir, allow_lint, pkg_dir, strict=False):
    """raw: runner JSON. kinds: {story T: grid|cut|seam}. Returns {"findings": [...], "stats": {...}}."""
    off = {p["out"]: p["off"] for p in parts}
    S = []   # flat samples; kinds is the {(part, local): (story T, kind)} lookup from make_plan
    for part, d in raw["parts"].items():
        for s in d["samples"]:
            T, kind = kinds.get((part, round(s["t"], 2))) or (round(off.get(part, 0.0) + s["t"], 3), "grid")
            S.append({"T": T, "part": part, "local": s["t"], "kind": kind, "s": s})
    S.sort(key=lambda x: x["T"])
    for x in S:
        x["fi"] = list(x["s"]["texts"]) + card_items(raw["parts"][x["part"]], x["s"], pkg_dir)
    grid = [x for x in S if x["kind"] == "grid"]
    findings = []

    def add(sev, rule, t0, t1, part, local, el, text, detail, extra=None):
        f = {"sev": sev, "rule": rule, "t0": round(t0, 2), "t1": round(t1, 2), "part": part, "local": round(local, 2), "el": el, "text": (text or "")[:80], "detail": detail}
        if extra:
            f.update(extra)
        findings.append(f)

    per_el = {}   # (part, id, rule) -> [(T, payload)]
    tex = [0]     # texture-sized text samples (not reported)

    # ---- rules 1, 2 (per element), collecting per-sample violations
    for x in S:
        s, part, T = x["s"], x["part"], x["T"]
        for t in x["fi"]:
            if not shown(t):
                continue
            key = (part, t["id"])
            if t["fpx"] < FLOOR_PX - FLOOR_TOL and alnum(t["t"]) >= 2 and x["kind"] == "grid":
                if t["fpx"] < TEXTURE_PX:
                    tex[0] += 1
                else:
                    per_el.setdefault(key + ("legibility",), []).append((T, (t, x["local"])))
            if True:
                boxes = t["cut"] if t["vis"] < 0.999 and t.get("cut") else t["ink"]
                worst = []
                for b in boxes:
                    for sev, kind, detail in card_problems(platforms.box_problems(prof, {"x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3]}), t):
                        worst.append((sev, kind, detail))
                if worst:
                    rank = {"FAIL": 2, "WARN": 1}
                    worst.sort(key=lambda w: -rank[w[0]])
                    per_el.setdefault(key + ("frame",), []).append((T, (t, x["local"], worst[0], x["kind"])))

    for (part, eid, rule), items in per_el.items():
        for run in merge_runs([(T, p) for T, p in items if rule != "frame" or p[3] == "grid"] if rule == "frame" else items, step):
            t0, t1 = run[0][0], run[-1][0]
            dur = (t1 - t0) + step
            t, local = run[0][1][0], run[0][1][1]
            if rule == "legibility":
                if dur + 1e-6 < MIN_RUN_S:
                    continue
                fp = min(p[0]["fpx"] for _, p in run)
                sev = "FAIL" if (not t.get("cv") and (strict or (is_reading(t["t"]) and fp < READ_FAIL_PX))) else "WARN"   # canvas labels are scene texture: WARN only
                add(sev, "legibility", t0, t1, part, local, t["e"], t["t"], "%.1f px < %d%s (opacity %.2f, on screen %.1f s)" % (fp, FLOOR_PX, " reading text" if is_reading(t["t"]) else " label", t["op"], dur), {"px": round(fp, 1)})
            else:
                sevs = [p[2][0] for _, p in run]
                sev = "FAIL" if "FAIL" in sevs else "WARN"
                worst = next(p[2] for _, p in run if p[2][0] == sev)
                if dur + 1e-6 < 0.3 and sev == "FAIL":
                    sev = "WARN"   # a pass through an edge or overlay shorter than 0.3 s is a transit (a pop, a slide), not a resting place; still shown
                add(sev, "frame", t0, t1, part, local, t["e"], t["t"], "%s: %s" % (worst[1], worst[2]))
    # the probes between grid samples (cut/seam instants) can expose a single-frame defect: report them as such
    for x in S:
        if x["kind"] == "grid":
            continue
        for t in x["fi"]:
            if not shown(t):
                continue
            boxes = t["cut"] if t["vis"] < 0.999 and t.get("cut") else t["ink"]
            probs = []
            for b in boxes:
                probs += card_problems(platforms.box_problems(prof, {"x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3]}), t)
            probs = [p for p in probs if p[0] == "FAIL"]
            if probs:
                # skip if a grid run already reported this element at (near) this time
                if any(f["rule"] == "frame" and f["part"] == x["part"] and f["el"] == t["e"] and f["text"] == t["t"][:80] and f["t0"] - 0.15 <= x["T"] <= f["t1"] + 0.15 for f in findings):
                    continue
                add("FAIL" if x["kind"] == "cut" else "WARN", "frame", x["T"], x["T"], x["part"], x["local"], t["e"], t["t"], "%s: %s (probe %s %.3f s)" % (probs[0][1], probs[0][2], x["kind"], x["T"]))

    # ---- rule 3: stacked text (per sample; runs merged over the grid, probes count alone)
    st = {}
    for x in S:
        vis = [t for t in x["s"]["texts"] if shown(t)]
        for i in range(len(vis)):
            for j in range(i + 1, len(vis)):
                a, b = vis[i], vis[j]
                if a["id"] == b["id"] or norm(a["t"]) == norm(b["t"]):
                    continue
                if bool(a.get("cv")) != bool(b.get("cv")):
                    continue   # a canvas world with DOM type laid over it is the layout, not a collision; canvas-vs-DOM stacking is a named blind spot
                if isinstance(a["id"], str) and isinstance(b["id"], str) and a["id"].split(":")[0] == b["id"].split(":")[0]:
                    continue   # two strings of ONE canvas: the scene paints them back to front itself (a pile of pages), the DOM cannot see what covers what
                if b["id"] in a.get("anc", ()) or a["id"] in b.get("anc", ()):
                    continue   # one sits inside the other (a button's label and its pressed state): a designed composite, not a collision
                if min(a["op"], b["op"]) < STACK_OPACITY:
                    continue   # a dissolve passing through 0.5-0.8 is a transition, not two solid texts on top of each other
                best = 0.0
                for ra in a["ink"]:
                    for rb in b["ink"]:
                        best = max(best, box_overlap_frac(ra, a.get("rot", 0.0), rb, b.get("rot", 0.0)))
                if best > OVERLAP_FRAC:
                    st.setdefault((x["part"], a["id"], b["id"]), []).append((x["T"], (a, b, best, x["local"], x["kind"])))
    for (part, ia, ib), items in st.items():
        gitems = [(T, p) for T, p in items if p[4] == "grid"]
        pitems = [(T, p) for T, p in items if p[4] != "grid"]
        for run in merge_runs(gitems, step):
            a, b, best, local = run[0][1][0], run[0][1][1], max(p[2] for _, p in run), run[0][1][3]
            dur = (run[-1][0] - run[0][0]) + step
            add("FAIL" if (best > 0.3 or dur >= 0.3) else "WARN", "stacked", run[0][0], run[-1][0], part, local, a["e"] + " x " + b["e"], "'%s' over '%s'" % (a["t"][:30], b["t"][:30]),
                "overlap %d%% of the smaller box for %.1f s" % (round(best * 100), dur))
        for T, p in pitems:
            if any(f["rule"] == "stacked" and f["part"] == part and f["t0"] - 0.15 <= T <= f["t1"] + 0.15 and f["text"] == ("'%s' over '%s'" % (p[0]["t"][:30], p[1]["t"][:30]))[:80] for f in findings):
                continue
            add("FAIL" if p[4] == "cut" or p[2] > 0.3 else "WARN", "stacked", T, T, part, p[3], p[0]["e"] + " x " + p[1]["e"], "'%s' over '%s'" % (p[0]["t"][:30], p[1]["t"][:30]),
                "overlap %d%% of the smaller box at the %s frame %.3f s" % (round(p[2] * 100), p[4], T))

    # ---- rule 4: empty on the cut
    for x in S:
        if x["kind"] != "cut":
            continue
        s = x["s"]
        vt = [t for t in s["texts"] if shown(t)]
        content = []
        for p in s["paints"]:
            if p["kind"] in ("bgcolor", "gradient", "border") and area(p["box"]) >= 0.85 * FW * FH:
                continue   # a flat ground is the background
            if p["eo"] >= 0.3:
                content.append(p["box"])
        for im in s["imgs"]:
            if im["op"] >= 0.3 and im["vis"] >= 0.3:
                content.append(im["box"])
        big = max([inter_area(b, (0, 0, FW, FH)) / (FW * FH) for b in content] or [0.0])
        faint = [t for t in s["texts"] if 0.05 < t["op"] <= OPACITY_MIN and t["vis"] >= 0.5 and onframe_frac(t["ink"]) >= ONFRAME_MIN]
        if not vt and big < EMPTY_COVER:
            add("WARN" if faint else "FAIL", "empty-on-cut", x["T"], x["T"], x["part"], x["local"], "(frame)", "", "cut frame %.3f s: %s and the largest non-background element covers %d%% of the frame" % (x["T"], "the text is still fading in (opacity <= 0.5)" if faint else "no visible text", round(big * 100)))
        else:
            # sparse: some text, but text boxes plus every painted element together fill under SPARSE_COVER of the frame (a lone label on a bare panel)
            cells = set()
            for b in content + [r for t in vt for r in t["ink"]]:
                c = (max(0, int(b[0] // 40)), max(0, int(b[1] // 40)), min(26, int(b[2] // 40)), min(47, int(b[3] // 40)))
                for gx in range(c[0], c[2] + 1):
                    for gy in range(c[1], c[3] + 1):
                        cells.add((gx, gy))
            cover = len(cells) / (27.0 * 48.0)
            if big < EMPTY_COVER and cover < SPARSE_COVER:
                add("WARN", "empty-on-cut", x["T"], x["T"], x["part"], x["local"], "(frame)", "", "cut frame %.3f s is sparse: text and objects together cover about %d%% of the frame" % (x["T"], round(cover * 100)))

    # ---- rule 5: text lint on the real strings
    import gate as _gate
    seen = {}
    for x in S:
        vt = [t for t in x["s"]["texts"] if shown(t, 0.3)]
        for t in vt:
            seen.setdefault(t["t"], (x["T"], x["part"], x["local"], t["e"]))
        for ln in lines_of(vt):
            seen.setdefault(ln, (x["T"], x["part"], x["local"], "(line)"))
    reported = set()
    for txt, (T, part, local, e) in sorted(seen.items(), key=lambda kv: kv[1][0]):
        hits = _gate.lint_text(txt)
        if not hits:
            continue
        n = norm(txt)
        if any(a and (n == a or (len(n) >= 4 and n in a) or (len(a) >= 4 and a in n)) for a in allow_lint):
            continue
        key = tuple(sorted(h["hit"] for h in hits))
        if (key, n) in reported:
            continue
        reported.add((key, n))
        add("FAIL", "text-lint", T, T, part, local, e, txt, "; ".join(h["hit"] for h in hits)[:70])
    # a line already reported as a single element string is not reported again as a rebuilt line
    uniq, seen_k = [], set()
    for f in findings:
        if f["rule"] == "text-lint":
            k = (f["detail"], norm(f["text"]))
            if any(f2["rule"] == "text-lint" and f2 is not f and f2["detail"] == f["detail"] and norm(f["text"]) != norm(f2["text"]) and norm(f2["text"]) in norm(f["text"]) for f2 in findings):
                continue
        uniq.append(f)
    findings = uniq

    # ---- images that are text cards (a captured source strip): OCR-equivalent line height = ink-row height x displayed scale x 1.09
    # (1.09 is the measured ratio of Vision's line box to the ink rows on S102's Express strips: 36 px by OCR where the rows say 33).
    img_runs = {}
    for x in S:
        if x["kind"] != "grid":
            continue
        look = raw["parts"][x["part"]].get("look", "")
        for im in x["s"]["imgs"]:
            win = im.get("cut") or im["box"]
            if im["op"] <= OPACITY_MIN or im["k"] <= 0 or area(win) < 0.012 * FW * FH or onframe_frac([win]) < 0.5:
                continue
            fpath = os.path.join(pkg_dir, look, im["src"].split("?")[0])
            if not os.path.exists(fpath):
                continue
            ih = image_text_height(fpath)
            if not ih:
                continue
            px = ih["h"] * im["k"] * IMG_OCR_RATIO
            if px < FLOOR_PX - FLOOR_TOL and px >= 0.5 * TEXTURE_PX:
                img_runs.setdefault((x["part"], im["id"]), []).append((x["T"], (im, px, ih, x["local"])))
    for (part, iid), items in img_runs.items():
        for run in merge_runs(items, step):
            dur = (run[-1][0] - run[0][0]) + step
            if dur + 1e-6 < MIN_RUN_S:
                continue
            im, _, ih, local = run[0][1]
            px = min(p[1] for _, p in run)
            add("FAIL" if (strict or px < IMG_FAIL_PX) else "WARN", "legibility", run[0][0], run[-1][0], part, local, im["e"] + "[" + os.path.basename(im["src"]) + "]", "(text inside image)",
                "%.1f px < %d: ink line %.0f px in the file x scale %.2f x %.2f, on screen %.1f s" % (px, FLOOR_PX, ih["h"], im["k"], IMG_OCR_RATIO, dur), {"px": round(px, 1), "image": True})

    # one defect on many identical elements (a dial's twelve "24" ticks) is one line with a count
    merged, idx = [], {}
    for f in findings:
        k = (f["rule"], f["sev"], f["part"], f["t0"], f["t1"], norm(f["text"]), f["detail"].split(" (")[0] if f["rule"] == "legibility" else f["detail"])
        if k in idx:
            merged[idx[k]]["n"] = merged[idx[k]].get("n", 1) + 1
        else:
            idx[k] = len(merged); merged.append(f)
    findings = merged
    # one line of per-letter or per-word elements that sits in the same place is ONE finding
    gk, out3 = {}, []
    for f in findings:
        if f["rule"] == "frame":
            k = (f["sev"], f["part"], round(f["t0"], 1), round(f["t1"], 1), f["detail"].split(":")[0], re.sub(r"[0-9]+", "#", f["detail"].split(":", 1)[-1]))
            if k in gk:
                h = gk[k]; h["n"] = h.get("n", 1) + 1
                if len(h["text"]) < 40 and f["text"] not in h["text"]:
                    h["text"] += " " + f["text"]
                continue
            gk[k] = f
        out3.append(f)
    findings = out3
    # a label that sits under the floor for the whole short is ONE warning with its span, not thirty
    g, out2 = {}, []
    for f in findings:
        if f["rule"] == "legibility" and f["sev"] == "WARN" and not f.get("image"):
            k = (norm(f["text"]), round(f.get("px", 0)))
            if k in g:
                h = g[k]; h["t0"] = min(h["t0"], f["t0"]); h["t1"] = max(h["t1"], f["t1"]); h["runs"] = h.get("runs", 1) + 1; h["n"] = max(h.get("n", 1), f.get("n", 1))
                continue
            g[k] = f
        out2.append(f)
    findings = out2

    findings.sort(key=lambda f: (f["t0"], f["rule"]))
    nf = sum(1 for f in findings if f["sev"] == "FAIL")
    nw = sum(1 for f in findings if f["sev"] == "WARN")
    st = {"samples": len(S), "grid": len(grid), "cut_frames": sum(1 for x in S if x["kind"] == "cut"), "FAIL": nf, "WARN": nw, "texture_samples": tex[0]}
    return {"findings": findings, "stats": st}


# ------------------------------------------------------------------------------------------------- publish the cloud half
CLOUD_FILES = (("kit/cloud/workflows/agmm-short-domlint.yml", ".github/workflows/agmm-short-domlint.yml"),
               ("kit/tools/dom_lint_runner.mjs", ".github/scripts/dom_lint_runner.mjs"))


def publish_cloud():
    """Put the workflow and the runner into the public repo (idempotent; reads the file's sha first). Only these two paths."""
    import base64
    sys.path.insert(0, TOOLS)
    import snap  # noqa: E402
    for local, remote in CLOUD_FILES:
        data = open(os.path.join(V2, local), "rb").read()
        for attempt in range(4):   # a transient API error must not look like "file does not exist" (PUT then needs a sha and fails)
            r = snap._gh(["api", "repos/%s/contents/%s" % (ACTIONS_REPO, remote)], check=False)
            if r.returncode == 0 or "404" in (r.stderr or ""):
                break
            time.sleep(5 + attempt * 5)
        sha = json.loads(r.stdout).get("sha") if r.returncode == 0 else None
        if sha and base64.b64decode(json.loads(r.stdout)["content"]) == data:
            print("unchanged: " + remote)
            continue
        args = ["api", "-X", "PUT", "repos/%s/contents/%s" % (ACTIONS_REPO, remote), "-f", "message=dom-lint: %s (kit/tools/dom_lint.py)" % os.path.basename(remote),
                "-f", "content=" + base64.b64encode(data).decode(), "-f", "branch=main"]
        if sha:
            args += ["-f", "sha=" + sha]
        snap._gh(args)
        print("published: " + remote)


# ------------------------------------------------------------------------------------------------- main
def main():
    if "--publish" in sys.argv:
        publish_cloud()
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--every", type=float, default=0.1, help="sampling step in seconds (default 0.1: the 0.4 s persistence rule needs it; 0.5 is allowed for a quick look)")
    ap.add_argument("--platform")
    ap.add_argument("--backend", choices=["actions", "local"], default=os.environ.get("DOM_LINT", "actions"))
    ap.add_argument("--raw", help="re-judge a saved raw JSON (no browser)")
    ap.add_argument("--json", help="write the findings JSON here (default out/<ID>/domlint/result.json)")
    ap.add_argument("--build-dir", help="a build dir holding parts.json and pkg/ (default out/<ID>/build)")
    ap.add_argument("--release", help="lint an ARCHIVED package: a snap-<id>-<sha16> release of the public repo (e.g. the version a reviewer returned)")
    ap.add_argument("--out-dir", help="where raw.json / result.json go (default out/<ID>/domlint, or out/<ID>/domlint-<release>)")
    ap.add_argument("--keep-release", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--css", help="mutation tests only (local backend): CSS injected into every page, e.g. '*{opacity:0!important}' must make every cut frame empty")
    ap.add_argument("--strict-floor", action="store_true", help="the card's literal rule: ANY text under 42 px FAILs (default: reading text under 38 px and image text under 37 px FAIL, the rest WARN)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    sid = a.id
    p = platforms.profile(a.platform) if a.platform else platforms.for_short(sid)
    if p is None:
        p = platforms.profile("instagram")
        print("note: %s has no routed platform; checking against instagram_reels" % sid)
    if a.css and a.backend != "local":
        tool_error("--css is a local mutation-test switch: use --backend local")
    rel_tmp = None
    if a.release:
        out = os.path.join(KIT, "out", sid)
        rel_tmp = tempfile.mkdtemp(prefix="agmm-domlint-rel-")
        pkg_root, parts, beats, rel_sha = load_release(a.release, rel_tmp)
        bd = None
    else:
        out, bd, parts, beats = load_build(sid, a.build_dir)
        pkg_root = os.path.join(bd, "pkg")
    kinds = sample_times(parts, beats, a.every)
    while len(kinds) > 780 and not a.raw:   # the snap plan format allows 800 frames in all; a long short coarsens the step instead of failing
        a.every = round(a.every * 1.25, 3)
        kinds = sample_times(parts, beats, a.every)
        log("too many samples for one dispatch; step raised to %.3f s" % a.every)
    plan, kinds = make_plan(parts, kinds)
    prof_json = {"visible": {k: p["visible"][k] for k in ("x0", "y0", "x1", "y1")}, "overlays": [{k: o[k] for k in ("x0", "y0", "x1", "y1")} for o in p["overlays"]]}
    ddir = a.out_dir or os.path.join(out, "domlint-" + a.release if a.release else "domlint")
    os.makedirs(ddir, exist_ok=True)
    raw_path = a.raw or os.path.join(ddir, "raw.json")
    t_start = time.time()
    if not a.raw:
        try:
            if a.backend == "local":
                run_local(sid, pkg_root, plan, prof_json, raw_path, a.css)
            else:
                run_actions(sid, parts, plan, prof_json, raw_path, (a.release, rel_sha) if a.release else None)
        except SystemExit:
            raise
        except Exception as e:
            tool_error("%s backend failed: %s" % (a.backend, str(e)[-700:]))
    try:
        raw = json.load(open(raw_path))
    except (OSError, ValueError) as e:
        tool_error("cannot read raw result %s: %s" % (raw_path, e))
    for part, d in raw["parts"].items():
        if d.get("errors"):
            print("note: %s page errors: %s" % (part, "; ".join(d["errors"])[:300]))
    exc = os.path.join(out, "lint-exceptions.json")
    allow = []
    if os.path.exists(exc):
        try:
            allow = [norm(x.get("text")) for x in json.load(open(exc)).get("lint", []) if x.get("text")]
        except ValueError:
            pass
    res = analyze(raw, sid, p, a.every if not a.raw else _infer_step(raw), kinds, parts, ddir, allow, os.path.join(pkg_root, ""), a.strict_floor)
    if rel_tmp and not a.keep_release:
        shutil.rmtree(rel_tmp, ignore_errors=True)
    res["id"], res["platform"], res["step"] = sid, p["key"], a.every
    jp = a.json or os.path.join(ddir, "result.json")
    json.dump(res, open(jp, "w"), indent=1)
    for f in res["findings"]:
        span = ("%.2fs" % f["t0"]) if f["t1"] == f["t0"] else ("%.2f-%.2fs" % (f["t0"], f["t1"]))
        who = ("" if f["el"] == "(frame)" else f["el"]) + (" x%d" % f["n"] if f.get("n", 1) > 1 else "") + (" over %d runs" % f["runs"] if f.get("runs", 1) > 1 else "")
        print("%s %-12s %-13s %s %.2f | %s | %s %s" % (f["sev"], span, f["rule"], f["part"].split("-")[-1], f["local"], f["detail"], who, ("'" + f["text"] + "'") if f["text"] else ""))
    s = res["stats"]
    print("dom_lint %s -> %s: %d samples (%d cut frames), %d FAIL, %d WARN (raw: %s)" % (sid, p["key"], s["samples"], s["cut_frames"], s["FAIL"], s["WARN"], os.path.relpath(raw_path, KIT)))
    sys.exit(1 if s["FAIL"] else 0)


def _infer_step(raw):
    ts = []
    for d in raw["parts"].values():
        ts = [s["t"] for s in d["samples"]]
        break
    gaps = sorted(b - a for a, b in zip(ts, ts[1:]) if b - a > 0.03)
    return gaps[len(gaps) // 2] if gaps else 0.1


if __name__ == "__main__":
    main()
