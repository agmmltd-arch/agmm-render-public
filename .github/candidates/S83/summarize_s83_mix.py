#!/usr/bin/env python3
"""Reduce private render output to a bounded text-only quality receipt."""
import argparse, hashlib, json
from pathlib import Path

def main():
 p=argparse.ArgumentParser(); p.add_argument('--manifest',required=True,type=Path); p.add_argument('--master',required=True,type=Path); p.add_argument('--output',required=True,type=Path); a=p.parse_args()
 m=json.loads(a.manifest.read_text()); master=m.get('master',{}); final=master.get('final',{}); codec=master.get('codec_check',{})
 if not a.master.is_file(): raise ValueError('master output missing')
 sha=hashlib.sha256(a.master.read_bytes()).hexdigest(); declared=master.get('sha256')
 if declared and declared!=sha: raise ValueError('mix manifest master SHA mismatch')
 receipt={'schema':'agmm-s83-mix-quality-receipt-v1','status':'TECHNICAL_MIX_RENDERED_NEEDS_EARS_AND_EDITORIAL_REVIEW','master':{'bytes':a.master.stat().st_size,'sha256':sha,'duration_seconds':m.get('duration_s'),'sample_rate_hz':m.get('sample_rate'),'integrated_lufs':final.get('integrated_lufs'),'true_peak_dbtp':final.get('true_peak_dbtp'),'limiter':master.get('limiter'),'limiter_passes':master.get('limiter_passes'),'codec_check':codec},'sfx_cue_count':len(m.get('cues',[])),'clamp_count':len(m.get('clamps',[])),'warnings':{'cue_clamps':'REVIEW_REQUIRED','word_timing_anomalies':'REVIEW_REQUIRED','heidi_voice_or_music_interaction':'REVIEW_REQUIRED'},'audio_review':'NOT_PERFORMED','rights':'NOT_ASSESSED','approval':'NOT_GRANTED','protected_master_or_stems_in_artifact':False}
 a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(receipt,indent=2)+'\n'); print('MIX_RECEIPT_CREATED audio_review=NOT_PERFORMED artifact_contains_audio=false')
if __name__=='__main__': main()
