#!/usr/bin/env python3
"""Generate paragraph-by-paragraph Sam-voice TTS (Mistral voxtral-mini-tts-2603) for one
pilot piece, with per-paragraph ASR word-timing check. Resumable: skips a paragraph whose
wav+receipt+words already exist and verify. No key or reference bytes are written out.

Usage: gen_paragraphs.py <piece_dir>   (piece_dir contains paragraphs.txt, one paragraph per
blank-line-separated block; outputs PNN.wav / PNN.receipt.json / PNN.words.json there)
"""
import base64, datetime as dt, hashlib, json, re, sys, time, wave, io
import urllib.error, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from asr_compare import compare as asr_value_compare

REF = Path('/Users/samwall/alfred/builds/video-program-2026-09-23/v2/shorts/voice/ref/sam-reference-20260905T152059Z-cdf499.wav')
REF_SHA = '3df9d7568c0b0569887e6c9f39bd35835cda305a09d288ea535c63d9cdc15443'

def sha(b):
    return hashlib.sha256(b).hexdigest()

def env_key():
    for line in Path('/Users/samwall/alfred/.env').read_text().splitlines():
        if line.startswith('MISTRAL_KEY='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    raise RuntimeError('MISTRAL_KEY absent')

def _with_retry(fn, retries=5):
    for attempt in range(retries):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                wait = 8 * (attempt + 1)
                print('  HTTP', e.code, '- backing off', wait, 's', flush=True)
                time.sleep(wait)
                continue
            raise

def call_json(url, key, obj, timeout=180):
    def _do():
        req = urllib.request.Request(url, data=json.dumps(obj).encode(), headers={
            'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, dict(res.headers.items()), json.load(res)
    return _with_retry(_do)

def transcribe_words(key, raw, name):
    boundary = 'v2pilot' + sha(raw)[:16]
    body = bytearray()
    def field(fname, value, filename=None, mime=None):
        body.extend(f'--{boundary}\r\n'.encode())
        cd = f'Content-Disposition: form-data; name="{fname}"'
        if filename: cd += f'; filename="{filename}"'
        body.extend((cd + '\r\n').encode())
        if mime: body.extend(f'Content-Type: {mime}\r\n'.encode())
        body.extend(b'\r\n' + value + b'\r\n')
    field('model', b'voxtral-mini-latest')
    field('timestamp_granularities', b'word')
    field('file', raw, name, 'audio/wav')
    body.extend(f'--{boundary}--\r\n'.encode())
    def _do():
        req = urllib.request.Request('https://api.mistral.ai/v1/audio/transcriptions', data=bytes(body), headers={
            'Authorization': 'Bearer ' + key, 'Content-Type': 'multipart/form-data; boundary=' + boundary}, method='POST')
        with urllib.request.urlopen(req, timeout=180) as res:
            return res.status, dict(res.headers.items()), json.load(res)
    return _with_retry(_do)

def norm_words(s):
    s = s.lower()
    s = s.replace('builder.ai', 'builder ai')
    return re.findall(r"[a-z0-9']+", s)

def main():
    piece_dir = Path(sys.argv[1]).resolve()
    raw = piece_dir.joinpath('paragraphs.txt').read_text(encoding='utf-8')
    paragraphs = [p.strip() for p in raw.strip().split('\n\n') if p.strip()]
    ref = REF.read_bytes()
    assert sha(ref) == REF_SHA, 'reference hash mismatch'
    key = env_key()
    n_regen = 0
    for i, text in enumerate(paragraphs, 1):
        stem = f'P{i:02d}'
        wav_path = piece_dir / f'{stem}.wav'
        receipt_path = piece_dir / f'{stem}.receipt.json'
        words_path = piece_dir / f'{stem}.words.json'
        if wav_path.exists() and receipt_path.exists() and words_path.exists():
            try:
                old = json.loads(receipt_path.read_text())
                if old.get('input_sha256') == sha(text.encode()) and old.get('wav_sha256') == sha(wav_path.read_bytes()) \
                   and old.get('asr_status') == 'checked' and old.get('asr_match') is True:
                    print(stem, 'already verified, skipped', flush=True)
                    continue
            except Exception:
                pass
        attempt = 0
        while True:
            attempt += 1
            status, headers, data = call_json('https://api.mistral.ai/v1/audio/speech', key, {
                'model': 'voxtral-mini-tts-2603', 'input': text,
                'ref_audio': base64.b64encode(ref).decode(), 'response_format': 'wav', 'stream': False})
            wav_raw = base64.b64decode(data['audio_data'])
            with wave.open(io.BytesIO(wav_raw)) as f:
                info = {'channels': f.getnchannels(), 'rate': f.getframerate(), 'width': f.getsampwidth(),
                        'frames': f.getnframes(), 'duration_s': round(f.getnframes() / f.getframerate(), 6)}
            assert (info['channels'], info['rate'], info['width']) == (1, 24000, 2), info
            item = {
                'paragraph': stem, 'text': text, 'input_sha256': sha(text.encode()),
                'reference_sha256_only': REF_SHA, 'model': 'voxtral-mini-tts-2603',
                'tts_http_status': status, 'tts_request_id': headers.get('x-request-id'),
                'wav_sha256': sha(wav_raw), 'wav_bytes': len(wav_raw), 'wav_info': info,
                'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                'attempt': attempt, 'asr_status': 'pending',
                'wpm': round(len(text.split()) / (info['duration_s'] / 60.0), 1),
            }
            try:
                asr_status, asr_headers, resp = transcribe_words(key, wav_raw, wav_path.name)
                asr_text = resp.get('text', '')
                match, cmp_detail = asr_value_compare(text, asr_text)
                item.update({
                    'asr_status': 'checked', 'asr_http_status': asr_status,
                    'asr_request_id': asr_headers.get('x-request-id'),
                    'asr_text': asr_text, 'asr_match': match, 'asr_compare_detail': cmp_detail,
                })
            except Exception as e:
                item.update({'asr_status': 'error', 'asr_error_type': type(e).__name__, 'asr_error': str(e)[:300]})
                match = None
                resp = {}
            if item['asr_status'] == 'checked' and not match and attempt < 3:
                print(stem, 'ASR mismatch (', item['asr_compare_detail'].get('reason'), '), regenerating (attempt', attempt, ')', flush=True)
                n_regen += 1
                time.sleep(2)
                continue
            if item['asr_status'] == 'checked' and not match and attempt >= 3:
                item['asr_residual_mismatch'] = True
                print(stem, 'WARNING: ASR still mismatched after 3 attempts, keeping last take for Gemini listening review:', item['asr_compare_detail'], flush=True)
            wav_path.write_bytes(wav_raw)
            words_path.write_text(json.dumps(resp, indent=2, ensure_ascii=False) + '\n')
            receipt_path.write_text(json.dumps(item, indent=2) + '\n')
            print(stem, 'duration', info['duration_s'], 'wpm', item['wpm'], 'ASR', item['asr_status'],
                  'match', item.get('asr_match'), flush=True)
            break
        time.sleep(1.5)
    print('done,', len(paragraphs), 'paragraphs,', n_regen, 'regenerations', flush=True)

if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as e:
        print('Mistral HTTP', e.code, e.read()[:400], flush=True)
        raise SystemExit(1)
