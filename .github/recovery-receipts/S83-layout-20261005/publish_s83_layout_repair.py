#!/usr/bin/env python3
"""Guarded S83 actual-layout delta publisher. Never dispatches Actions.

Default mode performs read-only local/native preflight. --publish is the
root-owned, non-force ref update path and is intentionally not run by this card.
"""
from __future__ import annotations
import argparse, base64, hashlib, importlib.util, json, pathlib, sys

BUILD = pathlib.Path('/Users/samwall/alfred/builds/video-autonomy-2026-10-02')
CANDIDATE = BUILD / 'S83-layout-repair-ec323'
BASE = BUILD / 'S83-production-luna-chat'
MAP = CANDIDATE / 'S83-LAYOUT-REPAIR-DELTA-MAP.json'
MAP_SHA256 = '2ef46777042e9afb24321f42c7ebdc6119c701448c8522c5388fc9ccb6135c99'
REPO = 'agmmltd-arch/agmm-render-public'
HEAD = '440d0714ca6e9b10d97518fe197a371c4b3edc9d'
TREE = 'b8b3bb644312c7e078a39409befc548be5429f77'
DEST = '.github/candidates/S83'
WORKFLOW = '.github/workflows/s83-source-capture.yml'
ALLOWED = {
 f'{DEST}/index.html', f'{DEST}/CANDIDATE-MANIFEST.json', f'{DEST}/CANDIDATE-MANIFEST.sha256',
 f'{DEST}/CANDIDATE-TEXT-HASHES.txt', f'{DEST}/PARENT-IDENTITY.json',
 f'{DEST}/MIX-RUNTIME-DEPENDENCIES.json', f'{DEST}/s83-source-capture.workflow.yml', WORKFLOW,
 f'{DEST}/assert_s83_layout.py', f'{DEST}/test_s83_layout_regressions.py',
}
RUNTIME_PINS = {
 '.github/workflows/agmm-short-capture.yml':'3cb41404efec5fed821510b8d8717b8188221891',
 '.github/scripts/capture_short_package.py':'65f9b89f126c6113a91061a2f1f361954c96a0ae',
 '.github/scripts/render_short_package.py':'754099346a84c5bd305f5684ef24399a53bd9697',
 '.github/workflows/agmm-short-package.yml':'2e8c6e21409e0bdaaf80356d8b02b71bd4c5491b',
 'tools/agmm-kit-mirror/sound/v2/audio_core.py':'9a0aaee6f0676677efff34d25fdcf79d9537cb16',
 'tools/agmm-kit-mirror/sound/v2/audio_rules.json':'e00afb1410d4ae9278be24ccb3811972a62e7b17',
 'tools/agmm-kit-mirror/sound/v2/mix2.py':'623521fb087ce296fe3895f6c23205c49976b837',
 'tools/agmm-kit-mirror/sound/v2/voice_chain.py':'ea817bb829f4ffd68b2abdaacb1a8128731d4b21',
 'tools/agmm-kit-mirror/sound/library.json':'ddaf188c42e87d6a8d7b42e17f4433e0b5ef0a05',
}
spec=importlib.util.spec_from_file_location('s83_existing_api',BUILD/'BUILD/publish_s83_candidate.py')
if spec is None or spec.loader is None: raise RuntimeError('existing gh_json helper unavailable')
api_module=importlib.util.module_from_spec(spec); spec.loader.exec_module(api_module)
gh_json=api_module.gh_json

def blob_sha(data:bytes)->str:
 return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()

def read_text(path:pathlib.Path)->bytes:
 if path.is_symlink() or not path.is_file() or CANDIDATE.resolve() not in path.resolve().parents:
  raise RuntimeError(f'missing, symlinked, or escaped source: {path}')
 data=path.read_bytes(); data.decode('utf-8'); return data

