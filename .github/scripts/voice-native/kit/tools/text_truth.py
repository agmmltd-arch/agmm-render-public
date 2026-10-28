#!/usr/bin/env python3
"""text_truth.py: every compiled on-screen string that is not a verbatim source quote goes through the story engine's
meaning check (slate/daily/lib/meaning.py: oc-mimo-flash judge, evidence must be verbatim in a saved source).

  python3 tools/text_truth.py specs/<ID>/spec.json --sources <dir of <label>.txt> [--script shorts/scripts-v2/<ID>.md]
  python3 tools/text_truth.py --selftest --sources <dir>      # proves "HEADLINES LIE." fails

Strings checked: headlines, kickers, notes, tags, checklist rows, stat/contrast/meter labels and values, chain nodes,
board cells, flap texts, stamp/flip/event texts. Not checked: clip crops (they ARE the source), the CTA card, and the
ILLUSTRATION tags. Labels and the mechanical rules are meaning.py's own: ENTAILED needs evidence copied verbatim from
a saved source; FRAMING passes only with no number, no name and <= 14 words; NO_CLAIM only for advice to the viewer
(or a line with no number that restates the lesson). Anything else fails. Writes out/<ID>/text-truth.json.
Fails closed: if the judge is unavailable, nothing passes."""
import argparse, json, os, re, sys
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2 = os.path.dirname(KIT)
sys.path.insert(0, os.path.join(V2, "slate", "daily", "lib"))
import meaning as M       # noqa: E402
import scriptcheck as sc  # noqa: E402
import lanes              # noqa: E402
import brief as briefmod  # noqa: E402
import nums               # noqa: E402

PROMPT = M.PROMPT.replace("For EACH numbered sentence\nof the voice script below", "For EACH numbered ON-SCREEN TEXT of a news video below (headlines, labels and\ncards shown while the voice speaks; 'A / B' means A and B are on screen together, judge them together: a\nqualifier on either part counts)").replace(
    "VOICE SCRIPT (numbered sentences):", "The voice script, for context only (it is NOT evidence):\n{script}\n\nON-SCREEN TEXTS (numbered):")


def plain(s):
    return re.sub(r"\[/?[argmo]\]", "", str(s)).replace("\n", " ").strip()


def strings_of(spec):
    out = []
    def add(t, where):
        t = plain(t)
        if t and re.search(r"[A-Za-z0-9]", t) and t.upper() not in ("ILLUSTRATION",) and (t, where) not in out:
            out.append((t, where))
    for b in spec["beats"]:
        P = b["props"]
        top = [plain(it["text"]) for it in P.get("items", []) if it["kind"] in ("kicker", "headline", "note")]
        if top:   # words shown together are judged together: a kicker can carry the qualifier its headline drops
            add(" / ".join(top), "%s words on screen together" % b["id"])
        for it in P.get("items", []):
            k = it["kind"]
            if k in ("headline", "kicker", "note"):
                continue
            elif k == "tags":
                for q in it["items"]: add(q["text"], "%s tag" % b["id"])
            elif k == "checklist":
                for q in it["items"]: add(q["text"], "%s checklist" % b["id"])
            elif k == "stat":
                add(" ".join(x for x in (it.get("label"), it.get("value"), it.get("foot")) if x), "%s stat" % b["id"])
            elif k == "contrast":
                for side in ("a", "b"):
                    q = it[side]; add(" ".join(x for x in (q.get("label"), q.get("value"), q.get("foot")) if x), "%s contrast %s" % (b["id"], side))
            elif k == "chain":
                add(" -> ".join(it["nodes"]), "%s chain" % b["id"])
            elif k == "meter" and it.get("mode") != "tick":
                add(" ".join(x for x in (it.get("label"), it.get("value"), it.get("foot")) if x), "%s meter" % b["id"])
            elif k == "stamp":
                add(it["text"], "%s stamp" % b["id"])
            elif k == "pad":
                for l in it.get("lines", []): add(l, "%s pad" % b["id"])
        for a in P.get("actions", []):
            if a["do"] == "flap":
                add(a["text"], "%s flap" % b["id"])
            if a["do"] == "event":
                for kk in ("text", "front", "back"):
                    if a.get(kk): add(a[kk], "%s %s %s" % (b["id"], a["kind"], kk))
    return out


