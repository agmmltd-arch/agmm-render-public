#!/usr/bin/env python3
"""Authenticated encryption for hosted render parts and review artifacts."""
import argparse
import hashlib
import hmac
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

MAGIC=b'AGMM-RENDER-SEALED-v1\n'; LIMIT=20_000_000_000


def host():
    if platform.system()!='Linux' or os.environ.get('GITHUB_ACTIONS','').lower() not in ('true','1'):
        raise RuntimeError('render artifact handling requires hosted Linux Actions')
    password=os.environ.get('VOICEFREE_PASS');tmp=os.environ.get('RUNNER_TEMP')
    if not password or not tmp:raise ValueError('hosted encryption context unavailable')
    return password.encode(),tmp


def valid(name):
    p=PurePosixPath(name)
    return not p.is_absolute() and bool(p.parts) and all(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9._-]*',x) and x not in ('.','..') for x in p.parts)


def seal(directory, output):
    password,tmp=host();directory=Path(directory);output=Path(output)
    if directory.is_symlink() or not directory.is_dir() or output.exists() or output.is_symlink():raise ValueError('invalid input or existing output')
    files=[]
    for p in directory.rglob('*'):
        if p.is_symlink():raise ValueError('symlink forbidden')
        if p.is_file():
            rel=p.relative_to(directory).as_posix()
            if not valid(rel):raise ValueError('unsafe artifact name')
            files.append((p,rel))
        elif not p.is_dir():raise ValueError('special artifact forbidden')
    if not files or len(files)>3000 or sum(p.stat().st_size for p,_ in files)>LIMIT:raise ValueError('artifact size or file count invalid')
    with tempfile.TemporaryDirectory(prefix='agmm-render-',dir=tmp) as d:
        archive=Path(d)/'bundle.tar'; cipher=Path(d)/'bundle.enc'
        with tarfile.open(archive,'w:') as t:
            for p,rel in sorted(files,key=lambda item:item[1]):t.add(p,arcname=rel,recursive=False)
        with tarfile.open(archive,'r:') as t:
            members=t.getmembers()
            if len(members)!=len(files) or any(not m.isfile() or not valid(m.name) for m in members):raise ValueError('unsafe archive')
        subprocess.run(['openssl','enc','-aes-256-cbc','-pbkdf2','-salt','-pass','env:VOICEFREE_PASS',
                        '-in',str(archive),'-out',str(cipher)],capture_output=True,check=True)
        salt=os.urandom(16); key=hashlib.pbkdf2_hmac('sha256',password,b'agmm-render-mac-v1'+salt,200_000)
        mac=hmac.new(key,MAGIC+salt,hashlib.sha256)
        with output.open('xb') as dst,cipher.open('rb') as src:
            dst.write(MAGIC+salt)
            for block in iter(lambda:src.read(8*1024*1024),b''):mac.update(block);dst.write(block)
            dst.write(mac.digest())
    print('Hosted render artifacts encrypted and authenticated')


def unseal(archive, output):
    password,tmp=host();archive=Path(archive);output=Path(output)
    if archive.is_symlink() or not archive.is_file() or output.exists() or output.is_symlink():raise ValueError('invalid input or existing output')
    size=archive.stat().st_size; headerlen=len(MAGIC)+16
    if size<headerlen+32 or size>LIMIT+100_000_000:raise ValueError('invalid envelope size')
    with tempfile.TemporaryDirectory(prefix='agmm-render-',dir=tmp) as d:
        cipher=Path(d)/'bundle.enc';plain=Path(d)/'bundle.tar'
        with archive.open('rb') as src,cipher.open('xb') as dst:
            header=src.read(headerlen)
            if len(header)!=headerlen or not header.startswith(MAGIC):raise ValueError('invalid envelope header')
            salt=header[len(MAGIC):];key=hashlib.pbkdf2_hmac('sha256',password,b'agmm-render-mac-v1'+salt,200_000)
            mac=hmac.new(key,header,hashlib.sha256);remaining=size-headerlen-32
            while remaining:
                chunk=src.read(min(8*1024*1024,remaining))
                if not chunk:raise ValueError('truncated envelope')
                mac.update(chunk);dst.write(chunk);remaining-=len(chunk)
            tag=src.read(32)
            if not hmac.compare_digest(mac.digest(),tag):raise ValueError('artifact authentication failed')
        subprocess.run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-pass','env:VOICEFREE_PASS',
                        '-in',str(cipher),'-out',str(plain)],capture_output=True,check=True)
        with tarfile.open(plain,'r:') as t:
            members=t.getmembers(); names=[m.name for m in members]
            if not members or len(members)>3000 or len(set(names))!=len(names) or sum(m.size for m in members)>LIMIT or any(not m.isfile() or not valid(m.name) for m in members):
                raise ValueError('unsafe authenticated artifact')
            output.mkdir(mode=0o700)
            for member in members:
                dest=output.joinpath(*PurePosixPath(member.name).parts);dest.parent.mkdir(parents=True,exist_ok=True)
                with t.extractfile(member) as src,dest.open('xb') as dst:shutil.copyfileobj(src,dst,1024*1024)
    print('Hosted render artifacts authenticated and opened')


def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=('seal','unseal'));p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();(seal if a.operation=='seal' else unseal)(a.input,a.out)


if __name__=='__main__':main()
