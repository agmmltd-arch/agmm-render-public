#!/usr/bin/env python3
"""produce.py <ID> [--from STAGE] [--only STAGE] [--spec-tokens N] [--status TEXT]

One short, end to end, idempotent and resumable (state in kit/out/<ID>/state.json; a finished stage is skipped
unless --from names it or an earlier stage):
  build     build_short.py specs/<ID>.json  (images, audio + music-gap check, sealed part projects)
  dispatch  commit the package to agmmltd-arch/agmm-video-render and dispatch agmm-v2-design-system-render.yml
            with one matrix target per part (parallel runners); guards: package present at the commit with the same
            sha256, commit on origin/main, run found by its head sha (P1 once logged another build's run)
  wait      poll the run until it completes; every part job must succeed
  pull      tooling/render/pull_and_prune.sh (verify every artifact with ffprobe, then delete it from GitHub)
  assemble  concat the parts by stream copy (no picture re-encode on the Mac) + mux the mix (AAC 320k) -> FINAL.mp4
  gate      qa/gate.py (10 checks) + kit checks 11-15 on FINAL.mp4; on GitHub Actions by default (kit/tools/gate_actions.py), AGMM_GATE=local for the old path
  web       <ID>-web.mp4 (h264 crf 22, maxrate 10M, faststart) + poster.jpg (the hook frame)
  card      card.json for the review page (src, not video; reference + reference_url from the script file)
ffmpeg is nice'd, 2 threads, one process at a time.

RENDER PATH: the implicit default is AGMM_RENDER=codespace so a missing environment variable cannot start media
work on this Mac. AGMM_RENDER=local and AGMM_RENDER=auto remain explicit operator choices only. A local dispatch
renders every part on this Mac, SEQUENTIALLY, one render at a time, `nice -n 15`, `--workers 1`, behind the local
guard, then applies the runner's bitrate cap. 4K parts are skipped locally (res4k_skipped_local). wait/pull are
no-ops for a local round. AGMM_RENDER=codespace runs root's tools/render_codespace.py (GitHub Codespaces free
allowance; parts land in renders/r<N>/cs-<part>/) with the same stage marking; AGMM_RENDER=actions (alias github)
restores the Actions path.
AGMM_RENDER=cloud (25 Sep) renders in a Claude Code cloud session on the $250 cloud credit, in two passes: the first
dispatch stages the package in the render repo and exits 3 with the routine body for a Claude session to fire
(RemoteTrigger); `--from dispatch` after the run pulls the parts to renders/r<N>/cc-<part>/. See kit/CLOUD-RENDER.md.
Local stays the fallback. See kit/LOCAL-RENDER.md."""
import argparse, atexit, fcntl, glob, hashlib, json, os, re, shutil, signal, subprocess, sys, tarfile, threading, time
from datetime import datetime, timezone

KIT = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.dirname(KIT)
ROOT = os.path.dirname(V2)                    # the build root the review page serves (paths in cards start with v2/)
REPO = "agmmltd-arch/agmm-video-render"
WF = "agmm-kit-render.yml"          # per-target res (1080 | 4k supersampled), --quality high masters
RR = os.path.join(KIT, ".render-repo")
STAGES = ["build", "dispatch", "wait", "pull", "assemble", "gate", "web", "better", "card", "publish"]


def spec_of(ID):
    p = os.path.join(KIT, "specs", ID, "spec.json")
    return p if os.path.exists(p) else os.path.join(KIT, "specs", ID + ".json")


def sh(cmd, cwd=None, check=True, nice=False, env=None):
    if nice:
        cmd = ["nice", "-n", "15"] + cmd
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if check and p.returncode:
        sys.exit("FAILED: %s\n%s\n%s" % (" ".join(cmd[:6]), p.stdout[-2000:], p.stderr[-2000:]))
    return p


