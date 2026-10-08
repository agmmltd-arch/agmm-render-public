#!/usr/bin/env python3
"""crop_clause.py: one real clause from a real page -> a source card that reads on a phone, with a dated credit, or a hard FAIL.

  python3 tools/crop_clause.py --url URL --phrase "exact clause" --id S50 [--key NAME] [--min-px 48] [--card-w 960] [--out DIR]
                               [--metric font|xheight|box] [--wait 2] [--fetch auto|browser|curl] [--allow-undated] [--install]

root 6 Oct 2026 (buzz-gap fix #2, maker-decomposition.md section 4). Why it exists: every short carried its own capture.py, and the free crew
cannot LOOK at a crop. The commonest returns were "no real source shown" (31), "legibility under 42 px" (31) and the blank white strip.
The free model only supplies the phrase (from the fact pack); this tool does the looking with checks that can fail.

What it does
  1. Opens the page headless (Playwright chrome-headless-shell, 1280 css wide, device scale 4). It re-executes itself under
     tools/heavy.py (the Mac's 3 heavy slots) unless CROP_CLAUSE_IN_HEAVY=1 or --no-heavy.
  2. Finds the phrase VERBATIM in the rendered DOM (whitespace, curly quotes, dashes, nbsp, soft hyphens normalised; case and every
     other character must match). Not found = FAIL. The phrase may not span two paragraphs.
  3. Sweeps the viewport width (320..2400 css) and keeps the layout where the phrase sits on ONE line with the biggest glyphs per
     card width. If no layout puts it on one line it FAILS (it never reflows the page's text).
  4. Crops tight to the phrase's own words (word boundaries: no neighbour glyphs), at device scale >= what the card needs.
  5. Measures px_at_card_width: the glyph size when the crop is placed at --card-w (default 960 = the kit's text-safe width). Default
     metric "font" = computed font-size x scale, the same quantity compose.py calls "render at N px" (0.8 x line box ~ 0.93 x font).
     "xheight" and "box" are reported too and selectable. Under --min-px (48) = FAIL, with the longest clause that would fit.
  6. Takes date and publisher from the page's own metadata (JSON-LD datePublished, article:published_time, itemprop, <time datetime>,
     then a visible date element beside the headline). Never invented. No date = FAIL, or with --allow-undated the credit reads
     "<PUBLISHER>, DATE NOT PUBLISHED ON PAGE".
  7. Looks at its own output: pixel variance and ink fraction of the crop (the blank white strip), and OCRs the crop with the kit's
     macOS Vision tool to confirm the words are really painted.

Outputs (in --out, default kit/media/<ID>/clauses/)
  <key>.png            the crop (what a scene shows; real pixels, nothing retyped)
  <key>.json           url, phrase, publisher, date, credit line, px_at_card_width (all three metrics), crop box, checks
  <key>.sources.js     window.<ID>_SRC = {items: {<key>: {...}}} in the shape compose.py / S44-S50-S119 scenes.js consume:
                       src, css, px, marks{phrase:[[x,y,w,h]] css px}, lines, credit, date, url (+ marks_px and pitch for S118-style scenes)
  <key>.preview.png    the crop at card width with the credit line under it (for a human or reviewer to look at)
  --install            also merge the item into specs/<ID>/sources.js (backup first) and copy the PNG to specs/<ID>/media/<key>.png

Exit codes (every failure also writes <key>.FAIL.json and prints "CROP_CLAUSE FAIL <code> ..." on stderr)
  0 ok | 1 usage/internal | 2 phrase not found verbatim | 3 page unreachable, blocked, challenge or blank | 4 crop renders blank / text not painted
  5 text under --min-px at card width | 6 date unavailable | 7 phrase covered by an overlay | 8 phrase cannot sit on one line at any width
"""
import argparse, difflib, json, os, re, shutil, subprocess, sys, time, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
OCR = os.path.join(HERE, "ocr_vision")
HEAVY = os.path.join(HERE, "heavy.py")
CHROME = os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-x64/chrome-headless-shell")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
FULL_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
WIDTHS = list(range(320, 721, 20)) + [800, 900, 1024, 1280, 1536, 1920, 2400]
DPR = 4
# a body this small, or one that says this, is a block page, not an article
CHALLENGE = re.compile(r"just a moment|attention required|access denied|verify you are (a )?human|are you a robot|captcha|"
                       r"enable javascript and cookies|request blocked|unusual traffic|pardon our interruption|bot detection", re.I)
HIDE_CSS = ("[id*=cookie i]:not(html):not(body),[class*=cookie i]:not(html):not(body),[id*=consent i]:not(html):not(body),"
            "[class*=consent i]:not(html):not(body),[id*=sp_message i],[id*=onetrust i],[class*=onetrust i],iframe,"
            "#onetrust-consent-sdk,.ad,[class*=advert i]:not(html):not(body){display:none!important}")
NOISE_URL = re.compile(r".*(consent|cmp\.|onetrust|cookielaw|cookiebot|googletagmanager|doubleclick|hotjar|privacy-mgmt|adservice|"
                       r"sourcepoint|chartbeat|permutive|googlesyndication|taboola|outbrain).*")


class Fail(Exception):
    def __init__(self, code, msg, **detail):
        Exception.__init__(self, msg); self.code = code; self.msg = msg; self.detail = detail


