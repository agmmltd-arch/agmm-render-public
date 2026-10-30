#!/usr/bin/env python3
"""Hosted-only, non-approving hydration of the exact resolved Intel source."""
import hashlib,io,json,os,subprocess,sys,tarfile,zipfile
from pathlib import Path
REPO='agmmltd-arch/agmm-render-public';RUN=41122956665;ART=13010140030;HEAD='4fd75cfe967de30bc0c3f71fa92542510b6f1385'
def need(ok,msg):
 if not ok:raise ValueError(msg)
def api(path):return json.loads(subprocess.check_output(['gh','api','repos/'+REPO+path]))
def hydrate(root,sid):
 need(sys.platform.startswith('linux') and os.environ.get('GITHUB_ACTIONS')=='true','Ubuntu Actions required');need(sid=='S384','exact short only')
 run=api('/actions/runs/'+str(RUN));need(run.get('head_sha')==HEAD and run.get('run_attempt')==1 and run.get('event')=='workflow_dispatch' and run.get('status')=='completed' and run.get('conclusion')=='success' and run.get('path')=='.github/workflows/intel-licensed-logo-proof.yml','producer differs')
 artifact=api('/actions/artifacts/'+str(ART));need(artifact.get('name')=='intel-logo-source-ENC' and artifact.get('workflow_run',{}).get('id')==RUN and not artifact.get('expired'),'artifact differs')
 raw=subprocess.check_output(['gh','api','repos/'+REPO+'/actions/artifacts/'+str(ART)+'/zip']);need(artifact.get('digest')=='sha256:'+hashlib.sha256(raw).hexdigest() and len(raw)<10_000_000,'artifact bytes differ')
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  need(z.namelist()==['intel-asset.enc'],'unexpected archive');encrypted=z.read('intel-asset.enc')
 plain=subprocess.run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-pass','env:VOICEFREE_PASS'],input=encrypted,capture_output=True,check=True).stdout
 with tarfile.open(fileobj=io.BytesIO(plain)) as tar:
  members=tar.getmembers();names=[x.name for x in members];need(len(members)==2 and all(x.isfile() for x in members) and 'intel.json' in names,'unexpected source inventory');logos=[x for x in members if x.name in ('intel-logo.png','intel-logo.jpg','intel-logo.jpeg','intel-logo.webp')];need(len(logos)==1 and 800<logos[0].size<5_000_000,'logo size or type differs')
  rec=json.load(tar.extractfile('intel.json'));need(rec.get('name')=='Intel' and rec.get('commons')=='https://commons.wikimedia.org/wiki/File:Intel_logo_2023.svg' and rec.get('licence')=='Public domain' and rec.get('restrictions')=='trademarked','source rights metadata differs')
  logo=tar.extractfile(logos[0]).read();need(len(logo)==logos[0].size,'logo length differs')
  root=Path(root);base=root/'kit/assets';target=base/'cache/logos'/('intel'+Path(logos[0].name).suffix);record=base/sid/'assets.json';need(not target.exists() and not record.exists(),'asset would overwrite existing')
  target.parent.mkdir(parents=True,exist_ok=True);record.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(logo)
  rec['file']=str(target.relative_to(base));document={'id':sid,'logos':{'Intel':rec},'wordmarks':{},'photos':[],'source_proof_run':RUN,'release_approval':False}
  record.write_text(json.dumps(document,indent=2)+'\n');print('Exact source candidate hydrated; rights and creative review remain required.')
if __name__=='__main__':hydrate(sys.argv[1],sys.argv[2])
