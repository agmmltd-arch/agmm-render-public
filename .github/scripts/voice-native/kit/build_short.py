#!/usr/bin/env python3
"""build_short.py <spec.json> [--skip-images] [--skip-audio] [--parts N]

Turns one short's spec into a complete, sealed HyperFrames render package using the kit's versioned component
library (kit/lib). Nothing is rendered here (laptop rule): the package renders off-Mac via produce.py.

Steps (each writes into kit/out/<ID>/):
  1. validate the spec (components, looks, on-screen text rules: no dashes/middots, nothing that would fit under 42px)
  2. resolve every word reference ("@billion", "@it#3", "@700+0.2", "@gone.end") against the voice's words.json,
     fill every component's default times, derive caption windows and word-synced ink for quotes/documents
  3. images: generate each prompt with ~/.fleet/bin/media image (free Cloudflare backends via auto; never gemini-*, never the local CPU backend),
     keep the media receipt, key cut-outs off green (design-system/tools/key_green.py), downscale to web JPG/PNG
  4. audio: sound cues derived from the beat events (+ spec extras), each SFX placed by its measured onset
     (sound/library.json via sound/mix.py), a bed envelope that obeys Sam's music-gap rule, then a measured
     gap check (bed rises <=3 dB in voice gaps and stays >=10 LU under the voice) that fails the build if breached
  5. project: N part projects (frame-exact windows of one story clock) + static_check + SHA256SUMS -> source.tar.gz
Outputs: out/<ID>/resolved.json, audio/mix.wav, audio/cues.json, audio/gap-check.json, gate/script.txt,
gate/captions-timed.json, build/source.tar.gz (+ .sha256), build/parts.json, BUILD.json (timings + versions)."""
import argparse, difflib, glob, hashlib, json, math, os, re, shutil, subprocess, sys, time

from voice_script_binding import check_voice_script_binding

KIT = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.dirname(KIT)
LIB = os.path.join(KIT, "lib")
SOUND = os.path.join(V2, "sound")
MEDIA = os.path.expanduser("~/.fleet/bin/media")
KEY_GREEN = os.path.join(V2, "design-system/tools/key_green.py")
FPS = 30
LOOKS = {"dossier": 0.66, "newsroom": 0.45, "explainer": 0.58, "cinematic": 0.46, "evidence": 0.56,
         "whitemodel": 0.56, "softui": 0.56, "desktop": 0.78, "chart": 0.55, "opsmap": 0.44}   # hero glyph width (em)
COMPONENTS = {"hook-frame", "entity-card", "big-number-slam", "quote-card", "comparison", "chart", "map", "call-grid",
              "document", "checklist", "cta-card", "statement", "custom", "scene"}
BESPOKE = {"custom", "scene"}          # code written for this short (specs/<ID>/scenes.js)
REGISTRY = os.path.join(KIT, "registry", "images.json")   # sha256 of every image any short has used -> short id
AUDIO_OVERRIDES = os.path.join(KIT, "registry", "audio-overrides")
NO_CAPTIONS = {"statement", "quote-card", "checklist", "cta-card"}   # the picture already is the words
BANNED = ["—", "–", "·", "fictional", "illustrative", "ai-generated", "ai generated"]
MIN_PX = 42


def die(msg):
    sys.exit("build_short: " + msg)


def version():
    return open(os.path.join(LIB, "VERSION")).read().strip()


# ------------------------------------------------------------------ words and references
def norm(w):
    return re.sub(r"[^a-z0-9£$%]", "", str(w).lower())


def load_words(path):
    d = json.load(open(path))
    arr = d["words"] if isinstance(d, dict) else d
    out = []
    for w in arr:
        word = str(w.get("word") or w.get("text") or "").strip()
        if word:
            out.append({"word": word, "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3),
                        "emph": bool(w.get("emph") or w.get("emphasis"))})
    return out


class Resolver:
    REF = re.compile(r"^@(#?[^#+\-.\s]+(?:\.[a-z0-9]+)*?)(?:#(\d+))?(\.end)?([+-]\d+(?:\.\d+)?)?$", re.I)

    def __init__(self, words):
        self.words = words
        self.n = [norm(w["word"]) for w in words]

    def word(self, ref):
        m = re.match(r"^@(.+?)(\.end)?([+-]\d+(?:\.\d+)?)?$", ref)
        if not m:
            die("bad word reference %r" % ref)
        body, end, off = m.group(1), m.group(2), float(m.group(3) or 0)
        if body.startswith("#") and body[1:].isdigit():
            idx = int(body[1:])
        else:
            nth = 1
            if "#" in body:
                body, k = body.rsplit("#", 1)
                nth = int(k)
            key = norm(body)
            hits = [i for i, x in enumerate(self.n) if x == key]
            if len(hits) < nth:
                die("word reference %r: %r occurs %d time(s) in the voice" % (ref, key, len(hits)))
            idx = hits[nth - 1]
        w = self.words[idx]
        return idx, round((w["end"] if end else w["start"]) + off, 3)

    def t(self, v, base=None):
        """numbers are seconds; "@ref" is a word time; "+0.4" is relative to the beat start"""
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.startswith("@"):
            return self.word(v)[1]
        if isinstance(v, str) and re.match(r"^\+\d", v) and base is not None:
            return round(base + float(v[1:]), 3)
        die("cannot resolve time %r" % (v,))


TIME_KEYS = re.compile(r"^(at|.*At|at[A-Z0-9].*|from|to)$")   # 24 Sep: prefix form (atScreening) too; w1 lost time on S29


def resolve_times(obj, R, base):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if TIME_KEYS.match(k) and isinstance(v, list) and all(isinstance(x, (str, int, float)) for x in v):
                out[k] = [R.t(x, base) for x in v]          # 24 Sep: an array of word refs under one ...At key (w2, S33)
            elif TIME_KEYS.match(k) and not isinstance(v, (dict, list)) and v is not None:
                out[k] = R.t(v, base)
            else:
                out[k] = resolve_times(v, R, base)
        return out
    if isinstance(obj, list):
        return [resolve_times(x, R, base) for x in obj]
    return obj


