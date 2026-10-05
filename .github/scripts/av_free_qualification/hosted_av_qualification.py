"""One bounded GenerateContent request per complete audiovisual sample; hosted Ubuntu only."""
import hashlib,json,os,platform,random,subprocess,time,urllib.error,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
import qualification as q

API="https://generativelanguage.googleapis.com"
PROMPT=("Review the entire supplied video using audiovisual perception. Inspect the whole timeline, including openings, pauses, edits and ending. "
 "Give timestamped, directly observed evidence about source/picture authenticity, motion/cuts, captions/layout, speech intelligibility and cadence, "
 "music masking or pumping, SFX placement/masking, noise/clicks/clipping, and cut-off words. Report issues and clear passes with timestamps. "
 "Do not infer the identity of the sample, transcribe the script as a substitute for listening, score loudness, or approve/reject release.")

class Refused(RuntimeError): pass

def guard_google_url(url):
 u=urlsplit(url)
 if u.scheme!="https" or not u.hostname or u.username or u.password or u.port not in (None,443):
  raise Refused("untrusted Google API/upload URL")
 host=u.hostname.lower()
 if host!="generativelanguage.googleapis.com" and not host.endswith(".googleapis.com"):
  raise Refused("upload destination is outside trusted Google API origins")

class GoogleRedirectGuard(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  guard_google_url(newurl)
  return super().redirect_request(req,fp,code,msg,headers,newurl)

def safe_urlopen(req,timeout):
 q.runtime_key(); guard_google_url(req.full_url)
 return urllib.request.build_opener(GoogleRedirectGuard()).open(req,timeout=timeout)

def http_once(method,url,headers,data=b"",timeout=120,opener=None):
 q.runtime_key(); guard_google_url(url)
 req=urllib.request.Request(url,method=method,data=data,headers=headers)
 opener=safe_urlopen if opener is None else opener
 try:
  with opener(req,timeout=timeout) as r:
   return {"status":r.status,"headers":{k.lower():v for k,v in r.headers.items()},"body":r.read()}
 except urllib.error.HTTPError as e:
  raise Refused("Google API HTTP "+str(e.code)+"; terminal; no retry/fallback") from None
 except (urllib.error.URLError,TimeoutError,OSError) as e:
  raise Refused("Google API transport "+type(e).__name__+"; terminal; no retry/fallback") from None

def upload_video(path,key,opener=None):
 q.runtime_key()
 path=Path(path); size=path.stat().st_size
 if not size: raise Refused("empty audiovisual sample")
 start_headers={"x-goog-api-key":key,"X-Goog-Upload-Protocol":"resumable","X-Goog-Upload-Command":"start",
  "X-Goog-Upload-Header-Content-Length":str(size),"X-Goog-Upload-Header-Content-Type":"video/mp4","Content-Type":"application/json"}
 started=http_once("POST",API+"/upload/v1beta/files",start_headers,json.dumps({"file":{"display_name":"blind-sample.mp4"}}).encode(),opener=opener)
 upload_url=started["headers"].get("x-goog-upload-url")
 if not upload_url: raise Refused("Files API returned no resumable upload URL")
 # Validate origin before reading/sending any source media; one transfer attempt only.
 guard_google_url(upload_url)
 uploaded=http_once("POST",upload_url,{"Content-Length":str(size),"X-Goog-Upload-Offset":"0","X-Goog-Upload-Command":"upload, finalize"},
  path.read_bytes(),timeout=900,opener=opener)
 try: f=json.loads(uploaded["body"]).get("file",{})
 except (ValueError,TypeError): f={}
 if not f.get("name") or not f.get("uri"): raise Refused("Files API upload returned no file resource")
 guard_google_url(f["uri"])
 return f

def wait_active(name,key,opener=None,sleep=time.sleep):
 q.runtime_key()
 for i in range(12):
  if i: sleep(10)
  r=http_once("GET",API+"/v1beta/"+name,{"x-goog-api-key":key},timeout=30,opener=opener)
  try:
   f=json.loads(r["body"]); f=f.get("file",f)
  except (ValueError,TypeError): raise Refused("malformed Files API status; terminal") from None
  if f.get("state")=="ACTIVE":
   if not f.get("uri"): raise Refused("ACTIVE file has no Google URI")
   guard_google_url(f["uri"])
   return f
  if f.get("state")!="PROCESSING": raise Refused("Files API returned FAILED/unknown state; terminal")
 raise Refused("Files API processing timeout; terminal; no upload retry")

def one_generate_content_request(file_uri,key,opener=None):
 q.runtime_key(); guard_google_url(file_uri)
 body={"contents":[{"parts":[
  {"file_data":{"mime_type":"video/mp4","file_uri":file_uri}},
  {"text":PROMPT}]}],"generationConfig":{"temperature":0.1,"maxOutputTokens":4000}}
 raw=json.dumps(body,separators=(",",":")).encode()
 response=http_once("POST",API+"/v1beta/models/"+q.MODEL+":generateContent",{"Content-Type":"application/json","x-goog-api-key":key},raw,timeout=600,opener=opener)
 try: parsed=json.loads(response["body"])
 except (ValueError,TypeError): return response["body"],None
 return response["body"],parsed

def probe_full_av(path,expected_duration,run=subprocess.run):
 q.runtime_key()
 p=run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,duration","-of","json",str(path)],
       check=True,capture_output=True,text=True)
 data=json.loads(p.stdout); kinds=[s.get("codec_type") for s in data.get("streams",[])]
 if kinds.count("video")!=1 or kinds.count("audio")!=1: raise Refused("master must contain exactly one video and one audio stream")
 duration=float(data.get("format",{}).get("duration") or 0)
 if duration<=0 or abs(duration-expected_duration)>0.75: raise Refused("full audiovisual master duration differs from its pin")
 return duration

