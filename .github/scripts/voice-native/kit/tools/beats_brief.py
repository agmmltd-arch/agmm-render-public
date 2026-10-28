#!/usr/bin/env python3
"""beats_brief.py: the one-shot briefs a free lane needs to plan, fill and revise specs/<ID>/beats.json with no file
access (lanes are one-shot; everything they need is pasted in).

  beats_brief.py plan   --id X12 --script shorts/scripts-v2/S02.md --voice shorts/voice/S02 --sources specs/X12/sources.js [--route-as S02]
  beats_brief.py fill   ... --plan specs/X12/plan.json
  beats_brief.py revise ... --beats specs/X12/beats.json --findings findings.json

Every brief carries the parts CATALOGUE, the spoken script sentence by sentence with every word's only valid reference
and each sentence's [start], the fact ledger, and the real sources with ONLY the phrases that exist on each crop
(tools/sources_from_media.py). The fill brief adds one worked example and the checked plan; the revise brief adds the
compiled short's findings (compose.py warnings + the free vision review) and asks for the whole revised file."""
import argparse, json, os, re, sys
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2 = os.path.dirname(KIT)
sys.path.insert(0, KIT)
import build_short as BS  # noqa: E402


def rel(p, base):
    return p if os.path.isabs(p) else os.path.join(base, p)


def story(a):
    vid = os.path.basename(a.voice.rstrip("/"))
    wpath = os.path.join(rel(a.voice, V2), vid + ".words.json")
    words = BS.load_words(wpath)
    seen, sents, cur = {}, [], []
    for w in words:
        k = BS.norm(w["word"]); seen[k] = seen.get(k, 0) + 1
        cur.append((w["word"], "@%s%s" % (k, "#%d" % seen[k] if seen[k] > 1 else ""), w["start"]))
        if re.search(r"[.!?]$", w["word"]):
            sents.append(cur); cur = []
    if cur:
        sents.append(cur)
    lines = ["S%d [start %s, %.2f s] %s" % (i + 1, s[0][1] if i else "(hook: no start)", s[0][2], " ".join("%s(%s)" % (w, r) for w, r, _ in s))
             for i, s in enumerate(sents)]
    script = open(rel(a.script, V2)).read()
    ledger = script.split("## Fact ledger")[1].split("\n## ")[0].strip() if "## Fact ledger" in script else "(see the script)"
    t = open(rel(a.sources, KIT)).read()
    items = json.loads(t[t.index("{"):t.rindex("}") + 1]).get("items", {})
    said = {BS.norm(w["word"]) for w in words}
    def spoken_score(ph):
        toks = [BS.norm(t) for t in ph.split()]
        return sum(1 for t in toks if t in said and (len(t) > 3 or re.search(r"\d", t))) / max(1.0, len(toks) ** 0.5)
    src = []
    for k, v in items.items():
        if v.get("css"):
            ph = sorted(v.get("marks") or {}, key=lambda p: (-spoken_score(p), len(p)))
            ph = [p for p in ph if spoken_score(p) > 0][:24]
            if not ph:
                continue                      # a crop that shares nothing with the voice is not offered
            src.append("- %s: the real page, credited %s, %s. Page text: \"%s\"\n  Phrases you may mark (copy one exactly; the voice says these words): %s" % (
                k, v.get("credit"), v.get("date"), (v.get("text") or "")[:360], json.dumps(ph)))
        else:
            src.append("- %s: a logo image (use it in a chip, or a board cell {\"logo\": \"%s\"})" % (k, k))
    top = {"id": a.id, "voice": {"wav": os.path.relpath(os.path.join(rel(a.voice, V2), vid + ".wav"), V2), "words": os.path.relpath(wpath, V2)},
           "sources": os.path.relpath(rel(a.sources, KIT), KIT), "music": {"bed": a.bed}, "script": {"id": vid, "file": os.path.relpath(rel(a.script, V2), V2)}}
    if a.route_as:
        top["route_as"] = a.route_as
    if a.scratch:
        top["reproduction_of"] = "%s embodiment test (scratch; never rendered or posted)" % vid
    return {"lines": lines, "ledger": ledger, "src": src, "top": top, "cta": sents[-1][0][1], "n": len(sents)}


