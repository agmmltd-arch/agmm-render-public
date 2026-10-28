#!/usr/bin/env python3
"""assets.py: the REAL-ASSET LANE for forge2 (card forge-assets, 6 Oct 2026). Real logos and real photographs for a short, free, licence-gated, cached.

  assets.py fetch <ID> [--names "A,B"] [--photos N] [--refresh]   find the organisations in the script, fetch each real logo and up to N (default 2) licensed photographs
  assets.py verify <ID>                                           exit 1 unless every kept asset has file, source URL, licence and credit; prints refusals
  assets.py resolve "<Name>"                                      one logo (cache) and print its record, for a quick look

What it does (all headless, through heavy.py; Wikimedia is asked politely through source_media.api_json, which caches and paces):
  LOGOS   Wikidata search (the name must equal the item's label or alias) -> P154 logo -> Commons file info. The file is kept ONLY when its Commons licence is on the
          whitelist (CC0, CC BY, CC BY-SA, public domain / PD-textlogo, OGL): the URL, licence, licence URL, author and retrieval time are recorded. Anything else (no logo,
          unknown or non-free licence, ambiguous entity) is REFUSED with its reason and the beat uses a typeset wordmark in the brand colour instead. Nothing is invented:
          a URL is only ever one the Wikimedia API itself returned.
  PHOTOS  Commons search on the organisation or place, bitmap JPEG, width >= 1000, licence on the whitelist, no people (title/description words), at most N kept. The credit
          line shown on screen is "Photo: <author>, <licence>" (author trimmed to 22 characters).
Cache: kit/assets/cache/<kind>/<slug>.* plus .json (reused by every short; --refresh refetches). Per-short result: kit/assets/<ID>/assets.json.
Never prints a secret (none is used). Rules: kit/media/MEDIA-RULES.md (logos editorial only, never on the CTA frame, never implying endorsement)."""
import datetime, hashlib, json, os, re, shutil, subprocess, sys, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
V2 = os.path.dirname(KIT)
ASSETS = os.path.join(KIT, "assets")
HEAVY = os.path.join(HERE, "heavy.py")
sys.path.insert(0, HERE)
import source_media as SM  # noqa: E402  (api_json, commons_info, commons_search, wd_search, wd_entities, pick_logo, PD_GOOD, PEOPLEY, http, load_short)

GENERIC = set("""AI Asked American Follow None The This That It They He She We You I Our Their There When Then But So If And Or Of In On At For To UK British English Monday Tuesday Wednesday Thursday Friday
Saturday Sunday January February March April May June July August September October November December Every Some Most Many One Two Three New Last First Next Here Now Not Yes No""".split())


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "x"


def lic_ok(lic):
    l = (lic or "").strip()
    if not l:
        return False
    if re.search(r"non-?free|fair use|all rights reserved|copyrighted|unknown|no known|permission", l, re.I):
        return False
    return bool(SM.PD_GOOD.match(l) or re.match(r"^(public domain|pd[- ]|cc[- ]?0|cc[- ]by|ogl|open government licence)", l, re.I))


# Wikidata classes that make an item an organisation or brand (the entity gate: a surname, a place or a person never gets a logo or a photograph by name collision)
ORG_CLASSES = {"Q4830453", "Q783794", "Q43229", "Q327333", "Q891723", "Q6881511", "Q1616075", "Q2085381", "Q1058914", "Q431289", "Q167270", "Q7210356", "Q484652", "Q245016", "Q178790",
               "Q1664720", "Q2659904", "Q15265344", "Q11032", "Q41298", "Q1002697", "Q22687", "Q7278", "Q1321960", "Q15911314", "Q5003624", "Q16917", "Q3918", "Q31855", "Q7075", "Q14350566",
               "Q4382945", "Q3914", "Q2385804", "Q28640", "Q1048835", "Q66344", "Q220659", "Q2001305", "Q5", "Q1307214", "Q3624078", "Q6256", "Q1006733", "Q1752346", "Q161726", "Q10689397", "Q116452534"} - {"Q5"}


def is_org(ent):
    """an organisation / company / brand / product item: has a logo (P154), or is an instance of an organisation class (never a human, Q5)"""
    cls = {c["mainsnak"]["datavalue"]["value"].get("id") for c in SM.claim_value(ent, "P31") if isinstance(c["mainsnak"]["datavalue"]["value"], dict)}
    if "Q5" in cls:
        return False
    return bool(SM.claim_value(ent, "P154") or (cls & ORG_CLASSES) or (SM.claim_value(ent, "P856") and not SM.claim_value(ent, "P625")))      # an official website and no coordinates: a body, not a place


