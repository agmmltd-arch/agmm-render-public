#!/usr/bin/env python3
"""Headless preview for writers: PNG frames of a built short at every beat, with nothing opened in the Claude app.

Root, 24 Sep 23:45: ten writers driving the Claude app's built-in browser pane froze the desktop app (Sam had to
message from his phone) and gave writers each other's pages. Never preview in the app pane. This wraps
`hyperframes snapshot` (headless Chrome, low priority) over out/<ID>/build/pkg/<part>/.

Usage: snap.py <ID> [--every SECONDS] [--at 3.2,10.5] [--against <reference.mp4>]
  default: one frame 0.35 s into every beat, plus the first and last frame of the short
Writes out/<ID>/snap/<part>/*.jpg and prints the list (look at them with the Read tool).

WHERE IT RUNS (6 Oct, root: the free Codespaces allowance is 120 core-hours a month per account and snaps burned ~80 each
in two days). Backends, in this order on the Mac:
  1. actions   -> GitHub Actions in the PUBLIC repo agmmltd-arch/agmm-render-public (workflow agmm-short-snap.yml): free and
                  unlimited. The short's own package (build/pkg/<look> for every part in parts.json, nothing else) is
                  secret-scanned (the same scan as the render dispatcher / films), uploaded to a content-hashed release
                  snap-<id>-<sha16> (reused on repeat calls), the workflow renders exactly the requested frames with
                  hyperframes@0.8.71 and uploads JPGs q92, which come back to the same out/<ID>/snap/<part>/ paths.
  2. codespace -> a render-pool codespace, only if actions failed, and only for accounts under the hours guard: an account
                  whose core_min this month (registry/codespace-usage-<user>.jsonl) exceeds AGMM_CS_MAX_HOURS (default 110)
                  or has a registry/codespace-402-<user>-<YYYY-MM>.flag is skipped; if none is left the path is refused.
AGMM_SNAP selects:  unset / auto / codespace / remote -> actions, then guarded codespace (codespace and remote are the old
                    spellings and keep working: makers' commands do not change)   | actions -> actions only, no fallback
                    | codespace-only -> the codespace pool only (guarded)           | local -> refused on the Mac (exit 86).
--against <reference.mp4> cannot go to the public repo (it is not the short's own package), so it skips actions.
Output lines and paths are identical on every backend.
AGMM_SNAP_ACTIONS_WAIT (default 1500 s) bounds the wait for the workflow run. The free plan runs only 20 hosted jobs at once
across the account, so a 4K film wave can leave a snap QUEUED for minutes: after AGMM_SNAP_QUEUE_WAIT (default 600 s) in the
queue the run is cancelled and, when the hours guard still allows a codespace, the call falls back to it.
(Earlier history, 28 Sep: local headless Chrome was the Mac's biggest load on a 60 W charger at 6-8% battery, and
battery_guard.sh SIGSTOPs heavy.py jobs, so every writer's snap queued and timed out; the codespace path was added then.)
AGMM_SNAP_POOL_WAIT (default 300 s) bounds the wait for a free codespace pool member before falling back.
CODESPACES 402 / OVER HOURS (opsA 19 Oct): when cs_guard_users() finds no usable account (402 flag or hours), the codespace is not even
listed: Actions is the only route, it gets the whole AGMM_SNAP_ACTIONS_WAIT (no 600 s queue cancel that falls into a dead codespace), and a
transient Actions failure is retried AGMM_SNAP_ACTIONS_RETRIES (default 2) times. The 402 flag is now written on any "HTTP 402"
(render_codespace.run), not only when the text said "billing". Delete registry/codespace-402-<user>-<month>.flag once the budget is raised."""
import argparse
import random, glob, hashlib, json, os, re, shlex, shutil, subprocess, sys, tarfile, tempfile, time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.dirname(os.path.abspath(__file__))
HF = "hyperframes@0.8.71"
# node is on the render image already (renders use npx); this only runs on a fresh image that lacks it
NODE_SETUP = ("command -v npx >/dev/null || [ -x ~/.local/node/bin/npx ] || (mkdir -p ~/.local && "
              "curl -fsSL https://nodejs.org/dist/v22.11.0/node-v22.11.0-linux-x64.tar.xz | tar -xJ -C ~/.local && "
              "ln -sfn ~/.local/node-v22.11.0-linux-x64 ~/.local/node)")


def log(msg):
    print("snap: " + msg, file=sys.stderr, flush=True)


def battery_low():
    """True when the Mac is below 25% and not charging (pmset's status token, same test as battery_guard.sh)."""
    try:
        line = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[-1]
    except Exception:
        return False
    m = re.search(r"(\d+)%", line)
    return bool(m) and int(m.group(1)) < 25 and "; charging" not in line and "; charged" not in line and "finishing charge" not in line


def codespace_blocked():
    """True when no codespace account may host a snap (402 flag or hours guard): Actions is then the only hosted route."""
    try:
        cs_guard_users()
        return False
    except RuntimeError:
        return True


