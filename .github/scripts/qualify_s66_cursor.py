#!/usr/bin/env python3
"""Fresh hosted DOM and named source-frame evidence; never editorial approval."""
from __future__ import annotations
import argparse, importlib.util, json, os, platform
from pathlib import Path
import seal_s66_cursor as seal

NATIVE_PINS = {
    'kit/tools/dom_lint.py': 'e2550cf87621c65c05a8b39d9f6822046e3c0d3dd8434b9f02efba6cf9cb7d6d',
    'kit/platforms/platforms.py': '413fcc21644943c8042543b323e4cfcd3140380998efd4dc4e2ad36916d86a1d',
    'kit/platforms/frames.json': 'cbefbbed08d8535c0da981d9dc1dfe75a71ed855e9ac03f011de5575619a2cc2',
    'qa/gate.py': 'f8fac87d55cd0813776cef03513ae155f7fd6c155e741967a42ba77cd7f8415b',
}
QA_PINS = {
    'PLAN.json': '2228a697bd80d94eb65112fadcac349685d98393839cd1710a2ed1a48d2ebca2',
    'SHOTS-PLAN.json': 'cb48166eac140a2cc5005ce49b0081b593c34da46561ead08ba224b682e1d70f',
    'PROFILE.json': '04b65c71aab4f95414f7c3f48d96b828a0c28a24a75c2bc99d080292a8e6377e',
    'QA-CONTRACT.json': 'c68dabc11223dfd7b3671faa458578ba98c944f524f84ed7d9b073a41ed82ac0',
}
require, sha = seal.require, seal.sha

def pinned(root, pins):
    for name, digest in pins.items():
        require(sha((root/name).read_bytes()) == digest, 'reviewed source/QA dependency drift: '+name)

def validate_facts(raw, plan):
    require(set(raw.get('parts', {})) == {x['part'] for x in plan}, 'fresh DOM part set differs from source plan')
    for job in plan:
        got = raw['parts'][job['part']]
        require(got.get('look') == job['look'] and got.get('errors') == [], 'page errors or wrong look: '+job['part'])
        samples = got.get('samples', [])
        require([x['t'] for x in samples] == job['times'], 'missing/extra/reordered fresh DOM samples')
        require(all(x.get('nTl', 0) > 0 for x in samples), 'missing native timeline')

