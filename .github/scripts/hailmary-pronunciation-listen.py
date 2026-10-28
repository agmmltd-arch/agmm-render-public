import base64, json, os, subprocess, urllib.error, urllib.request

film = os.environ['FILM']
subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i','input/gate-input/mix.wav','-ac','1','-ar','24000','-b:a','64k','/tmp/listen.mp3'], check=True)
prompt = '''Listen to the entire attached British English narration with its music and effects. Report audible speech errors only, without assuming they exist. The reveal should say the three letter sounds AY JEE EM quickly. The phrase AI consultancy should sound AY EYE consultancy, not EYE EYE. The website should spell AY JEE EM EM dot CO dot UK. Return JSON with keys reveal, ai, website, other_errors. For each of reveal, ai, website return {"verdict": "correct" or "incorrect" or "uncertain" or "not_found", "seconds": number or null}. For other_errors return an array of {"seconds": number, "category": "mispronunciation" or "missing_word" or "unclear"}, without quoting script. Listen rather than infer from spelling.'''
if film == 'H08':
    prompt += ''' In the hook, the word rows occurs twice. Listen to their vowel sounds independently. Return an additional rows key {"first": "roh" or "raw" or "uncertain", "second": "roh" or "raw" or "uncertain"}. roh rhymes with goes; raw rhymes with paws.'''
payload={'generationConfig':{'temperature':0.1,'maxOutputTokens':1800,'responseMimeType':'application/json'},'contents':[{'parts':[{'text':prompt},{'inline_data':{'mime_type':'audio/mp3','data':base64.b64encode(open('/tmp/listen.mp3','rb').read()).decode()}}]}]}
req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent',json.dumps(payload).encode(),{'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']})
try:
    with urllib.request.urlopen(req,timeout=240) as response:
        result=json.load(response)
except urllib.error.HTTPError as error:
    raise SystemExit('Audio listener HTTP status '+str(error.code))
text=''.join(p.get('text','') for p in result['candidates'][0]['content']['parts'])
answer=json.loads(text)
safe={'film':film,'model':'gemini-3.5-flash-lite'}
for k in ('reveal','ai','website'):
    v=answer.get(k) or {}; verdict=v.get('verdict')
    safe[k]={'verdict':verdict if verdict in ('correct','incorrect','uncertain','not_found') else 'uncertain','seconds':v.get('seconds') if isinstance(v.get('seconds'),(int,float)) else None}
safe['other_errors']=[{'seconds':v.get('seconds'),'category':v.get('category')} for v in answer.get('other_errors',[]) if isinstance(v,dict) and isinstance(v.get('seconds'),(int,float)) and v.get('category') in ('mispronunciation','missing_word','unclear')]
if film=='H08':
    v=answer.get('rows') or {}; safe['rows']={k:v.get(k) if v.get(k) in ('roh','raw','uncertain') else 'uncertain' for k in ('first','second')}
os.makedirs('out',exist_ok=True)
with open('out/listen.json','w') as f: json.dump(safe,f,indent=2)
print(json.dumps(safe))
