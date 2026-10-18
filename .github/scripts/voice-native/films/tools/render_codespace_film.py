#!/usr/bin/env python3
"""Render a long-form film's time segments on GitHub Codespaces (1920x1080), N codespaces in parallel.

Why: 24 Sep 2026 GitHub Actions refused jobs (spending limit), every Google credit is gone and Sam will not pay.
Codespaces gives agmmltd-arch 120 core-hours a month on 4-core machines and stops at the $0 limit instead of billing.
This is the film counterpart of kit/tools/render_codespace.py (shorts). Docs: films/tools/README-RENDER.md.

What it does
  * Reads a sealed package made by the film's tools/package.sh (renders/<tag>/source.tar.gz: film/, audio/, static_check.py,
    SHA256SUMS.txt). The composition must read `window.<X>_SEG = null;` in index.html (a segment plays T = t0 + local).
  * Splits the film into segments (default 8.6 s, the last takes the remainder), orders them heaviest-first when an
    estimate file is given, and runs ONE shared queue across N codespaces named agmm-film-1..N (work stealing: a
    codespace that finishes early takes the next segment, so the slow office scenes do not strand one machine).
  * Per segment, on the codespace: copy film/ -> segNN, set <X>_SEG and data-duration, `npx hyperframes@0.8.71 render
    --fps 30 --quality high`, then cap with the SAME x264 settings on every segment (CRF 16, maxrate 25M, GOP 60,
    timescale 15360) so segments join by stream copy. Rendering runs under setsid nohup (stdin from /dev/null, so the
    launching ssh returns at once) and is polled; a poll that finds no marker and no render process marks it DEAD.
  * Copies each segment back, probes it locally (1920x1080, exact frame count), resumes past segments already on disk.
  * Stops each codespace as soon as the queue is empty (billing counts running time, not work) and appends one line
    per codespace to kit/registry/codespace-usage.jsonl (same format as the shorts tool) with core-minutes.

Usage
  render_codespace_film.py <film build dir> --tag r2 [--n 4] [--workers 3] [--full 517.4] [--seglen 8.6]
                           [--only 01,07] [--est est.json] [--dest DIR] [--id F01-arup] [--dry-run]
  Output: <build>/renders/<tag>/cs1080/SEG<NN>.mp4 (+ .render.log), result.json. Exit 0 = every segment present+verified.
Never renders on the Mac: the only local work is gh, ffprobe and file copies.
"""
import argparse, fcntl, json, math, os, queue, re, shlex, subprocess, sys, threading, time

V2 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Two GitHub accounts host render machines, each with its own free allowance (120 core-hours/month, 2 running at once).
# Root, 24 Sep ~23:00: FILMS RENDER ON SamAGMM (Sam's personal account, repo SamAGMM/agmm-render-box); the shorts use
# agmmltd-arch. AGMM_GH_USER picks the account; every gh call then runs with that account's GH_TOKEN (gh holds both
# logins; the gh default stays agmmltd-arch). One core-minute ledger per account, shared with the shorts tool.
GH_USER = os.environ.get("AGMM_GH_USER", "SamAGMM")
REPO = {"agmmltd-arch": "agmmltd-arch/agmm-video-render", "SamAGMM": "SamAGMM/agmm-render-box"}[GH_USER]
LEDGER = os.path.join(V2, "kit", "registry", "codespace-usage-%s.jsonl" % GH_USER)
_TOKEN = None


def gh_env():
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = subprocess.run(["gh", "auth", "token", "-u", GH_USER], capture_output=True, text=True).stdout.strip()
        if not _TOKEN:
            sys.exit("gh holds no login for %s (gh auth login, then gh auth switch back to agmmltd-arch)" % GH_USER)
    return dict(os.environ, GH_TOKEN=_TOKEN)
MACHINE = "standardLinux32gb"   # 4 cores / 16 GB; only 2- and 4-core machines are offered on this plan
CORES = 4
FPS = 30
HF = "hyperframes@0.8.71"
# identical on every segment so the concat demuxer can join them with -c copy
RES = ""   # set from --res in main()
CAP4K = ("-map 0:v:0 -an -c:v libx264 -profile:v high -preset slow -crf 17 -maxrate 60M -bufsize 120M -level:v 5.1 "
         "-pix_fmt yuv420p -r 30 -g 60 -video_track_timescale 15360 -movflags +faststart")   # = cloud_film.CAP["landscape-4k"]