# ------------------------------------------------------------------ text normalisation (mirrored in JS below, character for character)
def norm_char(c):
    out = ""
    for ch in unicodedata.normalize("NFKC", c):
        if ch in "‘’‚‛′ʼ":
            out += "'"
        elif ch in "“”„‟″":
            out += '"'
        elif "‐" <= ch <= "―" or ch in "−⁃":
            out += "-"
        elif ch in "­​‌‍⁠﻿":
            pass
        elif ch.isspace():
            out += " "
        else:
            out += ch
    return out


def norm(s):
    out = ""
    for c in s:
        for ch in norm_char(c):
            if ch == " " and (not out or out.endswith(" ")):
                continue
            out += ch
    return out.strip()


JS_COMMON = r"""
const normChar = c => { let out = '';
  for (const ch of c.normalize('NFKC')) {
    if (/[‘’‚‛′ʼ]/.test(ch)) out += "'";
    else if (/[“”„‟″]/.test(ch)) out += '"';
    else if (/[‐-―−⁃]/.test(ch)) out += '-';
    else if (/[­​-‍⁠﻿]/.test(ch)) { }
    else if (/\s/.test(ch)) out += ' ';
    else out += ch; }
  return out; };
"""

JS_FIND = JS_COMMON + r"""
async (target) => {
  try { await Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 4000))]); } catch (e) {}
  const nodes = [], flat = [], map = [];
  const SEP = '\u0001';
  const tw = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  let n, prevBlk = null, prevNode = null;
  const blockOf = p => { let b = p; while (b && b !== document.body) { const d = getComputedStyle(b).display; if (!(/^inline/.test(d) || d === 'contents')) return b; b = b.parentElement; } return document.body; };
  const push = (ch, ni, off) => { if (ch === ' ' && (flat.length === 0 || flat[flat.length - 1] === ' ' || flat[flat.length - 1] === SEP)) return; flat.push(ch); map.push([ni, off]); };
  while ((n = tw.nextNode())) {
    const p = n.parentElement; if (!p) continue;
    if (p.closest('script,style,noscript,template,head,title')) continue;
    if (p.checkVisibility && !p.checkVisibility()) continue;
    const blk = blockOf(p), ni = nodes.length; nodes.push(n);
    if (prevNode && blk !== prevBlk) { flat.push(SEP); map.push([-1, 0]); }
    else if (prevNode) { const rg = document.createRange(); rg.setStartAfter(prevNode); rg.setEndBefore(n);
      if (rg.cloneContents().querySelector('br')) push(' ', ni, 0); }
    const t = n.textContent;
    for (let j = 0; j < t.length; j++) { const o = normChar(t[j]); for (const ch of o) push(ch, ni, j); }
    prevBlk = blk; prevNode = n;
  }
  const hay = flat.join(''); const hits = [];
  let i = hay.indexOf(target); while (i >= 0) { hits.push(i); i = hay.indexOf(target, i + 1); }
  window.__cc = { hits: [], ranges: [] };
  for (const h of hits) {
    const a = map[h], b = map[h + target.length - 1]; if (!a || !b || a[0] < 0 || b[0] < 0) continue;
    const r = document.createRange(); r.setStart(nodes[a[0]], a[1]); r.setEnd(nodes[b[0]], b[1] + 1);
    const rs = [...r.getClientRects()].filter(q => q.width > 0.5 && q.height > 0.5);
    window.__cc.ranges.push({ r, painted: rs.length > 0 });
  }
  const live = window.__cc.ranges.filter(x => x.painted);
  window.__cc.range = (live[0] || window.__cc.ranges[0] || {}).r || null;
  return { occurrences: hits.length, usable: window.__cc.ranges.length, painted: live.length, textLen: hay.length };
}"""

JS_ANALYSE = r"""
async () => {
  const R = window.__cc && window.__cc.range; if (!R) return null;
  const el = R.startContainer.parentElement;
  document.querySelectorAll('body *').forEach(x => { const cs = getComputedStyle(x);
    if ((cs.position === 'fixed' || cs.position === 'sticky') && !x.contains(R.commonAncestorContainer)) x.style.setProperty('display', 'none', 'important'); });
  el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
  await new Promise(r => setTimeout(r, 60));
  const rs = [...R.getClientRects()].filter(q => q.width > 0.5 && q.height > 0.5);
  if (!rs.length) return { rects: [], lines: 0 };
  // lines: cluster rects whose vertical centres are within half a rect height
  const lines = []; for (const q of rs.slice().sort((a, b) => a.top - b.top || a.left - b.left)) {
    const cy = q.top + q.height / 2; const L = lines.find(l => Math.abs(l.cy - cy) < Math.min(l.h, q.height) * 0.5);
    if (L) { L.l = Math.min(L.l, q.left); L.r = Math.max(L.r, q.right); L.t = Math.min(L.t, q.top); L.b = Math.max(L.b, q.bottom); } else lines.push({ cy, h: q.height, l: q.left, r: q.right, t: q.top, b: q.bottom }); }
  const u = { l: Math.min(...rs.map(q => q.left)), r: Math.max(...rs.map(q => q.right)), t: Math.min(...rs.map(q => q.top)), b: Math.max(...rs.map(q => q.bottom)) };
  const cs = getComputedStyle(el);
  let bg = 'rgb(255, 255, 255)'; for (let b = el; b; b = b.parentElement) { const c = getComputedStyle(b).backgroundColor; if (c && !/rgba\(0, 0, 0, 0\)|transparent/.test(c)) { bg = c; break; } }
  const c2 = document.createElement('canvas').getContext('2d'); c2.font = cs.fontStyle + ' ' + cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
  const mx = c2.measureText('x'), mh = c2.measureText('H');
  const pts = [0.25, 0.5, 0.75].map(f => [u.l + (u.r - u.l) * f, (u.t + u.b) / 2]);
  let covered = 0, coverer = null;
  for (const [x, y] of pts) { if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) continue; const t = document.elementFromPoint(x, y);
    if (t && !(el.contains(t) || t.contains(el))) { covered++; coverer = t.tagName.toLowerCase() + (t.id ? '#' + t.id : '') + (typeof t.className === 'string' && t.className ? '.' + t.className.split(' ')[0] : ''); } }
  const prevCh = R.startOffset > 0 ? (R.startContainer.textContent || '')[R.startOffset - 1] : ' ', nextCh = (R.endContainer.textContent || '')[R.endOffset] || ' ';
  const own = [...R.getClientRects()].filter(q => q.width > 0.5 && q.height > 0.5).map(q => [q.left, q.top, q.width, q.height]);
  return { sx: scrollX, sy: scrollY, lines: lines.length, u: [u.l, u.t, u.r - u.l, u.b - u.t], own,
           lineRects: lines.map(l => [l.l, l.t, l.r - l.l, l.b - l.t]),
           font: parseFloat(cs.fontSize), lh: parseFloat(cs.lineHeight) || 0, family: cs.fontFamily.slice(0, 80), weight: cs.fontWeight, color: cs.color, bg,
           transform: cs.textTransform, opacity: (() => { let o = 1; for (let b = el; b; b = b.parentElement) o *= parseFloat(getComputedStyle(b).opacity); return o; })(),
           xh: mx.actualBoundingBoxAscent || 0, caph: mh.actualBoundingBoxAscent || 0, covered, coverer, vw: innerWidth, prevCh, nextCh };
}"""

