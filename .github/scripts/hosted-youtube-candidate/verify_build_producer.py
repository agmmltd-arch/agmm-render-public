#!/usr/bin/env python3
"""Verify the actual native build run and its encrypted owner receipt."""
import argparse
import io
import json
import os
import platform
import re
import subprocess
import tarfile
import urllib.request
from pathlib import Path

REPO='agmmltd-arch/agmm-render-public'
ALLOWED_RUNTIME={'44edcc3fc0de6cc08657af9e3d1787087661c427'}


def api(path):
    token=os.environ.get('GH_TOKEN')
    if not token:raise ValueError('GitHub token unavailable')
    req=urllib.request.Request('https://api.github.com/'+path,
        headers={'Accept':'application/vnd.github+json','Authorization':'Bearer '+token})
    with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)


def verify(run_id, metadata, hashes):
    if platform.system()!='Linux' or os.environ.get('GITHUB_ACTIONS','').lower() not in ('true','1'):
        raise ValueError('producer verification requires hosted Linux Actions')
    if not re.fullmatch(r'[0-9]{6,}',run_id or ''):raise ValueError('invalid build run ID')
    if not os.environ.get('VOICEFREE_PASS'):raise ValueError('receipt key unavailable')
    run=api('repos/'+REPO+'/actions/runs/'+run_id)
    if (run.get('event')!='workflow_dispatch' or run.get('conclusion')!='success'
            or run.get('run_attempt')!=1 or run.get('head_sha') not in ALLOWED_RUNTIME
            or not str(run.get('path','')).startswith('.github/workflows/native-build-encrypted-candidate.yml')):
        raise ValueError('native build producer not qualified')
    jobs=api('repos/'+REPO+'/actions/runs/'+run_id+'/jobs?per_page=100').get('jobs',[])
    matches=[j for j in jobs if j.get('name')=='build' and j.get('conclusion')=='success']
    if len(matches)!=1:raise ValueError('unique successful native build job required')
    steps={s.get('name'):s.get('conclusion') for s in matches[0].get('steps',[])}
    for name in ('Run unchanged native source and sound build with provider access denied',
                 'Seal exact native inputs to an encrypted package',
                 'Return encrypted native build input','Return encrypted native build metadata'):
        if steps.get(name)!='success':raise ValueError('native producer step missing: '+name)
    if metadata.is_symlink() or not metadata.is_file() or metadata.stat().st_size>20_000_000:raise ValueError('invalid encrypted metadata')
    plain=subprocess.run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-pass','env:VOICEFREE_PASS',
                          '-in',str(metadata)],capture_output=True,check=True).stdout
    if len(plain)>20_000_000:raise ValueError('native receipt archive too large')
    with tarfile.open(fileobj=io.BytesIO(plain),mode='r:') as t:
        entries=t.getmembers();files=[m for m in entries if m.isfile()]
        if any(not (m.isfile() or m.isdir()) or not m.name.startswith('native-build-json') or '..' in Path(m.name).parts for m in entries):
            raise ValueError('unsafe receipt archive')
        matches=[m for m in files if m.name=='native-build-json/PACKAGE-RECEIPT.json']
        if len(matches)!=1 or matches[0].size>2_000_000:raise ValueError('native receipt missing or duplicated')
        receipt=json.load(t.extractfile(matches[0]))
    if (receipt.get('status')!='NATIVE_PACKAGE_ENCRYPTED_NOT_UPLOADED'
            or str(receipt.get('run_id'))!=run_id or receipt.get('runtime_commit')!=run['head_sha']
            or receipt.get('release_approved') is not False or receipt.get('content_posted') is not False):
        raise ValueError('native owner receipt mismatch')
    exact=receipt.get('exact_request',{}).get('inputs',{})
    for key in ('source','parts','mix'):
        if (exact.get(key) or {}).get('sha256')!=hashes[key]:raise ValueError('build input binding mismatch')
    print('Completed native producer and exact source/parts/audio pins verified; no release approval')


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--metadata',type=Path,required=True)
    p.add_argument('--source-sha256',required=True);p.add_argument('--parts-sha256',required=True);p.add_argument('--mix-sha256',required=True)
    a=p.parse_args();verify(a.run_id,a.metadata,{'source':a.source_sha256,'parts':a.parts_sha256,'mix':a.mix_sha256})


if __name__=='__main__':main()
