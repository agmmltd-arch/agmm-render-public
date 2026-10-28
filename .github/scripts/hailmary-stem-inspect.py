import json, os, wave
import numpy as np

def read(path):
 with wave.open(path,'rb') as f:
  assert f.getsampwidth()==2
  return f.getframerate(),f.getnchannels(),np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(np.float64)/32768
sr,ch,mix=read('input/gate-input/mix.wav')
tracks=[]
for name in ('voice','music','sfx'):
 s,c,x=read(f'input/gate-input/stems/{name}.wav'); assert (s,c)==(sr,ch); tracks.append(x)
n=min(map(len,[mix]+tracks)); target=mix[:n]; summed=sum(x[:n] for x in tracks); delta=target-summed
rm=lambda x:float(np.sqrt(np.mean(x*x)))
metadata=json.load(open('input/gate-input/mix.json'))
clips=[]
for c in metadata['clips']:
 if c.get('voice'):
  clips.append({k:c.get(k) for k in ('at','in','out','gain_db')})
out={'film':os.environ['FILM'],'sample_rate':sr,'channels':ch,'seconds':n/(sr*ch),'mix_rms':rm(target),'difference_rms':rm(delta),'difference_relative_db':20*np.log10(max(rm(delta),1e-12)/max(rm(target),1e-12)),'correlation':float(np.corrcoef(target,summed)[0,1]),'original_voice_clip_timing':clips}
os.makedirs('out',exist_ok=True)
with open('out/stem-inspection.json','w') as f: json.dump(out,f,indent=2)
print(json.dumps(out))
