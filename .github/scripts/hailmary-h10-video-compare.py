import base64,json,os,subprocess,urllib.error,urllib.request
import imageio_ffmpeg
ff=imageio_ffmpeg.get_ffmpeg_exe()
for name,path in [('A','old/SHARE.mp4'),('B','new/SHARE.mp4')]:
 subprocess.run([ff,'-nostdin','-v','error','-y','-i',path,'-t','8.1','-an','-vf','scale=360:640,fps=10','-c:v','libx264','-preset','veryfast','-crf','30','-movflags','+faststart','/tmp/'+name+'.mp4'],check=True)
prompt='Watch each complete silent clip independently. Focus on the main man and specifically whether his head rotates unnaturally or unexpectedly during the opening. Do not guess if the head is too small, hidden, or you cannot tell. Return JSON only {"A":{"person_visible":true or false,"head_rotation":"yes" or "no" or "uncertain"},"B":{"person_visible":true or false,"head_rotation":"yes" or "no" or "uncertain"}}.'
parts=[{'text':prompt}]
for name in ('A','B'):
 parts.extend([{'text':'Clip '+name},{'inline_data':{'mime_type':'video/mp4','data':base64.b64encode(open('/tmp/'+name+'.mp4','rb').read()).decode()}}])
body={'generationConfig':{'temperature':0.1,'maxOutputTokens':500,'responseMimeType':'application/json'},'contents':[{'parts':parts}]}
req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent',json.dumps(body).encode(),{'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']})
try:
 with urllib.request.urlopen(req,timeout=240) as r:result=json.load(r)
except urllib.error.HTTPError as e:raise SystemExit('Video reviewer HTTP status '+str(e.code))
raw=''.join(p.get('text','') for p in result['candidates'][0]['content']['parts']);obj=json.loads(raw);out={}
for k in ('A','B'):
 v=obj.get(k) or {}; out[k]={'person_visible':v.get('person_visible') if isinstance(v.get('person_visible'),bool) else None,'head_rotation':v.get('head_rotation') if v.get('head_rotation') in ('yes','no','uncertain') else 'uncertain'}
os.makedirs('out',exist_ok=True);json.dump(out,open('out/comparison.json','w'),indent=2);print(json.dumps(out))
