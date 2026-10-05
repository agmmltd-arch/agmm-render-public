#!/usr/bin/env python3
"""Exact staging-head, current-main, native-preimage, and payload-closure guard."""
import hashlib,json,os,subprocess,sys,urllib.request
from pathlib import Path
MANIFEST=Path(".github/candidates/free-av-qualification/candidate-manifest.json")
class Refused(RuntimeError): pass

def main():
 m=json.loads(MANIFEST.read_text(encoding="utf-8"))
 expected=os.environ.get("EXPECTED_CANDIDATE_COMMIT","").strip()
 event=os.environ.get("GITHUB_SHA","").strip()
 head=subprocess.run(["git","rev-parse","HEAD"],check=True,capture_output=True,text=True).stdout.strip()
 if not expected or expected!=event or event!=head: raise Refused("dispatch must pin exact candidate commit; moving ref refused")
 parent=m["publication_map"]["expected_public_head_sha"]
 req=urllib.request.Request("https://api.github.com/repos/agmmltd-arch/agmm-render-public/commits/main",headers={"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"})
 with urllib.request.urlopen(req,timeout=20) as r: current=json.loads(r.read())
 if current["sha"]!=parent or current["commit"]["tree"]["sha"]!=m["publication_map"]["expected_public_tree_sha"]:
  raise Refused("public main moved from exact native preimage; candidate map is stale")
 paths=[x["path"] for x in m["publication_map"]["destinations"]]
 if len(paths)!=len(set(paths)): raise Refused("candidate map contains duplicate paths")
 if any(x.get("preimage")!={"state":"absent"} or x.get("operation")!="create" for x in m["publication_map"]["destinations"]):
  raise Refused("candidate installation is not exact all-create closure")
 for path,digest in m["candidate_files"].items():
  data=Path(path).read_bytes()
  if hashlib.sha256(data).hexdigest()!=digest: raise Refused("runtime file differs from frozen candidate manifest: "+path)
 if set(m["candidate_files"])!=set(paths)-{".github/candidates/free-av-qualification/candidate-manifest.json"}:
  raise Refused("publication destinations do not exactly equal runtime closure plus manifest")
 print("PASS exact staging commit; current public main/tree; all-create path map; complete candidate SHA-256 closure")
if __name__=="__main__": main()
