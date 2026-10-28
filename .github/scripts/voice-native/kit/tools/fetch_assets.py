#!/usr/bin/env python3
"""fetch_assets.py: keyless, licence-gated stock for the format engine (p12, prod-2030-2026-10-20, 20 Oct 2026).

  fetch_assets.py logo  "<Name>" [--for ID] [--refresh]      company logo from Wikimedia Commons (via Wikidata P154)
  fetch_assets.py image "<query>" [--for ID] [--n 3] [--min-w 700] [--orientation tall|wide|square]
                                                            commercial-licence photograph / illustration from Openverse
  fetch_assets.py sfx   "<query>" [--kind whoosh] [--for ID] [--max-ms 4000]
                                                            commercial-licence sound effect from Openverse (audio)
  fetch_assets.py verify                                    every registry record: file on disk, sha256 matches, licence on the whitelist, attribution + source URL present
  fetch_assets.py list                                      what is registered
  fetch_assets.py credits ID                                CAPTION CREDITS lines for every asset registered for that short
  fetch_assets.py --selftest                                fetches ONE real logo and ONE real whoosh SFX and records the licence of each; FAILS if either is missing,
                                                            and proves the verifier can fail (a record with its licence blanked is refused)

Why this file exists: lesson 5 of kit/CREATIVE-SCHOOL.md ("assets come from free libraries with the licence recorded") and the format engine
(kit/tools/format_engine.py) needs the known name's logo, a hero image and its sound cues without a model or a key. It EXTENDS kit/tools/assets.py (Law 1: no
second Wikimedia logic): logos go through assets.resolve_logo (Wikidata item must equal the name, must be an organisation, Commons licence on the whitelist), then
this file adds the sha256, the attribution text, the trademark note and the registry rows. Openverse images and audio are new here.

Sources (no key, no account, nothing paid):
  Openverse  https://api.openverse.org/v1/images/ and /v1/audio/, license_type=commercial, then this file ALSO drops every -nd, -nc and sampling licence
             (the engine crops, scales and mixes: an ND work cannot be adapted). Kept: CC0, PDM, CC BY, CC BY-SA. The licence, creator, landing page and
             Openverse's own attribution string are recorded verbatim.
             1024 PX CEILING: Openverse's thumbnail proxy (/v1/images/<id>/thumb/) never returns more than 1024 px. The original `url` is tried first (and kept when it
             is <= 8 MB); when only the proxy works the record says so and `max_display_px` is the file's real width, so build_short's display_w rule (never upscale)
             can hold. Audio is the provider's own preview (mp3); its onset is NOT measured here (decoding is Actions-only), so `onset_ms` is null and the engine does
             not place a fetched cue by onset until a measured value is registered.
  Wikimedia  Commons through assets.resolve_logo. Every logo is marked `use: "logo: editorial identification use"` (a trademark: it identifies the company the
             story is about, never on the CTA card, never beside the AGMM mark; kit/media/MEDIA-RULES.md).

Registries (all written atomically under a lock; existing registries are only APPENDED to):
  kit/registry/fetched-images.json   images + logos: key -> {kind, name/query, file, source_url, landing_url, licence, licence_url, creator, attribution, use, sha256, w, h, max_display_px, used_by[]}
  kit/registry/fetched-sfx.json      sound effects, same fields plus duration_ms, onset_ms (null), onset_measured (false)
  kit/registry/images.json           the kit's existing sha256 -> owning short map: each fetched image/logo adds sha256 -> "fetch_assets:<ID or slug>" so no generated image
                                     can ever collide with it and a stock photo is not handed to two shorts (backup: images.json.bak-2026-10-20-fleet)
Files: kit/assets/cache/openverse/ (images), kit/assets/cache/sfx/ (audio), logos stay where assets.py keeps them (kit/assets/cache/logos/).
Never prints a secret (none is used). The network is the only side effect; nothing is rendered or decoded."""
import argparse, datetime, fcntl, hashlib, json, os, re, shutil, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
V2 = os.path.dirname(KIT)
ASSETS = os.path.join(KIT, "assets")
REG = os.path.join(KIT, "registry")
R_IMG = os.path.join(REG, "fetched-images.json")
R_SFX = os.path.join(REG, "fetched-sfx.json")
R_HASH = os.path.join(REG, "images.json")
UA = "AGMM-fetch-assets/1.0 (agmm.co.uk; editorial video, licence-gated stock)"
OV = "https://api.openverse.org/v1"
OK_LICENCES = {"cc0", "pdm", "by", "by-sa"}          # Openverse license slugs we keep (commercial use + adaptation allowed)
MAX_IMG_BYTES = 8_000_000
LOGO_USE = "logo: editorial identification use"
sys.path.insert(0, HERE)


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def slug(s, n=40):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:n] or "x"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------ http (cached JSON, polite)
def http(url, binary=False, timeout=40, tries=3):
    last = (0, b"" if binary else "")
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                return r.status, (data if binary else data.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = (e.code, b"" if binary else "")
            if e.code in (429, 502, 503) and i + 1 < tries:
                time.sleep(6 * (i + 1))
                continue
            return last
        except Exception:
            last = (0, b"" if binary else "")
            time.sleep(2)
    return last


def api_json(url, cache_days=7):
    cdir = os.path.join(ASSETS, "cache", "api")
    os.makedirs(cdir, exist_ok=True)
    cf = os.path.join(cdir, "ov-" + hashlib.sha1(url.encode()).hexdigest() + ".json")
    if os.path.exists(cf) and time.time() - os.path.getmtime(cf) < cache_days * 86400:
        return json.load(open(cf))
    time.sleep(0.6)
    st, body = http(url)
    if st != 200:
        raise RuntimeError("Openverse HTTP %s for %s" % (st, url.split("?")[0]))
    j = json.loads(body)
    json.dump(j, open(cf, "w"))
    return j


# ------------------------------------------------------------------------------------------------ registries
class Locked:
    def __init__(self, path):
        self.path = path
        self.fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fh = open(self.path + ".lock", "a")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def load_reg(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return {}


def save_reg(path, d):
    tmp = path + ".tmp-%d" % os.getpid()
    json.dump(d, open(tmp, "w"), indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def backup_once(path):
    bak = path + ".bak-2026-10-20-fleet"
    if os.path.exists(path) and not os.path.exists(bak):
        shutil.copy2(path, bak)


def register(reg_path, key, rec, for_id=None):
    """append-only upsert of one record; used_by accumulates; images.json gets sha256 -> owner."""
    with Locked(reg_path):
        reg = load_reg(reg_path)
        old = reg.get(key, {})
        used = sorted(set((old.get("used_by") or []) + ([for_id] if for_id else [])))
        rec = dict(rec, used_by=used, registered=old.get("registered") or now())
        reg[key] = rec
        save_reg(reg_path, reg)
    if rec.get("sha256") and reg_path == R_IMG:
        with Locked(R_HASH):
            backup_once(R_HASH)
            h = load_reg(R_HASH)
            h.setdefault(rec["sha256"], "fetch_assets:" + (for_id or key))
            save_reg(R_HASH, h)
    return rec


# ------------------------------------------------------------------------------------------------ Openverse
def lic_slug(r):
    return str(r.get("license") or "").lower()


def lic_text(r):
    s = lic_slug(r)
    if s == "cc0":
        return "CC0 1.0"
    if s == "pdm":
        return "Public Domain Mark 1.0"
    return "CC %s %s" % (s.upper(), r.get("license_version") or "")


def ov_ok(r):
    return lic_slug(r) in OK_LICENCES and not r.get("mature") and bool(r.get("url")) and bool(r.get("foreign_landing_url") or r.get("detail_url"))


def ov_search(kind, q, **kw):
    p = {"q": q, "license_type": "commercial", "page_size": kw.pop("page_size", 20), "mature": "false"}
    p.update({k: v for k, v in kw.items() if v is not None})
    j = api_json("%s/%s/?%s" % (OV, kind, urllib.parse.urlencode(p)))
    return [r for r in j.get("results", []) if ov_ok(r)]


def _dims(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (None, None)


def _record_common(r, dest, kind, query):
    credit = r.get("attribution") or ('"%s" by %s is licensed under %s.' % (r.get("title") or "untitled", r.get("creator") or "unknown", lic_text(r)))
    return {"kind": kind, "query": query, "openverse_id": r.get("id"), "title": r.get("title"), "file": os.path.relpath(dest, ASSETS),
            "source_url": r.get("url"), "landing_url": r.get("foreign_landing_url"), "provider": r.get("provider"),
            "licence": lic_text(r), "licence_url": r.get("license_url"), "creator": r.get("creator"), "attribution": credit,
            "sha256": sha256_file(dest), "retrieved": now()}


def fetch_images(query, for_id=None, n=1, min_w=700, orientation=None, category=None, refresh=False):
    out_dir = os.path.join(ASSETS, "cache", "openverse")
    os.makedirs(out_dir, exist_ok=True)
    cands = ov_search("images", query, category=category, aspect_ratio=orientation)
    reg = load_reg(R_IMG)
    taken = {r["sha256"]: k for k, r in reg.items() if r.get("sha256")}
    out = []
    for r in cands:
        if len(out) >= n:
            break
        key = "ov-image-" + (r.get("id") or "")[:8]
        if key in reg and not refresh and os.path.exists(os.path.join(ASSETS, reg[key]["file"])):
            if for_id and for_id not in (reg[key].get("used_by") or []) and reg[key].get("used_by"):
                continue                       # already a different short's picture: a stock photo is not handed to two shorts
            out.append(register(R_IMG, key, reg[key], for_id))
            continue
        w0 = r.get("width") or 0
        if w0 and w0 < min_w:
            continue
        ext = ".jpg"
        dest = os.path.join(out_dir, "%s-%s%s" % (slug(query, 24), (r.get("id") or "x")[:8], ext))
        via = "original"
        st, data = http(r["url"], binary=True)
        if not (st == 200 and 8000 < len(data) <= MAX_IMG_BYTES):
            st, data = http("%s/images/%s/thumb/" % (OV, r["id"]), binary=True)        # the proxy: 1024 px ceiling
            via = "openverse thumb proxy (1024 px ceiling)"
        if not (st == 200 and len(data) > 8000):
            continue
        open(dest, "wb").write(data)
        w, h = _dims(dest)
        if not w or w < min_w and via == "original":
            os.remove(dest)
            continue
        rec = _record_common(r, dest, "image", query)
        if rec["sha256"] in taken and taken[rec["sha256"]] != key:
            os.remove(dest)
            continue
        rec.update({"w": w, "h": h, "max_display_px": w, "via": via, "use": "photograph/illustration, adapted (cropped, scaled)"})
        out.append(register(R_IMG, key, rec, for_id))
    return out


def fetch_sfx(query, kind="whoosh", for_id=None, max_ms=4000, refresh=False):
    out_dir = os.path.join(ASSETS, "cache", "sfx")
    os.makedirs(out_dir, exist_ok=True)
    cands = [r for r in ov_search("audio", query, category="sound_effect") if (r.get("duration") or 0) and r["duration"] <= max_ms]
    if not cands:
        cands = [r for r in ov_search("audio", query) if (r.get("duration") or 0) and r["duration"] <= max_ms]
    reg = load_reg(R_SFX)
    for r in sorted(cands, key=lambda r: (lic_slug(r) != "cc0", r.get("duration") or 0)):
        key = "ov-sfx-%s-%s" % (slug(kind, 16), (r.get("id") or "")[:8])
        if key in reg and not refresh and os.path.exists(os.path.join(ASSETS, reg[key]["file"])):
            return register(R_SFX, key, reg[key], for_id)
        ft = (r.get("filetype") or "mp3").lower()
        dest = os.path.join(out_dir, "%s-%s.%s" % (slug(kind, 16), (r.get("id") or "x")[:8], ft))
        st, data = http(r["url"], binary=True)
        if not (st == 200 and len(data) > 3000):
            continue
        open(dest, "wb").write(data)
        rec = _record_common(r, dest, "sfx", query)
        rec.update({"sfx_kind": kind, "duration_ms": r.get("duration"), "format": ft, "onset_ms": None, "onset_measured": False,
                    "use": "sound effect mixed under the voice"})
        return register(R_SFX, key, rec, for_id)
    return None


# ------------------------------------------------------------------------------------------------ SFX library harvest (26 Oct 2026, Sam: "use the Openverse API")
# Roles the format engine cues, with the Openverse queries that find candidates, the earshot description used to trim (`find`) and to rank
# (`match`), the longest a one-shot may be after trimming, and the engine cue kinds it serves. Candidates are METADATA ONLY here: the audio is
# downloaded, trimmed, measured and judged on GitHub Actions (earshot; never this Mac) by .github/scripts/earshot/sfx_analyse.py.
SFX_ROLES = {
    "whoosh": {"queries": ["whoosh", "swoosh", "swish", "air whoosh transition"], "desc": "a fast air whoosh", "alt": ["a swoosh passing by", "a short swish"], "max_s": 1.4, "kinds": ["whoosh", "seam"]},
    "tick": {"queries": ["tick", "clock tick", "small click", "light tap"], "desc": "a short light tick", "alt": ["a clock tick", "a small click", "a soft tap"], "max_s": 0.30, "kinds": ["tick", "click", "flap"]},
    "pop": {"queries": ["pop", "bubble pop", "ui pop", "cork pop"], "desc": "a soft rounded pop", "alt": ["a bubble pop", "a cork pop", "a UI pop"], "max_s": 0.45, "kinds": ["pop"]},
    "stamp": {"queries": ["rubber stamp", "stamp thud", "stamping paper", "ink stamp", "stamp", "desk thud", "book drop", "approved stamp"], "desc": "a rubber stamp thud on paper", "alt": ["a heavy thud", "a rubber stamp hitting a desk", "a book dropped on a table"], "max_s": 0.8, "kinds": ["stamp", "press"]},
    "ding": {"queries": ["ding", "notification", "bell ping", "chime"], "desc": "a bright notification ding", "alt": ["a small bell ting", "a notification chime", "a glass ting"], "max_s": 1.6, "kinds": ["ping"]},
    "impact": {"queries": ["impact", "hit", "boom", "thud", "punch"], "desc": "a punchy impact hit", "alt": ["a deep cinematic boom", "a heavy thud", "a punchy hit"], "max_s": 1.4, "kinds": ["slam", "hit", "sub"]},
    "cash": {"queries": ["coin", "cash register", "coins drop", "money"], "desc": "a coin clink", "alt": ["coins clinking", "a cash register ding", "money coins"], "max_s": 1.4, "kinds": ["money", "coin", "counter"]},
    "paper": {"queries": ["paper", "page turn", "paper rustle", "paper slide"], "desc": "a paper rustle", "alt": ["paper rustling", "a page turning", "paper sliding"], "max_s": 1.2, "kinds": ["paper"]},
    "typing": {"queries": ["keyboard typing", "key press", "typewriter", "computer keyboard"], "desc": "a mechanical keyboard key press", "alt": ["typing on a computer keyboard", "a keyboard key click", "a typewriter"], "max_s": 1.6, "kinds": ["type", "pen"]},
    "error": {"queries": ["error buzz", "error beep", "wrong answer buzzer", "denied"], "desc": "a short error buzz", "alt": ["an error beep", "a buzzer for a wrong answer", "a harsh buzz"], "max_s": 1.2, "kinds": ["error"]},
    "riser": {"queries": ["riser", "rising sweep", "count up", "ascending beeps"], "desc": "a rising riser building up", "alt": ["a rising riser building tension", "an uplifter sweep", "ascending beeps"], "max_s": 3.0, "kinds": ["riser", "count"]},
}
R_CAND = os.path.join(REG, "sfx-candidates.json")


def harvest_sfx(roles=None, pages=2, per_role=70, pace=3.6):
    """Openverse audio search per role: license_type=commercial, then only cc0 / pdm / by / by-sa (never nc, nd, sampling, unknown), not mature,
    with a real URL and landing page, 60 ms - 12 s. Metadata only (source URL, licence + URL, creator, attribution). -> kit/registry/sfx-candidates.json"""
    out = load_reg(R_CAND)
    out.setdefault("_meta", {})["harvested"] = now()
    for role, spec in SFX_ROLES.items():
        if roles and role not in roles:
            continue
        seen = {c["openverse_id"]: c for c in out.get(role, [])}
        for q in spec["queries"]:
            for pg in range(1, pages + 1):
                try:
                    time.sleep(pace)
                    rs = ov_search("audio", q, page=pg, page_size=20)
                except RuntimeError as e:
                    print("  %s / %s p%d: %s" % (role, q, pg, str(e)[:80]))
                    break
                if not rs:
                    break
                for r in rs:
                    d = r.get("duration") or 0
                    if not (60 <= d <= 12000) or r["id"] in seen or lic_slug(r) not in OK_LICENCES:
                        continue
                    seen[r["id"]] = {"openverse_id": r["id"], "role": role, "query": q, "title": r.get("title"), "source_url": r["url"], "landing_url": r.get("foreign_landing_url"),
                                     "provider": r.get("provider"), "licence_slug": lic_slug(r), "licence": lic_text(r), "licence_url": r.get("license_url"),
                                     "creator": r.get("creator"), "attribution": r.get("attribution") or '"%s" by %s is licensed under %s.' % (r.get("title") or "untitled", r.get("creator") or "unknown", lic_text(r)),
                                     "duration_ms": d, "filetype": (r.get("filetype") or "mp3").lower()}
        out[role] = list(seen.values())[:per_role]
        print("%-8s %3d candidates (cc0/pdm %d, by/by-sa %d)" % (role, len(out[role]), sum(1 for c in out[role] if c["licence_slug"] in ("cc0", "pdm")), sum(1 for c in out[role] if c["licence_slug"] in ("by", "by-sa"))), flush=True)
        save_reg(R_CAND, out)
    return out


# Root ruling 26 Oct: CC BY needs attribution in the POSTED caption, which is not wired for every platform, so only CC0 / PDM sounds are usable for now. Widen thin roles
# with cc0 / pdm-only searches (Openverse `license=cc0,pdm`) and keep ONLY ids not already harvested -> registry/sfx-candidates-extra.json
SFX_EXTRA = {
    "stamp": ["stamp", "thump", "wood hit", "desk slap", "rubber"],
    "error": ["error", "buzzer", "wrong", "negative beep", "alert"],
    "riser": ["riser", "rising", "sweep up", "build up", "uplifter"],
    "ding": ["bell", "ding", "ping", "glockenspiel", "success sound"],
    "paper": ["paper crumple", "paper tear", "newspaper", "page flip", "envelope"],
    "impact": ["punch", "slam", "bang", "drum hit", "boom"],
    "typing": ["typing", "keystroke", "typewriter key", "laptop keys", "keyboard"],
}
R_CAND_X = os.path.join(REG, "sfx-candidates-extra.json")


def harvest_extra(roles=None, pace=3.6):
    have = {c["openverse_id"] for r, v in load_reg(R_CAND).items() if r != "_meta" for c in v}
    out = load_reg(R_CAND_X)
    for role, qs in SFX_EXTRA.items():
        if roles and role not in roles:
            continue
        pages = 3 if role in ("stamp", "error", "riser", "ding") else 2
        seen = {c["openverse_id"]: c for c in out.get(role, [])}
        for q in qs:
            for pg in range(1, pages + 1):
                try:
                    time.sleep(pace)
                    rs = ov_search("audio", q, page=pg, page_size=20, license="cc0,pdm")
                except RuntimeError as e:
                    print("  %s / %s p%d: %s" % (role, q, pg, str(e)[:80]))
                    break
                if not rs:
                    break
                for r in rs:
                    d = r.get("duration") or 0
                    if not (60 <= d <= 12000) or r["id"] in seen or r["id"] in have or lic_slug(r) not in ("cc0", "pdm"):
                        continue
                    seen[r["id"]] = {"openverse_id": r["id"], "role": role, "query": q, "title": r.get("title"), "source_url": r["url"], "landing_url": r.get("foreign_landing_url"),
                                     "provider": r.get("provider"), "licence_slug": lic_slug(r), "licence": lic_text(r), "licence_url": r.get("license_url"),
                                     "creator": r.get("creator"), "attribution": r.get("attribution") or '"%s" by %s is licensed under %s.' % (r.get("title") or "untitled", r.get("creator") or "unknown", lic_text(r)),
                                     "duration_ms": d, "filetype": (r.get("filetype") or "mp3").lower()}
        out[role] = list(seen.values())[:90]
        print("%-8s +%3d new cc0/pdm candidates" % (role, len(out[role])), flush=True)
        save_reg(R_CAND_X, out)
    return out


# Root follow-up 26 Oct (thin-vs-pilots): roles that fall under 20 usable files get a wider cc0 / pdm harvest -> registry/sfx-candidates-extra2.json
SFX_EXTRA2 = {
    "tick": ["clock tick", "metronome", "switch click", "light switch", "button click", "mouse click", "tick tock", "click", "pen click", "latch"],
    "typing": ["keyboard", "mechanical key", "typing keys", "key press", "keypad", "computer keys", "typewriter", "type"],
}
R_CAND_X2 = os.path.join(REG, "sfx-candidates-extra2.json")


def harvest_extra2(roles=None, pace=3.6, pages=3):
    have = {c["openverse_id"] for p in (R_CAND, R_CAND_X) for r, v in load_reg(p).items() if r != "_meta" for c in v}
    out = load_reg(R_CAND_X2)
    for role, qs in SFX_EXTRA2.items():
        if roles and role not in roles:
            continue
        seen = {c["openverse_id"]: c for c in out.get(role, [])}
        for q in qs:
            for pg in range(1, pages + 1):
                try:
                    time.sleep(pace)
                    rs = ov_search("audio", q, page=pg, page_size=20, license="cc0,pdm")
                except RuntimeError as e:
                    print("  %s / %s p%d: %s" % (role, q, pg, str(e)[:80]))
                    break
                if not rs:
                    break
                for r in rs:
                    d = r.get("duration") or 0
                    if not (60 <= d <= 12000) or r["id"] in seen or r["id"] in have or lic_slug(r) not in ("cc0", "pdm"):
                        continue
                    seen[r["id"]] = {"openverse_id": r["id"], "role": role, "query": q, "title": r.get("title"), "source_url": r["url"], "landing_url": r.get("foreign_landing_url"),
                                     "provider": r.get("provider"), "licence_slug": lic_slug(r), "licence": lic_text(r), "licence_url": r.get("license_url"),
                                     "creator": r.get("creator"), "attribution": r.get("attribution") or '"%s" by %s is licensed under %s.' % (r.get("title") or "untitled", r.get("creator") or "unknown", lic_text(r)),
                                     "duration_ms": d, "filetype": (r.get("filetype") or "mp3").lower()}
            out[role] = list(seen.values())[:160]
            save_reg(R_CAND_X2, out)
        print("%-8s +%3d new cc0/pdm candidates" % (role, len(out.get(role, []))), flush=True)
    return out


# ------------------------------------------------------------------------------------------------ Wikimedia logos (through assets.py)
def fetch_logo(name, for_id=None, refresh=False):
    import assets as A
    r = A.resolve_logo(name, refresh=refresh)
    if not r.get("file"):
        return {"refused": r.get("refused", "no logo"), "name": name}
    path = os.path.join(ASSETS, r["file"])
    au = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", r.get("author") or "")).strip() or "Wikimedia Commons contributors"
    rec = {"kind": "logo", "name": name, "wikidata": r.get("wikidata"), "file": r["file"], "source_url": r.get("file_url"), "landing_url": r.get("commons"),
           "provider": "wikimedia-commons", "licence": r.get("licence"), "licence_url": r.get("licence_url"), "creator": au,
           "attribution": "Logo of %s: %s via Wikimedia Commons, %s. Trademark of its owner, shown for editorial identification only." % (name, au[:60], r.get("licence")),
           "sha256": sha256_file(path), "w": r.get("w"), "h": r.get("h"), "max_display_px": None, "use": LOGO_USE, "retrieved": r.get("retrieved") or now(),
           "restrictions": r.get("restrictions")}
    w, h = _dims(path)
    rec["file_w"], rec["file_h"] = w, h
    rec["max_display_px"] = w
    return register(R_IMG, "logo-" + slug(name), rec, for_id)


# ------------------------------------------------------------------------------------------------ queries for the engine
def logo_for(name, for_id=None):
    """the registered, verified logo record for a name, fetching it if needed; None when the name has no licensed logo (the engine then typesets a wordmark)."""
    try:
        r = fetch_logo(name, for_id)
    except Exception:
        return None
    return None if r.get("refused") else r


def sfx_for(kind, measured_only=True):
    """a registered cue of that kind whose onset has been measured (so it can be placed on an event); None otherwise (the engine uses sound/library.json ids).
    26 Oct 2026: earshot's code-made takes (MIT, no download, onset / peak / end measured by `earshot kit render`, registry/earshot-sfx.json) come first;
    the Openverse previews below keep onset_measured false (decoding is Actions-only), so they are only ever returned with measured_only=False."""
    sl = os.path.join(REG, "sfx-library.json")          # 26 Oct (Sam: "use the Openverse API"): the licensed, earshot-measured library, best role match first
    if os.path.exists(sl):
        try:
            d = json.load(open(sl))
            role = (d.get("kind_role") or {}).get(kind)
            cand = sorted([i for i in d["items"].values() if i["role"] == role and i["source_kind"] == "openverse" and i.get("onset_ms") is not None], key=lambda i: -i["role_match"]["z"])
            if cand:
                i, S = cand[0], cand[0]["source"]
                return {"kind": "sfx", "sfx_kind": kind, "id": i["id"], "file": "../sound/library/openverse/%s.wav" % i["id"], "provider": S["provider"], "licence": S["licence"], "licence_url": S["licence_url"],
                        "source_url": S["source_url"], "landing_url": S["landing_url"], "creator": S["creator"], "attribution": S["attribution"], "sha256": i["sha256"],
                        "sha256_source": i["sha256_source"], "duration_ms": round(i["duration_s"] * 1000), "onset_ms": i["onset_ms"], "peak_ms": i["peak_ms"], "end_ms": i["end_ms"],
                        "onset_measured": True, "anchor": i["anchor"], "anchor_ms": i["anchor_ms"], "role_match_z": i["role_match"]["z"]}
        except (OSError, ValueError, KeyError):
            pass
    es = os.path.join(REG, "earshot-sfx.json")
    if os.path.exists(es):
        try:
            d = json.load(open(es))
            ids = (d.get("kinds") or {}).get(kind) or []
            if ids and ids[0] in d["items"]:
                m = d["items"][ids[0]]
                return {"kind": "sfx", "sfx_kind": kind, "id": ids[0], "file": "../sound/library/earshot/%s.wav" % ids[0], "provider": "earshot", "licence": "MIT (earshot 0.4.0), made in code",
                        "sha256": m["sha256"], "duration_ms": round(m["duration_s"] * 1000), "onset_ms": m["onset_ms"], "peak_ms": m["peak_ms"], "end_ms": m["end_ms"],
                        "onset_measured": True, "anchor": m["anchor"], "anchor_ms": m["anchor_ms"]}
        except (OSError, ValueError, KeyError):
            pass
    for k, r in load_reg(R_SFX).items():
        if r.get("sfx_kind") == kind and (r.get("onset_measured") or not measured_only):
            return r
    return None


def images_for(query, for_id, n=1, **kw):
    try:
        return fetch_images(query, for_id, n=n, **kw)
    except Exception:
        return []


# ------------------------------------------------------------------------------------------------ verify
REQUIRED = ("file", "source_url", "licence", "attribution", "sha256", "landing_url")


def lic_good(lic):
    l = (lic or "").strip()
    if not l or re.search(r"\b(nd|nc|sampling)\b|no[- ]?deriv|non-?commercial|non-?free|fair use|unknown", l, re.I):
        return False
    return bool(re.match(r"^(cc0|cc[ -]?by|public domain|pdm|pd[- ]|ogl|open government)", l, re.I))


def check_record(key, r, base=ASSETS):
    bad = []
    for k in REQUIRED:
        if not r.get(k):
            bad.append("%s: missing %s" % (key, k))
    p = os.path.join(base, r.get("file", "x"))
    if not os.path.exists(p):
        bad.append("%s: file missing on disk (%s)" % (key, r.get("file")))
    elif r.get("sha256") and sha256_file(p) != r["sha256"]:
        bad.append("%s: sha256 does not match the file" % key)
    if r.get("licence") and not lic_good(r["licence"]):
        bad.append("%s: licence %r is not on the whitelist" % (key, r["licence"]))
    if r.get("kind") == "logo" and r.get("use") != LOGO_USE:
        bad.append("%s: a logo must carry use=%r" % (key, LOGO_USE))
    return bad


def verify():
    bad, n = [], 0
    for path in (R_IMG, R_SFX):
        for k, r in load_reg(path).items():
            n += 1
            bad += check_record(k, r)
    print("fetch_assets verify: %d records, %d problems" % (n, len(bad)))
    for b in bad:
        print("  FAIL", b)
    return 1 if bad else 0


def credits(ID):
    lines = []
    for path in (R_IMG, R_SFX):
        for k, r in load_reg(path).items():
            if ID in (r.get("used_by") or []):
                lines.append("%s | %s | %s | %s" % (r.get("kind"), r.get("attribution"), r.get("landing_url"), r.get("licence")))
    return lines


# ------------------------------------------------------------------------------------------------ selftest
LOGO_TRY = ["BBC", "Ofcom", "HMRC", "NatWest", "Tesco", "Sainsbury's", "Asda", "Barclays"]


def selftest():
    fails = []
    # 1. one real logo, licence recorded
    logo = None
    tried = []
    for nm in LOGO_TRY:
        try:
            r = fetch_logo(nm, for_id="SELFTEST")
        except Exception as e:                     # a network error on one name is not the end; the next name is tried
            tried.append("%s: %s" % (nm, e))
            continue
        if r.get("refused"):
            tried.append("%s: %s" % (nm, r["refused"]))
            continue
        logo = r
        break
    if not logo:
        fails.append("no logo fetched (tried: %s)" % "; ".join(tried))
    else:
        bad = check_record("logo-" + slug(logo["name"]), logo)
        if bad:
            fails += bad
        if not logo.get("licence") or logo.get("use") != LOGO_USE:
            fails.append("logo licence/use not recorded")
        print("SELFTEST logo   : %s | %s | %s | sha256 %s | %s" % (logo["name"], logo["licence"], logo["landing_url"], logo["sha256"][:16], logo["use"]))
    # 2. one real whoosh SFX, licence recorded
    sfx = None
    try:
        sfx = fetch_sfx("whoosh", kind="whoosh", for_id="SELFTEST")
    except Exception as e:
        fails.append("sfx fetch error: %s" % e)
    if not sfx:
        fails.append("no whoosh SFX fetched")
    else:
        bad = check_record("sfx", sfx)
        if bad:
            fails += bad
        if sfx.get("onset_measured") is not False or sfx.get("onset_ms") is not None:
            fails.append("sfx onset must be unmeasured until Actions measures it")
        print("SELFTEST whoosh : %s | %s | %s | %s ms | sha256 %s" % (sfx["title"], sfx["licence"], sfx["landing_url"], sfx["duration_ms"], sfx["sha256"][:16]))
        print("                  attribution: %s" % sfx["attribution"])
    # 3. the verifier can fail: a copy of each record with its licence blanked, then with a wrong sha256, must be refused
    for name, rec in (("logo", logo), ("sfx", sfx)):
        if not rec:
            continue
        a = check_record(name, dict(rec, licence=""))
        b = check_record(name, dict(rec, sha256="0" * 64))
        c = check_record(name, dict(rec, licence="CC BY-NC 4.0"))
        if not (a and b and c):
            fails.append("%s: verifier accepted a bad record (blank licence %s, wrong sha %s, NC licence %s)" % (name, bool(a), bool(b), bool(c)))
        else:
            print("SELFTEST can-fail (%s): blank licence, wrong sha256 and an NC licence are each refused" % name)
    if fails:
        print("SELFTEST FAIL")
        for f in fails:
            print("  -", f)
        return 1
    print("SELFTEST PASS: 1 licensed logo + 1 licensed whoosh registered; verify() can fail")
    return 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("logo"); a.add_argument("name"); a.add_argument("--for", dest="for_id"); a.add_argument("--refresh", action="store_true")
    a = sub.add_parser("image"); a.add_argument("query"); a.add_argument("--for", dest="for_id"); a.add_argument("--n", type=int, default=3)
    a.add_argument("--min-w", type=int, default=700); a.add_argument("--orientation"); a.add_argument("--category")
    x2 = sub.add_parser("sfx-harvest-extra2"); x2.add_argument("--roles", nargs="*")
    x = sub.add_parser("sfx-harvest-extra"); x.add_argument("--roles", nargs="*")
    h = sub.add_parser("sfx-harvest"); h.add_argument("--roles", nargs="*"); h.add_argument("--pages", type=int, default=2)
    a = sub.add_parser("sfx"); a.add_argument("query"); a.add_argument("--kind", default="sfx"); a.add_argument("--for", dest="for_id"); a.add_argument("--max-ms", type=int, default=4000)
    sub.add_parser("verify"); sub.add_parser("list")
    a = sub.add_parser("credits"); a.add_argument("id")
    ns = ap.parse_args()
    if ns.cmd == "logo":
        r = fetch_logo(ns.name, ns.for_id, ns.refresh)
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 1 if r.get("refused") else 0
    if ns.cmd == "image":
        rs = fetch_images(ns.query, ns.for_id, ns.n, ns.min_w, ns.orientation, ns.category)
        for r in rs:
            print("%-28s %4sx%-4s %s | %s | %s" % (r["file"], r["w"], r["h"], r["licence"], r["creator"], r["landing_url"]))
        return 0 if rs else 1
    if ns.cmd == "sfx-harvest-extra2":
        harvest_extra2(ns.roles)
        return 0
    if ns.cmd == "sfx-harvest-extra":
        harvest_extra(ns.roles)
        return 0
    if ns.cmd == "sfx-harvest":
        harvest_sfx(ns.roles, ns.pages)
        return 0
    if ns.cmd == "sfx":
        r = fetch_sfx(ns.query, ns.kind, ns.for_id, ns.max_ms)
        print(json.dumps(r, indent=1, ensure_ascii=False) if r else "no sfx found")
        return 0 if r else 1
    if ns.cmd == "verify":
        return verify()
    if ns.cmd == "list":
        for p in (R_IMG, R_SFX):
            for k, r in load_reg(p).items():
                print("%-26s %-5s %-22s %s" % (k, r.get("kind"), r.get("licence"), r.get("file")))
        return 0
    if ns.cmd == "credits":
        print("\n".join(credits(ns.id)))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
