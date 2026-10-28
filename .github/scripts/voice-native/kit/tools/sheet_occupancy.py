#!/usr/bin/env python3
"""sheet_occupancy.py <ID> [--json] [--frames snap|sheet] | --report ID ID ...   (20 Oct 2026, root's gate on S136)

Why: S136 (an engine short) passed every gate and was returned by root as a slideshow: the same figure and a small white card on a flat ground, content in the top 40% of the
frame, the rest empty colour. sheet_check's FILL/VARIETY read colour, so a flat ground that changes colour from beat to beat still "varies". These checks read LAYOUT: what part
of the frame is EMPTY (large flat regions of any colour) and what is not, beat to beat. An EMPTY block is one of 6 px (at 270x480) with std < 4 that belongs to a connected flat
region of 40 or more blocks, whatever its colour: a coloured sheet, a plain desk and an empty panel are all empty; text, objects, edges, gradients with texture and a map's
coastlines are content.

  OCCUPANCY  per beat, the share of the frame that is content (median over beats, and the lower half of the frame on its own: "content in the top 40%, the rest empty colour").
             FAIL when the median beat is under OCC_MEDIAN_MIN or the median lower half under LOWER_MEDIAN_MIN, or more than OCC_LOW_FRAC of the beats are under OCC_LOW
             (the CTA beat: OCC_LOW_CTA).
  DISTINCT   each beat's content mask. Neighbouring beats are NEAR-IDENTICAL when the masks overlap at IoU >= DISTINCT_IOU (colour is ignored: an alternating ground colour is not a
             new layout). FAIL on a run of RUN_MAX or more beats whose neighbours are all near-identical.
  SCALE      the largest connected content element of each beat as a share of the frame; FAIL when the median beat is under SCALE_MEDIAN_MIN.

Frames are the storyboard's own (out/<ID>/snap beat-middle frames, else the tiles of registry/storyboards/<ID>-storyboard.jpg), normalised to 270x480 like sheet_check.
Floors were set on 20 Oct from the approved sheets and the two bars (S05, S56) so that S136 fails and S05 and S56 pass; `--report` prints the numbers for any shorts so the floors can be
audited, and the review note records that the DISTINCT floor, which S05 and S56 clear, is cleared by only a few older approved shorts: it gates ENGINE shorts only (precheck_all).
No browser, no render, no model.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sheet_check as SC       # noqa: E402

BS = 6                       # block size in px at 270x480
FLAT_STD = 4.0
FLAT_REGION = 40             # blocks: a flat region this big is EMPTY
OCC_MEDIAN_MIN = 0.33
LOWER_MEDIAN_MIN = 0.30
OCC_LOW = 0.20
OCC_LOW_CTA = 0.15
OCC_LOW_FRAC = 0.20
DISTINCT_IOU = 0.50
RUN_MAX = 4
SCALE_MEDIAN_MIN = 0.18
OBJ_FILL_MEDIAN_MIN = 0.30       # engine shorts (dark worlds): the object pixels cover this share of the safe zone under the headline, median beat
OBJ_LARGEST_MEDIAN_MIN = 0.22
HEADLINE_MEDIAN_MIN = 100        # px: the body headline of an engine short is 2-5 words at 100-120 px (S05: SEPARATING ITS IT / ASDA'S PRE-TAX LOSS)
OBJ_WIDTH_MEDIAN_MIN = 0.55      # share of the 808 px safe-zone width covered by the beat's object (S05's tag, plate, bars)
OBJ_CENTER_Y = (650, 1000)       # centre of mass of the object on beats whose headline is on top. Beats whose headline is set low (layout slot, 26 Oct) have the object above it by construction (format_engine slot_checks), so they are not judged here       # centre of mass of the object: mid-frame, not tucked under the headline
HERO_MIDDLE_MAX = 2              # beats (after frame 0, before the loop end) whose main object is the hero tag    # ... and the largest single object covers this share


def _np():
    import numpy as np
    return np


def _label4(m):
    np = _np()
    lab = np.zeros(m.shape, dtype=int)
    sizes, n = {}, 0
    for y in range(m.shape[0]):
        for x in range(m.shape[1]):
            if m[y, x] and not lab[y, x]:
                n += 1
                st, c = [(y, x)], 0
                lab[y, x] = n
                while st:
                    cy, cx = st.pop()
                    c += 1
                    for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                        if 0 <= ny < m.shape[0] and 0 <= nx < m.shape[1] and m[ny, nx] and not lab[ny, nx]:
                            lab[ny, nx] = n
                            st.append((ny, nx))
                sizes[n] = c
    return lab, sizes


def content_mask(img):
    """bool grid (rows x cols) of CONTENT blocks for one 270x480 PIL image"""
    np = _np()
    g = np.asarray(img.convert("L"), dtype=float)
    H, W = (g.shape[0] // BS) * BS, (g.shape[1] // BS) * BS
    b = g[:H, :W].reshape(H // BS, BS, W // BS, BS).swapaxes(1, 2).reshape(H // BS, W // BS, -1)
    flat = b.std(axis=2) < FLAT_STD
    lab, sz = _label4(flat)
    empty = np.zeros(flat.shape, dtype=bool)
    for k, c in sz.items():
        if c >= FLAT_REGION:
            empty |= (lab == k)
    return ~empty


def load_data(ID):
    """the display list of an engine short (specs/<ID>/scenes.js FMT_DATA), or None"""
    import re as _re
    p = os.path.join(KIT, "specs", ID, "scenes.js")
    try:
        t = open(p, encoding="utf-8").read()
        m = _re.search(r"window\.FMT_DATA = (\{.*\});\n", t)
        return json.loads(m.group(1)) if m else None
    except (OSError, ValueError):
        return None


def data_checks(D):
    """-> (fails, numbers). HEADLINE: median body headline px; OBJECT WIDTH / CENTRE: the object of every span (rects, images, paths, bars; the hero tag spans use the tag's own key); HERO TAG: middle beats whose object is the hero tag."""
    np = _np()
    fails = []
    spans = D.get("spans") or []
    heads = [it["fs"] for it in D["items"] if it.get("head") and any(sp["t_in"] - 0.01 <= it["ti"] < sp["t_out"] for sp in spans)]
    med_h = float(np.median(heads)) if heads else 0.0
    if heads and med_h < HEADLINE_MEDIAN_MIN:
        fails.append("HEADLINE: the median body headline is %.0f px (floor %d): a 2 to 5 word headline at 100 to 120 px, not the spoken clause at 60 to 76 px." % (med_h, HEADLINE_MEDIAN_MIN))
    tk = D["tag"]["keys"]
    widths, centers = [], []
    for b_ in (D.get("beats") or []):
        if b_.get("obj"):
            ob_ = b_["obj"]
            widths.append((ob_[2] - ob_[0]) / 808.0)
            if str(b_.get("head", "top")).startswith("top"):
                centers.append((ob_[1] + ob_[3]) / 2.0)
    for sp in ([] if widths else spans):
        xs0, ys0, xs1, ys1 = [], [], [], []
        if sp["kind"] == "price_tag":
            k = [k_ for k_ in tk if k_["t"] <= sp["t_in"] + 0.9][-1]
            xs0, ys0, xs1, ys1 = [k["x"]], [k["y"]], [k["x"] + k["w"]], [k["y"] + k["h"]]
        else:
            for it in D["items"]:
                if it.get("obj") != sp["i"]:
                    continue
                if it["k"] in ("rect", "img", "path"):
                    xs0.append(it["x"]); ys0.append(it["y"]); xs1.append(it["x"] + it["w"]); ys1.append(it["y"] + it["h"])
                elif it["k"] == "bars":
                    for b in it["bars"]:
                        xs0.append(b["x"]); xs1.append(b["x"] + b["w"]); ys0.append(it["base"] - b["h"] - b["numfs"]); ys1.append(it["base"] + 66)
        if xs0:
            widths.append((max(xs1) - min(xs0)) / 808.0)
            centers.append((min(ys0) + max(ys1)) / 2.0)
    med_w = float(np.median(widths)) if widths else 0.0
    med_c = float(np.median(centers)) if centers else 0.0
    if widths and med_w < OBJ_WIDTH_MEDIAN_MIN:
        fails.append("OBJECT WIDTH: the median object covers %.0f%% of the safe-zone width (floor %.0f%%; S05's tag, plate and bars run 55 to 70%%)." % (100 * med_w, 100 * OBJ_WIDTH_MEDIAN_MIN))
    if centers and not OBJ_CENTER_Y[0] <= med_c <= OBJ_CENTER_Y[1]:
        fails.append("OBJECT CENTRE: the median object is centred at y %.0f (needs %d to %d): mid-frame, not tucked under the headline." % (med_c, OBJ_CENTER_Y[0], OBJ_CENTER_Y[1]))
    bt = D.get("beats") or []
    end = max([sp["t_out"] for sp in spans] or [0])
    hero = 0
    for b in bt[1:]:
        mid = (b["t0"] + b["t1"]) / 2.0
        if mid >= end or mid < (spans[0]["t_in"] if spans else 0):
            continue
        k = [k_ for k_ in tk if k_["t"] <= mid][-1]
        if k["y"] < 1000:
            hero += 1
    if hero > HERO_MIDDLE_MAX:
        fails.append("HERO TAG: the hero tag is the main object of %d middle beats (max %d: frame 0, the beats where the voice says the figure, the loop end; the chip everywhere else)." % (hero, HERO_MIDDLE_MAX))
    return fails, {"headline_median": med_h, "obj_width_median": round(med_w, 3), "obj_center_median": round(med_c, 1), "hero_middle_beats": hero}


def object_mask(img):
    """bool grid (6 px blocks) of OBJECT blocks for a frame of a dark-world engine short: the WORLD (map, desk, inbox ... : dark, low contrast) counts as ground, whatever its texture.
    A block is object when a quarter of its pixels are bright (luminance > 150) or vivid (saturation > 0.5 and luminance > 90); enclosed holes are filled (a dark panel with a bright border and a
    figure is one object). Only meaningful for the engine's dark worlds."""
    np = _np()
    a = np.asarray(img.convert("RGB"), dtype=float)
    mx, mn = a.max(axis=2), a.min(axis=2)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    med = float(np.median(lum))
    if med > 140:                         # a LIGHT world (warm paper): objects are what departs from the paper, dark cards, accent, shadows
        px = (np.abs(lum - med) > 55) | ((sat > 0.55) & (np.abs(lum - med) > 25))
    else:
        px = (lum > 150) | ((sat > 0.5) & (lum > 90))
    H, W = (px.shape[0] // BS) * BS, (px.shape[1] // BS) * BS
    m = px[:H, :W].reshape(H // BS, BS, W // BS, BS).mean(axis=(1, 3)) > 0.25
    # dilate once so letter gaps close, then fill every hole not reachable from the frame border
    p = np.pad(m, 1)
    d = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            d |= p[1 + dy:1 + dy + m.shape[0], 1 + dx:1 + dx + m.shape[1]]
    out = ~d
    reach = np.zeros(m.shape, dtype=bool)
    st = [(y, x) for y in range(m.shape[0]) for x in range(m.shape[1]) if (y in (0, m.shape[0] - 1) or x in (0, m.shape[1] - 1)) and out[y, x]]
    for y, x in st:
        reach[y, x] = True
    while st:
        cy, cx = st.pop()
        for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
            if 0 <= ny < m.shape[0] and 0 <= nx < m.shape[1] and out[ny, nx] and not reach[ny, nx]:
                reach[ny, nx] = True
                st.append((ny, nx))
    return ~reach


ZONE = (139, 312, 20, 222)        # rows / cols (6 px blocks at 270x480) of the safe zone under the headline: y 556-1248, x 80-888


def object_fill(frames, zones=None):
    """share of each beat's object zone covered by object pixels; zones[i] = (y0, y1) rows the beat's object may sit in (the layout slot), else the default band under a top headline"""
    np = _np()
    fills, largest = [], []
    for fi_, f in enumerate(frames):
        m = object_mask(f["img"])
        zy = zones[fi_] if zones and fi_ < len(zones) and zones[fi_] else None
        r0, r1, c0, c1 = int((zy[0] / 4.0 if zy else ZONE[0]) / BS), int((zy[1] / 4.0 if zy else ZONE[1]) / BS), int(ZONE[2] / BS), int(ZONE[3] / BS)
        z = m[r0:r1, c0:c1]
        fills.append(float(z.mean()))
        lab, n = SC._label8(z)
        largest.append(max([int((lab == k).sum()) for k in range(1, n + 1)] or [0]) / float(z.size))
    return fills, largest


def largest_region(m):
    """size of the biggest 8-connected region of True blocks"""
    np = _np()
    lab, n = SC._label8(m)
    if n == 0:
        return 0
    return int(max(((lab == k).sum() for k in range(1, n + 1))))


def iou(a, b):
    u = (a | b).sum()
    return float((a & b).sum()) / u if u else 1.0


def measure(frames):
    masks = [content_mask(f["img"]) for f in frames]
    occ = [float(m.mean()) for m in masks]
    lower = [float(m[m.shape[0] // 2:].mean()) for m in masks]
    scale = [largest_region(m) / float(m.size) for m in masks]
    ious = [iou(masks[i], masks[i + 1]) for i in range(len(masks) - 1)]
    runs, cur = [], 0                 # n near-identical neighbour pairs in a row = n + 1 beats
    for i, v in enumerate([x >= DISTINCT_IOU for x in ious] + [False]):
        if v:
            cur += 1
        else:
            if cur + 1 >= RUN_MAX:
                runs.append((i - cur, i))       # beats i-cur .. i inclusive
            cur = 0
    return {"occ": occ, "lower": lower, "scale": scale, "runs": runs, "iou": [round(x, 2) for x in ious]}


def check(ID, source="auto", engine=True):
    np = _np()
    beats = SC._beats(ID)
    frames, how = SC.load_frames(ID, source)
    mm = measure(frames)
    n = len(frames)
    fails, bl = [], []
    stale = SC.snap_staleness(ID, how)
    warns = [stale] if stale else []

    def beat_fail(i, msg):
        b = beats[i]
        bl.append({"i": i, "id": b.get("id"), "t": round(float(b["from"]), 2), "text": msg})
    med_occ = float(np.median(mm["occ"]))
    med_low = float(np.median(mm["lower"]))
    lows = [i for i, o in enumerate(mm["occ"]) if o < (OCC_LOW_CTA if i == n - 1 else OCC_LOW)]
    bad_occ = False
    occ_fails = []
    if med_occ < OCC_MEDIAN_MIN:
        bad_occ = True
        occ_fails.append("OCCUPANCY: the median beat has %.0f%% of the frame as content (floor %.0f%%; S05 holds 42%%): the rest is empty flat colour. Put a world, an object or a headline in the empty part of every beat." % (100 * med_occ, 100 * OCC_MEDIAN_MIN))
    if med_low < LOWER_MEDIAN_MIN:
        bad_occ = True
        occ_fails.append("OCCUPANCY: the median lower half of the frame is %.0f%% content (floor %.0f%%; S05 holds 35%%): content sits in the top of the frame and the rest is empty colour." % (100 * med_low, 100 * LOWER_MEDIAN_MIN))
    if len(lows) > OCC_LOW_FRAC * n:
        bad_occ = True
        occ_fails.append("OCCUPANCY: %d of %d beats are under %.0f%% content (max %.0f%% of the beats)." % (len(lows), n, 100 * OCC_LOW, 100 * OCC_LOW_FRAC))
    if engine:
        # an engine short has a CLEAN world (one flat plane, root's 21 Oct rule): flat colour is the ground by design, so the judge is the OBJECT metrics below (object pixels, object width,
        # headline px, hero-tag beats), not how much of the frame is textured. The textured-frame numbers stay in the report.
        bad_occ = False
    else:
        fails.extend(occ_fails)
    if bad_occ:
        for i in lows:
            beat_fail(i, "OCCUPANCY: only %.0f%% of this beat's frame carries anything. Fill it: the world map behind, the object at picture scale." % (100 * mm["occ"][i]))
    runs = mm["runs"]
    if engine:                       # the close (verdict, then the question card) is text-led by DIRECTOR's ordering: DISTINCT judges the body beats before it
        vi = next((i for i, b_ in enumerate(beats) if b_.get("id") == "verdict"), None)
        if vi is not None:
            runs = [(a_, min(b_, vi - 1)) for a_, b_ in runs if a_ < vi - 1 and min(b_, vi - 1) - a_ + 1 >= RUN_MAX]
    for a, b in runs:
        fails.append("DISTINCT: beats %d to %d (%s..%s) have the same layout (content masks overlap at IoU >= %.2f in every neighbouring pair): %d beats in a row that differ only in colour or words. "
                     "Give each beat its own object in its own place." % (a, b, beats[a].get("id"), beats[b].get("id"), DISTINCT_IOU, b - a + 1))
        for i in range(a, b + 1):
            beat_fail(i, "DISTINCT: this beat repeats the layout of its neighbours.")
    D0 = load_data(ID) if engine else None
    zones = None
    if D0 and D0.get("beats"):
        bz = [b_.get("zone") for b_ in D0["beats"]]
        zones = bz[1:-1] if n > 4 else bz
    ofill, olarge = object_fill(frames[1:-1] if n > 4 else frames, zones)
    med_of, med_ol = float(np.median(ofill)), float(np.median(olarge))
    if engine and med_of < OBJ_FILL_MEDIAN_MIN:
        fails.append("OBJECT: the object pixels (the world counts as ground) cover %.0f%% of the safe zone under the headline in the median beat (floor %.0f%%): the story object must sit mid-frame at hero scale." % (100 * med_of, 100 * OBJ_FILL_MEDIAN_MIN))
    if engine and med_ol < OBJ_LARGEST_MEDIAN_MIN:
        fails.append("OBJECT: the largest object covers %.0f%% of the safe zone in the median beat (floor %.0f%%): scale it up." % (100 * med_ol, 100 * OBJ_LARGEST_MEDIAN_MIN))
    dfails, dnum = [], {}
    if engine:
        D = D0
        if D:
            dfails, dnum = data_checks(D)
            fails.extend(dfails)
    med_sc = float(np.median(mm["scale"]))
    if med_sc < SCALE_MEDIAN_MIN:
        fails.append("SCALE: the median beat's largest element is %.0f%% of the frame (floor %.0f%%): no beat has an object at picture scale; everything is a small card." % (100 * med_sc, 100 * SCALE_MEDIAN_MIN))
    return {"id": ID, "ok": not fails, "frames": how, "fails": fails, "warns": warns, "stale_snap": stale, "beats": bl, "n": n, "occ_median": round(med_occ, 3), "occ_min": round(min(mm["occ"]), 3), "lower_median": round(med_low, 3), "data": dnum, "obj_fill_median": round(med_of, 3), "obj_largest_median": round(med_ol, 3),
            "occ_low_beats": lows, "scale_median": round(med_sc, 3), "runs": mm["runs"], "occ": [round(x, 2) for x in mm["occ"]], "scale": [round(x, 2) for x in mm["scale"]], "iou": mm["iou"]}


def selftest():
    """synthetic dark-world frames: a small bright card in the top 40% FAILS the object test, a picture-scale card passes (the check can fail)"""
    from PIL import Image, ImageDraw
    import random
    random.seed(3)

    def frame(card):
        im = Image.new("RGB", (270, 480), (36, 20, 46))
        d = ImageDraw.Draw(im)
        for _ in range(40):                                  # world texture: dim shapes, never bright
            x, y = random.randint(0, 230), random.randint(0, 440)
            d.rectangle([x, y, x + random.randint(20, 60), y + random.randint(10, 40)], fill=(70, 52, 84))
        d.rectangle(card, fill=(245, 236, 216))
        return {"img": im}
    small = [frame((20, 70, 150, 130)) for _ in range(8)]
    big = [frame((22, 150, 200, 290)) for _ in range(8)]
    fs, ls = object_fill(small)
    fb, lb = object_fill(big)
    ok1 = max(fs) < OBJ_FILL_MEDIAN_MIN or max(ls) < OBJ_LARGEST_MEDIAN_MIN
    ok2 = min(fb) >= OBJ_FILL_MEDIAN_MIN and min(lb) >= OBJ_LARGEST_MEDIAN_MIN
    print("%s small card in the top 40%%: object fill %.2f largest %.2f (floors %.2f / %.2f): fails as it must" % ("PASS" if ok1 else "FAIL", max(fs), max(ls), OBJ_FILL_MEDIAN_MIN, OBJ_LARGEST_MEDIAN_MIN))
    print("%s picture-scale card mid-frame: object fill %.2f largest %.2f: passes" % ("PASS" if ok2 else "FAIL", min(fb), min(lb)))
    # display-list checks: a bad list fails all three, a good one passes
    bad = {"items": [dict(k="text", id="t1", head=True, fs=70, ti=1.0, lines=["X"], x=80, y=296, w=780)] + [dict(k="rect", id="r%d" % i, obj=i, x=200, y=700, w=150, h=120, ti=1, to=2) for i in range(3)],
           "spans": [dict(i=i, kind="counter", t_in=1.0 + 3 * i, t_out=3.5 + 3 * i) for i in range(3)], "tag": {"keys": [dict(t=0, x=80, y=700, w=500, h=370)]},
           "beats": [dict(id="b%d" % i, t0=1.2 * i, t1=1.2 * i + 1.2) for i in range(8)]}
    f1, n1 = data_checks(bad)
    good = {"items": [dict(k="text", id="t1", head=True, fs=110, ti=1.0, lines=["X"], x=80, y=296, w=780)] + [dict(k="rect", id="r%d" % i, obj=i, x=90, y=620, w=680, h=420, ti=1, to=2) for i in range(3)],
            "spans": bad["spans"], "tag": {"keys": [dict(t=0, x=80, y=700, w=500, h=370), dict(t=0.5, x=440, y=1076, w=340, h=160)]}, "beats": bad["beats"]}
    f2, n2 = data_checks(good)
    ok3 = len(f1) >= 3 and not f2
    herob = dict(good, tag={"keys": [dict(t=0, x=80, y=700, w=500, h=370)]})
    f3, _ = data_checks(herob)
    ok4 = any("HERO TAG" in x for x in f3)
    print("%s headline 70 px, object 150 px wide, hero tag on 5 beats: %d failures raised (%s); a good list raises none" % ("PASS" if ok3 else "FAIL", len(f1), ", ".join(x.split(":")[0] for x in f1)))
    print("%s the hero tag on every beat is caught" % ("PASS" if ok4 else "FAIL"))
    return 0 if ok1 and ok2 and ok3 and ok4 else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    ap = argparse.ArgumentParser()
    ap.add_argument("id", nargs="*")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--frames", default="auto", choices=("auto", "snap", "sheet"))
    ap.add_argument("--report", action="store_true", help="one line of numbers per ID, no exit code")
    a = ap.parse_args()
    if a.report:
        for sid in a.id:
            try:
                r = check(sid, a.frames)
            except Exception as e:
                print("%-6s error: %s" % (sid, e))
                continue
            print("%-6s %-4s n=%2d occ median %.2f min %.2f lower-half %.2f low-beats %d | scale median %.2f | object fill %.2f largest %.2f | near-identical runs %s" %
                  (sid, "PASS" if r["ok"] else "FAIL", r["n"], r["occ_median"], r["occ_min"], r["lower_median"], len(r["occ_low_beats"]), r["scale_median"], r["obj_fill_median"], r["obj_largest_median"], r["runs"] or "none"))
        return 0
    try:
        r = check(a.id[0], a.frames)
    except Exception as e:
        print("sheet_occupancy: tool error: %s" % e, file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(r, indent=1, default=str))
    else:
        print("sheet_occupancy %s: %s (frames from %s)" % (r["id"], "PASS" if r["ok"] else "FAIL", r["frames"]))
        if r.get("stale_snap"):
            print("  " + r["stale_snap"])
        print("  occupancy per beat: " + " ".join("%.2f" % x for x in r["occ"]))
        print("  display list: %s" % (r.get("data") or "n/a"))
        print("  object fill %.2f (floor %.2f), largest object %.2f (floor %.2f)" % (r["obj_fill_median"], OBJ_FILL_MEDIAN_MIN, r["obj_largest_median"], OBJ_LARGEST_MEDIAN_MIN))
        print("  median %.2f (floor %.2f), lower half %.2f (floor %.2f), min %.2f, %d beats under %.2f | largest element median %.2f (floor %.2f) | near-identical runs of %d+: %s" %
              (r["occ_median"], OCC_MEDIAN_MIN, r["lower_median"], LOWER_MEDIAN_MIN, r["occ_min"], len(r["occ_low_beats"]), OCC_LOW, r["scale_median"], SCALE_MEDIAN_MIN, RUN_MAX, r["runs"] or "none"))
        for m in r["fails"]:
            print("  FAIL " + m)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
