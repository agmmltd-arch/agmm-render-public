#!/usr/bin/env python3
"""Isolated-clip pronunciation check for every proper noun in a short (per PRODUCTION-RULES.md:
whole-file critique flip-flops on name pronunciation between runs -- see pilot VOICE-QA.md --
so every name gets its own short clip cut from the FINAL delivered wav and a dedicated Gemini
listen, batched into one call per piece to save quota).
Usage: name_check.py <piece_dir> <name>   (piece_dir/names.txt: one name/phrase per line)
Writes <piece_dir>/<name>.namecheck.json
"""
import json, re, subprocess, sys, wave
from pathlib import Path

NICE = ['nice', '-n', '15']

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\n{r.stderr}")
    return r.stdout, r.stderr

def norm(s):
    return re.findall(r"[a-z0-9']+", s.lower())

def find_span(words, phrase_tokens):
    """First matching consecutive run of words[i].word (normalised) == phrase_tokens."""
    n = len(phrase_tokens)
    for i in range(len(words) - n + 1):
        ok = True
        for k in range(n):
            wtoks = norm(words[i + k]['word'])
            if not wtoks or wtoks[0] != phrase_tokens[k]:
                ok = False
                break
        if ok:
            return i, i + n - 1
    return None

def main():
    piece_dir = Path(sys.argv[1]).resolve()
    name = sys.argv[2]
    wav = piece_dir / f'{name}.wav'
    names_file = piece_dir / 'names.txt'
    if not names_file.exists():
        print('no names.txt, skipping name_check'); return
    names = [l.strip() for l in names_file.read_text().splitlines() if l.strip()]
    words = json.loads((piece_dir / f'{name}.words.json').read_text())['words']

    work = piece_dir / 'namecheck-work'
    work.mkdir(exist_ok=True)
    clips = []
    misses = []
    for idx, phrase in enumerate(names):
        toks = norm(phrase)
        span = find_span(words, toks)
        if span is None:
            misses.append(phrase)
            continue
        i0, i1 = span
        # tight padding: at ~165-172 wpm words sit ~0.3-0.4s apart, so a generous pad bleeds
        # neighbouring words into the clip (confirmed on S01: 0.35s pad picked up "customer",
        # "asking...what to", "With"). ASR word-boundary imprecision is at most ~100-200ms
        # (per pilot VOICE-QA.md known limitations), so a small asymmetric pad is enough.
        prev_end = words[i0 - 1]['end'] if i0 > 0 else 0.0
        next_start = words[i1 + 1]['start'] if i1 + 1 < len(words) else words[i1]['end'] + 1.0
        start = max(0.0, words[i0]['start'] - min(0.12, max(0.0, (words[i0]['start'] - prev_end) / 2)))
        end = words[i1]['end'] + min(0.15, max(0.0, (next_start - words[i1]['end']) / 2))
        clip_path = work / f'clip{idx:02d}.wav'
        run(NICE + ['ffmpeg', '-y', '-i', str(wav), '-ss', f'{start:.3f}', '-t', f'{end-start:.3f}',
                    '-ar', '24000', '-ac', '1', str(clip_path)])
        clips.append({'name': phrase, 'clip': clip_path, 'start': round(start, 3), 'end': round(end, 3)})

    if not clips:
        (piece_dir / f'{name}.namecheck.json').write_text(json.dumps(
            {'names_expected': names, 'names_found_in_audio': [], 'names_missing_from_audio': misses,
             'note': 'no name occurrences located in words.json to clip'}, indent=2))
        print('No names found to clip;', len(misses), 'missing:', misses)
        return

    # concat clips with 1s silence between, for one batched Gemini call
    silence = work / 'sil1s.wav'
    run(NICE + ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono', '-t', '1.0',
                '-ar', '24000', '-ac', '1', str(silence)])
    seq = []
    for i, c in enumerate(clips):
        if i > 0:
            seq.append(silence)
        seq.append(c['clip'])
    listfile = work / 'concat.txt'
    listfile.write_text('\n'.join(f"file '{p.resolve()}'" for p in seq) + '\n')
    concat_wav = work / 'batch.wav'
    run(NICE + ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(listfile), '-c', 'copy', str(concat_wav)])

    with wave.open(str(concat_wav)) as f:
        dur = f.getnframes() / f.getframerate()
    mp4 = work / 'batch.mp4'
    run(NICE + ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=320x180:r=1',
                '-i', str(concat_wav), '-shortest', '-c:v', 'libx264', '-x264-params', 'threads=2', '-tune', 'stillimage',
                '-pix_fmt', 'yuv420p', '-b:v', '40k', '-c:a', 'aac', '-b:a', '96k', str(mp4)])

    listing = '\n'.join(f"Clip {i+1}: expected name/phrase spoken here is \"{c['name']}\"" for i, c in enumerate(clips))
    prompt = f"""This audio has {len(clips)} short clips, each separated by exactly 1 second of silence,
each clip an isolated cut of one proper noun/phrase from a voiceover (a cloned voice reading a script).
{listing}

For each clip in order, listen closely and report EXACTLY what you heard and whether it matches the
expected name/phrase as a natural, correct English pronunciation of it. Return ONLY a JSON array, one
object per clip, no markdown fences:
[{{"clip": 1, "expected": "...", "heard": "...", "correct": true/false, "note": "..."}}]
"""
    gemini_watch = Path(__file__).resolve().parents[3] / 'tooling' / 'gemini_watch.py'
    out_json = piece_dir / f'{name}.namecheck.gemini.json'
    r = subprocess.run(['python3', str(gemini_watch), str(mp4), prompt, '--json', '--out', str(out_json)],
                        capture_output=True, text=True)
    result = {'names_expected': names, 'names_found_in_audio': [c['name'] for c in clips],
              'names_missing_from_audio': misses, 'n_clips': len(clips), 'batch_duration_s': round(dur, 2)}
    if r.returncode == 0 and out_json.exists():
        try:
            gem = json.loads(out_json.read_text())
            result['gemini_verdicts'] = gem
        except Exception as e:
            result['gemini_parse_error'] = str(e)
            result['gemini_raw'] = out_json.read_text()[:2000]
    else:
        result['gemini_error'] = r.stderr[-1000:]
    (piece_dir / f'{name}.namecheck.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2)[:3000])

if __name__ == '__main__':
    main()
