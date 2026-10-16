#!/usr/bin/env python3
"""Ubuntu-only transport/layout adapter. Native evaluation/issue sources are unchanged."""
from __future__ import annotations
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from urllib.parse import unquote_plus, urlsplit, urlunsplit

HERE = Path(__file__).resolve().parent
NATIVE = HERE / "master-evaluation-native"
FROZEN = Path("/Users/samwall/alfred/builds")
PUBLIC = "agmmltd-arch/agmm-render-public"
PRIVATE = "agmmltd-arch/agmm-video-render"
SCHEMA = "agmm-hosted-native-master-evaluation-v1"


class Refused(RuntimeError): pass


def need(ok, why):
    if not ok: raise Refused(why)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def file_sha(path, blob=False):
    h = hashlib.sha1() if blob else hashlib.sha256()
    if blob: h.update(("blob %d\0" % path.stat().st_size).encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""): h.update(block)
    return h.hexdigest()


def clean(value):
    p = PurePosixPath(value)
    need(not p.is_absolute() and ".." not in p.parts and str(p) == value, "unsafe runtime path")
    return value


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=300)
    need(r.returncode == 0, "hosted GitHub read failed: " + args[0])
    return r.stdout


def host(payload):
    need(platform.system() == "Linux" and os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("AGMM_HOSTED_MASTER_EVALUATION") == "1", "full native media evaluation is Ubuntu Actions only")
    need(os.environ.get("GITHUB_REPOSITORY") == PUBLIC and os.environ.get("GITHUB_REF") == "refs/heads/main", "unapproved runtime repository/ref")
    need(payload.get("schema") == SCHEMA and payload.get("runtime_commit") == os.environ.get("GITHUB_SHA"), "immutable runtime mismatch")
    need(re.fullmatch(r"[0-9a-f]{40}", payload.get("private_commit", "")) and re.fullmatch(r"[0-9a-f]{40}", payload.get("manifest_blob", "")), "invalid protected commit/blob")
    need(re.fullmatch(r"[0-9a-f]{64}", payload.get("plan_sha256", "")), "invalid plan identity")
    base = "protected-inputs/S87/master-evaluation/" + payload["plan_sha256"] + "/"
    need(payload.get("manifest_path") == base + "INPUTS.json" and re.fullmatch(r"S87-native-eval-[a-f0-9]{20}", payload.get("tag", "")), "protected prefix or label mismatch")
    pins = json.loads((NATIVE / "PINS.json").read_text())
    for rel, value in pins.items(): need(file_sha(NATIVE / clean(rel)) == value, "unchanged native source closure mismatch: " + rel)
    wanted = {".github/scripts/master-evaluation-native/" + p for p in pins} | {".github/scripts/master-evaluation-native/PINS.json", ".github/scripts/master_evaluation_existing.py", ".github/scripts/render_short_package.py", ".github/workflows/agmm-short-master-evaluate.yml"}
    need(type(payload.get("publication")) is dict and set(payload["publication"]) == wanted, "full public runtime closure inventory is required")
    for rel, value in payload["publication"].items():
        p = HERE.parents[1] / clean(rel)
        need(file_sha(p, True) == value["git_blob_sha"], "published adapter/workflow closure changed: " + rel)
    return base, pins


def private_inputs(payload, root, pins):
    def git(*args):
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=120)
        need(r.returncode == 0, "private source metadata verification failed"); return r.stdout.strip()
    need(git("rev-parse", "HEAD") == payload["private_commit"], "private checkout commit mismatch")
    need(git("remote", "get-url", "origin") in ("git@github.com:%s.git" % PRIVATE, "https://github.com/%s.git" % PRIVATE), "wrong protected repository")
    need(not git("status", "--porcelain", "--untracked-files=no"), "private inputs changed after checkout")
    path = root / payload["manifest_path"]
    need(path.is_file() and not path.is_symlink() and file_sha(path, True) == payload["manifest_blob"], "protected manifest blob mismatch")
    manifest = json.loads(path.read_text()); plan = manifest["plan"]
    need(manifest.get("schema") == SCHEMA + "-inputs" and digest(plan) == payload["plan_sha256"], "complete plan identity mismatch")
    need(plan.get("schema") == SCHEMA and plan.get("id") == "S87" and plan.get("mode") in ("evaluate", "proposal") and plan.get("proposal_only") is True, "bounded proposal-only native route required")
    need(plan.get("v2") == str(FROZEN / "video-program-2026-09-23/v2") and plan.get("timezone") == "Europe/London", "original path/timezone contract changed")
    need(not plan.get("pending_dependencies") and plan.get("native_sources") == pins, "native dependency/closure is incomplete")
    base = str(PurePosixPath(payload["manifest_path"]).parent) + "/"
    rows = manifest["assets"]
    need(len(rows) == len(plan["assets"]) and len({r["runtime_path"] for r in rows}) == len(rows), "protected full input count/uniqueness mismatch")
    tree = {}
    for line in git("ls-tree", "-r", "-l", "--full-tree", payload["private_commit"], "--", base).splitlines():
        meta, name = line.split("\t", 1); mode, kind, blob, size = meta.split(); tree[name] = (mode, kind, blob, int(size))
    need(set(tree) == {payload["manifest_path"]} | {r["private_path"] for r in rows}, "protected input subtree contains missing/extra files")
    for planned, row in zip(plan["assets"], rows):
        need(row["runtime_path"] == planned["runtime_path"] and row["private_path"] == base + clean(row["runtime_path"]) and row["bytes"] == planned["bytes"], "native input path/size mismatch")
        need(tree.get(row["private_path"]) == ("100644", "blob", row["git_blob_sha"], row["bytes"]), "protected native Git entry mismatch")
        p = root / row["private_path"]
        need(p.is_file() and not p.is_symlink() and file_sha(p, True) == row["git_blob_sha"], "protected file bytes differ from native Git blob")
    return manifest


