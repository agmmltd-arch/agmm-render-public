#!/usr/bin/env python3
"""precheck_all.py <ID> [--platform P] [--only a,b] [--skip a,b] [--no-cache] [--keep-going] [--final] [--json] [--no-build]
(kit/ maker kit v3, 13 Oct 2026: one command instead of ~12 hand-run checks)

Runs every pre-submit check a maker used to run by hand, in the right order and in parallel where it is safe, and prints ONE table of
FAILs with the time in the short, the rule, the detail and the exact fix hint. Exit 0 = every check passed, 1 = at least one FAIL,
2 = no FAIL but a check could not run (tool error). Nothing here renders anything on the Mac: the browser halves run on GitHub Actions
inside the owning tools; the only local jobs (build, voice_lead_check) go through tools/heavy.py.

Order (the dependency graph, not a preference):
  concept        concept_check.py            1 s, no build. A FAIL stops the run (changing the world means a rebuild anyway) unless --keep-going.
  build          produce.py <ID> --only build via heavy.py (its own BUILD LANE of AGMM_BUILD_SLOTS=3, 13 Oct: no longer queues behind voice/whisper jobs on the general slots);
                 skipped when storyboard.stale_build says the package is current.
  voice          voice_lead_check.py via heavy.py, ONLY if the take is newer than <ID>.voicelead.json; otherwise the existing verdict is read.
  dom_lint       } both are Actions workflows of their own, so they run in PARALLEL with each other and with the snap chain
  polish_check   }
  static         static_precheck.py (10 fps snaps, Actions; 13 Oct: split into up to 8 parallel contiguous snap calls with overlap, limited to half the free hosted slots; AGMM_STATIC_SPLIT=1 = one call). Then the frame check: frame_precheck's own OCR + platform + text-lint rules run over the
                 2 s grid frames static just snapped (no second cloud snap; validated identical to frame_precheck.py on S92 0/0 and S25 0 FAIL/75 WARN).
                 --real-frame runs frame_precheck.py itself instead (own snap; chained after static, never parallel: they share out/<ID>/snap and static
                 selects frames by mtime, so it would read the other's frames as duplicates)
  sheet          sheet_check.py, after dom_lint (HERO/SOURCE read domlint/raw.json) and static (the beat-middle frames come from its snaps)
  btl            better_than_last.py --strict, after the snaps (frame density reads out/<ID>/snap)

Cache (out/<ID>/precheck/cache.json): a check is skipped when its inputs are byte-identical to the last run (package sha256 from
build/parts.json, plus lint-exceptions.json / platform where the check reads them). A cached FAIL is printed again with the time it was
found, so a re-run after an unrelated fix does not spend a cloud run to learn what it already knew. concept and btl are never cached (cheap, and
the approved window moves). --no-cache forces everything. Tool errors are never cached.

--final  adds --refresh to better_than_last (recompute the window now: "strict window moves", run it immediately before submit).
Output files: out/<ID>/precheck/<check>.log (full tool output), cache.json, last.json (the table as data), beats.jpg (mid-beat contact sheet for the LOOK).
"""
import argparse, concurrent.futures as cf, datetime, glob, hashlib, json, os, re, shutil, subprocess, sys, threading, time

TOOLS = os.path.dirname(os.path.abspath(__file__))
KIT = os.environ.get("PRECHECK_KIT") or os.path.dirname(TOOLS)
V2 = os.path.dirname(KIT)
PY = sys.executable
YT_PY = os.environ.get("PRECHECK_YT_PY") or os.path.expanduser("~/alfred/yt-engine/.venv/bin/python")
UNIVERSAL_RULE = "u1"   # bump when kit/platforms/universal.py changes what dom_lint / polish_check report, so cached results are not reused
ORDER = ["concept", "build", "voice", "frame", "dom_lint", "polish", "static", "sheet", "btl"]

