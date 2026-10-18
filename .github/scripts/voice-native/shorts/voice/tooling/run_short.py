#!/usr/bin/env python3
"""Orchestrate one short end to end: paragraph TTS+ASR, assemble, whole-file ASR, 3-pass
Gemini critique (regenerate up to 3 total attempts if naturalness/emphasis avg < 8), isolated
name-pronunciation check, word-timing spot-check. Resumable at every step (checks for existing
output before redoing work) so a crash/quota-stall can be re-run without re-spending quota on
work already done. Writes voice/<ID>/RESULT.json.
Usage: run_short.py <voice_dir> <ID> [--from-existing]
--from-existing (13 Oct 2026): the paragraph takes were generated elsewhere (the Voxtral WEB demo, Mistral API = 402) and ingested by
films/voice/tooling/ingest_web_takes.py + check_web_takes.py. No TTS, no Mistral/Gemini API: asserts every receipt passed the local ASR check
and the receipts match paragraphs.txt, assembles (165-172 wpm, no --film), then runs films/voice/tooling/post_checks_local.py (local whisper
whole-file ASR, timing, gaps, names, loudness, spot check) which writes RESULT.json (FINISHED_LOCAL_CHECKS_PASS, listening UNJUDGED).
voice_lead_check.py reads that status in its LOCAL MODE. Run it through kit/tools/heavy.py.
"""
import hashlib, json, shutil, subprocess, sys, time
from pathlib import Path

TOOLING = Path(__file__).resolve().parent
LO, HI = 165.0, 172.0
BAR = 6.5  # Flash-calibrated 24 Sep: Sam-approved pilot voices score 4.7-7.7 under gemini-2.5-flash (8-9 under pro)

def sh(cmd, **kw):
    print('+', ' '.join(cmd), flush=True)
    r = subprocess.run(cmd, **kw)
    return r

def run_ok(cmd, log):
    with open(log, 'a') as f:
        f.write('\n+ ' + ' '.join(cmd) + '\n')
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        f.write(r.stdout)
    print(r.stdout[-1500:], flush=True)
    return r.returncode == 0, r.stdout

def gen_and_assemble(piece_dir, sid, log):
    ok, out = run_ok(['python3', str(TOOLING / 'gen_paragraphs.py'), str(piece_dir)], log)
    if not ok:
        return False, 'gen_paragraphs failed: ' + out[-800:]
    ok, out = run_ok(['python3', str(TOOLING / 'assemble.py'), str(piece_dir), sid, str(LO), str(HI)], log)
    if not ok:
        return False, 'assemble failed: ' + out[-800:]
    return True, out

def clear_paragraph_takes(piece_dir):
    for p in piece_dir.glob('P??.wav'):
        p.unlink()
    for p in piece_dir.glob('P??.receipt.json'):
        p.unlink()
    for p in piece_dir.glob('P??.words.json'):
        p.unlink()

def main_existing(voice_dir, sid):
    piece_dir = voice_dir / sid
    log = piece_dir / 'run.log'
    rcs = sorted(piece_dir.glob('P??.receipt.json'))
    paras = [p for p in piece_dir.joinpath('paragraphs.txt').read_text(encoding='utf-8').strip().split('\n\n') if p.strip()]
    assert len(rcs) == len(paras), f'{len(rcs)} receipts for {len(paras)} paragraphs'
    for i, (rc, text) in enumerate(zip(rcs, paras), 1):
        r = json.loads(rc.read_text())
        assert rc.name[:3] == f'P{i:02d}', f'receipt sequence broken at {rc.name}'
        assert r.get('input_sha256') == hashlib.sha256(text.strip().encode()).hexdigest(), f'{rc.name} text sha does not match paragraphs.txt'
    bad = [r.name[:3] for r in rcs if not json.loads(r.read_text()).get('asr_match')]
    assert not bad, f'takes failing the ASR check, regenerate first: {bad}'
    ok, out = run_ok(['python3', str(TOOLING / 'assemble.py'), str(piece_dir), sid, str(LO), str(HI)], log)
    assert ok, 'assemble failed: ' + out[-800:]
    films_tool = TOOLING.parent.parent.parent / 'films' / 'voice' / 'tooling' / 'post_checks_local.py'
    py = Path.home() / 'alfred/yt-engine/.venv/bin/python'
    ok, out = run_ok([str(py), str(films_tool), str(piece_dir), sid, '--band', str(LO), str(HI)], log)
    print('post_checks_local exit ok =', ok)
    return 0 if ok else 1

