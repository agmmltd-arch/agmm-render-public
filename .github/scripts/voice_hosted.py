#!/usr/bin/env python3
"""Immutable Ubuntu adapter around the existing AGMM native voice owners.

No activation, native promotion, source approval, card/claim or release writes.
The conductor-owned request binds its existing four/day admission and private
inputs; a separate native client reconciles JSON only. Media stays on Actions.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo
from datetime import datetime

HERE = Path(__file__).resolve().parent
NATIVE = HERE / "voice-native"
PUBLIC = "agmmltd-arch/agmm-render-public"
PRIVATE = "agmmltd-arch/agmm-video-render"
WORKFLOW = ".github/workflows/agmm-short-voice.yml"
BASE = Path("/Users/samwall/alfred/builds/video-program-2026-09-23/v2")
REF = "shorts/voice/ref/sam-reference-20260905T152059Z-cdf499.wav"
REF_SHA = "3df9d7568c0b0569887e6c9f39bd35835cda305a09d288ea535c63d9cdc15443"
SCHEMA = "agmm-native-hosted-voice-v1"


def need(value, why):
    if not value:
        raise ValueError(why)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def clean(value):
    p = PurePosixPath(value)
    need(str(p) == value and not p.is_absolute() and ".." not in p.parts
         and p.parts and "\n" not in value and "\r" not in value, "unsafe relative path")
    return value


def call(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True).stdout


def gh(path):
    return json.loads(call("gh", "api", path))


def host():
    from voice_effects import host as check_host
    check_host()
    need(os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "reruns are reconciliation-only")
    need(re.fullmatch(r"[0-9a-f]{40}", os.environ.get("GITHUB_SHA", "")), "immutable runner commit absent")


def source_closure():
    pins = json.loads((HERE / "voice-publication.json").read_text())
    for rel, wanted in pins["files"].items():
        p = HERE.parent.parent / clean(rel)
        need(p.is_file() and not p.is_symlink() and file_sha(p) == wanted,
             "runtime source changed/missing: " + rel)
    return pins


def validate_request(request, now=None):
    need(request.get("schema") == SCHEMA, "wrong request schema")
    need(re.fullmatch(r"[SC][0-9]{2,3}", request.get("id", "")), "wrong native id")
    need(re.fullmatch(r"voice-[A-Za-z0-9._-]{8,140}", request.get("intent", "")), "unsafe intent")
    need(re.fullmatch(r"[0-9a-f]{40}", request.get("private_commit", "")), "private input must be immutable")
    need(re.fullmatch(r"[0-9a-f]{40}", request.get("manifest_blob", "")), "manifest blob missing")
    prefix = clean(request["private_prefix"])
    need(prefix.startswith("voice-hosted-inputs/") and len(PurePosixPath(prefix).parts) == 2,
         "wrong protected namespace")
    need(request.get("manifest_path") == prefix + "/MANIFEST.json", "manifest outside namespace")
    need(request.get("mode") in ("api", "from-existing", "voicelead"), "unknown owner mode")
    if request["mode"] == "api":
        for name, slot in (("AGMM_MISTRAL_KEY", "MISTRAL_KEY"), ("AGMM_NATIVE_GEMINI_KEY_B", "GEMINI_KEY_B")):
            role = request.get("credential_roles", {}).get(name, {})
            need(role.get("native_slot") == slot and role.get("same_existing_credential") is True
                 and role.get("root_verified") is True
                 and re.fullmatch(r"[0-9a-f]{64}", role.get("actual_evidence_sha256") or "")
                 and re.fullmatch(r"[0-9a-f]{64}", role.get("expected_sha256") or "")
                 and (slot != "GEMINI_KEY_B" or role.get("tier") == "free"
                      and re.fullmatch(r"[0-9a-f]{64}", role.get("project_evidence_sha256") or "")),
                 "existing native provider/free-project binding absent")
    admission = request["admission"]
    need(admission.get("owner") == "crew/conductor.py" and admission.get("id") == request["id"]
         and admission.get("step") == "voice" and admission.get("daily_cap") == 4
         and type(admission.get("count_before")) is int and 0 <= admission["count_before"] < 4,
         "foreign owner/daily voice admission")
    for key in ("conductor_sha256", "state_sha256", "input_binding_sha256"):
        need(re.fullmatch(r"[0-9a-f]{64}", admission.get(key, "")), "unbound native admission")
    base_intent = "voice-" + request["id"] + "-" + admission["input_binding_sha256"]
    retry = request.get("prior_no_effect")
    capacity = request.get("prior_capacity")
    need(not (retry and capacity), "ambiguous retry authority")
    wanted = base_intent + ("-after-" + str(retry["run_id"]) if retry else
                           "-after-capacity-" + str(capacity["checkpoint"]["run_id"]) if capacity else "")
    need(request["intent"] == wanted, "retry label requires an exact prior no-effect run")
    if now is not None:
        need(admission["day"] == datetime.fromtimestamp(now, ZoneInfo("Europe/London")).strftime("%Y-%m-%d")
             and 0 <= now - admission["at"] <= 1800, "stale native admission")
    return prefix


def previous_runs(request):
    """The provider intent already exists durably as this exact Actions run.

    Refuse any older matching intent or input binding. Continuation uses a new
    conductor-owned request only after exact prior checkpoint reconciliation;
    that proof must be explicitly transported rather than treating a rerun as safe.
    """
    current = gh("repos/%s/actions/runs/%s" % (PUBLIC, os.environ["GITHUB_RUN_ID"]))
    need(current.get("path") == WORKFLOW and current.get("head_sha") == os.environ["GITHUB_SHA"]
         and current.get("display_title") == "AGMM native voice " + request["intent"], "foreign Actions owner")
    seen = []
    for page in range(1, 10001):
        data = gh("repos/%s/actions/workflows/agmm-short-voice.yml/runs?per_page=100&page=%d" % (PUBLIC, page))
        runs = data["workflow_runs"]
        seen.extend(runs)
        if len(runs) < 100:
            break
    else:
        raise ValueError("incomplete prior run inventory")
    base_intent = "AGMM native voice voice-" + request["id"] + "-" + request["admission"]["input_binding_sha256"]
    prior = []
    for run in seen:
        if str(run["id"]) == os.environ["GITHUB_RUN_ID"]:
            continue
        if run.get("display_title", "").startswith(base_intent):
            prior.append(run)
    retry = request.get("prior_no_effect")
    capacity = request.get("prior_capacity")
    if capacity:
        from voice_capacity import prove_capacity
        proof = capacity["checkpoint"]
        need(proof == prove_capacity(proof["run_id"], proof["producer_git_blobs"])
             and proof["id"] == request["id"], "known capacity producer differs")
        restored = capacity["restoration"]
        need(restored.get("owner") == "root-existing-provider-account" and restored.get("provider") == "mistral"
             and restored.get("state") == "available" and 0 <= time.time() - restored["observed_at"] <= 1800
             and re.fullmatch(r"[0-9a-f]{64}", restored.get("actual_evidence_sha256", "")),
             "capacity restoration is not evidenced; no provider retry")
        prior = [r for r in prior if r["id"] != proof["run_id"]]
    need(bool(retry) == bool(prior) or bool(capacity), "prior durable intent requires explicit no-effect reconciliation")
    if prior:
        from voice_no_effect import prove_no_effect
        pins = source_closure()
        proofs = []
        for row in prior:
            full = gh("repos/%s/actions/runs/%s" % (PUBLIC, row["id"]))
            tree = gh("repos/%s/git/trees/%s?recursive=1" % (PUBLIC, full["head_sha"]))
            need(not tree.get("truncated"), "prior source inventory incomplete")
            blob = next(r["sha"] for r in tree["tree"] if r["path"] == WORKFLOW)
            jobs = gh("repos/%s/actions/runs/%s/jobs?per_page=100" % (PUBLIC, row["id"]))
            proofs.append(prove_no_effect(full, jobs, blob, pins["allowed_no_effect_workflow_blobs"]))
        latest = max(proofs, key=lambda p: p["run_id"])
        need(retry == latest if retry else latest["run_id"] < capacity["checkpoint"]["run_id"],
             "retry does not bind the latest exact completed proof")
    return current


def private_inputs(request, private_root, verify_media=True):
    manifest_path = private_root / request["manifest_path"]
    raw = manifest_path.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    need(blob == request["manifest_blob"], "protected manifest changed")
    need(call("git", "rev-parse", "HEAD", cwd=private_root).strip() == request["private_commit"],
         "protected checkout commit differs")
    manifest = json.loads(raw)
    need(manifest["request_identity"] == {k: request[k] for k in
         ("schema", "id", "intent", "mode", "admission")}, "protected/native intent mismatch")
    rows = manifest["files"]
    need(len({r["runtime_path"] for r in rows}) == len(rows), "duplicate input paths")
    sid = request["id"]
    required = {"shorts/scripts-v2/" + sid + ".md"} | {
        "shorts/voice/%s/%s" % (sid, n) for n in ("paragraphs.txt", "names.txt", "source.json")}
    paths = {clean(r["runtime_path"]) for r in rows}
    need(required <= paths and (request["mode"] != "api" or REF in paths), "incomplete voice inputs")
    for rel in paths:
        need(rel in required | {REF, "shorts/voice/ASR-TRIAGE.json"}
             or rel.startswith("shorts/voice/" + sid + "/"), "foreign input or executable source")
        need(not rel.endswith((".py", ".sh", ".env")), "input cannot replace runtime")
        if rel.startswith("shorts/voice/" + sid + "/") and rel not in required:
            name = rel.removeprefix("shorts/voice/" + sid + "/")
            need(re.fullmatch(r"(?:P[0-9]{2}\.(?:wav|mp4|receipt\.json|words\.json)|" + sid +
                 r"\.(?:wav|words\.json|receipt\.json|voicelead\.json)|RESULT\.json)", name),
                 "only original native take/final input names may enter a piece")
    need(not any(r["runtime_path"] != REF and r["sha256"] == REF_SHA for r in rows),
         "private reference cannot be relabelled as generated piece media")
    prefix = request["private_prefix"] + "/"
    tree = {}
    for line in call("git", "ls-tree", "-r", "-l", "HEAD", "--", prefix, cwd=private_root).splitlines():
        info, name = line.split("\t", 1)
        mode, kind, git_blob, size = info.split()
        tree[name] = (mode, kind, git_blob, int(size))
    need(set(tree) == {request["manifest_path"]} | {prefix + r["runtime_path"] for r in rows},
         "protected input subtree has missing/extra assets")
    for row in rows:
        need(tree[prefix + row["runtime_path"]] == ("100644", "blob", row["git_blob_sha"], row["bytes"]),
             "protected Git entry differs")
        if not verify_media and row["runtime_path"] not in required:
            continue
        p = private_root / prefix / row["runtime_path"]
        need(p.is_file() and not p.is_symlink() and p.stat().st_size == row["bytes"]
             and file_sha(p) == row["sha256"], "private asset binding changed: " + row["runtime_path"])
    if REF in paths:
        need(next(r["sha256"] for r in rows if r["runtime_path"] == REF) == REF_SHA,
             "Sam reference identity changed")
    body = {r["runtime_path"]: r["sha256"] for r in rows if r["runtime_path"] != REF}
    need(body == request["input_bindings"] and digest(body) == request["admission"]["input_binding_sha256"],
         "input binding differs from native admission")
    return manifest


def text_binding(sid):
    piece = BASE / "shorts/voice" / sid
    source = json.loads((piece / "source.json").read_text())
    need(source.get("id") == sid and source.get("script_file") == str(BASE / "shorts/scripts-v2" / (sid + ".md")),
         "source id/path differs")
    text = (BASE / "shorts/scripts-v2" / (sid + ".md")).read_text()
    spec = importlib.util.spec_from_file_location("frozen_native_prepare", BASE / "shorts/voice/tooling/prepare.py")
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    spoken = prepare.extract_spoken(text)
    norm = lambda x: " ".join(x.split())
    need(norm(" ".join(spoken)) == norm(source["full_spoken_text"]), "canonical authored source differs")
    # Reuse the unchanged owner's expansion/folding/reviewed-CLEAN equivalence,
    # including curated names. Fresh work does not yet have final media/RESULT;
    # those remaining prerequisites are enforced in full after the native chain.
    sys.path.insert(0, str(BASE / "shorts/voice/tooling"))
    issues = prepare.voicelead_prerequisite_issues(str(BASE / "shorts/voice"), sid)
    input_issues = [x for x in issues if x.startswith(("current authored", "source.json", "paragraphs.txt", "names.txt"))]
    need(not input_issues, "native input binding: " + "; ".join(input_issues))
    # Preserve existing curated names verbatim; no heuristic extraction equality.
    return prepare, piece


def stage(manifest, request, private_root):
    need(not BASE.exists() and not (Path.home() / "alfred").exists(), "runner is not a fresh native sandbox")
    shutil.copytree(NATIVE, BASE)
    for row in manifest["files"]:
        rel = row["runtime_path"]
        dest = BASE / rel
        need(not dest.exists(), "input would overwrite native source")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(private_root / request["private_prefix"] / rel, dest)
    # Same compatible original-layout adapter as the existing master evaluator.
    (Path.home() / "alfred").symlink_to(BASE.parents[2], target_is_directory=True)
    for rel in ("yt-engine/.venv/bin/python", "venvs/pitch/bin/python"):
        p = Path.home() / "alfred" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            need(rel.startswith("yt-engine/"), "pinned native Praat environment not installed")
            p.symlink_to(sys.executable)
    return text_binding(request["id"])


def output_checkpoint(request, output, piece, effects, status):
    """Explicit generated-only export: the private ref and input tree never leave."""
    output.mkdir(parents=True, exist_ok=True)
    generated = output / "generated"
    generated.mkdir(exist_ok=True)
    inventory = []
    for p in sorted(piece.rglob("*")):
        if not p.is_file() or p.is_symlink() or p.name in ("paragraphs.txt", "names.txt", "source.json"):
            continue
        # Generated native files and their technical/listening metadata only.
        need(p.suffix in (".wav", ".mp4", ".json", ".txt", ".log"), "unknown generated export type")
        rel = p.relative_to(piece)
        dest = generated / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
        inventory.append({"path": rel.as_posix(), "sha256": file_sha(dest), "bytes": dest.stat().st_size,
                          "original_mtime_ns": p.stat().st_mtime_ns})
    shutil.copytree(effects, output / "effects", dirs_exist_ok=True)
    triage_path = BASE / "shorts/voice/ASR-TRIAGE.json"
    if triage_path.exists():
        triage = json.loads(triage_path.read_text())
        (output / "CURRENT-TRIAGE.json").write_text(json.dumps(
            {request["id"]: triage[request["id"]]} if request["id"] in triage else {}, indent=2) + "\n")
    receipt = {"schema": SCHEMA, "id": request["id"], "intent": request["intent"],
               "mode": request["mode"], "status": status, "request_sha256": digest(request),
               "runtime_commit": os.environ["GITHUB_SHA"], "run_id": os.environ["GITHUB_RUN_ID"],
               "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "native_inputs": request["admission"],
               "publication_sha256": file_sha(HERE / "voice-publication.json"), "generated": inventory,
               "triage_sha256": file_sha(output / "CURRENT-TRIAGE.json") if (output / "CURRENT-TRIAGE.json").exists() else None,
               "ref_exported": False, "approval": False, "release_approval": False,
               "original_qa_intake_authority_required": True}
    (output / "RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    metadata = output.parent / "voice-json"
    metadata.mkdir(exist_ok=True)
    shutil.copyfile(output / "RECEIPT.json", metadata / "RECEIPT.json")
    for name in ("RESULT.json", request["id"] + ".voicelead.json"):
        if (piece / name).is_file():
            shutil.copyfile(piece / name, metadata / name)
    if (output / "CURRENT-TRIAGE.json").exists():
        shutil.copyfile(output / "CURRENT-TRIAGE.json", metadata / "CURRENT-TRIAGE.json")
    (metadata / "EFFECTS.json").write_text(json.dumps([
        json.loads(p.read_text()) for p in sorted(effects.glob("*.json"))], indent=2) + "\n")


def run(request, private_root, output):
    host()
    source_closure()
    # The qualified workflow already enforces fresh/day-bound admission before
    # dependency hydration. Cold model/wheel setup must not silently expire an
    # accepted immutable run after its original owner reserved the attempt.
    validate_request(request)
    previous_runs(request)
    if request["mode"] == "api":
        need(bool(os.environ.get("AGMM_VOICE_MISTRAL_KEY")), "Mistral runner credential unavailable: no effect")
        need(bool(os.environ.get("AGMM_VOICE_GEMINI_FREE_KEY")), "free review credential unavailable: no effect")
        from verify_voice_credential_roles import compare
        roles=compare({name:r["expected_sha256"] for name,r in request["credential_roles"].items()},os.environ)
        need(all(r["exact_existing_native_match"] for r in roles.values()),
             "existing native credential changed before provider step; no effect")
    manifest = private_inputs(request, private_root)
    prepare, piece = stage(manifest, request, private_root)
    # A cached FINISHED is reusable only after the unchanged full prerequisite
    # binding AND an original exact-bound hosted receipt; otherwise stop.
    existing_result = piece / "RESULT.json"
    if existing_result.exists():
        need(request["mode"] == "voicelead", "cached RESULT requires explicit reconciliation/voicelead mode")
        need(not prepare.voicelead_prerequisite_issues(str(BASE / "shorts/voice"), request["id"]),
             "cached voice prerequisites failed")
    effects = output.parent / "voice-effects"
    effects.mkdir(exist_ok=False)
    environment = os.environ.copy()
    environment.update(AGMM_VOICE_CHILD="1", AGMM_VOICE_EFFECTS=str(effects),
                       AGMM_VOICE_PIECE=str(piece), FLEET_FREE_ONLY="1", HF_HUB_OFFLINE="1",
                       GEMINI_WATCH_KEY="GEMINI_KEY_B", GEMINI_WATCH_VERTEX="0",
                       PYTHONPATH=str(HERE / "voice-site") + os.pathsep + str(HERE))
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK"):
        environment.pop(key, None)
    status = "FAILED"
    try:
        if request["mode"] != "voicelead":
            command = [sys.executable, str(BASE / "shorts/voice/tooling/run_short.py"),
                       str(BASE / "shorts/voice"), request["id"]]
            if request["mode"] == "from-existing":
                command.append("--from-existing")
            result = subprocess.run(command, env=environment, capture_output=True, text=True)
            (piece / "hosted-native.log").write_text(result.stdout + result.stderr)
            need(result.returncode == 0 and not (effects / "STOP.json").exists(), "native chain stopped; reconcile checkpoint")
        issues = prepare.voicelead_prerequisite_issues(str(BASE / "shorts/voice"), request["id"])
        need(not issues, "native prerequisite failure: " + "; ".join(issues))
        result = subprocess.run([sys.executable, str(BASE / "shorts/voice/tooling/voice_lead_check.py"),
                                 str(BASE / "shorts/voice"), request["id"]],
                                env=environment, capture_output=True, text=True)
        (piece / "hosted-voicelead.log").write_text(result.stdout + result.stderr)
        need(result.returncode == 0 and not (effects / "STOP.json").exists(), "native voicelead failed")
        report = json.loads((piece / (request["id"] + ".voicelead.json")).read_text())
        need(report.get("verdict") == "PASS", "native voicelead not PASS")
        status = "NATIVE_CHECKS_COMPLETED_REVIEW_REQUIRED"
    finally:
        if (effects / "STOP.json").exists():
            status = json.loads((effects / "STOP.json").read_text())["status"]
        source_closure()
        for row in manifest["files"]:
            if row["runtime_path"] in {REF, "shorts/scripts-v2/" + request["id"] + ".md"} or Path(row["runtime_path"]).name in ("paragraphs.txt", "names.txt", "source.json"):
                need(file_sha(BASE / row["runtime_path"]) == row["sha256"], "protected source input mutated")
        output_checkpoint(request, output, piece, effects, status)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", type=Path, required=True)
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--private-root", type=Path)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    request = json.loads(args.request.read_text())
    if args.preflight:
        host()
        source_closure()
        prefix = validate_request(request, time.time())
        previous_runs(request)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write("private_commit=%s\nprivate_prefix=%s\n" % (request["private_commit"], prefix))
    else:
        run(request, args.private_root, args.output)


if __name__ == "__main__":
    main()