# ---------------------------------------------------------------------------------------------------- fix hints (one per rule)
HINTS = {
    "concept": {
        "_": "python3 tools/concept_check.py --suggest <ID> shows the classes free NOW (approved + reserved by makers in flight); change the WORLD (ground, hero device, source treatment: differ on 2 of the 4 house-look axes), rewrite specs/<ID>/concept.json; a teal/petrol ground is still 'dark navy' to R3/R4",
        "R0": "fix concept.json schema/enums; bed must equal spec.json music.bed; ground hex must match its luminance class",
        "R1": "differ from EACH of the last 10 approved on >= 3 of 7 axes (world, ground, hero device, hook, signature, camera, source presentation)",
        "R2": "pick a dominant palette hue shared with at most 2 of the last 10",
        "R3": "ground must leave the dark navy/charcoal bucket (pale paper, warm or mid-tone) while 3+ of the last 10 approved + live reservations are dark; concept_check --suggest <ID> lists free grounds",
        "R4": "of {dark navy ground, giant-number hero, mono kicker, cream-card sources} match at most 2: change the hero device and the source treatment",
        "R5": "choose another music bed (not in 3+ of the last 10)",
        "R6": "better_than_last.short must be one of the last 10 approved and really differ from it on the named axis",
        "R7": "pitch: frame 0 names a subject + a number the script speaks; >= 8 constructed objects each tied to a spoken word; every figure sentence has a claim (outlet, date, url)",
    },
    "build": {"_": "read out/<ID>/precheck/build.log; a scene that throws or an unresolved @word fails the build loudly; images need backend auto"},
    "voice": {
        "_": "re-chunk the failing paragraph at SENTENCE boundaries (same words), re-voice only it (revoice.py), re-point @word anchors, rebuild; ASR-TRIAGE only via triage_store.py",
        "pace": "RUSHED = >= 6.7 syl/s AND >= 190 script wpm: re-voice that paragraph in sentence chunks near 168 wpm; CTA FAIL at 210+ wpm (S52's is 120)",
        "cta": "banned CTA 'Follow, we track this every week.': use a full sentence ('Follow for the next real story.'), change script last line AND the on-screen CTA, re-voice P(last) only",
        "name": "a name the ASR spells differently (homophone) is a spelling matter: fix names.txt tokens (e.g. \"Replit's\") or triage CLEAN via triage_store; do not loop re-voices",
        "suspect": "both transcribers miss the script: reword the script text for the ASR (e.g. 'Allen & Overy'), regenerate source.json with prepare.py, or re-voice the paragraph",
        "stale": "voicelead.json is older than the take: run voice_lead_check (this tool does it)",
    },
    "frame": {
        "text-lint": "no ' - ' or em dash, no AI-tell words in OUR text: reword. A publisher's own dash inside a real source crop: add the exact OCR line to out/<ID>/lint-exceptions.json {\"lint\":[{\"text\":\"..\",\"reason\":\"source crop: <outlet>\"}]} (autofix.py validates the file)",
        "outside_visible": "move the text >= 60 px inside the routed platform's visible rect, at the END of the beat's camera move too; a credit outside the rect is a FAIL for the reviewer",
        "under_overlay": "text sits under the platform UI (caption/rail): lift it above the overlay zone, cap widths at the rail edge; pass --platform if the short is unrouted",
        "_": "reposition the named text inside the routed platform's safe rect; re-check every beat the moved object is on (frame_precheck --at)",
    },
    "dom_lint": {
        "legibility": "type under 42 px (source-card image text under 37): show only the spoken clause on a >= 770 px card, re-crop with crop_clause (>= 48 px), raise type to 42+, delete tiny mono kicker / ILLUSTRATION chips",
        "frame": "text box cut by the platform rect or under an overlay >= 0.3 s: move it inside (60 px at the end of the beat), unrouted shorts are judged as Instagram",
        "stacked": "two strings overlap: bring the outgoing text carrier to opacity 0 (AGP.motion.exit) before the next enters, make semi-transparent slabs opaque, 40 px between a chip and the headline",
        "empty-on-cut": "the cut frame has no text/object: land the beat's FULL composition on the cut (opaque from the first frame, <= 26 px offset, no opacity-0 headline waiting for a word)",
        "text-lint": "no dash/AI-tell/banned CTA in our text: reword; a publisher's own dash in a source crop goes in out/<ID>/lint-exceptions.json with the EXACT line",
        "_": "see dom_lint.py docstring for the rule; JSON in out/<ID>/domlint/result.json",
    },
    "polish": {
        "pop": "AGP.motion.enter(ctx, el, t, {from:...}) / AGP.motion.exit(ctx, el, t): nothing appears or leaves in ONE frame mid-beat",
        "flicker": "do not set opacity 1 then 0 inside 3 frames; a mark that must flash uses enter + exit",
        "jitter": "no per-frame Math.round on left/top; float with sine.inOut, never a per-frame random",
        "snap": "tween it (AGP.motion.enter/swap) or split the move over 8+ frames",
        "easing": "never ease:'none' on an entrance; AGP.motion.EASE_IN (power3.out) arriving, EASE_OUT leaving, 6-10 frames",
        "edge": "overshoot clipped by the frame edge: slams at most 1.1x, anchored top-left (transformOrigin 0% 0%), 60 px inside the frame",
        "overlap": "text colliding with text for a few frames: stagger, or exit the first before the second enters",
        "distort": "an <img> drawn at the wrong aspect: give it width AND height from its natural ratio or object-fit:contain; after a crop_clause --install copy specs/<ID>/media/clauses/<key>.png over media/<ID>/final/real-<id>-<key>.png (python3 tools/autofix.py <ID> does this)",
        "cutjump": "a carried object steps at the beat cut: AGP.motion.carry(prev) gives the next camera the transform the last one ended on",
        "widow": "AGP.motion.widow(el) glues the last two words (autofix.py does it for string literals)",
        "_": "AGP.motion in kit/lib/prologue.js has the standard entrance/exit/swap/carry set; see kit/tools/polish_check.py docstring",
    },
    "static": {
        "_": "no span over 1.5 s without motion (gate check 3, 0.4% floor): give the beat a LARGE word-tied event (a card dropping 400 px, a 130 px stamp, a camera push); on light paper worlds add a handheld float (two sines per axis, ~20 px, via left/top). Re-run after any cutjump fix: it can unmask a static span",
    },
    "sheet": {
        "VARIETY": "beats look like one picture seen again: give each beat its OWN constructed prop at its own position and colour",
        "BACKDROP": "the same disc/badge silhouette behind the subject on > half the beats: vary the backdrop",
        "LONE": "one object on a bare ground: add a persistent world or texture to the beat",
        "FILL": "empty beat: the subject must fill >= 60% of the frame from the cut; scale the object up rather than widening the set",
        "HERO": "hook beat needs a hero line >= the HOOK_HERO_PX; most beats need a large line",
        "SOURCE": "source-card text too small: crop to the spoken clause and widen the card (>= 48 px)",
        "OCCUPANCY": "engine short: flat empty colour fills the frame (content in the top 40%): the world map, an object at picture scale and the headline must fill every beat (sheet_occupancy.py)",
        "DISTINCT": "engine short: neighbouring beats share one layout: each beat needs its own object in its own place (sheet_occupancy.py)",
        "SCALE": "engine short: no beat has an element the size of the picture: scale the object up",
        "_": "python3 tools/sheet_check.py <ID> names the beats; fix those beats",
    },
    "btl": {
        "_": "lift the BEHIND metric (never the tool): beats/min (split at a new OBJECT), longest beat, density, cue pan share (every cue's x = its object's x; centred x 470..590 does not count: use 330/760), cues/min <= 60 distinct, sound bed LU",
        "beats_per_min": "plan 21-22 beats in a 56 s short: split the longest beat at a clause, each half its own object",
        "beat_len_max_s": "split the longest beat (often the CTA: headline beat `ctah` + link-card beat `cta`, each under ~4.3 s)",
        "cue_pan_share": "give every authored sfx an 'x' (its object's place on screen); centred cues (x 470..590) count as unpanned; python3 tools/autofix.py <ID> lists them",
        "cues_per_min": "one designed sound per on-screen event; never pad with companion cues; ceiling ~60 distinct events/min",
    },
}


