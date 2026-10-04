#!/usr/bin/env python3
"""Build and validate a strict public review allowlist. Raw source assets cannot pass."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil

FILM = "FILM05-WAVE10-27S9-SILENT-PICTURE-PROOF.mp4"
RECEIPTS = {
    "receipts/SOURCE-RECEIPT.json",
    "receipts/FINAL-VIDEO-RECEIPT.json",
    "receipts/HYPERFRAMES-CHECK-SUMMARY.json",
    "receipts/FRAME-COUNT.txt",
    "receipts/FRAME-REVIEW-INDEX.csv",
    "receipts/BLACK-FREEZE-SCAN.txt",
    "receipts/PREIMAGE-GATE.md",
    "receipts/PUBLIC-PAYLOAD-GUARD-RECEIPT.txt",
}
PNG = b"\x89PNG\r\n\x1a\n"
JPEG = b"\xff\xd8\xff"
MP4_BOX = b"ftyp"
PRIVATE_BASE_ARCHIVE_SHA256 = "8bdbf047f74a6ce0de4d860df5174ca765ebc49da44f300e38910a500323461f"

class PayloadError(ValueError):
    pass

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()

def sniff(raw: bytes) -> str:
    if len(raw)>=8 and raw[:8]==PNG: return "png"
    if raw.startswith(JPEG): return "jpeg"
    if len(raw)>=8 and raw[4:8]==MP4_BOX: return "mp4"
    if raw.startswith(b"\x1f\x8b"): return "gzip"
    if raw.startswith(b"PK\x03\x04") or raw.startswith(b"PK\x05\x06"): return "zip"
    if len(raw)>=262 and raw[257:262]==b"ustar": return "tar"
    return "unknown"

def _safe_tree(root: Path) -> list[Path]:
    root=root.resolve(strict=True)
    result=[]
    for parent, dirs, files in os.walk(root, topdown=True, followlinks=False):
        pp=Path(parent)
        for name in dirs + files:
            p=pp/name
            if p.is_symlink(): raise PayloadError(f"symlink refused: {p.relative_to(root)}")
            if not p.is_dir() and not p.is_file(): raise PayloadError(f"non-regular file refused: {p.relative_to(root)}")
            rel=p.relative_to(root).as_posix()
            parts=PurePosixPath(rel).parts
            if not parts or any(x in ("", ".", "..") for x in parts) or "\\" in rel:
                raise PayloadError("unsafe path refused")
        result.extend(pp/n for n in files)
    return result

def validate_tree(root: Path, *, blocked_hashes: set[str], expected_film_sha256: str,
                  expected_stills: int=31, expected_sheets: int=18,
                  require_guard_receipt: bool=True) -> dict:
    root=root.resolve(strict=True)
    files=_safe_tree(root)
    rels={p.relative_to(root).as_posix() for p in files}
    expected={FILM} | RECEIPTS
    stills={p for p in rels if re.fullmatch(r"stills/[A-Za-z0-9._-]+\.png",p)}
    sheets={p for p in rels if re.fullmatch(r"contact-sheets/sheet-\d{3}\.jpg",p)}
    expected |= stills | sheets
    if len(stills)!=expected_stills or len(sheets)!=expected_sheets:
        raise PayloadError(f"wrong bounded review set: {len(stills)} stills, {len(sheets)} sheets")
    if not require_guard_receipt: expected.discard("receipts/PUBLIC-PAYLOAD-GUARD-RECEIPT.txt")
    if rels != expected:
        raise PayloadError(f"public payload allowlist mismatch: unexpected={sorted(rels-expected)}, missing={sorted(expected-rels)}")
    if set(r.relative_to(root).as_posix() for r in files if r.is_file()) != rels:
        raise PayloadError("payload contains non-regular files")
    final=root/FILM
    final_hash=sha256(final)
    if final_hash != expected_film_sha256:
        raise PayloadError("synchronized output does not match the recorded final film hash")
    for p in files:
        rel=p.relative_to(root).as_posix()
        raw=p.read_bytes()
        kind=sniff(raw[:512])
        digest=sha256(p)
        if digest in blocked_hashes or digest==PRIVATE_BASE_ARCHIVE_SHA256:
            raise PayloadError(f"known raw source/archive bytes refused: {rel}")
        if rel==FILM:
            if kind!="mp4": raise PayloadError("review film is not an MP4 container")
        elif rel.startswith("stills/"):
            if kind!="png": raise PayloadError(f"renamed or invalid still payload: {rel}")
        elif rel.startswith("contact-sheets/"):
            if kind!="jpeg": raise PayloadError(f"invalid contact sheet: {rel}")
        else:
            if kind in {"mp4","gzip","zip","tar","png","jpeg"}:
                raise PayloadError(f"non-text bytes refused in receipt path: {rel}")
            if len(raw)>2_000_000 or b"\x00" in raw: raise PayloadError(f"oversized or binary receipt: {rel}")
            text=raw.decode("utf-8")
            if any(token in text for token in ("/Users/", "/home/runner/", "BEGIN OPENSSH", "ghp_", "github_pat_", "Bearer ")):
                raise PayloadError(f"unsanitized or credential-like receipt text: {rel}")
            if rel.endswith(".json"): json.loads(text)
    return {"files":len(files),"stills":len(stills),"contact_sheets":len(sheets),"film_sha256":final_hash}

def _copy_checked(src: Path, dst: Path) -> None:
    if not src.is_file() or src.is_symlink(): raise PayloadError(f"required review file absent or unsafe: {src.name}")
    dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(src,dst)

def make_public_payload(*, evidence:Path, scratch:Path, project:Path, manifest:Path,
                        output:Path, expected_stills:int=31, expected_sheets:int=18) -> dict:
    evidence=evidence.resolve(strict=True);scratch=scratch.resolve(strict=True);project=project.resolve(strict=True)
    if output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True)
    source_film=evidence/"motion"/FILM
    _copy_checked(source_film,output/FILM)
    still_dir=output/"stills";still_dir.mkdir()
    stills=sorted((evidence/"stills").glob("*.png"))
    if len(stills)!=expected_stills: raise PayloadError(f"expected {expected_stills} stills, found {len(stills)}")
    for p in stills:
        if p.is_symlink() or not re.fullmatch(r"[A-Za-z0-9._-]+\.png",p.name): raise PayloadError("unsafe native still name")
        _copy_checked(p,still_dir/p.name)
    sheets=sorted((evidence/"motion"/"full-sheets").glob("sheet-*.jpg"))
    if len(sheets)!=expected_sheets: raise PayloadError(f"expected {expected_sheets} contact sheets, found {len(sheets)}")
    sheet_dir=output/"contact-sheets";sheet_dir.mkdir()
    for p in sheets:
        if p.is_symlink() or not re.fullmatch(r"sheet-\d{3}\.jpg",p.name): raise PayloadError("unsafe contact sheet name")
        _copy_checked(p,sheet_dir/p.name)
    rdir=output/"receipts";rdir.mkdir()
    for name,src in {
        "FRAME-COUNT.txt": evidence/"motion"/"FRAME-COUNT.txt",
        "FRAME-REVIEW-INDEX.csv": evidence/"motion"/"FRAME-REVIEW-INDEX.csv",
        "PREIMAGE-GATE.md": project/"PREIMAGE-GATE.md",
    }.items(): _copy_checked(src,rdir/name)
    # Only counters and bounded, path-free findings leave the hosted worker.
    check=json.loads((evidence/"check.json").read_text(encoding="utf-8"))
    summary={"ok":check.get("ok"),"strict":check.get("strict"),"hyperframes_version":check.get("_meta",{}).get("version"),"sections":{}}
    for key in ("lint","runtime","layout","motion","contrast"):
        section=check.get(key,{})
        summary["sections"][key]={k:section.get(k) for k in ("ok","errorCount","warningCount","infoCount","enabled") if k in section}
        findings=section.get("findings",[])
        summary["sections"][key]["findings"]=[{"code":x.get("code"),"severity":x.get("severity"),"time":x.get("time")} for x in findings]
    (rdir/"HYPERFRAMES-CHECK-SUMMARY.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    probes=[]
    for item in json.loads(manifest.read_text(encoding="utf-8"))["assets"]:
        media=project/item["composition_path"]
        actual_hash=sha256(media)
        if actual_hash != item["hosted_sha256"]: raise PayloadError(f"hosted source changed: {item['id']}")
        probe_path=scratch/f"{item['id']}-ffprobe.json"
        probe=json.loads(probe_path.read_text(encoding="utf-8"))
        video=next(x for x in probe["streams"] if x.get("codec_type")=="video")
        probes.append({"id":item["id"],"creator":item["creator"],"page":item["page"],"license":item["license"],"rights_note":item["rights_note"],"sha256":actual_hash,"video":{"width":video.get("width"),"height":video.get("height"),"frame_rate":video.get("r_frame_rate"),"duration_seconds":probe.get("format",{}).get("duration")}})
    (rdir/"SOURCE-RECEIPT.json").write_text(json.dumps({"acquired_and_verified_on":"hosted Ubuntu","sources":probes,"all_raw_source_media_excluded":True},indent=2,sort_keys=True)+"\n",encoding="utf-8")
    probe=json.loads((scratch/"final-ffprobe.json").read_text(encoding="utf-8"))
    videos=[x for x in probe.get("streams",[]) if x.get("codec_type")=="video"]
    audios=[x for x in probe.get("streams",[]) if x.get("codec_type")=="audio"]
    if len(videos)!=1 or audios: raise PayloadError("final proof is not silent video-only")
    v=videos[0]
    final_hash=sha256(source_film)
    final={"file":FILM,"sha256":final_hash,"duration_seconds":float(probe["format"]["duration"]),"frame_count":837,"width":v.get("width"),"height":v.get("height"),"frame_rate":v.get("r_frame_rate"),"audio_streams":0,"development_picture_only":True}
    (rdir/"FINAL-VIDEO-RECEIPT.json").write_text(json.dumps(final,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    black=(scratch/"black-freeze-scan.txt").read_text(encoding="utf-8",errors="replace")
    events=[line.strip() for line in black.splitlines() if re.search(r"\b(?:black_start|freeze_start|freeze_end|freeze_duration)=",line)]
    (rdir/"BLACK-FREEZE-SCAN.txt").write_text(("\n".join(events) if events else "No black or freeze events reported by the hosted scan.")+"\n",encoding="utf-8")
    raw_hashes={x["hosted_sha256"] for x in json.loads(manifest.read_text(encoding="utf-8"))["assets"]}
    raw_hashes.add(PRIVATE_BASE_ARCHIVE_SHA256)
    first=validate_tree(output,blocked_hashes=raw_hashes,expected_film_sha256=final_hash,expected_stills=expected_stills,expected_sheets=expected_sheets,require_guard_receipt=False)
    (rdir/"PUBLIC-PAYLOAD-GUARD-RECEIPT.txt").write_text(
        f"PASS: {first['files']+1} exact allowlisted files; {first['stills']} review stills; {first['contact_sheets']} contact sheets; final proof SHA-256 {first['film_sha256']}; no raw-source or archive bytes.\n",encoding="utf-8")
    result=validate_tree(output,blocked_hashes=raw_hashes,expected_film_sha256=final_hash,expected_stills=expected_stills,expected_sheets=expected_sheets)
    return result
