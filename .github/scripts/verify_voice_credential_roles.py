#!/usr/bin/env python3
"""Non-provider comparison against root's private native-key expectations.

Expected fingerprints may enter only in the workflow request. Actual/expected
fingerprints and secret values are never returned, logged or written. This
verifies key identity only; root separately verifies the existing free project.
"""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from voice_effects import host
from voice_hosted import need, source_closure

SLOTS = {"AGMM_MISTRAL_KEY":("MISTRAL_KEY","AGMM_VOICE_MISTRAL_KEY"),
         "AGMM_GEMINI_FREE_REVIEW_KEY":("GEMINI_KEY_B","AGMM_VOICE_GEMINI_FREE_KEY")}


def compare(expected, environment):
    need(set(expected)==set(SLOTS) and all(re.fullmatch(r"[0-9a-f]{64}",v or "") for v in expected.values()),
         "complete root-supplied native identity expectations required")
    roles={}
    for name,(slot,env_name) in SLOTS.items():
        value=environment.get(env_name,"")
        match=bool(value) and hmac.compare_digest(hashlib.sha256(value.encode()).hexdigest(),expected[name])
        roles[name]={"native_slot":slot,"present":bool(value),"exact_existing_native_match":match,
                     "source":"existing Actions secret; root-supplied native expectation",
                     "provider_called":False}
    return roles


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--request",type=Path,required=True);ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--require-match",action="store_true")
    a=ap.parse_args();host();source_closure()
    r=json.loads(a.request.read_text())
    expected=r.get("expected_credential_sha256")
    if expected is None:
        expected={name:role["expected_sha256"] for name,role in r.get("credential_roles",{}).items() if name in SLOTS}
    roles=compare(expected,os.environ)
    complete=all(v["exact_existing_native_match"] for v in roles.values())
    report={"status":"EXACT_EXISTING_CREDENTIAL_IDENTITIES_MATCH" if complete else "CREDENTIAL_IDENTITIES_INCOMPLETE_OR_DIFFERENT",
            "roles":roles,"runtime_commit":os.environ["GITHUB_SHA"],"run_id":os.environ["GITHUB_RUN_ID"],
            "run_attempt":os.environ["GITHUB_RUN_ATTEMPT"],"provider_calls":0,
            "fingerprints_emitted":False,"credential_values_emitted":False,"free_project_verified":False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+"\n")
    if a.require_match:need(complete,"existing native runner credential identity differs; no provider effect")


if __name__=="__main__":main()