def hint_for(check, rule, text=""):
    h = HINTS.get(check, {})
    if rule and rule in h:
        return h[rule]
    low = (rule + " " + text).lower()
    for k, v in h.items():
        if k != "_" and k.lower() in low:
            return v
    return h.get("_", "")


# ---------------------------------------------------------------------------------------------------- helpers
def sha(path_or_bytes):
    if isinstance(path_or_bytes, bytes):
        return hashlib.sha256(path_or_bytes).hexdigest()[:16]
    try:
        return hashlib.sha256(open(path_or_bytes, "rb").read()).hexdigest()[:16]
    except OSError:
        return "-"


def now():
    return datetime.datetime.now().strftime("%H:%M:%S")


def stamp(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")


class Ctx:
    def __init__(self, a):
        self.id = a.id
        self.a = a
        self.out = os.path.join(KIT, "out", a.id)
        self.pdir = os.path.join(self.out, "precheck")
        os.makedirs(self.pdir, exist_ok=True)
        self.cache_p = os.path.join(self.pdir, "cache.json")
        try:
            self.cache = json.load(open(self.cache_p))
        except (OSError, ValueError):
            self.cache = {}
        self.lock = threading.Lock()
        self.results = {}

    # -- inputs the cache keys are made of
    def pkg(self):
        try:
            return json.load(open(os.path.join(self.out, "build", "parts.json"))).get("sha256") or "-"
        except (OSError, ValueError):
            return "-"

    def lintexc(self):
        return sha(os.path.join(self.out, "lint-exceptions.json"))

    def key(self, check):
        p = self.pkg()
        base = "pkg:%s" % p
        if check == "dom_lint":
            return "%s|lx:%s|pf:%s|uz:%s" % (base, self.lintexc(), self.a.platform or "", UNIVERSAL_RULE)   # a cached result from before the universal rule has no such lines
        if check == "frame":
            return "%s|lx:%s|pf:%s" % (base, self.lintexc(), self.a.platform or "")
        if check == "polish":
            return base + "|uz:" + UNIVERSAL_RULE
        if check == "static":
            import static_precheck
            return base + "|checker:" + static_precheck.checker_version()
        if check == "sheet":
            return "%s|dom:%s" % (base, sha(os.path.join(self.out, "domlint", "raw.json")))
        return None

    def save(self):
        with self.lock:
            tmp = self.cache_p + ".tmp"
            json.dump(self.cache, open(tmp, "w"), indent=1)
            os.replace(tmp, self.cache_p)


def run_cmd(cmd, log, cwd=KIT, env=None, timeout=3300):
    """-> (rc, seconds, text). The full output is written to `log`."""
    t0 = time.time()
    e = dict(os.environ)
    e.update(env or {})
    try:
        p = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, timeout=timeout)
        rc, text = p.returncode, (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr.strip() else "")
    except subprocess.TimeoutExpired as ex:
        rc, text = 124, "TIMEOUT after %ds\n%s" % (timeout, (ex.stdout or b"")[-2000:] if isinstance(ex.stdout, bytes) else (ex.stdout or ""))
    except OSError as ex:
        rc, text = 127, "cannot run %s: %s" % (cmd[0], ex)
    open(log, "w").write("$ %s\n(rc %s, %.0fs)\n%s" % (" ".join(cmd), rc, time.time() - t0, text))
    return rc, time.time() - t0, text


T_RX = re.compile(r"(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?s\b")


def when_of(line):
    m = T_RX.search(line)
    if not m:
        return "-"
    return "%ss" % m.group(1) if not m.group(2) else "%s-%ss" % (m.group(1), m.group(2))


def parse_findings(check, text):
    """-> list of {when, rule, detail, line, sev}. FAIL lines only (and WARN count separately)."""
    fails, warns = [], 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        sev = None
        if re.match(r"^FAIL\b", line):
            sev = "FAIL"
        elif re.match(r"^WARN\b", line):
            warns += 1
            continue
        elif check in ("sheet",) and line.startswith("FAIL "):
            sev = "FAIL"
        if not sev:
            continue
        body = line[4:].strip()
        rule, detail = "", body
        if check == "dom_lint":     # FAIL 10.60-13.00s legibility A 0.00 | 32.9 px < 42 ... | img[..]
            m = re.match(r"^([\d.]+(?:-[\d.]+)?s)\s+(\S+)\s+\S+\s+[\d.]+\s*\|\s*(.*)$", body)
            if m:
                rule, detail = m.group(2), m.group(3)
        elif check == "polish":     # FAIL  12.30- 12.50s pop  | msg ...
            m = re.match(r"^([\d.]+)-\s*([\d.]+)s\s+(\S+)\s+(.*)$", body)
            if m:
                rule, detail = m.group(3), m.group(4)
        elif check == "frame":      # FAIL   12.5s outside_visible detail | text
            m = re.match(r"^([\d.]+)s\s+(\S+)\s+(.*)$", body)
            if m:
                rule, detail = m.group(2), m.group(3)
        fails.append({"when": when_of(line), "rule": rule, "detail": re.sub(r"\s+", " ", detail)[:150], "line": line[:300]})
    seen, uniq = set(), []          # dom_lint prints one row per run of identical samples; two rows with the same text are one defect
    for f in fails:
        k = (f["when"], f["rule"], f["detail"])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq, warns


