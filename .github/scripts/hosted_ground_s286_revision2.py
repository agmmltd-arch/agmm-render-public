#!/usr/bin/env python3
"""Verify both exact provider replies and replay original grounded correction on Ubuntu."""
import hashlib,io,json,os,re,subprocess,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE/'voice-native';sys.path.insert(0,str(ROOT/'kit/tools'))
import extract_story as story
from writer_crypto import crypt
REPO='agmmltd-arch/agmm-render-public';WF='.github/workflows/agmm-protected-llm-writer.yml';BLOB='8d0106cba8b46e207c3afe2f385841fbce914697'
def need(ok,msg):
 if not ok:raise ValueError(msg)
def sha(b):return hashlib.sha256(b).hexdigest()
def api(path):return json.loads(subprocess.check_output(['gh','api',path]))
def provider(saved,password):
 meta=saved['meta'];rid=meta['request_id'];run_id=meta['run_id'];need(meta.get('model_key')=='q30a3b-iq3xxs' and re.fullmatch(r'w[0-9a-f]{12}',rid or ''),'writer metadata invalid')
 run=api('repos/%s/actions/runs/%s'%(REPO,run_id));need(run.get('path')==WF and run.get('event')=='workflow_dispatch' and run.get('run_attempt')==1 and run.get('status')=='completed' and run.get('conclusion')=='success' and run.get('display_title')=='llmw '+rid,'writer run invalid')
 need(api('repos/%s/contents/%s?ref=%s'%(REPO,WF,run['head_sha']))['sha']==BLOB,'writer workflow changed')
 aa=api('repos/%s/actions/runs/%s/artifacts?per_page=100'%(REPO,run_id))['artifacts'];arts=[x for x in aa if x.get('name')=='llm-'+rid and not x.get('expired')];need(len(arts)==1 and arts[0]['workflow_run']['id']==run_id and re.fullmatch(r'sha256:[a-f0-9]{64}',arts[0].get('digest') or ''),'writer artifact invalid')
 raw=subprocess.check_output(['gh','api','repos/%s/actions/artifacts/%s/zip'%(REPO,arts[0]['id'])]);need(len(raw)<10_000_000 and 'sha256:'+sha(raw)==arts[0]['digest'],'writer artifact digest differs')
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  need(z.namelist()==['response.enc'] and z.getinfo('response.enc').file_size<9_000_000,'writer archive invalid');p=json.loads(crypt(z.read('response.enc'),password,True))
 need(p['meta'].get('request_id')==rid and p['meta'].get('model')=='q30a3b-iq3xxs','provider request differs')
 text=((p['response'].get('choices') or [{}])[0].get('message') or {}).get('content') or '';text=re.sub(r'(?is)<think>.*?</think>','',text.strip()).strip();need(text==saved['response'],'writer response differs');return text

def prior_attested(first_path,revision_path,password):
 need(sha(first_path.read_bytes())=='1e68f8f9877bf5464ddafde832571f3de118a53c8204e7c11834271fa850d6b0','first response differs')
 d=sha(revision_path.read_bytes());need(d=='c7c765af6bd887f2580f064d91fc1686ac3982863743b0a8ee9150713dc0e681','first correction differs')
 run=api('repos/%s/actions/runs/40783509716'%REPO);path='.github/workflows/s286-ground-revision1-candidate.yml'
 need(run.get('path')==path and run.get('display_title')=='S286 correction grounding '+d and run.get('event')=='workflow_dispatch' and run.get('run_attempt')==1 and run.get('status')=='completed' and run.get('conclusion')=='success','prior run identity differs')
 need(api('repos/%s/contents/%s?ref=%s'%(REPO,path,run['head_sha'])).get('sha')=='1aae308d400586aee6bfc7615cad310bae29553c','prior workflow differs')
 a=api('repos/%s/actions/artifacts/12858635556'%REPO);need(not a.get('expired') and a.get('workflow_run',{}).get('id')==40783509716 and a.get('name')=='S286-revision1-grounded-ENC','prior report unavailable')
 raw=subprocess.check_output(['gh','api','repos/%s/actions/artifacts/12858635556/zip'%REPO]);need(a.get('digest')=='sha256:'+sha(raw),'prior report digest differs')
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  need(z.namelist()==['grounded.enc'] and z.getinfo('grounded.enc').file_size<9000000,'prior report archive differs');packet=json.loads(crypt(z.read('grounded.enc'),password,True))
 need(packet.get('id')=='S286' and packet.get('writer_runs')==[40778105350,40780853048] and packet.get('release_approved') is False and packet.get('independent_av_review') is False,'prior report identity differs')
 return packet

