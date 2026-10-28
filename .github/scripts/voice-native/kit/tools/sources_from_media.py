#!/usr/bin/env python3
"""sources_from_media.py: turn source_media.py's crops into a sources.js whose highlightable phrases EXIST on the page.

  python3 tools/sources_from_media.py <MEDIA_ID> [--out-id X12] [--credit "OFFICE FOR NATIONAL STATISTICS"] [--date "20 JUL 2026"]

Reads kit/media/<MEDIA_ID>/manifest.json (every usable page_claim_crop / doc crop, and the logos), OCRs each crop with
the kit's own macOS Vision tool (tools/ocr_vision, free, local), and writes into specs/<OUT_ID>/:
  sources.js   window.<OUT_ID>_SRC = {items: {key: {src, css, marks: {phrase: [[x, y, w, h], ...]}, credit, date, text}}}
  media/       the crops and logos (compose.py --stage copies them into out/<OUT_ID>/img)
  PHRASES.md   every phrase a clip may mark, per crop (beats_brief.py pastes these; compose.py rejects any other)
Phrases are cut from the OCR text itself: each clause, each short sentence, and every number with its 1-3 words of
context ("around 35%", "construction (13%)"). Word boxes are interpolated along each OCR line (Vision gives line
boxes), which is exact enough for a highlighter drawn 4 px wider than the words.
Read-only on kit/media. Never alters a crop."""
import argparse, json, os, re, shutil, subprocess, sys
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OCR = os.path.join(KIT, "tools", "ocr_vision")
DOMAIN_CREDIT = {"ons.gov.uk": "OFFICE FOR NATIONAL STATISTICS", "gov.uk": "GOV.UK", "bbc.co.uk": "BBC NEWS", "bbc.com": "BBC NEWS",
                 "theguardian.com": "THE GUARDIAN", "ft.com": "FINANCIAL TIMES", "reuters.com": "REUTERS", "businessinsider.com": "BUSINESS INSIDER",
                 "ico.org.uk": "INFORMATION COMMISSIONER'S OFFICE", "cnbc.com": "CNBC", "theverge.com": "THE VERGE", "bloomberg.com": "BLOOMBERG"}
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


def clean(t):
    t = re.sub(r"\bAl\b", "AI", t)          # Vision reads "AI" as "Al" in most sans faces
    return re.sub(r"^[•·\-\s]+", "", t).strip()


def credit_of(url):
    host = re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0]
    for d, c in DOMAIN_CREDIT.items():
        if host == d or host.endswith("." + d):
            return c
    return host.upper()


def date_of(asset, media_dir, manifest):
    if asset.get("published"):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", asset["published"])
        if m:
            return "%d %s %s" % (int(m.group(3)), MONTHS[int(m.group(2)) - 1], m.group(1))
    txt = os.path.join(media_dir, re.sub(r"-(claim\d+-\d+|hero|fold|byline|masthead)\.png$", ".txt", asset["file"]))
    if os.path.exists(txt):
        t = open(txt, errors="ignore").read()
        m = re.search(r"Release date:\s*\n?\s*(\d{1,2}) ([A-Z][a-z]+) (\d{4})", t) or re.search(r"\b(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})\b", t)
        if m:
            return "%s %s %s" % (m.group(1), m.group(2)[:3].upper(), m.group(3))
    return (manifest.get("story_date") or "").upper()


