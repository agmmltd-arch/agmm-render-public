#!/usr/bin/env python3
"""Blinded synthetic audio experiment. No production inputs or approval."""
import json, os, random, subprocess, tempfile
from pathlib import Path
import torch
from transformers import AutoModelForCausalLM, AutoProcessor, AutoTokenizer

torch.set_num_threads(4)
model_path=os.environ['MIDASHENG_MODEL']
model=AutoModelForCausalLM.from_pretrained(model_path,trust_remote_code=True).eval().to('cpu')
processor=AutoProcessor.from_pretrained(model_path,trust_remote_code=True)
tokenizer=AutoTokenizer.from_pretrained(model_path)
results = {'schema':'midasheng-synthetic-audio-v1', 'release_approved':False, 'results':[], 'labels':{}}
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
        msg=[{'role':'user','content':[{'type':'text','text':'Listen to the entire recording. Describe any unintended interruptions, unwanted noise, or rhythmic changes in loudness. Is it clean or defective?'}, {'type':'audio','path':str(audio)}]}]
        try:
            with torch.inference_mode():
                inputs=processor.apply_chat_template(msg,tokenize=True,add_generation_prompt=True,add_special_tokens=True,return_dict=True).to(device=model.device,dtype=model.dtype)
                answer=tokenizer.batch_decode(model.generate(**inputs,max_new_tokens=180,do_sample=False),skip_special_tokens=True)
            results['results'].append({'blind_id':ident,'content':str(answer)[:8000]})
        except Exception as e:
            results['results'].append({'blind_id':ident,'error':type(e).__name__})
            break
        Path(os.environ['RUNNER_TEMP'],'midasheng-results.json').write_text(json.dumps(results,indent=2))
Path(os.environ['RUNNER_TEMP'],'midasheng-results.json').write_text(json.dumps(results,indent=2))