# ---------------------------------------------------------------------------------------------------- the checks
def result(check, status, secs=0.0, fails=None, warns=0, note="", cached=None, log=None, rc=None):
    return {"check": check, "status": status, "secs": round(secs, 1), "fails": fails or [], "warns": warns, "note": note,
            "cached_at": cached, "log": log, "rc": rc, "at": time.time()}


def tool_check(ctx, check, cmd, env=None, cacheable=True, ok_rcs=(0,), fail_rcs=(1,), extra_parse=None):
    log = os.path.join(ctx.pdir, check + ".log")
    key = ctx.key(check) if cacheable and not ctx.a.no_cache else None
    if key:
        c = ctx.cache.get(check)
        if c and c.get("key") == key and c.get("status") in ("PASS", "FAIL"):
            r = dict(c["res"])
            r["cached_at"] = stamp(c["res"]["at"])
            r["secs"] = 0.0
            return r
    rc, secs, text = run_cmd(cmd, log, env=env)
    if extra_parse:
        fails, warns, status_override = extra_parse(text, rc)
    else:
        fails, warns = parse_findings(check, text)
        status_override = None
    if status_override:
        status = status_override
    elif rc in ok_rcs and not fails:
        status = "PASS"
    elif rc in fail_rcs or fails:
        status = "FAIL"
    else:
        status = "ERROR"
    if status == "FAIL" and not fails:
        tail = [l for l in text.splitlines() if l.strip()][-1:] or ["(no output)"]
        fails = [{"when": "-", "rule": "", "detail": tail[0][:150], "line": tail[0]}]
    note = ""
    if status == "ERROR":
        note = [l for l in text.splitlines() if l.strip()][-1:][0][:160] if text.strip() else "rc %s" % rc
    res = result(check, status, secs, fails, warns, note=note, log=log, rc=rc)
    if key and status in ("PASS", "FAIL"):
        ctx.cache[check] = {"key": key, "status": status, "res": res}
        ctx.save()
    return res


def concept_card_refusal(ID):
    sys.path.insert(0, TOOLS)
    import concept_card
    ok, why = concept_card.gate_ok(ID)
    return None if ok else why


def step_concept(ctx):
    why = concept_card_refusal(ctx.id)
    if why:
        return result("concept", "FAIL", fails=[{"when": "-", "rule": "CARD", "detail": why, "line": why}], note=why)
    def parse(text, rc):
        fails = []
        for l in text.splitlines():
            m = re.match(r"^\s*\[FAIL\]\s*(R\d)\s+(.*)$", l)
            if m:
                fails.append({"when": "-", "rule": m.group(1), "detail": re.sub(r"\s+", " ", m.group(2).strip())[:150], "line": l.strip()})
        if rc == 1 and not fails:
            fails = [{"when": "-", "rule": "", "detail": [x for x in text.splitlines() if x.strip()][-1][:150], "line": ""}]
        return fails, sum(1 for l in text.splitlines() if "[WARN]" in l), None
    return tool_check(ctx, "concept", [PY, "tools/concept_check.py", ctx.id], cacheable=False, extra_parse=parse)


MAX_SHORT_S = 59.85     # gate check 7 PASS band ends at 60.0 s; the encode adds up to ~0.05 s


def step_build(ctx):
    """root 13 Oct: the build also owns the duration. S69 (60.9 s) and S72 (60.6 s) were approved, rendered on Actions and
    gated before check 7's 60-90 s WARN blocked them from arming (arming takes overall PASS only). Catch it before submit."""
    why = concept_card_refusal(ctx.id)
    if why:
        return result("build", "FAIL", fails=[{"when": "-", "rule": "CARD", "detail": why, "line": why}], note=why)
    r = _step_build_core(ctx)
    if r.get("status") not in ("PASS", "SKIP"):
        return r
    try:
        dur = float(json.load(open(os.path.join(ctx.out, "BUILD.json"))).get("dur"))
    except Exception:
        return r
    if dur > MAX_SHORT_S:
        line = "built duration %.2f s > %.2f s: gate check 7 will WARN (60-90 s band) and arming refuses it; trim the end hold or dead air, never time-stretch" % (dur, MAX_SHORT_S)
        return result("build", "FAIL", r.get("secs") or 0.0, note=line, fails=[{"when": "-", "rule": "duration", "detail": line, "line": line}])
    r["note"] = (r.get("note") or "") + "; %.2f s" % dur
    return r


