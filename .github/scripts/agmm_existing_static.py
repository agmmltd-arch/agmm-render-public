"""Measure a complete existing native snap grid on Ubuntu with frozen native rules."""
import ast, hashlib, importlib.util, json, math, os, re, sys
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import render_short_package as short

def native_function(path, name):
    source=Path(path).read_text()
    fn=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name)
    ns={'np':np,'gate':type('NativeGate',(),{})()}
    for key,value in [('STATIC_SAMPLE_WIDTH',320),('STATIC_SAMPLE_FPS',10),('STATIC_DIFF_PCT_THRESHOLD',0.4),('STATIC_MAX_SPAN',{'short':1.5})]:
        ns[key]=value
        setattr(ns['gate'],key,value)
    return fn,ns

def main():
    cfg=json.loads(Path('config.json').read_text())
    source=Path('exact-input/source.tar.gz')
    short.verify_hash(source,cfg['transport_sha256'],'transport source')
    project=Path('exact-input/project')
    short.safe_extract(source,project)
    for p in cfg['parts']:
        short.validate_sha_file(project,p['look'])
    for rel,expected in cfg['text_bindings'].items():
        assert short.sha256(project/rel)==expected, 'Hosted source differs from frozen current '+rel
    receipt=json.loads(Path('snaps/SNAP-RECEIPT.json').read_text())
    assert receipt['source_sha256']==cfg['transport_sha256']
    assert str(receipt['run_id'])==str(cfg['snap_run_id'])
    duration=max(p['off']+p['dur'] for p in cfg['parts'])
    count=math.ceil(duration*10-1e-8)
    selected={}
    for p in cfg['parts']:
        names=receipt['parts'][p['out']]
        for name in names:
            if not name.startswith('frame-'):
                continue
            m=re.search(r'at-([\d.]+)s',name)
            assert m,'No sample timestamp'
            t=p['off']+float(m.group(1)); index=round(t*10)
            assert 0<=index<count and abs(t-index/10)<0.015,'Irregular grid'
            assert index not in selected,'Duplicate sample'
            selected[index]=Path('snaps')/p['out']/name
    assert set(selected)==set(range(count)), 'Incomplete full 0.1 second grid'
    gate_src=Path('native_gate.py').read_text()
    pre_src=Path('native_static_precheck.py').read_text()
    assert hashlib.sha256(gate_src.encode()).hexdigest()==cfg['native_gate_sha256']
    assert hashlib.sha256(pre_src.encode()).hexdigest()==cfg['native_precheck_sha256']
    fn,ns=native_function('native_gate.py','static_hold_spans')
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'native_gate.py','exec'),ns)
    ns['gate'].static_hold_spans=ns['static_hold_spans']
    fn=next(n for n in ast.parse(pre_src).body if isinstance(n,ast.FunctionDef) and n.name=='measure')
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'native_static_precheck.py','exec'),ns)
    result=ns['measure']([selected[i] for i in range(count)])
    result.update(id=cfg['id'],at=datetime.now(timezone.utc).isoformat(),source_hash=cfg['source_hash'],
                  package_sha256=cfg['package_sha256'],transport_sha256=cfg['transport_sha256'],
                  complete_grid=True,duration_s=duration,backend='public Ubuntu Actions; all sampling and measurement hosted',
                  snap_run_id=cfg['snap_run_id'],run_id=os.environ['GITHUB_RUN_ID'],current_text_bindings_verified=True,
                  native_gate_sha256=cfg['native_gate_sha256'],native_precheck_sha256=cfg['native_precheck_sha256'],
                  scope='Source snapshots only; final encoded-master gate and independent perception still required')
    Path('result').mkdir(exist_ok=True)
    Path('result/static-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['verdict','frames','max_span_s','bad_spans','current_text_bindings_verified']}))
    dom_path=Path('.github/scripts/agmm_native_dom_lint.py').resolve()
    sys.path.insert(0,str(dom_path.parent))
    import agmm_static_native_gate as gate
    import agmm_native_platforms as platforms
    sys.modules['gate']=gate
    sys.modules['platforms']=platforms
    spec=importlib.util.spec_from_file_location('native_dom',dom_path)
    dom=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dom)
    raw=json.loads(Path('dom/raw.json').read_text())
    assert not any(d.get('errors') for d in raw['parts'].values()), 'Native DOM page errors'
    _, kinds=dom.make_plan(cfg['parts'],dom.sample_times(cfg['parts'],cfg['beats'],0.1))
    expected={(p,t) for p,t in kinds}
    actual={(p,round(s['t'],2)) for p,d in raw['parts'].items() for s in d['samples']}
    assert actual==expected, 'Missing/extra native DOM samples'
    dom_result=dom.analyze(raw,cfg['id'],cfg['profile'],0.1,kinds,cfg['parts'],'result',cfg['lint_exceptions'],str(project),False)
    dom_result.update(id=cfg['id'],at=datetime.now(timezone.utc).isoformat(),source_hash=cfg['source_hash'],
                      package_sha256=cfg['package_sha256'],transport_sha256=cfg['transport_sha256'],
                      dom_run_id=cfg['dom_run_id'],run_id=os.environ['GITHUB_RUN_ID'],current_text_bindings_verified=True,
                      backend='public Ubuntu Actions; native DOM analysis including image cards hosted')
    Path('result/dom-result.json').write_text(json.dumps(dom_result,indent=2)+'\n')
    print(json.dumps({'dom_stats':dom_result['stats']}))
    return 1 if result['verdict']=='FAIL' or dom_result['stats']['FAIL'] else 0

if __name__=='__main__':
    raise SystemExit(main())
