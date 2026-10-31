#!/usr/bin/env python3
"""Synthetic audio-only blinded research; not video or release approval."""
import json,random,subprocess,tempfile
from pathlib import Path

def call(args,timeout=120):
 return subprocess.run(args,check=True,capture_output=True,text=True,timeout=timeout)
with tempfile.TemporaryDirectory() as td:
 p=Path(td);source=p/'source.wav'
 phrase='A business introduced an automated service. Customers were promised faster responses, but the process needed careful testing. The team checked every result before making a decision.'
 call(['espeak-ng','-s','145','-w',str(source),phrase])
 filters={'clean':'anull','noise':'anoisesrc=color=white:amplitude=0.10[noise];[0:a][noise]amix=inputs=2:duration=first',
          'dropout':"volume='if(between(t,2,3.2),0,1)':eval=frame",'pumping':"volume='if(lt(mod(t,0.7),0.35),0.12,1)':eval=frame"}
 labels=list(filters);random.SystemRandom().shuffle(labels);results=[]
 for index,label in enumerate(labels):
  name=chr(65+index);audio=p/(name+'.wav');flt=filters[label]
  args=['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source)]
  args+=['-filter_complex',flt] if label=='noise' else ['-af',flt]
  call(args+['-ar','16000','-ac','1',str(audio)])
  prompt='<__media__>\nListen to the entire audio. Describe any unintended interruptions, unwanted noise, or rhythmic changes in loudness. Explain whether the sound is clean or defective.'
  try:
   proc=subprocess.run(['build/bin/llama','cli','-m','model.gguf','-mm','mmproj.gguf','--audio',str(audio),'-sys','Analyze the recording and respond in text.','-p',prompt,'--temp','0','-n','180','--no-display-prompt'],capture_output=True,text=True,timeout=360)
   results.append({'blind_id':name,'code':proc.returncode,'stdout':proc.stdout[-12000:],'stderr_tail':proc.stderr[-1500:]})
  except subprocess.TimeoutExpired:results.append({'blind_id':name,'status':'timeout'})
 Path('research-results.json').write_text(json.dumps({'schema':'synthetic-audio-research-v1','results':results,'labels':dict(zip('ABCD',labels)),'release_approval':False,'continuous_visual_review':False},indent=2))