def _step_build_core(ctx):
    log = os.path.join(ctx.pdir, "build.log")
    sys.path.insert(0, TOOLS)
    why = None
    try:
        if os.environ.get("PRECHECK_KIT"):
            raise ImportError("test kit: use the mtime rule below")
        import storyboard
        why = storyboard.stale_build(ctx.id)
    except Exception as e:      # storyboard import pulls numpy etc.; fall back to the same mtime rule (storyboard.stale_build)
        spec = os.path.join(KIT, "specs", ctx.id)
        res = os.path.join(ctx.out, "resolved.json")
        if not os.path.exists(res) or not os.path.exists(os.path.join(ctx.out, "build", "parts.json")):
            why = "no build yet"
        else:
            newest = max([os.path.getmtime(f) for f in glob.glob(os.path.join(spec, "*")) if os.path.isfile(f) and f.endswith((".json", ".js", ".css"))
                          and os.path.basename(f) != "concept.json"] or [0])
            why = "specs changed after the last build" if newest > os.path.getmtime(res) + 1 else None
    if not os.path.exists(os.path.join(ctx.out, "build", "parts.json")):
        why = why or "no package (out/%s/build/parts.json)" % ctx.id
    if ctx.a.no_build:
        return result("build", "SKIP" if not why else "FAIL", note="--no-build" if not why else "stale/missing package and --no-build: %s" % why,
                      fails=[] if not why else [{"when": "-", "rule": "", "detail": why, "line": why}])
    if not why:
        return result("build", "PASS", note="package current (%s, built %s)" % (ctx.pkg()[:8], stamp(os.path.getmtime(os.path.join(ctx.out, "build", "parts.json")))))
    rc, secs, text = run_cmd([PY, os.path.join(KIT, "tools", "heavy.py"), "--", PY, "produce.py", ctx.id, "--only", "build"], log, timeout=3000)
    ok = rc == 0 and os.path.exists(os.path.join(ctx.out, "build", "parts.json"))
    if ok:
        return result("build", "PASS", secs, note="rebuilt (%s): %s" % (why, ctx.pkg()[:8]), log=log, rc=rc)
    last = [l for l in text.splitlines() if l.strip()][-3:]
    return result("build", "FAIL", secs, fails=[{"when": "-", "rule": "", "detail": " | ".join(last)[:150], "line": " | ".join(last)}], log=log, rc=rc)


def step_voice(ctx):
    sys.path.insert(0, os.path.join(V2, "shorts", "voice", "tooling"))
    from prepare import voicelead_prerequisite_issues, voicelead_input_mtime, voicelead_runtime_issue
    issues = voicelead_prerequisite_issues(os.path.join(V2, "shorts", "voice"), ctx.id)
    if issues:
        return result("voice", "FAIL", fails=[{"when": "-", "rule": "prerequisite", "detail": s, "line": s} for s in issues])
    vdir = os.path.join(V2, "shorts", "voice", ctx.id)
    vl = os.path.join(vdir, ctx.id + ".voicelead.json")
    takes = [os.path.join(vdir, ctx.id + ".wav"), os.path.join(vdir, ctx.id + ".words.json")] + glob.glob(os.path.join(vdir, "P*.wav"))
    takes = [t for t in takes if os.path.exists(t)]
    if not takes:
        return result("voice", "FAIL", fails=[{"when": "-", "rule": "stale", "detail": "no voice take in shorts/voice/%s" % ctx.id, "line": ""}])
    newest = voicelead_input_mtime(os.path.join(V2, "shorts", "voice"), ctx.id)
    log = os.path.join(ctx.pdir, "voice.log")
    ran = False
    secs = 0.0
    if (not os.path.exists(vl)) or os.path.getmtime(vl) < newest or ctx.a.no_cache:
        if why := voicelead_runtime_issue():
            return result("voice", "FAIL", fails=[{"when": "-", "rule": "hosted", "detail": why, "line": why}])
        env = {"HEAVY_MAX_S": "900"}
        for attempt in (1, 2):      # voice_lead_check can hang on a dead socket while holding a slot: heavy.py stops it at 900 s, retry once
            rc, s, text = run_cmd([PY, os.path.join(KIT, "tools", "heavy.py"), "--", YT_PY, "shorts/voice/tooling/voice_lead_check.py", "shorts/voice", ctx.id],
                                  log, cwd=V2, env=env, timeout=2400)
            secs += s
            if rc != 124:
                break
        ran = True
    if not os.path.exists(vl):
        return result("voice", "ERROR", secs, note="voice_lead_check wrote no voicelead.json (see %s)" % log, log=log)
    d = json.load(open(vl))
    fails = []
    for f in d.get("fails", []):
        s = str(f)
        low = s.lower()
        rule = ("pace" if ("wpm" in low or "syl" in low or "rush" in low) else "cta" if "cta" in low else "name" if "name" in low
                else "suspect" if "suspect" in low or "asr" in low else "")
        pm = re.search(r"\bP\d\d\b", s)
        fails.append({"when": pm.group(0) if pm else "-", "rule": rule, "detail": re.sub(r"\s+", " ", s)[:150], "line": s[:300]})
    warns = len(d.get("warns", []))
    status = "FAIL" if (d.get("verdict") != "PASS" or fails) else "PASS"
    if status == "FAIL" and not fails:
        fails = [{"when": "-", "rule": "", "detail": "verdict %s" % d.get("verdict"), "line": ""}]
    note = "voicelead.json %s (%s)" % (d.get("verdict"), stamp(os.path.getmtime(vl)))
    return result("voice", status, secs, fails, warns, note=note + ("" if ran else ", take not newer: not re-run"),
                  cached=None if ran else stamp(os.path.getmtime(vl)), log=log if ran else vl)


def step_dom_lint(ctx):
    cmd = [PY, "tools/dom_lint.py", ctx.id] + (["--platform", ctx.a.platform] if ctx.a.platform else [])
    return tool_check(ctx, "dom_lint", cmd)


