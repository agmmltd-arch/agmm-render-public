#!/usr/bin/env python3
"""Hydrate a genuinely completed voice into the existing builder's Ubuntu layout.

This is an input adapter, not a builder, review approval or release. It runs only
on the authorised public Ubuntu host, verifies the original producer and artifact
digest, and preserves exact native WAV/words/source/receipt names. Mac callers
receive metadata pointers only and can never use this function as a downloader.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from voice_effects import host
from voice_hosted import PUBLIC, WORKFLOW, BASE, clean, digest, file_sha, gh, need, private_inputs, source_closure


def validate_completed(receipt, request, run, artifact):
    sid = request["id"]
    need(receipt.get("status") == "NATIVE_CHECKS_COMPLETED_REVIEW_REQUIRED"
         and receipt.get("id") == sid and receipt.get("intent") == request["intent"]
         and receipt.get("request_sha256") == digest(request)
         and receipt.get("native_inputs") == request["admission"], "voice not complete/exact-source bound")
    need(str(run["id"]) == str(receipt["run_id"]) and run.get("path") == WORKFLOW
         and run.get("head_sha") == receipt["runtime_commit"] and run.get("event") == "workflow_dispatch"
         and run.get("run_attempt") == 1 and run.get("status") == "completed"
         and run.get("conclusion") == "success", "wrong/stale/uncompleted voice producer")
    need(artifact.get("workflow_run", {}).get("id") == run["id"] and not artifact.get("expired")
         and artifact.get("name") == request["intent"] + ("-GENERATED-ENC" if request.get("selection_producer") else "-GENERATED")
         and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.get("digest") or ""),
         "foreign/expired/unbound voice artifact")
    required = {sid + ".wav", sid + ".words.json", sid + ".receipt.json", sid + ".voicelead.json", "RESULT.json"}
    inventory = receipt["generated"]
    paths = {r["path"] for r in inventory}
    need(len(paths) == len(inventory) and required <= paths, "incomplete final voice output inventory")
    for row in inventory:
        clean(row["path"])
        need(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) and row["bytes"] > 0, "invalid generated file binding")


def stage_text_inputs(manifest, request, private_root, v2):
    """Preserve exact already-staged preparation; never overwrite generated data."""
    sid = request["id"]
    piece = v2 / "shorts/voice" / sid
    allowed = {"paragraphs.txt", "names.txt", "source.json"}
    if piece.exists():
        need(all(p.is_file() and not p.is_symlink() and p.name in allowed for p in piece.iterdir()),
             "never overwrite existing builder generated voice/take/RESULT inputs")
    piece.mkdir(parents=True, exist_ok=True)
    wanted = {"shorts/scripts-v2/" + sid + ".md"} | {"shorts/voice/%s/%s" % (sid, n) for n in allowed}
    for row in manifest["files"]:
        rel = row["runtime_path"]
        if rel not in wanted:
            continue
        destination = v2 / rel
        if destination.exists():
            need(destination.is_file() and not destination.is_symlink() and file_sha(destination) == row["sha256"],
                 "builder canonical source/preparation differs")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(private_root / request["private_prefix"] / rel, destination)
    return piece


def hydrate(pointer, request, private_root, work, v2):
    host()
    source_closure()
    need(v2.resolve() == BASE and v2.is_dir(), "existing builder must use its isolated original Ubuntu layout")
    need(not work.exists(), "fresh hosted artifact work directory required")
    run = gh("repos/%s/actions/runs/%s" % (PUBLIC, pointer["run_id"]))
    artifact = gh("repos/%s/actions/artifacts/%s" % (PUBLIC, pointer["artifact_id"]))
    need(artifact.get("digest") == pointer["artifact_digest"], "artifact coordinates changed")
    # Producer source is pinned independently of the consumer's current runtime.
    producer_tree = gh("repos/%s/git/trees/%s?recursive=1" % (PUBLIC, run["head_sha"]))
    need(not producer_tree.get("truncated"), "voice producer source tree incomplete")
    producer_blobs = {r["path"]: r.get("sha") for r in producer_tree["tree"] if r["type"] == "blob"}
    need(all(producer_blobs.get(p) == b for p, b in pointer["producer_git_blobs"].items())
         and WORKFLOW in pointer["producer_git_blobs"], "unqualified voice producer closure")
    work.mkdir(parents=True)
    archive = work / "generated.zip"
    with archive.open("xb") as stream:
        subprocess.run(["gh", "api", "repos/%s/actions/artifacts/%s/zip" % (PUBLIC, artifact["id"])],
                       check=True, stdout=stream, stderr=subprocess.PIPE)
    need("sha256:" + file_sha(archive) == artifact["digest"], "generated artifact digest mismatch")
    unpacked = work / "unpacked"
    unpacked.mkdir()
    if request.get("selection_producer"):
        need(bool(os.environ.get("VOICEFREE_PASS")), "hosted voice decryption key unavailable")
        with zipfile.ZipFile(archive) as z:
            members = [x for x in z.infolist() if not x.is_dir()]
            need(len(members) == 1 and members[0].filename == "voice-generated.enc"
                 and members[0].file_size < 2_000_000_000, "encrypted generated inventory differs")
            encrypted = work / "voice-generated.enc"
            with z.open(members[0]) as src, encrypted.open("xb") as dst:
                shutil.copyfileobj(src, dst)
        plain = work / "voice-generated.tar"
        with plain.open("xb") as stream:
            subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-pass", "env:VOICEFREE_PASS", "-in", str(encrypted)],
                           check=True, stdout=stream, stderr=subprocess.PIPE)
        with tarfile.open(plain, "r:") as tar:
            members = tar.getmembers()
            need(all(m.isfile() or m.isdir() for m in members) and sum(m.size for m in members) < 2_000_000_000,
                 "unsafe generated archive")
            seen = set()
            for item in members:
                name = item.name.removeprefix("./").rstrip("/")
                if name in ("", ".") and item.isdir(): continue
                clean(name)
                need(name not in seen and (name in ("RECEIPT.json", "CURRENT-TRIAGE.json")
                     or name.startswith(("generated/", "effects/"))
                     or item.isdir() and name in ("generated", "effects")), "unexpected generated archive path")
                seen.add(name)
                dest = unpacked / name
                if item.isdir(): dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(item) as src, dest.open("xb") as dst: shutil.copyfileobj(src, dst)
    else:
        with zipfile.ZipFile(archive) as z:
            need(sum(x.file_size for x in z.infolist()) < 2_000_000_000, "voice artifact exceeds bounded size")
            seen = set()
            for item in z.infolist():
                name = item.filename.rstrip("/")
                clean(name)
                need(name not in seen and not stat.S_ISLNK(item.external_attr >> 16), "linked/duplicate voice artifact file")
                seen.add(name)
                need(name in ("RECEIPT.json", "CURRENT-TRIAGE.json") or name.startswith(("generated/", "effects/"))
                     or item.is_dir() and name in ("generated","effects"),
                     "unexpected voice artifact path")
            z.extractall(unpacked)
    receipt = json.loads((unpacked / "RECEIPT.json").read_text())
    validate_completed(receipt, request, run, artifact)
    need(file_sha(unpacked / "RECEIPT.json") == pointer["receipt_sha256"], "native metadata/hosted receipt differs")
    for p in (unpacked / "effects").glob("*.json"):
        state = json.loads(p.read_text()).get("status")
        need(state not in ("EFFECT_UNKNOWN", "CAPACITY_402", "ACCEPTED_PROVIDER_STAGE_FAILED_RECONCILE"),
             "provider effect requires reconciliation")
    actual = {p.relative_to(unpacked / "generated").as_posix() for p in (unpacked / "generated").rglob("*") if p.is_file()}
    need(actual == {r["path"] for r in receipt["generated"]}, "generated inventory missing/extra files")
    for row in receipt["generated"]:
        p = unpacked / "generated" / row["path"]
        need(p.stat().st_size == row["bytes"] and file_sha(p) == row["sha256"], "generated output bytes changed")
    # Builder consumers need exact source/preparation, never Sam's TTS reference.
    # They may sparse-checkout only MANIFEST and these four text files; Git blob
    # metadata still proves every original producer input's immutable identity.
    manifest = private_inputs(request, private_root, verify_media=False)
    sid = request["id"]
    piece = stage_text_inputs(manifest, request, private_root, v2)
    for row in receipt["generated"]:
        # Superseded takes and provider responses stay in the checkpoint, not in
        # the active builder input tree. Only original native final inputs copy.
        rel = row["path"]
        if "/" not in rel and rel.endswith((".wav", ".json")):
            shutil.copyfile(unpacked / "generated" / rel, piece / rel)
    triage_path = unpacked / "CURRENT-TRIAGE.json"
    if triage_path.exists():
        need(file_sha(triage_path) == receipt.get("triage_sha256"), "take-bound triage bytes differ")
        triage = json.loads(triage_path.read_text())
        need(set(triage) <= {sid}, "foreign triage entry")
        # The original lock/merge owner changes only these exact take-bound
        # entries, retaining every other ID; no whole-file overwrite.
        spec = importlib.util.spec_from_file_location("builder_native_triage_store", v2 / "shorts/voice/tooling/triage_store.py")
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        store.update(str(v2 / "shorts/voice"), triage)
    sys.path.insert(0, str(v2 / "shorts/voice/tooling"))
    spec = importlib.util.spec_from_file_location("builder_native_prepare", v2 / "shorts/voice/tooling/prepare.py")
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    need(not prepare.voicelead_prerequisite_issues(str(v2 / "shorts/voice"), sid), "hydrated native prerequisites fail")
    lead = json.loads((piece / (sid + ".voicelead.json")).read_text())
    need(lead.get("id") == sid and lead.get("verdict") == "PASS", "hydrated voicelead not PASS")
    handoff = {"id": sid, "status": "EXACT_VOICE_HYDRATED_FOR_EXISTING_HOSTED_BUILDER",
               "producer_run": run["id"], "artifact_id": artifact["id"], "artifact_digest": artifact["digest"],
               "request_sha256": digest(request), "voice_sha256": file_sha(piece / (sid + ".wav")),
               "words_sha256": file_sha(piece / (sid + ".words.json")), "listening_review": lead.get("listening_review"),
               "build_short_executed": False, "builder_ready": False,
               "storyboard_approved": False, "release_approved": False}
    (work / "VOICE-HANDOFF.json").write_text(json.dumps(handoff, indent=2) + "\n")
    return handoff


def main():
    ap = argparse.ArgumentParser()
    for key in ("pointer", "request", "private-root", "work", "v2"):
        ap.add_argument("--" + key, type=Path, required=True)
    a = ap.parse_args()
    hydrate(json.loads(a.pointer.read_text()), json.loads(a.request.read_text()), a.private_root, a.work, a.v2)


if __name__ == "__main__":
    main()
