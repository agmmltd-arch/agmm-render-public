#!/usr/bin/env python3
"""Ubuntu-only exact S86-D CTA source seal. No programme media is decoded/rendered."""
from __future__ import annotations
import argparse, copy, hashlib, json, os, platform, re, tarfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

REPOSITORY = "agmmltd-arch/agmm-render-public"
PARENT_TAG = "S86-source-quote-37171207319"
PARENT_RELEASE_ID = 402788582
PARENT_NODE_ID = "RE_kwDOU05Rms4YAhDm"
PARENT_SOURCE_SHA = "666a90579d57f2bd5c2abed41e55b5dad3fff790f93707d79b2929bddf1c93b6"
PARENT_PARTS_SHA = "e995d9d0354b808714bf89e2a082a98200a8ef92733d1896181635dfecffbb88"
PARENT_MIX_SHA = "0c252cdf6e412fc2ccadcdb29b940d6a23b7c527276ebf79da468b7f633df436"
PARENT_ASSETS = {
 "source.tar.gz": (608971395, 9817800, "sha256:" + PARENT_SOURCE_SHA),
 "parts.json": (608971394, 699, "sha256:" + PARENT_PARTS_SHA),
 "mix.wav": (608971392, 17452902, "sha256:" + PARENT_MIX_SHA),
 "source-receipt.json": (608971391, 56219, "sha256:ef1db9c644b0e4c59f5d087deb2e858e052f4c98f56dad3cdc630378c2d5f26f"),
}
EXPECTED_PARTS = [
 {"look":"s86-a","file":"index.html","out":"S86-A","off":0.0,"dur":15.166666666666666},
 {"look":"s86-b","file":"index.html","out":"S86-B","off":15.166666666666666,"dur":15.166666666666666},
 {"look":"s86-c","file":"index.html","out":"S86-C","off":30.333333333333332,"dur":15.166666666666666},
 {"look":"s86-d","file":"index.html","out":"S86-D","off":45.5,"dur":15.1},
]
INSERT = b'"button": "FOLLOW",'
REPLACEMENT = b'"button": "FOLLOW",\n"pressed": "FOLLOW",'
SUFFIX = "/s86-d/spec.js"

class SealError(ValueError): pass

def sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def require(condition: bool, message: str) -> None:
    if not condition: raise SealError(message)

def require_hosted(env: Mapping[str,str], system: str) -> None:
    require(system == "Linux" and env.get("RUNNER_OS") == "Linux" and env.get("GITHUB_ACTIONS") == "true", "GitHub Actions Ubuntu only; refusing local CLI")
    require(env.get("GITHUB_REPOSITORY") == REPOSITORY, "wrong GitHub repository")
    require(env.get("GITHUB_REF") == "refs/heads/main" and env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "manual current-main dispatch required")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", ""))), "invalid workflow SHA")

def validate_repository_and_head(repo: Mapping[str,Any], main_ref: Mapping[str,Any], github_sha: str) -> None:
    require(repo.get("full_name")==REPOSITORY and repo.get("private") is False and repo.get("visibility")=="public", "repository must be the public render repo")
    obj=main_ref.get("object")
    require(isinstance(obj,dict) and obj.get("sha")==github_sha, "workflow commit is not exact current main")

def release_absence_result(status: int, body: Any, tag: str) -> None:
    if status != 404: raise SealError(f"release-tag absence requires HTTP 404; got {status}")
    if body not in (None, {}, "") and (not isinstance(body,dict) or body.get("message")!="Not Found"):
        raise SealError("404 response was not GitHub's exact not-found JSON")

def validate_parent_release(row: Mapping[str,Any]) -> None:
    require(row.get("id")==PARENT_RELEASE_ID and row.get("node_id")==PARENT_NODE_ID and row.get("tag_name")==PARENT_TAG, "parent release numeric ID/node ID/tag mismatch")
    assets=row.get("assets")
    require(isinstance(assets,list), "parent assets missing")
    byname={}
    for a in assets:
        if isinstance(a,dict):
            n=a.get("name"); require(n not in byname, "duplicate parent asset name"); byname[n]=a
    require(set(byname)==set(PARENT_ASSETS), "parent release assets differ from exact four-file native set")
    for name,(asset_id,size,digest) in PARENT_ASSETS.items():
        a=byname.get(name); require(isinstance(a,dict),f"missing {name}")
        require((a.get("id"),a.get("size"),a.get("digest"))==(asset_id,size,digest),f"parent {name} native asset pin mismatch")