def unresolved_refs(obj, path=""):
    """Any "@word" string left after resolution is a timing the scene will compare as a string, which silently fails
    (the element shows from frame 0). Writers lost hours to this on S29 and S33: list them so the build can fail loudly."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += unresolved_refs(v, path + "." + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += unresolved_refs(v, "%s[%d]" % (path, i))
    elif isinstance(obj, str) and re.match(r"^@[^\s]+$", obj):
        out.append("%s = %r" % (path, obj))
    return out


def sync_text(text, highlight, R, t0, t1):
    """word-synced ink for a quote/document body: align the on-screen words to the spoken words in [t0, t1)"""
    toks = text.split()
    idx = [i for i, w in enumerate(R.words) if t0 - 0.2 <= w["start"] < t1]
    spoken = [R.n[i] for i in idx]
    hl = {norm(h) for h in (highlight or [])}
    sm = difflib.SequenceMatcher(a=[norm(t) for t in toks], b=spoken, autojunk=False)
    times = [None] * len(toks)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            times[a + k] = R.words[idx[b + k]]["start"]
    # interpolate the unspoken words between their spoken neighbours
    known = [(i, t) for i, t in enumerate(times) if t is not None]
    if not known:
        step = (t1 - t0 - 0.4) / max(1, len(toks))
        times = [t0 + 0.2 + i * step for i in range(len(toks))]
    else:
        for i in range(len(toks)):
            if times[i] is None:
                prev = max([k for k in known if k[0] < i], default=None, key=lambda k: k[0])
                nxt = min([k for k in known if k[0] > i], default=None, key=lambda k: k[0])
                if prev and nxt:
                    times[i] = prev[1] + (nxt[1] - prev[1]) * (i - prev[0]) / (nxt[0] - prev[0])
                elif prev:
                    times[i] = prev[1] + 0.12 * (i - prev[0])
                else:
                    times[i] = max(t0, nxt[1] - 0.12 * (nxt[0] - i))
    return [[w, round(t, 3), 1 if norm(w) in hl else 0] for w, t in zip(toks, times)], sum(1 for t in known) / max(1, len(toks))


# ------------------------------------------------------------------ validation of on-screen text
def texts(obj, path=""):
    keys = {"text", "value", "label", "kicker", "name", "role", "title", "source", "mark", "tag", "subject", "year", "prompt"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and (k in keys) and not v.startswith("@"):
                yield path + "." + k, k, v
            elif k == "lines" and isinstance(v, list):
                for i, x in enumerate(v):
                    if isinstance(x, str):
                        yield path + ".lines[%d]" % i, "line", x
                    else:
                        yield from texts(x, path + ".lines[%d]" % i)
            else:
                yield from texts(v, path + "." + k)
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            yield from texts(x, path + "[%d]" % i)


def fit_px(text, width, maxpx, cw):
    return min(maxpx, math.floor(width / (max(1, len(text)) * cw)))


def validate(spec, problems):
    if spec.get("look") not in LOOKS:
        problems.append("look %r is not one of %s" % (spec.get("look"), sorted(LOOKS)))
    cw = LOOKS.get(spec.get("look"), 0.55)
    ids = set()
    for i, b in enumerate(spec.get("beats", [])):
        if b.get("component") not in COMPONENTS:
            problems.append("beat %d: component %r not in the catalogue" % (i, b.get("component")))
        if b.get("id") in ids:
            problems.append("beat %d: duplicate id %r" % (i, b.get("id")))
        ids.add(b.get("id"))
        if i and "start" not in b:
            problems.append("beat %d (%s): needs a start word reference" % (i, b.get("id")))
        for p, k, v in texts({"props": b.get("props", {}), "overlays": b.get("overlays", [])}, "beats[%d]" % i):
            low = v.lower()
            for bad in BANNED:
                if bad in low:
                    problems.append("%s: %r contains %r (OCR reads dashes/middots as dashes; no AI/fictional tags)" % (p, v, bad))
            if k in ("value", "line", "name", "mark") and fit_px(v, 960, 400, cw) < MIN_PX:
                problems.append("%s: %r is too long for one line at >=42px; split it" % (p, v))
    last, first = spec["beats"][-1], spec["beats"][0]
    if last.get("component") != "cta-card" and not (last.get("component") in ("scene", "custom") and last.get("id") == "cta"):
        problems.append("the last beat must be the CTA: a cta-card, or a bespoke scene with id 'cta' (Sam: no final CTA is a failure)")
    if first.get("component") != "hook-frame" and not (first.get("component") in ("scene", "custom") and first.get("id") == "hook"):
        problems.append("the first beat must be the hook: a hook-frame, or a bespoke scene with id 'hook' (frame 0 is the hook)")


MOVES = os.path.join(KIT, "registry", "moves.json")
PRIMS = re.compile(r"\b(AG2?\.(?:tx\.)?[A-Za-z]+|K\.[A-Za-z]+)\s*\(")


def moves_entry(spec):
    """What this short's picture is made of: signature concept, the signature scenes' code hash, transitions, primitives."""
    src = ""
    for f in spec.get("code", []) + spec.get("signature", {}).get("files", []):
        src += open(f if os.path.isabs(f) else os.path.join(KIT, f)).read()
    sig_names = [b.get("props", {}).get("scene") or b.get("props", {}).get("module") for b in spec["beats"] if b.get("signature")]
    bodies = []
    for n in sig_names:
        m = re.search(r'scenes\["%s"\]\s*=\s*function([\s\S]*?)\n  \};' % re.escape(n or ""), src)
        if m:
            bodies.append(re.sub(r"\s+", "", m.group(1)))
    return {"id": spec["id"], "look": spec["look"], "signature_concept": spec.get("signature_concept", ""),
            "signature_code_hash": hashlib.sha256("".join(bodies).encode()).hexdigest()[:16] if bodies else None,
            "transitions": sorted(set(spec.get("transitions", [])) | {b.get("tx") for b in spec["beats"] if b.get("tx")}),
            "primitives": sorted(set(PRIMS.findall(src))), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def variety_check(spec, problems):
    """Sam, 24 Sep 20:15: our own custom animations, micro details, visuals, transitions. Across the 105: a signature
    concept or signature code that repeats one in the last 15 shorts is refused; so is a transition set identical to
    any of the last 10."""
    import difflib
    if spec.get("reproduction_of") or spec.get("composed"):
        return None   # composed shorts: compose.py's novelty rule replaces the code-hash registry (bespoke_report checks it)
    me = moves_entry(spec)
    if not me["signature_concept"]:
        problems.append("signature_concept: one line describing the signature moment (checked against the last 15 shorts)")
    if len(me["transitions"]) < 2:
        problems.append("transitions: list the transition moves this short uses (checked against the last 10 shorts)")
    reg = [e for e in (json.load(open(MOVES)) if os.path.exists(MOVES) else []) if e["id"] != spec["id"]]
    for e in reg[-15:]:
        if me["signature_code_hash"] and e.get("signature_code_hash") == me["signature_code_hash"]:
            problems.append("signature scene code is identical to %s's (last 15): build a new signature" % e["id"])
        if me["signature_concept"] and difflib.SequenceMatcher(None, me["signature_concept"].lower(), e.get("signature_concept", "").lower()).ratio() >= 0.8:
            problems.append("signature concept repeats %s's (last 15): %r" % (e["id"], e.get("signature_concept")))
    for e in reg[-10:]:
        if set(e.get("transitions", [])) == set(me["transitions"]):
            problems.append("transition set is identical to %s's (last 10): %s" % (e["id"], me["transitions"]))
    return me


def register_moves(me):
    reg = [e for e in (json.load(open(MOVES)) if os.path.exists(MOVES) else []) if e["id"] != me["id"]] + [me]
    os.makedirs(os.path.dirname(MOVES), exist_ok=True)
    json.dump(reg, open(MOVES, "w"), indent=1)


def bespoke_report(spec, problems):
    """Sam, 24 Sep ~19:10: 'make sure we aren't reusing everything and genuinely building from scratch, like in those
    references, recreating and multiplying them'. The kit is infrastructure; every production spec must be a bespoke
    recreation of its own reference. Fails the spec when:
      - there is no reference beat map (from gemini_watch + the research breakdown) or a beat does not say which
        reference beat it mirrors;
      - more than 40% of beats are UNMODIFIED catalogue components (a catalogue beat with an `extend` scene counts
        as modified; bespoke = component "scene"/"custom");
      - there is no signature beat built from scratch;
      - any image is not generated for this story (a `src` reuse; hash reuse is caught after generation);
      - fewer than 60% of beats carry a sound design written for them (`sfx` authored on the beat).
    A spec with "reproduction_of" (a kit fidelity test against an existing video) is exempt and says so."""
    beats = spec.get("beats", [])
    n = max(1, len(beats))
    cat = [b["id"] for b in beats if b.get("component") not in BESPOKE and not b.get("extend")]
    rep = {"beats": len(beats), "unmodified_catalogue": len(cat), "unmodified_catalogue_share": round(len(cat) / n, 2),
           "bespoke_or_extended": n - len(cat), "signature_beats": [b["id"] for b in beats if b.get("signature") and (b.get("component") in BESPOKE or b.get("extend"))],
           "authored_sound_share": round(sum(1 for b in beats if b.get("sfx")) / n, 2),
           "reference_beats": len(spec.get("reference_map", {}).get("beats", [])), "mode": "reproduction" if spec.get("reproduction_of") else "production"}
    if spec.get("reproduction_of"):
        return rep
    if spec.get("composed"):
        # root, 29 Sep: a compiled short (tools/compose.py, beats.json -> scenes.js) is NOT hand-built, so the catalogue
        # share and the signature code-hash rules do not apply to it and it may not claim them. It must pass compose's
        # novelty rule instead (>= 1 signature event; no lead part on > 35% of beats; look + world + events new against the
        # last 3 shorts on its platform), re-derived here from specs/<ID>/beats.json rather than trusting the stamp.
        rep["mode"] = "composed"
        try:
            sys.path.insert(0, os.path.join(KIT, "tools"))
            import compose as _compose
            ok, msg = _compose.novelty_gate(spec)
        except Exception as e:   # a missing or broken compiler never lets a compiled spec through
            ok, msg = False, "compose.novelty_gate unavailable: %s" % e
        rep["novelty"] = msg
        if not ok:
            problems.append("COMPOSED SHORT REFUSED (novelty): " + msg)
        return rep   # NOTE for root: the reference_map / mirrors rule is not applied to composed shorts (no free step makes it yet)
    rm = spec.get("reference_map") or {}
    if not rm.get("beats"):
        problems.append("reference_map.beats is empty: watch the reference first (tooling/gemini_watch.py) and map it beat by beat")
    src = rm.get("source")
    if not src or not os.path.exists(src if os.path.isabs(src) else os.path.join(KIT, src)):
        problems.append("reference_map.source must point at the saved gemini_watch output for the reference")
    nref = len(rm.get("beats", []))
    for b in beats:
        m = b.get("mirrors")
        if m is None or not all(isinstance(i, int) and 0 <= i < nref for i in (m if isinstance(m, list) else [m])):
            problems.append("beat %s: 'mirrors' must name the reference beat index(es) it recreates" % b.get("id"))
    # 25 Sep: the final beat must put the audit link on screen (a cta-card shows it by default; a bespoke CTA scene
    # must carry "agmm.co.uk/ai-constraint-audit" in its props) and say what the voice says.
    last = beats[-1] if beats else {}
    if last.get("component") != "cta-card" and "ai-constraint-audit" not in json.dumps(last):
        problems.append("the CTA beat does not show the audit link: use cta-card, or give your CTA scene a prop with "
                        "\"agmm.co.uk/ai-constraint-audit\" and render it on screen")
    if rep["unmodified_catalogue_share"] > 0.40:
        problems.append("%d of %d beats (%.0f%%) are unmodified catalogue components %s; at most 40%% (write scenes, or extend)"
                        % (len(cat), n, 100 * rep["unmodified_catalogue_share"], cat))
    if not rep["signature_beats"]:
        problems.append("no signature beat: mark one bespoke beat \"signature\": true")
    for k, im in spec.get("images", {}).items():
        if im.get("src") or not im.get("prompt"):
            problems.append("image %s: every image is generated fresh for this story (prompt, never src)" % k)
        if not im.get("display_w"):
            problems.append("image %s: declare display_w (the widest it is shown on screen, incl. camera zoom) so upscaling is caught" % k)
    if rep["authored_sound_share"] < 0.60:
        problems.append("only %.0f%% of beats carry authored sfx; write the sound design for at least 60%% of beats" % (100 * rep["authored_sound_share"]))
    return rep


# ------------------------------------------------------------------ component default times + sound events
def fill(beat, R, dur_total):
    c, p, B0, B1 = beat["comp"], beat["props"], beat["from"], beat["to"]
    ev = []   # (t, kind, gain_override, pan)   pan: -1 left .. +1 right, the element's place on screen

    def E(t, kind, g=None, pan=0.0):
        if t is not None and 0 <= t < dur_total:
            ev.append((round(t, 3), kind, g, pan))
    money = lambda s: bool(re.search(r"[£$€]", s or ""))
    if c == "hook-frame":
        E(0.12 if B0 <= 0.05 else B0, "slam")
        if p.get("stamp"):
            p["stamp"].setdefault("at", B0)
            E(p["stamp"]["at"] + 0.16, "stamp")
    elif c == "big-number-slam":
        p.setdefault("at", round(B0 + 0.3, 3))
        p.setdefault("kickerAt", round(B0 + 0.05, 3)); p.setdefault("labelAt", round(p["at"] + 0.45, 3))
        p.setdefault("sourceAt", round(p["at"] + 0.7, 3)); p.setdefault("decoAt", round(B0 + 0.05, 3))
        if p.get("object"):
            p.setdefault("objAt", round(p["at"] + 0.3, 3)); E(p["objAt"], "whoosh")
        if p.get("loss"):
            E(p["at"], "stamp"); E(p["at"] + 0.02, "downer")
        else:
            E(p["at"], "slam")
            if money(p.get("value")):
                E(p["at"] + 0.02, "money")
        if p.get("label"):
            E(p["labelAt"], "whoosh", -10)
        if p.get("deco") and p["deco"] != "none":
            for k in range(3):
                E(p["decoAt"] + 0.25 * k, "paper", -12)
    elif c == "entity-card":
        p.setdefault("at", round(B0 + 0.2, 3)); p.setdefault("roleAt", round(p["at"] + 0.5, 3))
        E(p["at"], "slam")
        if p.get("monogram") or p.get("object"):
            E(B0 + 0.08, "pop")
        if p.get("role"):
            E(p["roleAt"], "whoosh", -11)
    elif c == "quote-card":
        p.setdefault("at", round(B0 + 0.15, 3))
        if p.get("year"):
            p.setdefault("yearAt", round(B0 + 0.1, 3)); E(p["yearAt"], "slam")
        E(p["at"], "paper", -8)
        sync, cover = sync_text(p.get("text", ""), p.get("highlight"), R, B0, B1)
        p["sync"] = sync; beat["_sync_cover"] = round(cover, 2)
    elif c == "statement":
        for i, ln in enumerate(p.get("lines", [])):
            ln.setdefault("at", round(B0 + 0.1 + i * 0.25, 3))
            E(ln["at"], "slam" if i < len(p["lines"]) - 1 else "stamp")
    elif c == "comparison":
        for k, side in (("a", 0), ("b", 1)):
            p[k].setdefault("at", round(B0 + 0.2 + side * 0.4, 3))
            E(p[k]["at"], "pop", None, -0.4 if side == 0 else 0.4); E(p[k]["at"] + 0.15, "slam", -8, -0.3 if side == 0 else 0.3)
    elif c == "chart":
        p.setdefault("at", round(B0 + 0.25, 3))
        E(p["at"], "whoosh", -9)
        for L in p.get("labels", []):
            L.setdefault("at", round(p["at"] + 0.7, 3)); E(L["at"], "pop")
        if p.get("downAt") is not None:
            E(p["downAt"], "downer"); E(p["downAt"] + 0.02, "slam")
        for b in p.get("bars", []):
            pass
        if p.get("kind") == "bars":
            for i, b in enumerate(p.get("bars", [])):
                b.setdefault("at", round(p["at"] + i * 0.3, 3)); E(b["at"], "pop")
    elif c == "map":
        for i, q in enumerate(p.get("places", [])):
            q.setdefault("at", round(B0 + 0.1 + i * 0.6, 3)); E(q["at"], "pop")
        p.setdefault("routeAt", round(B0 + 0.3, 3)); E(p["routeAt"], "whoosh", -8)
        if p.get("title"):
            p.setdefault("titleAt", round(p["routeAt"] + p.get("routeDur", 1.4), 3)); E(p["titleAt"], "slam")
    elif c == "call-grid":
        for i, T in enumerate(p.get("tiles", [])):
            T.setdefault("at", round(B0 + 0.1 + i * 0.25, 3)); E(T["at"], "pop", -9)
            if T.get("tag"):
                T.setdefault("tagAt", round(T["at"] + 0.6, 3)); E(T["tagAt"], "ping", -10)
        if p.get("banner"):
            E(p["banner"]["at"], "slam")
    elif c == "document":
        if B0 > 0.05:
            E(B0, "whoosh", -8)
        if p.get("badge"):
            E(p["badge"]["at"], "pop")
        if p.get("prompt"):
            pr = p["prompt"]; pr.setdefault("dur", 1.5)
            E(pr["at"], "ping", -10)
            for k in range(6):
                E(pr["at"] + 0.15 + k * pr["dur"] / 6, "type")
        if p.get("text"):
            sync, cover = sync_text(p["text"], p.get("highlight"), R, B0, B1)
            p["sync"] = sync; beat["_sync_cover"] = round(cover, 2)
            for k in range(0, len(sync), 4):
                E(sync[k][1], "type", -15)
        if p.get("build"):
            for k in range(3):
                E(p["build"]["at"] + 0.17 * k, "pop", -8)
        if p.get("strike"):
            E(p["strike"]["at"], "slam")
        if p.get("click"):
            E(p["click"]["at"], "click")
        for s in p.get("stickers", []):
            E(s["at"], "slam")
    elif c == "checklist":
        for i, it in enumerate(p.get("items", [])):
            it.setdefault("at", round(B0 + 0.5 + i * 0.8, 3)); it.setdefault("tickAt", round(it["at"] + 0.3, 3))
            E(it["at"], "whoosh", -11); E(it["tickAt"], "tick")
    elif c == "cta-card":
        p.setdefault("at", round(B0 + 0.03, 3)); p.setdefault("pressDelay", 1.5)
        E(p["at"] + 0.65, "pop"); E(p["at"] + p["pressDelay"], "press")
        if p.get("sub"):
            E(p["sub"]["at"], "pop")
    if p.get("syncText"):          # any component / signature can ask for word-synced ink of a spoken line
        sync, cover = sync_text(p["syncText"], p.get("highlight"), R, B0, B1)
        p["sync"] = sync; beat["_sync_cover"] = round(cover, 2)
    for o in beat.get("overlays", []):
        if o.get("type") == "stamp":
            E(o["at"] + 0.16, "stamp")
        elif o.get("type") == "sticker":
            E(o["at"], "slam")
        elif o.get("type") == "object":
            E(o.get("at", B0), "whoosh", -9)
    return ev


SFX_KIND = {  # event kind -> (library categories "a|b" or "=exact id", default gain dB)
    # 25 Sep sound upgrade (Sam: "give all the sound design some upgrades"): impacts are layered kits (sub + body +
    # transient on one onset), objects get real Foley (paper, stamps, keys, coins, clicks), risers and reverse swells
    # land their PEAK on the event. The v1 categories stay in the library for exact ids and old reproductions.
    "slam": ("impact_layered|impact_soft", -5), "stamp": ("foley_stamp", -3), "money": ("foley_cash|cash_register_coins", -6),
    "downer": ("downer", -4), "whoosh": ("whoosh_air|whoosh", -9), "seam": ("whoosh_air|swoosh_transition", -8),
    "pop": ("ui_pop|foley_click", -8), "tick": ("foley_click", -6), "type": ("foley_keyboard", -13),
    "ping": ("notification_ping", -10), "click": ("foley_click|mouse", -6), "press": ("=ui_click_04", -3),
    "paper": ("foley_paper|paper_page", -11), "riser": ("riser_short", -9), "swell": ("reverse_swell", -9),
    "sub": ("impact_sub", -8), "hit": ("impact_body", -6), "coin": ("foley_cash", -8), "counter": ("foley_cash", -9),
    "printer": ("foley_printer", -10), "phone": ("foley_phone", -12), "shutter": ("camera_shutter", -8),
    "drone": ("subtle_drones", -14), "heartbeat": ("heartbeat_ticktock", -10),
}
PEAK_ANCHOR = ("riser_short", "reverse_swell", "riser", "reverse_cymbal")   # the peak lands on the event
MAX_CUE_S = {"heartbeat_ticktock": 2.5, "subtle_drones": 3.0, "riser": 2.5, "crowd_room_tone": 3.0}  # long files cut
BANNED_SOUND = re.compile(r"glitch|zap|electric|buzz", re.I)
# density: 10-20 designed sound events a minute, at most 3 sounding at once (Sam's immersive-but-under-the-voice rule).
# Layers inside 0.12 s are one event; a same-category run with gaps <= 0.35 s is one gesture (sound/audit_sound.py).
PRIORITY = {"spec": 3, "authored": 3, "slam": 2, "stamp": 2, "money": 2, "downer": 2, "riser": 2, "swell": 2, "sub": 2,
            "hit": 2, "press": 2, "coin": 2, "counter": 2, "printer": 2, "phone": 2, "seam": 1, "whoosh": 1}


def sound_events(cues, lib):
    ev = []
    for c in sorted(cues, key=lambda c: c["t"]):
        cat = lib[c["sfx_id"]]["category"]
        if ev and (c["t"] - ev[-1]["last"] <= 0.12 or (cat == ev[-1]["cat"] and c["t"] - ev[-1]["last"] <= 0.35)):
            ev[-1]["cues"].append(c); ev[-1]["last"] = c["t"]
        else:
            ev.append({"t": c["t"], "last": c["t"], "cat": cat, "cues": [c]})
    for e in ev:
        e["prio"] = max(PRIORITY.get(c["event"], 0) for c in e["cues"])
        spans = [(c["t"], c["t"] + min(float(lib[c["sfx_id"]].get("duration_s") or 0.3), float(c.get("max_s") or 99))) for c in e["cues"]]
        e["span"] = (min(a for a, _ in spans), max(b for _, b in spans))
    return ev


def thin_sound(cues, lib, dur, log):
    """Keep the design inside 10-20 events a minute and <= 3 overlapping, dropping the least important and most
    crowded events first (authored cues outrank derived ones). Every drop is logged in audio/thinned.json."""
    ev = sound_events(cues, lib)

    def overlap_peak(ev):
        pts = sorted([(e["span"][0], 1, i) for i, e in enumerate(ev)] + [(e["span"][1], -1, i) for i, e in enumerate(ev)])
        cur, best, live, at = 0, 0, set(), set()
        for t, d, i in pts:
            if d > 0:
                live.add(i)
            else:
                live.discard(i)
            if len(live) > best:
                best, at = len(live), set(live)
        return best, at

    while True:
        peak, at = overlap_peak(ev)
        if peak <= 3:
            break
        i = min(at, key=lambda i: (ev[i]["prio"], -ev[i]["t"]))
        log.append({"t": ev[i]["t"], "cues": [c["sfx_id"] for c in ev[i]["cues"]], "why": "overlap %d > 3" % peak})
        ev.pop(i)
    # r3 (25 Sep 22:40): check 15 wants 20-60 events a minute (P2 runs ~60); thinning to 20 made every build fail it
    while len(ev) / (dur / 60.0) > 60.0:
        def crowd(i):
            g = [abs(ev[i]["t"] - ev[j]["t"]) for j in (i - 1, i + 1) if 0 <= j < len(ev)]
            return min(g) if g else 99
        i = min(range(len(ev)), key=lambda i: (ev[i]["prio"], crowd(i)))
        log.append({"t": ev[i]["t"], "cues": [c["sfx_id"] for c in ev[i]["cues"]], "why": "density over 60 events/min"})
        ev.pop(i)
    return [c for e in ev for c in e["cues"]], ev


def pan_of(x):
    """an element's horizontal position on the 1080-wide frame (px, or 0..1) -> pan -0.7..0.7"""
    if x is None:
        return 0.0
    x = float(x)
    f = x / 1080.0 if x > 1.0 else x
    return round(max(-0.7, min(0.7, (f - 0.5) * 1.4)), 2)