JS_META = r"""
() => {
  const q = (s) => document.querySelector(s), m = (n) => { const e = q('meta[property="' + n + '"],meta[name="' + n + '"],meta[itemprop="' + n + '"]'); return e ? e.getAttribute('content') : null; };
  const out = { dates: [], site: null, title: null, h1: null };
  const ld = [...document.querySelectorAll('script[type="application/ld+json"]')];
  const walk = (o, f) => { if (Array.isArray(o)) o.forEach(x => walk(x, f)); else if (o && typeof o === 'object') { f(o); Object.values(o).forEach(x => walk(x, f)); } };
  let ldPub = null;
  for (const s of ld) { try { walk(JSON.parse(s.textContent), o => {
      if (o.datePublished) out.dates.push(['json-ld datePublished', String(o.datePublished)]);
      if (o.publisher && (o.publisher.name || typeof o.publisher === 'string') && !ldPub) ldPub = o.publisher.name || o.publisher;
      if (o.dateCreated && !o.datePublished) out.dates.push(['json-ld dateCreated', String(o.dateCreated)]); }); } catch (e) {} }
  for (const k of ['article:published_time', 'og:article:published_time', 'datePublished', 'pubdate', 'publishdate', 'publish-date', 'DC.date.issued', 'dcterms.created', 'dcterms.issued', 'sailthru.date', 'parsely-pub-date', 'article.published', 'date', 'og:pubdate', 'cXenseParse:recs:publishtime'])
    { const v = m(k); if (v) out.dates.push(['meta ' + k, v]); }
  const tt = q('time[itemprop="datePublished"][datetime],[itemprop="datePublished"][datetime],[itemprop="datePublished"][content]');
  if (tt) out.dates.push(['itemprop datePublished', tt.getAttribute('datetime') || tt.getAttribute('content')]);
  const h1 = q('h1'); out.h1 = h1 ? h1.innerText.trim().slice(0, 200) : null; out.title = document.title || null;
  const scope = (h1 && (h1.closest('article,main,header') || h1.parentElement)) || document.body;
  const tm = scope.querySelector('time[datetime]') || document.querySelector('article time[datetime],main time[datetime]');
  if (tm) out.dates.push(['time datetime', tm.getAttribute('datetime')]);
  for (const e of scope.querySelectorAll('time,[class*="date" i],[class*="publish" i],[class*="byline" i],[class*="timestamp" i]')) {
    const t = (e.innerText || '').trim(); if (!t || t.length > 90 || /updated|modified|edited/i.test(t)) continue;
    if (/\b\d{1,2}(st|nd|rd|th)?\s+[A-Za-z]{3,9}\.?,?\s+\d{4}\b|\b[A-Za-z]{3,9}\.?\s+\d{1,2}(st|nd|rd|th)?,?\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b/.test(t)) { out.dates.push(['visible date element', t]); break; } }
  out.site = m('og:site_name') || m('application-name') || m('twitter:site');
  out.ldPublisher = ldPub; out.canonical = (q('link[rel="canonical"]') || {}).href || null; out.ogTitle = m('og:title');
  return out;
}"""

JS_BODY = r"""
() => { const t = (document.body ? document.body.innerText : '') || ''; return { title: document.title || '', textLen: t.trim().length, head: t.trim().slice(0, 300) }; }"""