def main():
    voice_dir = Path(sys.argv[1]).resolve()
    sid = sys.argv[2]
    if '--from-existing' in sys.argv:
        sys.exit(main_existing(voice_dir, sid))
    piece_dir = voice_dir / sid
    log = piece_dir / 'run.log'
    assert (piece_dir / 'paragraphs.txt').exists(), f'{piece_dir}: run prepare.py first'

    result_path = piece_dir / 'RESULT.json'
    if result_path.exists():
        prev = json.loads(result_path.read_text())
        if prev.get('status') == 'FINISHED':
            print(sid, 'already FINISHED, skipping'); print(json.dumps(prev, indent=2)); return

    attempts = []
    final_avg = None
    attempt_n = 0
    while attempt_n < 3:
        attempt_n += 1
        label = f'pass{attempt_n}'
        ok, msg = gen_and_assemble(piece_dir, sid, log)
        if not ok:
            attempts.append({'attempt': attempt_n, 'stage': 'gen_or_assemble', 'error': msg[-500:]})
            time.sleep(5)
            continue
        ok, out = run_ok(['python3', str(TOOLING / 'whole_file_asr.py'), str(piece_dir), sid], log)
        receipt = json.loads((piece_dir / f'{sid}.receipt.json').read_text())
        full_asr = receipt.get('full_file_asr', {})

        avg_path = piece_dir / f'{sid}.gemini-critique-{label}-avg.json'
        if not (avg_path.exists() and json.loads(avg_path.read_text()).get('n_runs', 0) >= 3):
            ok, out = run_ok(['python3', str(TOOLING / 'multi_critique.py'), str(piece_dir), sid, label, '3'], log)
        avg = json.loads(avg_path.read_text()) if avg_path.exists() else {}
        nat = avg.get('naturalness_score')
        emph = avg.get('emphasis_score')
        clears = (nat is not None and emph is not None and nat >= BAR and emph >= BAR)
        attempts.append({
            'attempt': attempt_n, 'label': label,
            'wpm_speaking_final': receipt.get('wpm_speaking_final'),
            'lufs_i_post': (receipt.get('loudnorm_measured_post') or {}).get('output_i'),
            'full_asr_match': full_asr.get('match'),
            'naturalness': nat, 'flow': avg.get('flow_score'), 'pace': avg.get('pace_score'),
            'emphasis': emph, 'robotic_votes': avg.get('robotic_cadence_votes'),
            'clears_bar': clears,
        })
        final_avg = avg
        # keep every take so the BEST one survives (root fix, 24 Sep: the last take used to win even when worse)
        take = piece_dir / f'take-{label}'
        take.mkdir(exist_ok=True)
        for suf in ('.wav', '.words.json', '.receipt.json'):
            src = piece_dir / f'{sid}{suf}'
            if src.exists():
                shutil.copy2(src, take / f'{sid}{suf}')
        attempts[-1]['take_dir'] = str(take)
        if clears:
            break
        if attempt_n < 3:
            print(sid, f'attempt {attempt_n} below bar (nat={nat}, emph={emph}), regenerating paragraph takes', flush=True)
            clear_paragraph_takes(piece_dir)
            time.sleep(3)

    # restore the best take (highest naturalness + emphasis) before the name check and spot-check
    scored = [x for x in attempts if x.get('naturalness') is not None and x.get('take_dir')]
    if scored:
        best = max(scored, key=lambda x: (x['naturalness'] or 0) + (x['emphasis'] or 0))
        for suf in ('.wav', '.words.json', '.receipt.json'):
            src = Path(best['take_dir']) / f'{sid}{suf}'
            if src.exists():
                shutil.copy2(src, piece_dir / f'{sid}{suf}')
        for x in attempts:
            x['selected'] = (x is best)
    # name pronunciation check (on the selected best take)
    ok, out = run_ok(['python3', str(TOOLING / 'name_check.py'), str(piece_dir), sid], log)
    namecheck = json.loads((piece_dir / f'{sid}.namecheck.json').read_text()) if (piece_dir / f'{sid}.namecheck.json').exists() else {}

    # word-timing spot-check (10 words)
    r = subprocess.run(['python3', str(TOOLING / 'spotcheck_words.py'), str(piece_dir), sid, '10'],
                        capture_output=True, text=True)
    (piece_dir / f'{sid}.spotcheck.txt').write_text(r.stdout)
    spotcheck_ok = (r.returncode == 0)

    receipt = json.loads((piece_dir / f'{sid}.receipt.json').read_text())
    last = next((x for x in attempts if x.get('selected')), attempts[-1] if attempts else {})
    status = 'FINISHED' if last.get('clears_bar') else 'FINISHED_BELOW_BAR'
    result = {
        'id': sid, 'status': status, 'n_attempts': len(attempts), 'attempts': attempts,
        'final': last, 'namecheck_summary': {
            'expected': namecheck.get('names_expected'),
            'found_in_audio': namecheck.get('names_found_in_audio'),
            'missing_from_audio': namecheck.get('names_missing_from_audio'),
            'verdicts': namecheck.get('gemini_verdicts'),
        },
        'spotcheck_words_ok': spotcheck_ok,
        'wav_path': str(piece_dir / f'{sid}.wav'),
        'words_json_path': str(piece_dir / f'{sid}.words.json'),
        'receipt_path': str(piece_dir / f'{sid}.receipt.json'),
        'wpm_final': receipt.get('wpm_speaking_final'),
        'lufs_final': (receipt.get('loudnorm_measured_post') or {}).get('output_i'),
        'full_asr_match': (receipt.get('full_file_asr') or {}).get('match'),
    }
    result_path.write_text(json.dumps(result, indent=2))
    print('RESULT', sid, status)
    print(json.dumps(result, indent=2)[:3000])

if __name__ == '__main__':
    main()