def step_polish(ctx):
    return tool_check(ctx, "polish", [PY, "tools/polish_check.py", ctx.id])


def archive_stale_snaps(ctx):
    """snap frames older than the current package describe a build that no longer exists (sheet_check, better_than_last and the maker's own eyes
    would read them). Move them (never delete) to out/<ID>/snap-archive-<stamp>/."""
    pj = os.path.join(ctx.out, "build", "parts.json")
    if not os.path.exists(pj):
        return 0
    cut = os.path.getmtime(pj)
    old = [f for f in glob.glob(os.path.join(ctx.out, "snap", "**", "frame-*"), recursive=True) if os.path.isfile(f) and os.path.getmtime(f) < cut]
    if not old:
        return 0
    dest = os.path.join(ctx.out, "snap-archive-%s" % time.strftime("%Y%m%d-%H%M%S"))
    for f in old:
        rel = os.path.relpath(f, os.path.join(ctx.out, "snap"))
        os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
        shutil.move(f, os.path.join(dest, rel))
    # root 13 Oct: every precheck left another ~300 MB snap-archive behind (25 dirs, 5.6 GB in one day) and the disk filled.
    # Frames of superseded builds are only useful one step back, so keep the newest archive and drop the older ones.
    for stale in sorted(glob.glob(os.path.join(ctx.out, "snap-archive-*")))[:-1]:
        shutil.rmtree(stale, ignore_errors=True)
    return len(old)


def frame_from_static_snaps(ctx):
    """frame_precheck's work WITHOUT its own cloud snap: static_precheck has just snapped every 0.1 s of the short, so the 2 s grid frame_precheck
    wants (story times 0.5, 2.5, ...) is already on disk. Same OCR (tools/ocr_vision), same rules (platforms.box_problems, the gate's lint_text,
    lint-exceptions.json), same output lines. Returns None when any wanted frame is missing, so the caller falls back to the real tool."""
    parts_p = os.path.join(ctx.out, "build", "parts.json")
    try:
        parts = json.load(open(parts_p))["parts"]
        sys.path.insert(0, os.path.join(KIT, "platforms"))
        sys.path.insert(0, os.path.join(V2, "qa"))
        import platforms
        import gate as _gate
    except Exception:
        return None
    tot = sum(float(p["dur"]) for p in parts)
    step = 2.0
    wanted = [round(0.5 + i * step, 2) for i in range(int(max(tot - 0.6, 0) / step) + 1)]
    frames = {}
    for pt in parts:
        for f in glob.glob(os.path.join(ctx.out, "snap", pt["out"], "frame-*-at-*s.jpg")):
            m = re.search(r"-at-([\d.]+)s\.jpg$", f)
            if m:
                a = float(pt["off"]) + float(m.group(1))
                if os.path.getmtime(f) >= os.path.getmtime(parts_p):
                    frames.setdefault(round(a * 10), (f, pt["out"], m.group(1)))
    shots = []
    for t in wanted:
        k = round(t * 10)
        if k not in frames:
            return None
        shots.append((t,) + frames[k])
    p = platforms.profile(ctx.a.platform) if ctx.a.platform else platforms.for_short(ctx.id)
    if p is None:
        p = platforms.profile("instagram")
    exc = os.path.join(ctx.out, "lint-exceptions.json")
    try:
        allow = {x.get("text") for x in (json.load(open(exc)).get("lint", []) if os.path.exists(exc) else [])}
    except (OSError, ValueError, AttributeError):
        allow = set()
    lines, fails, warns = [], 0, 0
    for t, f, part, local in shots:
        r = subprocess.run([os.path.join(KIT, "tools", "ocr_vision"), f], capture_output=True, text=True)
        try:
            o = json.loads(r.stdout)
            sc = 1080.0 / o["w"]
            ocr = o["lines"]
        except Exception:
            return None
        for l in ocr:
            if l.get("conf", 0) < 0.3 or len(re.sub(r"\s", "", l.get("text", ""))) < 3:
                continue
            hits = [x for x in _gate.lint_text(l["text"]) if l["text"] not in allow]
            if hits:
                lines.append("FAIL %6ss %-15s %s | %s" % (local, "text-lint", "; ".join(x.get("hit", "") for x in hits)[:60], l["text"][:70]))
                fails += 1
            box = {"x0": l["x"] * sc, "x1": (l["x"] + l["w"]) * sc, "y0": l["y"] * sc, "y1": (l["y"] + l["h"]) * sc}
            for sev, kind, detail in platforms.box_problems(p, box):
                lines.append("%s %6ss %-15s %s | %s" % (sev, local, kind, detail, l["text"][:70]))
                fails += sev == "FAIL"
                warns += sev == "WARN"
    lines.append("frame_precheck(fast, from the static snaps) %s -> %s: %d snaps, %d FAIL, %d WARN" % (ctx.id, p["key"], len(shots), fails, warns))
    return "\n".join(lines) + "\n", fails, warns


