#!/usr/bin/env python3
"""Pinned Ubuntu-only adapter around the complete, unchanged native sound audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
NATIVE = HERE / "sound-audit-native"
REPO = "agmmltd-arch/agmm-render-public"
PRIVATE = "agmmltd-arch/agmm-video-render"


class Refused(RuntimeError):
    pass


def need(ok, why):
    if not ok:
        raise Refused(why)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def file_sha(path, git_blob=False):
    h = hashlib.sha1() if git_blob else hashlib.sha256()
    if git_blob:
        h.update(("blob %d\0" % path.stat().st_size).encode())
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def relative(value):
    p = PurePosixPath(value)
    need(not p.is_absolute() and ".." not in p.parts and str(p) == value, "unsafe input path")
    return value


def gh(*args):
    p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=300)
    need(p.returncode == 0, "hosted GitHub read failed: " + " ".join(args[:2]))
    return p.stdout


def verify_payload(payload):
    need(platform.system() == "Linux" and os.environ.get("GITHUB_ACTIONS") == "true"
         and os.environ.get("AGMM_HOSTED_SOUND_AUDIT") == "1", "native media audit runs only on the explicit Ubuntu Actions route")
    need(os.environ.get("GITHUB_REPOSITORY") == REPO and os.environ.get("GITHUB_REF") == "refs/heads/main", "unapproved repository/ref")
    need(payload.get("schema") == 1 and re.fullmatch(r"[SCP][0-9]{2,3}", payload.get("id", "")), "invalid sound payload")
    need(payload.get("runtime_commit") == os.environ.get("GITHUB_SHA") and re.fullmatch(r"[0-9a-f]{40}", payload.get("runtime_commit", "")), "exact runtime commit mismatch")
    for key in ("plan_sha256", "manifest_sha256", "approved_hash", "request_id", "package_id"):
        need(re.fullmatch(r"[0-9a-f]{64}", payload.get(key, "")), "invalid payload hash " + key)
    for key in ("private_commit", "manifest_blob"):
        need(re.fullmatch(r"[0-9a-f]{40}", payload.get(key, "")), "invalid native Git ID")
    binding = payload["render_binding"]
    hashes = {k: binding[k] for k in ("source_sha256", "parts_sha256", "mix_sha256")}
    need(all(re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes.values()) and digest(hashes) == payload["package_id"], "native render package binding mismatch")
    need(digest(dict(hashes, approved_hash=payload["approved_hash"], render_4k=binding["render_4k"], workers=binding["workers"])) == payload["request_id"], "native render request binding mismatch")
    base = "protected-inputs/%s/sound-audit/%s/" % (payload["id"], payload["plan_sha256"])
    need(payload.get("manifest_path") == base + "INPUTS.json", "private input prefix mismatch")
    master = payload["master"]
    need(master.get("tag") == payload["id"] + "-" + payload["request_id"][:16], "native tag/request identity mismatch")
    need(re.fullmatch(r"[0-9a-f]{64}", master.get("sha256", "")) and type(master.get("bytes")) is int and master["bytes"] > 0
         and type(master.get("run")) is int and master["run"] > 0, "invalid exact master identity")
    need(master["artifact"]["name"] == master["tag"] + "-FINAL-MASTERS" and type(master["artifact"]["id"]) is int, "source artifact identity mismatch")
    pins = json.loads((NATIVE / "PINS.json").read_text())
    need(set(pins) == {"sound/audit_sound.py", "sound/v2/audio_core.py", "sound/library.json"}, "native closure inventory changed")
    for rel, sha in pins.items():
        p = NATIVE / relative(rel)
        need(p.is_file() and not p.is_symlink() and file_sha(p) == sha, "native algorithm/library source changed: " + rel)
    return base, pins


def verify_private(payload, private_root, pins):
    def git(*args):
        r = subprocess.run(["git", "-C", str(private_root), *args], capture_output=True, text=True, timeout=120)
        need(r.returncode == 0, "private Git metadata verification failed")
        return r.stdout.strip()
    need(git("rev-parse", "HEAD") == payload["private_commit"], "private checkout commit mismatch")
    need(git("remote", "get-url", "origin") in ("git@github.com:%s.git" % PRIVATE, "https://github.com/%s.git" % PRIVATE), "private origin mismatch")
    need(not git("status", "--porcelain", "--untracked-files=no"), "private checkout has tracked changes")
    mp = private_root / payload["manifest_path"]
    need(mp.is_file() and not mp.is_symlink() and file_sha(mp) == payload["manifest_sha256"] and file_sha(mp, True) == payload["manifest_blob"], "protected manifest SHA/Git blob mismatch")
    manifest = json.loads(mp.read_text())
    need(manifest.get("schema") == "agmm-hosted-sound-private-inputs-v1" and manifest.get("id") == payload["id"], "invalid protected manifest")
    for key in ("plan_sha256", "master", "approved_hash", "request_id", "package_id", "render_binding"):
        need(manifest.get(key) == payload[key], "protected manifest binding mismatch: " + key)
    need(manifest.get("native_sources") == pins, "protected manifest native source mismatch")
    base = str(PurePosixPath(payload["manifest_path"]).parent) + "/"
    rows = manifest["assets"]
    paths = [r["private_path"] for r in rows]
    need(len(paths) == len(set(paths)) and paths, "duplicate/empty protected inputs")
    listing = git("ls-tree", "-r", "-l", "--full-tree", payload["private_commit"], "--", base)
    tree = {}
    for line in listing.splitlines():
        meta, name = line.split("\t", 1)
        mode, kind, sha, size = meta.split()
        tree[name] = {"mode": mode, "kind": kind, "sha": sha, "bytes": int(size)}
    need(set(tree) == set(paths) | {payload["manifest_path"]}, "private input subtree contains missing/extra blobs")
    for row in rows:
        rel = relative(row["runtime_path"])
        need(row["private_path"] == base + rel and tree[row["private_path"]] == {"mode": "100644", "kind": "blob", "sha": row["git_blob_sha"], "bytes": row["bytes"]}, "private native blob/tree mismatch")
        src = private_root / row["private_path"]
        need(src.is_file() and not src.is_symlink() and src.stat().st_size == row["bytes"] and file_sha(src, True) == row["git_blob_sha"], "private file differs from pinned Git blob/size")
    return manifest


def stage_inputs(manifest, private_root, root):
    need(not root.exists(), "fresh hosted audit staging directory required")
    root.mkdir(parents=True)
    for rel in ("sound/audit_sound.py", "sound/v2/audio_core.py", "sound/library.json"):
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(NATIVE / rel, dest)
    verified = []
    for row in manifest["assets"]:
        src, dest = private_root / row["private_path"], root / relative(row["runtime_path"])
        actual = file_sha(src)  # only Ubuntu reads/hashes these media bytes
        for key in ("text_sha256", "catalogue_sha256", "stem_sha256"):
            if row.get(key):
                need(actual == row[key], "protected input differs from recorded native hash: " + row["runtime_path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        need(file_sha(dest) == actual and dest.stat().st_size == row["bytes"], "hosted input changed during staging")
        verified.append({"runtime_path": row["runtime_path"], "git_blob_sha": row["git_blob_sha"], "bytes": row["bytes"], "sha256_ubuntu": actual})
    out = root / "kit/out" / manifest["id"]
    cues = json.loads((out / "audio/cues.json").read_text())["cues"]
    mix = json.loads((out / "audio/mix2/mix_manifest.json").read_text())
    need(mix.get("master", {}).get("sha256") == manifest["render_binding"]["mix_sha256"], "native mix manifest differs from the exact rendered mix")
    library = {r["id"]: r for r in json.loads((root / "sound/library.json").read_text())["items"]}
    ids = {r["sfx_id"] for r in cues + mix["sfx"]["cues"]}
    need(len(mix["sfx"]["cues"]) == manifest["cue_count"] and len(ids) == manifest["sfx_count"], "native sound cue coverage mismatch")
    required = {"kit/out/%s/%s" % (manifest["id"], r) for r in ("resolved.json", "audio/cues.json", "audio/mix2/mix_manifest.json", "audio/mix2/music_gain.json", "audio/mix2/stems/voice.wav", "audio/mix2/stems/music.wav", "audio/mix2/stems/sfx.wav")}
    required |= {"sound/" + relative(library[i]["path"]) for i in ids}
    need({r["runtime_path"] for r in manifest["assets"]} == required, "audit inputs must equal the native sound-only dependency subset")
    return out, verified


def obtain_master(payload, out, tmp):
    master = payload["master"]
    artifact = json.loads(gh("api", "repos/%s/actions/artifacts/%s" % (REPO, master["artifact"]["id"])))
    need(not artifact.get("expired") and all(artifact.get(k) == v for k, v in master["artifact"].items()), "exact master artifact expired/changed")
    run = json.loads(gh("api", "repos/%s/actions/runs/%s" % (REPO, master["run"])))
    need(run.get("conclusion") == "success" and run.get("path") == ".github/workflows/agmm-short-package.yml" and artifact.get("workflow_run", {}).get("id") == master["run"], "master artifact is not the exact successful native package run")
    gh("run", "download", str(master["run"]), "-R", REPO, "-n", master["artifact"]["name"], "-D", str(tmp))
    files = list(tmp.iterdir())
    need({p.name for p in files} == {"FINAL.mp4", "TECHNICAL-EVIDENCE.json", "SHA256SUMS.txt"}
         and all(p.is_file() and not p.is_symlink() for p in files), "source master artifact inventory mismatch; compact/4K substitutes refused")
    p = tmp / "FINAL.mp4"
    need(p.stat().st_size == master["bytes"] and file_sha(p) == master["sha256"], "downloaded Ubuntu master is not the exact collected master")
    evidence = json.loads((tmp / "TECHNICAL-EVIDENCE.json").read_text())
    need(any(m.get("file") == "FINAL.mp4" and m.get("sha256") == master["sha256"] and m.get("bytes") == master["bytes"] for m in evidence.get("masters", [])), "source artifact technical evidence does not bind the collected master")
    shutil.copyfile(p, out / "FINAL.mp4")
    need(file_sha(out / "FINAL.mp4") == master["sha256"], "exact master changed during staging")


def run_native(payload, private_root, work, output):
    _, pins = verify_payload(payload)
    manifest = verify_private(payload, private_root, pins)
    out, verified = stage_inputs(manifest, private_root, work / "v2")
    obtain_master(payload, out, work / "master-artifact")
    output.mkdir(parents=True, exist_ok=False)
    native_report = work / "audit-native.json"
    command = [sys.executable, str(work / "v2/sound/audit_sound.py"), str(out / "FINAL.mp4"), "--build", str(out), "--json", str(native_report)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1500,
                            env=dict(os.environ, AUDIT_SOUND_LIBJSON=str(work / "v2/sound/library.json")))
    need(result.returncode in (0, 1) and native_report.is_file(), "native sound audit did not complete; no result emitted")
    report = json.loads(native_report.read_text())
    need(report.get("status") == ("PASS" if result.returncode == 0 else "FAIL"), "native sound exit/status mismatch")
    need(file_sha(out / "FINAL.mp4") == payload["master"]["sha256"], "exact master changed during the native audit")
    for row in verified:
        p = work / "v2" / row["runtime_path"]
        need(p.stat().st_size == row["bytes"] and file_sha(p) == row["sha256_ubuntu"], "native audit input changed during the audit")
    for rel, sha in pins.items():
        need(file_sha(work / "v2" / rel) == sha, "native audit algorithm/library changed during the audit")
    report.update({"_master_sha256": payload["master"]["sha256"], "_rc": result.returncode,
                   "_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()})
    (output / "audit.json").write_text(json.dumps(report, indent=1) + "\n")
    runtime = {".github/scripts/sound-audit-native/" + rel: value for rel, value in pins.items()}
    runtime[".github/scripts/sound-audit-native/PINS.json"] = file_sha(NATIVE / "PINS.json")
    receipt = {"schema": "agmm-hosted-native-sound-audit-v1", "id": payload["id"], "plan_sha256": payload["plan_sha256"],
               "private_commit": payload["private_commit"], "manifest_blob": payload["manifest_blob"], "manifest_sha256": payload["manifest_sha256"],
               "approved_hash": payload["approved_hash"], "request_id": payload["request_id"], "package_id": payload["package_id"],
               "render_binding": payload["render_binding"],
               "public_commit": os.environ["GITHUB_SHA"], "run_id": int(os.environ["GITHUB_RUN_ID"]), "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
               "master_sha256": payload["master"]["sha256"], "master_bytes": payload["master"]["bytes"], "master_artifact": payload["master"]["artifact"],
               "native_exit_code": result.returncode, "no_video": False, "runtime_pins": runtime, "report_canonical_sha256": digest(report),
               "verified_inputs": verified, "host": "GitHub Actions Ubuntu", "media_published": False,
               "post_audit_inputs_verified": True, "post_audit_master_sha256": payload["master"]["sha256"],
               "editorial_review": "OPEN", "release_approval": "NOT_GRANTED", "runtime": {"python": platform.python_version(), "image_os": os.environ.get("ImageOS"), "image_version": os.environ.get("ImageVersion"), "numpy": __import__("numpy").__version__, "ffmpeg_package": subprocess.check_output(["dpkg-query", "-W", "-f=${Version}", "ffmpeg"], text=True), "ffmpeg": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0], "ffprobe": subprocess.check_output(["ffprobe", "-version"], text=True).splitlines()[0]}}
    (output / "RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    need({p.name for p in output.iterdir()} == {"audit.json", "RECEIPT.json"}, "only JSON results may cross the artifact boundary")
    print("native sound audit " + report["status"] + "; JSON-only result; review/approval open")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--private-root", type=Path)
    ap.add_argument("--work", type=Path)
    ap.add_argument("--output", type=Path)
    a = ap.parse_args()
    payload = json.loads(os.environ["SOUND_PAYLOAD"])
    base, _ = verify_payload(payload)
    if a.preflight:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("private_commit=" + payload["private_commit"] + "\n")
            f.write("private_prefix=" + base + "\n")
        return
    need(a.private_root is not None and a.work is not None and a.output is not None, "hosted run requires all isolated paths")
    run_native(payload, a.private_root, a.work, a.output)


if __name__ == "__main__":
    main()
