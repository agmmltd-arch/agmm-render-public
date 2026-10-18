#!/usr/bin/env python3
"""Ubuntu-only export of exact accepted native takes after a KNOWN 402.

No provider calls, dispatch or native state changes. Root can transport these
verified take files through its protected uploader, then request a fresh native
admission AFTER real capacity is restored. Unknown effects are never resumable.
The unchanged gen_paragraphs cache check independently revalidates every take.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import zipfile
from voice_effects import host
from voice_hosted import PUBLIC, WORKFLOW, clean, digest, file_sha, gh, need, source_closure


def extract(pointer, paragraphs, output):
    host()
    source_closure()
    need(not output.exists(), "fresh protected checkpoint export required")
    run = gh("repos/%s/actions/runs/%s" % (PUBLIC, pointer["run_id"]))
    artifact = gh("repos/%s/actions/artifacts/%s" % (PUBLIC, pointer["artifact_id"]))
    need(run["path"] == WORKFLOW and run["head_sha"] == pointer["runtime_commit"]
         and run["run_attempt"] == 1 and run["status"] == "completed"
         and run["conclusion"] == "failure", "checkpoint producer not an exact failed first attempt")
    tree = gh("repos/%s/git/trees/%s?recursive=1" % (PUBLIC, run["head_sha"]))
    blobs = {r["path"]: r.get("sha") for r in tree["tree"] if r["type"] == "blob"}
    need(not tree.get("truncated") and WORKFLOW in pointer["producer_git_blobs"]
         and all(blobs.get(p) == b for p, b in pointer["producer_git_blobs"].items()), "checkpoint producer unqualified")
    need(artifact["digest"] == pointer["artifact_digest"] and not artifact["expired"]
         and artifact["workflow_run"]["id"] == run["id"]
         and artifact["name"] == pointer["intent"] + "-GENERATED", "checkpoint artifact differs")
    output.mkdir(parents=True)
    archive = output / "checkpoint.zip"
    with archive.open("xb") as stream:
        subprocess.run(["gh", "api", "repos/%s/actions/artifacts/%s/zip" % (PUBLIC, artifact["id"])],
                       check=True, stdout=stream, stderr=subprocess.PIPE)
    need("sha256:" + file_sha(archive) == artifact["digest"], "checkpoint ZIP digest differs")
    unpacked = output / "checkpoint"
    with zipfile.ZipFile(archive) as z:
        names = []
        need(sum(r.file_size for r in z.infolist()) < 2_000_000_000, "checkpoint too large")
        for item in z.infolist():
            name = item.filename.rstrip("/")
            clean(name)
            need(not stat.S_ISLNK(item.external_attr >> 16) and name not in names, "linked/duplicate checkpoint member")
            need(name in ("RECEIPT.json", "CURRENT-TRIAGE.json") or name.startswith(("effects/", "generated/"))
                 or item.is_dir() and name in ("generated","effects"), "foreign checkpoint member")
            names.append(name)
        z.extractall(unpacked)
    receipt = json.loads((unpacked / "RECEIPT.json").read_text())
    need(receipt["status"] == "CAPACITY_402" and receipt["id"] == pointer["id"]
         and receipt["intent"] == pointer["intent"] and receipt["request_sha256"] == pointer["request_sha256"]
         and file_sha(unpacked / "RECEIPT.json") == pointer["receipt_sha256"], "checkpoint receipt differs")
    effects = [json.loads(p.read_text()) for p in (unpacked / "effects").glob("[0-9][0-9][0-9][0-9].json")]
    need(effects and any(e.get("status") == "CAPACITY_402" and e.get("http_status") == 402 for e in effects)
         and all(e.get("status") in ("ACCEPTED", "REJECTED", "CAPACITY_402") for e in effects),
         "checkpoint contains unknown effects; never retry")
    rows = {r["path"]: r for r in receipt["generated"]}
    actual = {p.relative_to(unpacked/"generated").as_posix() for p in (unpacked/"generated").rglob("*") if p.is_file()}
    need(len(rows)==len(receipt["generated"]) and actual==set(rows), "checkpoint generated inventory differs")
    for rel, row in rows.items():
        clean(rel)
        p = unpacked / "generated" / rel
        need(p.is_file() and p.stat().st_size == row["bytes"] and file_sha(p) == row["sha256"], "checkpoint body differs")
    paras = [p.strip() for p in paragraphs.read_text().strip().split("\n\n") if p.strip()]
    accepted = []
    target = output / "protected-takes"
    target.mkdir()
    for index, text in enumerate(paras, 1):
        stem = "P%02d" % index
        names = [stem + suffix for suffix in (".wav", ".receipt.json", ".words.json")]
        if not all(name in rows for name in names):
            continue
        old = json.loads((unpacked / "generated" / names[1]).read_text())
        need(old.get("input_sha256") == hashlib.sha256(text.encode()).hexdigest()
             and old.get("wav_sha256") == rows[names[0]]["sha256"]
             and old.get("asr_status") == "checked" and old.get("asr_match") is True,
             "take is not eligible for unchanged native cached acceptance")
        for name in names:
            shutil.copyfile(unpacked / "generated" / name, target / name)
            accepted.append(dict(rows[name], runtime_path="shorts/voice/%s/%s" % (pointer["id"], name)))
    result = {"id": pointer["id"], "producer_run": run["id"], "artifact_id": artifact["id"],
              "artifact_digest": artifact["digest"], "status": "KNOWN_CAPACITY_CHECKPOINT_EXPORTED",
              "accepted_files": accepted, "capacity_restored": False, "provider_called": False,
              "fresh_native_cap_admission_required": True, "original_quality_checks_unchanged": True,
              "source_request_sha256": pointer["request_sha256"]}
    (output / "CHECKPOINT-EXPORT.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pointer", type=Path, required=True)
    ap.add_argument("--paragraphs", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    extract(json.loads(a.pointer.read_text()), a.paragraphs, a.output)
