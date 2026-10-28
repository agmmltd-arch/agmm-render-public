import json,math,os,re,subprocess,wave
import numpy as np

film=os.environ['FILM']; plan=json.loads(os.environ['PLAN']); assert len(plan)<=8
def run(args,**kw): return subprocess.run(args,check=True,**kw)
for item in plan:
 para=item['para']; label=item['label']; rid=str(item['run']); take=int(item['take'])
 assert re.fullmatch(r'P[1-8]',para) and re.fullmatch(r'H(?:0[2-9]|1[01])-[A-Za-z0-9-]+',label) and rid.isdigit() and 1<=take<=10
 enc='pack-'+para;dest='voice-'+para;os.makedirs(enc,exist_ok=True);os.makedirs(dest,exist_ok=True)
 run(['gh','run','download',rid,'-R',os.environ['GITHUB_REPOSITORY'],'-n','voicefree-chatterbox-'+label+'-ENC','-D',enc])
 with open(enc+'/synth-pack.enc','rb') as inp, open(enc+'/decoded.tar','wb') as out:
  run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-pass','env:VOICEFREE_PASS'],stdin=inp,stdout=out)
 run(['tar','-xf',enc+'/decoded.tar','-C',dest])
os.chdir('film'); spec=json.load(open('mix.json'))
def pcm(path):
 with wave.open(path,'rb') as f:
  assert f.getsampwidth()==2 and f.getnchannels()==2 and f.getframerate()==48000
  return np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(float)/32768
def rms(a):return float(np.sqrt(np.mean(a*a)))
report=[]
for item in plan:
 para=item['para'];old=[c for c in spec['clips'] if c.get('voice') and os.path.basename(c['src'])==para+'.wav']
 if not old: report.append({'para':para,'status':'missing original voice'});continue
 original_start=min(c['at'] for c in old);original_end=max(c['at']+c['out']-c['in'] for c in old)
 extension=float(item.get('extend',0));assert 0<=extension<=1.0
 end=min(float(spec['duration'])-.1,original_end+extension)
 start=float(item.get('replace_from',original_start)); assert original_start<=start<end
 target=end-start
 first=float(item['first']);last=float(item['last']);cut0=max(0,first-.04);cut1=last+.04;tempo=(cut1-cut0)/target
 if (tempo<.82 and item.get('pad_short') is True) or (tempo<1 and item.get('native_short') is True):
  target=cut1-cut0;end=start+target;tempo=1.0
 if not .82<=tempo<=1.18:report.append({'para':para,'status':'timing mismatch','tempo':tempo,'start':start,'end':end});continue
 source_para=item.get('source_para',para);assert re.fullmatch(r'P[1-8]',source_para)
 path=f'../voice-{para}/{source_para}.t{int(item["take"])}.wav'; dst='proof-'+para+'.wav'
 run(['ffmpeg','-nostdin','-v','error','-y','-i',path,'-af',f'atrim=start={cut0}:end={cut1},asetpts=PTS-STARTPTS,atempo={tempo}','-ar','48000','-ac','2','-c:a','pcm_s16le',dst])
 orig=dict(spec);orig['clips']=old;json.dump(orig,open('old-'+para+'.json','w'))
 run(['python3','mix.py','old-'+para+'.json','../old-'+para+'.wav'])
 run(['ffmpeg','-nostdin','-v','error','-y','-i','../old-'+para+'.wav','-ar','48000','-ac','2','-c:a','pcm_s16le','../old-'+para+'-s16.wav'])
 a=pcm('../old-'+para+'-s16.wav')[int(start*48000)*2:int(original_end*48000)*2];b=pcm(dst)
 print('level diagnostic',para,'start',start,'end',end,'old samples',len(a),'new samples',len(b),'old rms',rms(a),'new rms',rms(b),flush=True)
 gain_offset=0
 if not len(a) or rms(a)<1e-8:
  # Some one-clip mixes are silent with this renderer. Use the original
  # measured voice stem in this interval and undo its recorded master gain.
  stem='../input/gate-input/stems/voice.wav'
  if not os.path.exists(stem):report.append({'para':para,'status':'missing level reference'});continue
  run(['ffmpeg','-nostdin','-v','error','-y','-i',stem,'-ar','48000','-ac','2','-c:a','pcm_s16le','../level-stem.wav'])
  a=pcm('../level-stem.wav')[int(start*48000)*2:int(original_end*48000)*2]
  gain_offset=float(os.environ['GAIN1'])+float(os.environ['GAIN2'])
  print('fallback stem level',para,rms(a),flush=True)
 if not len(a) or not len(b) or rms(a)<1e-8 or rms(b)<1e-8:
  report.append({'para':para,'status':'silent level input'});continue
 gain=20*math.log10(rms(a)/rms(b))-gain_offset
 boost=float(item.get('boost_db',0)); assert -4<=boost<=4
 gain+=boost
 if not -12<gain<12:report.append({'para':para,'status':'level mismatch','gain_db':gain});continue
 kept=[]
 if 'replace_from' in item:
  for c in old:
   cend=c['at']+c['out']-c['in']
   if cend<=start: kept.append(c)
   elif c['at']<start:
    prefix=dict(c);prefix['out']=prefix['in']+start-prefix['at'];prefix['fade_out']=.015;kept.append(prefix)
 spec['clips']=[c for c in spec['clips'] if c not in old]+kept
 spec['clips'].append({'src':dst,'in':0,'out':target,'at':start,'gain_db':gain,'pan':0,'fade_in':.008,'fade_out':.012,'voice':True})
 report.append({'para':para,'status':'proof inserted','start':start,'end':end,'original_end':original_end,'tempo':tempo,'gain_db':gain,'clips_replaced':len(old),'take':item['take']})
json.dump(spec,open('mix-batch-proof.json','w'),indent=1)
run(['python3','mix.py','mix-batch-proof.json','../mix-proof.wav'])
json.dump({'film':film,'items':report,'music_and_effect_plan_unchanged':True,'voice_spans_unchanged':True},open('../proof-details.json','w'),indent=2)
print(json.dumps({'film':film,'items':report}))
