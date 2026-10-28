#!/usr/bin/env python3
"""Build a source-bound story-label request on Ubuntu; output authenticated ciphertext only."""
import hashlib, io, json, os, re, subprocess, sys, tarfile, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent / 'voice-native'
sys.path.insert(0,str(ROOT/'kit/tools'))
from writer_crypto import crypt
import extract_story as story

def need(ok, message):
    if not ok: raise ValueError(message)

def sha(b): return hashlib.sha256(b).hexdigest()

def main():
    need(sys.platform.startswith('linux') and os.getenv('GITHUB_ACTIONS')=='true','Ubuntu Actions required')
    root=Path(sys.argv[1]); output=Path(sys.argv[2]); m=(root/'MANIFEST.json').read_bytes()
    need(sha(m)==os.environ['STORY_MANIFEST_SHA'], 'manifest differs')
    manifest=json.loads(m); need(manifest['id']=='S286' and manifest['voice_run_id']==40775520117 and manifest['timing_run_id']==40777347363 and manifest['no_media'] is True,'manifest identity')
    for rel,h in manifest['files'].items():
        need(re.fullmatch(r'[a-zA-Z0-9_./-]+',rel) is not None and '..' not in Path(rel).parts,'unsafe path')
        source=root/rel;need(source.is_file() and not source.is_symlink() and source.stat().st_size<2_000_000 and sha(source.read_bytes())==h,'source changed')
        if rel.startswith('shorts/'):
            target=ROOT/rel; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(source.read_bytes())
    meta=json.loads(subprocess.check_output(['gh','api','repos/agmmltd-arch/agmm-render-public/actions/artifacts/12853589799']))
    need(meta['id']==12853589799 and meta['name']=='S286-timing-proof-ENC' and not meta['expired'] and meta['workflow_run']['id']==40777347363 and meta['digest']=='sha256:a605752d939e6d838081c3ee894d8de1607607fdbfb3b43b979cfaa86bfc6ca7','timing source artifact invalid')
    run=json.loads(subprocess.check_output(['gh','api','repos/agmmltd-arch/agmm-render-public/actions/runs/40777347363']))
    need(run['head_sha']=='53481d15e810a67065060542418bf3bf9ed7f555' and run['status']=='completed' and run['conclusion']=='success' and run['run_attempt']==1,'timing producer invalid')
    raw=subprocess.check_output(['gh','api','repos/agmmltd-arch/agmm-render-public/actions/artifacts/12853589799/zip'])
    need(len(raw)<5_000_000 and 'sha256:'+sha(raw)==meta['digest'],'timing artifact bytes invalid')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=z.namelist();need(names==['timing.enc'] and z.getinfo('timing.enc').file_size<5_000_000,'timing archive invalid');cipher=z.read('timing.enc')
    plain=subprocess.run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-pass','env:VOICEFREE_PASS'],input=cipher,capture_output=True,check=True).stdout
    need(len(plain)<10_000_000,'timing tar too large')
    with tarfile.open(fileobj=io.BytesIO(plain),mode='r:') as tar:
        items=tar.getmembers(); need(all(x.isfile() or x.isdir() for x in items),'unsafe timing tar')
        regular=[x for x in items if x.isfile()]; files={x.name.removeprefix('./'):x for x in regular}
        need(len(regular)==2 and len(files)==2 and set(files)=={'S286.words.json','TIMING-RECEIPT.json'} and all(x.size<5_000_000 for x in files.values()),'timing tar inventory invalid')
        words=tar.extractfile(files['S286.words.json']).read(); receipt=json.loads(tar.extractfile(files['TIMING-RECEIPT.json']).read())
    need(receipt['id']=='S286' and receipt['source_run_id']=='40775520117' and receipt['artifact_id']=='12853429931' and receipt['audio_exported'] is False and receipt['release_approval'] is False and sha(words)==receipt['timing_sha256'],'timing receipt invalid')
    timing=ROOT/'shorts/voice/S286/S286.words.json';timing.parent.mkdir(parents=True,exist_ok=True);timing.write_bytes(words)
    ctx=story.build_context('S286');need(ctx['mode']=='voice' and ctx['ranges'] is not None and len(ctx['ledger'])>0 and len(ctx['sources'])==2 and all(ctx['src_paras'].values()),'story source or voice alignment incomplete')
    prompt=story.build_prompt(ctx)['full'];need(1000<len(prompt)<100_000,'story prompt size invalid')
    packet={'schema':'agmm-story-prompt-v1','id':'S286','voice_run_id':40775520117,'timing_run_id':40777347363,'source_manifest_sha256':sha(m),'timing_sha256':sha(words),'prompt_sha256':sha(prompt.encode()),'prompt':prompt,'release_approved':False}
    password=os.environ['AGMM_WRITER_PASS'];output.write_bytes(crypt(json.dumps(packet,ensure_ascii=False).encode(),password));print('Prepared authenticated story prompt; exact sources and checked timing bound; no approval.')
if __name__=='__main__':main()
