#!/usr/bin/env python3
"""craft_check.py <ID> | --selftest      (CRAFT-BUILD, 19 Oct 2026; run by concept_check.py as rule R10)

Verifies the `craft` block of specs/<ID>/concept.json is FILLED, and filled with something that can be checked, not with words that
pass. Why: free text-only lanes take the first idea that passes. The block makes the author answer four questions BEFORE writing
(from Felix Rieseberg's "deeper version" prompt) and commit to a locked message, a banned list, one central visual rule, one named move
per beat and a named hook type. Every field has a test that can fail (see --selftest, which feeds bad blocks and requires FAIL):

  answers.expert_move     >= 40 chars: what a top short-form explainer professional would do here that the brief does not ask for
  answers.rawest_source   a LOCATOR (https URL or a file path) to the original document or page, not a news summary
  answers.methods         >= 2 distinct items, each >= 15 chars: the specific tools and methods
  answers.outside_judges  >= 2 items, each naming a judge OTHER than the author (dom_lint, frame_fill, concept_check, polish_check, static,
                          voice_lead_check, quote_check, better_than_last, gate, the independent reviewer, Jev, YouTube retention ...);
                          at least one a measuring tool; self-judging wording ("I will check", "maker review") FAILS
  locked_message          20-140 chars, >= 70% of its content words occur in the script (the one line a viewer repeats; no slogan of ours)
  banned                  >= 6 unique items, >= 3 of them specific to THIS story (not the generic list: robots, brains, sparkles, glow ...)
  central_visual_rule     >= 6 words, naming at least one word the script speaks (words tied to a formal behaviour)
  beat_moves              one {beat, verb} per beat (every beat of spec.json when it exists, else >= 6), a single lowercase verb, no two
                          adjacent beats share a verb, >= 60% of the verbs distinct
  hook                    type from kit/HOOK-MENU.md (registry/hook-labels.json "types"), t0 and t1_5 (what is on screen at 0 s and 1.5 s) >= 30 chars,
                          desired_reaction >= 20 chars; a discouraged type needs why_discouraged >= 40 chars; the type must match the script's first
                          sentence (a date opener cannot be labelled stake-slam, a question cannot be anything but question-prompt)
STRATEGY v3 (19 Oct 2026, kit/registry/strategy-v3.json; check_v3 below): V3 rule1 frame0 (known name, cause, cost) + frame0 dom + beat2 artefact | rule2 first clause (<= 8 words) and opener | rule3 "you" in the
first two sentences | rule5 length (WARN over 50 s) | rule6 verdict then closing question, no "follow for more" | experiment (six arms, derivable ones must equal the short).
FAIL from live_from (17:00 19 Oct) and for unclaimed IDs, WARN in flight. `--selftest` proves each rule with a FAIL and a PASS case.
Enforced (FAIL) for shorts claimed at or after CRAFT_LIVE_FROM; WARN for shorts already in flight. AGMM_CRAFT_ENFORCE=1 forces FAIL, =0 forces WARN.
Library: check(ID, concept, derived=False, script=None, spec=None) -> [(ok, name, detail, level)]."""
import json, os, re, sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2 = os.path.dirname(KIT)
CRAFT_LIVE_FROM = os.environ.get("AGMM_CRAFT_LIVE_FROM", "2026-10-19T16:00:00")
LABELS = os.path.join(KIT, "registry", "hook-labels.json")
DISCOURAGED = {"date-anchor", "number-as-subject", "abstract-opener", "question-prompt"}
GENERIC_BANS = re.compile(r"robot|brain|sparkle|glow|neon|bounc|shockwave|particle|lens ?flare|glass|rgb|camera ?shake|stock|canva|template|clich|gradient|drop ?shadow|confetti|lorem|placeholder|ai[- ]?generated|wallpaper", re.I)
JUDGES = re.compile(r"dom_lint|frame_fill|sheet_check|concept_check|polish_check|static_precheck|static check|voice_lead_check|quote_check|better_than_last|frame_precheck|"
                    r"precheck_all|gate|reviewer|\bjev\b|retention|analytics|hound|\basr\b|whisper|art director|crop_clause|audit_sound|\bocr\b", re.I)
TOOLS = re.compile(r"dom_lint|frame_fill|sheet_check|concept_check|polish_check|static_precheck|static check|voice_lead_check|quote_check|better_than_last|frame_precheck|"
                   r"precheck_all|gate|\basr\b|whisper|crop_clause|audit_sound|\bocr\b|retention|analytics", re.I)
SELF = re.compile(r"\b(i|we|claude|the maker|maker|self|myself)\b[ -]*(will |can )?(review|check|judge|verify|approve|grade|eyeball)|looks? good to me|my own (check|review)", re.I)
STOP = set("a an the of to in on at for by with from and or but that this these those is was are were be been it its as if so than then they their them he she his her you your we our i not no into out up down over under about after before just more most one two".split())
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"


def norm(s):
    return " ".join(re.findall(r"[a-z0-9£$%']+", (s or "").lower().replace("’", "'")))


def content_words(s):
    return [w for w in norm(s).split() if w not in STOP and len(w) > 2]


def script_text(ID):
    p = os.path.join(V2, "shorts", "scripts-v2", ID + ".md")
    if not os.path.exists(p):
        return None
    t = open(p).read()
    m = re.search(r"##\s*Spoken script\s*\n(.*?)(?=\n##\s|\Z)", t, re.S | re.I)
    return (m.group(1) if m else t).strip()


def first_sentence(spoken):
    parts = re.split(r"(?<=[.!?])\s+|\n+", spoken or "")
    parts = [p.strip() for p in parts if p.strip()]
    return parts[0] if parts else ""


def enforced(ID):
    e = os.environ.get("AGMM_CRAFT_ENFORCE")
    if e is not None:
        return e == "1"
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import concept_reserve
        c = concept_reserve.claim_of(ID)
        at = (c or {}).get("at")
        if at:
            return at >= CRAFT_LIVE_FROM
    except Exception:
        pass
    return True      # unclaimed (a scratch id, a new one): required


def spec_beats(ID):
    p = os.path.join(KIT, "specs", ID, "spec.json")
    try:
        return [b["id"] for b in json.load(open(p))["beats"]]
    except Exception:
        return None


def hook_types():
    try:
        return json.load(open(LABELS))["types"]
    except Exception:
        return ["stake-slam", "contradiction", "jargon-plain", "artefact-open", "quote-open", "enumeration-roll", "word-becomes-object",
                "viewer-consequence", "date-anchor", "number-as-subject", "abstract-opener", "question-prompt"]


