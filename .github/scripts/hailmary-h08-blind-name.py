import base64,json,os,re,subprocess,urllib.error,urllib.request
import imageio_ffmpeg
take=os.environ['TAKE']; start=float(os.environ['START']); end=float(os.environ['END'])
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-y','-ss',str(start),'-to',str(end),'-i','voice/'+os.environ['PARA']+'.t'+take+'.wav','-ac','1','-ar','24000','-b:a','64k','/tmp/clip.mp3'],check=True)
prompt='Transcribe the spoken sounds in this isolated audio clip as accurately as possible. If the speaker says letter names, write the letters in order. Do not guess or complete missing sounds. If indistinct, say unclear. Return JSON {"heard":"..."}.'
body={'generationConfig':{'temperature':0.1,'maxOutputTokens':300,'responseMimeType':'application/json'},'contents':[{'parts':[{'text':prompt},{'inline_data':{'mime_type':'audio/mp3','data':base64.b64encode(open('/tmp/clip.mp3','rb').read()).decode()}}]}]}
req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent',json.dumps(body).encode(),{'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']})
try:
 with urllib.request.urlopen(req,timeout=240) as r: result=json.load(r)
except urllib.error.HTTPError as e: raise SystemExit('Audio listener HTTP status '+str(e.code))
txt=''.join(p.get('text','') for p in result['candidates'][0]['content']['parts']); answer=json.loads(txt); heard=str(answer.get('heard',''))[:500]
heard=re.sub(r'[^A-Za-z .,!\-?]',' ',heard).strip()
compact=re.sub(r'[^a-z]','',heard.lower())
names=[name for name in ('agmm','agm','amg','aem','igm','gm','ag') if name in compact]
terms=('kettle','cattle','receipts','receipt','one','and','dot','co','uk','right','next','to','the','so','where','finds','builds','money')
counts={term:len(re.findall(r'\b'+term+r'\b',heard.lower())) for term in terms}
out={'voice_label':os.environ['VOICE_LABEL'],'take':int(take),'name_markers':names,'word_markers':[term for term in terms if counts[term]],'word_counts':counts,'range_seconds':[start,end]}
os.makedirs('out',exist_ok=True); json.dump(out,open('out/blind.json','w'),indent=2); print(json.dumps(out))
