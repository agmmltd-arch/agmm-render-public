#!/usr/bin/env python3
"""Exact-master native sound audit: metadata-only Mac client, Ubuntu media work.

The protected-input uploader owns TRANSPORT.json. This module never reads an
audio/video/archive file. It reuses the accepted DOM client's source guard and
native authentication wrapper; it does not issue a review or a release.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
REPO = "agmmltd-arch/agmm-render-public"
PRIVATE = "agmmltd-arch/agmm-video-render"
WORKFLOW = "agmm-short-sound-audit.yml"


class Refused(RuntimeError):
    pass


def need(ok, why):
    if not ok:
        raise Refused(why)


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return digest_bytes(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def read_json(path):
    need(Path(path).suffix == ".json", "only JSON metadata may be read by this client")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-%d" % os.getpid())
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def file_stat(path):
    path = Path(path)
    s = path.lstat()
    need(stat.S_ISREG(s.st_mode) and not path.is_symlink() and path.resolve() == path.absolute(), "input must be a regular file without symlink components: " + str(path))
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode]


def clean_path(value):
    p = PurePosixPath(value)
    need(not p.is_absolute() and ".." not in p.parts and str(p) == value, "unsafe relative input path")
    return value


def source_guard(v2, sid, request_path):
    # Reuse the accepted exact native approval/request/package metadata contract.
    dom = module(v2 / "kit/tools/dom_lint_hosted.py", "sound_guard_dom")
    platforms = module(v2 / "kit/platforms/platforms.py", "sound_guard_platforms")
    target = platforms.resolve(platforms.routed_platform(sid) or "instagram")
    _, guard = dom.snapshot(v2, sid, request_path, target, "0" * 40)
    # Sound is independent of the posting destination. Route changes cannot
    # change the sound result, but approval/source/package/maker changes can.
    return {k: guard[k] for k in ("source_hash", "metadata_sha256", "package_stat", "media_stat", "maker_identity")}


def make_plan(v2, sid, request_path, artifact):
    v2, request_path = Path(v2).resolve(), Path(request_path).resolve()
    need(re.fullmatch(r"[SCP][0-9]{2,3}", sid), "invalid short ID")
    out = v2 / "kit/out" / sid
    before = source_guard(v2, sid, request_path)
    request = read_json(request_path)
    collected = read_json(request_path.with_name("COLLECTED.json"))
    need(collected.get("tag") == sid + "-" + request["request_id"][:16], "native master tag/request identity mismatch")
    need(collected.get("tag") == request["workflow_inputs"]["tag"] and type(collected.get("run")) is int,
         "COLLECTED tag/run does not match the exact native request")
    need(re.fullmatch(r"[0-9a-f]{64}", collected.get("sha256", "")), "COLLECTED lacks the full master SHA256")
    need(file_stat(out / "FINAL.mp4")[2] == collected.get("bytes"), "current master size differs from COLLECTED")
    need(artifact.get("name") == collected["tag"] + "-FINAL-MASTERS" and type(artifact.get("id")) is int
         and artifact.get("digest", "").startswith("sha256:") and artifact.get("expired") is False,
         "exact unexpired FINAL-MASTERS artifact metadata required")
    # bundle_files only enumerates paths/JSON; NEVER call make_bundle.
    gate = module(v2 / "kit/tools/gate_actions.py", "sound_input_inventory")
    native_inventory = {Path(src).relative_to(v2).as_posix(): arc for arc, src in gate.bundle_files(sid, str(out)) if src}
    relout = "kit/out/" + sid
    required = [relout + "/" + p for p in ("resolved.json", "audio/cues.json", "audio/mix2/mix_manifest.json", "audio/mix2/music_gain.json",
                                                  "audio/mix2/stems/voice.wav", "audio/mix2/stems/music.wav", "audio/mix2/stems/sfx.wav")]
    library = read_json(v2 / "sound/library.json")
    by_id = {row["id"]: row for row in library["items"]}
    cues = read_json(out / "audio/cues.json")["cues"]
    mix_manifest = read_json(out / "audio/mix2/mix_manifest.json")
    need(mix_manifest.get("master", {}).get("sha256") == request["inputs"]["mix"]["sha256"], "native mix manifest no longer matches the rendered mix")
    mix_spec_sha = digest_bytes((out / "audio/mix_spec.json").read_bytes())
    need(mix_manifest.get("spec_sha256") == mix_spec_sha, "native mix specification changed after the stem render")
    placements = mix_manifest["sfx"]["cues"]
    ids = {row["sfx_id"] for row in cues + placements}
    need(ids <= set(by_id), "native cues reference a missing library item")
    required += sorted({"sound/" + clean_path(by_id[i]["path"]) for i in ids})
    rows = []
    for rel in sorted(required):
        need(rel in native_inventory, "sound input is absent from the native gate inventory: " + rel)
        s = file_stat(v2 / rel)
        row = {"runtime_path": rel, "source_relative": rel, "stat": s, "bytes": s[2]}
        if rel.endswith(".json"):
            row["text_sha256"] = digest_bytes((v2 / rel).read_bytes())
        else:
            match = next((e for e in library["items"] if "sound/" + e["path"] == rel), {})
            if match.get("sha256"):
                row["catalogue_sha256"] = match["sha256"]
            if "/mix2/stems/" in rel:
                row["stem_sha256"] = mix_manifest["stems"][Path(rel).stem]["sha256"]
        rows.append(row)
    need(before == source_guard(v2, sid, request_path), "source changed during input enumeration")
    need(all(file_stat(v2 / row["source_relative"]) == row["stat"] for row in rows), "sound input metadata changed during enumeration")
    native_sources = {rel: digest_bytes((v2 / rel).read_bytes()) for rel in ("sound/audit_sound.py", "sound/v2/audio_core.py", "sound/library.json")}
    return {"schema": "agmm-hosted-sound-input-plan-v1", "id": sid, "request_relative": request_path.relative_to(v2).as_posix(),
            "request_id": request["request_id"], "package_id": request["package_id"], "approved_hash": request["approval"]["approved_hash"],
            "render_binding": dict({k + "_sha256": request["inputs"][k]["sha256"] for k in ("source", "parts", "mix")}, render_4k=request["workflow_inputs"]["render_4k"], workers=request["workflow_inputs"]["workers"]),
            "mix_spec_text_sha256": mix_spec_sha,
            "source_guard": before, "collected_sha256": digest_bytes(request_path.with_name("COLLECTED.json").read_bytes()),
            "native_sources": native_sources, "master_stat": file_stat(out / "FINAL.mp4"),
            "master": {"sha256": collected["sha256"], "bytes": collected["bytes"], "run": collected["run"], "tag": collected["tag"],
                       "artifact": {k: artifact[k] for k in ("id", "name", "digest", "created_at", "expires_at")}},
            "cue_count": len(placements), "sfx_count": len(ids), "assets": rows}


def verify_plan(v2, plan):
    artifact = dict(plan["master"]["artifact"], expired=False)
    current = make_plan(v2, plan["id"], Path(v2) / plan["request_relative"], artifact)
    need(current == plan, "source/approval/package/input/master metadata changed since the protected transport plan")


def gh_client(v2):
    return module(Path(v2) / "kit/tools/snap.py", "sound_audit_snap")._gh


def runtime_commit(v2, gh):
    head = json.loads(gh(["api", "repos/%s/commits/main" % REPO]).stdout)["sha"]
    tree = json.loads(gh(["api", "repos/%s/git/trees/%s?recursive=1" % (REPO, head)]).stdout)
    need(not tree.get("truncated"), "public source tree metadata was truncated")
    blobs = {r["path"]: r["sha"] for r in tree["tree"] if r["type"] == "blob"}
    pins = read_json(HERE / "sound_audit_hosted_publication.json")
    need(all(blobs.get(p) == row["git_blob_sha"] for p, row in pins.items()), "exact reviewed sound runtime closure is not published; no local fallback")
    return head, pins


def verify_transport(transport, plan, tree):
    need(transport.get("schema") == "agmm-hosted-sound-transport-v1" and transport.get("plan_sha256") == digest(plan), "transport belongs to another plan")
    need(re.fullmatch(r"[0-9a-f]{40}", transport.get("private_commit", "")) and not tree.get("truncated"), "invalid or truncated private commit tree")
    blobs = {r["path"]: r for r in tree["tree"] if r["type"] == "blob"}
    manifest = transport["input_manifest"]
    need(manifest["plan_sha256"] == digest(plan) and manifest["master"] == plan["master"], "protected manifest master/plan binding mismatch")
    need(all(manifest.get(k) == plan[k] for k in ("id", "approved_hash", "request_id", "package_id", "render_binding", "native_sources", "cue_count", "sfx_count")), "protected manifest source/input binding mismatch")
    base = "protected-inputs/%s/sound-audit/%s/" % (plan["id"], digest(plan))
    need(transport.get("manifest_path") == base + "INPUTS.json", "transport private prefix mismatch")
    mb = blobs.get(base + "INPUTS.json", {})
    need(mb.get("sha") == transport.get("manifest_blob") and mb.get("size") == len(transport["manifest_text"].encode()), "private manifest native Git blob/size mismatch")
    need(json.loads(transport["manifest_text"]) == manifest, "transport manifest text changed")
    rows = manifest["assets"]
    need([r["runtime_path"] for r in rows] == [r["runtime_path"] for r in plan["assets"]], "protected input inventory mismatch")
    expected = {base + "INPUTS.json"}
    for row, planned in zip(rows, plan["assets"]):
        path = base + clean_path(row["runtime_path"])
        expected.add(path)
        need(row["private_path"] == path and row["bytes"] == planned["bytes"], "protected path/size differs from plan")
        need(all(row.get(k) == planned.get(k) for k in ("text_sha256", "catalogue_sha256", "stem_sha256")), "protected input hash metadata changed")
        native = blobs.get(path, {})
        need(native.get("sha") == row.get("git_blob_sha") and native.get("size") == row["bytes"] and native.get("mode") == "100644", "protected native Git blob/size/mode mismatch")
    need({p for p in blobs if p.startswith(base)} == expected, "private audit prefix contains missing/extra assets")


def verify_report(report, receipt, transport, plan, run, pins):
    need(receipt.get("schema") == "agmm-hosted-native-sound-audit-v1" and receipt.get("plan_sha256") == digest(plan), "sound receipt plan mismatch")
    need(receipt.get("master_sha256") == report.get("_master_sha256") == plan["master"]["sha256"] and receipt.get("master_bytes") == plan["master"]["bytes"], "sound report exact-master mismatch")
    need(receipt.get("post_audit_inputs_verified") is True and receipt.get("post_audit_master_sha256") == plan["master"]["sha256"], "post-audit native input/master verification missing")
    need(receipt.get("private_commit") == transport["private_commit"] and receipt.get("manifest_blob") == transport["manifest_blob"], "sound private-input provenance mismatch")
    need(receipt.get("manifest_sha256") == digest_bytes(transport["manifest_text"].encode()) and receipt.get("master_artifact") == plan["master"]["artifact"], "sound manifest/artifact provenance mismatch")
    need(all(receipt.get(k) == plan[k] for k in ("id", "approved_hash", "request_id", "package_id")), "sound source approval/request binding mismatch")
    need(receipt.get("render_binding") == plan["render_binding"], "sound render input binding mismatch")
    need(all(pins.get(".github/scripts/sound-audit-native/" + rel, {}).get("sha256") == value for rel, value in plan["native_sources"].items()), "hosted sound algorithms differ from the current native source")
    need(receipt.get("public_commit") == run["headSha"] and str(receipt.get("run_id")) == str(run["databaseId"]), "sound workflow run provenance mismatch")
    need(receipt.get("runtime_pins") == {p: row["sha256"] for p, row in pins.items() if p.startswith(".github/scripts/sound-audit-native/")}, "sound runtime source mismatch")
    need(receipt.get("report_canonical_sha256") == digest(report), "sound report JSON digest mismatch")
    verified = receipt.get("verified_inputs") or []
    need(len(verified) == len(plan["assets"]), "sound verified input coverage mismatch")
    for actual, planned, protected in zip(verified, plan["assets"], transport["input_manifest"]["assets"]):
        need(actual.get("runtime_path") == planned["runtime_path"] and actual.get("bytes") == planned["bytes"] and actual.get("git_blob_sha") == protected["git_blob_sha"]
             and re.fullmatch(r"[0-9a-f]{64}", actual.get("sha256_ubuntu", "")), "sound verified input identity mismatch")
        need(all(actual["sha256_ubuntu"] == planned[k] for k in ("text_sha256", "catalogue_sha256", "stem_sha256") if planned.get(k)), "sound verified input digest mismatch")
    need(report.get("mode") == "mix2" and report.get("status") in ("PASS", "FAIL") and type(report.get("fails")) is list,
         "incomplete native sound audit report")
    for key in ("loudness", "bed_rows", "swells", "banned", "density", "onsets", "stereo", "rules", "duration_s"):
        need(key in report, "native sound audit omitted " + key)
    need(report["onsets"]["cues"] == plan["cue_count"] and receipt.get("no_video") is False, "native cue coverage/full picture stereo check required")
    need(report.get("_rc") == (1 if report["status"] == "FAIL" else 0) and bool(report["fails"]) == (report["status"] == "FAIL"), "native audit exit/status mismatch")


def validate_cached(v2, sid, transport=None):
    root = Path(v2) / "kit/out" / sid / "machine-pass"
    transport = transport or read_json(root / "sound-inputs/TRANSPORT.json")
    plan = transport["plan"]
    need(plan.get("id") == sid, "sound transport short ID mismatch")
    verify_plan(v2, plan)
    cache = root / ("audit_sound-%s.json" % plan["master"]["sha256"][:16])
    receipt = read_json(cache.with_suffix(".hosted.json"))
    report = read_json(cache)
    need(receipt["transport_sha256"] == digest(transport), "sound cache transport changed")
    pins = read_json(HERE / "sound_audit_hosted_publication.json")
    verify_report(report, receipt["hosted"], transport, plan, receipt["run"], pins)
    return report


def prepare_existing(ctx, sid, timeout=1500):
    v2 = Path(ctx.v2)
    root = v2 / "kit/out" / sid / "machine-pass"
    try:
        transport = read_json(root / "sound-inputs/TRANSPORT.json")
        plan = transport["plan"]
        need(plan["id"] == sid, "transport short ID mismatch")
        verify_plan(v2, plan)
        cache = root / ("audit_sound-%s.json" % plan["master"]["sha256"][:16])
        if cache.exists():
            report = validate_cached(v2, sid, transport)
            return (0 if report["status"] == "PASS" else 1), "existing exact-master hosted native sound audit " + report["status"]
        root.mkdir(parents=True, exist_ok=True)
        with (root / ".sound-hosted.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Recheck after acquiring the owner lock.
            verify_plan(v2, plan)
            gh = gh_client(v2)
            head, pins = runtime_commit(v2, gh)
            need(all(pins.get(".github/scripts/sound-audit-native/" + rel, {}).get("sha256") == value for rel, value in plan["native_sources"].items()), "published sound runtime differs from the current native source")
            tree = json.loads(gh(["api", "repos/%s/git/trees/%s?recursive=1" % (PRIVATE, transport["private_commit"])]).stdout)
            verify_transport(transport, plan, tree)
            artifact = json.loads(gh(["api", "repos/%s/actions/artifacts/%s" % (REPO, plan["master"]["artifact"]["id"])]).stdout)
            need(not artifact.get("expired") and all(artifact.get(k) == v for k, v in plan["master"]["artifact"].items()), "exact source master artifact is expired/changed; no local upload or substituted render")
            payload = {"schema": 1, "id": sid, "plan_sha256": digest(plan), "private_commit": transport["private_commit"], "manifest_path": transport["manifest_path"],
                       "manifest_blob": transport["manifest_blob"], "manifest_sha256": digest_bytes(transport["manifest_text"].encode()), "runtime_commit": head,
                       "master": plan["master"], "approved_hash": plan["approved_hash"], "request_id": plan["request_id"], "package_id": plan["package_id"], "render_binding": plan["render_binding"]}
            work = root / "sound-hosted" / digest({"plan": digest(plan), "private_commit": transport["private_commit"], "pins": pins})
            work.mkdir(parents=True, exist_ok=True)
            ip = work / "INTENT.json"
            intent = read_json(ip) if ip.exists() else {"payload": payload, "plan_sha256": digest(plan), "label": "%s-sound-%s" % (sid, digest(payload)[:20]), "dispatch_attempted": False,
                                                      "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
            need(intent["payload"] == dict(payload, runtime_commit=intent["payload"]["runtime_commit"]), "hosted sound intent changed; no duplicate dispatch")
            payload, head = intent["payload"], intent["payload"]["runtime_commit"]
            if not intent["dispatch_attempted"]:
                intent["dispatch_attempted"] = True
                atomic(ip, intent)  # durable before the non-idempotent provider call
                gh(["workflow", "run", WORKFLOW, "-R", REPO, "--ref", "main", "-f", "label=" + intent["label"], "-f", "payload=" + json.dumps(payload, separators=(",", ":"))])
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                time.sleep(15)
                if not intent.get("run_id"):
                    rows = json.loads(gh(["run", "list", "-R", REPO, "--workflow", WORKFLOW, "--event", "workflow_dispatch", "--limit", "50", "--json", "databaseId,displayTitle"]).stdout)
                    matches = [r for r in rows if r["displayTitle"] == "AGMM exact-master sound " + intent["label"]]
                    need(len(matches) <= 1, "ambiguous hosted sound run; no result adopted")
                    if not matches:
                        continue
                    intent["run_id"] = str(matches[0]["databaseId"])
                    atomic(ip, intent)
                run = json.loads(gh(["run", "view", intent["run_id"], "-R", REPO, "--json", "databaseId,status,conclusion,headSha,event,createdAt,startedAt,updatedAt,url"]).stdout)
                need(run["headSha"] == head and run["event"] == "workflow_dispatch", "wrong sound runtime/event")
                dt = __import__("datetime").datetime
                need(dt.fromisoformat(run["createdAt"].replace("Z", "+00:00")) >= dt.fromisoformat(intent["created_at"]) - __import__("datetime").timedelta(seconds=5), "sound run predates its durable intent")
                if run["status"] == "completed":
                    need(run["conclusion"] == "success", "hosted native sound tool failed; no cache; run " + intent["run_id"])
                    break
            else:
                raise Refused("hosted sound wait expired; original intent/run retained; no duplicate or cancellation")
            with tempfile.TemporaryDirectory(prefix="agmm-sound-json-") as tmp:
                gh(["run", "download", intent["run_id"], "-R", REPO, "-n", intent["label"] + "-JSON", "-D", tmp], timeout=300)
                files = list(Path(tmp).iterdir())
                need(sorted(p.name for p in files) == ["RECEIPT.json", "audit.json"] and all(p.is_file() and not p.is_symlink() and p.stat().st_size < 2_000_000 for p in files), "sound output must be exactly two bounded JSON files")
                report, receipt = read_json(Path(tmp) / "audit.json"), read_json(Path(tmp) / "RECEIPT.json")
            verify_report(report, receipt, transport, plan, run, pins)
            verify_plan(v2, plan)
            need(read_json(root / "sound-inputs/TRANSPORT.json") == transport, "transport changed during sound run")
            # Cache last: a crash before it leaves an incomplete pair that refuses.
            atomic(cache.with_suffix(".hosted.json"), {"hosted": receipt, "run": run, "transport_sha256": digest(transport)})
            atomic(cache, report)
            return (0 if report["status"] == "PASS" else 1), "fresh hosted exact-master native sound audit " + report["status"] + "; run " + str(run["databaseId"])
    except (OSError, ValueError, KeyError, Refused, RuntimeError) as exc:
        return 2, "hosted sound audit refused: %s; no Mac media fallback" % exc


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("id")
    ap.add_argument("--v2", type=Path, required=True)
    ap.add_argument("--request", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    req = read_json(a.request)
    collected = read_json(a.request.with_name("COLLECTED.json"))
    gh = gh_client(a.v2)
    rows = json.loads(gh(["api", "repos/%s/actions/runs/%s/artifacts" % (REPO, collected["run"])]).stdout)["artifacts"]
    matches = [r for r in rows if r["name"] == req["workflow_inputs"]["tag"] + "-FINAL-MASTERS" and not r["expired"]]
    need(len(matches) == 1, "expected one unexpired exact master artifact")
    atomic(a.output, make_plan(a.v2, a.id, a.request, matches[0]))
    print("metadata-only protected input plan written: " + str(a.output))


if __name__ == "__main__":
    main()
