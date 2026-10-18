"""Metadata-only proof that the sole native provider step never started.

Authoritative completed Actions jobs plus an explicitly qualified immutable
workflow are required. Missing output artifacts or a failed job alone prove
nothing. A native/provider step that started remains reconciliation-only.
"""
import hashlib
import json

PROVIDER_STEP = "Run unchanged native chain and exact-bound voicelead on Ubuntu"


def prove_no_effect(run, jobs, workflow_blob, allowed_workflow_blobs, *,
                    workflow=".github/workflows/agmm-short-voice.yml", job_name="voice", step=PROVIDER_STEP):
    def need(value, why):
        if not value:
            raise ValueError(why)
    need(workflow_blob in allowed_workflow_blobs, "prior workflow has no qualified no-effect boundary")
    need(run.get("status") == "completed" and run.get("conclusion") in ("failure", "cancelled", "skipped")
         and run.get("run_attempt") == 1 and run.get("event") == "workflow_dispatch"
         and run.get("path") == workflow, "prior run identity/outcome not eligible")
    need(jobs.get("total_count") == len(jobs.get("jobs", [])) <= 1, "incomplete/foreign job inventory")
    for job in jobs["jobs"]:
        need(job.get("run_id") == run["id"] and job.get("run_attempt") == 1
             and job.get("name") == job_name and job.get("status") == "completed", "foreign or unfinished job")
        steps = job.get("steps", [])
        target = [s for s in steps if s.get("name") == step]
        need(len(target) <= 1, "ambiguous native provider step")
        if target:
            need(target[0].get("conclusion") == "skipped",
                 "native/provider step may have started")
        else:
            # The complete authoritative step list ends after an earlier failed
            # setup/checkout/identity step. Those exact qualified steps perform
            # no native chain or provider request; optional identity comparisons
            # only hash in memory and emit booleans.
            need(steps and any(s.get("conclusion") in ("failure", "cancelled") for s in steps)
                 and any(s.get("name") == "Complete job" and s.get("status") == "completed" for s in steps),
                 "absence of a provider step is not yet a completed no-effect proof")
    summary = {"run_id": run["id"], "runtime_commit": run["head_sha"],
               "workflow_blob": workflow_blob, "status": "RECONCILED_NO_EFFECT",
               "provider_step_started": False,
               "jobs_sha256": hashlib.sha256(json.dumps(jobs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    return summary
