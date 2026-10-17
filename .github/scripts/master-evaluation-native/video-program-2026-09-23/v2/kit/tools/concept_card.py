#!/usr/bin/env python3
"""concept_card.py: the concept-first gate (VARIETY for root, 13 Oct 2026).

Why: 60% of storyboard returns are concept-level (sameness, the same world, the same prop on every beat), and they were caught
only after a full build and 25-40 snap rounds. A concept card costs minutes to write and minutes to judge.

Card     : specs/<ID>/concept.json + specs/<ID>/CONCEPT-CARD.md, one page with ONE table, a row per beat:
           | beat | hero object | scale | ground | props | source treatment |
           scale = share of the frame the hero fills, e.g. 70% (the bar is >= 60%).
States   : registry/concept-cards/<ID>.json history: concept_submitted -> concept_approved | concept_returned
Applies  : only to IDs whose queue.json claim is at or after registry/concept-gate.json live_from AND that have never had a
           storyboard submitted (a short already past this point skips it). AGMM_CONCEPT_GATE_FORCE=1 forces it (tests, proofs);
           registry/concept-gate.off turns it off.
Enforced : storyboard.py submit and precheck_all refuse a gated ID until the card is concept_approved AND concept.json and the
           card still hash to what the reviewer approved.

  concept_card.py submit <ID> [--card PATH]   card checks + concept_check (reservations, R8 props, R9 images) -> concept_submitted
  concept_card.py review <ID>                  reviewer digest: card, checks, the window's worlds/props, hook tiles of the window
  concept_card.py approve <ID> "<what you compared and why>"   (AGMM_REVIEWER=1, AGMM_REVIEWER_NAME, never the maker)
  concept_card.py return  <ID> "<the one defect that matters and the fix>"
  concept_card.py status <ID> | gate <ID>     gate exits 1 when a build is not allowed yet
"""
import contextlib, datetime, fcntl, functools, hashlib, json, os, re, sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(KIT, "registry")
GATE_CFG = os.path.join(REG, "concept-gate.json")
OFF = os.path.join(REG, "concept-gate.off")
COLS = ["beat", "hero object", "scale", "ground", "props", "source treatment"]
MIN_ROWS = 6
SCALE_MIN = 60
SAME_HERO_MAX = 0.4


def cards_dir():
    return os.environ.get("AGMM_CONCEPT_CARDS_DIR") or os.path.join(REG, "concept-cards")


def now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def card_path(ID, override=None):
    return override or os.environ.get("AGMM_CONCEPT_CARD_PATH") or os.path.join(KIT, "specs", ID, "CONCEPT-CARD.md")


