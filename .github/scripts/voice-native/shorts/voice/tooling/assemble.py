#!/usr/bin/env python3
"""Assemble a piece's paragraph takes into one final voice file:
- trim leading/trailing silence per take, 10ms fade in/out (no clicks)
- join with silence gaps (0.25-0.45s within-section; 0.6-0.9s at section breaks, film only)
- two-pass loudnorm to ~-18 LUFS integrated
- optional atempo (<=1.10x, or down to 0.91x) if aggregate wpm is outside target band
- emit <name>.wav, <name>.words.json (word timings, offset + emphasis flags), <name>.receipt.json
- emit a black-frame mp4 for Gemini listening review
Usage: assemble.py <piece_dir> <out_name> <target_wpm_lo> <target_wpm_hi> [--film]
"""
import hashlib, json, random, re, subprocess, sys, wave
from pathlib import Path

NICE = ['nice', '-n', '15']
STAKES = {'ransom','ransomware','cyberattack','cyber','attack','attacked','collapsed','collapse',
          'bankrupt','bankruptcy','lawsuit','sued','fired','fraud','breach','hacked','stolen',
          'crashed','shut','closed','loss','losses','cancelled','delayed','warning','crisis',
          'died','death','risk','fined','scandal','disputed','refused','leaked','exposed'}

def load_names(piece_dir):
    """Per-piece proper-noun list for emphasis flagging (shorts have a different company/name
    set each time, unlike the pilot's fixed four pieces)."""
    p = piece_dir / 'names.txt'
    if not p.exists():
        return set()
    names = set()
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        for tok in re.findall(r"[a-z0-9'.]+", line.lower()):
            names.add(tok)
    return names

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\n{r.stderr}")
    return r.stdout, r.stderr

def wav_duration(path):
    with wave.open(str(path), 'rb') as f:
        return f.getnframes() / f.getframerate()

def _detect_silence(src, threshold_db=-45, min_dur=0.04):
    _, err = run(NICE + ['ffmpeg', '-nostats', '-i', str(src), '-af',
                          f'silencedetect=noise={threshold_db}dB:d={min_dur}', '-f', 'null', '-'])
    starts, ends = [], []
    for line in err.splitlines():
        line = line.strip()
        if 'silence_start:' in line:
            starts.append(float(line.split('silence_start:')[1].strip().split()[0]))
        elif 'silence_end:' in line:
            ends.append(float(line.split('silence_end:')[1].strip().split('|')[0].strip()))
    return starts, ends

def trim_and_fade(src, dst, threshold_db=-45, min_sil=0.04, fade=0.012):
    """Trim leading/trailing near-silence using exact timestamps from silencedetect (so we
    know precisely how much was cut off the front), then apply a short fade in/out to avoid
    clicks. Returns (output_duration, leading_trim_removed_seconds)."""
    total = wav_duration(src)
    starts, ends = _detect_silence(src, threshold_db, min_sil)
    leading_trim = 0.0
    trailing_cut_at = total
    if starts and starts[0] < 0.02:
        # leading silence interval: silence_start ~0, silence_end is where speech begins
        if ends:
            # root 29 Sep: cutting exactly at the -45 dB crossing, then fading in over 12 ms, shaved the first consonant
            # (S21 "Monzo" heard as "Lonzo", S26 "It's" at 71% ASR confidence). Keep 60 ms of pre-roll before the onset.
            leading_trim = max(0.0, ends[0] - 0.06)
    if ends:
        # if the last silence interval runs to (or past) EOF, trim back to where it starts
        last_start = starts[-1] if starts else None
        if last_start is not None and (total - last_start) < 1.0 and last_start > leading_trim:
            # confirm this interval has no matching 'end' before EOF (i.e. it's trailing)
            if len(ends) < len(starts):
                trailing_cut_at = last_start
    trimmed_dur = max(0.05, trailing_cut_at - leading_trim)
    tmp = dst.with_suffix('.trim.wav')
    run(NICE + ['ffmpeg', '-y', '-threads', '2', '-i', str(src), '-ss', f'{leading_trim:.4f}',
                '-t', f'{trimmed_dur:.4f}', '-c', 'copy', str(tmp)])
    dur = wav_duration(tmp)
    run(NICE + ['ffmpeg', '-y', '-threads', '2', '-i', str(tmp), '-af',
                f"afade=t=in:st=0:d={fade},afade=t=out:st={max(0,dur-fade)}:d={fade}", str(dst)])
    tmp.unlink()
    return wav_duration(dst), leading_trim

def make_silence(dst, seconds):
    run(NICE + ['ffmpeg', '-y', '-f', 'lavfi', '-i', f'anullsrc=r=24000:cl=mono', '-t', f'{seconds:.4f}',
                '-ar', '24000', '-ac', '1', '-sample_fmt', 's16', str(dst)])

def concat_wavs(paths, out_path):
    listfile = out_path.with_suffix('.concat.txt')
    listfile.write_text('\n'.join(f"file '{p.resolve()}'" for p in paths) + '\n')
    run(NICE + ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(listfile), '-c', 'copy', str(out_path)])
    listfile.unlink()