def apply_audio_overrides(sid, cues, adir, path=None):
    """Apply narrow, reviewable sound-only corrections without invalidating the visual storyboard.

    Each row must bind the exact cue time, SFX id and previous pan.  A stale, broad or ambiguous
    override fails the build instead of silently touching a different event.  The input file and
    applied receipt live outside specs/<ID>, because these values affect the mix only, never pixels.
    """
    p = path or os.path.join(AUDIO_OVERRIDES, sid + ".json")
    if not os.path.exists(p):
        return []
    doc = json.load(open(p))
    rows = doc.get("cues", [])
    if not isinstance(rows, list) or not rows:
        die("audio override %s must contain a non-empty cues list" % p)
    applied = []
    for row in rows:
        try:
            t, old = float(row["t"]), float(row["from_pan"])
            sfx_id, reason = str(row["sfx_id"]), str(row["reason"]).strip()
        except (KeyError, TypeError, ValueError):
            die("audio override row is incomplete: %r" % row)
        drop = row.get("drop") is True
        if drop == ("pan" in row):
            die("audio override for %s@%.4f must set exactly one of pan or drop=true" % (sfx_id, t))
        new = None if drop else float(row["pan"])
        if (new is not None and not -0.7 <= new <= 0.7) or not reason:
            die("audio override for %s@%.4f needs pan -0.7..0.7 or drop=true, plus a reason" % (sfx_id, t))
        matches = [c for c in cues if c.get("sfx_id") == sfx_id and abs(float(c.get("t", -999)) - t) <= 0.001]
        if len(matches) != 1:
            die("audio override for %s@%.4f matched %d cues (expected exactly one)" % (sfx_id, t, len(matches)))
        cue = matches[0]
        if abs(float(cue.get("pan", 0)) - old) > 0.001:
            die("audio override for %s@%.4f expected old pan %.2f, found %.2f" % (sfx_id, t, old, cue.get("pan", 0)))
        if drop:
            cues.remove(cue)
            applied.append({"t": t, "sfx_id": sfx_id, "from_pan": old, "drop": True, "reason": reason})
        else:
            cue["pan"] = round(new, 2)
            applied.append({"t": t, "sfx_id": sfx_id, "from_pan": old, "pan": round(new, 2), "reason": reason})
    os.makedirs(adir, exist_ok=True)
    receipt = {"source": p, "source_sha256": hashlib.sha256(open(p, "rb").read()).hexdigest(), "applied": applied}
    json.dump(receipt, open(os.path.join(adir, "audio-override-receipt.json"), "w"), indent=1)
    return applied