def phrases(lines, scale=2.0):
    """{phrase: [rect...]} from OCR lines [{text, x, y, w, h}] in css px (image px / scale)."""
    text, spans, pos = "", [], 0
    for l in lines:
        t = clean(l["text"])
        spans.append((pos, pos + len(t), l, t)); text += t + " "; pos += len(t) + 1
    out = {}

    def rects(i, j):
        R = []
        for a, b, l, t in spans:
            s, e = max(a, i), min(b, j)
            if s < e:
                cw = l["w"] / max(1, len(t))
                R.append([round((l["x"] + (s - a) * cw) / scale, 1), round(l["y"] / scale, 1), round((e - s) * cw / scale, 1), round(l["h"] / scale, 1)])
        return R

    def add(i, j):
        p = text[i:j].strip(" ,;:.")
        if not p:
            return
        i = text.index(p, i); j = i + len(p)
        n = len(p.split())
        before, after = text[i - 2:i] if i >= 2 else text[:i], text[j:j + 2]
        broken = (p.count("(") != p.count(")") or re.match(r"^\d", p) and re.search(r"[\d,.]$", before)
                  or re.search(r"\d$", p) and re.match(r"^[,.]\d", after) or re.search(r"\b(The|the|a|an|of|and|to|in|with)$", p)
                  or (n < 2) or (n == 2 and not re.search(r"\d", p) and any(len(w) < 4 for w in p.split())))
        R_ = rects(i, j)
        if 2 <= n <= 22 and p not in out and not broken and len(R_) == 1:   # one line only: a wrapped phrase cannot be shown big
            out[p] = R_
    for m in re.finditer(r"[^,;:()]+", text):                         # clauses
        add(m.start(), m.end())
    for m in re.finditer(r"[^.!?]+[.!?]?", text):                     # short sentences
        add(m.start(), m.end())
    for m in re.finditer(r"[^,;:().!?]+", text):                        # 2-4 word chunks inside each clause
        ws = [(w.start() + m.start(), w.end() + m.start()) for w in re.finditer(r"\S+", m.group(0))]
        for n_ in (2, 3, 4):
            for i_ in range(0, max(0, len(ws) - n_ + 1)):
                add(ws[i_][0], ws[i_ + n_ - 1][1])
    for m in re.finditer(r"\(?[£$€]?\d[\d,.]*%?\)?(?:\s+(?:million|billion|bn|m|per cent|percent|flights|jobs|staff|people|firms|businesses|days|years|computers))?", text):   # numbers (+ unit) with 1-3 words of context
        core = re.match(r"\(?[£$€]?\d[\d,.]*%?\)?", text[m.start():]).end()
        for k in (1, 2, 3):
            pre = text[:m.start()].rstrip().split(" ")
            st0 = text.rfind(" ".join(pre[-k:]), 0, m.start()) if len(pre) >= k else -1
            if st0 >= 0:
                add(st0, m.start() + core)                # without its unit (stays on one line more often)
            if len(pre) >= k:
                st = m.start() - len(" ".join(pre[-k:])) - (len(text[:m.start()]) - len(text[:m.start()].rstrip())) - 1 + 1
                st = text.rfind(" ".join(pre[-k:]), 0, m.start())
                if st >= 0:
                    add(st, m.end())
        add(m.start(), m.end())
    return out, text.strip()


