#!/usr/bin/env python3
"""source_media.py: build the REAL MEDIA pack for one short or film (Sam: "show the real thing").

For every factual claim and every named entity in a short's script and fact ledger (shorts/scripts-v2/<ID>.md) or a
film's dossier (films/dossiers/<name>/facts.json), collect the real evidence into v2/kit/media/<ID>/:
  pages/    source page screenshots at 2x: fold, hero (headline + standfirst + byline + date), masthead, and one crop per
            claim paragraph with highlight boxes. Article photographs are greyed (s.30(2) never covers photographs).
  docs/     primary documents (regulator notices, judgments, filings, press releases): PDF pages at 200 dpi, plus the
            claim's region cropped; scanned PDFs are OCR'd locally (tools/ocr_vision.swift, macOS Vision).
  logos/    official logos: Wikidata P154 -> Wikimedia Commons SVG rendered at 2x; else Commons search; else brand page.
  photos/   licensed photos of places/products (Commons, licence whitelist), flagged for a human people check.
  clips/    clip candidates (yt-dlp search, Creative Commons first) with in/out from captions and a still at in-point.
  manifest.json  every asset: source URL, retrieval time, licence, rights basis, credit line, claims it evidences.
  EVIDENCE.md    claim -> assets table, or "none available" with the reason.   contact.jpg  every image, labelled.
Rules: v2/kit/media/MEDIA-RULES.md. Headless only: every browser, PDF, OCR and ffmpeg job runs through tools/heavy.py.

Usage:
  source_media.py <ID> [--no-clips] [--refresh]    build or rebuild the pack (plan.json is created on first run; edit it)
  source_media.py verify <ID>                      exit 1 unless every claim is evidenced or explicitly none-available,
                                                   and every usable asset has file, source, retrieval time, licence, credit
Internal (run under heavy.py): _browser <jobs.json> <out.json> · _pdf <jobs.json> <out.json>
"""
import datetime, glob, hashlib, html, json, os, re, shutil, subprocess, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
V2 = os.path.dirname(KIT)
MEDIA = os.path.join(KIT, "media")
HEAVY = os.path.join(HERE, "heavy.py")
OCR_SRC = os.path.join(HERE, "ocr_vision.swift")
OCR_BIN = os.path.join(HERE, ".bin", "ocr_vision")
WHISPER_PY = os.path.expanduser("~/alfred/yt-engine/.venv/bin/python")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0.0.0 Safari/537.36")
WIKI_UA = "AGMM-source-media/1.0 (agmm.co.uk; editorial research)"

# ----------------------------------------------------------------------------------------------------------- helpers

def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def slug(s, n=48):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:n].strip("-") or "x"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def http(url, ua=UA, timeout=40, binary=False, tries=2):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "en-GB,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                return r.status, r.headers.get("Content-Type", ""), r.geturl(), (data if binary else data.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = (e.code, e.headers.get("Content-Type", "") if e.headers else "", url, b"" if binary else "")
            if e.code in (429, 503) and i + 1 < tries:
                time.sleep(15 * (i + 1)); continue
            return last
        except Exception as e:  # noqa: BLE001
            last = (0, "", url, b"" if binary else "")
            time.sleep(2)
    return last


def api_json(url):
    """Wikimedia/Wayback JSON with an on-disk cache (media/_cache/api) and polite pacing: Wikimedia answers HTTP 429
    "too many requests" when many writers share this Mac's IP, so reruns must not re-ask."""
    cdir = os.path.join(MEDIA, "_cache", "api")
    os.makedirs(cdir, exist_ok=True)
    cf = os.path.join(cdir, hashlib.sha1(url.encode()).hexdigest() + ".json")
    if os.path.exists(cf) and time.time() - os.path.getmtime(cf) < 7 * 86400:
        return json.load(open(cf))
    for i in range(4):
        time.sleep(1.0)
        st, ct, _, body = http(url, ua=WIKI_UA, tries=1)
        if st == 200:
            try:
                j = json.loads(body)
            except ValueError:
                j = None
            if j is not None:
                json.dump(j, open(cf, "w"))
                return j
        if st in (429, 503, 0):
            time.sleep(20 * (i + 1)); continue
        break
    return {}


def heavy(cmd, timeout=1800):
    """Run a heavy job through heavy.py (machine-wide slots, nice 15)."""
    return subprocess.run([sys.executable, HEAVY, "--"] + cmd, capture_output=True, text=True, timeout=timeout)


def strip_html(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(s or "")))).strip()


