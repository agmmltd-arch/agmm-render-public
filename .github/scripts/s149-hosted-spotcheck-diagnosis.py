#!/usr/bin/env python3
"""Read only exact S149 generated-checkpoint text on the hosted runner."""
import hashlib,io,json,os,subprocess,tarfile,zipfile
from pathlib import Path
raw=subprocess.run(['gh','api','repos/agmmltd-arch/agmm-render-public/actions/artifacts/13038017730/zip'],capture_output=True,check=True).stdout
assert len(raw)<20000000 and hashlib.sha256(raw).hexdigest()=='e3ef240f7587bd252035aab1fbf08aa82d8a5e31e63f7cb58a76ef260f2def91'
with zipfile.ZipFile(io.BytesIO(raw)) as z:
 members=[x for x in z.infolist() if not x.is_dir()]
 assert len(members)==1 and members[0].filename=='voice-generated.enc' and members[0].file_size<20000000
 enc=z.read(members[0])
assert os.environ.get('VOICEFREE_PASS')
plain=subprocess.run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-pass','env:VOICEFREE_PASS'],input=enc,capture_output=True,check=True).stdout
assert len(plain)<100000000
with tarfile.open(fileobj=io.BytesIO(plain),mode='r:') as t:
 items=[x for x in t.getmembers() if x.isfile() and x.name.removeprefix('./')=='generated/S149.spotcheck.txt']
 assert len(items)==1 and items[0].size<100000
 text=t.extractfile(items[0]).read().decode('utf-8')
lines=text.splitlines(); failed=[x for x in lines if 'FAIL' in x];summary=[x for x in lines if 'words checked' in x]
assert len(summary)==1
out={'schema':'agmm-spotcheck-text-diagnosis-v1','id':'S149','producer_run_id':41188550083,'failure_lines':failed,'summary':summary[0],'release_approval':False,'audio_exported':False}
Path(os.environ['RUNNER_TEMP'],'s149-diagnosis.json').write_text(json.dumps(out,indent=2)+'\n')
