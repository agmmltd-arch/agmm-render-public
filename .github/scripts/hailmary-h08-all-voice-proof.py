import json,math,os,subprocess,wave
import numpy as np
os.chdir('film')
spec=json.load(open('mix-hook-proof.json'))
items=[('P6','../v-reveal/P6.t8.wav',0.07,3.2),('P7','../v-ai/P6.t2.wav',0.24,10.53),('P8','../v-website/P8.t4.wav',0.11,3.66)]
def pcm(path):
 with wave.open(path,'rb') as f:
  assert f.getsampwidth()==2 and f.getnchannels()==2 and f.getframerate()==48000
  return np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(float)/32768
def rms(a): return float(np.sqrt(np.mean(a*a)))
report=[]
for para,path,first,last in items:
 old=[c for c in spec['clips'] if c.get('voice') and os.path.basename(c['src'])==para+'.wav']
 assert old,para
 start=min(c['at'] for c in old); end=max(c['at']+c['out']-c['in'] for c in old); target=end-start
 cut0=max(0,first-.04); cut1=last+.04; tempo=(cut1-cut0)/target
 assert .82<=tempo<=1.18,(para,tempo)
 dst='proof-'+para+'.wav'
 subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',path,'-af',f'atrim=start={cut0}:end={cut1},asetpts=PTS-STARTPTS,atempo={tempo}','-ar','48000','-ac','2','-c:a','pcm_s16le',dst],check=True)
 original=dict(spec);original['clips']=old; json.dump(original,open('old-'+para+'.json','w'))
 subprocess.run(['python3','mix.py','old-'+para+'.json','../old-'+para+'.wav'],check=True)
 subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i','../old-'+para+'.wav','-ar','48000','-ac','2','-c:a','pcm_s16le','../old-'+para+'-s16.wav'],check=True)
 a=pcm('../old-'+para+'-s16.wav')[int(start*48000)*2:int(end*48000)*2]; b=pcm(dst)
 gain=20*math.log10(rms(a)/rms(b)); assert -12<gain<12
 spec['clips']=[c for c in spec['clips'] if c not in old]
 spec['clips'].append({'src':dst,'in':0,'out':target,'at':start,'gain_db':gain,'pan':0,'fade_in':.008,'fade_out':.012,'voice':True})
 report.append({'para':para,'start':start,'end':end,'tempo':tempo,'gain_db':gain,'clips_replaced':len(old)})
json.dump(spec,open('mix-all-proof.json','w'),indent=1)
subprocess.run(['python3','mix.py','mix-all-proof.json','../mix-all-candidate.wav'],check=True)
json.dump(report,open('../all-proof-details.json','w'),indent=2)
print(json.dumps(report))
