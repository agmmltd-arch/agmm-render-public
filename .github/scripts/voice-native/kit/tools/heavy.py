#!/usr/bin/env python3
"""Run a heavy local job (headless snapshot, ffmpeg encode, whisper) only while holding one of N machine-wide slots.

Root, 25 Sep 01:40: ten writers plus five film builders all ran headless snapshots at once (11 headless Chromes) and
the Mac's load hit 71 on 16 cores. Every heavy local job waits for a free slot, so at most SLOTS run together.
Usage: heavy.py [--slots 2] [--lane NAME] -- <command ...>      (exit code = the command's)

BUILD LANE (13 Oct 2026, kit maker-kit card "static-parallel"): `produce.py <ID> --only build` is short (46 recorded builds: median 38 s,
p90 103 s, max 189 s) and light (measured S92: 66 CPU-s in 93 s wall = 0.7 core, 219 MB peak, ffmpeg/numpy under `nice 15`), but it queued
10+ min behind 15-minute voice_lead_check/whisper jobs on the 3 general slots. A job whose command is exactly a produce.py --only build
(or any job started with --lane build) now takes a slot from its OWN pool of AGMM_BUILD_SLOTS (default 3) instead: lock files
lane-build-slot-N.lock, a 900 s cap (HEAVY_MAX_S overrides) so a hung build cannot hold a slot for 30 min. Worst case it adds 3 builds x 0.7
core = ~2 of the machine's 16 cores on top of the 3 general slots, so the 25 Sep overload (15 heavy jobs, load 71) cannot recur from builds.
Every other command keeps the general pool exactly as before (lock files slot-N.lock)."""
import fcntl, os, re, subprocess, sys, time

SLOT_DIR = os.environ.get("AGMM_HEAVY_SLOT_DIR") or "/tmp/agmm-heavy-slots"   # the env override exists for test_heavy_lane.py only
BUILD_SLOTS = 3
BUILD_MAX_S = 900


def is_build_cmd(cmd):
    """True for `... produce.py <ID> --only build` (ID like S92/C13/P01; optional wrappers such as /usr/bin/time before it)."""
    for i, tok in enumerate(cmd):
        if os.path.basename(tok) == "produce.py":
            rest = cmd[i + 1:]
            return len(rest) == 3 and re.fullmatch(r"[A-Z]\d{2,3}", rest[0]) is not None and rest[1:] == ["--only", "build"]
    return False


def main():
    a = sys.argv[1:]
    slots = None   # general pool default 3 (root 28 Sep 19:25: Sam "dw about the battery", back to 3)
    lane = None
    while a and a[0] in ("--slots", "--lane"):
        if a[0] == "--slots":
            slots = int(a[1])
        else:
            lane = a[1]
            if not re.fullmatch(r"[a-z]{1,12}", lane):
                sys.exit("heavy.py: --lane must be 1-12 lowercase letters")
        a = a[2:]
    if a and a[0] == "--":
        a = a[1:]
    if lane is None and is_build_cmd(a):
        lane = "build"
    if lane == "build":
        slots = slots or int(os.environ.get("AGMM_BUILD_SLOTS", str(BUILD_SLOTS)))
        os.environ.setdefault("HEAVY_MAX_S", str(BUILD_MAX_S))
    slots = slots or 3
    prefix = "slot" if lane is None else "lane-%s-slot" % lane
    os.makedirs(SLOT_DIR, exist_ok=True)
    fh = None
    while fh is None:
        for i in range(slots):
            f = open(os.path.join(SLOT_DIR, "%s-%d.lock" % (prefix, i)), "w")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fh = f; break
            except OSError:
                f.close()
        if fh is None:
            time.sleep(3)
    try:
        # root 6 Oct: hung jobs (a whisper hub check on a dead socket) held all slots ~90 min while ~30 jobs waited.
        # A heavy job gets HEAVY_MAX_S (default 30 min) of wall time, then it is stopped and its slot freed (exit 124).
        limit = int(os.environ.get("HEAVY_MAX_S", "1800"))
        # FINISHER 13 Oct: the job runs in its OWN process group and the timeout stops the whole group. Before, only the direct
        # child was terminated: S63's produce.py was stopped at 2700 s while its qa/gate.py child (and ffmpeg/ocr_vision under it)
        # ran on outside any slot, kept the load up, and 31 min later wrote a 10-of-15-check GATE.json that the board read as a
        # PASS. A TERM/INT/HUP sent to heavy.py is forwarded to the group too, so stopping heavy.py stops its job.
        import signal
        p = subprocess.Popen(["nice", "-n", "15"] + a, start_new_session=True)

        def _group(sig):
            try:
                os.killpg(p.pid, sig)
            except OSError:
                pass

        def _forward(signum, _frame):
            _group(signum)
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                _group(signal.SIGKILL)
            sys.exit(128 + signum)
        for _s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(_s, _forward)
        try:
            sys.exit(p.wait(timeout=limit))
        except subprocess.TimeoutExpired:
            _group(signal.SIGTERM)
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pass
            _group(signal.SIGKILL)      # whatever is left of the group (grandchildren that ignored TERM)
            sys.stderr.write("heavy.py: job exceeded %d s and was stopped (whole process group) to free its slot\n" % limit)
            sys.exit(124)
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN); fh.close()


if __name__ == "__main__":
    main()