def _check_r10(ID, c, derived=False, script=None, spec=None):
    lvl = "FAIL" if enforced(ID) else "WARN"
    out = []
    k = c.get("craft")
    if not isinstance(k, dict):
        out.append((False if lvl == "FAIL" else True, "R10 craft block", "concept.json has no `craft` block (required for shorts claimed from %s; template and meaning: kit/WRITER-BRIEF.md "
                    "'CRAFT BLOCK', kit/MAKER-CARD.md section 2)" % CRAFT_LIVE_FROM, lvl))
        return out
    add = lambda ok, name, detail: out.append((bool(ok), "R10 " + name, detail, "FAIL"))
    spoken = script if script is not None else script_text(ID)
    sw = set(content_words(spoken)) if spoken else None
    a = k.get("answers") if isinstance(k.get("answers"), dict) else {}
    s = (a.get("expert_move") or "").strip()
    add(len(s) >= 40, "expert_move", "ok" if len(s) >= 40 else "answers.expert_move must say, in >= 40 chars, what a top short-form explainer professional would do that the brief does not ask for")
    s = (a.get("rawest_source") or "").strip()
    loc = re.search(r"https?://\S+|(?:^|[\s(])[\w./~-]+\.(?:pdf|json|csv|xml|txt|md|html?|xlsx?)\b|(?:^|[\s(])(?:specs|shorts|out|research)/\S+", s)
    add(len(s) >= 30 and loc, "rawest_source", "ok: %s" % (loc.group(0).strip() if loc else "") if (len(s) >= 30 and loc) else
        "answers.rawest_source must be >= 30 chars and carry a locator (https URL or a file path) of the ORIGINAL document or page, not a news summary")
    m = a.get("methods") if isinstance(a.get("methods"), list) else []
    ms = [x.strip() for x in m if isinstance(x, str) and len(x.strip()) >= 15]
    add(len(set(ms)) >= 2, "methods", "ok" if len(set(ms)) >= 2 else "answers.methods needs >= 2 distinct items of >= 15 chars (specific tools and methods, eg 'crop_clause.py on the FCA notice paragraph 4')")
    j = a.get("outside_judges") if isinstance(a.get("outside_judges"), list) else []
    js = [x for x in j if isinstance(x, str)]
    bad = [x for x in js if not JUDGES.search(x) or SELF.search(x)]
    add(len(js) >= 2 and not bad and any(TOOLS.search(x) for x in js), "outside_judges",
        "ok" if (len(js) >= 2 and not bad and any(TOOLS.search(x) for x in js)) else
        "answers.outside_judges needs >= 2 items, each naming a judge other than the author (dom_lint, frame_fill, concept_check, polish_check, the independent reviewer, Jev, retention ...), at least one a measuring tool; "
        "not allowed: %s" % (bad[:3] or "(fewer than 2 or no measuring tool)"))
    lm = (k.get("locked_message") or "").strip()
    cw = content_words(lm)
    hit = [w for w in cw if sw is None or w in sw]
    ok = 20 <= len(lm) <= 140 and cw and (sw is None or len(hit) / float(len(cw)) >= 0.7) and not re.search(r"[–—]", lm)
    add(ok, "locked_message", "ok" if ok else "locked_message must be 20-140 chars, no dash, and >= 70%% of its content words must be words the script speaks (%s of %s are; the one line a viewer repeats, never our own slogan)" % (len(hit), len(cw)))
    b = k.get("banned") if isinstance(k.get("banned"), list) else []
    bs = []
    for x in b:
        if isinstance(x, str) and 3 <= len(x.strip()) <= 80 and x.strip().lower() not in [y.lower() for y in bs]:
            bs.append(x.strip())
    spec_ = [x for x in bs if not GENERIC_BANS.search(x)]
    add(len(bs) >= 6 and len(spec_) >= 3, "banned", "ok: %d items, %d specific" % (len(bs), len(spec_)) if (len(bs) >= 6 and len(spec_) >= 3) else
        "banned needs >= 6 unique items of 3-80 chars, and >= 3 specific to THIS story's subject (got %d unique, %d specific; generic bans such as robots, brains, sparkles, glow do not count)" % (len(bs), len(spec_)))
    r = (k.get("central_visual_rule") or "").strip()
    tied = [w for w in content_words(r) if sw is not None and w in sw]
    add(len(r.split()) >= 6 and (sw is None or tied), "central_visual_rule", "ok: ties %s" % ",".join(sorted(set(tied))[:4]) if (len(r.split()) >= 6 and (sw is None or tied)) else
        "central_visual_rule must be >= 6 words and name at least one word the script speaks, saying how that word behaves as an object on screen")
    bm = k.get("beat_moves") if isinstance(k.get("beat_moves"), list) else []
    pairs = [(x.get("beat"), (x.get("verb") or "").strip()) for x in bm if isinstance(x, dict)]
    ids = spec if spec is not None else spec_beats(ID)
    errs = []
    if any(not re.fullmatch(r"[a-z]{3,14}", v) for _, v in pairs):
        errs.append("each verb must be ONE lowercase word of 3-14 letters")
    if ids:
        miss = [i for i in ids if i not in [p for p, _ in pairs]]
        extra = [p for p, _ in pairs if p not in ids]
        if miss: errs.append("beats with no move: %s" % ",".join(miss[:6]))
        if extra: errs.append("moves for beats spec.json does not have: %s" % ",".join(map(str, extra[:4])))
        order = {i: n for n, i in enumerate(ids)}
        pairs = sorted([p for p in pairs if p[0] in order], key=lambda p: order[p[0]])
    elif len(pairs) < 6:
        errs.append("needs >= 6 beats (no spec.json yet to count)")
    adj = [pairs[i][0] + "/" + pairs[i + 1][0] for i in range(len(pairs) - 1) if pairs[i][1] and pairs[i][1] == pairs[i + 1][1]]
    if adj: errs.append("adjacent beats share a verb: %s" % ", ".join(adj[:4]))
    if pairs and len(set(v for _, v in pairs)) < 0.6 * len(pairs):
        errs.append("only %d distinct verbs in %d beats (need >= 60%%)" % (len(set(v for _, v in pairs)), len(pairs)))
    add(not errs, "beat_moves", "ok: %d beats, %d verbs" % (len(pairs), len(set(v for _, v in pairs))) if not errs else "; ".join(errs))
    h = k.get("hook") if isinstance(k.get("hook"), dict) else {}
    types = hook_types()
    ht = h.get("type")
    errs = []
    if ht not in types: errs.append("hook.type %r is not in the menu %s" % (ht, types))
    for f, n in (("t0", 30), ("t1_5", 30), ("desired_reaction", 20)):
        if len((h.get(f) or "").strip()) < n: errs.append("hook.%s needs >= %d chars" % (f, n))
    if ht in DISCOURAGED and len((h.get("why_discouraged") or "").strip()) < 40:
        errs.append("%s is a discouraged hook type: hook.why_discouraged (>= 40 chars) must say why this story needs it" % ht)
    fs = first_sentence(spoken)
    if fs and ht in types:
        if re.match(r"^(on|in|back in)\b.{0,40}\b(%s|(19|20)\d\d)\b|^(%s)\b" % (MONTHS, MONTHS), fs.lower()) and ht != "date-anchor":
            errs.append("the script opens on a date ('%s') so hook.type must be date-anchor, not %s" % (fs[:50], ht))
        if fs.endswith("?") and ht != "question-prompt":
            errs.append("the script's first sentence is a question, so hook.type must be question-prompt, not %s" % ht)
        if ht == "viewer-consequence" and not re.search(r"\byou(r|rs)?\b", fs.lower()):
            errs.append("viewer-consequence needs 'you' or 'your' in the first sentence")
    add(not errs, "hook type", "ok: %s" % ht if not errs else "; ".join(errs))
    return out


def check(ID, c, derived=False, script=None, spec=None):
    """R10 craft block + the strategy-v3 rules. A malformed craft block (a number where a string belongs) is a reported FAIL/WARN, never a silent skip."""
    lvl = "FAIL" if (enforced(ID) and v3_enforced(ID)) else "WARN"     # a malformed block only blocks a short claimed after the cut; in flight it is the old "not run" WARN, now reported with its reason
    try:
        out = _check_r10(ID, c, derived, script, spec)
    except Exception as e:
        out = [(False, "R10 craft block", "craft block could not be read (%s: %s); every craft field must be the type the template shows" % (type(e).__name__, e), lvl)]
    try:
        out += check_v3(ID, c, script)
    except Exception as e:
        out.append((False, "V3 strategy", "strategy v3 check could not run (%s: %s)" % (type(e).__name__, e), "FAIL" if v3_enforced(ID) else "WARN"))
    return out


