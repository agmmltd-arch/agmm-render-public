"""triage_store.py - the ONLY way to write ASR-TRIAGE.json (root, 5 Oct 2026).

Six agents voice and triage in parallel. Every writer used to load the file, change it, and dump the whole thing back,
so concurrent runs silently erased each other's verdicts (S17, S82, S83, S90, S104 lost theirs at 18:00; m4 restored its
own CLEAN entries before every build). update() re-reads the file under an exclusive lock, applies only the given
short/paragraph entries, and replaces the file atomically.

    import triage_store
    triage_store.update(vdir, {"S118": {"P02": {...entry...}}})          # replace those entries
    triage_store.update(vdir, {...}, merge_fields=True)                  # update fields inside existing entries
    triage_store.update(vdir, {...}, only_new=True)                      # never overwrite an existing verdict
"""
import fcntl
import json
import os
import tempfile


def read(vdir):
    try:
        return json.load(open(os.path.join(vdir, "ASR-TRIAGE.json")))
    except Exception:
        return {}


def update(vdir, entries, merge_fields=False, only_new=False):
    tp = os.path.join(vdir, "ASR-TRIAGE.json")
    with open(tp + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        cur = read(vdir)
        for sid, paras in entries.items():
            dst = cur.setdefault(sid, {})
            for p, v in paras.items():
                if only_new and p in dst:
                    continue
                if merge_fields and isinstance(dst.get(p), dict):
                    dst[p].update(v)
                else:
                    dst[p] = v
        fd, tmp = tempfile.mkstemp(dir=vdir, prefix=".asr-triage-")
        with os.fdopen(fd, "w") as fh:
            json.dump(cur, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, tp)
    return cur
