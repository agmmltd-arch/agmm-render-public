#!/usr/bin/env python3
"""compose.py v2 (29 Sep 2026, round 2): compile a declarative specs/<ID>/beats.json into specs/<ID>/spec.json +
specs/<ID>/scenes.js for the unchanged pipeline (build_short.py -> snap.py / storyboard.py / produce.py).

A free model chooses and fills proven parts (kit/lib/parts/parts.js, CATALOGUE.md); it never writes animation code.
This compiler lays everything out itself and REFUSES what it cannot make good. v1 is kept as compose.py.bak-2026-09-29-v1.

Usage:
  compose.py specs/<ID>/beats.json            validate, lay out, write spec.json + scenes.js, print the report
  compose.py specs/<ID>/beats.json --check    validate + lay out only (writes nothing)
  compose.py specs/<ID>/beats.json --stage    also copy the source crops the short uses into out/<ID>/img/
  compose.py specs/<ID>/beats.json --json     print the report as JSON (for tools/lane_short.py)
  compose.py --plan plan.json --voice shorts/voice/<ID> [--sources ...]   validate a lane's beat plan (plan-then-fill)

Layout rules the model cannot break (root, 29 Sep round 2):
  - text measured with the kit's own font files (PIL; within 1% of Chrome), laid out inside the ROUTED platform's text
    safe rect and clear of its notches (kit/platforms/frames.json via platforms.for_short; AGP.SAFE as the fallback);
  - every camera key is simulated and every word in the world (board cells, stamped or flipped text) is checked in its
    FINAL transformed box; overlay boxes include their persistent motion (breathe, float, rotation);
  - headlines are >= 110 px (a long line is broken once at the best word, then it fails);
  - on every beat the world, the clip, the cards and the events fill >= 55% of the frame (raster of the final boxes);
  - a card or stat shows its value from its first frame (the card lands on its slam word);
  - nothing on screen is a number the voice, the script's fact ledger and the sources do not contain;
  - a clip marks only phrases that exist on its crop (tools/sources_from_media.py lists them);
  - more than 6 s with nothing new is refused; frame 0 must show the number; the CTA says what the voice says;
  - NOVELTY (replaces the catalogue/code-hash rules for compiled shorts; build_short.py calls novelty_gate): at least
    one signature event; no lead part on more than 35% of beats; look + world + signature events must not repeat two of
    three against any of the last 3 shorts armed or posted on the same platform (auto-poster video plans).
"""
import argparse, glob, json, math, os, re, shutil, sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2 = os.path.dirname(KIT)
LIB = os.path.join(KIT, "lib")
sys.path.insert(0, KIT)
import build_short as BS   # noqa: E402  (Resolver, load_words, ffdur, pan_of, norm: the build's own clock)

PARTS_JS = os.path.join(LIB, "parts", "parts.js")
PLANS_GLOB = os.path.expanduser("~/alfred/auto-poster/carousel_v3/runtime/video-plan-*.json")
KIT3_LOOK = {"paper": "explainer", "night": "cinematic", "blueprint": "chart", "leather": "evidence"}
FALLBACK_FRAME = {"platform": "fallback (AGP.SAFE)", "SAFE": {"x0": 90, "y0": 250, "x1": 990, "y1": 1600},
                  "NOTCHES": [{"x0": 950, "y0": 1050, "x1": 1080, "y1": 1750, "name": "right action rail"}]}
BANNED = ["—", "–", "·", "link in bio", "free audit", "fictional", "illustrative", "ai-generated"]
TOP_KINDS = ["kicker", "headline", "note", "progress", "chip", "tags", "checklist"]
MID_KINDS = ["stat", "contrast", "chain", "tally"]
FLOAT_KINDS = ["calendar", "clock", "pad", "meter", "monitor", "stamp"]
ALL_KINDS = TOP_KINDS + MID_KINDS + FLOAT_KINDS + ["clip", "cta"]
ACTIONS = ["state", "mark", "flap", "valves", "lines", "blink", "event", "reading", "run", "tickets", "address", "post"]
# the world bank (root, 29 Sep round 3): bespoke worlds from approved shorts, by name
WORLD_ALIAS = {"pipes": {"type": "grid", "glyph": "tap", "feed": "pipe"},              # S44
               "screens": {"type": "grid", "glyph": "screen"},                            # S52
               "departures": {"type": "board"},                                          # S52
               "floorplan": {"type": "grid", "glyph": "seat", "feed": "plan"},          # S59
               "pinmap": {"type": "grid", "glyph": "pin", "feed": "map", "rows": 1}}    # C37
UKMAP = os.path.join(KIT, "specs", "C37", "ukmap.js")
EVENTS = ["spray", "burst", "bolt", "seal", "stamp", "crack", "fill", "drain", "flip", "pour", "cut", "send", "flyoff", "stack", "topple"]
PUSH, HERO_MIN, FILL_MIN, LEAD_MAX, GAP_MAX = 1.04, 140, 0.55, 0.35, 6.0
PLAN_HERO = 150          # a plan headline must fit at >= 150 px (root round 3: pilots run 150-250)
GLYPH = {"tap": (60, 50, 92, 64), "screen": (200, 150, 216, 186), "pc": (170, 124, 216, 186), "person": (90, 110, 112, 132),
         "doc": (90, 116, 114, 140), "coin": (84, 52, 100, 70), "block": (36, 54, 48, 68), "desk": (170, 120, 200, 150),
         "pin": (50, 72, 72, 92), "ticket": (150, 80, 172, 100), "box": (90, 90, 112, 112), "seat": (64, 58, 96, 86)}
FLOAT_SIZE = {"calendar": (350, 290), "clock": (260, 260), "pad": (480, 520), "meter": (460, 250), "monitor": (520, 390)}
FONTS = {   # file, variable weight, letter-spacing (em), uppercase; the same faces kit.css / kit2.css load
    "paper": {"hero": ("ds/fonts/spacegrotesk-var.woff2", 700, -0.035, True), "mono": ("ds/fonts/plexmono-600-normal.woff2", None, 0.05, True), "hand": ("ds/fonts/kalam-700-normal.woff2", None, 0, False)},
    "night": {"hero": ("ds/fonts/anton-400-normal.woff2", None, 0, True), "mono": ("ds2/fonts/GeistMono-Bold.ttf", None, 0.05, True), "hand": ("ds2/fonts/NothingYouCouldDo-Regular.ttf", None, 0, False)},
    "blueprint": {"hero": ("ds2/fonts/BricolageGrotesque-Bold.ttf", None, -0.02, True), "mono": ("ds2/fonts/JetBrainsMono-Bold.ttf", None, 0.05, True), "hand": ("ds2/fonts/NothingYouCouldDo-Regular.ttf", None, 0, False)},
    "leather": {"hero": ("ds2/fonts/YoungSerif-Regular.ttf", None, -0.01, False), "mono": ("ds2/fonts/RedHatMono-Bold.ttf", None, 0.05, True), "hand": ("ds2/fonts/NothingYouCouldDo-Regular.ttf", None, 0, False)},
}
NUMWORD = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
           "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13", "fifteen": "15", "twenty": "20", "thirty": "30",
           "forty": "40", "fifty": "50", "hundred": "100", "half": "50", "tripled": "3"}


class Fail(Exception):
    pass


# ------------------------------------------------------------------ text
_FC = {}


def _font(path, size, weight):
    from PIL import ImageFont
    k = (path, int(size), weight)
    if k not in _FC:
        f = ImageFont.truetype(os.path.join(LIB, path), int(size))
        if weight:
            try:
                f.set_variation_by_axes([weight])
            except Exception:
                pass
        _FC[k] = f
    return _FC[k]


def plain(s):
    return re.sub(r"\[/?[argmo]\]", "", str(s))


def lines_of(s):
    return plain(s).split("\n")


def text_w(look, face, text, size, ls=None):
    """rendered width in px of the widest line (CSS letter-spacing counted per glyph, as Chrome does), +2%."""
    f, wt, ls0, up = FONTS[look][face]
    ls = ls0 if ls is None else ls
    F = _font(f, size, wt)
    return max((F.getlength(l.upper() if up else l) + ls * size * len(l)) for l in lines_of(text)) * 1.02


def fit_px(look, face, text, maxw, want, ls=None):
    w = text_w(look, face, text, want, ls)
    return want if w <= maxw else int(want * maxw / w)