def judge(items, script_text, sources, log=None):
    pack = "\n\n".join("[%s] %s" % (s["label"], s["text"][:9000]) for s in sources)
    prompt = PROMPT.format(script=script_text[:4000], lines="\n".join("%d. %s" % (i + 1, t) for i, (t, _) in enumerate(items)), pack=pack)
    text, lane, tried, j = None, None, [], None
    for ln in M.JUDGES:
        text, lane, t = lanes.call(prompt, [ln], timeout_s=600, part="text-truth", log=log, wait_busy=600)
        tried += t
        j = briefmod.parse_json(text) if text else None
        if isinstance(j, dict) and isinstance(j.get("lines"), list):
            break
    rows, fails = [], []
    got = {}
    for l in (j or {}).get("lines", []) if isinstance(j, dict) else []:
        try:
            got[int(l.get("n"))] = l
        except (TypeError, ValueError):
            pass
    for i, (t, where) in enumerate(items):
        l = got.get(i + 1)
        row = {"n": i + 1, "text": t, "where": where}
        if not l:
            row.update(label="MISSING", why="no verdict (judge %s)" % (lane or "unavailable"))
        else:
            lab = str(l.get("label", "")).upper().replace(" ", "_"); ev = str(l.get("evidence", "") or "")
            row.update(label=lab, evidence=ev, why=l.get("why", ""))
            if lab == "ENTAILED":
                parts = [p for p in re.split(r"\s*\.\.\.\s*|\s*…\s*", ev) if len(p.strip()) > 8]
                if not (parts and all(any(sc.lnorm(p) in s["text_l"] or M.near_verbatim(p, s["text_l"]) for s in sources) for p in parts)):
                    row.update(label="UNSUPPORTED", why="evidence not verbatim in any saved source")
            elif lab == "FRAMING":
                names = [w for k, w in enumerate(re.findall(r"[A-Za-z][\w'-]*", t)) if k and w[0].isupper() and not t.isupper()]
                if nums.values(t) or names or len(sc.words(t)) > 14:
                    row.update(label="NOT_ENTAILED", why="called FRAMING but carries a number, a name or 15+ words")
                else:
                    row["label"] = "NO_CLAIM"
            elif lab == "NO_CLAIM":
                advice = re.search(r"\b(you|your|pick|put|check|ask|start|try)\b", t, re.I)
                if nums.values(t) or not advice:
                    row.update(label="NOT_ENTAILED", why="called NO_CLAIM but it is a factual line: " + str(row.get("why", "")))
        if row["label"] not in ("ENTAILED", "NO_CLAIM"):
            fails.append("TEXT %s [%s]: %r (%s)" % (row["label"], where, t, str(row.get("why", ""))[:140]))
        rows.append(row)
    return {"lane": lane, "tried": tried, "rows": rows, "fails": fails, "pass": bool(j) and not fails, "raw": (text or "")[:4000]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", nargs="?"); ap.add_argument("--sources", required=True); ap.add_argument("--script"); ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sdir = a.sources if os.path.isabs(a.sources) else next((d for d in (os.path.abspath(a.sources), os.path.join(KIT, a.sources), os.path.join(V2, a.sources)) if os.path.isdir(d)), a.sources)
    sources = sc.load_sources(sdir)
    if not sources:
        sys.exit("text_truth: no sources in %s" % a.sources)
    script_text = open(os.path.join(V2, a.script)).read() if a.script else ""
    if a.selftest:
        items = [("HEADLINES LIE.", "selftest planted"), ("35% OF UK FIRMS USE AI", "selftest true"), ("ONLY 1 IN 10 USE IT EXTENSIVELY", "selftest true")]
        r = judge(items, script_text, sources)
        for row in r["rows"]:
            print("%-14s %-36s %s" % (row["label"], row["text"], str(row.get("why", ""))[:90]))
        planted = r["rows"][0]["label"] not in ("ENTAILED", "NO_CLAIM")
        print("SELFTEST %s: the planted line %s" % ("PASS" if planted else "FAIL", "failed as it must" if planted else "passed (the check is blind)"))
        sys.exit(0 if planted else 1)
    spec = json.load(open(a.spec))
    items = strings_of(spec)
    r = judge(items, script_text, sources)
    out = os.path.join(KIT, "out", spec["id"]); os.makedirs(out, exist_ok=True)
    json.dump(dict(r, id=spec["id"], n=len(items)), open(os.path.join(out, "text-truth.json"), "w"), indent=1)
    for f in r["fails"]:
        print(f)
    print("text-truth %s: %d strings, %d failed (judge %s)" % ("PASS" if r["pass"] else "FAIL", len(items), len(r["fails"]), r["lane"]))
    sys.exit(0 if r["pass"] else 1)


if __name__ == "__main__":
    main()