def make_blind_videos(verified_videos,outdir,expected_durations=None,ffmpeg=subprocess.run,rng=None):
 q.runtime_key()
 rng=rng or random.SystemRandom(); outdir=Path(outdir); outdir.mkdir(parents=True,exist_ok=True)
 ids=["blind-"+x for x in "ABCDEF"]; rng.shuffle(ids)
 expected_durations=expected_durations or {"p1":58.9,"p2":59.7,"p3":58.4}
 specs=[("P1-r7-published",Path(verified_videos["p1"]),"p1","clean"),
  ("P2-corrected-audio-v2",Path(verified_videos["p2"]),"p2","clean"),
  ("P3-corrected-audio-v2",Path(verified_videos["p3"]),"p3","clean"),
  ("synthetic-periodic-pumping",Path(verified_videos["p1"]),"p1","pump"),
  ("synthetic-high-level-noise",Path(verified_videos["p1"]),"p1","noise"),
  ("synthetic-audio-dropout",Path(verified_videos["p1"]),"p1","dropout")]
 public=[]; labels={}
 for blind_id,(label,src,sourcekey,kind) in zip(ids,specs):
  source_duration=probe_full_av(src,expected_durations[sourcekey],ffmpeg)
  dst=outdir/(blind_id+".mp4")
  if kind=="clean": dst.write_bytes(src.read_bytes())
  else:
   args=["ffmpeg","-nostdin","-v","error","-y","-i",str(src)]
   if kind=="pump":
    args += ["-map","0:v:0","-map","0:a:0","-af","volume='if(lt(mod(t,4),1),0.12,1)':eval=frame"]
   elif kind=="dropout":
    args += ["-map","0:v:0","-map","0:a:0","-af","volume='if(lt(mod(t,8),1),0,1)':eval=frame"]
   else:
    args += ["-f","lavfi","-i","anoisesrc=color=pink:amplitude=0.5:sample_rate=48000","-filter_complex",
     "[1:a]atrim=duration=3600[n];[0:a][n]amix=inputs=2:duration=first:weights='1 1':normalize=0[a]",
     "-map","0:v:0","-map","[a]"]
   args += ["-c:v","copy","-c:a","aac","-b:a","128k","-movflags","+faststart",str(dst)]
   ffmpeg(args,check=True,capture_output=True)
  if not dst.is_file() or not dst.stat().st_size: raise Refused("blind complete-video sample missing")
  derived_duration=probe_full_av(dst,expected_durations[sourcekey],ffmpeg)
  if abs(derived_duration-source_duration)>0.25: raise Refused("sample no longer covers the complete original audiovisual duration")
  digest=q.sha256_file(dst)
  public.append({"blind_id":blind_id,"file":dst.name,"bytes":dst.stat().st_size,"sha256":digest})
  labels[blind_id]={"source_label":label,"expected":"clean" if kind=="clean" else "synthetic-severe-audio-defect","stimulus_sha256":digest}
 if len(public)!=6 or len({x["blind_id"] for x in public})!=6: raise Refused("six-item panel construction failed")
 return public,labels