def from_sources(src_js, out_id):
    """older hand-made sources.js (S44, S52...): OCR each crop again and ADD every phrase on it to its marks (the
    hand-drawn marks are kept), so a compiled short can mark short phrases that read big. Writes specs/<out_id>/."""
    sys.path.insert(0, os.path.join(KIT, "tools"))
    import compose as C
    items, path = C.load_sources(src_js)
    sd = os.path.join(KIT, "specs", out_id); os.makedirs(os.path.join(sd, "media"), exist_ok=True)
    out, md = {}, ["# %s: phrases a clip may mark (tools/sources_from_media.py --from-sources %s)" % (out_id, src_js), ""]
    for k, v in items.items():
        f = C.find_image(path, v["src"])
        v = dict(v)
        if f:
            name = os.path.basename(v["src"]); name2 = re.sub(r"^real-[a-z0-9]+-", "", name)
            shutil.copyfile(f, os.path.join(sd, "media", name2))
            v["src"] = "img/real-%s-%s" % (out_id.lower(), name2)
        if v.get("css") and f:
            r = subprocess.run([OCR, f], capture_output=True, text=True)
            d = json.loads(r.stdout.splitlines()[0]) if r.stdout.strip() else {}
            if d.get("lines"):
                sc_ = d["w"] / float(v["css"][0])
                ph, _ = phrases(d["lines"], sc_)
                v["lines"] = [[round(l["x"] / sc_, 1), round(l["y"] / sc_, 1), round(l["w"] / sc_, 1), round(l["h"] / sc_, 1), clean(l["text"])] for l in d["lines"]]
                marks = dict(ph); marks.update(v.get("marks") or {})
                v["marks"] = marks
                md += ["## %s (%s, %s)" % (k, v.get("credit"), v.get("date"))] + ["- %s" % p for p in marks] + [""]
        out[k] = v
    open(os.path.join(sd, "sources.js"), "w").write("window.%s_SRC = %s;\n" % (out_id, json.dumps({"by": "sources_from_media.py --from-sources " + src_js, "items": out}, indent=1)))
    open(os.path.join(sd, "PHRASES.md"), "w").write("\n".join(md) + "\n")
    print("wrote specs/%s/sources.js from %s: %d items, %d phrases" % (out_id, src_js, len(out), sum(len(v.get("marks", {})) for v in out.values())))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media_id"); ap.add_argument("--out-id"); ap.add_argument("--credit"); ap.add_argument("--date")
    ap.add_argument("--from-sources", action="store_true", help="media_id is a sources.js path (hand-made); add OCR phrases to it")
    a = ap.parse_args()
    if a.from_sources:
        return from_sources(a.media_id, a.out_id)
    out_id = a.out_id or a.media_id
    md = os.path.join(KIT, "media", a.media_id)
    man = json.load(open(os.path.join(md, "manifest.json")))
    sd = os.path.join(KIT, "specs", out_id); os.makedirs(os.path.join(sd, "media"), exist_ok=True)
    items, lines_md, n = {}, ["# %s: phrases a clip may mark (generated by tools/sources_from_media.py from media/%s)" % (out_id, a.media_id), ""], 0
    crops = [x for x in man["assets"] if x.get("type") in ("page_claim_crop", "doc_claim_crop", "doc_crop") and x.get("usable", True)]
    for x in crops:
        f = os.path.join(md, x["file"])
        r = subprocess.run([OCR, f], capture_output=True, text=True)
        if r.returncode or not r.stdout.strip():
            print("skip (OCR failed): %s" % x["file"], file=sys.stderr); continue
        d = json.loads(r.stdout.splitlines()[0])
        if d.get("error") or not d.get("lines"):
            continue
        ph, text = phrases(d["lines"])
        if not ph or any(v.get("text") == text[:600] for v in items.values()):
            continue                                  # an identical crop of the same paragraph adds nothing
        n += 1
        key = "src%d" % n
        name = "%s-%s.png" % (key, re.sub(r"[^a-z0-9]+", "-", x["id"].lower())[-20:].strip("-"))
        shutil.copyfile(f, os.path.join(sd, "media", name))
        items[key] = {"src": "img/real-%s-%s" % (out_id.lower(), name), "px": [d["w"], d["h"]], "css": [d["w"] / 2, d["h"] / 2],
                      "lines": [[round(l["x"] / 2, 1), round(l["y"] / 2, 1), round(l["w"] / 2, 1), round(l["h"] / 2, 1), clean(l["text"])] for l in d["lines"]],
                      "marks": ph, "url": x.get("page_url") or x.get("source_url"), "credit": a.credit or credit_of(x.get("page_url") or x.get("source_url")),
                      "date": a.date or date_of(x, md, man), "text": text[:600], "headline": x.get("headline"), "claims": x.get("claims")}
        lines_md += ["## %s (%s, %s)" % (key, items[key]["credit"], items[key]["date"]), "Page text: %s" % text[:400], "Phrases:"] + ["- %s" % p for p in ph] + [""]
    for x in [x for x in man["assets"] if x.get("type") == "logo"]:
        k = re.sub(r"[^a-z0-9]+", "_", os.path.splitext(os.path.basename(x["file"]))[0].lower()) + "_logo"
        name = os.path.basename(x["file"])
        shutil.copyfile(os.path.join(md, x["file"]), os.path.join(sd, "media", name))
        items[k] = {"src": "img/real-%s-%s" % (out_id.lower(), name), "credit": (x.get("credit_line") or "LOGO").upper()}
        lines_md += ["## %s: logo (%s)" % (k, items[k]["credit"]), ""]
    open(os.path.join(sd, "sources.js"), "w").write("window.%s_SRC = %s;\n" % (out_id, json.dumps({"by": "tools/sources_from_media.py from media/%s" % a.media_id, "items": items}, indent=1)))
    open(os.path.join(sd, "PHRASES.md"), "w").write("\n".join(lines_md) + "\n")
    print("wrote specs/%s/sources.js: %d crops, %d logos, %d phrases" % (out_id, n, len(items) - n, sum(len(v.get("marks", {})) for v in items.values())))


if __name__ == "__main__":
    main()