def step_snapchain(ctx, done):
    """static_precheck then frame_precheck, sequentially (they share out/<ID>/snap)."""
    moved = 0
    if not (ctx.cache.get("static") and ctx.cache["static"].get("key") == ctx.key("static") and not ctx.a.no_cache):
        moved = archive_stale_snaps(ctx)
    st = tool_check(ctx, "static", [PY, "tools/static_precheck.py", ctx.id], env={"AGMM_SNAP": "actions"})
    if moved:
        st["note"] = (st.get("note") or "") + "archived %d stale snap frames to out/%s/snap-archive-*" % (moved, ctx.id)
    done["static"] = st
    ctx.results["static"] = st
    fr = None
    if st["status"] in ("PASS", "FAIL") and not st.get("cached_at") and not ctx.a.real_frame:
        key = ctx.key("frame")
        t0 = time.time()
        got = frame_from_static_snaps(ctx)      # only right after a FRESH static capture (a cached static means the snaps may predate the package)
        if got:
            text, nf, nw = got
            log = os.path.join(ctx.pdir, "frame.log")
            open(log, "w").write(text)
            fails, warns = parse_findings("frame", text)
            fr = result("frame", "FAIL" if fails else "PASS", time.time() - t0, fails, warns, note="from the static snaps (no second cloud snap)", log=log, rc=1 if fails else 0)
            ctx.cache["frame"] = {"key": key, "status": fr["status"], "res": fr}
            ctx.save()
    if fr is None:
        fr = tool_check(ctx, "frame", [PY, "tools/frame_precheck.py", ctx.id, "--every", "2"] + (["--platform", ctx.a.platform] if ctx.a.platform else []))
    ctx.results["frame"] = fr
    return st, fr


def step_sheet(ctx):
    return tool_check(ctx, "sheet", [PY, "tools/sheet_check.py", ctx.id])


def step_btl(ctx):
    cmd = [PY, "tools/better_than_last.py", ctx.id, "--strict"] + (["--refresh"] if ctx.a.final else [])

    def parse(text, rc):
        fails = []
        for l in text.splitlines():
            s = l.strip()
            m = re.match(r"^!\s+(\S+)", s)          # "! behind_window_median:beats_per_min" (one per held dimension)
            if m:
                tok = m.group(1)
                rule = tok.split(":")[-1]
                fails.append({"when": "-", "rule": rule, "detail": re.sub(r"\s+", " ", tok)[:150], "line": s[:300]})
            elif s.startswith("HOLD") or re.search(r"\bHOLD\b.*:|no AHEAD|missing.*(eyes|ears)", s):
                if not any(f["line"] == s for f in fails):
                    fails.append({"when": "-", "rule": "", "detail": re.sub(r"\s+", " ", s)[:150], "line": s[:300]})
        status = "FAIL" if (rc == 2 or fails) else ("PASS" if rc == 0 else "ERROR")
        if rc == 2 and not fails:
            fails = [{"when": "-", "rule": "", "detail": [x for x in text.splitlines() if x.strip()][-1][:150], "line": ""}]
        return fails, 0, status
    return tool_check(ctx, "btl", cmd, cacheable=False, extra_parse=parse)


