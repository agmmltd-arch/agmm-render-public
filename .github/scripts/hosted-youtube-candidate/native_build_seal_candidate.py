#!/usr/bin/env python3
"""Candidate replacement for the public native build package release.

Runs only after the original native build and its real approval/voice checks.
It creates a local encrypted artifact but does not upload, dispatch, or approve.
"""
import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

import build_native_short as native
from seal_build_inputs import seal


def seal_native(request, output, encrypted_output):
    native.host();native.source_closure()
    native.need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','package seal rerun refused')
    output=Path(output);receipt_path=output/'PACKAGE-RECEIPT.json';receipt=json.loads(receipt_path.read_text())
    native.need(receipt['request_sha256']==native.digest(request) and receipt['status']=='NATIVE_PACKAGE_BUILT_NOT_SEALED',
                'stale or incomplete native build receipt')
    dispatch=native.validate_owner(request)
    exact=dispatch.exact_request(request['id'],root=native.BASE)
    native.need(exact==receipt['exact_request'],'package or source changed before seal')
    native.need(dispatch._config(native.BASE/'crew/short-cloud-dispatch.json')['enabled'],
                'native dispatch configuration disabled')
    dispatch._secret_scan(exact['inputs']['source']['path'])
    keys={'source.tar.gz':'source','parts.json':'parts','mix.wav':'mix'}
    hashes={name:exact['inputs'][key]['sha256'] for name,key in keys.items()}
    with tempfile.TemporaryDirectory(prefix='agmm-native-input-',dir=os.environ['RUNNER_TEMP']) as tmp:
        for name,key in keys.items():shutil.copyfile(exact['inputs'][key]['path'],Path(tmp)/name)
        seal(tmp,hashes,encrypted_output)
    receipt.update(status='NATIVE_PACKAGE_ENCRYPTED_NOT_UPLOADED',render_dispatched=False,
                   release_approved=False,content_posted=False)
    receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
    print('Native approved-input package encrypted; provider upload not yet verified')


def main():
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--encrypted-output',type=Path,required=True)
    a=p.parse_args();seal_native(json.loads(a.request.read_text()),a.output,a.encrypted_output)


if __name__=='__main__':main()