# ------------------------------------------------------------------ date, publisher
def parse_date(s):
    """-> (D MON YYYY, iso) or None. Only what the page itself states."""
    s = (s or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return "%d %s %s" % (int(m.group(3)), MONTHS[int(m.group(2)) - 1], m.group(1)), "%s-%s-%s" % m.groups()
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", s)
    mo = None
    if m:
        d, mn, y = m.groups()
    else:
        m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", s)
        if not m:
            return None
        mn, d, y = m.groups()
    for i, fm in enumerate(FULL_MONTHS):
        if mn.lower() == fm or (len(mn) >= 3 and fm.startswith(mn.lower()) and (len(mn) == 3 or mn.lower() == fm[:len(mn)])):
            mo = i + 1; break
    if not mo or not (1 <= int(d) <= 31):
        return None
    return "%d %s %s" % (int(d), MONTHS[mo - 1], y), "%s-%02d-%02d" % (y, mo, int(d))


def publisher_of(url, meta):
    host = re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0]
    sys.path.insert(0, HERE)
    try:
        import sources_from_media as SFM
        for d, c in SFM.DOMAIN_CREDIT.items():
            if host == d or host.endswith("." + d):
                return c, "kit domain map"
    except Exception:
        pass
    for name, src in ((meta.get("site"), "og:site_name"), (meta.get("ldPublisher"), "json-ld publisher")):
        if name and isinstance(name, str) and 2 <= len(name.strip()) <= 60 and not name.strip().startswith("@"):
            return name.strip().upper(), src
    return host.upper() or "UNKNOWN SOURCE", "host name"


# ------------------------------------------------------------------ pixels
def pixel_stats(path):
    from PIL import Image
    im = Image.open(path).convert("L"); w, h = im.size
    px = im.load(); hist = im.histogram(); bg = max(range(256), key=lambda i: hist[i])
    n = w * h; ink = sum(hist[i] for i in range(256) if abs(i - bg) > 48)
    mean = sum(i * hist[i] for i in range(256)) / float(n); var = sum(hist[i] * (i - mean) ** 2 for i in range(256)) / float(n)
    def row_ink(y):
        return sum(1 for x in range(w) if abs(px[x, y] - bg) > 48) / float(w)
    def col_ink(x):
        return sum(1 for y in range(h) if abs(px[x, y] - bg) > 48) / float(h)
    return {"w": w, "h": h, "bg_gray": bg, "ink_fraction": round(ink / float(n), 5), "std": round(var ** 0.5, 2),
            "edge_ink": {"top": round(row_ink(0), 3), "bottom": round(row_ink(h - 1), 3), "left": round(col_ink(0), 3), "right": round(col_ink(w - 1), 3)}}


def trim_strays(path, dpr, pady_css):
    """A neighbouring line's descender or ascender can enter the crop's top or bottom rows (tight line-height). Ink bands that touch the crop's top or bottom edge,
    are separated from the phrase's own band by blank rows, and hold under 15% of the ink are not the phrase: cut them. -> (rows cut from top, rows cut from bottom)."""
    from PIL import Image
    im = Image.open(path).convert("RGB"); g = im.convert("L"); w, h = g.size; px = g.load()
    hist = g.histogram(); bg = max(range(256), key=lambda i: hist[i])
    rows = [sum(1 for x in range(w) if abs(px[x, y] - bg) > 48) for y in range(h)]
    bands, st = [], None
    for y, c in enumerate(rows):
        if c and st is None: st = y
        if not c and st is not None: bands.append([st, y]); st = None
    if st is not None: bands.append([st, h])
    if len(bands) < 2:
        return 0, 0
    tot = float(sum(rows)); mass = [sum(rows[a:b]) for a, b in bands]
    keep = [i for i, (a, b) in enumerate(bands) if not ((a == 0 or b == h) and mass[i] / tot < 0.15)]
    if len(keep) == len(bands) or not keep:
        return 0, 0
    first, last = bands[keep[0]], bands[keep[-1]]
    m = int(pady_css * dpr)
    top = max(first[0] - m, bands[keep[0] - 1][1] if keep[0] > 0 else 0)
    bot = min(last[1] + m, bands[keep[-1] + 1][0] if keep[-1] + 1 < len(bands) else h)
    im.crop((0, top, w, bot)).save(path)
    return top, h - bot


def ocr_ratio(path, phrase):
    if not os.path.exists(OCR):
        return None, None
    r = subprocess.run([OCR, path], capture_output=True, text=True, timeout=60)
    if r.returncode or not r.stdout.strip():
        return None, None
    d = json.loads(r.stdout.splitlines()[0])
    txt = " ".join(l["text"] for l in d.get("lines", []))
    f = lambda s: re.sub(r"[^a-z0-9]", "", norm(s).lower())
    a, b = f(txt), f(phrase)
    if not b:
        return None, txt
    # Vision reads "AI" as "Al": fold l/i/1 together on both sides so that read is not a miss
    g = lambda s: re.sub(r"[il1|]", "l", s)
    sm = difflib.SequenceMatcher(None, g(a), g(b), autojunk=False)
    blk = sm.find_longest_match(0, len(g(a)), 0, len(g(b)))
    return round(max(sm.ratio(), blk.size / float(len(g(b)))), 3), txt


# ------------------------------------------------------------------ the browser
def open_page(pw, url, fetch, wait, dpr):
    """-> (browser, ctx, page, status, mode). mode 'browser' or 'curl' (HTML fetched with curl and served to the page under its own URL:
    the trick S103/S118 needed for sites that refuse a headless client)."""
    exe = CHROME if os.path.exists(CHROME) else None
    br = pw.chromium.launch(headless=True, **({"executable_path": exe} if exe else {}))
    ctx = br.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=dpr, locale="en-GB", user_agent=UA)
    ctx.route(NOISE_URL, lambda r: r.abort())
    status, mode = None, fetch
    if fetch == "curl":
        r = subprocess.run(["curl", "-sL", "-m", "60", "-A", UA, "-w", "\n%{http_code}", url], capture_output=True, timeout=90)
        body, _, code = r.stdout.rpartition(b"\n")
        status = int(code or 0)
        ctx.route(url, lambda route, request=None: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body))
    pg = ctx.new_page()
    try:
        resp = pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        if fetch != "curl":
            status = resp.status if resp else None
    except Exception as e:
        raise Fail(3, "page unreachable: %s" % str(e).splitlines()[0][:160], url=url)
    try:
        pg.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    pg.add_style_tag(content=HIDE_CSS)
    pg.wait_for_timeout(int(wait * 1000))
    return br, ctx, pg, status, mode


