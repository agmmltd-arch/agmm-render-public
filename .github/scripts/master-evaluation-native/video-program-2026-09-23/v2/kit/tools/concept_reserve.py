#!/usr/bin/env python3
"""concept_reserve.py: reservations of look classes for shorts being made (VARIETY, 13 Oct 2026).

Why: concept_check judged a concept against the last 10 APPROVED shorts only, so parallel makers raced. S104 passed at
14:08 on a dark navy ground; S103 (dark charcoal, in review) was approved at 14:03-14:09; S104 then failed R3 and was
returned after a full build. A reservation puts a short's ground class, world, hero and the other look axes on the
record while it is being made, so concept_check counts it like an approved short and the next maker is told first.

Registry : registry/concept-reservations.json  {"live_from": ISO, "reservations": {ID: record}}  (override: AGMM_RESERVATIONS)
Record   : id, maker, reserved_at, source (claim|concept|backfill), axes {ground, dark_cool, dominant_hue, world_family,
           hero_device, hook_mechanic, signature, camera, source_presentation, bed} (a partial reservation may omit axes)
Live at T: reserved_at <= T, the short is still `claimed` in registry/queue.json, its storyboard is not approved at T, and
           either its storyboard is `submitted` at T (held up to 48 h for the reviewer) or the maker touched specs/<ID>/ or
           out/<ID>/ within LEASE_H hours before T. Released, approved, idle or abandoned claims free themselves.
Priority : a short counts only reservations made BEFORE its own (first come, first served); without a reservation, all.
Enforce  : FAIL for shorts claimed at or after live_from; WARN for earlier claims (makers active when this shipped keep
           working). AGMM_RESERVATIONS_ENFORCE=1 forces FAIL (replays, tests).

CLI      : concept_reserve.py list [--at ISO]          live and dead reservations with the reason
           concept_reserve.py backfill                  one time: reserve every claimed short's current concept.json
           concept_reserve.py reserve <ID> [--ground dark-coolneutral] [--world interior-set] [--hero giant-number] [--maker X]
                                                        claim-time reservation of chosen classes (refused if it breaks R3/R2)
Library  : live(T, exclude, before) -> [record]; lock_concept(ID, concept, maker); my_reserved_at(ID); enforced(ID)
"""
import argparse, contextlib, datetime, fcntl, glob, json, os, sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(KIT, "registry")
QUEUE = os.path.join(REG, "queue.json")
LEASE_H = 6.0
SUBMITTED_HOLD_H = 48.0
AXES = ["ground", "dark_cool", "dominant_hue", "world_family", "hero_device", "hook_mechanic", "signature", "camera",
        "source_presentation", "bed"]


def path():
    return os.environ.get("AGMM_RESERVATIONS") or os.path.join(REG, "concept-reservations.json")


def now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def _dt(s):
    return datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def load():
    p = path()
    if not os.path.exists(p):
        return {"live_from": None, "reservations": {}}
    try:
        d = json.load(open(p))
    except Exception:
        return {"live_from": None, "reservations": {}}
    d.setdefault("reservations", {})
    return d


@contextlib.contextmanager
def locked():
    """exclusive lock around read-check-write, so two makers cannot both take the last slot."""
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = load()
        yield d
        tmp = p + ".tmp"
        json.dump(d, open(tmp, "w"), indent=1)
        os.replace(tmp, p)


def queue():
    try:
        return json.load(open(QUEUE))
    except Exception:
        return {}


def claim_of(ID, q=None):
    e = (q if q is not None else queue()).get(ID)
    return e if isinstance(e, dict) and e.get("state") == "claimed" else None


def enforced(ID, d=None):
    if os.environ.get("AGMM_RESERVATIONS_ENFORCE") == "1":
        return True
    d = d or load()
    lf = d.get("live_from")
    e = claim_of(ID)
    return bool(lf and e and e.get("at", "") >= lf)