# ------------------------------------------------------------------------------------------------------------------------------
# CREATIVE STRATEGY v3 (root, 19 Oct 2026): the machine-checkable half of the seven rules. Vault: 04-Playbooks/AGMM short-form creative
# strategy v3 — 2026-10-19.md . Cutoff and numbers: registry/strategy-v3.json. Rule 4 (brand recognition) is declared in craft.experiment and
# judged by the reviewer; rule 7 (visible series) lives in lib/overlays/sting.js and autoposter/tools/strategy_v3_captions.py.
#   V3 rule1 frame0          craft.frame0 = {known_name, known_name_as, cause, cost}; V3 rule1 frame0 dom measures t=0 from dom_lint raw.json: <= 6 words at 60 px+, a named entity, largest text a figure or the turn at 200 px+
#   V3 rule1 beat2 artefact   craft.beat2_artefact = {artefact: phone-screen|letter|receipt|notice|dashboard|ad, at_s 0.8-2.5, attribution}: the proof at about 1.5 s
#   V3 rule2 first clause     the first spoken clause (up to the first , ; : . ? ! or dash) is <= 8 words
#   V3 rule2 opener           and does not open on a date, a place, "In", "This is" or "So"
#   V3 rule3 you by 3s        "you"/"your" inside the first two sentences
#   V3 rule5 length           spoken length over 50 s is a WARN unless craft.length_reason (30+ chars) says why
#   V3 rule6 ending           a verdict sentence then a closing question in the last four sentences; "follow for more" and kin are banned
#   V3 experiment             craft.experiment fills all six arms, and every arm that can be derived must equal what the short really is
# FAIL for shorts claimed at or after live_from (and for IDs with no claim); WARN for shorts in flight. Rule 5 is always a WARN.
# The reviewer RETURNs with the rule number when rules 1, 2, 3 or 6 fail on an ID under the cutoff (SPRINT-REVIEWER card, CONCEPT-REVIEWER card).
# ------------------------------------------------------------------------------------------------------------------------------
V3_REG = os.path.join(KIT, "registry", "strategy-v3.json")
V3_DEFAULT = {"live_from": "2026-10-19T17:00:00", "first_clause_max_words": 8, "length_warn_over_s": 50,
              "frame0_words_max": 12, "frame0_readable_px": 70, "frame0_largest_px": 200,
              "rule3_you_max_s": 4.5, "rule3_you_max_word_index": 9, "rule3_you_est_max_s": 3.5}
ARTEFACTS = ("phone-screen", "letter", "receipt", "notice", "dashboard", "ad")
BRAND_ARMS = ("household", "b2b", "foreign")
MOTION_RE = re.compile(r"arriv|tick|typing|types\b|typed\b|land|stamp|scroll|count|slid|print|flip|load|stream|drop|puls|blink|sweep|push|zoom|\bpan\b|flick|updat|refresh|roll|swipe|appear|fill|ris(e|ing)|climb|ping|buzz|reveal|draw|wipe", re.I)
ABBR = {"dr", "mr", "mrs", "ms", "st", "ltd", "inc", "vs", "no", "plc", "co", "mt", "jr", "sr", "approx", "e.g", "i.e", "etc"}
MONTH_NAMES = set("january february march april june july august september october november december jan feb mar apr jun jul aug sep sept oct nov dec".split())
WEEKDAYS = set("monday tuesday wednesday thursday friday saturday sunday".split())
PLACES = set("""london manchester birmingham leeds glasgow liverpool bristol sheffield edinburgh cardiff belfast newcastle nottingham leicester
 coventry bradford hull southampton portsmouth plymouth brighton oxford cambridge cornwall devon essex kent surrey sussex norfolk suffolk yorkshire
 lancashire cumbria wales scotland england ireland britain uk america usa us china india germany france spain italy japan canada australia europe
 asia africa california texas seattle singapore dubai brazil mexico sweden norway denmark netherlands poland walsall wolverhampton
 swansea aberdeen dundee inverness norwich exeter derby stoke slough luton croydon camden hackney westminster whitehall""".split())
PREP_PLACE = {"at", "across", "inside", "outside", "near", "from", "down", "over"}
BANNED_CTA = re.compile(r"follow (us |me )?for (more|the next|one real|daily|updates|part)|follow (us |me )?(and|&) (like|subscribe)|like,? (and |&)?subscribe|hit (the )?(like|follow|subscribe)|"
                        r"smash (the )?(like|follow)|don'?t forget to (follow|like|subscribe)|follow (the )?(page|account|channel)|link in (my |the )?bio|stay tuned|more (stories )?like this|\bfollow for\b", re.I)
VERDICT_RE = re.compile(r"\b(if|when|unless|any|every|everyone|nobody|no one|never|always|cannot|can|can't|won't|isn't|aren't|doesn't|don't|not|only|means|rule|lesson|worth|must|should|need|needs)\b|\byou(r|rs)?\b", re.I)
YOU_RE = re.compile(r"\byou(?:r|rs|rself|'re|’re|'ve|’ve|'ll|’ll|'d|’d)?\b", re.I)


def v3_cfg():
    try:
        return {**V3_DEFAULT, **json.load(open(V3_REG))}
    except Exception:
        return dict(V3_DEFAULT)


def _birth_iso(path):
    try:
        import datetime
        st = os.stat(path)
        return datetime.datetime.fromtimestamp(getattr(st, "st_birthtime", st.st_mtime)).strftime("%Y-%m-%dT%H:%M:%S")
    except OSError:
        return None


def v3_claimed_at(ID):
    """ISO time this ID was claimed, or None when it has no claim and no spec folder (a new or scratch ID)."""
    try:
        q = json.load(open(os.path.join(KIT, "registry", "queue.json"))).get(ID)
    except Exception:
        q = None
    if isinstance(q, dict):
        if q.get("state") == "claimed" and q.get("at"):
            return q["at"]
        if q.get("finished"):
            return q["finished"]
    return _birth_iso(os.path.join(KIT, "specs", ID))


def v3_enforced(ID):
    e = os.environ.get("AGMM_V3_ENFORCE")
    if e is not None:
        return e == "1"
    at = v3_claimed_at(ID)
    return True if not at else at >= v3_cfg()["live_from"]


def _ends_clause(tok):
    t = tok.rstrip("\"'”’)")
    return bool(re.search(r"[,;:.?!]$", t)) and t.lower().rstrip(".,;:?!") not in ABBR and not re.fullmatch(r"[A-Z]\.", t)


def spoken_sentences(spoken):
    out = []
    for para in re.split(r"\n\s*\n", spoken or ""):
        cur = []
        for tok in para.split():
            cur.append(tok)
            t = tok.rstrip("\"'”’)")
            if re.search(r"[.?!]$", t) and t.lower().rstrip(".?!") not in ABBR and not re.fullmatch(r"[A-Z]\.", t):
                out.append(" ".join(cur)); cur = []
        if cur:
            out.append(" ".join(cur))
    return [s.strip() for s in out if re.search(r"\w", s)]


def first_clause(spoken):
    out = []
    for tok in (spoken or "").split():
        if tok in ("—", "–", "-", "--") and out:
            break
        out.append(tok)
        if _ends_clause(tok):
            break
    return [t for t in out if re.search(r"\w", t)]


def _norm_tok(t):
    t = re.sub(r"^[^\w£$]+|[^\w%]+$", "", t.lower())
    return re.sub(r"['’]s$", "", t)


