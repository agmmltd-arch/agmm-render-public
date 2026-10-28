#!/usr/bin/env python3
"""Validate hosted selected takes against admission before native voice execution.

Only a source-bound selection, never a review or release approval. Call on Ubuntu
inside the native voice sandbox after authenticating the producer workflow, its
immutable source closure, artifact ID and GitHub archive digest.
"""
import hashlib
import json
from pathlib import Path
import re



def validate_producer(run, artifact, run_id, commit, artifact_id):
    """Caller supplies GitHub API evidence, independently fetched on Actions."""
    if not (str(run.get('id')) == str(run_id) and run.get('path') == '.github/workflows/voicefree-hosted-select.yml'
            and run.get('status') == 'completed' and run.get('conclusion') == 'success'
            and run.get('event') == 'workflow_dispatch' and run.get('run_attempt') == 1
            and run.get('head_sha') == commit and re.fullmatch(r'[0-9a-f]{40}', commit)):
        raise ValueError('unqualified selection producer')
    if not (str(artifact.get('id')) == str(artifact_id) and artifact.get('name') == 'voice-selection-' + str(run_id) + '-ENC'
            and artifact.get('expired') is False and str((artifact.get('workflow_run') or {}).get('id')) == str(run_id)
            and re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest') or '')):
        raise ValueError('unqualified encrypted selection artifact')
    return artifact['digest']


def validate(metadata, directory, sid, expected_run, expected_commit, bindings):
    def need(ok, message):
        if not ok: raise ValueError(message)
    need(metadata.get('schema') == 'agmm-hosted-selected-takes-v1', 'selection schema')
    need(metadata.get('id') == sid and re.fullmatch(r'S[0-9]{2,3}', sid), 'piece identity')
    need(str(metadata.get('selector_run_id')) == str(expected_run), 'producer run')
    need(metadata.get('selector_commit') == expected_commit and re.fullmatch(r'[0-9a-f]{40}', expected_commit), 'producer commit')
    need(metadata.get('status') == 'SELECTED_REQUIRES_NATIVE_VOICE_CHECK' and metadata.get('release_approval') is False, 'selection is not a release approval')
    rows = metadata.get('rows')
    need(isinstance(rows, list) and rows, 'no selected paragraphs')
    expected = {}
    paragraphs = set()
    for row in rows:
        name = row.get('paragraph', '')
        need(re.fullmatch(r'P[0-9]{2}', name) and name not in paragraphs, 'invalid or repeated paragraph')
        paragraphs.add(name)
        files = row.get('files', {})
        need(set(files) == {name + '.wav', name + '.words.json', name + '.receipt.json'}, 'incomplete paragraph')
        for filename, detail in files.items():
            need(re.fullmatch(r'[0-9a-f]{64}', detail.get('sha256', '')) and type(detail.get('bytes')) is int and 0 < detail['bytes'] <= 100_000_000, 'invalid file binding')
            rel = 'shorts/voice/' + sid + '/' + filename
            need(bindings.get(rel) == detail['sha256'], 'selection differs from admission')
            expected[filename] = detail
    media_bindings = {k for k in bindings if k.startswith('shorts/voice/' + sid + '/P')}
    need(media_bindings == {'shorts/voice/' + sid + '/' + n for n in expected}, 'admission take inventory differs')
    directory = Path(directory)
    need(directory.is_dir() and not directory.is_symlink(), 'selection directory')
    entries = list(directory.iterdir())
    need({p.name for p in entries} == set(expected) | {'SELECTION.json'}, 'unexpected selection file')
    need(all(p.is_file() and not p.is_symlink() for p in entries), 'unsafe selection file')
    need(json.loads((directory/'SELECTION.json').read_text()) == metadata, 'selection metadata differs')
    for name, detail in expected.items():
        p = directory / name
        need(p.stat().st_size == detail['bytes'], 'selected file size differs')
        h=hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024), b''): h.update(block)
        need(h.hexdigest() == detail['sha256'], 'selected file digest differs')
    return sorted(expected)


def materialize(request, destination, work):
    """Download and validate an encrypted take pack solely on Ubuntu Actions.

    The caller must have already admitted request['input_bindings'] and checked
    that the pinned producer commit belongs to its qualified source closure.
    No files are installed into the native tree until validation completes.
    """
    import os, shutil, subprocess, sys, tarfile, zipfile
    if not (sys.platform.startswith('linux') and os.environ.get('GITHUB_ACTIONS') == 'true'):
        raise ValueError('hosted Ubuntu execution required')
    if not os.environ.get('VOICEFREE_PASS'):
        raise ValueError('selection decryption key absent')
    producer = request['selection_producer']
    metadata = request['selection_metadata']
    repo = 'agmmltd-arch/agmm-render-public'
    def gh(endpoint):
        return json.loads(subprocess.check_output(['gh','api','repos/' + repo + '/' + endpoint]))
    run_id = str(producer['run_id'])
    run = gh('actions/runs/' + run_id)
    artifact = gh('actions/artifacts/' + str(producer['artifact_id']))
    archive_digest = validate_producer(run, artifact, run_id, producer['commit'], producer['artifact_id'])
    work = Path(work); work.mkdir(parents=True, exist_ok=False)
    archive = work/'archive.zip'
    with archive.open('xb') as out:
        subprocess.run(['gh','api','repos/' + repo + '/actions/artifacts/' + str(producer['artifact_id']) + '/zip'],stdout=out,check=True)
    h=hashlib.sha256()
    with archive.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    if 'sha256:' + h.hexdigest() != archive_digest: raise ValueError('selection archive digest differs')
    encrypted=work/'selected.enc'
    with zipfile.ZipFile(archive) as z:
        members=[m for m in z.infolist() if not m.is_dir()]
        if len(members)!=1 or members[0].filename!='selected.enc' or members[0].file_size>1_000_000_000:
            raise ValueError('unexpected encrypted selection inventory')
        with z.open(members[0]) as src,encrypted.open('xb') as out: shutil.copyfileobj(src,out)
    plain=work/'selected.tar'
    with plain.open('xb') as out:
        subprocess.run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-pass','env:VOICEFREE_PASS','-in',str(encrypted)],stdout=out,check=True)
    unpack=work/'selected'; unpack.mkdir()
    with tarfile.open(plain,'r:') as tar:
        members=tar.getmembers()
        files=[m for m in members if m.isfile()]
        if any(not (m.isfile() or m.isdir()) for m in members) or sum(m.size for m in files)>1_000_000_000:
            raise ValueError('unsafe selected take archive')
        seen=set()
        for member in files:
            name=member.name.removeprefix('./')
            if not re.fullmatch(r'(?:SELECTION\.json|P[0-9]{2}\.(?:wav|words\.json|receipt\.json))',name) or name in seen:
                raise ValueError('unexpected selection archive member')
            seen.add(name)
            with tar.extractfile(member) as src,(unpack/name).open('xb') as out: shutil.copyfileobj(src,out)
    files=validate(metadata,unpack,request['id'],run_id,producer['commit'],request['input_bindings'])
    destination=Path(destination)
    if not destination.is_dir() or destination.is_symlink(): raise ValueError('native destination unavailable')
    for name in files:
        if (destination/name).exists(): raise ValueError('native selected take already exists')
    for name in files: shutil.copyfile(unpack/name,destination/name)
    return files
