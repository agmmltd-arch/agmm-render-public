import base64,json,os,subprocess,urllib.error,urllib.request
import imageio_ffmpeg
source=os.environ['SOURCE']; start=float(os.environ.get('START','0'));end=float(os.environ.get('END','3'));model=os.environ.get('MODEL','gemini-3.5-flash-lite')
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-y','-ss',str(start),'-to',str(end),'-i',source,'-vn','-ac','1','-ar','24000','-b:a','64k','/tmp/vowel.mp3'],check=True)
prompt='Listen to the first prominent vowel sound in this short audio clip. Which word has the same vowel: DAY or MY? Only classify the sound you actually hear, with no context or guess. Return JSON only {"rhyme":"day" or "my" or "uncertain"}.'
body={'generationConfig':{'temperature':0.1,'maxOutputTokens':200,'responseMimeType':'application/json'},'contents':[{'parts':[{'text':prompt},{'inline_data':{'mime_type':'audio/mp3','data':base64.b64encode(open('/tmp/vowel.mp3','rb').read()).decode()}}]}]}
req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',json.dumps(body).encode(),{'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']})
try:
 with urllib.request.urlopen(req,timeout=240) as r:result=json.load(r)
except urllib.error.HTTPError as e:raise SystemExit('Audio listener HTTP status '+str(e.code))
raw=''.join(p.get('text','') for p in result['candidates'][0]['content']['parts']);v=json.loads(raw);r=v.get('rhyme');out={'model':model,'rhyme':r if r in ('day','my','uncertain') else 'uncertain'}
print(json.dumps(out))