def opener_problem(spoken):
    """(kind, detail) when the script opens on 'In', 'So', 'This is', a date or a place; else None."""
    toks = (spoken or "").split()
    if not toks:
        return None
    w = [_norm_tok(t) for t in toks[:8]]
    head = " ".join(toks[:5])
    if w[0] == "in":
        return ("in", "opens on 'In' ('%s')" % head)
    if w[0] == "so":
        return ("so", "opens on 'So' ('%s')" % head)
    if len(w) > 1 and w[0] in ("this", "these") and w[1] in ("is", "was", "are", "were"):
        return ("this-is", "opens on 'This is' ('%s')" % head)
    lead = w[:4]
    j = " ".join(w[:3])
    if any(x in MONTH_NAMES or x in WEEKDAYS for x in lead) or (len(lead) > 1 and lead[0] == "may" and re.match(r"\d", lead[1])) or \
            any(re.fullmatch(r"(19|20)\d\d", x) for x in lead) or any(re.fullmatch(r"\d{1,2}(st|nd|rd|th)", x) for x in lead) or \
            re.match(r"^(yesterday|last (night|week|month|year|summer|winter|spring|autumn)|earlier (this|today)|on (a|the|\d))", j):
        return ("date", "opens on a date ('%s')" % head)
    if w[0] in PLACES or (w[0] in PREP_PLACE and len(w) > 1 and toks[1][:1].isupper() and w[1] in PLACES):
        return ("place", "opens on a place name ('%s')" % head)
    return None


def spoken_seconds(ID, spoken):
    """(seconds, how): the locked voice's last word end when shorts/voice/<ID>/<ID>.words.json exists, else words / 2.8 per second (168 wpm)."""
    p = os.path.join(V2, "shorts", "voice", ID, ID + ".words.json")
    try:
        return float(json.load(open(p))["words"][-1]["end"]), "voice words.json"
    except Exception:
        n = len(re.findall(r"[A-Za-z0-9£$%']+", spoken or ""))
        return n / 2.8, "estimate from %d words at 168 wpm" % n


def ending_analysis(spoken):
    """The last four sentences: the last question in them, the declarative sentence before it (the verdict: 5-28 words and a judgement marker such as a
    condition, a modal, a negation or 'you'; a bare fact does not count), and any banned follow-CTA. A heuristic: the reviewer still reads the line."""
    S = spoken_sentences(spoken)
    n = len(S)
    tail = S[max(0, n - 4):]
    banned = [BANNED_CTA.search(s).group(0) for s in tail if BANNED_CTA.search(s)]
    isq = lambda s: s.rstrip("\"'”’) ").endswith("?")
    qi = next((i for i in range(n - 1, max(-1, n - 5), -1) if isq(S[i])), None)
    q = S[qi] if qi is not None else None
    v = None
    if qi is not None and qi >= 1:
        cand = S[qi - 1]
        if not isq(cand) and 5 <= len(cand.split()) <= 28 and VERDICT_RE.search(cand) and not BANNED_CTA.search(cand) and not re.search(r"agmm|audit|\.co\.uk", cand, re.I):
            v = cand
    qok = q is not None and 4 <= len(q.split()) <= 25
    typ = "verdict-question" if (v and qok) else "question-only" if qok else "none"
    return {"type": typ, "verdict": v, "question": q if qok else None, "banned": banned}


def length_bucket(sec):
    return "<35" if sec < 35 else "35-50" if sec <= 50 else ">50"


def parse_overrides(ex):
    """craft.experiment.overrides -> ({rule_number: (hypothesis, why_better)}, [problems]).
    Accepted shapes: {"overrides": "rule 1", "hypothesis": "...", "why_better": "..."} (a string or list of rule names sharing one hypothesis),
    or {"overrides": [{"rule": "rule 2", "hypothesis": "...", "why_better": "..."}]}. A named rule with an empty hypothesis or why_better is NOT overridden."""
    ok, problems = {}, []
    if not isinstance(ex, dict) or not ex.get("overrides"):
        return ok, problems
    raw = ex["overrides"]
    entries = []
    if isinstance(raw, list) and raw and all(isinstance(x, dict) for x in raw):
        entries = [(x.get("rule"), x.get("hypothesis"), x.get("why_better")) for x in raw]
    else:
        entries = [(raw, ex.get("hypothesis"), ex.get("why_better"))]
    for rule, hyp, why in entries:
        nums = sorted({int(n) for n in re.findall(r"\d", json.dumps(rule))}) if rule else []
        hyp, why = (hyp if isinstance(hyp, str) else "").strip(), (why if isinstance(why, str) else "").strip()
        if not nums:
            problems.append("experiment.overrides %r names no rule number (write e.g. \"rule 1\")" % (rule,))
        elif not hyp or not why:
            problems.append("override of rule %s needs a non-empty hypothesis and why_better, so it is not applied" % ",".join(map(str, nums)))
        else:
            for n in nums:
                ok[n] = (hyp, why)
    return ok, problems


GENERIC_NAMES = {"he", "she", "they", "it", "someone", "somebody", "a company", "the company", "a firm", "a man", "a woman", "a customer", "a business", "a bank", "an employee", "a worker", "a firm"}
FIGURE_RE = re.compile(r"\d|[£$€%]|\b(hundred|thousand|million|billion|trillion|per ?cent)\b", re.I)
READABLE_PX = 60        # text under this at t=0 is credit, label or detail chrome; it is not "read" in the first second
LARGEST_MIN_PX = 200    # the figure or the turn is the hero at 200 px or more (strategy v3 rule 1)


def _alnum(x):
    return re.sub(r"[^a-z0-9]", "", (x or "").lower())


def _name_alts(known):
    return [a.strip() for a in re.split(r"[/,&+|·]|\band\b", known or "") if len(_alnum(a)) >= 3]


def frame0_declared_problems(f0, spoken):
    """craft.frame0 = {known_name, cause, cost[, known_name_as: logo|text]}: the three things on frame 0 (strategy v3 rule 1). Text-only: needs no build."""
    if f0 is None:
        return ["concept.json has no craft.frame0 {known_name, cause, cost}: frame 0 is [a known name] + [a tiny cause] + [a huge cost]"]
    errs = []
    st = lambda x: x.strip() if isinstance(x, str) else ""
    kn, ca, co = st(f0.get("known_name")), st(f0.get("cause")), st(f0.get("cost"))
    alts = _name_alts(kn)
    if not alts or kn.lower() in GENERIC_NAMES or any(a.lower() in GENERIC_NAMES for a in alts):
        errs.append("frame0.known_name must be a name the viewer knows (a company, brand or institution), not %r: a nameless 'he' or 'a company' at frame 0 is a return" % kn)
    elif spoken and not any(_alnum(a) in _alnum(spoken) for a in alts):
        errs.append("frame0.known_name %r does not appear in the script: it must be the script's subject" % kn)
    if not ca or len(ca.split()) > 5:
        errs.append("frame0.cause must be the tiny cause in 1 to 5 words (got %d)" % len(ca.split()))
    if not co or not FIGURE_RE.search(co):
        errs.append("frame0.cost must be the huge cost as a figure (digits, a currency sign or a percentage), got %r" % co)
    nm_as = f0.get("known_name_as", "text")
    if nm_as not in ("logo", "text"):
        errs.append("frame0.known_name_as must be 'logo' or 'text'")
    readable = len(ca.split()) + len(co.split()) + (len(kn.split()) if nm_as == "text" else 0)
    if not errs and readable > 6:
        errs.append("frame 0 declares %d readable words (cause + cost%s); the limit is 6 at t=0: cut words, or show the name as a logo (known_name_as: logo)" % (readable, " + name" if nm_as == "text" else ""))
    return errs


