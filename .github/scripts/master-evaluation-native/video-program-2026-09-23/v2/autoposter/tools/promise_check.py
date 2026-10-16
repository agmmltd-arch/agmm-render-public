#!/usr/bin/env python3
"""Every promise a short makes must be delivered in the caption that goes out with it (Sam, 25 Sep 13:05:
"make sure any promises like guides or docs or whatever in the videos are supplied in the description/bio/caption").

    python3 tools/promise_check.py <ID> [--platform youtube]     # prints the verdict; exit 0 delivered, 1 not

Sources, all read for every short:
  spoken     the "## Spoken script" section of v2/shorts/scripts-v2/<ID>.md, and the voice's words.json
  on-screen  the gate's OCR of the rendered master (gate/rN/gemini_ocr_raw.txt: what a viewer actually reads),
             the text strings authored in kit/specs/<ID>/scenes.js, and string props in spec.json
Promise triggers: guide, checklist, template, playbook, worksheet, cheat sheet, toolkit, pdf, doc, download,
"free <thing>", "link in the description/bio/below", "in the description", "comment <WORD>", "get the/our/my",
and any agmm.co.uk address shown or spoken.
Delivered means: the routed platform's caption carries a URL that answers HTTP 200 now AND whose page carries
the promised thing (the words after "free", or the noun: "checklist" needs "checklist" on the page). A "free X"
promise needs the page itself to call X free ("free X" or "X is free"): the audit page says the audit is a
£2,000 engagement and only the 30-minute fit call is free, so "Free AI Constraint Audit" is NOT delivered.
A "comment WORD" promise is never delivered: the v2 lane has no comment-keyword automation.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from urllib.parse import unquote_plus, urlsplit, urlunsplit
from pathlib import Path

HERE = Path(__file__).resolve().parent
V2 = HERE.parents[1]
AP = HERE.parent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36"
NOUNS = r"guide|guides|checklist|checklists|template|templates|playbook|worksheet|cheat ?sheet|toolkit|pdf|" \
        r"doc|docs|document|download|downloads|e-?book|workbook|swipe file"
TRIGGER = re.compile(
    r"(?i)\b(?:" + NOUNS + r")\b|\bfree\b(?!\s+up\b|dom|d\b)|\blink\s+(?:is\s+)?(?:in|below|above|in the)\b|"
    r"\bin the (?:description|bio|comments?|caption)\b|\bcomment\s+[\"'‘“]?[A-Z]{2,}\b|"
    r"\bget (?:the|our|my|your) (?:free )?(?:" + NOUNS + r")\b|agmm\s*(?:\.|dot)\s*co\s*(?:\.|dot)\s*uk[\w/\-]*")
STOP = {"the", "a", "an", "our", "my", "your", "and", "is", "in", "bio", "link", "below", "to", "for", "of", "at", "on"}
URL_RE = re.compile(r"https?://[^\s)>\]]+")
AGMM_ADDR = re.compile(r"(?i)agmm\s*(?:\.|dot)\s*co\s*(?:\.|dot)\s*uk(/[\w\-/]*)?")
_PAGES: dict = {}


class _QATag(urllib.request.BaseHandler):
    handler_order = 90

    def http_request(self, request):
        parts = urlsplit(request.full_url)
        first_party = parts.hostname in ("agmm.co.uk", "www.agmm.co.uk")
        from_first_party = urlsplit("//" + request.origin_req_host).hostname in ("agmm.co.uk", "www.agmm.co.uk")
        if first_party or from_first_party:
            tags = {"utm_source": "qa", "utm_campaign": "qa_release_audit"}
            query = []
            for pair in parts.query.split("&") if parts.query else []:
                key, _, value = pair.partition("=")
                key, value = unquote_plus(key), unquote_plus(value)
                if key in tags and (first_party or value == tags[key]): continue
                query.append(pair)
            if first_party: query += ["utm_source=qa", "utm_campaign=qa_release_audit"]
            # Preserve this Request's timeout and bounded redirect_dict. Preserve
            # unrelated query bytes and the fragment; never tag caption text.
            request.full_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(query), parts.fragment))
        return request

    https_request = http_request


class _Redirects(urllib.request.HTTPRedirectHandler):
    # Python3.9 has no308 handler and its redirect_request rejects308. Retain
    # the native scheme/loop/hop limits; only GET/HEAD gain308 compatibility.
    http_error_308 = urllib.request.HTTPRedirectHandler.http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        compatible = 307 if code == 308 and req.get_method() in ("GET", "HEAD") else code
        redirected = super().redirect_request(req, fp, compatible, msg, headers, newurl)
        if redirected is not None and req.get_method() == "HEAD": redirected.method = "HEAD"
        return redirected


_OPENER = urllib.request.build_opener(_QATag(), _Redirects())


def _text_of_html(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def fetch(url: str) -> dict:
    if url in _PAGES:
        return _PAGES[url]
    # root 13 Oct: one transient timeout (Mac at load 585) withdrew 6 armed back-catalogue posts as
    # "promise_no_longer_delivered" while the page answered 200. Retry transport errors and 5xx 3 times with backoff;
    # a real 4xx (404, 410) still fails at once, and a failure is not cached so the next tick re-checks.
    import time as _t
    for attempt in range(3):
        try:
            with _OPENER.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=25) as r:
                body = r.read(3_000_000).decode("utf-8", "replace")
                out = {"status": r.status, "final": r.geturl(), "text": _text_of_html(body)}
        except Exception as exc:  # noqa: BLE001
            out = {"status": getattr(exc, "code", None) or 0, "final": url, "text": "", "error": str(exc)[:160]}
        if out["status"] and out["status"] < 500:
            break
        if attempt < 2:
            _t.sleep(5 * (attempt + 1) ** 2)
    if out["status"] == 200:
        _PAGES[url] = out
    return out


# ---------------------------------------------------------------- sources
def spoken_lines(sid: str) -> list[tuple[str, str]]:
    out = []
    script = V2 / "shorts" / "scripts-v2" / f"{sid}.md"
    if script.is_file():
        m = re.search(r"(?s)## Spoken script\s*(.*?)(?:\n## |\Z)", script.read_text(encoding="utf-8"))
        for s in re.split(r"(?<=[.!?])\s+|\n+", (m.group(1) if m else "")):
            if s.strip():
                out.append(("spoken script", s.strip()))
    words = V2 / "shorts" / "voice" / sid / f"{sid}.words.json"
    if words.is_file():
        ws = json.loads(words.read_text(encoding="utf-8")).get("words") or []
        joined = " ".join(str(w.get("word", "")) for w in ws)
        for s in re.split(r"(?<=[.!?])\s+", joined):
            if s.strip():
                out.append(("voice words", s.strip()))
    return out


def screen_lines(sid: str, gate_json: str | None = None) -> list[tuple[str, str]]:
    out = []
    ocr = None
    if gate_json:
        cand = Path(gate_json).parent / "gemini_ocr_raw.txt"
        ocr = cand if cand.is_file() else None
    if ocr is None:
        gates = sorted((V2 / "kit" / "out" / sid / "gate").glob("r*/gemini_ocr_raw.txt"))
        ocr = gates[-1] if gates else None
    if ocr:
        raw = ocr.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"\[.*\]", raw, re.S)
        try:
            for e in json.loads(m.group(0)) if m else []:
                out.append((f"on-screen (gate OCR {ocr.parent.name} {e.get('start')}s)", str(e.get("text", "")).replace("\n", " ")))
        except ValueError:
            out += [(f"on-screen (gate OCR {ocr.parent.name})", l) for l in raw.splitlines() if l.strip()]
    spec_dir = V2 / "kit" / "specs" / sid
    scenes = spec_dir / "scenes.js"
    if scenes.is_file():
        for q in re.findall(r"'((?:[^'\\\n]|\\.){3,})'|\"((?:[^\"\\\n]|\\.){3,})\"", scenes.read_text(encoding="utf-8")):
            s = html.unescape(re.sub(r"<[^>]+>", " ", q[0] or q[1]))
            s = re.sub(r"\s+", " ", s).strip()
            if re.search(r"[A-Za-z]{2,}\s+[A-Za-z]{2,}", s) and not re.search(r"[{};=]|px\b|rgba?\(|#[0-9a-f]{3}", s):
                out.append(("on-screen (scenes.js)", s))
    spec = spec_dir / "spec.json"
    if spec.is_file():
        def walk(v):
            if isinstance(v, dict):
                for k, x in v.items():
                    if k in ("props", "text", "label", "headline", "cta", "link"):
                        yield from walk_vals(x)
                    else:
                        yield from walk(x)
            elif isinstance(v, list):
                for x in v:
                    yield from walk(x)

        def walk_vals(v):
            if isinstance(v, str):
                if not v.startswith("@") and re.search(r"[A-Za-z]{2,}", v):
                    yield v
            elif isinstance(v, (dict, list)):
                for x in (v.values() if isinstance(v, dict) else v):
                    yield from walk_vals(x)
        for s in walk(json.loads(spec.read_text(encoding="utf-8")).get("beats", [])):
            out.append(("on-screen (spec.json props)", s))
    return out


# ---------------------------------------------------------------- promises
def promises(sid: str, gate_json: str | None = None, lines: list[tuple[str, str]] | None = None) -> list[dict]:
    """`lines` overrides the short's own sources (a film passes its VO text and its gate OCR; arm_film.py)."""
    seen, out = set(), []
    for src, line in (lines if lines is not None else spoken_lines(sid) + screen_lines(sid, gate_json)):
        for m in TRIGGER.finditer(line):
            trig = m.group(0)
            low = trig.lower()
            # A court filing's docket header ("Case 2:23-cv-05023 Document 1 Filed 12/19/23") is a source citation,
            # not an offer (S55, 25 Sep: the complaint shown on screen was read as a promised "doc"). Nor is the verb
            # in a list ("test, assess, measure, document, or inquire": the complaint's own words, S55 42 s).
            if low in ("doc", "document") and re.match(r"\s*(?:\d+\b|,|or\b|and\b)", line[m.end():]):
                continue
            # root 29 Sep (S60): "contract and document review is one of the most proven places to start" names a kind
            # of work, not an offer. A bare doc/document/docs is a promise only with an offer word just before it
            # (get/download/grab/send/free/our/my/we wrote/we made/link); guides, checklists etc. keep the old rule.
            if low in ("doc", "docs", "document", "documents", "pdf", "pdfs") and not re.search(
                    r"(?i)\b(?:get|download|grab|send|sent|free|our|my|we(?:'ve)?\s+(?:wrote|made|put)|link|this)\b[\w\s,'-]{0,20}$",
                    line[:m.start()]):
                continue
            if AGMM_ADDR.fullmatch(trig.strip()):
                path = (AGMM_ADDR.match(trig.strip()).group(1) or "/").rstrip("/") or "/"
                kind, obj = "address", path
            elif low.startswith("comment"):
                kind, obj = "comment", trig.split()[-1].strip("\"'‘“")
            elif low.startswith("free"):
                # "did that for free, and the world watched" is story, not an offer (S48, 25 Sep): an offer puts
                # "free" before the thing offered. Skip "for free" and a "free" followed by punctuation.
                if re.search(r"(?i)\bfor\s*$", line[:m.start()]) or re.match(r"\s*[,.;:!?]", line[m.end():]):
                    continue
                # Brain 13 Oct (parked by Marshal, F03): "the report had been on the department's website since
                # the fourth of July, free for anyone to read" is a story clause about who may read a named
                # document, not an offer (S48's cousin). An offer always puts the thing offered straight after
                # "free" ("free checklist", "free thirty-minute call"); "free for anyone/everyone/all/the public"
                # is the predicate-adjective form and names the reader, so there is no object to deliver. Only
                # those person words are skipped: "free for a limited time" and "a free checklist for anyone"
                # still parse, because "for" must sit immediately after "free".
                if re.match(r"(?i)\s+for (?:anyone|anybody|everyone|everybody|all|the public)\b", line[m.end():]):
                    continue
                # On-screen source code is not an offer (S43, 28 Sep: the invoice's C# line "var free = d.Slots..."):
                # skip "free" used as a variable, i.e. preceded by var/let/const/int or followed by "=".
                if re.search(r"(?i)\b(?:var|let|const|int|bool|def)\s*$", line[:m.start()]) or re.match(r"\s*=(?!=)|\[|\(|\.\w", line[m.end():]) \
                        or re.search(r"(?i)\breturn\s*$", line[:m.start()]):
                    continue
                after = [w for w in re.findall(r"[A-Za-z0-9\-]+", line[m.end():])[:5]]
                phrase = []
                for w in after:
                    if w.lower() in STOP and phrase:
                        break
                    if w.lower() not in STOP:
                        phrase.append(w)
                kind, obj = "free", " ".join(phrase[:4]).lower()
            elif re.fullmatch(r"(?i)" + NOUNS, low) or low.startswith("get "):
                kind, obj = "thing", re.search(r"(?i)" + NOUNS, trig).group(0).lower()
            else:
                kind, obj = "link", ""
            key = (kind, obj)
            if key in seen or (kind == "free" and not obj):
                continue
            seen.add(key)
            out.append({"kind": kind, "object": obj, "source": src, "line": line[:220], "trigger": trig})
    return out