def page_problem(pg, status):
    b = pg.evaluate(JS_BODY)
    if status is not None and status >= 400:
        return "HTTP %s" % status, b
    if b["textLen"] < 200:
        return "page has only %d characters of visible text (blank, or a script wall)" % b["textLen"], b
    if CHALLENGE.search(b["title"]) or (b["textLen"] < 1500 and CHALLENGE.search(b["head"])):
        return "block or challenge page (title %r)" % b["title"][:60], b
    return None, b


def locate(pw, a):
    """open + find; returns everything the later stages need. Raises Fail."""
    target = norm(a.phrase)
    tried = []
    modes = ["browser", "curl"] if a.fetch == "auto" else [a.fetch]
    last = None
    for mode in modes:
        br = None
        try:
            br, ctx, pg, status, mode_used = open_page(pw, a.url, mode, a.wait, DPR)
            prob, body = page_problem(pg, status)
            if prob:
                tried.append("%s: %s" % (mode, prob)); br.close(); last = Fail(3, "page blocked or blank (%s)" % "; ".join(tried), url=a.url, tried=tried); continue
            f = pg.evaluate(JS_FIND, target)
            if not f["usable"]:
                br.close()
                raise Fail(2, "phrase not found verbatim on the page (%d chars of visible text searched, mode %s): %r" % (f["textLen"], mode, a.phrase),
                           url=a.url, phrase=a.phrase, normalised=target, page_text_chars=f["textLen"], page_title=body["title"])
            return br, ctx, pg, status, mode, f, body
        except Fail as e:
            if br and e.code != 2:
                try: br.close()
                except Exception: pass
            if e.code == 2:
                raise
            last = e; tried.append("%s: %s" % (mode, e.msg))
        except Exception as e:
            last = Fail(3, "browser error: %s" % str(e).splitlines()[0][:160], url=a.url); tried.append("%s: %s" % (mode, last.msg))
            if br:
                try: br.close()
                except Exception: pass
    raise last or Fail(3, "page could not be opened", url=a.url)


def card_geometry(r, card_w):
    f = r["font"]
    padl = 0.0 if r.get("prevCh", " ").strip() else max(1.5, 0.08 * f)      # a neighbour glyph touches this side: crop exactly at the word edge
    padr = 0.0 if r.get("nextCh", " ").strip() else max(1.5, 0.08 * f)
    # vertical pad: never into the line above or below. Free space above and below the glyph box is half the leading: (line-height - box height) / 2
    lh = r.get("lh") or 1.2 * f
    pady = max(0.03 * f, min(0.10 * f, (lh - r["u"][3]) / 2.0 + 0.04 * f))       # never less than 3% of an em: descender tips touch the content-area edge
    u = r["u"]; cw = u[2] + padl + padr
    k = card_w / cw
    return {"padl": padl, "padr": padr, "pady": pady, "css_w": cw, "k": k, "px_font": f * k, "px_xheight": r["xh"] * k, "px_box": u[3] * k * 0.8}


def make_card_preview(png, out, card_w, credit_line, px_note):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(png).convert("RGB"); k = card_w / float(im.width)
    im = im.resize((card_w, max(1, int(round(im.height * k)))), Image.LANCZOS)
    strip = 78
    card = Image.new("RGB", (card_w, im.height + strip), (255, 255, 255)); card.paste(im, (0, 0))
    d = ImageDraw.Draw(card)
    fnt, fpath = None, None
    for p in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Supplemental/Courier New.ttf", "/Library/Fonts/Arial.ttf"):
        if os.path.exists(p):
            try: fnt = ImageFont.truetype(p, 34); fpath = p; break
            except Exception: pass
    fnt = fnt or ImageFont.load_default()
    d.line([(0, im.height), (card_w, im.height)], fill=(200, 200, 200), width=2)
    size = 34
    while fpath and size > 12 and d.textlength(credit_line, font=ImageFont.truetype(fpath, size)) > card_w - 28:
        size -= 2
    if fpath:
        fnt = ImageFont.truetype(fpath, size)
    d.text((14, im.height + 8), credit_line, fill=(40, 40, 40), font=fnt)
    try: fs = ImageFont.truetype(fpath, 20) if fpath else fnt
    except Exception: fs = fnt
    d.text((14, im.height + 50), px_note, fill=(120, 120, 120), font=fs or fnt)
    card.save(out)


