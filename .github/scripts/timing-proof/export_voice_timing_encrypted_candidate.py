#!/usr/bin/env python3
"""Export source-bound voice timing JSON on Ubuntu, never audio or approval."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

PUBLIC = 'agmmltd-arch/agmm-render-public'
WORKFLOW = '.github/workflows/agmm-short-voice.yml'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def gh_json(path):
    return json.loads(subprocess.check_output(['gh', 'api', path]))


def export(pointer, run, artifact, producer_blobs, archive, output):
    need(sys.platform.startswith('linux') and os.environ.get('GITHUB_ACTIONS') == 'true', 'Ubuntu Actions required')
    sid = pointer.get('id', '')
    need(re.fullmatch(r'S[0-9]+', sid) is not None, 'invalid short id')
    intent = pointer.get('intent', '')
    need(intent.startswith('voice-' + sid + '-'), 'intent does not match short')
    need(pointer.get('voice_checks_complete') is True, 'voice checks incomplete')
    need(str(run.get('id')) == str(pointer.get('run_id')) and run.get('path') == WORKFLOW
         and run.get('event') == 'workflow_dispatch' and run.get('run_attempt') == 1
         and run.get('status') == 'completed' and run.get('conclusion') == 'success', 'producer run invalid')
    pinned = pointer.get('producer_git_blobs') or {}
    need(WORKFLOW in pinned and all(producer_blobs.get(k) == v for k, v in pinned.items()), 'producer closure changed')
    need(str(artifact.get('id')) == str(pointer.get('artifact_id'))
         and str((artifact.get('workflow_run') or {}).get('id')) == str(run['id'])
         and artifact.get('name') == intent + ('-GENERATED-ENC' if pointer.get('request', {}).get('selection_producer') else '-GENERATED') and not artifact.get('expired')
         and artifact.get('digest') == pointer.get('artifact_digest'), 'artifact identity invalid')
    need(re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest') or '') is not None, 'invalid artifact digest')
    with archive.open('rb') as f:
        h = hashlib.sha256()
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    need('sha256:' + h.hexdigest() == artifact['digest'], 'artifact bytes mismatch')
    timing_name = 'generated/' + sid + '.words.json'
    encrypted = bool(pointer.get('request', {}).get('selection_producer'))
    if encrypted:
        need(bool(os.environ.get('VOICEFREE_PASS')), 'hosted voice decryption key unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            encrypted_file = Path(tmp) / 'voice.enc'
            plain_file = Path(tmp) / 'voice.tar'
            with zipfile.ZipFile(archive) as z:
                infos = z.infolist()
                need(len(infos) == 1 and infos[0].filename == 'voice-generated.enc'
                     and infos[0].file_size < 2_000_000_000, 'unexpected encrypted voice archive')
                with z.open(infos[0]) as src, encrypted_file.open('xb') as dst:
                    import shutil
                    shutil.copyfileobj(src, dst)
            with plain_file.open('xb') as dst:
                subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2',
                                '-pass', 'env:VOICEFREE_PASS', '-in', str(encrypted_file)],
                               check=True, stdout=dst, stderr=subprocess.PIPE)
            with tarfile.open(plain_file, 'r:') as tar:
                items = tar.getmembers()
                need(all(i.isfile() or i.isdir() for i in items)
                     and sum(i.size for i in items) < 2_000_000_000, 'unsafe voice tar')
                names = [i.name.removeprefix('./').rstrip('/') for i in items]
                need(len(names) == len(set(names)), 'duplicate voice tar paths')
                need(names.count('RECEIPT.json') == 1 and names.count(timing_name) == 1,
                     'required files missing')
                receipt_item, timing_item = (items[names.index(name)] for name in ('RECEIPT.json', timing_name))
                need(receipt_item.isfile() and timing_item.isfile() and receipt_item.size <= 2_000_000
                     and timing_item.size <= 8_000_000, 'invalid or oversized text file')
                raw_receipt = tar.extractfile(receipt_item).read()
                data = tar.extractfile(timing_item).read()
    else:
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            need(len(names) == len(set(names)), 'duplicate archive paths')
            need(sum(i.file_size for i in infos) < 2_000_000_000, 'archive too large')
            need(names.count('RECEIPT.json') == 1 and names.count(timing_name) == 1, 'required files missing')
            need(z.getinfo('RECEIPT.json').file_size <= 2_000_000 and z.getinfo(timing_name).file_size <= 8_000_000, 'text file too large')
            raw_receipt = z.read('RECEIPT.json')
            data = z.read(timing_name)
    need(sha(raw_receipt) == pointer.get('receipt_sha256'), 'receipt bytes mismatch')
    receipt = json.loads(raw_receipt)
    need(receipt.get('status') == 'NATIVE_CHECKS_COMPLETED_REVIEW_REQUIRED'
         and receipt.get('id') == sid and receipt.get('intent') == intent
         and str(receipt.get('run_id')) == str(run['id'])
         and str(receipt.get('run_attempt')) == '1'
         and receipt.get('runtime_commit') == run.get('head_sha'), 'receipt source mismatch')
    entries = [r for r in receipt.get('generated', []) if r.get('path') == sid + '.words.json']
    need(len(entries) == 1, 'timing inventory not unique')
    need(len(data) == entries[0].get('bytes') and sha(data) == entries[0].get('sha256'), 'timing bytes mismatch')
    json.loads(data)
    output.mkdir(parents=True, exist_ok=True)
    (output / (sid + '.words.json')).write_bytes(data)
    (output / 'TIMING-RECEIPT.json').write_text(json.dumps({
        'schema': 'agmm-voice-timing-export-v1', 'id': sid, 'intent': intent,
        'source_run_id': str(run['id']), 'artifact_id': str(artifact['id']),
        'artifact_digest': artifact['digest'], 'source_receipt_sha256': sha(raw_receipt),
        'timing_sha256': sha(data), 'audio_exported': False, 'release_approval': False,
    }, indent=2) + '\n')


def main():
    need(sys.platform.startswith('linux') and os.environ.get('GITHUB_ACTIONS') == 'true', 'Ubuntu Actions required')
    pointer = json.loads(Path(sys.argv[1]).read_text())
    run = gh_json('repos/%s/actions/runs/%s' % (PUBLIC, pointer['run_id']))
    artifact = gh_json('repos/%s/actions/artifacts/%s' % (PUBLIC, pointer['artifact_id']))
    tree = gh_json('repos/%s/git/trees/%s?recursive=1' % (PUBLIC, run['head_sha']))
    need(not tree.get('truncated'), 'producer tree truncated')
    blobs = {r['path']: r.get('sha') for r in tree['tree'] if r.get('type') == 'blob'}
    archive = Path(os.environ['RUNNER_TEMP']) / 'voice-source.zip'
    with archive.open('xb') as f:
        subprocess.run(['gh', 'api', 'repos/%s/actions/artifacts/%s/zip' % (PUBLIC, pointer['artifact_id'])], stdout=f, check=True)
    try:
        export(pointer, run, artifact, blobs, archive, Path(sys.argv[2]))
    finally:
        archive.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
