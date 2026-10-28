import base64,glob,io,json,os,urllib.error,urllib.request
from PIL import Image
files=glob.glob('proof/**/*.png',recursive=True)
def timeof(p):
 try:return float(os.path.basename(p).removesuffix('s.png'))
 except ValueError:return None
files=sorted(((timeof(p),p) for p in files if timeof(p) is not None),key=lambda x:x[0])
print('times available:',[x[0] for x in files])
if len(files)<5: raise SystemExit('Insufficient named frames')
parts=[{'text':'Inspect these consecutive frames from a 3D animated vertical video opening. Each image is labelled with its time in seconds. For each, say whether the main male character and his head are visible, and describe only observable head direction (front, left, right, up, down, unclear). Then decide whether head orientation shows a large unnatural rotation across frames, or whether evidence is inconclusive. Return JSON only {"frames":[{"seconds":0,"person_visible":true or false,"head_direction":"front" or "left" or "right" or "up" or "down" or "unclear"}],"rotation":"yes" or "no" or "inconclusive"}. Do not infer missing pixels.'}]
for t,p in files:
 im=Image.open(p).convert('RGB');im.thumbnail((540,960));b=io.BytesIO();im.save(b,format='JPEG',quality=85)
 parts.extend([{'text':str(t)+' seconds'},{'inline_data':{'mime_type':'image/jpeg','data':base64.b64encode(b.getvalue()).decode()}}])
body={'generationConfig':{'temperature':0.1,'maxOutputTokens':1500,'responseMimeType':'application/json'},'contents':[{'parts':parts}]}
req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent',json.dumps(body).encode(),{'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']})
try:
 with urllib.request.urlopen(req,timeout=240) as r: result=json.load(r)
except urllib.error.HTTPError as e:raise SystemExit('Vision reviewer HTTP status '+str(e.code))
raw=''.join(p.get('text','') for p in result['candidates'][0]['content']['parts']); obj=json.loads(raw)
out={'rotation':obj.get('rotation') if obj.get('rotation') in ('yes','no','inconclusive') else 'inconclusive','frames':[]}
for f in obj.get('frames',[]):
 if isinstance(f,dict) and isinstance(f.get('seconds'),(int,float)):
  out['frames'].append({'seconds':f['seconds'],'person_visible':f.get('person_visible') if isinstance(f.get('person_visible'),bool) else None,'head_direction':f.get('head_direction') if f.get('head_direction') in ('front','left','right','up','down','unclear') else 'unclear'})
os.makedirs('out',exist_ok=True);json.dump(out,open('out/review.json','w'),indent=2);print(json.dumps(out))