def loudnorm_two_pass(src, dst, target_i=-18.0, target_tp=-2.0, target_lra=7.0):
    out1, err1 = run(NICE + ['ffmpeg', '-i', str(src), '-af',
                              f'loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json',
                              '-f', 'null', '-'])
    txt = err1 if 'input_i' in err1 else out1
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', txt, re.S)
    meas = json.loads(m.group(0))
    af = (f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:"
          f"measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:measured_LRA={meas['input_lra']}:"
          f"measured_thresh={meas['input_thresh']}:offset={meas['target_offset']}:linear=true:print_format=json")
    out2, err2 = run(NICE + ['ffmpeg', '-y', '-i', str(src), '-af', af, '-ar', '24000', '-ac', '1',
                              '-sample_fmt', 's16', str(dst)])
    txt2 = err2 if 'output_i' in err2 else out2
    m2 = re.search(r'\{[^{}]*"input_i"[^{}]*\}', txt2, re.S)
    return meas, (json.loads(m2.group(0)) if m2 else None)

def atempo_chain(factor):
    # ffmpeg atempo supports 0.5-2.0 per stage; single stage covers our small range
    return f"atempo={factor:.4f}"

def apply_tempo(src, dst, factor):
    run(NICE + ['ffmpeg', '-y', '-threads', '2', '-i', str(src), '-af', atempo_chain(factor),
                '-ar', '24000', '-ac', '1', '-sample_fmt', 's16', str(dst)])

def make_blackframe_mp4(wav_path, mp4_path, max_bytes=17_000_000):
    dur = wav_duration(wav_path)
    # keep resolution/bitrate low enough to stay under Gemini's inline size cap
    run(NICE + ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=320x180:r=1',
                '-i', str(wav_path), '-shortest', '-c:v', 'libx264', '-x264-params', 'threads=2', '-tune', 'stillimage',
                '-pix_fmt', 'yuv420p', '-b:v', '40k', '-c:a', 'aac', '-b:a', '96k', str(mp4_path)])
    size = mp4_path.stat().st_size
    if size > max_bytes:
        run(NICE + ['ffmpeg', '-y', '-i', str(mp4_path), '-c:v', 'libx264', '-x264-params', 'threads=2', '-b:v', '20k',
                    '-c:a', 'aac', '-b:a', '64k', str(mp4_path) + '.small.mp4'])
        Path(str(mp4_path) + '.small.mp4').replace(mp4_path)
    return mp4_path.stat().st_size