def main():
 need(sys.platform.startswith('linux') and os.getenv('GITHUB_ACTIONS')=='true','Ubuntu Actions required')
 prompt_path,first_path,revision_path,revision2_path,schema_path,out=map(Path,sys.argv[1:7]);password=os.environ['AGMM_WRITER_PASS']
 prompt=json.loads(crypt(prompt_path.read_bytes(),password,True));first=json.loads(crypt(first_path.read_bytes(),password,True));revision=json.loads(crypt(revision_path.read_bytes(),password,True));revision2=json.loads(crypt(revision2_path.read_bytes(),password,True))
 need(prompt.get('id')==first.get('id')==revision.get('id')=='S286' and prompt['prompt_sha256']==first['prompt_sha256'] and sha(prompt['prompt'].encode())==prompt['prompt_sha256'],'original prompt binding differs')
 prior=prior_attested(first_path,revision_path,password);one=first['response'];two=revision['response'];three=provider(revision2,password);need(revision2.get('id')=='S286' and len({first['meta']['run_id'],revision['meta']['run_id'],revision2['meta']['run_id']})==3,'reused writer run')
 story.STORY_DATA_MD=str(schema_path);need(story.load_schema() is not None,'original schema missing');ctx=story.build_context('S286');need(ctx['mode']=='voice' and ctx['ranges'] is not None,'checked voice missing')
 generated=story.build_prompt(ctx);need(sha(generated['full'].encode())==prompt['prompt_sha256'],'current prompt differs')
 before,fail,_=story.extract('S286',ctx=ctx,replies=[{'text':one,'lane':'ghw-q30a3b-iq3xxs','family':'free-hosted'}],retries=0,save_receipts=False);need(before is not None and before.get('status')=='rejected' and bool(fail),'no failed initial grounding')
 correction=story.feedback_prompt(generated,one,fail)['full'];need(sha(correction.encode())==revision['prompt_sha256'],'feedback prompt differs')
 result,failures,_=story.extract('S286',ctx=ctx,replies=[{'text':one,'lane':'ghw-q30a3b-iq3xxs','family':'free-hosted'},{'text':two,'lane':'ghw-q30a3b-iq3xxs','family':'free-hosted'}],retries=1,save_receipts=False)
 need(result is not None and result==prior['story'] and failures==prior['grounding_failures'] and prior['schema_errors']==[],'first correction replay differs')
 feedback2=story.feedback_prompt(generated,two,failures)['full'];need(sha(feedback2.encode())==revision2['prompt_sha256'],'second feedback prompt differs')
 result,failures,_=story.extract('S286',ctx=ctx,replies=[{'text':one,'lane':'ghw-q30a3b-iq3xxs','family':'free-hosted'},{'text':two,'lane':'ghw-q30a3b-iq3xxs','family':'free-hosted'},{'text':three,'lane':'ghw-q30a3b-iq3xxs','family':'free-hosted'}],retries=2,save_receipts=False)
 need(result is not None,'no final original story result');errors=story.schema_errors(result) if result.get('status')!='rejected' else []
 packet={'schema':'agmm-hosted-story-grounding-revision2-v1','id':'S286','writer_runs':[first['meta']['run_id'],revision['meta']['run_id'],revision2['meta']['run_id']],'story':result,'grounding_failures':failures,'schema_errors':errors,'release_approved':False,'independent_av_review':False}
 out.write_bytes(crypt(json.dumps(packet,ensure_ascii=False).encode(),password));print('Original grounding replay complete; status=%s failures=%d schema_errors=%d; no release approval.'%(result.get('status'),len(failures),len(errors)))
if __name__=='__main__':main()
