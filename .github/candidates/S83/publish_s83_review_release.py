#!/usr/bin/env python3
"""Publish a four-asset S83 development preview only after draft SHA inventory checks."""
import argparse, hashlib, json, os, platform, re, subprocess
from pathlib import Path
REPO='agmmltd-arch/agmm-render-public'
FILES={'FINAL.mp4','PUBLIC-TECHNICAL-EVIDENCE.json','PREVIEW-SHA256SUMS.txt','S83-DEVELOPMENT-PREVIEW.json'}
class Refusal(ValueError): pass

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def expected_files(root,tag,head):
 root=Path(root); entries=list(root.iterdir())
 if root.is_symlink() or any(p.is_symlink() or not p.is_file() for p in entries) or {p.name for p in entries}!=FILES: raise Refusal('payload must contain exactly four regular review files')
 receipt=json.loads((root/'S83-DEVELOPMENT-PREVIEW.json').read_text())
 if receipt.get('schema')!='agmm-s83-development-preview-v1' or receipt.get('tag')!=tag or receipt.get('source_run',{}).get('head_sha')!=head: raise Refusal('preview receipt tag/head mismatch')
 if receipt.get('release_url')!=f'https://github.com/{REPO}/releases/tag/{tag}' or tag!=f"S83-development-review-{receipt.get('source_run',{}).get('id')}-a{receipt.get('source_run',{}).get('attempt')}": raise Refusal('preview tag URL/run identity mismatch')
 reviewed=receipt.get('reviewed_source_frames',{})
 if (reviewed.get('count')!=37 or reviewed.get('source_public_head_sha')!=head
         or reviewed.get('candidate_manifest_sha256')!=receipt.get('candidate_manifest_sha256')
         or not re.fullmatch(r'[0-9a-f]{64}',str(reviewed.get('sha256','')))):
  raise Refusal('preview does not bind 37 source frames independently reviewed for this exact candidate/head')
 binding=receipt.get('private_input_binding',{})
 if binding.get('repository')!='agmmltd-arch/agmm-video-render' or binding.get('count')!=18 or not re.fullmatch(r'[0-9a-f]{40}',str(binding.get('commit',''))) or any(not re.fullmatch(r'[0-9a-f]{64}',str(binding.get(k,''))) for k in ('manifest_sha256','verification_receipt_sha256')): raise Refusal('preview does not bind exact private input verification')
 tech=json.loads((root/'PUBLIC-TECHNICAL-EVIDENCE.json').read_text())
 if tech.get('schema')!='agmm-s83-public-review-technical-v1' or tech.get('technical_status')!='PASS' or tech.get('editorial_status')!='NOT_REVIEWED' or tech.get('full_av_review')!='OPEN' or tech.get('release_approval')!='NOT_GRANTED': raise Refusal('safe public technical receipt status mismatch')
 safe_reviewed=tech.get('reviewed_source_frames',{})
 if (tech.get('source_frames_sha256')!=reviewed.get('sha256') or tech.get('source_frame_binding_receipt_sha256')!=receipt.get('source_frame_binding_receipt_sha256') or safe_reviewed!=reviewed
         or not re.fullmatch(r'[0-9a-f]{64}',str(tech.get('source_frame_binding_receipt_sha256','')))):
  raise Refusal('technical receipt does not bind the reviewed 37-frame source packet')
 safe_mix=tech.get('source_mix',{}); bound_mix=receipt.get('source_mix',{})
 if any(safe_mix.get(k)!=bound_mix.get(k) for k in ('sha256','bytes','quality_receipt_sha256','source_clock_receipt_sha256')) or not re.fullmatch(r'[0-9a-f]{64}',str(safe_mix.get('sha256',''))) or not re.fullmatch(r'[0-9a-f]{64}',str(safe_mix.get('quality_receipt_sha256',''))): raise Refusal('preview does not carry the exact mix/quality receipt binding')
 if tech.get('master',{}).get('sha256')!=sha(root/'FINAL.mp4') or tech.get('master',{}).get('size_bytes')!=(root/'FINAL.mp4').stat().st_size or tech.get('master',{}).get('audio_streams')!=1: raise Refusal('safe technical receipt is not bound to the mixed video')
 if (receipt.get('editorial_status')!='NOT_REVIEWED' or receipt.get('full_av_review')!='OPEN' or receipt.get('release_approval')!='NOT_GRANTED' or receipt.get('ready')!='NOT_GRANTED' or receipt.get('raw_voice_or_stems_public') is not False): raise Refusal('preview lost review/private-input safeguards')
 if (root/'FINAL.mp4').read_bytes()[4:8]!=b'ftyp': raise Refusal('final is not an MP4 container')
 rows={p.name:{'name':p.name,'size':p.stat().st_size,'sha256':sha(p)} for p in entries}
 sums={}
 for line in (root/'PREVIEW-SHA256SUMS.txt').read_text().splitlines():
  h,n=line.split('  ',1)
  if n in sums: raise Refusal('duplicate checksum entry')
  sums[n]=h
 if sums!={n:rows[n]['sha256'] for n in ('FINAL.mp4','PUBLIC-TECHNICAL-EVIDENCE.json')}: raise Refusal('preview checksum inventory mismatch')
 inventory=receipt.get('asset_inventory')
 expected_inventory=[{'name':n,'size':rows[n]['size'],'sha256':rows[n]['sha256']} for n in ('FINAL.mp4','PUBLIC-TECHNICAL-EVIDENCE.json','PREVIEW-SHA256SUMS.txt')]
 if inventory!=expected_inventory: raise Refusal('preview receipt asset inventory mismatch')
 return rows

