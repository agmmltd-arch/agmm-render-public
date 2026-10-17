#!/usr/bin/env python3
"""Exact S66 cursor-label seal using the existing hosted source-seal owner."""
from __future__ import annotations
import argparse, copy, gzip, hashlib, io, json, os, platform, tarfile
from pathlib import Path, PurePosixPath
import seal_s86_cta as archive

TAG = 'short-s66-d1482b2b30c0a1b584a6d3aea177b28fae73eb329d8fa4d58286ff2206487570'
RELEASE_ID = 411255158
NODE_ID = 'RE_kwDOU05Rms4Yg0F2'
ASSETS = {
    'source.tar.gz': (635838753, 11576618, '8d2ad2f65a82d715a31a1ac83adcbe74164de1fa19fc03db625e90d459efd678'),
    'parts.json': (635838751, 548, 'e22b09a28d8d04ab115ca89897a86d5fa7a373a2e0cb36a218a8e8f63e050fe5'),
    'mix.wav': (635838758, 15782502, '7f1bd76f112c05ab1bc2c8f69e9e66318f27e92129e9e338dfd21d3725d0b160'),
}
BEFORE = '4f458a12904c46423330b1247f66e4ce856bc40dd362787ec97a29f1f2b411d7'
AFTER = '6a3b4cfdcbbd1fbcea90d38bc8b90c2265d749cf88eca70bdfc6daa11833478c'
ANCHOR = b'      c.style.left = (x + (offX || 0)).toFixed(1) + "px"; c.style.top = (y + (offY || 0)).toFixed(1) + "px";'
ADDITION = (b'\n      // Instagram text-safe rail starts at x=881; allow the parent 1.02 push and 10px drift.\n'
            b'      if (label === "AGENT") tg.style.left = Math.min(58, 850 - x - (offX || 0) - tg.offsetWidth) + "px";')
PARTS = [{'look': 's66-'+letter.lower(), 'file': 'index.html', 'out': 'S66-'+letter,
          'off': offset, 'dur': 13.7} for letter, offset in zip('ABCD', [0.0, 13.7, 27.4, 41.1])]
DEPENDENCIES = {
    'seal_s86_cta.py': '02571680773620f63b12a66a44f5986cc14d7a1ccf9737a936134cc694c91839',
    'render_short_package.py': '2c7db0660522368489697d48220d8832e3f84b070d946e2f83133b4eb4114028',
    'dom_lint_runner.mjs': '24192a80e4c4334d699faa81c0aa52dc45048c6523d8a96f0cc39d140381c859',
}
require, sha = archive.require, archive.sha

def validate_parent(row):
    require((row.get('id'), row.get('node_id'), row.get('tag_name'), row.get('draft')) ==
            (RELEASE_ID, NODE_ID, TAG, False), 'original S66 release identity drift')
    rows = row.get('assets'); require(isinstance(rows, list), 'asset list absent')
    require(len(rows) == 3 and {x.get('name') for x in rows} == set(ASSETS), 'original S66 asset set drift')
    for asset in rows:
        aid, size, digest = ASSETS[asset['name']]
        require((asset.get('id'), asset.get('size'), asset.get('digest'), asset.get('state')) ==
                (aid, size, 'sha256:'+digest, 'uploaded'), 'original S66 asset metadata drift')

def check_dependencies(root):
    for name, digest in DEPENDENCIES.items():
        require(sha((root/name).read_bytes()) == digest, 'reviewed runtime dependency drift: '+name)

def transform(payloads):
    """Pure text-only transformation; caller verifies the immutable full archive first."""
    before = dict(payloads)
    changed = []
    for part in PARTS:
        prefix = part['look']; key = prefix+'/sig/scenes1.js'; sums = prefix+'/SHA256SUMS.txt'
        archive._verify_sums(prefix, payloads, sums)
        old = payloads.get(key)
        require(isinstance(old, bytes) and sha(old) == BEFORE and old.count(ANCHOR) == 1, 'original S66 helper drift: '+key)
        new = old.replace(ANCHOR, ANCHOR+ADDITION, 1)
        require(sha(new) == AFTER, 'candidate helper bytes differ from independently qualified source')
        old_line = (BEFORE+'  ./sig/scenes1.js').encode()
        require(payloads[sums].count(old_line) == 1, 'S66 helper checksum entry ambiguous')
        payloads[key] = new
        payloads[sums] = payloads[sums].replace(old_line, (AFTER+'  ./sig/scenes1.js').encode(), 1)
        archive._verify_sums(prefix, payloads, sums)
        changed.extend([key, sums])
    require(sorted(k for k in payloads if payloads[k] != before[k]) == sorted(changed), 'unexpected archive member changed')
    return before, changed

