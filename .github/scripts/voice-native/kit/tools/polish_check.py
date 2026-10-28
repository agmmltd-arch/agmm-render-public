#!/usr/bin/env python3
"""polish_check.py <ID> [--build-dir DIR] [--backend actions|local] [--raw raw.json[.gz]] [--json out.json] [--from S --to S] [--strict]
(root card "polish-shorts", 12 Oct 2026; Sam, 12 Oct: "make sure all motion graphics and all the tiny detail visuals are perfect --
each video has been about 85% clean; we can make them much better")

A frame-by-frame lint of a short's BUILT package for the micro-defects that gates and contact sheets miss. Scenes are DOM and pure
functions of time, so the part's own GSAP timeline is seeked at EVERY output frame (30 fps) in headless Chrome and, per frame, every
visible text element and painted object is recorded (box, effective opacity, cumulative scale/rotation, visible share after clips;
tools/polish_runner.mjs in the public repo, workflow agmm-short-polish.yml).  This file turns those series into findings, per element:

  pop        an element appears (opacity/clip 0 -> >0.9) in ONE frame, then does not move at all for the next 6 frames (no entrance), while the rest of the
             frame keeps going; or one disappears in ONE frame mid-beat. Not a pop: arriving with a whole-scene cut (most large elements replaced). On a cut
             that keeps part of the picture (a board, a HUD tag) a NEW element landing hard is a WARN, mid-beat and big (>= 40000 px^2 or 60 px type) a FAIL.
             WARN also: enters oversized at full opacity and snaps to size in <= 3 frames. INFO (counted, never refuses): hard-on with a 4-5 frame settle (the kit's slam).
  cutjump    the SAME text on both sides of a beat cut that keeps part of the picture moves/rescales: FAIL at 12 px or 2% scale, WARN under (a camera reset at the seam)
  flicker    visible for 1-3 frames only (ghost), or hidden 1-2 frames and back (blink), or opacity dip; boxes and text of 24+ px, not at a cut, not svg marks, not rolling digits
  jitter     frame-to-frame position noise (alternating accelerations > 0.5 px, amplitude 0.5-4 px) sustained >= 12 frames on an element that otherwise holds (x/y at 1 px+ is a FAIL,
             size noise a WARN). The kit's 10 fps 'boil' (steps on one phase of f % 3) and 6-frame landing shake are exempt.
  snap       position/scale of a held element jumps (> 60 px or > 12%) in one frame mid-hold: FAIL; a text whose width/height jumps (a changed string) is a WARN; a one-frame
             size glitch (+-3% for ONE frame and back) is a WARN; a jump that repeats 3+ times (a looping background wrapping) is ignored
  easing     an entrance move (>= 40 px) rest -> move -> rest that is linear (constant speed, CV < 0.12; FAIL on a 15000 px^2 / 60 px object, else WARN) or covers 80+ px in <= 3 frames (FAIL)
  overlap    two text elements overlapping > 10% of the smaller box for 1-8 frames then separating (FAIL over 30%); text partly covered (6-60%) for 8+ frames by an opaque
             object that paints ABOVE it (z-index chain, then document order); text lines touching/overprinting (6-30%) for 12+ frames
  edge       an element crosses the frame edge by >= 3 px for <= 12 frames with a turnaround, inside before and after (overshoot clipped)
  distort    an <img> drawn at another aspect than its file (> 4%; FAIL over 12%): the squashed quote cards
  colour     a box/chip changes colour by a step of 90+ in ONE frame mid-hold (WARN); the same on text is INFO (the kit's word highlight on the beat)
  cropcut    the clip window of a source card slices through ink at an edge (pixel check on the package's own image)
  widow      a wrapped text block of >= 5 words whose last line is a single word
  drift      stacked siblings (same width / same type size) whose left edges differ by 1-6 px (or centres, centred text)
  style      same-size sibling boxes with different corner radius / border / shadow;  typescale: same-role texts 3-15% apart in size
  zflip      a visible element's z-index changes
  sfx        a sound cue (audio/cues.json) whose nearest visual event (appear/land/cut) is more than 2 frames away while one sits within +-0.4 s (WARN, advisory)

Exit code 1 if any FAIL, 2 on a tool error, else 0.  Nothing here renders a video or opens a local Chrome: the browser half runs on GitHub
Actions (the public repo's agmm-short-polish.yml, same package route, secret scan, hash check and polling rules as snap.py / dom_lint.py).
--backend local runs the same runner through tools/heavy.py (3 machine-wide slots), for one-off debugging only.
--raw FILE re-judges a saved raw (rule tuning, calibration): no browser, no network.

Thresholds are calibrated on the audited defects in monday-recovery/polish-shorts.md (precision/recall are in that report); every rule has a
--only RULE switch and a per-rule override file (--tune tune.json) so a threshold can be moved without touching the code."""
import argparse, glob, gzip, hashlib, json, math, os, random, re, shutil, subprocess, sys, tempfile, time

TOOLS = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(TOOLS)
V2 = os.path.dirname(KIT)
FPS = 30.0
FW, FH = 1080.0, 1920.0
ACTIONS_REPO = "agmmltd-arch/agmm-render-public"
ACTIONS_WF = "agmm-short-polish.yml"
sys.path.insert(0, os.path.join(KIT, "platforms"))
UNIVERSAL_LEVEL = None   # set by main(): "FAIL" for a short claimed at or after universal live_from, else "WARN" (--universal overrides)
LEDGER = os.path.join(KIT, "registry", "actions-polish-usage.jsonl")


def log(msg):
    print("polish_check: " + msg, file=sys.stderr, flush=True)


def tool_error(msg):
    print("TOOL ERROR: " + msg, file=sys.stderr)
    raise SystemExit(2)


# ------------------------------------------------------------------------------------------------- build / plan
def load_build(sid, build_dir=None):
    out = os.path.join(KIT, "out", sid)
    bd = build_dir or os.path.join(out, "build")
    try:
        parts = json.load(open(os.path.join(bd, "parts.json")))["parts"]
    except (OSError, ValueError, KeyError) as e:
        tool_error("no readable %s/parts.json (build the package first: produce.py %s --only build): %s" % (bd, sid, e))
    beats = []
    for cand in (os.path.join(out, "resolved.json"), os.path.join(os.path.dirname(bd), "resolved.json")):
        try:
            r = json.load(open(cand))
            bl = r.get("beats", r) if isinstance(r, dict) else r
            beats = [{"id": b.get("id"), "from": float(b["from"]), "to": float(b["to"])} for b in bl]
            break
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if not beats:   # fall back to the beats inside the package itself
        import tarfile
        try:
            with tarfile.open(os.path.join(bd, "source.tar.gz")) as tf:
                name = sorted(m.name for m in tf.getmembers() if m.name.endswith("/spec.js"))[0]
                sp = tf.extractfile(name).read().decode()
            d = json.loads(re.search(r"=\s*(\{.*\})\s*;?\s*$", sp, re.S).group(1))
            beats = [{"id": b.get("id"), "from": float(b["from"]), "to": float(b["to"])} for b in d["beats"]]
        except Exception:
            beats = []
    cues = []
    for cand in (os.path.join(os.path.dirname(bd), "audio", "cues.json"), os.path.join(out, "audio", "cues.json")):
        try:
            cj = json.load(open(cand))
            cues = cj.get("cues", cj) if isinstance(cj, dict) else cj
            break
        except (OSError, ValueError):
            continue
    return out, bd, parts, beats, cues


# ------------------------------------------------------------------------------------------------- backends
def local_runner_cmd():
    node = os.path.expanduser("~/.local/node/bin/node")
    if not os.path.exists(node):
        node = shutil.which("node") or tool_error("no node on this Mac (~/.local/node/bin/node)")
    ppt = os.environ.get("POLISH_PUPPETEER") or os.environ.get("DOM_LINT_PUPPETEER")
    if not ppt:
        cands = sorted(glob.glob(os.path.expanduser("~/.npm/_npx/*/node_modules/puppeteer-core")), key=os.path.getmtime)
        ppt = cands[-1] if cands else tool_error("no puppeteer-core in ~/.npm/_npx")
    chrome = os.environ.get("POLISH_CHROME") or os.environ.get("DOM_LINT_CHROME") or next(iter(sorted(glob.glob(os.path.expanduser(
        "~/.cache/hyperframes/chrome/chrome-headless-shell/*/*/chrome-headless-shell")))), None)
    if not chrome:
        tool_error("no headless chrome (set POLISH_CHROME)")
    return node, ppt, chrome


