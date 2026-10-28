import base64,json,os,subprocess,urllib.error,urllib.request
import imageio_ffmpeg
ff=imageio_ffmpeg.get_ffmpeg_exe();source=os.environ['SOURCE'];start=float(os.environ['START']);end=float(os.environ['END'])
subprocess.run([ff,'-nostdin','-v','error','-y','-ss',str(start),'-to',str(end),'-i',source,'-vn','-ac','1','-ar','24000','-b:a','64k','/tmp/ai.mp3'],check=True)
prompt='Listen carefully to this brief British English speech clip. After the initial article, classify the two syllable sounds: "ay eye" (first rhymes with day, second with my), "eye eye" (both rhyme with my), "other", or "uncertain". Base the answer on the audio, not on what would make sense. Return JSON only {"syllables":"ay eye" or "eye eye" or "other" or "uncertain", "clear":true or false or null}.'
body={'generationConfig':{'temperature':0.1,'maxOutputTokens':300,'responseMimeType':'application/json'},'contents':[{'parts':[{'text':prompt},{'inline_data':{'mime_type':'audio/mp3','data':base64.b64encode(open('/tmp/ai.mp3','rb').read()).decode()}}]}]}
req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent',json.dumps(body).encode(),{'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']})
try:
 with urllib.request.urlopen(req,timeout=240) as r:result=json.load(r)
except urllib.error.HTTPError as e:raise SystemExit('Audio listener HTTP status '+str(e.code))
raw=''.join(p.get('text','') for p in result['candidates'][0]['content']['parts']);v=json.loads(raw);syllables=v.get('syllables')
out={'film':os.environ['FILM'],'syllables':syllables if syllables in ('ay eye','eye eye','other','uncertain') else 'uncertain','clear':v.get('clear') if isinstance(v.get('clear'),bool) else None}
os.makedirs('out',exist_ok=True);json.dump(out,open('out/ai.json','w'),indent=2);print(json.dumps(out))