def hosted_order():
    if codespace_blocked():
        log("codespaces unusable (402 flag / hours guard): GitHub Actions only, full wait, retried on failure")
        return ["actions"]
    return ["actions", "codespace"]


def backends():
    """Ordered backends for this call (see the module docstring). Raises SystemExit(86) for a refused local request."""
    m = os.environ.get("AGMM_SNAP", "").strip().lower()
    if m == "actions":
        return ["actions"]
    if m == "codespace-only":
        return ["codespace"]
    if m == "local":
        if sys.platform == "darwin":
            # root 6 Oct: crew tools (self_review.py, forge_free/checks.py) still ask for local; on the Mac that exited 86.
            # Serve them from the hosted path instead of failing (no media work on the Mac either way).
            log("local snapshots are disabled on this Mac; using the hosted Actions path instead")
            return hosted_order()
        return ["local"]
    # unset, auto, and the legacy "codespace"/"remote": hosted, free Actions first, the allowance-limited codespace pool
    # only as a fallback. root 29 Sep: the battery is NEVER consulted. Off the Mac an unset AGMM_SNAP still means local.
    if m in ("", "auto", "codespace", "remote"):
        if m == "" and sys.platform != "darwin":
            return ["local"]
        return hosted_order()
    log("unknown AGMM_SNAP=%r; using auto (actions, then guarded codespace)" % m)
    return hosted_order()


def local_snap(pdir, dest, local, against):
    # machine-wide 2-slot limit (tools/heavy.py): at most two heavy local jobs at once (root, 25 Sep 01:45)
    cmd = ["python3", os.path.join(TOOLS, "heavy.py"), "--", os.path.expanduser("~/.local/node/bin/npx"), "--yes", HF, "snapshot", pdir,
           "-o", dest, "--at", ",".join("%.2f" % t for t in local), "--no-end", "--describe", "false"]
    if against:
        cmd += ["--against", against]
    env = dict(os.environ, HYPERFRAMES_NO_TELEMETRY="1", PATH=os.path.expanduser("~/.local/node/bin") + ":" + os.environ["PATH"])
    env.pop("GEMINI_API_KEY", None)
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=900)
    if r.returncode:
        sys.exit("snapshot failed for %s: %s" % (os.path.basename(dest), (r.stdout + r.stderr)[-800:]))


def cs_core_hours(user, month=None):
    """This month's codespace core-hours for one account: the sum of core_min in registry/codespace-usage-<user>.jsonl
    (renders, films and snaps all append there)."""
    month = month or time.strftime("%Y-%m")
    total = 0.0
    try:
        with open(os.path.join(KIT, "registry", "codespace-usage-%s.jsonl" % user)) as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if str(row.get("at", "")).startswith(month):
                    total += float(row.get("core_min") or 0)
    except OSError:
        pass
    return total / 60.0


def cs_guard_users():
    """The codespace hours guard (root, 6 Oct): accounts allowed to host a snap. An account is skipped when its core-hours
    this month exceed AGMM_CS_MAX_HOURS (default 110 of the free 120) or when registry/codespace-402-<user>-<YYYY-MM>.flag
    says GitHub already refused it for billing. Raises when none is left: the codespace path is then refused."""
    limit = float(os.environ.get("AGMM_CS_MAX_HOURS", "110"))
    month = time.strftime("%Y-%m")
    users = [os.environ["AGMM_GH_USER"]] if os.environ.get("AGMM_GH_USER") else ["agmmltd-arch", "SamAGMM"]
    ok, why = [], []
    for u in users:
        hours = cs_core_hours(u, month)
        if hours > limit:
            why.append("%s used %.1f core-hours in %s (limit %g)" % (u, hours, month, limit))
        elif os.path.exists(os.path.join(KIT, "registry", "codespace-402-%s-%s.flag" % (u, month))):
            why.append("%s has a 402 billing flag for %s" % (u, month))
        else:
            ok.append(u)
    if not ok:
        raise RuntimeError("codespace path REFUSED by the hours guard: " + "; ".join(why))
    return ok


def _acquire(rc, wait, users):
    """render_codespace.acquire_pool(), but bounded: the same lock files in the same order, so a snap and a render never
    hold the same pool member; gives up after `wait` seconds instead of queueing forever. `users` comes from cs_guard_users()."""
    import fcntl
    os.makedirs(rc.POOL_LOCKS, exist_ok=True)
    t_end = time.time() + wait
    while True:
        for user in users:
            for name in rc.POOL[user]:
                f = open(os.path.join(rc.POOL_LOCKS, "%s-%s.lock" % (user, name)), "w")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    f.close(); continue
                if user != rc.GH_USER:
                    rc.GH_USER, rc._TOKEN = user, None
                    rc.REPO = {"agmmltd-arch": "agmmltd-arch/agmm-video-render", "SamAGMM": "SamAGMM/agmm-render-box"}[user]
                    rc.LEDGER = os.path.join(KIT, "registry", "codespace-usage-%s.jsonl" % user)
                return name, f
        if time.time() >= t_end:
            raise RuntimeError("no free codespace pool member after %.0f s (renders hold all of them)" % wait)
        time.sleep(10)


