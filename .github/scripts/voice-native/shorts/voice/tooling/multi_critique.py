#!/usr/bin/env python3
"""Run N independent fresh Gemini listening passes (same prompt) on a piece's blackframe mp4
and average the numeric scores. Writes <name>.gemini-critique-<label>-runN.json per run and
<name>.gemini-critique-<label>-avg.json with the average + all raw runs.
Usage: multi_critique.py <piece_dir> <name> <label> <n_runs> [--film]
"""
import json, subprocess, sys, time
from pathlib import Path

def main():
    piece_dir = Path(sys.argv[1]).resolve()
    name = sys.argv[2]
    label = sys.argv[3]
    n = int(sys.argv[4])
    is_film = '--film' in sys.argv

    receipt = json.loads((piece_dir / f'{name}.receipt.json').read_text())
    lo, hi = receipt['target_wpm_range']
    register = 'calm journalistic (measured, investigative, not hyped)' if is_film \
        else 'urgent/insider energy (0x100x register)'
    target_desc = f'{lo}-{hi} wpm, {register}'
    prompt_template = (Path(__file__).resolve().parent / 'critique_prompt.txt').read_text()
    names_file = piece_dir / 'names.txt'
    names_list = ', '.join(l.strip() for l in names_file.read_text().splitlines() if l.strip()) if names_file.exists() else 'any proper nouns in the script'
    prompt = prompt_template.replace('TARGET_WPM_DESC', target_desc).replace('NAMES_LIST', names_list)

    mp4 = piece_dir / f'{name}.blackframe.mp4'
    gemini_watch = Path(__file__).resolve().parents[3] / 'tooling' / 'gemini_watch.py'

    runs = []
    i = 1
    while i <= n:
        out_txt = piece_dir / f'{name}.gemini-critique-{label}-run{i}.json'
        if out_txt.exists():
            try:
                data = json.loads(out_txt.read_text())
                if isinstance(data.get('naturalness_score'), (int, float)):
                    runs.append(data)
                    print(f'run {i}: (cached)', {k: data.get(k) for k in ('naturalness_score', 'flow_score', 'pace_score', 'emphasis_score', 'robotic_cadence')}, flush=True)
                    i += 1
                    continue
            except Exception:
                pass
        ok = False
        for attempt in range(6):
            cmd = ['python3', str(gemini_watch), str(mp4), prompt, '--json', '--out', str(out_txt)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                ok = True
                break
            if '429' in r.stderr or 'RESOURCE_EXHAUSTED' in r.stderr:
                wait = 20 * (attempt + 1)
                print(f'run {i} rate-limited, backing off {wait}s (attempt {attempt+1})', flush=True)
                time.sleep(wait)
                continue
            print(f'run {i} FAILED (non-429):', r.stderr[-500:], flush=True)
            break
        if not ok:
            print(f'run {i} giving up after retries', flush=True)
            i += 1
            continue
        try:
            data = json.loads(out_txt.read_text())
        except Exception as e:
            print(f'run {i} parse failed:', e, flush=True)
            i += 1
            continue
        runs.append(data)
        print(f'run {i}:', {k: data.get(k) for k in ('naturalness_score', 'flow_score', 'pace_score', 'emphasis_score', 'robotic_cadence')}, flush=True)
        i += 1
        time.sleep(8)

    keys = ['naturalness_score', 'flow_score', 'pace_score', 'emphasis_score']
    avg = {}
    for k in keys:
        vals = [r[k] for r in runs if isinstance(r.get(k), (int, float))]
        avg[k] = round(sum(vals) / len(vals), 2) if vals else None
    robotic_votes = [bool(r.get('robotic_cadence')) for r in runs]
    avg['robotic_cadence_votes'] = robotic_votes
    avg['n_runs'] = len(runs)
    avg['label'] = label
    avg['raw_runs'] = runs

    out_avg = piece_dir / f'{name}.gemini-critique-{label}-avg.json'
    out_avg.write_text(json.dumps(avg, indent=2))
    print('AVERAGE:', json.dumps({k: avg[k] for k in keys + ['n_runs']}, indent=2))

if __name__ == '__main__':
    main()
