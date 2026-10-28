#!/usr/bin/env python3
"""Return minimal, exact-bound build metadata; never approve or post content.

This pure validator handles metadata only. The caller must first verify the
producer run and verify the provider artifact digest before decrypting it on Ubuntu.
"""
import argparse
import io
import json
import os
import platform
import re
import subprocess
import tarfile
from pathlib import Path


def public_metadata(receipt, *, run_id, runtime_commit, expected_id, request_sha256, approved_hash):
    if (receipt.get('status') != 'NATIVE_PACKAGE_ENCRYPTED_NOT_UPLOADED'
        or str(receipt.get('run_id')) != str(run_id)
        or receipt.get('runtime_commit') != runtime_commit
        or receipt.get('id') != expected_id
        or receipt.get('request_sha256') != request_sha256
        or receipt.get('approved_hash') != approved_hash
        or receipt.get('release_approved') is not False
        or receipt.get('content_posted') is not False
        or receipt.get('render_dispatched') is not False):
        raise ValueError('build receipt is not bound to this request')
    if not re.fullmatch(r'[SC][0-9]{2,3}', expected_id or ''):
        raise ValueError('invalid build identity')
    for value in (request_sha256, approved_hash):
        if not re.fullmatch(r'[a-f0-9]{64}', value or ''):
            raise ValueError('invalid text binding')
    exact = receipt.get('exact_request') or {}
    if (exact.get('id') != expected_id or (exact.get('approval') or {}).get('approved_hash') != approved_hash
        or exact.get('editorial_status') != 'NOT_REVIEWED'):
        raise ValueError('native package identity or review status differs')
    hashes = {}
    for key in ('source', 'parts', 'mix'):
        value = ((exact.get('inputs') or {}).get(key) or {}).get('sha256')
        if not re.fullmatch(r'[a-f0-9]{64}', value or ''):
            raise ValueError('missing package digest')
        hashes[key + '_sha256'] = value
    return {'id': expected_id, 'run_id': str(run_id), 'runtime_commit': runtime_commit,
            'request_sha256': request_sha256, 'approved_hash': approved_hash,
            **hashes, 'release_approval': False, 'content_posted': False}


def receipt_from_tar(data):
    if len(data) > 20_000_000:
        raise ValueError('metadata archive too large')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
        entries = archive.getmembers()
        if (not entries or any(not (m.isfile() or m.isdir()) or
                not m.name.startswith('native-build-json') or '..' in Path(m.name).parts for m in entries)):
            raise ValueError('unsafe metadata archive')
        found = [m for m in entries if m.isfile() and m.name == 'native-build-json/PACKAGE-RECEIPT.json']
        if len(found) != 1 or found[0].size > 2_000_000:
            raise ValueError('missing or duplicated receipt')
        return json.load(archive.extractfile(found[0]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--id', required=True)
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--approved-hash', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Linux' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('hosted Ubuntu Actions required')
    if args.metadata.is_symlink() or not args.metadata.is_file() or args.metadata.stat().st_size > 20_000_000:
        raise ValueError('invalid provider metadata')
    data = subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-pass',
                           'env:VOICEFREE_PASS', '-in', str(args.metadata)], capture_output=True, check=True).stdout
    receipt = receipt_from_tar(data)
    commit = 'eba9dff89f1c06e232f948d07e45601f019b1fa1'
    result = public_metadata(receipt, run_id=args.run_id, runtime_commit=commit, expected_id=args.id,
                             request_sha256=args.request_sha256, approved_hash=args.approved_hash)
    import verify_build_producer
    verify_build_producer.verify(args.run_id, args.metadata,
                                 {k: result[k + '_sha256'] for k in ('source', 'parts', 'mix')})
    if args.output.exists() or args.output.is_symlink():
        raise ValueError('output already exists')
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