def pick_sfx(events, lib, extras):
    cats, byid = {}, {}
    for it in lib["items"]:
        cats.setdefault(it["category"], []).append(it["id"]); byid[it["id"]] = it
    for k in cats:
        cats[k].sort()
    cues, last, used = [], {}, {}
    for ev in sorted(events, key=lambda e: e[0]):
        t, kind, g = ev[0], ev[1], ev[2]
        pan = ev[3] if len(ev) > 3 else 0.0
        src, g0 = SFX_KIND.get(kind, (kind, -8))
        if src.startswith("="):
            sid = src[1:]
        else:
            ids = [i for c in src.split("|") for i in cats.get(c, [])]
            if not ids:
                die("no SFX in category %r" % src)
            n = used.get(src, 0); sid = ids[(n * 5 + int(t * 7)) % len(ids)]      # round robin over every take
            if last.get(src) == sid:
                sid = ids[(ids.index(sid) + 1) % len(ids)]
            used[src] = n + 1; last[src] = sid
        cues.append({"t": t, "sfx_id": sid, "gain_db": g if g is not None else g0, "event": kind, "pan": pan})
    for x in extras:
        sid = x["sfx"]
        if sid in cats:
            sid = cats[sid][int(x["t"] * 7) % len(cats[sid])]
        cues.append({"t": x["t"], "sfx_id": sid, "gain_db": x.get("gain", -8), "event": "spec", "pan": x.get("pan", 0.0)})
    for c in cues:
        if c["sfx_id"] not in byid:
            die("unknown sfx id %r (not in sound/library.json)" % c["sfx_id"])
        cat = byid[c["sfx_id"]]["category"]
        # frame-exact: the scene event shows on frame round(t * FPS); the sound's onset (or peak) lands on that frame
        c["event_t"] = round(round(c["t"] * FPS) / FPS, 4)
        c["t"] = c["event_t"]
        c["anchor"] = "peak" if cat in PEAK_ANCHOR else "onset"
        if cat in MAX_CUE_S:
            c["max_s"] = MAX_CUE_S[cat]
        c["category"] = cat
    # Banned sounds (Sam, 25 Sep, on the published Builder.ai short): "this loud electrical repeating noise in some
    # parts... it's not that good of a sound bite... just make from now on". The glitch family (glitch_01..08, 0.1 s
    # digital zaps, often fired in pairs) is out. Posted videos stay as they are; every new build refuses them.
    bad = [c for c in cues if BANNED_SOUND.search(str(c["sfx_id"])) or BANNED_SOUND.search(str(c["event"]))
           or BANNED_SOUND.search(c.get("category", ""))]
    if bad:
        die("banned sound: %s at %s s. Sam rejected the glitch/electrical zap (25 Sep). Design a sound that belongs to "
            "the on-screen event instead (paper, a stamp, a click, a real-world foley), per CRAFT-STANDARD section 6."
            % (bad[0]["sfx_id"], bad[0]["t"]))
    # thin collisions: same category inside 80 ms keeps the first
    cues.sort(key=lambda c: c["t"])
    out = []
    for c in cues:
        if any(abs(c["t"] - o["t"]) < 0.08 and o["category"] == c["category"] for o in out[-4:]):
            continue
        out.append(c)
    # Effect ceiling (root, 24 Sep 23:15). Sam flagged loud sound design on P1 and S11: specs put hits at 0 to -5 dB and
    # stacked 4-5 impacts inside 0.6 s. Every effect is capped at -12 dB, and from the 3rd hit inside any 0.6 s window the
    # rest drop to -16 dB. With this, S11 went from gate check 13 FAIL (+9.4 / +5.0 dB) to PASS (+7.2 / +0.5).
    HIT = ("impact", "slam", "stamp", "hit", "boom", "thud")
    for c in out:
        if c["gain_db"] > -12:
            c["gain_db"] = -12
    hits = [c for c in out if any(h in c["sfx_id"] or h in str(c["event"]) for h in HIT)]
    for i, c in enumerate(hits):
        if sum(1 for o in hits[:i] if c["t"] - o["t"] <= 0.6) >= 2:
            c["gain_db"] = min(c["gain_db"], -16)
    return out


# ------------------------------------------------------------------ audio: bed envelope with the music-gap rule
def run(cmd, **kw):
    p = subprocess.run(["nice", "-n", "15"] + cmd, capture_output=True, text=True, **kw)
    if p.returncode:
        print(p.stdout[-1500:], p.stderr[-1500:])
        die("command failed: %s" % " ".join(cmd[:4]))
    return p


def ffdur(path):
    import os
    if os.environ.get("FLEET_NO_LOCAL_MEDIA") == "1":
        return 0.0
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip())


def speech_segments(words, join=0.25):
    segs = []
    for w in words:
        if segs and w["start"] - segs[-1][1] <= join:
            segs[-1][1] = w["end"]
        else:
            segs.append([w["start"], w["end"]])
    return segs


