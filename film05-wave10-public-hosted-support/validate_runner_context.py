#!/usr/bin/env python3
"""Refuse runner.* expressions in job-level env; require first-step GITHUB_ENV initialization."""
from pathlib import Path
import re
import sys

RUNNER_CONTEXT=re.compile(r"(?:\$\{\{\s*runner\.|\bRUNNER_TEMP\b|\bGITHUB_ENV\b)",re.I)

def validate(text: str) -> None:
    lines=text.splitlines()
    job_ranges=[]
    jobs_start=next((i for i,line in enumerate(lines) if line=="jobs:"),None)
    if jobs_start is None: raise ValueError("workflow has no jobs section")
    i=jobs_start+1
    while i<len(lines):
        if lines[i] and not lines[i][0].isspace(): break
        if re.match(r"^  [A-Za-z0-9_-]+:\s*$",lines[i]):
            start=i; j=i+1
            while j<len(lines) and (not lines[j] or lines[j][0].isspace()):
                if re.match(r"^  [A-Za-z0-9_-]+:\s*$",lines[j]): break
                j+=1
            job_ranges.append((start,j))
            i=j
        else: i+=1
    if not job_ranges: raise ValueError("workflow has no job mappings")
    for start,end in job_ranges:
        job=lines[start:end]
        for n,line in enumerate(job):
            if re.match(r"^    env:\s*$",line):
                k=n+1
                while k<len(job) and (not job[k] or len(job[k])-len(job[k].lstrip())>4):
                    if RUNNER_CONTEXT.search(job[k]):
                        raise ValueError("runner context or runner-local variables are unavailable in job-level env")
                    k+=1
                env_text="\n".join(job[n+1:k])
                if re.search(r"^\s+(?:PRIVATE_SCRATCH|PUBLIC_PAYLOAD):",env_text,re.M):
                    raise ValueError("runner-local paths must not be assigned in job-level env")
    steps_start=next((i for i,line in enumerate(lines) if line=="    steps:"),None)
    if steps_start is None: raise ValueError("workflow job has no steps")
    first_step=next((line.strip() for line in lines[steps_start+1:] if re.match(r"^      - name:",line)),None)
    if first_step != "- name: Initialize runner-local paths":
        raise ValueError("RUNNER_TEMP/GITHUB_ENV initializer must be the first step")
    init_start=next((i for i,line in enumerate(lines) if line.strip()=="- name: Initialize runner-local paths"),None)
    if init_start is None: raise ValueError("first-step runner path initializer is missing")
    init=[]
    for line in lines[init_start+1:]:
        if re.match(r"^      - name:",line): break
        init.append(line)
    block="\n".join(init)
    for token in ("$RUNNER_TEMP", "$GITHUB_ENV", "PRIVATE_SCRATCH", "PUBLIC_PAYLOAD"):
        if token not in block: raise ValueError(f"runner path initializer does not export {token}")
    print("RUNNER_CONTEXT_GATE_PASS: runner paths are initialized from RUNNER_TEMP at step scope")

if __name__=="__main__":
    if len(sys.argv)!=2: raise SystemExit("usage: validate_runner_context.py WORKFLOW.yml")
    validate(Path(sys.argv[1]).read_text(encoding="utf-8"))
