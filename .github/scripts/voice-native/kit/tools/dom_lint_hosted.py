#!/usr/bin/env python3
"""Metadata/source-only client for the native Ubuntu DOM lint of existing inputs.

Never open, package, hash, download or decode programme media on this host.
The Actions artifact contains exactly three JSON files. Rule evaluation, including
source-image pixels and package fingerprinting, is entirely on Ubuntu.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import posixpath
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
REPO = "agmmltd-arch/agmm-render-public"
WORKFLOW = "agmm-short-domlint.yml"
BRANCH = '    if "--hosted-request" in sys.argv:\n        import dom_lint_hosted\n        sys.exit(dom_lint_hosted.main())\n'


class Refused(RuntimeError):
    pass


def need(ok, why):
    if not ok:
        raise Refused(why)


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return digest_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def stat_tree(root):
    """Detect drift using filesystem metadata only; never open any package/media file."""
    rows = []
    need(root.is_dir() and not root.is_symlink(), "current build/pkg is absent or linked")
    for path in sorted(root.rglob("*")):
        s = path.lstat()
        need(not stat.S_ISLNK(s.st_mode) and (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)), "package contains a link/special file")
        rows.append([path.relative_to(root).as_posix(), s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino, s.st_mode])
    need(rows, "current build/pkg is empty")
    return rows


def snapshot(v2, sid, request_path, target, runtime_commit):
    need(re.fullmatch(r"[SCP][0-9]{2,3}", sid), "invalid short ID")
    need(re.fullmatch(r"[0-9a-f]{40}", runtime_commit or ""), "explicit immutable hosted runtime commit required")
    kit = v2 / "kit"
    out = kit / "out" / sid
    reqpath = request_path.resolve()
    need((out / "cloud-dispatch").resolve() in reqpath.parents and reqpath.name == "REQUEST.json", "use the native existing render REQUEST.json")
    raw_req = reqpath.read_bytes()  # JSON metadata only
    req = json.loads(raw_req)
    need(req.get("kind") == "agmm_short_cloud_dispatch_request" and req.get("schema") == 1 and req.get("id") == sid, "not this short's native render REQUEST")
    need(req.get("workflow", {}).get("repository") == REPO and req.get("workflow", {}).get("workflow") == "agmm-short-package.yml", "unapproved hosted render route")
    wi, inputs = req["workflow_inputs"], req["inputs"]
    binding = {}
    for key in ("source", "parts", "mix"):
        item = inputs[key]
        need(re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", "")) and wi.get(key + "_sha256") == item["sha256"], "native input hash binding mismatch")
        need(type(item.get("bytes")) is int and item["bytes"] > 0, "invalid native input byte count")
        binding[key + "_sha256"] = item["sha256"]
    need(req["package_id"] == digest(binding), "native render package_id mismatch")
    need(req["request_id"] == digest(dict(binding, approved_hash=req["approval"]["approved_hash"], render_4k=wi["render_4k"], workers=wi["workers"])), "native render request_id mismatch")
    need(wi["release"] == "short-%s-%s" % (sid.lower(), req["package_id"]), "native render release mismatch")
    platforms = module(kit / "platforms" / "platforms.py", "domlint_hosted_platforms")
    prof = platforms.profile(target)
    route = platforms.routed_platform(sid)
    need(platforms.resolve(route or "instagram") == prof["key"], "explicit target differs from canonical native routing (strict Instagram for unrouted shorts)")
    approval = read_json(kit / "registry" / "storyboards" / (sid + ".json"))
    approver = approval.get("by", "")
    need(approval.get("state") == "approved" and re.fullmatch(r"root|claude-root|sonnet-[a-z0-9._-]+|opus-[a-z0-9._-]+", approver, re.I)
         and not re.search(r"(?<![a-z])(hound|forge|marshal|scout|baton|brain|clef|jev)(?![a-z])", approver, re.I), "known independent native storyboard approval required")
    queue = read_json(kit / "registry" / "queue.json")
    need(approver.lower() != str((queue.get(sid) or {}).get("writer", "")).lower(), "native maker cannot approve this storyboard")
    dispatcher = module(v2 / "crew" / "short_cloud_dispatch.py", "domlint_hosted_dispatch")
    current = dispatcher._spec_hash(kit / "specs" / sid, skip_archives=True)  # exact native source-code hash; no raster/audio/archive IO
    need(current == approval.get("approved_hash") == req["approval"].get("approved_hash") == req["approval"].get("current_hash"), "current source/approval differs from the native render REQUEST")
    partpath = out / "build" / "parts.json"
    partbytes = partpath.read_bytes()  # JSON metadata only
    need(digest_bytes(partbytes) == inputs["parts"]["sha256"], "current parts.json changed since render REQUEST")
    parts = json.loads(partbytes)
    build = read_json(out / "BUILD.json")
    need(parts.get("sha256") == inputs["source"]["sha256"] and parts.get("bytes") == inputs["source"]["bytes"], "current parts source binding changed")
    need(build.get("id") == sid and build.get("package_sha256") == inputs["source"]["sha256"] and build.get("parts") == parts["parts"], "current BUILD.json no longer names the render package")
    for key, path in (("source", out / "build" / "source.tar.gz"), ("mix", out / "audio" / "mix.wav")):
        need(path.is_file() and not path.is_symlink() and path.stat().st_size == inputs[key]["bytes"], "current %s file metadata changed" % key)
    resolved = read_json(out / "resolved.json")
    beats = [float(b["from"]) for b in resolved["beats"]]
    exceptions = out / "lint-exceptions.json"
    allow = [re.sub(r"\s+", " ", t.get("text", "")).strip().lower() for t in (read_json(exceptions).get("lint", []) if exceptions.exists() else []) if t.get("text")]
    pins = read_json(HERE / "dom_lint_hosted_pins.json")
    for origin, remote in (("kit/tools/dom_lint.py", "domlint-native/kit/tools/dom_lint.py"), ("qa/gate.py", "domlint-native/qa/gate.py"), ("kit/platforms/platforms.py", "domlint-native/kit/platforms/platforms.py"), ("kit/platforms/frames.json", "domlint-native/kit/platforms/frames.json"), ("kit/tools/dom_lint_runner.mjs", "dom_lint_runner.mjs"), ("kit/platforms/universal.py", "domlint-native/kit/platforms/universal.py"), ("kit/platforms/universal.json", "domlint-native/kit/platforms/universal.json")):
        source = (v2 / origin).read_bytes()
        if origin.endswith("dom_lint.py"):
            source = source.replace(BRANCH.encode(), b"", 1)
        need(digest_bytes(source) == pins[remote], "native lint runtime source differs from the published closure: " + origin)
    # Drop local paths from the public dispatch. Preserve native cryptographic IDs.
    clean = dict(req, inputs={key: {k: item[k] for k in ("sha256", "bytes")} for key, item in inputs.items()})
    uni = module(kit / "platforms" / "universal.py", "domlint_hosted_universal")      # 19 Oct 2026: the universal safe-zone rule's level is decided here (queue.json), not on the runner
    payload = {"schema": 1, "render_request": clean, "request_sha256": digest_bytes(raw_req), "target": prof["key"], "runtime_commit": runtime_commit,
               "every": 0.1, "beat_starts": beats, "allow_lint": allow, "universal_level": uni.level(sid)}
    routing = read_json(v2 / "jev-v2" / "fit" / "routing.json")
    override = (routing.get("manual_overrides") or {}).get(sid) or {}
    routing_fingerprint = digest_bytes(json.dumps({"assignment": (routing.get("assignment") or {}).get(sid), "manual_override": override}, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) if override.get("class") == "assign-unrouted" else None
    textpaths = [reqpath, partpath, out / "BUILD.json", out / "resolved.json", kit / "registry" / "storyboards" / (sid + ".json")]
    if exceptions.exists():
        textpaths.append(exceptions)
    guard = {"payload": payload, "source_hash": current, "metadata_sha256": {str(p): digest_bytes(p.read_bytes()) for p in textpaths}, "package_stat": stat_tree(out / "build" / "pkg"),
             "media_stat": {key: [(out / sub).stat().st_ino, (out / sub).stat().st_size, (out / sub).stat().st_mtime_ns, (out / sub).stat().st_ctime_ns] for key, sub in (("source", "build/source.tar.gz"), ("mix", "audio/mix.wav"))}, "native_sources": pins, "routing_fingerprint": routing_fingerprint,
             "routing_identity": {"assignment": (routing.get("assignment") or {}).get(sid), "manual_override": override},
             "maker_identity": {k: (queue.get(sid) or {}).get(k) for k in ("writer", "at")}}
    return payload, guard


def verify_result(payload, pins, report, raw, receipt, run_id):
    req = payload["render_request"]
    expected = {"schema": 1, "kind": "agmm_hosted_native_domlint", "id": req["id"], "target": payload["target"], "runtime_commit": payload["runtime_commit"],
                "run_id": str(run_id), "request_id": req["request_id"], "request_sha256": payload["request_sha256"], "release": req["workflow_inputs"]["release"],
                "source_sha256": req["inputs"]["source"]["sha256"], "parts_sha256": req["inputs"]["parts"]["sha256"], "approved_hash": req["approval"]["approved_hash"], "repository": REPO,
                "native_sources": pins, "step": 0.1, "image_checks": "native image_text_height + card_items + image legibility; no omission"}
    for key, value in expected.items():
        need(receipt.get(key) == value, "hosted receipt mismatch: " + key)
    need(re.fullmatch(r"[0-9a-f]{64}", receipt.get("pkg_fingerprint", "")) and type(receipt.get("pkg_files")) is int and receipt["pkg_files"] > 0, "hosted package fingerprint is absent")
    need(type(receipt.get("image_files_checked")) is int and receipt["image_files_checked"] >= 0, "native image checks were omitted")
    need(report.get("id") == req["id"] and report.get("platform") == payload["target"] and report.get("step") == 0.1, "native report target mismatch")
    stats = report.get("stats") or {}
    need(stats.get("samples") == receipt.get("samples") and stats.get("cut_frames") == receipt.get("cut_frames") and stats.get("samples", 0) > 0 and stats.get("cut_frames") == len(payload["beat_starts"]), "native report sample/cut coverage mismatch")
    need(stats.get("FAIL") == receipt.get("FAIL") == sum(f.get("sev") == "FAIL" for f in report["findings"]), "native FAIL count mismatch")
    need(stats.get("WARN") == receipt.get("WARN") == sum(f.get("sev") == "WARN" for f in report["findings"]), "native WARN count mismatch")
    need(sum(len(d["samples"]) for d in raw["parts"].values()) == stats["samples"] and all("imgs" in s for d in raw["parts"].values() for s in d["samples"]), "native raw JSON omits samples/image facts")
    images = {posixpath.normpath(d["look"] + "/" + unquote(urlsplit(im["src"]).path)) for d in raw["parts"].values() for s in d["samples"] for im in s["imgs"]}
    vectors = sorted(i for i in images if i.lower().endswith(".svg"))
    need(receipt["image_files_checked"] == len(images) and receipt.get("image_files_decoded") == len(images) - len(vectors)
         and receipt.get("native_svg_blind_spots") == vectors, "native image pixel checks were omitted")


def guard_without_runtime(guard):
    """A new main commit alone is never a new production-input attempt."""
    if not isinstance(guard.get("payload"), dict):
        return guard
    return dict(guard, payload={k: v for k, v in guard["payload"].items() if k != "runtime_commit"})


def run_existing(v2, sid, request_path, target, runtime_commit, timeout=1500):
    v2, request_path = Path(v2), Path(request_path)
    payload, before = snapshot(v2, sid, request_path, target, runtime_commit)
    # Keep the existing authenticated native wrapper; no credential lookup/copy here.
    snap = module(v2 / "kit" / "tools" / "snap.py", "domlint_hosted_snap")
    gh = snap._gh
    intent_root = v2 / "kit" / "out" / sid / "domlint" / "hosted"
    intent_dir = intent_root / digest({"payload": payload, "pins": before["native_sources"]})
    intent_path = intent_dir / "INTENT.json"
    prior = []
    for path in sorted(intent_root.glob("*/INTENT.json")):
        saved = read_json(path)
        if saved.get("dispatch_attempted") and guard_without_runtime(saved.get("guard", {})) == guard_without_runtime(before):
            prior.append((path, saved))
    need(len(prior) <= 1, "multiple existing hosted dispatch intents match current inputs; reconcile them before any new attempt")
    if prior:
        intent_path, intent = prior[0]
        intent_dir = intent_path.parent
        old_runtime = intent["guard"].get("payload", payload).get("runtime_commit")
        need(re.fullmatch(r"[0-9a-f]{40}", old_runtime or ""), "existing intent lacks an immutable runtime commit")
        if old_runtime != runtime_commit:
            runtime_commit = old_runtime
            payload, before = snapshot(v2, sid, request_path, target, runtime_commit)
        need(intent["guard"] == before, "source metadata changed since the existing hosted dispatch intent; no duplicate dispatch")
    elif intent_path.exists():
        intent = read_json(intent_path)
        need(intent["guard"] == before, "source metadata changed since the existing hosted dispatch intent; no duplicate dispatch")
    else:
        intent = {"label": "%s-dl-existing-%s-%d-%d" % (sid, payload["render_request"]["request_id"][:8], int(time.time()), os.getpid()), "guard": before, "dispatch_attempted": False}
    # An attempted intent may only resume its own exact, still-reviewed closure.
    # New attempts continue to require independently reviewed current main.
    resolve_runtime_commit(v2, runtime_commit, gh, resume_intent=bool(intent["dispatch_attempted"]))
    intent_dir.mkdir(parents=True, exist_ok=True)
    label = intent["label"]
    args = ["workflow", "run", WORKFLOW, "-R", REPO, "--ref", "main", "-f", "release=" + payload["render_request"]["workflow_inputs"]["release"], "-f", "source_sha256=" + payload["render_request"]["inputs"]["source"]["sha256"], "-f", "tag=" + label, "-f", "plan=[]", "-f", "profile={}", "-f", "existing_request=" + json.dumps(payload, separators=(",", ":"))]
    run_id = intent.get("run_id")
    if not intent["dispatch_attempted"]:
        intent["dispatch_attempted"] = True
        temporary = intent_path.with_suffix(".tmp"); temporary.write_text(json.dumps(intent, indent=1) + "\n"); os.replace(temporary, intent_path)
        dispatched = gh(args)
        match = re.search(r"/actions/runs/(\d+)", (dispatched.stdout or "") + (dispatched.stderr or ""))
        run_id = match.group(1) if match else None
        if run_id is not None:
            intent["run_id"] = run_id
            temporary = intent_path.with_suffix(".tmp"); temporary.write_text(json.dumps(intent, indent=1) + "\n"); os.replace(temporary, intent_path)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(15)  # all Actions queries/retries respect the shared provider pacing
        if run_id is None:
            rows = json.loads(gh(["run", "list", "-R", REPO, "--workflow", WORKFLOW, "--event", "workflow_dispatch", "--limit", "30", "--json", "databaseId,displayTitle"]).stdout)
            matches = [r for r in rows if r["displayTitle"] == "AGMM short DOM lint " + label]
            if matches:
                run_id = str(matches[0]["databaseId"])
                intent["run_id"] = run_id
                temporary = intent_path.with_suffix(".tmp"); temporary.write_text(json.dumps(intent, indent=1) + "\n"); os.replace(temporary, intent_path)
            continue
        run = json.loads(gh(["run", "view", run_id, "-R", REPO, "--json", "status,conclusion,headSha,event,createdAt,startedAt,updatedAt,url"]).stdout)
        need(run["headSha"] == runtime_commit and run["event"] == "workflow_dispatch", "wrong hosted workflow/runtime")
        if run["status"] == "completed":
            need(run["conclusion"] == "success", "hosted native lint tool failed: run " + run_id)
            break
    else:
        raise Refused("hosted lint wait expired; run is left intact, no cancellation or duplicate dispatch: " + str(run_id))
    with tempfile.TemporaryDirectory(prefix="agmm-domlint-json-") as tmp:
        gh(["run", "download", run_id, "-R", REPO, "-n", label + "-DOMLINT", "-D", tmp], timeout=300)
        files = sorted(p.name for p in Path(tmp).iterdir())
        need(files == ["RECEIPT.json", "raw.json", "result.json"] and all(p.is_file() and not p.is_symlink() for p in Path(tmp).iterdir()), "hosted artifact must contain only the three JSON outputs")
        data = {p.name: p.read_bytes() for p in Path(tmp).iterdir()}
    report, raw, receipt = (json.loads(data[name]) for name in ("result.json", "raw.json", "RECEIPT.json"))
    need(digest_bytes(data["result.json"]) == receipt["result_sha256"] and digest_bytes(data["raw.json"]) == receipt["raw_sha256"], "hosted JSON output bytes changed")
    verify_result(payload, before["native_sources"], report, raw, receipt, run_id)
    _, after = snapshot(v2, sid, request_path, target, runtime_commit)
    need(before == after, "source/approval/routing/package metadata changed while hosted lint ran; result not bound")
    return {"result": report, "raw": raw, "receipt": receipt, "guard": before, "bytes": data, "run": run}


def resolve_runtime_commit(v2, requested=None, gh=None, resume_intent=False):
    """Verify publication by git-blob metadata only; no remote source/media download."""
    if gh is None:
        gh = module(Path(v2) / "kit/tools/snap.py", "domlint_hosted_snap")._gh
    head = json.loads(gh(["api", "repos/%s/commits/main" % REPO]).stdout)["sha"]
    commit = requested or head
    need(re.fullmatch(r"[0-9a-f]{40}", commit or ""), "invalid immutable public runtime commit")
    need(requested is None or requested == head or resume_intent, "public main moved from the independently reviewed runtime commit")
    tree = json.loads(gh(["api", "repos/%s/git/trees/%s?recursive=1" % (REPO, commit)]).stdout)
    need(not tree.get("truncated"), "public runtime source tree metadata was truncated")
    blobs = {item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "blob"}
    wanted = read_json(HERE / "dom_lint_hosted_publication.json")
    need(all(blobs.get(path) == value["git_blob_sha"] for path, value in wanted.items()), "reviewed hosted workflow/source closure has not been published exactly; no Mac fallback")
    return commit


def prepare_existing(ctx, sid, timeout=1500):
    """Safe normal prepare owner path, selected from existing JSON metadata only."""
    try:
        v2 = Path(ctx.v2); kit = v2 / "kit"; out = Path(ctx.out(sid))
        partbytes = (out / "build/parts.json").read_bytes()
        parts = json.loads(partbytes)
        build = read_json(out / "BUILD.json")
        approval = read_json(kit / "registry/storyboards" / (sid + ".json"))
        need(build.get("id") == sid and build.get("package_sha256") == parts.get("sha256") and build.get("parts") == parts.get("parts"), "current BUILD/parts source metadata disagree")
        found = []
        for path in sorted((out / "cloud-dispatch").glob("*/REQUEST.json")):
            req = read_json(path)
            inputs = req.get("inputs") or {}
            if req.get("id") == sid and (inputs.get("source") or {}).get("sha256") == parts.get("sha256") and (inputs.get("parts") or {}).get("sha256") == digest_bytes(partbytes) and (req.get("approval") or {}).get("approved_hash") == approval.get("approved_hash"):
                found.append(path)
        need(len(found) == 1, "expected one native existing render REQUEST matching current source/parts/approval; found %d; use the explicit owner command to resolve ambiguity" % len(found))
        platforms = module(kit / "platforms/platforms.py", "domlint_hosted_platforms")
        target = (platforms.for_short(sid) or platforms.profile("instagram"))["key"]
        dest = out / "domlint"
        if all((dest / name).is_file() for name in ("BOUND.json", "HOSTED-RECEIPT.json", "result.json", "raw.json")):
            bound = read_json(dest / "BOUND.json")
            if bound.get("binding_kind") == "hosted-existing-render-inputs":
                receipt = read_json(dest / "HOSTED-RECEIPT.json")
                p, guard = snapshot(v2, sid, found[0], target, receipt["runtime_commit"])
                if bound.get("source_guard_sha256") == digest(guard):
                    report = read_json(dest / "result.json"); raw = read_json(dest / "raw.json")
                    verify_result(p, guard["native_sources"], report, raw, receipt, receipt["run_id"])
                    need(bound.get("result_sha256") == receipt["result_sha256"] == digest_bytes((dest / "result.json").read_bytes()) and receipt["raw_sha256"] == digest_bytes((dest / "raw.json").read_bytes()), "cached hosted native report bytes changed")
                    need(bound.get("hosted_receipt_sha256") == digest_bytes((dest / "HOSTED-RECEIPT.json").read_bytes()), "cached hosted receipt bytes changed")
                    return (1 if receipt["FAIL"] else 0), "existing native hosted report run %s still bound (%d FAIL); no new dispatch" % (receipt["run_id"], receipt["FAIL"])
        runtime = resolve_runtime_commit(v2)
        return bind_existing(ctx, sid, str(found[0]), target, runtime, timeout)
    except (Refused, OSError, ValueError, KeyError, RuntimeError) as error:
        return 2, "hosted DOM prepare refused: " + str(error)


def bind_existing(ctx, sid, request_path, target, runtime_commit, timeout=1500):
    """Called by the qa.machine_pass owner; seals real native bytes, BOUND last."""
    if not re.fullmatch(r"[SCP][0-9]{2,3}", sid):
        return 2, "hosted DOM lint refused: invalid short ID"
    dest = Path(ctx.out(sid)) / "domlint"
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with (dest / ".hosted.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            data = run_existing(ctx.v2, sid, request_path, target, runtime_commit, timeout)
            receipt = data["receipt"]
            rc = 1 if receipt["FAIL"] else 0
            bound = {"id": sid, "pkg_fingerprint": receipt["pkg_fingerprint"], "pkg_files": receipt["pkg_files"], "result_sha256": receipt["result_sha256"], "fails": receipt["FAIL"], "warns": receipt["WARN"], "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rc": rc,
                     "by": "machine_pass.lint_and_bind", "platform": receipt["target"], "target": receipt["target"], "binding_kind": "hosted-existing-render-inputs", "hosted_receipt_sha256": digest_bytes(data["bytes"]["RECEIPT.json"]), "hosted_run": receipt["run_id"], "runtime_commit": receipt["runtime_commit"],
                     "source_sha256": receipt["source_sha256"], "parts_sha256": receipt["parts_sha256"], "approved_hash": receipt["approved_hash"], "request_id": receipt["request_id"], "routing_fingerprint": data["guard"]["routing_fingerprint"], "source_guard_sha256": digest(data["guard"]),
                     "hosted_run_created_at": data["run"].get("createdAt"), "hosted_run_started_at": data["run"].get("startedAt"), "hosted_run_updated_at": data["run"].get("updatedAt")}
            # Preserve prior source JSON evidence; do not overwrite an earlier receipt silently.
            archive = dest / ("history-%s-%d" % (time.strftime("%Y%m%d-%H%M%S"), os.getpid()))
            old = [dest / n for n in ("raw.json", "result.json", "HOSTED-RECEIPT.json", "HOSTED-RUN.json", "BOUND.json") if (dest / n).is_file()]
            if old:
                archive.mkdir()
                for path in old:
                    shutil.copyfile(path, archive / path.name)
            for name, body in dict(data["bytes"], **{"HOSTED-RECEIPT.json": data["bytes"]["RECEIPT.json"], "HOSTED-RUN.json": json.dumps(data["run"], indent=1).encode() + b"\n"}).items():
                if name == "RECEIPT.json":
                    continue
                temp = dest / (name + ".tmp-%d" % os.getpid()); temp.write_bytes(body); os.replace(temp, dest / name)
            temp = dest / ("BOUND.json.tmp-%d" % os.getpid()); temp.write_text(json.dumps(bound, indent=1) + "\n"); os.replace(temp, dest / "BOUND.json")
            return rc, "native hosted lint run %s: %d FAIL, fingerprint %s, target %s" % (receipt["run_id"], receipt["FAIL"], receipt["pkg_fingerprint"][:12], receipt["target"])
    except (Refused, OSError, ValueError, KeyError, RuntimeError) as error:
        return 2, "hosted DOM lint refused: " + str(error)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id"); ap.add_argument("--hosted-request", required=True)
    ap.add_argument("--platform", required=True); ap.add_argument("--hosted-runtime-commit", required=True)
    ap.add_argument("--v2", default=str(HERE.parents[1])); ap.add_argument("--json", required=True)
    a = ap.parse_args()
    try:
        need(re.fullmatch(r"[SCP][0-9]{2,3}", a.id), "invalid short ID")
        lockpath = Path(a.v2) / "kit/out" / a.id / "domlint/.hosted.lock"
        lockpath.parent.mkdir(parents=True, exist_ok=True)
        with lockpath.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            data = run_existing(a.v2, a.id, a.hosted_request, a.platform, a.hosted_runtime_commit)
        dest = Path(a.json); dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({k: data[k] for k in ("result", "receipt", "guard", "run")}, indent=1) + "\n")
        print("hosted native result/provenance collected: " + str(dest))
        return 1 if data["receipt"]["FAIL"] else 0
    except (Refused, OSError, ValueError, KeyError, RuntimeError) as error:
        print("TOOL ERROR: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