def cache_dir(kind):
    d = os.path.join(ASSETS, "cache", kind)
    os.makedirs(d, exist_ok=True)
    return d


def download(url, dest):
    for i in range(3):
        st, ct, _, data = SM.http(url, ua=SM.WIKI_UA, binary=True, tries=1)
        if st == 200 and data and len(data) > 800:
            open(dest, "wb").write(data)
            return True
        time.sleep(8 * (i + 1))
    return False


def entities_for(ID, names=None):
    """organisations named in the short: the subject and its parts ('Harber v HMRC' -> Harber, HMRC), the outlets, then capitalised names by frequency in the script"""
    story = SM.load_short(ID)
    out, seen = [], set()

    def add(n, role):
        n = re.sub(r"\s+", " ", n).strip(" .,:;()'\"")
        if not n or n in GENERIC or len(n) < 2 or n.lower() in seen:
            return
        seen.add(n.lower())
        out.append({"name": n, "role": role})
    if names:
        for n in names:
            add(n, "named")
        return out, story
    for part in re.split(r"\s+(?:v|vs|and|&)\s+", re.sub(r"\s*\(.*?\)", "", story["company"])):
        add(part, "subject")
    for e in SM.derive_entities(story):
        if e["role"] in ("outlet", "source"):
            add(e["name"], e["role"])
    freq = {}
    for mm in re.finditer(r"\b([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*)\b", story["script"]):
        m = " ".join(w for w in mm.group(1).split() if w not in GENERIC)
        pre = story["script"][max(0, mm.start() - 3):mm.start()]
        sentence_start = mm.start() == 0 or bool(re.search(r"[.!?\n]\s*$", pre)) or pre.strip() == "" 
        if m and len(m) > 2 and not (sentence_start and " " not in m and not m.isupper() and not re.search(r"[a-z][A-Z]", m)):      # a lone capitalised word at a sentence start is just a sentence start
            freq[m] = freq.get(m, 0) + 1
    for n, c in sorted(freq.items(), key=lambda kv: -kv[1])[:6]:
        add(n, "mentioned")
    return out[:9], story


def resolve_logo(name, story_date="2026-10", refresh=False):
    """-> record with file (a PNG in the cache) or refused (reason)"""
    d = cache_dir("logos")
    jp = os.path.join(d, slug(name) + ".json")
    if os.path.exists(jp) and not refresh:
        return json.load(open(jp))
    rec = {"name": name, "retrieved": now()}
    ents = SM.wd_search(name)
    cand = None
    for e in ents[:5]:
        mt = (e.get("match") or {}).get("text", e.get("label", ""))
        by_label = e.get("label", "").lower() == name.lower()
        by_alias = mt.lower() == name.lower() and not by_label
        if by_label or (by_alias and (name.isupper() or " " in name)):      # an alias match is trusted only for an acronym (HMRC) or a multi-word name; "Only" is not an alias of anything we mean
            cand = e
            break
    if not cand:
        rec["refused"] = "no Wikidata item whose label or alias equals the name (ambiguous or unknown organisation)"
        json.dump(rec, open(jp, "w"), indent=1)
        return rec
    ent = SM.wd_entities([cand["id"]]).get(cand["id"], {})
    rec["wikidata"] = cand["id"]
    if not is_org(ent):
        rec["refused"] = "Wikidata %s is not an organisation, company or brand (name collision with a person or a place): no logo and no wordmark" % cand["id"]
        json.dump(rec, open(jp, "w"), indent=1)
        return rec
    rec["org"] = True
    pl = SM.pick_logo(ent, story_date)
    if not pl:      # no P154: a Commons drawing whose title carries the organisation's name and the word logo (still licence-gated below)
        lab = cand.get("label") or name
        for t in SM.commons_search(lab + " logo", "drawing", limit=8):
            tl = re.sub(r"^file:", "", t.lower().replace("_", " ")).strip()
            if re.match(r"^%s\b[\s(\-]*(logo|wordmark|symbol)" % re.escape(lab.lower()), tl):      # the title must BEGIN with the organisation's name then 'logo' ("Text only" in another charity's file is not the brand ONLY)
                pl = {"file": t, "why": "Commons search '%s logo' (no Wikidata P154)" % lab}
                break
    if not pl:
        rec["refused"] = "Wikidata %s has no logo image (P154) and Commons has no matching logo drawing" % cand["id"]
        json.dump(rec, open(jp, "w"), indent=1)
        return rec
    ci = SM.commons_info(pl["file"], width=900)
    if not ci:
        rec["refused"] = "Commons file %s not found" % pl["file"]
        json.dump(rec, open(jp, "w"), indent=1)
        return rec
    rec.update({"commons": ci["page"], "file_url": ci["url"], "licence": ci["licence"], "licence_url": ci.get("licence_url"), "author": (ci.get("artist") or "")[:80], "why": pl["why"], "restrictions": ci.get("restrictions")})
    if not lic_ok(ci["licence"]):
        rec["refused"] = "licence not on the whitelist (%s)" % (ci["licence"] or "unknown")
        json.dump(rec, open(jp, "w"), indent=1)
        return rec
    thumb = ci.get("thumb") or ci["url"]
    ext = ".png" if (thumb.lower().endswith(".png") or ".svg." in thumb.lower()) else os.path.splitext(urllib.parse.urlparse(thumb).path)[1] or ".png"
    dest = os.path.join(d, slug(name) + ext)
    if not download(thumb, dest):
        ci2 = SM.commons_info(pl["file"], width=480)      # the 900 px thumbnail was refused or missing: a smaller one is still a sharp logo on a card
        if not (ci2 and ci2.get("thumb") and download(ci2["thumb"], dest)):
            pass
    if not os.path.exists(dest):
        rec["refused"] = "download failed (%s)" % thumb[:80]
        json.dump(rec, open(jp, "w"), indent=1)
        return rec
    rec["file"] = os.path.relpath(dest, ASSETS)
    rec["w"], rec["h"] = ci.get("w"), ci.get("h")
    json.dump(rec, open(jp, "w"), indent=1)
    return rec


