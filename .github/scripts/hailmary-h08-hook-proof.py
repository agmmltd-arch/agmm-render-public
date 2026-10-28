import json, math, os, subprocess, wave
import numpy as np

os.chdir('film')
spec=json.load(open('mix.json')); original=[c for c in spec['clips'] if c.get('voice')]
assert len(original)>2 and abs(original[0]['at']-.08)<.001 and abs(original[1]['at']-3.311)<.001 and abs(original[2]['at']-4.695)<.001
start=original[0]['at']; end=original[1]['at']+original[1]['out']-original[1]['in']; target=end-start
with wave.open('../voice/P1.t1.wav','rb') as f: duration=f.getnframes()/f.getframerate()
tempo=duration/target
assert 0.8 <= tempo <= 1.1
subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i','../voice/P1.t1.wav','-af',f'atempo={tempo}','-ar','48000','-ac','2','-c:a','pcm_s16le','hook-proof.wav'],check=True)
old=dict(spec); old['clips']=original[:2]
json.dump(old,open('hook-old.json','w'))
subprocess.run(['python3','mix.py','hook-old.json','../old-voice.wav'],check=True)
subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i','../old-voice.wav','-ar','48000','-ac','2','-c:a','pcm_s16le','../old-voice-s16.wav'],check=True)
def pcm(path):
 with wave.open(path,'rb') as f:
  assert f.getsampwidth()==2 and f.getnchannels()==2 and f.getframerate()==48000
  return np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(float)/32768
old_pcm=pcm('../old-voice-s16.wav')[int(start*48000)*2:int(end*48000)*2]
new_pcm=pcm('hook-proof.wav')
def rms(a): return float(np.sqrt(np.mean(a*a)))
gain=20*math.log10(rms(old_pcm)/rms(new_pcm))
assert -12<gain<12
replacement={'src':'hook-proof.wav','in':0,'out':target,'at':start,'gain_db':gain,'pan':0,'fade_in':.008,'fade_out':.012,'voice':True}
spec['clips']=[c for c in spec['clips'] if c is not original[0] and c is not original[1]]+[replacement]
json.dump(spec,open('mix-hook-proof.json','w'),indent=1)
subprocess.run(['python3','mix.py','mix-hook-proof.json','../mix-candidate.wav'],check=True)
report={'start':start,'end':end,'source_duration':duration,'tempo':tempo,'gain_db':gain,'original_voice_clips_replaced':2,'music_and_effect_clips_retained':True,'voice_spans_unchanged':True}
json.dump(report,open('../proof-details.json','w'),indent=2)
print(json.dumps(report))
