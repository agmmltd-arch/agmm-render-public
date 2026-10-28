#!/usr/bin/env python3
"""Check source motion before render, using 0.1 s snapshots from public Ubuntu Actions.

Uses gate check 3's unchanged 10 fps, 320 px, 0.4% and 1.5 s rules.
This is a source check, never a replacement for the encoded-master gate.
Incomplete capture or source changes refuse the check, rather than return PASS.

Parallel capture (13 Oct 2026): the ~580 frames used to go through ONE Actions snap call (350-500 s of the maker's precheck wall time).
They are now split into AGMM_STATIC_SPLIT (default 8; 1 = the old single call) contiguous time ranges, each its own snap.py call, so
each lands on its own hosted runner (capped by the free hosted slots, see hosted_free_slots). Neighbouring ranges overlap by
AGMM_STATIC_OVERLAP frames (default 3) on each side.
Why the overlap, measured on S25 (n=8): the SAME instant rendered by two runners is not always the same pixels (0.01-0.10% mean diff,
persistent for a whole chunk edge, so it is session state, not a one-frame warm-up). A transition between the last frame of one runner
and the first of the next would therefore carry that offset. So the frame-to-frame differences are computed INSIDE each chunk (chunk k
owns the transitions lo..hi, using its own frames up to hi, which the trailing overlap provides) and only the differences are
joined: a static span that crosses a split is measured from one browser session exactly as in a single call. The overlap frames are
also compared across runners; a gross disagreement (> OVERLAP_TOL_PCT, e.g. a different package or a broken render) refuses the check
instead of returning a verdict. Calls are started staggered with jitter (the first one alone until it has dispatched, so the
content-hashed release is created once) and snap.py polls GitHub every 15-21 s, so the secondary rate limit sees well under 60
requests a minute from this tool.
"""
import argparse
import datetime
import glob
import hashlib
import json
import math
import os
import pathlib
import random
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


