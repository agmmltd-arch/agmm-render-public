#!/usr/bin/env python3
"""Existing build_short/mix2 → existing short_cloud_dispatch release owner.

Ubuntu only. Exact current protected inputs, real queue writer and storyboard
approval are mandatory. This packages source/mix; it cannot approve or publish
content. The original renderer is dispatched later by the original native owner.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from voice_effects import host
from voice_hosted import HERE, NATIVE, BASE, PUBLIC, PRIVATE, clean, digest, file_sha, need, call, gh, source_closure
from stage_hosted_voice import hydrate

SCHEMA = "agmm-native-hosted-short-build-v1"


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


def preflight(request):
    host()
    source_closure()
    need(os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "build rerun is reconciliation-only")
    need(request.get("schema") == SCHEMA and re.fullmatch(r"[SC][0-9]{2,3}", request.get("id", "")), "invalid build identity")
    need(re.fullmatch(r"[0-9a-f]{40}", request.get("private_commit", ""))
         and re.fullmatch(r"[0-9a-f]{40}", request.get("manifest_blob", "")), "immutable protected build coordinates required")
    prefix = clean(request["private_prefix"])
    need(prefix.startswith("native-short-build-inputs/") and len(Path(prefix).parts) == 2, "foreign build namespace")
    need(request["manifest_path"] == prefix + "/MANIFEST.json", "build manifest outside protected namespace")
    base_intent = "build-" + request["id"] + "-" + request["input_binding_sha256"]
    retry = request.get("prior_no_effect")
    need(request["intent"] == base_intent + ("-after-" + str(retry["run_id"]) if retry else ""), "noncanonical build intent")
    need(request.get("owner") and request["owner"]["kind"] == "native-queue-claim"
         and request["owner"]["writer"] and re.fullmatch(r"[0-9a-f]{64}", request["approved_hash"]),
         "genuine native writer and approved source required")
    current = gh("repos/%s/actions/runs/%s" % (PUBLIC, os.environ["GITHUB_RUN_ID"]))
    candidate_workflow = ".github/workflows/native-build-encrypted-candidate.yml"
    need(current["path"].split("@", 1)[0] == candidate_workflow
         and current["head_sha"] == os.environ["GITHUB_SHA"]
         and current["display_title"] == "AGMM native build " + request["intent"], "foreign builder producer")
    # No retry is admitted until this encrypted workflow has its own qualified
    # no-effect proof. Check both the old and new producer to prevent overlap.
    need(not retry, "encrypted build retry requires qualified reconciliation")
    for workflow in ("agmm-short-native-build.yml", "native-build-encrypted-candidate.yml"):
        page = 1
        while True:
            runs = gh("repos/%s/actions/workflows/%s/runs?per_page=100&page=%d" % (PUBLIC, workflow, page))["workflow_runs"]
            need(not any(str(r["id"]) != os.environ["GITHUB_RUN_ID"] and
                         r.get("display_title", "").startswith("AGMM native build " + base_intent) for r in runs),
                 "prior build requires explicit reconciliation")
            if len(runs) < 100:
                break
            page += 1
    return prefix


def stage_inputs(request, private_root):
    need(call("git", "rev-parse", "HEAD", cwd=private_root).strip() == request["private_commit"], "build private commit changed")
    raw = (private_root / request["manifest_path"]).read_bytes()
    need(hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == request["manifest_blob"], "build manifest changed")
    manifest = json.loads(raw)
    identity = {k: v for k, v in request.items() if k not in ("private_commit", "private_prefix", "manifest_path", "manifest_blob")}
    need(manifest["request_identity"] == identity, "private build request differs")
    rows = manifest["files"]
    need(len({r["runtime_path"] for r in rows}) == len(rows), "duplicate build input paths")
    need(digest({r["runtime_path"]: {k: r.get(k) for k in ("git_blob_sha", "bytes", "native_stat")} for r in rows}) == request["input_binding_sha256"],
         "build input identity differs")
    prefix = request["private_prefix"] + "/"
    tree = {}
    for line in call("git", "ls-tree", "-r", "-l", "HEAD", "--", prefix, cwd=private_root).splitlines():
        meta, name = line.split("\t", 1)
        mode, kind, blob, size = meta.split()
        tree[name] = (mode, kind, blob, int(size))
    need(set(tree) == {request["manifest_path"]} | {prefix + r["runtime_path"] for r in rows}, "build input tree incomplete/foreign")
    need(not BASE.exists() and not (Path.home() / "alfred").exists(), "builder sandbox already owned")
    shutil.copytree(NATIVE, BASE)
    (Path.home() / "alfred").symlink_to(BASE.parents[2], target_is_directory=True)
    verified = []
    for row in rows:
        rel = clean(row["runtime_path"])
        need(tree[prefix + rel] == ("100644", "blob", row["git_blob_sha"], row["bytes"]), "build Git asset differs")
        need(not rel.endswith((".py", ".sh", ".env")), "protected build data cannot overwrite executable runtime")
        p = private_root / prefix / rel
        need(p.is_file() and not p.is_symlink() and p.stat().st_size == row["bytes"], "build input absent/linked/size changed")
        actual_blob = call("git", "hash-object", str(p), cwd=private_root).strip()
        need(actual_blob == row["git_blob_sha"], "build input Git body changed")
        actual = file_sha(p)  # measured ONLY here on Ubuntu, including current font bodies
        if row.get("sha256"):
            need(actual == row["sha256"], "declared build input SHA differs")
        if row.get("native_stat"):
            stat = row["native_stat"]
            need(stat["before"] == stat["after"] and stat["before"]["bytes"] == row["bytes"]
                 and stat["native_path"] == str(BASE / rel), "native uploader stat/provenance changed")
        dest = BASE / rel
        need(not dest.exists(), "protected input would overwrite pinned runtime")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
        verified.append({"runtime_path": rel, "bytes": row["bytes"], "git_blob_sha": actual_blob,
                         "sha256_ubuntu": actual, "native_stat": row.get("native_stat")})
    return manifest, verified


def compare_current_runtime_assets(verified, work):
    """Actual uploaded current bodies vs exact hosted donor, never stat==hash."""
    donor = json.loads((HERE / "builder-runtime-donor.json").read_text())
    actual = {r["runtime_path"]: r for r in verified}
    rows = [r for r in donor["files"] if r["runtime_path"] in actual]
    need(len(rows) == len(donor["files"]), "current native fonts/textures are incomplete")
    release = gh("repos/%s/releases/tags/%s" % (PUBLIC, donor["release"]))
    asset = next(a for a in release["assets"] if a["id"] == donor["asset_id"])
    need(asset.get("digest") == "sha256:" + donor["sha256"], "runtime donor provider digest differs")
    work.mkdir(parents=True, exist_ok=True)
    archive = work / "runtime-donor.tar.gz"
    with archive.open("xb") as stream:
        subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream", "repos/%s/releases/assets/%s" % (PUBLIC, asset["id"])],
                       stdout=stream, stderr=subprocess.PIPE, check=True)
    need(file_sha(archive) == donor["sha256"], "runtime donor body differs")
    compared = []
    with tarfile.open(archive) as tar:
        members = {}
        for member in tar.getmembers():
            name = member.name.removeprefix("./")
            if name in ("", "."):
                continue
            clean(name)
            need(name not in members and (member.isfile() or member.isdir()), "runtime donor linked/duplicate/special member")
            members[name] = member
        for row in rows:
            member = members[row["package_path"]]
            need(member.isfile(), "runtime donor font/texture not a file")
            raw = tar.extractfile(member).read()
            sha = hashlib.sha256(raw).hexdigest()
            need(sha == row["sha256"], "runtime donor inner bytes differ")
            compared.append({"runtime_path": row["runtime_path"], "donor_sha256": sha,
                             "current_sha256_ubuntu": actual[row["runtime_path"]]["sha256_ubuntu"],
                             "equal": sha == actual[row["runtime_path"]]["sha256_ubuntu"],
                             "body_used": "EXACT_CURRENT_PROTECTED_NATIVE_INPUT"})
    return compared


def validate_owner(request):
    sid = request["id"]
    queue = json.loads((BASE / "kit/registry/queue.json").read_text())
    claim = queue.get(sid) or {}
    need(claim.get("state") == "claimed" and claim.get("writer") == request["owner"]["writer"]
         and claim == request["owner"]["entry"], "foreign/stale native queue owner")
    need(not os.environ.get("AGMM_SKIP_STORYBOARD") and not os.environ.get("AGMM_REVIEWER"), "review bypass flags refused")
    produce = module(BASE / "kit/storyboard_guard.py", "native_short_storyboard_guard")
    produce.storyboard_guard(sid)  # unchanged reviewer + same-source guard, no bypass flags
    dispatch = module(BASE / "crew/short_cloud_dispatch.py", "native_short_dispatch")
    source = dispatch._spec_hash(BASE / "kit/specs" / sid, skip_archives=True)
    legacy = dispatch._spec_hash(BASE / "kit/specs" / sid, skip_archives=False)
    need(request["approved_hash"] in (source, legacy), "approved build source changed")
    spec = json.loads((BASE / "kit/specs" / sid / "spec.json").read_text())
    need(spec["id"] == sid and (spec.get("music") or {}).get("engine", "mix2") == "mix2", "wrong id or non-current mix owner")
    need(spec["voice"]["wav"] in ("shorts/voice/%s/%s.wav" % (sid, sid), str(BASE / "shorts/voice" / sid / (sid + ".wav")))
         and spec["voice"]["words"] in ("shorts/voice/%s/%s.words.json" % (sid, sid), str(BASE / "shorts/voice" / sid / (sid + ".words.json"))),
         "builder voice path differs")
    for key, image in spec.get("images", {}).items():
        if image.get("src"):
            p = Path(image["src"])
            p = p if p.is_absolute() else BASE / p
            need(p.is_relative_to(BASE) and p.is_file(), "approved source image missing")
        else:
            receipt = BASE / "kit/out" / sid / "images" / (key + ".receipt.json")
            final = BASE / "kit/out" / sid / "img" / (key + (".png" if image.get("cutout") else ".jpg"))
            need(receipt.is_file() and final.is_file() and json.loads(receipt.read_text()).get("spec_hash") ==
                 hashlib.sha256(json.dumps(image, sort_keys=True).encode()).hexdigest()[:16],
                 "image requires real production; no model/provider fallback in package job")
    return dispatch


def run(request, private_root, voice_private_root, work, output):
    preflight(request)
    manifest, verified = stage_inputs(request, private_root)
    comparisons = compare_current_runtime_assets(verified, work / "runtime-donor")
    sid = request["id"]
    if request.get("voice_pointer"):
        hydrate(request["voice_pointer"], request["voice_request"], voice_private_root, work / "voice-hydration", BASE)
    prepare = module(BASE / "shorts/voice/tooling/prepare.py", "builder_prepare")
    sys.path.insert(0, str(BASE / "shorts/voice/tooling"))
    need(not prepare.voicelead_prerequisite_issues(str(BASE / "shorts/voice"), sid), "builder voice is incomplete/unqualified")
    lead = json.loads((BASE / "shorts/voice" / sid / (sid + ".voicelead.json")).read_text())
    need(lead["verdict"] == "PASS", "builder voicelead not PASS")
    dispatch = validate_owner(request)
    environment = os.environ.copy()
    environment.update(AGMM_BUILD_CHILD="1", AGMM_BUILD_ROOT=str(BASE), FLEET_FREE_ONLY="1",
                       PYTHONPATH=str(HERE / "voice-site") + os.pathsep + str(HERE))
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK", "AGMM_VOICE_MISTRAL_KEY", "AGMM_VOICE_GEMINI_FREE_KEY", "AGMM_SKIP_STORYBOARD", "AGMM_REVIEWER", "VOICEFREE_PASS"):
        environment.pop(key, None)
    output.mkdir(parents=True, exist_ok=False)
    run = subprocess.run([sys.executable, str(BASE / "kit/build_short.py"), str(BASE / "kit/specs" / sid / "spec.json")],
                         env=environment, capture_output=True, text=True)
    (output / "build.log").write_text(run.stdout + run.stderr)
    need(run.returncode == 0, "unchanged native build_short failed; no release/render")
    validate_owner(request)
    exact = dispatch.exact_request(sid, root=BASE)
    config = dispatch._config(BASE / "crew/short-cloud-dispatch.json")
    need(config["enabled"], "original native dispatch configuration is disabled")
    for p in (BASE / "kit/out" / sid / "BUILD.json", BASE / "kit/out" / sid / "build/parts.json"):
        shutil.copyfile(p, output / p.name)
    receipt = {"schema": SCHEMA, "id": sid, "intent": request["intent"], "request_sha256": digest(request),
               "status": "NATIVE_PACKAGE_BUILT_NOT_SEALED", "runtime_commit": os.environ["GITHUB_SHA"],
               "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
               "owner": request["owner"], "approved_hash": request["approved_hash"], "exact_request": exact,
               "verified_inputs": verified, "runtime_asset_comparisons": comparisons,
               "render_dispatched": False, "release_approved": False, "content_posted": False}
    (output / "PACKAGE-RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")


def seal(request, output):
    host()
    source_closure()
    need(os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "package seal rerun refused")
    receipt_path = output / "PACKAGE-RECEIPT.json"
    receipt = json.loads(receipt_path.read_text())
    need(receipt["request_sha256"] == digest(request) and receipt["status"] == "NATIVE_PACKAGE_BUILT_NOT_SEALED",
         "stale/incomplete native build receipt")
    dispatch = validate_owner(request)
    exact = dispatch.exact_request(request["id"], root=BASE)
    need(exact == receipt["exact_request"], "package/source changed before seal")
    config = dispatch._config(BASE / "crew/short-cloud-dispatch.json")
    need(config["enabled"], "native dispatch configuration disabled")
    # Durable in-job phase before the release mutation. The Actions run is the
    # outer durable intent; a lost seal result is reconciled, never replayed.
    receipt["status"] = "RELEASE_EFFECT_UNKNOWN"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    # Reuse the release owner, but refuse any clobber/repair of an existing object.
    def release_runner(command):
        need("--clobber" not in command and "delete" not in command, "existing release differs; never replace")
        return subprocess.run(command, capture_output=True, text=True, timeout=300)
    release = dispatch._release(release_runner, config, exact)
    provider = gh("repos/%s/releases/tags/%s" % (PUBLIC, exact["workflow_inputs"]["release"]))
    assets = {a["name"]: a for a in provider["assets"]}
    for name, key in (("source.tar.gz", "source"), ("parts.json", "parts"), ("mix.wav", "mix")):
        need(assets[name]["size"] == exact["inputs"][key]["bytes"]
             and assets[name].get("digest") == "sha256:" + exact["inputs"][key]["sha256"], "sealed package provider binding differs")
    receipt.update(status="NATIVE_PACKAGE_SEALED_RENDER_NOT_DISPATCHED", release=provider)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", type=Path, required=True)
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--seal", action="store_true")
    ap.add_argument("--private-root", type=Path)
    ap.add_argument("--voice-private-root", type=Path)
    ap.add_argument("--work", type=Path)
    ap.add_argument("--output", type=Path)
    a = ap.parse_args()
    r = json.loads(a.request.read_text())
    if a.preflight:
        prefix = preflight(r)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write("private_commit=%s\nprivate_prefix=%s\n" % (r["private_commit"], prefix))
            if r.get("voice_request"):
                v = r["voice_request"]
                stream.write("voice_private_commit=%s\nvoice_private_prefix=%s\n" % (v["private_commit"], v["private_prefix"]))
    elif a.seal:
        seal(r, a.output)
    else:
        run(r, a.private_root, a.voice_private_root, a.work, a.output)


if __name__ == "__main__":
    main()
