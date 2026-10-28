#!/usr/bin/env python3
"""Seal a byte-bound master package on hosted Linux before artifact upload."""
import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path


def encrypt(video, thumbnail, integrity, expected_sha256, thumbnail_sha256, output):
    if platform.system()!='Linux' or os.environ.get('GITHUB_ACTIONS','').lower() not in ('true','1'):
        raise RuntimeError('master packaging is restricted to hosted Linux Actions')
    if not os.environ.get('VOICEFREE_PASS') or any(not re.fullmatch(r'[a-f0-9]{64}', x or '') for x in (expected_sha256,thumbnail_sha256)):
        raise ValueError('key or expected master hash unavailable')
    video=Path(video); thumbnail=Path(thumbnail); integrity=Path(integrity); output=Path(output)
    if not re.fullmatch(r'[A-Za-z0-9._-]+\.mp4',video.name) or video.is_symlink() or not video.is_file():
        raise ValueError('invalid master')
    if integrity.name!='REMOTE-INTEGRITY.json' or integrity.is_symlink() or not integrity.is_file() or integrity.stat().st_size>1_000_000 or output.exists() or output.is_symlink():
        raise ValueError('invalid integrity input or existing output')
    if thumbnail.is_symlink() or not thumbnail.is_file() or thumbnail.stat().st_size>20_000_000:
        raise ValueError('invalid thumbnail')
    data=json.loads(integrity.read_text())
    pinned=data.get('master_4k_sha256') or data.get('master_sha256') or (data.get('outputs') or {}).get('master_sha256')
    digest=hashlib.sha256()
    with video.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):digest.update(block)
    if digest.hexdigest()!=expected_sha256 or pinned!=expected_sha256 or hashlib.sha256(thumbnail.read_bytes()).hexdigest()!=thumbnail_sha256:
        raise ValueError('master differs from approved and native integrity pins')
    with tempfile.TemporaryDirectory(prefix='agmm-master-',dir=os.environ['RUNNER_TEMP']) as d:
        plain=Path(d)/'master.tar'
        with tarfile.open(plain,'w:') as t:
            t.add(video,arcname=video.name,recursive=False)
            t.add(integrity,arcname='REMOTE-INTEGRITY.json',recursive=False)
            t.add(thumbnail,arcname='thumbnail.jpg',recursive=False)
        with tarfile.open(plain,'r:') as t:
            members=t.getmembers()
            if len(members)!=3 or any(not m.isfile() for m in members):raise ValueError('invalid sealed members')
            archived=hashlib.sha256()
            with t.extractfile(video.name) as f:
                for block in iter(lambda:f.read(8*1024*1024),b''):archived.update(block)
            if archived.hexdigest()!=expected_sha256:raise ValueError('master changed during packaging')
            with t.extractfile('REMOTE-INTEGRITY.json') as f:
                archived_integrity=json.load(f)
            if archived_integrity!=data:raise ValueError('integrity changed during packaging')
            with t.extractfile('thumbnail.jpg') as f:
                if hashlib.sha256(f.read()).hexdigest()!=thumbnail_sha256:raise ValueError('thumbnail changed during packaging')
        subprocess.run(['openssl','enc','-aes-256-cbc','-pbkdf2','-salt','-pass','env:VOICEFREE_PASS',
                        '-in',str(plain),'-out',str(output)],check=True,capture_output=True)
    print('Exact native master sealed; this does not approve or schedule it')


def main():
    p=argparse.ArgumentParser();p.add_argument('--video',required=True);p.add_argument('--thumbnail',required=True);p.add_argument('--integrity',required=True)
    p.add_argument('--expected-sha256',required=True);p.add_argument('--thumbnail-sha256',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();encrypt(a.video,a.thumbnail,a.integrity,a.expected_sha256,a.thumbnail_sha256,a.out)


if __name__=='__main__':main()
