#!/usr/bin/env python3
"""Select candidate voices on Ubuntu using the existing free-voice ranking.

This returns takes for the native voice checker, never a release approval.
"""
import hashlib
import json
from pathlib import Path
import shutil


def choose(candidates, text, allow_slow=False):
    short = len(text.split()) <= 12
    target = 140.0 if short else 168.0
    fast_max = 220.0 if allow_slow else (195.0 if short else 185.0)
    good = [c for c in candidates if c.get('asr_match') is True and c.get('span_wpm')
            and c['span_wpm'] <= fast_max and (allow_slow or short or c['span_wpm'] >= 158.0)]
    if not allow_slow:
        good = [c for c in good if c.get('native_ratio') is None or c['native_ratio'] >= 0.985]
        return min(good, key=lambda c: abs(c['span_wpm'] - target)) if good else None
    return max(good, key=lambda c: (round(c.get('native_ratio') if c.get('native_ratio') is not None else 1.0, 2),
                                    -abs(c['span_wpm'] - target))) if good else None


def select(packs, paragraphs, destination):
    """Only source-bound takes; first pass then fallback after all rounds."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError('destination must be fresh')
    plans = {}
    for key, text in paragraphs.items():
        candidates = []
        for pack in packs:
            for receipt_path in sorted(Path(pack).glob(key + '.t*.receipt.json')):
                rec = json.loads(receipt_path.read_text())
                stem = receipt_path.name[:-len('.receipt.json')]
                wav = receipt_path.with_name(stem + '.wav')
                words = receipt_path.with_name(stem + '.words.json')
                if not wav.is_file() or not words.is_file():
                    continue
                if rec.get('input_sha256') != hashlib.sha256(text.encode()).hexdigest():
                    raise ValueError('take text binding differs')
                h = hashlib.sha256()
                with wav.open('rb') as f:
                    for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
                if h.hexdigest() != rec.get('wav_sha256'):
                    raise ValueError('take bytes differ from receipt')
                json.loads(words.read_text())
                candidates.append({'asr_match': rec.get('asr_match') is True, 'span_wpm': rec.get('span_wpm'),
                                   'native_ratio': rec.get('native_ratio'), 'wav': wav, 'words': words,
                                   'receipt': receipt_path, 'sha256': h.hexdigest()})
        best = choose(candidates, text) or choose(candidates, text, allow_slow=True)
        if not best:
            raise ValueError('no qualifying take for ' + key)
        plans[key] = best
    destination.mkdir(parents=True)
    rows = []
    for key, best in plans.items():
        for field, suffix in [('wav', '.wav'), ('words', '.words.json'), ('receipt', '.receipt.json')]:
            target = destination / (key + suffix)
            shutil.copyfile(best[field], target)
        # Match the existing api_queue.cmd_install free-take receipt exactly.
        receipt_path = destination / (key + '.receipt.json')
        receipt = json.loads(receipt_path.read_text())
        if receipt.get('free_engine') is not True:
            raise ValueError('selected take is not free-engine')
        receipt['paragraph'] = key
        receipt['revoiced_by'] = 'api_queue.py 20 Oct 2026 free ' + str(receipt.get('engine'))
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        files = {}
        for suffix in ('.wav', '.words.json', '.receipt.json'):
            path = destination / (key + suffix)
            data = path.read_bytes()
            files[key + suffix] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        rows.append({'paragraph': key, 'files': files, 'span_wpm': best['span_wpm'],
                     'native_ratio': best['native_ratio']})
    (destination / 'SELECTION.json').write_text(json.dumps({'status': 'SELECTED_REQUIRES_NATIVE_VOICE_CHECK',
        'release_approval': False, 'rows': rows}, indent=2) + '\n')
    return rows


def run_hosted(request, private, work):
    import os, re, subprocess, sys, tarfile, zipfile
    if not sys.platform.startswith('linux') or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Ubuntu Actions required')
    sid = request.get('id', '')
    if not re.fullmatch(r'S[0-9]+', sid) or not (1 <= len(request.get('runs', [])) <= 2):
        raise ValueError('invalid source request')
    if not os.environ.get('VOICEFREE_PASS'):
        raise ValueError('encryption key missing')
    def gh(path):
        return json.loads(subprocess.check_output(['gh','api',path]))
    work = Path(work)
    work.mkdir(parents=True, exist_ok=False)
    paras, packs = {}, []
    for idx, source in enumerate(request['runs']):
        tag, run_id = source['tag'], str(source['run_id'])
        if not re.fullmatch(r'S[0-9]+-r[12]-chatterbox-[0-9]+', tag) or not tag.startswith(sid + '-r') or not run_id.isdigit():
            raise ValueError('invalid source tag or run')
        req = json.loads((Path(private) / 'voice-free/req' / tag / 'request.json').read_text())
        if req.get('id') != sid or req.get('label') != tag:
            raise ValueError('private source request mismatch')
        for entry in req.get('paragraphs', []):
            key, text = entry.get('key'), entry.get('text')
            if not isinstance(key, str) or not re.fullmatch(r'P[0-9]{2}', key) or not isinstance(text, str) or not text:
                raise ValueError('invalid paragraph')
            if key in paras and paras[key] != text:
                raise ValueError('rounds differ in paragraph text')
            paras[key] = text
        run = gh('repos/agmmltd-arch/agmm-render-public/actions/runs/' + run_id)
        if (str(run.get('id')) != run_id or run.get('path') != '.github/workflows/voicefree-chatterbox.yml'
                or run.get('status') != 'completed' or run.get('conclusion') != 'success'
                or run.get('event') != 'workflow_dispatch' or run.get('run_attempt') != 1):
            raise ValueError('source run not qualified')
        artifacts = gh('repos/agmmltd-arch/agmm-render-public/actions/runs/' + run_id + '/artifacts')['artifacts']
        matches = [a for a in artifacts if a.get('name') == 'voicefree-chatterbox-' + tag + '-ENC' and not a.get('expired')]
        if len(matches) != 1 or not re.fullmatch(r'sha256:[0-9a-f]{64}', matches[0].get('digest') or ''):
            raise ValueError('source artifact unavailable or ambiguous')
        art = matches[0]; zip_path = work / ('artifact%d.zip' % idx)
        with zip_path.open('xb') as stream:
            subprocess.run(['gh','api','repos/agmmltd-arch/agmm-render-public/actions/artifacts/%s/zip' % art['id']],stdout=stream,check=True)
        h = hashlib.sha256()
        with zip_path.open('rb') as f:
            for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
        if 'sha256:' + h.hexdigest() != art['digest']:
            raise ValueError('source artifact digest mismatch')
        enc = work / ('pack%d.enc' % idx)
        with zipfile.ZipFile(zip_path) as z:
            members = [x for x in z.infolist() if not x.is_dir()]
            if len(members) != 1 or not members[0].filename.endswith('.enc') or members[0].file_size > 1_000_000_000:
                raise ValueError('invalid encrypted artifact')
            with z.open(members[0]) as src, enc.open('xb') as dst: shutil.copyfileobj(src,dst)
        plain = work / ('pack%d.tar' % idx)
        with plain.open('xb') as out:
            subprocess.run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-pass','env:VOICEFREE_PASS','-in',str(enc)],stdout=out,check=True)
        pack = work / ('pack%d' % idx);pack.mkdir()
        with tarfile.open(plain,'r:') as t:
            members = [m for m in t.getmembers() if m.isfile()]
            if sum(m.size for m in members) > 2_000_000_000:
                raise ValueError('take pack too large')
            seen = set()
            for m in members:
                name = m.name.removeprefix('./')
                if not re.fullmatch(r'(?:results\.json|P[0-9]{2}\.t[0-9]+\.(?:wav|words\.json|receipt\.json))',name) or name in seen:
                    raise ValueError('unexpected take pack file')
                seen.add(name)
                with t.extractfile(m) as src,(pack/name).open('xb') as dst: shutil.copyfileobj(src,dst)
        reference = str(req.get('ref') or '')
        if not reference.startswith('voice-free/ref/') or '..' in Path(reference).parts:
            raise ValueError('invalid reference path')
        ref_file = Path(private) / reference
        if not ref_file.is_file():
            raise ValueError('reference missing')
        rh = hashlib.sha256()
        with ref_file.open('rb') as f:
            for b in iter(lambda: f.read(1024*1024), b''): rh.update(b)
        result = json.loads((pack/'results.json').read_text())
        if result.get('id') != sid or result.get('label') != tag or result.get('reference_sha256') != rh.hexdigest():
            raise ValueError('source result provenance mismatch')
        for path in pack.glob('P*.receipt.json'):
            rec = json.loads(path.read_text())
            if (rec.get('free_engine') is not True or rec.get('engine') != 'chatterbox'
                    or rec.get('reference_sha256') != rh.hexdigest() or rec.get('asr_status') != 'checked'
                    or str((rec.get('run') or {}).get('id')) != run_id
                    or (rec.get('run') or {}).get('sha') != run.get('head_sha')):
                raise ValueError('take producer provenance mismatch')
        packs.append(pack)
    if not paras:
        raise ValueError('no source paragraphs')
    select(packs,paras,work/'selected')
    manifest = json.loads((work/'selected'/'SELECTION.json').read_text())
    manifest.update({'schema': 'agmm-hosted-selected-takes-v1', 'id': sid,
                     'private_commit': request['private_commit'], 'sources': request['runs'],
                     'selector_run_id': os.environ['GITHUB_RUN_ID'],
                     'selector_commit': os.environ['GITHUB_SHA']})
    (work/'selected'/'SELECTION.json').write_text(json.dumps(manifest, indent=2) + '\n')
    # Metadata has hashes and provenance only: no source text or audio.
    (work/'selection-metadata.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    import sys
    run_hosted(json.loads(Path(sys.argv[1]).read_text()),sys.argv[2],sys.argv[3])