def nice_date(d):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", d or "")
    if not m:
        return d
    return "%d %s %s" % (int(m.group(3)), "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()[int(m.group(2)) - 1], m.group(1))


def domain(url):
    return urllib.parse.urlparse(url).netloc.lower().replace("www.", "")

# ----------------------------------------------------------------------------------------------- licence knowledge

OUTLETS = {  # domain -> (display name, organisation for the credit)
    "theguardian.com": "The Guardian", "bbc.co.uk": "BBC News", "bbc.com": "BBC News", "fca.org.uk": "Financial Conduct Authority",
    "tomshardware.com": "Tom's Hardware", "ndtv.com": "NDTV", "reuters.com": "Reuters", "ft.com": "Financial Times",
    "gov.uk": "GOV.UK", "ncsc.gov.uk": "National Cyber Security Centre", "cisa.gov": "CISA",
    "find-and-update.company-information.service.gov.uk": "Companies House", "company-information.service.gov.uk": "Companies House",
    "starlingbank.com": "Starling Bank", "apps.apple.com": "Apple App Store", "web.archive.org": "Internet Archive",
    "judiciary.uk": "Courts and Tribunals Judiciary", "caselaw.nationalarchives.gov.uk": "The National Archives, Find Case Law",
    "theregister.com": "The Register", "independent.co.uk": "The Independent", "telegraph.co.uk": "The Telegraph",
    "thetimes.com": "The Times", "thetimes.co.uk": "The Times", "sky.com": "Sky News", "news.sky.com": "Sky News",
    "cfodive.com": "CFO Dive", "businessinsider.com": "Business Insider", "cnn.com": "CNN",
}
AUTHORITY = ("fca.org.uk", "gov.uk", "judiciary.uk", "bailii.org", "nationalarchives.gov.uk", "parliament.uk",
             "bankofengland.co.uk", "ico.org.uk", "ncsc.gov.uk", "sfo.gov.uk", "cma.gov.uk", "ofcom.org.uk",
             "legislation.gov.uk", "sec.gov", "justice.gov", "cisa.gov", "europa.eu", "bbc.co.uk/news", "bbc.com/news",
             "reuters.com", "company-information.service.gov.uk")
NOT_USABLE = (("bbc.co.uk/iplayer", "BBC iPlayer programme: BBC copyright, no licence to download or clip; describe it, cite it, don't show it"),
              ("bbc.co.uk/sounds", "BBC Sounds: no licence to clip"),)
BROADCASTERS = re.compile(r"\b(bbc|sky news|itv|channel 4|gb news|reuters|bloomberg|cnbc|guardian|financial times|"
                          r"the times|telegraph|al jazeera|cnn|fox|abc news|nbc|cbs|euronews|dw news|independent)\b", re.I)
PD_GOOD = re.compile(r"^(cc0|cc[ -]by([ -]sa)?[ -]?\d(\.\d)?|cc[ -]by([ -]sa)?|public domain|pd|pd-[\w-]+|ogl|open government licence.*)$", re.I)
PEOPLEY = re.compile(r"\b(man|woman|men|women|people|person|portrait|crowd|pride|staff|team|ceo|founder|headshot|selfie|"
                     r"boy|girl|child|children|wedding|party)\b", re.I)


def page_rights(url, page_text=""):
    """(licence, rights_basis, credit_org) for a captured page or document."""
    d = domain(url)
    org = next((v for k, v in OUTLETS.items() if d == k or d.endswith("." + k)), d)
    t = page_text or ""
    if d.endswith("fca.org.uk"):
        return ("© The Financial Conduct Authority (FCA terms, not OGL; fca.org.uk/legal cl.3)",
                "UK fair dealing: criticism/review and quotation (CDPA s.30(1), s.30(1ZA)); reproduced unmodified, acknowledged",
                "Financial Conduct Authority")
    if "company-information.service.gov.uk" in d:
        return ("Public register document (Companies House); content is the filer's",
                "UK fair dealing: quotation / reporting (CDPA s.30); redact private individuals", "Companies House")
    if d.endswith("ncsc.gov.uk"):  # verified 25 Sep: ncsc.gov.uk terms-and-conditions, "Use of website content": OGL v3.0
        return ("Open Government Licence v3.0 (Crown copyright; NCSC website terms)", "Licence: OGL v3.0, acknowledge the NCSC and link the OGL",
                "National Cyber Security Centre")
    if re.search(r"Open Government Licence", t) or (d.endswith("gov.uk") and not t):
        return ("Open Government Licence v3.0", "Licence: OGL v3.0, attribution statement required", org)
    if re.search(r"Open Justice Licence", t):
        return ("Open Justice Licence", "Licence: Open Justice Licence", org)
    if d.endswith(".gov") and not d.endswith("gov.uk"):
        return ("US federal government work, public domain (17 U.S.C. 105)", "Public domain (US federal work); credit the agency", org)
    if d == "web.archive.org":
        return ("© the archived site's owner; archived copy by the Internet Archive",
                "UK fair dealing: quotation / criticism and review (CDPA s.30); credit site + archive date", org)
    return ("© %s, all rights reserved" % org,
            "UK fair dealing: quotation, criticism/review, news reporting of text (CDPA s.30(1), (1ZA), (2)); photos masked", org)

# ------------------------------------------------------------------------------------------------------ story input

def load_story(sid):
    sid = sid.upper()
    if sid[0] in "SC":
        return load_short(sid)
    if sid[0] == "F":
        return load_film(sid)
    sys.exit("unknown ID kind: %s" % sid)


def md_section(txt, name):
    m = re.search(r"^## %s[^\n]*\n(.*?)(?=^## |\Z)" % re.escape(name), txt, re.M | re.S)
    return m.group(1).strip() if m else ""


def load_short(sid):
    path = os.path.join(V2, "shorts", "scripts-v2", sid + ".md")
    txt = open(path).read()
    company = (re.search(r"^\| Company \| (.+?) \|", txt, re.M) or [None, sid])[1]
    sources = re.findall(r"^- (https?://\S+)", md_section(txt, "Sources used"), re.M)
    claims = []
    for row in md_section(txt, "Fact ledger (every spoken claim and where it comes from)").splitlines() or \
            md_section(txt, "Fact ledger").splitlines():
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("Claim", "") or set(cells[0]) <= set("-: "):
            continue
        refs = [int(n) - 1 for n in re.findall(r"%s_(\d+)" % sid, cells[1])]
        claims.append({"n": len(claims) + 1, "text": cells[0], "source_label": cells[1],
                       "source_urls": [sources[i] for i in refs if 0 <= i < len(sources)] or sources[:1]})
    return {"id": sid, "kind": "short", "path": path, "company": company, "sources": sources, "claims": claims,
            "script": md_section(txt, "Spoken script"), "legal": md_section(txt, "Legal notes"),
            "title": (re.search(r"^# (.+)$", txt, re.M) or [None, sid])[1]}


def load_film(fid):
    d = glob.glob(os.path.join(V2, "films", fid + "-*"))
    if not d:
        sys.exit("no film folder for %s" % fid)
    name = os.path.basename(d[0]).split("-", 1)[1]
    path = os.path.join(V2, "films", "dossiers", name, "facts.json")
    j = json.load(open(path))
    items = list(j.get("facts") or [])
    fb = j.get("fact_bank") or {}
    if isinstance(fb, dict):
        for k, v in fb.items():
            items += [dict(x, category=k) for x in v if isinstance(x, dict)]
    for x in j.get("timeline") or []:
        if isinstance(x, dict) and x.get("url"):
            items.append({"fact": x.get("event") or x.get("fact") or x.get("what") or "", "url": x["url"], "date": x.get("date")})
    claims, sources = [], []
    for x in items:
        u = x.get("url") or x.get("source_url")
        text = x.get("fact") or x.get("claim") or ""
        if not text:
            continue
        if u and u not in sources:
            sources.append(u)
        claims.append({"n": len(claims) + 1, "text": text, "source_label": x.get("source") or domain(u or ""),
                       "source_urls": [u] if u else [], "snippet": x.get("snippet")})
    extra = [v["url"] for v in (j.get("visual_sources") or []) if isinstance(v, dict) and v.get("url")]
    return {"id": fid, "kind": "film", "path": path, "company": j.get("protagonist") or j.get("working_title") or name,
            "sources": sources, "claims": claims, "script": "", "legal": "", "title": j.get("working_title") or name,
            "visual_sources": extra}

# ------------------------------------------------------------------------------------------------ claim matching

NUM_RE = re.compile(r"£?\d[\d,]*(?:\.\d+)?\s*(?:million|billion|bn|m|k)?(?![\w])", re.I)
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def num_alts(tok):
    """Regex alternatives for a number as written in the ledger: '3,088' also '3088'; '£29m' also '£29 million'."""
    t = tok.strip()
    m = re.match(r"(£?)(\d[\d,]*(?:\.\d+)?)\s*(million|billion|bn|m|k)?$", t, re.I)
    if not m:
        return [re.escape(t)]
    cur, n, unit = m.group(1), m.group(2), (m.group(3) or "").lower()
    bare = n.replace(",", "")
    forms = {n, bare}
    if len(bare) > 3 and "," not in n and "." not in bare and not re.fullmatch(r"(19|20)\d\d", bare):
        forms.add("{:,}".format(int(bare)))
    alts = []
    for f in forms:
        f = re.escape(f)
        if unit in ("m", "million"):
            alts += [r"%s%s\s*(?:m\b|million)" % (re.escape(cur) + "?", f)]
        elif unit in ("bn", "billion"):
            alts += [r"%s%s\s*(?:bn\b|billion)" % (re.escape(cur) + "?", f)]
        else:
            alts += [r"(?<![\d.,])%s%s(?![\d]|,\d)" % (re.escape(cur) + ("?" if cur else ""), f)]
    return alts


def auto_find(text):
    """Default token groups for a claim: every number, every quoted phrase, every Month YYYY. Each group is a list of
    regex alternatives; a location matches the claim when it matches enough distinct groups."""
    groups = []
    for q in re.findall(r"['‘“\"]([^'’”\"]{4,80})['’”\"]", text):
        groups.append([re.escape(q.strip()).replace(r"\ ", r"\s+")])
    rest = re.sub(r"['‘“\"][^'’”\"]{4,80}['’”\"]", " ", text)
    for m in re.findall(r"(?:%s)\s+\d{4}" % MONTHS, rest):
        groups.append([re.escape(m).replace(r"\ ", r"\s+")])
    rest = re.sub(r"(?:%s)\s+\d{4}" % MONTHS, " ", rest)
    for tok in NUM_RE.findall(rest):
        tok = tok.strip().rstrip(",.")
        if re.fullmatch(r"\d", tok):
            continue
        groups.append(num_alts(tok))
    seen, out = set(), []
    for g in groups:
        k = tuple(g)
        if k not in seen:
            seen.add(k); out.append(g)
    return out


def claim_jobs(story, plan):
    out = []
    for c in story["claims"]:
        o = (plan.get("claims") or {}).get(str(c["n"]), {})
        groups = [g if isinstance(g, list) else [g] for g in o.get("find", [])] or auto_find(c["text"])
        need = o.get("need") or (min(2, len(groups)) if groups else 0)
        out.append({"n": c["n"], "groups": groups, "need": need})
    return out


def match_text(text, groups):
    """-> (score, [(start, end)]) over normalised text."""
    spans, score = [], 0
    for g in groups:
        hit = None
        for alt in g:
            m = re.search(alt, text, re.I)
            if m:
                hit = m; break
        if hit:
            score += 1; spans.append((hit.start(), hit.end()))
    return score, spans


def norm1(s):  # 1:1 character normalisation (keeps offsets)
    return (s.replace(" ", " ").replace("‘", "'").replace("’", "'").replace("“", '"')
            .replace("”", '"').replace("–", "-").replace("—", "-").replace(" ", " ").replace(" ", " "))

# ------------------------------------------------------------------------------------------------ browser worker

PAGE_JS_PREP = r"""
() => {
  const kill = [];
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.position === 'fixed') kill.push(el);
    else if (cs.position === 'sticky') el.style.position = 'static';
  }
  kill.forEach(el => el.style.setProperty('display', 'none', 'important'));
  for (const el of document.querySelectorAll('[id*="sp_message"],[class*="sp_message"],[id*="onetrust"],[class*="cookie"],[id*="cookie"],[class*="consent"],[id*="consent"],iframe[src*="consent"],iframe[src*="privacy-mgmt"]')) {
    // never the page itself: FCA's <body> carries "eu-cookie-compliance-popup-open" (blanked the whole page, 25 Sep)
    if (el === document.body || el === document.documentElement || el.querySelector('h1, main, article')) continue;
    el.style.setProperty('display', 'none', 'important');
  }
  for (const el of [document.documentElement, document.body]) {
    el.style.setProperty('overflow', 'visible', 'important'); el.style.setProperty('position', 'static', 'important');
    el.classList.remove('sp-message-open');
  }
  return kill.length;
}
"""

PAGE_JS_MASK = r"""
() => {
  let n = 0;
  const inChrome = el => el.closest('header, nav, [role=banner], [class*=logo], [class*=masthead], [id*=logo]');
  for (const el of document.querySelectorAll('img, picture, video, [style*="background-image"]')) {
    const r = el.getBoundingClientRect();
    if (r.width >= 220 && r.height >= 140 && !inChrome(el)) {
      el.style.setProperty('filter', 'grayscale(1) contrast(0) brightness(1.75)', 'important'); n++;
    }
  }
  return n;
}
"""

PAGE_JS_INFO = r"""
(claims) => {
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const box = el => { const r = el.getBoundingClientRect(); return {x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height}; };
  const norm = s => s.replace(/ /g,' ').replace(/[‘’]/g,"'").replace(/[“”]/g,'"').replace(/[–—]/g,'-').replace(/[  ]/g,' ');
  const root = document.querySelector('article') || document.querySelector('main') || document.body;
  const h1 = [...document.querySelectorAll('h1')].find(vis);
  const q = sel => [...document.querySelectorAll(sel)].filter(vis);
  const near = (els) => els.find(e => !h1 || Math.abs(box(e).y - box(h1).y) < 1400);
  const by = near(q('[rel=author], [itemprop=author], [data-link-name="byline"], [class*=byline], [class*=Byline], [data-testid*=byline], address, a[href*="/profile/"], [class*=author-name], [class*=author]'));
  const tm = near(q('time, [class*=dateline], [class*=publish], [data-testid*=timestamp], [class*=date]'));
  const sf = near(q('[data-gu-name="standfirst"], [class*=standfirst], [class*=strapline], [class*=subtitle], [class*=dek], [class*=summary], header h2, .article__subtitle, [class*=intro]'));
  const logo = q('header a[href="/"] svg, header a[href="/"] img, [class*=logo] svg, [class*=logo] img, [id*=logo] svg, [id*=logo] img, a[href="/"] svg, a[href="https://' + location.host + '/"] img')
      .find(e => box(e).y < 400 && box(e).w > 40);
  const meta = n => { const m = document.querySelector('meta[property="' + n + '"], meta[name="' + n + '"]'); return m ? m.content : null; };
  // text blocks
  const blocks = [...root.querySelectorAll('p, li, h1, h2, h3, blockquote, figcaption, td, dd, dt')]
    .filter(vis).filter(b => !b.closest('nav, footer, aside, [role=navigation], [class*=related], [class*=newsletter], [class*=comment]'))
    .filter(b => !b.querySelector('p, li'));
  const texts = blocks.map(b => { const nodes = []; let s = ''; const w = document.createTreeWalker(b, NodeFilter.SHOW_TEXT);
    while (w.nextNode()) { nodes.push([w.currentNode, s.length]); s += w.currentNode.nodeValue; } return {nodes, s: norm(s)}; });
  const results = [];
  for (const c of claims) {
    const hits = [];
    texts.forEach((t, i) => {
      let score = 0; const rects = []; const gs = [];
      for (const [gi, g] of c.groups.entries()) {
        let m = null;
        for (const alt of g) { try { m = new RegExp(alt, 'i').exec(t.s); } catch (e) { m = null; } if (m) break; }
        if (!m) continue;
        score++; gs.push(gi);
        const range = document.createRange(); let a = null, b = null;
        for (const [node, off] of t.nodes) {
          const L = node.nodeValue.length;
          if (!a && m.index < off + L) a = [node, m.index - off];
          if (m.index + m[0].length <= off + L) { b = [node, m.index + m[0].length - off]; break; }
        }
        if (a && b) { try { range.setStart(a[0], a[1]); range.setEnd(b[0], b[1]);
          for (const r of range.getClientRects()) rects.push({x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height}); } catch (e) {} }
      }
      if (score >= c.need && score > 0) hits.push({i, score, gs, box: box(blocks[i]), rects, text: t.s.slice(0, 600)});
    });
    hits.sort((p, q) => q.score - p.score || p.i - q.i);
    // keep the best hit, then hits that evidence a token group not yet covered (claim 6 of S29 = fine + quote + apology)
    const keep = [], covered = new Set();
    for (const h of hits) {
      if (keep.length >= 3) break;
      if (!keep.length || h.gs.some(g => !covered.has(g))) { keep.push(h); h.gs.forEach(g => covered.add(g)); }
    }
    results.push({n: c.n, hits: keep});
  }
  const links = [...root.querySelectorAll('a[href]')].filter(a => !a.closest('nav, footer, header, aside, [class*=related]'))
    .map(a => ({href: a.href, text: (a.innerText || '').trim().slice(0, 120)}));
  const pdfs = [...root.querySelectorAll('a[href$=".pdf"], a[href*=".pdf?"]')].filter(a => !a.closest('nav, footer, header, aside, [class*=related]')).map(a => ({href: a.href, text: (a.innerText || '').trim().slice(0, 160)}));
  return {
    title: document.title, h1: h1 ? norm(h1.innerText.trim()) : null, h1box: h1 ? box(h1) : null,
    byline: by ? norm(by.innerText.trim()).slice(0, 160) : null, bybox: by ? box(by) : null,
    date: tm ? (tm.getAttribute('datetime') || norm(tm.innerText.trim())).slice(0, 80) : null, datebox: tm ? box(tm) : null,
    sfbox: sf ? box(sf) : null, logobox: logo ? box(logo) : null,
    published: meta('article:published_time') || meta('datePublished') || meta('DC.date.issued') || meta('date'),
    site_name: meta('og:site_name'), og_title: meta('og:title'),
    text: norm(document.body.innerText), claims: results, links, pdfs,
    pageW: document.documentElement.scrollWidth, pageH: document.documentElement.scrollHeight
  };
}
"""


def _clip(b, pad, W, H, minw=0, pady=None):
    pady = pad if pady is None else pady
    x0 = max(0, b["x"] - pad); y0 = max(0, b["y"] - pady)
    x1 = min(W, b["x"] + b["w"] + pad); y1 = min(H, b["y"] + b["h"] + pady)
    if x1 - x0 < minw:
        cx = (x0 + x1) / 2; x0 = max(0, cx - minw / 2); x1 = min(W, x0 + minw)
    return {"x": x0, "y": y0, "width": max(1, x1 - x0), "height": max(1, y1 - y0)}


def _union(bs):
    bs = [b for b in bs if b]
    x0 = min(b["x"] for b in bs); y0 = min(b["y"] for b in bs)
    x1 = max(b["x"] + b["w"] for b in bs); y1 = max(b["y"] + b["h"] for b in bs)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def chrome_path():
    """A headless Chrome that exists on this Mac: hyperframes' chrome-headless-shell first, then Playwright's cache
    (the pip playwright wants a build number that may not be downloaded; pointing at an existing shell avoids that)."""
    pats = [os.path.expanduser("~/.cache/hyperframes/chrome/chrome-headless-shell/*/chrome-headless-shell-mac-*/chrome-headless-shell"),
            os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac-*/chrome-headless-shell")]
    for p in pats:
        hits = sorted(glob.glob(p))
        if hits:
            return hits[-1]
    return None


def browser_worker(jobs_path, out_path):
    from playwright.sync_api import sync_playwright
    jobs = json.load(open(jobs_path))
    res = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True, executable_path=chrome_path(), args=["--disable-blink-features=AutomationControlled"])
        ctx = br.new_context(viewport={"width": 1280, "height": 1400}, device_scale_factor=2, user_agent=UA,
                             locale="en-GB", timezone_id="Europe/London")
        for job in jobs:
            page = ctx.new_page()
            r = {"job": job, "ok": False, "files": {}}
            try:
                if job["kind"] == "svg":
                    # data URI: an about:blank page may not load file:// (every SVG logo rendered as a broken image, 25 Sep)
                    import base64
                    src = "data:image/svg+xml;base64," + base64.b64encode(open(job["file"], "rb").read()).decode()
                    page.set_content('<html><body style="margin:0;background:transparent">'
                                     '<img id="l" src="%s" style="width:%dpx;display:block"></body></html>' % (src, job["width"]))
                    page.wait_for_timeout(600)
                    el = page.query_selector("#l")
                    ok = page.evaluate("() => { const i = document.getElementById('l'); return i.complete && i.naturalWidth > 0; }")
                    if ok:
                        el.screenshot(path=job["out"], omit_background=True)
                        r["ok"] = True; r["files"]["png"] = job["out"]
                    else:
                        r["error"] = "SVG did not decode"
                elif job["kind"] == "page":
                    resp = page.goto(job["url"], wait_until="domcontentloaded", timeout=45000)
                    r["status"] = resp.status if resp else 0
                    try:
                        page.wait_for_load_state("networkidle", timeout=12000)
                    except Exception:  # noqa: BLE001
                        pass
                    for y in range(0, 9000, 900):  # trigger lazy loading
                        page.evaluate("y => window.scrollTo(0, y)", y); page.wait_for_timeout(120)
                    page.evaluate("() => window.scrollTo(0, 0)"); page.wait_for_timeout(800)
                    r["hidden_overlays"] = page.evaluate(PAGE_JS_PREP)
                    r["masked_photos"] = page.evaluate(PAGE_JS_MASK) if job.get("mask", True) else 0
                    page.wait_for_timeout(400)
                    info = page.evaluate(PAGE_JS_INFO, job["claims"])
                    r["final_url"] = page.url
                    W, H = info["pageW"], info["pageH"]
                    body = info["text"] or ""
                    r["blocked"] = bool((r["status"] or 0) >= 400 or len(body) < 400 or re.search(
                        r"access denied|just a moment|attention required|are you a robot|captcha|403 forbidden|enable javascript and cookies", body[:3000], re.I))
                    info.pop("text")
                    r["info"] = info
                    pre = job["prefix"]
                    open(pre + ".txt", "w").write(body)
                    r["files"]["text"] = pre + ".txt"
                    if not r["blocked"]:
                        hero_parts = [info.get("h1box"), info.get("sfbox"), info.get("bybox"), info.get("datebox")]
                        hero_parts = [b for b in hero_parts if b and (not info.get("h1box") or abs(b["y"] - info["h1box"]["y"]) < 1400)]
                        if hero_parts:
                            u = _union(hero_parts)
                            head = [b for b in [info.get("h1box"), info.get("sfbox")] if b]
                            tail = [b for b in [info.get("bybox"), info.get("datebox")] if b]
                            if u["h"] > 520 and head and tail:
                                # a masked lead photo sits between headline and byline (BBC, NCSC): two tight crops, not a grey slab
                                hu = _union(head)
                                if hu["h"] > 520:
                                    hu = info["h1box"]
                                clip = _clip(hu, 28, W, H, minw=760, pady=22)
                                page.screenshot(path=pre + "-hero.png", clip=clip, full_page=True)
                                r["files"]["hero"] = pre + "-hero.png"; r["hero_clip"] = clip
                                bclip = _clip(_union(tail), 28, W, H, minw=420, pady=18)
                                page.screenshot(path=pre + "-byline.png", clip=bclip, full_page=True)
                                r["files"]["byline"] = pre + "-byline.png"
                            else:
                                clip = _clip(u, 28, W, H, minw=760, pady=22)
                                page.screenshot(path=pre + "-hero.png", clip=clip, full_page=True)
                                r["files"]["hero"] = pre + "-hero.png"; r["hero_clip"] = clip
                            fold = {"x": 0, "y": 0, "width": min(W, 1280), "height": min(H, max(900, u["y"] + u["h"] + 60, 0) if u["y"] + u["h"] < 2600 else 1400)}
                        else:
                            fold = {"x": 0, "y": 0, "width": min(W, 1280), "height": min(H, 1400)}
                        page.screenshot(path=pre + "-fold.png", clip=fold, full_page=True)
                        r["files"]["fold"] = pre + "-fold.png"
                        if info.get("logobox"):
                            page.screenshot(path=pre + "-masthead.png", clip=_clip(info["logobox"], 14, W, H), full_page=True)
                            r["files"]["masthead"] = pre + "-masthead.png"
                        r["claim_crops"] = []
                        for c in info["claims"]:
                            for k, h in enumerate(c["hits"]):
                                clip = _clip(h["box"], 26, W, H, minw=640, pady=10)
                                f = "%s-claim%02d-%d.png" % (pre, c["n"], k + 1)
                                page.screenshot(path=f, clip=clip, full_page=True)
                                hl = [{"x": round((q["x"] - clip["x"]) * 2), "y": round((q["y"] - clip["y"]) * 2),
                                       "w": round(q["w"] * 2), "h": round(q["h"] * 2)} for q in h["rects"]]
                                r["claim_crops"].append({"n": c["n"], "file": f, "score": h["score"], "highlight_boxes_px": hl,
                                                         "text": h["text"]})
                    r["ok"] = not r["blocked"]
                elif job["kind"] == "site_logo":
                    page.goto(job["url"], wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(2500)
                    page.evaluate(PAGE_JS_PREP)
                    info = page.evaluate(PAGE_JS_INFO, [])
                    if info.get("logobox"):
                        page.screenshot(path=job["out"], clip=_clip(info["logobox"], 10, info["pageW"], info["pageH"]), full_page=True)
                        r["ok"] = True; r["files"]["png"] = job["out"]; r["final_url"] = page.url
            except Exception as e:  # noqa: BLE001
                r["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
            finally:
                page.close()
            res.append(r)
        br.close()
    json.dump(res, open(out_path, "w"), indent=1)

# ---------------------------------------------------------------------------------------------------- PDF worker

def ensure_ocr():
    if os.path.exists(OCR_BIN) and os.path.getmtime(OCR_BIN) >= os.path.getmtime(OCR_SRC):
        return True
    os.makedirs(os.path.dirname(OCR_BIN), exist_ok=True)
    p = subprocess.run(["swiftc", "-O", OCR_SRC, "-o", OCR_BIN], capture_output=True, text=True)
    return p.returncode == 0


def pdf_lines(doc_page, scale, ocr_png=None):
    """-> list of lines [{text, x, y, w, h}] in rendered-pixel coords (origin top-left), and the text source."""
    tp = doc_page.get_textpage()
    n = tp.count_chars()
    H = doc_page.get_height()
    lines = []
    if n > 20:
        text = tp.get_text_range()
        cur = {"chars": [], "boxes": []}
        for i in range(n):
            ch = text[i] if i < len(text) else ""
            if ch in "\r\n":
                if cur["chars"]:
                    lines.append(cur); cur = {"chars": [], "boxes": []}
                continue
            try:
                l, b, r, t = tp.get_charbox(i)
            except Exception:  # noqa: BLE001
                continue
            cur["chars"].append(ch); cur["boxes"].append((l * scale, (H - t) * scale, r * scale, (H - b) * scale))
        if cur["chars"]:
            lines.append(cur)
        out = []
        for ln in lines:
            bx = [b for b, c in zip(ln["boxes"], ln["chars"]) if c.strip()]
            if not bx:
                continue
            out.append({"text": "".join(ln["chars"]), "boxes": ln["boxes"], "x": min(b[0] for b in bx), "y": min(b[1] for b in bx),
                        "w": max(b[2] for b in bx) - min(b[0] for b in bx), "h": max(b[3] for b in bx) - min(b[1] for b in bx)})
        return out, "text-layer"
    if ocr_png and ensure_ocr():
        p = subprocess.run([OCR_BIN, ocr_png], capture_output=True, text=True, timeout=300)
        try:
            j = json.loads(p.stdout.strip().splitlines()[0])
        except (ValueError, IndexError):
            return [], "ocr-failed"
        return [dict(t, boxes=None) for t in j["lines"]], "ocr (macOS Vision)"
    return [], "no-text"


def pdf_worker(jobs_path, out_path):
    import pypdfium2 as pdfium
    from PIL import Image  # noqa: F401
    jobs = json.load(open(jobs_path))
    res = []
    for job in jobs:
        r = {"job": job, "pages": [], "claim_crops": [], "ok": False}
        try:
            doc = pdfium.PdfDocument(job["pdf"])
            dpi = job.get("dpi", 200); scale = dpi / 72.0
            r["n_pages"] = len(doc)
            meta = doc.get_metadata_dict() if hasattr(doc, "get_metadata_dict") else {}
            r["meta"] = {k: v for k, v in (meta or {}).items() if v}
            texts = []
            imgs = {}
            limit = min(len(doc), job.get("max_pages", 60))
            for i in range(limit):
                pg = doc[i]
                img = pg.render(scale=scale).to_pil()
                png = "%s-p%02d.png" % (job["prefix"], i + 1)
                img.save(png)
                imgs[i] = (png, img)
                lines, how = pdf_lines(pg, scale, ocr_png=png)
                texts.append({"i": i, "lines": lines, "how": how})
            full = open(job["prefix"] + ".txt", "w")
            for t in texts:
                full.write("\n=== page %d (%s)\n" % (t["i"] + 1, t["how"]) + "\n".join(l["text"] for l in t["lines"]))
            full.close()
            r["text_file"] = job["prefix"] + ".txt"
            r["text_source"] = sorted({t["how"] for t in texts})
            keep = set(job.get("pages_always", [0]))
            for c in job["claims"]:
                cands = []
                for t in texts:
                    ls = t["lines"]
                    for k in range(len(ls)):  # sliding window of 4 lines = a paragraph-sized match region
                        win = ls[k:k + 4]
                        s = norm1(" ".join(l["text"] for l in win))
                        sc, spans = match_text(s, c["groups"])
                        if sc >= max(1, c["need"]):
                            cands.append((sc, -t["i"], -k, t["i"], k, spans))
                if not cands:
                    continue
                cands.sort(reverse=True)
                used = []
                for sc, _, _, pi, k, spans in cands:
                    if len(used) >= 2 or any(pi == up and abs(k - uk) < 9 for up, uk in used):
                        continue  # one crop per region: neighbouring windows are the same paragraph
                    used.append((pi, k))
                    keep.add(pi)
                    ls = texts[pi]["lines"]
                    # grow the window to whole paragraphs: stop at a vertical gap well above the page's usual line gap
                    ordered = sorted(range(len(ls)), key=lambda q: ls[q]["y"])
                    pos = {q: j for j, q in enumerate(ordered)}
                    gaps = [ls[ordered[j + 1]]["y"] - (ls[ordered[j]]["y"] + ls[ordered[j]]["h"]) for j in range(len(ordered) - 1)]
                    med = sorted(g for g in gaps if g > 0)[len([g for g in gaps if g > 0]) // 2] if any(g > 0 for g in gaps) else 10
                    win_idx = sorted(pos[q] for q in range(k, min(len(ls), k + 4)))
                    a_, b_ = win_idx[0], win_idx[-1]
                    while a_ > 0 and win_idx[0] - a_ < 6 and gaps[a_ - 1] <= 1.6 * med:
                        a_ -= 1
                    while b_ < len(ordered) - 1 and b_ - win_idx[-1] < 8 and gaps[b_] <= 1.6 * med:
                        b_ += 1
                    region = [ls[ordered[j]] for j in range(a_, b_ + 1)]
                    png, img = imgs[pi]
                    xs0 = min(l["x"] for l in ls) if ls else 0
                    xs1 = max(l["x"] + l["w"] for l in ls) if ls else img.width
                    top_room = gaps[a_ - 1] / 2 if a_ > 0 else 30
                    bot_room = gaps[b_] / 2 if b_ < len(gaps) else 30
                    y0 = max(0, min(l["y"] for l in region) - min(30, max(4, top_room)))
                    y1 = min(img.height, max(l["y"] + l["h"] for l in region) + min(30, max(4, bot_room)))
                    x0 = max(0, xs0 - 30); x1 = min(img.width, xs1 + 30)
                    crop = img.crop((int(x0), int(y0), int(x1), int(y1)))
                    f = "%s-claim%02d-%d.png" % (job["prefix"], c["n"], len([q for q in r["claim_crops"] if q["n"] == c["n"]]) + 1)
                    crop.save(f)
                    # highlight boxes: lines in the window that carry a matched token
                    hl = []
                    for l in ls[k:k + 4]:
                        ln = norm1(l["text"])
                        for g in c["groups"]:
                            for alt in g:
                                m = re.search(alt, ln, re.I)
                                if m:
                                    if l.get("boxes") and m.end() <= len(l["boxes"]):
                                        bb = l["boxes"][m.start():m.end()]
                                        bx0 = min(b[0] for b in bb); by0 = min(b[1] for b in bb)
                                        bx1 = max(b[2] for b in bb); by1 = max(b[3] for b in bb)
                                    else:  # OCR line: proportional span inside the line box
                                        L = max(1, len(ln)); bx0 = l["x"] + l["w"] * m.start() / L; bx1 = l["x"] + l["w"] * m.end() / L
                                        by0 = l["y"]; by1 = l["y"] + l["h"]
                                    hl.append({"x": round(bx0 - x0), "y": round(by0 - y0), "w": round(bx1 - bx0), "h": round(by1 - by0)})
                                    break
                    r["claim_crops"].append({"n": c["n"], "file": f, "page": pi + 1, "score": sc, "highlight_boxes_px": hl,
                                             "text": " ".join(l["text"] for l in region)[:700]})
            for i, (png, img) in imgs.items():
                if i in keep:
                    r["pages"].append({"page": i + 1, "file": png, "w": img.width, "h": img.height})
                else:
                    os.remove(png)
            r["ok"] = True
        except Exception as e:  # noqa: BLE001
            r["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        res.append(r)
    json.dump(res, open(out_path, "w"), indent=1)

# ------------------------------------------------------------------------------------------------- Wikimedia

def wd_entities(ids):
    j = api_json("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=labels|descriptions|claims|sitelinks&languages=en&ids="
                 + "|".join(ids))
    return j.get("entities", {})


def wd_search(name):
    j = api_json("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&language=en&type=item&limit=7&search="
                 + urllib.parse.quote(name))
    return j.get("search", [])


def commons_info(title, width=2400):
    title = title if title.startswith("File:") else "File:" + title
    j = api_json("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|size|mime|extmetadata"
                 "&iiurlwidth=%d&titles=%s" % (width, urllib.parse.quote(title)))
    for p in (j.get("query", {}).get("pages", {}) or {}).values():
        if "imageinfo" in p:
            ii = p["imageinfo"][0]
            em = {k: strip_html(v.get("value", "")) for k, v in (ii.get("extmetadata") or {}).items()}
            return {"title": p["title"], "url": ii["url"], "thumb": ii.get("thumburl"), "w": ii.get("width"), "h": ii.get("height"),
                    "mime": ii.get("mime"), "page": ii.get("descriptionurl"), "licence": em.get("LicenseShortName") or em.get("License"),
                    "licence_url": em.get("LicenseUrl"), "artist": em.get("Artist"), "credit": em.get("Credit"),
                    "restrictions": em.get("Restrictions"), "usage": em.get("UsageTerms"), "attribution": em.get("Attribution"),
                    "date": em.get("DateTimeOriginal") or em.get("DateTime"), "desc": (em.get("ImageDescription") or "")[:300]}
    return None


def commons_search(q, filetype=None, limit=12):
    s = q + (" filetype:%s" % filetype if filetype else "")
    j = api_json("https://commons.wikimedia.org/w/api.php?action=query&format=json&list=search&srnamespace=6&srlimit=%d&srsearch=%s"
                 % (limit, urllib.parse.quote(s)))
    return [x["title"] for x in j.get("query", {}).get("search", [])]


def claim_value(ent, prop):
    return [c for c in ent.get("claims", {}).get(prop, []) if c.get("mainsnak", {}).get("datavalue")]


def pick_logo(ent, story_date):
    vals = claim_value(ent, "P154")
    best, why = None, None
    for c in vals:
        q = c.get("qualifiers", {})
        st = (q.get("P580") or [{}])[0].get("datavalue", {}).get("value", {}).get("time", "")[1:8]
        en = (q.get("P582") or [{}])[0].get("datavalue", {}).get("value", {}).get("time", "")[1:8]
        f = c["mainsnak"]["datavalue"]["value"]
        covers = (not st or st <= story_date) and (not en or en >= story_date)
        rank = {"preferred": 2, "normal": 1}.get(c.get("rank"), 0)
        key = (covers, rank)
        if best is None or key > best[0]:
            best, why = (key, f, st, en), "Wikidata P154, %s%s" % ("covers story date %s" % story_date if covers else "nearest", ", rank " + c.get("rank", ""))
    if not best:
        return None
    return {"file": best[1], "valid_from": best[2] or None, "valid_to": best[3] or None, "why": why, "all": [c["mainsnak"]["datavalue"]["value"] for c in vals]}

# ----------------------------------------------------------------------------------------------------- the build

STOP_ENTS = set("""The A An And But So If In On At Of For To It Its This That These Those Once When Then Follow UK British
January February March April May June July August September October November December Monday Tuesday Wednesday Thursday
Friday Saturday Sunday Here Starling's He She They We You I Our Their There""".split())


def derive_entities(story):
    ents = []
    comp = re.sub(r"\s*\(.*?\)", "", story["company"]).strip()
    aliases = re.findall(r"\((.*?)\)", story["company"])
    ents.append({"name": comp, "role": "subject", "aliases": [a for a in aliases if not re.search(r"fine|case|scandal", a, re.I)]})
    for u in story["sources"]:
        d = domain(u)
        org = next((v for k, v in OUTLETS.items() if d == k or d.endswith("." + k)), None)
        if org and org not in [e["name"] for e in ents]:
            ents.append({"name": org, "role": "source" if "fca" in d or d.endswith("gov.uk") else "outlet"})
    names = re.findall(r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*|[A-Z]{2,})\b", story["script"])
    for n in names:
        n = " ".join(w for w in n.split() if w not in STOP_ENTS)
        if not n or n in STOP_ENTS or any(n.lower() in (e["name"].lower() + " " + " ".join(e.get("aliases", []))).lower() for e in ents):
            continue
        ents.append({"name": n, "role": "mentioned", "auto": True})
    return ents


def default_plan(story):
    months = re.findall(r"(20\d\d)", story["script"] + " " + " ".join(c["text"] for c in story["claims"]))
    return {
        "id": story["id"], "title": story["title"],
        "story_date": (max(months) + "-06") if months else datetime.date.today().strftime("%Y-%m"),
        "entities": derive_entities(story),
        "extra_sources": [{"url": u, "why": "dossier visual source"} for u in story.get("visual_sources", [])],
        "follow_links": True, "max_followed": 4,
        "claims": {str(c["n"]): {"find": auto_find(c["text"])} for c in story["claims"]},
        "photo_queries": [re.sub(r"\s*\(.*?\)", "", story["company"]).strip()],
        "photo_files": [], "clip_queries": [re.sub(r"\s*\(.*?\)", "", story["company"]).strip()],
        "clip_need": "optional", "max_clips": 3, "reject": {},
        "_note": "Auto-drafted. Edit entities (pin qid / logo_file / brand_page), claim find regexes, extra_sources, reject; re-run.",
    }


class Pack:
    def __init__(self, sid, refresh=False, clips=True):
        self.story = load_story(sid)
        self.sid = self.story["id"]
        self.dir = os.path.join(MEDIA, self.sid)
        for sub in ("pages", "docs", "logos", "photos", "clips", "work"):
            os.makedirs(os.path.join(self.dir, sub), exist_ok=True)
        self.plan_path = os.path.join(self.dir, "plan.json")
        if not os.path.exists(self.plan_path):
            json.dump(default_plan(self.story), open(self.plan_path, "w"), indent=1, ensure_ascii=False)
            print("wrote draft plan", self.plan_path)
        self.plan = json.load(open(self.plan_path))
        for x in self.plan.get("extra_claims") or []:  # spoken claims the fact ledger does not list separately
            n = len(self.story["claims"]) + 1
            self.story["claims"].append({"n": n, "text": x["text"], "source_label": x.get("source_label", "script (not a separate ledger row)"),
                                         "source_urls": []})
            self.plan.setdefault("claims", {})[str(n)] = {k: v for k, v in x.items() if k in ("find", "need", "none_reason", "note", "also")}
        self.refresh, self.do_clips = refresh, clips
        self.assets, self.rejected, self.skipped, self.entities_out = [], [], [], []
        self.cjobs = claim_jobs(self.story, self.plan)
        self.log = []

    def say(self, *a):
        s = " ".join(str(x) for x in a); print(s); self.log.append(s)

    def add(self, **a):
        a.setdefault("retrieved_at", now())
        a.setdefault("claims", []); a.setdefault("entities", [])
        f = os.path.join(self.dir, a["file"])
        if os.path.exists(f):
            a["sha256"] = sha(f)
            try:
                from PIL import Image
                with Image.open(f) as im:
                    a["w"], a["h"] = im.size
            except Exception:  # noqa: BLE001
                pass
        stem = os.path.splitext(os.path.basename(a["file"]))[0]
        # ids must stay unique: a 60-char slug cut the "-claim01-1" suffix off and every crop of a page collided (25 Sep)
        a["id"] = a.get("id") or "%s-%s-%s" % (a["type"], slug(stem, 40), hashlib.sha1(a["file"].encode()).hexdigest()[:6])
        if any(x["id"] == a["id"] for x in self.assets):
            raise SystemExit("duplicate asset id %s" % a["id"])
        rj = next((v for k, v in (self.plan.get("reject") or {}).items() if k == a["id"] or k in a["file"]), None)
        if rj:
            a["usable"] = False; a["reject_reason"] = rj
        for k, v in (self.plan.get("asset_notes") or {}).items():  # reviewer's use notes, matched like reject
            if k == a["id"] or k in a["file"]:
                a["review_note"] = v
        a.setdefault("usable", True)
        self.assets.append(a)
        return a

    def rel(self, p):
        return os.path.relpath(p, self.dir)

    # ---- sources: pages + PDFs
    def sources(self):
        srcs = [{"url": u, "why": "script source"} for u in self.story["sources"]] + list(self.plan.get("extra_sources") or [])
        pages, pdfs, seen = [], [], set()
        for s in srcs:
            u = s["url"]
            if u in seen:
                continue
            seen.add(u)
            bad = next((why for pat, why in NOT_USABLE if pat in u), None)
            if bad:
                self.skipped.append({"url": u, "reason": bad}); continue
            if s.get("kind") == "pdf" or re.search(r"\.pdf($|\?)|format=pdf", u):
                pdfs.append(s)
            else:
                pages.append(s)
        results = self.run_pages(pages)
        # follow citations one level deep: authority domains and PDFs linked from the article body
        if self.plan.get("follow_links", True):
            found = []
            for r in results:
                info = r.get("info") or {}
                for L in (info.get("links") or []) + (info.get("pdfs") or []):
                    h = L["href"].split("#")[0]
                    if h in seen or not h.startswith("http") or domain(h) == domain(r["job"]["url"]) and not re.search(r"\.pdf", h):
                        continue
                    bad = next((why for pat, why in NOT_USABLE if pat in h), None)
                    if bad:
                        if h not in [x["url"] for x in self.skipped]:
                            self.skipped.append({"url": h, "reason": bad, "found_in": r["job"]["url"]})
                        continue
                    if re.search(r"share\.php|sharer|sharearticle|facebook\.com|linkedin\.com|twitter\.com|x\.com/|/intent/|/share\?|mailto:|confirm-follow|sign-?in|log-?in|subscribe|newsletter|cookies|privacy|accessibility|/help\b|searching-the-", h, re.I):
                        continue
                    if re.search(r"\.pdf($|\?)", h) or any(a in h for a in AUTHORITY):
                        seen.add(h); found.append({"url": h, "followed": True, "why": "cited by %s (%s)" % (domain(r["job"]["url"]), L["text"][:60])})
            found = found[: self.plan.get("max_followed", 4)]
            if found:
                self.say("following", len(found), "cited primary links:", [f["url"] for f in found])
            fp = [f for f in found if re.search(r"\.pdf($|\?)", f["url"])]
            fh = [f for f in found if f not in fp]
            pdfs += fp
            if fh:
                self.run_pages(fh)
        self.run_pdfs(pdfs)

    def subject_names(self):
        subj = [e for e in self.plan["entities"] if e.get("role") == "subject"]
        return [n.lower() for e in subj for n in [e["name"]] + list(e.get("aliases") or [])]

    def about_subject(self, text):
        """A followed citation only counts if it is about THIS story: it must name the subject (S11: an unrelated 2019
        BBC password article matched 'password' + 'guess' and was nearly filed as evidence)."""
        t = (text or "").lower()
        return any(n in t for n in self.subject_names() + [n.split()[0] for n in self.subject_names() if len(n.split()[0]) >= 3])

    def run_pages(self, pages):
        if not pages:
            return []
        jobs = []
        for s in pages:
            pre = os.path.join(self.dir, "pages", slug(domain(s["url"]) + "-" + urllib.parse.urlparse(s["url"]).path, 70))
            jobs.append({"kind": "page", "url": s["url"], "prefix": pre, "claims": self.cjobs, "why": s.get("why"), "followed": s.get("followed", False), "mask": s.get("mask_photos", True)})
        res = self.browser(jobs)
        # blocked -> Wayback
        retry = []
        for r in res:
            if r.get("blocked") or not r.get("ok"):
                self.say("blocked:", r["job"]["url"], r.get("status"), r.get("error", ""))
                st, _, _, body = http("https://archive.org/wayback/available?url=" + urllib.parse.quote(r["job"]["url"]), timeout=20, tries=1)
                try:
                    wb = json.loads(body) if st == 200 else {}
                except ValueError:
                    wb = {}
                if st != 200:
                    self.say("wayback unreachable (HTTP %s)" % st)
                snap = (wb.get("archived_snapshots") or {}).get("closest") or {}
                if snap.get("available"):
                    j = dict(r["job"], url=snap["url"].replace("http://", "https://"), prefix=r["job"]["prefix"] + "-wayback",
                             why=(r["job"].get("why") or "") + "; original blocked (HTTP %s), Wayback copy %s" % (r.get("status"), snap.get("timestamp")),
                             original=r["job"]["url"])
                    retry.append(j)
                else:
                    self.skipped.append({"url": r["job"]["url"], "reason": "blocked (HTTP %s%s) and no Wayback copy (archive.org HTTP %s)" % (
                        r.get("status"), ", " + r["error"][:80] if r.get("error") else "", st)})
        if retry:
            res2 = self.browser(retry)
            for r in res2:
                if not r.get("ok"):
                    self.skipped.append({"url": r["job"].get("original"), "reason": "blocked, Wayback copy also failed"})
            res += res2
        for r in res:
            body = open(r["files"]["text"]).read() if r.get("files", {}).get("text") and os.path.exists(r["files"]["text"]) else ""
            if r.get("ok") and r["job"].get("followed") and (not r.get("claim_crops") or not self.about_subject(body)):
                self.skipped.append({"url": r["job"]["url"], "reason": "cited by a source but " + (
                    "carries none of the claims' tokens" if not r.get("claim_crops") else "does not name the story's subject (unrelated)")})
                for f in list(r["files"].values()) + [c["file"] for c in r.get("claim_crops", [])]:
                    if os.path.exists(f):
                        os.remove(f)
                r["ok"] = False
            elif r.get("ok"):
                self.record_page(r)
        return [r for r in res if r.get("ok")]

    def record_page(self, r):
        job, info = r["job"], r["info"]
        url = job.get("original") or job["url"]
        body = open(r["files"]["text"]).read() if r["files"].get("text") else ""
        lic, basis, org = page_rights(job["url"], body[-6000:])
        pub = nice_date((info.get("published") or info.get("date") or "")[:10])
        credit = "Source: %s%s" % (org, (", " + pub) if pub else "")
        if "wayback" in job["prefix"]:
            credit += " (archived by the Internet Archive)"
        common = dict(source_url=url, page_url=r.get("final_url") or job["url"], licence=lic, rights_basis=basis, credit_line=credit,
                      publisher=org, headline=info.get("h1") or info.get("og_title"), byline=info.get("byline"),
                      published=info.get("published") or info.get("date"), why=job.get("why"),
                      notes="%d article photo(s) greyed out (not ours to use); %d overlay(s) hidden, no consent accepted" %
                            (r.get("masked_photos", 0), r.get("hidden_overlays", 0)))
        ents = [e["name"] for e in self.plan["entities"] if e["name"].lower() in (body[:20000].lower())]
        for kind in ("hero", "byline", "fold", "masthead"):
            if r["files"].get(kind):
                extra = dict(common)
                if kind == "fold":  # the full top of the page carries the site's own sidebars (other stories, other names)
                    extra["notes"] = common["notes"] + "; FOLD = whole page top incl. unrelated sidebars/other headlines: " \
                        "use as a screen-in-scene establishing shot, push in to the article column, never hold on the sidebar"
                self.add(type="page_" + kind, file=self.rel(r["files"][kind]), entities=ents if kind != "masthead" else [org],
                         claims=[], **extra)
        about = self.about_subject(body)
        for c in r.get("claim_crops", []):
            if not about:
                self.rejected.append({"url": url, "file": self.rel(c["file"]), "reason": "claim %d matched on a page that never names the "
                                      "story's subject: context, not evidence for this claim" % c["n"]})
                os.remove(c["file"]); continue
            self.add(type="page_claim_crop", file=self.rel(c["file"]), claims=[c["n"]], match_score=c["score"],
                     highlight_boxes_px=c["highlight_boxes_px"], matched_text=c["text"], entities=ents, **common)

    def run_pdfs(self, pdfs):
        jobs = []
        for s in pdfs:
            name = slug(domain(s["url"]) + "-" + (s.get("name") or os.path.basename(urllib.parse.urlparse(s["url"]).path).replace(".pdf", "")), 70)
            path = os.path.join(self.dir, "docs", name + ".pdf")
            if self.refresh or not os.path.exists(path):
                st, ct, final, data = http(s["url"], binary=True, timeout=90)
                if st != 200 or not data[:5] == b"%PDF-":
                    self.skipped.append({"url": s["url"], "reason": "PDF fetch failed (HTTP %s, %s)" % (st, ct)}); continue
                open(path, "wb").write(data)
            jobs.append({"pdf": path, "prefix": os.path.join(self.dir, "docs", name), "claims": self.cjobs, "url": s["url"],
                         "why": s.get("why"), "title": s.get("title"), "date": s.get("date"), "followed": s.get("followed", False), "pages_always": s.get("pages_always", [0]), "dpi": 200})
        if not jobs:
            return
        jp, op = os.path.join(self.dir, "work", "pdf-jobs.json"), os.path.join(self.dir, "work", "pdf-out.json")
        json.dump(jobs, open(jp, "w"), indent=1)
        p = heavy([sys.executable, os.path.abspath(__file__), "_pdf", jp, op], timeout=3600)
        if p.returncode != 0:
            self.say("pdf worker failed:", p.stderr[-800:]); return
        for r in json.load(open(op)):
            job = r["job"]
            if not r.get("ok"):
                self.skipped.append({"url": job["url"], "reason": "PDF render failed: %s" % r.get("error")}); continue
            txt = open(r["text_file"]).read() if r.get("text_file") and os.path.exists(r["text_file"]) else ""
            if job.get("followed") and (not r["claim_crops"] or not self.about_subject(txt)):
                self.skipped.append({"url": job["url"], "reason": "cited PDF " + ("carries none of the claims' tokens" if not r["claim_crops"]
                                                                              else "does not name the story's subject (unrelated)")})
                for f in [p["file"] for p in r["pages"]] + [job["pdf"], r.get("text_file") or ""]:
                    if f and os.path.exists(f):
                        os.remove(f)
                continue
            lic, basis, org = page_rights(job["url"], txt[-4000:])
            dt = job.get("date") or (r.get("meta", {}).get("CreationDate", "")[2:10])
            dt = "%s-%s-%s" % (dt[:4], dt[4:6], dt[6:8]) if re.fullmatch(r"\d{8}", dt or "") else (dt or "")
            title = job.get("title") or r.get("meta", {}).get("Title") or os.path.basename(job["pdf"])
            credit = "Source: %s, %s%s" % (org, title, (", " + nice_date(dt)) if dt else "")
            common = dict(source_url=job["url"], licence=lic, rights_basis=basis, credit_line=credit, publisher=org, document_title=title,
                          document_date=dt or None, why=job.get("why"), n_pages=r.get("n_pages"), text_source=r.get("text_source"),
                          local_pdf=self.rel(job["pdf"]))
            for pg in r["pages"]:
                self.add(type="document_page", file=self.rel(pg["file"]), page=pg["page"], dpi=200, **common)
            about = self.about_subject(txt)
            for c in r["claim_crops"]:
                if not about:
                    self.rejected.append({"url": job["url"], "file": self.rel(c["file"]), "reason": "claim %d matched in a document that never "
                                          "names the story's subject" % c["n"]})
                    os.remove(c["file"]); continue
                self.add(type="document_claim_crop", file=self.rel(c["file"]), page=c["page"], dpi=200, claims=[c["n"]],
                         match_score=c["score"], highlight_boxes_px=c["highlight_boxes_px"], matched_text=c["text"], **common)

    def browser(self, jobs):
        tag = hashlib.md5(json.dumps(jobs, sort_keys=True).encode()).hexdigest()[:8]
        jp, op = os.path.join(self.dir, "work", "br-%s.json" % tag), os.path.join(self.dir, "work", "br-%s-out.json" % tag)
        json.dump(jobs, open(jp, "w"), indent=1)
        p = heavy([sys.executable, os.path.abspath(__file__), "_browser", jp, op], timeout=3600)
        if p.returncode != 0 or not os.path.exists(op):
            self.say("browser worker failed:", p.stderr[-1500:])
            return []
        return json.load(open(op))

    # ---- entities: logos + photos
    def entities(self):
        story_date = self.plan.get("story_date", "")[:7]
        svg_jobs = []
        for e in self.plan["entities"]:
            out = {"name": e["name"], "role": e.get("role"), "qid": e.get("qid"), "logo": None, "photo": [], "notes": []}
            if e.get("skip"):
                out["logo_none_reason"] = e["skip"]; self.entities_out.append(out); continue
            ent = None
            if not e.get("qid") and not e.get("logo_file"):
                ctx_words = set(w.lower() for w in re.findall(r"[A-Za-z]{4,}", self.story["script"] + " " + self.story["title"]))
                best = None
                for h in wd_search(e["name"]):
                    desc = (h.get("description") or "").lower()
                    lab = (h.get("label") or "").lower()
                    ov = len(set(re.findall(r"[a-z]{4,}", desc)) & ctx_words)
                    exact = lab == e["name"].lower() or e["name"].lower() in [a.lower() for a in h.get("aliases", [])] if isinstance(h.get("aliases"), list) else lab == e["name"].lower()
                    kindy = bool(re.search(r"bank|company|business|regulator|authority|broadcaster|newspaper|website|county|city|group|agency|organi[sz]ation|ransomware|firm|haulier|logistics", desc))
                    sc = ov * 2 + (3 if exact else 0) + (2 if kindy else 0)
                    if sc >= 4 and (best is None or sc > best[0]):
                        best = (sc, h["id"], h.get("description"))
                if best:
                    e["qid"] = best[1]; out["qid"] = best[1]; out["notes"].append("auto-resolved %s (%s), score %d" % (best[1], best[2], best[0]))
                else:
                    out["notes"].append("no confident Wikidata match; pin qid or logo_file in plan.json")
            if e.get("qid"):
                ent = wd_entities([e["qid"]]).get(e["qid"], {})
                out["label"] = ent.get("labels", {}).get("en", {}).get("value")
                out["description"] = ent.get("descriptions", {}).get("en", {}).get("value")
                site = claim_value(ent, "P856")
                out["official_site"] = site[0]["mainsnak"]["datavalue"]["value"] if site else None
            # logo
            lf, why, valid = e.get("logo_file"), "pinned in plan.json", {}
            if not lf and ent:
                pl = pick_logo(ent, story_date)
                if pl:
                    lf, why, valid = pl["file"], pl["why"], {"valid_from": pl["valid_from"], "valid_to": pl["valid_to"]}
                    out["logo_all"] = pl["all"]
            if not lf and e.get("role") != "mentioned":
                toks = [t.lower() for t in re.findall(r"\w+", e["name"])]
                for t in commons_search(e["name"] + " logo", "drawing") + commons_search(e["name"] + " logo"):
                    tl = t.lower()
                    if all(x in tl for x in toks) and "logo" in tl:
                        lf, why = t, "Commons search '%s logo'" % e["name"]; break
            if lf:
                ci = commons_info(lf, width=1600)
                if ci:
                    ext = os.path.splitext(urllib.parse.urlparse(ci["url"]).path)[1].lower()  # Commons URLs now carry ?utm_ params
                    base = os.path.join(self.dir, "logos", slug(e["name"]))
                    orig = base + ext
                    if self.refresh or not os.path.exists(orig):
                        st, _, _, data = http(ci["url"], ua=WIKI_UA, binary=True, tries=4)
                        if st == 200:
                            open(orig, "wb").write(data)
                    png = base + ".png"
                    if ext == ".svg":
                        svg_jobs.append({"kind": "svg", "file": orig, "out": png, "width": 800})
                    elif os.path.exists(orig):
                        if ci.get("thumb") and (self.refresh or not os.path.exists(png)):
                            st, _, _, data = http(ci["thumb"], ua=WIKI_UA, binary=True, tries=4)
                            if st == 200:
                                open(png, "wb").write(data)
                    tm = "; trademark of %s: editorial identification only, never implying endorsement" % e["name"]
                    out["logo"] = {"file": self.rel(png), "original": self.rel(orig), "commons": ci["page"], "why": why, **valid}
                    out["_logo_meta"] = dict(source_url=ci["page"], licence=(ci["licence"] or "unknown") + tm,
                                             licence_url=ci.get("licence_url"), author=ci.get("artist"),
                                             rights_basis="Commons licence %s (copyright); trade mark used referentially" % ci["licence"],
                                             credit_line="Logo: %s (via Wikimedia Commons)" % e["name"], restrictions=ci.get("restrictions"),
                                             original_file=self.rel(orig), why=why, **valid)
            elif e.get("brand_page") or (out.get("official_site") and e.get("role") == "subject"):
                bp = e.get("brand_page") or out["official_site"]
                png = os.path.join(self.dir, "logos", slug(e["name"]) + "-site.png")
                r = self.browser([{"kind": "site_logo", "url": bp, "out": png}])
                if r and r[0].get("ok"):
                    out["logo"] = {"file": self.rel(png), "brand_page": bp, "why": "header logo captured from the company's own site"}
                    out["_logo_meta"] = dict(source_url=bp, licence="© %s, trade mark; editorial identification only" % e["name"],
                                             rights_basis="Trade mark used referentially; copyright: fair dealing (quotation)",
                                             credit_line="Logo: %s" % e["name"], why="brand page header")
            if not out["logo"]:
                out["logo_none_reason"] = e.get("logo_none_reason") or (
                    "mentioned only; no logo needed" if e.get("role") == "mentioned" else "no Wikidata P154, no Commons logo, no brand page")
            self.entities_out.append(out)
        if svg_jobs:
            self.browser(svg_jobs)
        for out in self.entities_out:
            if out.get("_logo_meta"):
                m = out.pop("_logo_meta")
                lp = os.path.join(self.dir, out["logo"]["file"])
                if os.path.exists(lp) and logo_has_ink(lp):
                    a = self.add(type="logo", file=out["logo"]["file"], entities=[out["name"]], **m)
                    out["logo"]["asset"] = a["id"]
                else:
                    out["logo_none_reason"] = "logo file failed to render/download (empty or broken image)"; out["logo"] = None

    def photos(self):
        want = []
        for f in self.plan.get("photo_files") or []:
            want.append((f if isinstance(f, str) else f["file"], "pinned in plan.json", f.get("claims", []) if isinstance(f, dict) else [],
                         f.get("entities", []) if isinstance(f, dict) else []))
        for q in self.plan.get("photo_queries") or []:
            qn = q if isinstance(q, str) else q["q"]
            n = 0
            for t in commons_search(qn, "bitmap", limit=25):
                if n >= (q.get("n", 3) if isinstance(q, dict) else 3):
                    break
                if re.search(r"\b(logo|wordmark|icon|symbol|emblem|coat of arms|screenshot|signature)\b", t, re.I):
                    self.rejected.append({"title": t, "reason": "a mark or screenshot, not a photo (logos come from the logo stage)"}); continue
                if PEOPLEY.search(t):
                    self.rejected.append({"title": t, "reason": "title suggests identifiable people; not auto-selected"}); continue
                want.append((t, "Commons search '%s'" % qn, q.get("claims", []) if isinstance(q, dict) else [],
                             q.get("entities", []) if isinstance(q, dict) else [])); n += 1
        seen = set()
        for t, why, claims, ents in want:
            if t in seen:
                continue
            seen.add(t)
            ci = commons_info(t, width=2400)
            if not ci:
                self.rejected.append({"title": t, "reason": "no Commons imageinfo"}); continue
            lic = (ci["licence"] or "").strip()
            if not PD_GOOD.match(lic):
                self.rejected.append({"title": t, "reason": "licence '%s' not on the whitelist" % lic}); continue
            if max(ci["w"] or 0, ci["h"] or 0) < 1600:
                self.rejected.append({"title": t, "reason": "too small (%sx%s) for a 2x master" % (ci["w"], ci["h"])}); continue
            f = os.path.join(self.dir, "photos", slug(t.replace("File:", ""), 60) + ".jpg")
            if self.refresh or not os.path.exists(f):
                st, _, _, data = http(ci["thumb"] or ci["url"], ua=WIKI_UA, binary=True, timeout=90, tries=4)
                if st != 200:
                    self.rejected.append({"title": t, "reason": "download HTTP %s" % st}); continue
                open(f, "wb").write(data)
            author = re.sub(r"\s+", " ", ci.get("artist") or "unknown")[:120]
            self.add(type="photo", file=self.rel(f), source_url=ci["page"], licence=lic, licence_url=ci.get("licence_url"),
                     author=author, rights_basis="Licence: %s (Wikimedia Commons)" % lic,
                     credit_line="Photo: %s, %s, via Wikimedia Commons" % (author, lic), why=why, description=ci["desc"],
                     taken=ci.get("date"), claims=claims, entities=ents,
                     review="LOOK before use: no identifiable private individuals; editorial context only")

    # ---- clips
    def clips(self):
        if not self.do_clips:
            return
        subj = [t.lower() for t in re.findall(r"[A-Za-z]{3,}", re.sub(r"\s*\(.*?\)", "", self.story["company"]))][:2]
        cands, seen = [], set()
        for q in self.plan.get("clip_queries") or []:
            for url in ("https://www.youtube.com/results?search_query=%s&sp=EgIwAQ%%253D%%253D" % urllib.parse.quote_plus(q),
                        "ytsearch8:%s" % q):
                p = subprocess.run(["yt-dlp", "--flat-playlist", "--playlist-end", "8", "--print",
                                    "%(id)s\t%(title)s\t%(channel)s\t%(duration)s", url], capture_output=True, text=True, timeout=120)
                for line in p.stdout.splitlines():
                    parts = line.split("\t")
                    if len(parts) < 4 or parts[0] in seen:
                        continue
                    seen.add(parts[0])
                    title = parts[1]
                    if not all(s in title.lower() for s in subj[:1]):
                        continue
                    cands.append({"id": parts[0], "title": title, "channel": parts[2], "duration": parts[3],
                                  "cc_search": "sp=" in url, "query": q})
        self.say("clip candidates (title names %s):" % subj[:1], len(cands))
        kept = 0
        for c in cands:
            if kept >= self.plan.get("max_clips", 3):
                break
            vurl = "https://www.youtube.com/watch?v=" + c["id"]
            p = subprocess.run(["yt-dlp", "-J", "--skip-download", vurl], capture_output=True, text=True, timeout=120)
            try:
                meta = json.loads(p.stdout)
            except ValueError:
                self.rejected.append({"url": vurl, "reason": "metadata failed: " + p.stderr[-200:]}); continue
            cues, how = self.captions(c["id"], meta)
            best = None
            for cj in self.cjobs:
                for k in range(len(cues)):
                    win = cues[k:k + 3]
                    s = norm1(" ".join(x["text"] for x in win))
                    sc, _ = match_text(s, cj["groups"])
                    if sc >= max(1, cj["need"]) and (best is None or sc > best[0]):
                        best = (sc, cj["n"], win[0]["start"], s)
            if not best:
                self.rejected.append({"url": vurl, "title": meta.get("title"), "reason": "no claim token found in its speech (%s)" % how}); continue
            t_in = max(0, best[2] - 0.3); t_out = t_in + 5.0
            lic = meta.get("license") or "Standard YouTube Licence"
            cc = "creative commons" in lic.lower()
            risk = "LOW" if cc else ("HIGH" if BROADCASTERS.search((meta.get("channel") or "") + " " + (meta.get("uploader") or "")) else "MEDIUM")
            still = os.path.join(self.dir, "clips", "%s-in.jpg" % c["id"])
            if self.refresh or not os.path.exists(still):
                # googlevideo URLs 403 a bare ffmpeg (they need yt-dlp's headers): fetch one second through yt-dlp, grab a frame,
                # delete the temporary segment. Only the still is kept, for review.
                seg = os.path.join(self.dir, "work", "seg-%s.mp4" % c["id"])
                subprocess.run(["yt-dlp", "-q", "-f", "18/best[height<=720][ext=mp4]/best[height<=720]", "--download-sections",
                                "*%.2f-%.2f" % (t_in + 1.0, t_in + 2.0), "--force-overwrites", "-o", seg, vurl],
                               capture_output=True, text=True, timeout=300)
                still_kind = "frame at in-point"
                if os.path.exists(seg):
                    heavy(["ffmpeg", "-y", "-loglevel", "error", "-i", seg, "-frames:v", "1", "-q:v", "2", still], timeout=300)
                    os.remove(seg)
                if not os.path.exists(still):
                    # 25 Sep: every googlevideo media request 403s from this Mac (yt-dlp without an impersonation target), so
                    # fall back to the video's own thumbnail for review; the in/out times still come from its speech.
                    for tn in ("maxresdefault", "hqdefault"):
                        st, _, _, data = http("https://i.ytimg.com/vi/%s/%s.jpg" % (c["id"], tn), binary=True, tries=1)
                        if st == 200 and len(data) > 5000:
                            open(still, "wb").write(data); still_kind = "YouTube thumbnail (video frames 403 from this Mac)"; break
            else:
                still_kind = "cached"
            kept += 1
            date = meta.get("upload_date") or ""
            self.add(type="clip_candidate", file=self.rel(still), still_missing=not os.path.exists(still), source_url=vurl,
                     title=meta.get("title"), channel=meta.get("channel"), uploaded="%s-%s-%s" % (date[:4], date[4:6], date[6:]) if date else None,
                     duration_s=meta.get("duration"), clip_in_s=round(t_in, 2), clip_out_s=round(t_out, 2), matched_speech=best[3][:300],
                     timing_source=how, still_kind=still_kind, claims=[best[1]], licence=lic,
                     rights_basis=("Licence: CC BY (credit the channel)" if cc else
                                   "UK fair dealing only (quotation/criticism, <=5 s, original audio muted); uploader may not be the rights holder"),
                     content_id_risk=risk, credit_line="Clip: %s, YouTube%s" % (meta.get("channel"), (", " + date[:4]) if date else ""),
                     need=self.plan.get("clip_need", "optional"),
                     usable=cc or risk != "HIGH",
                     notes="candidate only: not downloaded; still frame at in-point for review")

    def captions(self, vid, meta):
        base = os.path.join(self.dir, "work", "subs-" + vid)
        wcache = base + ".whisper.json"
        if os.path.exists(wcache) and not self.refresh:
            return json.load(open(wcache)), "local faster-whisper (cached)"
        for tries in range(2):
            if not (glob.glob(base + "*.json3") and not self.refresh):
                subprocess.run(["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", "en.*,en",
                                "--sub-format", "json3", "-o", base + ".%(ext)s", "https://www.youtube.com/watch?v=" + vid],
                               capture_output=True, text=True, timeout=180)
            fs = sorted(glob.glob(base + "*.json3"))
            if fs:
                j = json.load(open(fs[0]))
                cues = []
                for ev in j.get("events", []):
                    t = "".join(s.get("utf8", "") for s in ev.get("segs", []) or []).strip()
                    if t:
                        cues.append({"start": ev.get("tStartMs", 0) / 1000.0, "text": t})
                return cues, "YouTube captions"
            time.sleep(15)
        # fallback: local faster-whisper on the audio (temporary copy, deleted after), only for short videos
        if (meta.get("duration") or 9999) <= 900 and os.path.exists(WHISPER_PY):
            aud = base + ".m4a"
            subprocess.run(["yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio", "-o", aud, "https://www.youtube.com/watch?v=" + vid],
                           capture_output=True, text=True, timeout=600)
            if os.path.exists(aud):
                code = ("import json,sys\nfrom faster_whisper import WhisperModel\nm=WhisperModel('small.en',compute_type='int8')\n"
                        "segs,_=m.transcribe(sys.argv[1])\nprint(json.dumps([{'start':s.start,'text':s.text} for s in segs]))")
                p = heavy([WHISPER_PY, "-c", code, aud], timeout=1800)
                os.remove(aud)
                try:
                    cues = json.loads(p.stdout.strip().splitlines()[-1])
                    json.dump(cues, open(wcache, "w"))
                    return cues, "local faster-whisper (captions rate-limited)"
                except (ValueError, IndexError):
                    pass
        return [], "no captions available"

    # ---- outputs
    def ocr_scan(self):
        """OCR every usable still (local macOS Vision, through heavy.py) and flag dashes: a screenshot carrying an em or
        en dash fails the render gate's OCR checks 1/2, so it must be cropped past the dash before use."""
        files = [os.path.join(self.dir, a["file"]) for a in self.assets if a.get("usable") and a["file"].lower().endswith((".png", ".jpg"))
                 and os.path.exists(os.path.join(self.dir, a["file"]))]
        if not files or not ensure_ocr():
            return
        out = {}
        for i in range(0, len(files), 20):
            p = heavy([OCR_BIN] + files[i:i + 20], timeout=1800)
            for line in p.stdout.splitlines():
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                out[j.get("file")] = " ".join(x["text"] for x in j.get("lines", []))
        for a in self.assets:
            t = out.get(os.path.join(self.dir, a["file"]))
            if t is None:
                continue
            a["ocr_text"] = t[:400]
            if re.search("[\u2013\u2014]", t):
                a["warning"] = "contains an em/en dash (OCR): crop past it before use or gate checks 1/2 fail"

    def finish(self):
        self.ocr_scan()
        claims = []
        for c in self.story["claims"]:
            ev = [a for a in self.assets if c["n"] in a.get("claims", []) and a.get("usable")]
            ev.sort(key=lambda a: (0 if a["type"].startswith("document") else 1 if a["type"] == "page_claim_crop" else 2, -a.get("match_score", 0)))
            o = (self.plan.get("claims") or {}).get(str(c["n"]), {})
            entry = {"n": c["n"], "text": c["text"], "ledger_source": c["source_label"], "evidence": [a["id"] for a in ev]}
            for k in o.get("also") or []:  # reviewer-linked evidence (asset id or file substring), e.g. a register page
                for a in self.assets:
                    if a.get("usable") and (k == a["id"] or k in a["file"]) and a["id"] not in entry["evidence"]:
                        entry["evidence"].append(a["id"])
                        if c["n"] not in a["claims"]:
                            a["claims"].append(c["n"])
            if entry["evidence"]:
                entry["status"] = "evidenced"
                entry["primary"] = [a["id"] for a in ev if a["type"].startswith("document")][:2]
            else:
                entry["status"] = "none_available"
                entry["none_reason"] = o.get("none_reason") or "UNEXPLAINED: no source location matched this claim's find tokens"
            if o.get("note"):
                entry["note"] = o["note"]
            claims.append(entry)
        man = {"id": self.sid, "title": self.story["title"], "kind": self.story["kind"], "script": os.path.relpath(self.story["path"], V2),
               "built_at": now(), "rules": "v2/kit/media/MEDIA-RULES.md", "tool": "v2/kit/tools/source_media.py",
               "story_date": self.plan.get("story_date"), "claims": claims, "entities": self.entities_out,
               "assets": self.assets, "rejected": self.rejected + [dict(id=a["id"], reason=a["reject_reason"]) for a in self.assets if a.get("reject_reason")],
               "skipped_sources": self.skipped,
               "counts": {}}
        for a in self.assets:
            if a.get("usable"):
                man["counts"][a["type"]] = man["counts"].get(a["type"], 0) + 1
        json.dump(man, open(os.path.join(self.dir, "manifest.json"), "w"), indent=1, ensure_ascii=False)
        self.write_evidence(man)
        self.write_credits(man)
        self.contact(man)
        return man

    def write_credits(self, man):
        """CREDITS.json in the writers' hand-sourced format (specs/S48/media/CREDITS.json, specs/C10/media/CREDITS.json):
        logos[] and documents_quoted_verbatim[], plus screenshots[], photos[], clips[]. `file` paths are relative to v2/kit."""
        kp = lambda f: os.path.relpath(os.path.join(self.dir, f), KIT)  # noqa: E731
        cr = {"retrieved": man["built_at"][:10], "generated_by": "tools/source_media.py %s" % man["id"], "manifest": kp("manifest.json"),
              "logos": [], "documents_quoted_verbatim": [], "screenshots": [], "photos": [], "clips": []}
        for a in man["assets"]:
            if not a.get("usable"):
                continue
            base = {"key": a["id"], "file": kp(a["file"]), "source": a.get("source_url"), "licence": a.get("licence"),
                    "review_note": a.get("review_note"),
                    "attribution_on_screen": a.get("credit_line"), "retrieved_at": a.get("retrieved_at"), "claims": a.get("claims", [])}
            if a["type"] == "logo":
                cr["logos"].append(dict(base, what="%s logo" % ", ".join(a.get("entities", [])), author=a.get("author"),
                                        original=kp(a["original_file"]) if a.get("original_file") else None,
                                        valid_from=a.get("valid_from"), valid_to=a.get("valid_to"),
                                        use="identification of the company under discussion; editorial, no endorsement implied"))
            elif a["type"] in ("page_claim_crop", "document_claim_crop"):
                cr["documents_quoted_verbatim"].append(dict(base, where="claim %s" % ",".join(map(str, a.get("claims", []))),
                                                            text=a.get("matched_text"), headline=a.get("headline") or a.get("document_title"),
                                                            byline=a.get("byline"), date=a.get("published") or a.get("document_date"),
                                                            page=a.get("page"), highlight_boxes_px=a.get("highlight_boxes_px"),
                                                            use=a.get("rights_basis")))
            elif a["type"] in ("page_hero", "page_byline", "page_fold", "page_masthead", "document_page"):
                cr["screenshots"].append(dict(base, what=a["type"], headline=a.get("headline") or a.get("document_title"),
                                              byline=a.get("byline"), date=a.get("published") or a.get("document_date"), page=a.get("page"),
                                              use=a.get("rights_basis")))
            elif a["type"] == "photo":
                cr["photos"].append(dict(base, author=a.get("author"), what=a.get("description"), use=a.get("rights_basis")))
            elif a["type"] == "clip_candidate":
                cr["clips"].append(dict(base, what=a.get("title"), channel=a.get("channel"), clip_in_s=a.get("clip_in_s"),
                                        clip_out_s=a.get("clip_out_s"), content_id_risk=a.get("content_id_risk"), use=a.get("rights_basis")))
        json.dump(cr, open(os.path.join(self.dir, "CREDITS.json"), "w"), indent=1, ensure_ascii=False)

    def write_evidence(self, man):
        A = {a["id"]: a for a in man["assets"]}
        L = ["# %s real-media evidence pack" % man["id"], "",
             "Built %s by `v2/kit/tools/source_media.py %s`. Rules: `v2/kit/media/MEDIA-RULES.md`. Every asset's licence, "
             "rights basis and on-screen credit is in `manifest.json`." % (man["built_at"], man["id"]), "",
             "## Claims", "", "| # | Claim (fact ledger) | Status | Evidence (best first) |", "|---|---|---|---|"]
        for c in man["claims"]:
            ev = "<br>".join("`%s` %s%s" % (A[x]["file"] if x in A else x, (A[x].get("publisher") or A[x].get("channel") or "") if x in A else "",
                                             (" p.%s" % A[x]["page"]) if x in A and A[x].get("page") and A[x]["type"] == "document_claim_crop" else "")
                             for x in c["evidence"][:4]) or ("none available: " + c.get("none_reason", ""))
            L.append("| %d | %s | %s | %s |" % (c["n"], c["text"].replace("|", "/"), c["status"], ev))
        L += ["", "## Entities", "", "| Entity | Wikidata | Logo | Licence |", "|---|---|---|---|"]
        for e in man["entities"]:
            lg = e.get("logo")
            L.append("| %s | %s | %s | %s |" % (e["name"], e.get("qid") or "", ("`%s`" % lg["file"]) if lg else "none: " + e.get("logo_none_reason", ""),
                                                A[lg["asset"]]["licence"][:90] if lg and lg.get("asset") in A else ""))
        L += ["", "## Assets by type", ""] + ["- %s: %d" % (k, v) for k, v in sorted(man["counts"].items())]
        if man["skipped_sources"]:
            L += ["", "## Sources not usable", ""] + ["- %s: %s" % (s["url"], s["reason"]) for s in man["skipped_sources"]]
        if man["rejected"]:
            L += ["", "## Rejected", ""] + ["- %s: %s" % (r.get("title") or r.get("url") or r.get("id"), r["reason"]) for r in man["rejected"]]
        open(os.path.join(self.dir, "EVIDENCE.md"), "w").write("\n".join(L) + "\n")

    def contact(self, man):
        from PIL import Image, ImageDraw
        ims = [a for a in man["assets"] if a.get("usable") and a["file"].lower().endswith((".png", ".jpg")) and os.path.exists(os.path.join(self.dir, a["file"]))]
        if not ims:
            return
        TW, TH, cols = 420, 330, 5
        rows = (len(ims) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * TW, rows * (TH + 44)), (24, 24, 24))
        d = ImageDraw.Draw(sheet)
        for i, a in enumerate(ims):
            im = Image.open(os.path.join(self.dir, a["file"])).convert("RGBA")
            bg = Image.new("RGBA", im.size, (205, 205, 205, 255)); bg.alpha_composite(im); im = bg.convert("RGB")
            im.thumbnail((TW - 12, TH - 12))
            x, y = (i % cols) * TW, (i // cols) * (TH + 44)
            sheet.paste(im, (x + (TW - im.width) // 2, y + 6))
            d.text((x + 6, y + TH + 2), a["type"][:40], fill=(255, 210, 90))
            d.text((x + 6, y + TH + 16), os.path.basename(a["file"])[:58], fill=(230, 230, 230))
            d.text((x + 6, y + TH + 29), ("claims " + ",".join(map(str, a.get("claims", [])))) if a.get("claims") else "", fill=(140, 220, 140))
        sheet.save(os.path.join(self.dir, "contact.jpg"), quality=85)


def logo_has_ink(path):
    """A rendered logo must carry visible marks: a broken-image render is flat grey or fully transparent."""
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    a = im.getchannel("A").resize((200, 200))
    opaque = sum(1 for v in a.getdata() if v > 16) / 40000.0
    if opaque < 0.05:  # a broken <img> leaves a 16 px icon on a transparent box
        return False
    bg = Image.new("RGBA", im.size, (128, 128, 128, 255)); bg.alpha_composite(im)  # black-on-transparent read as all black
    rgb = bg.convert("RGB").resize((64, 64))
    lo, hi = zip(*rgb.getextrema())
    return max(h - l for l, h in zip(lo, hi)) > 40


def build(sid, refresh=False, clips=True):
    pk = Pack(sid, refresh, clips)
    if refresh:
        for sub in ("pages", "docs", "logos", "photos", "clips"):
            for f in glob.glob(os.path.join(pk.dir, sub, "*")):
                os.remove(f)
    pk.sources()
    pk.entities()
    pk.photos()
    pk.clips()
    man = pk.finish()
    print(json.dumps(man["counts"], indent=1))
    print("claims:", ", ".join("%d %s" % (c["n"], c["status"]) for c in man["claims"]))
    print("pack:", pk.dir)
    return verify(sid)

# ------------------------------------------------------------------------------------------------------- verify

def verify(sid):
    d = os.path.join(MEDIA, sid.upper())
    mp = os.path.join(d, "manifest.json")
    if not os.path.exists(mp):
        print("FAIL: no manifest", mp); return 1
    man = json.load(open(mp))
    errs = []
    A = {a["id"]: a for a in man["assets"]}
    for c in man["claims"]:
        if c["status"] == "evidenced":
            live = [x for x in c["evidence"] if x in A and A[x].get("usable")]
            if not live:
                errs.append("claim %d marked evidenced but no usable asset" % c["n"])
        elif not c.get("none_reason") or c["none_reason"].startswith("UNEXPLAINED"):
            errs.append("claim %d: no evidence and no stated reason" % c["n"])
    for a in man["assets"]:
        if not a.get("usable"):
            continue
        for k in ("file", "source_url", "retrieved_at", "licence", "credit_line", "rights_basis"):
            if not a.get(k):
                errs.append("%s: missing %s" % (a["id"], k))
        if a["type"] != "clip_candidate" and not os.path.exists(os.path.join(d, a["file"])):
            errs.append("%s: file missing %s" % (a["id"], a["file"]))
        if a.get("sha256") and os.path.exists(os.path.join(d, a["file"])) and sha(os.path.join(d, a["file"])) != a["sha256"]:
            errs.append("%s: file changed since manifest (sha256)" % a["id"])
        if "—" in a.get("credit_line", "") or "–" in a.get("credit_line", ""):
            errs.append("%s: dash in credit line" % a["id"])
    for e in man["entities"]:
        if not e.get("logo") and not e.get("logo_none_reason"):
            errs.append("entity %s: no logo and no reason" % e["name"])
    n_ev = sum(1 for c in man["claims"] if c["status"] == "evidenced")
    print("%s: %d/%d claims evidenced, %d none-available, %d usable assets, %d entities" % (
        sid, n_ev, len(man["claims"]), len(man["claims"]) - n_ev, sum(1 for a in man["assets"] if a.get("usable")), len(man["entities"])))
    for a in man["assets"]:
        if a.get("usable") and a.get("warning"):
            print("  WARN %s: %s" % (a["id"], a["warning"]))
    for e in errs:
        print("  FAIL", e)
    print("VERIFY", "PASS" if not errs else "FAIL (%d)" % len(errs))
    return 1 if errs else 0


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit(2)
    if a[0] == "_browser":
        return browser_worker(a[1], a[2])
    if a[0] == "_pdf":
        return pdf_worker(a[1], a[2])
    if a[0] == "verify":
        sys.exit(verify(a[1]))
    sys.exit(build(a[0], refresh="--refresh" in a, clips="--no-clips" not in a))


if __name__ == "__main__":
    main()
