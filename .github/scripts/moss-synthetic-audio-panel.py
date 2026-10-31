#!/usr/bin/env python3
"""Blinded synthetic audio experiment. No production inputs or approval."""
import json, os, random, subprocess, tempfile
from pathlib import Path
import torch
from src.audio_io import load_audio
from src.modeling_moss_audio import MossAudioModel
from src.processing_moss_audio import MossAudioProcessor

torch.set_num_threads(4)
model_path=os.environ['MOSS_MODEL']
model=MossAudioModel.from_pretrained(model_path,trust_remote_code=True,dtype='auto',device_map='cpu').eval()
processor=MossAudioProcessor.from_pretrained(model_path,trust_remote_code=True,enable_time_marker=True)
results = {'schema':'moss-synthetic-audio-v1', 'release_approved':False, 'results':[], 'labels':{}}
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
                raw=load_audio(str(audio),sample_rate=processor.config.mel_sr)
                inputs=processor(text='Listen to the entire recording. Describe any unintended interruptions, unwanted noise, or rhythmic changes in loudness. Is it clean or defective?',audios=[raw],return_tensors='pt').to(model.device)
                if inputs.get('audio_data') is not None: inputs['audio_data']=inputs['audio_data'].to(model.dtype)
                inputs['audio_input_mask']=inputs['input_ids']==processor.audio_token_id
                generated=model.generate(**inputs,max_new_tokens=180,do_sample=False,num_beams=1,use_cache=True)
                answer=processor.decode(generated[0,inputs['input_ids'].shape[1]:],skip_special_tokens=True)
            results['results'].append({'blind_id':ident,'content':str(answer)[:8000]})
        except Exception as e:
            results['results'].append({'blind_id':ident,'error':type(e).__name__})
            break
        Path(os.environ['RUNNER_TEMP'],'moss-results.json').write_text(json.dumps(results,indent=2))
Path(os.environ['RUNNER_TEMP'],'moss-results.json').write_text(json.dumps(results,indent=2))
