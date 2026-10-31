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
words=json.loads(files['generated/S149.words.json'])['words']
import random
random.seed(42); indices=sorted(random.sample(range(len(words)),min(15,len(words))))
rows=[]
for i in indices:
 w=words[i]; start=w['start']; dur=w['end']-start
 def measure(fixed):
  if fixed:
   args=['-af',f'atrim=start={max(0,start):.3f}:duration={dur:.3f},asetpts=PTS-STARTPTS,astats=metadata=1:reset=0']
  else:
   args=['-ss',f'{max(0,start):.3f}','-t',f'{dur:.3f}','-af','astats=metadata=1:reset=1']
  proc=subprocess.run(['ffmpeg','-nostats','-i','pipe:0']+args+['-f','null','-'],input=files['generated/S149.wav'],capture_output=True,check=True)
  lines=[x.strip().split(':')[-1].strip() for x in proc.stderr.decode(errors='replace').splitlines() if 'RMS level dB' in x]
  assert lines
  x=float(lines[0]);return round(x,2) if math.isfinite(x) else None
 old=measure(False);new=measure(True)
 rows.append({'word':w['word'],'start':start,'end':w['end'],'legacy_rms_db':old,'fixed_window_rms_db':new,'fixed_above_floor':new is not None and new > -50})
out={'schema':'agmm-s149-exact-window-recheck-v1','id':'S149','producer_run_id':41188550083,'sampled_words':rows,'audio_exported':False,'source_approval':False,'release_approval':False,'interpretation':'signal measurement only; not intelligibility or audiovisual review'}
Path(os.environ['RUNNER_TEMP'],'s149-window.json').write_text(json.dumps(out,indent=2)+'\n')
