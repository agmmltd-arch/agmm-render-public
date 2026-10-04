#!/usr/bin/env python3
"""Fail-closed text-only manifest/runtime preflight for a hosted S81 package."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path, PurePosixPath

FORBIDDEN={'.wav','.mp3','.mp4','.mov','.png','.jpg','.jpeg','.webp','.zip','.tar','.gz'}
_LOCAL_ROOTS='|'.join(('Users','Volumes','private','tmp','var','home','root','workspace','github'))
ABSOLUTE_LOCAL_PATH=re.compile(r'(?<![A-Za-z0-9:])/'+r'(?:'+_LOCAL_ROOTS+r')/[^\s"\'<>]+')
_BACKSLASH=chr(92)
WINDOWS_ABSOLUTE_PATH=re.compile(r'(?i)(?<![A-Za-z0-9])(?:[A-Z]:'+re.escape(_BACKSLASH)+r'|'+re.escape(_BACKSLASH*2)+r'[^'+re.escape(_BACKSLASH)+r'\s]+'+re.escape(_BACKSLASH)+r')[^\s"\'<>]+')
CREDENTIAL_PATTERNS=(
 re.compile(r'(?i)\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'),
 re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}'),
 re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
 re.compile(r'-----BEGIN (?:RSA|EC|OPENSSH|PRIVATE) PRIVATE KEY-----'),
 re.compile(r'(?i)["\']?(?:api[_-]?key|access[_-]?token|client[_-]?secret|token|secret|password|authorization)["\']?\s*[:=]\s*["\'][^"\']{12,}["\']'),
)

def validate_public_text_rows(rows:dict[str,bytes|str])->dict:
 """Reject local absolute-path disclosures and credential-like text in all published text."""
 for rel,value in rows.items():
  if not isinstance(rel,str) or not isinstance(value,(bytes,str)): raise ValueError('public text inventory has invalid entry')
  try: text=value.decode('utf-8') if isinstance(value,bytes) else value
  except UnicodeDecodeError: raise ValueError(f'public text is not UTF-8: {rel}') from None
  if ABSOLUTE_LOCAL_PATH.search(text) or WINDOWS_ABSOLUTE_PATH.search(text): raise ValueError(f'absolute local path is forbidden in public text: {rel}')
  if any(pattern.search(text) for pattern in CREDENTIAL_PATTERNS): raise ValueError(f'credential-like text is forbidden in public payload: {rel}')
 return {'status':'PUBLIC_TEXT_PRIVACY_PASS','files_scanned':len(rows)}

def sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1<<20),b''): h.update(block)
 return h.hexdigest()

def verify_payload(root:Path, manifest_path:Path)->dict:
 m=json.loads(manifest_path.read_text())
 if m.get('kind')!='s81_hosted_capture_text_payload_manifest': raise ValueError('wrong payload manifest kind')
 rows=m.get('required_files')
 if not isinstance(rows,list) or not rows: raise ValueError('payload manifest is empty')
 seen=set()
 root=root.resolve()
 for row in rows:
  rel=row.get('path',''); p=PurePosixPath(rel)
  if p.is_absolute() or '..' in p.parts or not rel or rel in seen: raise ValueError(f'unsafe or duplicate payload path: {rel!r}')
  seen.add(rel); target=root/rel
  if not target.is_file(): raise ValueError(f'missing required S81 text payload: {rel}')
  if target.suffix.lower() in FORBIDDEN: raise ValueError(f'media payload forbidden in text candidate set: {rel}')
  data=target.read_bytes()
  try:data.decode('utf-8')
  except UnicodeDecodeError: raise ValueError(f'payload is not UTF-8 text: {rel}') from None
  if len(data)!=row.get('bytes') or sha(target)!=row.get('sha256'): raise ValueError(f'payload digest/size mismatch: {rel}')
 for required in ('candidate/scenes.js','candidate/spec.json','candidate/sources.js','candidate/spec-delta.json','candidate/capture-plan-source.json','candidate/mix_spec.json','candidate/selected-sound-assets.json','candidate/storyboard-and-sound.md','voice-text/S81.words.json','voice-text/S81.receipt.json','voice-text/S81.RESULT.json'):
  if required not in seen: raise ValueError(f'manifest omits required source/craft file: {required}')
 actual=set()
 for p in root.rglob('*'):
  if p.is_symlink(): raise ValueError(f'symlink forbidden in S81 text payload: {p.relative_to(root)}')
  if p.is_file(): actual.add(p.relative_to(root).as_posix())
 allowed=seen | {'S81-CANDIDATE-MANIFEST.json'}
 if actual != allowed: raise ValueError(f'S81 payload file set differs: extra={sorted(actual-allowed)}, missing={sorted(allowed-actual)}')
 validate_public_text_rows({rel:(root/rel).read_bytes() for rel in sorted(actual)})
 return {'status':'TEXT_PAYLOAD_VERIFIED','files':len(rows),'manifest_sha256':sha(manifest_path),'approval':'NOT_GRANTED'}

def verify_runtime(repo:Path, lock_path:Path)->dict:
 lock=json.loads(lock_path.read_text())
 if lock.get('repository')!='agmmltd-arch/agmm-render-public' or lock.get('visibility')!='public': raise ValueError('runtime lock must bind the public renderer repository')
 for rel,row in lock['required_remote_files'].items():
  p=repo/rel
  if not p.is_file(): raise ValueError(f'missing pinned runtime file: {rel}')
  if len(p.read_bytes())!=row['bytes'] or sha(p)!=row['sha256']: raise ValueError(f'pinned runtime drift: {rel}')
 return {'status':'RUNTIME_TEXT_PINS_VERIFIED','files':len(lock['required_remote_files']),'observed_head':lock['observed_head'],'runner':lock['runner'],'approval':'NOT_GRANTED'}

def main():
 ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
 p=sub.add_parser('payload'); p.add_argument('--root',type=Path,required=True); p.add_argument('--manifest',type=Path,required=True)
 r=sub.add_parser('runtime'); r.add_argument('--repo',type=Path,required=True); r.add_argument('--lock',type=Path,required=True)
 a=ap.parse_args(); out=verify_payload(a.root,a.manifest) if a.cmd=='payload' else verify_runtime(a.repo,a.lock)
 print(json.dumps(out,sort_keys=True))
if __name__=='__main__': main()