def bed_envelope(words, dur, music, bed_lufs):
    """Bed gain curve in dB, sampled every 50 ms. Under speech the bed sits `under_lu` (default 15) LU below the voice;
    in a voice gap it may rise at most gap_rise_db (<=3 dB: Sam, 24 Sep, 'the bed must not jump up in the pauses');
    before the first word / after the last it may sit up to +3 dB; designed swells (the lesson, the CTA) are capped at
    +3 dB; drops go as low as the spec says (a near-silence beat). Slew-limited so nothing pumps."""
    voice_lufs = music.get("voice_lufs", -18.0)
    base = (voice_lufs - music.get("under_lu", 16.0)) - bed_lufs
    rise = min(3.0, music.get("gap_rise_db", 2.0))
    segs = speech_segments(words)
    first, last = segs[0][0], segs[-1][1]
    step = 0.05
    n = int(dur / step) + 2
    lvl = []
    for k in range(n):
        t = k * step
        if t < first - 0.12:
            v = base + min(3.0, music.get("intro_db", 2.0))
        elif t > last + 0.15:
            v = base + min(3.0, music.get("outro_db", 3.0))
        elif any(a - 0.12 <= t <= b + 0.15 for a, b in segs):
            v = base
        else:
            v = base + rise
        for s in music.get("swells", []):
            if s["from"] <= t <= s["to"]:
                v = max(v, base + min(3.0, s.get("db", 3.0)))
        for tr in music.get("trims", []):     # local trims added by the gap-rule loop
            if tr["from"] <= t <= tr["to"]:
                v += tr["db"]
        for d in music.get("drops", []):
            if d["from"] <= t <= d["to"]:
                v = base + d.get("db", -18.0)
        lvl.append(v)
    out = [lvl[0]]
    for v in lvl[1:]:                       # slew limit: up 30 dB/s, down 60 dB/s
        p = out[-1]
        out.append(min(v, p + 1.5) if v > p else max(v, p - 3.0))
    fade0 = int(max(0, dur - 0.6) / step)
    for k in range(fade0, n):               # tail fade
        out[k] = out[fade0] + (-40.0 - out[fade0]) * min(1.0, (k - fade0) * step / 0.6)
    return base, [(round(k * step, 3), round(v, 2)) for k, v in enumerate(out)]


def apply_envelope(src_wav, dst_wav, env):
    import numpy as np, wave
    with wave.open(src_wav, "rb") as w:
        ch, sw, sr, nf = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(nf), dtype=np.int16).reshape(-1, ch).astype(np.float32)
    ts = np.arange(x.shape[0]) / sr
    g = 10 ** (np.interp(ts, [e[0] for e in env], [e[1] for e in env]) / 20.0)
    y = np.clip(x * g[:, None], -32768, 32767).astype(np.int16)
    with wave.open(dst_wav, "wb") as w:
        w.setnchannels(ch); w.setsampwidth(2); w.setframerate(sr); w.writeframes(y.tobytes())


def momentary(path):
    """momentary loudness (400 ms) every 100 ms: [(t, M)]"""
    p = subprocess.run(["nice", "-n", "15", "ffmpeg", "-nostats", "-hide_banner", "-threads", "2", "-i", path, "-af",
                        "ebur128=metadata=1,ametadata=print:key=lavfi.r128.M", "-f", "null", "-"], capture_output=True, text=True)
    out, t = [], None
    for line in (p.stdout + p.stderr).splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            t = float(m.group(1))
        m = re.search(r"lavfi\.r128\.M=(-?[0-9.]+|-inf)", line)
        if m and t is not None:
            out.append((t, float(m.group(1)) if m.group(1) != "-inf" else -120.0))
    return out


def gap_check(words, bed_path, voice_path, music):
    """Sam's rule, measured: in the 3 longest voice gaps the bed may rise at most ~3 dB from its ducked level and must
    stay at least ~10 LU under the voice. Designed swells (spec music.swells) are excluded, as the rule allows."""
    segs = speech_segments(words)
    swells = music.get("swells", [])
    gaps = []
    for a, b in zip(segs, segs[1:]):
        g0, g1 = a[1], b[0]
        if g1 - g0 >= 0.4 and not any(s["from"] - 0.5 <= g0 <= s["to"] for s in swells):
            gaps.append((g1 - g0, g0, g1, a))
    gaps.sort(reverse=True)
    bedM, voiceM = momentary(bed_path), momentary(voice_path)

    def at(series, t):
        return min(series, key=lambda x: abs(x[0] - t))[1]

    rows, ok = [], True
    for length, g0, g1, seg in gaps[:3]:
        mid = (g0 + g1) / 2 + 0.2          # M covers the previous 400 ms, so sample 0.2 s past the middle
        b_gap = at(bedM, min(mid, g1))
        sp0, sp1 = max(seg[0], seg[1] - 1.2), seg[1]
        b_speech = max(x[1] for x in bedM if sp0 + 0.4 <= x[0] <= sp1) if any(sp0 + 0.4 <= x[0] <= sp1 for x in bedM) else at(bedM, sp1)
        v_speech = max(x[1] for x in voiceM if sp0 + 0.4 <= x[0] <= sp1 + 0.05) if any(sp0 + 0.4 <= x[0] <= sp1 + 0.05 for x in voiceM) else at(voiceM, sp1)
        rise, under = round(b_gap - b_speech, 2), round(v_speech - b_gap, 2)
        good = rise <= 3.0 and under >= 10.0
        ok &= good
        rows.append({"gap": [round(g0, 2), round(g1, 2)], "len_s": round(length, 2), "bed_M_gap": b_gap, "bed_M_speech_before": b_speech,
                     "voice_M_speech_before": v_speech, "rise_db": rise, "bed_under_voice_lu": under, "pass": good})
    return {"rule": "bed rises <=3 dB in a voice gap and stays >=10 LU under the voice (Sam, 24 Sep)", "gaps": rows, "pass": bool(ok and rows)}


# ------------------------------------------------------------------ images
def make_image(key, im, img_dir, rec_dir):
    os.makedirs(img_dir, exist_ok=True); os.makedirs(rec_dir, exist_ok=True)
    cut = im.get("cutout", False)
    final = os.path.join(img_dir, key + (".png" if cut else ".jpg"))
    receipt = os.path.join(rec_dir, key + ".receipt.json")
    want = hashlib.sha256(json.dumps(im, sort_keys=True).encode()).hexdigest()[:16]
    if os.path.exists(final) and os.path.exists(receipt) and json.load(open(receipt)).get("spec_hash") == want:
        return json.load(open(receipt))
    from PIL import Image
    t0 = time.time()
    if im.get("src"):
        raw = im["src"] if os.path.isabs(im["src"]) else os.path.join(V2, im["src"])
        rec = {"key": key, "source": "existing file", "path": raw, "sha256": hashlib.sha256(open(raw, "rb").read()).hexdigest()}
    else:
        raw = os.path.join(rec_dir, key + ".raw.png")
        prompt = im["prompt"]
        if cut:
            prompt += " Isolated single object on a completely flat pure chroma green (#00ff00) background, no shadow on the background, no other objects."
        # remote backends only, in order (flux-local is a 24-minute CPU job on this Mac: never)
        # Root, 24 Sep 23:40: the old default fell back to the PAID gemini image backends when a spec gave no backend
        # (9 images, $0.94 billed to Adam's card before w6 caught it). Free Cloudflare backends only; a spec naming a
        # gemini-* backend is refused.
        if str(im.get("backend", "")).startswith("gemini"):
            die("image %s asks for the paid backend %r; use auto (free Cloudflare FLUX.2)" % (key, im["backend"]))
        for backend in (["auto"] if im.get("backend") in (None, "", "auto") else [im["backend"]]):
            cmd = [MEDIA, "image", "--prompt", prompt, "--out", raw, "--aspect", im.get("aspect", "9:16" if not cut else "1:1"), "--backend", backend,
                   "--size", im.get("size", "2K")]
            p = subprocess.run(cmd, capture_output=True, text=True)
            if p.returncode == 0 and os.path.exists(raw):
                break
            print("image %s: %s failed (%s), trying the next backend" % (key, backend, (p.stderr or p.stdout).strip()[-160:]))
        if p.returncode or not os.path.exists(raw):
            die("image %s failed on every remote backend: %s" % (key, (p.stderr or p.stdout)[-600:]))
        rec = {"key": key, "source": "media image", "prompt": prompt, "cmd": cmd[:2] + ["--aspect", cmd[7], "--backend", cmd[9]],
               "sha256": hashlib.sha256(open(raw, "rb").read()).hexdigest()}
        try:   # the fleet's own receipt line for this file
            for line in reversed(open(os.path.expanduser("~/.fleet/media.jsonl")).read().splitlines()[-50:]):
                r = json.loads(line)
                if r.get("path") == raw:
                    rec["media_receipt"] = r; break
        except Exception:
            pass
    if cut and not im.get("src"):
        keyed = os.path.join(rec_dir, key + ".keyed.png")
        subprocess.run(["python3", KEY_GREEN, raw, keyed], check=True, capture_output=True)
        img = Image.open(keyed)
    else:
        img = Image.open(raw)
    # native sharpness (Sam, 24 Sep): images are generated at 2K and only ever DOWNscaled; never upscaled.
    w = im.get("width", 2400)
    if img.width > w:
        img = img.resize((w, round(img.height * w / img.width)), Image.LANCZOS)
    need = im.get("display_w")          # the widest this image is ever shown on screen (px at 1080x1920, incl. camera zoom)
    if need and img.width < need:
        die("image %s is %dpx wide but is displayed at up to %dpx: it would be upscaled (blurry). Generate larger or show it smaller." % (key, img.width, need))
    if final.endswith(".jpg"):
        img.convert("RGB").save(final, "JPEG", quality=88)
    else:
        img.save(final, "PNG", optimize=True)
    rec.update({"final": final, "final_sha256": hashlib.sha256(open(final, "rb").read()).hexdigest(), "spec_hash": want,
                "seconds": round(time.time() - t0, 1)})
    json.dump(rec, open(receipt, "w"), indent=1)
    return rec