def local_preflight():
 raw=read_text(MAP)
 if hashlib.sha256(raw).hexdigest()!=MAP_SHA256: raise RuntimeError('frozen delta map SHA-256 mismatch')
 m=json.loads(raw)
 if (m.get('schema')!='agmm-s83-layout-repair-delta-map-v1' or m.get('repository')!=REPO or
     m.get('destination')!='main' or m.get('observed_main')!=HEAD or m.get('candidate_parent')!=HEAD or
     m.get('observed_tree_sha')!=TREE or m.get('candidate_manifest_sha256')!='fae670b35f33fd843f10c0c7d1d567b3bf5be244191bf0e8e292cb19b6af7c85'):
  raise RuntimeError('frozen map identity/manifest binding failed')
 targets=m.get('targets'); by={t.get('path'):t for t in targets or []}
 if len(by)!=10 or set(by)!=ALLOWED or sum(t.get('operation')=='update' for t in targets)!=8 or sum(t.get('operation')=='create' for t in targets)!=2:
  raise RuntimeError('delta must contain the exact 10 allowlisted destinations (8 updates, 2 creates)')
 if m.get('runtime_pins')!=RUNTIME_PINS: raise RuntimeError('runtime-pin set differs from reviewed nine pins')
 files={}
 for t in targets:
  src=t.get('local_source')
  if src not in {'index.html','CANDIDATE-MANIFEST.json','CANDIDATE-MANIFEST.sha256','CANDIDATE-TEXT-HASHES.txt','PARENT-IDENTITY.json','MIX-RUNTIME-DEPENDENCIES.json','s83-source-capture.workflow.yml','assert_s83_layout.py','test_s83_layout_regressions.py'}:
   raise RuntimeError('unexpected mapped local source')
  data=read_text(CANDIDATE/src)
  p=t['proposed']
  if len(data)!=p['bytes'] or hashlib.sha256(data).hexdigest()!=p['sha256'] or blob_sha(data)!=p['blob_sha1']:
   raise RuntimeError(f'proposed local identity mismatch: {t["path"]}')
  files[t['path']]=data
 if files[f'{DEST}/s83-source-capture.workflow.yml']!=files[WORKFLOW]: raise RuntimeError('root workflow alias does not exactly match candidate workflow')
 manifest_bytes=files[f'{DEST}/CANDIDATE-MANIFEST.json']
 if hashlib.sha256(manifest_bytes).hexdigest()!=m['candidate_manifest_sha256']: raise RuntimeError('manifest digest differs from map')
 manifest=json.loads(manifest_bytes); declared=manifest.get('candidate_files')
 if not isinstance(declared,dict) or len(declared)!=50: raise RuntimeError('manifest must close exactly 50 candidate text files')
 hashes={}
 for line in files[f'{DEST}/CANDIDATE-TEXT-HASHES.txt'].decode().splitlines():
  digest,rel=line.split(None,1); hashes[rel.strip()]=digest
 if hashes!=declared or hashlib.sha256(files[f'{DEST}/CANDIDATE-TEXT-HASHES.txt']).hexdigest()!=manifest.get('candidate_text_hashes_sha256'):
  raise RuntimeError('manifest/text-hash closure mismatch')
 side=files[f'{DEST}/CANDIDATE-MANIFEST.sha256'].decode().split()
 if not side or side[0]!=hashlib.sha256(manifest_bytes).hexdigest(): raise RuntimeError('manifest sidecar mismatch')
 # Candidate map manifest covers fifty source files. Changed members come from
 # the delta; the immutable original freeze supplies only unchanged text bytes.
 for rel,digest in declared.items():
  data=files.get(f'{DEST}/{rel}')
  if data is None:
   base=BASE/rel
   if base.is_symlink() or not base.is_file() or BASE.resolve() not in base.resolve().parents: raise RuntimeError(f'unchanged source missing/unsafe: {rel}')
   data=base.read_bytes(); data.decode('utf-8')
  if hashlib.sha256(data).hexdigest()!=digest: raise RuntimeError(f'full manifest payload mismatch: {rel}')
 return m,files,by