def restore(path, mtime_ns):
    os.utime(path, ns=(mtime_ns, mtime_ns))


def stage(manifest, private_root):
    plan = manifest["plan"]; v2 = Path(plan["v2"])
    need(not v2.exists(), "fresh isolated native v2 required; no reuse of a previous evaluation tree")
    for rel, expected in plan["native_sources"].items():
        dest = FROZEN / clean(rel); dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(NATIVE / rel, dest); need(file_sha(dest) == expected, "native source changed during layout reconstruction")
    verified = []
    for planned, row in zip(plan["assets"], manifest["assets"]):
        src = private_root / row["private_path"]; dest = FROZEN / clean(row["runtime_path"])
        actual = file_sha(src)
        need(not planned.get("text_sha256") or actual == planned["text_sha256"], "native metadata/source bytes changed")
        dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, dest); restore(dest, planned["mtime_ns"])
        need(file_sha(dest) == actual and dest.stat().st_size == planned["bytes"], "native input staging changed bytes")
        verified.append({"runtime_path": row["runtime_path"], "git_blob_sha": row["git_blob_sha"], "bytes": row["bytes"], "sha256_ubuntu": actual, "mtime_ns": planned["mtime_ns"]})
    # Keep HOME intact. The unchanged expanduser paths resolve through this
    # compatible symlink into the exact frozen original /Users layout.
    home_alfred = Path.home() / "alfred"
    need(not home_alfred.exists() and not home_alfred.is_symlink(), "runner already has an alfred layout")
    home_alfred.symlink_to(FROZEN.parent, target_is_directory=True)
    for row in sorted(plan["lease_stats"], key=lambda r: len(PurePosixPath(r["runtime_path"]).parts), reverse=True):
        p = FROZEN / clean(row["runtime_path"])
        if row["is_dir"]: p.mkdir(parents=True, exist_ok=True)
        need(p.exists(), "native reference lease input is absent")
        restore(p, row["mtime_ns"])
    for row in plan["native_directory_stats"]:
        p = FROZEN / clean(row["runtime_path"])
        need(p.is_dir(), "native consumed directory is missing")
        restore(p, row["mtime_ns"])
    return v2, verified


