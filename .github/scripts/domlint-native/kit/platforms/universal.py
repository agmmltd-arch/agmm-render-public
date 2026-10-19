#!/usr/bin/env python3
"""universal.py -- the ONE safe zone every new short is laid out in (Sam, 19 Oct 2026, after a short posted to TikTok with a lot of it
hidden: "make all content going forward respect all the platforms' sizes").

The zone is DERIVED, never typed: the part of the 1080x1920 master that is inside the visible rect, inside the documented safe area and
under NO overlay of TikTok, Instagram Reels, YouTube Shorts, Facebook Reels and LinkedIn vertical video at the same time, read from
kit/platforms/frames.json (`python3 universal.py build` rewrites universal.json from it; the numbers in frames.json carry their own
evidence: Sam's 29 Sep iPhone screenshot for Instagram, the platforms' own safe-zone templates for TikTok and YouTube, Meta's ads guide
for Facebook). Today that is:   x 80-888, y 288-1248, minus the TikTok action column x >= 780 from y 840 down (x0 derives to 120 and is
lowered to 80 by OVERRIDES: see the rationale there and in universal.json).

    sys.path.insert(0, "<v2>/kit/platforms"); import universal
    universal.text_problems(box)        [(severity, kind, detail)] for a text box (master px); FAIL only beyond TOL_PX of the zone
    universal.hero_problems(box)        same for a hero object (image, drawing, card): partly hidden is fine, mostly hidden is not
    universal.level(ID)                 "FAIL" for a short claimed at or after LIVE_FROM, "WARN" for one already in flight
    universal.mass_out(cells)           share of occupied 40-px cells that sit outside the zone (the check that sees objects, not only text)

CLI:  python3 universal.py build | show | level <ID>
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
V2 = os.path.dirname(KIT)
FRAMES = os.path.join(HERE, "frames.json")
UJSON = os.path.join(HERE, "universal.json")
QUEUE = os.path.join(KIT, "registry", "queue.json")
W, H = 1080, 1920
PLATFORMS = ("tiktok", "instagram_reels", "youtube_shorts", "facebook_reels", "linkedin_feed")
TOL_PX = 8          # a text box may touch the zone edge by this much (Vision boxes sit on a 4-px grid, gate.py EDGE_CLIP_PX)
HERO_MIN_AREA = 6000          # px^2: smaller pieces are texture, the mass check counts them
HERO_MAX_AREA = 0.55 * W * H  # a ground or a full-frame panel is the background, not a hero object
HERO_OUT_FRAC = 0.5           # a hero object FAILs when this share of its own area lies outside the zone
MASS_CELL = 40
MASS_BAD = 0.30               # a sample is "off-zone" when more than this share of the picture's occupied cells is outside
MASS_FAIL_SHARE = 0.20        # ... and the short fails when more than this share of its samples are off-zone (WARN above MASS_WARN_SHARE)
MASS_WARN_SHARE = 0.08


def derive(frames=None):
    """-> {"x0","y0","x1","y1","notches":[...], "per_platform":{...}} by rasterising frames.json (1 px exact; the rects are all axis-aligned)."""
    import numpy as np
    f = frames or json.load(open(FRAMES))
    ok = np.ones((H, W), bool)
    per = {}
    for k in PLATFORMS:
        p = f["platforms"][k]
        m = np.zeros((H, W), bool)

        def rect(mm, r, val):
            mm[int(r["y0"]):int(r["y1"]), int(r["x0"]):int(r["x1"])] = val
        rect(m, p["visible"], True)
        if p.get("doc_safe"):
            d = np.zeros((H, W), bool)
            rect(d, p["doc_safe"], True)
            m &= d
        for o in p["overlays"]:
            rect(m, o, False)
        ys, xs = np.where(m)
        per[k] = {"x0": int(xs.min()), "y0": int(ys.min()), "x1": int(xs.max()) + 1, "y1": int(ys.max()) + 1,
                  "free_px": int(m.sum())}
        ok &= m
    ys, xs = np.where(ok)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    # the zone is a rectangle minus rectangular notches: find them as the maximal blocks of the bbox that are NOT free
    notches = []
    prev = None
    for y in range(y0, y1):
        row = np.where(ok[y])[0]
        sig = (int(row.min()), int(row.max()) + 1) if len(row) else None
        if sig != prev:
            if prev is not None and (prev[1] < x1) and notches and notches[-1].get("_open"):
                notches[-1]["y1"] = y
                notches[-1].pop("_open")
            if sig is not None and sig[1] < x1:
                notches.append({"x0": sig[1], "y0": y, "x1": x1, "y1": y1, "_open": True})
            prev = sig
    for n in notches:
        n.pop("_open", None)
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "notches": notches, "per_platform": per}


# Root's decision, 19 Oct 2026 (Sam wants no questions routed to him): the LEFT edge is 80 px, not the derived 120. No platform draws UI on the left
# edge; 120 is TikTok's conservative ad-template side margin (80/720 per side), it blocked every approved short by 20-40 px of text, and 74 (Instagram's
# measured 50 px crop + 24) leaves no margin for screen rounding. Everything else stays derived.
OVERRIDES = {"x0": {"value": 80, "rationale": "No platform draws UI on the left edge. The derived 120 is TikTok's conservative ad-template side margin (80/720 per side) "
                                               "and blocked every approved short by 20-40 px of text; 74 (Instagram measured crop 50 + 24) leaves no margin for "
                                               "screen rounding. Root decision 19 Oct 2026."}}


def build():
    z = derive()
    derived_x0 = z["x0"]
    for k, o in OVERRIDES.items():
        z[k] = o["value"]
    old = {}
    try:
        old = json.load(open(UJSON))
    except (OSError, ValueError):
        pass
    out = {"schema": "agmm-universal-zone-v1",
           "note": "the intersection of the overlay-free areas of TikTok, Instagram Reels, YouTube Shorts, Facebook Reels and LinkedIn vertical "
                   "video at 1080x1920, derived from frames.json by universal.py build. Text and hero objects of every new short stay inside it.",
           "platforms": list(PLATFORMS), "master": [W, H],
           "zone": {k: z[k] for k in ("x0", "y0", "x1", "y1", "notches")},
           "derived_zone_x0": derived_x0,
           "overrides": OVERRIDES,
           "per_platform_free_rect": z["per_platform"],
           "tolerance_px": TOL_PX,
           "live_from": old.get("live_from") or "2026-10-19T17:00:00",
           "live_from_rule": "FAIL for a short whose first claim in registry/queue.json is at or after live_from; WARN for one already in flight "
                             "(claimed earlier) or never claimed. AGMM_UNIVERSAL_ENFORCE=1 forces FAIL, =0 forces WARN."}
    json.dump(out, open(UJSON, "w"), indent=1)
    return out


def load():
    try:
        return json.load(open(UJSON))
    except (OSError, ValueError):
        return build()


def zone():
    return load()["zone"]


def live_from():
    return load()["live_from"]


def _rects(z):
    return [(z["x0"], z["y0"], z["x1"], z["y1"], True)] + [(n["x0"], n["y0"], n["x1"], n["y1"], False) for n in z.get("notches", [])]


def inside_area(box, z=None):
    """area of box (x0,y0,x1,y1) that lies inside the zone."""
    z = z or zone()
    x0, y0, x1, y1 = box
    ix0, iy0, ix1, iy1 = max(x0, z["x0"]), max(y0, z["y0"]), min(x1, z["x1"]), min(y1, z["y1"])
    a = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    for n in z.get("notches", []):
        nx0, ny0, nx1, ny1 = max(ix0, n["x0"]), max(iy0, n["y0"]), min(ix1, n["x1"]), min(iy1, n["y1"])
        a -= max(0, nx1 - nx0) * max(0, ny1 - ny0)
    return max(0, a)


def overshoot(box, z=None):
    """{'left','right','top','bottom','notch'} px by which the box leaves the zone (only positive values). 'notch' is how far a box that sits
    in the notch rows reaches into the action column."""
    z = z or zone()
    x0, y0, x1, y1 = box
    o = {"left": z["x0"] - x0, "right": x1 - z["x1"], "top": z["y0"] - y0, "bottom": y1 - z["y1"]}
    for n in z.get("notches", []):
        if y1 > n["y0"] and y0 < n["y1"] and x1 > n["x0"] and x0 < n["x1"]:
            o["notch"] = max(o.get("notch", 0), x1 - n["x0"])
    return {k: round(v) for k, v in o.items() if v > 0}


def text_problems(box, z=None, tol=None):
    """[(severity, kind, detail)]: FAIL when a text box leaves the universal zone by more than tol px. Boxes wholly off canvas are parked, not shown."""
    z = z or zone()
    tol = TOL_PX if tol is None else tol
    x0, y0, x1, y1 = box
    if x1 <= 0 or x0 >= W or y1 <= 0 or y0 >= H:
        return []
    o = {k: v for k, v in overshoot(box, z).items() if v > tol}
    if not o:
        return []
    where = ", ".join("%s by %d px" % kv for kv in sorted(o.items()))
    return [("FAIL", "universal_text", "outside the universal safe zone (x %d-%d, y %d-%d, no TikTok column): %s" % (
        z["x0"], z["x1"], z["y0"], z["y1"], where))]


def hero_problems(box, z=None):
    """[(severity, kind, detail)] for a hero object: FAIL when at least HERO_OUT_FRAC of its area is outside the zone."""
    z = z or zone()
    x0, y0, x1, y1 = box
    a = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    if a < HERO_MIN_AREA or a > HERO_MAX_AREA:
        return []
    out = 1.0 - inside_area(box, z) / a
    if out >= HERO_OUT_FRAC:
        return [("FAIL", "universal_hero", "%d%% of this object is outside the universal safe zone (under a platform's UI)" % round(out * 100))]
    return []


def cell_allowed(cx, cy, z=None):
    z = z or zone()
    if not (z["x0"] <= cx < z["x1"] and z["y0"] <= cy < z["y1"]):
        return False
    return not any(n["x0"] <= cx < n["x1"] and n["y0"] <= cy < n["y1"] for n in z.get("notches", []))


def mass_out(cells, z=None):
    """cells: iterable of (gx, gy) 40-px cell indices that hold content. -> (outside, total)."""
    z = z or zone()
    tot = out = 0
    for gx, gy in cells:
        tot += 1
        if not cell_allowed(gx * MASS_CELL + MASS_CELL // 2, gy * MASS_CELL + MASS_CELL // 2, z):
            out += 1
    return out, tot


def claimed_at(sid):
    """ISO time of the short's first claim in registry/queue.json, whatever state it is in now; None when it never had one."""
    try:
        e = json.load(open(QUEUE)).get(sid)
    except (OSError, ValueError):
        return None
    if not isinstance(e, dict):
        return None
    return e.get("concept_claimed_at") or e.get("claimed_at") or (e.get("at") if str(e.get("state", "")).startswith("claimed") else None)


def level(sid):
    """"FAIL" (claimed at or after live_from) or "WARN" (in flight, or never claimed)."""
    e = os.environ.get("AGMM_UNIVERSAL_ENFORCE")
    if e is not None:
        return "FAIL" if e == "1" else "WARN"
    at = claimed_at(sid)
    return "FAIL" if (at and at >= live_from()) else "WARN"


def main():
    a = sys.argv[1:]
    if a[:1] == ["build"]:
        print(json.dumps(build(), indent=1))
    elif a[:1] == ["level"] and len(a) > 1:
        print("%s claimed_at=%s live_from=%s -> %s" % (a[1], claimed_at(a[1]), live_from(), level(a[1])))
    else:
        z = zone()
        print("universal zone: x %d-%d, y %d-%d, notches %s, tolerance %d px, live from %s" % (
            z["x0"], z["x1"], z["y0"], z["y1"], [(n["x0"], n["y0"], n["x1"], n["y1"]) for n in z["notches"]], TOL_PX, live_from()))


if __name__ == "__main__":
    main()
