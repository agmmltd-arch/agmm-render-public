#!/usr/bin/env python3
"""Bind a hosted S83 mixed review master to exact source/input receipts; no publishing here."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, re, shutil
from pathlib import Path

REPO="agmmltd-arch/agmm-render-public"
VIDEO="FINAL.mp4"
TECH="PUBLIC-TECHNICAL-EVIDENCE.json"
SUMS="PREVIEW-SHA256SUMS.txt"
RECEIPT="S83-DEVELOPMENT-PREVIEW.json"

class Refusal(ValueError): pass

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def exact_object(path: Path, schema: str, *, key: str='schema') -> dict:
    if path.is_symlink() or not path.is_file(): raise Refusal(f"missing or unsafe receipt: {path.name}")
    doc=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(doc,dict) or doc.get(key)!=schema: raise Refusal(f"receipt schema mismatch: {path.name}")
    return doc

def prepare(final: Path, evidence_path: Path, protected_path: Path, source_manifest: Path,
            source_packet: Path, parts_path: Path, mix_path: Path, mix_receipt_path: Path,
            clock_path: Path, head: str, run_id: str,
            attempt: str, tag: str, output: Path) -> dict:
    if platform.system()!="Linux" or os.environ.get('GITHUB_ACTIONS')!="true" or os.environ.get('RUNNER_ENVIRONMENT')!="github-hosted":
        raise Refusal("review-media hashing/export is restricted to GitHub-hosted Linux")
    if output.exists(): raise Refusal("refusing to overwrite a review export directory")
    if not re.fullmatch(r"[0-9a-f]{40}",head): raise Refusal("public head must be a full Git SHA")
    if not (run_id.isdigit() and attempt.isdigit() and tag == f'S83-development-review-{run_id}-a{attempt}'):
        raise Refusal("run-scoped preview release identity is invalid")
    if not final.is_file() or final.is_symlink() or final.stat().st_size<=8: raise Refusal("mixed master missing or unsafe")
    with final.open('rb') as f:
        if f.read(8)[4:8] != b'ftyp': raise Refusal("final is not a bounded MP4 container")
    protected=exact_object(protected_path,'agmm-s83-protected-input-verification-v1')
    input_manifest=exact_object(source_manifest.parent/'PROTECTED-INPUTS.json','agmm-s83-protected-inputs-v1')
    rows=input_manifest.get('assets',[])
    if input_manifest.get('repository')!='agmmltd-arch/agmm-video-render' or len(rows)!=18 or protected.get('private_commit')!=input_manifest.get('private_tree_binding',{}).get('commit'):
        raise Refusal('private receipt does not bind the candidate protected-input manifest')
    if protected.get('status')!='PASS_18_EXACT_INPUTS' or protected.get('asset_count')!=18 or len(protected.get('items',[]))!=18:
        raise Refusal("exact 18 private inputs have not been verified")
    by_name={x.get('name'):x for x in protected['items']}
    if len(by_name)!=18 or any(x.get('status')!='PASS' for x in protected['items']): raise Refusal("private input receipt contains missing, duplicate or failed items")
    for row in rows:
        item=by_name.get(row.get('name'))
        if not item or item.get('asset_id')!=row.get('id') or item.get('git_blob_sha')!=row.get('git_blob_sha') or item.get('bytes')!=row.get('size') or item.get('sha256')!=str(row.get('digest','')).removeprefix('sha256:'):
            raise Refusal('verified private item differs from the exact protected manifest: '+str(row.get('name')))
    candidate=exact_object(source_manifest,'agmm-s83-candidate-manifest-v1')
    if candidate.get('story_id')!='S83': raise Refusal('candidate manifest story identity mismatch')
    from guard_review_artifact import validate_packet
    packet=validate_packet(source_packet)
    source=json.loads((source_packet/'SOURCE-CAPTURE-RECEIPT.json').read_text())
    status=json.loads((source_packet/'CAPTURE-STATUS.json').read_text())
    check=json.loads((source_packet/'HYPERFRAMES-CHECK.json').read_text())
    frame_binding=exact_object(source_packet/'SOURCE-FRAMES-BINDING.json','agmm-s83-source-frames-binding-v1')
    if (packet.get('source_frames_sha256')!=frame_binding.get('frames_sha256')
            or frame_binding.get('candidate_manifest_sha256')!=sha(source_manifest)
            or frame_binding.get('source_public_head_sha')!=head):
        raise Refusal('37 source frames were not reviewed against this exact candidate manifest and public head')
    clock=exact_object(clock_path,'agmm-s83-hosted-source-clock-receipt-v1')
    if clock.get('status')!='TECHNICAL_SOURCE_BINDING_PASS_AUDIO_REVIEW_REQUIRED': raise Refusal('source clock receipt is not technically verified')
    if source.get('story_id')!='S83' or status.get('status')!='SOURCE_CHECK_AND_STILLS_CAPTURED_NEEDS_INDEPENDENT_EYES':
        raise Refusal("source-only review packet is not a complete successful S83 capture")
    if len([p for p in source_packet.glob('still-frame-*.png') if p.is_file() and not p.is_symlink()])!=37:
        raise Refusal("exact 37 source captures are required")
    evidence=exact_object(evidence_path,'agmm_short_remote_technical_evidence',key='kind')
    if evidence.get('technical_status')!='PASS' or evidence.get('editorial_status')!='NOT_REVIEWED' or evidence.get('publication_status')!='NOT_REQUESTED':
        raise Refusal("technical render is not a passing, unreviewed development output")
    masters=evidence.get('masters')
    if not isinstance(masters,list) or len(masters)!=1: raise Refusal("expected exactly one 1080 review master")
    master=masters[0]
    if master.get('file')!='FINAL.mp4' or master.get('resolution')!='1080' or master.get('full_decode')!='PASS' or master.get('frames')!=1696:
        raise Refusal("master technical evidence differs from the S83 delivery contract")
    probe=master.get('probe',{}); streams=probe.get('streams',[]) if isinstance(probe,dict) else []
    videos=[x for x in streams if x.get('codec_type')=='video']; audios=[x for x in streams if x.get('codec_type')=='audio']
    if len(videos)!=1 or len(audios)!=1 or (videos[0].get('width'),videos[0].get('height'),videos[0].get('r_frame_rate'))!=(1080,1920,'30/1'):
        raise Refusal('master probe must show one 1080x1920/30 video and one mixed audio stream')
    if audios[0].get('codec_name')!='aac' or int(audios[0].get('sample_rate',0))!=48000 or int(audios[0].get('channels',0))!=2:
        raise Refusal('master must contain exactly one stereo 48 kHz AAC mix')
    audio=master.get('audio',{})
    if not (-15.0<=float(audio.get('integrated_lufs',999))<=-13.0) or float(audio.get('true_peak_dbfs',999))>-1.0:
        raise Refusal('master loudness receipt is outside the -14 LUFS/true-peak standard')
    if master.get('sha256')!=sha(final) or master.get('bytes')!=final.stat().st_size: raise Refusal("final media identity differs from render receipt")
    part_doc=json.loads(parts_path.read_text()); mix_sha=sha(mix_path); parts_sha=sha(parts_path)
    mix_receipt=exact_object(mix_receipt_path,'agmm-s83-mix-quality-receipt-v1')
    mix_master=mix_receipt.get('master',{})
    if (mix_receipt.get('status')!='TECHNICAL_MIX_RENDERED_NEEDS_EARS_AND_EDITORIAL_REVIEW'
            or mix_receipt.get('audio_review')!='NOT_PERFORMED'
            or mix_receipt.get('approval')!='NOT_GRANTED'
            or mix_receipt.get('protected_master_or_stems_in_artifact') is not False
            or mix_master.get('sha256')!=mix_sha
            or mix_master.get('bytes')!=mix_path.stat().st_size):
        raise Refusal('mix-quality receipt does not bind the exact private master and open review status')
    if part_doc!={'parts':[{'look':'S83','file':'S83.mp4','out':'S83','off':0,'dur':56.533333}],'frames':1696}:
        raise Refusal("S83 render part inventory/duration changed")
    output.mkdir(parents=True)
    shutil.copyfile(final,output/VIDEO)
    safe={
      'schema':'agmm-s83-public-review-technical-v1','technical_status':'PASS',
      'master':{'name':VIDEO,'size_bytes':final.stat().st_size,'sha256':sha(final),'resolution':'1080x1920','frame_rate':'30/1','frames':1696,'duration_seconds':56.533333,'audio_streams':1,'audio_codec':'aac','sample_rate_hz':48000,'channels':2,'integrated_lufs':audio['integrated_lufs'],'true_peak_dbfs':audio['true_peak_dbfs']},
      'source_mix':{'sha256':mix_sha,'bytes':mix_path.stat().st_size,'quality_receipt_sha256':sha(mix_receipt_path),'source_clock_receipt_sha256':sha(clock_path)},
      'reviewed_source_frames':{'sha256':frame_binding['frames_sha256'],'candidate_manifest_sha256':frame_binding['candidate_manifest_sha256'],'source_public_head_sha':frame_binding['source_public_head_sha'],'count':37},
      'source_frames_sha256':frame_binding['frames_sha256'],'source_frame_binding_receipt_sha256':sha(source_packet/'SOURCE-FRAMES-BINDING.json'),
      'editorial_status':'NOT_REVIEWED','audio_listening':'NOT_PERFORMED','full_av_review':'OPEN',
      'rights':'NOT_ASSESSED','release_approval':'NOT_GRANTED','ready':'NOT_GRANTED'
    }
    (output/TECH).write_text(json.dumps(safe,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    (output/SUMS).write_text(f"{sha(output/VIDEO)}  {VIDEO}\n{sha(output/TECH)}  {TECH}\n",encoding='utf-8')
    receipt={
      'schema':'agmm-s83-development-preview-v1','repository':REPO,'tag':tag,
      'release_url':f'https://github.com/{REPO}/releases/tag/{tag}',
      'source_run':{'id':int(run_id),'attempt':int(attempt),'head_sha':head},
      'candidate_manifest_sha256':sha(source_manifest),'source_capture_receipt_sha256':sha(source_packet/'SOURCE-CAPTURE-RECEIPT.json'),
      'source_still_count':37,'source_check_sha256':sha(source_packet/'HYPERFRAMES-CHECK.json'),
      'source_frames_sha256':frame_binding['frames_sha256'],'source_frame_binding_receipt_sha256':sha(source_packet/'SOURCE-FRAMES-BINDING.json'),
      'reviewed_source_frames':{'sha256':frame_binding['frames_sha256'],'candidate_manifest_sha256':frame_binding['candidate_manifest_sha256'],'source_public_head_sha':frame_binding['source_public_head_sha'],'count':37},
      'parts_sha256':parts_sha,'mix_sha256':mix_sha,
      'source_mix':{'sha256':mix_sha,'bytes':mix_path.stat().st_size,'quality_receipt_sha256':sha(mix_receipt_path),'source_clock_receipt_sha256':sha(clock_path)},
      'private_input_binding':{'repository':'agmmltd-arch/agmm-video-render','commit':protected.get('private_commit'),'count':18,'manifest_sha256':sha(source_manifest.parent/'PROTECTED-INPUTS.json'),'verification_receipt_sha256':sha(protected_path)},
      'exported_master':{'name':VIDEO,'size_bytes':final.stat().st_size,'sha256':sha(final)},
      'asset_inventory':[{'name':VIDEO,'size':(output/VIDEO).stat().st_size,'sha256':sha(output/VIDEO)},
                         {'name':TECH,'size':(output/TECH).stat().st_size,'sha256':sha(output/TECH)},
                         {'name':SUMS,'size':(output/SUMS).stat().st_size,'sha256':sha(output/SUMS)}],
      'editorial_status':'NOT_REVIEWED','audio_listening':'OPEN','full_av_review':'OPEN','release_approval':'NOT_GRANTED','ready':'NOT_GRANTED',
      'raw_voice_or_stems_public':False
    }
    (output/RECEIPT).write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return receipt

def main():
    p=argparse.ArgumentParser();
    for name in ('final','evidence','protected','manifest','source-packet','parts','mix','mix-receipt','clock-receipt','head','run-id','attempt','tag','output'): p.add_argument('--'+name,required=True)
    a=p.parse_args()
    prepare(Path(a.final),Path(a.evidence),Path(a.protected),Path(a.manifest),Path(a.source_packet),Path(a.parts),Path(a.mix),Path(a.mix_receipt),Path(a.clock_receipt),a.head,a.run_id,a.attempt,a.tag,Path(a.output))
    print('S83_REVIEW_EXPORT_PREPARED_NOT_PUBLISHED')
if __name__=='__main__':
    try: main()
    except Exception as exc: raise SystemExit('REFUSED: '+str(exc)) from exc