def obtain_public(plan, v2, work):
    out = v2 / "kit/out/S87"; build = out / "build"; build.mkdir(parents=True, exist_ok=True)
    exact = work / "public-render-inputs"; exact.mkdir()
    gh("release", "download", plan["source_release"], "-R", PUBLIC, "-p", "source.tar.gz", "-p", "parts.json", "-p", "mix.wav", "-D", str(exact))
    for filename, key, dest in (("source.tar.gz", "source_sha256", build / "source.tar.gz"), ("parts.json", "parts_sha256", build / "parts.json"), ("mix.wav", "mix_sha256", out / "audio/mix.wav")):
        need(file_sha(exact / filename) == plan[key], "existing public render input changed: " + filename)
        if dest.exists(): need(file_sha(dest) == plan[key], "protected/current parts differ from exact native render input")
        else: dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(exact / filename, dest)
    restore(build / "source.tar.gz", plan["public_asset_stats"]["source"][3]); restore(out / "audio/mix.wav", plan["public_asset_stats"]["mix"][3])
    spec = importlib.util.spec_from_file_location("native_package_extraction", HERE / "render_short_package.py")
    package = importlib.util.module_from_spec(spec); spec.loader.exec_module(package)
    package.safe_extract(build / "source.tar.gz", build / "pkg")
    master = plan["master"]
    artifact = json.loads(gh("api", "repos/%s/actions/artifacts/%s" % (PUBLIC, master["artifact"]["id"])))
    need(not artifact.get("expired") and all(artifact.get(k) == value for k, value in master["artifact"].items()), "exact master artifact expired/changed")
    run = json.loads(gh("api", "repos/%s/actions/runs/%s" % (PUBLIC, master["run"])))
    need(run.get("conclusion") == "success" and run.get("path") == ".github/workflows/agmm-short-package.yml" and artifact.get("workflow_run", {}).get("id") == master["run"], "wrong original master producer run")
    downloaded = work / "original-master"
    gh("run", "download", str(master["run"]), "-R", PUBLIC, "-n", master["artifact"]["name"], "-D", str(downloaded))
    need({p.name for p in downloaded.iterdir()} == {"FINAL.mp4", "TECHNICAL-EVIDENCE.json", "SHA256SUMS.txt"}, "original master artifact inventory mismatch")
    need(all(p.is_file() and not p.is_symlink() for p in downloaded.iterdir()), "master artifact contains linked/special files")
    p = downloaded / "FINAL.mp4"
    need(file_sha(p) == master["sha256"] and p.stat().st_size == master["bytes"], "original master SHA/size mismatch")
    technical = json.loads((downloaded / "TECHNICAL-EVIDENCE.json").read_text())
    need(any(r.get("file") == "FINAL.mp4" and r.get("sha256") == master["sha256"] and r.get("bytes") == master["bytes"] for r in technical.get("masters", [])), "native producer technical evidence does not bind this master")
    shutil.copyfile(p, out / "FINAL.mp4"); restore(out / "FINAL.mp4", plan["master_stat"][3])


def frozen_sound_cached(helper, plan, v2, sid, transport=None):
    """Portable content proof, without pretending Mac inode values are Linux stats."""
    need(str(v2) == plan["v2"] and sid == plan["id"] == "S87", "frozen sound caller SID/layout mismatch")
    root = Path(v2) / "kit/out/S87/machine-pass"
    cache = root / ("audit_sound-%s.json" % plan["master"]["sha256"][:16])
    expected_paths = {p.relative_to(FROZEN).as_posix() for p in (cache, cache.with_suffix(".hosted.json"), root / "sound-inputs/TRANSPORT.json")}
    snapshot = plan.get("sound_snapshot")
    need(type(snapshot) is dict and set(snapshot) == expected_paths, "qualified frozen sound snapshot missing")
    captured_assets = {r["runtime_path"]: r.get("text_sha256") for r in plan["assets"]}
    for rel, expected in snapshot.items():
        need(captured_assets.get(rel) == expected, "frozen sound evidence is not bound in protected inputs")
        need(file_sha(FROZEN / clean(rel)) == expected, "frozen sound evidence bytes changed")
    captured = helper.read_json(root / "sound-inputs/TRANSPORT.json")
    need(transport is None or transport == captured, "frozen sound transport argument differs")
    sound_plan = captured["plan"]
    need(sound_plan.get("id") == sid and sound_plan["master"]["sha256"] == plan["master"]["sha256"]
         and sound_plan["master"]["bytes"] == plan["master"]["bytes"], "frozen sound/master identity mismatch")
    need(all(sound_plan[k] == plan[k] for k in ("request_id", "package_id", "approved_hash")), "frozen sound/source/approval binding differs")
    sidecar = helper.read_json(cache.with_suffix(".hosted.json")); report = helper.read_json(cache)
    need(sidecar["transport_sha256"] == helper.digest(captured), "frozen sound transport digest mismatch")
    pins = helper.read_json(Path(v2) / "kit/tools/sound_audit_hosted_publication.json")
    helper.verify_report(report, sidecar["hosted"], captured, sound_plan, sidecar["run"], pins)
    return report