class State:
    def __init__(self, out):
        self.path = os.path.join(out, "state.json")
        self.d = json.load(open(self.path)) if os.path.exists(self.path) else {"stages": {}}

    def done(self, s):
        return self.d["stages"].get(s, {}).get("ok")

    def mark(self, s, **kw):
        self.d["stages"][s] = dict(kw, ok=True, at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        json.dump(self.d, open(self.path, "w"), indent=1)

    def reset_from(self, s):
        for x in STAGES[STAGES.index(s):]:
            self.d["stages"].pop(x, None)
            # stale per-stage seconds from an earlier round made a local round report wait 1105 s / pull 463 s (24 Sep)
            self.d.get("cost", {}).get("wall_seconds_by_stage", {}).pop(x, None)
        json.dump(self.d, open(self.path, "w"), indent=1)


def render_repo():
    if not os.path.isdir(os.path.join(RR, ".git")):
        sh(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", "https://github.com/%s.git" % REPO, RR])
        sh(["git", "sparse-checkout", "set", "--no-cone", "/.github/workflows/" + WF, "/video-program/kit/"], cwd=RR)
        sh(["git", "checkout", "-q", "main"], cwd=RR)
    return RR


def stage_build(ID, out, st, a):
    t = time.time()
    p = subprocess.run(["python3", os.path.join(KIT, "build_short.py"), spec_of(ID)], capture_output=True, text=True)
    open(os.path.join(out, "build.log"), "w").write(p.stdout + p.stderr)
    if p.returncode:
        sys.exit("build failed:\n" + (p.stdout + p.stderr)[-3000:])
    print(p.stdout.strip().splitlines()[-1])
    st.mark("build", seconds=round(time.time() - t, 1))


MIN_FREE_GB = 4    # root, 24 Sep set 10 (the Mac was at 97% with 102 shorts to go). Root 28 Sep: 4. One codespace render adds
                   # ~0.3-0.4 GB of parts + FINAL and the gate ~0.5 GB temp; the growth that filled the disk was PNG snaps
                   # (3.5 GB in a morning), now written as JPG by tools/snap.py. Below 4 GB nothing new dispatches.


def disk_guard(where):
    free = shutil.disk_usage(os.path.expanduser("~")).free / 1e9
    if free < MIN_FREE_GB:
        sys.exit("DISK GUARD (%s): only %.1f GB free, need %d. Prune posted masters / old rounds first." % (where, free, MIN_FREE_GB))


# ------------------------------------------------------------------------------------------------ local render path
RENDER_MODE = os.environ.get("AGMM_RENDER", "actions")   # root 12 Oct: Codespaces billing is dead; Actions renders work.strip().lower()
# `auto` is retained for an explicit operator request. tools/render_sched.py then picks local when the box is idle
# enough and disk allows, codespace otherwise, never both for one short, behind a global cap and FIFO queue.
_ = None   # auto | local | codespace | cloud | actions ("github" = actions)
OFF_ACTIONS = ("local", "codespace", "cloud")   # backends whose parts land on this disk; wait/pull are no-ops for them
HF_PKG = "hyperframes@0.8.71"          # the runner's pinned version (.render-repo/.github/workflows/agmm-kit-render.yml)
LOCAL_WORKERS = 1                      # fixed: render_lease.py only treats --workers 1 renders as leasable
LOCAL_LOAD_MAX = float(os.environ.get("AGMM_LOCAL_LOAD_MAX", "6"))   # 1-min load average above which a part does not start (explicit local; auto lifts it)
LOCAL_MAX_WAIT_MIN = float(os.environ.get("AGMM_LOCAL_MAX_WAIT_MIN", "180"))
SLOT_LOCK = os.path.expanduser("~/alfred/auto-poster/carousel_v3/runtime/video-slot-runner.lock")   # mkdir-lock dir
RENDER_LOCK = os.path.expanduser("~/.cache/agmm-local-render.lock")   # one local render on the Mac, across processes
# identical settings on every part so assemble can still join the parts by stream copy (same as the runner's cap step)
CAP_1080 = ["-map", "0:v:0", "-an", "-c:v", "libx264", "-profile:v", "high", "-preset", "slow", "-crf", "16", "-maxrate", "25M",
            "-bufsize", "50M", "-level:v", "4.2", "-pix_fmt", "yuv420p", "-r", "30", "-g", "60", "-video_track_timescale", "15360",
            "-x264-params", "threads=2",   # input-side -threads does NOT limit libx264 (measured 1173% CPU)
            "-movflags", "+faststart"]
HF_RE = re.compile(r"hyperframes\S*\s+render\b")


def _free_gb():
    return shutil.disk_usage(os.path.expanduser("~")).free / 1e9


def _other_renders():
    rows = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout.splitlines()
    return [r.strip() for r in rows if HF_RE.search(r) and int(r.split(None, 1)[0]) != os.getpid()]


def local_guard(log, where, load=True):
    """Wait (never fail fast) while the Mac is busy: 1-min load > 6, < 10 GB free, an autoposter slot running (its
    lock dir exists), or any other hyperframes render running. Every wait is logged; gives up after
    AGMM_LOCAL_MAX_WAIT_MIN."""
    t0, last = time.time(), None
    while True:
        why = []
        l1 = os.getloadavg()[0]
        if load and l1 > LOCAL_LOAD_MAX:
            why.append("load %.2f > %.0f" % (l1, LOCAL_LOAD_MAX))
        if _free_gb() < MIN_FREE_GB:
            why.append("disk %.1f GB free < %d" % (_free_gb(), MIN_FREE_GB))
        if os.path.exists(SLOT_LOCK):
            why.append("autoposter slot running (%s)" % SLOT_LOCK)
        others = _other_renders()
        if others:
            why.append("another hyperframes render is running: %s" % others[0][:160])
        if not why:
            w = round(time.time() - t0)
            if w:
                log("guard %s: clear after %ds" % (where, w))
            return w
        key = "; ".join(x.split()[0] for x in why)      # the kinds of block, not their values (log on change + every 5 min)
        if key != last or int(time.time() - t0) % 300 < 30:
            log("guard %s: WAIT %s" % (where, "; ".join(why)))
            last = key
        if time.time() - t0 > LOCAL_MAX_WAIT_MIN * 60:
            sys.exit("LOCAL GUARD (%s): still blocked after %.1f min: %s" % (where, LOCAL_MAX_WAIT_MIN, "; ".join(why)))
        time.sleep(30)


class Monitor(threading.Thread):
    """Samples the Mac while a local round runs: every 5 s the render process tree's CPU% and RSS, spawn latency of
    /usr/bin/true and timer overshoot (responsiveness); every 30 s one log line with `uptime` and vm_stat."""
    def __init__(self, path):
        super().__init__(daemon=True)
        self.path, self.root, self.stop_ev = path, None, threading.Event()
        self.peak = {"tree_cpu_pct": 0.0, "tree_rss_mb": 0.0, "load1": 0.0, "spawn_ms": 0.0, "timer_overshoot_ms": 0.0}
        self.min_free_mb, self.n, self.swapouts0, self.swapouts = None, 0, None, None
        self.fh = open(path, "a")

    def _tree(self):
        if not self.root:
            return 0.0, 0.0, 0
        rows = []
        for line in subprocess.run(["ps", "-axo", "pid=,ppid=,%cpu=,rss="], capture_output=True, text=True).stdout.splitlines():
            p = line.split()
            if len(p) == 4:
                rows.append((int(p[0]), int(p[1]), float(p[2]), int(p[3])))
        found, changed = {self.root}, True
        while changed:
            changed = False
            for pid, ppid, _, _ in rows:
                if ppid in found and pid not in found:
                    found.add(pid); changed = True
        cpu = sum(r[2] for r in rows if r[0] in found); rss = sum(r[3] for r in rows if r[0] in found) / 1024
        return cpu, rss, len(found & {r[0] for r in rows})

    def _vm(self):
        s = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
        pg = int(re.search(r"page size of (\d+)", s).group(1))
        g = lambda k: int(re.search(r"%s:\s+(\d+)" % k, s).group(1))
        return {"free_mb": round(g("Pages free") * pg / 2**20), "compressor_mb": round(g("Pages occupied by compressor") * pg / 2**20),
                "swapouts": g("Swapouts")}

    def run(self):
        while not self.stop_ev.is_set():
            t = time.time()
            subprocess.run(["/usr/bin/true"]); spawn = (time.time() - t) * 1000
            cpu, rss, nproc = self._tree(); l1 = os.getloadavg()[0]
            for k, v in (("tree_cpu_pct", cpu), ("tree_rss_mb", rss), ("load1", l1), ("spawn_ms", spawn)):
                self.peak[k] = max(self.peak[k], round(v, 1))
            if self.n % 6 == 0:
                vm = self._vm()
                self.swapouts0 = vm["swapouts"] if self.swapouts0 is None else self.swapouts0
                self.swapouts = vm["swapouts"]
                self.min_free_mb = vm["free_mb"] if self.min_free_mb is None else min(self.min_free_mb, vm["free_mb"])
                up = subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip()
                self.fh.write("%s | %s | vm free %dMB compressor %dMB swapouts %d | render tree %d procs cpu %.0f%% rss %.0fMB | spawn %.0fms\n" % (
                    time.strftime("%H:%M:%S"), up, vm["free_mb"], vm["compressor_mb"], vm["swapouts"], nproc, cpu, rss, spawn))
                self.fh.flush()
            self.n += 1
            t = time.time(); self.stop_ev.wait(5)
            if not self.stop_ev.is_set():
                self.peak["timer_overshoot_ms"] = max(self.peak["timer_overshoot_ms"], round((time.time() - t - 5) * 1000, 1))

    def summary(self):
        return dict(self.peak, min_vm_free_mb=self.min_free_mb, swapouts_during=(self.swapouts - self.swapouts0) if self.swapouts0 is not None else None,
                    samples=self.n, log=self.path)

    def close(self):
        self.stop_ev.set(); self.join(10); self.fh.close()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _verify_part(final, part, backend):
    """probe + FULL decode of one part master (the runner's framemd5 step): frame count must equal dur x 30"""
    odir = os.path.dirname(final)
    pj = sh(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", final]).stdout
    open(os.path.join(odir, part["out"] + ".ffprobe.json"), "w").write(pj)
    frames = int(json.loads(sh(["ffprobe", "-v", "error", "-threads", "2", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                "stream=nb_read_frames", "-of", "json", final], nice=True).stdout)["streams"][0]["nb_read_frames"])
    want = int(round(part["dur"] * 30))
    # the part duration is written to 3 decimals, so a part of 434 frames reads 14.467 s = 434.01 frames and the renderer
    # makes ceil() = 435 (o2, 25 Sep: C10 lost a 20-minute render to it). Accept exactly that one explained frame.
    import math
    # 25 Sep (o5, S25 cloud): with an exact duration (e.g. 425 frames) ceil() adds nothing, yet the renderer still
    # emits one trailing frame on the 2-mod-3 part split (426). The same single explained frame, whichever way it arises.
    allowed = {want, int(math.ceil(part["dur"] * 30 - 1e-9)), want + 1}
    open(os.path.join(odir, part["out"] + ".frames.txt"), "w").write("frames: %d (expected %s)\n" % (frames, sorted(allowed)))
    open(os.path.join(odir, part["out"] + ".sha256"), "w").write("%s  %s\n" % (_sha256(final), os.path.basename(final)))
    if frames not in allowed:
        sys.exit("%s render %s: %d frames decoded, expected %d" % (backend, part["out"], frames, want))
    v = [x for x in json.loads(pj)["streams"] if x["codec_type"] == "video"][0]
    return {"frames": frames, "size": "%dx%d" % (v["width"], v["height"]), "mbps": round(int(json.loads(pj)["format"]["bit_rate"]) / 1e6, 1),
            "bytes": os.path.getsize(final)}


def _mark_offactions(ID, out, st, n, run, dest, wall, **kw):
    """shared by every backend that leaves the parts on this disk (local, codespace): dispatch/wait/pull done, same
    layout renders/r<N>/<backend>-<part>/<out>.mp4 that stage_assemble globs"""
    st.d["round"] = n
    st.mark("dispatch", run=run, tag="k%s-r%d-%s" % (ID.lower(), n, run), render_wall_minutes=wall, **kw)
    st.mark("wait", run=run, render_runner_minutes=0, render_wall_minutes=wall, render_offactions_minutes=wall)
    st.mark("pull", run=run, dest=dest)
    with open(os.path.join(out, "RUNS.log"), "a") as fh:
        fh.write("r%d %s package_sha256=%s wall_min=%.1f %s\n" % (n, run.upper(), kw.get("package_sha256"), wall,
                 " ".join("%s=%s" % (k, kw[k]) for k in ("workers", "res4k_skipped_local") if k in kw)))


def _render_part_local(look_dir, part, dest, log, mon):
    """one part: the runner's steps (verify SHA256SUMS, static_check.py, render at --quality high, cap bitrate, probe
    and fully decode), on the Mac"""
    for line in open(os.path.join(look_dir, "SHA256SUMS.txt")):
        if line.strip():
            h, f = line.split(None, 1); f = f.strip().lstrip("*")
            if _sha256(os.path.join(look_dir, f)) != h:
                sys.exit("local render %s: SHA256SUMS mismatch on %s" % (part["out"], f))
    sh(["python3", "static_check.py"], cwd=look_dir)
    odir = os.path.join(dest, "local-" + part["out"]); os.makedirs(odir, exist_ok=True)
    raw, final = os.path.join(odir, part["out"] + ".raw.mp4"), os.path.join(odir, part["out"] + ".mp4")
    rec = {"part": part["out"], "look": part["look"]}
    rec["guard_wait_s"] = local_guard(log, "before render " + part["out"])
    lk = open(RENDER_LOCK, "w")
    fcntl.flock(lk, fcntl.LOCK_EX)               # one local render on this Mac, whoever started it
    try:
        rec["guard_wait_s"] += local_guard(log, "after lock " + part["out"])
        cmd = ["nice", "-n", "15", "npx", "--yes", HF_PKG, "render", "-c", part["file"], "--fps", "30", "--workers", str(LOCAL_WORKERS),
               "--quality", "high", "--output", raw]
        log("render %s: %s" % (part["out"], " ".join(cmd)))
        t = time.time()
        with open(os.path.join(odir, part["out"] + ".render.log"), "w") as fh:
            proc = subprocess.Popen(cmd, cwd=look_dir, stdout=fh, stderr=subprocess.STDOUT, env=dict(os.environ, HYPERFRAMES_NO_TELEMETRY="1"))
            mon.root = proc.pid
            rc = proc.wait()
            mon.root = None
        rec["render_s"] = round(time.time() - t, 1)
        if rc or not os.path.exists(raw):
            sys.exit("local render %s failed (exit %s); see %s" % (part["out"], rc, os.path.join(odir, part["out"] + ".render.log")))
        rec["cap_guard_wait_s"] = local_guard(log, "before cap " + part["out"], load=False)
        t = time.time()
        # -threads 2 before -i caps the DECODER (auto = one frame thread per core); -filter_threads 1 the scaler
        sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-filter_threads", "1", "-threads", "2", "-i", raw] + CAP_1080 + [final], nice=True)
        rec["cap_s"] = round(time.time() - t, 1)
        rec["bytes_before_cap"], rec["bytes"] = os.path.getsize(raw), os.path.getsize(final)
        open(os.path.join(odir, part["out"] + ".cap.txt"), "w").write("before %d after %d\n" % (rec["bytes_before_cap"], rec["bytes"]))
        os.remove(raw)
    finally:
        fcntl.flock(lk, fcntl.LOCK_UN); lk.close()
    rec.update(_verify_part(final, part, "local"))
    log("part %s done: render %.0fs, cap %.0fs, %d frames, %s, %.1f Mbps, %.0f MB" % (
        part["out"], rec["render_s"], rec["cap_s"], rec["frames"], rec["size"], rec["mbps"], rec["bytes"] / 1e6))   # box 29 Sep: was the undefined `frames` (NameError after every local part since 25 Sep)
    return rec


def stage_dispatch_local(ID, out, st, a):
    disk_guard("local dispatch")
    parts = json.load(open(os.path.join(out, "build/parts.json")))
    n = st.d.get("round", 0) + 1
    dest = os.path.join(out, "renders", "r%d" % n); os.makedirs(dest, exist_ok=True)
    logp = os.path.join(dest, "local-render.log")

    def log(msg):
        line = "%s %s" % (time.strftime("%F %T"), msg); print(line, flush=True)
        with open(logp, "a") as fh:
            fh.write(line + "\n")
    pkg = os.path.join(out, "build/source.tar.gz")
    sha = open(pkg + ".sha256").read().split()[0]
    if _sha256(pkg) != sha:
        sys.exit("local dispatch: package hash mismatch")
    work = os.path.join(out, "local-work", "r%d" % n)
    shutil.rmtree(work, ignore_errors=True); os.makedirs(work)
    with tarfile.open(pkg) as tf:
        tf.extractall(work)
    spec = json.load(open(spec_of(ID)))
    skip4k = bool(spec.get("render", {}).get("res4k"))
    if skip4k:
        log("spec asks for 4K masters: SKIPPED locally (res4k_skipped_local); 1080 masters only")
    mon = Monitor(os.path.join(dest, "local-monitor.log")); mon.start()
    t0, recs = time.time(), []
    log("local round r%d: %d parts, sequential, nice 15, --workers %d, package %s" % (n, len(parts["parts"]), LOCAL_WORKERS, sha[:12]))
    try:
        for p in parts["parts"]:
            recs.append(_render_part_local(os.path.join(work, p["look"]), p, dest, log, mon))
    finally:
        mon.close()
    wall = round((time.time() - t0) / 60, 1)
    shutil.rmtree(work, ignore_errors=True)
    m = mon.summary()
    log("local round r%d done: %.1f min wall, peak tree CPU %.0f%%, peak RSS %.0f MB, peak load %.2f, max spawn %.0f ms" % (
        n, wall, m["tree_cpu_pct"], m["tree_rss_mb"], m["load1"], m["spawn_ms"]))
    _mark_offactions(ID, out, st, n, "local", dest, wall, package_sha256=sha, workers=LOCAL_WORKERS, parts=recs,
                     res4k_skipped_local=skip4k, monitor=m, log=logp)


def storyboard_guard(ID):
    """25 Sep 02:25: no render without an art-director-approved storyboard (tools/storyboard.py).
    25 Sep 08:20 (the inspector found it): the guard ran only on the codespace path, so a local or actions render
    walked round it; it now runs in stage_dispatch for every mode. The skip switch needs a reviewer too, and an
    approval covers the spec it saw: a spec or scenes change after approval needs a new one (C08 was changed two
    minutes after approval on 25 Sep and only the art director's own eye caught it)."""
    sys.path.insert(0, os.path.join(KIT, "tools"))
    import storyboard as sb
    rp = os.path.join(KIT, "registry", "storyboards", ID + ".json")
    rec = json.load(open(rp)) if os.path.exists(rp) else {}
    state = rec.get("state")
    if os.environ.get("AGMM_SKIP_STORYBOARD") == "1":
        if os.environ.get("AGMM_REVIEWER") != "1":
            sys.exit("STORYBOARD GUARD: AGMM_SKIP_STORYBOARD needs AGMM_REVIEWER=1 as well; writers cannot skip the art director.")
        print("STORYBOARD GUARD skipped by a reviewer for %s" % ID, file=sys.stderr)
        return
    if state != "approved":
        sys.exit("STORYBOARD GUARD: %s has no approved storyboard (state %r). Run `python3 tools/storyboard.py submit %s` and wait for approval." % (ID, state, ID))
    want = rec.get("approved_hash")
    if want:
        now = sb.spec_hash(ID)
        if now != want and getattr(sb, "spec_hash_legacy", lambda i: None)(ID) == want:
            now = want   # approved under the pre-28 Sep hash (archives counted); unchanged since
        if now != want:
            sys.exit("STORYBOARD GUARD: %s changed since its storyboard was approved (spec/scenes hash %s, approved %s). Resubmit: `python3 tools/storyboard.py submit %s`." % (ID, now[:12], want[:12], ID))
    else:
        print("STORYBOARD GUARD: %s approval predates hash tracking (approved before 25 Sep 08:20); allowed, resubmit on any change" % ID, file=sys.stderr)


def stage_dispatch_codespace(ID, out, st, a):
    storyboard_guard(ID)
    """root owns tools/render_codespace.py <out_dir> <round>: renders every part in a GitHub Codespace with the
    workflow's commands (bitrate cap included) and copies them to renders/r<N>/cs-<part>/<out>.mp4; exit 0 = all
    parts present. Here: run it, then verify every part exists and fully decodes to dur x 30 frames."""
    disk_guard("codespace dispatch")
    parts = json.load(open(os.path.join(out, "build/parts.json")))["parts"]
    n = st.d.get("round", 0) + 1
    dest = os.path.join(out, "renders", "r%d" % n); os.makedirs(dest, exist_ok=True)
    tool = os.path.join(KIT, "tools", "render_codespace.py")
    if not os.path.exists(tool):
        sys.exit("AGMM_RENDER=codespace but %s does not exist yet; use AGMM_RENDER=local" % tool)
    sha = open(os.path.join(out, "build/source.tar.gz.sha256")).read().split()[0]
    t0 = time.time()
    with open(os.path.join(dest, "codespace-render.log"), "w") as fh:
        rc = subprocess.run(["python3", tool, out, str(n)], stdout=fh, stderr=subprocess.STDOUT).returncode
    wall = round((time.time() - t0) / 60, 1)
    if rc:
        sys.exit("render_codespace.py exited %d; see %s" % (rc, os.path.join(dest, "codespace-render.log")))
    recs = []
    for p in parts:
        f = os.path.join(dest, "cs-" + p["out"], p["out"] + ".mp4")
        if not os.path.exists(f):
            sys.exit("render_codespace.py exited 0 but %s is missing" % f)
        recs.append(dict(_verify_part(f, p, "codespace"), part=p["out"]))
    has4k = all(os.path.exists(os.path.join(dest, "cs-" + p["out"] + "-4K", p["out"] + "-4K.mp4")) for p in parts)
    print("codespace round r%d: %d parts verified in %.1f min" % (n, len(recs), wall))
    _mark_offactions(ID, out, st, n, "codespace", dest, wall, package_sha256=sha, parts=recs, res4k=has4k,
                     log=os.path.join(dest, "codespace-render.log"))


def stage_dispatch_cloud(ID, out, st, a):
    """Claude Code cloud render (kit/CLOUD-RENDER.md). Pass 1: tools/render_cloud.py stage commits the package to
    video-program/kit/<ID>/r<N>/ and writes renders/r<N>/cloud-trigger.json; exit 3 = a Claude session must fire it.
    Pass 2 (same command again, or --from dispatch): render_cloud.py pull reassembles the parts from the results
    branch (sha256 + bytes checked against the cloud manifest), then every part gets the same full-decode check."""
    disk_guard("cloud dispatch")
    parts = json.load(open(os.path.join(out, "build/parts.json")))["parts"]
    n = st.d.get("round", 0) + 1
    dest = os.path.join(out, "renders", "r%d" % n); os.makedirs(dest, exist_ok=True)
    tool = os.path.join(KIT, "tools", "render_cloud.py")
    sha = open(os.path.join(out, "build/source.tar.gz.sha256")).read().split()[0]
    staged = os.path.join(dest, "cloud-staged.json")
    if not os.path.exists(staged) or json.load(open(staged)).get("package_sha256") != sha:
        p = subprocess.run(["python3", tool, "stage", out, str(n)], capture_output=True, text=True)
        open(os.path.join(dest, "cloud-render.log"), "a").write(p.stdout + p.stderr)
        if p.returncode:
            sys.exit("render_cloud.py stage exited %d:\n%s" % (p.returncode, (p.stdout + p.stderr)[-1500:]))
        json.dump({"package_sha256": sha, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, open(staged, "w"))
        print(p.stdout.strip())
        print("CLOUD STAGED %s r%d: a Claude session fires RemoteTrigger create+run with %s, then re-run this command"
              % (ID, n, os.path.join(dest, "cloud-trigger.json")))
        sys.exit(3)
    p = subprocess.run(["python3", tool, "pull", out, str(n)], capture_output=True, text=True)
    open(os.path.join(dest, "cloud-render.log"), "a").write(p.stdout + p.stderr)
    if p.returncode == 3:
        print("CLOUD WAITING %s r%d: no results branch yet (fire %s if nobody has)" % (ID, n, os.path.join(dest, "cloud-trigger.json")))
        sys.exit(3)
    if p.returncode:
        sys.exit("render_cloud.py pull exited %d:\n%s" % (p.returncode, (p.stdout + p.stderr)[-1500:]))
    man = json.load(open(os.path.join(dest, "cloud-manifest.json")))
    recs = []
    for pt in parts:
        f = os.path.join(dest, "cc-" + pt["out"], pt["out"] + ".mp4")
        if not os.path.exists(f):
            sys.exit("render_cloud.py pull exited 0 but %s is missing" % f)
        recs.append(dict(_verify_part(f, pt, "cloud"), part=pt["out"]))
    wall = round(man["total_s"] / 60, 1)
    print("cloud round r%d: %d parts verified; cloud render %.1f min" % (n, len(recs), wall))
    _mark_offactions(ID, out, st, n, "cloud", dest, wall, package_sha256=sha, parts=recs, res4k=False,
                     branch=man.get("branch"), log=os.path.join(dest, "cloud-render.log"))


def stage_dispatch(ID, out, st, a):
    global LOCAL_LOAD_MAX
    storyboard_guard(ID)  # every render path, not only codespace
    if RENDER_MODE not in ("auto", "local", "codespace", "cloud", "actions", "github"):
        sys.exit("AGMM_RENDER must be auto, local, codespace, cloud or actions, not %r" % RENDER_MODE)
    sys.path.insert(0, os.path.join(KIT, "tools")); import render_sched   # box 29 Sep
    mode = RENDER_MODE
    if mode == "auto":
        disk_guard("auto dispatch")
        mode = render_sched.acquire(ID)       # waits in the FIFO queue; holds the per-short lock until this process exits
        # the scheduler judged the box by CPU idle, memory pressure and disk; the 1-min load average reads 40-90 on this
        # Mac under the fleet while 20-40% of the CPU is idle, so the old per-part load <= 6 wait would never clear
        LOCAL_LOAD_MAX = float(os.environ.get("AGMM_LOCAL_LOAD_MAX", "1e9"))
    else:
        render_sched.claim_id(ID, mode)       # explicit modes: still one backend per short at a time
    if mode in ("local", "codespace", "cloud"):
        try:
            return {"local": stage_dispatch_local, "codespace": stage_dispatch_codespace, "cloud": stage_dispatch_cloud}[mode](ID, out, st, a)
        finally:
            render_sched.release(ID)          # the slot frees when the parts are in; gate/web/judge do not hold it
    disk_guard("dispatch")
    rr = render_repo()
    parts = json.load(open(os.path.join(out, "build/parts.json")))
    n = st.d.get("round", 0) + 1
    tag = "k%s-r%d" % (ID.lower(), n)
    pkg = "video-program/kit/%s/r%d/source.tar.gz" % (ID, n)
    env = dict(os.environ, GIT_AUTHOR_NAME="ALFRED Brain", GIT_AUTHOR_EMAIL="agmm.ltd@gmail.com", GIT_COMMITTER_NAME="ALFRED Brain", GIT_COMMITTER_EMAIL="agmm.ltd@gmail.com")
    sh(["git", "pull", "-q", "--rebase", "origin", "main"], cwd=rr, env=env)
    os.makedirs(os.path.join(rr, os.path.dirname(pkg)), exist_ok=True)
    shutil.copy(os.path.join(out, "build/source.tar.gz"), os.path.join(rr, pkg))
    sha = open(os.path.join(out, "build/source.tar.gz.sha256")).read().strip()
    sh(["git", "add", "--sparse", pkg], cwd=rr)
    sh(["git", "commit", "-q", "-m", "kit %s package r%d" % (ID, n)], cwd=rr, env=env)
    for i in range(5):
        if sh(["git", "pull", "-q", "--rebase", "origin", "main"], cwd=rr, check=False, env=env).returncode == 0 and \
                sh(["git", "push", "-q", "origin", "HEAD:main"], cwd=rr, check=False).returncode == 0:
            break
        sh(["git", "rebase", "--abort"], cwd=rr, check=False); time.sleep(5 * (i + 1))
    else:
        sys.exit("push failed")
    src = sh(["git", "rev-parse", "HEAD"], cwd=rr).stdout.strip()
    got = subprocess.run("git show %s:%s | shasum -a 256" % (src, pkg), shell=True, cwd=rr, capture_output=True, text=True).stdout.split()[0]
    if got != sha:
        sys.exit("package hash mismatch at %s" % src)
    sh(["git", "fetch", "-q", "origin", "main"], cwd=rr)
    if sh(["git", "merge-base", "--is-ancestor", src, "origin/main"], cwd=rr, check=False).returncode:
        sys.exit("%s not on origin/main" % src)
    # 1080 masters always; a 4K (2160x3840, supersampled) master too for YouTube-bound shorts (spec render.res4k)
    spec = json.load(open(spec_of(ID)))
    tl = [{"look": p["look"], "file": p["file"], "out": p["out"], "res": "1080"} for p in parts["parts"]]
    if spec.get("render", {}).get("res4k"):
        tl += [{"look": p["look"], "file": p["file"], "out": p["out"] + "-4K", "res": "4k"} for p in parts["parts"]]
    targets = json.dumps(tl)
    t0 = datetime.now(timezone.utc)
    sh(["gh", "workflow", "run", WF, "--repo", REPO, "--ref", "main", "-f", "source_sha=" + src, "-f", "package=" + pkg,
        "-f", "package_sha256=" + sha, "-f", "targets=" + targets, "-f", "tag=" + tag])
    run = None
    for _ in range(30):
        time.sleep(6)
        rows = json.loads(sh(["gh", "run", "list", "--repo", REPO, "--workflow", WF, "--limit", "15", "--json", "databaseId,headSha,createdAt,event"]).stdout)
        since = (t0.timestamp() - 90)
        cands = [r for r in rows if r["headSha"] == src and r["event"] == "workflow_dispatch" and datetime.strptime(r["createdAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() >= since]
        if cands:
            run = cands[-1]["databaseId"]; break
    if not run:
        sys.exit("dispatched but could not find the run for %s" % src)
    st.d["round"] = n
    st.mark("dispatch", run=run, tag=tag, source_sha=src, package=pkg, package_sha256=sha, dispatched=t0.isoformat(timespec="seconds"))
    with open(os.path.join(out, "RUNS.log"), "a") as fh:
        fh.write("r%d source_sha=%s package_sha256=%s run=%s tag=%s\n" % (n, src, sha, run, tag))
    print("dispatched r%d run %s (%d parts)" % (n, run, len(parts["parts"])))


def stage_wait(ID, out, st, a):
    run = st.d["stages"]["dispatch"]["run"]
    if run in OFF_ACTIONS:        # a local/codespace round rendered inside dispatch; nothing to wait for
        d = st.d["stages"]["dispatch"]
        st.mark("wait", run=run, render_runner_minutes=0, render_wall_minutes=d.get("render_wall_minutes"), render_offactions_minutes=d.get("render_wall_minutes"))
        return
    while True:
        r = json.loads(sh(["gh", "run", "view", str(run), "--repo", REPO, "--json", "status,conclusion,jobs"]).stdout)
        if r["status"] == "completed":
            break
        time.sleep(30)
    jobs = [{"name": j["name"], "conclusion": j["conclusion"], "started": j["startedAt"], "completed": j["completedAt"]} for j in r["jobs"]]

    def secs(j):
        f = "%Y-%m-%dT%H:%M:%SZ"
        return (datetime.strptime(j["completed"], f) - datetime.strptime(j["started"], f)).total_seconds()
    mins = round(sum(secs(j) for j in jobs) / 60, 1)
    wall = round(max(secs(j) for j in jobs) / 60, 1)
    if r["conclusion"] != "success" or any(j["conclusion"] != "success" for j in jobs):
        st.d["stages"]["wait_failed"] = {"run": run, "jobs": jobs}
        json.dump(st.d, open(st.path, "w"), indent=1)
        sys.exit("render run %s concluded %s: %s" % (run, r["conclusion"], [(j["name"], j["conclusion"]) for j in jobs]))
    st.mark("wait", run=run, jobs=jobs, render_runner_minutes=mins, render_wall_minutes=wall)
    print("run %s ok: %.1f runner-min, %.1f min wall (longest part)" % (run, mins, wall))


def stage_pull(ID, out, st, a):
    run = st.d["stages"]["dispatch"]["run"]
    if run in OFF_ACTIONS:        # the parts are already on disk under renders/r<N>/<local|cs>-<part>/
        st.mark("pull", run=run, dest=os.path.join(out, "renders", "r%d" % st.d["round"]))
        return
    disk_guard("pull")
    dest = os.path.join(out, "renders", "r%d" % st.d["round"])
    os.makedirs(dest, exist_ok=True)
    p = sh(["bash", os.path.join(V2, "tooling/render/pull_and_prune.sh"), str(run), dest], check=False)
    open(os.path.join(dest, "pull.stdout.txt"), "w").write(p.stdout + p.stderr)
    if p.returncode:
        sys.exit("pull_and_prune failed: " + (p.stdout + p.stderr)[-1500:])
    st.mark("pull", dest=dest)


def _concat(dest, parts, suffix, out_path, mix):
    files = []
    for p in parts:
        hits = glob.glob(os.path.join(dest, "*", p["out"] + suffix + ".mp4"))
        if len(hits) != 1:
            sys.exit("part %s%s: expected one render, found %s" % (p["out"], suffix, hits))
        files.append(hits[0])
    lst = os.path.join(dest, "parts%s.txt" % suffix)
    open(lst, "w").write("".join("file '%s'\n" % f for f in files))
    sh(["ffmpeg", "-v", "error", "-y", "-threads", "2", "-f", "concat", "-safe", "0", "-i", lst, "-i", mix,
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest", "-movflags", "+faststart", out_path], nice=True)
    return json.loads(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration,size,bit_rate:stream=codec_type,width,height,r_frame_rate,nb_frames", "-of", "json", out_path]).stdout)


def stage_assemble(ID, out, st, a):
    """parts join by stream copy (the picture is never re-encoded on the Mac); the 1080 master is the gate's file,
    the 4K master (when rendered) is the YouTube upload"""
    dest = st.d["stages"]["pull"]["dest"]
    parts = json.load(open(os.path.join(out, "build/parts.json")))["parts"]
    mix = os.path.join(out, "audio/mix.wav")
    pr = _concat(dest, parts, "", os.path.join(out, "FINAL.mp4"), mix)
    kw = {"final": os.path.join(out, "FINAL.mp4"), "probe": pr}
    if glob.glob(os.path.join(dest, "*", parts[0]["out"] + "-4K.mp4")):
        kw["final_4k"] = os.path.join(out, "FINAL-4K.mp4")
        kw["probe_4k"] = _concat(dest, parts, "-4K", kw["final_4k"], mix)
    elif os.path.exists(os.path.join(out, "FINAL-4K.mp4")):
        # an earlier round's 4K master (older voice/picture) must not sit beside this round's 1080 master as if current
        stale = os.path.join(out, "FINAL-4K.mp4"); kw["removed_stale_4k_bytes"] = os.path.getsize(stale); os.remove(stale)
        print("removed stale FINAL-4K.mp4 from an earlier round (%.2f GB); this round has no 4K parts" % (kw["removed_stale_4k_bytes"] / 1e9))
    st.mark("assemble", **kw)
    # older rounds' part files are superseded once this round's masters exist (S11 kept 2.7 GB of them)
    freed = 0
    for f in glob.glob(os.path.join(out, "renders", "r*", "*", "*.mp4")):
        if not f.startswith(dest + os.sep):
            freed += os.path.getsize(f); os.remove(f)
    if freed: print("pruned %.2f GB of superseded round parts" % (freed / 1e9))
    for k in ("probe", "probe_4k"):
        if k in kw:
            v = [s for s in kw[k]["streams"] if s["codec_type"] == "video"][0]
            print("%s %dx%d %.2fs %s frames %.1f Mbps" % (k, v["width"], v["height"], float(kw[k]["format"]["duration"]), v.get("nb_frames"), int(kw[k]["format"]["bit_rate"]) / 1e6))




# ------------------------------------------------------------------ speed build 29 Sep: overlap the waiting stages
# Measured 29 Sep (tools/speed-2026-09-29/STATE-render.md): after the render a short spent gate ~1260 s + web ~250 s +
# better (judge) up to its 1200 s timeout STRICTLY one after another, and ~35 min of that was network waiting (the
# gate's critic, the judge's Gemini passes). web and better read only FINAL.mp4 (+ the spec), never the gate's result,
# so when this invocation will run them anyway they START with the gate and are collected, in the same order and
# with the same checks, when their stage comes. Nothing is skipped; every stage still records and fails as before.
# gate_core.py holds the gate's check runner (shared with the GitHub Actions gate); the names stay importable from here
from gate_core import gate_cmd, _append_check, _run_gate_checks, _kit_checks, web_cmd, poster_cmd  # noqa: E402,F401

PLAN = []          # the stages this invocation will run (main sets it); an --only run starts nothing early
_BG = {}           # "web" / "judge" -> {"proc", "t0", ...} started early by stage_gate


def _bg_cleanup():
    """a stage that exits early (sys.exit) must not leave an early-started encode or judge running"""
    for k in list(_BG):
        b = _BG.pop(k)
        if b["proc"].poll() is None:
            try:
                os.killpg(b["proc"].pid, signal.SIGKILL)
            except OSError:
                pass
            b["proc"].wait()


atexit.register(_bg_cleanup)


def _web_cmd(ID, out):
    final, web = os.path.join(out, "FINAL.mp4"), os.path.join(out, ID + "-web.mp4")
    # written to <web>.part and renamed on success: a killed encode never leaves a half file under the real name
    return web_cmd(final, web + ".part")


def _start_web(ID, out):
    logp = os.path.join(out, "web-encode.log")
    _BG["web"] = {"proc": subprocess.Popen(_web_cmd(ID, out), stdout=open(logp, "w"), stderr=subprocess.STDOUT, start_new_session=True),
                  "t0": time.time(), "log": logp}


def _judge_args(ID, out, st):
    spec = json.load(open(spec_of(ID)))
    url = spec.get("reference_url") or reference_from_script(_script(spec))[0]
    ref = spec.get("judge_against", url)
    ref = ref if ref.startswith("http") or os.path.isabs(ref) else os.path.join(V2, ref)
    jdir = os.path.join(out, "judge", "r%d" % st.d["round"])
    return spec, url, ref, jdir


def _start_judge(ID, out, st):
    spec, url, ref, jdir = _judge_args(ID, out, st)
    os.makedirs(os.path.dirname(jdir), exist_ok=True)
    logp = jdir + ".running.log"
    _BG["judge"] = {"proc": subprocess.Popen(["python3", os.path.join(KIT, "tools/judge.py"), os.path.join(out, "FINAL.mp4"), "--ref", ref, "--out", jdir, "--passes", "2"],
                                             stdout=open(logp, "w"), stderr=subprocess.STDOUT, start_new_session=True),
                    "t0": time.time(), "log": logp}






# 12 Oct (speed card): AGMM_GATE=actions (the default; AGMM_GATE=local forces the old path) runs the 15 checks on GitHub Actions (macos-latest, public repo: free) and keeps only
# the critic (check 9, network + keys) and the fetch on this Mac; local = the old path. AGMM_GATE_FALLBACK=local lets a failed
# Actions gate run locally (default for hand runs; the conductor sets "none" and decides the fallback itself, per ID).
GATE_MODE = os.environ.get("AGMM_GATE", "actions").strip().lower()
GATE_FALLBACK = os.environ.get("AGMM_GATE_FALLBACK", "local").strip().lower()


def stage_gate(ID, out, st, a):
    spec = json.load(open(spec_of(ID)))
    gdir = os.path.join(out, "gate", "r%d" % st.d["round"])
    os.makedirs(gdir, exist_ok=True)
    if "web" in PLAN and "web" not in _BG and GATE_MODE != "actions":
        _start_web(ID, out)          # (in actions mode the runner encodes the web copy too; see below)
    if "better" in PLAN and "judge" not in _BG:
        _start_judge(ID, out, st)
    g = rc = None
    st.d.pop("web_via", None)
    if GATE_MODE == "actions":
        sys.path.insert(0, os.path.join(KIT, "tools"))
        import gate_actions
        try:
            g, rc = gate_actions.run(ID, out, st.d, spec, gdir)
            st.d["gate_via"] = "actions"
            wsrc = os.path.join(gdir, "_web.mp4")
            if "web" in PLAN:
                try:
                    wmeta = json.load(open(os.path.join(gdir, "_meta.json")))
                except (OSError, ValueError):
                    wmeta = {}
                if os.path.exists(wsrc) and gate_actions.web_copy_ok(wsrc, os.path.join(out, "FINAL.mp4"), wmeta or {"web_sha256": None}):
                    os.replace(wsrc, os.path.join(out, ID + "-web.mp4.part"))
                    st.d["web_via"] = "actions"
                else:
                    print("the runner's web copy is missing or does not match FINAL.mp4; encoding it here")
                    _start_web(ID, out)
        except Exception as e:
            print("actions gate FAILED: %s" % str(e)[-900:])
            if GATE_FALLBACK != "local":
                sys.exit("FAILED: the Actions gate failed and AGMM_GATE_FALLBACK=%s (the conductor retries or falls back per ID)" % GATE_FALLBACK)
            print("falling back to the local gate")
    if g is None:
        if "web" in PLAN and "web" not in _BG:
            _start_web(ID, out)
        g, rc = _run_gate_checks(ID, out, st, spec, gdir)
        st.d["gate_via"] = "local"
    rows = [(c.get("id"), c.get("name"), c.get("status")) for c in g.get("checks", [])]
    for r in rows:
        print("  check %s %-28s %s" % r)
    for f in ("GATE.md", "GATE.json"):
        shutil.copy(os.path.join(gdir, f), os.path.join(out, f))
    st.mark("gate", exit=rc, overall=g.get("overall"), checks=rows, dir=gdir, via=st.d["gate_via"])
    print("gate overall %s (via %s)" % (g.get("overall"), st.d["gate_via"]))




def stage_web(ID, out, st, a):
    final, web, poster = os.path.join(out, "FINAL.mp4"), os.path.join(out, ID + "-web.mp4"), os.path.join(out, "poster.jpg")
    b = _BG.pop("web", None)
    part = web + ".part"
    if b is None and st.d.get("web_via") == "actions" and os.path.exists(part) and os.path.getmtime(part) >= os.path.getmtime(final):
        pass                       # the Actions gate's runner already encoded it from this FINAL.mp4 (gate_core.web_cmd) and the fetcher placed it
    elif b is None:                # not started early (e.g. --only web / --from web): encode now, same command
        sh(_web_cmd(ID, out))
    else:
        rc = b["proc"].wait()
        if rc:
            sys.exit("FAILED: web encode (started with the gate) exit %d\n%s" % (rc, open(b["log"]).read()[-2000:]))
        if os.path.getmtime(final) > b["t0"]:
            sys.exit("web: FINAL.mp4 changed while its web copy was encoding; re-run --from web")
    os.replace(web + ".part", web)
    gposter = os.path.join(st.d.get("stages", {}).get("gate", {}).get("dir", ""), "_poster.jpg")
    if st.d.get("web_via") == "actions" and os.path.exists(gposter) and os.path.getmtime(gposter) >= os.path.getmtime(final):
        shutil.copy(gposter, poster)
    else:
        sh(["ffmpeg", "-v", "error", "-y", "-threads", "2", "-ss", "0.4", "-i", final, "-frames:v", "1", "-q:v", "2", "-vf", "scale=1080:-2", poster], nice=True)
    st.mark("web", web=web, web_bytes=os.path.getsize(web), poster=poster)


def stage_better(ID, out, st, a):
    """Sam: 'Never a beta version of the original. It must always be better.' ours >= reference on every dimension,
    > on at least three; else a fix round with the critic's reasons (FIX-ROUND.md)."""
    spec, url, ref, jdir = _judge_args(ID, out, st)
    # root 29 Sep: judge.py hung 36-60 min on S05, S39 and S03 waiting on free critics, blocking the run behind an
    # advisory stage. It gets 20 min; a timeout is recorded as UNJUDGED and the reviewer's look decides.
    # speed build 29 Sep: judge.py normally started with the gate (same command); its 20 min count from ITS start.
    tmo = int(os.environ.get("AGMM_JUDGE_TIMEOUT", "1200"))
    tries = int(os.environ.get("AGMM_JUDGE_TRIES", "3"))
    for attempt in range(1, tries + 1):
        if "judge" not in _BG:
            _start_judge(ID, out, st)
        b = _BG.pop("judge")
        res = _collect_judge(ID, out, st, b, jdir, tmo)
        if res is not None:
            break
        # FINISHER 13 Oct: S66's judge wrote nothing (two passes raced on one temp file) and this stage returned silently, so the card
        # carried better_than_reference None and publish held it with no reason anyone acted on. A None is now retried, then recorded.
        print("better: judge attempt %d of %d wrote no better-than-ref.json%s" % (attempt, tries, "; retrying" if attempt < tries else ""), flush=True)
        if attempt < tries:
            time.sleep(min(60, 15 * attempt))
    if res is None:
        st.mark("better", verdict="UNJUDGED", attempts=tries, dir=jdir,
                why="judge.py wrote no better-than-ref.json in %d attempts (see %s.log)" % (tries, jdir))
        print("better: UNJUDGED after %d attempts (judge wrote nothing; %s.log). Publish needs a PASS: re-run --from better." % (tries, jdir))
        return
    _better_verdict(ID, out, st, spec, url, jdir, res)


def _collect_judge(ID, out, st, b, jdir, tmo):
    """wait for one judge.py run; returns its better-than-ref.json dict, or None when it wrote nothing (exits on a timeout or a moved master)"""
    try:
        b["proc"].wait(timeout=max(1, tmo - (time.time() - b["t0"])))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(b["proc"].pid, signal.SIGKILL)
        except OSError:
            pass
        b["proc"].wait()
        os.makedirs(jdir, exist_ok=True)
        open(jdir + ".log", "w").write("judge.py timed out (AGMM_JUDGE_TIMEOUT); better-than-ref UNJUDGED\n" + open(b["log"]).read()[-3000:])
        sys.exit("better: judge.py timed out after %ss; UNJUDGED (advisory). The reviewer's look decides; card left alone." % os.environ.get("AGMM_JUDGE_TIMEOUT", "1200"))
    with open(jdir + ".log", "a") as fh:
        fh.write(open(b["log"]).read())
    if os.path.getmtime(os.path.join(out, "FINAL.mp4")) > b["t0"]:
        sys.exit("better: FINAL.mp4 changed while the judge was watching it; re-run --from better")
    try:
        res = json.load(open(os.path.join(jdir, "better-than-ref.json")))
    except (OSError, ValueError):   # root 30 Sep: judge wrote nothing (timeout/crash); never crash produce (the caller retries)
        return None
    if os.path.getmtime(os.path.join(jdir, "better-than-ref.json")) < b["t0"]:
        return None                 # a result left by an earlier run is not this run's verdict
    return res


def _better_verdict(ID, out, st, spec, url, jdir, res):
    # NOT-A-COPY (frames pHash + VO 5-grams against the reference): a clone can never pass as "better"
    sys.path.insert(0, os.path.join(KIT, "tools")); import notcopy
    wp = spec["voice"]["words"]; wp = wp if os.path.isabs(wp) else os.path.join(V2, wp)
    nc = notcopy.check(os.path.join(out, "FINAL.mp4"), url, wp)
    json.dump(nc, open(os.path.join(jdir, "notcopy.json"), "w"), indent=1)
    res["not_a_copy"] = {"status": nc["status"], "summary": nc["summary"]}
    if nc["status"] != "PASS" and not spec.get("reproduction_of"):
        res["verdict"] = "FAIL"
        res["fix_round_brief"].insert(0, {"dimension": "not_a_copy", "ours": 0, "ref": 0, "critic_says": [nc["summary"]]})
    if res["verdict"] != "PASS":
        with open(os.path.join(out, "FIX-ROUND.md"), "w") as fh:
            fh.write("# %s fix round r%d: not better than the reference yet\n\nours %s\nreference %s\nbehind on %s; ahead on %s (need all >= and 3 ahead)\n\n" % (
                ID, st.d["round"], res["ours"], res["reference"], res["behind_on"], res["ahead_on"]))
            for f in res["fix_round_brief"]:
                fh.write("- **%s** ours %.1f vs ref %.1f: %s\n" % (f["dimension"], f["ours"], f["ref"], " / ".join(f["critic_says"])))
            fh.write("\nOur weaknesses (critic, with timestamps):\n" + "".join("- %s %s\n" % (w.get("t"), w.get("issue")) for w in res["our_weaknesses"]))
    json.dump(res, open(os.path.join(jdir, "better-than-ref.json"), "w"), indent=1)
    st.mark("better", verdict=res["verdict"], ours=res["ours"], reference=res["reference"], ahead_on=res["ahead_on"], behind_on=res["behind_on"],
            not_a_copy=res["not_a_copy"], dir=jdir)
    print("better-than-reference %s: ours %s vs ref %s" % (res["verdict"], res["ours"], res["reference"]))


def _script(spec):
    s = spec.get("script", {}).get("file")
    return s if not s or os.path.isabs(s) else os.path.join(V2, s)


def reference_from_script(path):
    """(url, the title the script claims) from the script's 'Reference remade' section"""
    if not path or not os.path.exists(path):
        return None, None
    s = open(path).read()
    m = re.search(r"## Reference remade\s+(\S+)\s*(\(([^\n]*)\))?", s)
    if not m:
        return None, None
    q = re.search(r"'([^']+)'", m.group(3) or "")
    return m.group(1), (q.group(1) if q else None)


def platform_why(path):
    if not path or not os.path.exists(path):
        return None
    m = re.search(r"\|\s*Platform suggestion\s*\|\s*([^|\n]+)\|", open(path).read())
    return m.group(1).strip() if m else None


def reference_metadata(url):
    """The reference label comes from the PLATFORM's own metadata, never a summary or a script header (Sam, 24 Sep:
    two Fern titles on the review page were invented). YouTube via yt-dlp; 0x100x reels via reel-index.csv."""
    if "youtube.com" in url or "youtu.be" in url:
        # FINISHER 13 Oct: S68's card died on one failed read ("could not read the reference's own metadata") that worked when re-run
        # by hand minutes later. A failed read is retried (3 tries, backoff) before the card refuses.
        for _try in range(3):
            p = subprocess.run(["yt-dlp", "--no-update", "--skip-download", "--print", "%(title)s\t%(channel)s\t%(view_count)s", url], capture_output=True, text=True)
            if not p.returncode and "\t" in p.stdout:
                break
            print("card: yt-dlp metadata read %d of 3 failed for %s: %s" % (_try + 1, url, (p.stderr or p.stdout).strip()[-160:]), flush=True)
            time.sleep(10 * (_try + 1))
        else:
            return None
        title, channel, views = p.stdout.strip().splitlines()[-1].split("\t")
        return {"title": title, "channel": channel, "views": int(views), "source": "yt-dlp"}
    m = re.search(r"instagram\.com/0x100x/reel/([A-Za-z0-9_-]+)", url)
    if m:
        import csv
        for r in csv.DictReader(open(os.path.join(os.path.dirname(V2), "research/0x100x-reels-2026-09-23/reel-index.csv"))):
            if r["id"] == m.group(1):
                return {"title": None, "caption_first_line": r["caption_first_line_unverified_claim"], "channel": "0x100x",
                        "views": r["public_grid_views_2026_09_23"], "source": "reel-index.csv"}
    return None


def _views(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return str(v)
    return "%.1fM" % (v / 1e6) if v >= 1e6 else "%dk" % round(v / 1e3)


def _references(spec, url, meta):
    """card `references`: every original this short remakes, each labelled from the platform's own metadata"""
    out = []
    for u in [url] + [x for x in spec.get("also_remakes", []) if x != url]:
        m = meta if u == url else reference_metadata(u)
        if not m:
            sys.exit("card: no platform metadata for %s" % u)
        out.append({"label": "%s: %s" % (m["channel"], m["title"] or "reel " + u.rstrip("/").split("/")[-1]), "url": u, "views": _views(m["views"])})
    return out


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def stage_card(ID, out, st, a):
    # 25 Sep 02:25: writers cannot certify their own work. "Ready to post" is set only by a reviewer (AGMM_REVIEWER=1),
    # after a frame-by-frame comparison against the approved pilot P1; everything else lands as "In review".
    if a.status == "Ready to post" and os.environ.get("AGMM_REVIEWER") != "1":
        a.status = "In review"
    spec = json.load(open(spec_of(ID)))
    url, claimed = reference_from_script(_script(spec))
    url = spec.get("reference_url", url)
    meta = reference_metadata(url)
    if not meta:
        sys.exit("card: could not read the reference's own metadata for %s; no card without a verified title" % url)
    if meta["title"]:
        claimed = spec.get("reference_title_claimed", claimed)
        import difflib
        if claimed and difflib.SequenceMatcher(None, _norm(claimed), _norm(meta["title"])).ratio() < 0.85:
            sys.exit("card: the script calls the reference %r but the platform says %r: fix the script before publishing" % (claimed, meta["title"]))
        label = "%s, '%s' (%s views, %s)" % (meta["channel"], meta["title"], format(meta["views"], ","), meta["source"])
    else:
        label = "%s reel %s (%s views on the 23 Sep grid; no platform title, first caption line: %s)" % (
            meta["channel"], url.rstrip("/").split("/")[-1], meta["views"], meta["caption_first_line"][:80])
    A = dict(st.d["stages"]["assemble"])
    if not A.get("final"):       # rehydrated shorts (e.g. S92): the assemble stage carries no final/probe; the master is out/<ID>/FINAL.mp4
        A["final"] = os.path.join(out, "FINAL.mp4")
        if not os.path.exists(A["final"]):
            sys.exit("card: assemble stage has no 'final' and %s does not exist" % A["final"])
    # rehydrated shorts (e.g. S92) have an assemble stage without a "probe" block: read the master itself
    if (A.get("probe") or {}).get("format", {}).get("duration") is not None:
        dur = float(A["probe"]["format"]["duration"])
    else:
        dur = float(json.loads(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", A["final"]]).stdout)["format"]["duration"])
    gate, better = st.d["stages"].get("gate", {}), st.d["stages"].get("better", {})
    rel = lambda p: os.path.relpath(p, ROOT)
    status = a.status if better.get("verdict", "PASS") in ("PASS", "UNJUDGED") and gate.get("overall") == "PASS" else "Fix round needed"
    # root 29 Sep: never downgrade a card a reviewer already passed ON THESE BYTES (a slow judge finishing after root_pass
    # would reset S21's "Ready to post" to "In review" and withdraw its armed slot).
    try:
        _prev = next((c for c in json.load(open(os.path.join(V2, "qa", "cards.json"))) if c.get("id") == ID), None)
        if _prev and _prev.get("status") == "Ready to post" and os.path.realpath(os.path.join(os.path.dirname(V2), _prev.get("master", ""))) == os.path.realpath(A["final"]) \
                and os.path.getmtime(os.path.join(V2, "qa", "cards.json")) >= os.path.getmtime(A["final"]):
            # FINISHER 13 Oct: the path matched but S40's card was Ready from an EARLIER master (its newest review is root's 6 Oct
            # RETURN); keep the card only when the newest review is a PASS made after this master was written.
            _rv = [r for r in json.load(open(os.path.join(V2, "qa", "review-log.json"))) if isinstance(r, dict) and r.get("id") == ID]
            _ok = bool(_rv) and str(_rv[-1].get("verdict", "")).startswith("PASS") and \
                time.mktime(time.strptime(str(_rv[-1].get("at", ""))[:16], "%Y-%m-%dT%H:%M")) >= os.path.getmtime(A["final"]) - 60
            if _ok:
                print("card: %s already Ready to post on this master (reviewer PASS %s); left as is" % (ID, _rv[-1].get("at")), flush=True)
                st.mark("card", card=_prev, kept=True)
                return
            print("card: %s says Ready to post but its newest review (%s %s) is not a PASS on this master; writing a fresh card" % (
                ID, (_rv[-1].get("verdict", "")[:40] if _rv else "none"), (_rv[-1].get("at") if _rv else "")), flush=True)
    except Exception:
        pass
    card = {"id": ID, "section": "shortform", "title": spec.get("title", ID), "platform": spec.get("platform_label", spec.get("platform", "")),
            "duration": "%.1fs" % dur, "look": spec["look"], "reference": label, "reference_url": url, "reference_meta": meta, "status": status,
            "references": _references(spec, url, meta), "reference_note": spec.get("reference_note"),
            "platform_why": spec.get("platform_why") or platform_why(_script(spec)),
            "src": rel(os.path.join(out, ID + "-web.mp4")), "type": "video/mp4", "poster": rel(os.path.join(out, "poster.jpg")),
            # the autoposter uploads the MASTER (never the web copy); gate_json is bound to the 1080 master it gated
            "master": rel(A["final"]), "master_4k": rel(A["final_4k"]) if A.get("final_4k") else None,
            "gate": rel(os.path.join(out, "GATE.md")), "gate_json": rel(os.path.join(gate.get("dir", out), "GATE.json")),
            "gate_json_video": rel(A["final"]),
            "better_than_reference": {k: better.get(k) for k in ("verdict", "ours", "reference", "ahead_on", "behind_on")} if better else None,
            "notes": "Kit %s. Gate %s (%s). Better-than-reference %s: ours %s vs reference %s. Bed %s." % (
                json.load(open(os.path.join(out, "BUILD.json")))["kit"], gate.get("overall"), ", ".join("%s %s" % (r[0], r[2]) for r in gate.get("checks", [])),
                better.get("verdict"), better.get("ours"), better.get("reference"), spec["music"]["bed"])}
    missing = [k for k in ("id", "section", "title", "platform", "platform_why", "duration", "reference", "reference_url", "status", "src", "type", "poster", "master", "gate_json") if not card.get(k)]
    if missing:
        sys.exit("card is missing %s" % missing)
    json.dump(card, open(os.path.join(out, "card.json"), "w"), indent=1)
    st.mark("card", card=card)
    print(json.dumps(card, indent=1))


def stage_publish(ID, out, st, a):
    """cards.json is changed ONLY through qa/card.py upsert (validates, atomic write). A short is published only when
    the gate and the better-than-reference judge both PASS, unless --publish-anyway (e.g. a kit test for root)."""
    cst = st.d["stages"].get("card") or {}
    if cst.get("kept"):
        print("publish: %s card kept at Ready to post (reviewer PASS on this master); nothing to upsert" % ID)
        st.mark("publish", via="kept")
        return
    if "card" not in cst:
        sys.exit("publish: the card stage recorded no card for %s (S40's KeyError, 13 Oct); re-run --from card" % ID)
    ok = st.d["stages"].get("gate", {}).get("overall") == "PASS" and st.d["stages"].get("better", {}).get("verdict") == "PASS"
    if not ok:   # the gate's own failures join the fix brief
        g = json.load(open(os.path.join(st.d["stages"]["gate"]["dir"], "GATE.json")))
        with open(os.path.join(out, "FIX-ROUND.md"), "a") as fh:
            fh.write("\n## Gate r%d failures\n" % st.d["round"] + "".join("- check %s %s: %s\n" % (c["id"], c["name"], c["summary"]) for c in g["checks"] if c["status"] == "FAIL")
                     + "".join("  - %s\n" % d for c in g["checks"] if c["status"] == "FAIL" for d in (c.get("details") or [])[:12] if isinstance(d, str)))
    if not ok and not a.publish_anyway:
        print("not published: gate %s, better-than-reference %s (FIX-ROUND.md)" % (st.d["stages"].get("gate", {}).get("overall"), st.d["stages"].get("better", {}).get("verdict")))
        return
    p = subprocess.run(["python3", os.path.join(V2, "qa/card.py"), "upsert", os.path.join(out, "card.json")], capture_output=True, text=True)
    print(p.stdout + p.stderr)
    if p.returncode:
        sys.exit("card.py refused the card")
    st.mark("publish", via="qa/card.py upsert")


def cost(ID, out, st, a, T0):
    c = st.d.get("cost", {})
    c.setdefault("wall_seconds_by_stage", {})
    c["kit"] = json.load(open(os.path.join(out, "BUILD.json")))["kit"] if os.path.exists(os.path.join(out, "BUILD.json")) else None
    w = st.d["stages"].get("wait", {})
    c["render_runner_minutes"] = w.get("render_runner_minutes"); c["render_wall_minutes"] = w.get("render_wall_minutes")
    r = st.d["stages"].get("dispatch", {}).get("run"); c["render_mode"] = r if r in OFF_ACTIONS else "actions"
    if a.spec_tokens:
        c["spec_writing_tokens_est"] = a.spec_tokens
    st.d["cost"] = c
    json.dump(st.d, open(st.path, "w"), indent=1)
    json.dump(c, open(os.path.join(out, "COST.json"), "w"), indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--from", dest="frm", choices=STAGES)
    ap.add_argument("--only", choices=STAGES)
    ap.add_argument("--spec-tokens", type=int)
    ap.add_argument("--status", default="In review")
    ap.add_argument("--publish-anyway", action="store_true")
    a = ap.parse_args()
    ID = a.id
    out = os.path.join(KIT, "out", ID)
    print(f'DEBUG: out={out}, exists={os.path.exists(out)}, isdir={os.path.isdir(out)}', flush=True)
    if not os.path.exists(out):
        os.makedirs(out)
    gate_lock = None
    if not a.only or a.only == "gate":
        gate_lock = open(os.path.join(out, "gate-process.lock"), "a+")
        try:
            fcntl.flock(gate_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            gate_lock.close()
            print("gate already running for %s; state left untouched" % ID, flush=True)
            return
    try:
        st = State(out)
        if a.frm:
            st.reset_from(a.frm)
        fns = {"build": stage_build, "dispatch": stage_dispatch, "wait": stage_wait, "pull": stage_pull, "assemble": stage_assemble,
               "gate": stage_gate, "web": stage_web, "better": stage_better, "card": stage_card, "publish": stage_publish}
        T0 = time.time()
        PLAN[:] = [a.only] if a.only else [s for s in STAGES if not st.done(s)]
        for s in STAGES:
            if a.only and s != a.only:
                continue
            if st.done(s) and not a.only:
                continue
            t = time.time()
            print("== %s %s" % (ID, s), flush=True)
            fns[s](ID, out, st, a)
            st.d.setdefault("cost", {}).setdefault("wall_seconds_by_stage", {})[s] = round(time.time() - t, 1)
            json.dump(st.d, open(st.path, "w"), indent=1)
        cost(ID, out, st, a, T0)
    finally:
        if gate_lock is not None:
            gate_lock.close()


if __name__ == "__main__":
    main()