def checker_version():
    """Changes to capture, measurement or binding code invalidate saved proof."""
    h = hashlib.sha256()
    for p in (KIT/'tools/static_precheck.py', KIT/'tools/snap.py',
              KIT/'tools/storyboard.py', KIT.parent/'qa/gate.py'):
        h.update(str(p.relative_to(KIT.parent)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def proof_binding(sid):
    b = bindings(sid)
    # parts.json binds the exact hosted package; resolved.json and the source
    # hash additionally reject a changed build or story between the two steps.
    if not json.loads(b['parts_json']).get('sha256'):
        raise RuntimeError('No hosted package digest; saved proof cannot be reused')
    b['checker_version'] = checker_version()
    return hashlib.sha256(json.dumps(b, sort_keys=True).encode()).hexdigest()


def current_result(sid):
    """Reuse a complete proof only for the identical package AND checker.

    This avoids capturing the entire film again between precheck and submit.
    It never promotes an old report or substitutes for the encoded-master gate.
    """
    try:
        if storyboard.stale_build(sid):
            return None
        r = json.loads((KIT/'out'/sid/'static-precheck/result.json').read_text())
        if r.get('proof_binding') != proof_binding(sid):
            return None
        if not r.get('complete_grid') or r.get('backend') != 'public Ubuntu Actions':
            return None
        if r.get('source_hash') != storyboard.spec_hash(sid):
            return None
        if r.get('verdict') not in ('PASS', 'FAIL'):
            return None
        if (r.get('fps') != gate.STATIC_SAMPLE_FPS or r.get('width') != gate.STATIC_SAMPLE_WIDTH
                or r.get('threshold_pct') != gate.STATIC_DIFF_PCT_THRESHOLD
                or r.get('max_allowed_s') != gate.STATIC_MAX_SPAN['short']):
            return None
        if r.get('frames') != math.ceil(float(r['duration_s']) * gate.STATIC_SAMPLE_FPS - 1e-8):
            return None
        if r['verdict'] == 'PASS' and (r.get('bad_spans') or r['max_span_s'] > gate.STATIC_MAX_SPAN['short']):
            return None
        return dict(r, reused_current_proof=True)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None


def _gray_small(path):
    import numpy as np
    from PIL import Image
    with Image.open(path) as image:
        width = gate.STATIC_SAMPLE_WIDTH
        height = round(image.height * width / image.width / 2) * 2
        return np.asarray(image.convert('L').resize((width, height), Image.Resampling.BICUBIC))


def spans_from_diffs(diffs, threshold_pct=None, sample_fps=None):
    """gate.static_hold_spans' span loop on a ready-made list of frame-to-frame differences (diffs[j] = frames j -> j+1). Kept in step with
    the gate by test_static_split.py, which feeds both the same data."""
    threshold_pct = gate.STATIC_DIFF_PCT_THRESHOLD if threshold_pct is None else threshold_pct
    dt = 1.0 / (gate.STATIC_SAMPLE_FPS if sample_fps is None else sample_fps)
    spans, run_start = [], None
    for i, d in enumerate(diffs):
        t = i * dt
        if d < threshold_pct:
            if run_start is None:
                run_start = t
        else:
            if run_start is not None:
                spans.append((run_start, t, t - run_start))
                run_start = None
    if run_start is not None:
        end_t = len(diffs) * dt
        spans.append((run_start, end_t, end_t - run_start))
    return spans


def chunk_diffs(paths):
    """Frame-to-frame differences (gate metric) over one chunk's own frames, in time order."""
    import numpy as np
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        a = np.stack(list(pool.map(_gray_small, paths))).astype(np.int16)
    return [float(np.abs(a[i] - a[i - 1]).mean() / 255.0 * 100.0) for i in range(1, len(a))]


def summarise(diffs, frames):
    spans = spans_from_diffs(diffs)
    limit = gate.STATIC_MAX_SPAN['short']
    bad = [s for s in spans if s[2] > limit]
    return {
        'verdict': 'FAIL' if bad else 'PASS',
        'frames': frames,
        'fps': gate.STATIC_SAMPLE_FPS,
        'width': gate.STATIC_SAMPLE_WIDTH,
        'threshold_pct': gate.STATIC_DIFF_PCT_THRESHOLD,
        'max_allowed_s': limit,
        'max_span_s': max((s[2] for s in spans), default=0),
        'bad_spans': [{'start_s': s[0], 'end_s': s[1], 'duration_s': s[2]} for s in bad],
        'spans': [{'start_s': s[0], 'end_s': s[1], 'duration_s': s[2]} for s in spans],
        'diff_pct': {'min': min(diffs), 'median': sorted(diffs)[len(diffs)//2], 'max': max(diffs)},
    }


def measure_split(chunks, found, count):
    """Split-capture measurement: each chunk's transitions come from that chunk's own frames (one browser session), then the lists join."""
    diffs = []
    for ch in chunks:
        top = min(ch['hi'] + 1, count)          # frames lo..hi: chunk k owns the transitions lo->lo+1 ... hi-1->hi
        mine = []
        for idx in range(ch['lo'], top):
            hit = [c for c in found[idx] if c[0] == ch['k']]
            if not hit:
                raise RuntimeError('chunk %d lacks its own sample at %.2fs; capture is incomplete' % (ch['k'], idx / gate.STATIC_SAMPLE_FPS))
            mine.append(hit[0][1])
        diffs.extend(chunk_diffs(mine))
    if len(diffs) != count - 1:
        raise RuntimeError('split measurement produced %d transitions for %d frames' % (len(diffs), count))
    result = summarise(diffs, count)
    result['diffs'] = [round(d, 6) for d in diffs]
    return result


def measure(paths):
    import numpy as np
    from concurrent.futures import ThreadPoolExecutor
    # 13 Oct: decoding + bicubic-resizing ~580 full-size JPEGs one after another took 65-70 s on the loaded Mac (a fifth of the whole check).
    # Pillow releases the GIL in decode and resize, so 8 threads give the same arrays (same calls, same order of results) in a fraction of that.
    with ThreadPoolExecutor(max_workers=8) as pool:
        frames = list(pool.map(_gray_small, paths))
    spans, diffs = gate.static_hold_spans(np.stack(frames))
    limit = gate.STATIC_MAX_SPAN['short']
    bad = [s for s in spans if s[2] > limit]
    result = {
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
    result['diffs'] = [round(float(d), 6) for d in diffs]
    return result


OVERLAP_TOL_PCT = 0.25        # same metric as the gate (mean |a-b| / 255 * 100, 320 px grey). Seen between runners: 0.00-0.10. A gross-error trap, not a determinism claim
MIN_CHUNK_FRAMES = 60         # never split a short into slivers: the fixed runner start-up cost (~60 s) would dominate
FRAME_RE = re.compile(r'frame-(\d+)-at-([\d.]+)s\.jpg$')


def split_plan(count, n, overlap):
    """Contiguous primary ranges [lo, hi) that tile 0..count exactly, each widened by `overlap` frames on the sides that have a
    neighbour -> [{'k', 'lo', 'hi', 'a', 'b', 'sub'}]. n=1 (or a short too small to split) gives the single legacy call in out/<ID>/snap."""
    n = max(1, min(int(n), count // MIN_CHUNK_FRAMES or 1))
    if n == 1:
        return [{'k': 0, 'lo': 0, 'hi': count, 'a': 0, 'b': count, 'sub': 'snap'}]
    base, extra = divmod(count, n)
    chunks, lo = [], 0
    for k in range(n):
        hi = lo + base + (1 if k < extra else 0)
        chunks.append({'k': k, 'lo': lo, 'hi': hi, 'a': max(0, lo - overlap), 'b': min(count, hi + overlap), 'sub': 'snap-sp%d' % k})
        lo = hi
    return chunks


def hosted_free_slots():
    """The free plan runs 20 hosted jobs at once across the account (snap.py docstring). Count the queued + running workflow runs in the
    public repo -> how many more jobs can start now, or None if GitHub cannot be asked. Two read calls per static_precheck."""
    import snap
    busy = 0
    for status in ('in_progress', 'queued'):
        r = snap._gh(['run', 'list', '-R', snap.ACTIONS_REPO, '--status', status, '--limit', '100', '--json', 'databaseId'], check=False, timeout=60)
        if r.returncode:
            return None
        try:
            busy += len(json.loads(r.stdout or '[]'))
        except ValueError:
            return None
    return max(0, 20 - busy)


def _launch(sid, ch, fps, dest, env, tag=''):
    times = ','.join('%.2f' % (i / fps) for i in range(ch['a'], ch['b']))
    logp = dest / ('capture-%d%s.log' % (ch['k'], tag))
    fh = open(logp, 'w')
    pr = subprocess.Popen([sys.executable, str(KIT / 'tools/snap.py'), sid, '--at', times], cwd=KIT,
                          env=dict(env, AGMM_SNAP_DIR=ch['sub']), stdout=fh, stderr=subprocess.STDOUT, text=True)
    fh.close()
    return {'ch': ch, 'proc': pr, 'log': logp, 't0': time.time()}


def run_chunks(sid, chunks, fps, dest, env):
    """Start every chunk's snap.py, staggered; return when all have finished. Chunk 0 goes alone until it has dispatched its workflow
    (or died), so a brand-new package's release is created once, not raced by four callers. A chunk that fails for a reason other than
    GitHub throttling is retried once. Raises RuntimeError if any chunk still failed."""
    old_logs = sorted(dest.glob('capture-*.log'))
    if old_logs:   # an earlier run's chunk logs move aside (archive, never delete) so capture.log holds only this run
        prev = dest / ('prev-logs-%d' % int(time.time()))
        prev.mkdir(exist_ok=True)
        for f in old_logs:
            os.replace(f, prev / f.name)
    runs = [_launch(sid, chunks[0], fps, dest, env)]
    t_end = time.time() + 240
    while time.time() < t_end and runs[0]['proc'].poll() is None and 'actions run' not in runs[0]['log'].read_text(errors='replace'):
        time.sleep(1)
    if runs[0]['proc'].poll() not in (None, 0):
        raise RuntimeError('chunk 0 failed before dispatch; see %s' % runs[0]['log'])
    for ch in chunks[1:]:
        time.sleep(1.5 + random.random() * 2)   # about 20 dispatches a minute at most; polls are 15-21 s apart per call (snap.py)
        runs.append(_launch(sid, ch, fps, dest, env))
    for r in runs:
        r['rc'] = r['proc'].wait()
        r['wall'] = time.time() - r['t0']
    bad = [r for r in runs if r['rc']]
    for r in list(bad):
        text = r['log'].read_text(errors='replace').lower()
        if any(w in text for w in ('rate limit', 'secondary', 'abuse', 'http 403', 'http 429')):
            continue   # never hammer a throttled account
        if 'intake refused' in text or r['rc'] == 87:
            continue   # the Mac's disk floor, not the runner: dispatching the same frames again cannot help (the hosted run is retained)
        again = _launch(sid, r['ch'], fps, dest, env, '-retry')
        again['rc'], again['wall'] = again['proc'].wait(), None
        again['wall'] = time.time() - again['t0']
        if again['rc'] == 0:
            runs[runs.index(r)] = again
            bad.remove(r)
    if bad:
        raise RuntimeError('Actions capture failed in chunk(s) %s; see %s' % ([r['ch']['k'] for r in bad], dest))
    return runs


def overlap_diff_pct(path_a, path_b):
    """The gate's own frame-difference metric between two renders of the SAME instant."""
    a, b = _gray_small(path_a).astype('int16'), _gray_small(path_b).astype('int16')
    if a.shape != b.shape:
        return 100.0
    return float(abs(a - b).mean() / 255.0 * 100.0)


def collect_frames(root, chunks, offsets, fps, count, started):
    """Read every chunk's frames from root/<chunk sub>/<part>/frame-*-at-*s.jpg into ONE grid. Returns (selected idx->path, found idx->[(k, path, part)],
    overlap_checks [(idx, primary, extra, diff_pct)], worst or None). Raises RuntimeError on: an irregular time, a frame outside its chunk's
    range, a duplicate inside one chunk, a sample with no single owning chunk, a missing sample, or overlap frames that disagree beyond
    OVERLAP_TOL_PCT. Frames older than `started` (minus 1 s) are stale and ignored."""
    found = {}      # idx -> [(chunk k, path, part)]
    for ch in chunks:
        seen = set()
        for f in glob.glob(str(root/ch['sub']/'*/frame-*.jpg')):
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
            if not ch['a'] <= idx < ch['b']:
                raise RuntimeError('Frame %s is outside chunk %d range %.1f-%.1fs; capture is ambiguous' % (p, ch['k'], ch['a']/fps, ch['b']/fps))
            if idx in seen:
                raise RuntimeError('Duplicate sample at %.2fs; capture is ambiguous' % (idx/fps))
            seen.add(idx)
            found.setdefault(idx, []).append((ch['k'], p, p.parent.name))
    selected, overlap_checks, pairs = {}, [], []
    for idx, cands in found.items():
        primary = [c for c in cands if chunks[c[0]]['lo'] <= idx < chunks[c[0]]['hi']]
        if len(primary) != 1:
            raise RuntimeError('Sample at %.2fs has no single owning chunk; capture is ambiguous' % (idx/fps))
        selected[idx] = primary[0][1]
        for extra in (c for c in cands if c is not primary[0]):
            pairs.append((idx, primary[0], extra))
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        overlap_checks = [(i, p, e, d) for (i, p, e), d in zip(pairs, pool.map(lambda t: overlap_diff_pct(t[1][1], t[2][1]), pairs))]
    missing = sorted(set(range(count)) - set(selected))
    if missing:
        raise RuntimeError('Missing %d of %d required samples, first indices %s' % (len(missing), count, missing[:10]))
    worst = max(overlap_checks, key=lambda c: c[3], default=None)
    if worst and worst[3] > OVERLAP_TOL_PCT:
        raise RuntimeError('Runners disagree: the %.2fs frame rendered by chunk %d and chunk %d differs by %.3f%% (limit %.2f%%); '
                           'no verdict from split capture, re-run with AGMM_STATIC_SPLIT=1' % (worst[0]/fps, worst[1][0], worst[2][0], worst[3], OVERLAP_TOL_PCT))
    return selected, found, overlap_checks, worst


def capture(sid):
    why = storyboard.stale_build(sid)
    if why:
        raise RuntimeError(why)
    before = bindings(sid)
    proof_before = proof_binding(sid)
    parts = json.loads(before['parts_json'])['parts']
    duration = max(float(p['off']) + float(p['dur']) for p in parts)
    fps = gate.STATIC_SAMPLE_FPS
    count = math.ceil(duration * fps - 1e-8)
    times = ','.join('%.2f' % (i / fps) for i in range(count))
    started = time.time()
    # Explicitly no Codespaces or Mac fallback.
    env = dict(os.environ, AGMM_SNAP='actions')
    dest = KIT/'out'/sid/'static-precheck'
    dest.mkdir(exist_ok=True)
    want = int(os.environ.get('AGMM_STATIC_SPLIT', '8'))
    free = None
    if want > 1 and os.environ.get('AGMM_STATIC_ADAPT', '1') != '0':
        # a saturated account only queues the extra runners (and pays their ~60 s start-up each): take at most HALF of the free hosted slots,
        # so makers starting at the same moment (each sees the same free count) cannot together ask for more than the account has
        free = hosted_free_slots()
        if free is not None:
            want = max(1, min(want, free // 2))
    chunks = split_plan(count, want, int(os.environ.get('AGMM_STATIC_OVERLAP', '3')))
    # a leftover chunk folder from an earlier run must not be read as this run's frames (mtime would also exclude it)
    for ch in chunks:
        old = KIT/'out'/sid/ch['sub']
        if ch['sub'] != 'snap' and old.exists():
            old.rename(KIT/'out'/sid/('%s-prev-%d' % (ch['sub'], int(started))))
    if len(chunks) == 1:
        run = subprocess.run([sys.executable, str(KIT/'tools/snap.py'), sid, '--at', times],
                             cwd=KIT, env=env, capture_output=True, text=True)
        (dest/'capture.log').write_text(run.stdout + run.stderr)
        if run.returncode:
            raise RuntimeError('Actions capture failed rc%d; see %s' % (run.returncode, dest/'capture.log'))
        runs = []
    else:
        try:
            runs = run_chunks(sid, chunks, fps, dest, env)
        finally:
            (dest/'capture.log').write_text('\n'.join('===== %s =====\n%s' % (p.name, p.read_text(errors='replace'))
                                                      for p in sorted(dest.glob('capture-*.log'))))
    capture_wall = time.time() - started
    if bindings(sid) != before:
        raise RuntimeError('Source/package changed while Actions captured it; no result bound')
    offsets = {p['out']: float(p['off']) for p in parts}
    selected, found, overlap_checks, worst = collect_frames(KIT/'out'/sid, chunks, offsets, fps, count, started)
    if len(chunks) > 1:
        result = measure_split(chunks, found, count)
    else:
        result = measure([selected[i] for i in range(count)])
    if bindings(sid) != before:
        raise RuntimeError('Source/package changed during measurement; no result bound')
    if len(chunks) > 1:
        # downstream tools (frame check, sheet_check, better_than_last) read the merged grid from out/<ID>/snap/<part>/ exactly as after
        # a single call: same per-part frame-NN-at-Xs.jpg names, NN = position in the part. Overlap duplicates are kept under
        # static-precheck/overlap/ (archive, never delete). Chunk folders left empty are removed.
        by_part = {}
        for idx in range(count):
            by_part.setdefault(next(c[2] for c in found[idx] if c[1] == selected[idx]), []).append(idx)
        for part, idxs in by_part.items():
            (KIT/'out'/sid/'snap'/part).mkdir(parents=True, exist_ok=True)
            for nn, idx in enumerate(idxs):
                at = FRAME_RE.search(selected[idx].name).group(2)
                target = KIT/'out'/sid/'snap'/part/('frame-%02d-at-%ss.jpg' % (nn, at))
                os.replace(selected[idx], target)
                os.utime(target, None)
                selected[idx] = target
        for idx, cands in found.items():
            for k, p, part in cands:
                if p.exists():
                    keep = dest/'overlap'/('chunk%d' % k)/part
                    keep.mkdir(parents=True, exist_ok=True)
                    os.replace(p, keep/p.name)
        for ch in chunks:
            base = KIT/'out'/sid/ch['sub']
            for d in sorted(base.glob('*'), reverse=True) + [base]:
                try:
                    d.rmdir()
                except OSError:
                    pass
        result['capture'] = {
            'mode': 'parallel', 'chunks': len(chunks), 'overlap_frames': int(os.environ.get('AGMM_STATIC_OVERLAP', '3')),
            'ranges_s': [[ch['a']/fps, ch['b']/fps] for ch in chunks], 'wall_s': round(capture_wall, 1),
            'chunk_wall_s': [round(r['wall'], 1) for r in runs],
            'overlap_pairs_compared': len(overlap_checks), 'overlap_worst_diff_pct': round(worst[3], 4) if worst else None,
            'overlap_tolerance_pct': OVERLAP_TOL_PCT, 'hosted_free_slots': free}
    else:
        result['capture'] = {'mode': 'single', 'chunks': 1, 'wall_s': round(capture_wall, 1), 'hosted_free_slots': free}
    result.update(id=sid, at=datetime.datetime.now().astimezone().isoformat(),
                  source_hash=before['source_hash'], package_sha256=json.loads(before['parts_json']).get('sha256'),
                  backend='public Ubuntu Actions', duration_s=duration, complete_grid=True,
                  capture_started_epoch=started, capture_log=str(dest/'capture.log'),
                  scope='pre-render source snapshots; encoded master gate and perception still required',
                  limitations=['JPEG/Pillow sampling differs from encoded ffmpeg frames; final check3 remains required',
                               'No static exceptions are excused by this source check'])
    if proof_binding(sid) != proof_before:
        raise RuntimeError('Source/package/checker changed during capture; no reusable proof written')
    result['proof_binding'] = proof_before
    (dest/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('id')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--reuse-current', action='store_true', help='Reuse only a complete identical-package and identical-checker proof')
    args = ap.parse_args()
    if not re.fullmatch(r'[A-Z]\d{2,3}', args.id):
        ap.error('Expected a short ID')
    try:
        result = current_result(args.id) if args.reuse_current else None
        if result is None:
            result = capture(args.id)
        elif not args.json:
            print('static_precheck: reused complete current package/checker proof from %s' % result['at'])
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
