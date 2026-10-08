#!/usr/bin/env python3
"""sheet_check.py <ID> [--json] [--frames snap|sheet] | --calibrate   (forge2 v2 card, 6 Oct 2026)

Deterministic checks on the beat frames of a short, written because forge2's first two shorts (S85, S07) passed every existing
gate and root rated S85 3/10: the same module wall on every beat, empty panels, no new object per beat. Frames come from
out/<ID>/snap/*/frame-*-at-*s.jpg (the storyboard's own beat-middle snaps) or, when those are gone, from the tiles of
registry/storyboards/<ID>-storyboard.jpg. Both are normalised to 270x480 before any measurement, so a number means the same
thing from either source. No browser, no render, no model.

  BACKDROP  (forge2 v3) the convex hull of each beat's biggest compact solid-colour region that is disc or badge shaped (fills 60-88% of its box, about as wide as tall, does
            not span the frame); beats whose hulls overlap at IoU >= BD_IOU form a group; FAIL when the largest group is over BD_SHARE_MAX of the beats.
  LONE      (forge2 v4) a beat is LONE when its picture is one object on ground with no texture of its own (under LONE_GROUND_DETAIL of the blocks outside the object's box are textured); FAIL when over LONE_MAX of the beats are
            LONE and the short has no persistent world (under LONE_FURN_MIN of the picture is textured at the same place in 60% of the beats).
  VARIETY   each beat's picture area (everything under the top 28% headline band) is reduced to a 6x10 colour grid. A beat has a
            TWIN when another beat is within TWIN_D of it. FAIL when the median nearest-neighbour distance is under NN_MEDIAN_MIN
            (the beats are the same wall seen again), or more than PAIR_FRAC_MAX of all beat pairs are near-duplicates, or any
            three consecutive beats are mutually near-duplicates.
  FILL      the picture area is cut into 10 px blocks; a block is CONTENT when it has texture (std) or differs from the frame's
            median colour. A beat is EMPTY when its content share is under FILL_FLOOR, or when one flat rectangle (connected flat
            blocks) covers more than FLAT_MAX of the picture area while content is under FLAT_FILL_MAX. The last beat (the CTA card
            on a plain ground) uses CTA_FILL_FLOOR.
  HERO      from out/<ID>/domlint/raw.json: the largest shown text line (DOM px, after camera) in each beat. FAIL when the hook beat
            (first two beats) has no line >= HOOK_HERO_PX, or fewer than HERO_BEAT_FRAC of beats carry a line >= HERO_PX.
  SOURCE    from the same raw.json plus the built package: text inside a source-card image, measured as dom_lint does (ink line in
            the file x display scale). FAIL under SRC_FAIL_PX (dom_lint's own FAIL line), WARN under SRC_WARN_PX.
Constants below are calibrated on registry/storyboards (51 approved sheets) and the 38 shorts that have domlint data; `--calibrate`
prints the evidence. Exit 1 on FAIL, 2 on a tool error. Library: `check(ID) -> {"ok", "fails", "warns", "beats", ...}` with one
"beat" entry (index, id, time, text) per failure so a maker can be sent back to the beat that owns it."""
import argparse, glob, json, os, re, sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(KIT, "registry", "storyboards")
TW, TH = 270, 480
BAND = 0.28            # top share of the frame left to the headline: measurements use the picture area below it

# ---- calibrated constants (see --calibrate; S85 4.1 / S07 4.5 vs post-6-Oct approved min 7.2)
TWIN_D = 7.0
NN_MEDIAN_MIN = 6.0
PAIR_D = 5.0
PAIR_FRAC_MAX = 0.35
RUN_D = 3.0
FILL_FLOOR = 0.15
CTA_FILL_FLOOR = 0.10
FLAT_MAX = 0.75
FLAT_FILL_MAX = 0.30
HOOK_HERO_PX = 100
HERO_PX = 80
HERO_BEAT_FRAC = 0.60
HERO180_PX = 180          # forge2 v3: at least HERO180_N beats carry a line this big (approved min 3: S72; S85 v2 has 1, S07 v2 2)
HERO180_N = 3
SRC_FAIL_PX = 30.0
SRC_WARN_PX = 36.0


def _np():
    import numpy as np
    from PIL import Image
    return np, Image


