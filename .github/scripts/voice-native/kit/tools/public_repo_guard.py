#!/usr/bin/env python3
"""public_repo_guard.py - nothing but code, specs and small text may enter agmmltd-arch/agmm-render-public.

Sam, 19 Oct 2026: the repo stays PUBLIC (free unlimited Actions), so the leaks stop at the door. Its history already holds
about 1.9 GB, almost all hosted stills (review-evidence/, public-review/, s86-public-review/ frame PNGs of 2-9 MB each).
This module is the one rule set; every writer we control calls it before anything leaves the Mac.

REFUSED (any one is enough)
  * media by extension, at any size: mp4 mov m4v wav flac m4a mp3 aac ogg opus webm mkv avi aif aiff mxf
  * images (png jpg jpeg webp gif bmp tif tiff heic avif) over 1 MiB
  * archives and model blobs (zip tar gz tgz xz bz2 zst 7z rar bin pt pth safetensors onnx ckpt) at any size
  * any file over 5 MiB, whatever it is called
  * any file under a directory named out/, renders/ (or render/), or final*/ (case-insensitive, any depth)
PASSES: code, specs, workflows and small text/json/md/csv; small images (<= 1 MiB) outside the blocked directories.
There is deliberately no bypass flag and no env override. If a file must go in, change this rule in a reviewed edit.

USE
  python3 public_repo_guard.py check FILE...             local files (exit 0 pass, 2 refuse; reasons on stderr)
  python3 public_repo_guard.py check-paths P[:SIZE]...   repo-relative paths with optional size in bytes
  python3 public_repo_guard.py pre-commit                git hook entry (staged files; only if a remote is the public repo)
  python3 public_repo_guard.py pre-push REMOTE URL       git hook entry (reads the ref lines on stdin)
  python3 public_repo_guard.py gh ARGS... [< stdin]      judge one `gh api` write call; exit 0 pass, 2 refuse
  python3 public_repo_guard.py install-hook REPO_DIR     install pre-commit + pre-push into a local clone
  python3 public_repo_guard.py selftest                  prove it refuses and passes (exit non-zero on any wrong answer)
Python: guard_gh(args, stdin_text) raises GuardRefusal; snap._gh calls it for every call that goes through the V2 tools.
Not covered (stated, not hidden): the 23 workflows inside the public repo that `git push` stills from Actions; a script that
bypasses every wrapper (call the GitHub API with curl); release assets (not git history, but public). See the OPS-B report.
"""
import base64
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

PUBLIC_REPO = "agmmltd-arch/agmm-render-public"
MIB = 1024 * 1024
IMAGE_CAP = 1 * MIB
ANY_CAP = 5 * MIB
MEDIA_EXT = {"mp4", "mov", "m4v", "wav", "flac", "m4a", "mp3", "aac", "ogg", "opus", "webm", "mkv", "avi", "aif", "aiff", "mxf"}
IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff", "heic", "avif"}
BINARY_EXT = {"zip", "tar", "gz", "tgz", "xz", "bz2", "zst", "7z", "rar", "bin", "pt", "pth", "safetensors", "onnx", "ckpt"}
BLOCK_DIR_GLOBS = ("out", "renders", "render", "final*")
CACHE = os.path.expanduser("~/.cache/public_repo_guard/blob-sizes.json")


class GuardRefusal(Exception):
    pass


def _ext(path):
    base = path.rsplit("/", 1)[-1].lower()
    return base.rsplit(".", 1)[-1] if "." in base else ""


def violations(entries):
    """entries: iterable of (repo-relative path, size in bytes or None). Returns a list of refusal reasons ([] = pass).
    An unknown size is judged on name alone for media/archives/blocked dirs, and REFUSED for images (cannot prove <= 1 MiB)."""
    out = []
    for path, size in entries:
        p = str(path).replace("\\", "/")
        while p.startswith("./"):
            p = p[2:]
        ext = _ext(p)
        dirs = [d.lower() for d in p.split("/")[:-1]]
        why = []
        if ext in MEDIA_EXT:
            why.append("media file (.%s)" % ext)
        if ext in BINARY_EXT:
            why.append("archive/binary (.%s)" % ext)
        for d in dirs:
            if any(fnmatch.fnmatch(d, g) for g in BLOCK_DIR_GLOBS):
                why.append("under blocked directory %s/" % d)
                break
        if ext in IMAGE_EXT:
            if size is None:
                why.append("image of unknown size (cannot prove <= 1 MiB)")
            elif size > IMAGE_CAP:
                why.append("image %.2f MiB > 1 MiB" % (size / MIB))
        if size is not None and size > ANY_CAP:
            why.append("file %.2f MiB > 5 MiB" % (size / MIB))
        if why:
            out.append("%s: %s" % (p, "; ".join(why)))
    return out


