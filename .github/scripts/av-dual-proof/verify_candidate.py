#!/usr/bin/env python3
"""Guard the installed main commit, its exact native parent, and the complete candidate closure."""
import hashlib,json,os,subprocess,urllib.request
from pathlib import Path
MANIFEST=Path(".github/candidates/free-av-qualification/candidate-manifest.json")
class Refused(RuntimeError): pass

def verify_snapshot(m,expected,event,ref,head,head_tree,parent,parent_tree,remote_main,remote_tree,parent_entries,current_paths,file_bytes):
 if ref!="refs/heads/main": raise Refused("qualification workflow must run from installed main")
 if not expected or expected!=event or event!=head or head!=remote_main:
  raise Refused("expected candidate, event SHA, checkout HEAD and live main must be identical")
 publication=m["publication_map"]
 if head_tree!=remote_tree: raise Refused("installed checkout tree differs from live main tree")
 if parent!=publication["expected_public_head_sha"] or parent_tree!=publication["expected_public_tree_sha"]:
  raise Refused("installed commit first parent/tree differs from frozen native preimage")
 destinations=publication["destinations"]
 paths=[x.get("path") for x in destinations]
 if len(paths)!=8 or len(set(paths))!=8: raise Refused("candidate map must contain eight unique native paths")
 for item in destinations:
  path=item["path"];operation=item.get("operation");preimage=item.get("preimage")
  actual=parent_entries.get(path)
  if operation=="create":
   if preimage!={"state":"absent"} or actual is not None: raise Refused("create preimage changed: "+path)
  elif operation=="update":
   if not isinstance(preimage,dict) or preimage.get("state")!="blob" or not preimage.get("git_blob_sha") or not preimage.get("mode"):
    raise Refused("update map lacks exact blob/mode preimage: "+path)
   if actual!={"git_blob_sha":preimage["git_blob_sha"],"mode":preimage["mode"]}:
    raise Refused("existing native preimage changed: "+path)
  else: raise Refused("unsupported publication operation: "+str(operation))
 if not set(paths).issubset(current_paths): raise Refused("installed main is missing one or more candidate paths")
 manifest_path=".github/candidates/free-av-qualification/candidate-manifest.json"
 candidate_files=m.get("candidate_files",{})
 if set(candidate_files)!=set(paths)-{manifest_path} or set(file_bytes)!=set(candidate_files):
  raise Refused("candidate runtime closure does not exactly match publication map")
 for path,digest in candidate_files.items():
  if hashlib.sha256(file_bytes[path]).hexdigest()!=digest:
   raise Refused("runtime file differs from manifest SHA-256: "+path)
 return True

def git_text(*args):
 p=subprocess.run(["git",*args],check=True,capture_output=True,text=True)
 return p.stdout

def main():
 m=json.loads(MANIFEST.read_text(encoding="utf-8"))
 expected=os.environ.get("EXPECTED_CANDIDATE_COMMIT","").strip()
 event=os.environ.get("GITHUB_SHA","").strip()
 ref=os.environ.get("GITHUB_REF","").strip()
 head=git_text("rev-parse","HEAD").strip()
 parent=git_text("rev-parse","HEAD^").strip()
 parent_tree=git_text("rev-parse",parent+"^{tree}").strip()
 head_tree=git_text("rev-parse",head+"^{tree}").strip()
 parents=git_text("rev-list","--parents","-n","1","HEAD").strip().split()
 if len(parents)!=2 or parents[1]!=parent: raise Refused("installed commit must have exactly one verified parent")
 current_paths=set(git_text("ls-tree","-r","--name-only","HEAD").splitlines())
 parent_entries={}
 for line in git_text("ls-tree","-r",parent).splitlines():
  meta,path=line.split("\t",1)
  mode,kind,sha=meta.split()
  if kind=="blob": parent_entries[path]={"git_blob_sha":sha,"mode":mode}
 req=urllib.request.Request("https://api.github.com/repos/agmmltd-arch/agmm-render-public/commits/main",headers={"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"})
 with urllib.request.urlopen(req,timeout=20) as response: current=json.loads(response.read())
 file_bytes={path:Path(path).read_bytes() for path in m["candidate_files"]}
 verify_snapshot(m,expected,event,ref,head,head_tree,parent,parent_tree,current["sha"],current["commit"]["tree"]["sha"],parent_entries,current_paths,file_bytes)
 print("PASS installed-main SHA/ref; exact first-parent tree; eight exact create/update native preimages; seven runtime hashes")
if __name__=="__main__": main()