def frame0_dom(ID, f0, spoken, raw=None):
    """The measured half of rule 1, read from dom_lint's raw DOM sample at t = 0 (out/<ID>/domlint/raw.json, written by `dom_lint.py <ID>` on Actions):
    (a) <= 6 words of text at >= READABLE_PX (the series sting is ignored), (b) a named entity visible (the declared known_name as text, a logo image or the script's own name),
    (c) the largest text is a figure or the turn at >= LARGEST_MIN_PX. -> [(ok, name, detail)]. No raw yet = one INFO line (nothing to measure)."""
    nm = "rule1 frame0 dom"
    cfg = v3_cfg()
    READABLE_PX, LARGEST_MIN_PX, WORDS_MAX = cfg["frame0_readable_px"], cfg["frame0_largest_px"], cfg["frame0_words_max"]
    if raw is None:
        pth = os.path.join(KIT, "out", ID, "domlint", "raw.json")
        try:
            raw = json.load(open(pth))
        except Exception:
            return [(True, nm, "INFO: no out/%s/domlint/raw.json yet; run `python3 tools/dom_lint.py %s` after the build and this line measures t=0 (<= 6 readable words, a named entity, a >= %d px figure)" % (ID, ID, LARGEST_MIN_PX))]
    try:
        part = raw["parts"][sorted(raw["parts"])[0]]
        smp = min(part["samples"], key=lambda x: abs(x.get("t", 9)))
        if abs(smp.get("t", 9)) > 0.05:
            return [(True, nm, "INFO: the raw DOM has no sample at t = 0")]
    except Exception as e:
        return [(True, nm, "INFO: raw DOM unreadable (%s)" % e)]

    def onframe(boxes):
        tot = inside = 0.0
        for x0, y0, x1, y1 in boxes or []:
            tot += max(0, (x1 - x0) * (y1 - y0))
            inside += max(0, min(x1, 1080) - max(x0, 0)) * max(0, min(y1, 1920) - max(y0, 0))
        return inside / tot if tot else 0.0
    shown = [t for t in smp.get("texts", []) if t.get("op", 0) > 0.5 and t.get("vis", 0) >= 0.5 and re.search(r"[A-Za-z0-9]", t.get("t", "")) and
             onframe(t.get("ink")) >= 0.25 and "agmm-sting" not in str(t.get("e", ""))]
    out = []
    read = [t for t in shown if t.get("fpx", 0) >= READABLE_PX]
    words = sum(len(re.findall(r"[A-Za-z0-9£$€%]+", t["t"])) for t in read)
    out.append((words <= WORDS_MAX, nm + " words", ("ok: %d readable words at t=0 (text >= %d px): %s" % (words, READABLE_PX, " / ".join(t["t"] for t in read))) if words <= WORDS_MAX else
                "%d readable words at t=0 (text >= %d px, sting ignored): %s; the limit is %d: cut it to the cause and the cost" % (words, READABLE_PX, " / ".join(t["t"] for t in read), WORDS_MAX)))
    alts = _name_alts((f0 or {}).get("known_name")) or []
    pool = [_alnum(t["t"]) for t in shown] + [_alnum(str(i.get("src", "")) + " " + str(i.get("alt", ""))) for i in smp.get("imgs", []) if i.get("op", 1) > 0.5]
    seen = [a for a in alts if any(_alnum(a) in x for x in pool)]
    out.append((bool(seen), nm + " name", ("ok: %s is visible at t=0 (text or logo)" % seen[0]) if seen else
                "no named entity visible at t=0%s: put the known name on frame 0 as a logo or as text" % ((" (declared: %s)" % ", ".join(alts)) if alts else " (frame0.known_name missing)")))
    big = max(shown, key=lambda t: t.get("fpx", 0)) if shown else None
    turn_words = set(w for w in _alnum_words((f0 or {}).get("cause", "") + " " + " ".join(first_clause(spoken)))) if spoken or f0 else set()
    is_fig = bool(big and (FIGURE_RE.search(big["t"]) or (turn_words and set(_alnum_words(big["t"])) <= turn_words)))
    okb = bool(big and big.get("fpx", 0) >= LARGEST_MIN_PX - 1 and is_fig)
    out.append((okb, nm + " hero", ("ok: the largest text is %r at %d px" % (big["t"], big["fpx"])) if okb else
                ("the largest text at t=0 is %r at %d px: it must be the figure or the turn at %d px or more" % (big["t"], big["fpx"], LARGEST_MIN_PX)) if big else "no readable text at t=0"))
    return out


def _alnum_words(x):
    return re.findall(r"[a-z0-9£$€%]+", (x or "").lower())