def run_local(root, parts, raw_path, t_from, t_to):
    node, ppt, chrome = local_runner_cmd()
    runner = os.environ.get("POLISH_RUNNER") or os.path.join(TOOLS, "polish_runner.mjs")
    if not os.path.exists(runner):
        tool_error("no local copy of the runner (the canonical one is .github/scripts/polish_runner.mjs in %s); set POLISH_RUNNER" % ACTIONS_REPO)
    tmp = tempfile.mkdtemp(prefix="agmm-polish-")
    try:
        pj = os.path.join(tmp, "parts.json")
        json.dump(parts, open(pj, "w"))
        cmd = [sys.executable, os.path.join(TOOLS, "heavy.py"), "--", node, runner, "--root", root, "--parts", pj, "--out", raw_path,
               "--chrome", chrome, "--puppeteer", ppt, "--from", str(t_from), "--to", str(t_to)]
        log("local runner via heavy.py")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3300)
        if r.returncode:
            tool_error("local runner rc %d: %s" % (r.returncode, (r.stdout + r.stderr)[-600:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_actions(sid, bd, parts, raw_path, t_from, t_to, release=None):
    sys.path.insert(0, TOOLS)
    import snap  # noqa: E402  (its package tar, secret scan, content-hashed release and gh wrapper: one mechanism, not two)
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix="agmm-polish-actions-")
    run_id = None
    try:
        if release:
            tag, how, sha = release, "given", ""
        else:
            archived = os.path.join(bd, "source.tar.gz")
            if os.path.exists(os.path.join(bd, "pkg")) and os.path.exists(os.path.join(KIT, "out", sid, "BUILD.json")) and bd == os.path.join(KIT, "out", sid, "build"):
                tarball, sha, size = snap._package_tar(sid, [p["look"] for p in parts], tmp)   # the current build, exactly as snap.py ships it
            elif os.path.exists(archived):   # an archived/restored package (the posted bytes' own source.tar.gz)
                tarball = archived
                h = hashlib.sha256()
                with open(tarball, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                sha, size = h.hexdigest(), os.path.getsize(tarball)
            else:
                raise RuntimeError("no package: neither %s/pkg (with out/%s/BUILD.json) nor %s" % (bd, sid, archived))
            snap._secret_scan(tarball)
            tag, how = snap._snap_release(sid, tarball, sha, size)
        if not sha:
            sha = json.loads(snap._gh(["api", "repos/%s/releases/tags/%s" % (ACTIONS_REPO, tag)]).stdout)["assets"][0]["digest"].split(":", 1)[1]
        label = "%s-pol-%s-%d-%d" % (sid, sha[:8], int(time.time()), os.getpid())
        pj = json.dumps([{"look": p["look"], "part": p["out"], "off": p["off"], "dur": p["dur"]} for p in parts], separators=(",", ":"))
        r = snap._gh(["workflow", "run", ACTIONS_WF, "-R", ACTIONS_REPO, "--ref", "main", "-f", "release=" + tag, "-f", "source_sha256=" + sha,
                      "-f", "tag=" + label, "-f", "parts=" + pj, "-f", "from_s=%s" % t_from, "-f", "to_s=%s" % t_to])
        m = re.search(r"/actions/runs/(\d+)", (r.stdout or "") + (r.stderr or ""))
        run_id = m.group(1) if m else None
        t_end = time.time() + float(os.environ.get("AGMM_POLISH_WAIT", "2400"))
        title = "AGMM short polish " + label
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
        log("actions run %s (package %s %s, %.0f s to dispatch)" % (run_id, tag, how, time.time() - t0))
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
            time.sleep(15 + random.random() * 8)   # GitHub's secondary rate limit: never faster than ~15 s with jitter
        if status != "completed":
            raise RuntimeError("workflow run %s did not finish within the wait (status %r)" % (run_id, status))
        if conclusion != "success":
            tail = (snap._gh(["run", "view", run_id, "-R", ACTIONS_REPO, "--log-failed"], check=False, timeout=120).stdout or "")[-900:]
            raise RuntimeError("workflow run %s ended %s: %s" % (run_id, conclusion, tail))
        name = label + "-POLISH"
        last = ""
        for _ in range(6):
            d = snap._gh(["run", "download", run_id, "-R", ACTIONS_REPO, "-n", name, "-D", os.path.join(tmp, "dl")], check=False, timeout=900)
            if d.returncode == 0:
                break
            last = (d.stderr or d.stdout)[-300:]
            time.sleep(3)
        else:
            raise RuntimeError("artifact %s did not download: %s" % (name, last))
        src = os.path.join(tmp, "dl", "raw.json.gz")
        if not os.path.exists(src):
            raise RuntimeError("artifact has no raw.json.gz: %s" % os.listdir(os.path.join(tmp, "dl")))
        os.makedirs(os.path.dirname(raw_path), exist_ok=True)
        with gzip.open(src, "rb") as fi, open(raw_path, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        log("actions done in %.0f s (run %s)" % (time.time() - t0, run_id))
        try:
            with open(LEDGER, "a") as fh:
                fh.write(json.dumps({"id": sid, "kind": "polish-actions", "run": run_id, "release": how, "wall_s": round(time.time() - t0),
                                     "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        except OSError:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------------------------------------- tracks
class Track(object):
    """One element's life: arrays over absolute story frames g (30 fps), one entry per frame it was visible (opacity > 0.02)."""
    __slots__ = ("part", "key", "kind", "label", "text", "g", "x0", "y0", "x1", "y1", "o", "s", "r", "v", "z", "col", "cbx", "meta", "pfirst", "plast",
                 "_pn", "idx")

    def __init__(self, part, key, m, g, D, Z, pfirst, plast, col=None, cbx=None):
        import numpy as np
        self.part, self.key, self.meta = part, key, m
        self.kind = m.get("k", "box")
        self.label = m.get("e", "")
        self.text = m.get("t", "")
        self.g = np.asarray(g, dtype=np.int64)
        D = np.asarray(D, dtype=float)
        self.x0, self.y0, self.x1, self.y1, self.o, self.s, self.r, self.v = [D[:, i] for i in range(8)]
        self.z = Z
        self.col = col or []
        self.cbx = cbx or []
        self.pfirst, self.plast = pfirst, plast   # first / last story frame this track's PART page covers
        self._pn = None
        self.idx = {int(f): i for i, f in enumerate(self.g)}

    def has(self, f):
        return f in self.idx

    def i(self, f):
        return self.idx.get(f)

    @property
    def area(self):
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2.0

    @property
    def p(self):
        """presence 0..1: effective opacity x visible share, normalised by this element's own peak (a 30% tint reaching its 30% is 'fully on')"""
        import numpy as np
        if self._pn is None:
            raw = np.clip(self.o, 0, 1) * np.clip(self.v, 0, 1)
            mx = float(raw.max()) if len(raw) else 1.0
            self._pn = raw / (mx if mx > 0.05 else 1.0)
        return self._pn

    def runs(self):
        """[(a, b)] index ranges (inclusive) of consecutive frames"""
        import numpy as np
        if not len(self.g):
            return []
        br = np.nonzero(np.diff(self.g) != 1)[0]
        starts = [0] + (br + 1).tolist()
        ends = br.tolist() + [len(self.g) - 1]
        return list(zip(starts, ends))

    def name(self):
        t = (self.text or "").strip()
        return ("'%s'" % t[:28] if t else self.label) + (" [%s]" % self.part if False else "")


def load_tracks(raw):
    tracks = []
    for pn, d in raw["parts"].items():
        fr = d["frames"]
        if not fr:
            continue
        for k, e in d["els"].items():
            if not e["f"]:
                continue
            g = [fr[i] for i in e["f"]]
            Z = [row[8] if len(row) > 8 else "" for row in e["d"]]
            C = [row[9] if len(row) > 9 else "" for row in e["d"]]
            CB = [row[10] if len(row) > 10 else None for row in e["d"]] if e["m"].get("k") == "img" else []
            tracks.append(Track(pn, k, e["m"], g, [row[:8] for row in e["d"]], Z, fr[0], fr[-1], C, CB))
    return tracks


# ------------------------------------------------------------------------------------------------- tuning
TUNE = {
    "pop_fail_area": 40000.0,        # px^2: a hard-on element at least this big (about 2% of the frame) FAILs, smaller is WARN
    "pop_min_area": 3000.0,          # smaller objects are texture
    "pop_hard": 0.85,                # presence in the first frame at or above this = appeared in one frame
    "pop_static_mv": 2.5,            # px per frame over the next 6 frames at or under this = no entrance (ambient float is ~1 px/frame)
    "pop_static_ds": 0.006,
    "pop_static_do": 0.03,
    "flicker_max_frames": 3,
    "jitter_amp_min": 0.5, "jitter_amp_max": 4.0, "jitter_frames": 12, "jitter_alt": 7,
    "snap_px": 60.0, "snap_scale": 0.12, "snap_still": 4.0,
    "ease_min_move": 40.0, "ease_cv": 0.12, "ease_fast_frames": 3,
    "overlap_frac": 0.10, "overlap_max_frames": 8, "touch_gap": 2.0,
    "edge_px": 3.0, "edge_max_frames": 12,
    "widow_min_words": 5,
    "drift_min": 1.0, "drift_max": 6.0,
    "sfx_tol_frames": 2, "sfx_window_frames": 12,
    "text_min_px": 42.0,
}
RULES = ("universal", "pop", "cutjump", "flicker", "jitter", "snap", "easing", "overlap", "edge", "widow", "drift", "zflip", "sfx", "distort", "colour", "cropcut", "style", "typescale")


class Finding(object):
    def __init__(self, rule, sev, f0, f1, msg, track=None, part="", extra=None):
        self.rule, self.sev, self.f0, self.f1, self.msg, self.part, self.extra = rule, sev, int(f0), int(f1), msg, part, extra or {}
        self.track = track

    def line(self):
        return "%s %6.2f-%6.2fs %-8s %s | %s%s" % (self.sev, self.f0 / FPS, (self.f1 + 1) / FPS, self.rule, self.msg, self.part,
                                                  (" " + self.where()) if self.track is not None else "")

    def where(self):
        t = self.track
        return "| %s %s" % (t.kind, ("'%s'" % t.text[:30]) if t.text else t.label)

    def as_json(self):
        d = {"rule": self.rule, "sev": self.sev, "f0": self.f0, "f1": self.f1, "t0": round(self.f0 / FPS, 3), "t1": round((self.f1 + 1) / FPS, 3),
             "msg": self.msg, "part": self.part}
        if self.track is not None:
            d["kind"], d["text"], d["label"] = self.track.kind, self.track.text, self.track.label
            i = self.track.i(self.f0)
            for dd in (1, -1, 2, -2, 3, -3):
                if i is None:
                    i = self.track.i(self.f0 + dd)
            if i is not None:
                d["box"] = [round(float(self.track.x0[i])), round(float(self.track.y0[i])), round(float(self.track.x1[i])), round(float(self.track.y1[i]))]
        d.update(self.extra)
        return d


# ------------------------------------------------------------------------------------------------- scene model
def scene_cut_frames(tracks):
    """Frames where (nearly) every large element is replaced = a hard scene cut. Part-page first frames are not cuts (each part is its own page)."""
    import numpy as np
    pres = {}
    for ti, t in enumerate(tracks):
        if float(np.median(t.area)) < 2500:
            continue
        pm = t.p
        for f, i in t.idx.items():
            if pm[i] > 0.1:
                pres.setdefault(f, set()).add(ti)
    pfirst = set(t.pfirst for t in tracks)
    cuts = {}
    for f in sorted(pres):
        if f in pfirst:
            continue
        a, b = pres.get(f - 1, set()), pres[f]
        if not a:
            continue
        cont, chg = len(a & b), len(a ^ b)
        if chg >= 6 and chg >= 4 * cont:
            cuts[f] = {"cont": cont, "chg": chg}
    return cuts


def carried_over(tracks, fc):
    """Tracks present at the cut frame fc that are visually the SAME thing as one present at fc-1 (same text, or same label and kind; centre within
    40 px and size within 12%). Returns {id(track at fc): (track before, i_before, j_after)}."""
    before = []
    for t in tracks:
        i = t.i(fc - 1)
        if i is not None and t.p[i] > 0.3:
            before.append((t, i))
    carried = {}
    for t in tracks:
        j = t.i(fc)
        if j is None or t.p[j] <= 0.3:
            continue
        wj, hj = t.x1[j] - t.x0[j], t.y1[j] - t.y0[j]
        best = None
        for u, i in before:
            if u is t:
                carried[id(t)] = (u, i, j); best = None; break
            if u.kind != t.kind:
                continue
            if t.kind == "text" and u.text != t.text:
                continue
            if t.kind != "text" and u.label != t.label:
                continue
            wi, hi = u.x1[i] - u.x0[i], u.y1[i] - u.y0[i]
            dcx = abs((u.x0[i] + u.x1[i]) / 2 - (t.x0[j] + t.x1[j]) / 2); dcy = abs((u.y0[i] + u.y1[i]) / 2 - (t.y0[j] + t.y1[j]) / 2)
            if dcx < 40 and dcy < 40 and abs(wi - wj) <= 0.12 * max(wi, wj, 1) and abs(hi - hj) <= 0.12 * max(hi, hj, 1):
                d = dcx + dcy
                if best is None or d < best[0]:
                    best = (d, u, i)
        if best is not None:
            carried[id(t)] = (best[1], best[2], j)
    return carried


def motion_after(t, a, b, n=6):
    """(max per-frame box-edge step px, max per-frame scale step, max opacity change from the first frame) over the next n frames of a run starting
    at index a (the run ends at b). A per-frame STEP, not a total: a scene's ambient float/drift moves an element a pixel or so a frame and is not an
    entrance; a slam or ease-out starts with steps of 3+ px or a scale step of 0.6%+."""
    m = min(b - a, n)
    mv = ds = do = 0.0
    for k in range(1, m + 1):
        j = a + k
        mv = max(mv, abs(t.x0[j] - t.x0[j - 1]), abs(t.y0[j] - t.y0[j - 1]), abs(t.x1[j] - t.x1[j - 1]), abs(t.y1[j] - t.y1[j - 1]))
        ds = max(ds, abs(t.s[j] / max(t.s[j - 1], 1e-6) - 1))
        do = max(do, abs(t.o[j] - t.o[a]))
    return mv, ds, do


def is_static(mv, ds, do):
    return mv < TUNE["pop_static_mv"] and ds < TUNE["pop_static_ds"] and do < TUNE["pop_static_do"]


# ------------------------------------------------------------------------------------------------- rules
def continuation_cuts(tracks, cuts):
    """{cut frame: carried map} for scene cuts after which part of the picture visibly carries on (2+ texts matched)."""
    out = {}
    for fc in cuts:
        cs = carried_over(tracks, fc)
        ntext = sum(1 for t in tracks if id(t) in cs and t.kind == "text" and t.text.strip() and t.p[t.i(fc)] > 0.5)
        if ntext >= 2:
            out[fc] = cs
    return out


def rule_pop(tracks, cuts, beats_f):
    import numpy as np
    out = []
    cutset = set(cuts) | set(beats_f)
    near_cut = lambda f: any(abs(f - c) <= 1 for c in cutset)
    cont = continuation_cuts(tracks, cuts)
    # index of appearances (for the 'replacement' exemption of exits)
    appear = []
    for t in tracks:
        for a, b in t.runs():
            if int(t.g[a]) > t.pfirst:
                appear.append((int(t.g[a]), t, a))
    for t in tracks:
        for a, b in t.runs():
            f0, fl = int(t.g[a]), int(t.g[b])
            area = float(t.area[a])
            big_enough = area >= TUNE["pop_min_area"] or (t.kind == "text" and t.text.strip() != "")
            peak_o = float(np.clip(t.o, 0, 1).max())
            if f0 > t.pfirst + 1 and big_enough and float(t.p[a]) >= TUNE["pop_hard"] and peak_o >= 0.4 and area < 0.6 * FW * FH:
                atcut = [fc for fc in cuts if abs(f0 - fc) <= 1]
                if atcut:
                    fc = atcut[0]
                    # a scene cut: exempt unless the picture carries on across it and this element is NOT one of the carried ones
                    exempt = fc not in cont or id(t) in cont[fc]
                else:
                    exempt = near_cut(f0)
                if not exempt:
                    mv, ds, do = motion_after(t, a, b)
                    if not atcut and (b - a + 1) >= 8 and area >= TUNE["pop_min_area"]:
                        # appears at full opacity LARGER than its resting size and snaps back within 3 frames: a 1-3 frame entrance, not an ease
                        w0, w6 = float(t.x1[a] - t.x0[a]), float(t.x1[a + 6] - t.x0[a + 6]) if (b - a) >= 6 else 0.0
                        if w6 > 0 and w0 / w6 >= 1.08:
                            settled = 0
                            for k in range(1, 7):
                                if abs((t.x1[a + k] - t.x0[a + k]) - w6) <= 0.015 * w6:
                                    settled = k; break
                            if 0 < settled <= 3:
                                out.append(Finding("pop", "WARN", f0, f0, "enters oversized (%.0f%% of its size) at full opacity and snaps to size in %d frame(s) (standard: 6-10 eased frames)" % (100 * w0 / w6, settled), t, t.part, {"snapin": True}))
                    if not is_static(mv, ds, do) and (b - a + 1) >= 4 and not atcut and area >= TUNE["pop_fail_area"]:
                        # hard-on at full opacity, then a short settle: the kit's own slam. Not a pop, but abrupt: counted (INFO)
                        n_settle = 0
                        for k in range(1, min(b - a, 10) + 1):
                            if abs(t.x0[a + k] - t.x0[a + k - 1]) > 0.5 or abs(t.y0[a + k] - t.y0[a + k - 1]) > 0.5 or abs(t.s[a + k] / max(t.s[a + k - 1], 1e-6) - 1) > 0.002:
                                n_settle = k
                        if n_settle <= 5:
                            out.append(Finding("pop", "INFO", f0, f0, "hard-on at full opacity, settles in %d frame(s) (standard: 6-10 eased frames)" % n_settle, t, t.part, {"hardon": True}))
                    if is_static(mv, ds, do) and (b - a + 1) >= 4:
                        fail = (area >= TUNE["pop_fail_area"] or (t.kind == "text" and float(t.meta.get("fs", 0) or 0) >= 60)) and not atcut
                        out.append(Finding("pop", "FAIL" if fail else "WARN", f0, f0, "appears in ONE frame with no entrance (%.0f px^2, no motion in the next 6 frames)%s" % (area, " [the picture carries on across this cut]" if atcut else ""), t, t.part))
            # hard exit mid-beat (not a swap for something appearing in the same place)
            if fl < t.plast and big_enough and float(t.p[b]) >= TUNE["pop_hard"] and (b - a + 1) >= 4 and area < 0.6 * FW * FH and peak_o >= 0.4:
                f_gone = fl + 1
                fcx = [fc for fc in cuts if abs(f_gone - fc) <= 1]
                if fcx and (fcx[0] not in cont or id(t) not in cont[fcx[0]] and False):
                    continue
                if near_cut(f_gone) and not fcx:
                    continue
                if fcx and fcx[0] in cont:
                    # continuation cut: an exit is a pop-out only when nothing carried replaces it
                    pass
                box = (t.x0[b], t.y0[b], t.x1[b], t.y1[b])
                swapped = False
                for fa, u, ua in appear:
                    if abs(fa - f_gone) <= 1 and u is not t:
                        ux0, uy0, ux1, uy1 = u.x0[ua], u.y0[ua], u.x1[ua], u.y1[ua]
                        ix = min(box[2], ux1) - max(box[0], ux0); iy = min(box[3], uy1) - max(box[1], uy0)
                        if ix > 0 and iy > 0 and ix * iy >= 0.5 * min(area, (ux1 - ux0) * (uy1 - uy0)):
                            swapped = True; break
                if not swapped:
                    out.append(Finding("pop", "WARN" if (area < TUNE["pop_fail_area"] * 2 or fcx) else "FAIL", f_gone, f_gone, "disappears in ONE frame mid-beat with no exit (%.0f px^2)" % area, t, t.part, {"exit": True}))
    # carried elements that JUMP at a continuation cut (same thing on both sides, different size/place)
    for fc, cs in cont.items():
        for tid, (u, i, j) in cs.items():
            t = next((x for x in tracks if id(x) == tid), None)
            if t is None or u is t:
                continue
            d = max(abs(u.x0[i] - t.x0[j]), abs(u.y0[i] - t.y0[j]), abs(u.x1[i] - t.x1[j]), abs(u.y1[i] - t.y1[j]))
            wj, wi = t.x1[j] - t.x0[j], u.x1[i] - u.x0[i]
            ds = abs(wj / max(wi, 1) - 1)
            ok = t.kind == "text" and (t.text.strip() != "")
            if ok and (d >= 3.0) and float(t.area[j]) >= 5000:
                out.append(Finding("cutjump", "FAIL" if (d >= 12 or ds >= 0.02) else "WARN", fc, fc, "the same text on both sides of the cut JUMPS: edges move up to %.0f px, width %+.1f%% (a camera/scale reset at the seam)" % (d, 100 * (wj / max(wi, 1) - 1)), t, t.part, {"cutjump": True}))
    return out


def rule_flicker(tracks, cuts, beats_f):
    import numpy as np
    out = []
    cs = set()
    for c in set(cuts) | set(beats_f):
        for k in (-1, 0, 1, 2):
            cs.add(c + k)
    mx = TUNE["flicker_max_frames"]
    for t in tracks:
        if float(t.area.max()) < 3000 and t.kind != "text":
            continue
        if t.kind == "text" and len(t.text.strip()) <= 2 and any(ch.isdigit() for ch in t.text):   # a rolling digit (odometer, countdown): its glyph changes every few frames by design
            continue
        rawpk = float(np.clip(t.o, 0, 1).max())
        if rawpk < 0.4 or float(t.area.max()) > 0.6 * FW * FH:
            continue
        if t.kind != "text" and float(np.median(np.minimum(t.x1 - t.x0, t.y1 - t.y0))) < 24:   # a thin stick/hairline: its bounding box changes size as it tilts
            continue
        if t.kind == "svg":   # a drawn mark (a needle, a flow dash, a spark, a clock hand) comes and goes with its bounding box: not a visible blink
            continue
        runs = t.runs()
        for a, b in runs:
            n = b - a + 1; f0, f1 = int(t.g[a]), int(t.g[b])
            if n <= mx and f0 > t.pfirst and f1 < t.plast and float(t.p[a:b + 1].max()) >= 0.5 and f0 not in cs and f1 + 1 not in cs:
                out.append(Finding("flicker", "FAIL", f0, f1, "ghost: visible for only %d frame(s)" % n, t, t.part))
        for (a, b), (c, d) in zip(runs, runs[1:]):
            gap = int(t.g[c] - t.g[b] - 1)
            f0 = int(t.g[b]) + 1
            if 1 <= gap <= 2 and (b - a + 1) >= 3 and (d - c + 1) >= 3 and t.p[b] >= 0.6 and t.p[c] >= 0.6 and f0 not in cs:
                # a designed flip: the box squashes toward the gap (split-flap / card flip), then opens again
                h = t.y1 - t.y0
                flip = b - 2 >= a and h[b] < 0.8 * h[b - 2] or (c + 2 <= d and h[c] < 0.8 * h[c + 2])
                if not flip:
                    out.append(Finding("flicker", "FAIL", f0, f0 + gap - 1, "blink: hidden for %d frame(s) and back" % gap, t, t.part))
        for a, b in runs:
            pp = t.p[a:b + 1]
            i = 1
            while i < len(pp) - 2:
                if pp[i - 1] >= 0.8 and pp[i] < 0.3:
                    j = i
                    while j < len(pp) and pp[j] < 0.3:
                        j += 1
                    f0 = int(t.g[a + i])
                    if j < len(pp) and (j - i) <= 2 and pp[j] >= 0.8 and f0 not in cs:
                        out.append(Finding("flicker", "FAIL", f0, int(t.g[a + j - 1]), "dip: opacity falls to <30%% for %d frame(s) and returns" % (j - i), t, t.part))
                    i = j
                i += 1
    return out


def rule_jitter(tracks, cuts, beats_f):
    import numpy as np
    out = []
    win = TUNE["jitter_frames"]
    for t in tracks:
        if float(t.area.max()) < 2500 and t.kind != "text" or t.kind == "svg":   # svg marks (clock hands, needles, dashes) rotate and redraw by design
            continue
        for a, b in t.runs():
            n = b - a + 1
            if n < win + 4:
                continue
            for name, arr in (("x", t.cx[a:b + 1]), ("y", t.cy[a:b + 1]), ("w", (t.x1 - t.x0)[a:b + 1]), ("h", (t.y1 - t.y0)[a:b + 1]), ("rot", t.r[a:b + 1] * 57.2958)):
                if name in ("w", "h") and t.kind != "text":
                    continue
                d1 = np.diff(arr)
                d2 = np.diff(d1)
                # window of `win` frames: element otherwise holds (net drift under 6 px over the window), accelerations alternate in sign
                k = 0
                m = len(d2)
                while k + win <= m:
                    seg = d2[k:k + win]
                    net = abs(arr[k + win + 1] - arr[k])
                    big = np.abs(seg) > (0.4 if name == "rot" else TUNE["jitter_amp_min"])
                    alt = int(np.sum((seg[:-1] * seg[1:] < 0) & big[:-1] & big[1:]))
                    amp = float(np.max(np.abs(arr[k:k + win + 2] - np.mean(arr[k:k + win + 2]))))
                    if alt >= (4 if name == "rot" else TUNE["jitter_alt"]) and net < 6 and (0.4 if name == "rot" else TUNE["jitter_amp_min"]) <= amp <= (6.0 if name == "rot" else TUNE["jitter_amp_max"]) and float(np.min(t.p[a + k:a + k + win + 2])) > 0.8:
                        # the kit's own boil steps every 3 frames (changes only on one phase of f % 3): designed
                        chg = np.nonzero(np.abs(d1[k:k + win + 1]) > 0.2)[0]
                        phases = set(int((int(t.g[a + k + c + 1])) % 3) for c in chg)
                        if len(phases) > 1 or len(chg) < 2:
                            f0 = int(t.g[a + k]); f1 = int(t.g[a + k + win + 1])
                            out.append(Finding("jitter", "FAIL" if (amp >= 1.0 and name in ("x", "y", "rot")) else "WARN", f0, f1, "%s noise +-%.1f %s (%d sign flips in %d frames) on an element that holds" % (name, amp, "deg" if name == "rot" else "px", alt, win), t, t.part))
                            k += win
                            continue
                    k += 2
    return merge_runs(out)


def merge_runs(fs, gap=2):
    """merge findings of the same rule+element+message-kind whose frame ranges touch, keep the first"""
    fs = sorted(fs, key=lambda f: (f.rule, id(f.track), f.msg.split(" ")[0], f.f0))
    out = []
    for f in fs:
        if out and out[-1].rule == f.rule and out[-1].track is f.track and out[-1].msg.split(" ")[0] == f.msg.split(" ")[0] and f.f0 <= out[-1].f1 + gap:
            out[-1].f1 = max(out[-1].f1, f.f1)
            continue
        out.append(f)
    return out


def rule_snap_ease(tracks, cuts, beats_f):
    import numpy as np
    out = []
    tracks = [t for t in tracks if t.kind != "svg"]
    cs = set()
    for c in set(cuts) | set(beats_f):
        for k in (-1, 0, 1, 2):
            cs.add(c + k)
    for t in tracks:
        if float(t.area.max()) < 2500 and not (t.kind == "text" and t.text.strip()):
            continue
        if float(t.area.max()) > 0.2 * FW * FH:   # a scrolling ground / tiled background wraps by one period: not a snap
            continue
        for a, b in t.runs():
            n = b - a + 1
            if n < 6:
                continue
            cx, cy, w = t.cx[a:b + 1], t.cy[a:b + 1], (t.x1 - t.x0)[a:b + 1]
            sp = np.hypot(np.diff(cx), np.diff(cy))
            sr = np.abs(t.s[a + 1:b + 1] / np.maximum(t.s[a:b], 1e-6) - 1)
            wr = np.abs(w[1:] / np.maximum(w[:-1], 1e-6) - 1)
            hh_ = (t.y1 - t.y0)[a:b + 1]
            hr = np.abs(hh_[1:] / np.maximum(hh_[:-1], 1e-6) - 1) if t.kind == "text" else np.zeros(len(wr))
            fr = t.g[a:b + 1]
            for i in range(2, len(sp) - 2):
                f = int(fr[i + 1])
                if f in cs or t.p[a + i] < 0.8 or t.p[a + i + 1] < 0.8:
                    continue
                jump = sp[i] > TUNE["snap_px"] or sr[i] > TUNE["snap_scale"] or (wr[i] > 0.15 and t.kind == "text") or (hr[i] > 0.25 and t.kind == "text")
                if jump and max(sp[i - 2], sp[i - 1], sp[i + 1], sp[i + 2]) < TUNE["snap_still"] and max(sr[i - 2:i].max(), sr[i + 1:i + 3].max()) < 0.01:
                    swap_only = t.kind == "text" and (wr[i] > 0.15 or hr[i] > 0.25 or (sp[i] <= TUNE["snap_px"] and sr[i] <= TUNE["snap_scale"]))   # same centre, new width/height: the string changed (a text swap), not a move
                    out.append(Finding("snap", "WARN" if swap_only else "FAIL", f, f, "jumps %.0f px / %.0f%% scale%s in ONE frame mid-hold (no easing)" % (sp[i], 100 * max(sr[i], wr[i] if t.kind == "text" else 0), (" / %.0f%% height (text reflow)" % (100 * hr[i])) if hr[i] > 0.25 else ""), t, t.part))
            # (periodic wraps are filtered after the loop)
            # entrance-style moves: rest -> move -> rest
            mv = sp > 1.5
            i = 0
            while i < len(sp):
                if mv[i]:
                    j = i
                    while j < len(sp) and mv[j]:
                        j += 1
                    seg = sp[i:j]
                    dist = float(np.hypot(cx[j] - cx[i], cy[j] - cy[i]))
                    rest_before = i == 0 or sp[max(0, i - 3):i].max() < 0.8
                    rest_after = j >= len(sp) or sp[j:j + 3].max() < 0.8
                    f0 = int(fr[i]); f1 = int(fr[j])
                    width_changes = t.kind == "text" and abs(w[min(j, len(w) - 1)] / max(w[i], 1) - 1) > 0.15   # a changed string is a text swap, not a move
                    if rest_before and rest_after and not width_changes and dist >= TUNE["ease_min_move"] and f0 not in cs and f0 > t.pfirst + 1 and float(np.min(t.p[a + i:a + j + 1])) > 0.6:
                        L = j - i
                        if L <= TUNE["ease_fast_frames"] and dist >= 80:
                            out.append(Finding("easing", "FAIL", f0, f1, "moves %.0f px in %d frames (too fast to read, standard is 6-10)" % (dist, L), t, t.part))
                        elif L >= 6:
                            mean = float(seg.mean())
                            cv = float(seg.std() / mean) if mean > 0 else 1.0
                            ends = min(seg[0], seg[-1]) / mean if mean > 0 else 0
                            if cv < TUNE["ease_cv"] and ends > 0.8:
                                big = float(t.area[a + i]) >= 15000 and min(float(t.x1[a + i] - t.x0[a + i]), float(t.y1[a + i] - t.y0[a + i])) >= 60
                                out.append(Finding("easing", "FAIL" if big else "WARN", f0, f1, "linear move: %.0f px over %d frames at constant speed (cv %.2f), no ease" % (dist, L, cv), t, t.part))
                    i = j
                else:
                    i += 1
    # a jump that repeats (3+ times, same label, same distance) is a tiled/looping background wrapping by one period, or a designed blip
    cnt = {}
    for f in out:
        if f.rule == "snap":
            k = (f.track.label, f.msg.split(" in ONE")[0][:24])
            cnt[k] = cnt.get(k, 0) + 1
    out = [f for f in out if not (f.rule == "snap" and cnt[(f.track.label, f.msg.split(" in ONE")[0][:24])] >= 3)]
    return out


def rule_overlap(tracks, cuts, beats_f):
    import numpy as np
    out = []
    cs = set()
    for c in set(cuts) | set(beats_f):
        for k in (-1, 0, 1, 2):
            cs.add(c + k)
    byp = {}
    for t in tracks:
        if t.kind == "text" and len(t.text.strip()) >= 3 and float(np.clip(t.o, 0, 1).max()) > 0.5:
            byp.setdefault(t.part, []).append(t)
    for part, ts in byp.items():
        n = len(ts)
        if n < 2:
            continue
        g0 = min(int(t.g[0]) for t in ts); g1 = max(int(t.g[-1]) for t in ts)
        F = g1 - g0 + 1
        X0 = np.full((n, F), np.nan); Y0 = X0.copy(); X1 = X0.copy(); Y1 = X0.copy(); P = np.zeros((n, F))
        for k, t in enumerate(ts):
            ix = t.g - g0
            # ink approximation: shave 12% off top and bottom (line boxes include leading)
            hh = t.y1 - t.y0
            X0[k, ix] = t.x0; X1[k, ix] = t.x1; Y0[k, ix] = t.y0 + 0.12 * hh; Y1[k, ix] = t.y1 - 0.12 * hh
            P[k, ix] = t.p * np.clip(t.o, 0, 1)
        A = (X1 - X0) * (Y1 - Y0)
        for i in range(n):
            for j in range(i + 1, n):
                ti, tj = ts[i], ts[j]
                if ti.text == tj.text:
                    continue
                lo = max(int(ti.g[0]), int(tj.g[0])) - g0; hi = min(int(ti.g[-1]), int(tj.g[-1])) - g0
                if hi < lo:
                    continue
                sl = slice(lo, hi + 1)
                ox = np.minimum(X1[i, sl], X1[j, sl]) - np.maximum(X0[i, sl], X0[j, sl])
                oy = np.minimum(Y1[i, sl], Y1[j, sl]) - np.maximum(Y0[i, sl], Y0[j, sl])
                ov = np.where((ox > 0) & (oy > 0), ox * oy, 0.0)
                sm = np.minimum(A[i, sl], A[j, sl])
                fr = np.where(sm > 0, ov / np.where(sm > 0, sm, 1), 0.0)
                hit = (fr > TUNE["overlap_frac"]) & (P[i, sl] > 0.7) & (P[j, sl] > 0.7)
                if not hit.any():
                    continue
                idx = np.nonzero(hit)[0]
                # runs
                runs = np.split(idx, np.nonzero(np.diff(idx) != 1)[0] + 1)
                for r in runs:
                    L = len(r)
                    f0 = g0 + lo + int(r[0]); f1 = g0 + lo + int(r[-1])
                    before_clear = r[0] > 0 and not hit[r[0] - 1] and (lo + r[0] - 1 >= 0)
                    after_clear = r[-1] < len(hit) - 1 and not hit[r[-1] + 1]
                    if L <= TUNE["overlap_max_frames"] and before_clear and after_clear and f0 not in cs and f0 - 1 not in cs and f1 + 1 not in cs:
                        out.append(Finding("overlap", "FAIL" if fr[r].max() > 0.3 else "WARN", f0, f1, "text collides with '%s' for %d frame(s) (%.0f%% of the smaller box) then separates" % (tj.text[:24], L, 100 * fr[r].max()), ti, ti.part))
    return out


def rule_edge(tracks, cuts, beats_f):
    import numpy as np
    out = []
    for t in tracks:
        if float(t.area.max()) > 0.6 * FW * FH or float(t.area.max()) < 2500 and t.kind != "text":
            continue
        # an entrance that STARTS oversized and is clipped by the frame edge (a stamp slamming in at 2.6x): mostly on-frame at the first frame, overflowing, inside by frame 10
        for a, b in t.runs():
            if int(t.g[a]) <= t.pfirst + 1 or b - a < 12:
                continue
            ov0 = np.maximum.reduce([-t.x0[a:a + 11], -t.y0[a:a + 11], t.x1[a:a + 11] - FW, t.y1[a:a + 11] - FH])
            onf = (min(t.x1[a], FW) - max(t.x0[a], 0)) * (min(t.y1[a], FH) - max(t.y0[a], 0)) / max(float(t.area[a]), 1.0)
            if t.kind != "svg" and float(t.area.max()) < 0.3 * FW * FH and ov0[0] >= max(12.0, TUNE["edge_px"]) and onf >= 0.6 and ov0[10] <= 1.0 and float(t.p[a]) > 0.5 and float(np.clip(t.o, 0, 1).max()) >= 0.4:
                n_out = int(np.sum(ov0 >= TUNE["edge_px"]))
                out.append(Finding("edge", "FAIL" if n_out >= 2 else "WARN", int(t.g[a]), int(t.g[a]) + n_out - 1, "enters oversized and is clipped by the frame edge by up to %.0f px for %d frame(s), inside by frame 10" % (float(ov0.max()), n_out), t, t.part))
        for a, b in t.runs():
            if b - a < 6:
                continue
            ov = np.maximum.reduce([-t.x0[a:b + 1], -t.y0[a:b + 1], t.x1[a:b + 1] - FW, t.y1[a:b + 1] - FH])
            out_f = ov >= TUNE["edge_px"]
            if not out_f.any():
                continue
            idx = np.nonzero(out_f)[0]
            for r in np.split(idx, np.nonzero(np.diff(idx) != 1)[0] + 1):
                if len(r) > TUNE["edge_max_frames"] or r[0] < 2 or r[-1] > len(out_f) - 3:
                    continue
                jump = float(np.hypot(t.cx[a + r[0]] - t.cx[a + r[0] - 1], t.cy[a + r[0]] - t.cy[a + r[0] - 1]))
                peak = int(np.argmax(ov[r[0]:r[-1] + 1]))
                if jump < 40 and 0 < peak < len(r) - 1 and ov[r[0] - 2] <= 1.0 and ov[r[-1] + 2] <= 1.0 and float(t.p[a + r[0]:a + r[-1] + 1].max()) > 0.5:
                    f0 = int(t.g[a + r[0]]); f1 = int(t.g[a + r[-1]])
                    out.append(Finding("edge", "FAIL", f0, f1, "crosses the frame edge by up to %.0f px for %d frame(s) (overshoot clipped), inside before and after" % (ov[r].max(), len(r)), t, t.part))
    return out


def rule_universal(tracks, cuts, beats_f):
    """(19 Oct 2026) text and hero objects stay inside the UNIVERSAL safe zone (kit/platforms/universal.py: free of the UI of TikTok, Instagram Reels,
    YouTube Shorts, Facebook Reels and LinkedIn at once). Per element, over its frames at presence > 0.5: a text box that leaves the zone by more than
    8 px (text line boxes are shrunk by 12% top and bottom: a DOM line box carries leading the ink does not), a hero object (img / drawing / card of 6000-55%
    of the frame, not a full-width band) with at least half of its area outside. A run of 9 frames (0.3 s) is a resting place; shorter is a transit.
    FAIL for shorts claimed at or after live_from, WARN for in-flight ones."""
    import numpy as np
    import universal
    z = universal.zone()
    lvl = UNIVERSAL_LEVEL or "WARN"
    out = []
    for t in tracks:
        if not len(t.g):
            continue
        w, h = t.x1 - t.x0, t.y1 - t.y0
        area = w * h
        pres = (np.clip(t.o, 0, 1) * np.clip(t.v, 0, 1)) > 0.5
        if t.kind == "text":
            if not (t.text or "").strip():
                continue
            y0, y1 = t.y0 + 0.12 * h, t.y1 - 0.12 * h
            bad = np.zeros(len(t.g), bool)
            bad |= (z["x0"] - t.x0) > universal.TOL_PX
            bad |= (t.x1 - z["x1"]) > universal.TOL_PX
            bad |= (z["y0"] - y0) > universal.TOL_PX
            bad |= (y1 - z["y1"]) > universal.TOL_PX
            for n in z.get("notches", []):
                bad |= (y1 > n["y0"]) & (y0 < n["y1"]) & ((t.x1 - n["x0"]) > universal.TOL_PX) & (t.x0 < n["x1"])
            bad &= pres & (t.x1 > 0) & (t.x0 < FW) & (t.y1 > 0) & (t.y0 < FH)
            kind = "universal_text"
        elif t.kind in ("img", "svg", "box", "canvas"):
            ok_size = (area >= universal.HERO_MIN_AREA) & (area <= universal.HERO_MAX_AREA) & (w < 0.95 * FW) & (h < 0.95 * FH)
            if not ok_size.any():
                continue
            ins = np.array([universal.inside_area((float(a), float(b), float(c), float(d)), z) for a, b, c, d in zip(t.x0, t.y0, t.x1, t.y1)])
            bad = ok_size & pres & (ins < (1.0 - universal.HERO_OUT_FRAC) * np.maximum(area, 1.0))
            kind = "universal_hero"
        else:
            continue
        idx = np.nonzero(bad)[0]
        if not len(idx):
            continue
        for r in np.split(idx, np.nonzero(np.diff(idx) != 1)[0] + 1):
            if len(r) < 9:
                continue
            i = int(r[len(r) // 2])
            box = [float(t.x0[i]), float(t.y0[i]), float(t.x1[i]), float(t.y1[i])]
            msg = "%s: outside the universal safe zone (x %d-%d, y %d-%d, no TikTok column), box %s, for %.1f s" % (
                "text" if t.kind == "text" else "object", z["x0"], z["x1"], z["y0"], z["y1"], [round(v) for v in box], len(r) / FPS)
            out.append(Finding("universal", lvl, int(t.g[r[0]]), int(t.g[r[-1]]), msg, t, t.part))
    # one line per scene run: a row of cards under the caption band is one defect
    grp = {}
    for f in out:
        grp.setdefault((f.part, f.track.kind == "text", round(f.f1 / 15.0)), []).append(f)
    res = []
    for fs in grp.values():
        f = fs[0]
        if len(fs) > 1:
            f.msg += " (+%d more in this scene)" % (len(fs) - 1)
        res.append(f)
    return res


def rule_distort(tracks):
    """an <img> drawn at a different aspect from its file (a squashed/stretched source card or picture); object-fit boxes are exempt"""
    out = []
    seen = set()
    for t in tracks:
        if t.kind != "img":
            continue
        m = t.meta
        nw, nh, ow, oh = float(m.get("nw", 0) or 0), float(m.get("nh", 0) or 0), float(m.get("ow", 0) or 0), float(m.get("oh", 0) or 0)
        if nw < 8 or nh < 8 or ow < 8 or oh < 8 or m.get("of") in ("cover", "contain", "scale-down", "none"):
            continue
        k = (ow / oh) / (nw / nh)
        if abs(k - 1) > 0.04 and float(t.area.max()) >= 5000:
            key = (t.part, m.get("src"), round(k, 2))
            if key in seen:
                continue
            seen.add(key)
            out.append(Finding("distort", "FAIL" if abs(k - 1) > 0.12 else "WARN", int(t.g[0]), int(t.g[-1]),
                               "image drawn at %.0f%% of its natural aspect (%dx%d file shown in a %dx%d box): %s" % (100 * k, nw, nh, ow, oh, "squashed" if k > 1 else "stretched" if k < 1 else ""), t, t.part, {"src": m.get("src")}))
    return out


def hex_dist(a, b):
    try:
        x = [int(v) for v in a.split(",")]; y = [int(v) for v in b.split(",")]
        return math.sqrt(sum((p - q) ** 2 for p, q in zip(x, y)))
    except ValueError:
        return 0.0


def rule_colour(tracks, cuts, beats_f):
    """a visible element changes colour by a large step in ONE frame, mid-hold (no ramp): highlight swaps, lit chips, recoloured words"""
    out = []
    cs = set()
    for c in set(cuts) | set(beats_f):
        for k in (-1, 0, 1, 2):
            cs.add(c + k)
    for t in tracks:
        if not t.col or float(t.area.max()) < 2500 and t.kind != "text":
            continue
        is_text = t.kind == "text"   # a word recolouring on the beat is the kit's designed highlight: INFO (counted), not a defect
        for a, b in t.runs():
            for i in range(max(a, 2), b - 2):
                f = int(t.g[i])
                if t.col[i] != t.col[i - 1] and t.col[i] and t.col[i - 1] and f not in cs and t.p[i] > 0.8 and t.p[i - 1] > 0.8:
                    d = hex_dist(t.col[i], t.col[i - 1])
                    if d >= 90 and t.col[i + 1] == t.col[i] and t.col[i - 2] == t.col[i - 1]:
                        out.append(Finding("colour", "INFO" if is_text else "WARN", f, f, "colour switches rgb(%s) -> rgb(%s) in ONE frame (step %.0f, no ramp)" % (t.col[i - 1], t.col[i], d), t, t.part))
    return out


def rule_overlap_obj(tracks, cuts, beats_f):
    """text partly covered by (or straddling the edge of) an opaque object that is not its container, for 3+ frames"""
    import numpy as np
    out = []
    objs = [t for t in tracks if t.kind in ("box", "img") and 3000 <= float(t.area.max()) <= 0.5 * FW * FH and float(np.clip(t.o, 0, 1).max()) >= 0.9]
    texts = [t for t in tracks if t.kind == "text" and len(t.text.strip()) >= 3 and float(np.clip(t.o, 0, 1).max()) > 0.5]
    byp = {}
    for o in objs:
        byp.setdefault(o.part, []).append(o)
    seen = set()
    for t in texts:
        tpath = t.key.split("#t")[0]
        for o in byp.get(t.part, []):
            if tpath.startswith(o.key + "/") or o.key.startswith(tpath + "/"):
                continue
            if t.meta.get("od") is not None and o.meta.get("od") is not None and not above(o, t):
                continue   # the object paints BELOW the text: text on a card/ground, not covered
            lo = max(int(t.g[0]), int(o.g[0])); hi = min(int(t.g[-1]), int(o.g[-1]))
            if hi - lo < 3:
                continue
            run = 0; first = None; peak = 0.0
            for f in range(lo, hi + 1):
                i, j = t.i(f), o.i(f)
                if i is None or j is None or t.p[i] < 0.7 or o.p[j] < 0.9:
                    run = 0; first = None; continue
                hh = t.y1[i] - t.y0[i]
                ty0, ty1 = t.y0[i] + 0.12 * hh, t.y1[i] - 0.12 * hh
                ox = min(t.x1[i], o.x1[j]) - max(t.x0[i], o.x0[j]); oy = min(ty1, o.y1[j]) - max(ty0, o.y0[j])
                ta = (t.x1[i] - t.x0[i]) * (ty1 - ty0)
                fr = (ox * oy / ta) if (ox > 0 and oy > 0 and ta > 0) else 0.0
                if 0.06 < fr < 0.6:
                    run += 1; first = first if first is not None else f; peak = max(peak, fr)
                    if run == 8 and (t.text, o.label, round(float(o.x0[j]) / 8)) not in seen:
                        seen.add((t.text, o.label, round(float(o.x0[j]) / 8)))
                        out.append(Finding("overlap", "WARN", first, first + 7, "text partly covered by %s '%s' (%.0f%% of the text box) for 8+ frames: it neither contains it nor clears it" % (o.kind, o.label, 100 * fr), t, t.part))
                else:
                    run = 0; first = None
    return out


def rule_cropcut(tracks, get_image):
    """a source card shown through a clip window: the window's left/right/top/bottom edge slices through ink (a letter, a full stop, a line).
    get_image(src) -> PIL image of that file from the package, or None. Looks at the steady window (static for 3 frames, fully visible)."""
    import numpy as np
    out = []
    seen = set()
    for t in tracks:
        if t.kind != "img" or not t.cbx or t.meta.get("of") in ("cover", "contain"):
            continue
        nw, nh = float(t.meta.get("nw", 0) or 0), float(t.meta.get("nh", 0) or 0)
        if nw < 50 or nh < 20 or float(t.area.max()) < 20000 or abs(float(t.r[0])) > 0.12:
            continue
        im = get_image(t.meta.get("src", ""))
        if im is None:
            continue
        g = np.asarray(im.convert("L"), dtype=np.int16)
        bg = int(np.median(g))
        ink = np.abs(g - bg) > 70
        for i in range(3, len(t.g) - 3):
            cb, cp = t.cbx[i], t.cbx[i - 3]
            if cb is None or cp is None or t.p[i] < 0.9:
                continue
            if max(abs(cb[k] - cp[k]) for k in range(4)) > 0.6:
                continue
            bw, bh = float(t.x1[i] - t.x0[i]), float(t.y1[i] - t.y0[i])
            if bw < 10 or bh < 10 or float(t.v[i]) < 0.02:
                continue
            kx, ky = nw / bw, nh / bh
            wx0, wx1 = int(round((cb[0] - t.x0[i]) * kx)), int(round((cb[2] - t.x0[i]) * kx))
            wy0, wy1 = int(round((cb[1] - t.y0[i]) * ky)), int(round((cb[3] - t.y0[i]) * ky))
            wx0, wy0 = max(0, wx0), max(0, wy0); wx1, wy1 = min(ink.shape[1], wx1), min(ink.shape[0], wy1)
            if wx1 - wx0 < 30 or wy1 - wy0 < 20:
                continue
            cuts = []
            # a cut through a glyph: ink on BOTH sides of the window edge at the same rows (left/right) or columns (top/bottom)
            if wx1 < ink.shape[1] - 1 and wx1 > 3:
                a = ink[wy0:wy1, wx1 - 3:wx1].any(axis=1); b = ink[wy0:wy1, wx1:wx1 + 3].any(axis=1)
                if int((a & b).sum()) >= 8:
                    cuts.append("right")
            if wx0 > 3:
                a = ink[wy0:wy1, wx0:wx0 + 3].any(axis=1); b = ink[wy0:wy1, wx0 - 3:wx0].any(axis=1)
                if int((a & b).sum()) >= 8:
                    cuts.append("left")
            # top/bottom edges are not judged: a crop window shows chosen lines of an article, so slivers of the neighbouring line at its top/bottom are the nature of a real-source crop
            if cuts:
                key = (t.part, t.meta.get("src"), tuple(cuts))
                if key in seen:
                    continue
                seen.add(key)
                out.append(Finding("cropcut", "WARN", int(t.g[i]), int(t.g[i]), "the clip window of source card %s slices through ink at its %s edge (a letter/full stop is cut)" % (t.meta.get("src", "")[-34:], "/".join(cuts)), t, t.part))
    return out


def paint_key(t):
    z = [int(x) for x in str(t.z[0]).split(".") if x.lstrip("-").isdigit()] if t.z and t.z[0] else []
    return (z, int(t.meta.get("od", 0) or 0))


def above(a, b):
    """True if a paints above b (z-index chain, then document order). Unknown order -> False."""
    za, oa = paint_key(a); zb, ob = paint_key(b)
    n = max(len(za), len(zb)); za = za + [0] * (n - len(za)); zb = zb + [0] * (n - len(zb))
    return (za, oa) > (zb, ob)


def rule_touch(tracks, cuts, beats_f):
    """two different text lines whose ink boxes overlap a little (2-15% of the smaller) and STAY like that for 12+ frames: lines touching / overprinting"""
    import numpy as np
    out = []
    byp = {}
    for t in tracks:
        if t.kind == "text" and len(t.text.strip()) >= 3 and float(np.clip(t.o, 0, 1).max()) > 0.5 and float(t.meta.get("fs", 0) or 0) >= 40:
            byp.setdefault(t.part, []).append(t)
    for part, ts in byp.items():
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                a, b = ts[i], ts[j]
                if a.text == b.text:
                    continue
                lo = max(int(a.g[0]), int(b.g[0])); hi = min(int(a.g[-1]), int(b.g[-1]))
                if hi - lo < 12:
                    continue
                run = 0; first = None; peak = 0.0
                for f in range(lo, hi + 1):
                    ia, ib = a.i(f), b.i(f)
                    if ia is None or ib is None or a.p[ia] < 0.9 or b.p[ib] < 0.9:
                        run = 0; first = None; continue
                    ha, hb = a.y1[ia] - a.y0[ia], b.y1[ib] - b.y0[ib]
                    ay0, ay1 = a.y0[ia] + 0.16 * ha, a.y1[ia] - 0.16 * ha
                    by0, by1 = b.y0[ib] + 0.16 * hb, b.y1[ib] - 0.16 * hb
                    ox = min(a.x1[ia], b.x1[ib]) - max(a.x0[ia], b.x0[ib]); oy = min(ay1, by1) - max(ay0, by0)
                    sm = min((a.x1[ia] - a.x0[ia]) * (ay1 - ay0), (b.x1[ib] - b.x0[ib]) * (by1 - by0))
                    fr = ox * oy / sm if (ox > 0 and oy > 0 and sm > 0) else 0.0
                    if 0.06 < fr < 0.30 and oy >= 2.0 and ox >= 0.3 * min(a.x1[ia] - a.x0[ia], b.x1[ib] - b.x0[ib]):
                        run += 1; first = first if first is not None else f; peak = max(peak, fr)
                        if run == 12:
                            out.append(Finding("overlap", "WARN", first, first + 11, "text lines touch/overprint '%s' for 12+ frames (%.0f%% of the smaller box)" % (b.text[:24], 100 * peak), a, a.part))
                    else:
                        run = 0; first = None
    return out


def rule_style(tracks):
    """sibling boxes (same parent, same label, similar size) that should match but differ in corner radius / border width / shadow; same-label text siblings whose type size or stack gaps are a near-miss"""
    import numpy as np
    out = []
    groups = {}
    for t in tracks:
        if t.kind == "box" and float(t.area.max()) >= 6000:
            groups.setdefault((t.part, t.meta.get("pid"), t.label), []).append(t)
    seen = set()
    for key, ts in groups.items():
        if len(ts) < 2 or len(ts) > 30:
            continue
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                a, b = ts[i], ts[j]
                lo = max(int(a.g[0]), int(b.g[0])); hi = min(int(a.g[-1]), int(b.g[-1]))
                if hi - lo < 10:
                    continue
                f = (lo + hi) // 2
                ia, ib = a.i(f), b.i(f)
                if ia is None or ib is None or a.p[ia] < 0.95 or b.p[ib] < 0.95:
                    continue
                wa, ha, wb, hb = a.x1[ia] - a.x0[ia], a.y1[ia] - a.y0[ia], b.x1[ib] - b.x0[ib], b.y1[ib] - b.y0[ib]
                if abs(wa - wb) > 0.15 * max(wa, wb) or abs(ha - hb) > 0.15 * max(ha, hb):
                    continue
                diffs = []
                if str(a.meta.get("cr")) != str(b.meta.get("cr")):
                    diffs.append("corner radius %s vs %s" % (a.meta.get("cr"), b.meta.get("cr")))
                if abs(float(a.meta.get("bw", 0) or 0) - float(b.meta.get("bw", 0) or 0)) >= 1:
                    diffs.append("border %.0f vs %.0f px" % (float(a.meta.get("bw", 0) or 0), float(b.meta.get("bw", 0) or 0)))
                if int(a.meta.get("sh", 0) or 0) != int(b.meta.get("sh", 0) or 0):
                    diffs.append("shadow on one, none on the other")
                if diffs and (key, tuple(diffs)) not in seen:
                    seen.add((key, tuple(diffs)))
                    out.append(Finding("style", "WARN", f, f, "sibling %s boxes of the same size differ: %s" % (a.label, "; ".join(diffs)), a, a.part))
    tg = {}
    for t in tracks:
        if t.kind == "text" and len(t.text.strip()) >= 3 and float(t.meta.get("fs", 0) or 0) >= 42:
            tg.setdefault((t.part, t.label), []).append(t)
    for (part, lab), ts in tg.items():
        if len(ts) < 2 or len(ts) > 40:
            continue
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                a, b = ts[i], ts[j]
                if a.text == b.text:
                    continue
                lo = max(int(a.g[0]), int(b.g[0])); hi = min(int(a.g[-1]), int(b.g[-1]))
                if hi - lo < 10:
                    continue
                fa, fb = float(a.meta.get("fs", 0) or 0), float(b.meta.get("fs", 0) or 0)
                r = max(fa, fb) / max(min(fa, fb), 1)
                if 1.03 <= r <= 1.15:
                    key = (part, lab, round(fa), round(fb))
                    if key in seen:
                        continue
                    seen.add(key)
                    f = (lo + hi) // 2
                    out.append(Finding("typescale", "WARN", f, f, "two '%s' texts on the same screen at %.0f and %.0f px (a %.0f%% step: neither the same size nor a deliberate step)" % (lab, fa, fb, 100 * (r - 1)), a, a.part))
    return out


def rule_glitch(tracks, cuts, beats_f):
    """a stable element changes size by 3%+ for exactly ONE frame and returns (a one-frame scale/size glitch), centre unchanged"""
    import numpy as np
    out = []
    cs = set()
    for c in set(cuts) | set(beats_f):
        for k in (-1, 0, 1, 2):
            cs.add(c + k)
    for t in tracks:
        if float(t.area.max()) < 3000 and not (t.kind == "text" and t.text.strip()) or float(t.area.max()) > 0.5 * FW * FH:
            continue
        for a, b in t.runs():
            if b - a < 8:
                continue
            w = (t.x1 - t.x0)[a:b + 1]
            for i in range(3, len(w) - 3):
                f = int(t.g[a + i])
                if f in cs or t.p[a + i] < 0.9:
                    continue
                before, here, after = w[i - 1], w[i], w[i + 1]
                if abs(w[i - 2] / max(before, 1) - 1) < 0.005 and abs(w[i + 2] / max(after, 1) - 1) < 0.005 and abs(after / max(before, 1) - 1) < 0.01 and abs(here / max(before, 1) - 1) >= 0.03:
                    dc = abs((t.x0[a + i] + t.x1[a + i]) / 2 - (t.x0[a + i - 1] + t.x1[a + i - 1]) / 2)
                    out.append(Finding("snap", "WARN", f, f, "one-frame size glitch: width %+.1f%% for ONE frame and back" % (100 * (here / max(before, 1) - 1)), t, t.part, {"glitch": True}))
    # the same pulse repeating (3+ times with the same size and step) is a designed beat (a blip, a scan bar), not a defect
    cnt = {}
    for f in out:
        cnt[(f.part, f.track.label, round(float(f.track.x1[0] - f.track.x0[0])), f.msg)] = cnt.get((f.part, f.track.label, round(float(f.track.x1[0] - f.track.x0[0])), f.msg), 0) + 1
    return [f for f in out if cnt[(f.part, f.track.label, round(float(f.track.x1[0] - f.track.x0[0])), f.msg)] < 3]


def rule_widow(tracks):
    out = []
    seen = set()
    for t in tracks:
        lw = t.meta.get("lw")
        if t.kind != "text" or not lw or len(lw) < 2:
            continue
        if t.text in seen:
            continue
        fs = float(t.meta.get("fs", 0) or 0)
        tot = sum(lw)
        if tot >= TUNE["widow_min_words"] and lw[-1] == 1 and max(lw[:-1]) >= 2:
            seen.add(t.text)
            out.append(Finding("widow", "WARN", int(t.g[0]), int(t.g[0]), "last line is ONE word: lines %s (%d px type)" % ("/".join(str(x) for x in lw), fs), t, t.part))
        elif len(lw) >= 3 and tot >= TUNE["widow_min_words"] and any(x == 1 for x in lw[1:-1]) and max(lw) >= 3:
            seen.add(t.text)
            out.append(Finding("widow", "WARN", int(t.g[0]), int(t.g[0]), "orphaned single word on its own middle line: lines %s" % "/".join(str(x) for x in lw), t, t.part))
    return out


def rule_drift(tracks, cuts, beats_f):
    """stacked siblings that nearly share an edge: left edges (left-aligned text/cards) or centres (centred text) 1-6 px apart"""
    import numpy as np
    out = []
    byp = {}
    for t in tracks:
        if t.kind in ("text", "box", "img") and float(t.area.max()) >= 2500 or (t.kind == "text" and t.text.strip()):
            pid = t.meta.get("pid") or ""
            byp.setdefault((t.part, pid), []).append(t)
    seen = set()
    for (part, pid), ts in byp.items():
        if len(ts) < 2 or len(ts) > 60:
            continue
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                a, b = ts[i], ts[j]
                if a.kind != b.kind:
                    continue
                lo = max(int(a.g[0]), int(b.g[0])); hi = min(int(a.g[-1]), int(b.g[-1]))
                if hi - lo < 12:
                    continue
                # a stable moment: both fully visible and unmoving for 4 frames
                f = None
                for ff in range(lo + 3, hi - 3):
                    ia, ib = a.i(ff), b.i(ff)
                    if ia is None or ib is None:
                        continue
                    if a.p[ia] > 0.95 and b.p[ib] > 0.95 and abs(a.x0[ia] - a.x0[ia - 3]) < 0.3 and abs(b.x0[ib] - b.x0[ib - 3]) < 0.3 and abs(a.y0[ia] - a.y0[ia - 3]) < 0.3 and abs(b.y0[ib] - b.y0[ib - 3]) < 0.3:
                        f = ff; break
                if f is None:
                    continue
                ia, ib = a.i(f), b.i(f)
                ax0, ay0, ax1, ay1 = a.x0[ia], a.y0[ia], a.x1[ia], a.y1[ia]
                bx0, by0, bx1, by1 = b.x0[ib], b.y0[ib], b.x1[ib], b.y1[ib]
                ovx = min(ax1, bx1) - max(ax0, bx0)
                stacked = ay1 <= by0 + 1 or by1 <= ay0 + 1
                if not stacked or ovx < 0.5 * min(ax1 - ax0, bx1 - bx0):
                    continue
                if abs((ay1 - ay0) - (by1 - by0)) > 0.35 * max(ay1 - ay0, by1 - by0) and a.kind == "text":
                    continue
                if a.kind == "text" and (a.text == b.text or abs(float(a.meta.get("fs", 0) or 0) - float(b.meta.get("fs", 0) or 0)) > 3):
                    continue
                dl = abs(ax0 - bx0); dc = abs((ax0 + ax1) / 2 - (bx0 + bx1) / 2); dr = abs(ax1 - bx1)
                left_al = a.meta.get("ta", "left") in ("left", "start") and b.meta.get("ta", "left") in ("left", "start")
                cen_al = a.meta.get("ta") == "center" and b.meta.get("ta") == "center"
                kind = None
                if a.kind != "text" and abs((ax1 - ax0) - (bx1 - bx0)) < 2.5:   # same-width stacked cards: left edge must match
                    if TUNE["drift_min"] <= dl <= TUNE["drift_max"]:
                        kind = "left edges differ by %.1f px (same-width stacked objects)" % dl
                elif a.kind == "text" and left_al and TUNE["drift_min"] <= dl <= TUNE["drift_max"]:
                    kind = "left edges differ by %.1f px (stacked left-aligned text, same type size)" % dl
                elif a.kind == "text" and cen_al and TUNE["drift_min"] <= dc <= TUNE["drift_max"] and len(a.text.strip()) > 2 and len(b.text.strip()) > 2:
                    kind = "centres differ by %.1f px (stacked centred text)" % dc
                if kind:
                    key = (part, round(ax0), round(bx0), a.text, b.text)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(Finding("drift", "WARN", f, f, "%s vs %s" % (kind, ("'%s'" % b.text[:24]) if b.text else b.label), a, a.part))
    return out


def rule_zflip(tracks):
    out = []
    for t in tracks:
        if float(t.area.max()) < 2500 or not t.z:
            continue
        for a, b in t.runs():
            if b - a < 8:
                continue
            zs = t.z[a:b + 1]
            for i in range(3, len(zs) - 3):
                if zs[i] != zs[i - 1] and t.p[a + i] > 0.8 and t.p[a + i - 1] > 0.8 and zs[i - 3] == zs[i - 1] and zs[i + 2] == zs[i]:
                    out.append(Finding("zflip", "WARN", int(t.g[a + i]), int(t.g[a + i]), "z-index changes %r -> %r while visible (layer jumps in front/behind)" % (zs[i - 1], zs[i]), t, t.part))
    return out


def visual_events(tracks, cuts):
    """[(frame, kind, area)] : appear, land (motion end), cut"""
    import numpy as np
    ev = [(f, "cut", 0.0) for f in cuts]
    for t in tracks:
        if float(t.area.max()) < 2500 and not (t.kind == "text" and t.text.strip()):
            continue
        if float(t.area.max()) > 0.6 * FW * FH:
            continue
        for a, b in t.runs():
            f0 = int(t.g[a])
            if f0 > t.pfirst:
                # the frame it first shows ON the screen (an element sliding in from off-frame is in the DOM earlier)
                k0 = a
                while k0 < b and (min(t.x1[k0], FW) - max(t.x0[k0], 0)) * (min(t.y1[k0], FH) - max(t.y0[k0], 0)) < 0.1 * float(t.area[k0]):
                    k0 += 1
                ev.append((int(t.g[k0]), "appear", float(t.area[a])))
            n = b - a + 1
            if n >= 4:
                sp = np.hypot(np.diff(t.cx[a:b + 1]), np.diff(t.cy[a:b + 1])) + np.abs(np.diff(t.s[a:b + 1])) * 600
                for i in range(1, len(sp) - 2):
                    if sp[i - 1] > 3 and sp[i + 1] < 0.8 and sp[i] <= sp[i - 1]:
                        ev.append((int(t.g[a + i + 1]), "land", float(t.area[a + i])))
    return ev


SKIP_CAT = ("whoosh", "riser", "swell", "drone", "ambience", "amb", "music", "sweep", "rise", "reverse", "bed", "tension")


def rule_sfx(tracks, cuts, cues):
    out = []
    if not cues:
        return out
    ev = visual_events(tracks, cuts)
    evf = sorted(ev)
    W = TUNE["sfx_window_frames"]; tol = TUNE["sfx_tol_frames"]
    import bisect
    fl = [e[0] for e in evf]
    for c in cues:
        cat = str(c.get("category") or c.get("sfx_id") or "")
        if any(s in cat.lower() for s in SKIP_CAT):
            continue
        tt = c.get("event_t", c.get("t"))
        if tt is None:
            continue
        f = tt * FPS
        lo, hi = bisect.bisect_left(fl, f - W), bisect.bisect_right(fl, f + W)
        near = evf[lo:hi]
        if not near:
            continue
        best = min(near, key=lambda e: abs(e[0] - f))
        d = best[0] - f
        if abs(d) > tol + 0.01:
            out.append(Finding("sfx", "WARN", int(round(f)), int(round(f)), "cue %s at %.2fs is %+.1f frames from the nearest visual event (%s at %.2fs)" % (cat, tt, d, best[1], best[0] / FPS), None, "", {"cue": cat, "offset_frames": round(d, 1)}))
    return out


def cluster(findings):
    """One defect per (rule, kind, frame): the sub-elements of a card that pops together are ONE pop. Keeps the worst severity and names the biggest elements."""
    groups = {}
    order = []
    for f in findings:
        sub = "cutjump" if f.extra.get("cutjump") else ("exit" if f.extra.get("exit") else f.msg.split(" ")[0])
        key = (f.rule, sub, f.f0, f.part) if f.rule in ("pop", "cutjump", "flicker", "snap", "easing", "jitter") else (id(f),)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(f)
    out = []
    for key in order:
        g = groups[key]
        if len(g) == 1:
            out.append(g[0]); continue
        def sz(f):
            i = f.track.i(f.f0) if f.track is not None else None
            return float(f.track.area[i]) if i is not None else 0.0
        g.sort(key=lambda x: (0 if x.sev == "FAIL" else 1, -sz(x)))
        top = g[0]
        sev = "FAIL" if any(x.sev == "FAIL" for x in g) else "WARN"
        names = ", ".join(("'%s'" % x.track.text[:18]) if x.track.text else x.track.label for x in g[:3])
        nf = Finding(top.rule, sev, min(x.f0 for x in g), max(x.f1 for x in g), "%s  [+%d more at the same frame: %s]" % (top.msg, len(g) - 1, names), top.track, top.part, dict(top.extra, n=len(g)))
        out.append(nf)
    return out


# ------------------------------------------------------------------------------------------------- judge
def judge(raw, beats, cues, only=None, tune=None, get_image=None):
    if tune:
        TUNE.update(tune)
    tracks = load_tracks(raw)
    cuts = scene_cut_frames(tracks)
    beats_f = [int(round(b["from"] * FPS)) for b in beats]
    want = lambda r: not only or r in only
    out = []
    if want("universal"):
        out += rule_universal(tracks, cuts, beats_f)
    if want("pop") or want("cutjump"):
        out += [f for f in rule_pop(tracks, cuts, beats_f) if want(f.rule)]
    if want("flicker"):
        out += rule_flicker(tracks, cuts, beats_f)
    if want("jitter"):
        out += rule_jitter(tracks, cuts, beats_f)
    if want("snap") or want("easing"):
        r = rule_snap_ease(tracks, cuts, beats_f) + (rule_glitch(tracks, cuts, beats_f) if want("snap") else [])
        out += [f for f in r if want(f.rule)]
    if want("overlap"):
        out += rule_overlap(tracks, cuts, beats_f)
    if want("edge"):
        out += rule_edge(tracks, cuts, beats_f)
    if want("widow"):
        out += rule_widow(tracks)
    if want("drift"):
        out += rule_drift(tracks, cuts, beats_f)
    if want("zflip"):
        out += rule_zflip(tracks)
    if want("distort"):
        out += rule_distort(tracks)
    if want("colour"):
        out += rule_colour(tracks, cuts, beats_f)
    if want("overlap"):
        out += rule_overlap_obj(tracks, cuts, beats_f)
        out += rule_touch(tracks, cuts, beats_f)
    if (want("style") or want("typescale")):
        out += [f for f in rule_style(tracks) if want(f.rule)]
    if want("cropcut") and get_image is not None:
        out += rule_cropcut(tracks, get_image)
    if want("sfx"):
        out += rule_sfx(tracks, cuts, cues)
    out = cluster(out)
    # one finding per (rule, frame, geometry): duplicated sub-elements of one object are one defect
    seen, uniq = set(), []
    for f in sorted(out, key=lambda f: (f.f0, f.rule)):
        box = f.as_json().get("box")
        key = (f.rule, f.f0, f.msg.split(" ")[0], tuple(round(v / 6) for v in box) if box else None, f.part)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    return uniq, {"tracks": len(tracks), "scene_cuts": sorted(cuts), "frames": sum(len(d["frames"]) for d in raw["parts"].values())}


def make_image_getter(bd):
    """get_image(src) -> PIL image from the package's own source.tar.gz (the files the page loaded), cached; None if absent"""
    import tarfile, io
    tarp = os.path.join(bd, "source.tar.gz")
    if not os.path.exists(tarp):
        return lambda src: None
    tf = tarfile.open(tarp)
    index = {}
    for m in tf.getmembers():
        if m.isreg() and m.name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            index.setdefault(m.name.split("/", 1)[-1], m)
    cache = {}

    def get(src):
        if not src:
            return None
        if src in cache:
            return cache[src]
        m = index.get(src)
        if m is None:
            for k, v in index.items():
                if k.endswith(src) or src.endswith(k):
                    m = v; break
        im = None
        if m is not None:
            from PIL import Image
            im = Image.open(io.BytesIO(tf.extractfile(m).read()))
            im.load()
        cache[src] = im
        return im
    return get


# ------------------------------------------------------------------------------------------------- main
def summarise(findings, label):
    import collections
    c = collections.Counter((f.rule, f.sev) for f in findings)
    return "%s: %s" % (label, ", ".join("%s %s %d" % (r, s, n) for (r, s), n in sorted(c.items())) or "no findings")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("id")
    ap.add_argument("--build-dir")
    ap.add_argument("--backend", default=os.environ.get("POLISH_BACKEND", "actions"), choices=("actions", "local"))
    ap.add_argument("--raw", help="re-judge a saved raw JSON (or .gz): no browser, no network")
    ap.add_argument("--release", help="snap-<id>-<sha16>: run on an archived package release instead of the current build")
    ap.add_argument("--json", help="write the findings here")
    ap.add_argument("--from", dest="t_from", type=float, default=0.0)
    ap.add_argument("--to", dest="t_to", type=float, default=99999.0)
    ap.add_argument("--only", help="comma list of rules: " + ",".join(RULES))
    ap.add_argument("--tune", help="JSON file of TUNE overrides")
    ap.add_argument("--strict", action="store_true", help="WARN counts as FAIL (exit 1)")
    ap.add_argument("--universal", choices=["auto", "fail", "warn"], default="auto", help="level of the universal-safe-zone rule: auto = FAIL for shorts claimed after universal.json live_from, WARN for in-flight ones")
    ap.add_argument("--quiet", action="store_true", help="print only the summary and FAIL lines")
    ap.add_argument("--info", action="store_true", help="also print INFO lines (hard-on entrances, counted but not defects)")
    a = ap.parse_args()
    out, bd, parts, beats, cues = load_build(a.id, a.build_dir)
    rawp = a.raw or os.path.join(out, "polish", "raw.json")
    if not a.raw:
        os.makedirs(os.path.dirname(rawp), exist_ok=True)
        if a.backend == "local":
            tmpl = None
            root = tempfile.mkdtemp(prefix="agmm-polish-pkg-")
            import tarfile
            try:
                with tarfile.open(os.path.join(bd, "source.tar.gz")) as tf:
                    tf.extractall(root)
                run_local(root, [{"look": p["look"], "part": p["out"], "off": p["off"], "dur": p["dur"]} for p in parts], rawp, a.t_from, a.t_to)
            finally:
                shutil.rmtree(root, ignore_errors=True)
        else:
            try:
                run_actions(a.id, bd, parts, rawp, a.t_from, a.t_to, a.release)
            except RuntimeError as e:
                tool_error(str(e))
    op = gzip.open if rawp.endswith(".gz") else open
    with op(rawp, "rt") as fh:
        raw = json.load(fh)
    only = set(a.only.split(",")) if a.only else None
    tune = json.load(open(a.tune)) if a.tune else None
    global UNIVERSAL_LEVEL
    import universal
    UNIVERSAL_LEVEL = {"fail": "FAIL", "warn": "WARN"}.get(a.universal) or universal.level(a.id)
    findings, info = judge(raw, beats, cues, only, tune, make_image_getter(bd))
    if not beats:
        log("no beats found: seam exemptions fall back to the DOM scene cuts only")
    nfail = sum(1 for f in findings if f.sev == "FAIL")
    for f in findings:
        if (a.quiet and f.sev != "FAIL") or (f.sev == "INFO" and not a.info):
            continue
        print(f.line())
    print(summarise(findings, "polish_check %s (%d tracks, %d frames, %d scene cuts)" % (a.id, info["tracks"], info["frames"], len(info["scene_cuts"]))))
    nwarn = sum(1 for f in findings if f.sev == "WARN")
    print("RESULT %s  FAIL=%d WARN=%d INFO=%d" % ("FAIL" if nfail or (a.strict and nwarn) else "PASS", nfail, nwarn, sum(1 for f in findings if f.sev == "INFO")))
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        json.dump({"id": a.id, "info": info, "findings": [f.as_json() for f in findings], "tune": TUNE}, open(a.json, "w"), indent=1)
    raise SystemExit(1 if (nfail or (a.strict and nwarn)) else 0)


if __name__ == "__main__":
    main()
