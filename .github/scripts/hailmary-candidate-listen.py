import base64, json, os, subprocess, urllib.error, urllib.request
import imageio_ffmpeg

kind=os.environ['KIND']; para=os.environ['PARA']
criteria={
 'rows':'The hook has one occurrence of a word sounding like rows. Classify its vowel as roh (rhymes with goes), raw (rhymes with paws), or uncertain.',
 'reveal':'At the end the company name should sound like three letter names AY JEE EM in quick succession. Classify the spoken name correct, incorrect, or uncertain.',
 'website':'The website should be spoken as four letter names AY JEE EM EM, then dot CO dot UK. Classify it correct, incorrect, or uncertain.',
 'ai':'The phrase AI consultancy should sound AY EYE consultancy, not EYE EYE consultancy. Classify it correct, incorrect, or uncertain.'}
parts=[{'text':'Listen independently to all five numbered British-English narration recordings. '+criteria[kind]+' Return JSON only: {"takes": [{"id":1, "verdict":"correct"|"incorrect"|"uncertain", "natural":true|false|null}]}. Use uncertain if a sound cannot be heard; do not infer pronunciation from meaning. For rows add "first":"roh"|"raw"|"uncertain" for each take. Do not quote the script.'}]
order=[int(x) for x in os.environ.get('ORDER','12345')]
assert sorted(order)==[1,2,3,4,5]
single=os.environ.get('SINGLE','')
if single:
 order=[int(single)]
 parts=[{'text':'Listen carefully to this single British-English recording. '+criteria[kind]+' Return JSON only: {"takes": [{"id":'+single+', "verdict":"correct" or "incorrect" or "uncertain", "natural":true or false or null, "first":"roh" or "raw" or "uncertain"}]}. Use uncertain when you cannot hear. Do not quote the script.'}]
for i in order:
 src=f'voice/{para}.t{i}.wav'; dst=f'/tmp/t{i}.mp3'
 subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-y','-i',src,'-ac','1','-ar','24000','-b:a','64k',dst],check=True)
 parts += [{'text':f'Take {i}:'},{'inline_data':{'mime_type':'audio/mp3','data':base64.b64encode(open(dst,'rb').read()).decode()}}]
body={'generationConfig':{'temperature':0.1,'maxOutputTokens':1800,'responseMimeType':'application/json'},'contents':[{'parts':parts}]}
req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent',json.dumps(body).encode(),{'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']})
try:
 with urllib.request.urlopen(req,timeout=240) as response: result=json.load(response)
except urllib.error.HTTPError as error: raise SystemExit('Audio listener HTTP status '+str(error.code))
txt=''.join(p.get('text','') for p in result['candidates'][0]['content']['parts']); answer=json.loads(txt); safe=[]
for v in (answer if isinstance(answer,list) else answer.get('takes',[])):
 if not isinstance(v,dict) or v.get('id') not in range(1,6): continue
 z={'id':v['id'],'verdict':v.get('verdict') if v.get('verdict') in ('correct','incorrect','uncertain') else 'uncertain','natural':v.get('natural') if isinstance(v.get('natural'),bool) else None}
 if kind=='rows': z.update({k:v.get(k) if v.get(k) in ('roh','raw','uncertain') else 'uncertain' for k in ('first','second')})
 safe.append(z)
out={'film':os.environ['FILM'],'kind':kind,'paragraph':para,'model':'gemini-3.5-flash-lite','takes':safe}
os.makedirs('out',exist_ok=True)
with open('out/listen.json','w') as f: json.dump(out,f,indent=2)
print(json.dumps(out))