def observe_native(plan, v2):
    """Execute native evaluate once; optional native issue only in this sandbox."""
    spec = importlib.util.spec_from_file_location("hosted_native_machine_pass", v2 / "qa/machine_pass.py")
    native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
    # c_audit is unchanged. Only its Mac-only cache filesystem adapter is
    # replaced after full host blob/SHA/mtime verification. verify_report and
    # every cache/transport/receipt/SID/master/runtime/run binding stay native.
    original_load = native.load_module
    def load_with_frozen_sound(path, name):
        loaded = original_load(path, name)
        if Path(path) == v2 / "kit/tools/sound_audit_hosted.py":
            loaded.validate_cached = lambda root, sid, transport=None: frozen_sound_cached(loaded, plan, root, sid, transport)
        return loaded
    native.load_module = load_with_frozen_sound
    ctx = native.Ctx(str(v2)); captures = []; promise_calls = []
    def profile(frame, event, result):
        if event == "return" and Path(frame.f_code.co_filename).name == "validate_release.py" and frame.f_code.co_name in ("reviewer_approval", "check_row"):
            captures.append({"function": frame.f_code.co_name, "result": copy.deepcopy(result)})
        if event == "return" and Path(frame.f_code.co_filename).name == "promise_check.py" and frame.f_code.co_name in ("fetch", "check"):
            caller = frame.f_back
            while caller is not None and not (Path(caller.f_code.co_filename).name == "machine_pass.py" and caller.f_code.co_name == "issue"):
                caller = caller.f_back
            platform_name = caller.f_locals.get("plat") if caller is not None else None
            observed = {k: result[k] for k in ("status", "final", "error") if k in result} if frame.f_code.co_name == "fetch" and isinstance(result, dict) else result
            promise_calls.append({"platform": platform_name, "function": frame.f_code.co_name,
                                  "url": frame.f_locals.get("url") if frame.f_code.co_name == "fetch" else None, "result": copy.deepcopy(observed)})
    old_profile = sys.getprofile(); sys.setprofile(profile)
    try:
        if plan["mode"] == "proposal":
            rc, report, why = native.issue(ctx, "S87", arm=False, log=lambda *_: None)
        else:
            report, _ = native.evaluate(ctx, "S87", run_slow=False)
            rc, why = (0 if report.ok else 1), "unchanged native evaluate completed"
    finally: sys.setprofile(old_profile)
    proposal = None
    if plan["mode"] == "proposal":
        cards = json.loads((v2 / "qa/cards.json").read_text()); rows = json.loads((v2 / "qa/review-log.json").read_text())
        reviews = rows if isinstance(rows, list) else rows.get("reviews", [])
        receipt = v2 / "kit/out/S87/machine-pass/RECEIPT.json"
        proposal = {"accepted_in_sandbox": rc == 0, "card": next((c for c in cards if c.get("id") == "S87"), None),
                    "review": next((r for r in reversed(reviews) if r.get("id") == "S87"), None),
                    "receipt": json.loads(receipt.read_text()) if receipt.is_file() else None}
    return {"schema": SCHEMA, "id": "S87", "plan_sha256": digest(plan), "proposal_only": True, "mode": plan["mode"], "ok": report.ok,
            "checks": report.checks, "evidence": report.evidence, "notes": report.notes, "native_rc": rc, "native_message": why,
            "native_validator_calls": captures, "native_promise_calls": promise_calls, "proposal": proposal}


class QATag(urllib.request.BaseHandler):
    """Transport tag only; the unchanged promise judgments keep their original URL."""
    handler_order = 90
    def http_request(self, request):
        parts = urlsplit(request.full_url)
        first_party = parts.hostname in ("agmm.co.uk", "www.agmm.co.uk")
        from_first_party = urlsplit("//" + request.origin_req_host).hostname in ("agmm.co.uk", "www.agmm.co.uk")
        if first_party or from_first_party:
            tags = {"utm_source": "qa", "utm_campaign": "qa_release_audit"}
            query = []
            for pair in parts.query.split("&") if parts.query else []:
                key, _, value = pair.partition("=")
                key, value = unquote_plus(key), unquote_plus(value)
                if key in tags and (first_party or value == tags[key]): continue
                query.append(pair)
            if first_party: query += ["utm_source=qa", "utm_campaign=qa_release_audit"]
            request.full_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(query), parts.fragment))
        return request
    https_request = http_request


