#!/usr/bin/env python3
"""Prepare a checked short's original story prompt on Ubuntu; never approve or post."""
import hashlib,json,os,re,subprocess,sys,tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE/'voice-native';sys.path.insert(0,str(ROOT/'kit/tools'))
import extract_story as story
from writer_crypto import crypt

def need(ok,message):
 if not ok:raise ValueError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()

def validate_manifest(root,sid,manifest_sha):
 need(re.fullmatch(r'S[0-9]{2,3}',sid or '') is not None,'invalid short ID')
 raw=(root/'MANIFEST.json').read_bytes();need(sha(raw)==manifest_sha,'manifest binding differs')
 data=json.loads(raw);need(data.get('schema')=='agmm-story-input-v2' and data.get('id')==sid and data.get('no_media') is True and data.get('release_approved') is False,'input manifest invalid')
 entries=data.get('files');need(isinstance(entries,dict) and 3<=len(entries)<=20,'invalid input inventory')
 allowed=lambda x: x in ('POINTER.json','story-data/STORY-DATA.md','shorts/scripts-v2/'+sid+'.md') or bool(re.fullmatch(r'shorts/scripts-v2/_sources/'+sid+r'_[0-9]+\.txt',x))
 need({'POINTER.json','story-data/STORY-DATA.md','shorts/scripts-v2/'+sid+'.md'}<=set(entries) and all(allowed(x) for x in entries),'input inventory differs')
 for name,digest in entries.items():
  f=root/name;need(re.fullmatch(r'[a-f0-9]{64}',digest or '') and not f.is_symlink() and f.is_file() and f.stat().st_size<2_000_000 and sha(f.read_bytes())==digest,'input bytes differ')
 pointer=json.loads((root/'POINTER.json').read_text())
 need(pointer.get('id')==sid and pointer.get('voice_checks_complete') is True and pointer.get('runtime_commit')=='94b4d6a419aeedb9ba1a769b184a44aed9dda4b3' and pointer.get('release_approval') is False and (pointer.get('request') or {}).get('selection_producer'),'checked voice identity differs')
 script='shorts/scripts-v2/'+sid+'.md';need((pointer.get('native_text_bindings') or {}).get(script)==entries[script],'checked voice script differs')
 return data,pointer

def main():
 need(sys.platform.startswith('linux') and os.getenv('GITHUB_ACTIONS')=='true','Ubuntu Actions required')
 root=Path(sys.argv[1]);sid=sys.argv[2];out=Path(sys.argv[3]);manifest,pointer=validate_manifest(root,sid,os.environ['STORY_MANIFEST_SHA'])
 for rel in manifest['files']:
  if rel.startswith('shorts/'):
   dest=ROOT/rel;dest.parent.mkdir(parents=True,exist_ok=True);need(not dest.exists(),'input would overwrite runtime');dest.write_bytes((root/rel).read_bytes())
 with tempfile.TemporaryDirectory(dir=os.environ['RUNNER_TEMP']) as temp:
  subprocess.run([sys.executable,str(HERE/'export_voice_timing.py'),str(root/'POINTER.json'),temp],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  timing=Path(temp)/(sid+'.words.json');receipt=json.loads((Path(temp)/'TIMING-RECEIPT.json').read_text());raw=timing.read_bytes()
  need(receipt['id']==sid and str(receipt['source_run_id'])==str(pointer['run_id']) and receipt.get('audio_exported') is False and receipt.get('release_approval') is False and sha(raw)==receipt['timing_sha256'],'timing source differs')
  dest=ROOT/'shorts/voice'/sid/(sid+'.words.json');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
  ctx=story.build_context(sid);need(ctx['mode']=='voice' and ctx['ranges'] is not None and bool(ctx['ledger']) and bool(ctx['sources']) and all(ctx['src_paras'].values()),'original story source or voice alignment incomplete')
  prompt=story.build_prompt(ctx)['full'];need(1000<len(prompt)<100_000,'invalid prompt size')
  packet={'schema':'agmm-story-prompt-v2','id':sid,'voice_run_id':pointer['run_id'],'source_manifest_sha256':os.environ['STORY_MANIFEST_SHA'],'timing_sha256':sha(raw),'prompt_sha256':sha(prompt.encode()),'prompt':prompt,'release_approved':False}
  out.write_bytes(crypt(json.dumps(packet,ensure_ascii=False).encode(),os.environ['AGMM_WRITER_PASS']));print('Exact checked voice and source-bound story prompt prepared; no release approval.')
if __name__=='__main__':main()
