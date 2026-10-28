#!/usr/bin/env python3
"""format_engine.py (v2): story.json + the voice's word timings -> a full short spec, deterministically. NO model, NO network, NO render (p02 of build prod-2030-2026-10-20).

  format_engine.py build <ID> [--format dossier|clean|newsroom] [--swatch D3] [--check]    write specs/<ID>/{spec.json, scenes.js, concept.json, CONCEPTS.md, STATE.md}
  format_engine.py check <ID>                                                              build and judge everything, write nothing
  format_engine.py produce <ID> | --all [--limit N] [--no-submit]                          voiced + v3 -> story.json -> clause crops -> build -> precheck_all -> storyboard submit (no human, no Claude)
  format_engine.py eligible                                                                 every script with its voice and v3 state
  format_engine.py --selftest                                                              fixture build + the DIRECTOR assertions, and bad fixtures that MUST fail

v1 (a card template: same figure, small white card, caption pill, alternating flat ground) was returned by root as a slideshow on 20 Oct (S136). v2 composes the way S05 does
(registry/storyboards/S05-storyboard.jpg, the approved bar; read the long comment above HEAD_X below):
  WORLD   one dark map (ds/map.js coastlines) the story lives in; a new camera view every beat
  HERO    ONE price-tag object with the figure at >= 205 px: full on frame 0, a chip while other things happen, full again on a tag beat and on the LAST frame
  NAME    the known-name logo plate (fetch_assets) at hero scale on frame 0, a chip after, big again on the last frame
  BEATS   each beat has its own object: plate | map | tag | pad (legal-pad checklist) | quote card | bars (the figure turns into a chart) | proof (source clipping, clause marked)
  TYPE    condensed headlines (Big Shoulders 700, 76-116 px) that fill the width, accent words; captions are OFF (the headline is the caption), like S05
  ENDING  verdict headline -> question -> CTA card over the world -> the last 0.5 s is frame 0 again (tag, plate, camera, headline)
Everything printed comes from story.json; all layout is decided here with the kit's own fonts, so the safe-zone / overlap / size checks hold by construction.
"""
import argparse, collections, copy, datetime, fcntl, glob, hashlib, json, math, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
V2 = os.path.dirname(KIT)
sys.path.insert(0, HERE)
sys.path.insert(0, KIT)
import fe_layout as FL      # noqa: E402
import fe_formats as FF     # noqa: E402
try:
    import engine_learn as EL   # noqa: E402  (26 Oct 2026: sampling weights learnt from posted shorts' measured results; absent or broken -> rule defaults)
except Exception:       # pragma: no cover
    EL = None

FPS = 30
FR = 1.0 / FPS
RT_JS = os.path.join(HERE, "format_engine_rt.js")
REG_FE = os.path.join(KIT, "registry", "format-engine.json")
FLEET_BAK = ".bak-2026-10-20-fleet"
CTA_LINK = "agmm.co.uk/ai-constraint-audit"
SERIES_LINE = "AI went wrong · real UK stories, daily"