def _refuse(reasons, where):
    msg = "public_repo_guard REFUSED (%s): only code, specs and small text may enter %s\n  - %s" % (
        where, PUBLIC_REPO, "\n  - ".join(reasons))
    raise GuardRefusal(msg)


# ---------------------------------------------------------------- git blob size cache (blob POST -> later tree POST)
def _git_blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _cache_load():
    try:
        return json.load(open(CACHE))
    except Exception:
        return {}


def _cache_put(sha, size):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        c = _cache_load()
        c[sha] = size
        if len(c) > 20000:
            c = dict(list(c.items())[-10000:])
        tmp = CACHE + ".%d.tmp" % os.getpid()
        json.dump(c, open(tmp, "w"))
        os.replace(tmp, CACHE)
    except Exception:
        pass


def _blob_size(sha, real_gh=None):
    c = _cache_load()
    if sha in c:
        return c[sha]
    # not seen by this guard: ask the repo (read-only). Failure means unknown, which the caller treats as a refusal for images.
    try:
        r = subprocess.run([real_gh or os.environ.get("GUARD_REAL_GH") or "gh", "api",
                            "repos/%s/git/blobs/%s" % (PUBLIC_REPO, sha), "--jq", ".size"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip().isdigit():
            return int(r.stdout.strip())
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- gh api write calls
def _parse_gh(args):
    """-> (endpoint, method, fields dict, wants_stdin_input). Only what the guard needs."""
    args = list(args)
    if not args or args[0] != "api":
        return None
    endpoint, method, fields, use_input = None, None, {}, False
    i = 1
    while i < len(args):
        a = args[i]
        if a in ("-X", "--method") and i + 1 < len(args):
            method = args[i + 1].upper(); i += 2; continue
        if a.startswith("--method="):
            method = a.split("=", 1)[1].upper(); i += 1; continue
        if a in ("-f", "-F", "--raw-field", "--field") and i + 1 < len(args):
            k, _, v = args[i + 1].partition("=")
            fields[k] = v; i += 2; continue
        if a == "--input" and i + 1 < len(args):
            use_input = args[i + 1]; i += 2; continue
        if a in ("-H", "--header", "--jq", "-q", "--template", "-t", "--cache", "--hostname") and i + 1 < len(args):
            i += 2; continue
        if a.startswith("-"):
            i += 1; continue
        if endpoint is None:
            endpoint = a
        i += 1
    if endpoint is None:
        return None
    if method is None:
        method = "POST" if (fields or use_input) else "GET"
    return endpoint.split("?")[0].lstrip("/"), method, fields, use_input


def guard_gh(args, stdin_text=None, real_gh=None):
    """Judge one gh invocation. No-op unless it is an `api` WRITE call against the public repo. Raises GuardRefusal."""
    parsed = _parse_gh(args)
    if not parsed:
        return
    endpoint, method, fields, use_input = parsed
    m = re.match(r"repos/%s/(.*)$" % re.escape(PUBLIC_REPO), endpoint, re.I)
    if not m or method in ("GET", "HEAD", "DELETE"):
        return
    rest = m.group(1)
    body = dict(fields)
    if use_input:
        raw = stdin_text if use_input == "-" else open(use_input, "r", encoding="utf-8").read()
        try:
            body.update(json.loads(raw or "{}"))
        except ValueError:
            _refuse(["write call to the public repo with an unparseable --input body"], "gh api " + rest)
    if rest.startswith("contents/") and method in ("PUT", "POST"):
        path = rest[len("contents/"):]
        content = body.get("content", "")
        try:
            size = len(base64.b64decode(content, validate=False)) if content else 0
        except Exception:
            size = None
        r = violations([(path, size)])
        if r:
            _refuse(r, "contents PUT")
    elif rest == "git/blobs" and method == "POST":
        content, enc = body.get("content", ""), body.get("encoding", "utf-8")
        try:
            data = base64.b64decode(content) if enc == "base64" else str(content).encode("utf-8")
        except Exception:
            _refuse(["blob content not decodable"], "git/blobs")
        _cache_put(_git_blob_sha(data), len(data))
        if len(data) > ANY_CAP:
            _refuse(["blob %.2f MiB > 5 MiB" % (len(data) / MIB)], "git/blobs")
    elif rest == "git/trees" and method == "POST":
        tree = body.get("tree")
        if not isinstance(tree, list):
            return                                   # a tree call without entries adds nothing
        entries, unknown = [], []
        for e in tree:
            if not isinstance(e, dict) or e.get("mode") == "160000" or e.get("type") == "commit":
                continue
            if e.get("sha") is None and "content" not in e:
                continue                             # entry with sha null deletes the path
            if "content" in e:
                size = len(str(e["content"]).encode("utf-8"))
            else:
                size = _blob_size(e["sha"], real_gh)
            entries.append((e.get("path", ""), size))
        r = violations(entries)
        if r:
            _refuse(r, "git/trees")
    # git/commits and git/refs carry no paths; the tree check above is the gate. releases are not git history.


# ---------------------------------------------------------------- git hooks
def _git(args, cwd=None, inp=None):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=False, input=inp)


def _remote_is_public(cwd=None):
    r = _git(["remote", "-v"], cwd)
    return PUBLIC_REPO.lower() in r.stdout.decode(errors="replace").lower()


def staged_entries(cwd=None):
    r = _git(["diff", "--cached", "--raw", "--no-renames", "--diff-filter=AM", "-z"], cwd)
    parts = r.stdout.split(b"\0")
    out, i = [], 0
    while i + 1 < len(parts):
        meta, path = parts[i].decode(), parts[i + 1].decode(errors="replace")
        i += 2
        new_sha = meta.split()[3]
        s = _git(["cat-file", "-s", new_sha], cwd)
        out.append((path, int(s.stdout.strip()) if s.returncode == 0 else None))
    return out


def pushed_entries(stdin_lines, cwd=None):
    out = []
    zero = "0" * 40
    for line in stdin_lines:
        f = line.split()
        if len(f) < 4 or f[1] == zero:
            continue
        local, remote_sha = f[1], f[3]
        rng = [local, "--not", "--remotes"] if remote_sha == zero else ["%s..%s" % (remote_sha, local)]
        r = _git(["log", "--no-renames", "--diff-filter=AM", "--raw", "-z", "--format="] + rng, cwd)
        parts = [p for p in r.stdout.split(b"\0")]
        i = 0
        while i < len(parts):
            p = parts[i].decode(errors="replace").strip("\n")
            if p.startswith(":"):
                path = parts[i + 1].decode(errors="replace") if i + 1 < len(parts) else ""
                new_sha = p.split()[3]
                s = _git(["cat-file", "-s", new_sha], cwd)
                out.append((path, int(s.stdout.strip()) if s.returncode == 0 else None))
                i += 2
            else:
                i += 1
    return out


HOOK_BODY = """#!/bin/sh
# installed by public_repo_guard.py install-hook (OPS-B 19 Oct 2026). Do not edit; there is no bypass by design.
exec python3 "%(guard)s" %(mode)s "$@"
"""


def install_hook(repo_dir):
    guard = os.path.abspath(__file__)
    hooks = _git(["rev-parse", "--git-path", "hooks"], repo_dir).stdout.decode().strip()
    hooks = hooks if os.path.isabs(hooks) else os.path.join(repo_dir, hooks)
    os.makedirs(hooks, exist_ok=True)
    done = []
    for name, mode in (("pre-commit", "pre-commit"), ("pre-push", "pre-push")):
        p = os.path.join(hooks, name)
        if os.path.exists(p) and "public_repo_guard.py" not in open(p).read():
            os.replace(p, p + ".before-public-repo-guard")
        open(p, "w").write(HOOK_BODY % {"guard": guard, "mode": mode})
        os.chmod(p, 0o755)
        done.append(p)
    return done


# ---------------------------------------------------------------- CLI
def _report(reasons, where):
    sys.stderr.write("public_repo_guard REFUSED (%s): only code, specs and small text may enter %s\n  - %s\n" % (
        where, PUBLIC_REPO, "\n  - ".join(reasons)))
    return 2


def selftest():
    bad = []

    def expect(label, got, want):
        ok = (got == want)
        print("%-62s %s" % (label, "ok" if ok else "WRONG (got %r want %r)" % (got, want)))
        if not ok:
            bad.append(label)

    v = lambda path, size=None: bool(violations([(path, size)]))
    expect("mp4 1 KB refused", v("x/test.mp4", 1000), True)
    expect("MOV tiny refused", v("a.MOV", 10), True)
    expect("wav / flac / m4a refused", all(v("a." + e, 10) for e in ("wav", "flac", "m4a")), True)
    expect(".py passes", v("kit/tools/foo.py", 40000), False)
    expect("workflow yml passes", v(".github/workflows/x.yml", 9000), False)
    expect("spec json 275 KB passes", v("status/F02.json", 275747), False)
    expect("png 2 MiB refused", v("frames/a.png", 2 * MIB), True)
    expect("png 900 KB passes", v("frames/a.png", 900000), False)
    expect("jpg exactly 1 MiB passes, +1 byte refused", (v("a.jpg", MIB), v("a.jpg", MIB + 1)), (False, True))
    expect("image of unknown size refused", v("a.png", None), True)
    expect("small file under out/ refused", v("v2/kit/out/S66/GATE.json", 100), True)
    expect("small file under renders/ refused", v("films/F03/build/renders/r27/notes.txt", 100), True)
    expect("small file under final*/ refused", v("final-v2/readme.md", 100), True)
    expect("directory 'finalize' also matches final*", v("finalize/x.py", 100), True)
    expect("'out' only as a directory (output.py passes)", v("tools/output.py", 100), False)
    expect("zip refused", v("a.zip", 10), True)
    expect("6 MiB json refused", v("big.json", 6 * MIB), True)
    # gh api write calls
    def gh(args, stdin=None):
        try:
            guard_gh(args, stdin)
            return "pass"
        except GuardRefusal:
            return "refuse"
    R = "repos/%s" % PUBLIC_REPO
    b64 = lambda b: base64.b64encode(b).decode()
    expect("gh PUT contents x.mp4 refused", gh(["api", "-X", "PUT", R + "/contents/clips/x.mp4", "-f", "content=" + b64(b"hi")]), "refuse")
    expect("gh PUT contents tool.py passes", gh(["api", "-X", "PUT", R + "/contents/.github/scripts/t.py", "-f", "content=" + b64(b"print(1)")]), "pass")
    expect("gh PUT contents 2 MiB png refused", gh(["api", "-X", "PUT", R + "/contents/a.png", "-f", "content=" + b64(b"x" * (2 * MIB))]), "refuse")
    expect("gh POST blob 6 MiB refused", gh(["api", R + "/git/blobs", "--method", "POST", "--input", "-"],
                                            json.dumps({"content": b64(b"y" * (6 * MIB)), "encoding": "base64"})), "refuse")
    big = b"z" * (2 * MIB)
    gh(["api", R + "/git/blobs", "--method", "POST", "--input", "-"], json.dumps({"content": b64(big), "encoding": "base64"}))
    expect("gh POST tree: 2 MiB png (blob seen earlier) refused",
           gh(["api", R + "/git/trees", "--method", "POST", "--input", "-"],
              json.dumps({"tree": [{"path": "p/a.png", "mode": "100644", "type": "blob", "sha": _git_blob_sha(big)}]})), "refuse")
    small = b"print('ok')\n"
    gh(["api", R + "/git/blobs", "--method", "POST", "--input", "-"], json.dumps({"content": b64(small), "encoding": "base64"}))
    expect("gh POST tree: small .py passes",
           gh(["api", R + "/git/trees", "--method", "POST", "--input", "-"],
              json.dumps({"tree": [{"path": "p/a.py", "mode": "100644", "type": "blob", "sha": _git_blob_sha(small)}]})), "pass")
    expect("gh POST tree: path under renders/ refused",
           gh(["api", R + "/git/trees", "--method", "POST", "--input", "-"],
              json.dumps({"tree": [{"path": "renders/a.py", "mode": "100644", "type": "blob", "sha": _git_blob_sha(small)}]})), "refuse")
    expect("gh GET / other repo / workflow run never judged",
           (gh(["api", R + "/contents/a.mp4"]), gh(["api", "-X", "PUT", "repos/other/x/contents/a.mp4", "-f", "content=eA=="]),
            gh(["workflow", "run", "x.yml", "-R", PUBLIC_REPO])), ("pass", "pass", "pass"))
    # real git hook, real repo: staged mp4 blocks a commit, a .py does not
    with tempfile.TemporaryDirectory() as td:
        repo = os.path.join(td, "r")
        for cmd in (["init", "-q", repo],):
            subprocess.run(["git"] + cmd, check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", "https://github.com/%s.git" % PUBLIC_REPO], check=True)
        install_hook(repo)
        cfg = ["-c", "user.name=t", "-c", "user.email=t@t"]
        open(os.path.join(repo, "ok.py"), "w").write("print(1)\n")
        subprocess.run(["git", "-C", repo, "add", "ok.py"], check=True)
        c1 = subprocess.run(["git", "-C", repo] + cfg + ["commit", "-q", "-m", "code"], capture_output=True, text=True)
        expect("git commit of a .py goes through the hook", c1.returncode, 0)
        open(os.path.join(repo, "clip.mp4"), "wb").write(b"\0\0\0\x18ftypmp42" + b"0" * 64)
        subprocess.run(["git", "-C", repo, "add", "clip.mp4"], check=True)
        c2 = subprocess.run(["git", "-C", repo] + cfg + ["commit", "-q", "-m", "media"], capture_output=True, text=True)
        expect("git commit of a test mp4 is refused", c2.returncode != 0 and "REFUSED" in c2.stderr, True)
    print("SELFTEST", "FAILED: %s" % bad if bad else "PASSED")
    return 1 if bad else 0


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 64
    cmd, rest = argv[1], argv[2:]
    if cmd == "check":
        ents = []
        for f in rest:
            if not os.path.isfile(f):
                return _report(["%s: not a readable file (refusing)" % f], "check")
            rel = os.path.relpath(os.path.abspath(f))
            ents.append((os.path.basename(f) if rel.startswith("..") else rel, os.path.getsize(f)))
        r = violations(ents)
        if r:
            return _report(r, "check")
        print("public_repo_guard: PASS (%d file(s))" % len(ents))
        return 0
    if cmd == "check-paths":
        ents = []
        for a in rest:
            p, _, s = a.rpartition(":") if re.search(r":\d+$", a) else (a, "", "")
            ents.append((p or a, int(s) if s else None))
        r = violations(ents)
        if r:
            return _report(r, "check-paths")
        print("public_repo_guard: PASS (%d path(s))" % len(ents))
        return 0
    if cmd == "pre-commit":
        if not _remote_is_public():
            return 0
        r = violations(staged_entries())
        return _report(r, "pre-commit") if r else 0
    if cmd == "pre-push":
        url = rest[1] if len(rest) > 1 else ""
        if PUBLIC_REPO.lower() not in url.lower():
            return 0
        r = violations(pushed_entries(sys.stdin.read().splitlines()))
        return _report(r, "pre-push") if r else 0
    if cmd == "gh":
        stdin_text = sys.stdin.read() if ("--input" in rest and rest[rest.index("--input") + 1:][:1] == ["-"]) else None
        try:
            guard_gh(rest, stdin_text)
        except GuardRefusal as e:
            sys.stderr.write(str(e) + "\n")
            return 2
        return 0
    if cmd == "install-hook":
        for p in install_hook(rest[0]):
            print("installed", p)
        return 0
    if cmd == "selftest":
        return selftest()
    sys.stderr.write("unknown command %r\n" % cmd)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