HEAD = """You are a video maker for AGMM. You write JSON only; you never write code. A compiler turns your JSON into the
animation. The craft (layout, motion, sound, platform safe zones) is built into its parts, and the compiler REFUSES
anything that breaks a rule. Your job is the story: which part shows which fact on which spoken word, in one
constructed world the camera travels, with one physical signature event that IS the story.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["plan", "fill", "revise"])
    ap.add_argument("--id", required=True); ap.add_argument("--script", required=True); ap.add_argument("--voice", required=True)
    ap.add_argument("--sources", required=True); ap.add_argument("--example", default="specs/X02/beats.json")
    ap.add_argument("--bed", default="ic_presenterator"); ap.add_argument("--scratch", action="store_true"); ap.add_argument("--route-as")
    ap.add_argument("--plan"); ap.add_argument("--beats"); ap.add_argument("--findings")
    a = ap.parse_args()
    S = story(a)
    cat = open(os.path.join(KIT, "lib", "parts", "CATALOGUE.md")).read()
    body = "\n=========== CATALOGUE ===========\n%s\n=========== THE STORY ===========\nThe voice is recorded. Sentence by sentence; every word carries the ONLY reference you may use for it.\n%s\n\nFact ledger (the only facts you may show):\n%s\n\nReal sources:\n%s\n" % (
        cat, "\n".join(S["lines"]), S["ledger"], "\n".join(S["src"]))
    sys.path.insert(0, os.path.join(KIT, "tools"))
    import compose as C
    FR = C.load_frame(a.route_as) if a.route_as else dict(C.FALLBACK_FRAME)
    width = (C.right_limit(FR, FR["SAFE"]["y0"], FR["SAFE"]["y0"] + 500) - FR["SAFE"]["x0"]) / 1.035
    caps = ", ".join("%s %d" % (lk, C.line_cap(lk, width)) for lk in C.FONTS)
    body += "\nHEADLINE SIZE: hero text renders at 150-250 px, so a headline line holds at most this many characters (by look): %s. 1 to 3 lines. A longer line fails.\n" % caps
    if a.mode == "plan":
        print(HEAD + body + """
=========== RETURN: THE PLAN ONLY ===========
Return ONLY a JSON plan inside one ```json block, no other text, no reasoning. Every beat except the cta has a
"headline": its hero words, short enough for the size rule below. Build the world from the WORLD BANK in the catalogue
(ticketline, pipes, mailroom, screens, departures, floorplan, pinmap): pick the one or two that ARE this story.
{"look": "<paper|night|blueprint|leather>", "signature_concept": "<one line>",
 "world": [<1 to 3 stations, full definitions as in the catalogue>],
 "beats": [{"id": "hook", "lead": "...", "why": "...", "lands_on": "@word"},
           {"id": "<name>", "start": "<a [start] ref from the story>", "lead": "...", "headline": "<2 TO 4\\nWORDS A LINE>", "why": "...", "lands_on": "@word", "lands_on2": "@word"},
           ...,
           {"id": "cta", "start": "%s", "lead": "cta", "why": "the spoken call to action", "lands_on": "@word"}]}
12 to 16 beats, one sentence each (%d sentences in the story); each start is its sentence's [start] ref; lands_on is
the word the beat's main moment lands on, inside that sentence. Leads: vary them (no lead on more than 35%% of beats)
and put at least one "event:<name>" where the story turns. The hook's frame 0 already shows the number even when the
voice says it a sentence later (its lands_on may be that number's word, up to 9 s in).""" % (S["cta"], S["n"]))
    elif a.mode == "fill":
        plan = open(rel(a.plan, KIT)).read()
        ex = open(rel(a.example, KIT)).read()
        print(HEAD + body + """
=========== AN APPROVED SHORT, RE-EXPRESSED (the format; not your story) ===========
%s
=========== YOUR CHECKED PLAN ===========
%s
=========== RETURN: beats.json ===========
Fill the plan beat for beat. Return ONLY the JSON inside one ```json block, no other text. Use exactly these values:
%s
plus "title", "look", "signature_concept", "world" (from the plan) and "beats". Rules the compiler enforces: every
headline 110 px or more (about 12 characters a line, at most 3 lines); top words = a kicker and ONE headline; every
beat's world + clip + cards fill 55%% of the frame (so keep a camera on a station in almost every beat); every clip
marks one phrase copied from its crop's list; cards always show their value; no number that is not in the story;
nothing over 6 s without a new part, mark or action; frame 0 shows the number; the cta line is the spoken line.""" % (
            ex, plan, json.dumps(S["top"])[1:-1]))
    else:
        cur = open(rel(a.beats, KIT)).read()
        fnd = json.load(open(a.findings))
        print(HEAD + body + """
=========== YOUR SHORT AS IT STANDS (compiled, rendered, looked at) ===========
%s
=========== WHAT THE CHECKS FOUND ===========
The compiler's warnings, and a vision model that looked at a frame at each beat start and 0.5 s in:
%s
=========== RETURN: the revised beats.json ===========
Fix what was found, beat by beat, without breaking anything that passed. Return ONLY the whole revised JSON inside
one ```json block, no other text. Keep "id", "voice", "sources", "music", "script" and "route_as" exactly as they are.""" % (
            cur, json.dumps(fnd, indent=1)))


if __name__ == "__main__":
    main()
