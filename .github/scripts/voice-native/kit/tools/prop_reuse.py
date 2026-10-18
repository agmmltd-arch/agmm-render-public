#!/usr/bin/env python3
"""prop_reuse.py: does a concept's MAIN props or world repeat the last 10 approved shorts and live reservations? (VARIETY, 13 Oct 2026)

Why: reviewers return "the same generic camera world" (S94), "the same grid" (S88), "phone-UI mock repeats S50" (S65), "green
vault repeats S72" (S10). concept_check R1-R4 compare enum look axes only and never see the props.

Props  : physical-object nouns (PROP_LEXICON) found in specs/<ID>/spec.json transitions + signature_concept and concept.json
         world.name + signature.description + pitch.objects[].name. A MAIN prop is named in >= MAIN_MIN of those entries.
World  : world_family + the prop nouns of world.name.
Rule   : FLAG when a MAIN prop is also a prop of >= K shorts in the window (approved last 10 + live reservations' props), or
         when the world (family + a world-name prop) repeats one in the window. K / MAIN_MIN come from `--calibrate`.
Images : exact sha256 of every image file under specs/<ID>/media and media/<ID>/final against the window's (reuse is banned).
Usage  : prop_reuse.py <ID> [--at ISO] ; prop_reuse.py --calibrate (labels from ~/.fleet/buzz/ladder/shadow.jsonl)
Library: check(ID, T, window_ids, reserved) -> dict(flag, detail, main, shared, images)
"""
import glob, hashlib, json, os, re, sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHADOW = os.path.expanduser("~/.fleet/buzz/ladder/shadow.jsonl")
K = 5            # calibrated 13 Oct (--calibrate): no K reaches <= 5% false flags with any recall, so R8 is ADVISORY (WARN)
MAIN_MIN = 2
PROP_LEXICON = set("""wall desk stamp grid page board calendar lamp phone screen tile paper flap brass map box office marker door window
tray sheet slip clipping pin floor plate clock machine tag file strip bolt stopwatch rail padlock tape bubble sign pile slot counter
checklist glass dial needle pen ticket badge table rack coin button pipe seal receipt printer folder envelope ledger invoice laptop
sensor cctv icon chart gauge meter barcode keyboard cursor vault safe drawer shelf crate pallet truck van car road bridge building
tower house shop store till trolley basket bottle cup plate bed chair sofa kitchen oven fridge server cable plug socket battery
bulb torch magnifier lens spreadsheet browser inbox email notification bell alarm siren headset microphone speaker radio television
tv monitor dashboard console lever switch valve conveyor belt robot arm drone satellite globe pin flag compass ruler scale weight
key lock card""".split()) - {"card"}
# surfaces every world stands on (calibration 13 Oct: wall/desk/page/stamp/slip/board drove 27 of 43 approvals to a flag);
# they still count for the WORLD rule through world.name, never as a main prop
SURFACE = set("wall desk page paper board floor slip stamp sheet strip box window door table tile plate tag file pile".split())


def _sing(w):
    return w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w


def _versions(sid, name):
    d = os.path.join(KIT, "specs", sid)
    c = [p for p in glob.glob(os.path.join(d, name + "*")) if os.path.isfile(p)]
    c += glob.glob(os.path.join(KIT, "out", sid, "spec-archive", name + ".*"))
    return c