def main_inner(a):
    from playwright.sync_api import sync_playwright
    os.makedirs(a.out, exist_ok=True)
    key = a.key
    t0 = time.time(); checks = {}; tm = {}
    stale = os.path.join(a.out, key + ".FAIL.json")
    if os.path.exists(stale):
        os.remove(stale)
    with sync_playwright() as pw:
        br, ctx, pg, status, mode, found, body = locate(pw, a)
        tm["open_and_find"] = round(time.time() - t0, 1)
        try:
            checks["page"] = {"status": status, "fetch_mode": mode, "title": body["title"][:120], "visible_text_chars": body["textLen"]}
            checks["find"] = {"occurrences": found["occurrences"], "painted_occurrences": found["painted"]}
            if not found["painted"]:
                raise Fail(4, "the phrase is in the DOM but has no painted box (display/visibility hides it): the crop would be blank", url=a.url, phrase=a.phrase)
            meta = pg.evaluate(JS_META)
            cands = []
            for w in WIDTHS:
                pg.set_viewport_size({"width": w, "height": 900}); pg.wait_for_timeout(120)
                # layout changed: rebuild the range (nodes survive; the Range object still points at them)
                r = pg.evaluate(JS_ANALYSE)
                if not r or not r.get("own"):
                    cands.append({"w": w, "lines": 0}); continue
                r["w"] = w
                u_ = r["u"]
                if u_[0] < -0.5 or u_[0] + u_[2] > w + 0.5:      # the page is wider than the viewport and the words sit past its edge: not a usable layout
                    r["lines"] = -1
                cands.append(r)
            tm["sweep_done"] = round(time.time() - t0, 1)
            one = [c for c in cands if c.get("lines") == 1]
            seen = sorted(set(c.get("lines", 0) for c in cands if c.get("lines", 0) > 0))
            if not one:
                raise Fail(8, "the phrase cannot sit on one line, fully inside the viewport, at any width 320-2400 css (line counts seen: %s). Use a shorter clause the voice actually says; this tool never reflows page text." % seen,
                           url=a.url, phrase=a.phrase, lines_seen=seen)
            clear = [c for c in one if c["covered"] < 2]
            if not clear:
                raise Fail(7, "the phrase is covered by <%s> (an overlay or banner sits on top of it at every width where it fits one line)" % one[0]["coverer"], url=a.url, coverer=one[0]["coverer"])
            one = clear
            for c in one:
                c["geo"] = card_geometry(c, a.card_w)
            best = max(one, key=lambda c: (round(c["geo"]["px_" + {"font": "font", "xheight": "xheight", "box": "box"}[a.metric]], 3), -c["w"]))
            geo = best["geo"]
            metric_px = geo["px_" + a.metric]
            checks["layout"] = {"viewport_css": best["w"], "single_line_widths": len(one), "of": len(cands), "font_css": best["font"], "family": best["family"],
                                "weight": best["weight"], "color": best["color"], "background": best["bg"], "text_transform": best["transform"], "opacity": round(best["opacity"], 3)}
            # --- size gate before spending a screenshot
            result_px = {"font": round(geo["px_font"], 1), "xheight": round(geo["px_xheight"], 1), "box": round(geo["px_box"], 1)}
            if metric_px < a.min_px:
                fit_chars = int(len(norm(a.phrase)) * metric_px / a.min_px)
                raise Fail(5, "clause too long: at card width %d px it renders at %.1f px (%s metric), under --min-px %d. About %d characters of this clause would fit at %d px; "
                              "cut it to the part the voice says." % (a.card_w, metric_px, a.metric, a.min_px, fit_chars, a.min_px),
                           url=a.url, phrase=a.phrase, px_at_card_width=result_px, phrase_chars=len(norm(a.phrase)), fit_chars=fit_chars, font_css=best["font"])
            # --- date and publisher: from the page, never invented
            dates = [(src, parse_date(v)) for src, v in meta["dates"]]
            dates = [(s, d) for s, d in dates if d]
            publisher, pub_src = publisher_of(a.url, meta)
            if a.credit:
                publisher, pub_src = a.credit.strip().upper(), "--credit"
            if dates:
                date_src, (date_txt, date_iso) = dates[0]
                credit_line = "%s, %s" % (publisher, date_txt)
            else:
                date_src, date_txt, date_iso = None, None, None
                if not a.allow_undated:
                    raise Fail(6, "no publication date in the page's metadata or beside the headline. The credit must carry a date; re-run with --allow-undated to credit "
                                  "'%s, DATE NOT PUBLISHED ON PAGE', or choose a source that dates itself." % publisher,
                               url=a.url, date_candidates_checked=[s for s, _ in meta["dates"]] or "none present", publisher=publisher)
                credit_line = "%s, DATE NOT PUBLISHED ON PAGE" % publisher
            # --- the crop is taken at device scale DPR. A card only ever needs min_px of glyph, so the source must hold min_px / font pixels per css px;
            # a short clause shown at the full card width is bigger than that and is simply not stretched past its own pixels (see max_sharp_width_px).
            need = a.min_px / best["font"]
            if need > DPR:
                raise Fail(5, "the page's own text is %.1f css px: reaching %d px on the card needs %.1fx magnification and the crop is taken at %dx. Choose a clause from larger type (headline, standfirst, pull quote)." % (best["font"], a.min_px, need, DPR),
                           url=a.url, phrase=a.phrase, font_css=best["font"])
            pg.set_viewport_size({"width": best["w"], "height": 900}); pg.wait_for_timeout(150)
            r = pg.evaluate(JS_ANALYSE)
            u = r["u"]; sx, sy = r["sx"], r["sy"]
            png = os.path.join(a.out, key + ".png")
            vx, vy = max(0, u[0] - geo["padl"]), max(0, u[1] - geo["pady"])
            in_view = u[1] - geo["pady"] >= 0 and u[1] + u[3] + geo["pady"] <= 900 and u[0] + u[2] + geo["padr"] <= best["w"] + 0.5
            if in_view:          # element was scrolled to the middle of the viewport: clip in viewport coordinates, no full-page surface
                clip = {"x": vx, "y": vy, "width": u[2] + geo["padl"] + geo["padr"], "height": u[3] + 2 * geo["pady"]}
                pg.screenshot(path=png, clip=clip)
                clip_page = dict(clip, x=clip["x"] + sx, y=clip["y"] + sy)
            else:
                clip_page = {"x": max(0, u[0] + sx - geo["padl"]), "y": max(0, u[1] + sy - geo["pady"]), "width": u[2] + geo["padl"] + geo["padr"], "height": u[3] + 2 * geo["pady"]}
                pg.screenshot(path=png, clip=clip_page, full_page=True)
            clip = clip_page
            tm["screenshot_done"] = round(time.time() - t0, 1)
        finally:
            br.close()
    cut_top, cut_bot = trim_strays(png, DPR, geo["pady"])
    st = pixel_stats(png); checks["pixels"] = st
    checks["trimmed_stray_rows_device_px"] = {"top": cut_top, "bottom": cut_bot}
    if st["ink_fraction"] < 0.004 or st["std"] < 8:
        os.remove(png)
        raise Fail(4, "the crop is blank: ink %.2f%% of pixels, std %.1f (text is in the DOM but not painted: transparent colour, opacity 0, an animation not yet finished, "
                      "or a covering layer). Re-run with a longer --wait, or choose another source." % (st["ink_fraction"] * 100, st["std"]), url=a.url, pixels=st)
    ratio, txt = ocr_ratio(png, a.phrase)
    checks["ocr"] = {"ratio": ratio, "read": (txt or "")[:200]}
    if ratio is not None and ratio < 0.75:
        os.remove(png)
        raise Fail(4, "the crop does not read as the phrase: OCR match %.2f (read %r)" % (ratio, (txt or "")[:80]), url=a.url, ocr=checks["ocr"])
    dpr = DPR
    warns = []
    if any(c in a.phrase for c in "–—"):
        warns.append("phrase contains an en or em dash: the render gate's OCR checks 1/2 fail on those; crop past the dash")
    if date_src and date_src.startswith("visible"):
        warns.append("date came from a visible date element beside the headline, not machine-readable metadata (no JSON-LD or meta date on this page): check it is the publication date, not an update")
    if found["occurrences"] > 1:
        warns.append("phrase occurs %d times on the page; the first painted one was cropped" % found["occurrences"])
    if best["transform"] not in ("none", ""):
        warns.append("CSS text-transform %s: the card shows the rendered case" % best["transform"])
    e = st["edge_ink"]
    if max(e["top"], e["bottom"]) > 0.10:
        os.remove(png)
        raise Fail(8, "a neighbouring line overlaps the phrase's line (ink on %.0f%% of the crop's top/bottom edge row after trimming): the clause cannot be isolated on one line on this page" % (100 * max(e["top"], e["bottom"])),
                   url=a.url, phrase=a.phrase, edge_ink=e)
    if max(e["top"], e["bottom"]) > 0.02 or max(e["left"], e["right"]) > 0.03:
        warns.append("ink touches a crop edge (%s): a neighbouring line or glyph may be clipped; look at the preview" % e)
    if geo["k"] > dpr:
        warns.append("at the full card width (%d px) this crop is stretched %.1fx past its %d px; show it no wider than %d px (it still reads %.0f px at that width)"
                     % (a.card_w, geo["k"] / dpr, st["w"], st["w"], geo["px_font"] * st["w"] / float(a.card_w)))
    if best["opacity"] < 0.9:
        warns.append("text opacity %.2f on the page" % best["opacity"])
    # --- sources.js item (compose.py / S44-S50 shape: css px; S118 shape: marks_px + pitch)
    cw_css, ch_css = clip["width"], clip["height"]
    mx = u[0] + sx - clip["x"]; my = u[1] + sy - clip["y"] - cut_top / float(dpr)
    mh = u[3]
    if my < 0:
        mh += my; my = 0.0
    mh = min(mh, st["h"] / float(dpr) - my)
    mark = [round(mx, 2), round(my, 2), round(u[2], 2), round(mh, 2)]
    if cut_top or cut_bot:
        warns.append("trimmed a neighbouring line's stray glyph rows from the crop (top %d, bottom %d device px)" % (cut_top, cut_bot))
    cssw, cssh = round(st["w"] / float(dpr), 2), round(st["h"] / float(dpr), 2)
    src = "img/real-%s-%s.png" % (a.id.lower(), re.sub(r"[^a-z0-9_]", "", key.lower().replace("-", "_")))
    item = {"src": src, "px": [st["w"], st["h"]], "css": [cssw, cssh], "marks": {a.phrase: [mark]}, "marks_px": {a.phrase: [[round(v * dpr) for v in mark]]},
            "lines": [[mark[0], mark[1], mark[2], mark[3], a.phrase]], "text": a.phrase, "url": a.url, "credit": publisher, "date": date_txt,
            "credit_line": credit_line, "pitch": round(best["font"] * 1.3 * dpr), "font_css": best["font"], "dpr": dpr,
            "px_at_card_width": result_px, "card_w": a.card_w, "max_sharp_width_px": st["w"], "by": "tools/crop_clause.py"}
    if date_txt is None:
        item["date"] = None
    js_ = {"url": a.url, "phrase": a.phrase, "id": a.id, "key": key, "publisher": publisher, "publisher_source": pub_src, "date": date_txt, "date_iso": date_iso,
           "date_source": date_src, "credit": credit_line, "headline": meta.get("ogTitle") or meta.get("title") or meta.get("h1"), "card_w": a.card_w, "min_px": a.min_px, "metric": a.metric,
           "px_at_card_width": result_px, "px_at_card_width_gated": round(metric_px, 1), "magnification_at_card_width": round(geo["k"], 2), "device_scale": dpr,
           "max_sharp_width_px": st["w"], "upscaled_at_card_width": geo["k"] > dpr,
           "crop_box": {"x": round(clip["x"], 2), "y": round(clip["y"], 2), "w": round(clip["width"], 2), "h": round(clip["height"], 2), "units": "css px, page coordinates",
                        "viewport_css": best["w"], "png_px": [st["w"], st["h"]]},
           "mark_rect_css": mark, "checks": checks, "warnings": warns, "timings_s": tm, "captured": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - t0, 1), "png": png}
    json.dump(js_, open(os.path.join(a.out, key + ".json"), "w"), indent=1, ensure_ascii=False)
    snippet = "window.%s_SRC = %s;\n" % (a.id, json.dumps({"captured": time.strftime("%Y-%m-%d"), "by": "tools/crop_clause.py", "items": {key: item}}, indent=1, ensure_ascii=False))
    open(os.path.join(a.out, key + ".sources.js"), "w").write(snippet)
    pw_ = min(a.card_w, st["w"]); kk = pw_ / float(a.card_w)
    make_card_preview(png, os.path.join(a.out, key + ".preview.png"), pw_, credit_line, "px at %d wide: font %.1f | x-height %.1f | box %.1f" % (pw_, result_px["font"] * kk, result_px["xheight"] * kk, result_px["box"] * kk))
    if a.install:
        install(a, key, item, png)
    for w_ in warns:
        print("CROP_CLAUSE WARN %s" % w_, file=sys.stderr)
    print("CROP_CLAUSE OK %s/%s  %s | %s | %.1f px at %d wide (%s) | %d x %d px | viewport %d | %s" % (
        a.id, key, publisher, date_txt or "NO DATE", metric_px, a.card_w, a.metric, st["w"], st["h"], best["w"], png))
    return 0


