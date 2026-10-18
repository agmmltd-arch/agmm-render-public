#!/usr/bin/env python3
"""concept_check.py: the sameness and pitch gate that runs BEFORE a storyboard is made (6 Oct 2026).

Why: Sam, 6 Oct 02:35: "be careful not to make the visuals too similar, they're starting to look the same. we're dropping
creativity", and "we're supposed to be getting better after each video". The reviewers kept returning one look (dark
navy/charcoal ground + giant figure + mono kicker + cream source card) by eye, one short at a time, hours after the maker
had built it. This tool makes the same call from structured text, in seconds, before anything is built or snapped.

Input : specs/<ID>/concept.json (schema: registry/concept.schema.json, every look field is an enum).
Window: the last 10 approved shorts by storyboard decision time (registry/storyboards/*.json history; a short is in the
        window at time T only if its latest state at T is "approved", ordered by that approval time, the short itself excluded).
Rules : each FAIL is a hard stop for `storyboard.py submit` unless `--concept-waiver "<reason>"` is given.
  R0 schema        the concept parses, every enum is legal, hex ground matches its luminance class, bed == spec.json music.bed
  R1 distance      must differ from EACH of the last 10 on >= 3 of 7 axes: world_family, ground bucket (luminance + hue
                   family), hero_device, hook_mechanic, signature mechanism, camera, source_presentation
  R2 palette       the dominant palette hue bucket may be shared with at most 2 of the last 10
  R3 dark ground   FAIL if the ground is the dark-navy/charcoal bucket (on >= 60% of beats) while >= 3 of the last 10 are
  R4 house look    root's 04:00 rule made mechanical: of {dark-navy/charcoal ground, giant-number hero, mono kicker,
                   cream-card sources} a new short may match at most 2 (it must differ on at least two)
  R5 bed           the bed may not be used by 3 or more of the last 10 (warn if it equals the latest approved's)
  R6 better        better_than_last.short must be in the window (or S52/P1) and, when the axis is a look axis, the concept must
                   really differ from that short on that axis
  R7 pitch         TEXT ONLY, against the script: frame 0 names a subject and a number from the script; >= 8 distinct
                   constructed objects each tied to a spoken word; every script sentence that carries a figure is covered by a
                   claim with a source; the signature is tied to a word in the script (and in words.json when present)
Sheet verification (`--verify-sheet`, run by storyboard.py after the sheet exists): the declared ground bucket and
beats_fraction must match the pixels of registry/storyboards/<ID>-storyboard.jpg, so a concept cannot say "cream" and ship navy.

Usage : concept_check.py <ID> [--at ISO8601] [--concept PATH] [--window N] [--json] [--verify-sheet] [--no-pitch]
        concept_check.py --menu [<ID>]     (before you write the concept: what the last 10 use, and which choices are free)
Exit  : 0 PASS (warnings allowed), 1 FAIL, 2 cannot run (bad arguments)
Library: check_for_submit(ID) -> (ok, text, report) is what storyboard.py calls.
"""
import argparse, colorsys, datetime, glob, json, math, os, re, sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2 = os.path.dirname(KIT)
REG = os.path.join(KIT, "registry")
SB_DIR = os.path.join(REG, "storyboards")
SCHEMA_PATH = os.path.join(REG, "concept.schema.json")
OFF_FLAG = os.path.join(REG, "concept-check.off")          # root's safety valve: this file present = advisory only
BACKFILL_CUTOFF = "2026-10-06T12:30:00"                    # derived (backfilled) concepts are valid only for shorts registered before this
LOOK_AXES = ["world_family", "ground", "hero_device", "hook_mechanic", "signature", "camera", "source_presentation"]
MIN_DIFF = 3
WINDOW_N = 10
PALETTE_SHARE_MAX = 2
DARK_COUNT_MAX = 2          # FAIL when 3 or more of the window are dark-navy/charcoal
OBJECTS_MIN = 8


# ----------------------------------------------------------------------------------------------------------- schema
def load_schema():
    return json.load(open(SCHEMA_PATH))


def _type_ok(v, t):
    ts = t if isinstance(t, list) else [t]
    for x in ts:
        if x == "string" and isinstance(v, str): return True
        if x == "number" and isinstance(v, (int, float)) and not isinstance(v, bool): return True
        if x == "integer" and isinstance(v, int) and not isinstance(v, bool): return True
        if x == "boolean" and isinstance(v, bool): return True
        if x == "array" and isinstance(v, list): return True
        if x == "object" and isinstance(v, dict): return True
        if x == "null" and v is None: return True
    return False


def validate(v, sch, path="$"):
    """minimal JSON-schema subset: type, enum, required, properties, items, pattern, min/max, minItems/maxItems, minLength."""
    errs = []
    if "type" in sch and not _type_ok(v, sch["type"]):
        return ["%s: expected %s, got %s" % (path, sch["type"], type(v).__name__)]
    if "enum" in sch and v not in sch["enum"]:
        errs.append("%s: %r is not one of %s" % (path, v, sch["enum"]))
    if isinstance(v, str):
        if "pattern" in sch and not re.search(sch["pattern"], v): errs.append("%s: %r does not match %s" % (path, v, sch["pattern"]))
        if "minLength" in sch and len(v) < sch["minLength"]: errs.append("%s: shorter than %d characters" % (path, sch["minLength"]))
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in sch and v < sch["minimum"]: errs.append("%s: %s below %s" % (path, v, sch["minimum"]))
        if "maximum" in sch and v > sch["maximum"]: errs.append("%s: %s above %s" % (path, v, sch["maximum"]))
    if isinstance(v, list):
        if "minItems" in sch and len(v) < sch["minItems"]: errs.append("%s: needs at least %d items" % (path, sch["minItems"]))
        if "maxItems" in sch and len(v) > sch["maxItems"]: errs.append("%s: at most %d items" % (path, sch["maxItems"]))
        if "items" in sch:
            for i, it in enumerate(v): errs += validate(it, sch["items"], "%s[%d]" % (path, i))
    if isinstance(v, dict):
        for k in sch.get("required", []):
            if k not in v: errs.append("%s: missing required field %r" % (path, k))
        for k, sub in sch.get("properties", {}).items():
            if k in v: errs += validate(v[k], sub, "%s.%s" % (path, k))
    return errs