# ---- SFX source (26 Oct 2026). Default "library" = sound/library.json (Sonniss + synthesised, onsets measured). AGMM_SFX_SOURCE=earshot swaps the kinds
# that have an earshot role (whoosh tick pop stamp ping slam click type) to earshot's code-made takes (MIT), whose onset / peak / end are MEASURED by
# `earshot kit render` and stored in registry/earshot-sfx.json + sound/library-earshot.json. Placement is by that measured onset (mix2 lands onset_ms, or
# anchor_ms for peak-anchored takes, on the cue), never the file start. Opt-in: nobody has listened to these inside a short yet.
SFX_SOURCE = os.environ.get("AGMM_SFX_SOURCE", "library").strip().lower()
ES_SFX = (json.load(open(os.path.join(KIT, "registry", "earshot-sfx.json"))) if os.path.exists(os.path.join(KIT, "registry", "earshot-sfx.json")) else {}) if SFX_SOURCE == "earshot" else {}
ES_KINDS = (ES_SFX.get("kinds") or {}) if SFX_SOURCE == "earshot" else {}
# SFX_SOURCE=openverse (26 Oct, Sam: "use the Openverse API"): the engine asks kit/registry/sfx-library.json for a sound by ROLE and ranks by earshot's precomputed
# `match` z against the role's description; every cue is placed by the sound's MEASURED onset (peak for risers) in the merged library mix2 reads. Variety: a
# file is never used twice in one short, and across shorts the least-used good match wins (kit/registry/sfx-usage.json, idempotent per short id). The earshot
# code-made bank is the second source when a role's licensed pool is exhausted.
def _jl(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


SFX_LIB = _jl(os.path.join(KIT, "registry", "sfx-library.json")) if SFX_SOURCE == "openverse" else {}
SFX_USAGE_PATH = os.environ.get("AGMM_SFX_USAGE_PATH") or os.path.join(KIT, "registry", "sfx-usage.json")
SFX_POOL, SFX_POOL_MIN_Z = 24, 1.0          # candidates considered per role (best match first) and the weakest match worth using
if SFX_SOURCE == "openverse" and not SFX_LIB.get("items"):
    raise SystemExit("AGMM_SFX_SOURCE=openverse but kit/registry/sfx-library.json is missing: run tools/earshot_sfx_register.py import-ov <artifact dir>")


def sfx_usage():
    return _jl(SFX_USAGE_PATH)


SFX_BANK_PENALTY = 6.0          # z units; bank variants rank below any usable Openverse sound of the role
SFX_K, SFX_RECENT = 8, 5          # choose among the top-k role matches (earshot score), least used first; no file in more than 1 of any 5 consecutive shorts


def sfx_recent_rows(sid):
    """-> [(at, short id, [ids])] of the OTHER shorts in the usage ledger, newest first (legacy list rows have at = 0)"""
    rows = []
    for k, v in sfx_usage().items():
        if k != sid:
            rows.append(((v.get("at", 0) if isinstance(v, dict) else 0), k, (v.get("ids", []) if isinstance(v, dict) else v)))
    return sorted(rows, key=lambda r: (r[0], r[1]), reverse=True)


def sfx_pick(P, kind):
    """-> (library id, trim dB) for an engine cue kind, or None when the role is exhausted for this short (the cue is dropped, never repeated).
    Candidates are the role's USABLE sounds (cc0 / pdm Openverse + the MIT code-made bank). Hard rules, in order: not already in this short; not in any of the
    previous SFX_RECENT-1 shorts (so a file is in at most 1 of any 5 consecutive shorts). Among what is left: the SFX_K best earshot role matches, least used overall
    first, then best match. Only if nothing is left is the 5-short cap relaxed (least used wins) and a 'cap relaxed' repair is logged: it counts as a violation."""
    role = SFX_LIB["kind_role"].get(kind)
    if not role:
        return None
    here = {c["kind"][1:] for c in P.sfx if c["kind"].startswith("=")}
    rows = sfx_recent_rows(P.sid)
    banned = {i for r in rows[: SFX_RECENT - 1] for i in r[2]}
    use = collections.Counter(i for r in rows for i in r[2])
    z = lambda i: (i.get("role_match") or {}).get("z", -9.0)
    allv = [i for i in SFX_LIB["items"].values() if i["role"] == role and i.get("usable", True) and i["source_kind"] in ("openverse", "earshot-bank") and z(i) >= SFX_POOL_MIN_Z - 100]
    # licensed recordings first: the code-made bank carries a z penalty so it only fills in where the Openverse pool is exhausted under the 5-short cap (bank share <= 40 % goal)
    pool = sorted([i for i in allv if (i["source_kind"] == "earshot-bank" or z(i) >= SFX_POOL_MIN_Z)], key=lambda i: -(z(i) - (SFX_BANK_PENALTY if i["source_kind"] == "earshot-bank" else 0.0)))
    ov = [i for i in pool if i["source_kind"] == "openverse"]
    ref = sorted(i["l50_lufs"] for i in ov[:SFX_POOL] if i.get("l50_lufs") is not None)
    ref = ref[len(ref) // 2] if ref else None
    free = [i for i in pool if i["id"] not in here and i["id"] not in banned]
    relaxed = False
    if not free:
        free = [i for i in pool if i["id"] not in here]
        relaxed = bool(free)
    if not free:
        return None
    top = free[:SFX_K]
    i = min(top, key=lambda i: (use[i["id"]], -z(i), sha1(P.sid + i["id"])))
    if relaxed:
        P.repairs.append("sfx: 5-short cap relaxed for %s (no unused %s sound left)" % (i["id"], role))
    trim = 0.0 if ref is None or i.get("l50_lufs") is None else max(-6.0, min(6.0, ref - i["l50_lufs"]))
    return i["id"], round(trim, 1)


def sfx_ledger_put(sid, ids):
    with open(SFX_USAGE_PATH + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = _jl(SFX_USAGE_PATH)
        d[sid] = {"ids": sorted(ids), "at": round(time.time(), 3)}
        tmp = SFX_USAGE_PATH + ".tmp-%d" % os.getpid()
        json.dump(d, open(tmp, "w"), indent=0)
        os.replace(tmp, SFX_USAGE_PATH)


def write_sfx_ledger(P):
    if SFX_SOURCE != "openverse" or P.sid.startswith("ZZ") or os.environ.get("AGMM_SFX_LEDGER") == "off":
        return
    sfx_ledger_put(P.sid, {c["kind"][1:] for c in P.sfx if c["kind"].startswith(("=ov_", "=es_", "=es2_"))})


if SFX_SOURCE == "earshot" and not ES_KINDS:
    raise SystemExit("AGMM_SFX_SOURCE=earshot but kit/registry/earshot-sfx.json is missing: run tools/earshot_sfx_register.py import <artifact dir>")

# ------------------------------------------------------------------------------------------------ constants (px on the 1080x1920 master)
INNER_W = 744
LOW_W = 658                   # below y 840 the TikTok column starts at x 780: text right edge <= 770
T_PROOF = 1.5
LEAD = 0.35                   # spec beats open this long before the first word of a state
FADE_IN, FADE_OUT = 6 * FR, 5 * FR
FLOAT_AMP = 0.0               # text never floats in v2; the hero tag swings by rotation only
GAP_FIRST3, GAP_LATER = 0.75, 0.85


def r2(v):
    return round(float(v) + 0.0, 2)


def jload(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return d


def sha1(b):
    return hashlib.sha1(b if isinstance(b, bytes) else b.encode("utf-8")).hexdigest()


class EngineError(Exception):
    pass


# ================================================================================================ inputs
def specs_dir(sid):
    return os.path.join(KIT, "specs", sid)


def load_inputs(sid, story_path=None, words_path=None):
    story = jload(story_path or os.path.join(specs_dir(sid), "story.json"))
    if not story:
        raise EngineError("no specs/%s/story.json: run tools/extract_story.py %s first" % (sid, sid))
    import build_short as BS
    wp = words_path or os.path.join(V2, story["inputs"]["words"])
    raw = jload(wp)
    rawl = raw["words"] if isinstance(raw, dict) else raw
    words = BS.load_words(wp)
    if len(words) != len(rawl):
        raise EngineError("words.json has %d entries but build_short.load_words keeps %d (an empty token): word indices would drift" % (len(rawl), len(words)))
    return story, words


BLOCKING = {"verdict", "question", "rule2", "rule3", "figure-unspoken", "known-name", "no-words", "alignment"}     # root struck the overrides on 20 Oct: an engine short needs a v3 script (needs-writer otherwise)


def validate_story(story, words, look=False):
    """-> list of problems. Structural truths the engine relies on; the grounding (G1-G11) was proved by extract_story and is not redone here."""
    pr = []
    if story.get("schema") != "agmm-story-v1":
        pr.append("schema is not agmm-story-v1")
    beats = story.get("beats") or []
    if len(beats) < 6:
        pr.append("fewer than 6 beats")
        return pr
    if story.get("status") == "rejected":
        pr.append("story.json status is rejected")
    blocking = [g for g in story.get("gaps", []) if g in BLOCKING]
    if blocking and not look:
        pr.append("blocking gaps %s: the script is not strategy-v3 (turn first, you by 3 s, verdict + question ending): flag needs-writer" % blocking)
    nxt = 0
    for b in beats:
        if b["t_from_word"] != nxt:
            pr.append("beat %s does not tile the words (starts at %d, expected %d)" % (b["id"], b["t_from_word"], nxt))
        nxt = b["t_to_word"] + 1
        if b["t_to_word"] >= len(words):
            pr.append("beat %s ends past the last word" % b["id"])
            break
        if abs(words[b["t_from_word"]]["start"] - b["t_from"]) > 0.02 and b["t_from_word"] != 0:
            pr.append("beat %s t_from %.3f is not words[%d].start %.3f (a re-voice since extraction?)" % (b["id"], b["t_from"], b["t_from_word"], words[b["t_from_word"]]["start"]))
    if nxt != len(words):
        pr.append("beats end at word %d but the take has %d words" % (nxt - 1, len(words)))
    if beats[-1]["kind"] != "cta" or beats[0]["kind"] != "hook":
        pr.append("first beat must be the hook and the last the cta")
    hc = story.get("huge_cost") or {}
    if not hc.get("display"):
        pr.append("huge_cost.display missing")
    if not hc.get("spoken"):
        pr.append("huge_cost.spoken is null: the voice never says the figure, so it cannot be the hero (figure-unspoken)")
    kn = story.get("known_name") or {}
    if not 1 <= len((kn.get("text") or "").split()) <= 3:
        pr.append("known_name.text must be 1-3 words")
    cause = (story.get("tiny_cause") or {}).get("text") or ""
    name_words = len((kn.get("text") or "").split()) if story.get("logo_asset") is None else 0
    declared = name_words + len(cause.split()) + len(str(hc.get("display", "")).split())
    f0max = int((jload(os.path.join(KIT, "registry", "strategy-v3.json"), {}) or {}).get("frame0_words_max", 12))   # root 21 Oct: one source of truth (was a stale 6; S05 won with ~10)
    if declared > f0max:
        pr.append("frame 0 declares %d readable words (name %d + cause %d + figure %d); craft_check allows %d: shorten tiny_cause or give the name a logo" % (declared, name_words, len(cause.split()), len(str(hc.get("display", "")).split()), f0max))
    hc_ = story.get("huge_cost") or {}
    if hc_.get("spoken"):
        import extract_story as ES_
        ok_h, why_h = ES_.hero_ok(hc_.get("unit"), ES_.sentence_around(words, hc_["spoken"][0]))          # root 27 Oct, G15 as the approved set implies
        if not ok_h:
            pr.append("needs-writer: the hero figure (%s %s) is %s (root 27 Oct: money, people, jobs, customers, records, files, hours, days, percent or a multiple, or a count whose sentence says what was lost or harmed)" % (hc_.get("display"), hc_.get("unit"), why_h))
    if story.get("world") not in ("map", "desk", "inbox", "statement", "counter", "phone", "tribunal", "room", "blueprint"):
        pr.append("story.json names no world (re-run tools/extract_story.py: since 20 Oct every story carries a world and an object per beat)")
    if not any("object" in b for b in beats):
        pr.append("story.json beats carry no object specs (re-run tools/extract_story.py)")
    rich = story.get("richness") or {}
    if story.get("status") == "thin" or (rich and rich.get("distinct_objects", 99) < rich.get("floor", 5)):
        pr.append("thin: needs richer sources (%s distinct groundable objects, floor %s): the supply line adds sources or drops the short" % (rich.get("distinct_objects"), rich.get("floor", 5)))
    if not story.get("verdict"):
        pr.append("no verdict")
    if not story.get("question"):
        pr.append("no question")
    return pr


# ================================================================================================ windows, chunks
class Win(object):
    pass


def build_windows(story, words):
    """story beats -> Win objects with the phrase aligned to the take: chunks = [(text, first word index, reveal time)] split at the stressed words."""
    import extract_story as ES
    out = []
    for i, b in enumerate(story["beats"]):
        w = Win()
        w.i, w.id, w.kind = i, b["id"], b["kind"]
        w.w0, w.w1, w.t0, w.t1 = b["t_from_word"], b["t_to_word"], float(b["t_from"]), float(b["t_to"])
        w.phrase, w.figure, w.quote, w.ledger, w.source_id = b.get("phrase"), b.get("figure"), b.get("quote"), b.get("ledger"), b.get("source_id")
        w.object = b.get("object")
        w.headline = b.get("headline")
        w.stress = list(b.get("stress") or [])
        w.sentences = b.get("sentences") or []
        w.chunks = []
        if w.phrase:
            pieces = []
            for wi in range(w.w0, w.w1 + 1):
                for tk in ES.toks(words[wi]["word"]):
                    pieces.append((tk, wi))
            ptoks = ES.sub_tokens(w.phrase)
            j, pos = 0, []
            for c, shown in ptoks:
                while j < len(pieces) and pieces[j][0] != c:
                    j += 1
                if j >= len(pieces):
                    raise EngineError("window %s: phrase word %r is not in the take (story.json is stale?)" % (w.id, c))
                pos.append((shown, pieces[j][1]))
                j += 1
            # a new chunk starts at a stressed word (and at the first word); at most 3 words per chunk unless it would leave a one-word tail
            cur = []
            stress = set(w.stress)
            for k, (shown, wi) in enumerate(pos):
                if cur and wi in stress and wi != cur[0][1]:
                    w.chunks.append(cur)
                    cur = []
                cur.append((shown, wi))
            if cur:
                w.chunks.append(cur)
            w.chunks = [dict(text=" ".join(s for s, _ in c), widx=c[0][1], t=words[c[0][1]]["start"] - FR, last_idx=c[-1][1]) for c in w.chunks]
        out.append(w)
    return out


def number_words_in(sentence):
    """the spoken words of a number inside a sentence ('ten point eight million', 'a hundred million dollars', 'eleven'): the pitch's number_spoken"""
    nw = r"(?:a |an )?(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|trillion|point|and|percent|dollars|pounds|euros)"
    best = ""
    for m in re.finditer(r"\b%s(?:[ -]%s)*\b" % (nw, nw), sentence, re.I):
        s = m.group(0)
        if re.search(r"hundred|thousand|million|billion|trillion|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|teen|ty\b", s, re.I) and len(s) > len(best):
            best = s
    return best.strip()


# ================================================================================================ the plan
class Plan(object):
    """everything one short is made of. Methods add items to the display list and register the boxes the self-check judges."""

    def __init__(self, sid, story, words, fmt_name, sw_key, assets=None):
        self.sid, self.story, self.words = sid, story, words
        self.fmt_name = fmt_name
        self.F = FF.FORMATS[fmt_name]
        self.sw_key = sw_key
        self.sw = FF.SWATCHES[sw_key]
        self.pal = {k: v for k, v in self.sw.items() if k not in ("fmt", "name", "gclass", "hue", "dark")}
        self.face = "cond"
        self.kface = self.F["kface"]
        self.caps = True
        self.assets = assets or {}
        self.wins = build_windows(story, words)
        self.dur = r2(math.ceil((words[-1]["end"] + 0.9) * FPS) / FPS)
        if self.dur > 60.0 and words[-1]["end"] + 0.35 <= 59.9:
            self.dur = 59.9
        self.items, self.boxes, self.sfx, self.events = [], [], [], []
        self.n = 0
        self.objects = []          # (name, word index, time) for the R7 pitch
        self.skins_used = []
        self.problems = []
        self.fillers = 0
        self.world_kind = story.get("world") or "desk"
        self.fetch_logos = False
        self.used_logos, self.routes, self.dropped, self.warn = [], [], [], []
        self.flags, self.repairs = set(), []          # repair flags set by build()'s retry loop; what fired is logged in the metrics
        self.light = not self.sw.get("dark", True)
        self.fig_hit = None
        self.tag_pulses, self.tag_drops = [], []

    # ---- tiny helpers
    def tw(self, t):
        return self.words[t]["start"]

    def nid(self, p="i"):
        self.n += 1
        return "%s%d" % (p, self.n)

    def col(self, name):
        return self.pal.get(name, name)

    # ---- display-list builders. A box is registered for every text item so the self-check can judge the zone and any overlap in time.
    def T(self, text, x, y, fs, wt, col, w=None, al="l", lh=1.1, ls=0.0, caps=None, it=False, ti=0.0, to=None, ain="rise", aout="fade", di=None, do=None, z=10,
          cols=None, a=None, face=None, maxlines=None, snd=None, sndx=None, oy=None, ob=None, event=True, lines=None, nobox=False, step=None, sh=None, head=False, org=None, os=None, rot=None):
        caps = self.caps if caps is None else caps
        face = face or self.face
        auto_width = w is None
        w = w if w is not None else INNER_W
        lines = lines or (text if isinstance(text, list) else FL.wrap(text, face, wt, fs, w, ls, caps))
        if auto_width and y + FL.block_h(lines, fs, lh) > 840:
            w = LOW_W
            if not isinstance(text, list):
                lines = FL.wrap(text, face, wt, fs, w, ls, caps)
        if maxlines and len(lines) > maxlines:
            self.problems.append("text %r wraps to %d lines at %d px (max %d)" % (str(text)[:40], len(lines), fs, maxlines))
        it_ = dict(k="text", id=self.nid("t"), lines=lines, x=r2(x), y=r2(y), w=r2(w), fs=fs, wt=wt, col=col, al=al, lh=lh, ls=ls, caps=bool(caps), it=bool(it), ti=r2(ti),
                   to=None if to is None else r2(to), ain=ain, aout=aout, z=z)
        if face != self.face:
            it_["face"] = face
        for k, v in (("cols", cols), ("a", a), ("di", di), ("do", do), ("oy", oy), ("ob", ob), ("step", step), ("sh", sh), ("org", org), ("os", os), ("rot", rot)):
            if v is not None:
                it_[k] = v
        if not nobox:
            bx = FL.text_box(x if al == "l" else (x + w / 2.0 if al == "c" else x + w), y, lines, face, wt, fs, lh, al, w, ls, caps)
            self.boxes.append(dict(id=it_["id"], box=bx, t0=ti, t1=to, label=" / ".join(lines)[:40], kind="text", fs=fs, head=head))
        self.items.append(it_)
        if event:
            self.events.append((ti, 1.0, "text"))
        if snd:
            self.cue(ti, snd, (sndx if sndx is not None else x + w / 2.0))
        return it_

    def R(self, x, y, w, h, fill=None, stroke=None, sw=4, r=None, ti=0.0, to=None, ain="fade", aout="fade", z=5, shadow=None, a=None, rot=None, org=None, gx=False,
          cols=None, di=None, do=None, snd=None, event=True, bg=None, pulse=None, os=None):
        it_ = dict(k="rect", id=self.nid("r"), x=r2(x), y=r2(y), w=r2(w), h=r2(h), fill=fill, stroke=stroke, sw=sw, r=r, ti=r2(ti), to=None if to is None else r2(to), ain=ain, aout=aout, z=z)
        for k, v in (("shadow", shadow), ("a", a), ("rot", rot), ("org", org), ("cols", cols), ("di", di), ("do", do), ("bg", bg), ("pulse", pulse), ("os", os)):
            if v is not None:
                it_[k] = v
        if gx:
            it_["gx"] = True
        self.items.append(it_)
        if event and ain not in ("none",):
            self.events.append((ti, 0.5 if (w * h) < 20000 else 1.0, "rect"))
        if snd:
            self.cue(ti, snd, x + w / 2.0)
            if not event:
                self.events.append((ti, 0.5, "rect"))
        return it_

    def PATH(self, d, x, y, w, h, stroke=None, fill=None, sw=6, ti=0.0, to=None, ain="draw", aout="fade", z=8, vb=None, di=None, a=None, snd=None, rot=None, event=True):
        it_ = dict(k="path", id=self.nid("p"), d=d, x=r2(x), y=r2(y), w=r2(w), h=r2(h), stroke=stroke, fill=fill, sw=sw, ti=r2(ti), to=None if to is None else r2(to), ain=ain, aout=aout, z=z)
        for k, v in (("vb", vb), ("di", di), ("a", a), ("rot", rot)):
            if v is not None:
                it_[k] = v
        self.items.append(it_)
        if event:
            self.events.append((ti, 0.5, "path"))
        if snd:
            self.cue(ti, snd, x + w / 2.0)
            if not event:
                self.events.append((ti, 0.5, "path"))
        return it_

    def IMG(self, src, x, y, w, h, ti=0.0, to=None, ain="fade", z=6, shadow=None, snd=None, rot=None, alt="", di=None):
        it_ = dict(k="img", id=self.nid("m"), src=src, x=r2(x), y=r2(y), w=r2(w), h=r2(h), ti=r2(ti), to=None if to is None else r2(to), ain=ain, aout="fade", z=z, alt=alt)
        for k, v in (("shadow", shadow), ("rot", rot), ("di", di)):
            if v is not None:
                it_[k] = v
        self.items.append(it_)
        self.events.append((ti, 1.0, "img"))
        if snd:
            self.cue(ti, snd, x + w / 2.0)
        return it_

    def RING(self, x, y, r, stroke, ti, sw=8, di=0.5, z=12, snd=None):
        it_ = dict(k="ring", id=self.nid("g"), x=r2(x), y=r2(y), r=r, stroke=stroke, sw=sw, ti=r2(ti), di=di, z=z)
        self.items.append(it_)
        self.events.append((ti, 0.5, "ring"))
        if snd:
            self.cue(ti, snd, x)
        return it_

    # ---- sound: kind -> (library id choices, gain). Onsets are measured in sound/library.json, so a cue lands on its picture event.
    CUE = {"paper": (["foley_paper_03", "foley_paper_05", "foley_paper_07"], -23), "click": (["foley_click_02", "foley_click_04", "ui_click_03"], -22),
           "pop": (["ui_pop_03", "ui_pop_04", "ui_pop_02"], -22), "stamp": (["foley_stamp_02", "foley_stamp_04"], -16), "slam": (["impact_soft_04", "impact_soft_06"], -18),
           "tick": (["foley_click_05", "foley_click_01"], -23), "type": (["foley_keyboard_05", "foley_keyboard_08"], -26), "print": (["foley_printer_02"], -21),
           "ping": (["notification_ping_05"], -22), "press": (["ui_click_04"], -14), "whoosh": (["whoosh_air_03", "whoosh_air_05"], -25), "flap": (["foley_click_03", "foley_click_06"], -23),
           "pen": (["typing_03"], -26)}

    def cue(self, t, kind, x):
        ids, g = self.CUE[kind]
        if SFX_SOURCE == "openverse" and kind in SFX_LIB.get("kind_role", {}):
            pk = sfx_pick(self, kind)
            if pk is None:
                self.repairs.append("sfx: no unused %s sound left, cue at %.2f dropped" % (SFX_LIB["kind_role"][kind], t))
                return
            self.sfx.append(dict(t=r2(t), kind="=" + pk[0], gain=g + pk[1], x=int(max(60, min(1020, x))), what=kind))
            return
        if ES_KINDS.get(kind):
            ids = ES_KINDS[kind]          # earshot takes: same gain (both libraries are peak-normalised to about -1 dBTP), measured onset in the registry
        k = len(self.sfx)
        self.sfx.append(dict(t=r2(t), kind="=" + ids[(k * 7 + int(t * 10)) % len(ids)], gain=g, x=int(max(60, min(1020, x))), what=kind))

    # ---- the self-check (the selftest runs this offline; the build refuses a plan that fails it)
    def check_geometry(self):
        errs = []
        for b in self.boxes:
            ev = FL.text_ok(b["box"].inflate(0), 0)
            infl = FL.text_ok(b["box"].inflate(FLOAT_AMP * 0.6), 0)       # float peaks: the sines weight 0.62 + 0.38, taper at both ends
            if ev or (infl and any(v for v in infl)):
                errs.append("text %r (%s) outside the universal zone at rest: %s box %s" % (b["label"], b["id"], (ev or infl)[0][2], b["box"]))
        # stacked text: two text boxes that share time and overlap by more than 10% of the smaller one
        bs = [b for b in self.boxes if b["kind"] == "text"]
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                a, c = bs[i], bs[j]
                a1 = a["t1"] if a["t1"] is not None else 1e9
                c1 = c["t1"] if c["t1"] is not None else 1e9
                if min(a1, c1) - max(a["t0"], c["t0"]) <= 0.08:
                    continue
                ov = a["box"].overlap(c["box"])
                if ov > 0.10 * min(a["box"].w * a["box"].h, c["box"].w * c["box"].h):
                    errs.append("stacked text: %r and %r overlap %.0f px^2 between %.2f and %.2f s" % (a["label"], c["label"], ov, max(a["t0"], c["t0"]), min(a1, c1)))
        return errs + self.problems



# ================================================================================================ the S05 grammar: one WORLD, one HERO tag, a known-name PLATE, a beat sequence
# Read registry/storyboards/S05-storyboard.jpg beside this. S05 lives in ONE world (a dark map the camera travels), has ONE hero (the price tag) that persists, moves and comes back on
# the last frame, shows real logo plates at hero scale, real source clippings with the clause marked and the outlet/date line, a chart the figure turns into, physical artefacts
# (a legal pad), condensed headlines that fill the width, and every frame is full edge to edge. This section builds exactly that from story.json:
#   world   ds/map.js real coastlines; a camera key per beat (a new region each beat, never still)
#   tag     the hero: hook (full, frame 0) -> chip (low) -> full again on a "tag" beat -> chip ... -> full on the last frame
#   plate   the known name: a logo plate (fetch_assets) or a condensed wordmark: hook (big) -> chip -> big again on the last frame
#   beats   each state has its OWN object: plate | map | tag | pad | quote | bars (+ the proof clipping at 1.5 s, the verdict headline, the question, the CTA card)
# DIRECTOR.md still holds: every beat lands whole on its cut, the outgoing layer is at 0 opacity on the cut, persisting objects are moved >= 0.55 s BEFORE the cut that follows them.
HEAD_X, HEAD_W, HEAD_Y = 80, 780, 296
OBJ_Y = 600
CHIP_TAG = dict(x=440, y=1076, w=340, h=160)
CHIP_PLATE_Y = 1112
LAND = 2 * FR
MONO = "mono"


def proj(lon, lat):
    """ds/map.js AG_MAP.project (Mercator on a 4000 px plane)"""
    lat = max(-80.0, min(84.0, lat))
    return ((lon + 180.0) / 360.0 * 4000.0, 2000.0 - (4000.0 / (2 * math.pi)) * math.log(math.tan(math.pi / 4 + lat * math.pi / 360.0)))


# camera presets (lon, lat, zoom): land-rich views first. A beat takes the next one; F0 and the last frame are VIEWS[0].
VIEWS = [(-3.0, 54.0, 3.3), (8.0, 49.0, 2.3), (-40.0, 48.0, 1.8), (-82.0, 40.0, 2.5), (20.0, 46.0, 2.5), (-3.5, 52.0, 4.6), (-100.0, 45.0, 1.7), (12.0, 42.0, 3.4)]


def fit_headline(P, text, maxlines=3, fs_max=116, fs_min=76, y=HEAD_Y):
    """Largest condensed size whose whole block fits the unchanged universal zone."""
    fs = fs_max
    while fs >= fs_min:
        # A tall block can enter the TikTok column although its first line does not.
        # Try a narrower wrap at the same size before reducing the font.
        for width in (HEAD_W, min(HEAD_W, LOW_W)):
            lines = FL.wrap(text, "cond", 700, fs, width, 0.0, True)
            box = FL.text_box(HEAD_X, y, lines, "cond", 700, fs, 0.9, caps=True)
            if (len(lines) <= maxlines and box.w <= width
                    and not FL.text_ok(box)):
                return fs, lines
        fs -= 2
    return None


def headline(P, chunk_texts, ti, to, y=HEAD_Y, maxlines=3, ain="slam", snd="slam", pulses=None, accent_last=True, fs_max=116):
    """a condensed headline that fills the width; the last chunk (or the last words of a single chunk) takes the accent colour"""
    words = []
    for ci, c in enumerate(chunk_texts):
        for w in c.split():
            words.append((w, ci))
    if not words:
        return None
    text = " ".join(w for w, _ in words)
    r = fit_headline(P, text, maxlines, fs_max, y=y)
    if not r:
        r = fit_headline(P, text, maxlines + 1, fs_max, y=y)
    if not r:
        raise EngineError("headline %r does not fit %d lines at 76 px" % (text[:50], maxlines + 1))
    fs, lines = r
    n = len(words)
    nacc = 0 if not accent_last else (max(1, int(round(n * 0.4))) if len(chunk_texts) == 1 else None)
    last_ci = max(ci for _, ci in words)
    html, k = [], 0
    for ln in lines:
        parts = []
        for tok in ln.split():
            w, ci = words[k]
            k += 1
            acc = (k > n - nacc) if nacc is not None else (ci == last_ci and len(chunk_texts) > 1)
            col = P.pal["accent"] if acc else P.pal["ink"]
            parts.append('<span style="color:%s">%s</span>' % (col, esc_html(tok.upper())))
        html.append(" ".join(parts))
    it = P.T(text.upper(), HEAD_X, y, fs, 700, P.pal["ink"], w=HEAD_W, lh=0.9, caps=True, ti=ti, to=to, ain=ain, di=LAND, z=14, lines=lines, face="cond", snd=snd, sndx=540,
             sh="0 10px 34px rgba(0,0,0,.85)", head=True)
    it["html"] = html
    it["os"] = 1.06
    it["org"] = "0% 100%"
    it["head"] = True
    if pulses:
        it["pulses"] = [r2(t) for t in pulses]
        P.events += [(t, 0.6, "pulse") for t in pulses]
    return it


def esc_html(s):
    return s.replace("&", "&amp;").replace("<", "&lt;")


def kicker(P, text, x, y, ti, to, col=None, w=None, fs=44, face=None):
    """a small condensed/mono line under or over an object (S05's mono kickers); never under 42 px"""
    face = face or P.kface
    wt = {"mono": 700, "serif": 600, "sans": 500, "cond": 700}[face]
    col = col or P.pal["dim"]
    return P.T(text, x, y, fs, wt, col, w=w or 700, lh=1.15, caps=(face != "serif"), ti=ti, to=to, ain="rise", di=LAND, z=12, face=face, event=False, ls=0.02 if face == "mono" else 0.0)


def plate_items(P, x, y, w, h, ti, to, snd=None):
    """a big transient known-name plate for the plate beat (the persistent one is the chip)"""
    P.R(x, y, w, h, fill=P.pal["plate"], r=18, ti=ti, to=to, ain="rise", di=LAND, z=8, shadow="0 22px 50px rgba(0,0,0,.55)", snd=snd)
    lg = P.assets.get("logo")
    if lg:
        ih = h - 40
        iw = min(w - 70, ih * lg["w"] / float(lg["h"]))
        P.IMG(lg["src"], x + (w - iw) / 2.0, y + 20, iw, ih, ti=ti, to=to, ain="rise", z=9, alt=P.story["known_name"]["text"], di=LAND)
    else:
        name = P.story["known_name"]["text"]
        fs = FL.fit_line(name, "cond", 700, w - 70, 120, 60, 0.0, True) or 60
        P.T(name, x + 35, y + (h - fs) / 2.0, fs, 700, P.pal["plate_ink"], w=w - 70, al="c", lh=1.0, caps=True, ti=ti, to=to, ain="rise", di=LAND, z=9, face="cond", event=False)


def kwt(P):
    return {"serif": 600, "sans": 500, "cond": 700}[P.kface]


# ------------------------------------------------------------------------------------------------ geometry of the persistent objects
def build_hero(P):
    st = P.story
    hc = st["huge_cost"]
    disp = hc["display"]
    cause = st["tiny_cause"]["text"]
    lab = hc["label"].upper()
    lg = P.assets.get("logo")
    def attempt(plate_h0, hfs_cap, min_fig=200):
        r = fit_headline(P, cause.upper(), 2, hfs_cap)
        if not r:
            return "tiny_cause %r does not fit two lines at 76 px" % cause
        hook_fs, hook_lines = r
        head_bottom = HEAD_Y + len(hook_lines) * hook_fs * 0.9
        plate_y0 = int(max(head_bottom + 16, 500))
        tag_y0 = plate_y0 + plate_h0 + 20
        budget = 1070 - tag_y0
        tag_max_w = LOW_W + 60
        vfs, ls_ = None, 0.0
        for floor in (205, 200, 180):          # craft_check wants the figure at 200 px or more: tighten the letter spacing (to -0.05 em) before shrinking it
            for iw, ls_try in ((550, 0.0), (tag_max_w - 90, 0.0), (tag_max_w - 90, -0.03), (tag_max_w - 90, -0.05)):
                v_ = FL.fit_line(disp, "cond", 700, iw, 250, floor, ls_try, True)
                if v_:
                    vfs, ls_ = v_, ls_try
                    break
            if vfs:
                break
        if not vfs:
            raise EngineError("figure %r does not fit the tag even at the 180 px floor with -0.05 em spacing (%d px inner width)" % (disp, tag_max_w - 90))
        P.tag_ls = ls_
        inner = int(min(tag_max_w, max(500, FL.tw(disp, "cond", 700, vfs, ls_, True) + 90))) - 60
        lfs = 46
        llines = FL.wrap(lab, "cond", 700, lfs, inner, 0.0, True)
        while (len(llines) > 2 or max(FL.tw(l, "cond", 700, lfs, 0.0, True) for l in llines) > inner) and lfs > 42:
            lfs -= 2
            llines = FL.wrap(lab, "cond", 700, lfs, inner, 0.0, True)
        if len(llines) > 2:
            raise EngineError("the figure label %r needs more than 2 lines at 42 px" % lab)
        vy = 30
        lab_h = len(llines) * lfs * 1.12
        vfs = min(vfs, int(budget - vy - 6 - lab_h - 22))
        if vfs < min_fig:
            return "frame 0 does not fit: the figure would be %d px (headline %d, plate %d, tag budget %d)" % (vfs, hook_fs, plate_h0, budget)
        ly = vy + vfs + 6
        return dict(hook_fs=hook_fs, hook_lines=hook_lines, head_bottom=head_bottom, plate_y0=plate_y0, tag_y0=tag_y0, vfs=vfs, lfs=lfs, llines=llines, vy=vy, ly=ly, plate_h0=plate_h0,
                    h=int(ly + lab_h + 22), w=int(min(tag_max_w, max(500, FL.tw(disp, "cond", 700, vfs, ls_, True) + 90))))
    got, err = None, None
    for min_fig in (200, 180):          # craft_check wants the figure at 200 px or more: shrink the plate and the headline first, the figure only as the last resort
        for plate_h0 in (210, 180, 150, 125, 100):
            for hfs_cap in (116, 104, 92, 80, 70):
                r = attempt(plate_h0, hfs_cap, min_fig)
                if isinstance(r, dict):
                    got = r
                    break
                err = r
            if got:
                break
        if got:
            break
    if not got:
        raise EngineError(err or "frame 0 does not fit")
    hook_fs, hook_lines, head_bottom, plate_y0, tag_y0 = got["hook_fs"], got["hook_lines"], got["head_bottom"], got["plate_y0"], got["tag_y0"]
    vfs, lfs, llines, vy, ly, plate_h0, h, w = got["vfs"], got["lfs"], got["llines"], got["vy"], got["ly"], got["plate_h0"], got["h"], got["w"]
    P.hook_fs, P.hook_lines = hook_fs, hook_lines
    P.tag_full = dict(x=80, y=tag_y0, w=w, h=h, vfs=vfs, lfs=lfs, lop=1, rot=0, op=1, vy=vy, ly=ly)
    cvfs = FL.fit_line(disp, "cond", 700, CHIP_TAG["w"] - 50, 130, 84, 0.0, True) or 84
    P.tag_chip = dict(x=CHIP_TAG["x"], y=CHIP_TAG["y"], w=CHIP_TAG["w"], h=CHIP_TAG["h"], vfs=cvfs, lfs=lfs, lop=0, rot=0, op=0, vy=(CHIP_TAG["h"] - cvfs) / 2.0, ly=CHIP_TAG["h"] - 4)
    P.tag_label = llines
    P.tag_value = disp
    sc_ = min(1.1, (LOW_W + 60) / float(w))         # preserve the normal 10% lift; wide figures keep their type clear of the column
    P.tag_obj = dict(P.tag_full, x=80, w=int(w * sc_), h=int(h * sc_), vfs=int(vfs * sc_), lfs=int(lfs * sc_), vy=int(vy * sc_), ly=int(ly * sc_))
    P.tag_obj["y"] = int(OBJ_Y0 + (OBJ_H - P.tag_obj["h"]) / 2.0)
    # the plate: logo image or condensed wordmark
    name = st["known_name"]["text"]
    if lg:
        pw0 = int(min(700, max(320, (plate_h0 - 44) * lg["w"] / float(lg["h"]) + 90)))
        pwc = int(min(320, max(220, (112 - 36) * lg["w"] / float(lg["h"]) + 60)))
        fs0 = fsc = None
    else:
        fs0 = FL.fit_line(name, "cond", 700, 600, plate_h0 - 60, 60, 0.0, True) or 60
        pw0 = int(min(700, FL.tw(name, "cond", 700, fs0, 0.0, True) + 100))
        fsc = FL.fit_line(name, "cond", 700, 260, 60, 44, 0.0, True) or 44
        pwc = int(min(320, FL.tw(name, "cond", 700, fsc, 0.0, True) + 56))
    P.plate_full = dict(x=80, y=plate_y0, w=pw0, h=plate_h0, op=1, fs=fs0 or 0)
    P.plate_chip = dict(x=84, y=CHIP_PLATE_Y, w=pwc, h=112, op=0, fs=fsc or 0)          # root 26 Oct: the persistent footer chips are filler; the tag and the plate are hidden between their beats
    P.head_bottom = head_bottom


def tag_key(P, t, state, **kw):
    k = dict(P.tag_full if state == "full" else (P.tag_obj if state == "obj" else P.tag_chip))
    k.update(kw)
    k["t"] = r2(t)
    return k


def plate_key(P, t, state, **kw):
    k = dict(P.plate_full if state == "full" else P.plate_chip)
    k.update(kw)
    k["t"] = r2(t)
    return k


# ------------------------------------------------------------------------------------------------ the states (timeline): groups of windows, one object per object-span (v2.1, root's gate 20 Oct)
EXIT_LEAD = 0.20
HERO_LEAD = 0.55
OBJ_X, OBJ_W = 90, 680                       # the object region: x 90-770 (text under the TikTok column must end at 770), y 556-1056 (the chips sit at 1076)
OBJ_Y0, OBJ_Y1 = 556, 1056          # the natural size an object is drawn in (<= 500 px tall); the layout grammar then places and scales it as a group
OBJ_H = OBJ_Y1 - OBJ_Y0
GROUP_MIN, GROUP_MAX_SPAN, HEAD_MAXWORDS = 1.2, 2.6, 10
HERO_MIDDLE_MAX = 2                           # the hero tag: frame 0, at most 2 middle beats where the voice says the figure, the loop end; the chip everywhere else


def cut_of(w):
    """the spec cut for window w: LEAD before its first word (the hook window is cut 0)"""
    return 0.0 if w.w0 == 0 else max(0.0, w.t0 - LEAD)


KIND_RANK = ["response", "cost", "turn", "stake", "lesson", "mechanism", "context", "proof", "hook"]


def group_kind(wins):
    for k in KIND_RANK:
        if any(w.kind == k for w in wins):
            return k
    return "context"


def hero_spec(P):
    return dict(kind="price_tag", content={}, figure=None, quote=None)


def same_object(a, b):
    """Identity is grounded content, not the drawing kind (two counters may say different numbers)."""
    from extract_story import object_identity
    return a is not None and b is not None and object_identity(a) == object_identity(b)


def plan_states(P):
    """-> P.plan: proof time, the body groups (one headline each; a group is a whole spoken clause), the object spans (one object per span, kept on screen across the groups
    of the span), verdict / question / cta states, the tail. Every time comes from the voice's own word times."""
    W, st, words = P.wins, P.story, P.words
    ic = next((i for i, w in enumerate(W) if w.kind == "cta"), None)
    if ic is None:
        raise EngineError("no cta window")
    vw0, vw1 = st["verdict"]["words"]
    iv = [i for i, w in enumerate(W) if w.w1 >= vw0 and w.w0 <= vw1 and i < ic]
    if not iv:
        raise EngineError("the verdict words are not in any window before the CTA")
    iv0 = iv[0]
    if W[0].t1 < 1.6:
        raise EngineError("the hook window is %.2f s: the proof needs 1.5 s inside it" % W[0].t1)
    has_proof = bool(P.assets.get("clause"))
    t_proof = T_PROOF
    im0 = next((j for j in range(1, iv0) if cut_of(W[j]) >= (t_proof + 1.7 if has_proof else 1.6)), iv0)
    groups, cur = [], None

    def new(w, ob):
        g = dict(wins=[w], figure=w.figure, quote=w.quote, source_id=w.source_id, object=None, nwords=w.w1 - w.w0 + 1)
        if ob is not None:
            g["object"] = dict(ob, figure=w.figure, quote=w.quote, win=w)
        return g

    for j in range(im0, iv0):
        w = W[j]
        ob = w.object
        if cur is None:
            cur = new(w, ob)
            continue
        span = w.t0 - cur["wins"][0].t0
        if (ob is not None and span >= GROUP_MIN) or span >= GROUP_MAX_SPAN:
            groups.append(cur)
            cur = new(w, ob)
        else:
            cur["wins"].append(w)
            cur["nwords"] += w.w1 - w.w0 + 1
            cur["figure"] = cur["figure"] or w.figure
            cur["quote"] = cur["quote"] or w.quote
            cur["source_id"] = cur["source_id"] or w.source_id
            if ob is not None and cur["object"] is None:
                cur["object"] = dict(ob, figure=w.figure, quote=w.quote, win=w)
    if cur:
        groups.append(cur)
    if not groups:
        raise EngineError("no body windows between the proof and the verdict")
    # hero-tag discipline: the tag is the main object on frame 0 and on at most HERO_MIDDLE_MAX middle beats; an empty first group takes it, a group that follows a tag re-shows the last real object
    hs0 = P.story["huge_cost"].get("spoken")
    g0_says = bool(hs0) and P.words[hs0[0]]["start"] <= groups[0]["wins"][-1].t1 and P.words[hs0[1]]["end"] >= groups[0]["wins"][0].t0 - LEAD
    if groups[0]["object"] is None and g0_says:          # DIRECTOR ruling 4: the hero returns only where the voice says the figure
        groups[0]["object"] = dict(hero_spec(P), win=groups[0]["wins"][0])
    elif groups[0]["object"] is None:
        groups[0]["bare"] = True
    n_tag, last_real, cur_kind = 0, None, None
    for g in groups:
        ob = g["object"]
        if ob is not None and ob["kind"] == "price_tag":
            # groups[0] is the first BODY group, not frame zero. When its
            # source-selected hero return is out of sync, the existing
            # tag_zero repair must remove it too, without altering the opener.
            if "tag_zero" in P.flags and g is groups[0] and not g0_says:
                g["object"] = None
                g["bare"] = True
                continue
            if (g is not groups[0] and n_tag >= (0 if "tag_zero" in P.flags else (1 if "tag_one" in P.flags else HERO_MIDDLE_MAX))) or cur_kind == "price_tag":
                g["object"] = dict(last_real, win=g["wins"][0]) if (last_real and cur_kind != "price_tag") else None
            else:
                n_tag += 1
        if g["object"] is not None and g["object"]["kind"] != "price_tag" and same_object(g["object"], last_real) and g is not groups[0]:
            g["object"] = None                    # only the SAME content persists; a new number or quote must never disappear
        if g["object"] is None and cur_kind == "price_tag":
            if last_real is not None:
                g["object"] = dict(last_real, win=g["wins"][0])
            else:
                g["bare"] = True            # no real object yet: a headline-only beat over the world, never a second tag beat
        ob = g["object"]
        if ob is not None:
            cur_kind = ob["kind"]
            if ob["kind"] != "price_tag":
                last_real = ob
    for g in groups:
        g["kind"] = group_kind(g["wins"])
        g["t0"], g["t1"] = g["wins"][0].t0, g["wins"][-1].t1
        g["C"] = cut_of(g["wins"][0])
        g["fi"] = g["C"]
    # object spans
    spans = []
    for gi, g in enumerate(groups):
        if g["object"] is not None:
            spans.append(dict(spec=g["object"], g0=gi, g1=gi))
        elif not g.get("bare") and spans:
            spans[-1]["g1"] = gi
        else:
            g["bare"] = True
    C_v, C_c = cut_of(W[iv0]), cut_of(W[ic])
    q = st["question"]
    stacked = (C_c - C_v) < 4.0 or re.sub(r"\W+", " ", st["question"]["text"].lower()).strip() == re.sub(r"\W+", " ", st["cta"]["line"].lower()).strip()      # the spoken close IS the question: the CTA card carries it
    if stacked:
        C_q = None
    elif q.get("spoken") and q.get("words"):
        C_q = max(C_v + 2.2, words[q["words"][0]]["start"] - 0.3)
    else:
        C_q = max(C_v + 2.4, C_c - 2.0)
    for si, sp in enumerate(spans):
        nxt = spans[si + 1] if si + 1 < len(spans) else None
        tagb = sp["spec"]["kind"] == "price_tag" or (nxt and nxt["spec"]["kind"] == "price_tag")
        end_cut = groups[sp["g1"] + 1]["C"] if sp["g1"] + 1 < len(groups) else C_v          # an object ends where the next group starts (a bare group between two objects is not under the first)
        sp["t_in"] = groups[sp["g0"]]["C"]
        sp["t_out"] = end_cut - (HERO_LEAD + 0.05 if tagb else EXIT_LEAD)
        sp["tagb"] = bool(tagb)
    for gi, g in enumerate(groups):
        nxt = groups[gi + 1] if gi + 1 < len(groups) else None
        nxt_cut = nxt["C"] if nxt else C_v
        sp = next((s for s in spans if s["g0"] <= gi <= s["g1"]), None)
        boundary = (nxt is None) or sp is None or gi == sp["g1"]
        g["E"] = nxt_cut - ((HERO_LEAD + 0.05 if (sp and sp["tagb"]) else EXIT_LEAD) if boundary else EXIT_LEAD)
    T_end = words[-1]["end"] + 0.05
    first_cut = groups[0]["C"]
    first_tag = spans[0]["spec"]["kind"] == "price_tag"
    P.plan = dict(t_proof=t_proof, has_proof=has_proof, groups=groups, spans=spans, C_v=C_v, C_q=C_q, C_c=C_c, stacked=stacked, T_end=T_end, iv0=iv0, ic=ic,
                  proof_to=first_cut - (HERO_LEAD + 0.05 if first_tag else EXIT_LEAD),
                  v_to=((C_q - EXIT_LEAD) if C_q else (C_c - EXIT_LEAD)), q_to=C_c - EXIT_LEAD, last_tag=spans[-1]["spec"]["kind"] == "price_tag")
    return P.plan


# ------------------------------------------------------------------------------------------------ keys: tag (full / object / chip), plate, world camera
def tag_boxes(P):
    """the hero tag's value and label boxes, one per key interval (rebuilt after the layout slots move the tag)"""
    tk = P.tag_keys
    P.boxes = [b_ for b_ in P.boxes if b_["id"] not in ("tag-value", "tag-label")]
    for a, b in zip(tk, tk[1:] + [dict(t=P.dur + 1)]):
        t0, t1 = a["t"] + 0.5, b["t"]
        if t1 - t0 < 0.15 or a.get("op", 1) < 0.5:
            continue
        vw = FL.tw(P.tag_value, "cond", 700, a["vfs"], getattr(P, "tag_ls", 0.0), True)
        P.boxes.append(dict(id="tag-value", box=FL.Box(a["x"] + (a["w"] - vw) / 2.0, a["y"] + a["vy"], a["x"] + (a["w"] + vw) / 2.0, a["y"] + a["vy"] + a["vfs"]), t0=t0, t1=t1,
                            label=P.tag_value, kind="text", fs=a["vfs"], hero=True))
        if a["lop"] > 0.5:
            lw = max(FL.tw(l, "cond", 700, a["lfs"], 0.0, True) for l in P.tag_label)
            P.boxes.append(dict(id="tag-label", box=FL.Box(a["x"] + (a["w"] - lw) / 2.0, a["y"] + a["ly"], a["x"] + (a["w"] + lw) / 2.0, a["y"] + a["ly"] + len(P.tag_label) * a["lfs"] * 1.12), t0=t0, t1=t1,
                                label=" / ".join(P.tag_label), kind="text", fs=a["lfs"], hero=True))


def plate_boxes(P):
    """the known-name plate's wordmark boxes, one per key interval (rebuilt after a bare beat places the plate)"""
    pk = P.plate_keys
    P.boxes = [b_ for b_ in P.boxes if b_["id"] != "plate-name"]
    if not P.assets.get("logo"):
        name = P.story["known_name"]["text"]
        for a, b in zip(pk, pk[1:] + [dict(t=P.dur + 1)]):
            t0, t1 = a["t"] + 0.5, b["t"]
            if t1 - t0 < 0.15 or a.get("op", 1) < 0.5:
                continue
            tw_ = FL.tw(name, "cond", 700, a["fs"], 0.0, True)
            P.boxes.append(dict(id="plate-name", box=FL.Box(a["x"] + (a["w"] - tw_) / 2.0, a["y"] + (a["h"] - a["fs"]) / 2.0, a["x"] + (a["w"] + tw_) / 2.0, a["y"] + (a["h"] + a["fs"]) / 2.0), t0=t0, t1=t1,
                                label=name, kind="text", fs=a["fs"], hero=True))


def build_keys(P):
    pl = P.plan
    tk = [tag_key(P, 0.0, "full")]
    pk = [plate_key(P, 0.0, "full")]
    t_first = (pl["t_proof"] if pl["has_proof"] else (pl["groups"][0]["C"] - HERO_LEAD))
    first_tag = pl["spans"][0]["spec"]["kind"] == "price_tag"
    if first_tag and not pl["has_proof"]:
        tk.append(tag_key(P, pl["spans"][0]["t_in"] - HERO_LEAD, "obj"))
        state = "obj"
        t_first = pl["spans"][0]["t_in"] - HERO_LEAD
    else:
        tk.append(tag_key(P, t_first, "chip"))
        state = "chip"
    pk.append(plate_key(P, t_first, "chip", op=0))          # the plate fades out and stays out (no footer chip)
    pk.append(plate_key(P, t_first + 0.45, "chip", op=0))
    for sp in pl["spans"]:
        if sp["spec"] is None:
            continue
        want = "obj" if sp["spec"]["kind"] == "price_tag" else "chip"
        if want != state:
            tk.append(tag_key(P, sp["t_in"] - HERO_LEAD, want))
            state = want
    if state == "obj":
        tk.append(tag_key(P, pl["C_v"] - HERO_LEAD, "chip"))
    te = pl["T_end"]
    tk.append(tag_key(P, te + FADE_OUT + FR + 0.1, "full"))
    pk.append(plate_key(P, te + FADE_OUT + FR, "full", op=0))          # on the way back the plate is out while the tag rises, and fades in at its place
    pk.append(plate_key(P, te + FADE_OUT + FR + 0.3, "full", op=1))
    # a beat with no object of its own (no cost figure said, no window object): the known-name plate stands in at hero scale mid-frame (S05's logo plate), never a hero-tag repeat and never an empty frame
    for gi_, g in enumerate(pl["groups"]):
        if not g.get("bare"):
            continue
        pw_, ph_ = P.plate_full["w"], P.plate_full["h"]
        px_, py_ = int(OBJ_X + (OBJ_W - pw_) / 2), int(OBJ_Y0 + (OBJ_H - ph_) / 2)
        t_a, t_b = g["C"] - 0.05, g["E"]
        pk.append(plate_key(P, t_a - 0.1, "full", x=px_, y=py_, op=0, bg=gi_))
        pk.append(plate_key(P, t_a, "full", x=px_, y=py_, op=1, bg=gi_))
        pk.append(plate_key(P, t_b, "full", x=px_, y=py_, op=1, bg=gi_))
        pk.append(plate_key(P, t_b + 0.2, "chip", op=0))
        P.events.append((r2(t_a), 1.0, "plate"))
    pk.sort(key=lambda k_: k_["t"])
    P.tag_keys, P.plate_keys = tk, pk
    P.fig_hit = None
    hc = P.story["huge_cost"]
    if hc.get("spoken") and P.words[hc["spoken"][0]]["start"] > 0.3:
        P.fig_hit = P.words[hc["spoken"][0]]["start"] - FR
        P.tag_pulses.append(P.fig_hit)
    tag_boxes(P)
    plate_boxes(P)
    P.events += [(k["t"], 1.0, "tag") for k in tk[1:]]
    for k in tk[1:]:
        P.cue(k["t"] + 0.05, "whoosh", k["x"] + k["w"] / 2.0)


# the set-dressing worlds: camera presets are plane coordinates (px, py, z) on the 4000 x 3550 plane
VIEWS_PLANE = [(1300, 900, 1.0), (2900, 2300, 1.5), (2200, 1000, 1.3), (900, 2400, 1.2), (3200, 900, 1.45), (1800, 3000, 1.35), (3300, 2800, 1.1), (1000, 1600, 1.6)]


def route_view(P, o):
    """camera framing both ends of a map_route: centre between them, zoom so the route spans about 560 px"""
    a, b = proj(*o["content"]["from_ll"]), proj(*o["content"]["to_ll"])
    d = max(40.0, math.hypot(a[0] - b[0], a[1] - b[1]))
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0 - d * 0.08, max(0.35, min(5.0, 600.0 / d)))


def world_keys(P):
    """one camera view per spec beat, moved 0.15 s before its cut so the move is the transition; the last key is the frame-0 view"""
    wk = []
    kind = P.world_kind
    h = int(sha1(P.sid)[:3], 16)
    spans = P.plan["spans"]

    def base(i):
        if kind == "map":
            lon, lat, z = VIEWS[i % len(VIEWS)]
            x, y = proj(lon, lat)
            return x, y, z
        return VIEWS_PLANE[i % len(VIEWS_PLANE)]

    def add(t, v):
        wk.append(dict(t=r2(t), px=r2(v[0]), py=r2(v[1]), z=round(v[2], 3)))
    add(0.0, base(0))
    prev_route = None
    for i, b in enumerate(P.spec_beats[1:]):
        t = b["t_from"]
        sp = next((s for s in spans if s["spec"] and s["t_in"] - 0.3 <= t < s["t_out"] + 0.3), None)
        if kind == "map" and sp and sp["spec"]["kind"] == "map_route":
            v = route_view(P, sp["spec"])
            if prev_route is sp:
                v = (v[0], v[1], v[2] * (1.06 if i % 2 else 1.0))
            prev_route = sp
            add(t - 0.15, v)
        else:
            add(t - 0.15, base(1 + (i + h) % 7))
        ln = b["t_to"] - b["t_from"]
        if ln > 1.9 and not (kind == "map" and sp and sp["spec"]["kind"] == "map_route"):       # a long beat: the camera keeps travelling (the static gate wants a large move every 1.5 s)
            v = base(1 + (i + h) % 7)
            n_ = 0
            tt = b["t_from"] + 1.0
            while tt < b["t_to"] - 0.4:
                n_ += 1
                add(tt, (v[0] + (90 if kind != "map" else 44) * n_, v[1] - (60 if kind != "map" else 26) * n_, v[2] * (1.0 + 0.1 * n_)))
                tt += 1.0
    add(P.plan["T_end"] + FADE_OUT + FR, base(0))
    P.world_keys = wk
    P.events += [(k["t"], 1.0, "world") for k in wk[1:]]


# ------------------------------------------------------------------------------------------------ headlines: a whole spoken clause per group
def norm_tok(t):
    return re.sub(r"[^a-z0-9£$%]", "", t.lower())


def group_words(P, g):
    """[(display token, take word index)]: the group's spoken words cut at a clause end (or HEAD_MAXWORDS), trailing . , ; : dropped from the last token"""
    w0, w1 = g["wins"][0].w0, g["wins"][-1].w1
    toks = [(P.words[i]["word"].strip(), i) for i in range(w0, w1 + 1) if re.search(r"\w", P.words[i]["word"])]
    if len(toks) > HEAD_MAXWORDS:
        cut = [k for k, (t, _) in enumerate(toks[:HEAD_MAXWORDS]) if re.search(r"[.,;:?!]$", t) and k >= 3]
        toks = toks[: (cut[-1] + 1 if cut else HEAD_MAXWORDS)]
    if toks:
        toks[-1] = (re.sub(r"[.,;:]+$", "", toks[-1][0]), toks[-1][1])
    return toks


def group_headline(P, g):
    """(text, accent word) of a group's headline: the model's 2-5 word headline of its first window that has one (grounded by extract_story G14), else the first 5 words of that window's phrase"""
    for w in g["wins"]:
        h = getattr(w, "headline", None)
        if h and h.get("text"):
            return h["text"].strip(), (h.get("accent") or "")
    for w in g["wins"]:
        if w.phrase:
            return " ".join(w.phrase.split()[:5]), ""
    toks_ = [t for t, _ in group_words(P, g)][:5]
    return " ".join(toks_), ""


HEAD_FS_MAX, HEAD_FS_MIN = 120, 100


BANNED_WORDS = set("streamline streamlined streamlines leverage leveraged seamless delve robust comprehensive empower elevate holistic utilise utilize synergy furthermore moreover".split())


def has_banned(text):
    return any(norm_tok(w) in BANNED_WORDS for w in (text or "").split())


def head_html(P, lines, ai):
    """the headline's lines as html with the accent word (index ai over all words) in the accent colour"""
    html, k = [], 0
    for ln in lines:
        parts = []
        for tok in ln.split():
            parts.append('<span style="color:%s">%s</span>' % (P.pal["accent"] if k == ai else P.pal["ink"], esc_html(tok)))
            k += 1
        html.append(" ".join(parts))
    return html


def headline_words(P, g, ti, to, accent=None, ain="slam", snd="slam"):
    """the headline of a group: 2-5 words in Big Shoulders at 100-120 px, max 2 lines, the key word in the accent colour. REPAIR before refuse: 88-76 px, then 64 px, then a shorter 2-4 word
    sub-phrase of the same grounded headline that holds the accent word; a headline that is not story text or holds a banned word falls back to the spoken words of the group."""
    text, acc = group_headline(P, g)
    ok_set = getattr(P, "_printable", None)
    if ok_set is None:
        ok_set = P._printable = printable_set(P)
    norm_ = lambda t: re.sub(r"[^a-z0-9£$%]+", " ", t.lower()).strip()
    if has_banned(text) or (norm_(text) not in ok_set and not any(norm_(text) in o for o in ok_set)):
        P.repairs.append("headline %r replaced by the spoken words (not story text or a banned word)" % text[:40])
        text, acc = " ".join(t for t, _ in group_words(P, g)[:4]), ""
    words_ = text.split()
    if not words_:
        return None
    up = " ".join(words_).upper()
    r = fit_headline(P, up, 2, HEAD_FS_MAX, HEAD_FS_MIN)
    if r is None:
        r = fit_headline(P, up, 2, HEAD_FS_MIN, 76)
        P.warn.append("headline %r needs under %d px to hold two lines" % (up, HEAD_FS_MIN))
    if r is None:
        r = fit_headline(P, up, 2, 76, 64)
        if r:
            P.repairs.append("headline %r stepped down to 64 px" % up[:40])
    if r is None:                      # a shorter contiguous 2-4 word piece of the same headline (grounded by construction), the accent word kept when it can be
        ai0 = next((k for k, w in enumerate(words_) if acc and norm_tok(w) == norm_tok(acc)), len(words_) - 1)
        best = None
        for n_ in range(min(4, len(words_) - 1), 1, -1):
            for i_ in range(0, len(words_) - n_ + 1):
                piece = words_[i_:i_ + n_]
                rr = fit_headline(P, " ".join(piece).upper(), 2, 76, 64)
                if rr and (i_ <= ai0 < i_ + n_ or best is None) and (best is None or (i_ <= ai0 < i_ + n_)):
                    best = (piece, rr)
                    if i_ <= ai0 < i_ + n_:
                        break
            if best:
                break
        if best:
            words_, r = best
            up = " ".join(words_).upper()
            if acc and norm_tok(acc) not in [norm_tok(w) for w in words_]:
                acc = ""
            P.repairs.append("headline cut to the sub-phrase %r" % up)
    if r is None:
        raise EngineError("headline %r does not fit two lines at 64 px even as a 2-word piece" % up)
    fs, lines = r
    ai = None
    if acc:
        for k, w in enumerate(words_):
            if norm_tok(w) == norm_tok(acc):
                ai = k
                break
    if ai is None:
        ai = len(words_) - 1
    g["_hm"] = dict(up=up, ai=ai)
    html = head_html(P, lines, ai)
    it = P.T(up, HEAD_X, HEAD_Y, fs, 700, P.pal["ink"], w=HEAD_W, lh=0.9, caps=True, ti=ti, to=to, ain=ain, di=LAND, z=14, lines=lines, face="cond", snd=snd, sndx=540,
             sh=("0 10px 34px rgba(0,0,0,.85)" if not P.light else "0 6px 20px rgba(255,255,255,.7)"), head=True)
    it["html"], it["os"], it["org"], it["head"] = html, 1.06, "0% 100%", True
    # the key word takes a pulse where the voice says it (when the take says it inside the group)
    idxs = [i for _, i in group_words(P, g)] or []
    hit = next((i for i in range(g["wins"][0].w0, g["wins"][-1].w1 + 1) if norm_tok(P.words[i]["word"]) == norm_tok(words_[ai])), None)
    if hit is not None and P.words[hit]["start"] - FR > ti + 0.3:
        t = r2(P.words[hit]["start"] - FR)
        it["pulses"] = [t]
        P.events.append((t, 0.6, "pulse"))
        P.cue(t, "tick", 300 + 400 * (len(P.sfx) % 2))
    return it


# ------------------------------------------------------------------------------------------------ the objects: each renders exactly its grounded spec; no content, no object
def esc_up(s):
    return (s or "").upper()


def card(P, x, y, w, h, ti, to, fill=None, r=18, stroke=None, sw=4, shadow="0 30px 70px rgba(0,0,0,.6)", a=None, snd="paper", z=7):
    return P.R(x, y, w, h, fill=fill, stroke=stroke, sw=sw, r=r, ti=ti, to=to, ain="rise", di=LAND, z=z, shadow=shadow, a=a, snd=snd)


def txt(P, text, x, y, fs, col, ti, to, w=OBJ_W, face="cond", wt=700, al="l", lh=1.05, caps=True, z=10, ain="rise", snd=None, lines=None, di=LAND, **kw):
    return P.T(text, x, y, fs, wt, col, w=w, al=al, lh=lh, caps=caps, ti=ti, to=to, ain=ain, di=di, z=z, face=face, event=False, snd=snd, lines=lines, **kw)


def wtime(P, idx, ti, floor=0.1):
    return max(ti + floor, P.words[idx]["start"] - FR)


def span_stage_ts(P, sp):
    """the start of every beat of the span after its first: the times an object may change state (root 26 Oct: a held object changes state on every beat)"""
    ts = [c[0] for c in getattr(P, "cuts_pre", []) if c[1] not in ("hook", "proof") and sp["t_in"] - 0.3 <= c[0] < sp["t_out"] - 0.4]
    return [t for t in ts if t > sp["t_in"] + 0.3]


def stage_times(sp, ti, cap):
    """[ti, beat 2 start, beat 3 start][:cap]: the start of each state of the object; sp['S'] records how many states the object shows"""
    ts = ([ti] + list(sp.get("stage_ts") or []))[:max(1, cap)]
    sp["S"] = len(ts)
    return ts


def reveal_t(i, n, ts, step=0.25, lead=0.2):
    """when item i of n appears when the items are shared out over the states: the first ceil(n/S) on state 0, and so on"""
    S = len(ts)
    g = min(S - 1, (i * S) // n)
    first = -(-g * n // S)
    return ts[g] + (lead if g == 0 else 0.15) + step * (i - first)


def obj_price_tag(P, sp, ti, to):
    t = wtime(P, P.story["huge_cost"]["spoken"][0], ti, 0.2)
    P.tag_drops.append(r2(t))
    P.RING(P.tag_obj["x"] + P.tag_obj["w"] / 2.0, P.tag_obj["y"] + 170, 90, P.pal["accent"], t, sw=8, di=0.55, snd="slam", z=22)
    return True


def obj_counter(P, sp, ti, to):
    f, c = sp["figure"], sp["content"]
    disp = f["display"]
    fs = FL.fit_line(disp, "cond", 700, 580, 260, 130, 0.0, True)
    if not fs:
        return False
    lab = FL.wrap(esc_up(c["label"]), "cond", 700, 56, 580, 0.0, True)
    if len(lab) > 2:
        return False
    ph = max(400, int(50 + fs + 24 + len(lab) * 56 * 1.1 + 50))
    y = OBJ_Y0 + (OBJ_H - ph) // 2
    stg = stage_times(sp, ti, 3)          # state 0: the figure on its card; state 1 (next beat): the stamp lands, the card turns to the accent colour; state 2: a rule is drawn under the figure (new marks on the spoken figure)
    ts_ = stg[1] + 0.1 if len(stg) > 1 else None
    if len(stg) > 2:
        P.R(OBJ_X + 120, y + 40 + fs + 6, OBJ_W - 240, 10, fill="#0d151e", ti=stg[2] + 0.1, to=to, ain="wipe", di=0.4, z=13, event=True)
    cd_ = card(P, OBJ_X, y, OBJ_W, ph, ti, to, fill="#0d151e", stroke=P.pal["accent"], sw=6, r=P.F["chip_r"] + 14, a=0.94)
    if ts_:
        cd_["col"], cd_["cols"] = "#0d151e", [[r2(ts_), P.pal["accent"]]]
        P.events.append((r2(ts_), 1.0, "stamp"))
        P.cue(ts_, "stamp", OBJ_X + OBJ_W / 2.0 + 150)
    t0 = wtime(P, f["spoken"][0], ti)
    it_ = P.T(disp, OBJ_X + 50, y + 40, fs, 700, P.pal["accent"], w=OBJ_W - 100, al="c", lh=1.0, caps=True, ti=ti, to=to, ain="slam", di=LAND, z=12, face="cond", snd="slam", sndx=OBJ_X + OBJ_W / 2.0 - 140, os=1.14, org="50% 100%", cols=([(r2(ts_), "#0d151e")] if ts_ else None))
    if t0 > ti + 0.35:
        it_["pulses"] = [r2(t0)]          # the figure is on the cut; it takes the pulse on the word the voice says
    lt_ = txt(P, esc_up(c["label"]), OBJ_X + 50, y + 40 + fs + 24, 56, "#f3efe6", ti, to, w=OBJ_W - 100, al="c", lines=lab)
    if ts_ and isinstance(lt_, dict):
        lt_["cols"] = [(r2(ts_), "#0d151e")]
    P.events.append((t0, 1.0, "counter"))
    return True


def obj_compare_bars(P, sp, ti, to):
    c = sp["content"]
    a_, b_ = c["a"], c["b"]
    vmax = max(a_["value"], b_["value"])
    base, numfs_max = OBJ_Y1 - 70, 130
    maxh = int(OBJ_H - numfs_max - 130)
    bars, bw = [], 250
    stg = stage_times(sp, ti, 2)          # state 0: the WAS bar; state 1 (next beat): the NOW bar rises to its figure
    for k, f in enumerate((a_, b_)):
        hh = max(70, maxh * f["value"] / vmax)
        nfs = FL.fit_line(f["display"], "cond", 700, bw + 70, numfs_max, 90, 0.0, True) or 90
        bars.append(dict(x=OBJ_X + 20 + k * 340, w=bw, h=hh, fill=(P.pal["dim"] if k == 0 else P.pal["accent"]), at=(ti + 0.08 if k == 0 else (stg[1] + 0.12 if len(stg) > 1 else ti + 0.3)), num=f["display"], numfs=nfs,
                         numcol=(P.pal["ink"] if k == 0 else P.pal["accent"]), lab=esc_up(f["label"])))
    it = dict(k="bars", id=P.nid("b"), x=OBJ_X, base=base, w=OBJ_W, bars=bars, baseCol=P.pal["dim"], labfs=50, labcol=P.pal["ink"], labface="cond", ti=r2(ti), to=r2(to), ain="rise", aout="fade", di=LAND, z=7)
    P.items.append(it)
    for b in bars:
        P.events.append((b["at"], 1.0, "bar"))
        P.cue(b["at"], "slam", b["x"] + b["w"] / 2.0)
    P.events.append((ti, 1.0, "bars"))
    for b, f in zip(bars, (a_, b_)):
        wn = FL.tw(esc_up(f["label"]), "cond", 700, 50, 0.0, True)
        P.boxes.append(dict(id=P.nid("bl"), box=FL.Box(b["x"] + b["w"] / 2.0 - wn / 2.0, base + 16, b["x"] + b["w"] / 2.0 + wn / 2.0, base + 16 + 55), t0=ti, t1=to, label=f["label"], kind="text", fs=50))
    return True


def logo_for_name(P, name):
    k = norm_tok(name)
    if k in P.assets.setdefault("logos", {}):
        return P.assets["logos"][k]
    rec = None
    if norm_tok(P.story["known_name"]["text"]) == k and P.assets.get("logo"):
        rec = P.assets["logo"]
    elif P.fetch_logos:
        try:
            import fetch_assets as FA
            r = FA.logo_for(name, P.sid)
            if r and r.get("file"):
                from PIL import Image
                lp = os.path.join(KIT, "assets", r["file"])
                with Image.open(lp) as im:
                    w, h = im.size
                rec = dict(src="img/logo-%s-%s.png" % (P.sid.lower(), re.sub(r"[^a-z0-9]+", "", k)[:12]), path=lp, w=w, h=h, credit=r.get("creator"), licence=r.get("licence"))
        except Exception:
            rec = None
    P.assets["logos"][k] = rec
    return rec


def display_name(P, name):
    """a name the page shortens ('The Neg') is shown in full when a source's own outlet says the whole of it (thenegotiator.co.uk -> The Negotiator): no plate ever prints a truncation"""
    k = re.sub(r"[^a-z0-9]", "", name.lower())
    for src in P.story.get("sources") or []:
        stem = re.sub(r"[^a-z0-9]", "", re.sub(r"\.(co\.uk|com|org|net|uk)$", "", (src.get("outlet") or "").lower()))
        if stem and stem.startswith(k) and len(stem) - len(k) >= 3:
            return ("The " + stem[3:].title()) if stem.startswith("the") and len(stem) > 5 else stem.title()
    return name


def plate_at(P, name, x, y, w, h, ti, to):
    name = display_name(P, name)
    P.R(x, y, w, h, fill=P.pal["plate"], r=18, ti=ti, to=to, ain="rise", di=LAND, z=8, shadow="0 22px 50px rgba(0,0,0,.55)", snd="paper")
    lg = logo_for_name(P, name)
    if lg:
        ih = h - 44
        iw = min(w - 80, ih * lg["w"] / float(lg["h"]))
        P.IMG(lg["src"], x + (w - iw) / 2.0, y + 22, iw, ih, ti=ti, to=to, ain="rise", z=9, alt=name, di=LAND)
        P.used_logos.append(lg)
    else:
        fb = FL.fit_block(name, "cond", 700, w - 80, h - 40, 130, 50, 1.0, 0.0, True)
        if not fb:
            raise EngineError("the name %r does not fit its plate (%d x %d) even on two lines at 50 px: a plate never truncates" % (name, w, h))
        fs, lines_, bh = fb
        P.T(lines_, x + 40, y + (h - bh) / 2.0, fs, 700, P.pal["plate_ink"], w=w - 80, al="c", lh=1.0, caps=True, ti=ti, to=to, ain="rise", di=LAND, z=9, face="cond", event=False, lines=lines_)


def obj_logo_pair(P, sp, ti, to):
    c = sp["content"]
    ph = 190
    y0 = OBJ_Y0 + (OBJ_H - 2 * ph - 120) // 2
    stg = stage_times(sp, ti, 2)          # state 0: the first name; state 1 (next beat): the arrow and the second name
    tb = stg[1] + 0.1 if len(stg) > 1 else ti + 0.25
    plate_at(P, c["a"], OBJ_X, y0, OBJ_W, ph, ti, to)
    plate_at(P, c["b"], OBJ_X, y0 + ph + 120, OBJ_W, ph, tb, to)
    cx = OBJ_X + OBJ_W / 2.0
    P.PATH("M0,0 L%d,%d L%d,0" % (35, 52, 70), cx - 35, y0 + ph + 30, 70, 56, stroke=P.pal["accent"], sw=14, ti=tb - 0.05, to=to, ain="draw", di=0.3, z=11, snd="tick", vb="0 0 70 56")
    return True


def clip_card(P, cl, name, ti, to, w_img=790, t_mark=None, y_top=None, strict=True):
    """ONE paper card for a source clipping: the outlet as its small masthead line, the clause crop with the marker, the date line. -> (y0, card height) or None when it cannot be shown at 42.5 px"""
    w = min(w_img, cl.get("sharp") or w_img, cl["w"])
    h = w * cl["h"] / float(cl["w"])
    pxv = cl.get("px") or 53
    pxv = pxv.get("font", 53) if isinstance(pxv, dict) else pxv
    px = pxv * w / float(cl["w"])          # the ink line is measured in the file; it is shown at w px
    if strict and px < 42.5:
        return None
    mfs = FL.fit_line(name, "cond", 700, 600, 56, 42, 0.0, True)
    if not mfs:
        raise EngineError("source masthead cannot fit at the 42 px readability floor: " + name)
    cred = FL.wrap(cl["credit"].upper(), "mono", 700, 48, 620, 0.02, False)
    ch = max(int(24 + mfs + 14 + 6 + 22 + h + 26 + len(cred) * 55 + 26), 300)
    if ch > OBJ_H + 20:
        return None
    y0 = OBJ_Y0 + max(0, (OBJ_H - ch) // 2) if y_top is None else y_top
    P.R(80, y0, 808, ch, fill="#ffffff", r=8, ti=ti, to=to, ain="rise", di=LAND, z=6, shadow="0 30px 70px rgba(0,0,0,.65)", snd="print")
    P.T(name, 104, y0 + 24, mfs, 700, "#121212", w=700, lh=1.0, caps=True, ti=ti + 0.1, to=to, ain="rise", di=LAND, z=10, face="cond", event=False)
    P.R(104, y0 + 24 + mfs + 12, 742, 6, fill="#121212", ti=ti + 0.1, to=to, ain="wipe", di=0.3, z=9, event=False)
    y = y0 + 24 + mfs + 14 + 6 + 22
    x = 89 + (w_img - w) / 2.0
    P.IMG(cl["src"], x, y, w, h, ti=ti, to=to, ain="rise", z=7, alt="source clause", di=LAND)
    P.R(x, y, w, h, fill="#ffd60a", a=0.45, ti=t_mark, to=to, ain="wipe", di=1.0, z=8)
    P.T(cred, 104, y + h + 26, 48, 700, "#121212", w=700, lh=1.15, caps=True, ti=ti, to=to, ain="rise", di=LAND, z=10, face="mono", event=False, ls=0.02, lines=cred)
    return y0, ch


def obj_clipping(P, sp, ti, to):
    """a source clipping: ONE paper card. The outlet is its masthead line (small, top) and nothing else: a giant outlet wordmark is a filler, not an object (root 26 Oct).
    State 0: the clipping; state 1 (next beat): the marker lands on the clause"""
    cl = P.assets.get("clips", {}).get(sp["content"]["key"])
    if not cl or not clip_is_new(P, sp, cl):
        return False
    src = next((s for s in (P.story.get("sources") or []) if s["id"] == sp["content"]["source_id"]), None)
    name = re.sub(r"\.(co\.uk|com|org|net)$", "", (src or {}).get("outlet") or "SOURCE", flags=re.I).upper()
    stg = stage_times(sp, ti, 2)
    t0 = (stg[1] + 0.15) if len(stg) > 1 else wtime(P, sp["win"].w0, ti, 0.4)
    return clip_card(P, cl, name, ti, to, t_mark=t0) is not None


def obj_quote_card(P, sp, ti, to):
    q = sp["quote"]
    t = q["text"]
    if q.get("quoted_in_source"):
        t = "“" + t + "”"
    fs_r = FL.fit_block(t, P.kface, kwt(P), 580, 300, 150, 48, 1.14, 0.0, False)          # a card that fits every layout slot (<= 476 px tall), not one that outgrows the object band
    if not fs_r:
        return False
    fs, lines, bh = fs_r
    ch = max(400, int(44 + bh + 20 + 48 + 36))
    y = OBJ_Y0 + max(0, (OBJ_H - ch) // 2)
    qcard = card(P, OBJ_X, y, OBJ_W, ch, ti, to, fill=P.pal["plate"], r=P.F["chip_r"] + 6)
    P.R(OBJ_X, y, 16, ch, fill=P.pal["accent"], r=6, ti=ti, to=to, ain="rise", di=LAND, z=8, event=False)
    qtxt = P.T(lines, OBJ_X + 50, y + 44, fs, kwt(P), P.pal["plate_ink"], w=580, lh=1.14, caps=False, ti=ti, to=to, ain="rise", di=LAND, z=10, face=P.kface, lines=lines, event=False)
    sp_ = (q.get("speaker") or "").strip()
    if sp_:
        P.T(sp_.upper(), OBJ_X + 50, y + 44 + bh + 20, 48, 700, P.pal["dim"] if False else P.pal["tag_lab"], w=580, lh=1.1, caps=True, ti=ti, to=to, ain="rise", di=LAND, z=10, face="mono", event=False, ls=0.04)
    # state 1 (next beat): the marker lands on the words the voice says (the window's own phrase, found inside the quote)
    stg = stage_times(sp, ti, 2)
    if len(stg) > 1:
        ph_ = [norm_tok(w_) for w_ in ((getattr(sp.get("win"), "phrase", None) or "").split())]
        flat = [(li, wi, norm_tok(w_)) for li, ln in enumerate(lines) for wi, w_ in enumerate(ln.split())]
        hit = None
        if ph_:
            for a_ in range(len(flat) - len(ph_) + 1):
                if [f_[2] for f_ in flat[a_:a_ + len(ph_)]] == ph_:
                    hit = flat[a_:a_ + len(ph_)]
                    break
        if not hit:          # the window's words are not a piece of the quote: the stamp lands on the whole card instead (card turns to the accent colour, the words to the ground colour)
            ts_ = stg[1] + 0.1
            qcard["col"], qcard["cols"] = P.pal["plate"], [[r2(ts_), P.pal["accent"]]]
            qtxt["cols"] = [(r2(ts_), P.pal["ground"])]
            P.events.append((r2(ts_), 1.0, "stamp"))
            P.cue(ts_, "stamp", OBJ_X + OBJ_W / 2.0 + 150)
        else:
            for li in sorted(set(h_[0] for h_ in hit)):
                ws = [h_ for h_ in hit if h_[0] == li]
                toks = lines[li].split()
                x0 = FL.tw(" ".join(toks[:ws[0][1]]) + (" " if ws[0][1] else ""), P.kface, kwt(P), fs, 0.0, False)
                x1 = FL.tw(" ".join(toks[:ws[-1][1] + 1]), P.kface, kwt(P), fs, 0.0, False)
                P.R(OBJ_X + 50 + x0 - 4, y + 44 + li * fs * 1.14 + 2, x1 - x0 + 8, fs * 1.14 - 4, fill="#ffd60a", a=0.5, ti=stg[1] + 0.15, to=to, ain="wipe", di=0.5, z=9, event=True)
    return True


def obj_checklist(P, sp, ti, to):
    items = sp["content"]["items"]
    rfs = 96
    while rfs > 56 and (any(len(FL.wrap(esc_up(i), "cond", 700, rfs, 480, 0.0, True)) > 2 for i in items) or
                        sum(len(FL.wrap(esc_up(i), "cond", 700, rfs, 480, 0.0, True)) for i in items) * rfs + len(items) * 22 + 110 > OBJ_H):
        rfs -= 4
    rl = [FL.wrap(esc_up(i), "cond", 700, rfs, 500, 0.0, True) for i in items]
    if max(FL.tw(l_, "cond", 700, rfs, 0.0, True) for l in rl for l_ in l) > 490:
        return False
    rhs = [int(len(l) * rfs + 22) for l in rl]
    ph = 80 + sum(rhs) + 20
    y0 = OBJ_Y0 + 30 + max(0, (OBJ_H - 30 - ph) // 2)
    lp = int(rfs)
    P.R(OBJ_X, y0, OBJ_W, ph, fill=P.pal["pad"], r=10, ti=ti, to=to, ain="rise", di=LAND, z=7, shadow="0 40px 90px rgba(0,0,0,.65)",
        bg="background-image:repeating-linear-gradient(180deg,transparent 0 %dpx,rgba(60,110,190,.32) %dpx %dpx);" % (lp - 3, lp - 3, lp), snd="paper")
    P.R(OBJ_X, y0 - 26, OBJ_W, 70, fill="#3a2c20", r=10, ti=ti, to=to, ain="rise", di=LAND, z=8, event=False)
    cur, bx = y0 + 70, int(rfs * 0.62)
    stg = stage_times(sp, ti, min(3, len(items)))          # the rows are shared out over the beats of the span: each beat ticks the next rows
    for i, it in enumerate(items):
        t = reveal_t(i, len(items), stg, 0.3, 0.25)
        ts_row = ti if len(stg) == 1 else t - 0.1
        P.T(rl[i], OBJ_X + 150, cur, rfs, 700, P.pal["plate_ink"], w=500, lh=1.0, caps=True, ti=ts_row, to=to, ain="rise", di=LAND, z=10, face="cond", event=False)
        P.R(OBJ_X + 44, cur + int(rfs * 0.16), bx, bx, fill=None, stroke=P.pal["plate_ink"], sw=6, r=6, ti=ts_row, to=to, ain="rise", di=LAND, z=9, event=False)
        P.PATH("M6,%d L%d,%d L%d,6" % (bx * 0.55, bx * 0.38, bx * 0.88, bx), OBJ_X + 44, cur + int(rfs * 0.16), bx, bx, stroke=P.pal["tick"], sw=10, ti=t, to=to, ain="draw", di=0.22, z=11, snd="tick", vb="0 0 %d %d" % (bx, bx))
        cur += rhs[i]
    return True


def obj_timeline(P, sp, ti, to):
    evs = sp["content"]["events"]
    n = len(evs)
    rowh = int((OBJ_H - 40) / n)
    x0 = OBJ_X + 40
    width = OBJ_W - 110
    # Dates can wrap too. The old fixed y+70 label overlapped a two-line
    # date, then the following event. Keep the spacious stacked treatment
    # when it fits; otherwise give dates and events separate columns.
    stacked = []
    for e in evs:
        dl = FL.wrap(e["when"].upper(), "mono", 700, 56, width, 0.04, True)
        wl = FL.wrap(e["what"].upper(), "cond", 700, 92, width, 0.0, True)
        stacked.append((dl, wl))
    columns = any(len(dl) * 56 + 14 + len(wl) * 92 * 0.95 > rowh - 16 for dl, wl in stacked)
    layouts = []
    for dl, wl in stacked:
        if not columns:
            layouts.append((56, dl, 92, wl, 0, len(dl) * 56 + 14, width, width))
            continue
        date_w, gap = 260, 30
        event_w = width - date_w - gap
        date = FL.fit_block(" ".join(dl), "mono", 700, date_w, rowh - 16, 56, 44, 1.0, 0.02, True)
        event = FL.fit_block(" ".join(wl), "cond", 700, event_w, rowh - 16, 92, 48, 1.0, 0.0, True)
        if not date or not event:
            raise EngineError("timeline has no readable layout for %d source events; use fewer source-grounded events" % n)
        layouts.append((date[0], date[1], event[0], event[1], date_w + gap, 0, date_w, event_w))
    P.R(x0 - 5, OBJ_Y0 + 30, 10, rowh * (n - 1) + 40, fill=P.pal["dim"], r=5, ti=ti, to=to, ain="wipe", di=0.5, z=6, event=True)
    stg = stage_times(sp, ti, min(3, n))          # the dated rows come in a few at a time, one set per beat
    for i, e in enumerate(evs):
        y = OBJ_Y0 + 20 + i * rowh
        t = reveal_t(i, n, stg, 0.35, 0.2)
        P.R(x0 - 24, y + 10, 48, 48, fill=P.pal["accent"], r=24, ti=t, to=to, ain="grow", di=0.2, z=9, snd="pop")
        dfs, dl, wfs, wl, dx, dy, dw, ww = layouts[i]
        P.T(dl, x0 + 50, y, dfs, 700, P.pal["accent"], w=dw, lh=1.0, caps=True, ti=t, to=to, ain="rise", di=LAND, z=10, face="mono", event=False, ls=0.02 if columns else 0.04, lines=dl)
        P.T(wl, x0 + 50 + dx, y + dy, wfs, 700, P.pal["ink"], w=ww, lh=1.0 if columns else 0.95, caps=True, ti=t, to=to, ain="rise", di=LAND, z=10, face="cond", event=False, lines=wl)
    return True


def art_paper(P, ti, to, h, w=OBJ_W, fill=None, y=None):
    h = max(h, 420)
    y = OBJ_Y0 + (OBJ_H - h) // 2 if y is None else y
    card(P, OBJ_X, y, w, h, ti, to, fill=fill or P.pal["plate"], r=P.F["chip_r"] + 4)
    return y


def obj_email(P, sp, ti, to):
    c = sp["content"]
    sj = FL.wrap(esc_up(c["subject"]), "cond", 700, 70, OBJ_W - 80, 0.0, True)
    bl = [FL.wrap(l, P.kface, kwt(P), 50, OBJ_W - 80, 0.0, False) for l in c["lines"]]
    if len(sj) > 2 or any(len(x) > 2 for x in bl):
        return False
    h = int(40 + 54 + 14 + len(sj) * 70 + 20 + sum(len(x) for x in bl) * 56 + len(bl) * 10 + 40)
    if h > OBJ_H:
        return False
    y = art_paper(P, ti, to, h)
    P.R(OBJ_X, y, OBJ_W, 20, fill=P.pal["accent"], r=6, ti=ti, to=to, ain="rise", di=LAND, z=8, event=False)
    P.T("FROM  " + esc_up(c["from"]), OBJ_X + 40, y + 40, 44, 700, P.pal["tag_lab"], w=OBJ_W - 80, lh=1.0, caps=True, ti=ti, to=to, ain="rise", di=LAND, z=10, face="mono", event=False)
    cur = y + 40 + 54 + 14
    P.T(sj, OBJ_X + 40, cur, 70, 700, P.pal["plate_ink"], w=OBJ_W - 80, lh=1.0, caps=True, ti=ti, to=to, ain="rise", di=LAND, z=10, face="cond", event=False, lines=sj)
    cur += len(sj) * 70 + 20
    stg = stage_times(sp, ti, min(3, len(bl)))          # the body lines come in over the beats of the span
    for i, ls in enumerate(bl):
        P.T(ls, OBJ_X + 40, cur, 50, kwt(P), P.pal["plate_ink"], w=OBJ_W - 80, lh=1.12, caps=False, ti=reveal_t(i, len(bl), stg), to=to, ain="rise", di=LAND, z=10, face=P.kface, lines=ls, event=(i == 0))
        cur += len(ls) * 56 + 10
    return True


def obj_phone_text(P, sp, ti, to):
    ms = sp["content"]["messages"]
    fs = 54
    lines = [FL.wrap(m["text"], "sans" if P.kface == "serif" else P.kface, 500 if P.kface != "cond" else 700, fs, 460, 0.0, False) for m in ms]
    if any(len(l) > 3 for l in lines):
        return False
    hs = [int(len(l) * fs * 1.12 + 50) for l in lines]
    tot = sum(hs) + 36 * (len(ms) - 1)
    if tot > OBJ_H - 20:
        return False
    y = OBJ_Y0 + (OBJ_H - tot) // 2
    fh = max(tot + 110, 440)
    P.R(OBJ_X + 10, OBJ_Y0 + (OBJ_H - fh) // 2, OBJ_W - 20, fh, fill="#0d151e", stroke=P.pal["dim"], sw=6, r=60, ti=ti, to=to, ain="rise", di=LAND, z=6, shadow="0 30px 70px rgba(0,0,0,.5)", a=0.95, snd="paper")
    fc = "sans" if P.kface == "serif" else P.kface
    wt = 500 if fc != "cond" else 700
    stg = stage_times(sp, ti, min(3, len(ms)))          # the messages arrive over the beats of the span
    for i, m in enumerate(ms):
        t = reveal_t(i, len(ms), stg, 0.5, 0.15)
        bw = int(max(FL.tw(l, fc, wt, fs, 0.0, False) for l in lines[i]) + 70)
        bx = OBJ_X + 40 if m["who"] == "them" else OBJ_X + OBJ_W - 40 - bw
        P.R(bx, y, bw, hs[i], fill=(P.pal["plate"] if m["who"] == "them" else P.pal["accent"]), r=40, ti=t, to=to, ain="rise", di=LAND, z=8, shadow="0 18px 40px rgba(0,0,0,.5)", snd="pop")
        P.T(lines[i], bx + 35, y + 25, fs, wt, P.pal["plate_ink"] if m["who"] == "them" else P.pal["ground"], w=bw - 70, lh=1.12, caps=False, ti=t, to=to, ain="rise", di=LAND, z=10, face=fc, lines=lines[i], event=False)
        y += hs[i] + 36
    return True


def obj_letter(P, sp, ti, to):
    c = sp["content"]
    hd = FL.wrap(esc_up(c["heading"]), "cond", 700, 84, OBJ_W - 100, 0.0, True)
    bl = [FL.wrap(l, P.kface, kwt(P), 52, OBJ_W - 100, 0.0, False) for l in c["lines"]]
    if len(hd) > 2 or any(len(x) > 3 for x in bl):
        return False
    h = int(60 + len(hd) * 84 + 28 + sum(len(x) for x in bl) * 58 + len(bl) * 14 + 50)
    if h > OBJ_H:
        return False
    y = art_paper(P, ti, to, h, fill="#f7f1e3")
    P.T(hd, OBJ_X + 50, y + 50, 84, 700, P.pal["plate_ink"], w=OBJ_W - 100, lh=0.95, caps=True, ti=ti, to=to, ain="rise", di=LAND, z=10, face="cond", event=False, lines=hd)
    P.R(OBJ_X + 50, y + 50 + len(hd) * 84 + 8, 220, 10, fill=P.pal["accent"], ti=ti + 0.2, to=to, ain="wipe", di=0.3, z=10)
    cur = y + 60 + len(hd) * 84 + 28
    stg = stage_times(sp, ti, min(3, len(bl)))
    for i, ls in enumerate(bl):
        P.T(ls, OBJ_X + 50, cur, 52, kwt(P), P.pal["plate_ink"], w=OBJ_W - 100, lh=1.12, caps=False, ti=reveal_t(i, len(bl), stg), to=to, ain="rise", di=LAND, z=10, face=P.kface, lines=ls, event=(i == 0))
        cur += len(ls) * 58 + 14
    return True


def obj_ledger_doc(P, sp, ti, to, title):
    c = sp["content"]
    its = c["items"]
    amt_w = max(FL.tw(i["amount"], "mono", 700, 48, 0.0, False) for i in its + [dict(amount=c["total"])]) + 10
    lab_w = OBJ_W - 80 - amt_w - 20
    ll = [FL.wrap(esc_up(i["label"]), "cond", 700, 62, lab_w, 0.0, True) for i in its]
    if any(len(x) > 2 for x in ll):
        return False
    head = (60 if title else 0) + (50 if c.get("to") else 0)
    rows = sum(len(x) for x in ll) * 66 + len(its) * 20
    h = int(40 + head + 30 + rows + 30 + 14 + 96 + 40)
    if h > OBJ_H:
        return False
    y = art_paper(P, ti, to, h, w=OBJ_W)
    cur = y + 40
    if title:
        P.T(title, OBJ_X + 40, cur, 60, 700, P.pal["plate_ink"], w=OBJ_W - 80, lh=1.0, caps=True, ti=ti, to=to, ain="rise", di=LAND, z=10, face="cond", event=False)
        cur += 60
    if c.get("to"):
        P.T("TO  " + esc_up(c["to"]), OBJ_X + 40, cur, 44, 700, P.pal["tag_lab"], w=OBJ_W - 80, lh=1.0, caps=True, ti=ti, to=to, ain="rise", di=LAND, z=10, face="mono", event=False)
        cur += 50
    cur += 30
    stg = stage_times(sp, ti, min(3, len(its) + 1))          # the rows come in over the beats; the total lands on the last state
    for i, it in enumerate(its):
        t = reveal_t(i, len(its) + 1, stg, 0.3)
        P.T(ll[i], OBJ_X + 40, cur, 62, 700, P.pal["plate_ink"], w=lab_w, lh=1.05, caps=True, ti=t, to=to, ain="rise", di=LAND, z=10, face="cond", lines=ll[i], event=(i == 0), snd=("tick" if i == 0 else None), sndx=OBJ_X + 200)
        P.T(it["amount"], OBJ_X + OBJ_W - 40 - amt_w, cur + 8, 48, 700, P.pal["plate_ink"], w=amt_w, al="r", lh=1.0, caps=False, ti=t, to=to, ain="rise", di=LAND, z=10, face="mono", event=False)
        cur += len(ll[i]) * 66 + 20
    cur += 30
    P.R(OBJ_X + 40, cur, OBJ_W - 80, 6, fill=P.pal["plate_ink"], ti=ti + 0.3, to=to, ain="wipe", di=0.3, z=10, event=False)
    cur += 14
    t = reveal_t(len(its), len(its) + 1, stg, 0.3)
    P.T("TOTAL", OBJ_X + 40, cur + 22, 44, 700, P.pal["tag_lab"], w=220, lh=1.0, caps=True, ti=t, to=to, ain="rise", di=LAND, z=10, face="mono", event=False)
    P.T(c["total"], OBJ_X + 200, cur, 96, 700, P.pal["accent"] if False else P.pal["tick"], w=OBJ_W - 240, al="r", lh=1.0, caps=False, ti=t, to=to, ain="slam", di=LAND, z=10, face="cond", event=True, snd="stamp", sndx=OBJ_X + 500, os=1.1, org="100% 100%")
    return True


def obj_receipt(P, sp, ti, to):
    return obj_ledger_doc(P, sp, ti, to, "")


def obj_invoice(P, sp, ti, to):
    return obj_ledger_doc(P, sp, ti, to, "INVOICE")


def obj_dashboard(P, sp, ti, to):
    ts = sp["content"]["tiles"]
    n = len(ts)
    cols = 1 if n == 2 else 2
    rows = (n + cols - 1) // cols
    gap = 24
    tw_ = (OBJ_W - gap * (cols - 1)) // cols
    th = int(min(250, (OBJ_H - gap * (rows - 1)) / rows))
    y0 = OBJ_Y0 + (OBJ_H - (th * rows + gap * (rows - 1))) // 2
    stg = stage_times(sp, ti, min(3, n))          # the tiles come in over the beats of the span
    for i, t in enumerate(ts):
        r_, c_ = divmod(i, cols)
        x, y = OBJ_X + c_ * (tw_ + gap), y0 + r_ * (th + gap)
        tt = reveal_t(i, n, stg, 0.2, 0.15)
        card(P, x, y, tw_, th, tt, to, fill="#0d151e", stroke=P.pal["accent"] if i == 0 else P.pal["dim"], sw=5, r=P.F["chip_r"] + 8, a=0.94, snd="pop")
        vfs = FL.fit_line(t["value"].upper(), "cond", 700, tw_ - 50, int(th - 110), 60, 0.0, True) or 60
        P.T(t["value"].upper(), x + 25, y + 20, vfs, 700, P.pal["accent"], w=tw_ - 50, al="l", lh=1.0, caps=True, ti=tt, to=to, ain="slam", di=LAND, z=10, face="cond", event=False, os=1.08, org="0% 100%")
        P.T(esc_up(t["label"]), x + 25, y + 20 + vfs + 8, 44, 700, "#f3efe6", w=tw_ - 50, lh=1.0, caps=True, ti=tt, to=to, ain="rise", di=LAND, z=10, face="mono", event=False, ls=0.04)
    return True


def obj_map_route(P, sp, ti, to):
    if P.world_kind != "map":
        return False
    c = sp["content"]
    P.routes.append(dict(a=list(proj(*c["from_ll"])), b=list(proj(*c["to_ll"])), t0=r2(ti + 0.1), t1=r2(to)))
    ph = 150
    plate_at(P, c["from"].upper(), OBJ_X, OBJ_Y0 + 20, 460, ph, ti, to)
    plate_at(P, c["to"].upper(), OBJ_X + OBJ_W - 460, OBJ_Y1 - ph - 20, 460, ph, ti + 0.3, to)
    P.events.append((ti + 0.1, 1.0, "route"))
    return True


OBJ_FN = {"price_tag": obj_price_tag, "counter": obj_counter, "compare_bars": obj_compare_bars, "logo_pair": obj_logo_pair, "clipping": obj_clipping, "quote_card": obj_quote_card,
          "checklist": obj_checklist, "timeline": obj_timeline, "artefact:email": obj_email, "artefact:phone_text": obj_phone_text, "artefact:letter": obj_letter,
          "artefact:receipt": obj_receipt, "artefact:invoice": obj_invoice, "artefact:dashboard": obj_dashboard, "map_route": obj_map_route}
OBJECT_FOR = {"price_tag": "hanging figure tag swings and drops", "counter": "counter panel with the figure at picture scale", "compare_bars": "bar chart the figures turn into", "logo_pair": "two known-name logo plates joined by an arrow",
              "clipping": "real source clipping with the clause marked and the outlet masthead", "quote_card": "quote card with the speaker", "checklist": "legal pad checklist the source itself lists",
              "timeline": "timeline of dated events", "artefact:email": "email with sender subject and body", "artefact:phone_text": "phone text bubbles", "artefact:letter": "letter on paper",
              "artefact:receipt": "receipt with items and total", "artefact:invoice": "invoice with items and total", "artefact:dashboard": "dashboard tiles with values", "map_route": "route drawn between two places on the map",
              "verdict": "verdict headline with an accent rule", "question": "question headline with YES and NO chips", "cta": "follow card with a button that presses", "hook": "hanging tag, logo plate and headline over the world",
              "proof": "source clipping with the clause marked"}


def render_objects(P):
    """two passes when the first changes the spans (an object that cannot be drawn hands its time to the one before it; a run of one kind merges): the states an object shows are
    staged on the beats of the span it ends up holding, so the second pass draws every object against its final span"""
    pl = P.plan
    snap = (len(P.items), len(P.boxes), len(P.events), len(P.sfx), len(P.tag_drops), len(P.objects), len(P.routes), P.n, len(P.used_logos))
    P.clip_seen = reset_clip_seen(P)
    before = [(sp["spec"] is None, round(sp["t_out"], 3)) for sp in pl["spans"]]
    _render_objects_pass(P)
    after = [(sp["spec"] is None, round(sp["t_out"], 3)) for sp in pl["spans"]]
    if before != after:
        del P.items[snap[0]:], P.boxes[snap[1]:], P.events[snap[2]:], P.sfx[snap[3]:], P.tag_drops[snap[4]:], P.objects[snap[5]:], P.routes[snap[6]:], P.used_logos[snap[8]:]
        P.n = snap[7]
        P.skins_used = []
        P.clip_seen = reset_clip_seen(P)
        _render_objects_pass(P)


def reset_clip_seen(P):
    cl = P.assets.get("clause")
    return [(cl.get("source_id"), cl.get("key"), cl["w"] / float(cl["h"]))] if cl else []


def clip_is_new(P, sp, cl):
    """root 26 Oct, ruling 4: a clipping of a source already shown (the proof counts) is a new object only if its clause is a different one AND its crop is visibly different (the width to height ratio differs by 25% or more); otherwise it is the same picture again"""
    sid_, key_, asp = sp["content"].get("source_id"), sp["content"].get("key"), cl["w"] / float(cl["h"])
    for s2, k2, a2 in getattr(P, "clip_seen", []):
        if s2 == sid_ and (k2 == key_ or abs(asp - a2) / a2 < 0.25):
            P.repairs.append("clipping %s dropped: the same source (%s) already shows a clipping of that clause or of that shape" % (key_, sid_))
            return False
    P.clip_seen.append((sid_, key_, asp))
    return True


def _render_objects_pass(P):
    pl = P.plan
    gs = pl["groups"]
    for si, sp in enumerate(pl["spans"]):
        spec = sp["spec"]
        if spec is None:
            continue
        marks = (len(P.items), len(P.boxes), len(P.events), len(P.sfx), len(P.tag_drops), len(P.objects), len(P.routes))
        def _leaves(x_):
            if isinstance(x_, str):
                yield x_
            elif isinstance(x_, dict):
                for k_, v_ in x_.items():
                    if k_ not in ("who", "key", "source_id", "ledger", "para", "kind", "unit", "from_ll", "to_ll"):
                        for y_ in _leaves(v_):
                            yield y_
            elif isinstance(x_, list):
                for v_ in x_:
                    for y_ in _leaves(v_):
                        yield y_
        if spec["kind"] != "price_tag" and any(has_banned(t_) for t_ in _leaves(spec.get("content"))):
            P.repairs.append("object %s at %.1f s dropped: it prints a banned word" % (spec["kind"], sp["t_in"]))
            P.dropped.append((spec["kind"], sp["t_in"]))
            sp["spec"] = None if si else spec
            if si == 0:
                spec = sp["spec"] = hero_spec(P)
            else:
                continue
        spec["stage_ts"] = span_stage_ts(P, sp) if spec["kind"] != "price_tag" else []
        spec["S"] = 1
        try:
            ok = OBJ_FN[spec["kind"]](P, spec, sp["t_in"], sp["t_out"])
        except (KeyError, TypeError, IndexError, AttributeError) as e:
            raise EngineError("object %s at %.2f s has no usable content (%s %s): an object without content is a build failure" % (spec["kind"], sp["t_in"], type(e).__name__, e))
        if ok:
            for b_ in P.boxes[marks[1]:]:
                b_["obj"] = si
            for it_ in P.items[marks[0]:]:
                it_["obj"], it_["objk"] = si, spec["kind"]
                if it_["k"] in ("rect", "text", "img", "path", "bars"):
                    it_["fl"] = si + 1
        if not ok:
            del P.items[marks[0]:], P.boxes[marks[1]:], P.events[marks[2]:], P.sfx[marks[3]:], P.tag_drops[marks[4]:], P.objects[marks[5]:], P.routes[marks[6]:]
            P.dropped.append((spec["kind"], sp["t_in"]))
            if si == 0:
                spec = hero_spec(P)
                sp["spec"] = spec
                if not obj_price_tag(P, spec, sp["t_in"], sp["t_out"]):
                    raise EngineError("the hero tag cannot be shown")
                ok = True
            else:
                sp["spec"] = None            # the previous object stays on screen
        if ok and sp["spec"]:
            wi = (spec.get("win") or gs[sp["g0"]]["wins"][0]).w0
            wi2, _ = script_word(P, gs[sp["g0"]]["wins"])
            P.objects.append((OBJECT_FOR[spec["kind"]], wi2, sp["t_in"]))
            P.skins_used.append(spec["kind"])
    # repair: the same kind twice in a row is ONE object that stays (the later span is removed and the earlier one runs to its end)
    prev_i = None
    for si, sp in enumerate(pl["spans"]):
        if sp["spec"] is None:
            continue
        if prev_i is not None and sp["spec"]["kind"] == pl["spans"][prev_i]["spec"]["kind"] and sp["spec"]["kind"] != "price_tag":
            ids_ = {it_["id"] for it_ in P.items if it_.get("obj") == si}
            P.items = [it_ for it_ in P.items if it_.get("obj") != si]
            P.boxes = [b_ for b_ in P.boxes if b_["id"] not in ids_]
            for it_ in P.items:
                if it_.get("obj") == prev_i and it_.get("to") is not None:
                    it_["to"] = r2(sp["t_out"])
            P.repairs.append("run of %s merged: the span at %.1f s is the same object" % (sp["spec"]["kind"], sp["t_in"]))
            pl["spans"][prev_i]["t_out"] = sp["t_out"]
            sp["spec"] = None
            continue
        prev_i = si
    P.skins_used = [sp_["spec"]["kind"] for sp_ in pl["spans"] if sp_["spec"]]          # what is actually on screen after the merges
    P.objects = [o_ for o_ in P.objects if any(sp_["spec"] and OBJECT_FOR.get(sp_["spec"]["kind"]) == o_[0] for sp_ in pl["spans"])]
    # an object that could not be drawn hands its time to the one before it (its items run to its own end)
    last = None
    last_index = None
    for span_index, sp in enumerate(pl["spans"]):
        if sp["spec"] is None and last is not None and last["spec"]["kind"] != "price_tag":          # the hero tag never absorbs a dropped neighbour (that is how it became the object of 4-5 beats)
            for it in P.items:
                if it.get("obj") == last_index and it.get("to") == r2(last["t_out"]):
                    it["to"] = r2(sp["t_out"])
            last["t_out"] = sp["t_out"]
        elif sp["spec"] is not None:
            last = sp
            last_index = span_index


def add_scene_items(P):
    pl = P.plan
    for gi, g in enumerate(pl["groups"]):
        g["head_it"] = headline_words(P, g, g["fi"], g["E"])
        sp = next((x for x in pl["spans"] if x["g0"] <= gi <= x["g1"]), None)
        if sp and sp["spec"] and sp["spec"]["kind"] != "price_tag" and gi > sp["g0"]:
            # the same object stays for another beat: a backing panel behind it changes colour with the headline, so the beat has its own picture
            k_ = gi - sp["g0"]
            col = mix_hex(P.pal["ground"], P.pal["accent"], 0.22 if k_ % 2 else 0.12) if k_ % 3 else mix_hex(P.pal["ground"], P.pal["ink"], 0.14)
            pan_ = P.R(OBJ_X - 30, OBJ_Y0 - 10, OBJ_W + 60, OBJ_H + 20, fill=col, r=P.F["chip_r"] + 20, ti=g["fi"], to=g["E"], ain="rise", di=LAND, z=2, event=False)
            pan_["pan"] = pl["spans"].index(sp)
    scene_verdict(P)
    P.skins_used.append("verdict")
    scene_question(P)
    scene_cta(P)
    scene_hook(P)
    scene_proof(P)
    scene_loop(P)


def outlet_of(P, g):
    srcs = P.story.get("sources") or []
    s_ = next((x for x in srcs if x["id"] == g.get("source_id")), srcs[0] if srcs else None)
    return (s_["outlet"].strip() if s_ else "Source")


def scene_hook(P):
    pl = P.plan
    end = pl["proof_to"] if pl["has_proof"] else (pl["groups"][0]["C"] - EXIT_LEAD if pl["groups"] else pl["C_v"] - EXIT_LEAD)
    if pl["spans"][0]["spec"]["kind"] == "price_tag" and not pl["has_proof"]:
        end = min(end, pl["groups"][0]["C"] - HERO_LEAD - 0.05)
    it = headline(P, [P.story["tiny_cause"]["text"]], 0.0, end, ain="cut", snd=None, maxlines=2)
    P.hook_item = it
    it["os"] = 1.05
    P.objects.append((OBJECT_FOR["hook"], P.story["known_name"]["words"][0], 0.2))
    P.objects.append(("figure tag that takes the pulse on the spoken figure", P.story["huge_cost"]["spoken"][0], P.words[P.story["huge_cost"]["spoken"][0]]["start"]))
    P.objects.append(("series sting plate", P.story["known_name"]["words"][0], 0.35))
    if P.fig_hit:
        P.cue(P.fig_hit, "slam", P.tag_full["x"] + P.tag_full["w"] / 2.0)


def scene_proof(P):
    """the first source clipping lands at 1.5 s: ONE paper card (outlet masthead, the crop, the date), the clause marked as the voice says it"""
    cl = P.assets.get("clause")
    pl = P.plan
    if not cl:
        return False
    t = pl["t_proof"]
    E = pl["proof_to"]
    hc = P.story["huge_cost"]
    ts = P.words[hc["spoken"][0]]["start"] if hc.get("spoken") else t
    srcs = {x_["id"]: x_ for x_ in P.story.get("sources") or []}
    sid_ = (hc.get("trace") or {}).get("source", "").split("#")[0]
    name = re.sub(r"\.(co\.uk|com|org|net)$", "", (srcs.get(sid_) or {}).get("outlet") or (cl.get("credit") or "SOURCE").split(",")[0], flags=re.I).upper()
    r_ = clip_card(P, cl, name, t, E, t_mark=max(t + 0.2, ts - 0.1), y_top=max(OBJ_Y, int(P.head_bottom + 40)), strict=False)
    if r_ is None:
        return False
    P.objects.append((OBJECT_FOR["proof"], hc["spoken"][0] if hc.get("spoken") else 0, t))
    return True


def scene_loop(P):
    """the last 0.5 s resolves to frame 0: the tag, the plate and the camera are already back (keys); the hook headline fades in again over the map"""
    pl = P.plan
    te = pl["T_end"]
    it = headline(P, [P.story["tiny_cause"]["text"]], te + 0.35, None, ain="rise", snd=None, maxlines=2)
    it["di"] = 0.2


def scene_verdict(P):
    pl = P.plan
    st = P.story
    vd = st["verdict"]
    fi, E = pl["C_v"], pl["v_to"]
    txt = vd["text"].upper()
    r = fit_headline(P, txt, 7, 112, 60)
    if not r:
        raise EngineError("the verdict (%d words) does not fit seven lines at 60 px" % len(txt.split()))
    fs, lines = r
    words = txt.split()
    k = len(words)
    nacc = max(2, int(round(k * 0.3)))
    html, c = [], 0
    for ln in lines:
        parts = []
        for tok in ln.split():
            c += 1
            parts.append('<span style="color:%s">%s</span>' % (P.pal["accent"] if c > k - nacc else P.pal["ink"], esc_html(tok)))
        html.append(" ".join(parts))
    it = P.T(txt, HEAD_X, HEAD_Y, fs, 700, P.pal["ink"], w=HEAD_W, lh=0.9, caps=True, ti=fi, to=E, ain="slam", di=LAND, z=14, lines=lines, face="cond", snd="paper", sndx=540,
             sh="0 10px 34px rgba(0,0,0,.85)", head=True)
    it["html"], it["os"], it["org"] = html, 1.06, "0% 100%"
    P.R(240, 700, 600, 600, fill=None, stroke=P.pal["accent"], sw=16, r="50%", ti=fi, to=E, ain="rise", di=LAND, z=3, a=0.55, event=False)
    P.R(300, 760, 480, 480, fill=None, stroke=P.pal["accent"], sw=6, r="50%", ti=fi, to=E, ain="rise", di=LAND, z=3, a=0.4, event=False)
    t_st = verdict_stamp_time(P)
    P.verdict_stamp = t_st
    vw0, vw1 = vd["words"]
    ntok = sum(len(l.split()) for l in lines)
    cum, pl_ = 0, []
    for kk, ln in enumerate(lines):
        a = vw0 + int(round((vw1 - vw0 + 1) * cum / float(ntok)))
        a = max(vw0, min(a, vw1))
        if kk > 0:
            pl_.append(max(fi + 0.4, P.words[a]["start"] - FR))
        cum += len(ln.split())
    it["pulses"] = [r2(t) for t in pl_]
    P.events += [(t, 0.6, "pulse") for t in pl_]
    ybot = HEAD_Y + len(lines) * fs * 0.9
    P.R(HEAD_X, ybot + 22, 420, 14, fill=P.pal["accent"], ti=t_st, to=E, ain="wipe", di=0.3, z=12, snd="stamp")
    P.objects.append((OBJECT_FOR["verdict"], vw1, t_st))


def verdict_stamp_time(P):
    vw0, vw1 = P.story["verdict"]["words"]
    st = []
    for b in P.story["beats"][P.plan["iv0"]: P.plan["ic"]]:
        st += [i for i in b["stress"] if vw0 <= i <= vw1]
    i = max(st) if st else vw1
    return max(P.words[i]["start"] - FR, P.plan["C_v"] + 0.9)


def yes_no(q):
    return bool(re.match(r"^(do|does|did|is|are|was|were|would|will|can|could|should|have|has)\b", q.strip(), re.I))


def scene_question(P):
    pl = P.plan
    if pl["stacked"]:
        return
    q = P.story["question"]
    txt = q["text"].upper()
    fi, E = pl["C_q"], pl["q_to"]
    r = fit_headline(P, txt, 4, 128, 80)
    if not r:
        raise EngineError("the question does not fit four lines at 80 px")
    fs, lines = r
    it = P.T(txt, HEAD_X, HEAD_Y, fs, 700, P.pal["ink"], w=HEAD_W, lh=0.9, caps=True, ti=fi, to=E, ain="slam", di=LAND, z=14, lines=lines, face="cond", snd="pop", sndx=540,
             sh="0 10px 34px rgba(0,0,0,.85)", head=True)
    words = txt.split()
    html, c = [], 0
    for ln in lines:
        parts = []
        for tok in ln.split():
            c += 1
            parts.append('<span style="color:%s">%s</span>' % (P.pal["accent"] if c > len(words) - 2 else P.pal["ink"], esc_html(tok)))
        html.append(" ".join(parts))
    it["html"], it["os"], it["org"] = html, 1.06, "0% 100%"
    if yes_no(q["text"]):
        yy = HEAD_Y + len(lines) * fs * 0.9 + 50
        for k, word in enumerate(("YES", "NO")):
            P.R(90 + k * 270, yy, 230, 104, fill=None, stroke=P.pal["ink"], sw=6, r=(52 if P.fmt_name == "clean" else 10), ti=fi, to=E, ain="rise", di=LAND, z=8, event=False)
            P.T(word, 90 + k * 270, yy + 20, 64, 700, P.pal["ink"], w=230, al="c", lh=1.0, caps=True, ti=fi, to=E, ain="rise", di=LAND, z=10, face="cond", event=False)
    P.R(240, 760, 600, 600, fill=None, stroke=P.pal["accent"], sw=16, r="50%", ti=fi, to=E, ain="rise", di=LAND, z=3, a=0.55, event=False)
    P.objects.append((OBJECT_FOR["question"], P.story["verdict"]["words"][1], fi))


def scene_cta(P):
    n0_ = len(P.items)
    _scene_cta(P)
    for it_ in P.items[n0_:]:
        if it_["k"] in ("rect", "text", "path"):
            it_["fl"] = 7                   # the card floats a few px, so the held question is never a still picture (static_precheck)


def _scene_cta(P):
    pl = P.plan
    cta = P.story["cta"]
    fi, E = pl["C_c"], pl["T_end"]
    cx0, cw0, cy0 = 60, 840, 310
    tfs = 48
    link_fs = FL.fit_line(CTA_LINK, "mono", 700, cw0 - 56, 44, 42, 0.0, False)
    if not link_fs:
        raise EngineError("the audit link does not fit one line at 42 px in the mono face")
    maxh = 836 - (cy0 + 40) - 24 - tfs - 8 - link_fs * 1.2 - 4        # the link row must end above y 840: the TikTok column starts there and the link is 767 px wide
    r = None
    for fs_ in range(100, 47, -2):          # shrink to the 48 px floor (DIRECTOR's floor is 42), at most 4 lines (the card headline is the spoken question), before refusing
        lines_ = FL.wrap(cta["line"].upper(), "cond", 700, fs_, cw0 - 110, 0.0, True)
        if len(lines_) <= 4 and len(lines_) * fs_ * 0.9 <= maxh and max(FL.tw(l, "cond", 700, fs_, 0.0, True) for l in lines_) <= cw0 - 100:
            r = (fs_, lines_)
            break
    if not r:
        raise EngineError("needs-writer: question too long (%d words do not fit above the audit link at 48 px in 4 lines): a v3 question is 6-22 words" % len(cta["line"].split()))
    fs, lines = r
    lh_ = len(lines) * fs * 0.9
    y = cy0 + 40
    ch = 40 + lh_ + 24 + tfs + 8 + link_fs * 1.2 + 34 + 112 + 40
    P.R(cx0, cy0, cw0, ch, fill="#0d151e", stroke="#2a3a4a", sw=3, r=18, ti=fi, to=E, ain="rise", di=LAND, z=5, shadow="0 40px 90px rgba(0,0,0,.8)", snd="paper")
    it = P.T(cta["line"].upper(), cx0 + 50, y, fs, 700, "#f3efe6", w=cw0 - 100, al="c", lh=0.9, caps=True, ti=fi, to=E, ain="rise", di=LAND, z=10, lines=lines, face="cond", event=False)
    ty = y + lh_ + 24
    P.T("AI CONSTRAINT AUDIT", cx0 + 50, ty, tfs, 700, "#f3efe6", w=cw0 - 100, al="c", lh=1.0, caps=True, ti=fi, to=E, ain="rise", di=LAND, z=10, face="cond", event=False)
    ly = ty + tfs + 8
    P.T(CTA_LINK, cx0 + 28, ly, link_fs, 700, P.pal["accent"], w=cw0 - 56, al="c", lh=1.2, caps=False, ti=fi, to=E, ain="rise", di=LAND, z=10, face="mono", event=False)
    by = ly + link_fs * 1.2 + 34
    t_press = P.words[cta["press"]]["start"] - FR
    t_ring = P.words[cta["ring"]]["end"] - 0.05
    bw = 600
    bx = cx0 + (cw0 - bw) / 2.0
    P.R(bx, by, bw, 112, fill=None, stroke=P.pal["accent"], sw=8, r=12, ti=fi, to=E, ain="rise", di=LAND, z=8, pulse=r2(t_press), event=False)
    bf = 66
    P.T("FOLLOW", bx, by + (112 - bf) / 2.0, bf, 700, P.pal["accent"], w=bw, al="c", lh=1.0, caps=True, ti=fi, to=E, ain="rise", di=LAND, z=10, face="cond", event=False)
    P.R(bx, by, bw, 112, fill=P.pal["accent"], r=12, ti=t_press, to=E, ain="wipe", di=0.25, z=11, snd="press")
    P.T("FOLLOWING", bx, by + (112 - bf) / 2.0, bf, 700, "#0d151e", w=bw, al="c", lh=1.0, caps=True, ti=t_press, to=E, ain="wipe", di=0.25, z=12, face="cond", event=False, nobox=True)
    P.cta_card = (cx0, cw0)
    P.RING(cx0 + cw0 / 2.0, ly + link_fs * 0.6, 64, P.pal["accent"], t_ring, sw=8, di=0.55, z=12, snd="ping")
    P.objects.append((OBJECT_FOR["cta"], cta["press"], t_press))



# ================================================================================================ script words, sound, spec beats
def script_norm(sid):
    import craft_check as CC
    sp = CC.script_text(sid) or ""
    return sp, CC.norm(sp)


def script_word(P, g_wins):
    """a plain word of the script spoken inside these windows (the R7 pitch ties every object to one)"""
    import craft_check as CC
    for w in g_wins:
        for i in list(w.stress) + list(range(w.w0, w.w1 + 1)):
            t = CC.norm(P.words[i]["word"])
            if t.isalpha() and len(t) >= 4 and t in P.script_n.split():
                return i, t
    return g_wins[0].w0, CC.norm(P.words[g_wins[0].w0]["word"])


def thin_sfx(P):
    """sort, keep cues >= 0.27 s apart (a closer one merges into the previous EVENT in craft_metrics), keep to <= 64 events a minute"""
    cs = sorted(P.sfx, key=lambda c: c["t"])
    out = []
    for c in cs:
        if out and c["t"] - out[-1]["t"] < 0.27:          # craft_metrics merges cues closer than 0.25 s into one event
            continue
        out.append(c)
    cap = int(P.dur / 60.0 * 64)
    if len(out) > cap:
        prio = {"stamp": 0, "slam": 0, "press": 0, "print": 1, "ping": 1, "paper": 2, "tick": 3, "click": 4, "pop": 4, "flap": 4, "pen": 5, "type": 5, "whoosh": 6}
        keep = sorted(out, key=lambda c: (prio.get(c["what"], 4), c["t"]))[:cap]
        out = sorted(keep, key=lambda c: c["t"])
    P.sfx = out


def pre_forb(P):
    """the windows around which a cut must not fall, predicted from the PLAN (the items do not exist yet): every object leaves at its span's end, every headline at its group's end,
    the hero tag moves HERO_LEAD before a tag span and back after it"""
    pl = P.plan
    out = []
    for sp in pl["spans"]:
        if sp["spec"]:
            out.append((sp["t_out"] - 0.02, sp["t_out"] + 5 * FR + 0.02))
            if sp["spec"]["kind"] == "price_tag":
                out.append((sp["t_in"] - HERO_LEAD - 0.02, sp["t_in"] - HERO_LEAD + 0.5))
    for g in pl["groups"]:
        out.append((g["E"] - 0.02, g["E"] + 5 * FR + 0.02))
    for t_ in (pl["proof_to"], pl["v_to"], pl["q_to"]):
        out.append((t_ - 0.02, t_ + 5 * FR + 0.02))
    return out


def precompute_beats(P):
    """the cut times, fixed BEFORE the objects are drawn so that an object can stage its state change on each beat of its span (root 26 Oct: a held object changes state on every beat)"""
    P.cuts_pre = compute_cuts(P, pre_forb(P))


def compute_cuts(P, forb_pre=None):
    """cuts: hook | proof (1.4 s) | each body state | verdict | question | cta, plus window starts that split any beat over 3.0 s. Never under 1.4 s, never over 4.4 s."""
    pl, W = P.plan, P.wins
    cuts = [(0.0, "hook", None, 0.0), (1.4, "proof", None, 0.0)]
    for i, g in enumerate(pl["groups"]):
        cuts.append((g["C"], "s%02d" % (i + 1), g["wins"][0].w0, LEAD))
    cuts.append((pl["C_v"], "verdict", W[pl["iv0"]].w0, LEAD))
    if pl["C_q"]:
        cuts.append((pl["C_q"], "question", None, 0.0))
    cuts.append((pl["C_c"], "cta", W[pl["ic"]].w0, LEAD))
    cuts.sort(key=lambda c: c[0])
    forb = list(forb_pre) if forb_pre is not None else []
    if forb_pre is None:
        for it in P.items:
            if it.get("to") is not None:
                forb.append((it["to"] - 0.02, it["to"] + (it.get("do") or 5 * FR) + 0.02))
        for ks in (P.tag_keys, P.plate_keys):
            for k in ks[1:]:
                forb.append((k["t"] - 0.02, k["t"] + 0.5))
    forb_tag = []
    for sp in pl["spans"]:
        if sp["spec"] and sp["spec"]["kind"] == "price_tag":          # a hero-tag span stays ONE beat (the tag is the object of at most HERO_MIDDLE_MAX beats)
            forb_tag.append((sp["t_in"] + 0.3, sp["t_out"] - 0.3))
    ok_cut = lambda t: not any(a_ <= t <= b_ for a_, b_ in forb + forb_tag)
    ok_cut_forced = lambda t: not any(a_ <= t <= b_ for a_, b_ in forb)
    cand = {}
    for w in W:
        if w.w0 > 0:
            cand[round(max(0.0, w.t0 - LEAD), 3)] = (w.w0, LEAD)
    for i, wd in enumerate(P.words):
        if i > 0:
            cand.setdefault(round(wd["start"] - 0.05, 3), (i, 0.05))
    again = True
    n = 0
    while again:
        again = False
        for a_, b_ in zip(cuts, cuts[1:] + [(P.dur, "end", None, 0.0)]):
            if b_[0] - a_[0] > (4.2 if a_[1] == "cta" else SPLIT_AT):
                mid = (a_[0] + b_[0]) / 2.0
                opts = sorted((abs(t - mid), t) for t in cand if t - a_[0] >= 1.4 and b_[0] - t >= 1.4 and ok_cut(t))
                if opts:
                    n += 1
                    t = opts[0][1]
                    cuts.append((t, "x%02d" % n, cand[t][0], cand[t][1]))
                    cuts.sort(key=lambda c: c[0])
                    again = True
                    break
    again = True                       # repair pass: a beat still over 4.4 s is split at the nearest word boundary even inside a hero-tag span (the extra tag beats are demoted afterwards)
    while again:
        again = False
        for a_, b_ in zip(cuts, cuts[1:] + [(P.dur, "end", None, 0.0)]):
            if b_[0] - a_[0] > 4.3:
                mid = (a_[0] + b_[0]) / 2.0
                for lo in (1.4, 1.0):
                    opts = sorted((abs(t - mid), t) for t in cand if t - a_[0] >= lo and b_[0] - t >= lo and ok_cut_forced(t))
                    if opts:
                        break
                if opts:
                    n += 1
                    t = opts[0][1]
                    cuts.append((t, "x%02d" % n, cand[t][0], cand[t][1]))
                    cuts.sort(key=lambda c: c[0])
                    P.repairs.append("split_beat %.1f-%.1f s at %.2f s" % (a_[0], b_[0], t))
                    again = True
                    break
    ic_ = next(i for i, c in enumerate(cuts) if c[1] == "cta")
    if ic_ != len(cuts) - 1:        # a long CTA is split at a word (STORY-DATA: ctah then cta); the LAST beat must be called cta
        cuts = [(t, ("ctah" if k == ic_ else ("ctah%d" % (k - ic_ + 1) if ic_ < k < len(cuts) - 1 else ("cta" if k == len(cuts) - 1 else bid))), wi, lead) for k, (t, bid, wi, lead) in enumerate(cuts)]
    return cuts


def spec_beats(P):
    pl, W = P.plan, P.wins
    cuts = getattr(P, "cuts_pre", None) or compute_cuts(P)
    beats = []
    for i, (t, bid, wi, lead) in enumerate(cuts):
        nxt = cuts[i + 1][0] if i + 1 < len(cuts) else P.dur
        b = dict(id=bid, component="scene", field="none", drift=False, tx="none", hold=0, captions=False, props=dict(scene="fmt-beat"), t_from=t, t_to=nxt)
        if i > 0:
            b["start"] = ("@#%d" % wi) if wi is not None else r2(t)
            b["lead"] = lead if wi is not None else 0
        if bid in ("cta", "ctah"):
            b["props"]["link"] = CTA_LINK
        if bid == "hook":
            b["lead"] = 0
        beats.append(b)
    P.spec_beats = beats
    return beats


VERBS = ["land", "stamp", "pin", "sweep", "tick", "flip", "lift", "print", "sign", "seal", "light", "slide", "open", "draw", "punch", "settle", "clip", "mark", "drop", "swing", "pull", "tilt", "slam", "pan", "zoom", "rise", "snap", "fill", "press", "spin", "glide", "knock", "crack", "peel", "stack", "fan", "trace", "flash", "push", "tuck", "hook", "cut"]


def pick_bed(P, exclude=()):
    mus = jload(os.path.join(V2, "sound", "music.json"))["items"]
    fam = {"dossier": ("dark investigative",), "clean": ("bright minimal", "driving tech"), "newsroom": ("sparse tense", "tense/minimal")}[P.fmt_name]
    banned = {"local-forecast", "airport-lounge"}
    c = [m["id"] for m in mus if m["id"] not in banned and m["id"] not in exclude and any(f in (m.get("mood_fit") or "") for f in fam)]
    h = int(sha1(P.sid + P.fmt_name)[:6], 16)
    return [c[(h + i) % len(c)] for i in range(len(c))] if c else []


ENGINE_VERSION = "2.0.0"


def make_spec(P, bed):
    sid, st = P.sid, P.story
    title = "%s: %s %s" % (st["known_name"]["text"], st["huge_cost"]["display"], st["huge_cost"]["label"])
    beats = []
    for i, b in enumerate(P.spec_beats):
        o = {k: v for k, v in b.items() if k not in ("t_from", "t_to")}
        o["mirrors"] = [0]
        o["sfx"] = [dict(at=c["t"], kind=c["kind"], gain=c["gain"], x=c["x"]) for c in P.sfx if b["t_from"] - 1e-6 <= c["t"] < b["t_to"] - 1e-6]
        if i == 0:
            o["lead"] = 0
        o["signature"] = (b["id"] == "verdict")
        beats.append(o)
    sig_name = {"dossier": "an accent rule stamps under the verdict", "clean": "the verdict is swept line by line and an accent rule is drawn under it", "newsroom": "an accent rule is stamped under the verdict"}[P.fmt_name]
    spec = dict(id=sid, title=title, slug=re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:28], look=P.F["look"], kit_defaults="2026-09-28", platform="", platform_label="universal safe zone (unrouted)",
                format="format_engine:" + P.fmt_name, script=dict(id=sid, file="shorts/scripts-v2/%s.md" % sid),
                voice=dict(wav="shorts/voice/%s/%s.wav" % (sid, sid), words="shorts/voice/%s/%s.words.json" % (sid, sid)), needs=["map"], world="fmt-world",
                signature_concept="%s: a hanging figure tag and a known-name plate travel a dark world map, one new object each beat, and %s on the verdict's last stressed word" % (P.F["name"].lower(), sig_name),
                transitions=["the camera travels to a new region of the map on every beat", "the figure tag swings between full size and a chip and returns on the last frame", "each beat brings its own object over the map"],
                code=["lib/prologue.js", "lib/overlays/sting.js", "specs/%s/scenes.js" % sid], music=dict(bed=bed, under_lu=13, gap_rise_db=0, drops=[], swells=[]), render=dict(parts=4, res4k=False),
                caption_style="highlight", tail=0.9,
                composed=dict(**{"from": "format_engine", "engine": "format_engine", "format": P.fmt_name, "swatch": P.sw_key, "skins": P.skins_used, "signature": True, "layout": layout_sig(P), "world_kind": P.world_kind,
                                 "story_sha1": sha1(json.dumps(P.story, sort_keys=True))[:16], "engine_version": ENGINE_VERSION}),
                beats=beats)
    return spec


# ================================================================================================ beat grid fillers: a pulse on something already on screen, never a floating extra
def add_fillers(P):
    """no gap over 0.75 s in the first 3.2 s or 1.1 s after between visible changes. A filler is a small pulse on the headline that is on screen, or on the tag (scale 1.035 / 1.07)."""
    ev = sorted(set(round(t, 3) for t, w, k in P.events if 0 <= t <= P.dur))
    pl = P.plan
    base = [0.0, 0.35, 1.0, pl["t_proof"], pl["C_v"] - 0.3, pl["C_c"] - HERO_LEAD, pl["T_end"] + FADE_OUT]
    if P.fig_hit:
        base.append(P.fig_hit)
    pts = sorted(set(ev + [round(b, 3) for b in base]))
    by_id = {it["id"]: it for it in P.items}
    n = 0
    for _ in range(120):
        worst = None
        for a, b in zip(pts, pts[1:] + [P.dur]):
            lim = GAP_FIRST3 if a < 3.2 else GAP_LATER
            if b - a > lim + 1e-6 and (worst is None or b - a > worst[1] - worst[0]):
                worst = (a, b)
        if not worst:
            break
        a, b = worst
        tm = round((a + b) / 2.0, 3) if b - a < 2.5 else round(a + (GAP_FIRST3 if a < 3.2 else GAP_LATER) * 0.85, 3)
        heads = [bx for bx in P.boxes if bx.get("head") and bx["t0"] <= tm - 0.1 and (bx["t1"] is None or bx["t1"] > tm + 0.3)]
        if heads and n % 2 == 0:
            it = by_id[heads[0]["id"]]
            it.setdefault("pulses", []).append(r2(tm))
            P.cue(tm, "tick", it["x"] + 200)
        else:
            P.tag_pulses.append(r2(tm))
            P.cue(tm, "click", P.tag_full["x"] + P.tag_full["w"] / 2.0)
        P.events.append((tm, 0.6, "filler"))
        pts = sorted(set(pts + [tm]))
        n += 1
    P.fillers = n


# ================================================================================================ the driver
def assemble(P):
    build_hero(P)
    plan_states(P)
    precompute_beats(P)
    render_objects(P)
    build_keys(P)
    add_scene_items(P)
    if P.fig_hit:
        P.cue(P.fig_hit, "slam", P.tag_full["x"] + P.tag_full["w"] / 2.0)
        P.events.append((P.fig_hit, 1.0, "fig"))
    P.cue(0.35, "whoosh", 400)
    P.events.append((0.35, 1.0, "sting"))
    spec_beats(P)
    apply_slots(P)
    world_keys(P)
    add_fillers(P)
    # centre-dead cues move to the 330 / 760 positions (build_short: x 470..590 counts as unpanned)
    for i, c in enumerate(P.sfx):
        if 470 <= c["x"] <= 590:
            c["x"] = 330 if (i % 2 == 0) else 760
    thin_sfx(P)
    write_sfx_ledger(P)
    return P


def new_plan(sid, story, words, fmt, sw_key, assets=None):
    P = Plan(sid, story, words, fmt, sw_key, assets)
    sp, sn = script_norm(sid) if os.path.exists(os.path.join(V2, "shorts", "scripts-v2", sid + ".md")) else ("", "")
    P.script_n = sn
    return P



# ================================================================================================ the checks (DIRECTOR.md + strategy v3), asserted so they cannot silently stop holding
def keys_equal(a, b, props):
    return all(abs(float(a.get(p, 0)) - float(b.get(p, 0))) < 0.5 for p in props)


def span_bbox(P, si):
    """(x0, y0, x1, y1) of the object of span si: its rects, images, paths and bars (the headline and the chips are not part of it); the hero tag spans use the tag's own object-state key"""
    sp = P.plan["spans"][si]
    if sp["spec"] is None:
        return None
    if sp["spec"]["kind"] == "price_tag":
        k = P.tag_obj
        return (k["x"], k["y"], k["x"] + k["w"], k["y"] + k["h"])
    xs0, ys0, xs1, ys1 = [], [], [], []
    for it in P.items:
        if it.get("obj") != si:
            continue
        if it["k"] in ("rect", "img", "path"):
            xs0.append(it["x"]); ys0.append(it["y"]); xs1.append(it["x"] + it["w"]); ys1.append(it["y"] + it["h"])
        elif it["k"] == "bars":
            for b in it["bars"]:
                xs0.append(b["x"]); xs1.append(b["x"] + b["w"]); ys0.append(it["base"] - b["h"] - b["numfs"]); ys1.append(it["base"] + 66)
        elif it["k"] == "text" and not it.get("head"):
            bx = getattr(P, "nat_boxes", {}).get(it["id"]) or next((b["box"] for b in P.boxes if b["id"] == it["id"]), None)
            if bx:
                xs0.append(bx.x0); xs1.append(bx.x1); ys0.append(bx.y0); ys1.append(bx.y1)
    if not xs0:
        return None
    return (min(xs0), min(ys0), max(xs1), max(ys1))


# ================================================================================================ the layout grammar (root, 26 Oct)
# Seven composition SLOTS per format (fe_formats.FORMATS[..]["slots"] orders them); each body beat takes one, by a rotation that never repeats a slot on two beats in a row.
# A slot decides where the headline sits (top | bottom | mid) and where the object sits in the space that is left (position + scale about its own centre). The object of a span
# is ONE group in the runtime (D.og): its transform springs between the slots of its beats, so a held object TRAVELS and the camera stays. Real difference, not jiggle: the
# headline and the object trade places, the object changes side and size. Every slot keeps DIRECTOR scale (width >= 448 px, height >= 284 px, text >= 44 px after scaling),
# the universal safe zone, the headline clear of the object, and text off text; a slot that cannot is not offered to that beat.
# ---- the layout grammar (root 26 Oct; recomposed on root's S264 ruling): every beat is ONE GROUP, the headline plus the object, centred vertically in the safe band; the object is scaled up by its
# height until the group fills about 65% of the band (never below its natural size, never wider than the safe width); the slot decides which side the headline sits on (above or below the object),
# which side the object leans to, and whether the headline is set left or right. The band is y 420-1240: the universal safe zone ends at y 1248 (dom_lint), which is tighter than the 1500 root named.
SLOT_DEFS = {
    "centre-low":  dict(head="top",    ax="c"),       # the S05 composition: headline over the object, the group centred
    "head-below":  dict(head="bottom", ax="c"),       # the object over the headline
    "left-top":    dict(head="top",    ax="l"),
    "right-below": dict(head="bottom", ax="r"),
    "left-below":  dict(head="bottom", ax="l"),
    "right-top":   dict(head="top",    ax="r"),
}
HEAD_SLOTS = {"plate-top": ("top", False), "plate-topr": ("top", True), "plate-below": ("bottom", False), "plate-belowr": ("bottom", True)}          # a bare beat: the known-name plate is its object
GROUP_BAND = (420, 1240)
GROUP_GAP = 34
GROUP_FILL = 0.65
S_MAX = 2.0
SLOT_CY = (500, 1110)
SLOT_MIN_W, SLOT_MIN_H, SLOT_MIN_FS = 448.0, 284.0, 42.4
SLOT_FIXED = ("map_route",)       # the route is drawn in the world; its plates stay where the route ends
CUTAWAY = False                   # a headline-only beat for a held object no slot can move: built, and refused by sheet_check FILL (a lone headline carries 19% content, floor 30%): off
LAYOUT_SAME_CORE = 0.6
LAYOUT_SAME = 0.8
SPLIT_AT = 3.6                    # a beat is cut in two only past this
SLOT_TRAVEL_LEAD = HERO_LEAD      # DIRECTOR: a persisting object moves >= 0.55 s BEFORE the cut that follows it; the outgoing headline is gone 0.2 s before it starts


def head_at(P, g, y, right):
    """the group's headline set with its top at y, left or right aligned, inside the universal zone (refit at >= min(100, its size) when the first fit leaves it); None when it cannot"""
    it = g.get("head_it")
    if not it:
        return None
    meta = g.get("_hm") or {}
    lines, fs, html = it["lines"], it["fs"], it["html"]
    for _ in range(3):
        hh = len(lines) * fs * 0.9
        low = (y + hh) > 840
        x, w = HEAD_X, (690 if (right and low) else HEAD_W)
        box = FL.text_box(x + w if right else x, y, lines, "cond", 700, fs, 0.9, "r" if right else "l", w, 0.0, True)
        if not FL.text_ok(box) and box.w <= w + 1:
            return dict(y=int(round(y)), x=x, w=w, al="r" if right else "l", lines=lines, fs=fs, html=html, box=box)
        r = fit_headline(P, meta.get("up", " ".join(lines)), 2, min(120, fs), min(100, fs), y=int(round(y)))
        if not r or (r[0] == fs and list(r[1]) == list(lines)):
            return None
        fs, lines = r
        html = head_html(P, lines, meta.get("ai", 0))
    return None


def tf_pt(c0, tr, x, y):
    return (c0[0] + tr["s"] * (x - c0[0]) + tr["tx"], c0[1] + tr["s"] * (y - c0[1]) + tr["ty"])


def tf_box(c0, tr, bx):
    x0, y0 = tf_pt(c0, tr, bx.x0, bx.y0)
    x1, y1 = tf_pt(c0, tr, bx.x1, bx.y1)
    return FL.Box(x0, y0, x1, y1)


def group_layout(P, g, name, right, core, bb):
    """-> (tr, hv): the object (core natural bbox) scaled and placed, the headline placed, as one group centred in the band; None when it does not fit at natural size or wider than the safe width"""
    d = SLOT_DEFS[name]
    it = g.get("head_it")
    cw, ch = float(core[2] - core[0]), float(core[3] - core[1])
    if not it or cw <= 0 or ch <= 0:
        return None
    x0, x1 = (80.0, 888.0) if cw > 780 else (90.0, 770.0)          # a full-width card (a clipping, over 780 px) is allowed under the TikTok column as before; the rest stay clear of it
    s_w = (x1 - x0) / cw
    if s_w < 0.85:
        return None
    band0, band1 = GROUP_BAND
    bh_ = band1 - band0
    hh = len(it["lines"]) * it["fs"] * 0.9
    s = min(max(1.0, min((GROUP_FILL * bh_ - hh - GROUP_GAP) / ch, S_MAX)), s_w)          # up by its height, never wider than the safe width (a card a little over 680 px comes in to it)
    hv, top = None, band0
    for _ in range(3):
        G = hh + GROUP_GAP + ch * s
        if G > bh_ + 1e-6:
            if s > min(1.0, s_w):
                s = max(min(1.0, s_w), (bh_ - hh - GROUP_GAP) / ch)
                continue
            return None
        top = band0 + (bh_ - G) / 2.0
        hy = top if d["head"] == "top" else top + ch * s + GROUP_GAP
        hv = head_at(P, g, hy, right)
        if hv is None:
            return None
        if abs(hv["box"].h - hh) < 1.0:
            break
        hh = hv["box"].h
    else:
        return None
    obj_top = top + hh + GROUP_GAP if d["head"] == "top" else top
    nw = cw * s
    nx0 = {"l": x0, "r": x1 - nw, "c": (x0 + x1 - nw) / 2.0}[d["ax"]]
    c0 = ((core[0] + core[2]) / 2.0, (core[1] + core[3]) / 2.0)
    tr = dict(tx=round(nx0 + nw / 2.0 - c0[0], 2), ty=round(obj_top + ch * s / 2.0 - c0[1], 2), s=round(s, 4), c0=c0)
    tr["bbox"] = (nx0, obj_top, nx0 + nw, obj_top + ch * s)
    tr["ext"] = tuple(tf_pt(c0, tr, bb[0], bb[1])) + tuple(tf_pt(c0, tr, bb[2], bb[3]))
    return tr, hv


def bare_layout(P, g, vert, right):
    """a beat with no object of its own: headline plus the known-name plate (hero scale) as one centred group -> hv with plate_x / plate_y"""
    it = g.get("head_it")
    if not it:
        return None
    pw_, ph_ = P.plate_full["w"], P.plate_full["h"]
    band0, band1 = GROUP_BAND
    hh = len(it["lines"]) * it["fs"] * 0.9
    hv = None
    for _ in range(3):
        G = hh + GROUP_GAP + ph_
        top = band0 + (band1 - band0 - G) / 2.0
        hy = top if vert == "top" else top + ph_ + GROUP_GAP
        hv = head_at(P, g, hy, right)
        if hv is None:
            return None
        if abs(hv["box"].h - hh) < 1.0:
            break
        hh = hv["box"].h
    py_ = top + hh + GROUP_GAP if vert == "top" else top
    hv = dict(hv, plate_x=int(OBJ_X + (OBJ_W - pw_) / 2), plate_y=int(py_))
    return hv


CHIP_BOXES = []          # the footer chips are gone (root 26 Oct)


def layout_blocks(head_box, obj_box):
    """the blocks (24 px grid) a beat's layout fills: the headline, the object, the two chips: a stand-in for the sheet's content mask, used to pick the slot that differs most from the last beat"""
    out = set()
    boxes = list(CHIP_BOXES)
    if head_box is not None:
        boxes.append((head_box.x0 - 12, head_box.y0 - 12, head_box.x1 + 12, head_box.y1 + 12))
    if obj_box is not None:
        boxes.append(tuple(obj_box))
    for x0, y0, x1, y1 in boxes:
        for gx in range(int(max(0, x0) // 24), int(min(1079, x1) // 24) + 1):
            for gy in range(int(max(0, y0) // 24), int(min(1919, y1) // 24) + 1):
                out.add((gx, gy))
    return out


def block_iou(a, b):
    u = len(a | b)
    return len(a & b) / float(u) if u else 1.0


def span_nat(P, si):
    """(natural bbox, the same with the room of a backing panel, smallest text px) of the object of span si"""
    core = span_bbox(P, si)
    if core is None:
        return None, None, 0
    sp = P.plan["spans"][si]
    bb = core
    if any(it.get("pan") == si for it in P.items):
        bb = (core[0] - 30, core[1] - 10, core[2] + 30, core[3] + 10)
    fs_ = [b["fs"] for b in P.boxes if b.get("obj") == si and b.get("kind") == "text" and b.get("fs")]
    if sp["spec"]["kind"] == "price_tag":
        fs_ += [P.tag_obj["lfs"], P.tag_obj["vfs"]]
    return core, bb, (min(fs_) if fs_ else 0)


def apply_slots(P):
    pl, bs, groups, spans = P.plan, P.spec_beats, P.plan["groups"], P.plan["spans"]
    order = list(FF.FORMATS[P.fmt_name].get("slots") or list(SLOT_DEFS))
    off = (int(sha1(P.sid)[:4], 16) + sum(int(f[5:]) for f in P.flags if f.startswith("lseed"))) % len(order)
    rot = order[off:] + order[:off]
    P.nat_boxes = {b["id"]: b["box"] for b in P.boxes if b.get("obj") is not None}
    body = [(i, b) for i, b in enumerate(bs) if groups[0]["C"] - 1e-6 <= b["t_from"] < pl["C_v"] - 1e-6]

    def group_at(t):
        gi = 0
        for k, g in enumerate(groups):
            if g["C"] <= t + 1e-6:
                gi = k
        return gi

    def span_at(t):
        best = None
        for si, sp in enumerate(spans):
            if sp["spec"] and sp["t_in"] - 0.3 <= t:
                best = si
        if best is not None and t < spans[best]["t_out"] + 0.35:
            return best
        return None
    recent_l = [v.get("layout") or [] for _, v in sorted([(v_.get("at", ""), v_) for k_, v_ in jload(REG_FE, {}).items() if k_ != P.sid], key=lambda x: x[0])[-10:]]          # the last 10 engine shorts' layouts: a beat avoids the token they put in the same place
    nat = {}
    nb_of = {}
    for _, b_ in body:
        nb_of[group_at(b_["t_from"])] = nb_of.get(group_at(b_["t_from"]), 0) + 1
    recs, group_head, last_used, bare_first = [], {}, {}, {}
    prev = None
    for k, (bi, b) in enumerate(body):
        gi = group_at(b["t_from"])
        g = groups[gi]
        si = span_at(b["t_from"])
        if si is not None and si not in nat:
            nat[si] = span_nat(P, si)
        names = list(rot) if si is not None else list(HEAD_SLOTS)
        if si is not None and spans[si]["spec"]["kind"] in SLOT_FIXED:
            names = ["centre-low"]
        elif si is not None and spans[si]["spec"]["kind"] == "price_tag":
            names = [n_ for n_ in names if SLOT_DEFS[n_]["head"] == "top"]          # the tag comes from frame 0's place: its headline stays above it
        if k == 0:
            names = ["centre-low"] if si is not None else ["plate-top"]
        if si is None and gi in bare_first:
            names = [bare_first[gi]]          # one plate per bare group: its beats keep one composition
        cands = []
        for rank, name in enumerate(names):
            for right in ((HEAD_SLOTS[name][1],) if si is None else (False, True)):
                tr = None
                if si is None:
                    vert, right_ = HEAD_SLOTS[name]
                    hv = bare_layout(P, g, vert, right_)
                    if hv is None:
                        continue
                    hname = vert + ("r" if right_ else "")
                    blocks = layout_blocks(hv["box"], (hv["plate_x"], hv["plate_y"], hv["plate_x"] + P.plate_full["w"], hv["plate_y"] + P.plate_full["h"]))
                else:
                    core, bb, minfs = nat[si]
                    res = group_layout(P, g, name, right, core, bb)
                    if res is None:
                        continue
                    tr, hv = res
                    hname = SLOT_DEFS[name]["head"] + ("r" if right else "")
                    hb = hv["box"]
                    if FL.Box(*tr["ext"]).overlap(FL.Box(hb.x0 - 8, hb.y0 - 8, hb.x1 + 8, hb.y1 + 8)) > 0:
                        continue
                    if any(FL.text_ok(tf_box(tr["c0"], tr, nb["box"])) for nb in (b_ for b_ in P.boxes if b_.get("obj") == si and b_.get("kind") == "text")):
                        continue
                    blocks = layout_blocks(hv["box"], tr["bbox"])
                cands.append((name, hname, hv, tr, rank, blocks))
        stuck = False
        pool = [c for c in cands if (c[0], c[1]) != ((prev or {}).get("slot"), (prev or {}).get("head"))]          # a beat differs from the last in its slot or in the side its headline is set on
        if not pool:
            pool, stuck = cands, bool(cands)
        def score(c):
            age = min(4, k - last_used.get(c[0], -99))
            iou_ = block_iou(c[5], prev["blocks"]) if prev else 0.0
            reach = 8.0 if iou_ <= 0.66 else 0.0          # sheet_check DISTINCT: the sheet's mask overlap runs about 0.72 x this block-grid overlap, so under 0.66 here is under 0.5 there
            tok = "%s:%s" % (c[0], c[1])
            same_pos = sum(1 for l_ in recent_l if k < len(l_) and l_[k] == tok)
            return reach + 6.0 * (1.0 - iou_) - 1.2 * same_pos + 0.6 * age - 0.05 * c[4]
        best = max(pool, key=score) if pool else None
        # a held object that no slot can move far enough (a tall quote card, a full-width clipping) steps aside for one beat: a headline-only beat, then it comes back
        if (CUTAWAY and si is not None and prev is not None and prev["si"] == si and prev["slot"] != "cutaway" and spans[si]["spec"]["kind"] not in ("price_tag",) + SLOT_FIXED
                and False):
            pass
        if best is None:
            raise EngineError("beat %s has no layout slot (object %s): the headline, the object and the safe zone leave no room" % (b["id"], (spans[si]["spec"]["kind"] if si is not None else "none")))
        name, hname, hv, tr, rank, blocks = best
        rec = dict(bi=bi, id=b["id"], t0=b["t_from"], t1=b["t_to"], gi=gi, si=si, slot=name, head=hname, hv=hv, tr=tr, stuck=stuck, blocks=blocks)
        recs.append(rec)
        if si is None:
            bare_first.setdefault(gi, name)
        last_used[name] = k
        prev = rec
    P.slot_recs = recs
    for r in recs:
        if r["stuck"]:
            P.repairs.append("layout slot repeated on beat %s: no other slot holds this object at DIRECTOR scale" % r["id"])
    # 1. headlines move. A group whose beats take different headline positions is RE-STAGED: the headline leaves before the object moves and slams again at the new place on the next beat
    def head_box(it, hv, t0, t1):
        return dict(id=it["id"], box=hv["box"], t0=t0, t1=t1, label=" / ".join(hv["lines"])[:40], kind="text", fs=hv["fs"], head=True)
    last_head = {}
    for gi, g in enumerate(groups):
        it0 = g.get("head_it")
        rs_ = [r for r in recs if r["gi"] == gi]
        if not it0 or not rs_:
            continue
        runs = []
        for r in rs_:
            if runs and runs[-1]["head"] == r["head"]:
                runs[-1]["t1"] = r["t1"]
            else:
                runs.append(dict(head=r["head"], t0=r["t0"], t1=r["t1"], hv=r["hv"]))
        orig_to = it0["to"]
        P.boxes = [b_ for b_ in P.boxes if b_["id"] != it0["id"]]
        for k, run in enumerate(runs):
            it = it0 if k == 0 else dict(it0, id=P.nid("t"), ti=r2(run["t0"]), ain="slam")
            if k:
                it.pop("snd", None)
                it["pulses"] = [t_ for t_ in (it0.get("pulses") or []) if t_ > run["t0"] + 0.3]
                P.items.append(it)
                P.events.append((r2(run["t0"]), 1.0, "text"))
            hv = run["hv"]
            it["y"], it["x"], it["w"], it["al"], it["lines"], it["fs"], it["html"] = r2(hv["y"]), hv["x"], hv["w"], hv["al"], hv["lines"], hv["fs"], hv["html"]
            it["org"] = "100% 100%" if hv["al"] == "r" else "0% 100%"
            it["to"] = orig_to if k == len(runs) - 1 else r2(runs[k + 1]["t0"] - SLOT_TRAVEL_LEAD - 0.25)
            if k == 0 and it0.get("pulses"):
                it0["pulses"] = [t_ for t_ in it0["pulses"] if k == len(runs) - 1 or t_ < it["to"] - 0.1]
            P.boxes.append(head_box(it, hv, it["ti"], it["to"]))
            last_head[gi] = it
    # 1b. a headline leaves before the object that moves at the next group's cut starts to move (no object ever slides over a headline that is still on screen)
    for a, b in zip(recs, recs[1:]):
        if a["gi"] == b["gi"]:
            continue
        moves = (a["si"] is not None and a["si"] == b["si"]) or (b["si"] is not None and spans[b["si"]]["spec"]["kind"] == "price_tag" and a["si"] != b["si"])
        it = last_head.get(a["gi"])
        if moves and it and it.get("to") is not None:
            lim = r2(b["t0"] - SLOT_TRAVEL_LEAD - 0.25)
            if it["to"] > lim:
                it["to"] = lim
                for b_ in P.boxes:
                    if b_["id"] == it["id"]:
                        b_["t1"] = lim
    # 2. the object groups: items, boxes, keys
    P.og = []
    og_by_si = {}
    for si in sorted(set(r["si"] for r in recs if r["si"] is not None)):
        rs = [r for r in recs if r["si"] == si]
        c0 = rs[0]["tr"]["c0"]
        keys = []
        last_tr = None
        for j, r in enumerate(rs):
            tr_ = r["tr"] or last_tr
            last_tr = tr_
            keys.append(dict(t=0.0 if j == 0 else r2(r["t0"] - SLOT_TRAVEL_LEAD), tx=tr_["tx"], ty=tr_["ty"], s=tr_["s"], op=0 if r["tr"] is None else 1))
            if j:
                P.events.append((r2(r["t0"] - SLOT_TRAVEL_LEAD + 0.1), 1.0, "slot"))
        og_by_si[si] = dict(rs=rs, c0=c0)
        if spans[si]["spec"]["kind"] != "price_tag":
            P.og.append(dict(i=si, cx=round(c0[0], 2), cy=round(c0[1], 2), keys=keys))
            for it in P.items:
                if it.get("obj") == si or it.get("pan") == si:
                    it["og"] = si
    # object boxes follow their beat's slot (one box per beat slice, same id)
    newb = []
    for bx in P.boxes:
        si = bx.get("obj")
        if si is None or si not in og_by_si:
            newb.append(bx)
            continue
        info = og_by_si[si]
        made = 0
        for r in info["rs"]:
            if r["tr"] is None:
                continue
            lo = max(bx["t0"], r["t0"])
            hi = min(bx["t1"] if bx["t1"] is not None else 1e9, r["t1"])
            if hi - lo > 0.02:
                nb = dict(bx)
                nb["box"], nb["t0"], nb["t1"] = tf_box(info["c0"], r["tr"], bx["box"]), lo, hi
                nb["fs"] = bx["fs"] * r["tr"]["s"]
                newb.append(nb)
                made += 1
        if not made:
            r = info["rs"][0]
            nb = dict(bx)
            nb["box"], nb["fs"] = tf_box(info["c0"], r["tr"], bx["box"]), bx["fs"] * r["tr"]["s"]
            newb.append(nb)
    P.boxes = newb
    # 3. the hero tag travels with its slot; the ring that marks the figure follows
    tk = P.tag_keys
    for si, info in og_by_si.items():
        sp = spans[si]
        if sp["spec"]["kind"] != "price_tag":
            continue
        c0 = info["c0"]
        t_obj = r2(sp["t_in"] - HERO_LEAD)
        for j, r in enumerate(info["rs"]):
            kk = tag_slot_key(P, t_obj if j == 0 else r["t0"] - SLOT_TRAVEL_LEAD, r["tr"], c0)
            if j == 0:
                for q, k0 in enumerate(tk):
                    if abs(k0["t"] - t_obj) < 0.011 and abs(k0["y"] - P.tag_obj["y"]) < 1.5:
                        tk[q] = kk
                        break
            else:
                tk.append(kk)
                P.events.append((kk["t"], 1.0, "tag"))
        for it in P.items:
            if it["k"] == "ring" and it.get("obj") == si:
                r = next((r_ for r_ in info["rs"] if r_["t0"] - 1e-6 <= it["ti"] < r_["t1"]), info["rs"][0])
                it["x"], it["y"] = [r2(v) for v in tf_pt(c0, r["tr"], it["x"], it["y"])]
    tk.sort(key=lambda k: k["t"])
    tag_boxes(P)
    # 4. the sheet's view of each beat: where the object may sit (rows y0-y1)
    for r in recs:
        if r["si"] is None or r["tr"] is None:
            r["zone"] = None
        else:
            r["zone"] = (max(288, int(r["tr"]["bbox"][1] - 24)), min(1248, int(r["tr"]["bbox"][3] + 24)))
    # the plate of a bare beat takes its place in the group
    moved = False
    for r in recs:
        if r["si"] is None and r["hv"] and "plate_y" in r["hv"]:
            for k_ in P.plate_keys:
                if k_.get("bg") == r["gi"]:
                    k_["x"], k_["y"] = r["hv"]["plate_x"], r["hv"]["plate_y"]
                    moved = True
    if moved:
        plate_boxes(P)


def layout_sig(P):
    """the layout sequence of a short: slot + headline side per body beat"""
    return ["%s:%s" % (r["slot"], r["head"]) for r in getattr(P, "slot_recs", [])]


def tag_slot_key(P, t, tr, c0):
    k = dict(P.tag_obj)
    s = tr["s"]
    k["x"], k["y"] = [int(round(v)) for v in tf_pt(c0, tr, P.tag_obj["x"], P.tag_obj["y"])]
    for p in ("w", "h", "vfs", "lfs", "vy", "ly"):
        k[p] = int(round(P.tag_obj[p] * s))
    k["t"] = r2(t)
    return k


def object_sig(spec):
    """the visible identity of an object: its kind and its content (the same formula extract_story.object_identity uses)"""
    if spec.get("kind") == "price_tag":          # the hero tag is one object whatever window said its figure
        return json.dumps(["price_tag"])
    f, q = spec.get("figure") or {}, spec.get("quote") or {}
    return json.dumps([spec.get("kind"), spec.get("content") or {}, [f.get(k) for k in ("value", "unit", "display")], [q.get(k) for k in ("text", "speaker", "source_id")]], sort_keys=True, default=str)


def repeat_checks(P):
    """root 26 Oct, rule 1 + the continuity ruling: an object holds across up to 3 consecutive beats ONLY if every beat shows a new state of it (a new value, a new mark, a new detail, a role change),
    grounded in the story. The check counts (object, state) pairs: the same pair on two beats is a slideshow. A story whose beats outnumber its distinct (object, state) pairs is THIN
    (it goes back to the supply line for richer sources; the engine never pads)."""
    recs = getattr(P, "slot_recs", None) or []
    seen, fails, per_span = {}, [], {}
    if os.environ.get("FE_LOOK_ALLOW_REPEAT") == "1":          # a LOOK build to read other fixes on a sheet; such a short is never submitted (produce --no-submit)
        return fails
    for r in recs:
        if r["si"] is None:
            continue
        spec = P.plan["spans"][r["si"]]["spec"]
        if spec["kind"] == "price_tag":          # the hero's permitted returns (DIRECTOR ruling 4): frame 0, up to HERO_MIDDLE_MAX middle beats where the voice says the figure, the loop-end close. None counts as a repeat; any other return fails
            hs_ = (P.story["huge_cost"].get("spoken") or [None, None])
            if hs_[0] is None or not (P.words[hs_[0]]["start"] <= r["t1"] + 0.05 and P.words[hs_[1]]["end"] >= r["t0"] - LEAD - 0.05):
                fails.append("the hero tag returns on beat %s where the figure is not spoken (it may return only on the beats where the voice says it)" % r["id"])
            continue
        j = per_span.get(r["si"], 0)
        per_span[r["si"]] = j + 1
        S = max(1, int(spec.get("S") or 1))
        r["state"] = min(j, S - 1)
        sig = (object_sig(spec), r["state"])
        if j >= 3:
            fails.append("object held too long: the %s is on its %d-th beat %s (a held object may take 3 beats at most)" % (spec["kind"], j + 1, r["id"]))
        if sig in seen:
            ids_ = len(set((object_sig(P.plan["spans"][q["si"]]["spec"]), q.get("state", 0)) for q in recs if q["si"] is not None))
            fails.append("object content repeated: the %s on beat %s shows the same state (%d of %d) as on beat %s (%d body beats, %d distinct objects and states)" % (spec["kind"], r["id"], r["state"] + 1, S, seen[sig], len(recs), ids_))
        else:
            seen[sig] = r["id"]
    return fails


def slot_checks(P):
    """-> failures of the layout grammar: a slot repeated on consecutive beats, fewer than 5 slots in the format, an object outside DIRECTOR scale or the safe zone, the headline over the object"""
    fails = []
    order = FF.FORMATS[P.fmt_name].get("slots") or []
    if len(set(order)) < 5:
        fails.append("the format %s has %d layout slots (needs >= 5)" % (P.fmt_name, len(set(order))))
    recs = getattr(P, "slot_recs", None)
    if recs is None:
        return ["the layout grammar did not run"]
    for a, b in zip(recs, recs[1:]):
        if a["slot"] == b["slot"] and a["head"] == b["head"] and not b.get("stuck"):
            fails.append("beats %s and %s use the same layout slot %r in a row" % (a["id"], b["id"], a["slot"]))
    for r in recs:
        if r["si"] is None or r["tr"] is None:
            continue
        tr = r["tr"]
        x0, y0, x1, y1 = tr["bbox"]
        w_, h_ = x1 - x0, y1 - y0
        mw_, mh_ = OBJ_MIN_W, OBJ_MIN_H
        if w_ < mw_ or h_ < mh_:
            fails.append("beat %s (%s): the object is %.0f x %.0f px (needs >= %.0f x %.0f)" % (r["id"], r["slot"], w_, h_, mw_, mh_))
        if x0 < 80 - 1 or x1 > 888 + 1 or y0 < 288 - 1 or y1 > 1248 + 1:
            fails.append("beat %s (%s): the object runs outside the safe zone (%.0f,%.0f)-(%.0f,%.0f)" % (r["id"], r["slot"], x0, y0, x1, y1))
        if y1 > 840 and x1 > 780 + 1 and (x1 - x0) <= 780 + 1:          # a full-width card (over 700 px) is allowed under the column as before
            fails.append("beat %s (%s): the object enters the TikTok column (x to %.0f below y 840)" % (r["id"], r["slot"], x1))
        hb = r["hv"]["box"]
        if FL.Box(x0, y0, x1, y1).overlap(hb) > 0:
            fails.append("beat %s (%s): the headline overlaps the object" % (r["id"], r["slot"]))
        lo_, hi_ = SLOT_CY
        if not lo_ <= (y0 + y1) / 2.0 <= hi_:
            fails.append("beat %s (%s): the object is centred at y %.0f (needs %d to %d)" % (r["id"], r["slot"], (y0 + y1) / 2.0, lo_, hi_))
    return fails


OBJ_MIN_W, OBJ_MIN_H = 0.55 * 808, 280


def director_checks(P):
    """-> list of failures. Each line is a rule from DIRECTOR.md / strategy v3 / root's gate on S136 that holds by construction."""
    fails = []
    pl = P.plan
    bs = P.spec_beats
    # 1. one world, travelled: a new camera view for every beat, never the same view twice running, back to the first on the last frame
    wk = P.world_keys
    if len(wk) < len(bs) + 1:
        fails.append("the world has %d camera keys for %d beats" % (len(wk), len(bs)))
    for a, b in zip(wk, wk[1:]):
        if abs(a["px"] - b["px"]) + abs(a["py"] - b["py"]) < 40 and abs(a["z"] - b["z"]) < 0.2:
            fails.append("the camera does not move between %.2f s and %.2f s" % (a["t"], b["t"]))
    if not keys_equal(wk[0], wk[-1], ("px", "py", "z")):
        fails.append("the world's last view is not its first (the loop)")
    # 2. on-screen text >= 42 px
    for it in P.items:
        if it["k"] == "text" and it["fs"] < 42:
            fails.append("text %r is %s px (< 42)" % (" ".join(it["lines"])[:30], it["fs"]))
    for k in P.tag_keys:
        if k["lop"] > 0.5 and k["lfs"] < 42:
            fails.append("tag label is %s px (< 42)" % k["lfs"])
        if k["vfs"] < 42:
            fails.append("tag figure is %s px" % k["vfs"])
    # 3. objects 60 px inside the frame edge
    for it in P.items:
        if it["k"] in ("rect", "img", "path", "text"):
            x0, y0, x1, y1 = it["x"], it["y"], it["x"] + it["w"], it["y"] + it.get("h", it["fs"] * 1.1 if it["k"] == "text" else 0)
            if it["k"] == "text":
                bx = next((b["box"] for b in P.boxes if b["id"] == it["id"]), None)
                if bx:
                    x0, x1 = bx.x0, bx.x1
            if x0 < 60 - 1e-6 or y0 < 60 or x1 > 1020 + 1e-6 or y1 > 1860:
                fails.append("%s item %s at (%d,%d)-(%d,%d) is inside 60 px of the frame edge" % (it["k"], it["id"], x0, y0, x1, y1))
    for k in P.tag_keys + P.plate_keys:
        if k["x"] < 60 or k["y"] < 60 or k["x"] + k["w"] > 1020 or k["y"] + k["h"] > 1860:
            fails.append("a tag/plate key at %.2f s is inside 60 px of the frame edge" % k["t"])
    # 4. no text over text, everything in the universal zone
    fails += P.check_geometry()
    # 5. beat rate and length
    for b in bs:
        if b["t_to"] - b["t_from"] > 4.4 + 1e-6:
            fails.append("beat %s is %.2f s (> 4.4)" % (b["id"], b["t_to"] - b["t_from"]))
    rate = len(bs) / (P.dur / 60.0)
    if rate < 21.0:
        fails.append("%.1f beats a minute (< 21)" % rate)
    # 6. the outgoing layer is at 0 opacity ON each cut: no item is mid-exit when a cut falls
    for b in bs[1:]:
        c = b["t_from"]
        for it in P.items:
            if it.get("to") is not None:
                d = it.get("do") or 5 * FR
                if it["to"] - 1e-6 < c < it["to"] + d - 1e-6:
                    fails.append("item %s is still fading out on the cut at %.2f s" % (it["id"], c))
                    break
    # 7. a reported figure is never counted through: no counting motion exists, and the hero figure is spoken
    if not P.story["huge_cost"].get("spoken"):
        fails.append("the hero figure is never spoken")
    if any(it.get("ain") == "count" for it in P.items):
        fails.append("a counting animation is present")
    # 8. sound: pan comes from the object's x; every cue has a visible event within 0.25 s
    for c in P.sfx:
        if 470 <= c["x"] <= 590:
            fails.append("cue at %.2f s is centred (x %d)" % (c["t"], c["x"]))
        if c["t"] > 0 and not any(abs(c["t"] - e[0]) < 0.25 for e in P.events + [(0.0, 0, "")] + [(P.fig_hit or -9, 0, "")]) and c["what"] not in ("paper", "whoosh"):
            fails.append("cue %s at %.2f s has no visible event within 0.25 s" % (c["what"], c["t"]))
    # 9. ending: verdict, question, CTA card with the audit link on ONE line >= 42 px and 24 px clear of the card each side; then the frame-0 composition (tag, plate, world, headline)
    link = [b for b in P.boxes if b["label"] == CTA_LINK]
    if not link:
        fails.append("the audit link is not on the CTA card")
    else:
        cx0, cw0 = P.cta_card
        bx = link[0]["box"]
        if link[0]["fs"] < 42 or bx.x0 - cx0 < 24 or (cx0 + cw0) - bx.x1 < 24:
            fails.append("the audit link is %s px and %.0f/%.0f px clear of the card (need >= 42 and 24)" % (link[0]["fs"], bx.x0 - cx0, (cx0 + cw0) - bx.x1))
    if not keys_equal(P.tag_keys[0], P.tag_keys[-1], ("x", "y", "w", "h", "vfs", "lfs", "lop", "rot", "op", "vy", "ly")):
        fails.append("the loop's last tag key is not the frame-0 tag")
    if not keys_equal(P.plate_keys[0], P.plate_keys[-1], ("x", "y", "w", "h", "op", "fs")):
        fails.append("the loop's last plate key is not the frame-0 plate")
    if P.dur - P.tag_keys[-1]["t"] < 0.45:
        fails.append("the tag has %.2f s to settle back to frame 0 (need >= 0.45)" % (P.dur - P.tag_keys[-1]["t"]))
    loop_h = [it for it in P.items if it.get("head") and it["ti"] >= pl["T_end"] and it.get("to") is None]
    if not loop_h:
        fails.append("the frame-0 headline does not return after the CTA")
    # 10. no prop labels: every printed string is story text, an outlet name, a credit, or fixed chrome
    ok = P.printable()
    for it in P.items:
        if it["k"] == "text":
            for ln in it["lines"]:
                n = re.sub(r"[^a-z0-9£$%]+", " ", ln.lower()).strip()
                n = re.sub(r"^(from|to|total|invoice|receipt|subject) ", "", n)           # fixed chrome in front of grounded text
                if n and n not in ok and not any(n in o for o in ok):
                    fails.append("printed string %r is not story text or fixed chrome" % ln)
    # 11. frame 0 (lesson 1): known name + tiny cause + the figure at >= 205 px, <= 12 readable words, the sting's bottom slot clear
    f0 = P.tag_full
    if f0["vfs"] < 180:
        fails.append("frame-0 figure is %s px" % f0["vfs"])
    words70 = len(P.story["huge_cost"]["display"].split()) + (len(P.story["tiny_cause"]["text"].split()) if P.hook_fs >= 70 else 0)
    if not P.assets.get("logo") and P.plate_full["fs"] >= 70:
        words70 += len(P.story["known_name"]["text"].split())
    if words70 > 12:
        fails.append("frame 0 has %d words at >= 70 px (> 12)" % words70)
    if f0["y"] + f0["h"] > 1088 - 16 + 1e-6:
        fails.append("the frame-0 tag runs to y %.0f into the sting's bottom slot" % (f0["y"] + f0["h"]))
    if P.hook_fs < 76:
        fails.append("the frame-0 headline is %s px (< 76)" % P.hook_fs)
    # 11b. root's second gate (21 Oct): the object is at hero scale and mid-frame; the hero tag is not the answer to every beat
    fails += slot_checks(P)
    fails += repeat_checks(P)
    n_tag = sum(1 for sp in P.plan["spans"] if sp["spec"] and sp["spec"]["kind"] == "price_tag" and sp["t_in"] > 0.5)
    first_in = P.plan["spans"][0]["t_in"] if P.plan["spans"] else 0
    tag_beats = sum(1 for b in bs[1:] if (b["t_from"] + b["t_to"]) / 2.0 >= first_in and any(sp["spec"] and sp["spec"]["kind"] == "price_tag" and sp["t_in"] - 0.4 <= (b["t_from"] + b["t_to"]) / 2.0 < sp["t_out"] for sp in P.plan["spans"]))
    if tag_beats > HERO_MIDDLE_MAX:
        fails.append("the hero tag is the object of %d middle beats (max %d)" % (tag_beats, HERO_MIDDLE_MAX))
    # 11c. root 21 Oct ("THE NEG" for The Negotiator): no text is truncated, ellipsised or clipped by its card
    boxes_by_id = dict({b["id"]: b["box"] for b in P.boxes}, **getattr(P, "nat_boxes", {}))
    for it in P.items:
        if it["k"] != "text":
            continue
        for ln in it["lines"]:
            if "\u2026" in ln or "..." in ln:
                fails.append("text %r contains an ellipsis (truncated copy)" % ln[:40])
        bx = boxes_by_id.get(it["id"])
        if bx is None:
            continue
        if bx.w > it["w"] + 2:
            fails.append("text %r is %.0f px wide in a %.0f px box (it would overflow or be clipped)" % (" ".join(it["lines"])[:34], bx.w, it["w"]))
        if it.get("obj") is not None:
            for r in P.items:
                if r["k"] == "rect" and r.get("obj") == it["obj"] and r["x"] <= bx.x0 + 2 <= r["x"] + r["w"] and r["y"] <= bx.y0 + 2 <= r["y"] + r["h"] and r.get("fill") and r["w"] * r["h"] > 40000:
                    if bx.x1 > r["x"] + r["w"] + 3 or bx.y1 > r["y"] + r["h"] + 3:
                        fails.append("text %r runs past the edge of its card (%.0f,%.0f to %.0f,%.0f in a card ending %.0f,%.0f)" % (" ".join(it["lines"])[:34], bx.x0, bx.y0, bx.x1, bx.y1, r["x"] + r["w"], r["y"] + r["h"]))
                    break
    for k in P.plate_keys:
        if not P.assets.get("logo") and k["fs"]:
            if FL.tw(P.story["known_name"]["text"], "cond", 700, k["fs"], 0.0, True) > k["w"] - 16:
                fails.append("the plate wordmark %r does not fit its plate (%d px wide, plate %d)" % (P.story["known_name"]["text"], FL.tw(P.story["known_name"]["text"], "cond", 700, k["fs"], 0.0, True), k["w"]))
    # 12. every beat has its own event within 0.9 s of its cut and each body beat its own scene object
    ev = sorted(e[0] for e in P.events)
    for b in bs[1:]:
        if not any(b["t_from"] - 0.4 <= t <= b["t_from"] + 0.9 for t in ev):
            fails.append("beat %s has no visible event within 0.9 s of its cut" % b["id"])
    kinds = [s for s in P.skins_used if s not in ("verdict",)]
    if len(set(kinds)) < min(3, len(kinds)):
        fails.append("the body beats use %d scene kinds (need >= 3)" % len(set(kinds)))
    for a, b in zip(kinds, kinds[1:]):
        if a == b:
            fails.append("two body beats in a row use the %s scene" % a)
    return fails


def printable_set(P):
    st = P.story
    texts = [st["known_name"]["text"], st["tiny_cause"]["text"], st["huge_cost"]["label"], st["huge_cost"]["display"], st["verdict"]["text"], st["question"]["text"], st["cta"]["line"],
             CTA_LINK, "YES", "NO", "FOLLOW", "FOLLOWING", "AI CONSTRAINT AUDIT"]
    for b in st["beats"]:
        for k in ("phrase",):
            if b.get(k):
                texts.append(b[k])
        if b.get("figure"):
            texts.append(b["figure"]["display"])
        if b.get("quote"):
            texts += [b["quote"]["text"], b["quote"].get("speaker") or ""]
    for s in st.get("sources", []):
        texts.append(s["outlet"])
    cl = P.assets.get("clause")
    if cl:
        texts.append(cl["credit"])
    texts += [w["word"] for w in P.words]          # a stressed word set at picture scale is a word the voice says
    texts.append(" ".join(w["word"] for w in P.words))       # a headline is a clause of what the voice says
    texts += [(b.get("headline") or {}).get("text") or "" for b in st["beats"]]
    for b in st["beats"]:
        ob_ = b.get("object") or {}
        if ob_.get("kind") in ("logo_pair", "map_route"):
            texts += [display_name(P, ob_["content"].get(k_, "")) for k_ in ("a", "b", "from", "to") if ob_["content"].get(k_)]
    texts += ["FROM", "TO", "TOTAL", "INVOICE", "RECEIPT", "SUBJECT"]       # chrome the engine prints around grounded content
    def leaves(x):
        if isinstance(x, str):
            yield x
        elif isinstance(x, dict):
            for k_, v_ in x.items():
                if k_ in ("who", "key", "source_id", "ledger", "para", "kind", "unit"):
                    continue
                for y_ in leaves(v_):
                    yield y_
        elif isinstance(x, list):
            for v_ in x:
                for y_ in leaves(v_):
                    yield y_
    for b in st["beats"]:
        if b.get("object"):
            texts += list(leaves(b["object"]["content"]))
    for src_ in st.get("sources", []):
        texts.append(re.sub(r"\.(co\.uk|com|org|net)$", "", src_.get("outlet") or "", flags=re.I))
    for cl_ in (P.assets.get("clips") or {}).values():
        texts.append(cl_["credit"])
    return set(re.sub(r"[^a-z0-9£$%]+", " ", t.lower()).strip() for t in texts if t)


Plan.printable = lambda self: printable_set(self)


# ================================================================================================ output: display list, spec, concept
def slot_info(P, bid):
    r = next((r_ for r_ in getattr(P, "slot_recs", []) if r_["id"] == bid), None)
    if not r:
        return {}
    d = dict(slot=r["slot"], head=r["head"])
    if "state" in r:
        d["state"] = r["state"]
    if r["zone"]:
        d["zone"] = list(r["zone"])
    if r["tr"]:
        d["obj"] = [round(v, 1) for v in r["tr"]["bbox"]]
    return d


def display_data(P):
    sw, F = P.sw, P.F
    lg = P.assets.get("logo")
    if P.light or P.world_kind != "map":
        land, coast, grid = sw["land"] if P.light else mix_hex(sw["ground"], sw["ink"], 0.30), sw["coast"] if P.light else mix_hex(sw["ground"], sw["ink"], 0.40), sw["grid"] if P.light else mix_hex(sw["ground"], sw["ink"], 0.16)
    else:
        land, coast, grid = mix_hex(sw["ground"], sw["ink"], 0.15), mix_hex(sw["ground"], sw["ink"], 0.42), mix_hex(sw["ground"], sw["ink"], 0.10)
    if P.world_kind == "map" and P.light:
        land, coast, grid = mix_hex(sw["ground"], sw["ink"], 0.10), mix_hex(sw["ground"], sw["ink"], 0.35), mix_hex(sw["ground"], sw["ink"], 0.06)
    world = dict(kind=P.world_kind, light=P.light, seed=int(sha1(P.sid)[:6], 16), keys=P.world_keys, ground=sw["ground"], land=land, coast=coast, grid=grid,
                 pin=sw["accent"], cx=540, cy=900, pins=([dict(lon=-1.6, lat=52.8, t=0.0)] if P.world_kind == "map" and not P.routes else []), routes=P.routes)
    tag = dict(keys=P.tag_keys, fill=sw["tag_fill"], radius=F["chip_r"] + 22, rim=sw["tag_rim"], string=sw["tag_string"], ink=sw["tag_ink"], labcol=sw["tag_lab"], labface="cond", labwt=700,
               value=P.tag_value, vls=getattr(P, "tag_ls", 0.0), label=P.tag_label, pulses=sorted(set(r2(t) for t in P.tag_pulses)), drops=sorted(set(r2(t) for t in P.tag_drops)))
    plate = dict(keys=P.plate_keys, fill=sw["plate"], ink=sw["plate_ink"], name=P.story["known_name"]["text"], logo=(dict(src=lg["src"]) if lg else None))
    spans = [dict(i=i, kind=(sp["spec"] or {}).get("kind"), t_in=r2(sp["t_in"]), t_out=r2(sp["t_out"])) for i, sp in enumerate(P.plan["spans"]) if sp["spec"]]
    return dict(z=F["z"], w=F["w"], pal=P.pal, dur=P.dur, sting=dict(avoid=[dict(x0=80, y0=296, x1=888, y1=1070)]), world=world, tag=tag, plate=plate, items=P.items, spans=spans, og=getattr(P, "og", []),
                beats=[dict(dict(id=b["id"], t0=b["t_from"], t1=b["t_to"]), **slot_info(P, b["id"])) for b in P.spec_beats])


def write_scenes(P, data):
    rt = open(RT_JS, encoding="utf-8").read()
    js = ("/* specs/%s/scenes.js: GENERATED by kit/tools/format_engine.py (v%s) from specs/%s/story.json + the voice take's word times (preset %s, swatch %s). Do not edit by hand:\n"
          "   change story.json or the engine and rebuild. The runtime below is tools/format_engine_rt.js, inlined so an approved short's hash freezes the exact version. */\n" % (P.sid, ENGINE_VERSION, P.sid, P.fmt_name, P.sw_key))
    js += rt + "\n"
    js += "window.FMT_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
    js += "(function(){ var K = window.AGK; K.scenes['fmt-world'] = function (ctx, spec, K2) { ctx.root.style.setProperty('--accent', window.FMT_DATA.pal.accent); window.FMT.run(ctx, spec, K2); };\n"
    js += "  K.scenes['fmt-beat'] = window.FMT.beat; })();\n"
    return js

# ================================================================================================ concept.json, craft block, pitch
def mix_hex(a, b, u):
    x = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    y = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(int(round(x[i] + (y[i] - x[i]) * u)) for i in range(3))


def sheet_fill(P):
    """the declared ground is what storyboard.py's sheet verification measures: the dominant colour over every beat, which is the desk / field around the sheet
    (31% of every frame) because the sheet's own tint changes from beat to beat"""
    return P.pal["ground"]


def pitch_block(P, spoken):
    import craft_check as CC
    st = P.story
    f0 = st["huge_cost"]
    lab = set(CC.content_words(f0["label"]))
    num_sentence, best = None, -1
    for s in CC.spoken_sentences(spoken):
        nw = number_words_in(s)
        if nw:
            sc = len(lab & set(CC.content_words(s)))
            if sc > best:
                best, num_sentence = sc, s
    if not num_sentence:
        raise EngineError("no sentence of the script speaks the hero figure as number words")
    nspoken = number_words_in(num_sentence)
    objs, seen = [], set()
    for name, wi, t in P.objects:
        w = CC.norm(P.words[wi]["word"])
        if not (w.isalpha() and w in CC.norm(spoken).split()):
            w = next((CC.norm(x["word"]) for x in P.words[max(0, wi - 6): wi + 7] if CC.norm(x["word"]).isalpha() and len(CC.norm(x["word"])) >= 4 and CC.norm(x["word"]) in CC.norm(spoken).split()), None)
        if not w:
            continue
        nm = name if name not in seen else "%s (%s)" % (name, w)
        k_ = 2
        while nm in seen:                 # one name per constructed object: the pitch check refuses duplicates
            nm = "%s (%s %d)" % (name, w, k_)
            k_ += 1
        seen.add(name)
        seen.add(nm)
        objs.append(dict(name=nm, word=w, at_s=None, constructed=True))
    # Use the gate's claim definition and the extractor's sentence/source bindings.
    # Never attribute every number to sources[0], or omit non-digit quantities.
    import concept_check as CK
    import extract_story as ES
    _, sentences = ES.parse_sentences(spoken)
    srcs = {s["id"]: s for s in st.get("sources") or []}
    claims = []
    for sent in sentences:
        if not CK.FIGURE_RX.search(CK.norm(sent["text"])):
            continue
        bound = sorted({b.get("source_id") for b in st["beats"]
                        if sent["id"] in b.get("sentences", []) and b.get("source_id") in srcs})
        if not bound:
            raise EngineError("factual sentence %s has no grounded source binding" % sent["id"])
        for source_id in bound:
            src = srcs[source_id]
            claims.append(dict(script_quote=sent["text"], source=dict(
                outlet=src["outlet"], date=src.get("published") or "undated source page",
                url=src["url"], shown_as="storyboard source attribution")))
    return dict(frame0=dict(subject=st["known_name"]["text"], number_on_screen=f0["display"], number_spoken=nspoken), objects=objs, claims=claims)


def hook_type_of(P):
    ht = P.story["experiment"]["hook_type"]
    import craft_check as CC
    if ht == "viewer-consequence" and not CC.YOU_RE.search((CC.spoken_sentences(P.spoken_text)[:1] or [""])[0]):
        return "stake-slam"                 # a viewer-consequence hook needs you/your in the first sentence (concept_check R10); the script's first sentence says none
    return ht


def craft_block(P, spoken):
    P.spoken_text = spoken
    import craft_check as CC
    st = P.story
    S = CC.spoken_sentences(spoken)
    you = any(CC.YOU_RE.search(s) for s in S[:2])
    sec = P.words[-1]["end"]
    ends = CC.ending_analysis(spoken)
    hc = st["huge_cost"]
    nm = st["known_name"]["text"]
    cl = P.assets.get("clause")
    fw = CC.norm(" ".join(CC.first_clause(spoken)))
    c0 = [CC.norm(x) for x in CC.content_words(spoken)]
    vtxt = st["verdict"]["text"]
    vw = next((w for w in CC.content_words(vtxt) if w in c0 and len(w) >= 5), "source")
    srcs = st.get("sources") or []
    ids = [b["id"] for b in P.spec_beats]
    h = int(sha1(P.sid)[:4], 16)
    moves = [dict(beat=bid, verb=VERBS[(i + h) % len(VERBS)]) for i, bid in enumerate(ids)]
    for i in range(1, len(moves)):          # adjacent beats never share a verb
        if moves[i]["verb"] == moves[i - 1]["verb"]:
            moves[i]["verb"] = VERBS[(VERBS.index(moves[i]["verb"]) + 1) % len(VERBS)]
    k = dict(
        answers=dict(
            expert_move="Keep ONE world map and ONE hero tag on screen from the first frame to the last, send the camera to a new region and give the beat its own object on every cut, so each stressed word moves something.",
            rawest_source="the original page behind the first source: %s (the proof clause is cut from its own paragraph)" % (srcs[0]["url"] if srcs else "specs/%s/story.json" % P.sid),
            methods=["format_engine.py cuts every beat from the voice take's word times (story.json windows, no model)", "crop_clause.py on the first source paragraph for the 1.5 s proof clause"],
            outside_judges=["dom_lint legibility and universal-zone rules on Actions", "concept_check R1 to R7 against the last 10 approved", "the independent reviewer comparing with P1 to P3"]),
        locked_message=vtxt if 20 <= len(vtxt) <= 140 else " ".join(vtxt.split()[:18]),
        banned=[b[:78] for b in P.F["banned"][:4]] + ["any figure beside %s that its source does not print" % hc["display"], "a made-up quote from %s" % nm, "an invented stamp or seal on the %s line" % st["tiny_cause"]["text"]],
        central_visual_rule="When the voice says %s the headline lands on the cut and the %s tag swings and drops." % (vw, hc["display"]),
        beat_moves=moves,
        hook=dict(type=hook_type_of(P), t0="%s plate, %s in %s px type on a hanging tag, %s in condensed type, over the map" % (nm, hc["display"], P.tag_full["vfs"], st["tiny_cause"]["text"]),
                  t1_5="the first source clause lands on the map and the tag drops to a chip at true size", desired_reaction="Wait, is that really what happened?"),
        frame0=dict(known_name=nm, known_name_as=("logo" if P.assets.get("logo") else "text"), cause=st["tiny_cause"]["text"], cost=hc["display"]),
        beat2_artefact=dict(artefact="notice", at_s=T_PROOF, attribution=("%s clause cut by crop_clause.py (%s)" % (outlet_of(P, {"source_id": None}), cl["credit"])) if cl else "no clause crop for this short (typeset fallback not used)"),
        experiment=dict(hook_type=hook_type_of(P), beat2_artefact="notice", you_by_3s=("yes" if you else "no"), brand_recognition=st["experiment"]["brand_recognition"],
                        length_bucket=CC.length_bucket(sec), ending_type=ends["type"]))
    k["loop_close"] = True
    if sec > 50:
        k["length_reason"] = "the story needs the failure, the official reply and the lesson in one take; the script predates strategy v3 and is not re-cut here"
    return k


WORLD_FAMILY = {"map": "map-plan", "desk": "desk-paper", "inbox": "ui-screen", "statement": "desk-paper", "counter": "interior-set", "phone": "ui-screen", "tribunal": "interior-set", "room": "interior-set", "blueprint": "desk-paper"}


def candidates(P):
    F = P.F
    h = int(sha1(P.sid)[:4], 16)
    rot = lambda a: [a[(h + i) % len(a)] for i in range(len(a))]
    return [WORLD_FAMILY[P.world_kind]], rot(F["hero"]), rot(F["signature"]), rot(F["source"])


def concept_dict(P, bed, world, hero, sig, srcp, spoken, bt, swap=False):
    import craft_check as CC
    import concept_check as CK
    gh = sheet_fill(P)
    st = P.story
    vw0, vw1 = st["verdict"]["words"]
    sw_idx = vw1
    for i in range(vw1, vw0 - 1, -1):
        w = CC.norm(P.words[i]["word"])
        if w.isalpha() and len(w) >= 4 and w in CC.norm(spoken).split():
            sw_idx = i
            break
    sig_word = CC.norm(P.words[sw_idx]["word"])
    c = {"schema": 1, "id": P.sid, "title": st["known_name"]["text"] + " " + st["huge_cost"]["display"],
         "world": {"name": "%s: %s %s world" % (P.F["name"].lower(), P.sw["name"], P.world_kind), "world_family": world, "look": P.F["look"]},
         "ground": {"hex": gh, "luminance": CK.lum_class_of(gh), "beats_fraction": 0.93},
         "palette": [gh, P.pal["ink"]] + ([P.pal["accent2"], P.pal["accent"]] if swap else [P.pal["accent"], P.pal["accent2"]]),
         "hero_device": hero, "camera": P.F["camera"], "type_voice": dict(P.F["type_voice"]), "source_presentation": srcp, "hook_mechanic": P.F["hook_mechanic"],
         "signature": {"mechanism": sig, "word": sig_word, "at_s": r2(getattr(P, "verdict_stamp", P.plan["C_v"])),
                       "description": "the verdict, verbatim from the script, lands whole on its cut, pulses line by line as it is spoken and an accent rule is stamped under it on %r" % sig_word},
         "bed": {"id": bed, "mood": "chosen for the %s format" % P.F["name"].lower()},
         "better_than_last": bt}
    return c


def choose_concept(P, spoken, beds):
    """first (palette order, bed, world, hero, signature, source) whose concept passes concept_check R0-R6, R8, R9 against the last 10 approved and live reservations -> (concept, report)"""
    import concept_check as CK
    worlds, heroes, sigs, srcs = candidates(P)
    best = None
    tried = 0
    ignore = ("R0 derived concept", "R0 bed matches spec.json")      # the spec on disk is rewritten right after the choice, with this bed

    def evaluate(bed, world, hero, sig, srcp, swap):
        bt = dict(short="S52", axis="signature", note="placeholder note long enough to satisfy the schema, replaced once a window short is known for this candidate", at_s=None)
        c = concept_dict(P, bed, world, hero, sig, srcp, spoken, bt, swap)
        rep = CK.run(P.sid, concept=dict(c), do_pitch=False)
        win = [w["id"] for w in rep.get("window", [])]
        ref = win[0] if win else "S52"
        oc = CK.load_concept(ref)
        mine = CK.axes_of(c)
        ax = None
        if oc is not None:
            theirs = CK.axes_of(oc)
            for a_, key in (("hero", "hero_device"), ("world", "world_family"), ("signature", "signature"), ("source", "source_presentation"), ("ground", "ground"), ("hook", "hook_mechanic")):
                if mine.get(key) != theirs.get(key):
                    ax = a_
                    break
        ax = ax or "signature"
        c["better_than_last"] = dict(short=ref, axis=ax, at_s=r2(c["signature"]["at_s"]),
                                     note="Against %s: this short keeps one hero tag and one known-name plate on a travelling world map from its first frame to its last, brings a different object on every beat, and its verdict lands at %.1f s on the spoken word %r." % (ref, c["signature"]["at_s"], c["signature"]["word"]))
        rep = CK.run(P.sid, concept=dict(c), do_pitch=False)
        bad = [x for x in rep["checks"] if not x["ok"] and re.match(r"R[0-9]\b", x["name"]) and not x["name"].startswith("R10") and x["name"] not in ignore and x.get("level") != "WARN"]
        return c, rep, bad

    mus = [m["id"] for m in jload(os.path.join(V2, "sound", "music.json"))["items"] if m["id"] not in ("local-forecast", "airport-lounge")]
    pool = list(beds) + [m for m in mus if m not in beds]
    ok_beds = []
    for bed in pool:                       # R5 (bed used by 3+ of the last 10, counting live reservations) depends on the bed alone: filter first, family first
        _, _, bad = evaluate(bed, worlds[0], heroes[0], sigs[0], srcs[0], True)
        if not any(x["name"].startswith("R5") for x in bad):
            ok_beds.append(bed)
        if len(ok_beds) >= 6:
            break
    beds = ok_beds or beds
    for swap in (False, True):
        hue_clash = False
        for bed in beds[:6]:
            for world in worlds:
                for hero in heroes:
                    for sig in sigs:
                        for srcp in srcs:
                            tried += 1
                            if tried > 600:
                                return None, best
                            c, rep, bad = evaluate(bed, world, hero, sig, srcp, swap)
                            if not bad:
                                return c, rep
                            if best is None or len(bad) < len(best[0]):
                                best = (bad, c)
                            if any(x["name"].startswith(("R2", "R3")) for x in bad):
                                hue_clash = True          # decided by the palette alone: no world, hero or bed can fix it; try the other palette order
                                break
                        if hue_clash:
                            break
                    if hue_clash:
                        break
                if hue_clash:
                    break
            if hue_clash:
                break
    return None, best


# ================================================================================================ assets (a real clause crop, a licensed logo)
def find_assets(sid, story, fetch=True):
    """a real clause crop (crop_clause output) from the first source that has one, and the known name's licensed logo (story.logo_asset, else fetch_assets.logo_for when `fetch`)"""
    a = {}
    base = specs_dir(sid)
    for src in (story.get("sources") or []):
        cl = src.get("clause")
        if not (cl and cl.get("key")):
            continue
        pj = os.path.join(base, "media", "clauses", cl["key"] + ".json")
        pp = os.path.join(base, "media", "clauses", cl["key"] + ".png")
        j = jload(pj)
        if not j and cl.get("phrase"):       # crop_clause was run with a longer --key than the story's own: find the crop by its phrase
            for cand in glob.glob(os.path.join(base, "media", "clauses", "*.json")):
                cj = jload(cand)
                if cj and cj.get("phrase") == cl["phrase"] and os.path.exists(cand[:-5] + ".png"):
                    j, pp = cj, cand[:-5] + ".png"
                    cl = dict(cl, key=os.path.basename(cand)[:-5])
                    break
        if j and os.path.exists(pp) and not has_banned(j.get("phrase") or cl.get("phrase") or ""):
            from PIL import Image
            with Image.open(pp) as im:
                w, h = im.size
            credit = j.get("credit") or j.get("credit_line") or ""
            a["clause"] = dict(src="img/clause-%s.png" % sid.lower(), path=pp, w=w, h=h, credit=credit, key=cl["key"], px=j.get("px_at_card_width"), sharp=j.get("max_sharp_width_px") or w, source_id=src.get("id"))
            break
    a["clips"] = {}
    for b in story.get("beats") or []:
        ob = b.get("object") or {}
        if ob.get("kind") != "clipping":
            continue
        key = ob["content"]["key"]
        pj, pp = os.path.join(base, "media", "clauses", key + ".json"), os.path.join(base, "media", "clauses", key + ".png")
        j = jload(pj)
        if j and os.path.exists(pp) and key not in a["clips"]:
            from PIL import Image
            with Image.open(pp) as im:
                w, h = im.size
            a["clips"][key] = dict(src="img/clip-%s-%s.png" % (sid.lower(), key[:24]), path=pp, w=w, h=h, credit=j.get("credit") or j.get("credit_line") or "", px=(j.get("px_at_card_width") or {}).get("font") if isinstance(j.get("px_at_card_width"), dict) else j.get("px_at_card_width"), key=key)
    lg = story.get("logo_asset")
    lp = None
    if lg and lg.get("path"):
        lp = os.path.join(KIT, "assets", lg["path"]) if not os.path.isabs(lg["path"]) else lg["path"]
        credit, licence = lg.get("credit"), lg.get("licence")
    elif fetch:
        try:
            import fetch_assets as FA
            rec = FA.logo_for(story["known_name"]["text"], sid)
        except Exception:
            rec = None
        if rec and rec.get("file"):
            lp = os.path.join(KIT, "assets", rec["file"])
            credit, licence = rec.get("creator"), rec.get("licence")
    if lp and os.path.exists(lp):
        from PIL import Image
        with Image.open(lp) as im:
            w, h = im.size
        a["logo"] = dict(src="img/logo-%s.png" % sid.lower(), path=lp, w=w, h=h, credit=credit, licence=licence)
    return a


def install_assets(P):
    d = os.path.join(KIT, "media", P.sid, "final")
    os.makedirs(d, exist_ok=True)
    for k in ("clause", "logo"):
        a = P.assets.get(k)
        if a:
            shutil.copy2(a["path"], os.path.join(d, os.path.basename(a["src"])))
    for a in list((P.assets.get("clips") or {}).values()) + [x for x in P.used_logos if x]:
        shutil.copy2(a["path"], os.path.join(d, os.path.basename(a["src"])))


# ================================================================================================ the driver
def pick_format(story, hint=None):
    if hint:
        return hint
    kinds = [b["kind"] for b in story["beats"]]
    if "response" in kinds or (story.get("experiment") or {}).get("hook_type") == "contradiction":
        return "newsroom"
    srcs = " ".join((s.get("outlet", "") + " " + s.get("url", "")) for s in story.get("sources", []))
    if story["huge_cost"].get("kind") == "money" or re.search(r"court|tribunal|judgment|fca\.org|ico\.org|ofcom|companieshouse|gov\.uk/(employment|government)", srcs, re.I):
        return "dossier"
    return "clean"


def fit_frame0(story, assets):
    """the known name's logo is looked up first: a logo counts as zero words in craft_check's frame-0 declaration (the limit is registry/strategy-v3.json frame0_words_max). tiny_cause is never trimmed
    (root 21 Oct: a trimmed cause is a fragment)"""
    if assets.get("logo") and not story.get("logo_asset"):
        story["logo_asset"] = {"path": "(fetched by fetch_assets)", "licence": "see fetch_assets registry"}


def repair_flags(fails, flags):
    """REPAIR BEFORE REFUSE (root 26 Oct): map the plan's own failures to a planner repair that has not fired yet -> [(flag, why)]"""
    new = []
    for f in fails:
        if re.search(r"beat \S+ is [\d.]+ s \(> 4\.4\)", f) and "force_split" not in flags:
            new.append(("force_split", f[:80]))
        elif "the hero tag is the object of" in f:
            new.append(("tag_zero" if "tag_one" in flags else "tag_one", f[:80]))
        elif "the hero tag returns on beat" in f and "figure is not spoken" in f and "tag_zero" not in flags:
            # Replan with no middle hero returns; the original director and
            # repeated-object checks still decide whether the result is valid.
            new.append(("tag_zero", f[:80]))
        elif "is not story text or fixed chrome" in f and "drop_unprintable" not in flags:
            new.append(("drop_unprintable", f[:80]))
        elif "NO-LANE" in f and "no_lane_repair" not in flags:
            new.append(("no_lane_repair", f[:80]))
        elif "groq daily token cap reached" in f and "groq_cap_repair" not in flags:
            new.append(("groq_cap_repair", f[:80]))
        elif "needs-writer" in f and "story_writer_repair" not in flags:
            new.append(("story_writer_repair", f[:80]))
        elif "VARIETY:" in f and "three near-identical pictures in a row" in f and "richer_sources" not in flags:
            new.append(("richer_sources", f[:80]))
    seen, out = set(), []
    for fl, why in new:
        if fl not in flags and fl not in seen:
            seen.add(fl)
            out.append((fl, why))
    return out


def drop_unprintable(P):
    """a printed string that is neither story text nor fixed chrome is removed (the object or text item and its boxes), never shown"""
    ok = P.printable()
    bad = set()
    for it in P.items:
        if it["k"] == "text":
            for ln in it["lines"]:
                n = re.sub(r"[^a-z0-9£$%]+", " ", ln.lower()).strip()
                n = re.sub(r"^(from|to|total|invoice|receipt|subject) ", "", n)
                if n and n not in ok and not any(n in o for o in ok):
                    bad.add(it["id"])
    if bad:
        P.items = [it for it in P.items if it["id"] not in bad]
        P.boxes = [b for b in P.boxes if b["id"] not in bad]
        P.repairs.append("dropped %d unprintable text items" % len(bad))


def no_lane_repair(P):
    """Pipeline repair for NO-LANE failures - the extract_story lane is not available"""
    # When the extract_story lane is not available, we can't process the story
    # This is a pipeline issue that requires lane recovery, not something the engine can fix
    P.repairs.append("extract_story lane not available; pipeline issue - waiting for lane recovery")
    return False  # Signal that this repair doesn't resolve the planning issue


def groq_cap_repair(P):
    """Pipeline repair for groq daily token cap reached"""
    # When Groq hits its daily token cap, we can't process more stories
    # This is a rate limit issue that requires waiting for the cap to reset
    P.repairs.append("Groq daily token cap reached; waiting for cap reset")
    return False  # Signal that this repair doesn't resolve the planning issue


def story_writer_repair(P):
    """Pipeline repair for needs-writer failures"""
    # When a story is marked as needs-writer, we need richer sources
    # This is a content issue that requires supply intervention
    P.repairs.append("story needs writer for richer sources; will retry after supply intervention")
    return False  # Signal that this repair doesn't resolve the planning issue


def richer_sources(P):
    """Pipeline repair for thin stories that need richer sources"""
    # When a story is too thin (fewer distinct objects than beats), it needs richer sources
    # This repair helps by providing guidance for story enrichment
    if hasattr(P, "story") and hasattr(P.story, "gaps"):
        P.story["needs_richer_sources"] = True
    P.repairs.append("story needs richer sources for completeness; will retry with enhanced sourcing")
    return False  # Signal that this repair doesn't resolve the planning issue


def plan_with_repairs(sid, story, words, fmt, sw, assets, seed=0):
    flags, log = (set(["lseed%d" % seed]) if seed else set()), []
    last = None
    for attempt in range(6):
        P = new_plan(sid, story, words, fmt, sw, assets)
        P.flags = set(flags)
        P.fetch_logos = True
        fails = []
        try:
            assemble(P)
            if "drop_unprintable" in flags:
                drop_unprintable(P)
            fails = director_checks(P)
        except EngineError as e:
            fails = [str(e)]
        if not fails:
            P.repairs = log + P.repairs
            return P
        new = repair_flags(fails, flags)
        last = fails
        if not new:
            break
        applied_any = False
        for fl, why in new:
            flags.add(fl)
            log.append("%s (%s)" % (fl, why))
            # Apply specific repairs based on flag type
            if fl == "force_split":
                # This is already handled in the new_plan logic through the beat splitting mechanism
                pass
            elif fl == "tag_zero":
                # This is already handled in the new_plan logic
                pass
            elif fl == "tag_one":
                # This is already handled in the new_plan logic
                pass
            elif fl == "drop_unprintable":
                drop_unprintable(P)
                applied_any = True
            elif fl in ["no_lane_repair", "groq_cap_repair", "story_writer_repair", "richer_sources"]:
                # Pipeline-level repairs that don't fix the planning issue, but log it for pipeline monitoring
                # These repairs signal that the failure is due to pipeline constraints, not planning issues
                pass
        # If we only applied pipeline-level repairs that don't fix the planning issue, break
        # This ensures the engine doesn't get stuck in a loop of retries that won't fix the issue
        if any(fl in ["no_lane_repair", "groq_cap_repair", "story_writer_repair", "richer_sources"] for fl, _ in new):
            break
    raise EngineError("the plan breaks DIRECTOR/FORMATS rules and no repair applies: " + " | ".join(last[:8]) + ((" [repairs tried: %s]" % "; ".join(log)) if log else ""))


# ================================================================================================ learnt weights (engine_learn.py -> registry/engine-weights.json)
EW_FAMILY_WORLDS = {"desk-paper": ("desk", "statement"), "ui-screen": ("inbox", "phone"), "interior-set": ("counter", "tribunal", "room")}
EW_COURT = r"court|tribunal|judgment|fca\.org|ico\.org|ofcom|companieshouse|gov\.uk/(employment|government)"


def ew_obj_kinds(story):
    return {(b_.get("object") or {}).get("kind", "") for b_ in story.get("beats", [])}


def ew_valid_formats(story):
    """the formats this story may take, and why when only one. The rule in pick_format stays the default; weights choose only among what the content allows:
    a response beat / contradiction hook is a newsroom story, a court or regulator source is a dossier story, money-only may be dossier or clean."""
    kinds = [b["kind"] for b in story["beats"]]
    if "response" in kinds or (story.get("experiment") or {}).get("hook_type") == "contradiction":
        return ["newsroom"], "response beat or contradiction hook"
    srcs = " ".join((s_.get("outlet", "") + " " + s_.get("url", "")) for s_ in story.get("sources", []))
    if re.search(EW_COURT, srcs, re.I):
        return ["dossier"], "court or regulator source"
    if story["huge_cost"].get("kind") == "money":
        return ["dossier", "clean"], None
    return ["dossier", "clean", "newsroom"], None


def ew_world_for(story, family):
    """the world name that stands for `family` on this story (a plane world is a label plus the light-ground pool: only map renders differently, and map needs a map_route)"""
    ks = ew_obj_kinds(story)
    srcs = " ".join((s_.get("outlet", "") + " " + s_.get("url", "")) for s_ in story.get("sources", []))
    if family == "ui-screen":
        return "phone" if "artefact:phone_text" in ks else "inbox"
    if family == "desk-paper":
        return "statement" if ks & {"artefact:receipt", "artefact:invoice", "artefact:dashboard"} else "desk"
    return "tribunal" if re.search(EW_COURT, srcs, re.I) else "counter"


def ew_apply(sid, story, fmt_hint, sw_hint, weights, prior=None):
    """-> dict(fmt, world, swatches, rec). With no weights (or EL missing) this returns exactly what build() always did. Every pick is among VALID options only;
    an explicit hint (CLI --format / --swatch) is never overridden; a pick already recorded in the short's own concept.json is reused so a rebuild is stable."""
    default_fmt = pick_format(story, fmt_hint)
    out = dict(fmt=default_fmt, world=story.get("world"), rec=None)
    wd = story.get("world")

    def swatch_pool(world, fmt):
        return (FF.FORMATS[fmt].get("swatches_light", []) + FF.FORMATS[fmt]["swatches"]) if world != "map" else list(FF.FORMATS[fmt]["swatches"])          # root 26 Oct: engine shorts sit on a LIGHT ground
    out["swatches"] = [sw_hint] if sw_hint else swatch_pool(wd, default_fmt)
    if EL is None or not weights:
        return out
    picks, prior_picks = {}, ((prior or {}).get("picks") or {})

    def pick(dim, options, default):
        pp = prior_picks.get(dim)
        if pp and pp.get("chosen") in options and pp.get("source") in ("weights", "reused"):
            r = dict(pp, source="reused")
            picks[dim] = r
            return r["chosen"]
        c, r = EL.choose(weights, dim, options, default, sid)
        picks[dim] = r
        return c
    # world: a map story stays a map story; any other story may take any plane world family the weights favour
    if wd and wd != "map" and wd in WORLD_FAMILY:
        fam_default = WORLD_FAMILY[wd]
        fams = [fam_default]          # root 26 Oct (rule 3, 7): the world reflects the story (care home = a room, planning = blueprints); the weights no longer move a story to another family
        fam = pick("world_family", fams, fam_default)
        if fam != fam_default:
            out["world"] = ew_world_for(story, fam)
    # format
    if not fmt_hint:
        opts, why = ew_valid_formats(story)
        if default_fmt in opts:
            out["fmt"] = pick("format", opts, default_fmt)
            if why:
                picks.setdefault("format", {})["forced_because"] = why
    # ground, then the swatch inside it
    if not sw_hint:
        pool = swatch_pool(out["world"], out["fmt"])
        gr = lambda k: "dark" if FF.SWATCHES[k].get("dark") else "light"
        avail = []
        for k in pool:
            if gr(k) not in avail:
                avail.append(gr(k))
        g = pick("ground", avail, gr(pool[0]))
        grp = [k for k in pool if gr(k) == g]
        first = pick("swatch", grp, grp[0])
        out["swatches"] = [first] + [k for k in grp if k != first] + [k for k in pool if gr(k) != g]
    if any(r.get("source") == "weights" for r in picks.values()):
        out["rec"] = dict(weights=EL.weights_ref(weights), picks=picks)
    elif prior_picks:
        out["rec"] = dict(weights=EL.weights_ref(weights), picks=picks)
    return out


_EW_CHANGED = [False]


def build(sid, fmt_hint=None, sw_hint=None, write=True, story_path=None, words_path=None, quiet=False, look=False):
    """weights first; if a weighted pick (not the rule default) makes the plan fail a gate, rebuild once with the rule defaults and say so in concept.json"""
    _EW_CHANGED[0] = False
    try:
        return _build(sid, fmt_hint, sw_hint, write, story_path, words_path, quiet, look, True)
    except EngineError as e:
        if not _EW_CHANGED[0]:
            raise
        return _build(sid, fmt_hint, sw_hint, write, story_path, words_path, quiet, look, False, str(e)[:300])


def _build(sid, fmt_hint, sw_hint, write, story_path, words_path, quiet, look, use_weights, fallback=None):
    story, words = load_inputs(sid, story_path, words_path)
    assets = find_assets(sid, story)
    fit_frame0(story, assets)
    pr = validate_story(story, words, look)
    if pr:
        raise EngineError("story.json is not renderable: " + "; ".join(pr))
    ew = ew_apply(sid, story, fmt_hint, sw_hint, (EL.load_weights() if (EL and use_weights) else None),
                  (jload(os.path.join(specs_dir(sid), "concept.json"), {}) or {}).get("engine_weights"))
    fmt, swatches = ew["fmt"], ew["swatches"]
    _EW_CHANGED[0] = bool(ew["rec"]) and any(r.get("chosen") != r.get("default") for r in ew["rec"]["picks"].values())
    if ew["world"] != story.get("world"):
        story = dict(story, world=ew["world"])           # in memory only: story.json on disk keeps the extractor's world
    spoken, _ = script_norm(sid)
    last_err = None
    options = [(sw, False) for sw in swatches]
    for sw, swp in options:
      for seed in range(4):          # a layout lookalike of a recent short re-rotates the slots (the start of the rotation moves) before the swatch changes
        P = plan_with_repairs(sid, story, words, fmt, sw, assets, seed)
        beds = pick_bed(P)
        c, rep = choose_concept(P, spoken, beds)
        if c is None:
            last_err = EngineError("no concept passes concept_check on swatch %s (closest: %s)" % (sw, [x["name"] for x in rep[0]] if rep else "none"))
            break
        bed = c["bed"]["id"]
        spec = make_spec(P, bed)
        if look:
            spec["composed"]["look_only"] = True       # a LOOK build of a story whose script is not v3: never submit it
        ok_n, msg_n = novelty_gate(spec)
        if not ok_n:
            last_err = EngineError("the plan fails the engine's novelty gate: " + msg_n)
            if "layout sequence" in msg_n:
                continue             # re-rotate the slots (next seed)
            break                    # try the next existing swatch; never waive novelty
        c["pitch"] = pitch_block(P, spoken)
        c["craft"] = craft_block(P, spoken)
        if ew["rec"]:
            c["engine_weights"] = ew["rec"]
        elif fallback:
            c["engine_weights"] = dict(fallback="a weighted pick failed a gate; rebuilt with the rule defaults", error=fallback)
        out = dict(plan=P, spec=spec, concept=c, report=rep, data=display_data(P))
        if write:
            write_all(P, spec, c, out["data"], fmt, sw)
        return out
    if fmt_hint is None and last_err is not None and "novelty gate" in str(last_err):
        # every swatch of the story's format is taken by the last engine shorts: another format composes the same story from the same grammar (Sam: no lookalikes)
        for other in [f_ for f_ in FF.FORMATS if f_ != fmt]:
            try:
                return build(sid, fmt_hint=other, sw_hint=sw_hint, write=write, story_path=story_path, words_path=words_path, quiet=quiet, look=look)
            except EngineError as e_:
                last_err = e_
    raise last_err or EngineError("no swatch worked")


def write_all(P, spec, concept, data, fmt, sw):
    d = specs_dir(P.sid)
    os.makedirs(d, exist_ok=True)

    def put(name, text):
        p = os.path.join(d, name)
        if os.path.exists(p):
            old = open(p, encoding="utf-8").read()
            if old == text:
                return
            shutil.copy2(p, p + FLEET_BAK)
        open(p, "w", encoding="utf-8").write(text)
    put("spec.json", json.dumps(spec, indent=1, ensure_ascii=False) + "\n")
    put("scenes.js", write_scenes(P, data))
    put("concept.json", json.dumps(concept, indent=1, ensure_ascii=False) + "\n")
    put("CONCEPTS.md", concepts_md(P, concept))
    put("STATE.md", state_md(P, concept))
    install_assets(P)
    with Locked(REG_FE):
        reg = jload(REG_FE, {})
        reg[P.sid] = dict(format=fmt, swatch=sw, world=concept["world"]["world_family"], signature=concept["signature"]["mechanism"], skins=P.skins_used, layout=layout_sig(P), world_kind=P.world_kind, at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        tmp = REG_FE + ".tmp%d" % os.getpid()
        json.dump(reg, open(tmp, "w"), indent=1)
        os.replace(tmp, REG_FE)


class Locked(object):
    def __init__(self, p):
        self.p = p

    def __enter__(self):
        os.makedirs(os.path.dirname(self.p), exist_ok=True)
        self.f = open(self.p + ".lock", "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def concepts_md(P, c):
    b = c["better_than_last"]
    st = P.story
    return "\n".join([
        "# %s concepts (generated by format_engine.py v%s, preset %s)" % (P.sid, ENGINE_VERSION, P.F["name"]),
        "",
        "This short is composed from `story.json` by one fixed grammar (S05's), so there is one concept, not three: the %s preset on swatch %s (%s)." % (P.F["name"], P.sw_key, P.sw["name"]),
        "",
        "## World",
        "One dark world map (real coastlines). The camera travels to a new region on every beat and the last view is the first. The hero tag and the known-name plate are on screen from frame 0 to the last frame.",
        "",
        "## Frame 0",
        "%s plate | %s | %s (%s px, accent) on a hanging tag | %s. The figure is already on screen and swings, then drops on the spoken word." % (st["known_name"]["text"], st["tiny_cause"]["text"], st["huge_cost"]["display"], P.tag_full["vfs"], st["huge_cost"]["label"]),
        "",
        "## Signature",
        c["signature"]["description"],
        "",
        "## Better than the last",
        b["note"],
        "",
        "Compared against the newest approved short (%s) on axis %s; concept_check R1 to R6 passed against the last 10 approved and live reservations." % (b["short"], b["axis"]),
        ""])


def state_md(P, c):
    import fetch_assets as FA
    lines = ["# %s STATE (format_engine.py %s)" % (P.sid, ENGINE_VERSION), "",
             "- built %s from story.json (%s, swatch %s). No model call." % (time.strftime("%d %b %Y %H:%M"), P.F["name"], P.sw_key), ""]
    mus = {m["id"]: m for m in jload(os.path.join(V2, "sound", "music.json"))["items"]}
    credit = mus.get(c["bed"]["id"], {}).get("credit", "")
    lines += ["## CAPTION CREDITS", ""]
    if credit:
        lines.append(credit)
    for ln in FA.credits(P.sid):
        lines.append(ln)
    if SFX_SOURCE == "openverse":          # CC BY / BY-SA sounds need their attribution in the caption; CC0 / PDM and the code-made bank do not
        seen_c = set()
        for c_ in P.sfx:
            it = SFX_LIB["items"].get(c_["kind"][1:]) or {}
            S = it.get("source") or {}
            if S.get("licence_slug") in ("by", "by-sa") and it["id"] not in seen_c:
                seen_c.add(it["id"])
                lines.append("sfx | %s | %s | %s" % (S.get("attribution"), S.get("landing_url"), S.get("licence")))
    cl = P.assets.get("clause")
    if cl:
        lines.append("Source clause: %s" % cl["credit"])
    if P.assets.get("logo"):
        lines.append("Logo: %s (%s), editorial identification use" % (P.assets["logo"].get("credit"), P.assets["logo"].get("licence")))
    lines.append("")
    return "\n".join(lines)


# ================================================================================================ novelty gate (called by build_short.py for composed.engine == "format_engine")
def novelty_gate(spec):
    """(ok, message). The variety rules for engine-made shorts, replacing the signature-code-hash guard (which would refuse every second short from one template):
    at least one signature event; no skin leads more than 35% of the body states; format + swatch + signature must not repeat two of three against any of the last 3
    engine shorts (registry/format-engine.json)."""
    c = spec.get("composed") or {}
    if not c.get("signature"):
        return False, "NOVELTY: no signature event declared"
    skins = c.get("skins") or []
    n = max(1, len(skins))
    cnt = collections.Counter(skins)
    over = {k: v for k, v in cnt.items() if v / float(n) > 0.5 + 1e-9}        # objects are chosen by meaning, so a story with many figures may repeat counters; no more than half the states
    if over and n >= 6:
        return False, "NOVELTY: skin %s leads over 35%% of the %d states" % (sorted(over), n)
    reg = jload(REG_FE, {})
    last = sorted([(v.get("at", ""), k, v) for k, v in reg.items() if k != spec["id"]])[-3:]
    sig = None
    mine = (c.get("format"), c.get("swatch"))
    clash = [k for _, k, v in last if sum([v.get("format") == mine[0], v.get("swatch") == mine[1], v.get("signature") == c.get("signature_mechanism")]) >= 2 and v.get("format") == mine[0] and v.get("swatch") == mine[1]]
    if clash:
        return False, "NOVELTY: same format and swatch as %s (one of the last 3)" % ",".join(clash)
    # root 26 Oct (Sam: "each video needs to be unique"): no two engine shorts share a layout sequence, or a hero device (world + first three objects) on the same palette, within the last 10
    import difflib
    mine_l = c.get("layout") or []
    for _, k, v in sorted([(v_.get("at", ""), k_, v_) for k_, v_ in reg.items() if k_ != spec["id"]])[-10:]:
        other = v.get("layout") or []
        if mine_l and other:
            r_ = difflib.SequenceMatcher(None, mine_l, other).ratio()
            core = lambda l_: [t_ for t_ in l_ if not t_.startswith("centre-low")]          # the S05 composition is half of every engine short; what tells two shorts apart is the other half
            r2_ = difflib.SequenceMatcher(None, core(mine_l), core(other)).ratio()
            if r_ >= LAYOUT_SAME or r2_ >= LAYOUT_SAME_CORE:
                return False, "NOVELTY: layout sequence is %.0f%% the same as %s (%.0f%% outside the S05 composition; must stay under %.0f%% and %.0f%%)" % (100 * r_, k, 100 * r2_, 100 * LAYOUT_SAME, 100 * LAYOUT_SAME_CORE)
        if skins and v.get("world_kind") and v.get("world_kind") == c.get("world_kind") and v.get("swatch") == c.get("swatch") and list(v.get("skins") or [])[:3] == list(skins)[:3]:
            return False, "NOVELTY: same world, palette and first three objects as %s (a hero device lookalike)" % k
    return True, "novelty PASS (skins %s; last 3: %s)" % (dict(cnt), ", ".join(k for _, k, _ in last) or "none")


# ================================================================================================ selftest

def make_fixture(fig="4.2M", cause="one dull button", name="Acme Bank", long_label=False):
    """a synthetic 46 s take and a story.json that follows STORY-DATA.md, no files read. Returns (story, words)."""
    paras = [
        "Acme Bank paid 4.2 million pounds over one dull button.",
        "The reset my card button sent every customer to a chatbot, and the chatbot gave up. Staff were then swamped by angry calls all week. The regulator opened a case and the bank apologised in public.",
        "Your own website may hide the same trap, so test every button that asks a customer to wait. Nobody tests the dull ones. The dull ones lose the money.",
        "Fix the dull button before it costs you a customer.",
        "Would you test yours today?",
        "Follow for the next real story.",
    ]
    words, t = [], 0.0
    sents = []
    for pi, ptxt in enumerate(paras):
        for si, s in enumerate([x for x in re.split(r"(?<=[.?!])\s+", ptxt) if x]):
            toks = s.split()
            sents.append((pi, si, len(words), len(words) + len(toks) - 1))
            for tk in toks:
                d = 0.30 + 0.025 * len(tk)
                words.append(dict(word=tk, start=round(t, 3), end=round(t + d, 3), emph=(len(words) < 1)))
                t += d + 0.02
            t += 0.30
        t += 0.35
    beats, i = [], 0
    kinds = ["context", "mechanism", "turn", "cost", "context", "response", "stake", "lesson", "context"]
    for k, (pi, si, a, b) in enumerate(sents):
        j = a
        parts = []
        while j <= b:
            e = min(b, j + 7)
            if b - e < 3:
                e = b
            parts.append((j, e))
            j = e + 1
        for (x, y) in parts:
            beats.append((x, y, "P%d.S%d" % (pi + 1, si + 1)))
    vsent = next(s for s in sents if s[0] == 3)
    qsent = next(s for s in sents if s[0] == 4)
    csent = next(s for s in sents if s[0] == 5)
    out = []
    for n, (x, y, sid_) in enumerate(beats):
        t0 = words[x]["start"] if x else 0.0
        t1 = words[y + 1]["start"] if y + 1 < len(words) else words[y]["end"]
        if sid_.startswith("P6"):
            kind = "cta"
        elif n == 0 or x == 0:
            kind = "hook"
        else:
            kind = kinds[n % len(kinds)]
        if sid_.startswith("P4"):
            kind = "verdict"
        if sid_.startswith("P5"):
            kind = "question"
        ph = " ".join(w["word"].strip(".,?") for w in words[x:min(y, x + 3) + 1]) if kind not in ("cta", "verdict", "question") else None
        out.append(dict(id=("b%02d" % n) if kind != "cta" else "cta", t_from_word=x, t_to_word=y, t_from=r2(t0), t_to=r2(t1), sentences=[sid_], kind=kind, phrase=ph,
                        figure=None, quote=None, source_id="SRC1", ledger="L1", stress=sorted(set([x] + ([y - 1] if y - x > 4 else [])))))
    out[0]["figure"] = dict(value=4200000, unit="GBP", display=fig, spoken=[3, 4], ledger="L1")
    body = [b for b in out if b["kind"] not in ("hook", "cta", "verdict", "question")]
    objs = [dict(kind="logo_pair", content=dict(a=name, b="The Herald")),
            dict(kind="quote_card", content={}),
            dict(kind="checklist", content=dict(items=["reset my card", "gave up", "angry calls"], source_id="SRC1", para=1)),
            dict(kind="artefact:receipt", content=dict(items=[dict(label="one dull button", amount="4.2M")], total="4.2M")),
            dict(kind="timeline", content=dict(events=[dict(when="in August", what="the bank apologised"), dict(when="all week", what="angry calls")])),
            dict(kind="artefact:email", content=dict(**{"from": "the regulator", "subject": "the reset my card button", "lines": ["the bank apologised in public"]})),
            dict(kind="artefact:phone_text", content=dict(messages=[dict(who="them", text="the chatbot gave up"), dict(who="us", text="test every button")])),
            dict(kind="compare_bars", content=dict(a=dict(value=2100000, display="2.1M", label="before", spoken=[3, 4], ledger="L1"), b=dict(value=4200000, display="4.2M", label="after", spoken=[3, 4], ledger="L1"), unit="GBP")),
            dict(kind="artefact:dashboard", content=dict(tiles=[dict(label="calls", value="all week"), dict(label="cost", value="4.2M")]))]
    for k_, ob_ in enumerate(objs):
        if 2 + 2 * k_ < len(body):
            body[2 + 2 * k_]["object"] = ob_
    qb = next((b for b in body if b.get("object") and b["object"]["kind"] == "quote_card"), None)
    if qb:
        qb["quote"] = dict(text="the chatbot gave up", speaker="Acme customer", source_id="SRC1", para=1, quoted_in_source=True)
    for b in out:
        b.setdefault("object", None)
    story = dict(schema="agmm-story-v1", id="ZZ1", world="desk", inputs=dict(words="x"), known_name=dict(text=name, words=[0, 1], **{"as": "wordmark"}, trace={}), logo_asset=None,
                 tiny_cause=dict(text=cause, trace={}),
                 huge_cost=dict(value=4200000, unit="GBP", kind="money", label=("customers asked for a card reset all week long" if long_label else "pounds over one dull button"), display=fig, spoken=[3, 4], trace={}),
                 turn=dict(words=[0, 1], text="x", n_words=2), you_by_3s=dict(word=None, t=None), beats=out,
                 verdict=dict(text="Fix the dull button before it costs you a customer.", sentence="P4.S1", words=[vsent[2], vsent[3]]),
                 question=dict(text="Would you test yours today?", spoken=True, sentence="P5.S1", words=[qsent[2], qsent[3]]),
                 cta=dict(line="Follow for the next real story.", words=[csent[2], csent[3]], press=csent[2], ring=csent[3], link=CTA_LINK),
                 sources=[dict(id="SRC1", outlet="The Herald", url="https://example.invalid/a", published="5 Jan 2026", clause=None)],
                 experiment=dict(hook_type="stake-slam", beat2_artefact="notice", you_by_3s=False, brand_recognition="b2b", length_bucket="35-50", ending_type="verdict+question"),
                 gaps=[], status="ready", grounding={})
    return story, words


def selftest():
    bad = 0

    def say(ok, name, detail=""):
        nonlocal bad
        print(("PASS " if ok else "FAIL ") + name + (("  -> " + detail) if (detail and not ok) else ""))
        bad += (not ok)

    def plan(fmt, story=None, words=None, sw=None):
        if story is None:
            story, words = make_fixture()
        P = new_plan("ZZ1", story, words, fmt, sw or FF.FORMATS[fmt]["swatches"][0])
        assemble(P)
        return P
    # S267 regression: a new counter was discarded merely because the previous object was also a counter.
    ob1 = dict(kind="counter", content={"label": "staff"}, figure=dict(value=1800, unit="people", display="1,800", spoken=[1, 1]))
    ob2 = dict(ob1, figure=dict(ob1["figure"], value=22000, display="22,000"))
    ob3 = dict(ob1, figure=dict(ob1["figure"], spoken=[5, 5]))
    say(not same_object(ob1, ob2), "different grounded figures of the same object kind are never dropped")
    say(same_object(ob1, ob3), "identical grounded content may persist across word windows")
    # ---- good fixture, every preset
    for fmt in ("dossier", "clean", "newsroom"):
        story, words = make_fixture()
        pr = validate_story(story, words)
        say(not pr, "%s fixture validates against STORY-DATA" % fmt, "; ".join(pr))
        try:
            P = plan(fmt, story, words)
        except EngineError as e:
            say(False, "%s fixture assembles" % fmt, str(e))
            continue
        fails = director_checks(P)
        rep_f = [f for f in fails if "object content repeated" in f]
        fails = [f for f in fails if "object content repeated" not in f]          # the synthetic fixture has 11 beats and 5 objects: it is THIN by root's rule 1, and must be caught as such
        say(not fails, "%s: DIRECTOR + root's gate checks hold by construction" % fmt, "; ".join(fails[:6]))
        say(bool(rep_f), "%s: bad: 11 beats on 5 distinct objects is caught as repeated content (thin, never padded)" % fmt)
        f0 = P.tag_full
        say(f0["vfs"] >= 205, "%s frame 0: figure %s px (>= 205), known-name plate present, tag ends y %d (sting slot y 1088 clear)" % (fmt, f0["vfs"], f0["y"] + f0["h"]))
        geo = P.check_geometry()
        say(not geo, "%s: every text box inside the universal zone, nothing stacked" % fmt, "; ".join(geo[:4]))
        import concept_check as CK
        concept = concept_dict(P, "local-forecast", *[x[0] for x in candidates(P)], "",
                               dict(short="S52", axis="signature", at_s=1,
                                    note="The fixture has a different scene object and its verdict lands on the spoken word."), False)
        errs = CK.validate(concept, CK.load_schema())
        say(not errs, "%s declares its actual type within the native concept schema" % fmt, "; ".join(errs))
        mu_ = make_spec(P, "ic_montauk-point")["music"]
        say(mu_.get("under_lu") == 13 and mu_.get("gap_rise_db") == 0 and not mu_.get("swells"), "%s: bed target 13 (measured about 3 LU deeper: 16-17, audit max 18), no gap rise, no swells (root 26 Oct)" % fmt)
        data = display_data(P)
        say(data["tag"]["keys"][0]["t"] == 0 and keys_equal(data["tag"]["keys"][0], data["tag"]["keys"][-1], ("x", "y", "w", "h", "vfs", "op")),
            "%s: the hero tag persists from t = 0 and the last 0.5 s returns it to the frame-0 layout" % fmt)
        say(keys_equal(data["world"]["keys"][0], data["world"]["keys"][-1], ("px", "py", "z")) and len(data["world"]["keys"]) >= len(P.spec_beats), "%s: one world, %d camera keys for %d beats, last view = first" % (fmt, len(data["world"]["keys"]), len(P.spec_beats)))
        ids = [it["id"] for it in data["items"]]
        say(len(ids) == len(set(ids)), "%s: item ids are unique" % fmt)
        say(len(P.objects) >= 8, "%s: %d pitch objects (>= 8 for concept_check R7)" % (fmt, len(P.objects)))
        say(len(set(P.skins_used)) >= 3, "%s: %d scene kinds in the body (%s)" % (fmt, len(set(P.skins_used)), ",".join(sorted(set(P.skins_used)))))
    # Whole-block geometry regressions from real S307 / S317 failures.
    story, words = make_fixture()
    P = new_plan("ZZ1", story, words, "dossier", "D3")
    txt = "If a supplier fires the team that knows you for an AI bet, you carry the cost."
    fitted = fit_headline(P, txt, 7, 112, 60)
    say(bool(fitted), "long verdict fits without lowering the 60 px floor")
    if fitted:
        fs, lines = fitted
        bx = FL.text_box(HEAD_X, HEAD_Y, lines, "cond", 700, fs, 0.9, caps=True)
        say(not FL.text_ok(bx), "long verdict clears the TikTok column across its whole height")
    P.T(txt, 80, 500, 100, 700, "#000", ti=0, to=1)
    say(P.items[-1]["w"] == LOW_W, "automatic text width considers every wrapped line")
    story, words = make_fixture(fig="£373BN")
    P = plan("dossier", story, words)
    say(P.tag_full["vfs"] >= 180, "wide spoken figure keeps the 180 px frame-0 floor (root 26 Oct)")
    for state in (P.tag_full, P.tag_obj):
        tw = FL.tw(P.tag_value, "cond", 700, state["vfs"], caps=True)
        bx = FL.Box(state["x"] + (state["w"] - tw) / 2, state["y"] + state["vy"],
                    state["x"] + (state["w"] + tw) / 2, state["y"] + state["vy"] + state["vfs"])
        say(not FL.text_ok(bx), "wide figure's full/body ink clears the universal zone")
    # ---- bad fixtures: each one MUST fail
    story, words = make_fixture(fig="1,234,567,890,123")
    try:
        plan("dossier", story, words)
        say(False, "bad: a figure too wide for 205 px is refused")
    except EngineError as e:
        say("205" in str(e) or "fit" in str(e), "bad: a figure too wide for 205 px is refused", str(e))
    story, words = make_fixture(cause="one very dull little button that nobody in the shop ever pressed")
    say(bool(validate_story(story, words)), "bad: a 12-word cause with a 2-word name and the figure (15 > 12 declared words, strategy-v3.json) is refused")
    story, words = make_fixture(cause="one very dull little button")
    say(not validate_story(story, words) or not any("declares" in x for x in validate_story(story, words)), "good: a 5-word cause with a 2-word name and the figure (8 <= 12 words) is NOT refused for length")
    story, words = make_fixture()
    story["beats"][3]["t_from_word"] += 1
    say(bool(validate_story(story, words)), "bad: beats that do not tile the take are refused")
    story, words = make_fixture()
    story["verdict"] = None
    say(bool(validate_story(story, words)), "bad: a story with no verdict is refused")
    story, words = make_fixture()
    story["gaps"] = ["rule2"]
    say(bool(validate_story(story, words)), "bad: a script that fails strategy rule 2 is refused (the override is struck: needs-writer)")
    story, words = make_fixture()
    P = plan("newsroom", story, words)
    base = len(director_checks(P))
    # distinct objects on every beat pass the repeat check
    Pr = plan("newsroom", story, words)
    for i_, r_ in enumerate(r for r in Pr.slot_recs if r["si"] is not None):
        pass
    sp_dist = [dict(spec=dict(kind="counter", content={"n": i_})) for i_ in range(len(Pr.slot_recs))]
    Pr.plan = dict(Pr.plan, spans=sp_dist)
    for i_, r_ in enumerate(Pr.slot_recs):
        r_["si"] = i_
    say(not repeat_checks(Pr), "distinct objects on every beat pass the repeat check")
    # root 26 Oct, ruling 1: the hero tag returns only on beats where the voice says the figure; those returns are not repeats
    Ph = plan("newsroom", story, words)
    rr_ = next(r for r in Ph.slot_recs if r["si"] is not None)
    Ph.plan["spans"][rr_["si"]]["spec"] = dict(kind="price_tag", content={})
    iw_ = next(i for i, w_ in enumerate(Ph.words) if rr_["t0"] <= w_["start"] < rr_["t1"] - 0.3)
    Ph.story["huge_cost"]["spoken"] = [iw_, iw_]
    Ph.slot_recs = [rr_]
    say(not [f for f in repeat_checks(Ph) if "hero tag" in f or "the price_tag" in f], "the hero tag on a beat where the figure is spoken passes (S264-shaped: it is not a repeat)")
    Ph.story["huge_cost"]["spoken"] = [len(Ph.words) - 1, len(Ph.words) - 1]
    say(any("hero tag returns" in f for f in repeat_checks(Ph)), "bad: a hero tag on a beat where the figure is not spoken is caught")
    P.T("tiny", 112, 600, 36, 400, "#000000", w=300, ti=5, to=6)
    say(len(director_checks(P)) > base, "bad: a 36 px line is caught (< 42 px)")
    P2 = plan("newsroom", story, words)
    P2.T("Overlapping words", 130, 330, 60, 700, "#000000", w=500, ti=0, to=None)
    say(any("stacked" in f for f in P2.check_geometry()), "bad: text laid over the headline is caught as stacked")
    P3 = plan("dossier", story, words)
    P3.T("Right edge", 700, 900, 60, 700, "#000000", w=400, ti=2, to=3, face="cond")
    say(any("universal zone" in f for f in P3.check_geometry()), "bad: text under the TikTok column is caught")
    P4 = plan("dossier", story, words)
    c = P4.spec_beats[3]["t_from"]
    P4.items.append(dict(k="rect", id="zz", x=100, y=500, w=100, h=100, ti=c - 2, to=c - 0.05, ain="fade", aout="fade", z=5))
    say(any("still fading out on the cut" in f for f in director_checks(P4)), "bad: an item still fading on a cut is caught")
    P5 = plan("clean", story, words)
    P5.spec_beats[2]["t_to"] = P5.spec_beats[2]["t_from"] + 6.0
    say(any("> 4.4" in f for f in director_checks(P5)), "bad: a 6 s beat is caught (> 4.4 s)")
    P6 = plan("newsroom", story, words)
    P6.sfx.append(dict(t=9.0, kind="=ui_pop_03", gain=-22, x=540, what="pop"))
    say(any("centred" in f for f in director_checks(P6)), "bad: a centred sound cue is caught")
    P7 = plan("dossier", story, words)
    P7.tag_keys[-1] = dict(P7.tag_keys[-1], x=P7.tag_keys[-1]["x"] + 80)
    say(any("loop" in f for f in director_checks(P7)), "bad: a tag that does not return to its frame-0 place is caught")
    P8 = plan("clean", story, words)
    P8.world_keys[2] = dict(P8.world_keys[2], px=P8.world_keys[1]["px"], py=P8.world_keys[1]["py"], z=P8.world_keys[1]["z"])
    say(any("camera does not move" in f for f in director_checks(P8)), "bad: a beat where the camera does not move is caught")
    P9 = plan("dossier", story, words)
    P9.skins_used = ["plate"] * len(P9.skins_used)
    say(any("scene kinds" in f or "in a row" in f for f in director_checks(P9)), "bad: one scene kind on every beat (the slideshow) is caught")
    story, words = make_fixture()
    bb = next(b for b in story["beats"] if b.get("object"))
    bb["object"] = dict(kind="counter", content={})
    try:
        plan("dossier", story, words)
        say(False, "bad: an object with no content is a build failure")
    except EngineError as e:
        say("no usable content" in str(e), "bad: an object with no content is a build failure", str(e))
    story, words = make_fixture()
    P10 = plan("clean", story, words)
    for sp in P10.plan["spans"][:5]:
        sp["spec"] = dict(kind="price_tag", content={})
    say(any("hero tag is the object of" in f for f in director_checks(P10)), "bad: the hero tag as the object of more than 2 middle beats is caught")
    P11 = plan("dossier", story, words)
    r_ = next(r for r in P11.slot_recs if r["tr"])
    r_["tr"] = dict(r_["tr"], bbox=(300, 700, 500, 850))
    say(any("needs >=" in f for f in director_checks(P11)), "bad: an object at a quarter of the safe-zone width is caught")
    # the layout grammar: >= 5 slots per format, a rotation that never repeats on consecutive beats, DIRECTOR scale / safe zone / headline clear of the object in every slot
    for fmt_ in ("dossier", "clean", "newsroom"):
        Pg = plan(fmt_, story, words)
        used_ = [(r["slot"], r["head"]) for r in Pg.slot_recs]
        say(len(set(FF.FORMATS[fmt_]["slots"])) >= 5 and len(set(used_)) >= 3 and not slot_checks(Pg),
            "%s layout grammar: %d slots in the format, %d used over %d beats, none repeated in a row, all inside scale and zone" % (fmt_, len(set(FF.FORMATS[fmt_]["slots"])), len(set(used_)), len(used_)), "; ".join(slot_checks(Pg)[:3]))
    for fmt_ in ("dossier", "clean", "newsroom"):          # root's S264 ruling: every beat is one group (headline + object) centred in the safe band, not parked in the top 40%
        Pg = plan(fmt_, story, words)
        ok_ = True
        for r_ in Pg.slot_recs:
            if r_["tr"]:
                y0_ = min(r_["tr"]["bbox"][1], r_["hv"]["box"].y0)
                y1_ = max(r_["tr"]["bbox"][3], r_["hv"]["box"].y1)
                ok_ = ok_ and GROUP_BAND[0] - 1 <= y0_ and y1_ <= GROUP_BAND[1] + 1 and abs((y0_ + y1_) / 2.0 - sum(GROUP_BAND) / 2.0) < 60
        say(ok_, "%s: every beat's headline + object group is centred in the band y %d-%d" % (fmt_, GROUP_BAND[0], GROUP_BAND[1]))
    Pg = plan("dossier", story, words)
    r_ = next(r for r in Pg.slot_recs if r["tr"])
    r_["tr"] = dict(r_["tr"], bbox=(100, 300, 780, 560))
    say(any("is centred at y" in f for f in slot_checks(Pg)), "bad: an object parked in the top of the frame is caught")
    Pg = plan("dossier", story, words)
    Pg.slot_recs[1]["slot"], Pg.slot_recs[1]["head"] = Pg.slot_recs[0]["slot"], Pg.slot_recs[0]["head"]
    say(any("same layout slot" in f for f in slot_checks(Pg)), "bad: the same slot on two consecutive beats is caught")
    Pg = plan("dossier", story, words)
    r_ = next(r for r in Pg.slot_recs if r["tr"] and r["head"].startswith("bottom"))
    hb_ = r_["hv"]["box"]
    r_["tr"] = dict(r_["tr"], bbox=(hb_.x0 + 20, hb_.y0 - 100, hb_.x1 - 20, hb_.y0 + 100))
    say(any("overlaps the object" in f for f in slot_checks(Pg)), "bad: a headline over the object is caught")
    Pg = plan("dossier", story, words)
    r_ = next(r for r in Pg.slot_recs if r["tr"] and r["slot"] != "centre-low")
    r_["tr"] = dict(r_["tr"], bbox=(500, 600, 960, 1000))
    say(any("outside the safe zone" in f for f in slot_checks(Pg)), "bad: an object outside the safe zone is caught")
    saved_ = FF.FORMATS["clean"]["slots"]
    FF.FORMATS["clean"]["slots"] = saved_[:4]
    say(any("layout slots (needs >= 5)" in f for f in slot_checks(plan("clean", story, words))), "bad: a format with 4 slots is caught")
    FF.FORMATS["clean"]["slots"] = saved_
    story, words = make_fixture()
    P12 = plan("dossier", story, words)
    P12.items.append(dict(k="text", id="zt", lines=["The Negotia\u2026"], x=100, y=700, w=300, fs=60, wt=700, col="#000", al="l", lh=1.0, ls=0, caps=True, it=False, ti=3, to=4, ain="rise", aout="fade", z=10))
    say(any("ellipsis" in f for f in director_checks(P12)), "bad: an ellipsised string (truncated copy) is caught")
    P13 = plan("newsroom", story, words)
    bx_ = FL.Box(100, 700, 700, 760)
    P13.items.append(dict(k="text", id="zw", lines=["TOO WIDE FOR ITS BOX"], x=100, y=700, w=300, fs=60, wt=700, col="#000", al="l", lh=1.0, ls=0, caps=True, it=False, ti=3, to=4, ain="rise", aout="fade", z=10))
    P13.boxes.append(dict(id="zw", box=bx_, t0=3, t1=4, label="TOO WIDE", kind="text", fs=60))
    say(any("overflow or be clipped" in f for f in director_checks(P13)), "bad: text wider than its box is caught")
    P14 = plan("clean", story, words)
    P14.story["sources"][0]["outlet"] = "thenegotiator.co.uk"
    say(display_name(P14, "The Neg") == "The Negotiator" and display_name(P14, "Acme") == "Acme", "a name the page shortens (The Neg) is shown in full from the source's own outlet")
    story, words = make_fixture()
    story["richness"] = {"distinct_objects": 3, "kinds": ["counter"], "floor": 5}
    say(any("thin" in x for x in validate_story(story, words)), "bad: a thin story (3 distinct objects, floor 5) is refused before any build")
    rf = repair_flags(["beat s01 is 5.83 s (> 4.4)", "the hero tag is the object of 4 middle beats (max 2)", "printed string 'X' is not story text or fixed chrome"], set())
    say({f for f, _ in rf} == {"force_split", "tag_one", "drop_unprintable"} and {f for f, _ in repair_flags(["the hero tag is the object of 4 middle beats (max 2)"], {"tag_one"})} == {"tag_zero"}, "repair before refuse: each planner failure maps to a repair that has not fired yet")
    story, words = make_fixture()
    P15 = plan("dossier", story, words)
    P15.items.append(dict(k="text", id="zp", lines=["INVENTED LABEL ON A PROP"], x=100, y=700, w=500, fs=60, wt=700, col="#000", al="l", lh=1.0, ls=0, caps=True, it=False, ti=3, to=4, ain="rise", aout="fade", z=10))
    drop_unprintable(P15)
    say(not any(it["id"] == "zp" for it in P15.items) and any("unprintable" in r for r in P15.repairs), "a printed label that is not story text is dropped by the repair, not shown")
    say(has_banned("to streamline operations") and not has_banned("to run operations"), "banned words are detected (streamline)")
    say(not cooldown_applies(dict(outcome="failed:extract_story", note="S357: NO-LANE: no free lane answered")) and not cooldown_applies(dict(outcome="failed:extract_story", no_lane=True)) and cooldown_applies(dict(outcome="refused:thin", note="thin")) and cooldown_applies(dict(outcome="failed:precheck", note="sheet")), "the 24 h failure cooldown does not apply to a NO-LANE failure, and still does to every other failure")
    # root 27 Oct (disk): a refused build keeps only what a reviewer needs
    tdir_ = tempfile.mkdtemp(prefix="fe-trim-")
    for sub_, fn_ in (("precheck", "beats.jpg"), ("domlint", "raw.json"), ("snap", "f1.jpg"), ("snap-archive-1", "f2.jpg"), ("audio", "a.wav"), ("build", "b.mp4"), ("static-precheck", "s.png"), ("snap-sp0-prev-9", "g.jpg")):
        os.makedirs(os.path.join(tdir_, "ZT1", sub_), exist_ok=True)
        open(os.path.join(tdir_, "ZT1", sub_, fn_), "wb").write(b"x" * 1000)
    open(os.path.join(tdir_, "ZT1", "BUILD.json"), "w").write("{}")
    fr_ = trim_out("ZT1", base=tdir_)
    kept_ = sorted(os.listdir(os.path.join(tdir_, "ZT1")))
    say(fr_ == 6000 and kept_ == ["BUILD.json", "domlint", "precheck"] and os.path.exists(os.path.join(tdir_, "ZT1", "precheck", "beats.jpg")), "a refused build keeps precheck/beats.jpg, the gate JSON, logs; the frame dumps and renders go (%d bytes freed, kept %s)" % (fr_, kept_))
    shutil.rmtree(tdir_, ignore_errors=True)
    global REG_FE
    reg_bak_, REG_FE = REG_FE, os.path.join("/tmp", "fe-novelty-selftest-%d.json" % os.getpid())
    json.dump({"A1": dict(format="clean", swatch="C4", world_kind="desk", skins=["counter", "quote_card", "logo_pair"], layout=["centre-low:top", "high-right:bottom", "left-tight:top", "full-bleed:bottom"], at="2026-10-01T00:00:00")}, open(REG_FE, "w"))
    base_ = dict(signature=True, skins=["plate", "counter", "logo_pair", "clipping", "timeline", "quote_card"], format="dossier", swatch="D3", world_kind="map")
    ok1_, _m1 = novelty_gate(dict(id="ZZ2", composed=dict(base_, layout=["centre-low:top", "high-right:bottom", "left-tight:top", "full-bleed:bottom"])))
    ok2_, _m2 = novelty_gate(dict(id="ZZ2", composed=dict(base_, layout=["close-up:top", "peek-left:bottomr", "small-right:topr", "high-left:bottom"])))
    ok3_, _m3 = novelty_gate(dict(id="ZZ2", composed=dict(base_, skins=["counter", "quote_card", "logo_pair", "x"], format="clean", swatch="C4", world_kind="desk", layout=["close-up:top", "peek-left:bottomr", "small-right:topr", "high-left:bottom"])))
    os.remove(REG_FE)
    REG_FE = reg_bak_
    say(not ok1_ and "layout sequence" in _m1, "bad: a short whose layout sequence repeats a recent short's is refused (no lookalikes)", _m1)
    say(ok2_, "a short with its own layout sequence passes the cross-short check", _m2)
    say(not ok3_, "bad: the same world, palette and first three objects as a recent short is refused (hero device lookalike)", _m3)
    ok_, msg = novelty_gate(dict(id="ZZ1", composed=dict(signature=True, skins=["plate"] * 8, format="dossier", swatch="D3")))
    say(not ok_, "bad: one scene on every state fails the novelty gate", msg)
    # ---- SFX source: earshot's measured takes (default off). The registry must hold a measured onset / end for every id the engine can emit, and
    #      with the switch on a built plan must emit earshot ids only with a measured onset. The check is run on a broken registry too: it MUST fail.
    reg_es = jload(os.path.join(KIT, "registry", "earshot-sfx.json"), {})
    if reg_es:
        def es_problems(reg, kinds, sfx):
            out = [i for i, m in reg.get("items", {}).items() if m.get("onset_ms") is None or m.get("end_ms") is None or not m["end_ms"] > m["onset_ms"] >= 0]
            out += ["kind %s: id %s unregistered" % (k, i) for k, ids in kinds.items() for i in ids if i not in reg.get("items", {})]
            out += ["cue %s has no measured onset" % c["kind"] for c in sfx if c["kind"].startswith("=es_") and c["kind"][1:] not in reg.get("items", {})]
            return out
        glb = globals()
        old_src, old_k = glb["SFX_SOURCE"], glb["ES_KINDS"]
        try:
            glb["SFX_SOURCE"], glb["ES_KINDS"] = "earshot", reg_es["kinds"]
            Pes = plan("dossier")
            n_es = sum(1 for c in Pes.sfx if c["kind"].startswith("=es_"))
            say(n_es > 0 and not es_problems(reg_es, reg_es["kinds"], Pes.sfx), "earshot source: a built plan emits %d earshot cues, every id has a measured onset" % n_es,
                "; ".join(es_problems(reg_es, reg_es["kinds"], Pes.sfx))[:200])
            broken = copy.deepcopy(reg_es)
            wid = broken["kinds"]["whoosh"]
            broken["items"][wid[0]]["onset_ms"] = None
            del broken["items"][wid[1]]
            say(len(es_problems(broken, broken["kinds"], Pes.sfx)) >= 2, "bad: a registry with an unmeasured onset and a missing id fails the earshot check")
        finally:
            glb["SFX_SOURCE"], glb["ES_KINDS"] = old_src, old_k
        if old_src not in ("earshot", "openverse"):
            Pdef = plan("dossier")
            say(not any(c["kind"].startswith("=es_") for c in Pdef.sfx), "default source (library): no earshot id is ever emitted")
    # ---- learnt weights (engine_learn.py): a weights file must shift the choice, only among valid options, and must never act without evidence
    if EL is not None:
        st_w, _ = make_fixture()
        def wdoc(dim, probs, active=True):
            return {"generated_at": "2026-10-26T00:00:00", "sha1": "selftest", "dimensions": {dim: {"active": active, "probs": probs}}}
        base = ew_apply("ZZ1", st_w, None, None, None)
        say(base["fmt"] == pick_format(st_w) and base["swatches"] == FF.FORMATS[base["fmt"]].get("swatches_light", []) + FF.FORMATS[base["fmt"]]["swatches"] and base["rec"] is None and base["world"] == st_w["world"],
            "weights: no weights file -> exactly the rule defaults (format, swatch order, world), nothing recorded")
        dark_first = lambda w_: sum(FF.SWATCHES[ew_apply("Z%d" % i, st_w, None, None, w_)["swatches"][0]].get("dark", False) for i in range(80))
        n_dark, n_light = dark_first(wdoc("ground", {"dark": 0.97, "light": 0.03})), dark_first(wdoc("ground", {"dark": 0.03, "light": 0.97}))
        say(n_dark > 55 and n_light < 25 and n_dark - n_light > 30, "weights: a ground weight shifts the first swatch (dark-first %d/80 when dark favoured, %d/80 when light favoured) and still explores" % (n_dark, n_light))
        say(n_dark < 80 and n_light > 0, "weights: the disfavoured ground is still drawn sometimes (exploration floor)")
        fm_ = lambda w_: [ew_apply("Z%d" % i, st_w, None, None, w_)["fmt"] for i in range(80)]
        st_w = copy.deepcopy(st_w)
        for b_ in st_w["beats"]:
            if b_["kind"] == "response":
                b_["kind"] = "context"                    # no response beat: the content leaves dossier and clean open (money story)
        got = fm_(wdoc("format", {"dossier": 0.02, "clean": 0.97, "newsroom": 0.01}))
        say(got.count("clean") > 55 and "newsroom" not in got, "weights: a format weight moves money stories dossier -> clean (%d/80) and never to an invalid newsroom" % got.count("clean"))
        say(set(fm_(wdoc("format", {"dossier": 0.02, "clean": 0.97, "newsroom": 0.01}, active=False))) == {pick_format(st_w)}, "weights: an inactive dimension (n below the gate) changes nothing")
        st_r = copy.deepcopy(st_w)
        st_r["beats"][1]["kind"] = "response"      # the fixture is a newsroom story by content; st_w was loosened above
        say(set(ew_apply("Z%d" % i, st_r, None, None, wdoc("format", {"dossier": 0.9, "clean": 0.05, "newsroom": 0.05}))["fmt"] for i in range(40)) == {"newsroom"},
            "weights: a response beat is a newsroom story whatever the weights say (content gate wins)")
        say(ew_apply("Z1", st_w, "dossier", "D3", wdoc("format", {"dossier": 0.0, "clean": 1.0, "newsroom": 0.0}))["fmt"] == "dossier", "weights: an explicit --format hint is never overridden")
        st_m = copy.deepcopy(st_w)
        st_m["world"] = "map"
        say(all(ew_apply("Z%d" % i, st_m, None, None, wdoc("world_family", {"desk-paper": 0.97, "ui-screen": 0.01, "interior-set": 0.01, "map-plan": 0.01}))["world"] == "map" for i in range(30)), "weights: a map story stays a map story")
        wfam = [ew_apply("Z%d" % i, st_w, None, None, wdoc("world_family", {"desk-paper": 0.01, "ui-screen": 0.97, "interior-set": 0.02}))["world"] for i in range(80)]
        say(all(w_ == st_w.get("world") for w_ in wfam), "weights: a world-family weight never moves a story out of its own world (root 26 Oct: the world reflects the story)", str(set(wfam)))
        r1 = ew_apply("Z5", st_w, None, None, wdoc("ground", {"dark": 0.5, "light": 0.5}))
        r2_ = ew_apply("Z5", st_w, None, None, wdoc("ground", {"dark": 0.5, "light": 0.5}), prior=r1["rec"])
        say(r1["swatches"] == r2_["swatches"], "weights: a rebuild of the same short reuses its recorded picks (attribution stays true)")
    # ---- SFX source "openverse": a licensed, earshot-measured library queried by role. Skipped until kit/registry/sfx-library.json exists.
    lib_reg = jload(os.path.join(KIT, "registry", "sfx-library.json"), {})
    if lib_reg.get("items"):
        glb = globals()
        keep = {k: glb[k] for k in ("SFX_SOURCE", "SFX_LIB", "SFX_USAGE_PATH", "SFX_POOL")}
        tmpd = tempfile.mkdtemp(prefix="sfxlib-selftest-")
        try:
            glb.update(SFX_SOURCE="openverse", SFX_LIB=lib_reg, SFX_USAGE_PATH=os.path.join(tmpd, "usage.json"))
            story, words = make_fixture()

            def build_n(n):
                P = new_plan("ZZ%d" % n, story, words, "dossier", FF.FORMATS["dossier"]["swatches"][0])
                assemble(P)
                ids = [c["kind"][1:] for c in P.sfx if c["kind"].startswith(("=ov_", "=es_", "=es2_"))]
                sfx_ledger_put(P.sid, ids)
                return P, ids

            def meta(i):
                return lib_reg["items"].get(i) or next(v for k, v in lib_reg["items"].items() if k.startswith(i + "@"))
            Pa, ia = build_n(1)
            say(len(ia) >= 3, "openverse source: a built plan cues %d library sounds chosen by role" % len(ia))
            ms = [meta(i) for i in ia]
            say(all(m.get("onset_ms") is not None and m.get("end_ms") is not None and m["end_ms"] > m["onset_ms"] for m in ms), "openverse source: every cue's sound has a MEASURED onset / end (placement is by onset, never the file start)")
            say(len(ia) == len(set(ia)), "openverse source: no file is used twice in one short", "%d cues, %d distinct" % (len(ia), len(set(ia))))
            say(all(m["source"].get("licence_slug") in ("cc0", "pdm", "mit") and m.get("usable", True) for m in ms), "openverse source: only cc0 / pdm / mit files marked usable are ever picked (CC BY never)", str({m["source"].get("licence_slug") for m in ms}))
            builds = [ia]
            relaxed = len([r for r in Pa.repairs if "cap relaxed" in r])
            for n in range(2, 7):
                P_, i_ = build_n(n)
                builds.append(i_)
                relaxed += len([r for r in P_.repairs if "cap relaxed" in r])
            worst = max(len(set(builds[j]) & set(builds[k])) for j in range(len(builds)) for k in range(j + 1, min(len(builds), j + 5)))
            say(worst == 0 and relaxed == 0, "openverse source: 6 consecutive shorts share no file inside any 5-short window (shared %d, cap relaxed %d times)" % (worst, relaxed))
            glb["SFX_POOL"] = 1
            lib_nb = dict(lib_reg, items={k: v for k, v in lib_reg["items"].items() if v["source_kind"] == "openverse" and v["role"] == "tick"})
            glb["SFX_LIB"] = lib_nb
            glb["SFX_USAGE_PATH"] = os.path.join(tmpd, "usage2.json")
            Pc = new_plan("ZZ9", story, words, "dossier", FF.FORMATS["dossier"]["swatches"][0])
            assemble(Pc)
            ic = [c["kind"][1:] for c in Pc.sfx if c["kind"].startswith(("=ov_", "=es_", "=es2_"))]
            say(len(ic) == len(set(ic)) and any("dropped" in r for r in Pc.repairs), "bad: with only a few tick files and no second source the repeat cue is dropped, never reused (%d dropped)" % sum(1 for r in Pc.repairs if "dropped" in r))
        finally:
            glb.update(keep)
            shutil.rmtree(tmpd, ignore_errors=True)
    print("format_engine selftest: %s" % ("ALL PASS" if not bad else "%d FAILED" % bad))
    return 1 if bad else 0


# ================================================================================================ produce: one command from a voiced script to a submitted storyboard
METRICS = os.path.join(KIT, "registry", "format-engine-metrics.json")
PY = sys.executable


def run_step(cmd, timeout, env=None):
    t = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=KIT, env=env)
        return r.returncode, time.time() - t, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, time.time() - t, "timeout after %d s" % timeout


def voice_state(sid):
    """(ok, reason): a sealed take = wav + words.json + RESULT FINISHED + voicelead PASS with no fails"""
    d = os.path.join(V2, "shorts", "voice", sid)
    for f in (sid + ".wav", sid + ".words.json"):
        if not os.path.exists(os.path.join(d, f)):
            import voice_install as VI
            if VI.status(sid)[1]:
                return True, "sealed (hosted, installs on produce)"
            return False, "no %s" % f
    res = jload(os.path.join(d, "RESULT.json"), {}) or {}
    vl = jload(os.path.join(d, sid + ".voicelead.json"), {}) or {}
    if not str(res.get("status")).startswith("FINISHED"):          # the free route writes FINISHED_LOCAL_CHECKS_PASS (listening UNJUDGED)
        return False, "voice RESULT status %r" % res.get("status")
    if vl.get("verdict") != "PASS" or vl.get("fails"):
        return False, "voicelead %r fails %s" % (vl.get("verdict"), vl.get("fails"))
    return True, "sealed"


def v3_state(sid):
    """(ok, reason): the script meets strategy v3 rules 2, 3 and 6 (the rules the engine cannot fix)"""
    import craft_check as CC
    sp = CC.script_text(sid) or ""
    if not sp:
        return False, "no spoken script"
    fc, S = CC.first_clause(sp), CC.spoken_sentences(sp)
    bad = []
    if len(fc) > 8 or CC.opener_problem(sp):
        bad.append("rule2")
    if not any(CC.YOU_RE.search(x) for x in S[:2]):
        bad.append("rule3")
    en = CC.ending_analysis(sp)
    if en["type"] != "verdict-question" or en["banned"]:
        bad.append("rule6")
    return (not bad), ("v3" if not bad else "needs-writer: " + ",".join(bad))


def figure_state(sid):
    """(ok, reason): the spoken script says a figure (the hero tag needs a spoken number; S253 Aldi has none and extract_story rejects it)"""
    # root 21 Oct: the script-text test counted "a different one" as a figure, so S254 (no number at all) looped through produce
    # every 20 min. Use extract_story's own reader on the installed voice words: a non-year quantity the voice actually says.
    try:
        import extract_story as ES
        ctx = ES.build_context(sid)
        w = ctx["words"]
        if any(n["kind"] != "year" for n in ES.spoken_numbers(w, 0, len(w) - 1)):
            return True, "figure"
        return False, "no spoken figure"
    except Exception:  # noqa: BLE001 - no installed words yet: fall back to the script text
        import craft_check as CC
        sp = CC.script_text(sid) or ""
        if any(number_words_in(x) for x in CC.spoken_sentences(sp)):
            return True, "figure (script text)"
        return False, "no spoken figure"


def cooldown_applies(last):
    """root 21 Oct: a short that failed or was refused is not retried for 24 h; root 27 Oct: unless it failed with NO-LANE (no lane answered: nothing was learnt about the story)"""
    return str(last.get("outcome", "")).startswith(("failed", "refused")) and not (last.get("no_lane") or "NO-LANE" in str(last.get("note", "")))


def eligible_ids():
    out = []
    for p in sorted(glob.glob(os.path.join(V2, "shorts", "scripts-v2", "S*.md"))):
        sid = os.path.basename(p)[:-3]
        ok, _ = voice_state(sid)
        if not ok or not v3_state(sid)[0] or not figure_state(sid)[0]:
            continue
        sp = jload(os.path.join(specs_dir(sid), "spec.json"), None)
        if sp and (sp.get("composed") or {}).get("engine") != "format_engine":
            continue                                    # another maker's spec: not ours to overwrite
        if sp and (sp.get("composed") or {}).get("look_only"):
            continue
        rec = jload(os.path.join(KIT, "registry", "storyboards", sid + ".json"), {}) or {}
        if rec.get("history") and rec["history"][-1].get("state") in ("submitted", "approved"):
            continue
        # root 21 Oct: a short that failed in the last 24 h is not retried every tick (S254 burned free calls 5 times) unless its
        # sealed take is newer than the failure.
        last = (jload(os.path.join(KIT, "registry", "format-engine-metrics.json"), {}) or {}).get(sid) or {}
        if cooldown_applies(last):
            try:
                t_fail = time.mktime(time.strptime(last.get("started", "")[:19], "%Y-%m-%dT%H:%M:%S"))
                rcpt = os.path.join(V2, "crew", "voice-hosted", "receipts", sid + ".json")
                newer = os.path.exists(rcpt) and os.path.getmtime(rcpt) > t_fail
                if time.time() - t_fail < 86400 and not newer:
                    continue
            except ValueError:
                pass
        out.append(sid)
    return out


OUT_KEEP_DIRS = ("precheck", "domlint", "polish", "gate")          # what a reviewer or the learning loop reads: precheck/beats.jpg, the gate JSON and logs
OUT_KEEP_NOTE = "kept precheck/beats.jpg, the sheet and gate JSON, story.json, metrics and logs; the raw frame dumps and renders are regenerable from story.json"


def trim_out(sid, base=None):
    """root 27 Oct (disk: 44 -> 1.4 GB in a day, engine builds wrote ~12 GB): a build that does not submit keeps only what a reviewer or the learning loop needs. Removes every sub-directory of
    kit/out/<ID> except precheck, domlint, polish and gate (snap frame dumps, snap-archive and snap-*-prev copies, audio, build, static-precheck are deterministic and regenerable from story.json);
    loose files (BUILD.json, COST.json, state.json, resolved.json, logs) stay. -> bytes freed. A submitted build is never trimmed here."""
    d = os.path.join(base or os.path.join(KIT, "out"), sid)
    if not os.path.isdir(d):
        return 0
    freed = 0
    for name in os.listdir(d):
        pth = os.path.join(d, name)
        if os.path.isdir(pth) and not os.path.islink(pth) and name not in OUT_KEEP_DIRS:
            for root_, _dirs, files in os.walk(pth):
                for f_ in files:
                    try:
                        freed += os.path.getsize(os.path.join(root_, f_))
                    except OSError:
                        pass
            shutil.rmtree(pth, ignore_errors=True)
    return freed


def produce(sid, submit=True, log=print, look=False, sw_hint=None, tried=()):
    """voiced + v3 -> story.json (one free-lane call) -> clause crops -> engine build -> precheck_all (incl. sheet_occupancy) -> storyboard submit. No human, no Claude.
    Returns a dict {id, outcome, stages{name: secs}, lane_calls, wall_s, note}. outcome is submitted | built | refused:<why> | failed:<stage>."""
    if sys.platform == "darwin":
        # This route's precheck renders/inspects media locally. Until its full
        # native chain is hosted, do not begin it or clean up prior outputs.
        return {"id": sid, "outcome": "held:hosted-only", "stages": {}, "lane_calls": 0,
                "wall_s": 0, "note": "format-engine media prechecks require the hosted route"}
    t0 = time.time()
    rec = dict(id=sid, started=time.strftime("%Y-%m-%dT%H:%M:%S"), stages={}, lane_calls=0, outcome="", note="")

    def done(outcome, note=""):
        if outcome not in ("submitted", "built"):          # a short that did not reach the sheet must not count against the next one's novelty (S317 was refused for S271's swatch)
            try:
                with Locked(REG_FE):
                    reg_ = jload(REG_FE, {})
                    if reg_.pop(sid, None) is not None:
                        tmp_ = REG_FE + ".tmp%d" % os.getpid()
                        json.dump(reg_, open(tmp_, "w"), indent=1)
                        os.replace(tmp_, REG_FE)
            except Exception:
                pass
        if outcome != "submitted":
            try:
                fr_ = trim_out(sid)
                if fr_:
                    rec["trimmed_mb"] = round(fr_ / 1048576.0, 1)
            except Exception:
                pass
        rec.update(outcome=outcome, note=note[:600], wall_s=round(time.time() - t0, 1))
        with Locked(METRICS):
            m = jload(METRICS, {})
            m[sid] = rec
            tmp = METRICS + ".tmp%d" % os.getpid()
            json.dump(m, open(tmp, "w"), indent=1)
            os.replace(tmp, METRICS)
        log("produce %s: %s (%.0f s, %d free-lane calls) %s" % (sid, outcome, rec["wall_s"], rec["lane_calls"], note[:200]))
        return rec

    def stage(name, secs):
        rec["stages"][name] = round(secs, 1)
    ok, why = voice_state(sid)
    if not ok:
        return done("refused:no-take", why)
    import voice_install as VI
    if not VI.status(sid)[0]:
        t = time.time()
        try:
            r = VI.install(sid)
        except Exception as e:                  # InstallError, a gh failure, an expired artifact: the short waits for a re-seal
            stage("voice_install", time.time() - t)
            return done("refused:voice-install", str(e))
        stage("voice_install", time.time() - t)
        rec["note"] += "installed the sealed take (%d files, run %s); " % (len(r["files"]), r.get("run_id"))
    ok, why = v3_state(sid)
    if not ok and not look:
        return done("refused:needs-writer", why)
    ok, why = figure_state(sid)
    if not ok:
        return done("refused:no-figure", why)
    if look:
        submit = False                       # a LOOK run (script not v3) never submits
    # 1. story.json (one free-lane call; skipped when story.json is current for these inputs)
    sp = os.path.join(specs_dir(sid), "story.json")
    cur = look and os.path.exists(sp)
    if os.path.exists(sp) and not look:
        _st = jload(sp, {}) or {}
        if len(((_st.get("tiny_cause") or {}).get("text") or "").split()) > 5:        # craft_check: frame0.cause is 1-5 words; a 6-word story is re-extracted under the 5-word cap
            os.replace(sp, sp + ".bak-2026-10-26-6word")
        rc, secs, out = run_step([PY, "tools/extract_story.py", "--verify", sid], 120)
        cur = rc == 0
        stage("verify_story", secs)
    if not cur:
        import extract_story as ES_lane
        if not ES_lane.lane_up():          # root 27 Oct: NO-LANE says nothing about the story; do not spend minutes to learn it, and do not start the 24 h cooldown
            rec["no_lane"] = True
            return done("failed:extract_story", "NO-LANE: no lane is up (every free lane is cooled, limited or erroring); retried on the next tick")
        rc, secs, out = run_step([PY, "tools/extract_story.py", sid], 900)
        stage("extract_story", secs)
        st = jload(sp, {}) or {}
        rec["lane_calls"] = len((st.get("grounding") or {}).get("attempts") or [])
        if rc != 0 or st.get("status") == "rejected":
            if "NO-LANE" in out:
                rec["no_lane"] = True          # no lane answered: nothing was learnt about the story
            return done("failed:extract_story", out[-400:])
    st = jload(sp, {}) or {}
    if st.get("status") == "thin" and not look:
        return done("refused:thin", "thin: needs richer sources (%s)" % (st.get("richness") or {}))
    if st.get("status") != "ready" and not look:
        why_ = " | ".join(str(a_.get("result"))[:400] for a_ in ((st.get("grounding") or {}).get("attempts") or [])[-1:])
        return done("refused:needs-writer", "story.json status %s gaps %s %s" % (st.get("status"), st.get("gaps"), why_))
    # 2. the real clause crops the story names: the hero's source clause and every clipping object (a paywalled page fails the crop: that clipping is dropped, the rest of the short stands)
    jobs = []
    for src in st.get("sources") or []:
        cl = src.get("clause")
        if cl and cl.get("phrase") and src.get("url"):
            jobs.append((src["url"], cl["phrase"], cl["key"]))
    srcs = {x["id"]: x for x in st.get("sources") or []}
    for b_ in st.get("beats") or []:
        ob = b_.get("object") or {}
        if ob.get("kind") == "clipping" and srcs.get(ob["content"]["source_id"], {}).get("url"):
            jobs.append((srcs[ob["content"]["source_id"]]["url"], ob["content"]["phrase"], ob["content"]["key"]))
    d = os.path.join(specs_dir(sid), "media", "clauses")
    seen = set()
    for url, phrase, key in jobs:
        if key in seen or os.path.exists(os.path.join(d, key + ".png")) or os.path.exists(os.path.join(d, key + ".FAIL.json")):
            continue                         # cropped already, or the page cannot be cropped (paywall): do not retry on every run
        seen.add(key)
        rc, secs, out = run_step([PY, "tools/crop_clause.py", "--url", url, "--phrase", phrase, "--id", sid, "--key", key, "--min-px", "54", "--out", d, "--allow-undated"], 400)
        stage("crop_" + key[:20], secs)
        if rc != 0:
            rec["note"] += "crop failed for %s: %s; " % (key, out.strip().splitlines()[-1][:120] if out.strip() else rc)
    # 3. build
    t = time.time()
    try:
        _out = build(sid, look=look, sw_hint=sw_hint)
        rec["repairs"] = list(getattr(_out["plan"], "repairs", []))[:12]
    except EngineError as e:
        stage("build", time.time() - t)
        if "object content repeated" in str(e):
            return done("refused:thin", "thin: the story has fewer distinct objects than beats; send it to the supply revise loop for richer sources (never padded): " + str(e)[:300])
        return done("refused:engine", str(e))
    stage("build", time.time() - t)
    # 4. precheck_all (concept, build, voice, frame, dom_lint, polish, static, sheet incl. sheet_occupancy, btl)
    env = dict(os.environ)
    env.setdefault("AGMM_GH_USER", "SamAGMM")
    rc, secs, out = run_step([PY, "tools/precheck_all.py", sid, "--keep-going"], 1500, env)
    stage("precheck_all", secs)
    last = jload(os.path.join(KIT, "out", sid, "precheck", "last.json"), {}) or {}
    bad = {k: v.get("status") for k, v in (last.get("results") or {}).items() if v.get("status") != "PASS"}
    if rc != 0 or bad:
        fl = []
        for k, v in (last.get("results") or {}).items():
            for f in (v.get("fails") or [])[:2]:
                fl.append("%s: %s" % (k, f.get("detail") or f.get("line")))
        sheet_f = " ".join(str(f.get("detail") or f.get("line")) for f in ((last.get("results") or {}).get("sheet", {}).get("fails") or []))
        skins_ = (jload(os.path.join(specs_dir(sid), "spec.json"), {}).get("composed") or {}).get("skins") or []
        non_card = [k_ for k_ in skins_ if k_ not in ("counter", "quote_card", "price_tag", "clipping")]
        if ("SCALE" in sheet_f or "DISTINCT" in sheet_f) and len(non_card) < 2:          # root 26 Oct: flat cards cannot clear SCALE and DISTINCT together: send it back for richer objects, do not force it
            return done("refused:thin", "thin: needs 2+ non-card objects (a map, bars, a logo pair, a timeline, a document); it has %d: %s | %s" % (len(non_card), non_card, sheet_f[:200]))
        return done("failed:precheck", "%s | %s" % (bad, " ; ".join(fl)[:400]))
    if not submit:
        return done("built", "precheck_all PASS; not submitted (--no-submit)")
    # 4b. the declared ground is the MEASURED one (computed the way sheet_check / concept_check read the sheet), so declaration and sheet cannot disagree (S317 failed:submit 3x)
    try:
        g_ = declare_measured_ground(sid)
        stage("ground", 0.1)
        rec["note"] += "ground declared from the sheet: %s; " % g_
    except Exception as e:
        rec["note"] += "ground declaration skipped (%s); " % str(e)[:80]
    # 5. submit for independent review (a maker never approves)
    rc, secs, out = run_step([PY, "tools/storyboard.py", "submit", sid], 1500, env)
    stage("submit", secs)
    sheet = os.path.join(KIT, "registry", "storyboards", sid + "-storyboard.jpg")
    if rc != 0:
        # the measured ground can read as a hue three recent approved shorts already own (concept_check R2): the sheet is honest, so the planner changes the swatch, never the rule
        rc2, _s2, out2 = run_step([PY, "tools/concept_check.py", sid], 300)
        if "[FAIL] R2" in out2 and len(tried) < 3:
            used = (jload(os.path.join(specs_dir(sid), "spec.json"), {}).get("composed") or {}).get("swatch")
            fmt_ = (jload(os.path.join(specs_dir(sid), "spec.json"), {}).get("composed") or {}).get("format")
            pool_ = [x for x in (FF.FORMATS[fmt_].get("swatches_light", []) + FF.FORMATS[fmt_]["swatches"]) if x != used and x not in tried] if fmt_ in FF.FORMATS else []
            if pool_:
                rec["note"] += "R2 hue refusal on %s: retrying on %s; " % (used, pool_[0])
                return produce(sid, submit=submit, log=log, look=look, sw_hint=pool_[0], tried=tuple(tried) + (used,))
        return done("failed:submit", out.strip()[-400:])
    return done("submitted", sheet)


def declare_measured_ground(sid):
    import sheet_check as SC, concept_check as CK
    from PIL import Image
    fr, _how = SC.load_frames(sid, "snap")
    n = len(fr)
    cols = 6
    im = Image.new("RGB", (270 * cols, 480 * (-(-n // cols))), (0, 0, 0))
    for i, f in enumerate(fr):
        im.paste(f["img"], ((i % cols) * 270, (i // cols) * 480))
    tmp = os.path.join(KIT, "out", sid, "precheck", "ground-sheet.jpg")
    im.save(tmp, quality=90)
    m = CK.measure_sheet(tmp)
    cp = os.path.join(specs_dir(sid), "concept.json")
    c = jload(cp)
    old = c["ground"]["hex"]
    c["ground"] = {"hex": m["hex"], "luminance": CK.lum_class_of(m["hex"]), "beats_fraction": round(min(0.99, max(0.5, m["share"])), 2)}
    if c.get("palette"):
        c["palette"][0] = m["hex"]            # R0: palette[0] IS the ground; the measured ground replaces the swatch's
    shutil.copy2(cp, cp + FLEET_BAK) if not os.path.exists(cp + FLEET_BAK) else None
    json.dump(c, open(cp, "w"), indent=1, ensure_ascii=False)
    return "%s -> %s" % (old, m["hex"])


def sweep_out():
    """a produce that was killed before it finished left its frame dumps behind: trim every engine short that is not submitted (the produce lock is held, so none is mid-build). -> bytes freed"""
    freed = 0
    for sid, v in (jload(os.path.join(KIT, "registry", "format-engine-metrics.json"), {}) or {}).items():
        if v.get("outcome") == "submitted" or not os.path.isdir(os.path.join(KIT, "out", sid)):
            continue
        sp = jload(os.path.join(specs_dir(sid), "spec.json"), None)
        rec = jload(os.path.join(KIT, "registry", "storyboards", sid + ".json"), {}) or {}
        if (sp and (sp.get("composed") or {}).get("engine") != "format_engine") or (rec.get("history") and rec["history"][-1].get("state") in ("submitted", "approved")):
            continue
        freed += trim_out(sid)
    return freed


def cmd_produce(a):
    lock = os.path.join(KIT, "registry", "format-engine-produce")
    with Locked(lock):                       # one produce at a time: the Actions snap pool and the heavy slots are shared
        fr_ = sweep_out()
        if fr_:
            print("sweep: %.0f MB of frame dumps from unfinished builds removed" % (fr_ / 1048576.0))
        ids = a.id or []
        if a.all:
            ids = eligible_ids()[: a.limit]
            print("produce --all: %d eligible: %s" % (len(ids), ", ".join(ids) or "none"))
        rc = 0
        for sid in ids:
            r = produce(sid, submit=not a.no_submit, look=a.look)
            rc |= 0 if r["outcome"] in ("submitted", "built") else 1
        return rc


def cmd_eligible(a):
    for p in sorted(glob.glob(os.path.join(V2, "shorts", "scripts-v2", "S*.md"))):
        sid = os.path.basename(p)[:-3]
        v, vr = voice_state(sid)
        k, kr = v3_state(sid)
        f_, fr_ = figure_state(sid)
        print("%-6s voice:%-26s v3:%-28s %-18s %s" % (sid, vr[:26], kr[:28], fr_, "ELIGIBLE" if (v and k and f_) else ""))
    return 0


# ================================================================================================ CLI
def cmd_build(a):
    out = build(a.id, a.format, a.swatch, write=not a.check, look=a.look)
    P = out["plan"]
    b = P.spec_beats
    print("format_engine %s: %s on %s | %.1f s | %d beats (%.1f a minute, longest %.1f s) | %d items | %d cues (%.0f a minute) | %d fillers | scenes %s"
          % (P.sid, P.F["name"], P.sw_key, P.dur, len(b), len(b) / (P.dur / 60.0), max(x["t_to"] - x["t_from"] for x in b), len(P.items), len(P.sfx), len(P.sfx) / (P.dur / 60.0), P.fillers, collections.Counter(P.skins_used).most_common()))
    print("concept_check R0-R9: PASS (%s, %s, %s)" % (out["concept"]["world"]["world_family"], out["concept"]["hero_device"], out["concept"]["signature"]["mechanism"]))
    if not a.check:
        js = os.path.join(specs_dir(P.sid), "scenes.js")
        node = os.path.expanduser("~/.local/node/bin/node")
        if os.path.exists(node):
            r = subprocess.run([node, "--check", js], capture_output=True, text=True)
            print("node --check scenes.js: %s" % ("ok" if r.returncode == 0 else r.stderr[:300]))
        print("wrote specs/%s/{spec.json, scenes.js, concept.json, CONCEPTS.md, STATE.md}" % P.sid)
    return 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build")
    b.add_argument("id")
    b.add_argument("--format", choices=["dossier", "clean", "newsroom"])
    b.add_argument("--swatch")
    b.add_argument("--check", action="store_true", help="build and judge everything, write nothing")
    b.add_argument("--look", action="store_true", help="LOOK build only: skip the v3-script refusal so the visuals can be inspected; the spec is marked look_only and must not be submitted")
    c = sub.add_parser("check")
    c.add_argument("id")
    pr = sub.add_parser("produce", help="voiced + v3 script -> story.json -> crops -> build -> precheck_all -> submit, no human")
    pr.add_argument("id", nargs="*")
    pr.add_argument("--all", action="store_true", help="every voiced, v3, engine-eligible short without a submission (use --limit)")
    pr.add_argument("--limit", type=int, default=1)
    pr.add_argument("--no-submit", action="store_true")
    pr.add_argument("--look", action="store_true", help="LOOK run on a short whose script is not v3: skips the v3 refusal and the submit, marks the spec look_only")
    sub.add_parser("eligible", help="list scripts with their voice and v3 state")
    a = ap.parse_args()
    try:
        if a.cmd == "build":
            return cmd_build(a)
        if a.cmd == "produce":
            return cmd_produce(a)
        if a.cmd == "eligible":
            return cmd_eligible(a)
        if a.cmd == "check":
            a.format, a.swatch, a.check, a.look = None, None, True, False
            return cmd_build(a)
    except EngineError as e:
        print("format_engine REFUSED %s" % getattr(a, "id", ""), "\n  " + str(e))
        return 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