def check_v3(ID, c, spoken=None):
    """Strategy v3 rules -> [(ok, name, detail, level)]. `c` is concept.json (it may have no craft block)."""
    cfg = v3_cfg()
    lvl = "FAIL" if v3_enforced(ID) else "WARN"
    out = []

    def add(ok, name, detail, level=None):
        emit(ok, "V3 " + name, detail, level or lvl)
    k = c.get("craft") if isinstance(c.get("craft"), dict) else {}
    ov, ov_problems = parse_overrides(k.get("experiment"))

    def emit(ok, name, detail, level):
        """A failed rule the agent declared an override for (craft.experiment.overrides + hypothesis + why_better) passes with an INFO note."""
        m = re.match(r"V3 rule(\d)", name)
        if not ok and m and int(m.group(1)) in ov:
            hyp, why = ov[int(m.group(1))]
            out.append((True, name, "INFO: default broken on purpose (override of rule %s). hypothesis: %s | why better: %s | the default would have said: %s" % (m.group(1), hyp[:120], why[:120], detail[:140]), "INFO"))
        else:
            out.append((bool(ok), name, detail, level))
    spoken = spoken if spoken is not None else script_text(ID)
    sec, ends, you = None, {"type": "none"}, None
    if not spoken:
        for n in ("rule2 first clause", "rule3 you by 3s", "rule6 ending"):
            add(False, n, "no shorts/scripts-v2/%s.md `## Spoken script` to read" % ID)
    else:
        fc = first_clause(spoken)
        mx = int(cfg["first_clause_max_words"])
        add(len(fc) <= mx, "rule2 first clause", ("ok: %d words ('%s')" % (len(fc), " ".join(fc))) if len(fc) <= mx else
            "the first spoken clause is %d words ('%s'); rule 2 wants the turn in %d or fewer: lead with the absurd, self-inflicted or costly turn and put the setup after it" % (len(fc), " ".join(fc), mx))
        op = opener_problem(spoken)
        add(op is None, "rule2 opener", "ok" if op is None else "%s; banned openers are a date, a place, 'In', 'This is', 'So' and any sentence that needs the next one to make sense" % op[1])
        S = spoken_sentences(spoken)
        you = any(YOU_RE.search(s) for s in S[:2])
        add(you, "rule3 you by 3s", ("ok: '%s'" % next(s[:70] for s in S[:2] if YOU_RE.search(s))) if you else
            "no 'you' or 'your' in the first two sentences ('%s'); say why it lands on THEIR bank, job, business or money" % " ".join(S[:2])[:90])
        sec, how = spoken_seconds(ID, spoken)
        reason = (k.get("length_reason") or "").strip()
        over = sec > float(cfg["length_warn_over_s"])
        if not over:
            out.append((True, "V3 rule5 length", "ok: %.1f s (%s), bucket %s" % (sec, how, length_bucket(sec)), "WARN"))
        elif len(reason) >= 30:
            out.append((True, "V3 rule5 length", "%.1f s (%s) is over %d s; craft.length_reason says why: %s" % (sec, how, cfg["length_warn_over_s"], reason[:70]), "WARN"))
        else:
            emit(False, "V3 rule5 length", "%.1f s (%s) is over %d s: cut to the single sharpest point, or give craft.length_reason (30+ chars) saying why this story needs it" % (sec, how, cfg["length_warn_over_s"]), "WARN")
        ends = ending_analysis(spoken)
        okend = ends["type"] == "verdict-question" and not ends["banned"]
        add(okend, "rule6 ending", ("ok: verdict '%s' then question '%s'" % (ends["verdict"][:60], ends["question"][:60])) if okend else
            "the last four sentences need a one-sentence verdict then a specific question ending '?' (found: %s)%s; 'follow for more' and kin are retired" % (
                ends["type"], "; banned phrase: " + ", ".join(ends["banned"]) if ends["banned"] else ""))
    f0 = k.get("frame0") if isinstance(k.get("frame0"), dict) else None
    spoken_for_f0 = spoken or ""
    errs = frame0_declared_problems(f0, spoken_for_f0)
    add(not errs, "rule1 frame0 (known name, small cause, huge cost)", ("ok: %s | %s | %s" % (f0.get("known_name"), f0.get("cause"), f0.get("cost"))) if not errs else "; ".join(errs))
    for ok_, nm_, dt_ in frame0_dom(ID, f0, spoken_for_f0):
        add(ok_, nm_, dt_)
    b2 = k.get("beat2_artefact") if isinstance(k.get("beat2_artefact"), dict) else None
    errs = []
    if b2 is None:
        errs.append("concept.json has no craft.beat2_artefact {artefact, at_s, attribution}: the real artefact is the PROOF at about 1.5 s, not the frame-0 hook")
    else:
        if b2.get("artefact") not in ARTEFACTS:
            errs.append("beat2_artefact.artefact %r must be one of %s" % (b2.get("artefact"), "/".join(ARTEFACTS)))
        at_ = b2.get("at_s")
        if not isinstance(at_, (int, float)) or isinstance(at_, bool) or not 0.8 <= at_ <= 2.5:
            errs.append("beat2_artefact.at_s must be a number between 0.8 and 2.5 (about 1.5 s)")
        if not isinstance(b2.get("attribution"), str) or len(b2["attribution"].strip()) < 8:
            errs.append("beat2_artefact.attribution (8+ chars) must name who or what the artefact is rebuilt from")
    add(not errs, "rule1 beat2 artefact", ("ok: %s at %.1f s" % (b2.get("artefact"), b2.get("at_s"))) if not errs else "; ".join(errs))
    ex = k.get("experiment") if isinstance(k.get("experiment"), dict) else None
    keys = ("hook_type", "beat2_artefact", "you_by_3s", "brand_recognition", "length_bucket", "ending_type")
    if ex is not None and "beat2_artefact" not in ex and ex.get("frame0_artefact"):
        ex = {**ex, "beat2_artefact": ex["frame0_artefact"]}      # legacy arm name from the first v3 draft
    errs = []
    if ex is None:
        errs.append("concept.json has no craft.experiment: declare all six arms %s" % list(keys))
    else:
        errs += ov_problems
        miss = [x for x in keys if not str(ex.get(x) or "").strip()]
        if miss:
            errs.append("craft.experiment is missing %s" % miss)
        if ex.get("brand_recognition") and ex["brand_recognition"] not in BRAND_ARMS:
            errs.append("experiment.brand_recognition must be one of %s" % "/".join(BRAND_ARMS))
        if ex.get("hook_type") and (k.get("hook") or {}).get("type") and ex["hook_type"] != k["hook"]["type"]:
            errs.append("experiment.hook_type %r differs from craft.hook.type %r" % (ex["hook_type"], k["hook"]["type"]))
        if ex.get("beat2_artefact") and b2 and 1 not in ov and ex["beat2_artefact"] != b2.get("artefact"):
            errs.append("experiment.beat2_artefact %r differs from craft.beat2_artefact.artefact %r" % (ex["beat2_artefact"], b2.get("artefact")))
        if ex.get("you_by_3s") and you is not None and str(ex["you_by_3s"]).lower() != ("yes" if you else "no"):
            errs.append("experiment.you_by_3s %r but the script says %s" % (ex["you_by_3s"], "yes" if you else "no"))
        if ex.get("length_bucket") and sec is not None and ex["length_bucket"] != length_bucket(sec):
            errs.append("experiment.length_bucket %r but the script runs %.1f s = %s" % (ex["length_bucket"], sec, length_bucket(sec)))
        if ex.get("ending_type") and spoken and ex["ending_type"] != ends["type"]:
            errs.append("experiment.ending_type %r but the script ends %r" % (ex["ending_type"], ends["type"]))
    add(not errs, "experiment", ("ok: " + ", ".join("%s=%s" % (x, ex.get(x)) for x in keys)) if not errs else "; ".join(errs))
    return out


