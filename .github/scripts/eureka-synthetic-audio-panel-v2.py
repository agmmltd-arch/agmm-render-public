#!/usr/bin/env python3
"""Blinded synthetic audio experiment. No production inputs or approval."""
import json, os, random, subprocess, tempfile
from pathlib import Path
import torch
from eureka_infer.api import EurekaAudio

torch.set_num_threads(4)
model = EurekaAudio(model_path=os.environ['EUREKA_MODEL'], device='cpu')
results = {'schema':'eureka-synthetic-audio-v1', 'release_approved':False, 'results':[], 'labels':{}}
labels = ['clean','noise','dropout','pumping']
random.SystemRandom().shuffle(labels)
filters={'clean':'anull','noise':'anoisesrc=color=white:amplitude=0.10[noise];[0:a][noise]amix=inputs=2:duration=first',
         'dropout':"volume='if(between(t,2,3.2),0,1)':eval=frame", 'pumping':"volume='if(lt(mod(t,0.7),0.35),0.12,1)':eval=frame"}
with tempfile.TemporaryDirectory() as td:
    p=Path(td);source=p/'source.wav'
    subprocess.run(['espeak-ng','-s','155','-w',str(source),'The manager checked the report before the meeting. Every figure had a source, and the team corrected the mistake before sending the result to their customers.'],check=True,capture_output=True)
    for i,label in enumerate(labels):
        ident=chr(65+i); audio=p/(ident+'.wav');results['labels'][ident]=label
        args=['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source)]
        args+=['-filter_complex' if label=='noise' else '-af',filters[label],'-ar','16000','-ac','1',str(audio)]
        subprocess.run(args,check=True,capture_output=True)
        msg=[{'role':'user','content':[{'type':'audio_url','audio_url':{'url':str(audio)}},
             {'type':'text','text':'Listen to the entire recording. Describe any unintended interruptions, unwanted noise, or rhythmic changes in loudness. Is it clean or defective?'}]}]
        try:
            with torch.inference_mode():
                answer=model.generate(msg,max_new_tokens=180,temperature=0.0,top_p=0.0,top_k=0,do_sample=False)
            results['results'].append({'blind_id':ident,'content':str(answer)[:8000]})
        except Exception as e:
            results['results'].append({'blind_id':ident,'error':type(e).__name__})
            break
        Path(os.environ['RUNNER_TEMP'],'eureka-results.json').write_text(json.dumps(results,indent=2))
Path(os.environ['RUNNER_TEMP'],'eureka-results.json').write_text(json.dumps(results,indent=2))
