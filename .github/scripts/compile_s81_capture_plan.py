#!/usr/bin/env python3
"""Bind S81 voice-clock stills to a validated hosted package's exact part geometry."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path


def compile_plan(candidate: dict, parts_doc: dict, source_sha: str, parts_sha: str, media_sha: str) -> dict:
    if candidate.get('short_id') != 'S81' or candidate.get('version') != 1:
        raise ValueError('candidate capture plan must be version 1 / S81')
    parts=parts_doc.get('parts')
    if not isinstance(parts,list) or not parts:
        raise ValueError('validated parts.json is required')
    duration=float(candidate.get('duration_s',-1))
    actual_duration=sum(float(x['dur']) for x in parts)
    if not math.isfinite(duration) or abs(actual_duration-duration)>1/30+1e-6:
        raise ValueError(f'candidate duration {duration} does not bind package duration {actual_duration}')
    requested=candidate.get('named_captures')
    if not isinstance(requested,list) or not requested:
        raise ValueError('candidate must contain named_captures')
    names=set(); captures=[]
    for row in requested:
        name=row.get('name'); t=float(row.get('global_s',float('nan')))
        if not isinstance(name,str) or not name or name in names:
            raise ValueError(f'duplicate or invalid capture name: {name!r}')
        names.add(name)
        if not math.isfinite(t) or not 0 <= t < actual_duration:
            raise ValueError(f'capture {name} is outside package timeline')
        owner=next((p for p in parts if float(p['off']) <= t < float(p['off'])+float(p['dur'])-1e-9),None)
        if owner is None:
            raise ValueError(f'capture {name} falls outside all parts')
        captures.append({'name':name,'kind':'beat','global':round(t,6),'local':round(t-float(owner['off']),6),'look':owner['look']})
    return {
      'version':1,'short_id':'S81','source_sha256':source_sha,'parts_sha256':parts_sha,
      'media_identity_sha256':media_sha,'include_part_seams':True,'captures':captures,
      'source_capture_only':True,'approval':'NOT_GRANTED'
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--candidate',type=Path,required=True)
    ap.add_argument('--parts',type=Path,required=True)
    ap.add_argument('--source-sha256',required=True)
    ap.add_argument('--parts-sha256',required=True)
    ap.add_argument('--media-identity-sha256',required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    plan=compile_plan(json.loads(a.candidate.read_text()),json.loads(a.parts.read_text()),a.source_sha256,a.parts_sha256,a.media_identity_sha256)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(plan,indent=2,sort_keys=True)+'\n')

if __name__=='__main__': main()