def selftest_v3():
    """Strategy v3: the good fixture must PASS every V3 rule; each bad variant must FAIL exactly the rule it breaks; an in-flight ID must only WARN."""
    import copy
    good_script = ("DPD's own chatbot called DPD the worst. If your business has a chatbot, a customer can do the same to you. "
                   "A customer asked it to swear, and it did. It then wrote a poem about how useless the company was. The screenshot reached a million people in a day. "
                   "The company switched the chatbot off within hours. If a chatbot can sack your brand in a screenshot, it isn't saving you money. "
                   "Would you let AI answer your customers? Yes or no.")
    good = {"craft": {"frame0": {"known_name": "DPD", "known_name_as": "text", "cause": "ONE SWEARING CHATBOT", "cost": "£150M"},
                      "beat2_artefact": {"artefact": "phone-screen", "at_s": 1.5, "attribution": "DPD chatbot screenshot as reported by the BBC, 18 Jan 2024"},
                      "hook": {"type": "stake-slam"},
                      "experiment": {"hook_type": "stake-slam", "beat2_artefact": "phone-screen", "you_by_3s": "yes", "brand_recognition": "household",
                                     "length_bucket": "<35", "ending_type": "verdict-question"}}}
    filler = " ".join(["The firm said the update broke a filter and that it was fixed that same morning."] * 9)

    def run(mut_c=None, mut_s=None, enforce="1"):
        c = copy.deepcopy(good)
        if mut_c: mut_c(c["craft"])
        sc = mut_s(good_script) if mut_s else good_script
        os.environ["AGMM_V3_ENFORCE"] = enforce
        return check_v3("S0", c, sc)
    bad, n = 0, 0
    r = run()
    nf = [(nm, d) for ok, nm, d, l in r if not ok]
    n += 1
    if nf: print("SELFTEST FAIL: the good V3 fixture failed %s" % nf); bad += 1
    cases = [  # (rule that must fail, what the mutation does)
        ("V3 rule2 first clause", None, lambda s: s.replace("DPD's own chatbot called DPD the worst.", "The delivery firm DPD had a chatbot that called DPD the worst.")),
        ("V3 rule2 opener", None, lambda s: "In January 2024 " + s),
        ("V3 rule2 opener", None, lambda s: "So " + s),
        ("V3 rule2 opener", None, lambda s: "This is the story of " + s),
        ("V3 rule2 opener", None, lambda s: "Walsall's " + s),
        ("V3 rule2 opener", None, lambda s: "14 March 2024. " + s),
        ("V3 rule3 you by 3s", None, lambda s: s.replace("If your business has a chatbot, a customer can do the same to you. ", "A customer could do the same to a brand. ").replace("your customers", "their customers")),
        ("V3 rule5 length", None, lambda s: s.replace("The company switched", filler + " The company switched")),
        ("V3 rule6 ending", None, lambda s: s.replace("Would you let AI answer your customers? Yes or no.", "Follow for more real AI stories.")),
        ("V3 rule6 ending", None, lambda s: s.replace("Would you let AI answer your customers? Yes or no.", "Would you let AI answer your customers? Follow for more.")),
        ("V3 rule6 ending", None, lambda s: s.replace("Would you let AI answer your customers? Yes or no.", "Think about that.")),
        ("V3 rule6 ending", None, lambda s: s.replace("If a chatbot can sack your brand in a screenshot, it isn't saving you money. ", "")),
        ("V3 rule1 frame0 (known name, small cause, huge cost)", lambda k: k["frame0"].update(known_name="he"), None),
        ("V3 rule1 frame0 (known name, small cause, huge cost)", lambda k: k["frame0"].update(known_name="Barclays"), None),
        ("V3 rule1 frame0 (known name, small cause, huge cost)", lambda k: k["frame0"].update(cost="a lot of money"), None),
        ("V3 rule1 frame0 (known name, small cause, huge cost)", lambda k: k["frame0"].update(cause="one very long and wordy cause of the whole thing"), None),
        ("V3 rule1 frame0 (known name, small cause, huge cost)", lambda k: k["frame0"].update(cause="ONE SWEARING CHATBOT WORD", cost="£150M TOTAL"), None),
        ("V3 rule1 frame0 (known name, small cause, huge cost)", lambda k: k.pop("frame0"), None),
        ("V3 rule1 beat2 artefact", lambda k: k["beat2_artefact"].update(artefact="slide"), None),
        ("V3 rule1 beat2 artefact", lambda k: k["beat2_artefact"].update(at_s=6), None),
        ("V3 rule1 beat2 artefact", lambda k: k["beat2_artefact"].update(attribution="BBC"), None),
        ("V3 rule1 beat2 artefact", lambda k: k.pop("beat2_artefact"), None),
        ("V3 experiment", lambda k: k.pop("experiment"), None),
        ("V3 experiment", lambda k: k["experiment"].update(brand_recognition=""), None),
        ("V3 experiment", lambda k: k["experiment"].update(you_by_3s="no"), None),
        ("V3 experiment", lambda k: k["experiment"].update(length_bucket=">50"), None),
        ("V3 experiment", lambda k: k["experiment"].update(ending_type="none"), None),
        ("V3 experiment", lambda k: k["experiment"].update(beat2_artefact="receipt"), None),
        ("V3 experiment", lambda k: k["experiment"].update(brand_recognition="famous"), None)]
    for rule, mc, ms in cases:
        n += 1
        r = run(mc, ms)
        hit = [x for x in r if x[1] == rule and not x[0]]
        if not hit:
            print("SELFTEST FAIL: a bad case for %s was not caught (fails: %s)" % (rule, [x[1] for x in r if not x[0]])); bad += 1
        elif rule != "V3 rule5 length" and hit[0][3] != "FAIL":
            print("SELFTEST FAIL: %s must be a FAIL when enforced, got %s" % (rule, hit[0][3])); bad += 1
    # a long script is excused by craft.length_reason, and is only ever a WARN
    n += 1
    r = run(lambda k: k.update(length_reason="the story needs both the failure and the legal outcome, so it runs long on purpose"), lambda s: s.replace("The company switched", filler + " The company switched"))
    if [x for x in r if x[1] == "V3 rule5 length" and not x[0]]: print("SELFTEST FAIL: length_reason did not excuse a long script"); bad += 1
    # the measured half of rule 1: a synthetic DOM sample at t=0 (the same shape dom_lint's raw.json has)
    def dom(texts, imgs=()):
        mk = lambda t, px, cls="x": {"t": t, "fpx": px, "op": 1, "vis": 1, "e": "div." + cls, "ink": [[100, 300, 900, 500]]}
        return {"parts": {"S0-A": {"samples": [{"t": 0, "texts": [mk(*a) for a in texts], "imgs": [{"src": i, "op": 1} for i in imgs]}]}}}
    f0 = good["craft"]["frame0"]
    GOODDOM = ([("ONE SWEARING CHATBOT", 120), ("£150M", 260), ("DPD", 90), ("BBC, 18 JAN 2024", 40), ("AI WENT WRONG", 50, "agmm-sting")], ())
    for label, texts, imgs, rule in (
            ("good DOM passes", GOODDOM[0], (), None),
            ("a logo image counts as the name", [("ONE SWEARING CHATBOT", 120), ("£150M", 260)], ("img/real-dpd-logo.svg",), None),
            ("too many readable words", GOODDOM[0] + [("AND THEN A WHOLE LONG SENTENCE ABOUT IT THAT NOBODY WILL READ IN TIME", 80)], (), "words"),
            ("no named entity visible", [("ONE SWEARING CHATBOT", 120), ("£150M", 260)], (), "name"),
            ("largest text under 200 px", [("ONE SWEARING CHATBOT", 120), ("£150M", 150), ("DPD", 90)], (), "hero"),
            ("largest text is not the figure or the turn", [("A STATEMENT ABOUT NOTHING", 260), ("£150M", 120), ("DPD", 90)], (), "hero")):
        n += 1
        os.environ["AGMM_V3_ENFORCE"] = "1"
        res = frame0_dom("S0", f0, good_script, raw=dom(texts, imgs))
        failed = [nm.split()[-1] for ok_, nm, dt in res if not ok_]
        if rule is None and failed:
            print("SELFTEST FAIL: %s but the DOM check failed %s" % (label, failed)); bad += 1
        if rule is not None and failed != [rule]:
            print("SELFTEST FAIL: %s: expected exactly [%s] to fail, got %s" % (label, rule, failed)); bad += 1
    n += 1
    ws = [x for x in frame0_dom("S0", f0, good_script, raw=dom(GOODDOM[0] + [("A MUCH LONGER SECOND LINE THAT NEEDS READING", 80)])) if not x[0]]
    if not ws:
        print("SELFTEST FAIL: the sting must be ignored but a long line must still fail"); bad += 1
    # real data (only when the dom_lint raw exists): S56 (45% held at 3 s on TikTok) passes, S72 (18%) fails on name + hero (root 19 Oct: the word limit is 12 at >=70 px, so S72's 8 words no longer fail it)
    real = {"S56": {"known_name": "Google", "known_name_as": "logo", "cause": "ONE WRONG ANSWER", "cost": "$100bn"},
            "S72": {"known_name": "Metro Bank", "cause": "HE TEXTED NO", "cost": "£14,244"}}
    for sid_, f0_ in real.items():
        if os.path.exists(os.path.join(KIT, "out", sid_, "domlint", "raw.json")):
            n += 1
            res = frame0_dom(sid_, f0_, script_text(sid_) or "")
            failed = [nm for ok_, nm, dt in res if not ok_]
            if (sid_ == "S56" and failed) or (sid_ == "S72" and not {"rule1 frame0 dom name", "rule1 frame0 dom hero"} <= set(failed)):
                print("SELFTEST FAIL: real %s should %s the frame-0 DOM check (failed: %s)" % (sid_, "pass" if sid_ == "S56" else "fail all of", failed)); bad += 1
    # overrides (coordinator, 19 Oct: the rules are strong defaults, not a cage)
    OV = lambda rule, **kw: (lambda k: k["experiment"].update(overrides=rule, hypothesis="a straight-to-camera first clause tests better than the turn", why_better="the story is the voice of the founder, the line is the artefact", **kw))
    n += 1
    long_clause = lambda s: s.replace("DPD's own chatbot called DPD the worst.", "The delivery firm DPD had a chatbot that called DPD the worst.")
    r = run(OV("rule 2"), long_clause)
    if [x for x in r if not x[0]] or not [x for x in r if x[1] == "V3 rule2 first clause" and x[3] == "INFO" and x[0]]:
        print("SELFTEST FAIL: a declared override of rule 2 must pass with an INFO note (got %s)" % [(x[1], x[0], x[3]) for x in r if not x[0] or x[3] == "INFO"]); bad += 1
    n += 1
    r = run(lambda k: k["experiment"].update(overrides="rule 2", hypothesis="x is better", why_better=""), long_clause)
    if not [x for x in r if x[1] == "V3 rule2 first clause" and not x[0]] or not [x for x in r if x[1] == "V3 experiment" and not x[0]]:
        print("SELFTEST FAIL: an override with an empty why_better must still FAIL rule 2 and be reported"); bad += 1
    n += 1
    r = run(OV("rule 3"), long_clause)
    if not [x for x in r if x[1] == "V3 rule2 first clause" and not x[0] and x[3] == "FAIL"]:
        print("SELFTEST FAIL: an override of rule 3 must not excuse rule 2"); bad += 1
    n += 1
    r = run(lambda k: (k.pop("frame0"), k.pop("beat2_artefact"), k["experiment"].update(overrides="rule 1", hypothesis="a talking-head frame 0 builds trust faster", why_better="the story is one person's account")), None)
    if [x for x in r if not x[0]] or not [x for x in r if x[1].startswith("V3 rule1 frame0") and x[3] == "INFO"]:
        print("SELFTEST FAIL: a declared override of rule 1 must pass with an INFO note (got %s)" % [(x[1], x[0], x[3]) for x in r if not x[0]]); bad += 1
    n += 1
    r = run(lambda k: k["experiment"].update(overrides=["rule 2", "rule 6"], hypothesis="h one", why_better="w one", ending_type="none"), lambda s: long_clause(s).replace("Would you let AI answer your customers? Yes or no.", "Think about that."))
    if [x for x in r if not x[0]]: print("SELFTEST FAIL: a two-rule override must pass both"); bad += 1
    # in flight: every failure must be a WARN, none a FAIL
    n += 1
    r = run(lambda k: (k.pop("frame0"), k.pop("experiment")), lambda s: "In January 2024 " + s, enforce="0")
    if not [x for x in r if not x[0]] or [x for x in r if not x[0] and x[3] == "FAIL"]: print("SELFTEST FAIL: an in-flight short must only WARN"); bad += 1
    os.environ.pop("AGMM_V3_ENFORCE", None)
    return n, bad