def qualify(native, contract_dir, prepared, output):
    seal.archive.require_hosted(os.environ, platform.system())
    pinned(native, NATIVE_PINS);pinned(contract_dir, QA_PINS)
    request = json.loads((output/'source-receipt.json').read_text())
    require(request['after_helper_sha256'] == seal.AFTER and request['before_helper_sha256'] == seal.BEFORE,
            'source seal differs from qualified helper')
    for name, row in request['corrected'].items():
        require(sha((output/name).read_bytes()) == row['sha256'], 'corrected input drift: '+name)
    input_receipt=json.loads((prepared/'INPUT-RECEIPT.json').read_text())
    require(input_receipt['source_sha256'] == request['corrected']['source.tar.gz']['sha256'] and
            input_receipt['parts_sha256'] == request['corrected']['parts.json']['sha256'] and
            input_receipt['mix_sha256'] == request['corrected']['mix.wav']['sha256'],
            'fresh unchanged render-owner input receipt does not bind this source/parts/mix')
    contract=json.loads((contract_dir/'QA-CONTRACT.json').read_text())
    plan=json.loads((contract_dir/'PLAN.json').read_text())
    shots=json.loads((contract_dir/'SHOTS-PLAN.json').read_text())
    raw=json.loads((output/'raw.json').read_text());shot_raw=json.loads((output/'raw-shots.json').read_text())
    validate_facts(raw, plan);validate_facts(shot_raw, shots)
    spec=importlib.util.spec_from_file_location('s66_native_dom', native/'kit/tools/dom_lint.py')
    lint=importlib.util.module_from_spec(spec);spec.loader.exec_module(lint)
    profile=lint.platforms.profile('instagram_reels')
    require(profile == json.loads((contract_dir/'PROFILE.json').read_text()), 'native platform profile drift')
    parts=json.loads((output/'parts.json').read_text())['parts']
    require(parts == contract['parts'], 'parts changed story timing')
    _, kinds=lint.make_plan(parts, lint.sample_times(parts, contract['beat_starts'], .1))
    result=lint.analyze(raw, 'S66', profile, .1, kinds, parts, str(output), [], str(prepared/'project'))
    (output/'dom-result.json').write_text(json.dumps(result, indent=2)+'\n')
    require(result['stats']['FAIL'] == 0, 'fresh native DOM lint has FAIL findings; preserve full evidence')
    agent=[];first={}
    for part,data in raw['parts'].items():
        for sample in data['samples']:
            for el in sample['texts']:
                if el['t'] != 'AGENT' or not lint.shown(el):continue
                require(all(74 <= b[0] <= b[2] <= 881 and 264 <= b[1] <= b[3] <= 1666 for b in el['ink']),
                        'AGENT lies outside original Instagram text-safe rectangle')
                agent.append({'part':part,'local':sample['t'],'ink':el['ink'],'fpx':el['fpx']})
                first.setdefault(part, agent[-1])
    require(len(agent) >= 47 and {'S66-B','S66-C','S66-D'} <= set(first), 'expected actual AGENT motion evidence missing')
    for part, minimum, maximum in [('S66-B',.55,.57),('S66-C',11.66,11.68)]:
        require(minimum <= first[part]['local'] <= maximum, 'first active frame was not captured: '+part)
    expected={job['part']+'-t'+format(t,'.2f')+'.png' for job in shots for t in job['times']}
    got={p.name for p in (output/'shots').glob('*.png')}
    require(got == expected, 'named QA PNG set incomplete or has extra media')
    png=[];off={p['out']:p['off'] for p in parts}
    for job in shots:
        for t in job['times']:
            p=output/'shots'/(job['part']+'-t'+format(t,'.2f')+'.png')
            b=p.read_bytes();require(b[:8] == b'\x89PNG\r\n\x1a\n' and
                 int.from_bytes(b[16:20],'big') == 1080 and int.from_bytes(b[20:24],'big') == 1920,
                 'QA frame is not full master 1080x1920 PNG')
            png.append({'name':p.name,'part':job['part'],'local_s':t,'global_s':round(off[job['part']]+t,5),
                        'bytes':len(b),'sha256':sha(b)})
    receipt={'schema':1,'kind':'s66_fresh_hosted_source_dom_qualification',
             'workflow':request['workflow'],'source_sha256':request['corrected']['source.tar.gz']['sha256'],
             'parts_sha256':request['corrected']['parts.json']['sha256'],'mix_sha256':request['corrected']['mix.wav']['sha256'],
             'source_receipt_sha256':sha((output/'source-receipt.json').read_bytes()),
             'fresh_original_mix_and_package_preflight':input_receipt,
             'raw_sha256':sha((output/'raw.json').read_bytes()),'raw_shots_sha256':sha((output/'raw-shots.json').read_bytes()),
             'dom_result_sha256':sha((output/'dom-result.json').read_bytes()),'dom_stats':result['stats'],
             'warnings':result['findings'],'first_active_AGENT_frames':first,'actual_AGENT_samples':len(agent),
             'png':png,'native_analysis_pins':NATIVE_PINS,'qa_pins':QA_PINS,
             'mechanical_status':'PASS_WITH_WARNINGS' if result['stats']['WARN'] else 'PASS',
             'storyboard_status':'FRESH_REVIEW_REQUIRED','editorial_status':'NOT_REVIEWED',
             'audio_status':'ORIGINAL_EXACT_MIX_PRESERVED_NOT_RELISTENED',
             'master_status':'NEW_RENDER_AND_GATE_REQUIRED','publication_status':'NOT_REQUESTED'}
    (output/'qa-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt

def main():
    seal.archive.require_hosted(os.environ, platform.system())
    ap=argparse.ArgumentParser()
    for name in ('native','contract-dir','prepared','output'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();r=qualify(a.native,a.contract_dir,a.prepared,a.output)
    print(json.dumps({'dom':r['dom_stats'],'png':len(r['png']),'editorial_status':r['editorial_status']}))
if __name__ == '__main__':main()