def make_beats_sheet(ctx):
    """out/<ID>/precheck/beats.jpg: the beat-middle frames of the newest snaps, for the LOOK (never a verdict)."""
    try:
        sys.path.insert(0, TOOLS)
        import sheet_check as SC
        frames, how = SC.load_frames(ctx.id, "snap")
        from PIL import Image
        n = len(frames)
        cols = 6
        rows = (n + cols - 1) // cols
        W, H = SC.TW, SC.TH
        im = Image.new("RGB", (cols * W, rows * H), (20, 20, 20))
        for i, f in enumerate(frames):
            im.paste(f["img"].resize((W, H)), ((i % cols) * W, (i // cols) * H))
        p = os.path.join(ctx.pdir, "beats.jpg")
        im.save(p, quality=88)
        return p
    except Exception:
        return None


# ---------------------------------------------------------------------------------------------------- orchestration
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("id")
    ap.add_argument("--platform")
    ap.add_argument("--only")
    ap.add_argument("--skip")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--real-frame", action="store_true", help="run frame_precheck.py itself (its own cloud snap) instead of reading the static snaps")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Z]\d{2,3}", a.id):
        ap.error("expected a short ID like S41")
    why = concept_card_refusal(a.id)
    if why:
        print("precheck_all REFUSED before build/voice/cloud: " + why, file=sys.stderr)
        return 1
    only = set(a.only.split(",")) if a.only else set(ORDER)
    skip = set(a.skip.split(",")) if a.skip else set()
    want = lambda n: n in only and n not in skip
    ctx = Ctx(a)
    t0 = time.time()
    started = now()
    R = {}
    print("precheck_all %s  started %s  (package %s)" % (a.id, started, ctx.pkg()[:10]), flush=True)

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        fut = {}
        # voice has no dependency on the package: start it at once
        if want("voice"):
            fut["voice"] = ex.submit(step_voice, ctx)
        if want("concept"):
            R["concept"] = step_concept(ctx)
            print("  concept   %-5s %s" % (R["concept"]["status"], R["concept"].get("note", "")), flush=True)
        stop = R.get("concept", {}).get("status") == "FAIL" and not a.keep_going
        if stop:
            print("  concept FAILED: not spending a build or cloud runs on this world (--keep-going overrides). Change the concept first.", flush=True)
        else:
            if want("build"):
                R["build"] = step_build(ctx)
                print("  build     %-5s %s" % (R["build"]["status"], R["build"].get("note", "")), flush=True)
            built = R.get("build", {}).get("status") in ("PASS", "SKIP") or "build" not in R
            if not built:
                print("  build FAILED: nothing else can run against a package that does not exist.", flush=True)
            else:
                if want("dom_lint"):
                    fut["dom_lint"] = ex.submit(step_dom_lint, ctx)
                if want("polish"):
                    fut["polish"] = ex.submit(step_polish, ctx)
                done = {}
                if want("static") or want("frame"):
                    fut["snapchain"] = ex.submit(step_snapchain, ctx, done)
                # sheet needs dom_lint raw + the static snaps
                if "dom_lint" in fut:
                    r = fut["dom_lint"].result()
                    R["dom_lint"] = r
                    print("  dom_lint  %-5s %s" % (r["status"], "cached %s" % r["cached_at"] if r.get("cached_at") else "%.0fs" % r["secs"]), flush=True)
                    # Craft's frame-zero rules read domlint/raw.json. The early
                    # concept check may have read the previous package (S317,
                    # 23 Oct). Keep the cheap early refusal, but never retain
                    # its verdict after collecting a new DOM report.
                    if want("concept"):
                        R["concept"] = step_concept(ctx)
                        print("  concept   %-5s (current DOM)" % R["concept"]["status"], flush=True)
                if "snapchain" in fut:
                    st, fr = fut["snapchain"].result()
                    if want("static"):
                        R["static"] = st
                        print("  static    %-5s %s" % (st["status"], "cached %s" % st["cached_at"] if st.get("cached_at") else "%.0fs" % st["secs"]), flush=True)
                    if want("frame"):
                        R["frame"] = fr
                        print("  frame     %-5s %s" % (fr["status"], "cached %s" % fr["cached_at"] if fr.get("cached_at") else "%.0fs" % fr["secs"]), flush=True)
                if "polish" in fut:
                    r = fut["polish"].result()
                    R["polish"] = r
                    print("  polish    %-5s %s" % (r["status"], "cached %s" % r["cached_at"] if r.get("cached_at") else "%.0fs" % r["secs"]), flush=True)
                if want("sheet"):
                    R["sheet"] = step_sheet(ctx)
                    print("  sheet     %-5s" % R["sheet"]["status"], flush=True)
                if want("btl"):
                    R["btl"] = step_btl(ctx)
                    print("  btl       %-5s" % R["btl"]["status"], flush=True)
        if "voice" in fut:
            R["voice"] = fut["voice"].result()
            print("  voice     %-5s %s" % (R["voice"]["status"], R["voice"].get("note", "")), flush=True)

    total = time.time() - t0
    beats = make_beats_sheet(ctx) if os.path.isdir(os.path.join(ctx.out, "snap")) else None
    bad = [c for c in ORDER if R.get(c, {}).get("status") == "FAIL"]
    err = [c for c in ORDER if R.get(c, {}).get("status") == "ERROR"]

    # ---- the table
    W = 150
    print("\n" + "=" * W)
    print("PRECHECK %s   %s -> %s   %.0f s wall   package %s" % (a.id, started, now(), total, ctx.pkg()[:10]))
    print("%-9s %-6s %-9s %s" % ("check", "status", "ran", "result"))
    for c in ORDER:
        r = R.get(c)
        if not r:
            continue
        ran = ("cached %s" % r["cached_at"]) if r.get("cached_at") else ("%.0f s" % r["secs"])
        extra = "%d FAIL, %d WARN" % (len(r["fails"]), r.get("warns", 0)) if r["status"] in ("PASS", "FAIL") else r.get("note", "")
        print("%-9s %-6s %-9s %s" % (c, r["status"], ran, extra))
    if bad:
        print("-" * W)
        print("%-9s %-13s %-15s %s" % ("check", "when", "rule", "what  (the fix is printed once per rule, under its first row)"))
        for c in bad:
            r = R[c]
            shown = set()
            for f in r["fails"][:10]:
                print("%-9s %-13s %-15s %s" % (c, f["when"][:13], (f.get("rule") or "-")[:15], f["detail"][:110]))
                h = hint_for(c, f.get("rule", ""), f.get("detail", ""))
                if h and (c, f.get("rule", "")) not in shown:
                    shown.add((c, f.get("rule", "")))
                    print("%-9s fix: %s" % ("", h))
            if len(r["fails"]) > 10:
                print("%-9s ... +%d more FAIL lines: %s" % (c, len(r["fails"]) - 10, r.get("log") or ""))
    for c in err:
        print("ERROR %s: %s" % (c, R[c].get("note", "")))
    if beats:
        print("LOOK: %s  (mid-beat frames of the newest snaps; the checks do not replace looking)" % beats)
    if bad:
        print("PRECHECK %s: FAIL in %s -> fix, then re-run `python3 tools/precheck_all.py %s` (unchanged checks come from cache); `python3 tools/autofix.py %s` does the deterministic ones" % (a.id, ", ".join(bad), a.id, a.id))
    elif err:
        print("PRECHECK %s: no FAIL but %s could not run: do not submit on this" % (a.id, ", ".join(err)))
    else:
        pr = os.path.join(ctx.out, "polish", "raw.json")
        hint = ""
        if os.path.exists(pr) and ctx.cache.get("polish", {}).get("key") == ctx.key("polish"):
            hint = "  (submit re-runs polish_check and static_precheck on Actions; `AGMM_POLISH_RAW=out/%s/polish/raw.json` before the command re-judges the saved polish run with no cloud call)" % a.id
        print("PRECHECK %s: PASS. Next: look at the frames, then `python3 tools/storyboard.py submit %s`%s" % (a.id, a.id, hint))
    json.dump({"id": a.id, "started": started, "wall_s": round(total, 1), "package": ctx.pkg(), "results": R, "exit": 1 if bad else (2 if err else 0)},
              open(os.path.join(ctx.pdir, "last.json"), "w"), indent=1, default=str)
    if a.json:
        print(json.dumps(R, indent=1, default=str))
    sys.exit(1 if bad else (2 if err else 0))


if __name__ == "__main__":
    main()