def sha(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
    except OSError:
        return None


def load_rec(ID):
    p = os.path.join(cards_dir(), ID + ".json")
    return json.load(open(p)) if os.path.exists(p) else {"id": ID, "state": None, "history": []}


def save_rec(rec):
    os.makedirs(cards_dir(), exist_ok=True)
    p = os.path.join(cards_dir(), rec["id"] + ".json")
    tmp = p + ".tmp-%d" % os.getpid()
    json.dump(rec, open(tmp, "w"), indent=1)
    os.replace(tmp, p)


def add_state(ID, state, **kw):
    rec = load_rec(ID)
    row = dict(at=now(), state=state, **kw)
    rec["history"].append(row)
    rec.update(state=state, updated=row["at"])
    if state == "concept_submitted":
        rec.update(submitted=row["at"], maker=kw.get("maker"), card=kw.get("card"), required=kw.get("required", False))
        for k in ("by", "notes", "decided"):
            rec.pop(k, None)
    elif state in ("concept_approved", "concept_returned"):
        rec.update(by=kw["by"], notes=kw["note"], decided=row["at"])
    save_rec(rec)
    return rec


def owner_edit(fn):
    """One native concept-record writer at a time; review/status/gate stay read-only."""
    @functools.wraps(fn)
    def wrapped(ID, *args, **kwargs):
        os.makedirs(cards_dir(), exist_ok=True)
        with open(os.path.join(cards_dir(), ID + ".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return fn(ID, *args, **kwargs)
    return wrapped


@contextlib.contextmanager
def claim_commit():
    """Use queue.py's actual lock for the final read+record commit; never rewrite the queue.

    Writers already hold the per-card lock; read-only reconciliation never edits it.
    Native checks/reservation edits finish before this short queue critical section;
    no queue writer takes the card lock.
    """
    import concept_reserve as cr
    os.makedirs(os.path.dirname(cr.QUEUE), exist_ok=True)
    with open(cr.QUEUE + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def claim_identity(claim):
    return (claim.get("state"), claim.get("writer"),
            claim.get("concept_claimed_at") or claim.get("claimed_at") or claim.get("at"),
            claim.get("claimed_at"))


def source_producers(rec, hashes=None):
    """Recorded source producers; optional hashes select one exact source version.

    A different queue submitter does not become the author of unchanged bytes.
    Prior producers remain participants in this ID and cannot become its independent
    reviewer by editing/reverting bytes. Exact-version attribution also keeps older
    receipts which predate the explicit producers field.
    """
    last = (rec.get("history") or [{}])[-1]
    producers = []
    def keep(name):
        name = name.strip() if isinstance(name, str) else ""
        if name and name.lower() not in [p.lower() for p in producers]:
            producers.append(name)
    for row in rec.get("history", []):
        if row.get("state") == "concept_submitted" and (hashes is None or (row.get("concept_sha"), row.get("card_sha")) == hashes):
            keep(row.get("maker"))
            for name in row.get("producers", []):
                keep(name)
    if hashes is None or (last.get("concept_sha"), last.get("card_sha")) == hashes:
        keep(rec.get("maker"))
    return producers


def enabled():
    if os.path.exists(OFF):
        return False
    if os.environ.get("AGMM_CONCEPT_GATE_FORCE") == "1":
        return True
    try:
        lf = json.load(open(GATE_CFG)).get("live_from")
        return bool(isinstance(lf, str) and datetime.datetime.strptime(lf, "%Y-%m-%dT%H:%M:%S"))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def applies(ID):
    """Only new claims, with a stable first claim time; old storyboards keep their path."""
    if not enabled():
        return False, "gate off or not live (registry/concept-gate.json / concept-gate.off)"
    if os.environ.get("AGMM_CONCEPT_GATE_FORCE") == "1":
        return True, "forced (AGMM_CONCEPT_GATE_FORCE=1)"
    try:
        sb = json.load(open(os.path.join(REG, "storyboards", ID + ".json")))
    except (OSError, ValueError):
        sb = {}
    if sb.get("state") in ("submitted", "approved", "returned", "concept_submitted", "concept_approved", "concept_returned") or any(h.get("state") == "submitted" for h in sb.get("history", [])):
        return False, "already past the concept point (existing storyboard)"
    if load_rec(ID).get("required"):
        return True, "this native concept handoff already requires review"
    lf = json.load(open(GATE_CFG))["live_from"]
    import concept_reserve as cr
    e = cr.claim_of(ID)
    if not e:
        return False, "not claimed yet"
    at = e.get("concept_claimed_at") or e.get("claimed_at") or e.get("at")
    if not at:
        return True, "claim timestamp missing: concept approval required"
    return (True, "first claimed %s, after gate live %s" % (at, lf)) if at >= lf else (False, "first claimed before gate live (%s)" % lf)


def source_matches(ID, rec=None, card=None):
    rec = rec or load_rec(ID)
    last = (rec.get("history") or [{}])[-1]
    stored = rec.get("card") or last.get("card")
    card = card_path(ID, card or (os.path.join(KIT, stored) if stored and not os.path.isabs(stored) else stored))
    return (sha(os.path.join(KIT, "specs", ID, "concept.json")), sha(card)) == (last.get("concept_sha"), last.get("card_sha")) and bool(last.get("concept_sha") and last.get("card_sha"))


def recorded_card(ID, rec, override=None):
    stored = rec.get("card") or next((h.get("card") for h in reversed(rec.get("history", [])) if h.get("card")), None)
    return card_path(ID, override or (os.path.join(KIT, stored) if stored and not os.path.isabs(stored) else stored))


def gate_ok(ID, card=None):
    ap, why = applies(ID)
    if not ap:
        return True, "concept gate does not apply: " + why
    rec = load_rec(ID)
    if rec.get("state") != "concept_approved":
        return False, "concept card is %s: submit it (concept_card.py submit %s) and wait for concept_approved before any build" % (rec.get("state") or "not submitted", ID)
    last = [h for h in rec["history"] if h["state"] == "concept_approved"][-1]
    if not source_matches(ID, rec, card):
        return False, "concept.json or the card changed after concept_approved (%s): resubmit the card" % last["at"]
    return True, "concept_approved %s by %s" % (last["at"], last.get("by"))


# ---------------------------------------------------------------------------------------------------- card checks
def parse_card(text):
    rows, head = [], None
    for l in text.splitlines():
        if not l.strip().startswith("|"):
            continue
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if head is None:
            if [c.lower() for c in cells][:6] == COLS:
                head = cells
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        rows.append(dict(zip(COLS, cells + [""] * 6)))
    return head, rows


def card_checks(ID, card, concept):
    out = []
    add = lambda ok, name, detail, lvl="FAIL": out.append({"ok": bool(ok), "name": name, "detail": detail, "level": lvl})
    if not os.path.exists(card):
        add(False, "C0 card exists", "%s is missing: one table, a row per beat: | %s |" % (card, " | ".join(COLS)))
        return out, []
    head, rows = parse_card(open(card).read())
    add(head is not None and len(rows) >= MIN_ROWS, "C0 one table, a row per beat",
        "%d beat rows (need >= %d) under the header | %s |" % (len(rows), MIN_ROWS, " | ".join(COLS)))
    empty = ["%s:%s" % (r["beat"], k) for r in rows for k in COLS if not r[k]]
    add(not empty, "C1 every cell filled", "empty: " + ", ".join(empty[:6]) if empty else "all filled")
    small = []
    for r in rows:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", r["scale"])
        if not m or float(m.group(1)) < SCALE_MIN:
            small.append("%s (%s)" % (r["beat"], r["scale"] or "-"))
    add(not small, "C2 hero fills >= %d%% of the frame on every beat" % SCALE_MIN, "under the bar: " + ", ".join(small[:6]) if small else "every beat >= %d%%" % SCALE_MIN)
    body = [r for r in rows if not re.match(r"cta", r["beat"], re.I)]
    norm = lambda s: re.sub(r"[^a-z ]", "", s.lower()).strip()
    heroes = {}
    for r in body:
        heroes.setdefault(norm(r["hero object"]), []).append(r["beat"])
    top = max(heroes.items(), key=lambda kv: len(kv[1])) if heroes else ("", [])
    share = len(top[1]) / float(max(1, len(body)))
    add(share <= SAME_HERO_MAX, "C3 no hero object on more than %d%% of beats" % (100 * SAME_HERO_MAX),
        "%r is the hero on %d of %d beats (%s): the S50 / S85 / S88 / S104 return ('the same prop on every beat')" % (top[0], len(top[1]), len(body), ",".join(top[1][:8]))
        if share > SAME_HERO_MAX else "most repeated hero %r on %d of %d" % (top[0], len(top[1]), len(body)), "WARN" if share > SAME_HERO_MAX else "FAIL")
    if concept:
        import concept_check as cc
        g = cc.ground_bucket(concept["ground"]["hex"]).split("-")[0]
        said = [r for r in rows if g in r["ground"].lower() or concept["ground"]["hex"].lower() in r["ground"].lower()]
        add(True, "C4 card grounds vs concept.json", "%d of %d rows name the concept ground (%s %s); declared beats_fraction %.2f" % (
            len(said), len(rows), concept["ground"]["hex"], g, concept["ground"]["beats_fraction"]), "FAIL")
    return out, rows


def render_checks(rows):
    return "\n".join("  [%s] %s: %s" % ("ok  " if x["ok"] else ("WARN" if x["level"] == "WARN" else "FAIL"), x["name"], x["detail"]) for x in rows)


# ---------------------------------------------------------------------------------------------------- commands
@owner_edit
def cmd_submit(ID, card=None):
    import concept_check as cc, concept_reserve as cr
    claim = cr.claim_of(ID) or {}
    maker = claim.get("writer")
    claimed = claim_identity(claim)
    if not maker or (os.environ.get("AGMM_MAKER") and os.environ["AGMM_MAKER"].lower() != str(maker).lower()):
        print("REFUSED: submit through the current native queue claim owner")
        return 1
    card = card_path(ID, card)
    initial = (sha(os.path.join(KIT, "specs", ID, "concept.json")), sha(card))
    concept = cc.load_concept(ID)
    checks, rows = card_checks(ID, card, concept)
    ok_c, text, rep = cc.check_for_submit(ID)
    print(render_checks(checks))
    print(text)
    hard = [x["name"] for x in checks if not x["ok"] and x["level"] == "FAIL"] + rep.get("failed", [])
    if hard:
        print("concept card %s REFUSED (fix and resubmit): %s" % (ID, "; ".join(hard)))
        return 1
    with claim_commit():
        if initial != (sha(os.path.join(KIT, "specs", ID, "concept.json")), sha(card)) or claim_identity(cr.claim_of(ID) or {}) != claimed:
            print("REFUSED: source or native claim changed during submit")
            return 1
        current = load_rec(ID)
        if current.get("state") in ("concept_submitted", "concept_approved") and source_matches(ID, current, card):
            print("concept card %s: unchanged %s retained" % (ID, current["state"]))
            return 0
        producers = source_producers(current, initial) or [maker]
        add_state(ID, "concept_submitted", maker=producers[0], producers=producers, submitter=maker,
                  required=applies(ID)[0], concept_sha=initial[0], card_sha=initial[1],
                  card=os.path.relpath(card, KIT) if card.startswith(KIT) else card, concept_check=rep["verdict"],
                  warns=[x["name"] for x in checks if not x["ok"]] + [x["name"] for x in rep["checks"] if not x["ok"]],
                  window=[w["id"] for w in rep.get("window", [])], reserved=[r["id"] for r in rep.get("reserved", [])])
    print("concept card %s: concept_submitted. A reviewer runs: python3 tools/concept_card.py review %s" % (ID, ID))
    return 0


def window_strip(ID, win, out):
    """Metadata-only references; image creation/decoding belongs on approved hosted compute."""
    return [os.path.join(REG, "storyboards", sid + "-storyboard.jpg") for sid in win
            if os.path.isfile(os.path.join(REG, "storyboards", sid + "-storyboard.jpg"))]


def cmd_review(ID, card=None):
    import concept_check as cc, prop_reuse as pr
    rec = load_rec(ID)
    card = recorded_card(ID, rec, card)
    print("CONCEPT CARD %s: state %s; gate: %s" % (ID, rec.get("state"), gate_ok(ID, card)[1]))
    concept = cc.load_concept(ID) or {}
    print("world: %s (%s) | ground %s x%.2f | hero %s | hook %s | signature %s on %r | sources %s | bed %s" % (
        concept.get("world", {}).get("name"), concept.get("world", {}).get("world_family"), concept.get("ground", {}).get("hex"),
        concept.get("ground", {}).get("beats_fraction", 0), concept.get("hero_device"), concept.get("hook_mechanic"),
        concept.get("signature", {}).get("mechanism"), concept.get("signature", {}).get("word"), concept.get("source_presentation"),
        concept.get("bed", {}).get("id")))
    print("\n--- the card (%s)" % card)
    print(open(card).read() if os.path.exists(card) else "(missing)")
    checks, _ = card_checks(ID, card, concept)
    rep = cc.run(ID, T=cc.grandfather_time(ID))
    text = cc.render(rep)
    print("--- card checks\n" + render_checks(checks))
    print("--- concept_check (approved window + live reservations, R8 props, R9 images)\n" + text)
    print("--- the window: what yours must not look like")
    for w in rep.get("window", []):
        o = cc.load_concept(w["id"]) or {}
        a, cnt, wp, fam = pr.props_of(w["id"])
        d = cc.distance(concept, o)[1] if concept and o else []
        print("  %-5s %-16s %-28s ground %-8s hero %-18s same axes as yours: %-40s props: %s" % (
            w["id"], fam, (o.get("world", {}).get("name") or "")[:28], o.get("ground", {}).get("hex"), o.get("hero_device"),
            ",".join(d) or "-", ",".join(sorted(p for p, n in cnt.items() if n >= 2))[:60]))
    strip = window_strip(ID, [w["id"] for w in rep.get("window", [])], os.path.join(KIT, "out", ID, "concept-card", "window-hooks.jpg"))
    print("--- LOOK via approved hosted/source review: window storyboard paths, newest first: %s" % (strip or "(no sheets)"))
    print("Judge in minutes: would a viewer who saw the window think yours is a new world? Is any hero repeated across beats? "
          "Then: AGMM_REVIEWER=1 AGMM_REVIEWER_NAME=<you> python3 tools/concept_card.py approve|return %s \"<note>\"" % ID)
    return 0


@owner_edit
def cmd_decide(ID, state, note, card=None):
    import concept_reserve as cr
    if os.environ.get("AGMM_REVIEWER") != "1":
        print("REFUSED: only a reviewer (AGMM_REVIEWER=1) decides a concept card")
        return 1
    by = (os.environ.get("AGMM_REVIEWER_NAME") or "").strip() or (os.environ.get("USER") or "").strip()
    if not by:
        print("REFUSED: a nonempty independent reviewer identity is required")
        return 1
    e = cr.claim_of(ID) or {}
    claim_owner = claim_identity(e)
    if not e:
        print("REFUSED: the submitted concept needs its native queue claim")
        return 1
    if e.get("writer") and by.lower() == str(e["writer"]).strip().lower():
        print("REFUSED: %s is the maker of %s; a maker never approves their own card" % (by, ID))
        return 1
    rec = load_rec(ID)
    if by and by.lower() in [p.lower() for p in source_producers(rec)]:
        print("REFUSED: the recorded concept producer cannot review their own submission")
        return 1
    if rec.get("state") != "concept_submitted":
        print("REFUSED: %s card is %s, not concept_submitted" % (ID, rec.get("state")))
        return 1
    last = (rec.get("history") or [{}])[-1]
    if state == "concept_approved" and not source_producers(rec, (last.get("concept_sha"), last.get("card_sha"))):
        print("REFUSED: the submitted source has no recorded producer provenance")
        return 1
    if len(note or "") < 40:
        print("REFUSED: write what you compared and why (40+ characters)")
        return 1
    card = recorded_card(ID, rec, card)
    c_now, k_now = sha(os.path.join(KIT, "specs", ID, "concept.json")), sha(card)
    if (c_now, k_now) != (last.get("concept_sha"), last.get("card_sha")):
        print("REFUSED: the card or concept.json changed since it was submitted; the maker resubmits")
        return 1
    if state == "concept_approved":
        import concept_check as cc
        checks, _ = card_checks(ID, card, cc.load_concept(ID))
        ok, text, rep = cc.check_for_submit(ID)
        if not ok or any(not x["ok"] and x["level"] == "FAIL" for x in checks):
            print("REFUSED: current native card/variety/reservation checks no longer pass\n" + text)
            return 1
        if (c_now, k_now) != (sha(os.path.join(KIT, "specs", ID, "concept.json")), sha(card)):
            print("REFUSED: concept/card changed while the review decision was checked")
            return 1
    with claim_commit():
        if claim_owner != claim_identity(cr.claim_of(ID) or {}):
            print("REFUSED: the native claim owner changed during the decision")
            return 1
        if (c_now, k_now) != (sha(os.path.join(KIT, "specs", ID, "concept.json")), sha(card)):
            print("REFUSED: concept/card changed before the decision commit")
            return 1
        add_state(ID, state, by=by, note=note, concept_sha=c_now, card_sha=k_now)
    print("%s %s by %s" % (ID, state, by))
    return 0


def main():
    a = sys.argv[1:]
    card = None
    if "--card" in a:
        i = a.index("--card")
        card = a[i + 1]
        del a[i:i + 2]
    if len(a) < 2:
        print(__doc__)
        return 2
    cmd, ID = a[0], a[1]
    if cmd == "submit":
        return cmd_submit(ID, card)
    if cmd == "review":
        return cmd_review(ID, card)
    if cmd in ("approve", "return"):
        return cmd_decide(ID, "concept_approved" if cmd == "approve" else "concept_returned", " ".join(a[2:]), card)
    if cmd == "status":
        print(json.dumps(load_rec(ID), indent=1))
        return 0
    if cmd == "gate":
        ok, why = gate_ok(ID, card)
        print(("ALLOWED: " if ok else "REFUSED: ") + why)
        return 0 if ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