def seal(parent, output, *, env=None, system=None):
    archive.require_hosted(os.environ if env is None else env, platform.system() if system is None else system)
    check_dependencies(Path(__file__).resolve().parent)
    require(not output.exists(), 'output already exists; preserve/reconcile prior attempt')
    for name, (_, size, digest) in ASSETS.items():
        p = parent/name
        require(p.is_file() and p.stat().st_size == size and sha(p.read_bytes()) == digest, 'original S66 input drift: '+name)
    parts = json.loads((parent/'parts.json').read_text())
    require(parts.get('parts') == PARTS and parts.get('frames') == 1644 and
            parts.get('sha256') == ASSETS['source.tar.gz'][2] and parts.get('bytes') == ASSETS['source.tar.gz'][1],
            'original S66 timeline/source binding drift')
    with tarfile.open(parent/'source.tar.gz', 'r:gz') as tf:
        members, payloads = archive._inventory(tf)
    require(len(members) == 349 and sum(m.isfile() for m in members) == 304, 'original full package inventory drift')
    before, changed = transform(payloads)
    output.mkdir(parents=True)
    with (output/'source.tar.gz').open('xb') as file:
        with gzip.GzipFile(filename='', fileobj=file, mode='wb', mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as tf:
                for m in members:
                    item = copy.copy(m); data = payloads[str(PurePosixPath(m.name))]
                    if item.isfile(): item.size = len(data); tf.addfile(item, io.BytesIO(data))
                    else: tf.addfile(item)
    source = output/'source.tar.gz'; parts['sha256'] = sha(source.read_bytes()); parts['bytes'] = source.stat().st_size
    (output/'parts.json').write_text(json.dumps(parts, indent=2)+'\n')
    # The final mix is copied byte-for-byte, without generating/normalising voice, SFX or music.
    (output/'mix.wav').write_bytes((parent/'mix.wav').read_bytes())
    receipt = {
        'kind': 's66_cursor_source_seal', 'schema': 1, 'id': 'S66',
        'parent': {'release': TAG, 'id': RELEASE_ID, 'node_id': NODE_ID, 'assets': ASSETS},
        'workflow': {k: os.environ.get(k) for k in ('GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')},
        'changed_members': changed, 'before_helper_sha256': BEFORE, 'after_helper_sha256': AFTER,
        'corrected': {name: {'sha256': sha((output/name).read_bytes()), 'bytes': (output/name).stat().st_size}
                      for name in ASSETS},
        'inventory': [{'path': k, 'before_sha256': sha(before[k]) if isinstance(before[k], bytes) else None,
                       'after_sha256': sha(payloads[k]) if isinstance(payloads[k], bytes) else None}
                      for k in sorted(payloads)],
        'editorial_status': 'NOT_REVIEWED', 'approval': 'NOT_GRANTED', 'public_posting': 'NOT_REQUESTED',
        'next': 'Fresh source-bound hosted DOM, storyboard/precheck review, render/gate/master evaluation and independent whole-master review remain required.'}
    require(receipt['corrected']['mix.wav']['sha256'] == ASSETS['mix.wav'][2], 'mix was changed')
    (output/'source-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt

def main():
    archive.require_hosted(os.environ, platform.system())
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='command', required=True)
    p=sub.add_parser('validate-parent');p.add_argument('metadata', type=Path)
    p=sub.add_parser('seal');p.add_argument('--parent', type=Path, required=True);p.add_argument('--output', type=Path, required=True)
    a=ap.parse_args()
    if a.command == 'validate-parent': validate_parent(json.loads(a.metadata.read_text()));print('exact original S66 release metadata PASS')
    else: print(json.dumps(seal(a.parent, a.output)['corrected'], sort_keys=True))
if __name__ == '__main__': main()
