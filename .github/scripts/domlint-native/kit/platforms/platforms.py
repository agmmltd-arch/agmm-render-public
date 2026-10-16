#!/usr/bin/env python3
"""Accessor for kit/platforms/frames.json (row 6, 29 Sep 2026). Import it from compose.py, frame_check.py, frame_mask.py:

    sys.path.insert(0, "<v2>/kit/platforms"); import platforms
    p = platforms.profile("instagram")          # alias -> instagram_reels
    p = platforms.for_short("S33")              # the short's ROUTED platform (jev-v2/fit/routing.json "assignment")
    platforms.text_safe(p)                      # {x0,y0,x1,y1,notches:[...],simple:{...}} in 1080x1920 master px
    platforms.box_problems(p, {"x0":..,"y0":..,"x1":..,"y1":..})   # [] when a text box is safe for that platform
    platforms.js_frame(p)                       # a JS object literal for AGP: {SAFE, NOTCHES, VISIBLE, OVERLAYS, platform}

CLI:  python3 platforms.py S33 | instagram [--js]
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.dirname(os.path.dirname(HERE))
FRAMES = os.path.join(HERE, "frames.json")
ROUTING = os.path.join(V2, "jev-v2", "fit", "routing.json")


def load():
    return json.load(open(FRAMES))


def resolve(name, frames=None):
    f = frames or load()
    key = f["routing_alias"].get(str(name).strip().lower())
    if not key:
        raise KeyError("unknown platform %r (known: %s)" % (name, ", ".join(sorted(f["routing_alias"]))))
    return key


def profile(name, frames=None):
    f = frames or load()
    k = resolve(name, f)
    p = dict(f["platforms"][k]); p["key"] = k
    return p


def routed_platform(short_id):
    try:
        return json.load(open(ROUTING))["assignment"].get(short_id)
    except (OSError, ValueError, KeyError):
        return None


def for_short(short_id, fallback=None):
    r = routed_platform(short_id) or fallback
    return profile(r) if r else None


def text_safe(p):
    return p["text_safe"]


def _overlap(a, b):
    w = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]); h = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
    return max(0, w) * max(0, h)


TOL_FAIL = 8     # px beyond the visible edge before a cut FAILs: Vision reports boxes on a 4-px grid at 1080 (gate.py EDGE_CLIP_PX)
TOL_TOUCH = 4    # 4-8 px beyond it: the first/last glyph touches or loses a sliver -> WARN "touching the crop"


def box_problems(p, box, overlay_frac=0.25):
    """box in master px. Returns a list of (severity, kind, detail). Same rules as frame_check / gate check 2."""
    out = []
    v = p["visible"]
    over = {"left": v["x0"] - box["x0"], "right": box["x1"] - v["x1"], "top": v["y0"] - box["y0"], "bottom": box["y1"] - v["y1"]}
    cut = {k: round(d) for k, d in over.items() if d > TOL_FAIL}
    touch = {k: round(d) for k, d in over.items() if TOL_TOUCH < d <= TOL_FAIL}
    if cut:
        out.append(("FAIL" if p.get("fail_outside_visible") else "WARN", "outside_visible",
                    "cut " + ", ".join("%s by %d px" % kv for kv in cut.items()) + " (%s)" % v["evidence"]))
    elif touch:
        out.append(("WARN", "touching_crop", "touches " + ", ".join("%s edge, %d px over" % kv for kv in touch.items()) +
                    " (%s)" % v["evidence"]))
    area = max(1, (box["x1"] - box["x0"]) * (box["y1"] - box["y0"]))
    for o in p["overlays"]:
        f = _overlap(box, o) / area
        # root 30 Sep 02:20: 25% let '...cost it $380 million' end under Instagram's rail (the key number hidden). A MEASURED
        # overlay hides whatever it covers, so >= 5% of a text box under it fails; estimated overlays keep the 25% warn line.
        if f >= (0.05 if o.get("evidence") == "measured" else overlay_frac):
            # root 29 Sep 21:05, Sam's S59 Instagram screenshot: 'IBM CEO:' under the Reels header and a caption label under
            # the caption/rail passed as WARNs (28 of them). A MEASURED overlay hides text on every phone: FAIL. Only
            # documented/estimated overlays stay WARN.
            sev = "FAIL" if o.get("evidence") == "measured" else "WARN"
            out.append((sev, "under_overlay", "%d%% under %s (%s)" % (round(f * 100), o.get("name", "overlay"), o["evidence"])))
    return out


def js_frame(p):
    ts = p["text_safe"]
    d = {"platform": p["key"], "SAFE": {k: ts[k] for k in ("x0", "y0", "x1", "y1")}, "SIMPLE": ts["simple"],
         "NOTCHES": [{k: n[k] for k in ("x0", "y0", "x1", "y1")} for n in ts["notches"]],
         "VISIBLE": {k: p["visible"][k] for k in ("x0", "y0", "x1", "y1")},
         "OVERLAYS": [{k: o[k] for k in ("x0", "y0", "x1", "y1")} for o in p["overlays"]]}
    return json.dumps(d, separators=(",", ":"))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    a = sys.argv[1]
    p = for_short(a) if routed_platform(a) else profile(a)
    if "--js" in sys.argv:
        print(js_frame(p))
    else:
        ts = p["text_safe"]
        print("%s -> %s  visible %s (%s)  text_safe x %d-%d y %d-%d  notches %s" % (
            a, p["key"], {k: p["visible"][k] for k in ("x0", "y0", "x1", "y1")}, p["visible"]["evidence"],
            ts["x0"], ts["x1"], ts["y0"], ts["y1"], [(n["x0"], n["y0"]) for n in ts["notches"]]))
