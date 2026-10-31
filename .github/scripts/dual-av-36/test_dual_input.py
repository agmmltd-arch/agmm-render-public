"""Synthetic checks only: never read or process programme media on this host."""
import json
from unittest.mock import patch
import hosted_av_qualification as av

with patch.object(av.q, 'runtime_key', return_value='synthetic'), patch.object(av, 'http_once', return_value={'body': b'{}'}) as post:
    try:
        av.one_generate_content_request('https://generativelanguage.googleapis.com/v1beta/files/a', 'key')
        raise AssertionError('missing audio accepted')
    except av.Refused:
        pass
    post.assert_not_called()
    av.one_generate_content_request('https://generativelanguage.googleapis.com/v1beta/files/a', 'key', audio_uri='https://generativelanguage.googleapis.com/v1beta/files/b')
    parts = json.loads(post.call_args.args[3])['contents'][0]['parts']
    assert [p.get('file_data', {}).get('mime_type') for p in parts[:2]] == ['video/mp4', 'audio/wav']
    assert parts[0]['video_metadata']['fps'] == 24.0
    try:
        av.one_generate_content_request('https://generativelanguage.googleapis.com/v1beta/files/a', 'key', audio_uri='https://example.com/b')
        raise AssertionError('foreign audio origin accepted')
    except av.Refused:
        pass
print('PASS: both modalities required and foreign audio origin rejected')

# Exercise the panel wiring with in-memory fakes and synthetic text placeholders.
import os, tempfile
from pathlib import Path
from types import SimpleNamespace
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    items = []
    for i in range(6):
        name = 'blind-%s.mp4' % i
        (root / name).write_text('synthetic')
        items.append({'blind_id': str(i), 'file': name, 'bytes': 9, 'sha256': 'synthetic'})
    labels = {str(i): {} for i in range(6)}
    uploads = []
    def command(args, **kwargs):
        if args[0] == 'ffmpeg':
            Path(args[-1]).write_text('synthetic')
            return SimpleNamespace(stdout='')
        return SimpleNamespace(stdout='{"format":{"duration":"60"}}')
    def upload(path, key, opener=None, mime='video/mp4'):
        uploads.append(mime)
        return {'name': mime}
    def active(name, key, opener=None, sleep=None):
        return {'uri': 'https://generativelanguage.googleapis.com/v1beta/files/' + ('v' if name == 'video/mp4' else 'a')}
    response = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': 'synthetic'}]}}]}
    with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'FLEET_FREE_ONLY': '1'}, clear=True), \
         patch.object(av.platform, 'system', return_value='Linux'), patch.object(av.q, 'runtime_key', return_value='key'), \
         patch.object(av.q, 'sha256_file', return_value='synthetic'), patch.object(av.subprocess, 'run', side_effect=command), \
         patch.object(av, 'upload_video', side_effect=upload), patch.object(av, 'wait_active', side_effect=active), \
         patch.object(av, 'one_generate_content_request', return_value=(b'{}', response)) as request:
        result = av.run_blind_panel(root, items, labels, root / 'results', 'key')
    assert result['calls'] == 6 and uploads == ['video/mp4', 'audio/wav'] * 6
    assert all(call.kwargs['audio_uri'].endswith('/a') for call in request.call_args_list)
print('PASS: six blinded items each send video and the matching extracted soundtrack')
