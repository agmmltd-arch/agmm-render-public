#!/usr/bin/env python3
"""Production queue for the parallel spec writers (root, 24 Sep 22:15). One short per writer at a time, never two
writers on one short, earliest posting slot first (Jev ROUTING schedule, v2/jev-v2/fit/routing.json).

  queue.py claim <writer> [ID]     -> prints the next READY short id (and claims it), or NONE; with ID, claims only that one
  queue.py done <id> <status>      -> status: published | failed:<reason> | parked:<reason>
  queue.py release <id>            -> give a claimed short back (e.g. writer stopping)
  queue.py ready <id> [note]       -> release a voiced short that has no routing slot (e.g. S80+) for claiming;
                                      refuses unless voice_ready(<id>) holds (voice lead, 25 Sep)
  queue.py status                  -> counts and the next ten ready

READY = voice RESULT.json status FINISHED, and every paragraph that failed the ASR word check is confirmed CLEAN in
shorts/voice/ASR-TRIAGE.json (the same rule build_short.voice_word_guard enforces), and not already claimed/published.
P1-P3 are approved pilots and never queued.
Shorts outside routing.json (S80+) sit in queue.json as needs-voice, so `claim` skipped them forever. `ready <id>`
sets state "ready" (only when voice_ready), and claim/status take those after the routed shorts, which keep their
posting-slot order. Release of a ready-state short returns it to "ready" instead of dropping it.
"""
import os, fcntl, glob, json, os, sys, time

from voice_script_binding import check_voice_script_binding

KIT = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.dirname(KIT)
Q = os.path.join(KIT, "registry", "queue.json")
VOICE = os.path.join(V2, "shorts", "voice")


def order():
    s = json.load(open(os.path.join(V2, "jev-v2/fit/routing.json")))["schedule"]
    seen = []
    for x in sorted(s, key=lambda x: (x["day"], x["slot"], x["platform"])):
        if x["item"] not in seen and x["item"] not in ("P1", "P2", "P3"):
            seen.append(x["item"])
    return seen, {x["item"]: x for x in s}


def voice_ready(sid):
    rp = os.path.join(VOICE, sid, "RESULT.json")
    if not os.path.exists(rp) or json.load(open(rp)).get("status") != "FINISHED":
        return False
    binding, _reason = check_voice_script_binding(sid, os.path.join(VOICE, sid), V2)
    if binding == "REFUSE":
        return False
    tri_p = os.path.join(VOICE, "ASR-TRIAGE.json")
    tri = json.load(open(tri_p)).get(sid, {}) if os.path.exists(tri_p) else {}
    for rcp in glob.glob(os.path.join(VOICE, sid, "P*.receipt.json")):
        if json.load(open(rcp)).get("asr_match") is False:
            p = os.path.basename(rcp).split(".")[0]
            if tri.get(p, {}).get("verdict") != "CLEAN":
                return False
    return True


def claimable(q, ids):
    # root 29 Sep: a short already made (a FINAL.mp4 exists) but missing from queue.json was handed out again (C21).
    made = lambda s: os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", s, "FINAL.mp4"))
    out = [s for s in ids if s not in q and voice_ready(s) and not made(s)]
    extra = [s for s, v in q.items() if v.get("state") == "ready" and s not in out and voice_ready(s)]
    return out + sorted(extra, key=lambda s: (q[s].get("ready_at", ""), s))


def with_q(fn):
    os.makedirs(os.path.dirname(Q), exist_ok=True)
    with open(Q + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        q = json.load(open(Q)) if os.path.exists(Q) else {}
        r = fn(q)
        json.dump(q, open(Q, "w"), indent=1)
        return r


def main():
    cmd = sys.argv[1]
    ids, slots = order()
    if cmd == "claim":
        writer = sys.argv[2]

        want = sys.argv[3] if len(sys.argv) > 3 else None   # root 29 Sep: `claim <writer> <ID>` claims that ID only

        def idle(sid, e):
            """a claim with nothing behind it: no out/<ID>, no spec file touched since the claim"""
            if os.path.exists(os.path.join(KIT, "out", sid)):
                return False
            try:
                t = time.mktime(time.strptime(e.get("at", ""), "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                return False
            return all(os.path.getmtime(x) < t for x in glob.glob(os.path.join(KIT, "specs", sid, "*")))

        def f(q):
            # root 29 Sep 22:48: Forge sat on 11 idle claims (no out/, no spec edit since claiming) and blocked every maker.
            # (1) an idle claim older than 4 h is released; (2) a writer with 2 idle claims gets no third.
            now = time.time()
            for sid, e in list(q.items()):
                if isinstance(e, dict) and e.get("state") == "claimed" and idle(sid, e):
                    try:
                        age = now - time.mktime(time.strptime(e.get("at", ""), "%Y-%m-%dT%H:%M:%S"))
                    except Exception:
                        continue
                    if age > 4 * 3600:          # same effect as `queue.py release <sid>`
                        if e.get("ready_at"):
                            e["state"] = "ready"
                        else:
                            q.pop(sid, None)
            mine = [sid for sid, e in q.items() if isinstance(e, dict) and e.get("state") == "claimed"
                    and str(e.get("writer", "")).lower() == writer.lower() and idle(sid, e)]
            if len(mine) >= 2:
                return "NONE (%s already holds %d idle claims: %s; build or release them first)" % (writer, len(mine), " ".join(mine))
            pool = claimable(q, ids)
            if want:
                if want not in pool:
                    return "NONE (%s is not claimable: claimed, made, or voice not ready)" % want
                pool = [want]
            for sid in pool:
                e = q.get(sid, {})
                e.pop("finished", None)
                e.update(state="claimed", writer=writer, at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                         slot={k: slots[sid][k] for k in ("day", "slot", "platform")} if sid in slots else {})
                q[sid] = e
                return sid
            return "NONE"
        print(with_q(f))
    elif cmd == "done":
        sid, status = sys.argv[2], sys.argv[3]

        def f(q):
            q.setdefault(sid, {}).update(state=status, finished=time.strftime("%Y-%m-%dT%H:%M:%S"))
        with_q(f); print("ok")
    elif cmd == "release":
        def f(q):
            e = q.get(sys.argv[2])
            if e and e.get("ready_at"):
                e["state"] = "ready"
            else:
                q.pop(sys.argv[2], None)
        with_q(f); print("released")
    elif cmd == "ready":
        sid = sys.argv[2]
        note = " ".join(sys.argv[3:])
        if not voice_ready(sid):
            print("REFUSED: %s voice is not ready (RESULT.json FINISHED + ASR triage CLEAN)" % sid); sys.exit(1)

        def f(q):
            e = q.setdefault(sid, {})
            st = str(e.get("state", ""))
            if st.startswith(("claimed", "published", "parked")):
                return "REFUSED: %s is %s" % (sid, st[:80])
            e.update(state="ready", ready_at=time.strftime("%Y-%m-%dT%H:%M:%S"), previous_state=st or None)
            if note:
                e["ready_note"] = note
            return "ok"
        r = with_q(f); print(r)
        if r != "ok":
            sys.exit(1)
    elif cmd == "status":
        q = json.load(open(Q)) if os.path.exists(Q) else {}
        states = {}
        for v in q.values():
            states[v["state"].split(":")[0]] = states.get(v["state"].split(":")[0], 0) + 1
        ready = claimable(q, ids)
        waiting = [s for s in ids if s not in q and not voice_ready(s)]
        print(json.dumps({"states": states, "ready": len(ready), "next_ready": ready[:10], "waiting_on_voice": len(waiting)}, indent=1))


if __name__ == "__main__":
    main()
