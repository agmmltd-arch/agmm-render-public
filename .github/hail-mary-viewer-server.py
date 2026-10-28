import os,re,pathlib,subprocess,time,json,hashlib,threading,http.server,urllib.parse,shutil
secret=os.environ['PLAYER_SESSION_KEY']
token=hashlib.sha256(('hail-mary-viewer:'+secret).encode()).hexdigest()
root=pathlib.Path('phone').resolve()
files={f'H{i:02d}':root/f'H{i:02d}-1080.mp4' for i in range(2,12)}
assert all(p.is_file() and p.stat().st_size for p in files.values())
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_HEAD(self): self.serve(False)
 def do_GET(self): self.serve(True)
 def serve(self,body):
  path=urllib.parse.urlsplit(self.path).path
  match=re.fullmatch('/'+token+r'/(H\d\d)\.mp4',path)
  if not match or match.group(1) not in files:
   self.send_error(404);return
  p=files[match.group(1)]; size=p.stat().st_size; start,end=0,size-1
  val=self.headers.get('Range')
  if val:
   m=re.fullmatch(r'bytes=(\d+)-(\d*)',val)
   if not m: self.send_error(416);return
   start=int(m.group(1));end=min(int(m.group(2)) if m.group(2) else end,end)
   if start>end: self.send_error(416);return
  self.send_response(206 if val else 200)
  self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1));self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer')
  if val:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
  self.end_headers()
  if body:
   try:
    with p.open('rb') as f:
     f.seek(start); left=end-start+1
     while left:
      chunk=f.read(min(left,262144))
      if not chunk:break
      self.wfile.write(chunk);left-=len(chunk)
   except (BrokenPipeError,ConnectionResetError):pass
httpd=http.server.ThreadingHTTPServer(('127.0.0.1',18765),Handler)
threading.Thread(target=httpd.serve_forever,daemon=True).start()
with open('tunnel.log','w') as log:
 tunnel=subprocess.Popen(['./cloudflared','tunnel','--no-autoupdate','--url','http://127.0.0.1:18765'],stdout=log,stderr=log)
for _ in range(120):
 time.sleep(1)
 if tunnel.poll() is not None:raise RuntimeError('tunnel stopped')
 s=pathlib.Path('tunnel.log').read_text(errors='replace')
 m=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',s)
 if m:break
else:raise RuntimeError('tunnel unavailable')
metadata=json.dumps({'base':m.group(0)+'/'+token,'films':list(files)})
subprocess.run(['openssl','enc','-aes-256-cbc','-pbkdf2','-salt','-out','viewer.enc','-pass','env:PLAYER_SESSION_KEY'],input=metadata.encode(),check=True)
pathlib.Path('viewer.ready').touch()
try:
 while tunnel.poll() is None:time.sleep(10)
finally:httpd.shutdown()