def main():
    piece_dir = Path(sys.argv[1]).resolve()
    out_name = sys.argv[2]
    lo, hi = float(sys.argv[3]), float(sys.argv[4])
    is_film = '--film' in sys.argv
    gap_lo, gap_hi = 0.25, 0.45
    section_gap_lo, section_gap_hi = 0.6, 0.9
    if '--gaps' in sys.argv:
        i = sys.argv.index('--gaps')
        gap_lo, gap_hi, section_gap_lo, section_gap_hi = (float(x) for x in sys.argv[i+1:i+5])

    receipts = sorted(piece_dir.glob('P??.receipt.json'))
    assert receipts, f'no receipts in {piece_dir}'
    n = len(receipts)
    NAMES = load_names(piece_dir)
    section_starts = set()
    if is_film:
        structure = json.loads((piece_dir / 'structure.json').read_text())
        section_starts = set(structure['section_starts'])  # 0-based

    work = piece_dir / 'assemble-work'
    work.mkdir(exist_ok=True)
    rng = random.Random(int(hashlib.sha256(out_name.encode()).hexdigest()[:8], 16))

    trimmed = []
    words_all = []
    para_texts = []
    para_durs = []
    total_words = 0
    cursor = 0.0
    gap_log = []
    seq_paths = []
    for i, rc in enumerate(receipts):
        item = json.loads(rc.read_text())
        stem = item['paragraph']
        src_wav = piece_dir / f'{stem}.wav'
        trimmed_wav = work / f'{stem}.trimmed.wav'
        dur, leading_trim = trim_and_fade(src_wav, trimmed_wav)
        para_durs.append(dur)
        para_texts.append(item['text'])
        total_words += len(item['text'].split())

        gap = 0.0
        if i > 0:
            if is_film and i in section_starts:
                gap = round(rng.uniform(section_gap_lo, section_gap_hi), 3)
            else:
                gap = round(rng.uniform(gap_lo, gap_hi), 3)
            gap_wav = work / f'gap-{i:03d}.wav'
            make_silence(gap_wav, gap)
            seq_paths.append(gap_wav)
            gap_log.append({'before_paragraph': i + 1, 'gap_s': gap, 'section_break': is_film and i in section_starts})
            cursor += gap
        seq_paths.append(trimmed_wav)

        # word timings for this paragraph, offset by cursor
        words_path = piece_dir / f'{stem}.words.json'
        resp = json.loads(words_path.read_text())
        # Mistral audio/transcriptions with timestamp_granularities=word returns a flat
        # 'segments' list, one per word, each {text, start, end}.
        wlist = [w for w in (resp.get('segments') or []) if w.get('type') == 'transcription_segment']
        if not wlist:
            wlist = resp.get('words') or []
        for w in wlist:
            word_text = w.get('word') or w.get('text') or ''
            start = w.get('start')
            end = w.get('end')
            if start is None or end is None:
                continue
            # shift by -leading_trim (silence cut off the front of this paragraph's clip),
            # then by +cursor (this paragraph's position in the assembled track); clip at 0
            # since a word's ASR start can occasionally fall a hair before the detected cut.
            adj_start = max(0.0, float(start) - leading_trim)
            adj_end = max(adj_start, float(end) - leading_trim)
            words_all.append({
                'word': word_text.strip(),
                'start': round(cursor + adj_start, 3),
                'end': round(cursor + adj_end, 3),
                'paragraph': stem,
                'emphasis': bool(re.search(r'\d', word_text)) or word_text.strip().strip('.,!?"\'').lower() in NAMES
                            or word_text.strip().strip('.,!?"\'').lower() in STAKES,
            })
        cursor += dur

    # repair zero/negative-duration word timestamps (a rare Mistral ASR rounding artifact,
    # not a real audio gap -- confirmed by RMS spot-checks): borrow up to 80ms from the gap
    # to the next word, without ever overlapping it.
    for idx in range(len(words_all)):
        w = words_all[idx]
        if w['end'] <= w['start']:
            nxt_start = words_all[idx + 1]['start'] if idx + 1 < len(words_all) else w['start'] + 0.08
            w['end'] = round(min(w['start'] + 0.08, max(w['start'] + 0.01, nxt_start)), 3)

    final_wav_raw = work / f'{out_name}.concat.wav'
    concat_wavs(seq_paths, final_wav_raw)
    raw_dur = wav_duration(final_wav_raw)
    speaking_dur = sum(para_durs)
    wpm_speaking = total_words / (speaking_dur / 60.0)
    wpm_delivered = total_words / (raw_dur / 60.0)

    tempo_factor = 1.0
    if wpm_speaking < lo:
        needed = lo / wpm_speaking
        tempo_factor = min(needed, 1.10)
    elif wpm_speaking > hi:
        needed = hi / wpm_speaking
        tempo_factor = max(needed, 0.85)

    tempo_applied_path = work / f'{out_name}.tempo.wav'
    if abs(tempo_factor - 1.0) > 0.005:
        apply_tempo(final_wav_raw, tempo_applied_path, tempo_factor)
        for w in words_all:
            w['start'] = round(w['start'] / tempo_factor, 3)
            w['end'] = round(w['end'] / tempo_factor, 3)
        src_for_loudnorm = tempo_applied_path
    else:
        src_for_loudnorm = final_wav_raw

    final_dur = wav_duration(src_for_loudnorm)
    final_speaking_dur = speaking_dur / tempo_factor
    wpm_final_speaking = total_words / (final_speaking_dur / 60.0)
    wpm_final_delivered = total_words / (final_dur / 60.0)

    final_wav = piece_dir / f'{out_name}.wav'
    meas_pre, meas_post = loudnorm_two_pass(src_for_loudnorm, final_wav)

    words_json_path = piece_dir / f'{out_name}.words.json'
    json.dump({'words': words_all, 'tempo_factor': tempo_factor}, open(words_json_path, 'w'), indent=2)

    mp4_path = piece_dir / f'{out_name}.blackframe.mp4'
    mp4_size = make_blackframe_mp4(final_wav, mp4_path)

    full_text = ' '.join(para_texts)
    receipt = {
        'name': out_name,
        'piece_dir': str(piece_dir),
        'n_paragraphs': n,
        'total_words': total_words,
        'gap_log': gap_log,
        'speaking_duration_s_pre_tempo': round(speaking_dur, 3),
        'assembled_duration_s_pre_tempo': round(raw_dur, 3),
        'wpm_speaking_pre_tempo': round(wpm_speaking, 1),
        'wpm_delivered_pre_tempo': round(wpm_delivered, 1),
        'tempo_factor_applied': round(tempo_factor, 4),
        'final_duration_s': round(final_dur, 3),
        'wpm_speaking_final': round(wpm_final_speaking, 1),
        'wpm_delivered_final': round(wpm_final_delivered, 1),
        'target_wpm_range': [lo, hi],
        'target_wpm_basis': 'wpm_speaking (excludes inserted gaps)',
        'loudnorm_measured_pre': meas_pre,
        'loudnorm_measured_post': meas_post,
        'target_lufs_i': -18.0,
        'blackframe_mp4_bytes': mp4_size,
        'full_script_text': full_text,
        'model': 'voxtral-mini-tts-2603',
        'reference_sha256_only': '3df9d7568c0b0569887e6c9f39bd35835cda305a09d288ea535c63d9cdc15443',
        'paragraph_receipts': [str(r.name) for r in receipts],
    }
    (piece_dir / f'{out_name}.receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k not in ('full_script_text', 'gap_log')}, indent=2))

if __name__ == '__main__':
    main()