# ----------------------------------------------------------------------------------------------------------- colour
def _rgb(hexstr):
    h = hexstr.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lab_of(rgb):
    c = [x / 255.0 for x in rgb]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    X = (0.4124 * c[0] + 0.3576 * c[1] + 0.1805 * c[2]) / 0.95047
    Y = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    Z = (0.0193 * c[0] + 0.1192 * c[1] + 0.9505 * c[2]) / 1.08883
    f = lambda t: t ** (1 / 3.0) if t > 0.008856 else 7.787 * t + 16 / 116.0
    fx, fy, fz = f(X), f(Y), f(Z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def lum_class_of(hexstr):
    L = lab_of(_rgb(hexstr))[0]
    return "dark" if L < 32 else ("mid" if L < 68 else "light")


def hue_bucket(hexstr):
    """fine hue bucket; near-neutral (Lab chroma < 9) is 'neutral'."""
    rgb = _rgb(hexstr)
    L, a, b = lab_of(rgb)
    if math.hypot(a, b) < 9:
        return "neutral"
    h = colorsys.rgb_to_hsv(*[x / 255.0 for x in rgb])[0] * 360
    if h < 15 or h >= 345: return "red"
    if h < 38: return "orange"
    if h < 70: return "amber"
    if h < 165: return "green"
    if h < 200: return "teal"
    if h < 255: return "blue"
    if h < 300: return "violet"
    return "pink"


HUE_FAMILY = {"neutral": "coolneutral", "teal": "coolneutral", "blue": "coolneutral", "red": "warm", "orange": "warm",
              "amber": "warm", "green": "green", "violet": "violet", "pink": "violet"}


def ground_bucket(hexstr):
    return "%s-%s" % (lum_class_of(hexstr), HUE_FAMILY[hue_bucket(hexstr)])


def chroma(hexstr):
    L, a, b = lab_of(_rgb(hexstr))
    return math.hypot(a, b)


def dominant_hue(palette):
    """hue bucket of the dominant palette colour: the first colour (they are ordered by area, the ground first) that a viewer
    reads as a hue and not as a tinted black, grey or paper: Lab chroma >= 15 for a dark colour (L* < 25, where a tint reads
    as black) and >= 9 for anything lighter; 'neutral:<lum>' if none."""
    for hx in palette:
        L = lab_of(_rgb(hx))[0]
        if chroma(hx) >= (15 if L < 25 else 9):
            return hue_bucket(hx)
    return "neutral:" + lum_class_of(palette[0])


# ----------------------------------------------------------------------------------------------------------- registry
def _ts(date, at):
    return "%sT%s" % (date or "2026-09-27", at)       # the oldest history rows carry no date (25-28 Sep): a fixed early date keeps their order


def storyboard_events():
    out = {}
    for f in glob.glob(os.path.join(SB_DIR, "*.json")):
        try:
            r = json.load(open(f))
        except Exception:
            continue
        if not isinstance(r, dict) or "id" not in r or "history" not in r:
            continue
        out[r["id"]] = sorted([(_ts(h.get("date"), h.get("at", "00:00:00")), h.get("state")) for h in r["history"]])
    return out


def first_registered(ID, events=None):
    ev = (events or storyboard_events()).get(ID)
    return ev[0][0] if ev else None


def approved_at(T, events=None, exclude=None):
    """[(approval_ts, id)] newest first: shorts whose latest state at or before T is 'approved'."""
    rows = []
    for sid, ev in (events or storyboard_events()).items():
        if sid == exclude or sid.startswith("_"):
            continue
        past = [e for e in ev if e[0] <= T]
        if past and past[-1][1] == "approved":
            rows.append((past[-1][0], sid))
    rows.sort(reverse=True)
    return rows


def load_concept(ID, path=None):
    p = path or os.path.join(KIT, "specs", ID, "concept.json")
    if not os.path.exists(p):
        return None
    return json.load(open(p))


def window_for(ID, T, n=WINDOW_N, events=None):
    """last n approved shorts at T that have a concept.json; also returns the ids skipped for lacking one."""
    win, missing = [], []
    for ts, sid in approved_at(T, events, exclude=ID):
        if len(win) >= n:
            break
        try:
            c = load_concept(sid)
        except Exception:
            c = None
        if c is None:
            missing.append(sid)
            continue
        win.append((sid, ts, c))
    return win, missing


# ----------------------------------------------------------------------------------------------------------- axes
MIXED_BELOW = 0.6


def ground_axis(c):
    """the ground axis of the distance: the ground bucket, or 'mixed' when no single ground carries 60% of the beats (a short
    that changes ground from beat to beat, like S52's navy airport, sunset, blue, wood desk, yellow and daylight, is not the
    one-ground house look the reviewers return)."""
    if c["ground"].get("beats_fraction", 1) < MIXED_BELOW:
        return "mixed"
    return ground_bucket(c["ground"]["hex"])


def axes_of(c):
    return {
        "world_family": c["world"]["world_family"],
        "ground": ground_axis(c),
        "hero_device": c["hero_device"],
        "hook_mechanic": c["hook_mechanic"],
        "signature": c["signature"]["mechanism"],
        "camera": c["camera"],
        "source_presentation": c["source_presentation"],
    }


def distance(a, b):
    """(number of differing axes, [axes that are the same])."""
    A, B = axes_of(a), axes_of(b)
    same = [k for k in LOOK_AXES if A[k] == B[k]]
    return len(LOOK_AXES) - len(same), same


def is_dark_cool(c):
    return ground_bucket(c["ground"]["hex"]) == "dark-coolneutral" and c["ground"].get("beats_fraction", 1) >= 0.6


def house_matches(c):
    m = []
    if is_dark_cool(c): m.append("dark navy/charcoal ground")
    if c["hero_device"] == "giant-number": m.append("giant-number hero")
    if c["type_voice"]["kicker"] == "mono": m.append("mono kicker")
    if c["source_presentation"] == "cream-card": m.append("cream source card")
    return m


# ----------------------------------------------------------------------------------------------------------- pitch
def norm(s):
    return " ".join(re.findall(r"[a-z0-9£$%']+", (s or "").lower().replace("’", "'")))


def script_text(ID):
    """the spoken part of shorts/scripts-v2/<ID>.md (after '## Spoken script'); None when there is no script."""
    p = os.path.join(V2, "shorts", "scripts-v2", ID + ".md")
    if not os.path.exists(p):
        return None
    t = open(p).read()
    m = re.search(r"##\s*Spoken script\s*\n(.*?)(?=\n##\s|\Z)", t, re.S | re.I)
    return (m.group(1) if m else t).strip()


def script_title_blob(ID):
    p = os.path.join(V2, "shorts", "scripts-v2", ID + ".md")
    return open(p).read() if os.path.exists(p) else ""


FIGURE_RX = re.compile(r"\d|hundred|thousand|million|billion|trillion|per ?cent|percent|£|\$|€|\bhalf\b|\bquarter\b|\bthird\b|\bten\b|\bone in\b")


def split_sentences(spoken):
    parts = re.split(r"(?<=[.!?])\s+|\n+", spoken)
    return [p.strip() for p in parts if p.strip()]


def words_json(ID):
    for p in (os.path.join(V2, "shorts", "voice", ID, ID + ".words.json"),):
        if os.path.exists(p):
            try:
                d = json.load(open(p))
                return d.get("words", d) if isinstance(d, dict) else d
            except Exception:
                return None
    return None


def word_times(words, w):
    key = norm(w)
    return [float(x["start"]) for x in (words or []) if norm(x.get("word", "")) == key]


def pitch_check(ID, c):
    """returns list of (ok, name, detail). Text only: it never looks at frames."""
    out = []
    p = c.get("pitch")
    spoken = script_text(ID)
    if spoken is None:
        return [(False, "pitch: script", "no shorts/scripts-v2/%s.md to check the pitch against" % ID)]
    if not p:
        return [(False, "pitch", "concept has no pitch block (frame0, objects, claims); write it from the script")]
    ns = norm(spoken)
    blob = norm(script_title_blob(ID))
    # frame 0: a named subject and a number from the script
    f0 = p["frame0"]
    ok_subj = norm(f0["subject"]) and norm(f0["subject"]) in blob
    out.append((bool(ok_subj), "pitch: frame 0 names a subject from the script",
                "subject %r %s the script" % (f0["subject"], "is in" if ok_subj else "is NOT in")))
    ok_num = bool(re.search(r"\d", f0["number_on_screen"])) and norm(f0["number_spoken"]) in ns and len(norm(f0["number_spoken"])) >= 3
    out.append((ok_num, "pitch: frame 0 carries a number the script speaks",
                "on screen %r, spoken as %r: %s" % (f0["number_on_screen"], f0["number_spoken"],
                                                    "found in the script" if ok_num else "NOT found in the script (copy the spoken words exactly)")))
    # objects: >= 8 distinct constructed objects, each tied to a spoken word
    words = words_json(ID)
    objs = p["objects"]
    names = [norm(o["name"]) for o in objs]
    dup = len(names) - len(set(names))
    bad = []
    for o in objs:
        if not o["constructed"]:
            continue
        if norm(o["word"]) not in ns.split() and norm(o["word"]) not in ns:
            bad.append("%s: word %r not in script" % (o["name"], o["word"]))
        elif o.get("at_s") is not None and words:
            ts = word_times(words, o["word"])
            if ts and min(abs(t - float(o["at_s"])) for t in ts) > 2.5:
                bad.append("%s: %r is spoken at %s but the object is placed at %.1f s" % (o["name"], o["word"], ", ".join("%.1f" % t for t in ts[:3]), o["at_s"]))
    tied = [o for o in objs if o["constructed"] and not any(o["name"] in b for b in bad)]
    ok_obj = len({norm(o["name"]) for o in tied}) >= OBJECTS_MIN and not dup
    out.append((ok_obj, "pitch: >= %d distinct constructed objects, each tied to a spoken word" % OBJECTS_MIN,
                "%d constructed and tied (%d listed)%s%s" % (len({norm(o['name']) for o in tied}), len(objs), "; duplicates: %d" % dup if dup else "",
                                                             "; " + "; ".join(bad[:4]) if bad else "")))
    # claims: every sentence that carries a figure is covered by a claim with a source
    uncovered, weak = [], []
    claims = p["claims"]
    for cl in claims:
        q = norm(cl["script_quote"])
        if len(q.split()) < 3 or q not in ns:
            weak.append("quote not in script: %r" % cl["script_quote"][:50])
        s = cl["source"]
        if not s.get("outlet", "").strip() or not s.get("date", "").strip():
            weak.append("claim %r has no outlet or date" % cl["script_quote"][:40])
        elif not (s.get("url", "").startswith("http") or (s.get("file") and os.path.exists(os.path.join(V2, s["file"])))):
            weak.append("claim %r has no url or existing file" % cl["script_quote"][:40])
    qs = [norm(cl["script_quote"]) for cl in claims]
    for sent in split_sentences(spoken):
        nsent = norm(sent)
        if FIGURE_RX.search(nsent) and not any(q and q in nsent for q in qs):
            uncovered.append(sent[:70])
    ok_claim = not uncovered and not weak
    out.append((ok_claim, "pitch: a source for every factual claim",
                "%d claims; %s" % (len(claims), "every figure sentence is covered" if not uncovered else "UNSOURCED: " + " | ".join(uncovered[:3]))
                + ("; " + "; ".join(weak[:3]) if weak else "")))
    # signature tied to a word in the script
    sig = c["signature"]
    w = sig.get("word")
    ok_sig = bool(w) and norm(w) in ns.split()
    detail = "word %r %s" % (w, "is spoken in the script" if ok_sig else "is NOT a word of the script")
    if ok_sig and words and sig.get("at_s") is not None:
        ts = word_times(words, w)
        if ts and min(abs(t - float(sig["at_s"])) for t in ts) > 3.0:
            ok_sig = False
            detail += "; but it is spoken at %s and the signature is placed at %.1f s" % (", ".join("%.1f" % t for t in ts[:3]), sig["at_s"])
    out.append((ok_sig, "pitch: signature lands on a spoken word", detail))
    return out


# ----------------------------------------------------------------------------------------------------------- main check
def spec_bed(ID):
    p = os.path.join(KIT, "specs", ID, "spec.json")
    try:
        return json.load(open(p)).get("music", {}).get("bed")
    except Exception:
        return None


def run(ID, T=None, concept_path=None, n=WINDOW_N, do_pitch=True, concept=None):
    """returns the report dict. T: ISO time the window is taken at (default now)."""
    T = T or datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    events = storyboard_events()
    checks = []
    add = lambda ok, name, detail, level="FAIL": checks.append({"ok": bool(ok), "name": name, "detail": detail, "level": level})
    rep = {"id": ID, "at": T, "checks": checks, "window": [], "missing_in_window": [], "verdict": "FAIL"}
    c = concept
    if c is None:
        try:
            c = load_concept(ID, concept_path)
        except Exception as e:
            add(False, "R0 concept.json parses", str(e))
            return finish(rep)
    if c is None:
        add(False, "R0 concept.json exists", "specs/%s/concept.json is missing: write it (schema registry/concept.schema.json, template in kit/WRITER-BRIEF.md)" % ID)
        return finish(rep)
    errs = validate(c, load_schema())
    if errs:
        add(False, "R0 schema", "; ".join(errs[:6]) + (" (+%d more)" % (len(errs) - 6) if len(errs) > 6 else ""))
        return finish(rep)
    add(True, "R0 schema", "valid")
    derived = bool(c.get("derived"))
    if derived:
        reg = first_registered(ID, events)
        if not reg or reg >= BACKFILL_CUTOFF:
            add(False, "R0 derived concept", "a derived (backfilled) concept is only valid for a short registered before %s; write a real concept.json" % BACKFILL_CUTOFF)
    g = c["ground"]
    if lum_class_of(g["hex"]) != g["luminance"]:
        add(False, "R0 ground luminance", "ground %s is %s, not %s" % (g["hex"], lum_class_of(g["hex"]), g["luminance"]))
    if c["palette"][0].lower() != g["hex"].lower():
        add(False, "R0 palette[0] is the ground", "palette[0] %s but ground %s" % (c["palette"][0], g["hex"]))
    sb = spec_bed(ID)
    if sb is not None and sb != c["bed"]["id"]:
        add(False, "R0 bed matches spec.json", "concept says %r but specs/%s/spec.json music.bed is %r" % (c["bed"]["id"], ID, sb))
    win, missing = window_for(ID, T, n, events)
    rep["window"] = [{"id": sid, "approved": ts} for sid, ts, _ in win]
    rep["missing_in_window"] = missing
    if len(win) < n:
        add(True, "window", "only %d of %d approved shorts have a concept.json (missing: %s)" % (len(win), n, ", ".join(missing[:8]) or "none"), "WARN")
    mine = axes_of(c)
    rep["axes"] = mine
    rep["ground_bucket"] = ground_bucket(g["hex"])
    rep["dominant_hue"] = dominant_hue(c["palette"])
    # R1 distance
    worst, rows = None, []
    for sid, ts, o in win:
        d, same = distance(c, o)
        rows.append({"id": sid, "diff": d, "same_on": same})
        if worst is None or d < worst[1]:
            worst = (sid, d, same)
    rep["distance"] = rows
    fails = [r for r in rows if r["diff"] < MIN_DIFF]
    add(not fails, "R1 distance (>= %d of 7 axes from each of the last %d)" % (MIN_DIFF, len(win)),
        ("min %d vs %s" % (worst[1], worst[0]) if worst else "no window") if not fails else
        "TOO CLOSE: " + "; ".join("%s differs on only %d (same: %s)" % (r["id"], r["diff"], ",".join(r["same_on"])) for r in fails))
    # R2 palette hue
    dh = rep["dominant_hue"]
    share = [sid for sid, _, o in win if dominant_hue(o["palette"]) == dh]
    add(len(share) <= PALETTE_SHARE_MAX, "R2 dominant palette hue shared with at most %d of the last %d" % (PALETTE_SHARE_MAX, len(win)),
        "dominant hue %r is shared with %d: %s" % (dh, len(share), ",".join(share) or "-"))
    # R3 dark navy/charcoal ground
    dark = [sid for sid, _, o in win if is_dark_cool(o)]
    if is_dark_cool(c):
        add(len(dark) <= DARK_COUNT_MAX, "R3 dark navy/charcoal ground while >= 3 of the last %d are" % len(win),
            "ground %s (%.0f%% of beats) is dark navy/charcoal; so are %d of the window: %s" % (g["hex"], 100 * g.get("beats_fraction", 1), len(dark), ",".join(dark) or "-"))
    else:
        add(True, "R3 dark navy/charcoal ground while >= 3 of the last %d are" % len(win),
            "ground %s is %s (not dark navy/charcoal, or on under 60%% of beats); window has %d dark navy/charcoal" % (g["hex"], mine["ground"], len(dark)))
    # R4 house look
    hm = house_matches(c)
    add(len(hm) <= 2, "R4 house look (differ on at least two of ground, hero, type voice, sources)",
        "matches %d of 4: %s" % (len(hm), ", ".join(hm) or "none"))
    # R5 bed
    bed = c["bed"]["id"]
    users = [sid for sid, _, o in win if o["bed"]["id"] == bed]
    add(len(users) < 3, "R5 bed not used by 3 or more of the last %d" % len(win), "bed %r used by %d: %s" % (bed, len(users), ",".join(users) or "-"))
    if win and win[0][2]["bed"]["id"] == bed:
        add(True, "R5 bed differs from the latest approved", "same bed as %s, the latest approved" % win[0][0], "WARN")
    # VARIETY 13 Oct: live reservations of shorts being made count like approved ones (the S103/S104 race)
    reservation_rules(rep, ID, c, T, win, dark, share, users, events, add)
    prop_rules(rep, ID, T, win, events, add)
    # R6 better_than_last honesty
    b = c["better_than_last"]
    ref = b["short"]
    ids = [sid for sid, _, _ in win]
    if ref in ids or ref in ("S52", "P1"):
        look_axis = {"world": "world_family", "ground": "ground", "hero": "hero_device", "hook": "hook_mechanic", "signature": "signature",
                     "camera": "camera", "source": "source_presentation"}.get(b["axis"])
        oc = next((o for sid, _, o in win if sid == ref), None)
        if oc is None and ref != "P1":
            try:
                oc = load_concept(ref)
            except Exception:
                oc = None
        if look_axis and oc is not None:
            same = axes_of(oc)[look_axis] == mine[look_axis]
            add(not same, "R6 better_than_last: really differs on its own axis", "claims to beat %s on %s but both are %r" % (ref, b["axis"], mine[look_axis]) if same
                else "%s on %s: %r vs %r" % (ref, b["axis"], mine[look_axis], axes_of(oc)[look_axis]))
        else:
            add(True, "R6 better_than_last names a recent short", "%s on %s" % (ref, b["axis"]))
    else:
        add(False, "R6 better_than_last names a RECENT short", "%s is not in the last %d approved (%s) nor S52/P1" % (ref, len(ids), ",".join(ids)))
    # R7 pitch
    if do_pitch:
        if c.get("pitch") or not derived:
            for ok, name, detail in pitch_check(ID, c):
                add(ok, "R7 " + name, detail)
        else:
            add(True, "R7 pitch", "derived concept without a pitch block: not checked (backfill); the next submit needs a real one", "WARN")
    return finish(rep)


def _cr():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import concept_reserve
    return concept_reserve


def reservation_rules(rep, ID, c, T, win, dark, share, users, events, add):
    """R1/R2/R3/R5 again, counting live reservations (made before this short's own) on top of the approved window.
    FAIL for shorts claimed after the reservation layer went live, WARN for earlier claims. Never raises."""
    try:
        cr = _cr()
        mine = cr.my_reserved_at(ID)
        res = cr.live(T, exclude=ID, before=mine if mine and mine <= T else None, events=events)
        lvl = "FAIL" if cr.enforced(ID) else "WARN"
    except Exception as e:
        add(True, "reservations", "not read (%s)" % e, "WARN")
        return
    rep["reserved"] = [{"id": r["id"], "maker": r.get("maker"), "reserved_at": r["reserved_at"], "why": r["why"]} for r in res]
    if not res:
        return
    ax = axes_of(c)
    if is_dark_cool(c):
        rd = [r["id"] for r in res if r["axes"].get("dark_cool")]
        if rd and len(dark) <= DARK_COUNT_MAX:
            tot = dark + rd
            add(len(tot) <= DARK_COUNT_MAX, "R3 dark ground counting live reservations",
                "%d dark approved (%s) + %d reserved by shorts being made (%s) = %d; max %d" % (
                    len(dark), ",".join(dark) or "-", len(rd), ",".join(rd), len(tot), DARK_COUNT_MAX), lvl if len(tot) > DARK_COUNT_MAX else "FAIL")
    dh = rep.get("dominant_hue")
    rh = [r["id"] for r in res if r["axes"].get("dominant_hue") == dh]
    if rh and len(share) <= PALETTE_SHARE_MAX:
        add(len(share) + len(rh) <= PALETTE_SHARE_MAX, "R2 dominant palette hue counting live reservations",
            "hue %r: %d approved (%s) + %d reserved (%s)" % (dh, len(share), ",".join(share) or "-", len(rh), ",".join(rh)),
            lvl if len(share) + len(rh) > PALETTE_SHARE_MAX else "FAIL")
    rb = [r["id"] for r in res if r["axes"].get("bed") == c["bed"]["id"]]
    if rb and len(users) < 3:
        add(len(users) + len(rb) < 3, "R5 bed counting live reservations",
            "bed %r: %d approved + %d reserved (%s)" % (c["bed"]["id"], len(users), len(rb), ",".join(rb)), lvl if len(users) + len(rb) >= 3 else "FAIL")
    close = []
    for r in res:
        known = [k for k in LOOK_AXES if r["axes"].get(k) is not None]
        if len(known) < len(LOOK_AXES):
            continue
        same = [k for k in LOOK_AXES if r["axes"][k] == ax[k]]
        if len(LOOK_AXES) - len(same) < MIN_DIFF:
            close.append("%s differs on only %d (same: %s)" % (r["id"], len(LOOK_AXES) - len(same), ",".join(same)))
    if close:
        add(False, "R1 distance from live reservations", "TOO CLOSE to a short being made: " + "; ".join(close), lvl)


def prop_rules(rep, ID, T, win, events, add):
    """R8 prop/world reuse (ADVISORY: calibration on the review log found no threshold with <= 5% false flags on
    first-pass approvals that still catches the returns; see prop_reuse.py --calibrate) and R9 exact image reuse
    (FAIL for claims after the reservation layer went live, WARN before; a film and its short C<n>/S<n> and mastheads/logos
    are exempt). Never raises."""
    try:
        import prop_reuse
        cr = _cr()
        mine = cr.my_reserved_at(ID)
        res = cr.live(T, exclude=ID, before=mine if mine and mine <= T else None, events=events)
        r = prop_reuse.check(ID, T if T < datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S") else None,
                             [sid for sid, _, _ in win], res)
        lvl = "FAIL" if cr.enforced(ID) else "WARN"
    except Exception as e:
        add(True, "R8 prop/world reuse", "not run (%s)" % e, "WARN")
        return
    rep["props"] = {"main": r["main"], "world_repeat": r["world_repeat"]}
    add(not r["flag"], "R8 prop/world reuse (advisory)", r["detail"], "WARN" if r["flag"] else "FAIL")
    num = re.sub(r"\D", "", ID)
    img = {sid: [p for p in paths if not re.search(r"mast|logo", p, re.I)] for sid, paths in r["images"].items()
           if re.sub(r"\D", "", sid) != num}
    img = {k: v for k, v in img.items() if v}
    add(not img, "R9 no image reused from the window", "; ".join("%s: %s" % (k, ", ".join(v[:3])) for k, v in img.items())
        or "no exact image shared with the last %d approved or live reservations" % len(win), lvl if img else "FAIL")


def lock_if_pass(ID, rep):
    """a PASS on today's window locks this concept's classes into the reservation registry (best effort)."""
    if rep.get("verdict") != "PASS":
        return
    try:
        c = load_concept(ID)
        if c:
            _cr().lock_concept(ID, c)
            rep.setdefault("notes", []).append("reservation locked for %s" % ID)
    except Exception as e:
        rep.setdefault("notes", []).append("reservation not written (%s)" % e)


def finish(rep):
    hard = [x for x in rep["checks"] if not x["ok"] and x["level"] == "FAIL"]
    rep["verdict"] = "FAIL" if hard else "PASS"
    rep["failed"] = [x["name"] for x in hard]
    return rep


def render(rep):
    L = ["concept_check %s at %s: %s" % (rep["id"], rep["at"], rep["verdict"])]
    if rep.get("window"):
        L.append("window (last %d approved): %s" % (len(rep["window"]), " ".join(w["id"] for w in rep["window"])))
    if rep.get("reserved"):
        L.append("reserved by shorts being made (counted too): %s" % " ".join("%s(%s)" % (r["id"], r.get("maker") or "-") for r in rep["reserved"]))
    for x in rep["checks"]:
        tag = "ok  " if x["ok"] else ("WARN" if x["level"] == "WARN" else "FAIL")
        if x["ok"] and x["level"] == "WARN":
            tag = "WARN"
        L.append("  [%s] %s: %s" % (tag, x["name"], x["detail"]))
    if rep["verdict"] == "FAIL":
        L.append("=> refused. Change the concept (a different world, ground, hero, hook or signature), not the file. "
                 "A deliberate exception needs: storyboard.py submit %s --concept-waiver \"<reason of 40+ characters>\"" % rep["id"])
    return "\n".join(L)


# ----------------------------------------------------------------------------------------------------------- sheet verification
def measure_sheet(path):
    """ground colour (modal border colour across tiles) and the share of tiles on it, from the storyboard sheet."""
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGB")
    W, H = im.size
    if W != 1620:
        return None
    top = H if H % 480 == 0 else (H - 44) // 2
    grounds = []
    for r in range(top // 480):
        for cc in range(6):
            a = np.asarray(im.crop((cc * 270, r * 480, cc * 270 + 270, r * 480 + 480)))
            if a.max() < 6:
                continue
            band = np.concatenate([a[:, :8].reshape(-1, 3), a[:, -8:].reshape(-1, 3), a[:10].reshape(-1, 3), a[-30:].reshape(-1, 3)])
            grounds.append(tuple(int(x) for x in np.median(band, axis=0)))
    if not grounds:
        return None
    labs = [lab_of(g) for g in grounds]
    clusters = []
    for i, l in enumerate(labs):
        for cl in clusters:
            if math.dist(l, cl["lab"]) < 14:
                cl["idx"].append(i)
                break
        else:
            clusters.append({"lab": l, "idx": [i]})
    clusters.sort(key=lambda cl: -len(cl["idx"]))
    big = clusters[0]
    gcol = tuple(int(np.median([grounds[i][k] for i in big["idx"]])) for k in range(3))
    return {"hex": "#%02x%02x%02x" % gcol, "share": len(big["idx"]) / float(len(grounds)), "tiles": len(grounds)}


def verify_sheet(ID, concept=None):
    """list of error strings; [] when the declared ground matches the sheet."""
    c = concept or load_concept(ID)
    sheet = os.path.join(SB_DIR, "%s-storyboard.jpg" % ID)
    if c is None or not os.path.exists(sheet):
        return ["no sheet or concept to verify"]
    m = measure_sheet(sheet)
    if not m:
        return ["could not read the sheet"]
    errs = []
    declared, measured = ground_bucket(c["ground"]["hex"]), ground_bucket(m["hex"])
    if declared != measured:
        errs.append("declared ground %s (%s) but the sheet's ground is %s (%s)" % (c["ground"]["hex"], declared, m["hex"], measured))
    if abs(c["ground"]["beats_fraction"] - m["share"]) > 0.25:
        errs.append("declared beats_fraction %.2f but %.0f%% of the sheet's beats sit on that ground" % (c["ground"]["beats_fraction"], 100 * m["share"]))
    return errs


# ----------------------------------------------------------------------------------------------------------- submit hook
def enforcement():
    if os.environ.get("AGMM_CONCEPT_CHECK") == "warn" or os.path.exists(OFF_FLAG):
        return "warn"
    return "enforce"


def grandfather_time(ID, concept_path=None):
    """Root 6 Oct 12:45: a short whose concept was ALREADY approved and has not been re-conceived since (a fix-only
    resubmit: framing, CTA split, voice) is judged against the window as it stood at its first approval, not today's.
    Otherwise S52 (Sam's model) and S02 could not get a framing fix through. 'Not re-conceived' = concept.json is still
    the derived backfill, or it is older than the short's latest approval."""
    ev = storyboard_events().get(ID) or []
    appr = [t for t, st in ev if st == "approved"]
    if not appr:
        return None
    c = load_concept(ID, concept_path) or {}
    p = concept_path or os.path.join(KIT, "specs", ID, "concept.json")
    try:
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%dT%H:%M:%S")
    except OSError:
        return None
    if c.get("derived") or mt <= appr[-1]:
        t = datetime.datetime.strptime(appr[0], "%Y-%m-%dT%H:%M:%S") - datetime.timedelta(seconds=1)
        return t.strftime("%Y-%m-%dT%H:%M:%S")
    return None


def check_for_submit(ID, concept_path=None):
    T = grandfather_time(ID, concept_path)
    rep = run(ID, T=T, concept_path=concept_path)
    if T:
        rep.setdefault("notes", []).append("concept already approved and unchanged: judged against the window at its first approval (%s)" % T)
    elif not concept_path:
        lock_if_pass(ID, rep)
    return rep["verdict"] == "PASS", render(rep), rep


def suggest(ID=None, T=None, n=WINDOW_N):
    """which ground classes, worlds and hero devices are free RIGHT NOW: last n approved + live reservations."""
    T = T or datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    events = storyboard_events()
    sch = load_schema()
    P = sch["properties"]
    win, _ = window_for(ID, T, n, events)
    try:
        cr = _cr()
        mine = cr.my_reserved_at(ID) if ID else None
        res = cr.live(T, exclude=ID, before=mine if mine and mine <= T else None, events=events)
    except Exception as e:
        res = []
        print("(reservations not read: %s)" % e)
    L = ["suggest%s at %s: last %d approved = %s" % (" for " + ID if ID else "", T, len(win), " ".join(s for s, _, _ in win)),
         "live reservations (shorts being made) = %s" % (" ".join("%s[%s %s]" % (r["id"], r.get("maker") or "-", r["axes"].get("ground")) for r in res) or "none")]
    used = lambda key_a, key_r: ([(s, axes_of(o)[key_a]) for s, _, o in win], [(r["id"], r["axes"].get(key_r)) for r in res])
    lums, fams = ["dark", "mid", "light"], ["coolneutral", "warm", "green", "violet"]
    dark_n = sum(1 for _, _, o in win if is_dark_cool(o)) + sum(1 for r in res if r["axes"].get("dark_cool"))
    a, r_ = used("ground", "ground")
    L.append("GROUND class (luminance-hue family; 'mixed' = no ground on 60% of beats):")
    for g in ["%s-%s" % (l, f) for l in lums for f in fams] + ["mixed"]:
        ua = [s for s, v in a if v == g]
        ur = [s for s, v in r_ if v == g]
        if g == "dark-coolneutral" and dark_n > DARK_COUNT_MAX:
            tag = "BLOCKED"
        elif g == "dark-coolneutral" and dark_n == DARK_COUNT_MAX:
            tag = "LAST-SLOT"
        else:
            tag = "FREE" if not ua and not ur else "in use"
        L.append("  %-18s %-8s approved: %-22s reserved: %s%s" % (g, tag, ",".join(ua) or "-", ",".join(ur) or "-",
                 ("   (R3: %d dark navy/charcoal already in approved+reserved, max %d)" % (dark_n, DARK_COUNT_MAX)) if tag == "BLOCKED" else
                 ("   (R3: %d dark already; the next dark short makes it %d: reserve it now or pick another class)" % (dark_n, dark_n + 1)) if tag == "LAST-SLOT" else ""))
    for title, enum, ka in (("WORLD family", P["world"]["properties"]["world_family"]["enum"], "world_family"),
                            ("HERO device", P["hero_device"]["enum"], "hero_device")):
        a, r_ = used(ka, ka)
        free = [v for v in enum if v not in {x for _, x in a} | {x for _, x in r_}]
        busy = ["%s x%d (%s)" % (v, len(ids), ",".join(ids)) for v, ids in
                sorted({v: [s for s, x in a + r_ if x == v] for v in {x for _, x in a + r_ if x}}.items(), key=lambda kv: -len(kv[1]))]
        L.append("%s FREE now: %s" % (title, ", ".join(free) or "none"))
        L.append("%s in use: %s" % (" " * len(title), "; ".join(busy) or "-"))
    L.append("Pick FREE classes, then reserve them before building: python3 tools/concept_reserve.py reserve %s --ground <class> --world <family> --hero <device>"
             % (ID or "<ID>"))
    L.append("(a concept_check PASS also locks your full concept.json into the reservation registry)")
    return "\n".join(L)


def menu(T=None, n=WINDOW_N, exclude=None):
    """what the last n approved shorts use on each axis, and which enum values NONE of them uses (the free choices)."""
    T = T or datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    sch = load_schema()
    win, missing = window_for(exclude, T, n)
    P = sch["properties"]
    enums = {"world_family": P["world"]["properties"]["world_family"]["enum"], "hero_device": P["hero_device"]["enum"],
             "hook_mechanic": P["hook_mechanic"]["enum"], "signature": P["signature"]["properties"]["mechanism"]["enum"],
             "camera": P["camera"]["enum"], "source_presentation": P["source_presentation"]["enum"]}
    L = ["window at %s: %s" % (T, " ".join("%s(%s)" % (sid, ax) for sid, ax in
                                          [(sid, "%s/%s" % (c["world"]["world_family"], ground_axis(c))) for sid, _, c in win]))]
    if missing:
        L.append("  (approved but without a concept.json, not counted: %s)" % ", ".join(missing))
    for ax, vals in enums.items():
        used = {}
        for sid, _, c in win:
            used.setdefault(axes_of(c)[ax], []).append(sid)
        L.append("%-20s used: %s" % (ax, "; ".join("%s x%d" % (v, len(ids)) for v, ids in sorted(used.items(), key=lambda kv: -len(kv[1])))))
        L.append("%-20s FREE: %s" % ("", ", ".join(v for v in vals if v not in used) or "none"))
    gb = {}
    for sid, _, c in win:
        gb.setdefault(ground_axis(c), []).append(sid)
    L.append("%-20s used: %s" % ("ground", "; ".join("%s x%d" % (v, len(ids)) for v, ids in sorted(gb.items(), key=lambda kv: -len(kv[1])))))
    dh = {}
    for sid, _, c in win:
        dh.setdefault(dominant_hue(c["palette"]), []).append(sid)
    L.append("%-20s used: %s   (a new short may share one with at most %d)" % ("dominant palette hue", "; ".join("%s x%d" % (v, len(ids)) for v, ids in sorted(dh.items(), key=lambda kv: -len(kv[1]))), PALETTE_SHARE_MAX))
    dark = [sid for sid, _, c in win if is_dark_cool(c)]
    L.append("dark navy/charcoal grounds in the window: %d (%s). %s" % (len(dark), ",".join(dark) or "-",
             "A dark navy/charcoal ground FAILS R3 now." if len(dark) > DARK_COUNT_MAX else "A dark navy/charcoal ground is still allowed."))
    beds = {}
    for sid, _, c in win:
        beds.setdefault(c["bed"]["id"], []).append(sid)
    L.append("beds in the window: " + "; ".join("%s x%d" % (b, len(i)) for b, i in sorted(beds.items(), key=lambda kv: -len(kv[1]))))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("id", nargs="?")
    ap.add_argument("--menu", action="store_true", help="print what the last 10 approved use on each axis and which values are free, then exit")
    ap.add_argument("--at", help="take the window at this time (ISO 8601), default now")
    ap.add_argument("--concept", help="check this file instead of specs/<ID>/concept.json")
    ap.add_argument("--window", type=int, default=WINDOW_N)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-pitch", action="store_true")
    ap.add_argument("--verify-sheet", action="store_true")
    ap.add_argument("--suggest", action="store_true", help="which ground / world / hero classes are free now (approved window + live reservations)")
    a = ap.parse_args()
    if a.suggest:
        print(suggest(a.id, a.at, a.window))
        return
    if a.menu:
        print(menu(a.at, a.window, a.id))
        return
    if not a.id:
        ap.error("an ID is required (or --menu)")
    rep = run(a.id, T=a.at, concept_path=a.concept, n=a.window, do_pitch=not a.no_pitch)
    if a.verify_sheet:
        errs = verify_sheet(a.id)
        rep["checks"].append({"ok": not errs, "level": "FAIL", "name": "sheet matches the declared ground", "detail": "; ".join(errs) or "ground and beats_fraction match the storyboard sheet"})
        finish(rep)
    if not a.at and not a.concept:
        lock_if_pass(a.id, rep)
    print(json.dumps(rep, indent=1) if a.json else render(rep))
    sys.exit(0 if rep["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
