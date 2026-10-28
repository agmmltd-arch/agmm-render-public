import json,os,subprocess
import numpy as np
import imageio_ffmpeg
ff=imageio_ffmpeg.get_ffmpeg_exe()
def audio(path):
 return np.frombuffer(subprocess.run([ff,'-nostdin','-v','error','-i',path,'-vn','-ac','1','-ar','16000','-f','f32le','-'],capture_output=True,check=True).stdout,dtype='<f4').astype(float)
a=audio('original/SHARE.mp4');b=audio('proof/VOICE-PROOF.mp4');n=min(len(a),len(b));a=a[:n];b=b[:n]
mask=np.ones(n,dtype=bool);detail=json.load(open('proof/proof-details.json'))
for item in detail.get('items',[]):
 if item.get('status')=='proof inserted':
  start=max(0,int((item['start']-.3)*16000));end=min(n,int((max(item['end'],item.get('original_end',item['end']))+.3)*16000));mask[start:end]=False
if mask.sum()<16000:raise SystemExit('Too little unaffected audio for comparison')
# Small encoder delays are possible. Find the best offset using 1/10-rate samples.
aa=a[::10];bb=b[::10];mm=mask[::10];scores=[]
for lag in range(-80,81):
 if lag>=0:x=aa[lag:];y=bb[:len(x)];m=mm[lag:]
 else:y=bb[-lag:];x=aa[:len(y)];m=mm[:len(y)]
 scores.append(float(np.dot(x[m],y[m])))
lag=(int(np.argmax(scores))-80)*10
if lag>=0:x=a[lag:];y=b[:len(x)];m=mask[lag:]
else:y=b[-lag:];x=a[:len(y)];m=mask[:len(y)]
x=x[m];y=y[m];rms=lambda z:float(np.sqrt(np.mean(z*z)))
gain=float(np.dot(x,y)/np.dot(y,y));out={'film':os.environ['FILM'],'unaffected_seconds':len(x)/16000,'lag_seconds':lag/16000,'correlation':float(np.corrcoef(x,y)[0,1]),'best_gain':gain,'difference_relative_db':float(20*np.log10(max(rms(x-gain*y),1e-12)/max(rms(x),1e-12)))}
os.makedirs('out',exist_ok=True);json.dump(out,open('out/preservation.json','w'),indent=2);print(json.dumps(out))