CAP = ("-map 0:v:0 -an -c:v libx264 -profile:v high -preset slow -crf 16 -maxrate 25M -bufsize 50M -level:v 4.2 "
       "-pix_fmt yuv420p -r 30 -g 60 -video_track_timescale 15360 -movflags +faststart")
SETUP = ("command -v ffmpeg >/dev/null || (sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "
         "ffmpeg libnss3 libatk-bridge2.0-0 libgbm1 libxkbcommon0 libasound2t64 libxcomposite1 libxdamage1 libxrandr2 "
         "libpango-1.0-0 libcairo2 fonts-liberation >/dev/null)")
LOCK = threading.Lock()
ACTIVE = {}   # display -> [codespace, t_start, done list, args]; lets a SIGTERM/SIGHUP still stop machines and write the ledger


def log(msg):
    with LOCK:
        print(time.strftime("%H:%M:%S ") + msg, flush=True)


def run(cmd, check=True, timeout=None, retries=0):
    for k in range(retries + 1):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=gh_env() if cmd and cmd[0] == "gh" else None)
        except subprocess.TimeoutExpired as ex:
            p = subprocess.CompletedProcess(cmd, 124, "", "timeout after %ss" % ex.timeout)
        if p.returncode == 0 or k == retries:
            break
        time.sleep(10 * (k + 1))
    # root 29 Sep: SamAGMM's 402 read as "UNREACHABLE" for 45 min and never reached render_sched, which kept routing to it.
    # A 402 "billing issue" on any gh call writes the month flag render_codespace.py writes, and stops this run.
    out = (p.stdout or "") + (p.stderr or "")
    if cmd and cmd[0] == "gh" and "HTTP 402" in out and "billing" in out:
        open(os.path.join(V2, "kit", "registry", "codespace-402-%s-%s.flag" % (GH_USER, time.strftime("%Y-%m"))), "w").write(
            "%s: %s\n" % (time.strftime("%F %T"), out[-300:]))
        sys.exit("CODESPACE 402 for %s: allowance used up this month; flagged for render_sched. Render locally." % GH_USER)
    if check and p.returncode:
        raise RuntimeError("FAILED: %s\n%s" % (" ".join(cmd)[:300], (p.stdout + p.stderr)[-1500:]))
    return p


def ssh(cs, script, check=True, timeout=600, retries=2):
    return run(["gh", "codespace", "ssh", "-c", cs, "--", "bash -lc " + shlex.quote(script)], check=check, timeout=timeout, retries=retries)


def segments(full, seglen):
    n = int(math.floor(full / seglen + 1e-9))
    out = []
    for k in range(n):
        t0 = round(k * seglen, 3)
        ln = round(seglen if k < n - 1 else full - t0, 3)
        out.append({"i": "%02d" % (k + 1), "t0": t0, "len": ln, "frames": int(round(ln * FPS))})
    return out


def probe(path):
    p = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,nb_frames,codec_name,pix_fmt",
             "-of", "json", path], check=False)
    try:
        s = json.loads(p.stdout)["streams"][0]
        return {"w": s["width"], "h": s["height"], "frames": int(s.get("nb_frames", 0)), "codec": s["codec_name"], "pix": s["pix_fmt"]}
    except Exception:
        return None


def verified(path, seg):
    if not os.path.exists(path):
        return None
    pr = probe(path)
    W_, H_ = (3840, 2160) if RES else (1920, 1080)   # 30 Sep: --res landscape-4k (F07 after the 1 Oct reset)
    ok = pr and pr["w"] == W_ and pr["h"] == H_ and pr["frames"] == seg["frames"] and pr["codec"] == "h264" and pr["pix"] == "yuv420p"
    return pr if ok else None


