#!/usr/bin/env python3
"""Seal/unseal exact native render inputs on Ubuntu Actions only."""
import argparse
import hashlib
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

NAMES=('source.tar.gz','parts.json','mix.wav')


def host():
    if platform.system()!='Linux' or os.environ.get('GITHUB_ACTIONS','').lower() not in ('true','1'):
        raise RuntimeError('render input handling is restricted to hosted Linux Actions')
    if not os.environ.get('VOICEFREE_PASS') or not os.environ.get('RUNNER_TEMP'):
        raise ValueError('hosted encryption context unavailable')


def hash_stream(f):
    h=hashlib.sha256()
    for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def check_hashes(hashes):
    if set(hashes)!=set(NAMES) or any(not re.fullmatch(r'[a-f0-9]{64}',x or '') for x in hashes.values()):
        raise ValueError('three exact SHA-256 pins required')


def seal(directory, hashes, output):
    host();check_hashes(hashes);directory=Path(directory);output=Path(output)
    if output.exists() or output.is_symlink():raise ValueError('output exists')
    files={n:directory/n for n in NAMES}
    for name,p in files.items():
        if p.is_symlink() or not p.is_file():raise ValueError('missing exact build input')
        with p.open('rb') as f:
            if hash_stream(f)!=hashes[name]:raise ValueError('build input pin mismatch')
    with tempfile.TemporaryDirectory(prefix='agmm-input-',dir=os.environ['RUNNER_TEMP']) as d:
        plain=Path(d)/'source.tar'
        with tarfile.open(plain,'w:') as t:
            for name in NAMES:t.add(files[name],arcname=name,recursive=False)
        with tarfile.open(plain,'r:') as t:
            members=t.getmembers()
            if len(members)!=3 or {m.name for m in members}!=set(NAMES) or any(not m.isfile() for m in members):
                raise ValueError('invalid exact build bundle')
            for name in NAMES:
                with t.extractfile(name) as f:
                    if hash_stream(f)!=hashes[name]:raise ValueError('build input changed while sealing')
        subprocess.run(['openssl','enc','-aes-256-cbc','-pbkdf2','-salt','-pass','env:VOICEFREE_PASS',
                        '-in',str(plain),'-out',str(output)],capture_output=True,check=True)
    print('Exact build inputs encrypted; no production approval implied')


def unseal(archive, hashes, output):
    host();check_hashes(hashes);archive=Path(archive);output=Path(output)
    if archive.is_symlink() or not archive.is_file() or output.exists() or output.is_symlink():
        raise ValueError('invalid archive or output')
    with tempfile.TemporaryDirectory(prefix='agmm-input-',dir=os.environ['RUNNER_TEMP']) as d:
        plain=Path(d)/'source.tar'
        subprocess.run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-pass','env:VOICEFREE_PASS',
                        '-in',str(archive),'-out',str(plain)],capture_output=True,check=True)
        with tarfile.open(plain,'r:') as t:
            members=t.getmembers()
            if len(members)!=3 or {m.name for m in members}!=set(NAMES) or any(not m.isfile() or m.size<1 or m.size>8_000_000_000 for m in members):
                raise ValueError('invalid exact build bundle')
            for name in NAMES:
                with t.extractfile(name) as f:
                    if hash_stream(f)!=hashes[name]:raise ValueError('encrypted input pin mismatch')
            output.mkdir(mode=0o700)
            for name in NAMES:
                with t.extractfile(name) as src,(output/name).open('xb') as dst:shutil.copyfileobj(src,dst,1024*1024)
    print('Exact build inputs verified and opened on hosted runner')


def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=('seal','unseal'))
    p.add_argument('--directory');p.add_argument('--archive');p.add_argument('--out',required=True)
    p.add_argument('--source-sha256',required=True);p.add_argument('--parts-sha256',required=True);p.add_argument('--mix-sha256',required=True)
    a=p.parse_args(); hashes=dict(zip(NAMES,(a.source_sha256,a.parts_sha256,a.mix_sha256)))
    if a.operation=='seal':seal(a.directory,hashes,a.out)
    else:unseal(a.archive,hashes,a.out)


if __name__=='__main__':main()
