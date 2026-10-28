#!/usr/bin/env python3
"""Verify and stage exact protected format assets on Ubuntu; no approval."""
import hashlib,json,os,re,shutil,subprocess,sys
from pathlib import Path

ALLOWED={'kit/lib/ds/fonts/sourceserif-var.woff2','kit/lib/ds/fonts/spacegrotesk-var.woff2',
'kit/lib/ds2/fonts/BigShoulders-Regular.ttf','kit/lib/ds2/fonts/BigShoulders-Bold.ttf',
'kit/lib/ds2/fonts/JetBrainsMono-Regular.ttf','kit/lib/ds2/fonts/JetBrainsMono-Bold.ttf',
'kit/lib/ds2/fonts/BigShoulders-OFL.txt','kit/lib/ds2/fonts/JetBrainsMono-OFL.txt',
'kit/registry/strategy-v3.json','kit/registry/hook-labels.json'}

def git_blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def stage(private,coordinates,v2,require_host=True):
 if require_host and not (sys.platform.startswith('linux') and os.environ.get('GITHUB_ACTIONS')=='true'):
  raise ValueError('hosted Ubuntu required')
 root=Path(private);target=Path(v2);prefix=coordinates['prefix'];commit=coordinates['commit']
 if not re.fullmatch(r'format-hosted-inputs/runtime-[0-9]+',prefix) or not re.fullmatch(r'[0-9a-f]{40}',commit):raise ValueError('invalid private coordinates')
 actual=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
 if actual!=commit:raise ValueError('protected checkout commit differs')
 base=root/prefix;raw=(base/'MANIFEST.json').read_bytes()
 if git_blob(raw)!=coordinates['manifest_blob']:raise ValueError('protected manifest differs')
 m=json.loads(raw);rows=m.get('files') or []
 if m.get('schema')!='agmm-format-runtime-inputs-v1' or len(rows)!=len(ALLOWED) or {r['runtime_path'] for r in rows}!=ALLOWED:raise ValueError('format input inventory differs')
 tree={}
 out=subprocess.check_output(['git','-C',str(root),'ls-tree','-r','-l','HEAD','--',prefix+'/'],text=True)
 for line in out.splitlines():
  info,name=line.split('\t',1);mode,kind,sha,size=info.split();tree[name]=(mode,kind,sha,int(size))
 if set(tree)!={prefix+'/MANIFEST.json'}|{prefix+'/'+r['runtime_path'] for r in rows}:raise ValueError('protected format Git inventory differs')
 if tree[prefix+'/MANIFEST.json']!=('100644','blob',coordinates['manifest_blob'],len(raw)):raise ValueError('protected format manifest Git entry differs')
 prepared=[]
 for row in rows:
  rel=row['runtime_path'];src=base/rel;dest=target/rel
  if tree[prefix+'/'+rel]!=('100644','blob',row['git_blob_sha'],row['bytes']):raise ValueError('protected format Git entry differs')
  if src.is_symlink() or not src.is_file() or src.stat().st_size!=row['bytes']:raise ValueError('protected format source invalid')
  data=src.read_bytes()
  if git_blob(data)!=row['git_blob_sha']:raise ValueError('protected format bytes changed')
  if target.is_symlink() or any((target/Path(*Path(rel).parts[:i])).is_symlink() for i in range(1,len(Path(rel).parts))):raise ValueError('linked format input ancestor')
  if dest.exists() or dest.is_symlink():raise ValueError('format input would overwrite runtime or data')
  prepared.append((src,dest))
 for src,dest in prepared:
  dest.parent.mkdir(parents=True,exist_ok=True)
  with src.open('rb') as source,dest.open('xb') as output:shutil.copyfileobj(source,output)
 return {'status':'EXACT_PROTECTED_FORMAT_INPUTS_STAGED','count':len(rows),'commit':commit,'production_approval':False}