def resolve_photos(name, want, refresh=False):
    d = cache_dir("photos")
    jp = os.path.join(d, slug(name) + ".json")
    if os.path.exists(jp) and not refresh:
        return json.load(open(jp))
    out = {"name": name, "retrieved": now(), "photos": [], "rejected": []}
    cand = None
    for e in SM.wd_search(name)[:5]:
        if (e.get("match") or {}).get("text", e.get("label", "")).lower() == name.lower() or e.get("label", "").lower() == name.lower():
            cand = e
            break
    titles = []
    if cand:
        ent = SM.wd_entities([cand["id"]]).get(cand["id"], {})
        if is_org(ent):      # the photograph is the one Wikidata itself records as THIS organisation's image (P18): relevance by record, never by a name search
            titles = [c["mainsnak"]["datavalue"]["value"] for c in SM.claim_value(ent, "P18")][:6]
        else:
            out["rejected"].append({"title": name, "why": "not an organisation item"})
    else:
        out["rejected"].append({"title": name, "why": "no Wikidata item with that label"})
    for t in titles:
        if len(out["photos"]) >= want:
            break
        ci = SM.commons_info(t, width=1400)
        if not ci or (ci.get("mime") or "") != "image/jpeg" or (ci.get("w") or 0) < 1000:
            continue
        txt = " ".join([t, ci.get("desc") or "", ci.get("artist") or ""])
        why = None
        if not lic_ok(ci.get("licence")):
            why = "licence %s" % (ci.get("licence") or "unknown")
        elif SM.PEOPLEY.search(txt):
            why = "people in the title or description"
        elif re.search(r"personality|trademark", ci.get("restrictions") or "", re.I):
            why = "restrictions: %s" % ci.get("restrictions")
        if why:
            out["rejected"].append({"title": t, "why": why})
            continue
        dest = os.path.join(d, slug(name) + "-%d.jpg" % (len(out["photos"]) + 1))
        if not download(ci.get("thumb") or ci["url"], dest):
            continue
        au = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", ci.get("artist") or "Wikimedia Commons")).strip()
        au = (au[:22]).rstrip(" ,;.") or "Wikimedia Commons"
        lic = ci["licence"]
        out["photos"].append({"file": os.path.relpath(dest, ASSETS), "commons": ci["page"], "file_url": ci["url"], "licence": lic, "licence_url": ci.get("licence_url"), "author": au,
                              "credit": "Photo: %s, %s" % (au, lic), "w": ci.get("w"), "h": ci.get("h"), "ratio": round((ci.get("h") or 1) / float(ci.get("w") or 1), 3), "title": t})
    json.dump(out, open(jp, "w"), indent=1)
    return out