def load_as_of(sid, name, T=None):
    """the version of specs/<sid>/<name> current at T: the newest backup/archive copy written at or before T, else the current file."""
    cur = os.path.join(KIT, "specs", sid, name)
    if T:
        import datetime
        ts = datetime.datetime.strptime(T[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
        c = sorted([(os.path.getmtime(p), p) for p in _versions(sid, name) if os.path.getmtime(p) <= ts])
        if c:
            cur = c[-1][1]
    try:
        return json.load(open(cur))
    except Exception:
        return None


def entries(sid, T=None):
    out = []
    s = load_as_of(sid, "spec.json", T) or {}
    out += [x for x in (s.get("transitions") or []) if isinstance(x, str)]
    if isinstance(s.get("signature_concept"), str):
        out.append(s["signature_concept"])
    c = load_as_of(sid, "concept.json", T) or {}
    out += [o.get("name", "") for o in (c.get("pitch") or {}).get("objects", [])]
    sig = (c.get("signature") or {}).get("description")
    if sig:
        out.append(sig)
    world = (c.get("world") or {})
    return out, world.get("name", "") or (s.get("world") if isinstance(s.get("world"), str) else ""), world.get("world_family")


def props_of(sid, T=None):
    """(all props, {prop: number of entries naming it}, world props, world_family)."""
    ents, wname, fam = entries(sid, T)
    cnt = {}
    for e in ents:
        for p in {_sing(w) for w in re.findall(r"[a-z]+", e.lower())} & PROP_LEXICON:
            cnt[p] = cnt.get(p, 0) + 1
    wp = {_sing(w) for w in re.findall(r"[a-z]+", (wname or "").lower())} & PROP_LEXICON
    return set(cnt) | wp, cnt, wp, fam


def image_hashes(sid):
    hs = {}
    for p in glob.glob(os.path.join(KIT, "specs", sid, "media", "**", "*"), recursive=True) + \
            glob.glob(os.path.join(KIT, "media", sid, "final", "*")):
        if p.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and os.path.isfile(p) and "/clauses/" not in p:
            try:
                hs[hashlib.sha256(open(p, "rb").read()).hexdigest()] = os.path.relpath(p, KIT)
            except OSError:
                pass
    return hs


def check(ID, T=None, window_ids=(), reserved=(), k=None, main_min=None, images=True):
    k = k or K
    main_min = main_min or MAIN_MIN
    allp, cnt, wp, fam = props_of(ID, T)
    main = sorted(p for p, n in cnt.items() if n >= main_min and p not in SURFACE) + sorted(wp - SURFACE - {p for p, n in cnt.items() if n >= main_min})
    others = {}
    for sid in window_ids:
        a, _, w, f = props_of(sid, T)
        others[sid] = (a, w, f)
    for r in reserved:
        others[r["id"]] = (set(r.get("props") or []), set(r.get("world_props") or []), r["axes"].get("world_family"))
    shared = {p: [sid for sid, (a, _, _) in others.items() if p in a] for p in main}
    hot = {p: ids for p, ids in shared.items() if len(ids) >= k}
    world_rep = [sid for sid, (_, w, f) in others.items() if fam and f == fam and wp & w]
    img = {}
    if images:
        mine = image_hashes(ID)
        # No target image can match the window when the target has no images (concept-only stage).
        for sid in others if mine else ():
            for h, path in image_hashes(sid).items():
                if h in mine:
                    img.setdefault(sid, []).append(mine[h])
    flag = bool(hot or world_rep)
    det = []
    if hot:
        det.append("main prop(s) repeat the window: " + "; ".join("%s in %d (%s)" % (p, len(i), ",".join(i)) for p, i in sorted(hot.items(), key=lambda kv: -len(kv[1]))))
    if world_rep:
        det.append("world %s with %s repeats %s" % (fam, ",".join(sorted(wp)), ",".join(world_rep)))
    return {"flag": flag, "detail": "; ".join(det) or "main props %s: none in %d+ of the window" % (",".join(main) or "-", k),
            "main": main, "shared": shared, "world_repeat": world_rep, "images": img, "props": sorted(allp), "world_props": sorted(wp)}


# ---------------------------------------------------------------------------------------------------- calibration
POS_STRICT = {216: "S94 same generic camera world", 217: "S88 reuse the same icon grid", 220: "S85 generic council/road object, line-chart/calendar",
              207: "S65 phone-UI mock repeats S50", 175: "S10 green vault repeats S72"}
POS_INTRA = {64: "S50 same pill grid on 17 of 20 beats", 90: "S104 same static bedroom on all frames", 219: "S84 repeated central plaque",
             218: "S07 generic object treatment", 235: "S85 same cream card stack every beat"}


def calibrate():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import concept_check as cc
    rows = [json.loads(l) for l in open(SHADOW) if l.strip()]
    events = cc.storyboard_events()
    cases = []
    for i, why in list(POS_STRICT.items()) + list(POS_INTRA.items()):
        cases.append((i, rows[i]["id"], rows[i]["at"][:19], 1, "strict" if i in POS_STRICT else "intra", why))
    seen = set()
    for i, r in enumerate(rows):
        if r.get("stage") == "storyboard_first_pass" and r.get("verdict") == "APPROVE" and r["id"] not in seen:
            seen.add(r["id"])
            cases.append((i, r["id"], r["at"][:19], 0, "approve", "first-pass approval"))
    grid = [(kk, mm) for kk in (2, 3, 4, 5) for mm in (1, 2)]
    res = {g: [] for g in grid}
    for i, sid, at, lab, tier, why in cases:
        win = [s for _, s in cc.approved_at(at, events, exclude=sid)[:cc.WINDOW_N]]
        for kk, mm in grid:
            res[(kk, mm)].append((lab, tier, check(sid, at, win, k=kk, main_min=mm, images=False)["flag"], sid))
    print("cases: %d strict positives, %d intra-short positives, %d first-pass approvals" % (
        len(POS_STRICT), len(POS_INTRA), sum(1 for c in cases if c[3] == 0)))
    print("%-4s %-8s | %-14s %-14s %-12s | %s" % ("K", "MAIN_MIN", "strict caught", "intra caught", "false flags", "flagged approvals"))
    for g in grid:
        r = res[g]
        st = [x for x in r if x[1] == "strict"]
        it = [x for x in r if x[1] == "intra"]
        ap = [x for x in r if x[1] == "approve"]
        print("%-4d %-8d | %2d/%-11d %2d/%-11d %2d/%-3d %5.1f%% | %s" % (g[0], g[1], sum(x[2] for x in st), len(st), sum(x[2] for x in it), len(it),
              sum(x[2] for x in ap), len(ap), 100.0 * sum(x[2] for x in ap) / max(1, len(ap)), ",".join(x[3] for x in ap if x[2])[:80]))
    print("caught at K=%d MAIN_MIN=%d: %s" % (K, MAIN_MIN, ", ".join("%s(%s)" % (x[3], x[1]) for x in res[(K, MAIN_MIN)] if x[2] and x[0])))


def main():
    import argparse
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("id", nargs="?")
    ap.add_argument("--at")
    ap.add_argument("--calibrate", action="store_true")
    a = ap.parse_args()
    if a.calibrate:
        return calibrate()
    import concept_check as cc, datetime
    T = a.at or datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    win = [s for _, s in cc.approved_at(T, exclude=a.id)[:cc.WINDOW_N]]
    r = check(a.id, a.at, win)
    print(json.dumps(r, indent=1))
    sys.exit(1 if r["flag"] or r["images"] else 0)


if __name__ == "__main__":
    main()
