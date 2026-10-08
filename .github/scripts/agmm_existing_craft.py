"""Run native sheet and strict ratchet checks on an existing hosted short package."""
import contextlib, hashlib, importlib.util, io, json, os, shutil, sys
from pathlib import Path
from datetime import datetime, timezone
import render_short_package as short

def module(name, filename):
    spec=importlib.util.spec_from_file_location(name,filename)
    m=importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m)
    return m

def main():
    cfg=json.loads(Path('config.json').read_text())
    inputs=json.loads(Path('.github/agmm-review/S84-craft-inputs-1820.json').read_text())
    assert hashlib.sha256(Path('.github/agmm-review/S84-craft-inputs-1820.json').read_bytes()).hexdigest()==cfg['craft_inputs_sha256']
    root=Path('native/v2').resolve(); kit=root/'kit'; out=kit/'out'/cfg['id']; out.mkdir(parents=True)
    src=Path('exact-input/source.tar.gz'); short.verify_hash(src,cfg['transport_sha256'],'transport source')
    project=Path('exact-input/project').resolve(); short.safe_extract(src,project)
    for p in cfg['parts']: short.validate_sha_file(project,p['look'])
    for rel,expected in cfg['text_bindings'].items(): assert short.sha256(project/rel)==expected, 'Hosted package differs from frozen current '+rel
    receipt=json.loads(Path('snaps/SNAP-RECEIPT.json').read_text())
    assert receipt['source_sha256']==cfg['transport_sha256'] and str(receipt['run_id'])==str(cfg['snap_run_id'])
    (out/'snap').symlink_to(Path('snaps').resolve(),target_is_directory=True)
    (out/'build').mkdir(); (out/'build/pkg').symlink_to(project,target_is_directory=True)
    (out/'build/parts.json').write_text(json.dumps({'parts':cfg['parts']}))
    (out/'resolved.json').write_text(json.dumps(inputs['resolved']))
    (out/'domlint').mkdir(); shutil.copyfile('dom/raw.json',out/'domlint/raw.json')
    (out/'audio').mkdir(); (out/'audio/cues.json').write_text(json.dumps(inputs['cues']))
    voice=root/'shorts/voice'/cfg['id']; voice.mkdir(parents=True); (voice/'RESULT.json').write_text(json.dumps(inputs['voice_result']))
    if inputs['seam'] is not None: (out/'seam_check.json').write_text(json.dumps(inputs['seam']))
    framepath=root/'kit/platforms'; framepath.mkdir(parents=True); (framepath/'frames.json').write_text(json.dumps(inputs['frames']))
    (root/'jev-v2/fit').mkdir(parents=True); (root/'jev-v2/fit/routing.json').write_text(json.dumps(inputs['routing']))
    cl=Path('native/craft-learning').resolve(); cl.mkdir(parents=True); (cl/'scoreboard.json').write_text(json.dumps(inputs['scoreboard']))
    scripts=Path('.github/scripts').resolve()
    platform=module('platforms',scripts/'agmm_native_platforms.py'); platform.HERE=str(framepath); platform.FRAMES=str(framepath/'frames.json'); platform.ROUTING=str(root/'jev-v2/fit/routing.json')
    module('gate',scripts/'agmm_static_native_gate.py')
    dom=module('dom_lint',scripts/'agmm_native_dom_lint.py')
    sheet=module('native_sheet',scripts/'agmm_native_sheet_check.py'); sheet.KIT=str(kit)
    result=sheet.check(cfg['id'],'snap')
    bind={'at':datetime.now(timezone.utc).isoformat(),'source_hash':cfg['source_hash'],'package_sha256':cfg['package_sha256'],
          'transport_sha256':cfg['transport_sha256'],'current_text_bindings_verified':True,'backend':'public Ubuntu Actions',
          'run_id':os.environ['GITHUB_RUN_ID'],'scope':'Native pre-render source checks; encoded master and independent perception still required'}
    result.update(bind); Path('result').mkdir(); Path('result/sheet-result.json').write_text(json.dumps(result,indent=2)+'\n')
    metrics=module('craft_metrics',scripts/'agmm_native_craft_metrics.py'); metrics.V2=str(root); metrics.KIT=str(kit)
    better=module('native_better',scripts/'agmm_native_better_than_last.py'); better.CL=str(cl); better.V2=str(root); better.KIT=str(kit)
    sys.argv=['better_than_last.py',cfg['id'],'--strict','--json']
    buffer=io.StringIO()
    with contextlib.redirect_stdout(buffer): rc=better.main()
    ratchet=json.loads(buffer.getvalue()); ratchet.update(bind); ratchet['native_exit_code']=rc
    Path('result/strict-result.json').write_text(json.dumps(ratchet,indent=2)+'\n')
    print(json.dumps({'sheet_ok':result['ok'],'sheet_fails':result['fails'],'sheet_warns':result['warns'],
                      'strict_verdict':ratchet['strict_verdict'],'strict_failures':ratchet['strict_failures']}))
    return 1 if not result['ok'] or rc else 0

if __name__=='__main__': raise SystemExit(main())
