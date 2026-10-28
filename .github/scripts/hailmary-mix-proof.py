import json,os,wave
import numpy as np
def read(path):
 with wave.open(path,'rb') as f:
  assert f.getsampwidth()==2
  return f.getframerate(),f.getnchannels(),np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(float)/32768
sr,ch,a=read('input/gate-input/mix.wav'); s,c,b=read('rebuilt.wav'); assert (s,c)==(sr,ch)
n=min(len(a),len(b)); a=a[:n]; b=b[:n]
def rms(x): return float(np.sqrt(np.mean(x*x)))
out={'film':os.environ['FILM'],'seconds':n/(sr*ch),'correlation':float(np.corrcoef(a,b)[0,1]),'difference_relative_db':float(20*np.log10(max(rms(a-b),1e-12)/max(rms(a),1e-12))),'max_difference':float(np.max(np.abs(a-b)))}
os.makedirs('out',exist_ok=True)
with open('out/proof.json','w') as f: json.dump(out,f,indent=2)
print(json.dumps(out))
