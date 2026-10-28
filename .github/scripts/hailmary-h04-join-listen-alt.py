import base64,json,os,subprocess,urllib.request,urllib.error
import imageio_ffmpeg
ff=imageio_ffmpeg.get_ffmpeg_exe()
subprocess.run([ff,'-nostdin','-y','-v','error','-ss','31.2','-to','34.5','-i','proof/VOICE-PROOF.mp4','-vn','-ac','1','-ar','24000','/tmp/full.wav'],check=True)
subprocess.run([ff,'-nostdin','-y','-v','error','-i','/tmp/full.wav','-filter_complex','[0:a]atrim=0:1.15,asetpts=PTS-STARTPTS[a];[0:a]atrim=start=1.55,asetpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=0:a=1[out]','-map','[out]','/tmp/glitch.wav'],check=True)
for n in ('full','glitch'):
 subprocess.run([ff,'-nostdin','-y','-v','error','-i','/tmp/'+n+'.wav','-b:a','64k','/tmp/'+n+'.mp3'],check=True)
 prompt='Listen to this short speech excerpt. Is any spoken word audibly cut off, mechanically chopped, or does the voice abruptly jump? Choose clear, defect, or uncertain. Focus only on audible sounds; do not assume an edit. Return JSON only {"integrity":"clear" or "defect" or "uncertain"}.'
 body={'generationConfig':{'temperature':0.1,'maxOutputTokens':1200,'responseMimeType':'application/json'},'contents':[{'parts':[{'text':prompt},{'inline_data':{'mime_type':'audio/mp3','data':base64.b64encode(open('/tmp/'+n+'.mp3','rb').read()).decode()}}]}]}
 req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/'+os.environ.get('MODEL','gemini-3-flash-preview')+':generateContent',json.dumps(body).encode(),{'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']})
 try:
  with urllib.request.urlopen(req,timeout=180) as r: result=json.load(r)
  v=json.loads(''.join(p.get('text','') for p in result['candidates'][0]['content']['parts'])).get('integrity');print('INTEGRITY',n,v if v in ('clear','defect','uncertain') else 'uncertain',flush=True)
 except urllib.error.HTTPError as e:print('HTTP',e.code,flush=True)