# ------------------------------------------------------------------ project + package
def bespoke_image_dependencies(spec, sig_files, out):
    """Resolve literal image dependencies in shipped scene code, including dated source crops."""
    refs = set()
    for source in sig_files:
        refs.update(re.findall(r'''['"](img/[^'"\s?#]+)['"]''', open(source).read()))
    assets = {}
    for ref in sorted(refs):
        relative = ref[4:]
        if os.path.isabs(relative) or ".." in relative.split("/"):
            die("unsafe bespoke image reference: " + ref)
        if os.path.splitext(relative)[1].lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}:
            die("unsupported bespoke image reference: " + ref)
        candidates = [os.path.join(out, "img", relative),
                      os.path.join(KIT, "out", "_mB-archive", spec["id"], "img", relative),
                      os.path.join(KIT, "media", spec["id"], "final", relative)]
        source = next((path for path in candidates if os.path.isfile(path)), None)
        if source is None:
            die("missing bespoke image dependency %s (checked %s)" % (ref, ", ".join(candidates)))
        assets[ref] = source
    return assets


HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=1080, height=1920" />
<title>AGMM {id} ({look}) part {part}</title>
<link rel="stylesheet" href="ds/kit.css" />
<link rel="stylesheet" href="ds2/kit2.css" />
<link rel="stylesheet" href="kit3.css" />
<script src="ds/vendor/gsap.min.js"></script>
<script src="ds/kit.js"></script>
<script src="ds2/kit2.js"></script>
{extra_js}<script src="kit3.js"></script>
<script src="spec.js"></script>
{sig_js}</head>
<body>
<div id="root" data-composition-id="{id}" data-look="{look}" data-start="0" data-width="1080" data-height="1920" data-duration="{pdur}">
  <div class="ag-stage"></div>
