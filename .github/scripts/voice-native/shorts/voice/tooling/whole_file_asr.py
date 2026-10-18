#!/usr/bin/env python3
"""Whole-file ASR exact-match check on an assembled final voice file (no Gemini call --
multi_critique.py handles the 3-pass listening critique separately to avoid a redundant call).
Usage: whole_file_asr.py <piece_dir> <name>
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_paragraphs import env_key, transcribe_words
from asr_compare import compare

def main():
    piece_dir = Path(sys.argv[1]).resolve()
    name = sys.argv[2]
    wav = piece_dir / f'{name}.wav'
    receipt_path = piece_dir / f'{name}.receipt.json'
    receipt = json.loads(receipt_path.read_text())
    expected = receipt['full_script_text']
    key = env_key()
    raw = wav.read_bytes()
    status, headers, resp = transcribe_words(key, raw, wav.name)
    asr_text = resp.get('text', '')
    match, detail = compare(expected, asr_text)
    receipt['full_file_asr'] = {
        'asr_http_status': status, 'asr_text': asr_text, 'match': match, 'detail': detail,
        'model': 'voxtral-mini-latest',
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    print('FULL ASR MATCH:', match)
    if not match:
        print('DETAIL:', json.dumps(detail, indent=2)[:3000])

if __name__ == '__main__':
    main()
