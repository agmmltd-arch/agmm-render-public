#!/usr/bin/env python3
"""render_actions_film.py <film build dir> --tag r4 [--res landscape-4k] [--only 01,07] [--workers 2] [--seglen 8.6] [--id F07]
(root, 30 Sep 2026)

Why: a 4K film is ~8 h on two Codespaces and each account has 120 free core-hours a month, so a film a day did not fit.
Public-repo GitHub Actions minutes are free and unlimited on standard runners, with up to 20 jobs at once:
agmmltd-arch/agmm-render-public, workflow agmm-film.yml (Sam, 30 Sep: "yes just make it public").

What it does (the same per-segment render as render_codespace_film.py: hyperframes@0.8.71, same x264 caps, same segments):
  1. SAFETY (public repo): refuses the package if any file name or text looks like a secret (.env, keys, tokens, cookies,
     private emails). The package is film/ + audio/ + static_check.py only, and it goes public for the render's duration
     only: the release asset is deleted afterwards and artifacts expire after 1 day. The workflow has contents:read only.
  2. Uploads the original sealed package plus a small code-only QA overlay, dispatches agmm-film.yml, waits.
  3. With --remote-only, all selected segment checks and full assembly checks stay on hosted runners; this Mac
     receives only artifact metadata receipts. Without it, the legacy local media-download path remains available.
  Exit 0 = every segment present and verified; then join4k.py / assemble as before.
"""
import argparse, calendar, glob, json, math, os, re, shutil, subprocess, sys, tarfile, tempfile, time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render_codespace_film as R   # noqa: E402  (segments, verified, flicker, probe: one definition of a good segment)

REPO = "agmmltd-arch/agmm-render-public"
WF = "agmm-film.yml"
SECRET_NAME = re.compile(r"(^|/)\.env|secret|token|credential|\.pem$|id_rsa|cookie|storage_state", re.I)
# 5 Oct: "helpdesk-was-likely-..." in an Ars Technica URL matched sk-...; a key starts a token, never mid-word.
SECRET_TEXT = re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}|sk-or-v1-|AIza[0-9A-Za-z_-]{30,}|ghp_[A-Za-z0-9]{30,}|github_pat_|xox[bp]-|"
                         rb"-----BEGIN (?:RSA |EC )?PRIVATE KEY|Bearer [A-Za-z0-9._-]{20,}|samuelwall3003|agmm\.ltd@gmail")


def gh(*args, check=True, timeout=600):
    r = subprocess.run(["gh"] + list(args), capture_output=True, text=True, timeout=timeout,
                       env=dict(os.environ, GH_PROMPT_DISABLED="1"))
    if check and r.returncode:
        sys.exit("gh %s failed: %s" % (" ".join(args[:3]), (r.stderr or r.stdout)[-400:]))
    return r


def scan(pkg):
    """Inspect tar headers and bounded small payloads without extracting any media."""
    bad = []
    count = total = 0
    try:
        with tarfile.open(pkg, mode="r|gz") as archive:
            for member in archive:
                count += 1
                if count > 10000:
                    raise ValueError("package has more than 10,000 entries")
                name = member.name
                parts = name.split("/")
                if name.startswith("/") or any(part == ".." for part in parts):
                    raise ValueError(f"unsafe archive path: {name[:160]}")
                if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                    raise ValueError(f"unsupported archive member type: {name[:160]}")
                if member.isdir():
                    continue
                if member.size < 0:
                    raise ValueError(f"negative archive entry size: {name[:160]}")
                total += member.size
                if total > 8 * 1024**3:
                    raise ValueError("package expands beyond 8 GiB")
                if SECRET_NAME.search(name):
                    bad.append(name)
                if member.size <= 5_000_000:
                    stream = archive.extractfile(member)
                    payload = stream.read(5_000_001) if stream else b""
                    if len(payload) != member.size:
                        raise ValueError(f"truncated or oversized archive entry: {name[:160]}")
                    if SECRET_TEXT.search(payload):
                        bad.append(name)
                # Large media entries are not read or extracted; tarfile advances by header size.
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise ValueError(f"cannot safely scan source package: {exc}") from exc
    return sorted(set(bad))


