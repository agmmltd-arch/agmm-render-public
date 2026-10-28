#!/usr/bin/env python3
"""Recheck an exact free-writer response with original story grounding on Ubuntu."""
import hashlib, io, json, os, re, subprocess, sys, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent/'voice-native'
sys.path.insert(0,str(ROOT/'kit/tools'))
import extract_story as story
from writer_crypto import crypt

REPO='agmmltd-arch/agmm-render-public'
WRITER='.github/workflows/agmm-protected-llm-writer.yml'
BLOB='8d0106cba8b46e207c3afe2f385841fbce914697'
def need(ok,msg):
 if not ok:raise ValueError(msg)
def api(path):return json.loads(subprocess.check_output(['gh','api',path]))
def sha(data):return hashlib.sha256(data).hexdigest()

def main():
 need(sys.platform.startswith('linux') and os.getenv('GITHUB_ACTIONS')=='true','Ubuntu Actions required')
 prompt_path, response_path, schema_path, output = map(Path,sys.argv[1:5]);password=os.environ['AGMM_WRITER_PASS']
 prompt=json.loads(crypt(prompt_path.read_bytes(),password,True));saved=json.loads(crypt(response_path.read_bytes(),password,True));meta=saved['meta'];rid=meta['request_id'];run_id=meta['run_id']
 need(prompt.get('id')=='S286' and saved.get('id')=='S286' and prompt['prompt_sha256']==saved['prompt_sha256'] and sha(prompt['prompt'].encode())==prompt['prompt_sha256'] and meta.get('model_key')=='q30a3b-iq3xxs' and re.fullmatch(r'w[0-9a-f]{12}',rid),'prompt/response binding invalid')
 run=api('repos/%s/actions/runs/%s'%(REPO,run_id));need(run.get('path')==WRITER and run.get('event')=='workflow_dispatch' and run.get('run_attempt')==1 and run.get('status')=='completed' and run.get('conclusion')=='success' and run.get('display_title')=='llmw '+rid,'writer run invalid')
 tree=api('repos/%s/contents/%s?ref=%s'%(REPO,WRITER,run['head_sha']));need(tree.get('sha')==BLOB,'writer workflow source changed')
 artifacts=api('repos/%s/actions/runs/%s/artifacts?per_page=100'%(REPO,run_id))['artifacts'];art=[a for a in artifacts if a['name']=='llm-'+rid and not a['expired']]
 need(len(art)==1 and art[0]['workflow_run']['id']==run_id and re.fullmatch(r'sha256:[a-f0-9]{64}',art[0]['digest']),'writer response artifact invalid')
 raw=subprocess.check_output(['gh','api','repos/%s/actions/artifacts/%s/zip'%(REPO,art[0]['id'])]);need(len(raw)<10_000_000 and 'sha256:'+sha(raw)==art[0]['digest'],'writer response digest invalid')
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  need(z.namelist()==['response.enc'] and z.getinfo('response.enc').file_size<9_000_000,'writer response archive invalid');provider=json.loads(crypt(z.read('response.enc'),password,True))
 need(provider['meta'].get('request_id')==rid and provider['meta'].get('model')=='q30a3b-iq3xxs','provider request identity differs')
 answer=((provider['response'].get('choices') or [{}])[0].get('message') or {}).get('content') or ''
 answer=re.sub(r'(?is)<think>.*?</think>','',answer.strip()).strip();need(answer==saved['response'],'saved response differs from provider')
 story.STORY_DATA_MD=str(schema_path);need(story.load_schema() is not None,'original schema missing')
 ctx=story.build_context('S286');need(ctx['mode']=='voice' and ctx['ranges'] is not None,'checked voice context missing')
 value,failures,_=story.extract('S286',ctx=ctx,replies=[{'text':answer,'lane':'ghw-q30a3b-iq3xxs','family':'free-hosted'}],retries=0,save_receipts=False)
 need(value is not None,'original extractor produced no story');errors=story.schema_errors(value) if value.get('status')!='rejected' else []
 result={'schema':'agmm-hosted-story-grounding-v1','id':'S286','writer_run_id':run_id,'prompt_sha256':prompt['prompt_sha256'],'story':value,'grounding_failures':failures,'schema_errors':errors,'release_approved':False,'independent_av_review':False}
 output.write_bytes(crypt(json.dumps(result,ensure_ascii=False).encode(),password));print('Original grounding complete; status=%s, failures=%d, schema_errors=%d; no release approval.'%(value.get('status'),len(failures),len(errors)))
if __name__=='__main__':main()
