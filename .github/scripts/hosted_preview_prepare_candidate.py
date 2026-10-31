#!/usr/bin/env python3
"""Prepare exact revised-script preview on Ubuntu; never use a voice or approve release."""
import hashlib, json, os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE / 'voice-native'
sys.path.insert(0, str(ROOT / 'kit/tools'))
import extract_story as story
from writer_crypto import crypt


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def validate(root, sid, binding):
    need(re.fullmatch(r'S[0-9]{2,3}', sid or '') is not None, 'invalid short ID')
    manifest = root / 'MANIFEST.json'
    need(not manifest.is_symlink() and manifest.is_file(), 'manifest missing')
    raw = manifest.read_bytes()
    need(len(raw) < 100000 and sha(raw) == binding, 'manifest binding differs')
    data = json.loads(raw)
    need(data.get('schema') == 'agmm-story-preview-input-v1' and data.get('id') == sid
         and data.get('timing') == 'estimated' and data.get('no_media') is True
         and data.get('release_approved') is False, 'preview manifest differs')
    entries = data.get('files')
    required = {'shorts/scripts-v2/' + sid + '.md', 'story-data/STORY-DATA.md'}
    def allowed(name):
        return name in required or bool(re.fullmatch(r'shorts/scripts-v2/_sources/' + sid + r'_[0-9]+\.txt', name))
    need(isinstance(entries, dict) and 3 <= len(entries) <= 12 and required <= set(entries)
         and all(allowed(name) for name in entries), 'preview source inventory differs')
    for rel, digest in entries.items():
        source = root / rel
        need(re.fullmatch(r'[a-f0-9]{64}', digest or '') is not None and not source.is_symlink()
             and source.is_file() and source.stat().st_size < 2000000 and sha(source.read_bytes()) == digest,
             'preview source differs')
    need(entries['shorts/scripts-v2/' + sid + '.md'] == data.get('revision_script_sha256'), 'revised script differs')
    return data


def main():
    need(sys.platform.startswith('linux') and os.getenv('GITHUB_ACTIONS') == 'true', 'Ubuntu Actions required')
    root, sid, output = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    data = validate(root, sid, os.environ['STORY_PREVIEW_MANIFEST_SHA'])
    for rel in data['files']:
        if rel.startswith('shorts/'):
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            need(not dest.exists() and not dest.is_symlink(), 'runtime input exists')
            dest.write_bytes((root / rel).read_bytes())
    # A pre-existing timing file would silently substitute the old checked voice.
    voice = ROOT / 'shorts/voice' / sid / (sid + '.words.json')
    need(not voice.exists() and not voice.is_symlink(), 'old voice timing present')
    ctx = story.build_context(sid)
    need(ctx['mode'] == 'estimated' and ctx['ranges'] is not None and ctx['ledger']
         and ctx['sources'] and all(ctx['src_paras'].values()), 'estimated context incomplete')
    prompt = story.build_prompt(ctx)['full']
    need(1000 < len(prompt) < 100000, 'preview prompt size invalid')
    packet = {'schema': 'agmm-story-preview-prompt-v1', 'id': sid,
              'revision_script_sha256': data['revision_script_sha256'],
              'source_manifest_sha256': os.environ['STORY_PREVIEW_MANIFEST_SHA'],
              'prompt_sha256': sha(prompt.encode()), 'prompt': prompt,
              'timing': 'estimated', 'release_approved': False}
    need(not output.exists() and not output.is_symlink(), 'output already exists')
    output.write_bytes(crypt(json.dumps(packet, ensure_ascii=False).encode(), os.environ['AGMM_WRITER_PASS']))
    print('Estimated preview prompt prepared; original grounding and independent review remain required.')


if __name__ == '__main__':
    main()