</div>
<script>window.AGK_PART = {{ off: {off}, dur: {pdur} }}; AGK.run(window.AGK_SPEC);</script>
</body>
</html>
"""

STATIC_CHECK = r'''import pathlib, re
root = pathlib.Path(__file__).parent
bad = [p for p in root.rglob('*') if p.suffix.lower() in {'.mp4', '.mov', '.wav', '.mp3', '.webm'}]
assert not bad, f"media leaked into source package: {bad}"
t = (root / 'index.html').read_text()
assert 'data-composition-id' in t and 'data-duration' in t
refs = set(re.findall(r'(?:src|href)="([^"]+)"', t))
missing = [r for r in refs if not (root / r).exists()]
assert not missing, f"referenced files missing: {missing}"
spec = (root / 'spec.js').read_text()
code = spec + '\n' + '\n'.join(p.read_text() for p in (root / 'sig').glob('*.js'))
imgs = set(re.findall(r"""['"](img/[^'"\s?#]+)['"]""", code))
assert all((root / i).exists() for i in imgs), [i for i in imgs if not (root / i).exists()]
print('static_check OK', len(list(root.rglob('*'))), 'entries')
'''


def build_project(spec, rs, out, parts):
    bdir = os.path.join(out, "build"); pkg = os.path.join(bdir, "pkg")
    uses_map = any(b["comp"] == "map" for b in rs["beats"]) or "map" in spec.get("needs", [])
    sig_files = []
    for s in spec.get("signature", {}).get("files", []) + spec.get("code", []):
        sig_files.append(s if os.path.isabs(s) else os.path.join(KIT, s))
    image_dependencies = bespoke_image_dependencies(spec, sig_files, out)
    shutil.rmtree(bdir, ignore_errors=True); os.makedirs(pkg)
    frames = int(round(rs["dur"] * FPS))
    per = int(math.ceil(frames / parts))
    windows = []
    for k in range(parts):
        f0, f1 = k * per, min(frames, (k + 1) * per)
        if f1 > f0:
            windows.append((chr(97 + k), f0 / FPS, (f1 - f0) / FPS))
    for name, off, pdur in windows:
        P = os.path.join(pkg, "%s-%s" % (spec["id"].lower(), name))
        os.makedirs(P)
        shutil.copytree(os.path.join(LIB, "ds"), os.path.join(P, "ds"), ignore=shutil.ignore_patterns("map.js", "coins3d.js", "*.DS_Store"))
        if uses_map:
            shutil.copy(os.path.join(LIB, "ds/map.js"), os.path.join(P, "ds/map.js"))
        shutil.copytree(os.path.join(LIB, "ds2"), os.path.join(P, "ds2"), ignore=shutil.ignore_patterns("white3d.js", "*.DS_Store"))
        # fonts: ship only the families the look uses (keeps the package small)
        shutil.copy(os.path.join(LIB, "kit3.js"), P); shutil.copy(os.path.join(LIB, "kit3.css"), P)
        shutil.copy(os.path.join(LIB, "VERSION"), os.path.join(P, "KIT_VERSION"))
        shutil.copytree(os.path.join(out, "img"), os.path.join(P, "img")) if os.path.isdir(os.path.join(out, "img")) else os.makedirs(os.path.join(P, "img"))
        for ref, source in image_dependencies.items():
            target = os.path.join(P, ref)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
        os.makedirs(os.path.join(P, "sig"), exist_ok=True)
        for f in sig_files:
            shutil.copy(f, os.path.join(P, "sig", os.path.basename(f)))
        open(os.path.join(P, "spec.js"), "w").write("window.AGK_SPEC = " + json.dumps(rs, indent=0) + ";\n")
        html = HTML.format(id=rs["id"], look=rs["look"], part=name, pdur="%.3f" % pdur, off="%.3f" % off,
                           extra_js='<script src="ds/map.js"></script>\n' if uses_map else "",
                           sig_js="".join('<script src="sig/%s"></script>\n' % os.path.basename(f) for f in sig_files))
        open(os.path.join(P, "index.html"), "w").write(html)
        open(os.path.join(P, "static_check.py"), "w").write(STATIC_CHECK)
        r = subprocess.run(["python3", "static_check.py"], cwd=P, capture_output=True, text=True)
        if r.returncode:
            die("static check failed in %s: %s" % (name, r.stderr[-800:]))
        files = sorted(os.path.relpath(os.path.join(d, f), P) for d, _, fs in os.walk(P) for f in fs if f != "SHA256SUMS.txt" and f != ".DS_Store")
        with open(os.path.join(P, "SHA256SUMS.txt"), "w") as fh:
            for f in files:
                fh.write("%s  ./%s\n" % (hashlib.sha256(open(os.path.join(P, f), "rb").read()).hexdigest(), f))
    tar = os.path.join(bdir, "source.tar.gz")
    env = dict(os.environ, COPYFILE_DISABLE="1")
    subprocess.run(["tar", "--no-xattrs", "-czf", tar, "-C", pkg, "."], check=True, env=env)
    sha = hashlib.sha256(open(tar, "rb").read()).hexdigest()
    open(tar + ".sha256", "w").write(sha + "\n")
    parts_meta = [{"look": "%s-%s" % (spec["id"].lower(), n), "file": "index.html", "out": "%s-%s" % (spec["id"], n.upper()), "off": off, "dur": pdur}
                  for n, off, pdur in windows]
    json.dump({"parts": parts_meta, "sha256": sha, "bytes": os.path.getsize(tar), "frames": frames}, open(os.path.join(bdir, "parts.json"), "w"), indent=1)
    return tar, sha, parts_meta


# ------------------------------------------------------------------ main
def voice_word_guard(vpath):
    """Root, 24 Sep: the voice runner keeps a paragraph after 3 failed ASR word checks (asr_match False) and nothing
    blocked it; S11 shipped "KMP" for KNP and "getting" for "guessing" into a finished render. Every failed paragraph
    must be confirmed CLEAN by the independent second transcriber (shorts/voice/tooling/asr_triage.py) or regenerated."""
    vdir = os.path.dirname(vpath); sid = os.path.basename(vdir)
    binding, reason = check_voice_script_binding(sid, vdir, V2)
    if binding == "REFUSE":
        die("VOICE SOURCE BINDING: %s" % reason)
    failed = []
    for rp in sorted(glob.glob(os.path.join(vdir, "P*.receipt.json"))):
        if json.load(open(rp)).get("asr_match") is False:
            failed.append(os.path.basename(rp).split(".")[0])
    if not failed:
        return
    tri_p = os.path.join(os.path.dirname(vdir), "ASR-TRIAGE.json")
    tri = json.load(open(tri_p)).get(sid, {}) if os.path.exists(tri_p) else {}
    bad = [p for p in failed if tri.get(p, {}).get("verdict") != "CLEAN"]
    if bad:
        die("VOICE WORD GUARD: %s paragraph(s) %s failed the ASR word check and are not confirmed CLEAN by asr_triage.py "
            "(%s). Regenerate them or run the triage." % (sid, bad, ", ".join("%s=%s" % (p, tri.get(p, {}).get("verdict", "untriaged")) for p in bad)))


def main():
    if os.environ.get("FLEET_NO_LOCAL_MEDIA") == "1":
        die("FLEET_NO_LOCAL_MEDIA: build_short.py cannot run on a video fleet worker; use the approved hosted route")
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--skip-images", action="store_true")
    ap.add_argument("--skip-audio", action="store_true")
    ap.add_argument("--parts", type=int, default=None)
    ap.add_argument("--check", action="store_true", help="validate + resolve only")
    ap.add_argument("--audio-only", metavar="DIR", help="resolve + build the sound only, writing into DIR (A/B and sound "
                    "iteration; never touches out/<ID>, the registries or the render package)")
    ap.add_argument("--words", action="store_true", help="print the voice's words as @references (with #n occurrence) and exit")
    a = ap.parse_args()
    if a.words:
        s = json.load(open(a.spec))
        wp = s["voice"]["words"] if os.path.isabs(s["voice"]["words"]) else os.path.join(V2, s["voice"]["words"])
        seen = {}
        for w in load_words(wp):
            k = norm(w["word"]); seen[k] = seen.get(k, 0) + 1
            print("%7.2f  @%s%s   %s" % (w["start"], k, "#%d" % seen[k] if seen[k] > 1 else "", w["word"]))
        return
    T0 = time.time()
    spec = json.load(open(a.spec))
    sid = spec["id"]
    sys.path.insert(0, os.path.join(KIT, "tools"))
    import concept_card
    allowed, why = concept_card.gate_ok(sid)
    if not allowed:
        die("concept card: " + why)
    out = os.path.abspath(a.audio_only) if a.audio_only else os.path.join(KIT, "out", sid)
    os.makedirs(out, exist_ok=True)
    problems = []
    validate(spec, problems)
    bespoke = bespoke_report(spec, problems)
    moves = variety_check(spec, problems)
    if problems:
        print("\n".join("SPEC ERROR: " + p for p in problems)); die("%d spec error(s)" % len(problems))

    vpath = spec["voice"]["wav"] if os.path.isabs(spec["voice"]["wav"]) else os.path.join(V2, spec["voice"]["wav"])
    wpath = spec["voice"]["words"] if os.path.isabs(spec["voice"]["words"]) else os.path.join(V2, spec["voice"]["words"])
    voice_word_guard(vpath)
    words = load_words(wpath)
    R = Resolver(words)
    vdur = ffdur(vpath)
    dur = round(math.ceil(max(vdur, words[-1]["end"] + spec.get("tail", 0.9)) * FPS) / FPS, 3)
    if dur > 60.0 and words[-1]["end"] + 0.35 <= 59.9:   # gate check 7: 30-60s passes, 60-90s only warns
        dur = 59.9

    # beats: start times from word references (lead so the picture lands with the word), ends = next start
    beats = []
    for i, b in enumerate(spec["beats"]):
        t = 0.0 if i == 0 else R.t(b["start"]) - b.get("lead", 0.1)
        beats.append({"id": b["id"], "comp": b["component"], "from": round(max(0.0, t), 3), "src": b})
    for i, b in enumerate(beats):
        b["to"] = beats[i + 1]["from"] if i + 1 < len(beats) else dur
        if b["to"] - b["from"] < 0.6:
            die("beat %s is %.2fs long; merge it (minimum 0.6s)" % (b["id"], b["to"] - b["from"]))
    # craft ledger 28 Sep: S04, S43, S49 FAILED check 15 stereo (1 of 5-7 cues toward the picture). With
    # spec "kit_defaults" >= "2026-09-28" an authored sfx with no "x" and no "pan" takes its beat's "x".
    kd = str(spec.get("kit_defaults") or "") >= "2026-09-28"
    rs_beats, events = [], []
    for i, b in enumerate(beats):
        src = b["src"]
        props = resolve_times(json.loads(json.dumps(src.get("props", {}))), R, b["from"])
        overlays = resolve_times(json.loads(json.dumps(src.get("overlays", []))), R, b["from"])
        beat = {"id": b["id"], "comp": b["comp"], "from": b["from"], "to": b["to"], "i": i, "props": props, "overlays": overlays}
        for k in ("field", "bg", "bgMode", "tx", "zoom", "hold", "extend", "drift", "signature", "mirrors"):
            if k in src:
                beat[k] = src[k]
        events += fill(beat, R, dur)
        if i > 0 and src.get("tx") != "none":   # "none": the scene's own camera is the transition, and its sound is authored
            tx = src.get("tx")
            events.append((b["from"], "glitch" if tx == "glitch" else "seam", -8 if tx != "cut" else -12))
        for x in src.get("sfx", []):
            events.append((R.t(x["at"], b["from"]), x["kind"], x.get("gain"),
                           x.get("pan", pan_of(x.get("x", src.get("x") if kd else None)))))
        rs_beats.append(beat)

    # caption windows: beats whose picture is not already the words
    wins = []
    for sb, beat in zip(spec["beats"], rs_beats):
        cap = sb.get("captions", beat["comp"] not in NO_CAPTIONS and not (beat["comp"] == "document" and beat["props"].get("text")))
        top = sb.get("captionTop", 1290)
        c_to = min(beat["to"], R.t(sb["captionsTo"], beat["from"])) if sb.get("captionsTo") else beat["to"]
        if cap:
            if wins and abs(wins[-1]["to"] - beat["from"]) < 0.01 and wins[-1]["top"] == top:
                wins[-1]["to"] = c_to
            else:
                wins.append({"from": beat["from"], "to": c_to, "top": top})
    # images
    images, img_hashes = {}, {}
    t_img = time.time()
    for key, im in spec.get("images", {}).items():
        if a.skip_images and not os.path.exists(os.path.join(out, "img", key + (".png" if im.get("cutout") else ".jpg"))):
            die("--skip-images but image %s has not been made" % key)
        rec = make_image(key, im, os.path.join(out, "img"), os.path.join(out, "images"))
        images[key] = {"src": "img/" + os.path.basename(rec["final"])}
        img_hashes[key] = rec.get("sha256")
    t_img = time.time() - t_img
    # fresh imagery: no image may already belong to another short (registry of every source hash)
    if not spec.get("reproduction_of") and not a.audio_only:
        reg = json.load(open(REGISTRY)) if os.path.exists(REGISTRY) else {}
        clash = ["%s (already used by %s)" % (k, reg[h]) for k, h in img_hashes.items() if h in reg and reg[h] != sid]
        if clash:
            die("imagery must be generated fresh for this story; reused: %s" % clash)
        for k, h in img_hashes.items():
            reg[h] = sid
        os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
        json.dump(reg, open(REGISTRY, "w"), indent=1)

    rs = {"id": sid.lower() + "-" + re.sub(r"[^a-z0-9]+", "-", spec.get("slug", spec.get("title", "short")).lower()).strip("-")[:24],
          "kit": version(), "look": spec["look"], "dur": dur, "words": words, "beats": rs_beats, "captions": wins, "images": images,
          "world": spec.get("world"), "kit_defaults": spec.get("kit_defaults")}
    json.dump(rs, open(os.path.join(out, "resolved.json"), "w"), indent=1)
    left = unresolved_refs(rs.get("beats", rs) if isinstance(rs, dict) else rs)
    if left:
        die("%d word reference(s) were not resolved to seconds, so those elements would silently show from frame 0: %s. "
            "Use a key ending in At (or at, atX, from, to) for every timing." % (len(left), "; ".join(left[:8])))
    unpanned = [(b.get("id"), x.get("at")) for b in spec["beats"] for x in b.get("sfx", [])
                 if "pan" not in x and "x" not in x and not (kd and "x" in b)]
    n_sfx = sum(len(b.get("sfx", [])) for b in spec["beats"])
    if unpanned:
        print("STEREO ADVISORY: %d of %d authored sfx have no x/pan (centred): %s. A centred cue while the picture "
              "moves off-centre fails check 15 on FINAL (S04, S43, S49 on 28 Sep). Add \"x\" (px or 0..1) or \"pan\"." % (
                  len(unpanned), n_sfx, ", ".join("%s@%s" % u for u in unpanned[:8])), file=sys.stderr)
    if a.check:
        print(json.dumps({"beats": [(b["id"], b["comp"], b["from"], b["to"]) for b in rs_beats], "captions": wins, "dur": dur}, indent=0))
        return

    # gate inputs: the spoken script and sentence-level timed captions
    gdir = os.path.join(out, "gate"); os.makedirs(gdir, exist_ok=True)
    sents, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[.!?]$", w["word"]):
            sents.append(cur); cur = []
    if cur:
        sents.append(cur)
    json.dump([{"start": s[0]["start"], "end": s[-1]["end"], "text": " ".join(x["word"] for x in s)} for s in sents],
              open(os.path.join(gdir, "captions-timed.json"), "w"), indent=1)
    script_file = spec.get("script", {}).get("file")
    spoken = "\n".join(" ".join(x["word"] for x in s) for s in sents)
    open(os.path.join(gdir, "script.txt"), "w").write(spoken + "\n")

    # audio
    t_aud = time.time()
    adir = os.path.join(out, "audio"); os.makedirs(adir, exist_ok=True)
    if not a.skip_audio:
        lib = json.load(open(os.path.join(SOUND, "library.json")))
        libx = {i["id"]: i for i in lib["items"]}
        extras = [{"t": R.t(x["at"]), "sfx": x["sfx"], "gain": x.get("gain", -8), "pan": x.get("pan", pan_of(x.get("x")))}
                  for x in spec.get("sfx", [])]
        cues = pick_sfx(events, lib, extras)
        music = spec.get("music", {})
        engine = music.get("engine", "mix2")
        if engine not in ("mix2", "legacy"):
            die("music.engine must be mix2 (default) or legacy (reproducing a posted video only)")
        mitems = {m["id"]: m for m in json.load(open(os.path.join(SOUND, "music.json")))["items"]}
        bed = mitems.get(music.get("bed"))
        if not bed:
            die("music.bed %r not in sound/music.json" % music.get("bed"))
        # Sam, 6 Oct 02:30: "get rid of the elevator theme tune too, it doesn't fit most stories" (Local Forecast on S02/S01;
        # Airport Lounge is the same lounge family). Pick a bed that fits THIS story's mood (S52's Oppressive Gloom was "perfect").
        if music.get("bed") in ("local-forecast", "airport-lounge"):
            die("music.bed %r is banned (Sam: the elevator tune does not fit the stories). Choose a bed for this story's mood."
                % music.get("bed"))
        mres = resolve_times(json.loads(json.dumps(music)), R, 0)
        voice_pad = os.path.join(adir, "voice-padded.wav")
        run(["ffmpeg", "-y", "-v", "error", "-threads", "2", "-i", vpath, "-af", "apad=whole_dur=%.3f" % dur, "-ar", "44100", voice_pad])
        if engine == "mix2":
            # 25 Sep sound upgrade: the mix is sound/v2/mix2.py (deterministic 4-stem mixer) via kit_bridge, with the
            # rules in sound/v2/audio_rules.json: bed >= 18 LU under the voice in every speech row, lifts and swells
            # only in true pauses (>= 0.4 s), a voice-keyed sidechain on the music AND the SFX bus, constant-power pan
            # per cue, peak-anchored risers, master -14 LUFS / <= -1 dBTP on the AAC encode. Density 10-20 events a
            # minute and <= 3 overlapping are enforced here (thin_sound) and measured by sound/audit_sound.py (gate 15).
            thinned = []
            cues, sev = thin_sound(cues, libx, dur, thinned)
            apply_audio_overrides(sid, cues, adir)
            epm = len(sev) / (dur / 60.0)
            if epm < 10.0:
                die("sound design too thin: %.1f events a minute (rule 10-20). Author sfx on the beats (kind + at, and x "
                    "for where the element sits on screen)." % epm)
            json.dump({"events_per_min": round(epm, 1), "events": len(sev), "thinned": thinned},
                      open(os.path.join(adir, "thinned.json"), "w"), indent=1)
            rooms = []
            for r in resolve_times(json.loads(json.dumps(spec.get("room", []))), R, 0):
                tone = libx.get(r.get("tone", "room_tone_01"))
                if not tone or tone["category"] != "room_tone":
                    die("room %r: tone must be a room_tone_* id" % r)
                rooms.append({"t0": float(r["from"]), "t1": float(r["to"]), "src": os.path.join(SOUND, tone["path"]),
                              "lowpass_hz": r.get("lowpass_hz", 3000), "under_speech_db": max(30.0, r.get("under_db", 34.0)),
                              "fade_s": r.get("fade_s", 0.5), "label": r.get("label", "room tone")})
            json.dump({"cues": cues, "engine": "mix2"}, open(os.path.join(adir, "cues.json"), "w"), indent=1)
            sys.path.insert(0, os.path.join(SOUND, "v2")); import kit_bridge
            ms = kit_bridge.mix_spec_from_kit(mres, os.path.join(SOUND, bed["path"]), voice_pad, cues, words_path=wpath,
                                              duration_s=dur, spec_id=sid, rooms=rooms, studio=spec["voice"].get("studio", True))
            json.dump(ms, open(os.path.join(adir, "mix_spec.json"), "w"), indent=1)
            p = subprocess.run(["nice", "-n", "15", "python3", os.path.join(SOUND, "v2/mix2.py"), "render", os.path.join(adir, "mix_spec.json"),
                                "--out", os.path.join(adir, "mix2")], capture_output=True, text=True)
            open(os.path.join(adir, "mix.log"), "w").write(p.stdout + "\n" + p.stderr)
            if p.returncode:
                die("mix2 failed: see audio/mix.log")
            shutil.copy(os.path.join(adir, "mix2", "master.wav"), os.path.join(adir, "mix.wav"))    # what produce.py muxes
            st = os.path.join(adir, "mix2", "stems")
            gc = gap_check(words, os.path.join(st, "music.wav"), os.path.join(st, "voice.wav"), mres)
            json.dump(gc, open(os.path.join(adir, "gap-check.json"), "w"), indent=1)
            sys.path.insert(0, SOUND); import audit_sound
            rep, summ = audit_sound.audit(argparse.Namespace(master=os.path.join(adir, "mix.wav"), build=out, voice=None, bed=None,
                                                             cues=None, words=wpath, stems=None, no_video=True))
            json.dump(rep, open(os.path.join(adir, "sound-audit.json"), "w"), indent=1)
            if rep["status"] != "PASS":
                print("\n".join("SOUND AUDIT: " + f for f in rep["fails"]))
                die("sound audit FAILED before render (audio/sound-audit.json)")
            print("sound: %s" % summ)
        else:
            # legacy engine (sound/mix.py + bed envelope), kept only to reproduce a posted video's mix engine. It uses
            # the current cue picker; an exact reproduction of a posted mix is its frozen audio/mix.wav.
            bed_wav, bed_raw = os.path.join(adir, "bed-shaped.wav"), os.path.join(adir, "bed-raw.wav")
            run(["ffmpeg", "-y", "-v", "error", "-threads", "2", "-stream_loop", "-1", "-i", os.path.join(SOUND, bed["path"]), "-t", "%.3f" % dur,
                 "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", bed_raw])
            # the rule is measured, and the bed is lowered in 1.5 LU steps until it holds (every attempt is kept in the receipt)
            attempts = []
            # r2 (S11 judge: "the lack of a compelling music bed"): a quiet line of voice used to pull the WHOLE bed down.
            # Now a failing gap gets a local trim (the gap and the second before it) and only after three local tries
            # does the whole bed come down.
            mres["under_lu"] = music.get("under_lu", 14.5)
            mres["trims"] = []
            for k in range(7):
                base, env = bed_envelope(words, dur, mres, bed["lufs_integrated"])
                apply_envelope(bed_raw, bed_wav, env)
                gc = gap_check(words, bed_wav, voice_pad, mres)
                attempts.append({"under_lu": mres["under_lu"], "trims": list(mres["trims"]), "pass": gc["pass"],
                                 "gaps": [(g["gap"], g["rise_db"], g["bed_under_voice_lu"]) for g in gc["gaps"]]})
                if gc["pass"]:
                    break
                if k < 3:
                    for g in gc["gaps"]:
                        if not g["pass"]:
                            cut = max(10.8 - g["bed_under_voice_lu"], g["rise_db"] - 2.8, 0) + 0.8
                            mres["trims"].append({"from": g["gap"][0] - 1.2, "to": g["gap"][1] + 0.1, "db": -round(cut, 2)})
                else:
                    mres["under_lu"] += 1.5
            gc["attempts"] = attempts
            os.remove(bed_raw)
            json.dump({"cues": cues, "duck": {"threshold": 0.5, "ratio": 1, "attack": 5, "release": 250, "makeup": 1.0}},
                      open(os.path.join(adir, "cues.json"), "w"), indent=1)
            json.dump({"bed": bed["id"], "credit": bed.get("credit"), "base_gain_db": round(base, 2), "envelope_db": env},
                      open(os.path.join(adir, "bed-envelope.json"), "w"), indent=1)
            json.dump(gc, open(os.path.join(adir, "gap-check.json"), "w"), indent=1)
            if not gc["pass"]:
                print(json.dumps(gc, indent=1)); die("music-gap rule FAILED (audio/gap-check.json)")
            p = subprocess.run(["python3", os.path.join(SOUND, "mix.py"), "--voice", voice_pad, "--music", bed_wav, "--cues", os.path.join(adir, "cues.json"),
                                "--out", os.path.join(adir, "mix.wav"), "--true-peak", "-3.0"], capture_output=True, text=True)
            open(os.path.join(adir, "mix.log"), "w").write(p.stdout + "\n" + p.stderr)
            if p.returncode:
                die("mix.py failed: see audio/mix.log")
            # the same rule measured on the final mix: momentary loudness in the 3 gaps vs the speech before them
            gc_mix = gap_check(words, os.path.join(adir, "mix.wav"), os.path.join(adir, "mix.wav"), mres)
            json.dump(gc_mix, open(os.path.join(adir, "gap-check-mix.json"), "w"), indent=1)
    t_aud = time.time() - t_aud
    if a.audio_only:
        print("audio-only build of %s in %s (%.0fs)" % (sid, out, t_aud))
        return

    parts = a.parts or spec.get("render", {}).get("parts", 4)
    tar, sha, pm = build_project(spec, rs, out, parts)
    info = {"id": sid, "kit": version(), "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "dur": dur, "voice": vpath, "words": wpath,
            "beats": len(rs_beats), "sfx_cues": len(json.load(open(os.path.join(adir, "cues.json")))["cues"]) if os.path.exists(os.path.join(adir, "cues.json")) else None,
            "images": len(images), "package": tar, "package_sha256": sha, "parts": pm,
            "sync_cover": {b["id"]: b.get("_sync_cover") for b in rs_beats if "_sync_cover" in b}, "bespoke": bespoke,
            "seconds": {"total": round(time.time() - T0, 1), "images": round(t_img, 1), "audio": round(t_aud, 1)}}
    json.dump(info, open(os.path.join(out, "BUILD.json"), "w"), indent=1)
    if moves:
        register_moves(moves)   # only a complete production build enters the variety registry
    print("built %s: %.2fs, %d beats, %s cues, %d images, %d parts, package %s (%.1f MB) in %.0fs" % (
        sid, dur, len(rs_beats), info["sfx_cues"], len(images), len(pm), sha[:12], os.path.getsize(tar) / 1e6, time.time() - T0))


if __name__ == "__main__":
    main()
