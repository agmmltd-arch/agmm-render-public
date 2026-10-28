#!/usr/bin/env python3
"""Preserve an exact encrypted native voice artifact on private Git from Ubuntu only."""
import hashlib,json,os,re,shutil,subprocess,sys,tempfile
from pathlib import Path
PUBLIC='agmmltd-arch/agmm-render-public';PRIVATE='agmmltd-arch/agmm-video-render'
def need(ok,msg):
 if not ok:raise ValueError(msg)
def sha_file(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def archive_branch(pointer):
 sid=pointer.get('id','');run=pointer.get('run_id');artifact=pointer.get('artifact_id');digest=pointer.get('artifact_digest','')
 need(re.fullmatch(r'S[0-9]{2,3}',sid or '') and isinstance(run,int) and isinstance(artifact,int) and re.fullmatch(r'sha256:[a-f0-9]{64}',digest or ''),'invalid voice archive identity')
 need(pointer.get('voice_checks_complete') is True and pointer.get('release_approval') is False and pointer.get('runtime_commit')=='94b4d6a419aeedb9ba1a769b184a44aed9dda4b3' and (pointer.get('request') or {}).get('selection_producer'),'voice not exact completed selected take')
 return 'voice-archive-'+sid.lower()+'-'+str(artifact)+'-'+digest[7:23]
def gh_json(path):return json.loads(subprocess.check_output(['gh','api',path]))
def main():
 need(sys.platform.startswith('linux') and os.environ.get('GITHUB_ACTIONS')=='true','Ubuntu Actions required')
 pointer_path=Path(sys.argv[1]);output=Path(sys.argv[2]);pointer=json.loads(pointer_path.read_text());branch=archive_branch(pointer)
 need(os.environ.get('VOICEFREE_PASS') and os.environ.get('AGMM_VOICE_ARCHIVE_DEPLOY_KEY'),'protected credentials unavailable')
 # Original exporter independently checks exact successful producer, source blobs,
 # artifact digest and native receipt, and extracts timing only on this runner.
 with tempfile.TemporaryDirectory(dir=os.environ['RUNNER_TEMP']) as tmp:
  work=Path(tmp);verified=work/'verified'
  subprocess.run([sys.executable,str(Path(__file__).with_name('export_voice_timing.py')),str(pointer_path),str(verified)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  receipt=json.loads((verified/'TIMING-RECEIPT.json').read_text());need(receipt['id']==pointer['id'] and str(receipt['artifact_id'])==str(pointer['artifact_id']) and receipt['release_approval'] is False,'native voice verification differs')
  meta=gh_json('repos/%s/actions/artifacts/%s'%(PUBLIC,pointer['artifact_id']));need(meta.get('digest')==pointer['artifact_digest'] and meta.get('workflow_run',{}).get('id')==pointer['run_id'] and not meta.get('expired'),'artifact changed')
  archive=work/'voice-generated.zip'
  with archive.open('xb') as f:subprocess.run(['gh','api','repos/%s/actions/artifacts/%s/zip'%(PUBLIC,pointer['artifact_id'])],stdout=f,stderr=subprocess.PIPE,check=True)
  need(archive.stat().st_size<90_000_000 and 'sha256:'+sha_file(archive)==pointer['artifact_digest'],'voice archive digest differs')
  key=work/'deploy-key';key.write_text(os.environ['AGMM_VOICE_ARCHIVE_DEPLOY_KEY']);key.chmod(0o600)
  env=dict(os.environ);env.pop('AGMM_VOICE_ARCHIVE_DEPLOY_KEY',None);env.pop('VOICEFREE_PASS',None)
  ssh='ssh -i '+str(key)+' -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new'
  env['GIT_SSH_COMMAND']=ssh;remote='git@github.com:'+PRIVATE+'.git'
  probe=subprocess.run(['git','ls-remote','--exit-code','--heads',remote,'refs/heads/'+branch],capture_output=True,env=env)
  need(probe.returncode==2,'archive branch already exists or remote outcome unknown')
  repo=work/'repo';repo.mkdir();subprocess.run(['git','init','-q'],cwd=repo,env=env,check=True)
  subprocess.run(['git','config','user.name','AGMM hosted archive'],cwd=repo,env=env,check=True);subprocess.run(['git','config','user.email','actions@users.noreply.github.com'],cwd=repo,env=env,check=True)
  shutil.copyfile(archive,repo/'voice-generated.zip');(repo/'pointer.json').write_text(json.dumps(pointer,sort_keys=True,indent=2)+'\n')
  binding={'schema':'agmm-private-voice-archive-v1','id':pointer['id'],'source_run_id':pointer['run_id'],'artifact_id':pointer['artifact_id'],'artifact_digest':pointer['artifact_digest'],'pointer_sha256':sha_file(repo/'pointer.json'),'release_approved':False}
  (repo/'ARCHIVE.json').write_text(json.dumps(binding,sort_keys=True,indent=2)+'\n')
  subprocess.run(['git','add','voice-generated.zip','pointer.json','ARCHIVE.json'],cwd=repo,env=env,check=True);subprocess.run(['git','commit','-qm','Preserve encrypted checked voice'],cwd=repo,env=env,check=True)
  commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,env=env,text=True).strip();need(re.fullmatch(r'[a-f0-9]{40}',commit),'bad archive commit')
  subprocess.run(['git','push',remote,commit+':refs/heads/'+branch],cwd=repo,env=env,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  remote_line=subprocess.check_output(['git','ls-remote','--heads',remote,'refs/heads/'+branch],env=env,text=True).strip();need(remote_line.split()[0]==commit,'archive branch readback differs')
  # Read the newly pushed content back on the hosted runner and verify exact provider digest.
  verify=work/'verify';verify.mkdir();subprocess.run(['git','init','-q'],cwd=verify,env=env,check=True);subprocess.run(['git','fetch','-q','--depth=1',remote,'refs/heads/'+branch],cwd=verify,env=env,check=True)
  with (work/'readback.zip').open('xb') as f:subprocess.run(['git','show','FETCH_HEAD:voice-generated.zip'],cwd=verify,env=env,stdout=f,stderr=subprocess.PIPE,check=True)
  need('sha256:'+sha_file(work/'readback.zip')==pointer['artifact_digest'],'private readback differs')
  output.write_text(json.dumps({'schema':'agmm-private-voice-archive-receipt-v1','id':pointer['id'],'source_run_id':pointer['run_id'],'artifact_id':pointer['artifact_id'],'artifact_digest':pointer['artifact_digest'],'private_branch':branch,'private_commit':commit,'release_approved':False},indent=2)+'\n')
  print('Exact encrypted voice preserved privately and read back; no release approval.')
if __name__=='__main__':main()
