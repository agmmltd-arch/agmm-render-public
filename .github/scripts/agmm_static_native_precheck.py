#!/usr/bin/env python3
"""Check source motion before render, using 0.1 s snapshots from public Ubuntu Actions.

Uses gate check 3's unchanged 10 fps, 320 px, 0.4% and 1.5 s rules.
This is a source check, never a replacement for the encoded-master gate.
Incomplete capture or source changes refuse the check, rather than return PASS.
"""
import argparse
import datetime
import glob
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import time

KIT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / 'tools'))
sys.path.insert(0, str(KIT.parent / 'qa'))
import storyboard
import gate


def bindings(sid):
    parts_path = KIT / 'out' / sid / 'build/parts.json'
    return {
        'source_hash': storyboard.spec_hash(sid),
        'parts_json': parts_path.read_text(),
        'resolved_json': (KIT / 'out' / sid / 'resolved.json').read_text(),
    }


def measure(paths):
    import numpy as np
    from PIL import Image
    frames = []
    for path in paths:
        with Image.open(path) as image:
            width = gate.STATIC_SAMPLE_WIDTH
            height = round(image.height * width / image.width / 2) * 2
            frames.append(np.asarray(image.convert('L').resize((width, height), Image.Resampling.BICUBIC)))
    spans, diffs = gate.static_hold_spans(np.stack(frames))
    limit = gate.STATIC_MAX_SPAN['short']
    bad = [s for s in spans if s[2] > limit]
    return {
        'verdict': 'FAIL' if bad else 'PASS',
        'frames': len(frames),
        'fps': gate.STATIC_SAMPLE_FPS,
        'width': gate.STATIC_SAMPLE_WIDTH,
        'threshold_pct': gate.STATIC_DIFF_PCT_THRESHOLD,
        'max_allowed_s': limit,
        'max_span_s': max((s[2] for s in spans), default=0),
        'bad_spans': [{'start_s': s[0], 'end_s': s[1], 'duration_s': s[2]} for s in bad],
        'spans': [{'start_s': s[0], 'end_s': s[1], 'duration_s': s[2]} for s in spans],
        'diff_pct': {'min': min(diffs), 'median': sorted(diffs)[len(diffs)//2], 'max': max(diffs)},
    }


def capture(sid):
    why = storyboard.stale_build(sid)
    if why:
        raise RuntimeError(why)
    before = bindings(sid)
    parts = json.loads(before['parts_json'])['parts']
    duration = max(float(p['off']) + float(p['dur']) for p in parts)
    fps = gate.STATIC_SAMPLE_FPS
    count = math.ceil(duration * fps - 1e-8)
    times = ','.join('%.2f' % (i / fps) for i in range(count))
    started = time.time()
    # Explicitly no Codespaces or Mac fallback.
    env = dict(os.environ, AGMM_SNAP='actions')
    run = subprocess.run([sys.executable, str(KIT/'tools/snap.py'), sid, '--at', times],
                         cwd=KIT, env=env, capture_output=True, text=True)
    dest = KIT/'out'/sid/'static-precheck'
    dest.mkdir(exist_ok=True)
    (dest/'capture.log').write_text(run.stdout + run.stderr)
    if run.returncode:
        raise RuntimeError('Actions capture failed rc%d; see %s' % (run.returncode, dest/'capture.log'))
    if bindings(sid) != before:
        raise RuntimeError('Source/package changed while Actions captured it; no result bound')
    offsets = {p['out']: float(p['off']) for p in parts}
    selected = {}
    for f in glob.glob(str(KIT/'out'/sid/'snap/*/frame-*.jpg')):
        p = pathlib.Path(f)
        if p.stat().st_mtime < started - 1:
            continue
        match = re.search(r'at-([\d.]+)s', p.name)
        if not match or p.parent.name not in offsets:
            continue
        absolute = offsets[p.parent.name] + float(match.group(1))
        idx = round(absolute * fps)
        if not 0 <= idx < count or abs(absolute - idx / fps) > 0.015:
            raise RuntimeError('Unexpected frame time %s; no PASS from an irregular grid' % p)
        if idx in selected:
            raise RuntimeError('Duplicate sample at %.2fs; capture is ambiguous' % (idx/fps))
        selected[idx] = p
    missing = sorted(set(range(count)) - set(selected))
    if missing:
        raise RuntimeError('Missing %d of %d required samples, first indices %s' % (len(missing), count, missing[:10]))
    paths = [selected[i] for i in range(count)]
    result = measure(paths)
    if bindings(sid) != before:
        raise RuntimeError('Source/package changed during measurement; no result bound')
    result.update(id=sid, at=datetime.datetime.now().astimezone().isoformat(),
                  source_hash=before['source_hash'], package_sha256=json.loads(before['parts_json']).get('sha256'),
                  backend='public Ubuntu Actions', duration_s=duration, complete_grid=True,
                  capture_started_epoch=started, capture_log=str(dest/'capture.log'),
                  scope='pre-render source snapshots; encoded master gate and perception still required',
                  limitations=['JPEG/Pillow sampling differs from encoded ffmpeg frames; final check3 remains required',
                               'No static exceptions are excused by this source check'])
    (dest/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('id')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    if not re.fullmatch(r'[A-Z]\d{2,3}', args.id):
        ap.error('Expected a short ID')
    try:
        result = capture(args.id)
    except Exception as e:
        print('static_precheck TOOL ERROR: %s' % e, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print('static_precheck %s: %s, %d frames @%dfps, longest %.2fs; %d spans >%.1fs' %
              (args.id, result['verdict'], result['frames'], result['fps'], result['max_span_s'],
               len(result['bad_spans']), result['max_allowed_s']))
        for span in result['bad_spans']:
            print('FAIL %.2f–%.2fs (%.2fs)' % (span['start_s'],span['end_s'],span['duration_s']))
    return 1 if result['verdict']=='FAIL' else 0


if __name__ == '__main__':
    raise SystemExit(main())