def last_activity(ID, T):
    """newest mtime <= T of specs/<ID>/* and out/<ID>/* (top level)."""
    best = None
    for f in glob.glob(os.path.join(KIT, "specs", ID, "*")) + glob.glob(os.path.join(KIT, "out", ID, "*")) + [os.path.join(KIT, "out", ID)]:
        try:
            m = _iso(os.path.getmtime(f))
        except OSError:
            continue
        if m <= T and (best is None or m > best):
            best = m
    return best


def sb_state_at(ID, T, events):
    ev = [e for e in events.get(ID, []) if e[0] <= T]
    return ev[-1] if ev else (None, None)


def status(rec, T, q, events):
    """(live: bool, reason)."""
    ID = rec["id"]
    if rec.get("reserved_at", "9") > T:
        return False, "reserved after %s" % T
    if not claim_of(ID, q):
        return False, "no longer claimed in queue.json"
    ts, st = sb_state_at(ID, T, events)
    if st == "approved":
        return False, "approved (counted as an approved short)"
    if st == "submitted":
        if _dt(T) - _dt(ts) <= datetime.timedelta(hours=SUBMITTED_HOLD_H):
            return True, "storyboard submitted %s, held for the reviewer" % ts
        return False, "submitted %s and not decided for %d h" % (ts, SUBMITTED_HOLD_H)
    act = max([x for x in (rec.get("reserved_at"), rec.get("renewed_at"), last_activity(ID, T)) if x] or ["0"])
    if _dt(T) - _dt(act) <= datetime.timedelta(hours=LEASE_H):
        return True, "lease: last activity %s" % act
    return False, "lease expired: no activity since %s (> %g h)" % (act, LEASE_H)


def live(T=None, exclude=None, before=None, events=None):
    """live reservations at T of other shorts, reserved strictly before `before` when given."""
    import concept_check as cc
    T = T or now()
    events = events if events is not None else cc.storyboard_events()
    q = queue()
    out = []
    for ID, rec in load()["reservations"].items():
        if ID == exclude:
            continue
        if before and rec.get("reserved_at", "9") >= before:
            continue
        ok, why = status(rec, T, q, events)
        if ok:
            out.append(dict(rec, why=why))
    return sorted(out, key=lambda r: r["reserved_at"])


def my_reserved_at(ID):
    rec = load()["reservations"].get(ID)
    return rec.get("reserved_at") if rec else None


def axes_from_concept(c):
    import concept_check as cc
    a = cc.axes_of(c)
    return {"ground": a["ground"], "dark_cool": cc.is_dark_cool(c), "dominant_hue": cc.dominant_hue(c["palette"]),
            "world_family": a["world_family"], "hero_device": a["hero_device"], "hook_mechanic": a["hook_mechanic"],
            "signature": a["signature"], "camera": a["camera"], "source_presentation": a["source_presentation"],
            "bed": c["bed"]["id"], "ground_hex": c["ground"]["hex"]}


def put(d, ID, axes, maker, source, at=None):
    """write a reservation; keep the original reserved_at when the axes did not change (a re-run is not a re-queue)."""
    old = d["reservations"].get(ID)
    at = at or now()
    keep = old and {k: old["axes"].get(k) for k in AXES} == {k: axes.get(k) for k in AXES}
    rec = {"id": ID, "maker": maker or (old or {}).get("maker"), "source": source if not keep else old.get("source", source),
           "reserved_at": old["reserved_at"] if keep else at, "renewed_at": at, "axes": axes}
    e = claim_of(ID)
    if e:
        rec["claim_at"] = e.get("at")
        rec["maker"] = rec["maker"] or e.get("writer")
    d["reservations"][ID] = rec
    return rec


def _props(ID):
    try:
        import prop_reuse
        a, cnt, wp, fam = prop_reuse.props_of(ID)
        return sorted(a), sorted(wp)
    except Exception:
        return [], []