def append_jsonl(outdir,name,row):
 p=Path(outdir)/name
 with p.open("a",encoding="utf-8") as stream:
  stream.write(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n")
  stream.flush(); os.fsync(stream.fileno())


def validate_provider_response(result):
 if not isinstance(result,dict): return None,"",True
 candidates=result.get("candidates",[])
 candidate=candidates[0] if isinstance(candidates,list) and candidates and isinstance(candidates[0],dict) else {}
 reason=candidate.get("finishReason")
 content=candidate.get("content",{})
 parts=content.get("parts",[]) if isinstance(content,dict) else []
 valid=isinstance(parts,list) and bool(parts) and all(isinstance(x,dict) and set(x)=={"text"} and isinstance(x["text"],str) for x in parts)
 text="".join(x["text"] for x in parts).strip() if valid else ""
 blocked=bool(result.get("promptFeedback",{}).get("blockReason"))
 return reason,text,blocked

def run_blind_panel(sample_dir,manifest,label_map,outdir,key,opener=None,sleep=time.sleep):
 q.runtime_key()
 if len(manifest)!=6 or len({x.get("blind_id") for x in manifest})!=6 or set(label_map)!={x["blind_id"] for x in manifest}: raise Refused("panel must contain six uniquely blinded items with a matching label map")
 if platform.system().strip().lower()!="linux" or os.getenv("GITHUB_ACTIONS","").strip().lower() not in ("true","1") or os.getenv("FLEET_FREE_ONLY","").strip()!="1":
  raise Refused("hosted GitHub Linux Free-only gate required")
 if os.getenv("GEMINI_WATCH_VERTEX","").strip().lower() in ("1","true","yes","on") or os.getenv("GEMINI_VERTEX_PROJECT","").strip():
  raise Refused("Vertex route forbidden")
 outdir=Path(outdir); outdir.mkdir(parents=True,exist_ok=True)
 label_bytes=(json.dumps(label_map,sort_keys=True,indent=2)+"\n").encode()
 (outdir/"labels-after-blind-review.private.json").write_bytes(label_bytes)
 label_hash=hashlib.sha256(label_bytes).hexdigest()
 (outdir/"blind-input-manifest.json").write_text(json.dumps({"model":q.MODEL,"items":manifest,"labels_sha256_commitment":label_hash,"provider_prompt_reveals_labels":False},sort_keys=True,indent=2)+"\n",encoding="utf-8")
 results=[]
 for item in manifest:
  path=Path(sample_dir)/item["file"]
  if path.stat().st_size!=item["bytes"] or q.sha256_file(path)!=item["sha256"]:
   append_jsonl(outdir,"blind-results.jsonl",{"blind_id":item["blind_id"],"status":"refused","reason":"sealed video preimage changed"})
   raise Refused("blind video preimage changed; terminal")
  try:
   file_info=upload_video(path,key,opener); active=wait_active(file_info["name"],key,opener,sleep)
   raw,result=one_generate_content_request(active["uri"],key,opener)
  except Refused as exc:
   append_jsonl(outdir,"blind-results.jsonl",{"blind_id":item["blind_id"],"status":"terminal_failure","reason":str(exc)})
   raise
  response_path=outdir/"provider-responses"/(item["blind_id"]+".json")
  response_path.parent.mkdir(parents=True,exist_ok=True)
  with response_path.open("wb") as stream:
   stream.write(raw); stream.flush(); os.fsync(stream.fileno())
  reason,text,blocked=validate_provider_response(result)
  complete=reason=="STOP" and bool(text) and not blocked
  row={"blind_id":item["blind_id"],"input_sha256":item["sha256"],"provider_response_file":str(response_path.relative_to(outdir)),
       "provider_response_sha256":hashlib.sha256(raw).hexdigest(),"model":q.MODEL,"finish_reason":reason,
       "blocked":blocked,"text":text,"response_sha256":hashlib.sha256(text.encode()).hexdigest() if text else None,
       "complete":complete}
  append_jsonl(outdir,"blind-results.jsonl",row)
  if not complete: raise Refused("provider response blocked, missing finishReason STOP, malformed or truncated; terminal")
  results.append(row)
  blind_doc={"model":q.MODEL,"calls":len(results),"call_cap":6,"retry_count":0,"fallback":False,
    "labels_sha256_commitment":label_hash,"results":results}
  (outdir/"blind-results.json").write_text(json.dumps(blind_doc,sort_keys=True,indent=2)+"\n",encoding="utf-8")
 return {"calls":len(results),"results":results}