def main_validate_parent(path: Path) -> None:
    validate_parent_release(json.loads(path.read_text(encoding="utf-8")))

def _inventory(tf: tarfile.TarFile) -> tuple[list[tarfile.TarInfo],dict[str,bytes|None]]:
    members=tf.getmembers(); seen=set(); payloads={}
    require(bool(members), "empty source archive")
    for m in members:
        raw=m.name; p=PurePosixPath(raw)
        require("\\" not in raw and not p.is_absolute() and ".." not in p.parts and (p.parts or (raw in (".","./") and m.isdir())), "unsafe archive path")
        norm=str(p)
        require(norm not in seen, f"duplicate archive path: {norm}"); seen.add(norm)
        require(m.isdir() or m.isfile(), "archive contains symlink, hardlink, device, or unsupported entry")
        if m.isfile():
            stream=tf.extractfile(m); require(stream is not None, "cannot read archive file")
            b=stream.read(); require(len(b)==m.size, "archive member size mismatch")
            payloads[norm]=b
        else: payloads[norm]=None
    return members,payloads

def _verify_sums(prefix: str, payloads: Mapping[str,bytes|None], sums_path: str) -> None:
    raw=payloads[sums_path]; require(isinstance(raw,bytes), "checksum manifest is not a regular file")
    entries={}
    for line in raw.decode("utf-8").splitlines():
        m=re.fullmatch(r"([0-9a-f]{64})  (.+)",line)
        require(m is not None,"malformed checksum line")
        name=m.group(2); require(name not in entries,"duplicate checksum path")
        p=PurePosixPath(name); require(not p.is_absolute() and ".." not in p.parts and "\\" not in name,"unsafe checksum path")
        entries[name]=m.group(1)
    target_names={"./"+str(PurePosixPath(path).relative_to(prefix)) for path,b in payloads.items() if path.startswith(prefix+"/") and path!=sums_path and isinstance(b,bytes)}
    require(set(entries)==target_names,"checksum manifest inventory differs from S86-D files")
    for name,digest in entries.items():
        path=str(PurePosixPath(prefix)/PurePosixPath(name))
        require(sha(payloads[path] or b"")==digest,f"checksum mismatch: {path}")