def flicker(path):
    """Share of frames that are isolated luma dips/spikes against BOTH neighbours (> 8 levels on a 64x36 grey thumb).
    25 Sep: F01 r2 SEG16 (rendered on an agmmltd-arch codespace, 3 workers) came back with 2 of every 3 frames black:
    one Chrome worker drew the WebGL scene and the other two captured an empty canvas. Probe, frame count and a
    contact sheet sampling every 6th frame (always the same worker) all passed. Clean segments score 0-2%, a press-room
    scene with camera flashes 2%, the broken one 33%."""
    import numpy as np
    raw = subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-threads", "2", "-i", path, "-vf", "scale=64:36,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 36, 64).astype(float)
    m = x.mean(axis=(1, 2))
    iso = [i for i in range(1, len(m) - 1) if (m[i] - m[i - 1]) * (m[i] - m[i + 1]) > 0 and min(abs(m[i] - m[i - 1]), abs(m[i] - m[i + 1])) > 8]
    return round(100.0 * len(iso) / max(1, len(m)), 1)


FLICKER_MAX = 5.0


def get_codespace(display):
    rows = json.loads(run(["gh", "codespace", "list", "--json", "name,displayName,state,repository"], retries=2).stdout)
    rows = [r for r in rows if r["repository"] == REPO and r["displayName"] == display]
    if rows:
        return rows[0]["name"], rows[0]["state"]
    out = run(["gh", "codespace", "create", "-R", REPO, "-b", "main", "-m", MACHINE, "--idle-timeout", "5m",
               "--retention-period", "72h", "--display-name", display], timeout=900, retries=1).stdout
    return out.strip().splitlines()[-1].strip(), "Created"


def ledger_append(row):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as fh:            # other writers (shorts tool, other films) append to the same file
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(row) + "\n")
        fcntl.flock(fh, fcntl.LOCK_UN)


def month_core_hours():
    ym = time.strftime("%Y-%m")
    tot = 0.0
    if os.path.exists(LEDGER):
        for l in open(LEDGER):
            if l.strip():
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                if str(r.get("at", "")).startswith(ym):
                    tot += float(r.get("core_min", 0))
    return tot / 60


