#!/usr/bin/env python3
"""The ONLY way to change v2/qa/cards.json (the review page's list).
Usage: card.py upsert <card.json | '{"id":...}'>  |  card.py remove <id>  |  card.py check
Validates required fields, file paths and JSON, then writes atomically. A hand edit once left a nested
quote in the file and the review page silently showed 0 videos (24 Sep); this cannot."""
import json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # build root
P = os.path.join(ROOT, "v2/qa/cards.json")
REQ = ["id", "section", "title", "platform", "platform_why", "reference", "reference_url", "status", "src", "type", "poster"]

def fleet_taste_approval_error(previous, incoming, env):
    """Fleet machine assessments cannot grant or rebind an operator taste approval.

    Preserve unchanged approved cards during metadata-only updates. A changed
    source/poster/title/choice requires a new independent review. Only an actual
    non-free native Codex Sol reviewer profile may approve within a fleet lane;
    the operator outside fleet still owns the normal manual review path.
    """
    if not env.get("FLEET_LANE"):
        return None
    status = str(incoming.get("status") or "").strip().lower()
    if not status.startswith(("approved", "ready to post", "ready-to-post", "release approved")):
        return None
    review_fields = ("status", "src", "poster", "title", "thumbnail_choice")
    if previous is not None and all(previous.get(k) == incoming.get(k) for k in review_fields):
        return None
    model = str(env.get("FLEET_MODEL_FLAG") or "").rsplit("/", 1)[-1].lower()
    sol_reviewer = (env.get("FLEET_LANE_KIND") == "codex"
                    and model in ("gpt-6-sol", "gpt-6.1-sol")
                    and env.get("FLEET_FREE_ONLY") != "1")
    if sol_reviewer:
        return None
    return ("Fleet machine assessments cannot grant or rebind taste approval. "
            "Keep the card pending or returned for independent operator gpt-sol review.")


def validate(cards, files_for=None):
    """files_for: only these ids get the on-disk src/poster check (Claude 5 Oct: one stale card, S56's archived web copy,
    blocked EVERY master pass; structure, ids, references and em dashes are still checked for all cards)."""
    errs = []; seen = set()
    for c in cards:
        cid = c.get("id", "?")
        for k in REQ:
            if not c.get(k): errs.append("%s: missing %s" % (cid, k))
        if c.get("section") not in ("shortform", "longform"): errs.append("%s: section must be shortform|longform" % cid)
        for k in ("src", "poster"):
            if (files_for is None or cid in files_for) and c.get(k) and not os.path.exists(os.path.join(ROOT, c[k])):
                errs.append("%s: %s not on disk: %s" % (cid, k, c[k]))
        if cid in seen: errs.append("%s: duplicate id" % cid)
        seen.add(cid)
        for r in c.get("references", []):
            if not (r.get("label") and str(r.get("url", "")).startswith("http")): errs.append("%s: reference needs label + http url" % cid)
        blob = json.dumps(c, ensure_ascii=False)
        if "—" in blob: errs.append("%s: em dash in card text" % cid)
    return errs

def write(cards, files_for=None):
    errs = validate(cards, files_for)
    if errs: sys.exit("REFUSED, cards.json unchanged:\n  " + "\n  ".join(errs))
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(P))
    with os.fdopen(fd, "w") as f: json.dump(cards, f, indent=1, ensure_ascii=False)
    json.load(open(tmp)); os.replace(tmp, P)

cards = json.load(open(P))
if sys.argv[1] == "check":
    e = validate(cards); print("OK %d cards" % len(cards) if not e else "\n".join(e)); sys.exit(1 if e else 0)
if sys.argv[1] == "remove":
    keep = [c for c in cards if c["id"] != sys.argv[2]]
    if len(keep) == len(cards): sys.exit("no card %s" % sys.argv[2])
    write(keep, set()); print("removed %s (%d cards)" % (sys.argv[2], len(keep))); sys.exit(0)
if sys.argv[1] == "upsert":
    a = sys.argv[2]; new = json.load(open(a)) if os.path.exists(a) else json.loads(a)
    previous = next((c for c in cards if c["id"] == new["id"]), None)
    approval_error = fleet_taste_approval_error(previous, new, os.environ)
    if approval_error:
        sys.exit("REFUSED, cards.json unchanged: " + approval_error)
    cards = [c for c in cards if c["id"] != new["id"]] + [new]
    order = {"longform": 0, "shortform": 1}
    write(cards, {new["id"]}); print("upserted %s (%d cards)" % (new["id"], len(cards)))
