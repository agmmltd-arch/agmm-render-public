#!/usr/bin/env python3
"""On-hosted-runner verification of exact protected Git inputs; emits sanitized text only."""
import argparse, hashlib, json, os, subprocess
from pathlib import Path


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def main():
    p=argparse.ArgumentParser(); p.add_argument('--manifest',required=True,type=Path); p.add_argument('--checkout',required=True,type=Path); p.add_argument('--output',required=True,type=Path); a=p.parse_args()
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_OS')!='Linux' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise SystemExit('refusing protected media verification outside a GitHub-hosted Linux runner')
    d=json.loads(a.manifest.read_text()); rows=d.get('assets',[]); expected=d.get('private_tree_binding',{}).get('commit')
    if len(rows)!=18 or len({x.get('private_tree_path') for x in rows})!=18: raise ValueError('exact 18 unique inputs required')
    if git(a.checkout,'rev-parse','HEAD') != expected: raise ValueError('private checkout commit mismatch')
    results=[]
    for row in rows:
        rel=row['private_tree_path']; f=a.checkout/rel
        if f.is_symlink() or not f.is_file(): raise ValueError('protected input missing or not regular: '+row['name'])
        blob=git(a.checkout,'rev-parse',f'{expected}:{rel}')
        if blob!=row['git_blob_sha']: raise ValueError('native Git blob mismatch: '+row['name'])
        size=f.stat().st_size
        if size!=row['size']: raise ValueError('byte size mismatch: '+row['name'])
        h=hashlib.sha256()
        with f.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''): h.update(chunk)
        digest=h.hexdigest()
        if 'sha256:'+digest != row['digest']: raise ValueError('release SHA256 mismatch: '+row['name'])
        results.append({'name':row['name'],'asset_id':row['id'],'git_blob_sha':blob,'bytes':size,'sha256':digest,'status':'PASS'})
    receipt={'schema':'agmm-s83-protected-input-verification-v1','status':'PASS_18_EXACT_INPUTS','private_repository':d['repository'],'private_commit':expected,'asset_count':len(results),'items':results,'runner':'GitHub-hosted Linux','media_review':'NOT_PERFORMED'}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(receipt,indent=2)+'\n'); print('PROTECTED_INPUTS_VERIFIED assets=18 commit='+expected)
if __name__=='__main__': main()