def remote_snap(ID, jobs, against):
    """jobs = [(look, part_out, pkg_dir, local_dest, times)]. Runs every part's snapshot on one pool codespace and copies
    the frames into each local_dest (fresh mtimes, so the caller's conversion loop treats them as this run's)."""
    sys.path.insert(0, TOOLS)
    import render_codespace as rc
    wait = float(os.environ.get("AGMM_SNAP_POOL_WAIT", "300"))
    t0 = time.time()
    name, lock = _acquire(rc, wait, cs_guard_users())
    t_cs = time.time()   # billing starts here, not while queueing for the lock
    # root 6 Oct: runs killed mid-way (usage limits, a stopped agent) left their scratch behind (1.3 GB gate-ocr, 0.9 GB snap
    # in /var/folders at 06:50). Clear this tool's OWN orphaned scratch, older than 3 h, before making a new one.
    import glob as _g, time as _t
    for _old in _g.glob(os.path.join(tempfile.gettempdir(), "agmm-snap-*")):
        if os.path.isdir(_old) and _t.time() - os.path.getmtime(_old) > 3 * 3600:
            shutil.rmtree(_old, ignore_errors=True)
    cs, started, tmp = None, False, tempfile.mkdtemp(prefix="agmm-snap-")
    try:
        rows = json.loads(rc.run(["gh", "codespace", "list", "--json", "name,displayName,state,repository"]).stdout)
        rows = [r for r in rows if r["repository"] == rc.REPO and (r["name"] == name or r["displayName"] == name)]
        if rows:
            cs, started = rows[0]["name"], rows[0]["state"] != "Available"
        else:
            cs, started = rc.pick_codespace(name), True
        log("remote on %s (%s, %s) after %.0f s pool wait" % (name, rc.GH_USER, "starting it" if started else "already running", time.time() - t0))
        rdir = "snap/%s-%d-%d" % (ID, os.getpid(), int(time.time()))
        bundle = os.path.join(tmp, "in.tar.gz")
        with tarfile.open(bundle, "w:gz") as tf:
            for look in sorted({j[0] for j in jobs}):
                tf.add(os.path.join(KIT, "out", ID, "build", "pkg", look), arcname="pkg/" + look)
        rc.ssh(cs, rc.SETUP + " && " + NODE_SETUP + " && rm -rf ~/%s && mkdir -p ~/%s" % (rdir, rdir), timeout=900)
        srcs = [bundle] + ([against] if against else [])
        rc.run(["gh", "codespace", "cp", "-c", cs, "-e"] + srcs + ["remote:~/%s/" % rdir], timeout=900)
        steps = ["cd ~/%s" % rdir, "export PATH=$HOME/.local/node/bin:$PATH HYPERFRAMES_NO_TELEMETRY=1", "tar -xzf in.tar.gz"]
        for look, part, _pdir, _dest, times in jobs:
            cmd = "mkdir -p out/%s && nice -n 10 npx --yes %s snapshot pkg/%s -o out/%s --at %s --no-end --describe false" % (
                shlex.quote(part), HF, shlex.quote(look), shlex.quote(part), ",".join("%.2f" % t for t in times))
            if against:
                cmd += " --against ~/%s/%s" % (rdir, shlex.quote(os.path.basename(against)))
            steps.append(cmd + " > out/%s.log 2>&1" % shlex.quote(part))
        steps.append("tar -czf result.tar.gz out")
        done = "~/%s/done" % rdir
        # detached + done-file (render_codespace, 25 Sep): a dropped ssh session must not kill the job
        rc.ssh(cs, "nohup bash -c %s > ~/%s/job.log 2>&1 &" % (
            shlex.quote("(%s) && echo OK > %s || echo FAIL > %s" % (" && ".join(steps), done, done)), rdir), check=False, timeout=300)
        t_end, status = time.time() + 1800, ""
        while time.time() < t_end:
            time.sleep(4)
            status = (rc.ssh(cs, "cat %s 2>/dev/null || true" % done, check=False, timeout=120).stdout or "").strip()
            if status in ("OK", "FAIL"):
                break
        if status != "OK":
            tail = rc.ssh(cs, "tail -n 25 ~/%s/job.log ~/%s/out/*.log 2>/dev/null" % (rdir, rdir), check=False, timeout=120).stdout
            raise RuntimeError("remote snapshot %s: %s" % (status or "timed out", tail[-1200:]))
        rc.run(["gh", "codespace", "cp", "-c", cs, "-e", "remote:~/%s/result.tar.gz" % rdir, tmp + "/"], timeout=900)
        with tarfile.open(os.path.join(tmp, "result.tar.gz")) as tf:
            tf.extractall(tmp)
        for _look, part, _pdir, dest, _times in jobs:
            got = sorted(glob.glob(os.path.join(tmp, "out", part, "*")))
            if not any(g.endswith(".png") for g in got):
                raise RuntimeError("no frames came back for %s" % part)
            os.makedirs(dest, exist_ok=True)
            for g in got:
                shutil.copyfile(g, os.path.join(dest, os.path.basename(g)))   # copyfile: fresh local mtime
        rc.ssh(cs, "rm -rf ~/%s" % rdir, check=False, timeout=120)
        log("remote done in %.0f s on %s" % (time.time() - t0, name))
    finally:
        if cs and started:
            # never stop a machine something else is rendering on (the film tool does not take the pool lock)
            busy = (rc.ssh(cs, "pgrep -fa 'hyperframes.*render|ffmpeg' | grep -v pgrep || true", check=False, timeout=120).stdout or "").strip()
            if busy:
                log("left %s running: another job is using it" % name)
            else:
                rc.run(["gh", "codespace", "stop", "-c", cs], check=False, timeout=300)   # we started it, so we stop it
        wall = time.time() - t_cs
        try:
            with open(rc.LEDGER, "a") as fh:
                fh.write(json.dumps({"id": ID, "kind": "snap", "codespace": cs, "wall_s": round(wall), "core_min": round(wall / 60 * rc.CORES, 1),
                                     "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        except OSError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)   # this run's own transient copies
        lock.close()


ACTIONS_REPO = "agmmltd-arch/agmm-render-public"   # PUBLIC: Actions minutes are free and unlimited there
ACTIONS_WF = "agmm-short-snap.yml"
ACTIONS_USER = "agmmltd-arch"                      # owner of that repo; the token is read per call, never printed
ACTIONS_LEDGER = os.path.join(KIT, "registry", "actions-snap-usage.jsonl")
class LocalSnapshotCapacityError(RuntimeError):
    """Hosted output remains available; local intake cannot consume the production reserve."""


def snapshot_capacity(directory, run_id, artifact_bytes=0):
    if sys.platform != "darwin":
        return
    floor = int(os.environ.get("AGMM_SNAP_MIN_FREE_BYTES", str(3 * 1024 ** 3)))
    required = floor + 2 * artifact_bytes  # archive plus extracted files at intake peak
    # 13 Oct 2026: the Mac sat at 1.9-4.5 GiB free all morning while ~10 makers wrote to it, and every finished hosted snapshot was refused
    # (4 chunk runs + 4 retries wasted for one static_precheck). The floor is NOT lowered: the call now waits up to AGMM_SNAP_DISK_WAIT
    # seconds (default 150) for the disk to recover before refusing, because the hosted run is already paid for and retained.
    t_wait = time.time()
    t_end = t_wait + float(os.environ.get("AGMM_SNAP_DISK_WAIT", "150"))
    while True:
        free = shutil.disk_usage(directory).free
        if free >= required or time.time() >= t_end:
            break
        time.sleep(10 + random.random() * 5)
    if time.time() - t_wait > 1:
        log("waited %.0f s for disk space (%.2f GiB free, %.2f GiB required)" % (time.time() - t_wait, free / 1024 ** 3, required / 1024 ** 3))
    if free < required:
        raise LocalSnapshotCapacityError(
            "Mac snapshot intake refused: %.2f GiB free, %.2f GiB required; "
            "hosted run %s retained. Free disk space before collecting; no quality PASS inferred."
            % (free / 1024 ** 3, required / 1024 ** 3, run_id))


def move_snapshot(source, target):
    # Both paths are on the same local source workspace volume. Avoid a second full snapshot copy.
    os.replace(source, target)
    os.utime(target, None)  # main() selects fresh frames by local mtime


SID_RE = re.compile(r"^[SCP][0-9]{2,3}$")
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SKIP_NAMES = (".DS_Store", "__MACOSX")
MAX_PACKAGE_BYTES = 1_000_000_000


def _gh(args, check=True, timeout=300):
    """gh against the public repo as the repo's owner account, whatever account is active; never echoes the token."""
    # OPS-B 19 Oct 2026 (Sam: the public render repo stays public, the leaks stop): refuse any write that would put media,
    # big images or out/ renders/ final*/ content into git history. Raises BEFORE the token is even read.
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    import public_repo_guard
    try:
        public_repo_guard.guard_gh(args)
    except public_repo_guard.GuardRefusal as e:
        raise RuntimeError(str(e))
    tok = subprocess.run(["gh", "auth", "token", "-u", ACTIONS_USER], capture_output=True, text=True, timeout=30).stdout.strip()
    env = dict(os.environ, GH_PROMPT_DISABLED="1")
    if tok:
        env["GH_TOKEN"] = tok
    r = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=timeout, env=env)
    if check and r.returncode:
        raise RuntimeError("gh %s failed: %s" % (" ".join(args[:3]), (r.stderr or r.stdout)[-500:].replace(tok, "***") if tok else (r.stderr or r.stdout)[-500:]))
    return r


def _package_tar(ID, looks, tmp):
    """Deterministic tar.gz of exactly this short's own look directories (build/pkg/<look>/..., same layout as
    build/source.tar.gz). Refuses anything that is not a short package: bad ID, no BUILD.json for this ID, unsafe look
    names, look dirs outside build/pkg, symlinks or special files."""
    import gzip
    if not SID_RE.fullmatch(ID):
        raise RuntimeError("not a short ID: %r (only S/C/P shorts go to the public repo)" % ID)
    out = os.path.join(KIT, "out", ID)
    try:
        build = json.load(open(os.path.join(out, "BUILD.json")))
    except (OSError, ValueError) as e:
        raise RuntimeError("no readable out/%s/BUILD.json: %s" % (ID, e))
    if build.get("id") != ID:
        raise RuntimeError("BUILD.json belongs to %r, not %s" % (build.get("id"), ID))
    pkg_root = os.path.realpath(os.path.join(out, "build", "pkg"))
    dest = os.path.join(tmp, "source.tar.gz")
    total = 0
    with open(dest, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as gz, \
            tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tf:
        for look in sorted(set(looks)):
            if not LABEL_RE.fullmatch(look):
                raise RuntimeError("unsafe look name %r" % look)
            base = os.path.join(pkg_root, look)
            if os.path.realpath(base) != base or not os.path.isdir(base):
                raise RuntimeError("look %s is not a real directory inside out/%s/build/pkg" % (look, ID))
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames if d not in SKIP_NAMES and not d.startswith("._"))
                entries = [(dirpath, True)] + [(os.path.join(dirpath, f), False) for f in sorted(filenames)
                                                if f not in SKIP_NAMES and not f.startswith("._")]
                for path, is_dir in entries:
                    st = os.lstat(path)
                    arc = os.path.relpath(path, pkg_root).replace(os.sep, "/")
                    if is_dir:
                        info = tarfile.TarInfo(arc); info.type = tarfile.DIRTYPE; info.mode = 0o755
                    else:
                        if not stat_isreg(st.st_mode):
                            raise RuntimeError("%s is a symlink or special file; packages hold regular files only" % arc)
                        info = tarfile.TarInfo(arc); info.size = st.st_size; info.mode = 0o644
                        total += st.st_size
                        if total > MAX_PACKAGE_BYTES * 4:
                            raise RuntimeError("package is larger than expected")
                    info.mtime = 0; info.uid = info.gid = 0; info.uname = info.gname = ""
                    if is_dir:
                        tf.addfile(info)
                    else:
                        with open(path, "rb") as fh:
                            tf.addfile(info, fh)
    size = os.path.getsize(dest)
    if size > MAX_PACKAGE_BYTES:
        raise RuntimeError("package tarball is %d bytes (> %d)" % (size, MAX_PACKAGE_BYTES))
    h = hashlib.sha256()
    with open(dest, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return dest, h.hexdigest(), size


def stat_isreg(mode):
    import stat
    return stat.S_ISREG(mode)


def _secret_scan(tarball):
    """The package becomes a PUBLIC release asset: the same scan as the short render dispatcher and the film tool
    (films/tools/render_actions_film.scan). Any hit, or a scan error, refuses the upload. Never weaken this."""
    sys.path.insert(0, os.path.join(os.path.dirname(KIT), "films", "tools"))
    import render_actions_film as raf
    try:
        bad = raf.scan(tarball)
    except ValueError as e:
        raise RuntimeError("REFUSED (public repo): cannot safely scan the package: %s" % e)
    if bad:
        raise RuntimeError("REFUSED (public repo): package contains secret-looking files/text: %s" % bad[:8])


def _snap_release(ID, tarball, sha, size):
    """Reuse the content-hashed release if it already holds exactly this asset, else create/repair it."""
    tag = "snap-%s-%s" % (ID.lower(), sha[:16])
    api = "repos/%s/releases/tags/%s" % (ACTIONS_REPO, tag)

    def lookup():
        r = _gh(["api", api], check=False)
        if r.returncode == 0:
            rel = json.loads(r.stdout)
            if rel.get("draft"):
                raise RuntimeError("release %s exists as a draft" % tag)
            assets = {a.get("name"): a for a in rel.get("assets", [])}
            exact = set(assets) == {"source.tar.gz"} and assets["source.tar.gz"].get("size") == size \
                and assets["source.tar.gz"].get("digest") == "sha256:" + sha
            return "exact" if exact else "wrong"
        if "HTTP 404" in (r.stderr or "") or "not found" in (r.stderr or "").lower():
            return "missing"
        raise RuntimeError("release lookup failed: %s" % (r.stderr or r.stdout)[-300:])

    state = lookup()
    if state == "exact":
        return tag, "reused"
    if state == "wrong":
        _gh(["release", "upload", tag, tarball, "-R", ACTIONS_REPO, "--clobber"], timeout=900)
        if lookup() != "exact":
            raise RuntimeError("release %s still does not hold the exact package after upload" % tag)
        return tag, "repaired"
    notes = "Exact AGMM short snapshot input (package only). Short %s. Editorial status NOT_REVIEWED; publication NOT_REQUESTED." % ID
    r = _gh(["release", "create", tag, tarball, "-R", ACTIONS_REPO, "--target", "main", "--title", tag, "--notes", notes,
             "--latest=false"], check=False, timeout=900)
    if r.returncode and lookup() != "exact":   # a concurrent call may have created it first
        raise RuntimeError("release creation failed: %s" % (r.stderr or r.stdout)[-300:])
    return tag, "created"


def actions_snap(ID, jobs, against, all_looks, queue_wait):
    """jobs = [(look, part_out, pkg_dir, local_dest, times)]. Packages, secret-scans and uploads the short's own package,
    dispatches agmm-short-snap.yml, waits (a run still QUEUED after queue_wait s is cancelled: the free plan runs 20 jobs at
    once across the whole account, so a 4K film wave can park snaps), downloads the JPG artifact and copies each frame into its local_dest (fresh
    mtimes, exactly like the codespace path). Raises on any failure so the caller can fall back or stop."""
    if against:
        raise RuntimeError("--against needs a reference video, which must not go to the public repo")
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix="agmm-snap-actions-")
    run_id = None
    try:
        # every look of the short, not just the requested ones: the tarball (and so the release) is the same for every call on this
        # build, so repeat snaps reuse it and upload nothing
        tarball, sha, size = _package_tar(ID, all_looks, tmp)
        _secret_scan(tarball)
        release, how = _snap_release(ID, tarball, sha, size)
        t_up = time.time()
        label = "%s-%s-%d-%d" % (ID, sha[:8], int(time.time()), os.getpid())
        plan = json.dumps([{"look": j[0], "part": j[1], "times": j[4]} for j in jobs], separators=(",", ":"))
        r = _gh(["workflow", "run", ACTIONS_WF, "-R", ACTIONS_REPO, "--ref", "main", "-f", "release=" + release,
                 "-f", "source_sha256=" + sha, "-f", "tag=" + label, "-f", "plan=" + plan])
        m = re.search(r"/actions/runs/(\d+)", (r.stdout or "") + (r.stderr or ""))
        run_id = m.group(1) if m else None
        t_end = time.time() + float(os.environ.get("AGMM_SNAP_ACTIONS_WAIT", "1500"))
        title = "AGMM short snap " + label
        while run_id is None and time.time() < t_end:   # older gh prints no URL: find the run by its unique title
            rows = json.loads(_gh(["run", "list", "-R", ACTIONS_REPO, "--workflow", ACTIONS_WF, "--event", "workflow_dispatch",
                                   "--limit", "30", "--json", "databaseId,displayTitle"]).stdout)
            hit = [x for x in rows if x.get("displayTitle") == title]
            if hit:
                run_id = str(hit[0]["databaseId"])
            else:
                time.sleep(6 + random.random() * 4)
        if run_id is None:
            raise RuntimeError("the workflow run never appeared")
        log("actions run %s (package %s %s, %.0f s to dispatch)" % (run_id, release, how, t_up - t0))
        status = conclusion = ""
        t_wait = time.time()
        while time.time() < t_end:
            v = json.loads(_gh(["run", "view", run_id, "-R", ACTIONS_REPO, "--json", "status,conclusion"], check=False).stdout or "{}")
            status, conclusion = v.get("status", ""), v.get("conclusion", "")
            if status == "completed":
                break
            if status != "in_progress" and time.time() - t_wait > queue_wait:
                _gh(["run", "cancel", run_id, "-R", ACTIONS_REPO], check=False)
                raise RuntimeError("run %s still %s after %.0f s (waiting for a hosted runner); cancelled it" % (run_id, status or "queued", queue_wait))
            if status == "in_progress":
                t_wait = time.time()   # the queue limit applies only until a runner picks the job up
            # root 6 Oct 08:55: ~10 agents polling every 3 s tripped GitHub's secondary rate limit on agmmltd-arch, which
            # blocked snaps, cloud renders and archives for everyone. Poll every ~15 s with jitter.
            # 13 Oct: floor raised from 12 to 15 s because static_precheck now runs several snap calls in parallel (4x the polls).
            time.sleep(15 + random.random() * 6)
        if status != "completed":
            raise RuntimeError("workflow run %s did not finish within the wait (status %r)" % (run_id, status))
        if conclusion != "success":
            tail = (_gh(["run", "view", run_id, "-R", ACTIONS_REPO, "--log-failed"], check=False, timeout=120).stdout or "")[-900:]
            raise RuntimeError("workflow run %s ended %s: %s" % (run_id, conclusion, tail))
        name = label + "-SNAPS"
        snapshot_capacity(tmp, run_id)
        artifacts = json.loads(_gh(["api", "repos/%s/actions/runs/%s/artifacts" % (ACTIONS_REPO, run_id)]).stdout)
        matching = [a for a in artifacts.get("artifacts", []) if a.get("name") == name]
        if matching:
            snapshot_capacity(tmp, run_id, max(int(a.get("size_in_bytes", 0)) for a in matching))
        last = ""
        for attempt in range(6):   # the artifact can lag the run's completion by a moment
            snapshot_capacity(tmp, run_id)
            d = _gh(["run", "download", run_id, "-R", ACTIONS_REPO, "-n", name, "-D", os.path.join(tmp, "dl")], check=False, timeout=600)
            if d.returncode == 0:
                break
            last = (d.stderr or d.stdout)[-300:]
            time.sleep(3)
        else:
            raise RuntimeError("artifact %s did not download: %s" % (name, last))
        for _look, part, _pdir, dest, times in jobs:
            got = sorted(glob.glob(os.path.join(tmp, "dl", part, "*.jpg")))
            if not any(os.path.basename(g).startswith("frame-") for g in got):
                raise RuntimeError("no frames came back for %s" % part)
            os.makedirs(dest, exist_ok=True)
            for g in got:
                move_snapshot(g, os.path.join(dest, os.path.basename(g)))
        wall = time.time() - t0
        log("actions done in %.0f s (run %s)" % (wall, run_id))
        try:
            with open(ACTIONS_LEDGER, "a") as fh:
                fh.write(json.dumps({"id": ID, "kind": "snap-actions", "run": run_id, "release": how, "wall_s": round(wall),
                                     "frames": sum(len(j[4]) for j in jobs), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        except OSError:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)   # this run's own transient copies


PART_EPS = 1e-6   # seconds; far below a frame (33 ms) and far above float error (~1e-14)


def assign_times(parts, times):
    """Part-local snapshot times for each part, in `parts` order. Every requested time belongs to EXACTLY ONE part.
    12 Oct 2026 (C13, 4 parts of 428 frames): the boundary 42.8 s is part C's end (28.5333.. + 14.2666.. = 42.800000000000004)
    and part D's start (1284/30 = 42.8), so the old test `off <= t < off + dur` was true for both and static_precheck refused the
    short ("Duplicate sample at 42.80s"); with the opposite one-ulp error it would have been true for neither ("Missing").
    The interval is now [off - eps, off + dur - eps): a tick on a boundary, up to float noise either way, goes to the LATER part,
    and the first matching part wins so a tick can never be counted twice. Local times are clamped at 0 (no "-0.0")."""
    out = [[] for _ in parts]
    for t in times:
        for i, p in enumerate(parts):
            if p["off"] - PART_EPS <= t < p["off"] + p["dur"] - PART_EPS:
                out[i].append(round(max(0.0, t - p["off"]), 2) + 0.0)
                break
    return out


def main():
    requested = os.environ.get("AGMM_SNAP", "").strip().lower()
    if sys.platform == "darwin" and requested == "local":
        log("local snapshots are disabled on this Mac; using the hosted Actions path instead")
        os.environ["AGMM_SNAP"] = requested = "auto"
    if os.environ.get("FLEET_NO_LOCAL_MEDIA") == "1" and requested not in ("actions", "auto", "codespace", "codespace-only", "remote"):
        log("FLEET_NO_LOCAL_MEDIA: local snapshots are disabled for video fleet workers; use the approved hosted route")
        raise SystemExit(86)
    ap = argparse.ArgumentParser()
    ap.add_argument("id"); ap.add_argument("--every", type=float); ap.add_argument("--at"); ap.add_argument("--against")
    a = ap.parse_args()
    t_run = time.time() - 1
    t_call = time.time()
    out = os.path.join(KIT, "out", a.id)
    parts = json.load(open(os.path.join(out, "build", "parts.json")))["parts"]
    total = parts[-1]["off"] + parts[-1]["dur"]
    if a.at:
        times = [float(x) for x in a.at.split(",")]
    elif a.every:
        times = [round(i * a.every, 2) for i in range(int(total / a.every) + 1)]
    else:
        beats = json.load(open(os.path.join(out, "resolved.json")))
        beats = beats.get("beats", beats) if isinstance(beats, dict) else beats
        times = sorted({0.05, round(total - 0.1, 2)} | {round(float(b["from"]) + 0.35, 2) for b in beats})
    jobs = []
    # 13 Oct 2026 (parallel static capture): static_precheck runs several snap.py calls at once over contiguous time ranges and
    # gives each its own output folder, so overlapping frames from two runners can be compared instead of overwriting each other.
    # Only "snap" or "snap-<alnum>" under out/<ID>/ is accepted; the default is unchanged.
    snapdir = os.environ.get("AGMM_SNAP_DIR", "snap")
    if not re.fullmatch(r"snap(-[A-Za-z0-9]{1,16})?", snapdir):
        raise SystemExit("AGMM_SNAP_DIR must be 'snap' or 'snap-<letters/digits>', got %r" % snapdir)
    assigned = assign_times(parts, times)
    for p, local in zip(parts, assigned):
        if local:
            jobs.append((p["look"], p["out"], os.path.join(out, "build", "pkg", p["look"]), os.path.join(out, snapdir, p["out"]), local))
    against = os.path.abspath(a.against) if a.against else None
    remote_ok = False
    order = backends() if jobs else []
    last_err = ""
    for backend in order:
        if backend == "local":
            break
        try:
            if backend == "actions":
                # queued longer than AGMM_SNAP_QUEUE_WAIT (default 600 s) -> give up on actions, but only when a guarded
                # codespace is really available to fall back to; otherwise keep waiting the whole AGMM_SNAP_ACTIONS_WAIT
                qw = float(os.environ.get("AGMM_SNAP_ACTIONS_WAIT", "1500"))
                if "codespace" in order[order.index("actions") + 1:]:
                    try:
                        cs_guard_users()
                        qw = float(os.environ.get("AGMM_SNAP_QUEUE_WAIT", "600"))
                    except RuntimeError:
                        pass
                actions_snap(a.id, jobs, against, [p["look"] for p in parts], qw)
            else:
                remote_snap(a.id, jobs, against)
            remote_ok = True
            break
        except LocalSnapshotCapacityError as e:
            log(str(e))
            raise SystemExit(87)  # local capacity cannot be solved by another hosted backend
        except (Exception, SystemExit) as e:
            nxt = [b for b in order[order.index(backend) + 1:] if b != "local"]
            last_err = str(e)
            log("%s path FAILED (%s)%s" % (backend, str(e).strip()[-600:], "; trying " + nxt[0] if nxt else ""))
    if order and not remote_ok and "actions" in order and order != ["local"] and codespace_blocked() \
            and not re.search(r"REFUSED|not a short ID|--against|BUILD\.json", last_err):
        # opsA 19 Oct: codespaces are 402-flagged (possibly flagged by this very call), so a failed Actions run has no fallback;
        # a transient failure (dispatch glitch, artifact lag, GitHub 5xx) is retried with the whole wait instead of killing the maker.
        for n in range(int(os.environ.get("AGMM_SNAP_ACTIONS_RETRIES", "2"))):
            time.sleep(float(os.environ.get("AGMM_SNAP_RETRY_PAUSE", "20")) * (1 + random.random()))
            log("codespaces unusable; retrying the Actions route (%d)" % (n + 1))
            try:
                actions_snap(a.id, jobs, against, [p["look"] for p in parts], float(os.environ.get("AGMM_SNAP_ACTIONS_WAIT", "1500")))
                remote_ok = True
                break
            except LocalSnapshotCapacityError as e:
                log(str(e))
                raise SystemExit(87)
            except (Exception, SystemExit) as e:
                last_err = str(e)
                log("actions retry %d FAILED (%s)" % (n + 1, last_err.strip()[-400:]))
                if re.search(r"REFUSED|not a short ID|--against|BUILD\.json", last_err):
                    break
    if order and not remote_ok and order != ["local"]:
        if sys.platform == "darwin":
            log("no hosted snapshot backend worked; refusing local fallback on this Mac")
            raise SystemExit(86)
        log("falling back to a LOCAL snapshot")
    shots = []
    for look, part, pdir, dest, local in jobs:
        os.makedirs(dest, exist_ok=True)
        if not remote_ok and os.environ.get("FLEET_NO_LOCAL_MEDIA") == "1":
            log("FLEET_NO_LOCAL_MEDIA: hosted snapshot failed; refusing local fallback")
            raise SystemExit(86)
        if not remote_ok:
            local_snap(pdir, dest, local, against)
        # 28 Sep (root): PNG snaps filled the disk (3.5 GB in one morning across 10 agents) and blocked renders.
        # This run's fresh PNGs become JPG q92 (about a tenth of the size, fine for looking at frames); the PNG is
        # this tool's own transient output, never an archived file. Older files in dest are left alone.
        from PIL import Image
        for f in sorted(glob.glob(os.path.join(dest, "*.png"))):
            if os.path.getmtime(f) >= t_run:
                j = f[:-4] + ".jpg"
                Image.open(f).convert("RGB").save(j, quality=92)
                os.remove(f)
                shots.append(j)
        shots += [f for f in sorted(glob.glob(os.path.join(dest, "*.jpg"))) if os.path.getmtime(f) >= t_run and f not in shots]
    print("\n".join(shots))
    print("%d frames in %s" % (len(shots), os.path.join(out, snapdir)))
    log("call took %.0f s" % (time.time() - t_call))


if __name__ == "__main__":
    main()
