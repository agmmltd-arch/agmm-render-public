#!/usr/bin/env python3
"""Sealed source pins and early runtime guards for hosted full audiovisual qualification."""
from __future__ import annotations
import hashlib,json,os,platform,urllib.request
from pathlib import Path
MODEL="gemini-3.8-flash"
KEY_NAME="AGMM_GEMINI_FREE_REVIEW_KEY"
QA="?utm_source=qa&utm_campaign=qa_release_audit"
ASSETS = {
  "P1-r7-published-web": {"url": "https://agmm-content-share.pages.dev/media/P1-0ed30928dcd7"+QA, "bytes": 38040764, "sha256": "0ed30928dcd77ba3fbc565e832a0e31064c11a2f308e3d0a863956cc07f3277e", "duration_s": 58.9, "lineage": "P1 FINAL-web; BUILD-NOTES identifies approved r7 final; exact published web bytes"},
  "P2-corrected-audio-v2": {"url": "https://agmm-content-share.pages.dev/media/P2-1d6ec1c4a20e"+QA, "bytes": 237283443, "sha256": "1d6ec1c4a20eb1a3b8f1c7e21d96712b823f1b8532b6750b5fd964af47d17226", "duration_s": 59.7, "lineage": "P2 corrected audio-v2 published candidate; not original defective mix"},
  "P3-corrected-audio-v2": {"url": "https://agmm-content-share.pages.dev/media/P3-ef449e83f2b8"+QA, "bytes": 48825636, "sha256": "ef449e83f2b8c6b7f75e836cd9bcc0e65a231efc8e7f264f58f602d660ab391b", "duration_s": 58.4, "lineage": "P3 corrected audio-v2 published candidate; not original defective mix"},
}

class Refused(RuntimeError): pass

def runtime_key(env=None,system=None):
 env=os.environ if env is None else env
 system=platform.system() if system is None else system
 if str(system).strip().lower()!="linux" or env.get("GITHUB_ACTIONS","").strip().lower() not in ("true","1") or env.get("FLEET_FREE_ONLY","").strip()!="1":
  raise Refused("requires hosted GitHub Actions Linux and FLEET_FREE_ONLY=1")
 if env.get("GEMINI_WATCH_VERTEX","").strip().lower() in ("1","true","yes","on") or env.get("GEMINI_VERTEX_PROJECT","").strip():
  raise Refused("Vertex route is forbidden")
 key=env.get(KEY_NAME)
 if not isinstance(key,str) or not key.strip(): raise Refused("required hosted Free-project secret is absent")
 if env.get("AGMM_GEMINI_FREE_PROJECT_ID","").strip()!="gen-lang-client-0105607923":
  raise Refused("configured project ID is not the Sam-confirmed billing-disabled Free project")
 if env.get("AGMM_GEMINI_BILLING_DISABLED","").strip().lower()!="true" or env.get("AGMM_GEMINI_FREE_TIER","").strip().lower()!="true":
  raise Refused("Free billing-disabled project provenance gate is not satisfied")
 return key

def sha256_file(path):
 runtime_key(); h=hashlib.sha256()
 with open(path,"rb") as stream:
  for block in iter(lambda:stream.read(1<<20),b""): h.update(block)
 return h.hexdigest()

def download_verified(asset,out,opener=urllib.request.urlopen):
 runtime_key()
 if not asset.get("url","").endswith(QA): raise Refused("source URL must carry QA tracking")
 req=urllib.request.Request(asset["url"],headers={"User-Agent":"S83-free-av-qualification/1"})
 total=0; digest=hashlib.sha256()
 with opener(req,timeout=90) as response,open(out,"wb") as stream:
  while True:
   block=response.read(1<<20)
   if not block: break
   total+=len(block)
   if total>asset["bytes"]: raise Refused("hosted source exceeds pinned byte size")
   digest.update(block); stream.write(block)
 if total!=asset["bytes"] or digest.hexdigest()!=asset["sha256"]: raise Refused("hosted source size/SHA-256 mismatch")
 return {"bytes":total,"sha256":digest.hexdigest()}
