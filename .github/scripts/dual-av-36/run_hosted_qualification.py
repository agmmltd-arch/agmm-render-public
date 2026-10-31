#!/usr/bin/env python3
"""One bounded six-item full audiovisual challenge; hosted-only, no local fallback."""
import json,os,tempfile,traceback
from pathlib import Path
import qualification as q
import hosted_av_qualification as av

def main():
 # Strict scope/provenance guard runs before directories, file reads, media, or network.
 key=q.runtime_key()
 result_dir=Path(os.getenv("QUALIFICATION_RESULTS_DIR","qualification-results"))
 result_dir.mkdir(parents=True,exist_ok=True)
 source_receipts={}; completed=0
 try:
  with tempfile.TemporaryDirectory(prefix="agmm-free-av-") as td:
   tmp=Path(td); sources={}
   for name,asset in q.ASSETS.items():
    dst=tmp/(name+".mp4")
    source_receipts[name]=q.download_verified(asset,dst)
    (result_dir/"source-receipts.json").write_text(json.dumps(source_receipts,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    av.probe_full_av(dst,asset["duration_s"])
    keyname="p1" if name.startswith("P1") else "p2" if name.startswith("P2") else "p3"
    sources[keyname]=dst
   manifest,labels=av.make_blind_videos(sources,tmp/"blind",expected_durations={"p1":58.9,"p2":59.7,"p3":58.4})
   panel=av.run_blind_panel(tmp/"blind",manifest,labels,result_dir,key)
   completed=panel["calls"]
  summary={"status":"COMPLETED_UNADJUDICATED","model":q.MODEL,"model_call_cap":6,"completed_calls":completed,
   "retry_count":0,"fallback":False,"release_approval":"NOT_GRANTED",
   "limitation":"Finite full audiovisual calibration panel; not general reviewer qualification or release approval."}
  (result_dir/"run-summary.json").write_text(json.dumps(summary,sort_keys=True,indent=2)+"\n",encoding="utf-8")
  return summary
 except Exception as exc:
  log=result_dir/"blind-results.jsonl"
  if log.exists():
   try: completed=sum(1 for line in log.read_text(encoding="utf-8").splitlines() if line.strip() and json.loads(line).get("complete") is True)
   except Exception: pass
  summary={"status":"PARTIAL_OR_REFUSED","model":q.MODEL,"model_call_cap":6,"completed_calls":completed,
   "retry_count":0,"fallback":False,"release_approval":"NOT_GRANTED","terminal_error_type":type(exc).__name__,
   "terminal_error":str(exc)[:300]}
  (result_dir/"run-summary.json").write_text(json.dumps(summary,sort_keys=True,indent=2)+"\n",encoding="utf-8")
  raise

if __name__=="__main__": main()