def selftest():
    """Good block must PASS; every bad variant must FAIL on the named rule. Exit 1 if the check cannot fail."""
    script = ("Barclays could pay up to £7.5 million for one outage. The cause was a computer most customers never knew existed. "
              "The regulator says the bank knew about the risk for years. Follow for the next real story.")
    beats = ["hook", "outage", "mainframe", "regulator", "years", "cta"]
    good = {"craft": {
        "answers": {"expert_move": "A top explainer editor would open on the regulator's own page, not on a headline, and build every beat from one of its numbered findings.",
                    "rawest_source": "FCA final notice, https://www.fca.org.uk/publication/final-notices/example.pdf paragraphs 3 to 9",
                    "methods": ["crop_clause.py on notice paragraph 4 for the quoted clause", "K.fit hero lines and AGP.motion for every enter and exit"],
                    "outside_judges": ["dom_lint legibility and frame rules on Actions", "the independent reviewer comparing with P1", "frame_fill via sheet_check"]},
        "locked_message": "The bank knew about the risk for years.",
        "banned": ["data centres full of blue light", "padlock icons", "a ticking clock", "pound-sign confetti", "robots", "glow", "mainframe cabinet cliches"],
        "central_visual_rule": "Every year the bank knew becomes one more unplugged cable on the same mainframe.",
        "beat_moves": [{"beat": b, "verb": v} for b, v in zip(beats, ["stamp", "drop", "unplug", "pin", "count", "press"])],
        "hook": {"type": "stake-slam", "t0": "BARCLAYS and 7.5 million pounds in 200 px type over a live mainframe", "t1_5": "the outage counter starts and the first cable pulls out",
                 "desired_reaction": "Wait, one old computer cost that much?"}}}
    def run(mut, expect_fail_on):
        import copy
        c = copy.deepcopy(good); mut(c["craft"])
        os.environ["AGMM_CRAFT_ENFORCE"] = "1"
        r = check("S0", c, script=script, spec=beats)
        fails = [n for ok, n, d, l in r if not ok and n.startswith("R10")]
        return fails
    bad = 0
    f = run(lambda k: None, None)
    if f: print("SELFTEST FAIL: the good block failed %s" % f); bad += 1
    cases = [("expert_move", lambda k: k["answers"].update(expert_move="be good")),
             ("rawest_source", lambda k: k["answers"].update(rawest_source="the BBC article about the outage and the fine in the news")),
             ("methods", lambda k: k["answers"].update(methods=["use tools"])),
             ("outside_judges", lambda k: k["answers"].update(outside_judges=["I will check it myself carefully", "maker review of the frames"])),
             ("locked_message", lambda k: k.update(locked_message="Synergy powers tomorrow's resilient ecosystems for everyone.")),
             ("banned", lambda k: k.update(banned=["robots", "brains", "sparkles", "glow", "neon", "bounce"])),
             ("central_visual_rule", lambda k: k.update(central_visual_rule="Make it look dynamic and modern with energy always.")),
             ("beat_moves", lambda k: k.update(beat_moves=[{"beat": b, "verb": "slide"} for b in beats])),
             ("beat_moves", lambda k: k["beat_moves"].pop()),
             ("hook type", lambda k: k["hook"].update(type="date-anchor")),
             ("hook type", lambda k: k["hook"].update(type="not-a-type")),
             ("hook type", lambda k: k["hook"].update(t0="short"))]
    for rule, mut in cases:
        fails = run(mut, rule)
        if not any(x == "R10 " + rule for x in fails):
            print("SELFTEST FAIL: a bad %s block was not caught (fails: %s)" % (rule, fails)); bad += 1
    c = {"id": "S0"}
    os.environ["AGMM_CRAFT_ENFORCE"] = "1"
    r = check("S0", c, script=script, spec=beats)
    if not any(not ok for ok, n, *_ in r if n.startswith("R10")): print("SELFTEST FAIL: a missing block was not a FAIL when enforced"); bad += 1
    os.environ["AGMM_CRAFT_ENFORCE"] = "0"
    r = check("S0", c, script=script, spec=beats)
    if any(not ok for ok, n, *_ in r if n.startswith("R10")): print("SELFTEST FAIL: a missing block must only WARN for an in-flight short"); bad += 1
    n3, b3 = selftest_v3()
    bad += b3
    print("craft_check selftest: %d R10 cases + %d strategy-v3 cases, %s" % (len(cases) + 3, n3, "ALL BEHAVE" if not bad else "%d PROBLEM(S)" % bad))
    sys.exit(1 if bad else 0)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        selftest()
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    ID = sys.argv[1]
    p = os.path.join(KIT, "specs", ID, "concept.json")
    c = json.load(open(p))
    bad = 0
    for ok, name, detail, level in check(ID, c):
        print("%-4s %s: %s" % ("ok" if ok else ("WARN" if level == "WARN" else "FAIL"), name, detail))
        bad += (not ok)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
