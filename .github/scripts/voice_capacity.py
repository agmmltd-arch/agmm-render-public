"""Exact JSON-only reconciliation of a known Mistral 402; no retry authority.

An unknown effect, started-but-missing receipt or absent artifact never becomes a
capacity proof. Separate root-owned actual capacity-restoration evidence and a
fresh original native admission are required before any continuation.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

PUBLIC = "agmmltd-arch/agmm-render-public"
WORKFLOW = ".github/workflows/agmm-short-voice.yml"


def need(value, why):
    if not value:
        raise ValueError(why)


def api(path):
    return json.loads(subprocess.run(["gh", "api", path], capture_output=True, text=True,
                                     check=True, timeout=60).stdout)


def prove_capacity(run_id, producer_git_blobs):
    run = api("repos/%s/actions/runs/%s" % (PUBLIC, run_id))
    need(run["status"] == "completed" and run["conclusion"] == "failure"
         and run["run_attempt"] == 1 and run["path"] == WORKFLOW, "not a completed exact capacity producer")
    tree = api("repos/%s/git/trees/%s?recursive=1" % (PUBLIC, run["head_sha"]))
    blobs = {r["path"]: r.get("sha") for r in tree["tree"] if r["type"] == "blob"}
    need(not tree.get("truncated") and WORKFLOW in producer_git_blobs
         and all(blobs.get(p) == b for p, b in producer_git_blobs.items()), "unqualified capacity producer")
    intent = run["display_title"].removeprefix("AGMM native voice ")
    artifacts = api("repos/%s/actions/runs/%s/artifacts?per_page=100" % (PUBLIC, run_id))["artifacts"]
    selected = [a for a in artifacts if a["name"] == intent + "-JSON" and not a["expired"]
                and a.get("workflow_run", {}).get("id") == run["id"]]
    generated = [a for a in artifacts if a["name"] == intent + "-GENERATED" and not a["expired"]
                 and a.get("workflow_run", {}).get("id") == run["id"]]
    need(len(selected) == len(generated) == 1, "exact capacity checkpoint artifacts missing")
    with tempfile.TemporaryDirectory(prefix="agmm-capacity-json-") as temp:
        subprocess.run(["gh", "run", "download", str(run_id), "--repo", PUBLIC,
                        "--name", intent + "-JSON", "--dir", temp], check=True, capture_output=True, timeout=60)
        files = list(Path(temp).iterdir())
        need(files and all(p.is_file() and not p.is_symlink() and p.suffix == ".json"
             and p.name in {"RECEIPT.json", "EFFECTS.json", "CURRENT-TRIAGE.json", "RESULT.json"}
                  | {intent.split("-")[1] + ".voicelead.json"}
             and p.stat().st_size < 2_000_000 for p in files), "unexpected capacity metadata inventory")
        raw = (Path(temp) / "RECEIPT.json").read_bytes()
        receipt = json.loads(raw)
        effects = json.loads((Path(temp) / "EFFECTS.json").read_text())
    operations = [e for e in effects if "operation" in e and e.get("operation") is not None]
    need(receipt["status"] == "CAPACITY_402" and receipt["intent"] == intent
         and receipt["runtime_commit"] == run["head_sha"] and str(receipt["run_id"]) == str(run_id)
         and receipt["run_attempt"] == "1" and operations
         and not any(e.get("status") in ("EFFECT_UNKNOWN", "ACCEPTED_PROVIDER_STAGE_FAILED_RECONCILE") for e in effects)
         and any(e.get("status") == "CAPACITY_402" and e.get("http_status") == 402 for e in operations)
         and all(e.get("status") in ("ACCEPTED", "REJECTED", "CAPACITY_402") for e in operations),
         "missing explicit 402 or unknown provider effects")
    return {"status": "RECONCILED_KNOWN_CAPACITY", "id": receipt["id"], "intent": intent,
            "run_id": run["id"], "runtime_commit": run["head_sha"],
            "producer_git_blobs": producer_git_blobs, "request_sha256": receipt["request_sha256"],
            "receipt_sha256": hashlib.sha256(raw).hexdigest(),
            "artifact_id": generated[0]["id"], "artifact_digest": generated[0]["digest"],
            "native_inputs": receipt["native_inputs"], "capacity_restored": False,
            "retry_authorised": False}