def validate_release(release,expected,tag,draft):
 if release.get('tag_name')!=tag or release.get('draft') is not draft or release.get('prerelease') is not True: raise Refusal('release tag/draft/prerelease state mismatch')
 found={}
 for asset in release.get('assets',[]):
  name=asset.get('name')
  if name in found or name not in expected: raise Refusal('release has duplicate or unexpected asset')
  want=expected[name]
  if asset.get('size')!=want['size'] or asset.get('digest')!='sha256:'+want['sha256']: raise Refusal('release asset size/SHA mismatch: '+str(name))
  if asset.get('browser_download_url')!=f'https://github.com/{REPO}/releases/download/{tag}/{name}': raise Refusal('release asset URL mismatch')
  found[name]=asset
 if set(found)!=set(expected): raise Refusal('release inventory is missing one or more expected assets')
 return found

def gh(args): return subprocess.run(['gh',*args],text=True,capture_output=True,check=False)
def publish(root,tag,head):
 if platform.system()!='Linux' or os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted': raise Refusal('release publishing requires GitHub-hosted Linux')
 if os.environ.get('GITHUB_REPOSITORY')!=REPO or os.environ.get('GITHUB_REF')!='refs/heads/main' or os.environ.get('GITHUB_SHA')!=head: raise Refusal('public repo/main/exact-head guard failed')
 if tag!=f"S83-development-review-{os.environ.get('GITHUB_RUN_ID')}-a{os.environ.get('GITHUB_RUN_ATTEMPT')}": raise Refusal('release tag does not match the actual native run/attempt')
 expected=expected_files(root,tag,head)
 query=gh(['api',f'repos/{REPO}/releases/tags/{tag}'])
 if query.returncode==0: raise Refusal('release tag already exists; no overwrite')
 try: missing=json.loads(query.stdout)
 except ValueError: missing={}
 if query.returncode!=1 or query.stderr.strip()!='gh: Not Found (HTTP 404)' or missing.get('status')!='404': raise Refusal('tag lookup not confirmed native HTTP 404; no create')
 create=gh(['release','create',tag,'--repo',REPO,'--target',head,'--title',f'S83 development preview {tag}','--notes','Hosted S83 review preview only. Full audiovisual review OPEN; rights NOT_ASSESSED; release approval NOT_GRANTED; Ready NOT_GRANTED.','--prerelease','--draft'])
 if create.returncode: raise Refusal('draft preview release creation failed')
 for name in sorted(FILES):
  uploaded=gh(['release','upload',tag,str(Path(root)/name),'--repo',REPO])
  if uploaded.returncode: raise Refusal('draft upload failed: '+name)
 query=gh(['api',f'repos/{REPO}/releases/tags/{tag}'])
 if query.returncode: raise Refusal('draft release inventory unavailable')
 draft=json.loads(query.stdout); found=validate_release(draft,expected,tag,True)
 commit=gh(['api',f'repos/{REPO}/commits/{tag}'])
 if commit.returncode or json.loads(commit.stdout).get('sha')!=head: raise Refusal('draft preview tag does not resolve to the exact reviewed head')
 if set(found)!=FILES: raise Refusal('draft asset inventory incomplete; release remains draft')
 published=gh(['release','edit',tag,'--repo',REPO,'--draft=false'])
 if published.returncode: raise Refusal('verified draft could not be published')
 query=gh(['api',f'repos/{REPO}/releases/tags/{tag}'])
 if query.returncode: raise Refusal('published release cannot be verified')
 release=json.loads(query.stdout); found=validate_release(release,expected,tag,False)
 commit=gh(['api',f'repos/{REPO}/commits/{tag}'])
 if commit.returncode or json.loads(commit.stdout).get('sha')!=head: raise Refusal('published preview tag does not resolve to the exact reviewed head')
 if set(found)!=FILES: raise Refusal('published asset inventory incomplete')
 return {'tag':tag,'asset_count':len(found),'full_av_review':'OPEN','release_approval':'NOT_GRANTED','ready':'NOT_GRANTED'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--payload',required=True);p.add_argument('--tag',required=True);p.add_argument('--head',required=True);a=p.parse_args();print(json.dumps(publish(a.payload,a.tag,a.head),indent=2))
if __name__=='__main__':
 try: main()
 except Exception as e: raise SystemExit('REFUSED: '+str(e)) from e