def worker(k, a, pkg, q, dest, results, failures):
    display = "%s-%d" % (a.prefix, k)
    t_start = time.time()
    cs = None; done = []
    try:
        # The account allows only 2 RUNNING codespaces at once (measured 24 Sep: a 3rd create/start returns HTTP 400
        # "You have too many codespaces running"), shared with the shorts' agmm-render-* machines. A worker that hits the
        # cap waits for a slot and gives up as soon as the queue is empty, so it never blocks or bills anything.
        while True:
            if q.empty():
                log("[%s] queue empty before a slot freed; not started" % display)
                return
            try:
                cs, state = get_codespace(display)
                if state == "Shutdown":
                    run(["gh", "codespace", "ssh", "-c", cs, "--", "true"], timeout=600)   # starts it; raises at the cap
                break
            except RuntimeError as ex:
                if "too many codespaces running" not in str(ex):
                    raise
                cs = None
                t_start = time.time()                     # no machine is running for this worker while it waits
                log("[%s] account at its running-codespace cap; waiting 60 s for a slot" % display)
                time.sleep(60)
        log("[%s] codespace %s (%s)" % (display, cs, state))
        ACTIVE[display] = [cs, t_start, done, a]
        J = "film-job-%s" % a.id
        # SALVAGE (24 Sep 23:40): an interrupted run leaves finished segments (.ok + .mp4) on the codespace; copy them back
        # before the job dir is cleared, so no finished render is thrown away
        left = ssh(cs, "cd ~/%s/out 2>/dev/null && for f in SEG*.ok; do b=${f%%.ok}; [ -s $b.mp4 ] && echo $b; done; true" % J, check=False).stdout.split()
        for o in [x for x in left if re.fullmatch(r"SEG\d\d", x)]:
            seg = next((x for x in segments(a.full, a.seglen) if "SEG" + x["i"] == o), None)
            if seg and not verified(os.path.join(dest, o + ".mp4"), seg):
                run(["gh", "codespace", "cp", "-c", cs, "-e", "remote:~/%s/out/%s.mp4" % (J, o), "remote:~/%s/out/%s.render.log" % (J, o), dest + "/"],
                    check=False, timeout=1800, retries=2)
                log("[%s] salvaged %s from an earlier run: %s" % (display, o, "verified" if verified(os.path.join(dest, o + ".mp4"), seg) else "BAD, will re-render"))
        # WARM-UP (25 Sep 00:30): hyperframes preflights `ffmpeg -version` with a 5 s timeout; on a codespace that has just
        # been started, the cold disk made it time out ("FFmpeg cannot start", no exit code) and both first renders failed.
        ssh(cs, SETUP + " && node -v && ffmpeg -version >/dev/null && npx --yes %s --version >/dev/null 2>&1; "
                        "rm -rf ~/%s && mkdir -p ~/%s/project ~/%s/out" % (HF, J, J, J), timeout=1200)
        run(["gh", "codespace", "cp", "-c", cs, "-e", pkg, "remote:~/%s/" % J], timeout=1800, retries=2)
        chk = ssh(cs, "cd ~/{J} && tar -xzf source.tar.gz -C project && cd project && sha256sum -c SHA256SUMS.txt >/dev/null && "
                      "python3 static_check.py && grep -o 'window\\.[A-Za-z0-9]*_SEG = null;' {c}/index.html".format(J=J, c=a.comp)).stdout
        var = re.search(r"window\.(\w+_SEG) = null;", chk).group(1)
        log("[%s] package verified, segment variable %s" % (display, var))
        while True:
            try:
                seg = q.get_nowait()
            except queue.Empty:
                break
            i = seg["i"]; o = "SEG%s" % i
            if verified(os.path.join(dest, o + ".mp4"), seg):     # salvaged by another worker after the queue was built
                continue
            for attempt in (1, 2):
                s = time.time()
                script = (
                    "cd ~/{J}/project && rm -rf seg{i} && cp -R {c} seg{i} && "
                    "sed -i 's|window.{v} = null;|window.{v} = {{ t0: {t0}, len: {ln} }};|' seg{i}/index.html && "
                    "sed -i -E 's|data-duration=\"[0-9.]+\"|data-duration=\"{ln}\"|' seg{i}/index.html && "
                    "rm -f ~/{J}/out/{o}.ok ~/{J}/out/{o}.fail && {{ "
                    "setsid nohup bash -c 'cd ~/{J}/project/seg{i} && HYPERFRAMES_NO_TELEMETRY=1 npx --yes {hf} render --fps 30 --workers {w} --quality high{res} "
                    "--player-ready-timeout 180000 --protocol-timeout 600000 --output ~/{J}/out/{o}.raw.mp4 > ~/{J}/out/{o}.render.log 2>&1 && "
                    "ffmpeg -hide_banner -loglevel error -y -i ~/{J}/out/{o}.raw.mp4 {cap} ~/{J}/out/{o}.mp4 && rm -f ~/{J}/out/{o}.raw.mp4 && "
                    "rm -rf ~/{J}/project/seg{i} && touch ~/{J}/out/{o}.ok || touch ~/{J}/out/{o}.fail' < /dev/null > /dev/null 2>&1 & }}; echo launched"
                ).format(J=J, i=i, c=a.comp, v=var, t0=seg["t0"], ln=seg["len"], o=o, hf=HF, w=a.workers, cap=(CAP4K if RES else CAP), res=(" --resolution " + RES if RES else ""))
                # never retried: a retry would double-launch. If the launch call itself times out, the poll below decides
                # (RUN if the render is alive, DEAD if it never started).
                ssh(cs, script, check=False, timeout=180, retries=0)
                status = "RUN"; bad_polls = 0
                while status == "RUN":
                    time.sleep(20)
                    # the poll also proves the render is alive: a codespace that idled out or restarted has no hyperframes
                    # process and no marker, which used to read as RUN forever. '[h]' keeps pgrep from matching this poll's own bash -lc line;
                    # the setsid wrapper's command line holds 'hyperframes@' until it touches .ok/.fail, cap stage included (23:31-23:42 on 24 Sep, both machines shut down)
                    p = ssh(cs, "cd ~/{J}/out && if [ -f {o}.ok ]; then echo OK; elif [ -f {o}.fail ]; then echo FAIL; "
                                "elif pgrep -f '[h]yperframes@' >/dev/null; then echo RUN; else sleep 5; [ -f {o}.ok ] && echo OK || echo DEAD; fi".format(J=J, o=o),
                            check=False, timeout=120, retries=1)
                    if p.returncode == 0:
                        bad_polls = 0
                        status = (p.stdout.strip().splitlines() or ["RUN"])[-1]
                    else:
                        bad_polls += 1
                        status = "UNREACHABLE" if bad_polls >= 6 else "RUN"
                    if time.time() - s > a.seg_timeout:
                        status = "TIMEOUT"
                if status == "OK":
                    local = os.path.join(dest, o + ".mp4")
                    run(["gh", "codespace", "cp", "-c", cs, "-e", "remote:~/%s/out/%s.mp4" % (J, o), "remote:~/%s/out/%s.render.log" % (J, o), dest + "/"],
                        timeout=1800, retries=2)
                    pr = verified(local, seg)
                    fl = flicker(local) if pr else None
                    if pr and fl > FLICKER_MAX:
                        os.rename(local, local + ".flicker-%s" % time.strftime("%H%M%S"))
                        pr = None; status = "FLICKER %.0f%% of frames are isolated black/bright frames" % fl
                    if pr:
                        tail = open(os.path.join(dest, o + ".render.log"), errors="ignore").read()
                        mode = re.search(r"(screenshot|beginframe|BeginFrame)[a-z ]*capture", tail)
                        done.append({"part": o, "t0": seg["t0"], "len": seg["len"], "secs": round(time.time() - s, 1), "frames": pr["frames"],
                                     "bytes": os.path.getsize(local), "capture": mode.group(0) if mode else None, "flicker_pct": fl})
                        ssh(cs, "rm -f ~/%s/out/%s.mp4" % (J, o), check=False)
                        log("[%s] %s ok in %.0fs (%d frames, %.1f MB)" % (display, o, time.time() - s, pr["frames"], os.path.getsize(local) / 1e6))
                        break
                    if not status.startswith("FLICKER"):
                        status = "BADPROBE %s" % probe(local)
                tail = ssh(cs, "tail -25 ~/%s/out/%s.render.log" % (J, o), check=False).stdout
                log("[%s] %s attempt %d failed: %s\n%s" % (display, o, attempt, status, tail[-1200:]))
                if status in ("TIMEOUT", "UNREACHABLE", "DEAD"):
                    ssh(cs, "pkill -f 'hyperframes' ; pkill -f chrome ; true", check=False)
            else:
                failures.append(o)
    except Exception as ex:   # a dead codespace must not strand the queue: other workers keep draining it
        log("[%s] worker error: %s" % (display, str(ex)[:1500]))
        failures.append("worker-%d: %s" % (k, str(ex)[:200]))
    finally:
        if cs and ACTIVE.pop(display, None) is not None:
            run(["gh", "codespace", "stop", "-c", cs], check=False, timeout=300, retries=2)
            wall = time.time() - t_start
            row = {"id": a.id, "round": a.tag, "account": GH_USER, "repo": REPO, "codespace": cs, "display": display, "kind": "film-1080", "wall_s": round(wall),
                   "core_min": round(wall / 60 * CORES, 1), "parts": done, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            ledger_append(row)
            results.append(row)
            log("[%s] stopped after %.1f min wall = %.0f core-min, %d segments" % (display, wall / 60, wall / 60 * CORES, len(done)))


def on_signal(signum, frame):
    """24 Sep 23:40: an app restart killed the run; its codespaces idled on unbilled-looking but billed, and no ledger line
    was written. Now any SIGTERM/SIGHUP/SIGINT stops every active codespace and writes its ledger line before exiting."""
    for display, (cs, t0, done, a) in list(ACTIVE.items()):
        ACTIVE.pop(display, None)
        run(["gh", "codespace", "stop", "-c", cs], check=False, timeout=300)
        wall = time.time() - t0
        ledger_append({"id": a.id, "round": a.tag, "account": GH_USER, "repo": REPO, "codespace": cs, "display": display, "kind": "film-1080",
                       "wall_s": round(wall), "core_min": round(wall / 60 * CORES, 1), "parts": done, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "note": "interrupted by signal %d" % signum})
        log("[%s] signal %d: stopped %s after %.1f min" % (display, signum, cs, wall / 60))
    os._exit(3)


def main():
    import signal
    for sg in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sg, on_signal)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("build")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--id", default=None, help="ledger id (default: the film folder name, e.g. F01-arup)")
    ap.add_argument("--comp", default="film", help="composition folder inside the package")
    ap.add_argument("--full", type=float, default=None, help="film length in s (default: data-duration of <comp>/index.html)")
    ap.add_argument("--seglen", type=float, default=8.6)
    ap.add_argument("--prefix", default="agmm-film", help="codespace display-name prefix; F05 uses agmm-film-f05 (card, 25 Sep)")
    ap.add_argument("--n", type=int, default=2, help="codespaces in parallel (agmm-film-1..N); the account runs at most 2 at once")
    ap.add_argument("--workers", type=int, default=3, help="hyperframes Chrome workers per codespace")
    ap.add_argument("--only", default="", help="comma list of segment ids to (re)render")
    ap.add_argument("--est", default=None, help="json {seg id: seconds} to order heaviest first")
    ap.add_argument("--dest", default=None)
    ap.add_argument("--seg-timeout", dest="seg_timeout", type=int, default=5400)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--res", default="", help="'' = 1920x1080 (default), 'landscape-4k' = 3840x2160 with cloud_film's 4K cap; dest defaults to cs4k/")
    a = ap.parse_args()
    b = os.path.abspath(a.build)
    if not a.id:
        a.id = os.path.basename(os.path.dirname(b)) if os.path.basename(b) == "build" else os.path.basename(b)
    pkg = os.path.join(b, "renders", a.tag, "source.tar.gz")
    if not os.path.exists(pkg):
        sys.exit("no package at %s (run tools/package.sh %s first)" % (pkg, a.tag))
    if a.full is None:
        idx = open(os.path.join(b, "renders", a.tag, "pkg", a.comp, "index.html")).read()
        a.full = float(re.search(r'data-duration="([0-9.]+)"', idx).group(1))
    global RES
    RES = a.res
    dest = os.path.abspath(a.dest or os.path.join(b, "renders", a.tag, "cs4k" if RES else "cs1080"))
    os.makedirs(dest, exist_ok=True)
    segs = segments(a.full, a.seglen)
    if a.only:
        want = set(x.strip().zfill(2) for x in a.only.split(","))
        segs = [s for s in segs if s["i"] in want]
    have = [s for s in segs if verified(os.path.join(dest, "SEG%s.mp4" % s["i"]), s)]
    todo = [s for s in segs if s not in have]
    if a.est:
        est = json.load(open(a.est)); med = sorted(est.values())[len(est) // 2] if est else 0
        todo.sort(key=lambda s: -est.get(s["i"], med))
    print("account %s (%s)" % (GH_USER, REPO))
    print("film %s tag %s: %d segments of %.1fs over %.1fs, %d already verified on disk, %d to render on %d codespace(s); "
          "month so far %.1f of 120 core-hours" % (a.id, a.tag, len(segs), a.seglen, a.full, len(have), len(todo), min(a.n, len(todo)), month_core_hours()))
    if a.dry_run or not todo:
        print(json.dumps([s["i"] for s in todo]))
        return 0 if not todo else 1
    q = queue.Queue()
    for s in todo:
        q.put(s)
    results, failures, th = [], [], []
    for k in range(1, min(a.n, len(todo)) + 1):
        t = threading.Thread(target=worker, args=(k, a, pkg, q, dest, results, failures), daemon=True)
        t.start(); th.append(t); time.sleep(5)
    for t in th:
        t.join()
    missing = [s["i"] for s in segs if not verified(os.path.join(dest, "SEG%s.mp4" % s["i"]), s)]
    core = sum(r["core_min"] for r in results)
    res = {"id": a.id, "tag": a.tag, "dest": dest, "segments": len(segs), "missing": missing, "failures": failures,
           "codespaces": results, "core_min": round(core, 1), "month_core_hours": round(month_core_hours(), 2)}
    json.dump(res, open(os.path.join(dest, "result.json"), "w"), indent=1)
    print("DONE %s %s: %d/%d segments verified, %.0f core-min this run; month so far %.1f of 120 core-hours; missing %s"
          % (a.id, a.tag, len(segs) - len(missing), len(segs), core, month_core_hours(), missing or "none"))
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