def seal(source: Path, parts: Path, mix: Path, parts_output: Path, output: Path, receipt: Path,
         *, parent_tag: str=PARENT_TAG, parent_release_id: int=PARENT_RELEASE_ID,
         parent_source_sha: str=PARENT_SOURCE_SHA, parent_parts_sha: str=PARENT_PARTS_SHA,
         parent_mix_sha: str=PARENT_MIX_SHA, env: Mapping[str,str]|None=None,
         system: str|None=None) -> dict[str,Any]:
    env=os.environ if env is None else env; system=platform.system() if system is None else system
    require_hosted(env,system)  # first operation before any paths are opened
    require((parent_tag,parent_release_id,parent_source_sha,parent_parts_sha,parent_mix_sha)==(PARENT_TAG,PARENT_RELEASE_ID,PARENT_SOURCE_SHA,PARENT_PARTS_SHA,PARENT_MIX_SHA),"source provenance pins do not match the immutable parent")
    src=source.read_bytes(); part_raw=parts.read_bytes(); mix_raw=mix.read_bytes()
    require(sha(src)==parent_source_sha,"parent source hash drift")
    require(sha(part_raw)==parent_parts_sha,"parent parts hash drift")
    require(sha(mix_raw)==parent_mix_sha,"parent mix hash drift")
    pdata=json.loads(part_raw)
    require(isinstance(pdata,dict) and isinstance(pdata.get("parts"),list),"parts schema malformed")
    require(pdata.get("parts")==EXPECTED_PARTS,"parts timeline or segment contract drift")
    require(pdata.get("sha256")==parent_source_sha and pdata.get("bytes")==len(src),"parts.json source binding drift")
    with tarfile.open(source,"r:gz") as tf: members,payloads=_inventory(tf)
    targets=[m for m in members if m.isfile() and (str(PurePosixPath(m.name))=="s86-d/spec.js" or str(PurePosixPath(m.name)).endswith(SUFFIX))]
    require(len(targets)==1,"expected exactly one S86-D spec.js")
    target=targets[0]; prefix=str(PurePosixPath(target.name).parent)
    sums_path=prefix+"/SHA256SUMS.txt"
    require(isinstance(payloads.get(sums_path),bytes),"S86-D checksum manifest missing")
    _verify_sums(prefix,payloads,sums_path)
    target_key=str(PurePosixPath(target.name))
    original=dict(payloads); before=payloads[target_key]; require(isinstance(before,bytes),"target not regular file")
    require(before.count(INSERT)==1 and b'"pressed": "FOLLOW"' not in before,"CTA patch precondition mismatch")
    ctas=[m.start() for m in re.finditer(rb'"kind"\s*:\s*"cta"',before)]
    require(len(ctas)==1 and before.find(INSERT,ctas[0])>=0,"CTA object ambiguous")
    after=before.replace(INSERT,REPLACEMENT,1); payloads[target_key]=after
    old_line=(sha(before)+"  ./spec.js").encode(); new_line=(sha(after)+"  ./spec.js").encode()
    sums=payloads[sums_path]; require(isinstance(sums,bytes) and sums.count(old_line)==1,"spec checksum entry mismatch")
    payloads[sums_path]=sums.replace(old_line,new_line,1); _verify_sums(prefix,payloads,sums_path)
    output.parent.mkdir(parents=True,exist_ok=True); parts_output.parent.mkdir(parents=True,exist_ok=True); receipt.parent.mkdir(parents=True,exist_ok=True)
    import io
    with tarfile.open(output,"w:gz",format=tarfile.PAX_FORMAT) as out:
        for m in members:
            info=copy.copy(m); data=payloads[str(PurePosixPath(m.name))]
            if m.isfile(): info.size=len(data or b""); out.addfile(info,io.BytesIO(data or b""))
            else: out.addfile(info)
    corrected_sha=sha(output.read_bytes()); newparts=dict(pdata); newparts["sha256"]=corrected_sha; newparts["bytes"]=output.stat().st_size
    parts_output.write_text(json.dumps(newparts,indent=2)+"\n",encoding="utf-8")
    manifest=[]
    for m in members:
        old=original[str(PurePosixPath(m.name))]; new=payloads[str(PurePosixPath(m.name))]
        manifest.append({"path":m.name,"type":"directory" if m.isdir() else "regular_file","before_bytes":m.size if m.isfile() else 0,"after_bytes":len(new or b"") if m.isfile() else 0,"before_sha256":sha(old) if isinstance(old,bytes) else None,"after_sha256":sha(new) if isinstance(new,bytes) else None})
    result={"kind":"s86_cta_source_seal","parent":{"tag":parent_tag,"release_id":parent_release_id,"node_id":PARENT_NODE_ID,"source_sha256":parent_source_sha,"parts_sha256":parent_parts_sha,"mix_sha256":parent_mix_sha},"corrected":{"source_sha256":corrected_sha,"source_bytes":output.stat().st_size,"parts_sha256":sha(parts_output.read_bytes()),"parts_bytes":parts_output.stat().st_size,"mix_sha256":sha(mix_raw),"mix_bytes":len(mix_raw)},"changed_member":target.name,"changed_member_before_sha256":sha(before),"changed_member_after_sha256":sha(after),"checksum_member":sums_path,"only_changed_members":[target.name,sums_path],"archive_inventory":manifest,"cta_pressed_label":"FOLLOW","editorial_status":"NOT_REVIEWED","approval":"NOT_GRANTED"}
    receipt.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8"); return result

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
    v=sub.add_parser("validate-parent"); v.add_argument("metadata",type=Path)
    absent=sub.add_parser("check-tag-absence"); absent.add_argument("--http-status",type=int,required=True); absent.add_argument("body",type=Path)
    q=sub.add_parser("seal")
    for name in ("source","parts","mix","parts-output","output","receipt"): q.add_argument("--"+name,type=Path,required=True)
    q.add_argument("--parent-tag",required=True); q.add_argument("--parent-release-id",type=int,required=True); q.add_argument("--parent-source-sha",required=True); q.add_argument("--parent-parts-sha",required=True); q.add_argument("--parent-mix-sha",required=True)
    a=ap.parse_args()
    if a.cmd=="validate-parent":
        main_validate_parent(a.metadata); print("parent numeric ID/node ID and asset pins PASS")
    elif a.cmd=="check-tag-absence":
        body=json.loads(a.body.read_text()) if a.body.exists() and a.body.stat().st_size else None
        release_absence_result(a.http_status,body,"S86-cta-follow")
        print("new release tag absent by exact HTTP 404 PASS")
    else:
        seal(a.source,a.parts,a.mix,a.parts_output,a.output,a.receipt,parent_tag=a.parent_tag,parent_release_id=a.parent_release_id,parent_source_sha=a.parent_source_sha,parent_parts_sha=a.parent_parts_sha,parent_mix_sha=a.parent_mix_sha)
if __name__=="__main__": main()