def numbers_in(t):
    return [re.sub(r"[,]", "", m).rstrip(".") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", str(t))]


def claims_in(t):
    """numbers that assert something: a percentage, money, a decimal, or 100 and over (clock times and small labels on a
    labelled illustration are micro-detail and not checked)."""
    t = re.sub(r"\b\d{1,2}:\d{2}\b", " ", str(t))
    out = []
    for m in re.finditer(r"([£$€])?(\d[\d,]*(?:\.\d+)?)\s*(%|bn|m\b|million|billion)?", t):
        n = m.group(2).replace(",", "").rstrip(".")
        try:
            v = float(n)
        except ValueError:
            continue
        if m.group(1) or m.group(3) or "." in n or v >= 100:
            out.append(n)
    return out


def num_words(t):
    return [NUMWORD[w] for w in re.findall(r"[a-z-]+", str(t).lower()) if w in NUMWORD]


# ------------------------------------------------------------------ platform frame
def load_frame(route_id):
    """the routed platform's text-safe rect and notches (kit/platforms/frames.json); AGP.SAFE + the rail as fallback."""
    try:
        sys.path.insert(0, os.path.join(KIT, "platforms"))
        import platforms as PF
        p = PF.for_short(route_id) if route_id else None
        if p and p.get("text_safe"):
            ts = p["text_safe"]
            return {"platform": p.get("key") or "?", "SAFE": {k: ts[k] for k in ("x0", "y0", "x1", "y1")},
                    "NOTCHES": [{k: n[k] for k in ("x0", "y0", "x1", "y1")} for n in ts.get("notches", [])],
                    "evidence": ts.get("evidence"), "route": PF.routed_platform(route_id)}
    except Exception as e:   # the framing worker's module is optional; say so, never guess
        print("compose: platform frames unavailable (%s); using AGP.SAFE" % e, file=sys.stderr)
    return dict(FALLBACK_FRAME, route=None)


def right_limit(FR, y0, y1):
    x1 = FR["SAFE"]["x1"]
    for n in FR["NOTCHES"]:
        if y1 > n["y0"] and y0 < n["y1"]:
            x1 = min(x1, n["x0"])
    return x1


def safe_problem(FR, b):
    """why a text box (x0,y0,x1,y1) is not safe, or None."""
    S = FR["SAFE"]
    x0, y0, x1, y1 = b
    if x1 <= 0 or x0 >= 1080 or y1 <= 0 or y0 >= 1920:
        return None                     # wholly off frame: never seen, never cut
    if x0 < S["x0"] - 1 or y0 < S["y0"] - 1 or x1 > S["x1"] + 1 or y1 > S["y1"] + 1:
        return "leaves the %s text-safe area (x %d-%d, y %d-%d)" % (FR["platform"], S["x0"], S["x1"], S["y0"], S["y1"])
    for n in FR["NOTCHES"]:
        if x1 > n["x0"] + 1 and y1 > n["y0"] and y0 < n["y1"]:
            return "runs under the %s notch (x > %d for y %d-%d)" % (FR["platform"], n["x0"], n["y0"], n["y1"])
    return None


# ------------------------------------------------------------------ sources
def load_sources(path):
    p = path if os.path.isabs(path) else os.path.join(V2, path)
    t = open(p).read()
    d = json.loads(t[t.index("{"):t.rindex("}") + 1])
    return d.get("items", d), p


def find_image(src_file, rel):
    sid = os.path.basename(os.path.dirname(src_file))
    name = os.path.basename(rel)
    cands = [os.path.join(KIT, "out", sid, "img", name), os.path.join(os.path.dirname(src_file), "media", re.sub(r"^real-[a-z0-9]+-", "", name)),
             os.path.join(os.path.dirname(src_file), "media", name)]
    for k, v in {"delta_logo": "delta-logo", "cs_logo": "crowdstrike-logo"}.items():
        if k in name:
            cands.append(os.path.join(os.path.dirname(src_file), "media", v + ".png"))
    return next((c for c in cands if os.path.exists(c)), None)


# ------------------------------------------------------------------ stations
def reshape(cols, rows, aspect):
    """cols x rows re-cut to the factorisation of the same count whose shape (w/h) is nearest `aspect`."""
    n, best = cols * rows, (cols, rows)
    for c in range(1, n + 1):
        if n % c == 0:
            r = n // c
            if abs(math.log((c / r) / aspect)) < abs(math.log((best[0] / best[1]) / aspect)):
                best = (c, r)
    return best


def gb_outline(w_target=900.0):
    """C37's own Great Britain outline, decimated and scaled: (path d, polygon of the mainland) in station px."""
    t = open(UKMAP).read(); d = json.loads(t[t.index("{"):t.rindex("}") + 1])
    subs = [list(map(float, re.findall(r"-?[\d.]+", x))) for x in re.findall(r"M[^M]+", d["gb"])]
    polys = [[(p[i], p[i + 1]) for i in range(0, len(p) - 1, 2)] for p in subs if len(p) >= 40]
    allp = [q for P in polys for q in P]
    x0, x1 = min(a for a, b in allp), max(a for a, b in allp); y0 = min(b for a, b in allp)
    k = w_target / (x1 - x0)
    main_i = max(range(len(polys)), key=lambda i: len(polys[i]))          # the mainland, chosen before decimating
    polys = [[((a - x0) * k + 60, (b - y0) * k + 60) for a, b in P[::max(1, len(P) // 400)]] for P in polys]
    path = " ".join("M" + " L".join("%.1f %.1f" % q for q in P) + " Z" for P in polys)
    return path, polys[main_i], polys


def inside(pt, poly):
    x, y, c = pt[0], pt[1], False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-9) + x1:
            c = not c
    return c


def lay_station(st, errs, warns, sources, uses_rowcol, look):
    if st.get("type") in WORLD_ALIAS:
        st = dict(WORLD_ALIAS[st["type"]], **{k: v for k, v in st.items() if k != "type"})
    t = st.get("type")
    sid = st.get("id")
    if t == "ticketline":   # S39: dispenser + conveyor + tray + desk
        return {"type": "ticketline", "w": 1080, "h": 1260, "reading": st.get("reading", ""), "plate": st.get("plate", "TAKE A TICKET"),
                "tray": st.get("tray", "DONE"), "desk": st.get("desk", "A PERSON"), "ticket": st.get("ticket", "No. 000"),
                "stamp": st.get("stamp", "DONE"), "label": st.get("label", "ILLUSTRATION"), "cols_n": 1, "rows_n": 1}
    if t == "mailroom":     # S53: envelopes + brass tray
        names = st.get("names") or []
        if not 2 <= len(names) <= 8:
            errs.append("world %s: a mailroom holds 2 to 8 envelopes (names)" % sid)
        rows = (len(names) + 1) // 2
        return {"type": "mailroom", "w": 1040, "h": 60 + rows * 290 + 320, "names": names, "address": st.get("address", "TO"),
                "postmark": st.get("postmark", "FIRST\nCLASS"), "tray": st.get("tray", "OUTGOING MAIL"), "label": st.get("label", "ILLUSTRATION"), "cols_n": 1, "rows_n": 1}
    if t == "grid":
        g = st.get("glyph", "block")
        if g not in GLYPH:
            errs.append("world %s: glyph %r is not one of %s" % (sid, g, sorted(GLYPH))); g = "block"
        uw, uh, px, py = GLYPH[g]
        cols, rows = int(st.get("cols", 10)), int(st.get("rows", 10))
        if cols * rows > 400:
            errs.append("world %s: %d units is too many (max 400)" % (sid, cols * rows))
        feed = st.get("feed", "none")
        # a grid should match the portrait frame; re-cut it when no action depends on its rows/cols
        shape = (cols * px) / (rows * py)
        cols0 = cols
        if not uses_rowcol and feed not in ("map",) and (shape > 1.2 or shape < 0.45) and cols * rows > 3:
            c2, r2 = reshape(cols, rows, 0.8 * py / px)
            if (c2, r2) != (cols, rows):
                warns.append("world %s: %d x %d re-cut to %d x %d so it fills the portrait frame (same %d units, same order; [col, row] points follow their unit)" % (sid, cols, rows, c2, r2, cols * rows))
                cols, rows = c2, r2
        out = {"type": "grid", "glyph": g, "uw": uw, "uh": uh, "cols_n": cols, "rows_n": rows, "cols_orig": cols0, "feed": feed,
               "initial": st.get("initial", "idle"), "label": st.get("label"), "pop": st.get("pop", True)}
        if feed == "map":
            n = cols * rows
            path, poly, allp = gb_outline()
            xs = [a for P in allp for a, b in P]; ys = [b for P in allp for a, b in P]
            W_, H_ = max(xs) + 60, max(ys) + 60
            pts, k = [], 0
            step = math.sqrt((W_ * H_ * 0.22) / max(1, n))
            while len(pts) < n and k < 20000:     # a seeded jittered lattice inside the mainland
                gx = (k * 0.6180339887 % 1.0) * W_; gy = ((k * 0.7548776662) % 1.0) * H_
                if inside((gx, gy), poly) and all((gx - a) ** 2 + (gy - b) ** 2 > (step * 0.55) ** 2 for a, b in pts):
                    pts.append((round(gx, 1), round(gy, 1)))
                k += 1
            pts.sort(key=lambda q: (q[1], q[0]))
            out.update({"cols_n": len(pts), "rows_n": 1, "pts": pts, "path": path, "w": int(W_), "h": int(H_), "colX": [p[0] for p in pts], "rowY": [0]})
            if len(pts) < n:
                warns.append("world %s: only %d pins fit on the map (asked %d)" % (sid, len(pts), n))
            return out
        if feed == "plan":
            out["room"] = st.get("room")
            out["colX"] = [70 + uw / 2 + c * px for c in range(cols)]
            out["rowY"] = [110 + uh / 2 + r * py for r in range(rows)]
            out["w"], out["h"] = int(out["colX"][-1] + uw / 2 + 110), int(out["rowY"][-1] + uh / 2 + 70)
            return out
        if feed == "pipe":
            out["feedY"] = 30
            out["colX"] = [36 + c * px for c in range(cols)]
            out["rowY"] = [30 + 68 + r * py for r in range(rows)]
            out["w"], out["h"] = out["colX"][-1] + 90, out["rowY"][-1] + 46
        elif feed == "fan":
            sw, sh = 700, 280
            gridw = (cols - 1) * px + uw
            out["w"] = max(gridw, sw)
            ox = (out["w"] - gridw) / 2
            out["colX"] = [ox + uw / 2 + c * px for c in range(cols)]
            out["rowY"] = [sh + 140 + uh / 2 + r * py for r in range(rows)]
            out["h"] = out["rowY"][-1] + uh / 2 + 10
            out.update({"srcX": (out["w"] - sw) / 2, "srcY": 0, "srcW": sw, "srcH": sh, "source": st.get("source", "UPDATE"), "sourceLabel": st.get("sourceLabel", "ILLUSTRATION")})
        else:
            out["colX"] = [uw / 2 + c * px for c in range(cols)]
            out["rowY"] = [uh / 2 + r * py for r in range(rows)]
            out["w"], out["h"] = (cols - 1) * px + uw, (rows - 1) * py + uh
        return out
    if t == "board":
        cols = st.get("columns") or ["TIME", "NAME", "STATUS"]
        rows = st.get("rows") or []
        if not rows:
            errs.append("world %s: a board needs rows" % sid)
        if len(rows) > 7:
            errs.append("world %s: %d rows; a board holds at most 7 (its text must read at 42 px on a phone)" % (sid, len(rows)))
        for r in rows:
            if len(r) != len(cols):
                errs.append("world %s: row %r has %d cells for %d columns" % (sid, r, len(r), len(cols)))
            for c in r:
                if isinstance(c, dict) and c.get("logo") and c["logo"] not in sources:
                    errs.append("world %s: logo %r not in the sources file" % (sid, c["logo"]))
                if isinstance(c, str) and re.fullmatch(r"[-_. ]+", c.strip() or "-"):
                    errs.append("world %s: placeholder cell %r; every cell says something real" % (sid, c))
        fpx, rowh, cellh = 60, 132, 96
        want = []
        for ci in range(len(cols)):
            m = max([text_w(look, "mono", str(cols[ci]), 44, 0.06)] + [(360 if isinstance(r[ci], dict) else text_w(look, "mono", str(r[ci]), fpx, 0.06) + 34) for r in rows if ci < len(r)])
            want.append(m)
        PAD = 320                               # the board's own panel runs past its words: it may bleed, they may not
        colsX, x = [], 40 + PAD
        for w in want:
            colsX.append(x); x += int(w) + 18
        tw = x + 22 - PAD
        return {"type": "board", "title": st.get("title", "BOARD"), "columns": cols, "rows": rows, "tones": st.get("tones"),
                "label": st.get("label", "ILLUSTRATION"), "colsX": colsX, "colsW": [int(w) + 4 for w in want], "w": tw + 2 * PAD,
                "h": 190 + len(rows) * rowh + 90 + 700 + 1000, "rowH": rowh, "cellH": cellh, "fontPx": fpx, "padX": PAD, "padTop": 700,
                "textW": tw, "textH": 190 + len(rows) * rowh + 90}
    errs.append("world %s: type %r is not grid or board" % (sid, t))
    return None


def remap(s, c, r):
    """a [col, row] the lane wrote for its own grid shape, moved to the same unit of the re-cut grid."""
    if s.get("cols_orig") and s["cols_orig"] != s.get("cols_n"):
        idx = int(r) * s["cols_orig"] + int(c)
        return idx % s["cols_n"], idx // s["cols_n"] + (r - int(r))
    return c, r


def unit_center(s, c, r):
    if s["type"] in ("ticketline", "mailroom"):
        return s["x"] + s["w"] / 2, s["y"] + s["h"] / 2
    c, r = remap(s, c, r)
    c = max(0, min(s.get("cols_n", 1) - 1, int(c))); r = max(0, min(s.get("rows_n", len(s.get("rows", [0]))) - 1, int(r)))
    if s["type"] == "grid" and s.get("pts"):
        p_ = s["pts"][max(0, min(len(s["pts"]) - 1, int(r) * s["cols_n"] + int(c)))]
        return s["x"] + p_[0], s["y"] + p_[1] - s["uh"] / 2
    if s["type"] in ("ticketline", "mailroom"):
        return s["x"] + s["w"] / 2, s["y"] + s["h"] / 2
    if s["type"] == "grid":
        if s["feed"] == "pipe":
            return s["x"] + s["colX"][c] + 10 + s["uw"] / 2, s["y"] + s["rowY"][r] - 14 + s["uh"] / 2
        return s["x"] + s["colX"][c], s["y"] + s["rowY"][r]
    return s["x"] + s["colsX"][min(c, len(s["colsX"]) - 1)] + s["colsW"][min(c, len(s["colsW"]) - 1)] / 2, s["y"] + s["padTop"] + 190 + r * s["rowH"] + s["cellH"] / 2


def point_of(s, p):
    """a point on a station, in world px: {"unit": [c, r]}, {"pipe": [c, r]} (on the drop pipe, between rows r and r+1),
    {"row": r}, [fx, fy] (fractions), or None (the centre); plus optional "dx"/"dy" px."""
    dx = dy = 0
    if isinstance(p, dict):
        dx, dy = p.get("dx", 0), p.get("dy", 0)
        if "unit" in p:
            x, y = unit_center(s, *p["unit"])
        elif "pipe" in p and s["type"] == "grid" and s["feed"] == "pipe":
            c, r = remap(s, int(p["pipe"][0]), float(p["pipe"][1])); c = int(c)
            c = max(0, min(s["cols_n"] - 1, c)); r0 = max(0, min(s["rows_n"] - 1, int(r)))
            x = s["x"] + s["colX"][c]
            y = s["y"] + s["rowY"][r0] + (r - r0) * (s["rowY"][1] - s["rowY"][0] if s["rows_n"] > 1 else 64)
        elif "row" in p:
            x, y = unit_center(s, 0, p["row"]); x = s["x"] + s["w"] / 2
        else:
            x, y = s["x"] + s["w"] / 2, s["y"] + s["h"] / 2
    elif isinstance(p, (list, tuple)) and len(p) == 2:
        x, y = s["x"] + s["w"] * float(p[0]), s["y"] + s["h"] * float(p[1])
    else:
        x, y = s["x"] + s["w"] / 2, s["y"] + s["h"] / 2
    return x + dx, y + dy


def pick_units(s, sel):
    n = s["cols_n"] * s["rows_n"]
    U = [(i % s["cols_n"], i // s["cols_n"]) for i in range(n)]
    sel = sel or {"all": True}
    if "units" in sel:
        out = [U[i] for i in sel["units"] if 0 <= i < n]
    elif "rows" in sel:
        out = [u for u in U if u[1] in sel["rows"]]
    elif "cols" in sel:
        out = [u for u in U if u[0] in sel["cols"]]
    elif "first" in sel:
        out = U[:sel["first"]]
    elif "last" in sel:
        out = U[n - sel["last"]:]
    elif "spread" in sel:
        out = [U[int((k + 0.5) * n / sel["spread"])] for k in range(sel["spread"])]
    else:
        out = list(U)
    if "except" in sel:
        ex = set(pick_units(s, sel["except"]))
        out = [u for u in out if u not in ex]
    return out


def order_units(lst, order, s):
    if order == "cols":
        return sorted(lst, key=lambda u: (u[0], u[1]))
    if order == "diag":
        return sorted(lst, key=lambda u: (u[0] + u[1], u[1]))
    if order == "centre":
        cc, cr = (s["cols_n"] - 1) / 2, (s["rows_n"] - 1) / 2
        return sorted(lst, key=lambda u: abs(u[0] - cc) + abs(u[1] - cr))
    return lst


# ------------------------------------------------------------------ camera
def frame_station(s, window, focus, zoom, bleed, aim_y=None):
    """camera key {x, y, s} that frames station s into window [x0,y0,x1,y1]. bleed (grids): fill the window, cropping
    up to 30% of the station; a board (words) is always contained. The focus slides inward so no bare wall shows.
    aim_y (opus-c1, 29 Sep): the screen y a FOCUS point lands on. A bleeding grid's window runs to the frame bottom,
    so its centre (y ~1290) sits under Facebook/Instagram's caption zone; the caller aims the focus at the middle of
    the text-safe band instead, so an event on the focused unit is readable and passes the safe check."""
    wx0, wy0, wx1, wy1 = window
    ww, wh = wx1 - wx0, wy1 - wy0
    if s["type"] == "board":                 # a board frames its WORDS into the window; its panel bleeds past it
        sc = min(ww / s["textW"], wh / s["textH"])
        fx, fy = s["x"] + s["padX"] + s["textW"] / 2, s["y"] + s["padTop"] + s["textH"] / 2
        cx, cy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
        return {"x": round(cx - fx * sc, 1), "y": round(cy - fy * sc, 1), "s": round(sc, 4), "fx": fx, "fy": fy, "cx": cx, "cy": cy}
    contain = min(ww / s["w"], wh / s["h"])
    cover = max(ww / s["w"], wh / s["h"])
    sc = contain * (min(1.5, cover / contain) if bleed else 1.0) * (zoom or 1.0)
    if s["type"] in ("board", "ticketline", "mailroom") or s.get("feed") == "plan":
        # CLOSE-UP (opus-c1, 29 Sep): zoom > 1 on a contained world moves the camera IN (one envelope, the LED) and
        # lets the set bleed past the window; its words are still checked at every camera key (safe_problem: each
        # word is wholly off frame or wholly in the text-safe rect). Without this, on a short safe band (Facebook
        # Reels y 293-1224) a mailroom or ticketline could never reach the fill floor under a 2-line headline.
        sc = min(sc, contain * max(1.0, zoom or 1.0))
    fx, fy = focus if focus else (s["x"] + s["w"] / 2, s["y"] + s["h"] / 2)
    if s["w"] * sc > ww:
        fx = min(max(fx, s["x"] + (ww / 2) / sc), s["x"] + s["w"] - (ww / 2) / sc)
    else:
        fx = s["x"] + s["w"] / 2
    cx, cy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
    if focus and aim_y is not None and wy0 < aim_y < wy1:
        cy = aim_y
    if s["h"] * sc > wh:
        fy = min(max(fy, s["y"] + (cy - wy0) / sc), s["y"] + s["h"] - (wy1 - cy) / sc)
    else:
        fy = s["y"] + s["h"] / 2
    return {"x": round(cx - fx * sc, 1), "y": round(cy - fy * sc, 1), "s": round(sc, 4), "fx": fx, "fy": fy, "cx": cx, "cy": cy}


def to_screen(k, box):
    x0, y0, x1, y1 = box
    return (k["x"] + x0 * k["s"], k["y"] + y0 * k["s"], k["x"] + x1 * k["s"], k["y"] + y1 * k["s"])


def world_text_boxes(s, look):
    """every word a station carries, in world px."""
    out = []
    if s["type"] == "board":
        T0 = s["y"] + s["padTop"]
        lw = text_w(look, "mono", s.get("label") or "", 44, 0.08)
        LY = T0 + 190 + len(s["rows"]) * s["rowH"] - 6
        out.append(("board label", (s["x"] + s["padX"] + 40, LY, s["x"] + s["padX"] + 40 + lw, LY + 52)))
        out.append(("board title %r" % s["title"], (s["x"] + s["padX"] + 40, T0 + 28, s["x"] + s["padX"] + 40 + text_w(look, "mono", s["title"], 58, 0.14), T0 + 98)))
        for ci, c in enumerate(s["columns"]):
            out.append(("board column %r" % c, (s["x"] + s["colsX"][ci], T0 + 118, s["x"] + s["colsX"][ci] + text_w(look, "mono", str(c), 44, 0.06), T0 + 170)))
        for ri in range(len(s["rows"])):
            for ci in range(len(s["columns"])):
                y = T0 + 190 + ri * s["rowH"]
                out.append(("board cell r%d c%d" % (ri, ci), (s["x"] + s["colsX"][ci] - 10, y, s["x"] + s["colsX"][ci] - 10 + s["colsW"][ci], y + s["cellH"])))
    elif s["type"] == "ticketline":
        out += [("machine LED", (s["x"] + 304, s["y"] + 116, s["x"] + 776, s["y"] + 306)), ("machine plate", (s["x"] + 350, s["y"] + 352, s["x"] + 730, s["y"] + 420)),
                ("tray label", (s["x"] + 640, s["y"] + 1070, s["x"] + 1020, s["y"] + 1130)), ("desk label", (s["x"] + 50, s["y"] + 1070, s["x"] + 360, s["y"] + 1130)),
                ("ILLUSTRATION label", (s["x"] + 40, s["y"] + 8, s["x"] + 40 + text_w(look, "mono", s.get("label") or "", 44, 0.08), s["y"] + 58))]
    elif s["type"] == "mailroom":
        for i, n in enumerate(s["names"]):
            x, y = s["x"] + 40 + (i % 2) * 500, s["y"] + 60 + (i // 2) * 290
            out.append(("envelope %r" % n, (x + 20, y + 100, x + 440, y + 240)))
        out.append(("mail tray", (s["x"] + 90, s["y"] + s["h"] - 250, s["x"] + s["w"] - 90, s["y"] + s["h"] - 80)))
    elif s.get("feed") == "plan" and s.get("room"):
        out.append(("room label", (s["x"] + 36, s["y"] + 30, s["x"] + 36 + text_w(look, "mono", s["room"], 40, 0.08), s["y"] + 80)))
    elif s.get("feed") == "fan":
        out.append(("source box %r" % s.get("source"), (s["x"] + s["srcX"], s["y"], s["x"] + s["srcX"] + s["srcW"], s["y"] + s["srcH"])))
    return out


# ------------------------------------------------------------------ sfx
class Cues:
    """foley ids rotate through the ones the approved shorts used (their onsets are proven by the gate)."""
    PROVEN = {"impact_heavy": ["01", "02", "03", "05", "06", "07"], "cash_register_coins": ["01", "02", "03", "04"],
              "whoosh_air": ["01", "02", "03", "04", "05"], "paper_page": ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10"],
              "foley_stamp": ["01", "02", "03", "04", "05", "06"], "swoosh_transition": ["01", "02", "03"],
              "foley_paper": ["01", "02", "03", "04", "05", "06", "07", "08", "09"], "ui_pop": ["01", "02", "03", "04"],
              "foley_click": ["01", "02", "03", "04", "05", "06"], "impact_soft": ["01", "02", "03", "04", "05", "06", "07", "08", "09"],
              "impact_body": ["02", "03", "05"], "notification_ping": ["02", "03", "04", "05", "07"], "ui_click": ["01", "02", "03", "04", "05"],
              "foley_keyboard": ["02", "03", "05", "07", "10", "11", "12"], "foley_cash": ["02", "03", "04", "05", "07", "09"]}

    def __init__(self):
        self.n = {}

    def id(self, fam):
        k = self.n.get(fam, 0); self.n[fam] = k + 1
        L = self.PROVEN.get(fam, ["01"])
        return "=%s_%s" % (fam, L[k % len(L)])


def eye_x(it):
    x, w = it.get("x", 540), it.get("w", 0)
    if it.get("kind") in ("headline", "kicker", "note", "checklist", "progress", "chip", "tag"):
        return int(x + min(w, 700) * 0.3)
    return int(x + w / 2)


EVENT_SFX = {"spray": [(0, "impact_body", -16)], "burst": [(0, "impact_body", -16)], "stamp": [(0.16, "foley_stamp", -14)],
             "crack": [(0, "impact_heavy", -15)], "fill": [(0, "ui_pop", -18)], "drain": [(0, "ui_pop", -18)],
             "flip": [(0.1, "paper_page", -18)], "cut": [(0, "foley_paper", -19), (0.3, "foley_paper", -19)],
             "send": [(0, "swoosh_transition", -18)], "flyoff": [(0, "swoosh_transition", -18)], "stack": [(0, "foley_click", -18)], "topple": [(0, "foley_click", -18)]}


# ------------------------------------------------------------------ novelty (replaces catalogue share + code hash)
def lead_of(b):
    """a beat's lead part: its signature event, else its middle part, else its world action, else its clip, else type."""
    for a in b.get("do") or []:
        if a.get("event"):
            return "event:%s" % a["event"]
    for it in b.get("show") or []:
        for k in MID_KINDS + ["cta"]:
            if k in it:
                return k
    for a in b.get("do") or []:
        v = next((x for x in ACTIONS if x in a), None)
        if v:
            return "world:%s:%s" % (a.get("on"), v)
    for it in b.get("show") or []:
        if "clip" in it:
            return "clip"
    return "headline"


def novelty_key(B):
    world = sorted("%s:%s" % (s.get("type"), s.get("glyph") or "") for s in B.get("world") or [])
    events = sorted({a["event"] for b in B.get("beats") or [] for a in b.get("do") or [] if a.get("event")})
    return {"look": B.get("look"), "world": world, "events": events}


def posting_history(platform_key):
    """film ids armed or posted on this platform, oldest first, from the auto-poster's own video plans (read-only)."""
    try:
        sys.path.insert(0, os.path.join(KIT, "platforms"))
        import platforms as PF
        alias = PF.load().get("routing_alias", {})
    except Exception:
        alias = {}
    rows = []
    for f in sorted(glob.glob(PLANS_GLOB)):
        try:
            d = json.load(open(f))
        except (OSError, ValueError):
            continue
        for s in d.get("slots", []):
            if str(s.get("status", "")).upper() not in ("ARMED", "POSTED", "PUBLISHED", "DONE", "VERIFIED"):
                continue
            for p in s.get("platforms", []):
                if alias.get(p, p) == platform_key:
                    rows.append((d.get("date", ""), s.get("slot", ""), s.get("film")))
    return [r[2] for r in sorted(rows)]


def history_key(fid):
    p = os.path.join(KIT, "specs", fid, "spec.json")
    try:
        sp = json.load(open(p))
    except (OSError, ValueError):
        return None
    if sp.get("composed") and sp["composed"].get("novelty", {}).get("key"):
        return sp["composed"]["novelty"]["key"]
    return {"look": "kit3:" + str(sp.get("look")), "world": [str(sp.get("world"))], "events": [str(sp.get("signature_concept", ""))[:60]]}


def novelty_check(B, platform_key):
    """(problems, record). The rule for compiled shorts (root, 29 Sep): >= 1 signature event; no lead part on > 35% of
    beats; look + world + events must not match two of three against any of the last 3 shorts on the same platform."""
    probs, beats = [], B.get("beats") or []
    leads = [lead_of(b) for b in beats]
    key = novelty_key(B)
    if not key["events"]:
        probs.append("NOVELTY: no signature event. Place at least one physical event (spray, bolt, stamp, crack, fill, flip, pour, cut, send, topple) on a world object")
    n = max(1, len(beats))
    counts = {}
    for l in leads:
        k = l.split(":")[0] + (":" + l.split(":")[-1] if l.startswith("world:") else (":" + l.split(":")[1] if l.startswith("event:") else ""))
        counts[k] = counts.get(k, 0) + 1
    over = {k: v for k, v in counts.items() if v / n > LEAD_MAX}
    for k, v in over.items():
        probs.append("NOVELTY: %r leads %d of %d beats (%.0f%%; at most %.0f%%). Vary what carries each beat" % (k, v, n, 100.0 * v / n, 100 * LEAD_MAX))
    hist = posting_history(platform_key) if platform_key else []
    last3 = hist[-3:]
    clash = []
    for fid in last3:
        hk = history_key(fid)
        if not hk:
            continue
        same = sum([hk.get("look") == key["look"], hk.get("world") == key["world"], hk.get("events") == key["events"] and bool(key["events"])])
        if same >= 2:
            clash.append(fid)
            probs.append("NOVELTY: look/world/signature events repeat %s (one of the last 3 on %s): change at least two of them" % (fid, platform_key))
    return probs, {"key": key, "leads": leads, "lead_counts": counts, "platform": platform_key, "last3": last3, "clash": clash,
                   "verdict": "FAIL" if probs else "PASS"}


def novelty_gate(spec):
    """called by build_short.py for a spec with "composed": re-derives the novelty from specs/<ID>/beats.json (never
    trusts the stamp) and returns (ok, message)."""
    bp = os.path.join(KIT, "specs", spec["id"], "beats.json")
    if not os.path.exists(bp):
        return False, "composed spec without specs/%s/beats.json" % spec["id"]
    B = load_beats(bp, [])
    FR = load_frame(B.get("route_as") or spec["id"])
    probs, rec = novelty_check(B, FR.get("platform"))
    return (not probs), ("; ".join(probs) if probs else "novelty PASS on %s (last 3: %s)" % (FR.get("platform"), ", ".join(rec["last3"]) or "none"))


# ------------------------------------------------------------------ JSON repair
def repair_json(t):
    out, stack, ins = [], [], 0
    pair = {"}": "{", "]": "["}
    close = {"{": "}", "[": "]"}
    in_str = esc = False
    for ch in t:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            while stack and stack[-1] != pair[ch]:
                out.append(close[stack.pop()]); ins += 1
            if stack:
                stack.pop()
        out.append(ch)
    while stack:
        out.append(close[stack.pop()]); ins += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out)), ins


def load_beats(bpath, warns):
    t = open(bpath).read()
    try:
        return json.loads(t)
    except ValueError as e:
        r, n = repair_json(t)
        try:
            d = json.loads(r)
        except ValueError:
            raise Fail("beats.json is not valid JSON (%s), and the bracket repair could not fix it" % e)
        warns.append("beats.json was not valid JSON (%s); repaired by inserting %d closing bracket(s)" % (e, n))
        return d


# ------------------------------------------------------------------ voice
def voice_of(B):
    v = B.get("voice") or {}
    vw = v.get("wav", ""); vj = v.get("words", "")
    vw = vw if os.path.isabs(vw) else os.path.join(V2, vw)
    vj = vj if os.path.isabs(vj) else os.path.join(V2, vj)
    if not (os.path.exists(vw) and os.path.exists(vj)):
        raise Fail("voice wav/words not found: %s / %s" % (vw, vj))
    words = BS.load_words(vj)
    dur = round(math.ceil(max(BS.ffdur(vw), words[-1]["end"] + B.get("tail", 0.9)) * BS.FPS) / BS.FPS, 3)
    if dur > 60.0 and words[-1]["end"] + 0.35 <= 59.9:
        dur = 59.9
    return words, dur


def sentence_starts(words):
    """the reference of every sentence's first word ("@its#2"), in order."""
    seen, refs, start = {}, [], True
    for w in words:
        k = BS.norm(w["word"]); seen[k] = seen.get(k, 0) + 1
        if start:
            refs.append("@%s%s" % (k, "#%d" % seen[k] if seen[k] > 1 else ""))
        start = bool(re.search(r"[.!?]$", w["word"]))
    return refs


# ------------------------------------------------------------------ the compiler
def compose(bpath, stage=False, squeeze=None):
    """squeeze: {beat id: factor} shrinks that beat's top words (never under the floors) to make room; main() raises it
    for a beat that misses the 55% fill before reporting the miss (a default the model does not have to get right)."""
    squeeze = squeeze or {}
    errs, warns = [], []
    B = load_beats(bpath, warns)
    sid = B.get("id") or os.path.basename(os.path.dirname(os.path.abspath(bpath)))
    look = B.get("look", "paper")
    if look not in KIT3_LOOK:
        raise Fail("look %r is not one of %s" % (look, sorted(KIT3_LOOK)))
    FR = load_frame(B.get("route_as") or sid)
    S = FR["SAFE"]
    sources, src_path = ({}, None)
    if B.get("sources"):
        sources, src_path = load_sources(B["sources"])
    # Ensure sources is a dict (convert from list if needed)
    if isinstance(sources, list):
        sources = {item["id"]: item for item in sources}
    words, dur = voice_of(B)
    R = BS.Resolver(words)

    def T(x, base, what):
        if x is None:
            return None
        try:
            result = R.t(x, base)
            return result
        except SystemExit as e:
            m = re.match(r"^@([^#+\-\s]+?)(?:#\d+)?(\.end)?([+-]\d+(?:\.\d+)?)?$", str(x))
            if m and base is not None:
                key = BS.norm(m.group(1)); hits = [i for i, n in enumerate(R.n) if n == key]
                if hits:
                    pick = next((i for i in hits if words[i]["start"] >= base - 0.2), hits[-1])
                    w = words[pick]
                    t = round((w["end"] if m.group(2) else w["start"]) + float(m.group(3) or 0), 3)
                    warns.append("%s: %r does not exist; used %r at %.2f s" % (what, x, m.group(1), t))
                    return t
            errs.append("%s: %s" % (what, str(e).replace("build_short: ", "")))
            return base

    def T_safe(x, base, what):
        result = T(x, base, what)
        return result if result is not None else 0

    # facts: every number on screen is said, in the script / ledger, or in the sources
    known = " ".join(w["word"] for w in words)
    sc = (B.get("script") or {}).get("file") if isinstance(B.get("script"), dict) else B.get("script")
    if sc and os.path.exists(os.path.join(V2, sc)):
        known += " " + open(os.path.join(V2, sc)).read()
    if isinstance(sources, dict) and "sources" in sources:
        known += " " + " ".join(str(v.get("text", "")) + " " + str(v.get("date", "")) for v in sources.get("sources", []))
    elif isinstance(sources, list):
        known += " " + " ".join(str(v.get("text", "")) + " " + str(v.get("date", "")) for v in sources)
    else:
        known += " " + " ".join(str(v.get("text", "")) + " " + str(v.get("date", "")) for v in sources.values())
    KNOWN = set(numbers_in(known)) | set(num_words(known))

    def check_numbers(obj, where):
        txt = plain(obj) if isinstance(obj, str) else plain(json.dumps(obj, ensure_ascii=False))
        txt = re.sub(r'"(at|until|start|tick|slam|flip|press|ring|write|switch|hide|travel|fill|show|marksAt|size|x|y|zoom|over|every|per|cols|rows|units|col|first|last|spread|hour|minute|width|context|stagger|whereCol|focus|unit|row|pipe|dx|dy|bolts|boltsAt|n|w|h|from|to|dur|drop|len|angle|scale|toppleAt|showAt|rot)"\s*:\s*(\[[^\]]*\]|"[^"]*"|[-0-9.]+)', "", txt)
        txt = re.sub(r"@[^\s\\\"]+", "", txt)
        for n in claims_in(txt):
            if n not in KNOWN:
                errs.append("%s: the number %r is not said by the voice nor in the script, fact ledger or sources (no invented numbers)" % (where, n))

    beats = B.get("beats") or []
    if len(beats) < 3:
        raise Fail("a short needs at least 3 beats (hook, body, cta)")
    if beats[0].get("id") != "hook":
        errs.append("the first beat must have id \"hook\"")
    if beats[-1].get("id") != "cta":
        errs.append("the last beat must have id \"cta\"")
    times = []
    for i, b in enumerate(beats):
        if i == 0:
            times.append(0.0)
        elif "start" not in b:
            errs.append("beat %s: needs \"start\": \"@word\"" % b.get("id")); times.append(times[-1] + 1)
        else:
            times.append(round(max(0.0, T_safe(b["start"], None, "beat %s start" % b.get("id")) - b.get("lead", 0.1)), 3))
    ends = times[1:] + [dur]
    for i, b in enumerate(beats):
        if ends[i] - times[i] < 0.6:
            errs.append("beat %s is %.2f s long: merge it (min 0.6 s)" % (b.get("id"), ends[i] - times[i]))

    # ---- world stations, side by side (a grid is re-cut to the portrait frame unless an action uses its rows/cols)
    rowcol = {a.get("on") for b in beats for a in b.get("do") or [] if isinstance(a.get("select"), dict) and ("rows" in a["select"] or "cols" in a["select"])} | \
             {a.get("on") for b in beats for a in b.get("do") or [] if isinstance(a.get("point"), dict) and "row" in a["point"]}
    stations, SX = {}, 0
    for st in B.get("world", []):
        check_numbers({"rows": st.get("rows"), "title": st.get("title"), "label": st.get("label"), "columns": st.get("columns"), "source": st.get("source")}, "world %s" % st.get("id"))
        g = lay_station(st, errs, warns, sources, st.get("id") in rowcol, look)
        if not g:
            continue
        g["id"] = st.get("id") or "st%d" % len(stations)
        g["x"], g["y"] = SX, 0
        SX += g["w"] + 5200
        stations[g["id"]] = g

    cues = Cues()
    spec_beats, all_items, report_beats = [], [], []
    prev_key, last_cam = None, None
    label_seen = {}
    for i, b in enumerate(beats):
        bid = b.get("id", "b%d" % i)
        B0, B1 = times[i], ends[i]
        items, actions, sfx = [], [], []

        def rt(x, what, default):
            if x is None:
                return default
            t = T(x, B0, "beat %s %s" % (bid, what))
            if t is not None and t < B0 - 0.051:
                warns.append("beat %s %s: %r is said before the beat starts; it lands on the cut" % (bid, what, x))
                return B0
            if t is not None and B1 + 0.001 < t <= B1 + 0.6:
                warns.append("beat %s %s: %r is just after the beat; it lands 0.35 s before the cut" % (bid, what, x))
                return round(max(B0, B1 - 0.35), 3)
            if t is not None and t > B1 + 0.6:
                errs.append("beat %s %s: %r is %.2f s, after the beat ends (%.2f); it belongs to a later beat" % (bid, what, x, t, B1))
            return t

        # ---- parse show
        parsed = []
        for j, it in enumerate(b.get("show") or []):
            dumped = json.dumps(it, ensure_ascii=False)
            if re.search("[—–·]", dumped):
                it = json.loads(re.sub(" ?[—–·] ?", ", ", dumped))
                warns.append("beat %s show[%d]: a dash or middot became a comma" % (bid, j))
            kinds = [k for k in it if k in ALL_KINDS]
            if len(kinds) != 1:
                errs.append("beat %s show[%d]: name exactly one part (%s); got %s" % (bid, j, ", ".join(ALL_KINDS), list(it.keys())))
                continue
            k = kinds[0]
            for bad in BANNED[3:]:
                if bad in dumped.lower():
                    errs.append("beat %s show[%d]: contains %r" % (bid, j, bad))
            if k not in ("clip",):
                check_numbers({kk: vv for kk, vv in it.items() if kk not in ("marks",)}, "beat %s show[%d]" % (bid, j))
            q = dict(it); q["kind"] = k; q["main"] = it[k]; q["j"] = j
            q["at"] = rt(it.get("at"), "show[%d].at" % j, B0 if i else 0.0)
            q["endAt"] = rt(it.get("until"), "show[%d].until" % j, B1)
            parsed.append(q)
        if i == 0:
            f0 = [q for q in parsed if q["at"] <= 0.05 and q["kind"] in ("headline", "stat")]
            if not any(re.search(r"[0-9%£$]", plain(json.dumps(q["main"]))) for q in f0):
                errs.append("hook: frame 0 must show the number in a headline that is on from the start (no \"at\")")
        if i == len(beats) - 1:
            cw_ = [w for w in words if w["start"] >= B0 - 0.05]
            spoken = {BS.norm(w["word"]) for w in cw_}
            said = re.sub(r"[.!?]+$", "", " ".join(w["word"] for w in cw_)).upper()
            for q in parsed:
                if q["kind"] != "cta":
                    continue
                m = dict(q["main"]) if isinstance(q["main"], dict) else {"line": str(q["main"] or "")}
                lw = [BS.norm(x) for x in plain(m.get("line", "")).split() if BS.norm(x)]
                if not lw or sum(1 for x in lw if x in spoken) / len(lw) < 0.6:
                    if lw:
                        warns.append("cta: line %r is not what the voice says; using %r" % (plain(m.get("line", "")), said))
                    m["line"] = said
                if "\n" not in m["line"]:
                    wl = m["line"].split(" ")
                    per = max(1, math.ceil(len(wl) / 3))
                    m["line"] = "\n".join(" ".join(wl[k:k + per]) for k in range(0, len(wl), per))
                def wref(w):
                    n = sum(1 for x in words[:words.index(w) + 1] if BS.norm(x["word"]) == BS.norm(w["word"]))
                    return "@" + BS.norm(w["word"]) + ("#%d" % n if n > 1 else "")
                for key_, dflt in (("press", wref(cw_[0]) + "+0.3"), ("ring", wref(cw_[-1]))):
                    ok = False
                    if m.get(key_):
                        try:
                            tt = R.t(m[key_], B0); ok = B0 - 0.05 <= tt <= B1
                        except SystemExit:
                            ok = False
                    if not ok:
                        m[key_] = dflt
                q["main"] = m
            if not any(q["kind"] == "cta" for q in parsed):
                errs.append("the cta beat must show a {\"cta\": ...} part")
        has_mid = any(q["kind"] in MID_KINDS for q in parsed)
        is_cta = any(q["kind"] == "cta" for q in parsed)
        cam = b.get("camera")
        if cam and cam.get("on") and cam["on"] not in stations:
            errs.append("beat %s camera.on %r is not a world station (%s)" % (bid, cam["on"], sorted(stations)))
            cam = None
        inherited = False
        if not (cam and cam.get("on")) and last_cam:
            cam = dict(last_cam); cam.pop("then", None); cam.pop("focus", None); cam.pop("zoom", None); inherited = True
            s_ = stations.get(cam["on"])
            if s_ and (s_["type"] == "board" or s_.get("feed") == "fan") and any(q["kind"] in FLOAT_KINDS for q in parsed):
                g_ = next((x for x in stations.values() if not (x["type"] == "board" or x.get("feed") == "fan")), None)
                if g_:
                    warns.append("beat %s: no camera; its props go over %r rather than over %r's words" % (bid, g_["id"], s_["id"]))
                    cam = {"on": g_["id"]}
        if cam and cam.get("on"):
            last_cam = cam
        st = stations.get(cam["on"]) if cam else None
        world_mode = "off" if (not st) else ("dim" if (has_mid or is_cta) else "on")
        wordy = lambda x: x["type"] in ("board", "ticketline", "mailroom") or x.get("feed") == "fan"   # stations that carry words
        if world_mode == "dim" and wordy(st):
            g_ = next((x for x in stations.values() if not wordy(x)), None)
            if g_:   # cards never sit over a board's words: they sit over the world's grid, lightly dimmed
                warns.append("beat %s: its cards sit over %r, not the board (a board's words would show through)" % (bid, g_["id"]))
                cam = {"on": g_["id"]}; st = g_

        # ---- top stack (measured)
        y = S["y0"]
        last_of = {}
        tops = [q for q in parsed if q["kind"] in TOP_KINDS]
        for q in tops:
            k = q["kind"]
            if q.get("replace") and k in last_of:
                prev = last_of[k]; ytop = prev["y"]
            else:
                prev = None; ytop = y
            x = max(S["x0"], q.get("x", S["x0"]))
            xr = right_limit(FR, ytop, ytop + 300)
            if k == "kicker":
                sz = fit_px(look, "mono", q["main"], xr - x, q.get("size", 46))
                if sz < 38:
                    errs.append("beat %s kicker %r does not fit one line: shorten it" % (bid, plain(q["main"])))
                h = int(sz * 1.18 * len(lines_of(q["main"])))
                box = {"kind": k, "text": q["main"], "x": x, "y": ytop, "size": sz, "tone": q.get("tone"), "w": int(text_w(look, "mono", q["main"], sz)), "h": h, "maxw": xr - x}
            elif k == "headline":
                want = max(HERO_MIN, int((q.get("size") or (150 if len(lines_of(q["main"])) <= 2 else 124)) * squeeze.get(bid, 1.0)))
                if q.get("size") and q["size"] < HERO_MIN:
                    warns.append("beat %s headline %r: size %d raised to %d" % (bid, plain(q["main"])[:30], q["size"], HERO_MIN))
                xr = x + (xr - x) / 1.035          # room for the 3% breathe
                sz = fit_px(look, "hero", q["main"], xr - x, want)
                if sz < HERO_MIN and len(lines_of(q["main"])) < 3:
                    raw_ws = q["main"].replace("\n", " \n ").split(" ")
                    ws = [w for w in q["main"].replace("\n", " ").split(" ") if w]
                    if len(ws) > 1:
                        best = None
                        for kk in range(1, len(ws)):
                            cand = " ".join(ws[:kk]) + "\n" + " ".join(ws[kk:])
                            if len(lines_of(q["main"])) == 2:
                                cand = q["main"]
                            s2 = fit_px(look, "hero", cand, xr - x, want)
                            if best is None or s2 > best[0]:
                                best = (s2, cand)
                        if len(lines_of(q["main"])) == 2:   # already two lines: try three
                            for kk in range(1, len(ws) - 1):
                                for kk2 in range(kk + 1, len(ws)):
                                    cand = " ".join(ws[:kk]) + "\n" + " ".join(ws[kk:kk2]) + "\n" + " ".join(ws[kk2:])
                                    s2 = fit_px(look, "hero", cand, xr - x, want)
                                    if s2 > best[0]:
                                        best = (s2, cand)
                        if best and best[0] > sz:
                            warns.append("beat %s headline re-broken as %r to stay large" % (bid, plain(best[1]).replace("\n", " / ")))
                            q["main"], sz = best[1], best[0]
                if sz < HERO_MIN:
                    errs.append("beat %s headline %r would render at %d px (< %d): shorten it (at most %d characters a line, 3 lines at most)" % (bid, plain(q["main"]).replace("\n", " / "), sz, HERO_MIN, line_cap(look, xr - x)))
                h = int(sz * 0.96 * len(lines_of(q["main"])))
                box = {"kind": k, "text": q["main"], "x": x, "y": ytop, "size": sz, "w": int(text_w(look, "hero", q["main"], sz)), "h": h, "maxw": xr - x}
            elif k == "note":
                x += 14                                  # room for its 3 degree tilt
                sz = max(42, fit_px(look, "hand", q["main"], xr - x - 20, int(q.get("size", 64) * squeeze.get(bid, 1.0))))
                if sz < 42:
                    errs.append("beat %s note %r is too long for the frame: shorten or split it" % (bid, plain(q["main"])))
                box = {"kind": k, "text": q["main"], "x": x, "y": ytop, "size": sz, "tone": q.get("tone"), "rot": q.get("rot", -3),
                       "w": int(text_w(look, "hand", q["main"], sz)), "h": int(sz * 1.08 * len(lines_of(q["main"]))), "maxw": xr - x - 20}
            elif k == "progress":
                st_ = [dict(s) for s in (q["main"] if isinstance(q["main"], list) else [])]
                if not st_:
                    errs.append("beat %s progress: give a list of states" % bid)
                for si, s2 in enumerate(st_):
                    s2["at"] = q["at"] if si == 0 else rt(s2.get("at"), "progress[%d].at" % si, q["at"])
                box = {"kind": k, "states": st_, "x": x, "y": ytop, "w": xr - x, "h": 62}
            elif k == "chip":
                m = q["main"]
                logo = m.get("logo") if isinstance(m, dict) else None
                text = m.get("text") if isinstance(m, dict) else m
                if logo and logo not in sources:
                    errs.append("beat %s chip logo %r not in the sources file" % (bid, logo))
                box = {"kind": k, "logo": logo, "text": text, "x": x, "y": ytop, "w": min(xr - x, (420 if logo else 0) + (int(text_w(look, "mono", text or "", 46)) + 22 if text else 0)), "h": 88, "maxw": xr - x}
            elif k == "tags":
                its = []
                for si, s2 in enumerate(q["main"] if isinstance(q["main"], list) else []):
                    s2 = {"text": s2} if isinstance(s2, str) else dict(s2)
                    s2["at"] = rt(s2.get("at"), "tags[%d].at" % si, q["at"]); its.append(s2)
                if not 1 <= len(its) <= 4:
                    errs.append("beat %s tags: 1 to 4 tags" % bid)
                box = {"kind": k, "items": its, "x": S["x0"], "y": ytop, "w": xr - S["x0"], "h": 140, "tone": q.get("tone")}
            elif k == "checklist":
                its = []
                for si, s2 in enumerate(q["main"] if isinstance(q["main"], list) else []):
                    s2 = {"text": s2} if isinstance(s2, str) else dict(s2)
                    s2["at"] = rt(s2.get("tick"), "checklist[%d].tick" % si, None) if s2.get("tick") is not None else None
                    s2["showAt"] = rt(s2.get("show"), "checklist[%d].show" % si, q["at"])
                    s2.pop("tick", None); s2.pop("show", None); its.append(s2)
                sz = q.get("size", 64)
                for s2 in its:
                    sz = min(sz, fit_px(look, "hero", s2["text"], xr - x - 90, 64))
                if sz < 42:
                    errs.append("beat %s checklist rows are too long: shorten them" % bid)
                box = {"kind": k, "items": its, "x": x, "y": ytop, "size": sz, "pitch": int(sz * 1.55), "w": xr - x, "h": int(sz * 1.55 * len(its)), "maxw": xr - x}
            box.update({"at": q["at"], "endAt": q["endAt"], "j": q["j"]})
            if prev is not None:
                prev["endAt"] = min(prev["endAt"], box["at"])
            else:
                y = ytop + box["h"] + (26 if k == "headline" else 16)
            last_of[k] = box
            items.append(box)
        firsts = [it for it in items if it["kind"] in ("headline", "kicker")]
        if firsts and not any(it["at"] <= B0 + 0.05 for it in firsts) and not any(q["kind"] in MID_KINDS + ["cta"] for q in parsed):
            f0_ = min(firsts, key=lambda it: it["at"])
            warns.append("beat %s: %s %r now lands on the cut (a beat is never half-built on its first frame)" % (bid, f0_["kind"], plain(f0_["text"])[:30]))
            f0_["at"] = B0
        top_bottom = max([it["y"] + it["h"] for it in items] + [S["y0"]])
        band = top_bottom + 34 if items else 0          # the solid band behind the words

        # ---- clips (bottom; they may sit over the world); marks must be phrases that exist on the crop
        bottom_top, prev_clip = S["y1"], None
        for q in [q for q in parsed if q["kind"] == "clip"]:
            key = q["main"]
            s = sources.get(key)
            if not s or not s.get("css"):
                errs.append("beat %s clip %r is not a page crop in the sources file (%s)" % (bid, key, [k for k, v in sources.items() if v.get("css")][:10])); continue
            marks = q.get("marks") or []
            marks = [marks] if isinstance(marks, str) else marks
            bad = [m for m in marks if m not in (s.get("marks") or {})]
            for m in bad:
                errs.append("beat %s clip %r: %r is not on that crop. Mark only a listed phrase: %s" % (bid, key, m, list((s.get("marks") or {}).keys())[:12]))
            if not marks:
                errs.append("beat %s clip %r: mark the phrase the voice says (a clip with no mark is unreadably small)" % (bid, key))
            marks = [m for m in marks if m not in bad]
            near = {BS.norm(w["word"]) for w in words if B0 - 6 <= w["start"] <= B1 + 6}
            near_d = {re.sub(r"\D", "", x) for x in near if re.search(r"\d", x)}
            near_s = {x[:5] for x in near if len(x) > 3}
            def relevant(m):
                toks = [BS.norm(x) for x in re.findall(r"[\w$£%.,']+", m)]
                nums = [re.sub(r"\D", "", t) for t in toks if re.search(r"\d", t)]
                content = [t for t in toks if len(t) > 3 and not re.search(r"\d", t)]
                hits = sum(1 for t in content if t[:5] in near_s)
                return any(n in near_d for n in nums) or hits >= 1   # a paraphrase shares at least one word with the voice
            irrelevant = [m for m in marks if not relevant(m)]
            if irrelevant and len(irrelevant) == len(marks):
                warns.append("beat %s clip %r: %r is not what the voice says in this beat; the clip is left out" % (bid, key, irrelevant[0])); continue
            marks = [m for m in marks if m not in irrelevant]
            rects = [r for m in marks for r in s["marks"][m] if r[2]]
            marks_at = [T(a, B0, "beat %s clip.marksAt" % bid) for a in (q.get("marksAt") or [])][:len(marks)]
            while len(marks_at) < len(marks):
                marks_at.append(q["at"] + 0.5 + 0.5 * len(marks_at))
            cw_css, ch_css = s["css"]
            if not rects:
                continue
            crop = q.get("crop", "band" if look == "paper" else "cut")
            top_c = max(0, min(r[1] for r in rects) - 6); bot_c = min(ch_css, max(r[1] + r[3] for r in rects) + 6)
            lh = sorted(r[3] for r in rects)[len(rects) // 2]
            yb_max = S["y1"] - (0 if look == "paper" else 68) - 22      # room for the float and a 0.75 degree tilt
            wmax = right_limit(FR, yb_max - 400, S["y1"]) - S["x0"] - 40
            k_need = 58.0 / lh
            left_c, right_c = 0.0, float(cw_css)
            k = wmax / cw_css
            if k < k_need:
                left_c = max(0.0, min(r[0] for r in rects) - 10); right_c = min(float(cw_css), max(r[0] + r[2] for r in rects) + 10)
                k = min(k_need * 1.08, wmax / (right_c - left_c))
            else:
                k = min(k, k_need * 1.6)
            poly = None                                   # a straight-cut snippet of the page (stairs left fragments hard to read)
            # page context around a short mark, cut on WORD boundaries (never half a word): widen word by word along the
            # mark's own OCR line while the words still render >= 46 px
            L_ = [l for l in (s.get("lines") or []) if len(l) == 5 and abs((l[1] + l[3] / 2) - (rects[0][1] + rects[0][3] / 2)) < l[3] * 0.6]
            if L_ and len(rects) == 1:
                lx, ly, lw_, lh_, lt = L_[0]
                cw1 = lw_ / max(1, len(lt))
                i0 = max(0, int(round((rects[0][0] - lx) / cw1))); i1 = min(len(lt), int(round((rects[0][0] + rects[0][2] - lx) / cw1)))
                a_ = lt.rfind(" ", 0, i0) + 1 if i0 > 0 else 0          # snap the mark itself out to whole words
                b_ = lt.find(" ", i1) if lt.find(" ", i1) >= 0 else len(lt)
                def span(a2, b2):
                    return lx + a2 * cw1 - 6, lx + b2 * cw1 + 6
                best = span(a_, b_)
                while True:
                    na = lt.rfind(" ", 0, a_ - 1) + 1 if a_ > 0 else None
                    nb = (lt.find(" ", b_ + 1) if lt.find(" ", b_ + 1) >= 0 else len(lt)) if b_ < len(lt) else None
                    grew = False
                    for cand in ([(na, b_)] if na is not None else []) + ([(a_, nb)] if nb is not None else []):
                        l2, r2 = span(*cand)
                        if (r2 - l2) * 1.0 <= wmax / (k_need * 1.0) and (r2 - l2) <= 2.6 * (best[1] - best[0]) + 80:
                            a_, b_ = cand; best = (l2, r2); grew = True; break
                    if not grew:
                        break
                left_c, right_c = max(0.0, best[0]), min(float(cw_css), best[1])
                k = min(k_need * 1.08, wmax / (right_c - left_c))
            else:
                left_c, right_c = max(0.0, left_c - 4), min(float(cw_css), right_c + 8)
                k = min(k, wmax / (right_c - left_c))
            wdt, h = int((right_c - left_c) * k), int((bot_c - top_c) * k)
            credit_w = int(text_w(look, "mono", (s.get("credit") or "") + (", " + s["date"] if s.get("date") else ""), 42, 0.03) + 30)
            if lh * k < 46:
                if len(rects) > 1:   # a phrase that wraps across a line break cannot be shown big: the clip is left out
                    warns.append("beat %s clip %r: %r wraps across lines and would read at %d px; the clip is left out" % (bid, key, marks[0], lh * k * 0.8)); continue
                errs.append("beat %s clip %r: the marked words would render at %d px (< 42); mark a shorter phrase" % (bid, key, lh * k * 0.8))
            x = S["x0"] + 20 + max(0, int((wmax - wdt) / 2))
            yb = yb_max - h
            room = right_limit(FR, yb_max - 60, S["y1"]) - 20 - int(math.sin(math.radians(0.75)) * 900 + 4)   # its tilt too
            if x + max(credit_w, wdt) > room:          # the credit shrinks to fit (never under 34 px), then the clip slides left
                credit_w = max(wdt, min(credit_w, room - S["x0"] - 20))
                x = max(S["x0"] + 20, room - max(credit_w, wdt))
            if credit_w * 1.0 < int(text_w(look, "mono", (s.get("credit") or "") + (", " + s["date"] if s.get("date") else ""), 34, 0.03) + 30):
                errs.append("beat %s clip %r: its credit cannot fit at 34 px beside the %s UI; a shorter credit is needed in the sources file" % (bid, key, FR["platform"]))
            box = {"kind": "clip", "source": key, "marks": marks, "marksAt": marks_at, "cropTop": top_c, "cropBot": bot_c, "creditW": credit_w,
                   "cropLeft": round(left_c, 1), "cropRight": round(right_c, 1), "poly": poly, "x": x, "y": int(yb), "w": wdt, "h": h,
                   "rot": q.get("rot", 0.4 if i % 2 else -0.4), "at": q["at"], "endAt": q["endAt"], "j": q["j"]}
            if prev_clip is not None and prev_clip["endAt"] > box["at"]:
                prev_clip["endAt"] = box["at"]
            prev_clip = box
            bottom_top = min(bottom_top, int(yb) - (58 if look == "paper" else 10))
            items.append(box)

        # ---- middle parts fill the space between the words and the evidence
        mid_top, mid_bot = top_bottom + 40, bottom_top - 30
        mids = [q for q in parsed if q["kind"] in MID_KINDS]
        mx0 = S["x0"]; mx1 = right_limit(FR, mid_top, mid_bot); MW = int((mx1 - mx0) / 1.022)
        avail = mid_bot - mid_top - 30 * max(0, len(mids) - 1)
        if mids and avail < 260 * len(mids):
            errs.append("beat %s: the middle has %d px for %d card(s); drop a top line or the clip, or split the beat" % (bid, mid_bot - mid_top, len(mids)))
        my = mid_top
        for q in mids:
            k = q["kind"]
            h = int(max(240, avail / max(1, len(mids))))
            m = q["main"]
            if k == "stat":
                m = dict(m) if isinstance(m, dict) else {"value": m}
                sz = min(fit_px(look, "hero", m.get("value", ""), MW - 80, 320), int(h * (0.42 if m.get("label") else 0.55)))
                ws = str(m.get("value", "")).split()
                if sz < 90 and len(ws) > 1 and "\n" not in str(m.get("value", "")):   # a long value breaks onto lines before it shrinks
                    best = max((" ".join(ws[:k2]) + "\n" + " ".join(ws[k2:]) for k2 in range(1, len(ws))), key=lambda v: fit_px(look, "hero", v, MW - 80, 320))
                    s2 = min(fit_px(look, "hero", best, MW - 80, 320), int(h * 0.3))
                    if s2 > sz:
                        warns.append("beat %s stat value broken as %r" % (bid, best.replace("\n", " / "))); m["value"], sz = best, s2
                ch_ = int(sz * 1.05 * len(lines_of(m.get("value", ""))) + (100 if m.get("label") else 40) + (110 if m.get("foot") else 50))
                if ch_ < h:                                   # no tall empty card: size it to its words, centred
                    my += (h - ch_) // 2 if len(mids) == 1 else 0; h = ch_
                if sz < 90:
                    errs.append("beat %s stat value %r is too long to read big: shorten it" % (bid, m.get("value")))
                slam = rt(m.get("slam"), "stat.slam", None)
                box = {"kind": k, "label": m.get("label"), "value": m.get("value", ""), "foot": m.get("foot"), "tone": m.get("tone"), "size": sz,
                       "x": mx0, "y": my, "w": MW, "h": h, "at": q["at"], "slamAt": slam if (slam and slam > q["at"] + 0.05) else None}
                if not str(m.get("value", "")).strip():
                    errs.append("beat %s stat has no value: a card always shows its figure" % bid)
            elif k == "contrast":
                a, bb = dict(m.get("a", {})), dict(m.get("b", {}))
                bb["at"] = rt(bb.pop("slam", None), "contrast.b.slam", None); a.pop("slam", None)
                if not str(a.get("value", "")).strip() or not str(bb.get("value", "")).strip():
                    errs.append("beat %s contrast: both cards need a value" % bid)
                gw = (MW - 40) / 2 - 68
                sz = min(q.get("size", 170), fit_px(look, "hero", a.get("value", ""), gw, 170), fit_px(look, "hero", bb.get("value", ""), gw, 170), int(h * 0.3))
                nl = max(len(lines_of(a.get("value", ""))), len(lines_of(bb.get("value", ""))))
                ch_ = int(sz * 1.05 * nl + 130 + 130)
                if ch_ < h:
                    my += (h - ch_) // 2 if len(mids) == 1 else 0; h = ch_
                if sz < 80:
                    errs.append("beat %s contrast values %r / %r would render at %d px: a contrast shows two short figures or words (about 8 characters a line)" % (bid, a.get("value"), bb.get("value"), sz))
                box = {"kind": k, "a": a, "b": bb, "size": max(42, sz), "x": mx0, "y": my, "w": MW, "h": h, "at": q["at"]}
            elif k == "chain":
                nodes = m
                bh = int((h - 90 * (len(nodes) - 1)) / max(1, len(nodes)))
                sz = min(110, int(bh * 0.5), min(fit_px(look, "hero", n, MW - 220, 110) for n in nodes))
                box = {"kind": k, "nodes": nodes, "boxH": bh, "gap": 90, "size": max(42, sz), "x": mx0 + 40, "y": my, "w": MW - 80, "h": h, "at": q["at"],
                       "hideAt": rt(q.get("hide"), "chain.hide", None), "travelAt": rt(q.get("travel"), "chain.travel", None)}
            else:
                box = {"kind": k, "columns": m.get("columns", []), "per": m.get("per", 44), "tone": m.get("tone", "alert"),
                       "fillAt": max(0.0, rt(m.get("fill"), "tally.fill", q["at"]) - 0.3), "over": m.get("over", 2.2), "x": mx0, "y": my, "w": MW, "h": h, "at": q["at"]}
            box.update({"endAt": q["endAt"], "j": q["j"]})
            items.append(box)
            my += h + 30

        # ---- floats (small constructed props beside the world)
        float_side = None
        for q in [q for q in parsed if q["kind"] in FLOAT_KINDS]:
            k, m = q["kind"], q["main"]
            side, vpos = q.get("side", "right"), q.get("v", "middle")
            if k == "stamp":
                txt = m if isinstance(m, str) else m.get("text", "")
                sz = min(q.get("size", 150), fit_px(look, "hero", txt, MW - 160, 150))
                fw, fh = int(text_w(look, "hero", txt, sz) + 90), int(sz + 50)
            else:
                fw, fh = FLOAT_SIZE[k]
            placed = None
            for shrink in (1.0, 0.85, 0.72, 0.6):
                w2, h2 = int(fw * shrink), int(fh * shrink)
                for vv in [vpos] + [v for v in ("top", "bottom", "middle") if v != vpos]:
                    yy = mid_top + 10 if vv == "top" else (mid_bot - h2 - 10 if vv == "bottom" else int((mid_top + mid_bot - h2) / 2))
                    xr = right_limit(FR, yy, yy + h2)
                    x = xr - w2 if side == "right" else (S["x0"] if side == "left" else S["x0"] + (xr - S["x0"] - w2) // 2)
                    cand = {"kind": k, "x": int(x), "y": int(yy), "w": w2, "h": h2}
                    if yy >= mid_top - 1 and yy + h2 <= mid_bot + 1 and not any(overlap(cand, o) for o in items if o["kind"] in FLOAT_KINDS + MID_KINDS):
                        placed = cand; break
                if placed:
                    break
            if not placed:
                errs.append("beat %s: no room for the %s beside the other parts; drop a part or split the beat" % (bid, k)); continue
            if placed["w"] < fw:
                warns.append("beat %s: %s shrunk to %d%% to fit beside the other parts" % (bid, k, 100 * placed["w"] / fw))
            box = dict(placed, at=q["at"], endAt=q["endAt"], j=q["j"])
            if k == "calendar":
                box.update({"labels": m if isinstance(m, list) else m.get("labels", []), "flipAt": rt(q.get("flip"), "calendar.flip", q["at"] + 0.2), "every": q.get("every", 0.34), "label": q.get("label", "ILLUSTRATION")})
            elif k == "clock":
                box.update({"hour": (m or {}).get("hour", 8) if isinstance(m, dict) else 8, "minute": (m or {}).get("minute", 0) if isinstance(m, dict) else 0})
            elif k == "pad":
                box.update({"title": m.get("title", "NOTES"), "lines": m.get("lines", []), "writeAt": rt(q.get("write"), "pad.write", q["at"] + 0.4)})
            elif k == "meter":
                if m.get("mode") == "tick" and str(m.get("foot", "")).upper() != "ILLUSTRATION":
                    warns.append("beat %s meter: a ticking counter is an illustration, never a reported figure; its foot now says ILLUSTRATION" % bid)
                    m = dict(m, foot="ILLUSTRATION")
                box.update({"label": m.get("label", ""), "value": m.get("value", ""), "foot": m.get("foot"), "mode": m.get("mode", "static")})
                if m.get("mode") != "tick" and not str(m.get("value", "")).strip():
                    errs.append("beat %s meter has no value" % bid)
            elif k == "monitor":
                box.update({"state": (m or {}).get("state", "alert") if isinstance(m, dict) else m, "stateAt": rt(q.get("switch"), "monitor.switch", None)})
            elif k == "stamp":
                box.update({"text": txt, "size": sz, "tone": q.get("tone", "alert"), "rot": q.get("rot", -8)})
            items.append(box)
            if k != "stamp" and side in ("left", "right"):
                float_side = (side, fw + 30)

        # ---- cta (scaled to the platform's safe height)
        for q in [q for q in parsed if q["kind"] == "cta"]:
            m = q["main"]
            cw = right_limit(FR, S["y0"], S["y1"]) - S["x0"]
            ch = S["y1"] - S["y0"]
            scale = min(1.0, ch / 1130.0, cw / 900.0)
            items.append({"kind": "cta", "text": m["line"], "handle": str(m.get("handle", "agmm")).lstrip("@"), "link": m.get("link", "agmm.co.uk/ai-constraint-audit"),
                          "button": m.get("button", "FOLLOW"), "x": S["x0"], "y": S["y0"], "w": cw, "h": ch, "scale": round(scale, 3),
                          "at": q["at"], "endAt": B1, "pressAt": T(m["press"], B0, "cta.press"), "ringAt": T(m["ring"], B0, "cta.ring"), "j": q["j"]})
            if "ai-constraint-audit" not in m.get("link", "agmm.co.uk/ai-constraint-audit"):
                errs.append("cta link must be agmm.co.uk/ai-constraint-audit")

        # ---- camera: grids bleed under the band and the clip; boards sit whole inside the safe area
        keys, cur = [], None
        if st:
            if wordy(st) and float_side:
                warns.append("beat %s: the props sit beside %r, not over its words" % (bid, st["id"]))
            if st["type"] in ("ticketline", "mailroom") or st.get("feed") == "plan":   # whole worlds, words safe
                window = [S["x0"], band, right_limit(FR, band, S["y1"]), S["y1"] if not (bottom_top < S["y1"]) else bottom_top - 20]; bleed = False
            elif st["type"] == "board":
                bx1 = right_limit(FR, top_bottom + 30, bottom_top - 30)
                if float_side and float_side[0] == "right":
                    bx1 -= float_side[1]
                window = [S["x0"] + (float_side[1] if float_side and float_side[0] == "left" else 0), top_bottom + 30, bx1, bottom_top - 30]
                bleed = False
            else:
                window = [0, band, 1080, 1920]
                bleed = True
            aim = (band + min(S["y1"], bottom_top)) / 2 if bleed else None
            k0 = frame_station(st, window, point_of(st, cam.get("focus")) if cam.get("focus") else None, cam.get("zoom", 1.0), bleed, aim)
            if st["type"] == "board" and world_mode == "on" and st["fontPx"] * k0["s"] < 42:
                errs.append("beat %s: the board's words would render at %d px (< 42): shorten its longest cell (%r) or use fewer columns" % (
                    bid, st["fontPx"] * k0["s"], max((str(c) for r in st["rows"] for c in r if isinstance(c, str)), key=len)))
            ktarget = k0
            if prev_key is not None:
                keys.append(dict(prev_key, at=round(max(0.0, B0 - 0.004), 3), ease="none"))
            keys.append({"at": B0, "x": k0["x"], "y": k0["y"], "s": k0["s"], "ease": "none"})
            then = cam.get("then")
            if then and world_mode == "on":
                tt = rt(then.get("at"), "camera.then.at", B0 + 0.4)
                ktarget = frame_station(st, window, point_of(st, then.get("focus")) if then.get("focus") else None, then.get("zoom", cam.get("zoom", 1.0)), bleed, aim)
                keys.append({"at": tt, "x": k0["x"], "y": k0["y"], "s": k0["s"], "ease": "none"})
                keys.append({"at": round(min(B1 - 0.05, tt + 0.6), 3), "x": ktarget["x"], "y": ktarget["y"], "s": ktarget["s"], "ease": "expo.out"})
            move = cam.get("move", "push")
            f1 = PUSH if move == "push" else (1 / PUSH if move == "pull" else 1.015)
            if st["type"] == "board":
                f1 = min(f1, 1.0 / 1.0) if move == "push" else f1
                f1 = 1.0 + (f1 - 1.0) * 0.5
            s1 = ktarget["s"] * f1
            ke = {"at": round(B1 - 0.03, 3), "x": round(ktarget["cx"] - ktarget["fx"] * s1, 1), "y": round(ktarget["cy"] - ktarget["fy"] * s1, 1), "s": round(s1, 4), "ease": "sine.inOut"}
            keys.append(ke)
            prev_key = {k: ke[k] for k in ("x", "y", "s")}
            cur = k0
            if items and top_bottom > S["y0"] and world_mode == "on":
                items.insert(0, {"kind": "scrim", "y": S["y0"] - 90, "h": band + 60 - (S["y0"] - 90), "fade": 60, "fadeTop": 70, "at": B0, "endAt": B1})
            if world_mode == "dim" or (world_mode == "on" and not items):
                pass
            if world_mode == "dim":
                items.insert(0, {"kind": "dim", "at": B0, "endAt": B1 + (0.5 if is_cta else 0), "alpha": 0.72 if not wordy(st) else 0.96, "blur": 0 if wordy(st) else 7})
            # the station's ILLUSTRATION label, in screen space, inside the safe area, above the clip
            first_seen = st["id"] not in label_seen or B0 - label_seen[st["id"]] > 20
            if st.get("label") and world_mode == "on" and st["type"] != "board" and first_seen:   # disclosure on arrival, not furniture on every beat
                label_seen[st["id"]] = B0
                ty = band + 12 if band else S["y0"]          # just under the words, never touching the clip's credit
                tx1 = right_limit(FR, ty, ty + 120)
                lab = st["label"]
                if text_w(look, "mono", lab, 42, 0.08) + 24 > tx1 - S["x0"]:
                    ws = lab.split(" ")
                    lab = min((" ".join(ws[:k2]) + "\n" + " ".join(ws[k2:]) for k2 in range(1, len(ws))), key=lambda v: text_w(look, "mono", v, 42, 0.08))
                tw = int(text_w(look, "mono", lab, 42, 0.08) + 24)
                if tw <= tx1 - S["x0"]:
                    items.append({"kind": "tag", "text": lab, "x": S["x0"], "y": int(ty), "w": tw, "h": 56 * len(lab.split("\n")), "size": 42,
                                  "maxw": tx1 - S["x0"], "at": B0, "endAt": B1, "j": -1})
                else:
                    warns.append("beat %s: the station label %r is too long to show; shorten it" % (bid, st["label"]))
        else:
            if items:
                items.insert(0, {"kind": "dim", "at": B0, "endAt": B1, "alpha": 0.97})

        # ---- world actions and signature events
        for j, a in enumerate(b.get("do") or []):
            s = stations.get(a.get("on"))
            if not s:
                errs.append("beat %s do[%d]: on %r is not a world station" % (bid, j, a.get("on"))); continue
            verb = [x for x in ACTIONS if x in a]
            if len(verb) != 1:
                errs.append("beat %s do[%d]: name one action of %s" % (bid, j, ACTIONS)); continue
            verb = verb[0]
            ok_for = {"state": s["type"] == "grid", "mark": s["type"] == "grid", "valves": s.get("feed") == "pipe", "lines": s.get("feed") == "fan",
                      "flap": s["type"] == "board", "blink": s["type"] == "board", "event": True,
                      "reading": s["type"] == "ticketline", "run": s["type"] == "ticketline", "tickets": s["type"] == "ticketline",
                      "address": s["type"] == "mailroom", "post": s["type"] == "mailroom"}
            if not ok_for[verb]:
                errs.append("beat %s do[%d]: %r does not apply to %r (%s): state/mark act on grids, flap/blink on boards, valves on a pipe feed, lines on a fan feed" % (
                    bid, j, verb, s["id"], s["type"] + ("/" + s.get("feed", "") if s.get("feed") not in (None, "none") else ""))); continue
            at = rt(a.get("at"), "do[%d].at" % j, B0 if i else 0.0)
            act = {"on": s["id"], "do": verb, "at": at}
            if verb == "event":
                kind = a["event"]
                if kind not in EVENTS:
                    errs.append("beat %s do[%d]: event %r is not one of %s" % (bid, j, kind, EVENTS)); continue
                px, py = point_of(s, a.get("point"))
                # an event ends with its beat unless "until" says otherwise (opus-c1, 29 Sep: S21's flip cards, stamps and a
                # toppled stack stayed on screen for the rest of the short); a joint (spray/burst/bolt/seal) still persists
                # across beats so a later bolt can seal it
                act.update({"do": "event", "kind": kind, "verb": kind, "px": round(px, 1), "py": round(py, 1), "endAt": T(a.get("until"), B0, "do[%d].until" % j) if a.get("until") else (None if kind in ("spray", "burst", "bolt", "seal") else B1)})
                for p_ in ("dir", "joint", "id", "bolts", "text", "tone", "size", "w", "h", "from", "to", "dur", "front", "back", "drop", "n", "dx", "dy", "angle", "len", "scale", "rot"):
                    if p_ in a:
                        act[p_] = a[p_]
                if a.get("material"):
                    act["mat"] = a["material"]
                for tk in ("showAt", "boltsAt", "toppleAt"):
                    src_k = {"showAt": "show", "boltsAt": "bolts_at", "toppleAt": "topple"}[tk]
                    if a.get(src_k) is not None:
                        act[tk] = T(a[src_k], B0, "do[%d].%s" % (j, src_k))
                check_numbers({kk: a.get(kk) for kk in ("text", "front", "back")}, "beat %s do[%d]" % (bid, j))
            elif verb == "state":
                act.update({"state": a["state"], "select": a.get("select"), "order": a.get("order", "rows"), "over": a.get("over")})
            elif verb == "mark":
                act.update({"mark": a["mark"], "select": a.get("select"), "order": a.get("order", "rows"), "over": a.get("over"), "endAt": rt(a.get("until"), "do[%d].until" % j, B1)})
            elif verb == "flap":
                check_numbers(str(a.get("flap")), "beat %s do[%d] flap" % (bid, j))
                act.update({"text": a["flap"], "col": a.get("col", len(s.get("columns", [1])) - 1), "rows": a.get("rows"), "where": a.get("where"), "not": a.get("not"),
                            "whereCol": a.get("whereCol"), "tone": a.get("tone"), "stagger": a.get("stagger")})
            elif verb == "valves":
                act.update({"cols": a.get("cols", []), "open": a["valves"] == "open"})
            elif verb == "lines":
                act.update({"select": a.get("select"), "order": a.get("order", "rows"), "tone": a.get("tone", "alert"), "off": a["lines"] == "off", "endAt": rt(a.get("until"), "do[%d].until" % j, B1)})
            elif verb == "blink":
                act.update({"rows": a.get("rows", []), "col": a.get("col", len(s.get("columns", [1])) - 1)})
            elif verb == "reading":
                check_numbers(str(a["reading"]), "beat %s do[%d] reading" % (bid, j)); act.update({"text": str(a["reading"])})
            elif verb in ("run", "tickets"):
                act.update({"do": "run" if verb == "run" else "pourtickets", "k": int(a.get("k", a.get("run") if isinstance(a.get("run"), int) else 9)),
                            "endAt": T(a.get("until"), B0, "do[%d].until" % j) if a.get("until") else B1})
            elif verb == "address":
                act.update({"units": a.get("units"), "stagger": a.get("stagger")})
            elif verb == "post":
                act.update({"endAt": T(a.get("until"), B0, "do[%d].until" % j) if a.get("until") else None})
            actions.append(act)
            if a.get("sfx") == "none":
                continue
            kk = cur or {"x": 0, "y": 0, "s": 1}
            if verb == "event":
                sx = kk["x"] + act["px"] * kk["s"]
                if act["kind"] in ("bolt", "seal"):
                    tb = act.get("boltsAt", at + 0.45); nb = act.get("bolts", 6)
                    ev = [(0, "whoosh_air", -18)] + [(tb - at + d, "foley_click", -17) for d in (0, 0.32, 0.64)] + [(tb - at + nb * 0.16 + 0.1, "impact_soft", -16)]
                elif act["kind"] == "pour":
                    ev = [(0, "cash_register_coins" if a.get("material", "coins") != "water" else "impact_soft", -17)]
                elif act["kind"] in ("stack", "topple") and act.get("toppleAt"):
                    ev = [(0, "foley_click", -18), (act["toppleAt"] - at, "impact_body", -15)]
                else:
                    ev = EVENT_SFX.get(act["kind"], [(0, "impact_soft", -17)])
                for dt, fam, g in ev:
                    sfx.append({"at": round(at + dt, 3), "kind": cues.id(fam), "gain": g, "x": int(max(0, min(1080, sx))), "_keep": True})
            elif s["type"] == "grid" and verb in ("state", "mark", "lines", "valves"):
                us = order_units(pick_units(s, a.get("select")), a.get("order", "rows"), s) if verb != "valves" else [(c, 0) for c in a.get("cols", [])]
                n = len(us)
                picks = [us[0], us[n // 2], us[-1]][:min(3, n)] if n else []
                over = a.get("over") if a.get("over") is not None else min(0.9, n * 0.012)
                for pi, u in enumerate(picks):
                    wx, wy = unit_center(s, u[0], u[1])
                    tt = at + (over * (pi / 2.0) if n > 1 else 0)
                    fam, g = ("cash_register_coins", -17) if (verb == "state" and a["state"] == "gold" and pi == 0) else \
                             ("impact_body", -16) if (verb == "state" and a["state"] == "alert" and pi == 0) else \
                             (("foley_stamp" if a.get("mark") == "x" else "ui_pop"), -19) if verb == "mark" else \
                             ("swoosh_transition", -18) if verb == "lines" else ("foley_click", -18)
                    sfx.append({"at": round(tt, 3), "kind": cues.id(fam), "gain": g - (2 if pi else 0), "x": int(max(0, min(1080, kk["x"] + wx * kk["s"])))})
            elif verb in ("reading", "run", "tickets", "address", "post"):
                sx = int(kk["x"] + (s["x"] + s["w"] * (0.5 if verb != "run" else 0.6)) * kk["s"])
                ev = {"reading": [(0, "ui_click", -17)], "run": [(0, "foley_stamp", -17), (0.52, "foley_stamp", -19), (1.04, "foley_stamp", -19)],
                      "tickets": [(0, "foley_paper", -18), (0.4, "foley_paper", -20)], "post": [(0, "paper_page", -18), (0.3, "impact_soft", -17)],
                      "address": [(0, "foley_paper", -19), (0.35, "foley_stamp", -18), (0.7, "foley_paper", -19)]}[verb]
                for dt, fam, g in ev:
                    sfx.append({"at": round(at + dt, 3), "kind": cues.id(fam), "gain": g, "x": max(0, min(1080, sx))})
            elif s["type"] == "board" and verb == "flap":
                sx = int(kk["x"] + (s["x"] + s["w"] * 0.72) * kk["s"])
                sfx += [{"at": round(at, 3), "kind": cues.id("foley_keyboard"), "gain": -16, "x": sx}, {"at": round(at + 0.25, 3), "kind": cues.id("foley_keyboard"), "gain": -18, "x": sx}]

        # ---- rule 1: overlapping boxes swap on the frame
        vis = [it for it in items if it["kind"] not in ("scrim", "dim", "cta")]
        for a in vis:
            for c in vis:
                if a is c or a["at"] > c["at"] or (a["at"] == c["at"] and vis.index(a) > vis.index(c)):
                    continue
                if overlap(a, c) and a["endAt"] > c["at"] + 0.001 and c["endAt"] > a["at"]:
                    if a["kind"] == "tag" or c["kind"] == "tag":   # the illustration tag gives way to any part
                        (a if a["kind"] == "tag" else c)["endAt"] = (a if a["kind"] == "tag" else c)["at"]; continue
                    if c["at"] - a["at"] < 0.3:
                        errs.append("beat %s: %s and %s share the same space at the same moment" % (bid, desc(a), desc(c)))
                    else:
                        a["endAt"] = c["at"]
        items = [it for it in items if not (it["kind"] == "tag" and it["endAt"] <= it["at"])]

        # ---- safe zones on FINAL boxes: overlay motion included, world words under every camera key
        for it in items:
            if it["kind"] in ("scrim", "dim", "clock", "monitor", "cta"):
                continue
            for bx, what in final_boxes(it, look):
                p = safe_problem(FR, bx)
                if p:
                    errs.append("beat %s: SAFE ZONE: %s %s (box x %d-%d, y %d-%d)" % (bid, what, p, bx[0], bx[2], bx[1], bx[3]))
        if st and world_mode == "on":
            texts = world_text_boxes(st, look)
            ev_on = {}
            for a in actions:
                if a["do"] == "event" and a["kind"] in ("stamp", "flip"):
                    w_ = a.get("w") or (a.get("size", 64) * 0.62 * len(str(a.get("text", a.get("front", "")))) + 60)
                    h_ = a.get("h") or a.get("size", 64) * 1.5
                    # an event's words exist only from when it shows (a flip shows 0.4 s early) to its end (opus-c1)
                    ev_on[len(texts)] = (a["at"] - (0.45 if a["kind"] == "flip" else 0.0), a.get("endAt") if a.get("endAt") is not None else 1e9)
                    texts.append(("%s text %r" % (a["kind"], str(a.get("text") or a.get("back") or "")), (a["px"] - w_ / 2, a["py"] - h_ / 2, a["px"] + w_ / 2, a["py"] + h_ / 2)))
            covers = [it for it in items if it["kind"] not in ("scrim", "dim", "tag")]
            for k_ in keys:
                if k_["at"] < B0 - 0.001:
                    continue
                for ti, (what, wb) in enumerate(texts):
                    if ti in ev_on and not (ev_on[ti][0] - 0.001 <= k_["at"] < ev_on[ti][1]) and not (k_["at"] >= B1 - 0.05 and ev_on[ti][0] < B1):
                        continue
                    sb = to_screen(k_, wb)
                    if ti in ev_on:   # the ILLUSTRATION tag gives way to an event's words too (S21 hook: tag over a flip card)
                        for tg in [it for it in items if it["kind"] == "tag"]:
                            if sb[2] > tg["x"] and sb[0] < tg["x"] + tg["w"] and sb[3] > tg["y"] and sb[1] < tg["y"] + tg["h"]:
                                tg["endAt"] = max(tg["at"], min(tg["endAt"], ev_on[ti][0]))
                    hit = next((it for it in covers if sb[2] > it["x"] and sb[0] < it["x"] + it.get("w", 0) and sb[3] > it["y"] and sb[1] < it["y"] + it.get("h", 0)
                                and it["at"] < B1 and it["endAt"] > B0), None)
                    if hit and sb[3] > band:
                        errs.append("beat %s: %s would sit over the world's %s (words on words); move it, or frame another station" % (bid, desc(hit), what))
                        break
                    if sb[1] < band and sb[3] > 0:   # under the solid band: hidden, not cut, unless it crosses the band edge
                        if sb[3] <= band:
                            continue
                    p = safe_problem(FR, sb)
                    if p:
                        errs.append("beat %s: SAFE ZONE (camera at %.2f s): %s %s; on screen x %d-%d, y %d-%d at camera scale %.2f; zoom out, move the focus or use a smaller station" % (bid, k_["at"], what, p, sb[0], sb[2], sb[1], sb[3], k_["s"]))
                        break

        # ---- fill: world + clip + cards + events cover >= 55% of the frame
        fill = fill_ratio(items, st if (st and (world_mode == "on" or (world_mode == "dim" and not wordy(st)))) else None, cur, band if world_mode == "on" else 0, actions, S["y0"] - 30)
        # a bank world with its own constructed set (the ticket hall, the leather desk, the blueprint, the paper map)
        # fills the frame with its set; its objects must still cover 30% on their own (an empty set never passes)
        has_set = bool(st) and world_mode == "on" and (st["type"] in ("ticketline", "mailroom") or st.get("feed") in ("plan", "map"))
        if has_set and fill >= 0.30 and fill < FILL_MIN:
            warns.append("beat %s: objects cover %d%%; the world's own set fills the rest of the frame" % (bid, fill * 100))
            fill = FILL_MIN
        if not is_cta and fill < FILL_MIN:
            tops_ = [it for it in items if it["kind"] in TOP_KINDS]
            errs.append("beat %s: the subject fills %d%% of the frame (needs %d%%). The top words (%s) take %d px of the frame's height: cut them to a kicker + a 2-line headline, move a line to another beat, or put a camera on a station%s" % (
                bid, fill * 100, FILL_MIN * 100, " + ".join("%s %d lines" % (it["kind"], len(lines_of(it.get("text", "x")))) for it in tops_), top_bottom - S["y0"],
                "" if st else " (this beat has no camera and no card)") + (
                "; NOTE the clip takes the lower frame, which squeezes this %s world into the gap between the words and the clip: drop the clip from this beat (quote it where the camera is on a grid station), or drop the kicker" % st["type"]
                if st and st["type"] in ("ticketline", "mailroom", "board") and any(it["kind"] == "clip" for it in items) else ""))

        # ---- sound
        hx = next((eye_x(it) for it in items if it["kind"] == "headline"), 540)
        sfx.insert(0, {"at": 0.1, "kind": "=impact_heavy_05", "gain": -16, "x": int(hx)} if i == 0 else
                   {"at": B0 + 0.01, "kind": cues.id("swoosh_transition" if i % 2 else "whoosh_air"), "gain": -19, "x": int(hx)})
        for it in items:
            if it["kind"] in ("scrim", "dim", "tag"):
                continue
            k, xc = it["kind"], eye_x(it)
            late = it["at"] > B0 + 0.06 and not (i == 0 and it["at"] <= 0.05)
            fam = {"headline": ("impact_soft", -17), "kicker": ("ui_pop", -20), "clip": ("paper_page", -19), "chip": ("ui_click", -18),
                   "note": ("foley_paper", -20), "stat": ("impact_heavy", -15), "contrast": ("paper_page", -19), "chain": ("paper_page", -19),
                   "tally": ("foley_paper", -19), "calendar": ("paper_page", -19), "clock": ("ui_click", -19), "pad": ("foley_paper", -19),
                   "meter": ("ui_click", -18), "monitor": ("impact_body", -17), "stamp": ("foley_stamp", -14), "checklist": ("foley_paper", -19),
                   "progress": ("notification_ping", -17), "tags": ("ui_pop", -18)}.get(k)
            if fam and late:
                sfx.append({"at": round(it["at"], 3), "kind": cues.id(fam[0]), "gain": fam[1], "x": xc})
            if k == "clip":
                for mi, ma in enumerate(it["marksAt"][:2]):
                    if ma > it["at"] + 0.1:
                        sfx.append({"at": round(ma, 3), "kind": cues.id("foley_paper"), "gain": -20, "x": xc - 150 + 300 * mi})
            if k == "contrast" and it["b"].get("at"):
                sfx.append({"at": round(it["b"]["at"], 3), "kind": cues.id("foley_stamp"), "gain": -14, "x": it["x"] + it["w"] * 3 // 4})
            if k == "tags":
                for ti, tg in enumerate(it["items"]):
                    if tg["at"] > B0 + 0.06:
                        sfx.append({"at": round(tg["at"], 3), "kind": cues.id("ui_pop"), "gain": -17, "x": int(it["x"] + (ti + 0.5) * it["w"] / len(it["items"]))})
            if k == "checklist":
                for row in it["items"]:
                    if row.get("at"):
                        sfx.append({"at": round(row["at"], 3), "kind": cues.id("foley_paper"), "gain": -19, "x": it["x"] + 40})
            if k == "progress":
                for st2 in it["states"][1:]:
                    sfx.append({"at": round(st2["at"], 3), "kind": cues.id("impact_body" if st2.get("tone") == "alert" else "notification_ping"), "gain": -16, "x": xc})
            if k == "chain":
                if it.get("travelAt"):
                    sfx.append({"at": round(it["travelAt"], 3), "kind": cues.id("swoosh_transition"), "gain": -18, "x": 540})
                if it.get("hideAt"):
                    sfx.append({"at": round(it["hideAt"], 3), "kind": cues.id("impact_soft"), "gain": -16, "x": 540})
            if k == "calendar":
                for fi in range(1, min(3, len(it["labels"]))):
                    sfx.append({"at": round(it["flipAt"] + fi * it["every"], 3), "kind": cues.id("paper_page"), "gain": -20, "x": xc})
            if k == "pad":
                for li in range(min(2, len(it["lines"]))):
                    sfx.append({"at": round(it["writeAt"] + li * 0.6, 3), "kind": cues.id("foley_paper"), "gain": -19, "x": xc})
            if k == "monitor" and it.get("stateAt"):
                sfx.append({"at": round(it["stateAt"], 3), "kind": cues.id("impact_body"), "gain": -16, "x": xc})
            if k == "cta":
                sfx.append({"at": round(it["pressAt"], 3), "kind": "press", "gain": -12, "x": 540})
                sfx.append({"at": round(it["ringAt"], 3), "kind": cues.id("foley_paper"), "gain": -20, "x": 540})
        for j, x in enumerate(b.get("sfx") or []):
            tgt = next((it for it in items if it.get("j") == x.get("on")), None)
            sfx.append({"at": rt(x.get("at"), "sfx[%d].at" % j, B0), "kind": x["kind"], "gain": x.get("gain", -18), "x": eye_x(tgt) if tgt else int(x.get("x", 540))})
        sfx = sorted([c for c in sfx if (B0 - 0.05 <= c["at"] < B1) or (c.get("_keep") and 0 <= c["at"] < dur)], key=lambda c: c["at"])
        for c in sfx:
            c.pop("_keep", None)

        # ---- pacing: > 6 s with nothing new is refused
        ev = sorted(set([B0, B1] + [it["at"] for it in items if it["kind"] not in ("scrim", "dim", "tag")] + [a["at"] for a in actions]
                        + [m for it in items if it["kind"] == "clip" for m in it["marksAt"]] + [k_["at"] for k_ in keys if k_["at"] >= B0]
                        + [it[k2] for it in items for k2 in ("pressAt", "ringAt", "flipAt", "writeAt", "stateAt", "travelAt", "hideAt") if it.get(k2) is not None]
                        + [a[k2] for a in actions for k2 in ("boltsAt", "toppleAt") if a.get(k2) is not None]
                        + [r[k2] for it in items for r in (it.get("items") or []) + (it.get("states") or []) if isinstance(r, dict) for k2 in ("at", "showAt") if r.get(k2) is not None]))
        gaps = [(ev[n + 1] - ev[n], ev[n]) for n in range(len(ev) - 1)]
        worst = max(gaps) if gaps else (0, B0)
        if worst[0] > GAP_MAX and i not in (0, len(beats) - 1):
            errs.append("beat %s: %.1f s with nothing new from %.2f s; split it or add a mark, action or part every 3-4 s" % (bid, worst[0], worst[1]))
        elif worst[0] > 4.0:
            warns.append("beat %s: %.1f s with nothing new from %.2f s" % (bid, worst[0], worst[1]))

        clean = [{k: v for k, v in it.items() if k not in ("j",) and v is not None} for it in items]
        all_items.append((bid, B0, B1, clean))
        report_beats.append({"id": bid, "from": B0, "to": B1, "fill": round(fill, 3), "lead": lead_of(b), "world": world_mode,
                             "min_headline": min([it["size"] for it in items if it["kind"] == "headline"] or [0])})
        sb = {"id": bid, "component": "scene", "start": b.get("start") if i else "@" + BS.norm(words[0]["word"]),
              "mirrors": b.get("mirrors", [0]), "field": "none", "drift": False, "tx": "none", "captions": False,
              "props": {"scene": "%s-%s" % (sid.lower(), bid), "cam": keys, "actions": actions, "items": clean, "labels": []}, "sfx": sfx}
        if i == 0:
            sb["lead"] = 0
        elif "lead" in b:
            sb["lead"] = b["lead"]
        if b.get("signature"):
            sb["signature"] = True
        if i == len(beats) - 1:
            sb["props"]["link"] = "agmm.co.uk/ai-constraint-audit"
        spec_beats.append(sb)

    if not any(b.get("signature") for b in beats):
        errs.append("mark the beat the story turns on with \"signature\": true")
    if not B.get("signature_concept"):
        errs.append("signature_concept: one line describing the signature moment")
    nov_probs, nov = novelty_check(B, FR.get("platform"))
    if not B.get("reproduction_of"):
        errs += nov_probs
    else:
        warns += ["(scratch, not enforced) " + p for p in nov_probs]
    report = {"id": sid, "dur": dur, "platform": FR.get("platform"), "safe": FR["SAFE"], "beats": report_beats, "errors": errs,
              "warnings": warns, "novelty": nov, "score": score_of(errs, warns, report_beats)}
    if errs:
        return report, None, None
    used_src = sorted({it["source"] for _, _, _, its in all_items for it in its if it["kind"] == "clip"} |
                      {it["logo"] for _, _, _, its in all_items for it in its if it["kind"] == "chip" and it.get("logo")} |
                      {c["logo"] for s in stations.values() if s["type"] == "board" for r in s["rows"] for c in r if isinstance(c, dict) and c.get("logo")})
    plan = {"look": look, "stations": list(stations.values()), "frame": {"SAFE": FR["SAFE"], "NOTCHES": FR["NOTCHES"], "platform": FR["platform"]}}
    js = [open(PARTS_JS).read(),
          "/* ---- composed by tools/compose.py v2 from %s (parts %s, platform %s). Edit beats.json and re-run; never edit this file. */" % (os.path.relpath(bpath, KIT), part_version(), FR["platform"]),
          "window.AGP_SRC = " + json.dumps({k: sources[k] for k in used_src}, indent=0) + ";",
          "AGP.install(%s, %s);" % (json.dumps(sid.lower()), json.dumps(plan, separators=(",", ":"))),
          "(function () { var A = window.AGK; " + " ".join('A.scenes["%s-%s"] = function (ctx, S, p, B, K) { AGP.beat(ctx, S, p, B, "%s-%s"); };' % (sid.lower(), sb["id"], sid.lower(), sb["id"]) for sb in spec_beats) + " })();"]
    spec = {"id": sid, "title": B.get("title", sid), "slug": B.get("slug", sid.lower()), "look": KIT3_LOOK[look],
            "platform": B.get("platform", FR.get("route") or ""), "platform_label": B.get("platform_label", ""), "format": B.get("format", "composed"),
            "script": B.get("script", {"id": sid, "file": ""}), "voice": B["voice"], "needs": [], "world": "%s-world" % sid.lower(),
            "signature_concept": B.get("signature_concept", ""), "transitions": B.get("transitions") or transitions_of(stations, all_items, nov["key"]),
            "code": ["specs/%s/scenes.js" % sid], "music": dict({"under_lu": 16}, **B.get("music", {"bed": "ic_presenterator"})), "render": {"parts": 4},
            "kit_defaults": "2026-09-28", "tail": B.get("tail", 0.9),
            "composed": {"from": "beats.json", "compose": "v2", "parts_version": part_version(), "platform": FR.get("platform"),
                         "novelty": {"verdict": nov["verdict"], "key": nov["key"], "last3": nov["last3"]}}, "beats": spec_beats}
    for k in ("reference_url", "reference_map", "reproduction_of", "reference_title_claimed", "reference_note"):
        if k in B:
            spec[k] = B[k]
    report["sources_used"] = used_src
    if stage and src_path:
        dst = os.path.join(KIT, "out", sid, "img"); os.makedirs(dst, exist_ok=True)
        for k in used_src:
            f = find_image(src_path, sources[k]["src"])
            if not f:
                raise Fail("image for source %r not found" % k)
            to = os.path.join(dst, os.path.basename(sources[k]["src"]))
            if os.path.abspath(f) != os.path.abspath(to):
                shutil.copyfile(f, to)
        report["staged"] = dst
    return report, spec, "\n".join(js) + "\n"


def final_boxes(it, look):
    """the box(es) a part really occupies while on screen, persistent motion included."""
    k, x, y, w, h = it["kind"], it["x"], it["y"], it.get("w", 0), it.get("h", 0)
    if k == "headline":
        return [((x, y, x + w * 1.03, y + h * 1.03), "headline %r" % plain(it["text"])[:30])]
    if k == "clip":
        pad = abs(math.sin(math.radians(0.75))) * w + 3
        top = y - (58 if look == "paper" else 0) - 10
        bot = y + h + (68 if look != "paper" else 0)
        return [((x - pad, top - pad, x + max(w, it.get("creditW", 0)) + pad, bot + pad), "clip %r with its credit" % it["source"])]
    if k in ("note", "stamp"):
        r = math.radians(abs(it.get("rot", -3)) + (4 if k == "stamp" else 0))
        W, H = w * math.cos(r) + h * math.sin(r), w * math.sin(r) + h * math.cos(r)
        return [((x - (W - w) / 2, y - (H - h) / 2, x + (W + w) / 2, y + (H + h) / 2), "%s %r" % (k, plain(it["text"])[:30]))]
    if k in ("stat", "contrast", "chain", "tally", "tags", "checklist", "kicker", "progress", "chip", "calendar", "pad", "meter", "tag"):
        g = 1.02 if k in ("stat", "contrast") else 1.0
        return [((x, y - (10 if k in ("pad", "calendar") else 0), x + w * g, y + h * g), "%s %s" % (k, desc(it)))]
    return []


def fill_ratio(items, st, k, band, actions, bandtop=0):
    """fraction of the 1080x1920 frame covered by the subject: the world (below the words' band), clips, cards, floats
    and event extents, on a 20 px raster."""
    G = [[0] * 54 for _ in range(96)]

    def paint(x0, y0, x1, y1):
        for r in range(max(0, int(y0 // 20)), min(96, int(math.ceil(y1 / 20)))):
            for c in range(max(0, int(x0 // 20)), min(54, int(math.ceil(x1 / 20)))):
                G[r][c] = 1
    if st and k:
        x0, y0, x1, y1 = to_screen(k, (st["x"], st["y"], st["x"] + st["w"], st["y"] + st["h"]))
        if band:
            paint(x0, y0, x1, min(y1, bandtop))
            paint(x0, max(y0, band), x1, y1)
        else:
            paint(x0, y0, x1, y1)
        for a in actions:
            if a["do"] == "event":
                e = 150
                ex, ey = k["x"] + a["px"] * k["s"], k["y"] + a["py"] * k["s"]
                paint(ex - e, ey - e, ex + e, ey + e)
    for it in items:
        if it["kind"] in ("clip", "stat", "contrast", "chain", "tally", "calendar", "pad", "meter", "monitor", "clock", "stamp", "cta"):
            paint(it["x"], it["y"], it["x"] + it["w"], it["y"] + it["h"])
    return sum(map(sum, G)) / float(54 * 96)


def score_of(errs, warns, beats):
    """compose's own measurable score, used to keep the better of two attempts (higher is better)."""
    if not beats:
        return -1e6
    return round(-100 * len(errs) - 2 * len(warns) + 50 * min(b["fill"] for b in beats) + 20 * sum(b["fill"] for b in beats) / len(beats)
                 + 0.1 * min([b["min_headline"] for b in beats if b["min_headline"]] or [0]), 2)


def stairs(rects, pad=3):
    n = len(rects)
    if n > 1:
        left, right = min(r[0] for r in rects), max(r[0] + r[2] for r in rects)
        rects = [[r[0], r[1], right - r[0], r[3]] if i == 0 else ([left, r[1], r[0] + r[2] - left, r[3]] if i == n - 1 else [left, r[1], right - left, r[3]]) for i, r in enumerate(rects)]
    tops = [r[1] - pad if i == 0 else (rects[i - 1][1] + rects[i - 1][3] + r[1]) / 2 for i, r in enumerate(rects)]
    bots = [tops[i + 1] if i < n - 1 else r[1] + r[3] + pad + 2 for i, r in enumerate(rects)]
    right = [r[0] + r[2] + pad for r in rects]
    p = []
    for i in range(n):
        p += [[right[i], tops[i]], [right[i], bots[i]]]
    for i in range(n - 1, -1, -1):
        p += [[rects[i][0] - pad, bots[i]], [rects[i][0] - pad, tops[i]]]
    return [[round(a, 1), round(b, 1)] for a, b in p]


def overlap(a, c, pad=6):
    return not (a["x"] + a.get("w", 0) + pad <= c["x"] or c["x"] + c.get("w", 0) + pad <= a["x"] or
                a["y"] + a.get("h", 0) + pad <= c["y"] or c["y"] + c.get("h", 0) + pad <= a["y"])


def desc(it):
    return "%s %r" % (it["kind"], plain(it.get("text") or it.get("source") or it.get("value") or it.get("label") or "")[:30])


def part_version():
    m = re.search(r'P\.VERSION = "([^"]+)"', open(PARTS_JS).read())
    return m.group(1) if m else "?"


def transitions_of(stations, all_items, key):
    t = ["hard camera cuts across one constructed world"]
    for s in stations.values():
        t.append("a grid of %d %s units changes state" % (s["cols_n"] * s["rows_n"], s["glyph"]) if s["type"] == "grid" else "a split-flap board flips")
    t += ["signature event: %s" % e for e in key["events"]]
    return t


# ------------------------------------------------------------------ plan-then-fill
def line_cap(look, width):
    """characters per headline line that still render at PLAN_HERO px across `width` (a typical uppercase line)."""
    # a WIDE sample (digits, %, M and W): a cap the lane can trust for any line it writes
    sample = "35% OF UK FIRMS MW 580"
    return int(width / (text_w(look, "hero", sample, PLAN_HERO) / float(len(sample))))


def rebreak(look, h, width):
    """the best 1-3 line break of a headline's words (largest hero px), or None; keeps the lane's own words."""
    import itertools
    ws = plain(h).replace("\n", " ").split()
    if not ws or len(ws) > 12:
        return None
    best = None
    for n in range(1, min(3, len(ws)) + 1):
        for cuts in itertools.combinations(range(1, len(ws)), n - 1):
            idx = (0,) + cuts + (len(ws),)
            t = "\n".join(" ".join(ws[idx[k]:idx[k + 1]]) for k in range(n))
            px = fit_px(look, "hero", t, width, 250)
            if best is None or px > best[1] + 0.5:
                best = (t, px)
    return best


def check_plan(plan, words, sources=None, route=None):
    """validate a lane's beat plan before it fills it: [errors], normalised plan."""
    errs = []
    look = plan.get("look") if plan.get("look") in FONTS else "paper"
    FR = load_frame(route) if route else dict(FALLBACK_FRAME)
    width = (right_limit(FR, FR["SAFE"]["y0"], FR["SAFE"]["y0"] + 500) - FR["SAFE"]["x0"]) / 1.035
    cap = line_cap(look, width)
    for b in plan.get("beats") or []:
        h = b.get("headline")
        if b.get("id") == "cta":
            continue
        if not h:
            errs.append("plan beat %s: give its \"headline\" (the hero words, at most %d characters a line, 1 to 3 lines)" % (b.get("id"), cap)); continue
        lines = str(h).split("\n")
        px = fit_px(look, "hero", h, width, 250)
        if len(lines) > 3 or px < PLAN_HERO:   # the lane picks the words; the layout picks the line breaks
            best = rebreak(look, h, width)
            if best and best[1] >= PLAN_HERO:
                b["headline"] = best[0]; b["_rebroken"] = True
                lines, px = best[0].split("\n"), best[1]
        if len(lines) > 3 or px < PLAN_HERO:
            errs.append("plan beat %s: headline %r would render at %d px; hero text is %d px or more: at most %d characters a line and 3 lines (%s look)" % (
                b.get("id"), plain(h).replace("\n", " / "), px, PLAN_HERO, cap, look))
    R = BS.Resolver(words)
    starts = sentence_starts(words)
    beats = plan.get("beats") or []
    if not 12 <= len(beats) <= 16:
        errs.append("plan: %d beats; plan 12 to 16 (one sentence each, the hook and the cta included)" % len(beats))
    if not beats or beats[0].get("id") != "hook":
        errs.append("plan: the first beat is \"hook\"")
    if not beats or beats[-1].get("id") != "cta":
        errs.append("plan: the last beat is \"cta\"")
    ts = []
    for i, b in enumerate(beats):
        if i == 0:
            ts.append(0.0); continue
        s = b.get("start")
        if s not in starts:
            errs.append("plan beat %s: start %r is not the first word of a sentence; use one of the [start] refs" % (b.get("id"), s))
        try:
            ts.append(R.t(s))
        except SystemExit:
            ts.append(ts[-1] + 1)
    ends = ts[1:] + [words[-1]["end"] + 0.9]
    for i, b in enumerate(beats):
        if ends[i] - ts[i] > 6.5 and not b.get("lands_on2"):
            errs.append("plan beat %s runs %.1f s: give it a second landing word (\"lands_on2\") or split it" % (b.get("id"), ends[i] - ts[i]))
        for key in ("lands_on", "lands_on2"):
            if b.get(key):
                try:
                    t = R.t(b[key])
                    if not ts[i] - 0.1 <= t <= (max(ends[i], 9.0) if i == 0 else ends[i]):   # the hook may land on its number up to 9 s in
                        errs.append("plan beat %s: %s %r is said outside the beat" % (b.get("id"), key, b[key]))
                except SystemExit as e:
                    errs.append("plan beat %s: %s %r: %s" % (b.get("id"), key, b[key], str(e).replace("build_short: ", "")))
    leads = [str(b.get("lead", "")) for b in beats]
    vocab = set(MID_KINDS + ["clip", "headline", "cta"]) | {"event:" + e for e in EVENTS}
    for i, l in enumerate(leads):
        if not (l in vocab or l.startswith("world:")):
            errs.append("plan beat %s: lead %r is not a part (%s, world:<station>:<action>)" % (beats[i].get("id"), l, sorted(vocab)))
    counts = {}
    for l in leads:
        counts[l] = counts.get(l, 0) + 1
    for l, v in counts.items():
        if v / max(1, len(beats)) > LEAD_MAX:
            errs.append("plan: %r leads %d of %d beats (> 35%%); vary the parts" % (l, v, len(beats)))
    if not any(l.startswith("event:") for l in leads):
        errs.append("plan: no beat is led by a signature event (event:<spray|bolt|stamp|crack|fill|flip|pour|cut|send|topple>)")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("beats", nargs="?"); ap.add_argument("--check", action="store_true"); ap.add_argument("--stage", action="store_true")
    ap.add_argument("--json", action="store_true"); ap.add_argument("--plan"); ap.add_argument("--voice"); ap.add_argument("--route-as")
    a = ap.parse_args()
    if a.plan:
        words = BS.load_words(os.path.join(V2, a.voice, os.path.basename(a.voice.rstrip("/")) + ".words.json"))
        w = []
        try:
            plan = load_beats(a.plan, w)
        except Fail as e:
            print(json.dumps({"errors": [str(e)], "warnings": []})); sys.exit(1)
        e = check_plan(plan, words, route=a.route_as)
        fixed = {b.get("id"): b["headline"] for b in plan.get("beats") or [] if b.get("_rebroken")}
        if fixed and not e:   # write the re-broken headlines back into the lane's plan file so fill sees them
            raw = json.load(open(a.plan))
            for b in raw.get("beats") or []:
                if b.get("id") in fixed:
                    b["headline"] = fixed[b["id"]]
            json.dump(raw, open(a.plan, "w"), indent=1)
            w.append("re-broke headline lines to reach %d px: %s" % (PLAN_HERO, "; ".join("%s -> %r" % kv for kv in fixed.items())))
        print(json.dumps({"errors": e, "warnings": w}, indent=1)); sys.exit(1 if e else 0)
    try:
        squeeze = {}
        for _ in range(4):
            report, spec, js = compose(os.path.abspath(a.beats), a.stage, squeeze)
            short = [re.match(r"beat (\S+): the subject fills", e).group(1) for e in report["errors"] if re.match(r"beat \S+: the subject fills", e)]
            if not short:
                break
            for b_ in short:
                squeeze[b_] = round(squeeze.get(b_, 1.0) * 0.85, 3)
        if squeeze:
            report["warnings"].append("top words shrunk to make room in %s" % ", ".join("%s (x%.2f)" % kv for kv in squeeze.items()))
    except Fail as e:
        print(json.dumps({"errors": [str(e)], "warnings": [], "score": -1e6}) if a.json else "COMPOSE ERROR: %s" % e); sys.exit(2)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as e:
        import traceback
        tb = traceback.extract_tb(sys.exc_info()[2])[-1]
        msg = "malformed beats.json (%s: %s; compose.py line %d)" % (type(e).__name__, e, tb.lineno)
        print(json.dumps({"errors": [msg], "warnings": [], "score": -1e6}) if a.json else "COMPOSE ERROR: " + msg); sys.exit(2)
    if not a.check and spec:
        d = os.path.dirname(os.path.abspath(a.beats))
        json.dump(spec, open(os.path.join(d, "spec.json"), "w"), indent=1)
        open(os.path.join(d, "scenes.js"), "w").write(js)
    if a.json:
        print(json.dumps(report, indent=1, default=str)); sys.exit(1 if report["errors"] else 0)
    for w in report["warnings"]:
        print("WARN: " + w)
    for e in report["errors"]:
        print("ERROR: " + e)
    print("platform %s, safe %s; novelty %s (key %s)" % (report["platform"], report["safe"], report["novelty"]["verdict"], report["novelty"]["key"]))
    print("beats: " + ", ".join("%s %.1f-%.1f fill %d%%" % (b["id"], b["from"], b["to"], b["fill"] * 100) for b in report["beats"]))
    if report["errors"]:
        print("%d error(s); nothing written" % len(report["errors"])); sys.exit(1)
    print("check OK" if a.check else "wrote spec.json + scenes.js (%d beats, %.2f s)%s" % (len(report["beats"]), report["dur"], ("; staged into " + report["staged"]) if report.get("staged") else ""))


if __name__ == "__main__":
    main()