def delivered(p: dict, caption: str) -> tuple[bool, str]:
    urls = [u.rstrip(".,;:!?'\"") for u in URL_RE.findall(caption)]
    if p["kind"] == "comment":
        return False, f"'comment {p['object']}' promised, but the v2 lane has no comment-keyword delivery"
    if not urls:
        return False, "the caption carries no link at all"
    pages = [(u, fetch(u)) for u in urls]
    live = [(u, pg) for u, pg in pages if pg["status"] == 200]
    if not live:
        return False, "no caption link answers 200: " + ", ".join(f"{u} -> {pg['status']}" for u, pg in pages)
    if p["kind"] == "link":
        return True, f"{live[0][0]} answers 200"
    if p["kind"] == "address":
        hits = [u for u, _ in live if "agmm.co.uk" in u and urllib.request.urlparse(u).path.rstrip("/").startswith(
            p["object"].rstrip("/") if p["object"] != "/" else "")]
        return (bool(hits), f"{hits[0]} answers 200" if hits else
                f"agmm.co.uk{p['object']} is shown or spoken but no caption link points there")
    # root 28 Sep (F01): the voice says "thirty-minute call with us", the page "free 30-minute fit call". Spoken number
    # words become digits on both sides, a trailing "with us/for you" is not part of the thing, and one qualifier word
    # may sit before the object's last word. The denial patterns below are unchanged, so "free audit" still fails.
    NUMW = {"five": "5", "ten": "10", "fifteen": "15", "twenty": "20", "thirty": "30", "forty-five": "45", "sixty": "60"}
    numw = lambda x: re.sub(r"\b(" + "|".join(sorted(NUMW, key=len, reverse=True)) + r")\b", lambda m: NUMW[m.group(1)], x)
    pobj = re.sub(r"\s+(?:with|for|from) (?:us|you)$", "", numw(p["object"].lower()).strip())
    words = pobj.split()
    obj = re.escape(pobj).replace(r"\ ", r"\W+")
    if p["kind"] == "free" and len(words) > 1:
        obj = r"\W+".join(re.escape(w) for w in words[:-1]) + r"(?:\W+[a-z]+)?\W+" + re.escape(words[-1])
    for u, pg in live:
        t = numw(pg["text"].lower())
        # A free guide is delivered by a live agmm.co.uk/learn/ page: the library is read without sign-up or payment.
        if p["kind"] == "free" and words and words[-1] in ("guide", "guides", "article", "checklist") and \
                "agmm.co.uk" in u and urllib.request.urlparse(u).path.startswith("/learn/") and "guide" in t:
            return True, f"{u} is a free-to-read agmm.co.uk/learn/ page (the '{p['object']}')"
        if p["kind"] == "thing" and re.search(r"\b" + obj.rstrip("s") + r"s?\b", t):
            return True, f"{u} answers 200 and the page carries '{p['object']}'"
        if p["kind"] == "free":
            # Same clause only: spaces or hyphens between the words, never across ? . ! (25 Sep: "Is the audit
            # free? + No. The AI Constraint Audit" matched a looser pattern and passed an undelivered promise).
            last = re.escape(p["object"].split()[-1])
            denied = re.search(r"is the (?:\w+ ){0,3}" + last + r" free\?\W*no\b", t) or \
                re.search(obj + r" (?:is|are) (?:not|n't|never) free", t) or re.search(obj + r" is a (?:fixed |paid )", t)
            called = re.search(r"\bfree[ \-]+(?:[a-z0-9\-]+ +)?" + obj.replace(r"\W+", r"[ \-]+") + r"\b", t) or \
                re.search(obj.replace(r"\W+", r"[ \-]+") + r" (?:is|are) (?:completely |totally )?free\b", t)
            if called and not denied:
                return True, f"{u} answers 200 and calls '{p['object']}' free: '{called.group(0)}'"
    if p["kind"] == "free":
        neg = next((m.group(0) for _, pg in live for m in [re.search(
            r"(?i)is the \w+ free\?\W*\+?\W*no[^.]{0,140}\.[^.]{0,80}", pg["text"])] if m), "")
        return False, (f"'free {p['object']}' is promised, but no caption page calls it free"
                       + (f" (the page says: \"{neg.strip()}\")" if neg else ""))
    return False, f"no caption page carries '{p['object']}'"


def check(sid: str, caption: str, gate_json: str | None = None, lines: list[tuple[str, str]] | None = None) -> dict:
    scanned = lines if lines is not None else spoken_lines(sid) + screen_lines(sid, gate_json)
    if not scanned:
        return {"id": sid, "ok": False, "promises": [], "undelivered": [{"kind": "unscanned", "line": "",
                "how": "no script, voice words or on-screen text found to scan; refusing to assume no promises"}]}
    ps = promises(sid, gate_json, scanned)
    results = []
    for p in ps:
        ok, how = delivered(p, caption)
        results.append({**p, "delivered": ok, "how": how})
    bad = [r for r in results if not r["delivered"]]
    return {"id": sid, "ok": not bad, "promises": results, "undelivered": bad}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--platform", default="youtube")
    ap.add_argument("--caption-file")
    args = ap.parse_args()
    if args.caption_file:
        caption = Path(args.caption_file).read_text(encoding="utf-8")
    else:
        caption = json.loads((AP / "items" / args.id / "captions.json").read_text())[args.platform]["caption"]
    res = check(args.id, caption)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
