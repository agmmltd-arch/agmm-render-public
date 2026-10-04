#!/usr/bin/env python3
"""Ubuntu-only durable review export of an exact corrected S86 1080 master."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, re, shutil, tempfile, urllib.error, urllib.parse, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
REPO="agmmltd-arch/agmm-render-public"; PARENT_SOURCE_SHA="666a90579d57f2bd5c2abed41e55b5dad3fff790f93707d79b2929bddf1c93b6"; PARENT_PARTS_SHA="e995d9d0354b808714bf89e2a082a98200a8ef92733d1896181635dfecffbb88"; PARENT_MIX_SHA="0c252cdf6e412fc2ccadcdb29b940d6a23b7c527276ebf79da468b7f633df436"; PARENT_RECEIPT_SHA="ef1db9c644b0e4c59f5d087deb2e858e052f4c98f56dad3cdc630378c2d5f26f"; EXPECTED_PARTS=[
 {"look":"s86-a","file":"index.html","out":"S86-A","off":0.0,"dur":15.166666666666666},
 {"look":"s86-b","file":"index.html","out":"S86-B","off":15.166666666666666,"dur":15.166666666666666},
 {"look":"s86-c","file":"index.html","out":"S86-C","off":30.333333333333332,"dur":15.166666666666666},
 {"look":"s86-d","file":"index.html","out":"S86-D","off":45.5,"dur":15.1},
]
OPEN_STATUS={"editorial_status":"NOT_REVIEWED","full_master_visual_review":"OPEN","every_frame_and_motion_review":"OPEN","audio_and_narration_listening":"OPEN","pilot_level_craft_review":"OPEN","thumbnail_review":"OPEN","ready_approval":"NOT_GRANTED","release_approval":"NOT_GRANTED","full_playback_verified":False}
class ExportError(ValueError): pass
def need(ok,msg):
 if not ok: raise ExportError(msg)
def sha(b): return hashlib.sha256(b).hexdigest()
def file_sha(p):
 h=hashlib.sha256(); n=0
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""): h.update(b); n+=len(b)
 return h.hexdigest(),n
def require_hosted(env:Mapping[str,str],system:str):
 need(system=="Linux" and env.get("RUNNER_OS")=="Linux" and env.get("GITHUB_ACTIONS")=="true","public GitHub Actions Ubuntu only")
 need(env.get("GITHUB_REPOSITORY")==REPO and env.get("GITHUB_REF")=="refs/heads/main" and env.get("GITHUB_EVENT_NAME")=="workflow_dispatch","manual main dispatch in public render repo required")
 need(bool(re.fullmatch(r"[0-9a-f]{40}",env.get("GITHUB_SHA",""))),"invalid export workflow commit")
def validate_repo_main(repo,ref,sha):
 need(repo.get("full_name")==REPO and repo.get("private") is False and repo.get("visibility")=="public","repository not public render repo")
 need(isinstance(ref.get("object"),dict) and ref["object"].get("sha")==sha,"export workflow is not current main")
def validate_run(run,run_id):
 need(run.get("id")==run_id and run.get("event")=="workflow_dispatch" and run.get("status")=="completed" and run.get("conclusion")=="success","render run not exact completed successful manual run")
 need(run.get("head_branch")=="main" and run.get("path")==".github/workflows/agmm-short-package.yml","run is not public short-package workflow on main")
 need(isinstance(run.get("head_sha"),str) and re.fullmatch(r"[0-9a-f]{40}",run["head_sha"]),"render run head SHA missing")
def validate_artifact(row, artifact_id, run_id, label, run_head_sha):
 wr=row.get("workflow_run",{})
 need(type(row.get("id")) is int and row["id"]==artifact_id and row.get("expired") is False and wr.get("id")==run_id and wr.get("head_sha")==run_head_sha,f"{label} artifact identity/expiry/run/head mismatch")
 need(isinstance(row.get("name"),str) and isinstance(row.get("size_in_bytes"),int) and row["size_in_bytes"]>0,f"{label} artifact metadata malformed")
 suffix="-EXACT-INPUT" if label=="input" else "-FINAL-MASTERS"
 need(row["name"].startswith("S86-") and row["name"].endswith(suffix),f"{label} artifact name is not the exact S86 render product")
 d=row.get("digest"); need(isinstance(d,str) and re.fullmatch(r"sha256:[0-9a-f]{64}",d),f"{label} native digest missing")
 exp=row.get("expires_at"); need(isinstance(exp,str),f"{label} expiry missing")
 dt=datetime.fromisoformat(exp.replace("Z","+00:00")); need(dt.tzinfo is not None and (dt-datetime.now(timezone.utc)).total_seconds()>900,f"{label} artifact expired/near expiry")
def validate_absence(status,body):
 need(status==404,f"exact tag absence requires HTTP 404; got {status}")
 if body not in (None,{},""): need(isinstance(body,dict) and body.get("message")=="Not Found","HTTP 404 body is not exact GitHub Not Found")
INITIAL_FILES={"S86-FOLLOW-CORRECTED-1080.mp4","INPUT-RECEIPT.json","TECHNICAL-EVIDENCE.json","SOURCE-LINEAGE.json","REVIEW-PLAYBACK-RECEIPT.json","SHA256SUMS.txt"}
FINAL_FILES=INITIAL_FILES|{"PLAYBACK-TRANSPORT-VERIFICATION.json","HOSTED-MEDIA-MANIFEST.json"}
def asset_inventory(directory:Path,finalized=False):
 expected=FINAL_FILES if finalized else INITIAL_FILES
 files={p.name:p for p in directory.iterdir() if p.is_file()}
 need(set(files)==expected,"export stage contents differ from exact review-release allowlist")
 assets={}
 for name,p in files.items():
  d,n=file_sha(p); assets[name]={"size":n,"digest":"sha256:"+d}
 return assets
def _zip_members(path,kind):
 out={}; total=0
 with zipfile.ZipFile(path) as z:
  for i in z.infolist():
   raw=i.filename
   if raw.endswith("/"): continue
   p=PurePosixPath(raw); mode=(i.external_attr>>16)&0xffff
   need("\\" not in raw and not p.is_absolute() and ".." not in p.parts and p.parts,"unsafe ZIP path")
   need(not mode or mode&0o170000 in (0,0o100000),"ZIP contains symlink/non-regular member")
   base=p.name; need(base not in out,f"duplicate ZIP basename {base}")
   if kind=="input": need(len(p.parts)==1 and base in {"INPUT-RECEIPT.json","MATRIX.json","NORMALISED-PARTS.json","source.tar.gz","parts.json","mix.wav"},"unexpected input ZIP member")
   else: need(len(p.parts)==1 and base in {"FINAL.mp4","FINAL-4K.mp4","TECHNICAL-EVIDENCE.json","SHA256SUMS.txt"},"unexpected output ZIP member")
   total+=i.file_size; need(total<=600_000_000,"ZIP expanded size over bound")
   out[base]=i
 return path,out

def read_member(path,info,limit=3_000_000):
 need(info.file_size<=limit,"text member exceeds receipt bound")
 with zipfile.ZipFile(path) as z: return z.read(info)
def hash_zip_member(path,info,limit):
 need(info.file_size<=limit,"ZIP media member exceeds explicit size bound")
 h=hashlib.sha256(); n=0
 with zipfile.ZipFile(path) as z, z.open(info) as src:
  for block in iter(lambda:src.read(1<<20),b""): h.update(block); n+=len(block)
 need(n==info.file_size,"ZIP media member size mismatch")
 return h.hexdigest(),n
def copy_zip_member(path,info,destination,limit,expected_digest):
 need(info.file_size<=limit,"ZIP master exceeds explicit size bound")
 h=hashlib.sha256(); n=0
 with zipfile.ZipFile(path) as z, z.open(info) as src, destination.open("wb") as dst:
  for block in iter(lambda:src.read(1<<20),b""): dst.write(block); h.update(block); n+=len(block)
 need(n==info.file_size and h.hexdigest()==expected_digest,"copied master bytes differ from verified archive member")
 return h.hexdigest(),n
def verify_zip_digest(path,row):
 digest,size=file_sha(path); need(size==row["size_in_bytes"] and "sha256:"+digest==row["digest"],"downloaded artifact ZIP differs from native metadata")
def validate_input_receipt(receipt,source_receipt,parts):
 need(isinstance(receipt,dict) and receipt.get("kind")=="agmm_short_exact_input_receipt","input producer receipt missing")
 need(receipt.get("source_sha256")==source_receipt.get("corrected",{}).get("source_sha256") and receipt.get("source_bytes")==source_receipt.get("corrected",{}).get("source_bytes"),"input source hash/size differs from sealed source")
 need(receipt.get("parts_sha256")==source_receipt.get("corrected",{}).get("parts_sha256") and receipt.get("parts_bytes")==source_receipt.get("corrected",{}).get("parts_bytes"),"input part metadata differs from corrected parts asset")
 need(receipt.get("mix_sha256")==source_receipt.get("corrected",{}).get("mix_sha256"),"input mix differs from seal receipt")
 need(receipt.get("duration")==60.6 and receipt.get("frames")==1818 and receipt.get("part_count")==4 and receipt.get("render_4k") is True,"render input contract differs from 60.6s full 1080 S86")
 need(parts.get("parts")==EXPECTED_PARTS,"corrected render parts drift")
def validate_source_provenance(parent_release,source_release,source_receipt,parts,mix_sha):
 need(parent_release.get("id")==402788582 and parent_release.get("node_id")=="RE_kwDOU05Rms4YAhDm" and parent_release.get("tag_name")=="S86-source-quote-37171207319","wrong immutable source parent")
 parent_rows=parent_release.get("assets",[])
 need(isinstance(parent_rows,list) and all(isinstance(a,dict) for a in parent_rows),"parent release asset rows malformed")
 parent_assets={a.get("name"):a for a in parent_rows}
 need(len(parent_assets)==len(parent_rows),"duplicate parent release asset name")
 pinned={"source.tar.gz":(608971395,9817800,PARENT_SOURCE_SHA),"parts.json":(608971394,699,PARENT_PARTS_SHA),"mix.wav":(608971392,17452902,PARENT_MIX_SHA),"source-receipt.json":(608971391,56219,PARENT_RECEIPT_SHA)}
 need(set(parent_assets)==set(pinned),"parent release asset set differs from pinned native inputs")
 for name,(aid,size,digest) in pinned.items():
  a=parent_assets[name]; need(a.get("id")==aid and a.get("size")==size and a.get("digest")=="sha256:"+digest,f"parent native asset pin mismatch: {name}")
 need(re.fullmatch(r"S86-cta-follow-[1-9][0-9]*",source_release.get("tag_name","")) is not None and type(source_release.get("id")) is int and source_release.get("draft") is False and source_release.get("prerelease") is False,"corrected source release identity/state malformed")
 p=source_receipt.get("parent",{}); c=source_receipt.get("corrected",{})
 need(p.get("tag")==parent_release["tag_name"] and p.get("release_id")==parent_release["id"] and p.get("node_id")==parent_release["node_id"],"seal receipt parent provenance mismatch")
 need(p.get("source_sha256")==PARENT_SOURCE_SHA and p.get("parts_sha256")==PARENT_PARTS_SHA and p.get("mix_sha256")==PARENT_MIX_SHA,"sealed source receipt does not preserve all three pinned parent input hashes")
 need(c.get("source_sha256")==parts.get("sha256") and c.get("source_bytes")==parts.get("bytes"),"corrected source receipt does not bind parts")
 need(c.get("parts_sha256")==sha(json.dumps(parts,indent=2).encode()+b"\n"),"parts receipt binding mismatch")
 need(c.get("mix_sha256")==mix_sha,"seal receipt does not bind exact mix")
 need(source_receipt.get("cta_pressed_label")=="FOLLOW" and source_receipt.get("editorial_status")=="NOT_REVIEWED" and source_receipt.get("approval")=="NOT_GRANTED","source seal approval/provenance fields invalid")
 asset_rows=source_release.get("assets",[])
 need(isinstance(asset_rows,list) and all(isinstance(a,dict) for a in asset_rows),"corrected source release asset rows malformed")
 assets={a.get("name"):a for a in asset_rows}
 need(len(assets)==len(asset_rows),"duplicate corrected source release asset name")
 receipt_raw=json.dumps(source_receipt,indent=2).encode()+b"\n"
 expected={"source.tar.gz":(c.get("source_bytes"),c.get("source_sha256")),"parts.json":(c.get("parts_bytes"),c.get("parts_sha256")),"mix.wav":(c.get("mix_bytes"),c.get("mix_sha256")),"source-receipt.json":(len(receipt_raw),sha(receipt_raw))}
 need(set(expected)==set(assets),"corrected source release assets differ from exact four-file seal set")
 for name,(size,digest) in expected.items():
  a=assets[name]
  need(a.get("size")==size and a.get("digest")=="sha256:"+digest,f"corrected source release asset metadata mismatch: {name}")
def _sum_rows(raw):
 out={}
 for line in raw.decode().splitlines():
  m=re.fullmatch(r"([0-9a-f]{64})  (.+)",line); need(m and m.group(2) not in out,"invalid/duplicate master checksum row"); out[m.group(2)]=m.group(1)
 return out
def prepare(run_id,input_id,master_id,repository,main_ref,run,input_metadata,master_metadata,input_zip,master_zip,source_receipt,parent_release,source_release,out,env=None,system=None):
 env=os.environ if env is None else env; system=platform.system() if system is None else system
 require_hosted(env,system) # before reading files or metadata
 validate_repo_main(repository,main_ref,env["GITHUB_SHA"]); validate_run(run,run_id)
 validate_artifact(input_metadata,input_id,run_id,"input",run["head_sha"]); validate_artifact(master_metadata,master_id,run_id,"master",run["head_sha"])
 need(input_metadata["name"][:-len("-EXACT-INPUT")] == master_metadata["name"][:-len("-FINAL-MASTERS")],"input and master artifacts are from different render tags")
 verify_zip_digest(input_zip,input_metadata); verify_zip_digest(master_zip,master_metadata)
 _,im=_zip_members(input_zip,"input"); _,mm=_zip_members(master_zip,"master")
 need(set(im)=={"INPUT-RECEIPT.json","MATRIX.json","NORMALISED-PARTS.json","source.tar.gz","parts.json","mix.wav"},"input artifact inventory mismatch")
 need(set(mm)=={"FINAL.mp4","FINAL-4K.mp4","TECHNICAL-EVIDENCE.json","SHA256SUMS.txt"},"render_4K=true master artifact inventory mismatch")
 get=lambda p,m,n:read_member(p,m[n])
 receipt=json.loads(get(input_zip,im,"INPUT-RECEIPT.json")); parts_raw=get(input_zip,im,"parts.json"); parts=json.loads(parts_raw)
 parts_digest=sha(parts_raw); mix_digest,mix_size=hash_zip_member(input_zip,im["mix.wav"],25_000_000)
 validate_source_provenance(parent_release,source_release,source_receipt,parts,mix_digest)
 validate_input_receipt(receipt,source_receipt,parts)
 corrected=source_receipt["corrected"]
 need(parts_digest==corrected["parts_sha256"] and len(parts_raw)==corrected["parts_bytes"],"exact parts bytes differ from source release receipt")
 need(mix_digest==corrected["mix_sha256"] and mix_size==corrected["mix_bytes"],"exact mix bytes differ from source release receipt")
 source_digest,source_size=hash_zip_member(input_zip,im["source.tar.gz"],15_000_000)
 need(source_digest==receipt["source_sha256"]==corrected["source_sha256"] and source_size==receipt["source_bytes"]==corrected["source_bytes"],"source package bytes do not match native input receipt")
 tech=json.loads(get(master_zip,mm,"TECHNICAL-EVIDENCE.json")); sums=_sum_rows(get(master_zip,mm,"SHA256SUMS.txt"))
 need(tech.get("technical_status")=="PASS" and tech.get("editorial_status")=="NOT_REVIEWED","technical receipt status invalid")
 rows4=[x for x in tech.get("masters",[]) if isinstance(x,dict) and x.get("file")=="FINAL-4K.mp4"]; need(len(rows4)==1,"4K-enabled technical receipt lacks unique FINAL-4K.mp4")
 row4=rows4[0]; d4,n4=hash_zip_member(master_zip,mm["FINAL-4K.mp4"],400_000_000)
 need(row4.get("sha256")==d4 and row4.get("bytes")==n4 and row4.get("resolution")=="4k" and row4.get("full_decode")=="PASS" and sums.get("FINAL-4K.mp4")==d4,"4K master/hash/technical receipt mismatch")
 rows=[x for x in tech.get("masters",[]) if isinstance(x,dict) and x.get("file")=="FINAL.mp4"]; need(len(rows)==1,"technical receipt lacks unique FINAL.mp4")
 need(set(sums)=={"FINAL.mp4","FINAL-4K.mp4","TECHNICAL-EVIDENCE.json","review/CONTACT-SHEET.jpg"},"master checksum inventory differs from pinned renderer output")
 need(sums["TECHNICAL-EVIDENCE.json"]==sha(get(master_zip,mm,"TECHNICAL-EVIDENCE.json")),"technical evidence checksum mismatch")
 row=rows[0]; digest,size=hash_zip_member(master_zip,mm["FINAL.mp4"],550_000_000)
 need(row.get("sha256")==digest and row.get("bytes")==size and sums.get("FINAL.mp4")==digest,"master/hash/technical receipt mismatch")
 need(row.get("resolution")=="1080" and row.get("frames")==1818 and row.get("full_decode")=="PASS","master is not full decoded 1080x1920 1818-frame output")
 probe=row.get("probe",{}); need(probe.get("format",{}).get("duration") in (60.6,"60.600000"),"master duration changed")
 streams=probe.get("streams",[]); v=[x for x in streams if x.get("codec_type")=="video"]; a=[x for x in streams if x.get("codec_type")=="audio"]
 need(len(v)==1 and len(a)==1 and v[0].get("width")==1080 and v[0].get("height")==1920 and a[0].get("sample_rate")=="48000" and a[0].get("channels")==2,"master stream contract mismatch")
 out.mkdir(parents=True,exist_ok=False); name="S86-FOLLOW-CORRECTED-1080.mp4"
 partial=out/".FINAL.mp4.partial"
 copy_zip_member(master_zip,mm["FINAL.mp4"],partial,550_000_000,digest)
 os.replace(partial,out/name)
 lineage={"schema":"agmm-s86-corrected-source-lineage-v1","source_release":{"tag":source_release["tag_name"],"id":source_release["id"]},"source_seal":source_receipt,"render_run_id":run_id,"render_head_sha":run["head_sha"],"input_artifact_id":input_id,"input_artifact_name":input_metadata["name"],"input_artifact_digest":input_metadata["digest"],"input_artifact_bytes":input_metadata["size_in_bytes"],"master_artifact_id":master_id,"master_artifact_name":master_metadata["name"],"master_artifact_digest":master_metadata["digest"],"master_artifact_bytes":master_metadata["size_in_bytes"],"input_receipt":receipt,"parts_sha256":receipt["parts_sha256"],"mix_sha256":receipt["mix_sha256"]}
 (out/"SOURCE-LINEAGE.json").write_text(json.dumps(lineage,indent=2)+"\n")
 (out/"INPUT-RECEIPT.json").write_bytes(get(input_zip,im,"INPUT-RECEIPT.json")); (out/"TECHNICAL-EVIDENCE.json").write_bytes(get(master_zip,mm,"TECHNICAL-EVIDENCE.json"))
 entries=[]
 tag=f"S86-cta-follow-review-{run_id}"
 review={"schema":"agmm-s86-corrected-review-playback-v1","status":"PUBLIC_REVIEW_PLAYBACK_ONLY","repository":REPO,"render_run_id":run_id,"render_head_sha":run["head_sha"],"source_tag":source_release["tag_name"],"source_release_id":source_release["id"],"input_artifact_id":input_id,"input_artifact_digest":input_metadata["digest"],"master_artifact_id":master_id,"master_artifact_digest":master_metadata["digest"],"asset_name":name,"master_sha256":digest,"master_bytes":size,"playback_url":f"https://github.com/{REPO}/releases/download/{tag}/{name}",**OPEN_STATUS,"scope_note":"Exact corrected 1080 final master copied byte-for-byte from its native successful full render artifact. No render/transcode in exporter; no approval implied."}
 (out/"REVIEW-PLAYBACK-RECEIPT.json").write_text(json.dumps(review,indent=2)+"\n")
 for f in sorted(out.iterdir()):
  d,n=file_sha(f); entries.append(f"{d}  {f.name}")
 (out/"SHA256SUMS.txt").write_text("\n".join(entries)+"\n")
 return {"tag":tag,"master_sha256":digest,"master_bytes":size,"asset_names":sorted(p.name for p in out.iterdir())}
def release_rows(pages):
 need(isinstance(pages,list),"authenticated release listing malformed")
 if all(isinstance(page,list) for page in pages): rows=[row for page in pages for row in page]
 else: rows=pages
 need(all(isinstance(row,dict) for row in rows),"authenticated release row malformed")
 return rows
def require_release_tag_absent(pages,tag):
 matches=[row for row in release_rows(pages) if row.get("tag_name")==tag]
 need(not matches,"a release with the intended exact tag already exists")
def select_unique_draft_release(pages,tag,target_commitish,release_id=None):
 matches=[row for row in release_rows(pages) if row.get("tag_name")==tag]
 need(len(matches)==1,"intended release tag does not resolve to exactly one native release")
 row=matches[0]
 need(type(row.get("id")) is int and row["id"]>0,"draft release REST ID is not an integer")
 need(row.get("draft") is True and row.get("prerelease") is True,"matching release is not a draft prerelease")
 need(row.get("target_commitish")==target_commitish,"matching draft targets a different current-main commit")
 if release_id is not None: need(row["id"]==release_id,"existing draft ID differs from exact tag listing")
 return row["id"]
def validate_release_assets(release,release_id,expected,published=False,target_commitish=None):
 need(type(release.get("id")) is int and release.get("id")==release_id and release.get("tag_name")==expected["tag"],"release ID/tag mismatch")
 need(release.get("draft") is (not published) and release.get("prerelease") is True,"release state not review prerelease")
 if target_commitish is not None: need(release.get("target_commitish")==target_commitish,"release target commit mismatch")
 rows=release.get("assets"); need(isinstance(rows,list),"release asset list malformed")
 actual={}
 for x in rows:
  n=x.get("name"); need(n not in actual and x.get("state")=="uploaded","duplicate/unuploaded release asset"); actual[n]=(x.get("size"),x.get("digest"))
 wanted={}
 for name,value in expected["assets"].items():
  wanted[name]=(value.get("size"),value.get("digest")) if isinstance(value,Mapping) else value
 need(actual==wanted,"release native asset list/size/digest mismatch")
class _AllowedRedirects(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  p=urllib.parse.urlsplit(newurl); need(p.scheme=="https" and p.hostname in {"github.com","release-assets.githubusercontent.com","objects.githubusercontent.com"} and p.port in (None,443),"redirect outside GitHub HTTPS host allowlist")
  return super().redirect_request(req,fp,code,msg,headers,newurl)
def range_probe(url,expected_bytes,expected_tag,opener=None):
 p=urllib.parse.urlsplit(url); need(p.scheme=="https" and p.hostname=="github.com","review URL must be GitHub HTTPS")
 need(p.path==f"/{REPO}/releases/download/{expected_tag}/S86-FOLLOW-CORRECTED-1080.mp4","review URL path/tag mismatch")
 opener=opener or urllib.request.build_opener(_AllowedRedirects())
 req=urllib.request.Request(url,headers={"Range":"bytes=0-0","Accept-Encoding":"identity"})
 try:
  with opener.open(req,timeout=20) as r:
   final=urllib.parse.urlsplit(r.geturl()); need(final.scheme=="https" and final.hostname in {"github.com","release-assets.githubusercontent.com","objects.githubusercontent.com"},"range redirect host not allowed")
   need(r.status==206 and r.headers.get("Content-Range")==f"bytes 0-0/{expected_bytes}","public asset not exact byte-range response")
   body=r.read(2); need(len(body)==1,"range response returned other than one byte")
   return {"status":206,"content_range":f"bytes 0-0/{expected_bytes}","bytes_read":1,"final_host":final.hostname,"full_playback_verified":False}
 except (OSError,urllib.error.URLError,urllib.error.HTTPError) as e: raise ExportError(f"public range probe failed: {type(e).__name__}") from e

def finalize(directory:Path,tag:str,range_result:Mapping[str,Any]):
 r=json.loads((directory/"REVIEW-PLAYBACK-RECEIPT.json").read_text())
 need(range_result.get("status")==206 and range_result.get("content_range")==f"bytes 0-0/{r['master_bytes']}" and range_result.get("bytes_read")==1,"range proof invalid")
 transport={"schema":"agmm-public-playback-transport-check-v1","status":"RANGE_RESPONSE_VERIFIED_ONLY","review_url":r["playback_url"],"master_sha256":r["master_sha256"],"master_bytes":r["master_bytes"],"http_status":206,"content_range":range_result["content_range"],"bytes_read_on_github_actions_ubuntu":1,"final_host":range_result.get("final_host"),**OPEN_STATUS}
 manifest=[{"cardID":"S86","url":r["playback_url"],"sha256":r["master_sha256"],"size":r["master_bytes"],"status":"review-pending"}]
 (directory/"PLAYBACK-TRANSPORT-VERIFICATION.json").write_text(json.dumps(transport,indent=2)+"\n")
 (directory/"HOSTED-MEDIA-MANIFEST.json").write_text(json.dumps(manifest,indent=2)+"\n")
 return asset_inventory(directory,True)

def main():
 require_hosted(os.environ,platform.system())  # refuse this CLI before parsing or opening user paths
 ap=argparse.ArgumentParser(); sp=ap.add_subparsers(dest="cmd",required=True)
 absent=sp.add_parser("check-absence"); absent.add_argument("--http-status",type=int,required=True); absent.add_argument("body",type=Path)
 inv=sp.add_parser("inventory"); inv.add_argument("directory",type=Path); inv.add_argument("--tag",required=True); inv.add_argument("--output",type=Path,required=True); inv.add_argument("--finalized",action="store_true")
 vr=sp.add_parser("verify-range"); vr.add_argument("--url",required=True); vr.add_argument("--bytes",type=int,required=True); vr.add_argument("--tag",required=True); vr.add_argument("--output",type=Path,required=True)
 fin=sp.add_parser("finalize"); fin.add_argument("directory",type=Path); fin.add_argument("--tag",required=True); fin.add_argument("range_result",type=Path); fin.add_argument("--output",type=Path,required=True)
 rel=sp.add_parser("validate-release"); rel.add_argument("release",type=Path); rel.add_argument("inventory",type=Path); rel.add_argument("--release-id",type=int,required=True); rel.add_argument("--target-commitish"); rel.add_argument("--published",action="store_true")
 absent_rel=sp.add_parser("check-release-absence"); absent_rel.add_argument("release_pages",type=Path); absent_rel.add_argument("--tag",required=True)
 select_rel=sp.add_parser("select-draft-release"); select_rel.add_argument("release_pages",type=Path); select_rel.add_argument("--tag",required=True); select_rel.add_argument("--target-commitish",required=True); select_rel.add_argument("--release-id",type=int)
 q=sp.add_parser("prepare")
 q.add_argument("--run-id",type=int,required=True); q.add_argument("--input-id",type=int,required=True); q.add_argument("--master-id",type=int,required=True)
 for n in ("repository","main-ref","run","input-metadata","master-metadata","input-zip","master-zip","source-receipt","parent-release","source-release","out"): q.add_argument("--"+n,type=Path,required=True)
 a=ap.parse_args()
 if a.cmd=="check-absence":
  body=json.loads(a.body.read_text()) if a.body.exists() and a.body.stat().st_size else None; validate_absence(a.http_status,body); print("exact HTTP 404 tag absence PASS")
 elif a.cmd=="inventory":
  result={"tag":a.tag,"assets":asset_inventory(a.directory,a.finalized)}; a.output.write_text(json.dumps(result,indent=2)+"\n"); print(json.dumps(result))
 elif a.cmd=="verify-range":
  result=range_probe(a.url,a.bytes,a.tag); a.output.write_text(json.dumps(result,indent=2)+"\n"); print(json.dumps(result))
 elif a.cmd=="finalize":
  result={"tag":a.tag,"assets":finalize(a.directory,a.tag,json.loads(a.range_result.read_text()))}; a.output.write_text(json.dumps(result,indent=2)+"\n"); print(json.dumps(result))
 elif a.cmd=="validate-release":
  validate_release_assets(json.loads(a.release.read_text()),a.release_id,json.loads(a.inventory.read_text()),published=a.published,target_commitish=a.target_commitish); print("native release ID/state/target/assets PASS")
 elif a.cmd=="check-release-absence":
  require_release_tag_absent(json.loads(a.release_pages.read_text()),a.tag); print("exact release tag absent from authenticated listing PASS")
 elif a.cmd=="select-draft-release":
  print(select_unique_draft_release(json.loads(a.release_pages.read_text()),a.tag,a.target_commitish,a.release_id))
 else:
  args=[json.loads(a.repository.read_text()),json.loads(a.main_ref.read_text()),json.loads(a.run.read_text()),json.loads(a.input_metadata.read_text()),json.loads(a.master_metadata.read_text())]
  result=prepare(a.run_id,a.input_id,a.master_id,*args,a.input_zip,a.master_zip,json.loads(a.source_receipt.read_text()),json.loads(a.parent_release.read_text()),json.loads(a.source_release.read_text()),a.out)
  print(json.dumps(result))
if __name__=="__main__": main()