def install(a, key, item, png):
    spec = os.path.join(os.environ.get("CROP_CLAUSE_SPECS") or os.path.join(KIT, "specs"), a.id); sj = os.path.join(spec, "sources.js")
    os.makedirs(os.path.join(spec, "media"), exist_ok=True)
    d = {"items": {}}
    if os.path.exists(sj):
        t = open(sj).read(); d = json.loads(t[t.index("{"):t.rindex("}") + 1]); d.setdefault("items", {})
        shutil.copyfile(sj, sj + ".bak-2026-10-06-cropclause")
    d["items"][key] = item
    open(sj, "w").write("window.%s_SRC = %s;\n" % (a.id, json.dumps(d, indent=1, ensure_ascii=False)))
    shutil.copyfile(png, os.path.join(spec, "media", os.path.basename(item["src"]).split("real-%s-" % a.id.lower(), 1)[-1]))
    print("CROP_CLAUSE installed %s into %s (backup .bak-2026-10-06-cropclause) and specs/%s/media/" % (key, sj, a.id))


def slug(p):
    return re.sub(r"[^a-z0-9]+", "-", norm(p).lower()).strip("-")[:40].strip("-") or "clause"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True); ap.add_argument("--phrase", required=True); ap.add_argument("--id", required=True, help="short id, e.g. S50")
    ap.add_argument("--key"); ap.add_argument("--min-px", type=float, default=48); ap.add_argument("--card-w", type=int, default=960)
    ap.add_argument("--out"); ap.add_argument("--metric", choices=["font", "xheight", "box"], default="font")
    ap.add_argument("--wait", type=float, default=2.0); ap.add_argument("--fetch", choices=["auto", "browser", "curl"], default="auto")
    ap.add_argument("--credit", help="publisher text for the credit line (e.g. \"MORGAN STANLEY PRESS RELEASE\"); the date still comes from the page")
    ap.add_argument("--allow-undated", action="store_true"); ap.add_argument("--install", action="store_true"); ap.add_argument("--no-heavy", action="store_true")
    a = ap.parse_args()
    if not re.match(r"^[A-Za-z][A-Za-z0-9]*$", a.id):
        print("CROP_CLAUSE FAIL 1 --id must be like S50", file=sys.stderr); return 1
    if not re.match(r"^(https?|file)://", a.url):
        print("CROP_CLAUSE FAIL 1 --url must be http(s):// or file://", file=sys.stderr); return 1
    a.key = a.key or slug(a.phrase)
    a.out = a.out or os.path.join(KIT, "media", a.id, "clauses")
    if not os.environ.get("CROP_CLAUSE_IN_HEAVY") and not a.no_heavy:
        env = dict(os.environ, CROP_CLAUSE_IN_HEAVY="1")
        return subprocess.call([sys.executable, HEAVY, "--", sys.executable, os.path.abspath(__file__)] + sys.argv[1:], env=env)
    try:
        return main_inner(a)
    except Fail as e:
        os.makedirs(a.out, exist_ok=True)
        rec = {"ok": False, "code": e.code, "message": e.msg, "id": a.id, "key": a.key, "phrase": a.phrase, "url": a.url, "detail": e.detail, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        json.dump(rec, open(os.path.join(a.out, a.key + ".FAIL.json"), "w"), indent=1, ensure_ascii=False, default=str)
        print("CROP_CLAUSE FAIL %d %s" % (e.code, e.msg), file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