def fetch(ID, names=None, photos=2, refresh=False):
    ents, story = entities_for(ID, names)
    res = {"id": ID, "retrieved": now(), "story_date": "2026-10", "logos": {}, "wordmarks": {}, "photos": [], "entities": ents}
    for e in ents:
        r = resolve_logo(e["name"], refresh=refresh)
        if r.get("file"):
            res["logos"][e["name"]] = r
        else:
            res["wordmarks"][e["name"]] = {"reason": r.get("refused", "?"), "wikidata": r.get("wikidata"), "org": bool(r.get("org"))}      # org False: a person, a place or an unknown name gets NO wordmark either
    for e in ents:
        if len(res["photos"]) >= photos or e["role"] == "mentioned" and len(res["photos"]) >= 1:
            break
        if e["name"] in ("ChatGPT", "OpenAI", "Google", "Microsoft", "Bing", "Bard", "Claude"):      # a product has no place to photograph
            continue
        r = resolve_photos(e["name"], photos - len(res["photos"]), refresh=refresh)
        for p in r.get("photos", []):
            p = dict(p); p["of"] = e["name"]
            res["photos"].append(p)
    d = os.path.join(ASSETS, ID)
    os.makedirs(d, exist_ok=True)
    json.dump(res, open(os.path.join(d, "assets.json"), "w"), indent=1, ensure_ascii=False)
    return res


def verify(ID):
    p = os.path.join(ASSETS, ID, "assets.json")
    if not os.path.exists(p):
        print("FAIL: no assets.json (run fetch)")
        return 1
    d = json.load(open(p))
    bad = []
    for n, r in d["logos"].items():
        for k in ("file", "commons", "licence", "retrieved"):
            if not r.get(k):
                bad.append("logo %s missing %s" % (n, k))
        if not os.path.exists(os.path.join(ASSETS, r.get("file", "x"))):
            bad.append("logo %s file missing on disk" % n)
        if not lic_ok(r.get("licence")):
            bad.append("logo %s licence not whitelisted: %s" % (n, r.get("licence")))
    for r in d["photos"]:
        for k in ("file", "commons", "licence", "credit"):
            if not r.get(k):
                bad.append("photo %s missing %s" % (r.get("title"), k))
        if not os.path.exists(os.path.join(ASSETS, r.get("file", "x"))):
            bad.append("photo file missing on disk")
        if not lic_ok(r.get("licence")):
            bad.append("photo licence not whitelisted: %s" % r.get("licence"))
    print("logos kept: %d | wordmark fallbacks: %d | photos kept: %d" % (len(d["logos"]), len(d["wordmarks"]), len(d["photos"])))
    for n, w in d["wordmarks"].items():
        print("  wordmark  %-18s %s" % (n, w["reason"]))
    for n, r in d["logos"].items():
        print("  LOGO      %-18s %s | %s | %s" % (n, r["licence"], r["commons"], r["file"]))
    for r in d["photos"]:
        print("  PHOTO     %-18s %s | %s" % (r.get("of", ""), r["credit"], r["commons"]))
    for b in bad:
        print("FAIL:", b)
    return 1 if bad else 0


def under_heavy(argv):
    return subprocess.call([sys.executable, HEAVY, "--", sys.executable, os.path.abspath(__file__)] + ["_run"] + argv)


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 2
    cmd = a[0]
    if cmd in ("fetch", "resolve") and os.environ.get("ASSETS_UNDER_HEAVY") != "1":
        os.environ["ASSETS_UNDER_HEAVY"] = "1"      # every fetch runs through heavy.py (machine-wide slots, nice)
        return under_heavy(a)
    if cmd == "_run":
        a = a[1:]
        cmd = a[0]
    if cmd == "fetch":
        ID = a[1]
        names = None
        photos = 2
        if "--names" in a:
            names = [x.strip() for x in a[a.index("--names") + 1].split(",") if x.strip()]
        if "--photos" in a:
            photos = int(a[a.index("--photos") + 1])
        r = fetch(ID, names, photos, "--refresh" in a)
        return verify(ID)
    if cmd == "resolve":
        r = resolve_logo(a[1], refresh="--refresh" in a)
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 0 if r.get("file") else 1
    if cmd == "verify":
        return verify(a[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
