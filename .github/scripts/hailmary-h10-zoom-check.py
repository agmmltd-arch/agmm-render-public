import base64,json,os,subprocess,urllib.request,urllib.error
import imageio_ffmpeg
ff=imageio_ffmpeg.get_ffmpeg_exe()
def ask(parts):
 body={'generationConfig':{'temperature':0.1,'maxOutputTokens':1000,'responseMimeType':'application/json'},'contents':[{'parts':parts}]}
 req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent',json.dumps(body).encode(),{'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']})
 try:
  with urllib.request.urlopen(req,timeout=180) as r: result=json.load(r)
 except urllib.error.HTTPError as e:raise SystemExit('HTTP status '+str(e.code))
 return json.loads(''.join(p.get('text','') for p in result['candidates'][0]['content']['parts']))
subprocess.run([ff,'-nostdin','-y','-v','error','-ss','2','-i','old/SHARE.mp4','-frames:v','1','-vf','scale=720:1280','/tmp/frame.png'],check=True)
prompt='Locate the visible head of the human male in this vertical frame. Return JSON only {"box":[ymin,xmin,ymax,xmax],"visible":true} with integer coordinates from 0 to 1000, or {"box":null,"visible":false} if the head is too unclear. Box only the head, not the body.'
b64=base64.b64encode(open('/tmp/frame.png','rb').read()).decode();d=ask([{'text':prompt},{'inline_data':{'mime_type':'image/png','data':b64}}]);print('HEAD_BOX',json.dumps(d),flush=True)
box=d.get('box');assert d.get('visible') is True and isinstance(box,list) and len(box)==4 and all(isinstance(x,(int,float)) and 0<=x<=1000 for x in box)
y0,x0,y1,x1=box;assert x1>x0 and y1>y0
cx=(x0+x1)/2000;cy=(y0+y1)/2000;cw=max(.22,min(.6,(x1-x0)/1000*2.5));ch=max(.18,min(.48,(y1-y0)/1000*2.5));left=max(0,min(1-cw,cx-cw/2));top=max(0,min(1-ch,cy-ch/2));vf=f'crop=iw*{cw}:ih*{ch}:iw*{left}:ih*{top},scale=640:640:force_original_aspect_ratio=decrease,pad=640:640:(ow-iw)/2:(oh-ih)/2,fps=10'
for name in ('old','new'):
 subprocess.run([ff,'-nostdin','-y','-v','error','-i',name+'/SHARE.mp4','-t','8','-an','-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','25','/tmp/'+name+'.mp4'],check=True)
parts=[{'text':'Examine both silent close-up clips independently, from start to finish. Describe the direction of the visible head at the beginning, middle and end. Report whether you observe large rotation, small rotation, none, or cannot tell. Do not assume they are different. Return JSON {"old":{"direction_start":"...","direction_middle":"...","direction_end":"...","rotation":"large|small|none|unclear"},"new":{same fields}}.'}]
for name in ('old','new'):parts.extend([{'text':name},{'inline_data':{'mime_type':'video/mp4','data':base64.b64encode(open('/tmp/'+name+'.mp4','rb').read()).decode()}}])
out=ask(parts);print('HEAD_REVIEW',json.dumps(out),flush=True)