def recheck(plan, v2, verified, proposal_mode=False):
    # Native issue is allowed to produce only a sandbox proposal and its ordinary
    # scratch receipt/check files. Original captured state remains cryptographically
    # bound in the input manifest, and the Mac performs full-state CAS on return.
    mutable = {"video-program-2026-09-23/v2/qa/cards.json", "video-program-2026-09-23/v2/qa/review-log.json",
               "video-program-2026-09-23/v2/kit/out/S87/machine-pass/LAST-CHECK.json",
               "video-program-2026-09-23/v2/kit/out/S87/machine-pass/RECEIPT.json"} if proposal_mode else set()
    originals = {r["runtime_path"]: r["sha256_ubuntu"] for r in verified}
    for row in verified:
        if row["runtime_path"] in mutable:
            continue
        p = FROZEN / row["runtime_path"]
        need(p.is_file() and file_sha(p) == row["sha256_ubuntu"] and p.stat().st_mtime_ns == row["mtime_ns"], "native captured input changed during evaluation: " + row["runtime_path"])
    for rel, wanted in plan["native_sources"].items(): need(file_sha(FROZEN / rel) == wanted, "native algorithm changed during evaluation")
    need(file_sha(v2 / "kit/out/S87/FINAL.mp4") == plan["master"]["sha256"], "exact master changed during native evaluation")
    return [{"runtime_path": rel, "original_sha256": originals.get(rel),
             "after_sha256": file_sha(FROZEN / rel) if (FROZEN / rel).is_file() else None} for rel in sorted(mutable)]


def run(payload, private_root, work, output):
    _, pins = host(payload)
    manifest = private_inputs(payload, private_root, pins); plan = manifest["plan"]
    v2, verified = stage(manifest, private_root)
    obtain_public(plan, v2, work)
    recheck(plan, v2, verified)
    projection = plan["snap_projection"]
    expected = [str(Path(p).resolve()) for p in projection["selected"]]
    spec = importlib.util.spec_from_file_location("evaluation_native_metrics", FROZEN / "craft-learning-2026-09-28/craft_metrics.py")
    metrics = importlib.util.module_from_spec(spec); spec.loader.exec_module(metrics)
    need([str(Path(p).resolve()) for p in metrics.snap_frames("S87")] == expected, "native snapshot projection changed selected file order")
    os.environ["TZ"] = plan["timezone"]; time.tzset()
    urllib.request.install_opener(urllib.request.build_opener(QATag()))
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK", "AGMM_INPUTS_TOKEN"):
        os.environ.pop(key, None)
    for key, value in plan["environment"].items():
        need(key in ("FLEET_LANE", "FLEET_LANE_KIND", "FLEET_MODEL_FLAG", "FLEET_FREE_ONLY", "AGMM_CONCEPT_CHECK", "AGMM_RESERVATIONS", "AGMM_RESERVATIONS_ENFORCE"), "unknown native environment override")
        os.environ[key] = value
    result = observe_native(plan, v2)
    mutations = recheck(plan, v2, verified, plan["mode"] == "proposal")
    output.mkdir(parents=True, exist_ok=False)
    body = json.dumps(result, indent=1, ensure_ascii=False).encode() + b"\n"
    (output / "evaluation.json").write_bytes(body)
    publication = payload["publication"]
    receipt = {"schema": SCHEMA, "id": "S87", "mode": plan["mode"], "proposal_only": True, "plan_sha256": digest(plan),
               "private_commit": payload["private_commit"], "manifest_blob": payload["manifest_blob"], "runtime_commit": os.environ["GITHUB_SHA"], "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
               "request_id": plan["request_id"], "approved_hash": plan["approved_hash"], "master_sha256": plan["master"]["sha256"], "master_bytes": plan["master"]["bytes"], "master_sha256_after": file_sha(v2 / "kit/out/S87/FINAL.mp4"),
               "native_sources": pins, "publication": publication, "inputs_verified_before_and_after": True, "verified_inputs": verified,
               "snapshot_projection": {"available": len(projection["available"]), "transported": len(projection["selected"]), "selected": projection["selected"], "native_selection_unchanged": True},
               "sound_validation": {"mode": "frozen-hosted-content-verified", "source_snapshot": plan["sound_snapshot"], "native_verify_report_unchanged": True, "mac_stat_values_not_simulated": True},
               "sandbox_native_mutations": mutations,
               "evaluation_sha256": hashlib.sha256(body).hexdigest(), "python": sys.version, "numpy": __import__("numpy").__version__, "pillow": __import__("PIL").__version__,
               "ffprobe": subprocess.run(["ffprobe", "-version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]}
    (output / "RECEIPT.json").write_text(json.dumps(receipt, indent=1) + "\n")
    need({p.name for p in output.iterdir()} == {"evaluation.json", "RECEIPT.json"}, "only JSON outputs may return")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--payload", default="evaluation-request.json"); ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--private-root", type=Path); ap.add_argument("--work", type=Path); ap.add_argument("--output", type=Path)
    a = ap.parse_args(); payload = json.loads(Path(a.payload).read_text())
    if a.preflight:
        base, _ = host(payload)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write("private_commit=%s\nprivate_prefix=%s\n" % (payload["private_commit"], base))
    else: run(payload, a.private_root, a.work, a.output)


if __name__ == "__main__": main()