def hosted_artifact_receipt(run_id, label, outdir, segments, assemble_full, jobs):
    """Record hosted outputs using API metadata only; never download media to Mac."""
    data = json.loads(gh("api", f"repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100").stdout)
    wanted = ({label + "-MASTER-4K", label + "-REVIEW-1080"} if assemble_full
              else {label + "-SEG" + s["i"] for s in segments})
    found = {a["name"]: a for a in data.get("artifacts", []) if a.get("name") in wanted}
    if set(found) != wanted or any(a.get("expired") or int(a.get("size_in_bytes", 0)) <= 0
                                   for a in found.values()):
        raise RuntimeError("hosted full run lacks unexpired, nonempty master/review artifacts")
    conclusions = {j.get("name"): j.get("conclusion") for j in jobs}
    receipt = {"kind": "hosted_actions_artifact_receipt", "run_id": str(run_id),
               "run_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
               "workflow_job_conclusions": conclusions,
               "ocr_job_conclusion": next((v for k, v in conclusions.items() if k.startswith("macos-ocr")), "NOT_PRESENT"),
               "artifacts": [{"name": n, "id": found[n]["id"],
                              "size_in_bytes": found[n]["size_in_bytes"],
                              "expires_at": found[n].get("expires_at")} for n in sorted(wanted)],
               "media_downloaded_to_mac": False, "verified_segment_count": len(segments),
               "editorial_gate": "NOT_RUN",
               "release_approval": "NOT_GRANTED"}
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "ACTIONS-ARTIFACT-RECEIPT.json"), "w") as f:
        json.dump(receipt, f, indent=2)
    return receipt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build"); ap.add_argument("--tag", required=True); ap.add_argument("--res", default="")
    ap.add_argument("--only", default=""); ap.add_argument("--workers", default="2"); ap.add_argument("--seglen", type=float, default=8.6)
    ap.add_argument("--n", type=int, default=2, help="codespaces in parallel (agmm-film-1..N); the account runs at most 2 at once")
    ap.add_argument("--comp", default="film"); ap.add_argument("--id", default=None); ap.add_argument("--no-retry", action="store_true")
    ap.add_argument("--remote-only", action="store_true", help="never download/verify MP4s on this Mac")
    ap.add_argument("--overlay", type=Path, help="small QA code overlay archive to publish with the sealed render package")
    a = ap.parse_args()
    b = os.path.abspath(a.build); R.RES = a.res
    fid = a.id or os.path.basename(os.path.dirname(b)).split("-")[0]
    pkg = os.path.join(b, "renders", a.tag, "source.tar.gz")
    if not os.path.exists(pkg):
        sys.exit("no package at %s (run tools/package.sh %s first)" % (pkg, a.tag))
    bad = scan(pkg)
    if bad:
        sys.exit("REFUSED (public repo): package contains secret-looking files/text: %s" % bad[:8])
    if a.remote_only and (not a.overlay or not a.overlay.is_file()):
        sys.exit("--remote-only requires the small QA overlay archive; no media will be moved to the Mac")
    if a.remote_only:
        allowed = {".github/scripts/assemble_verify.py", ".github/scripts/run_existing_ocr_check.py",
                   "qa/gate.py", "kit/tools/frame_check.py", "kit/tools/ocr_vision.swift",
                   "kit/platforms/platforms.py", "kit/platforms/frames.json", "film/film.js",
                   "film/film.css", "film/sets_studio.js", "film-overlay.sha256"}
        with tarfile.open(a.overlay, "r:gz") as overlay_tar:
            members = overlay_tar.getmembers()
            if len(members) != len(allowed) or {m.name for m in members} != allowed:
                sys.exit("REFUSED (public repo): QA overlay is not the exact seven-file allowlist")
            if any(not m.isfile() or m.size > 2_000_000 for m in members) or sum(m.size for m in members) > 8_000_000:
                sys.exit("REFUSED (public repo): QA overlay contains an invalid/oversized entry")
        overlay_bad = scan(a.overlay)
        if overlay_bad:
            sys.exit("REFUSED (public repo): QA overlay contains secret-like text: %s" % overlay_bad[:8])
    idx = open(os.path.join(b, "renders", a.tag, "pkg", a.comp, "index.html")).read()
    segvar = re.search(r"window\.(\w+_SEG) = null;", idx).group(1)
    full = float(re.search(r'data-duration="([0-9.]+)"', idx).group(1))
    segs = R.segments(full, a.seglen)
    dest = os.path.join(b, "renders", a.tag, "cs4k" if a.res else "cs1080"); os.makedirs(dest, exist_ok=True)
    selected = [s for s in segs if not a.only or s["i"] in a.only.split(",")]
    want = selected if a.remote_only else [s for s in selected if not R.verified(os.path.join(dest, "SEG%s.mp4" % s["i"]), s)]
    print("%s %s %s: %d segments, %d to render, dest %s" % (fid, a.tag, a.res or "1080", len(segs), len(want), dest), flush=True)
    if not want:
        return print("nothing to render: every segment already verified")
    # Only a fresh complete 4K matrix receives the hosted assembly job.
    if a.remote_only and (a.res != "landscape-4k" or a.comp != "film"):
        sys.exit("--remote-only currently supports film composition at validated 4K only")
    assemble_full = (a.remote_only and a.res == "landscape-4k" and not a.only
                     and len(want) == len(segs))
    sha = subprocess.run(["shasum", "-a", "256", pkg], capture_output=True, text=True).stdout.split()[0]
    rel = "%s-%s-%s-%s" % (fid, a.tag, a.res or "1080", time.strftime("%Y%m%d%H%M%S"))
    overlay_sha = None
    if a.remote_only:
        overlay_sha = subprocess.run(["shasum", "-a", "256", str(a.overlay)], capture_output=True, text=True, check=True).stdout.split()[0]
    release_created = False
    try:
        gh("release", "create", rel, pkg, "-R", REPO, "--title", rel, "--notes", "transient render input; deleted after the render")
        release_created = True
        if a.remote_only:
            gh("release", "upload", rel, str(a.overlay), "-R", REPO)
        for attempt in (1, 2):
            label = "%s-a%d" % (rel, attempt)
            before = time.time()
            gh("workflow", "run", WF, "-R", REPO, "-f", "release=" + rel, "-f", "package_sha256=" + sha, "-f", "comp=" + a.comp,
                "-f", "fid=" + fid, "-f", "segvar=" + segvar, "-f", "segs=" + json.dumps([{k: s[k] for k in ("i", "t0", "len")} for s in want]),
                "-f", "res=" + a.res, "-f", "workers=" + str(a.workers), "-f", "tag=" + label,
                "-f", "assemble_full=" + ("true" if assemble_full else "false"),
                "-f", "remote_only=" + ("true" if a.remote_only else "false"),
                "-f", "overlay_release_asset=" + (os.path.basename(str(a.overlay)) if a.remote_only else ""),
                "-f", "overlay_sha256=" + (overlay_sha or ""))
            run_id = None
            for _ in range(30):
                time.sleep(10)
                runs = json.loads(gh("run", "list", "-R", REPO, "-w", WF, "-L", "20", "--json", "databaseId,displayTitle").stdout)
                matches = [r for r in runs if r.get("displayTitle") == "AGMM film " + label]
                if len(matches) == 1:
                    run_id = matches[0]["databaseId"]
                if run_id:
                    break
            if not run_id:
                sys.exit("dispatched but no run appeared in 5 min")
            print("run %s: https://github.com/%s/actions/runs/%s" % (run_id, REPO, run_id), flush=True)
            deadline = time.time() + 6 * 3600
            while time.time() < deadline:
                try:
                    v = json.loads(gh("run", "view", str(run_id), "-R", REPO, "--json", "status,conclusion").stdout)
                except (SystemExit, ValueError) as e:   # 12 Oct: one GitHub TLS timeout killed the dispatcher and deleted the release under a running render
                    print("poll failed (%s); retrying in 30 s" % str(e)[:120], flush=True); time.sleep(30); continue
                if v["status"] == "completed":
                    print("run %s %s" % (run_id, v["conclusion"]), flush=True); break
                time.sleep(60)
            if a.remote_only:
                if v.get("status") == "completed":
                    run_jobs = json.loads(gh("api", f"repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100").stdout).get("jobs", [])
                    render_jobs = [j for j in run_jobs if j.get("name", "").startswith("render")]
                    render_ok = len(render_jobs) == len(want) and all(j.get("conclusion") == "success" for j in render_jobs)
                    assemble_jobs = [j for j in run_jobs if j.get("name") == "assemble"]
                    assemble_ok = (not assemble_full) or (len(assemble_jobs) == 1 and assemble_jobs[0].get("conclusion") == "success")
                    if render_ok and assemble_ok:
                        receipt_dir = os.path.join(b, "renders", a.tag, "remote-final")
                        receipt = hosted_artifact_receipt(run_id, label, receipt_dir, want, assemble_full, run_jobs)
                        want = []
                        ocr_status = receipt.get("ocr_job_conclusion", "NOT_PRESENT")
                        print(f"hosted render/assembly complete; OCR job {ocr_status}; zero MP4 downloaded to Mac; approval NOT GRANTED", flush=True)
                    else:
                        print("hosted render/assembly jobs failed; retrying selected work remotely", flush=True)
                else:
                    print("hosted run timed out; retrying selected work remotely", flush=True)
            else:
                with tempfile.TemporaryDirectory() as t:
                    gh("run", "download", str(run_id), "-R", REPO, "-D", t, check=False, timeout=3600)
                    for f in glob.glob(os.path.join(t, "*", "SEG*")):
                        shutil.move(f, os.path.join(dest, os.path.basename(f)))
                failed = []
                for s in want:
                    p = os.path.join(dest, "SEG%s.mp4" % s["i"])
                    pr = R.verified(p, s)
                    fl = R.flicker(p) if pr else None
                    if pr and fl is not None and fl > R.FLICKER_MAX:
                        os.rename(p, p + ".flicker-%s" % time.strftime("%H%M%S")); pr = None
                    if not pr:
                        failed.append(s)
                print("attempt %d: %d of %d verified%s" % (attempt, len(want) - len(failed), len(want),
                      (", failed: " + ",".join(s["i"] for s in failed)) if failed else ""), flush=True)
                want = failed
            if not want or a.no_retry:
                break
    finally:
        if release_created:
            gh("release", "delete", rel, "-R", REPO, "-y", "--cleanup-tag", check=False)
            print("release %s deleted (the package is no longer public)" % rel, flush=True)
    json.dump({"tag": a.tag, "res": a.res, "failed": [s["i"] for s in want], "at": time.strftime("%Y-%m-%dT%H:%M:%S")},
              open(os.path.join(dest, "actions-result.json"), "w"), indent=1)
    sys.exit(1 if want else 0)


if __name__ == "__main__":
    main()
