#!/usr/bin/env python3
"""Exact hosted-only S149 signal/timing diagnosis; exports numbers and text only."""
import hashlib,io,json,math,os,struct,subprocess,tarfile,zipfile
from pathlib import Path
raw=subprocess.run(['gh','api','repos/agmmltd-arch/agmm-render-public/actions/artifacts/13038017730/zip'],capture_output=True,check=True).stdout
assert len(raw)<20000000 and hashlib.sha256(raw).hexdigest()=='e3ef240f7587bd252035aab1fbf08aa82d8a5e31e63f7cb58a76ef260f2def91'
with zipfile.ZipFile(io.BytesIO(raw)) as z:
 members=[x for x in z.infolist() if not x.is_dir()];assert len(members)==1 and members[0].filename=='voice-generated.enc' and members[0].file_size<20000000
 enc=z.read(members[0])
assert os.environ.get('VOICEFREE_PASS')
plain=subprocess.run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-pass','env:VOICEFREE_PASS'],input=enc,capture_output=True,check=True).stdout
assert len(plain)<100000000
with tarfile.open(fileobj=io.BytesIO(plain),mode='r:') as t:
 files={}
 for member in t.getmembers():
  name=member.name.removeprefix('./')
  if name in ('generated/S149.wav','generated/S149.words.json','RECEIPT.json'):
   assert member.isfile() and name not in files and member.size<20000000
   files[name]=t.extractfile(member).read()
 assert set(files)=={'generated/S149.wav','generated/S149.words.json','RECEIPT.json'}
receipt=json.loads(files['RECEIPT.json']);assert receipt['id']=='S149' and str(receipt['run_id'])=='41188550083'
for name in ('S149.wav','S149.words.json'):
 rows=[x for x in receipt['generated'] if x['path']==name];assert len(rows)==1 and hashlib.sha256(files['generated/'+name]).hexdigest()==rows[0]['sha256']
words=json.loads(files['generated/S149.words.json'])['words'];near=[{'word':w['word'],'start':w['start'],'end':w['end']} for w in words if w['end']>=19 and w['start']<=24]
pcm=subprocess.run(['ffmpeg','-v','error','-i','pipe:0','-ss','19','-t','5','-f','s16le','-ar','16000','-ac','1','pipe:1'],input=files['generated/S149.wav'],capture_output=True,check=True).stdout
assert len(pcm)>10000 and len(pcm)%2==0
samples=struct.unpack('<%dh'%(len(pcm)//2),pcm);bins=[]
for k in range(0,len(samples),1600):
 chunk=samples[k:k+1600];rms=math.sqrt(sum((x/32768)**2 for x in chunk)/len(chunk));bins.append({'start_s':round(19+k/16000,2),'rms_db':round(20*math.log10(max(rms,1e-12)),1)})
out={'schema':'agmm-word-timing-diagnosis-v1','id':'S149','producer_run_id':41188550083,'words':near,'rms_100ms':bins,'interpretation':'signal only; no transcription, correction or approval','audio_exported':False,'release_approval':False}
Path(os.environ['RUNNER_TEMP'],'s149-timing.json').write_text(json.dumps(out,indent=2)+'\n')
