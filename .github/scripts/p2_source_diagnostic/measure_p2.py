import os,platform,json,hashlib,time,urllib.request,urllib.error
from pathlib import Path
from urllib.parse import urlsplit
HOSTS={"agmm-content-share.pages.dev","8a38cd75.agmm-content-share.pages.dev"}
PIN_BYTES=237283443
PIN_SHA="1d6ec1c4a20eb1a3b8f1c7e21d96712b823f1b8532b6750b5fd964af47d17226"
SUFFIX="/media/P2-1d6ec1c4a20e?utm_source=qa&utm_campaign=qa_release_audit"
def guard(url):
 u=urlsplit(url)
 if u.scheme!="https" or u.hostname not in HOSTS or u.username or u.password or u.port not in (None,443):raise ValueError("untrusted source origin")
class Redirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  guard(newurl)
  return super().redirect_request(req,fp,code,msg,headers,newurl)
def measure(label,url,opener):
 guard(url); start=time.monotonic(); digest=hashlib.sha256(); count=0
 row={"label":label,"requested_url":url,"expected_bytes":PIN_BYTES,"expected_sha256":PIN_SHA}
 try:
  with opener.open(urllib.request.Request(url,headers={"User-Agent":"AGMM-hosted-P2-integrity/1"}),timeout=30) as response:
   row.update(final_url=response.geturl(),http_status=response.status,content_type=response.headers.get("Content-Type"),content_length=response.headers.get("Content-Length"))
   guard(row["final_url"])
   if response.status!=200:raise ValueError("unexpected source HTTP status")
   while True:
    if time.monotonic()-start>90:raise TimeoutError("bounded source deadline")
    block=response.read(1<<20)
    if not block:break
    count+=len(block);digest.update(block)
    if count>PIN_BYTES+(1<<20):raise ValueError("response exceeds source bound")
 except Exception as exc:row.update(error_type=type(exc).__name__,error=str(exc)[:250])
 row.update(bytes=count,sha256=digest.hexdigest(),elapsed_s=round(time.monotonic()-start,3))
 row["exact_match"]=not row.get("error") and count==PIN_BYTES and row["sha256"]==PIN_SHA
 return row
def main():
 if platform.system()!="Linux" or os.getenv("GITHUB_ACTIONS")!="true" or os.getenv("RUNNER_ENVIRONMENT")!="github-hosted":raise RuntimeError("hosted Ubuntu only")
 out=Path("p2-source-results");out.mkdir()
 doc={"schema":"agmm-hosted-p2-integrity-v1","programme_media_saved":False,"provider_calls":0,"retry_count":0,"results":[]}
 opener=urllib.request.build_opener(Redirect())
 for label,host in [("proxy","agmm-content-share.pages.dev"),("immutable-origin","8a38cd75.agmm-content-share.pages.dev")]:
  doc["results"].append(measure(label,"https://"+host+SUFFIX,opener))
  (out/"receipt.json").write_text(json.dumps(doc,indent=2)+"\n")
 print(json.dumps({"provider_calls":0,"matches":[x["exact_match"] for x in doc["results"]]}))
if __name__=="__main__":main()