def lock_concept(ID, c, maker=None, d=None, source="concept", at=None):
    axes = axes_from_concept(c)
    props, wprops = _props(ID)
    if d is not None:
        rec = put(d, ID, axes, maker, source, at)
        rec.update(props=props, world_props=wprops)
        return rec
    with locked() as dd:
        rec = put(dd, ID, axes, maker, source, at)
        rec.update(props=props, world_props=wprops)
        return rec


def backfill():
    import concept_check as cc
    q = queue()
    n = 0
    with locked() as d:
        if not d.get("live_from"):
            d["live_from"] = now()
        for ID, e in q.items():
            if not (isinstance(e, dict) and e.get("state") == "claimed") or ID in d["reservations"]:
                continue
            p = os.path.join(KIT, "specs", ID, "concept.json")
            try:
                c = json.load(open(p))
                if cc.validate(c, cc.load_schema()):
                    continue
            except Exception:
                continue
            lock_concept(ID, c, e.get("writer"), d=d, source="backfill", at=_iso(os.path.getmtime(p)))
            n += 1
    return n


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import concept_check as cc
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["list", "backfill", "reserve"])
    ap.add_argument("id", nargs="?")
    ap.add_argument("--at")
    ap.add_argument("--ground", help="ground class, e.g. light-warm, mid-coolneutral, dark-coolneutral, mixed")
    ap.add_argument("--world", help="world_family enum")
    ap.add_argument("--hero", help="hero_device enum")
    ap.add_argument("--maker")
    a = ap.parse_args()
    if a.cmd == "backfill":
        print("backfilled %d reservations from claimed shorts' concept.json (%s)" % (backfill(), path()))
        return
    if a.cmd == "list":
        T = a.at or now()
        events = cc.storyboard_events()
        q = queue()
        d = load()
        print("reservations at %s (live_from %s, %s)" % (T, d.get("live_from"), path()))
        for ID, rec in sorted(d["reservations"].items(), key=lambda kv: kv[1].get("reserved_at", "")):
            ok, why = status(rec, T, q, events)
            ax = rec["axes"]
            print("  %-5s %-4s %s %-10s ground=%-16s world=%-16s hero=%-18s | %s" % (
                ID, "LIVE" if ok else "dead", rec.get("reserved_at"), (rec.get("maker") or "-")[:10], ax.get("ground"),
                ax.get("world_family"), ax.get("hero_device"), why))
        return
    # reserve: claim-time classes, checked under the lock
    if not a.id:
        ap.error("reserve needs an ID")
    with locked() as d:
        T = now()
        events = cc.storyboard_events()
        win, _ = cc.window_for(a.id, T, cc.WINDOW_N, events)
        q = queue()
        others = [r for i, r in d["reservations"].items() if i != a.id and status(r, T, q, events)[0]]
        old = (d["reservations"].get(a.id) or {}).get("axes", {})
        axes = dict(old)
        if a.ground:
            axes["ground"] = a.ground
            axes["dark_cool"] = a.ground == "dark-coolneutral"
        if a.world:
            axes["world_family"] = a.world
        if a.hero:
            axes["hero_device"] = a.hero
        if axes.get("dark_cool"):
            dark = [s for s, _, o in win if cc.is_dark_cool(o)] + [r["id"] for r in others if r["axes"].get("dark_cool")]
            if len(dark) > cc.DARK_COUNT_MAX:
                print("REFUSED: dark-coolneutral is taken: %d dark already (%s; max %d). Run concept_check.py --suggest %s"
                      % (len(dark), ",".join(dark), cc.DARK_COUNT_MAX, a.id))
                sys.exit(1)
        rec = put(d, a.id, axes, a.maker, "claim")
        print("reserved %s at %s: %s" % (a.id, rec["reserved_at"], json.dumps({k: v for k, v in axes.items() if v is not None})))


if __name__ == "__main__":
    main()
