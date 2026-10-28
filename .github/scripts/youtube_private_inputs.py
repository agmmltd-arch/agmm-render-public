#!/usr/bin/env python3
"""Verify and materialise only the three immutable protected text inputs."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

NAMES = ('metadata.json', 'approval.json', 'existing-rows.json')


def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def stage(root, commit, prefix, manifest_blob, output):
    root = Path(root).resolve(); output = Path(output).resolve()
    if not re.fullmatch(r'[a-f0-9]{40}', commit or '') or not re.fullmatch(r'[a-f0-9]{40}', manifest_blob or ''):
        raise ValueError('invalid commit or blob')
    if not re.fullmatch(r'youtube-hosted-inputs/[a-f0-9]{32}', prefix or ''):
        raise ValueError('invalid private namespace')
    if git(root, 'rev-parse', 'HEAD') != commit:
        raise ValueError('private commit mismatch')
    folder = root / prefix
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('private folder unavailable')
    for parent in (root / 'youtube-hosted-inputs', folder):
        if parent.is_symlink(): raise ValueError('symlinked source')
    mp = folder / 'MANIFEST.json'
    if mp.is_symlink() or not mp.is_file(): raise ValueError('manifest unavailable')
    if git(root, 'rev-parse', commit + ':' + prefix + '/MANIFEST.json') != manifest_blob:
        raise ValueError('manifest blob mismatch')
    if git(root, 'hash-object', str(mp)) != manifest_blob:
        raise ValueError('manifest bytes changed')
    manifest = json.loads(mp.read_text())
    if manifest.get('schema') != 'agmm-youtube-private-inputs-v1' or set(manifest.get('files', {})) != set(NAMES):
        raise ValueError('invalid input manifest')
    contents = {}
    for name in NAMES:
        path = folder / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError('invalid input file: ' + name)
        data = path.read_bytes()
        spec = manifest['files'][name]
        if not isinstance(spec, dict) or hashlib.sha256(data).hexdigest() != spec.get('sha256'):
            raise ValueError('input hash mismatch: ' + name)
        blob = git(root, 'rev-parse', commit + ':' + prefix + '/' + name)
        if blob != spec.get('git_blob') or git(root, 'hash-object', str(path)) != blob:
            raise ValueError('input tree mismatch: ' + name)
        json.loads(data)
        contents[name] = data
    if any((output / name).exists() or (output / name).is_symlink() for name in NAMES):
        raise ValueError('refuse to overwrite local inputs')
    for name, data in contents.items():
        with (output / name).open('xb') as f: f.write(data)
    print('Protected input source and three text files verified')


def main():
    p=argparse.ArgumentParser()
    for k in ('root','commit','prefix','manifest-blob'): p.add_argument('--'+k, required=True)
    a=p.parse_args(); stage(a.root,a.commit,a.prefix,a.manifest_blob,Path.cwd())


if __name__ == '__main__': main()