def remote_preflight(m,files,by):
 repo=gh_json(f'repos/{REPO}')
 if repo.get('full_name','').lower()!=REPO or repo.get('private') is not False or repo.get('default_branch')!='main': raise RuntimeError('repository identity/public/main check failed')
 current=gh_json(f'repos/{REPO}/commits/main')
 if current.get('sha')!=HEAD: raise RuntimeError(f'main moved: expected {HEAD}, got {current.get("sha")}')
 if current.get('commit',{}).get('tree',{}).get('sha')!=TREE: raise RuntimeError('native root tree differs from frozen map')
 tree=gh_json(f'repos/{REPO}/git/trees/{TREE}?recursive=1')
 if tree.get('truncated') is not False: raise RuntimeError('remote tree truncated or missing truncation status')
 remote={x['path']:x.get('sha') for x in tree.get('tree',[])}
 manifest=json.loads(files[f'{DEST}/CANDIDATE-MANIFEST.json'])
 # Validate the whole native package: candidate changes against proposed bytes;
 # unchanged members against their source bytes and native Git blob IDs.
 for rel,digest in manifest['candidate_files'].items():
  path=f'{DEST}/{rel}'; data=files.get(path)
  if data is None:
   base=BASE/rel; data=base.read_bytes()
  if hashlib.sha256(data).hexdigest()!=digest: raise RuntimeError(f'local manifest closure changed: {rel}')
  target=by.get(path)
  if target:
   observed=remote.get(path)
   if target['operation']=='create':
    if observed is not None: raise RuntimeError(f'create destination exists: {path}')
   else:
    pre=target['preimage']
    if observed!=pre['blob_sha1']: raise RuntimeError(f'native preimage moved: {path}')
    blob=gh_json(f'repos/{REPO}/git/blobs/{observed}')
    original=base64.b64decode(blob['content'])
    if len(original)!=pre['bytes'] or hashlib.sha256(original).hexdigest()!=pre['sha256'] or blob_sha(original)!=observed:
     raise RuntimeError(f'native preimage bytes/hash mismatch: {path}')
  elif remote.get(path)!=blob_sha(data): raise RuntimeError(f'unchanged manifest payload moved: {path}')
 # Sidecars and workflow alias are outside candidate_files but are explicit targets.
 for path,target in by.items():
  if path in {f'{DEST}/{rel}' for rel in manifest['candidate_files']}: continue
  observed=remote.get(path)
  if target['operation']=='create':
   if observed is not None: raise RuntimeError(f'create destination exists: {path}')
  else:
   pre=target['preimage']
   if observed!=pre['blob_sha1']: raise RuntimeError(f'native preimage moved: {path}')
   blob=gh_json(f'repos/{REPO}/git/blobs/{observed}'); raw=base64.b64decode(blob['content'])
   if len(raw)!=pre['bytes'] or hashlib.sha256(raw).hexdigest()!=pre['sha256'] or blob_sha(raw)!=observed: raise RuntimeError(f'native preimage mismatch: {path}')
 for path,sha in RUNTIME_PINS.items():
  if remote.get(path)!=sha: raise RuntimeError(f'runtime pin changed: {path}')
 return tree

def publish(m,files,by,tree):
 # Check the ref again before making any Git object POSTs; a moved-head negative
 # therefore produces zero POST/PATCH calls. The ref is checked once more just
 # before the non-force PATCH to close the object-creation race.
 if gh_json(f'repos/{REPO}/commits/main').get('sha')!=HEAD: raise RuntimeError('main moved before publication writes')
 entries=[]
 for path,data in sorted(files.items()):
  blob=gh_json(f'repos/{REPO}/git/blobs',method='POST',payload={'content':base64.b64encode(data).decode('ascii'),'encoding':'base64'})
  expected=by[path]['proposed']['blob_sha1']
  if blob.get('sha')!=expected: raise RuntimeError(f'GitHub blob identity mismatch: {path}')
  entries.append({'path':path,'mode':'100644','type':'blob','sha':blob['sha']})
 nt=gh_json(f'repos/{REPO}/git/trees',method='POST',payload={'base_tree':tree['sha'],'tree':entries})
 commit=gh_json(f'repos/{REPO}/git/commits',method='POST',payload={'message':'S83: repair actual source-note and evidence-state layout overlaps','tree':nt['sha'],'parents':[HEAD]})
 if gh_json(f'repos/{REPO}/commits/main').get('sha')!=HEAD: raise RuntimeError('main moved before non-force ref update; commit remains unreferenced')
 gh_json(f'repos/{REPO}/git/refs/heads/main',method='PATCH',payload={'sha':commit['sha'],'force':False})
 if gh_json(f'repos/{REPO}/commits/main').get('sha')!=commit['sha']: raise RuntimeError('post-publication main SHA mismatch')
 verify=gh_json(f'repos/{REPO}/git/trees/{nt["sha"]}?recursive=1')
 if verify.get('truncated') is not False: raise RuntimeError('post-publication tree truncated')
 observed={x['path']:x.get('sha') for x in verify.get('tree',[])}
 for path,t in by.items():
  if observed.get(path)!=t['proposed']['blob_sha1']: raise RuntimeError(f'post-publication target mismatch: {path}')
 for path,sha in RUNTIME_PINS.items():
  if observed.get(path)!=sha: raise RuntimeError(f'post-publication runtime pin mismatch: {path}')
 return commit['sha']

def main(argv=None):
 parser=argparse.ArgumentParser(); parser.add_argument('--publish',action='store_true'); args=parser.parse_args(argv)
 m,files,by=local_preflight(); tree=remote_preflight(m,files,by)
 if args.publish: print('PUBLISHED '+publish(m,files,by,tree)+'; no workflow dispatch performed')
 else: print('PREFLIGHT PASS: 10 exact text targets, 50-file manifest/hash closure, 8 native preimages, 9 runtime pins; zero writes')
 return 0

if __name__=='__main__':
 try: raise SystemExit(main())
 except Exception as exc: print(f'REFUSED: {exc}',file=sys.stderr); raise SystemExit(2)