# ------------------------------------------------------------------------------------------------- frames
def _beats(ID):
    r = json.load(open(os.path.join(KIT, "out", ID, "resolved.json")))
    return r.get("beats", r) if isinstance(r, dict) else r


def _sheet_tiles(ID):
    np, Image = _np()
    p = os.path.join(REG, ID + "-storyboard.jpg")
    im = Image.open(p).convert("RGB")
    W, H = im.size
    rows = H // TH if H % TH == 0 else (H - 44) // 2 // TH
    out = []
    for r in range(rows):
        for c in range(W // TW):
            t = im.crop((c * TW, r * TH, (c + 1) * TW, (r + 1) * TH))
            if np.asarray(t).std() < 2.5:        # the black filler at the end of the last row
                continue
            out.append(t)
    return out


def load_frames(ID, source="auto"):
    """-> (list of {i, id, t, img (PIL 270x480)}, how). One frame per beat, in beat order."""
    np, Image = _np()
    beats = _beats(ID)
    mids = [(float(b["from"]) + float(b["to"])) / 2.0 for b in beats]
    if source in ("auto", "snap"):
        cand = {}
        try:        # snap frame names carry PART-LOCAL seconds (S85-B frame-03-at-9.87s is story time 14.8 + 9.87)
            off = {p["out"]: float(p["off"]) for p in json.load(open(os.path.join(KIT, "out", ID, "build", "parts.json")))["parts"]}
        except Exception:
            off = {}
        for f in glob.glob(os.path.join(KIT, "out", ID, "snap", "*", "frame-*-at-*s.jpg")):
            m = re.search(r"-at-([0-9.]+)s\.jpg$", f)
            if m:
                t = round(float(m.group(1)) + off.get(os.path.basename(os.path.dirname(f)), 0.0), 2)
                if t not in cand or os.path.getmtime(f) > os.path.getmtime(cand[t]):
                    cand[t] = f
        got = []
        for i, b in enumerate(beats):
            ts = [t for t in cand if float(b["from"]) <= t < float(b["to"])]
            if not ts:
                got = None
                break
            t = min(ts, key=lambda x: abs(x - mids[i]))
            got.append({"i": i, "id": b.get("id"), "t": t, "img": Image.open(cand[t]).convert("RGB").resize((TW, TH))})
        if got:
            return got, "snap"
        if source == "snap":
            raise RuntimeError("no complete snap frames for %s (one per beat) under out/%s/snap" % (ID, ID))
    tiles = _sheet_tiles(ID)
    if len(tiles) == len(beats) + 1:
        tiles = tiles[1:]                 # the 0.1 s hook frame comes first
    if len(tiles) != len(beats):
        raise RuntimeError("sheet has %d tiles for %d beats" % (len(tiles), len(beats)))
    return [{"i": i, "id": b.get("id"), "t": round(mids[i], 2), "img": tiles[i]} for i, b in enumerate(beats)], "sheet"


# ------------------------------------------------------------------------------------------------- measures
def _picture(img):
    np, _ = _np()
    a = np.asarray(img)
    return a[int(a.shape[0] * BAND):]


def grid_feature(img):
    np, Image = _np()
    return np.asarray(Image.fromarray(_picture(img)).resize((6, 10), Image.BOX), dtype=float)


def variety(frames):
    np, _ = _np()
    F = [grid_feature(f["img"]) for f in frames]
    n = len(F)
    D = np.full((n, n), 1e9)
    for i in range(n):
        for j in range(n):
            if i != j:
                D[i, j] = np.abs(F[i] - F[j]).mean()
    nn = D.min(axis=1)
    pairs = D[np.triu_indices(n, 1)]
    pair_frac = float((pairs < PAIR_D).mean()) if len(pairs) else 0.0
    twins = [int(i) for i in range(n) if nn[i] < TWIN_D]
    run3 = [i for i in range(n - 2) if D[i, i + 1] < RUN_D and D[i + 1, i + 2] < RUN_D and D[i, i + 2] < RUN_D]
    return {"n": n, "nn_median": round(float(np.median(nn)), 2), "twin_frac": round(len(twins) / float(n), 2), "pair_frac": round(pair_frac, 3),
            "run3_at": run3, "nn": [round(float(x), 1) for x in nn], "twins": twins}


def fill_of(img):
    """-> (content share, largest flat rectangle share) of the picture area."""
    np, Image = _np()
    g = np.asarray(Image.fromarray(_picture(img)).convert("L"), dtype=float)
    bs = 10
    H, W = (g.shape[0] // bs) * bs, (g.shape[1] // bs) * bs
    b = g[:H, :W].reshape(H // bs, bs, W // bs, bs).swapaxes(1, 2)
    std = b.reshape(H // bs, W // bs, -1).std(axis=2)
    mean = b.reshape(H // bs, W // bs, -1).mean(axis=2)
    med = float(np.median(mean))
    content = (std > 7) | (np.abs(mean - med) > 25)
    flat = (std < 4) & ~content
    # largest 4-connected flat component
    seen = np.zeros_like(flat, dtype=bool)
    best = 0
    for y in range(flat.shape[0]):
        for x in range(flat.shape[1]):
            if flat[y, x] and not seen[y, x]:
                stack, cnt = [(y, x)], 0
                seen[y, x] = True
                while stack:
                    cy, cx = stack.pop()
                    cnt += 1
                    for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                        if 0 <= ny < flat.shape[0] and 0 <= nx < flat.shape[1] and flat[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
                best = max(best, cnt)
    return float(content.mean()), best / float(flat.size)


def hero_per_beat(ID):
    raw_p = os.path.join(KIT, "out", ID, "domlint", "raw.json")
    if not os.path.exists(raw_p):
        return None
    raw = json.load(open(raw_p))
    parts = json.load(open(os.path.join(KIT, "out", ID, "build", "parts.json")))["parts"]
    off = {p["out"]: p["off"] for p in parts}
    S = []
    for part, d in raw["parts"].items():
        for s in d["samples"]:
            mx = 0
            for T in s["texts"]:
                if T["op"] <= 0.6 or T["vis"] < 0.5 or (T.get("occ") is not None and T["occ"] >= 0.6):
                    continue
                ink = T["ink"][0]
                if ink[2] < 0 or ink[0] > 1080 or ink[3] < 0 or ink[1] > 1920 or T["fpx"] < 10:
                    continue
                if not re.search(r"[A-Za-z0-9]", T["t"] or ""):
                    continue
                mx = max(mx, T["fpx"])
            S.append((off.get(part, 0) + s["t"], mx))
    S.sort()
    out = []
    for b in _beats(ID):
        f, t = float(b["from"]), float(b["to"])
        v = [m for (T, m) in S if f + 0.35 <= T <= t - 0.05]
        out.append(max(v) if v else 0)
    return out


def source_px(ID):
    """{src basename: (min on-screen ink-line px over its visible samples)} for source-card images."""
    raw_p = os.path.join(KIT, "out", ID, "domlint", "raw.json")
    if not os.path.exists(raw_p):
        return None
    sys.path.insert(0, os.path.join(KIT, "tools"))
    import dom_lint as D
    raw = json.load(open(raw_p))
    res = {}
    for part, d in raw["parts"].items():
        look = d.get("look", "")
        for s in d["samples"]:
            for im in s["imgs"]:
                win = im.get("cut") or im["box"]
                if im["op"] <= 0.5 or im["k"] <= 0 or D.area(win) < 0.012 * 1080 * 1920 or D.onframe_frac([win]) < 0.5:
                    continue
                f = os.path.join(KIT, "out", ID, "build", "pkg", look, im["src"].split("?")[0])
                if not os.path.exists(f):
                    continue
                ih = D.image_text_height(f)
                if not ih:
                    continue
                if win[2] - win[0] < 300:        # a logo or icon, not a text strip
                    continue
                px = ih["h"] * im["k"]
                key = os.path.basename(im["src"])
                res[key] = min(res.get(key, 1e9), px)
    return res


# ------------------------------------------------------------------------------------------------- BACKDROP (forge2 v3)
BD_W = 135                  # working width of the picture area for the silhouette test
BD_MIN, BD_MAX = 0.06, 0.65 # a prop backdrop is a compact solid shape of 6 to 65% of the picture area
BD_FILL = (0.60, 0.88)      # a disc or badge fills 60 to 88% of its bounding box (a circle 0.785, a shield about 0.7; a plain rectangle is 1.0 and is not a badge)
BD_ASPECT = (0.70, 1.40)    # and is about as wide as it is tall
BD_IOU = 0.60               # two silhouettes are "the same backdrop shape" at this overlap
BD_SHARE_MAX = 0.50         # FAIL when more than half the beats share one backdrop silhouette


def _hull(pts):
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def backdrop_mask(img):
    """-> a 27x(h) boolean silhouette: the CONVEX HULL of the beat's biggest compact solid-colour region that does not span the frame (a disc, badge or plate behind the subject; the wall
    and the ground span it and are skipped). The hull because the icon drawn on a disc cuts the disc's colour into a C and the icon still belongs to the shape. None when the beat has no
    such region."""
    np, Image = _np()
    from PIL import ImageDraw
    pic = Image.fromarray(_picture(img))
    h = int(round(BD_W * pic.size[1] / float(pic.size[0])))
    a = np.asarray(pic.resize((BD_W, h), Image.BOX), dtype=int) // 36
    lab = a[:, :, 0] * 64 + a[:, :, 1] * 8 + a[:, :, 2]
    H, W = lab.shape
    seen = np.zeros((H, W), dtype=bool)
    best, best_area = None, 0
    for y in range(H):
        for x in range(W):
            if seen[y, x]:
                continue
            c = lab[y, x]
            stack, pts = [(y, x)], []
            seen[y, x] = True
            while stack:
                cy, cx = stack.pop()
                pts.append((cx, cy))
                for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                    if 0 <= ny < H and 0 <= nx < W and not seen[ny, nx] and lab[ny, nx] == c:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(pts) < BD_MIN * H * W * 0.25:
                continue
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            if (x0 <= 1 and x1 >= W - 2) or (y0 <= 1 and y1 >= H - 2):
                continue                      # spans the frame: wall or ground
            hull = _hull(pts)
            if len(hull) < 3:
                continue
            im = Image.new("L", (W, H), 0)
            ImageDraw.Draw(im).polygon(hull, fill=255)
            m = np.asarray(im) > 0
            area = m.sum() / float(H * W)
            if not (BD_MIN <= area <= BD_MAX) or len(pts) < 0.30 * m.sum() or not (BD_FILL[0] <= m.sum() / float((x1 - x0 + 1) * (y1 - y0 + 1)) <= BD_FILL[1]) or not (BD_ASPECT[0] <= (x1 - x0 + 1) / float(y1 - y0 + 1) <= BD_ASPECT[1]):
                continue
            if m.sum() > best_area:
                best, best_area = m, m.sum()
    if best is None:
        return None
    return np.asarray(Image.fromarray((best * 255).astype("uint8")).resize((27, max(1, int(round(27 * H / float(W))))), Image.BOX)) > 100


def backdrop(frames):
    """-> {shared share, cluster beat indexes, n_with_shape}: the largest group of beats whose backdrop silhouettes overlap at IoU >= BD_IOU, as a share of all beats"""
    np, _ = _np()
    ms = [backdrop_mask(f["img"]) for f in frames]
    n = len(ms)
    idx = [i for i in range(n) if ms[i] is not None]
    def iou(a, b):
        if a.shape != b.shape:
            return 0.0
        u = (a | b).sum()
        return float((a & b).sum()) / u if u else 0.0
    parent = {i: i for i in idx}
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for a_ in idx:
        for b_ in idx:
            if a_ < b_ and iou(ms[a_], ms[b_]) >= BD_IOU:
                parent[find(a_)] = find(b_)
    groups = {}
    for i in idx:
        groups.setdefault(find(i), []).append(i)
    big = max(groups.values(), key=len) if groups else []
    return {"share": round(len(big) / float(n), 3) if n else 0.0, "beats": sorted(big), "with_shape": len(idx), "n": n}


# ------------------------------------------------------------------------------------------------- LONE (forge2 v4)
LONE_MAX = 0.50           # FAIL when more than half the beats are a lone object on otherwise empty ground ...
LONE_GROUND_DETAIL = 0.10 # ... a beat is LONE when under 10% of the blocks outside its main object's box carry any texture (std > 2)
LONE_FURN_MIN = 0.12      # ... and the short has no persistent world: share of picture blocks textured (std > 8) at the same place in 60% of the beats (C13's score row, S72's ticker, S102's wall, an estate's streets)


def _blocks(img):
    np, Image = _np()
    g = np.asarray(_picture(img)).astype(float).mean(axis=2)
    bs = 10
    H, W = (g.shape[0] // bs) * bs, (g.shape[1] // bs) * bs
    return g[:H, :W].reshape(H // bs, bs, W // bs, bs).swapaxes(1, 2).reshape(H // bs, W // bs, -1)


def _label8(m):
    np, _ = _np()
    lab = np.zeros(m.shape, dtype=int)
    n = 0
    for y in range(m.shape[0]):
        for x in range(m.shape[1]):
            if m[y, x] and not lab[y, x]:
                n += 1
                st = [(y, x)]
                lab[y, x] = n
                while st:
                    cy, cx = st.pop()
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < m.shape[0] and 0 <= nx < m.shape[1] and m[ny, nx] and not lab[ny, nx]:
                                lab[ny, nx] = n
                                st.append((ny, nx))
    return lab, n


def _dil1(m):
    np, _ = _np()
    p = np.pad(m, 1)
    o = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            o |= p[1 + dy:1 + dy + m.shape[0], 1 + dx:1 + dx + m.shape[1]]
    return o


def lone_world(frames):
    """-> {share, beats, furn, n}: beats whose picture is ONE object (the biggest connected strong-edge region) on ground with no texture of its own; furn = the persistent world."""
    np, _ = _np()
    STD = [_blocks(f["img"]).std(axis=2) for f in frames]
    furn = float((np.mean([s > 8 for s in STD], axis=0) >= 0.6).mean())
    lone = []
    for i, s in enumerate(STD):
        core = s > 14
        lab, n = _label8(_dil1(core))
        if n == 0:
            lone.append(i)
            continue
        sz = [int(((lab == k) & core).sum()) for k in range(1, n + 1)]
        k = int(np.argmax(sz)) + 1
        ys, xs = np.where((lab == k) & core)
        out = np.ones(core.shape, dtype=bool)
        out[max(0, ys.min() - 1):ys.max() + 2, max(0, xs.min() - 1):xs.max() + 2] = False
        if out.sum() >= 20 and float((s[out] > 2.0).mean()) < LONE_GROUND_DETAIL:
            lone.append(i)
    n = len(frames)
    return {"share": round(len(lone) / float(n), 3) if n else 0.0, "beats": lone, "furn": round(furn, 3), "n": n}


# ------------------------------------------------------------------------------------------------- the check
def check(ID, source="auto"):
    beats = _beats(ID)
    frames, how = load_frames(ID, source)
    fails, warns, bl = [], [], []

    def beat_fail(i, msg):
        b = beats[i]
        bl.append({"i": i, "id": b.get("id"), "t": round(float(b["from"]), 2), "text": msg})

    # (i) intra-short variety
    v = variety(frames)
    if v["nn_median"] < NN_MEDIAN_MIN:
        msg = ("VARIETY: the beats look like one picture seen again: median distance to each beat's nearest twin is %.1f (floor %.1f; approved shorts "
               "run 7 to 25); %d of %d beats have a twin (distance < %.0f). Give each beat its OWN constructed prop at its own position and colour, "
               "not the module wall." % (v["nn_median"], NN_MEDIAN_MIN, len(v["twins"]), v["n"], TWIN_D))
        fails.append(msg)
        for i in v["twins"]:
            beat_fail(i, "VARIETY: this beat's frame is a near-duplicate of another beat's (distance %.1f < %.0f): the module wall shows through. Make its F2.prop bigger "
                         "(size 0.95), give it a plate colour unlike the neighbouring beats (plate: \"#hex\"), and tilt it (tilt: -5 or 5) so the prop, not the wall, is the picture." % (v["nn"][i], TWIN_D))
    if v["pair_frac"] > PAIR_FRAC_MAX:
        fails.append("VARIETY: %.0f%% of beat pairs are near-duplicates (max %.0f%%)." % (100 * v["pair_frac"], 100 * PAIR_FRAC_MAX))
    for i in v["run3_at"]:
        fails.append("VARIETY: beats %d-%d (%s..%s) are three near-identical pictures in a row." % (i, i + 2, beats[i].get("id"), beats[i + 2].get("id")))
        beat_fail(i + 1, "VARIETY: this beat and both neighbours are the same picture; change what is on screen.")
    # (i-b) backdrop: the same disc / badge silhouette behind the subject on more than half the beats (forge2 v3)
    bd = backdrop(frames)
    if bd["share"] > BD_SHARE_MAX:
        fails.append("BACKDROP: %.0f%% of the beats (%d of %d) put the subject on the same disc or badge silhouette (max %.0f%%; approved shorts reach 38%%): that reads as a stock-icon template. "
                     "Build the object INTO a place (desk, wall, shelf, street, floor) with no plate behind it." % (100 * bd["share"], len(bd["beats"]), bd["n"], 100 * BD_SHARE_MAX))
        for i in bd["beats"]:
            beat_fail(i, "BACKDROP: the subject sits on the same disc/badge silhouette as %d other beats. Remove the plate or badge: stand the object in its place (desk, wall, shelf, street or floor), scale 1.0 or more." % (len(bd["beats"]) - 1))
    # (i-c) lone object on empty ground, no persistent world (forge2 v4): the v3 failure, one flat icon per beat on a plain wall
    ln = lone_world(frames)
    if ln["share"] > LONE_MAX and ln["furn"] < LONE_FURN_MIN:
        fails.append("LONE: %.0f%% of the beats (%d of %d) are one object on an otherwise empty ground and the short has no persistent world (%.0f%% of the picture is textured at the same place in most beats; floor %.0f%%): "
                     "that reads as an explainer icon slideshow. Build every beat INSIDE the module's world (its grid, wall, board or town stays on screen and the camera travels between stations); a prop is only a secondary object placed in it."
                     % (100 * ln["share"], len(ln["beats"]), ln["n"], 100 * ln["furn"], 100 * LONE_FURN_MIN))
        for i in ln["beats"]:
            beat_fail(i, "LONE: this beat is one object on an empty ground. Show the module's world around it (travelTo a station that shows the grid/board/town), use a module verb on a story label, and make the object small and secondary.")
    # (ii) subject fill
    fills = []
    for f in frames:
        c, fl = fill_of(f["img"])
        fills.append((round(c, 2), round(fl, 2)))
        last = f["i"] == len(frames) - 1
        floor = CTA_FILL_FLOOR if last else FILL_FLOOR
        if c < floor:
            m = "FILL: only %.0f%% of the picture area under the headline carries anything (floor %.0f%%): an empty frame. Make the F2.prop fill it: size 0.95, pos center, and no camera station on bare floor (use a station that shows the wall or the objects)." % (100 * c, 100 * floor)
            fails.append("beat %d (%s) %s" % (f["i"], f["id"], m)); beat_fail(f["i"], m)
        elif fl > FLAT_MAX and c < FLAT_FILL_MAX and not last:
            m = ("FILL: one flat empty rectangle covers %.0f%% of the picture area (max %.0f%%) while only %.0f%% carries content: an empty panel." % (100 * fl, 100 * FLAT_MAX, 100 * c))
            fails.append("beat %d (%s) %s" % (f["i"], f["id"], m)); beat_fail(f["i"], m)
    # (iii) hero size, (iv) source crops: DOM data when present
    hero = hero_per_beat(ID)
    if hero is None:
        warns.append("HERO/SOURCE skipped: no out/%s/domlint/raw.json (run dom_lint first)" % ID)
        srcpx = None
    else:
        if max(hero[:2]) < HOOK_HERO_PX:
            m = "HERO: the hook beat has no line of %d px or more (largest %d px): the hook frame needs a hero line, subject plus number, in giant type." % (HOOK_HERO_PX, max(hero[:2]))
            fails.append(m); beat_fail(0, m)
        big = sum(1 for h in hero if h >= HERO_PX)
        if big < HERO_BEAT_FRAC * len(hero):
            fails.append("HERO: only %d of %d beats carry a line of %d px or more (need %.0f%%)." % (big, len(hero), HERO_PX, 100 * HERO_BEAT_FRAC))
            for i, h in enumerate(hero):
                if h < HERO_PX:
                    beat_fail(i, "HERO: largest line is %d px, need >= %d px: make the headline the hero." % (h, HERO_PX))
        n180 = sum(1 for h in hero if h >= HERO180_PX)
        if n180 < HERO180_N:
            fails.append("HERO: only %d beats carry a line of %d px or more (need %d: the hook and two more claims in giant type)." % (n180, HERO180_PX, HERO180_N))
            for i in sorted(range(len(hero)), key=lambda i_: -hero[i_])[:HERO180_N + 3]:
                if hero[i] < HERO180_PX and len(beats[i].get("id", "")) and beats[i].get("id") != "cta":
                    beat_fail(i, "HERO: largest line is %d px; this beat can be a hero beat: one line of 3 words at most plus a number at size 200 or more, nothing else in the text box." % hero[i])
        srcpx = source_px(ID)
        for k, px in (srcpx or {}).items():
            if px < SRC_FAIL_PX:
                fails.append("SOURCE: text inside source card %s is %.0f px on screen (floor %.0f): show it larger or crop a shorter clause." % (k, px, SRC_FAIL_PX))
            elif px < SRC_WARN_PX:
                warns.append("SOURCE: text inside source card %s is %.0f px (warn under %.0f)." % (k, px, SRC_WARN_PX))
    return {"id": ID, "ok": not fails, "frames": how, "fails": fails, "warns": warns, "beats": bl, "variety": {k: v[k] for k in ("nn_median", "twin_frac", "pair_frac", "run3_at")}, "backdrop": {k: bd[k] for k in ("share", "n", "with_shape")}, "lone": {k: ln[k] for k in ("share", "furn", "n")},
            "fill": fills, "hero": hero, "source_px": srcpx}


# ------------------------------------------------------------------------------------------------- calibration
def calibrate():
    import numpy as np
    rows = []
    for f in sorted(glob.glob(os.path.join(REG, "*.json"))):
        d = json.load(open(f))
        sid = d["id"]
        if not os.path.exists(os.path.join(KIT, "out", sid, "resolved.json")) or not os.path.exists(os.path.join(REG, sid + "-storyboard.jpg")):
            continue
        try:
            fr, _ = load_frames(sid, "sheet")
        except Exception:
            continue
        v = variety(fr)
        fills = [fill_of(x["img"]) for x in fr]
        rows.append({"id": sid, "state": d.get("state"), "decided": (d.get("decided") or "")[:10], "nn": v["nn_median"], "twin": v["twin_frac"], "pair": v["pair_frac"],
                     "run3": len(v["run3_at"]), "fillmin": min(c for c, _ in fills[:-1]), "fillmin_last": fills[-1][0],
                     "flat": max(fl for (c, fl) in fills[:-1] if c < FLAT_FILL_MAX) if any(c < FLAT_FILL_MAX for c, _ in fills[:-1]) else 0.0})
    ap = [r for r in rows if r["state"] == "approved"]
    for r in sorted(rows, key=lambda r: r["nn"]):
        print("%-9s %-5s %s nn %5.1f twin %.2f pair %.3f run3 %d fillmin %.2f last %.2f flat %.2f" % (r["state"], r["id"], r["decided"], r["nn"], r["twin"], r["pair"], r["run3"], r["fillmin"], r["fillmin_last"], r["flat"]))
    print("approved n=%d: nn min %.1f p10 %.1f | fillmin p5 %.2f min %.2f | pair max %.3f" % (len(ap), min(r["nn"] for r in ap), np.percentile([r["nn"] for r in ap], 10),
          np.percentile([r["fillmin"] for r in ap], 5), min(r["fillmin"] for r in ap), max(r["pair"] for r in ap)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id", nargs="?")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--frames", default="auto", choices=("auto", "snap", "sheet"))
    ap.add_argument("--calibrate", action="store_true")
    a = ap.parse_args()
    if a.calibrate:
        return calibrate()
    try:
        r = check(a.id, a.frames)
    except Exception as e:
        print("sheet_check: tool error: %s" % e, file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(r, indent=1, default=str))
    else:
        print("sheet_check %s: %s (frames from %s)" % (r["id"], "PASS" if r["ok"] else "FAIL", r["frames"]))
        print("  variety: nn_median %.1f (floor %.1f) twins %.0f%% pairs %.1f%% | hero: %s" % (r["variety"]["nn_median"], NN_MEDIAN_MIN, 100 * r["variety"]["twin_frac"], 100 * r["variety"]["pair_frac"],
              ("hook %d px, %d of %d beats >= %d px" % (max(r["hero"][:2]), sum(1 for h in r["hero"] if h >= HERO_PX), len(r["hero"]), HERO_PX)) if r["hero"] else "n/a"))
        print("  backdrop: %.0f%% of beats share one disc/badge silhouette (max %.0f%%)" % (100 * r["backdrop"]["share"], 100 * BD_SHARE_MAX))
        print("  fill per beat: " + " ".join("%.2f" % c for c, _ in r["fill"]))
        for m in r["fails"]:
            print("  FAIL " + m)
        for m in r["warns"]:
            print("  WARN " + m)
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
