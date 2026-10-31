#!/usr/bin/env python3
"""Blinded synthetic audio-only evaluation; no programme inputs or release approval."""
import json
import random
import subprocess
import tempfile
from pathlib import Path


def run(args, timeout=180):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / 'source.wav'
        run(['espeak-ng', '-s', '145', '-w', str(source),
             'A business introduced an automated service. Customers were promised faster responses, '
             'but the process needed careful testing. The team checked every result before making a decision.'])
        filters = {
            'clean': 'anull',
            'noise': 'anoisesrc=color=white:amplitude=0.10[noise];[0:a][noise]amix=inputs=2:duration=first',
            'dropout': "volume='if(between(t,2,3.2),0,1)':eval=frame",
            'pumping': "volume='if(lt(mod(t,0.7),0.35),0.12,1)':eval=frame",
        }
        labels = list(filters)
        random.SystemRandom().shuffle(labels)
        results = []
        for index, label in enumerate(labels):
            blind_id = chr(65 + index)
            prefix = root / (blind_id + '-')
            audio = Path(str(prefix) + '0000.wav')
            args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source)]
            args += ['-filter_complex', filters[label]] if label == 'noise' else ['-af', filters[label]]
            run(args + ['-ar', '16000', '-ac', '1', str(audio)])
            try:
                proc = subprocess.run(['build/bin/llama-omni-single-test-audio', '-m', 'models/model.gguf',
                                       '--audio', 'models/audio.gguf', '--test', str(prefix), '1',
                                       '--no-tts', '-ngl', '0'], capture_output=True, text=True, timeout=900)
                begin, end = 'AGMM_SYNTHETIC_RESPONSE_BEGIN', 'AGMM_SYNTHETIC_RESPONSE_END'
                response = proc.stdout.split(begin, 1)[1].split(end, 1)[0].strip() if begin in proc.stdout and end in proc.stdout else ''
                results.append({'blind_id': blind_id, 'exit_code': proc.returncode, 'response': response,
                                'stdout_tail': proc.stdout[-16000:], 'stderr_tail': proc.stderr[-3000:]})
            except subprocess.TimeoutExpired:
                results.append({'blind_id': blind_id, 'status': 'timeout'})
        Path('research-results.json').write_text(json.dumps({
            'schema': 'synthetic-audio-research-v1', 'results': results,
            'labels': dict(zip('ABCD', labels)), 'release_approval': False,
            'continuous_visual_review': False,
        }, indent=2) + '\n')


if __name__ == '__main__':
    main()
