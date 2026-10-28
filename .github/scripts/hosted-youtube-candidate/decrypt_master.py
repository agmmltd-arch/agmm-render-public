#!/usr/bin/env python3
"""Hosted-only extraction of an encrypted two-file approved-master package."""
import argparse
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


def extract(archive, output, video):
    if platform.system() != 'Linux' or os.environ.get('GITHUB_ACTIONS','').lower() not in ('true','1'):
        raise RuntimeError('master extraction is restricted to hosted Linux Actions')
    if not os.environ.get('VOICEFREE_PASS'):
        raise ValueError('encrypted master key unavailable')
    if not re.fullmatch(r'[A-Za-z0-9._-]+\.mp4',video or ''):
        raise ValueError('invalid master basename')
    archive=Path(archive); output=Path(output)
    if archive.is_symlink() or not archive.is_file() or output.exists():
        raise ValueError('invalid archive or existing output')
    with tempfile.TemporaryDirectory(prefix='agmm-master-',dir=os.environ['RUNNER_TEMP']) as d:
        plain=Path(d)/'master.tar'
        subprocess.run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-pass','env:VOICEFREE_PASS',
                        '-in',str(archive),'-out',str(plain)],check=True,capture_output=True)
        with tarfile.open(plain,'r:') as t:
            members=t.getmembers(); expected={video,'REMOTE-INTEGRITY.json'}
            if len(members)!=2 or {m.name for m in members}!=expected or any(not m.isfile() for m in members):
                raise ValueError('encrypted master package contents invalid')
            for m in members:
                if m.size<1 or m.size>(1_000_000 if m.name=='REMOTE-INTEGRITY.json' else 20_000_000_000):
                    raise ValueError('invalid master package size')
            output.mkdir(mode=0o700)
            for m in members:
                with t.extractfile(m) as src,(output/m.name).open('xb') as dst:
                    shutil.copyfileobj(src,dst,1024*1024)
    print('Encrypted master package extracted on hosted runner; byte verification still required')


def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--out',required=True);p.add_argument('--video',required=True)
    a=p.parse_args();extract(a.archive,a.out,a.video)


if __name__=='__main__':main()
