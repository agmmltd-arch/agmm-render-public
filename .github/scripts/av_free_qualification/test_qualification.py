import os,unittest,urllib.error,hashlib,random,json
from unittest.mock import patch
import qualification as q
import hosted_av_qualification as av
ENV={"GITHUB_ACTIONS":"true","FLEET_FREE_ONLY":"1","AGMM_GEMINI_FREE_PROJECT_ID":"gen-lang-client-0105607923","AGMM_GEMINI_BILLING_DISABLED":"true","AGMM_GEMINI_FREE_TIER":"true",q.KEY_NAME:"redacted-test-key"}
class Resp:
 def __init__(self,headers=None,body=b"{}"): self.status=200;self.headers=headers or {};self.body=body
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def read(self,*a):return self.body
class QualificationTests(unittest.TestCase):
 def test_scope_gate_rejects_mac_paid_vertex_missing_or_wrong_project(self):
  self.assertEqual(q.runtime_key(ENV,"Linux"),"redacted-test-key")
  for env,system in [(ENV,"Darwin"),({**ENV,"FLEET_FREE_ONLY":"0"},"Linux"),({**ENV,q.KEY_NAME:""},"Linux"),({k:v for k,v in ENV.items() if k!=q.KEY_NAME},"Linux"),({**ENV,"GEMINI_VERTEX_PROJECT":"paid"},"Linux"),({**ENV,"AGMM_GEMINI_FREE_PROJECT_ID":"other"},"Linux"),({**ENV,"AGMM_GEMINI_BILLING_DISABLED":"false"},"Linux"),({**ENV,"AGMM_GEMINI_FREE_TIER":"false"},"Linux")]:
   with self.assertRaises(q.Refused):q.runtime_key(env,system)
 def test_guard_precedes_network_process_and_media(self):
  net=[];proc=[]
  def n(*a,**k):net.append(1)
  def p(*a,**k):proc.append(1)
  with patch.dict(os.environ,{},clear=True):
   for fn in (lambda:q.download_verified({},object(),n),lambda:av.probe_full_av(object(),1,p),lambda:av.make_blind_videos({},object(),ffmpeg=p),lambda:av.upload_video(object(),"x",n)):
    with self.assertRaises(q.Refused):fn()
  self.assertEqual(net,[]);self.assertEqual(proc,[])
 def test_upload_origin_rejected_before_media_read(self):
  calls=[];media=[]
  class FakePath:
   def stat(self):return type("S",(),{"st_size":12})()
   def read_bytes(self):media.append(1);return b"media"
  def opener(req,timeout):
   calls.append(req.full_url);return Resp({"x-goog-upload-url":"https://evil.invalid/upload"})
  with patch.dict(os.environ,ENV,clear=True),patch.object(q.platform,"system",return_value="Linux"),patch.object(av,"Path",lambda x:FakePath()):
   with self.assertRaises(av.Refused):av.upload_video("ignored","secret",opener)
  self.assertEqual(len(calls),1);self.assertEqual(media,[])
 def test_single_mocked_provider_transport_failure_has_no_retry(self):
  calls=[]
  def opener(req,timeout):calls.append(req.full_url);raise urllib.error.URLError("synthetic quota/transport")
  with patch.dict(os.environ,ENV,clear=True),patch.object(q.platform,"system",return_value="Linux"):
   with self.assertRaises(av.Refused):av.http_once("POST",av.API+"/v1beta/models/"+q.MODEL+":generateContent",{},b"synthetic",opener=opener)
  self.assertEqual(len(calls),1)
 def test_provider_must_stop_with_nonempty_unblocked_text(self):
  good={"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":"observed"}]}}]}
  self.assertEqual(av.validate_provider_response(good),("STOP","observed",False))
  for bad in (None,{},{"candidates":[{"finishReason":"MAX_TOKENS","content":{"parts":[{"text":"partial"}]}}]},{"candidates":[{"finishReason":"SAFETY","content":{"parts":[{"text":"blocked"}]}}]},{"promptFeedback":{"blockReason":"SAFETY"},"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":"x"}]}}]}):
   reason,body,blocked=av.validate_provider_response(bad);self.assertFalse(reason=="STOP" and body and not blocked)
 def test_complete_six_video_panel_no_trim_and_qa_pins(self):
  self.assertEqual(len(q.ASSETS),3);self.assertTrue(all(a["url"].endswith(q.QA) for a in q.ASSETS.values()))
  source=AV_SOURCE
  self.assertIn('"synthetic-periodic-pumping"',source);self.assertIn('"synthetic-high-level-noise"',source);self.assertIn('"synthetic-audio-dropout"',source)
  self.assertNotIn('"-t"',source);self.assertIn('"file_data":{"mime_type":"video/mp4","file_uri":file_uri}',source)
  self.assertIn('len(public)!=6',source);self.assertIn('finishReason',source)
 def test_blinded_full_master_construction_in_memory(self):
  storage={"p1.mp4":b"p1-full","p2.mp4":b"p2-full","p3.mp4":b"p3-full"};ffmpeg_calls=[];probes=[]
  durations={"p1.mp4":58.9,"p2.mp4":59.7,"p3.mp4":58.4}
  class FP:
   def __init__(self,value):self.value=value if isinstance(value,str) else str(value)
   @property
   def name(self):return self.value.rsplit("/",1)[-1]
   def __str__(self):return self.value
   def __truediv__(self,other):return FP(self.value.rstrip("/")+"/"+str(other))
   def mkdir(self,*a,**k):return None
   def is_file(self):return self.value in storage
   def stat(self):return type("S",(),{"st_size":len(storage[self.value])})()
   def read_bytes(self):return storage[self.value]
   def write_bytes(self,data):
    storage[self.value]=data
    durations[self.value]=next(d for key,d in durations.items() if key in ("p1.mp4","p2.mp4","p3.mp4") and storage.get(key)==data)
    return len(data)
  def fake(args,**kw):
   if args[0]=="ffprobe":
    p=args[-1];probes.append(p);base=next((k for k in durations if p.endswith(k)),None);d=durations.get(base,58.9)
    return type("P",(),{"stdout":json.dumps({"format":{"duration":d},"streams":[{"codec_type":"video"},{"codec_type":"audio"}]})})()
   ffmpeg_calls.append(args);source=args[args.index("-i")+1];storage[args[-1]]=b"derived-full-"+str(len(ffmpeg_calls)).encode();durations[args[-1]]=durations[source];return type("P",(),{"stdout":""})()
  with patch.dict(os.environ,ENV,clear=True),patch.object(q.platform,"system",return_value="Linux"),patch.object(av,"Path",FP),patch.object(q,"sha256_file",lambda p:hashlib.sha256(storage[str(p)]).hexdigest()):
   manifest,labels=av.make_blind_videos({"p1":FP("p1.mp4"),"p2":FP("p2.mp4"),"p3":FP("p3.mp4")},FP("blind"),ffmpeg=fake,rng=random.Random(3))
  self.assertEqual(len(manifest),6);self.assertEqual(len(labels),6);self.assertEqual(len(probes),12);self.assertEqual(len(ffmpeg_calls),3)
  for args in ffmpeg_calls:self.assertNotIn("-t",args);self.assertIn("-c:v",args);self.assertIn("copy",args)
  self.assertEqual(sum(x["expected"]=="clean" for x in labels.values()),3)
  self.assertEqual(sum(x["expected"]=="synthetic-severe-audio-defect" for x in labels.values()),3)
 def test_prompt_withholds_labels(self):
  p=av.PROMPT.lower()
  for word in ("p1","p2","p3","positive","negative","pumping-injected","noise-injected"):self.assertNotIn(word,p)
  self.assertIn("entire supplied video",p)
