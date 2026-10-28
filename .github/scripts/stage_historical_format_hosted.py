#!/usr/bin/env python3
"""Stage a protected historical S357 format test on Ubuntu; never approve."""
import hashlib,json,os,re,subprocess,sys
from pathlib import Path

COMMON_TEXT={'kit/registry/fetched-images.json','kit/registry/images.json','kit/registry/format-engine.json','kit/registry/engine-weights.json','kit/registry/queue.json','sound/music.json','sound/library.json'}
def git_blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def text_allowed(name,sid):
 return name in COMMON_TEXT or name=='kit/specs/'+sid+'/story.json' or bool(re.fullmatch(r'kit/specs/'+sid+r'/media/clauses/[A-Za-z0-9_.-]+\.json',name)) or bool(re.fullmatch(r'kit/registry/storyboards/[A-Z][A-Z0-9_-]*\.json',name)) or bool(re.fullmatch(r'kit/specs/[A-Z][A-Z0-9_-]*/concept\.json',name))
def image_allowed(name,sid):
 return name=='kit/assets/cache/logos/amazon.png' or bool(re.fullmatch(r'kit/specs/'+sid+r'/media/clauses/[A-Za-z0-9_.-]+\.png',name))
def stage(private,coordinates,v2,require_host=True):
 if require_host and not (sys.platform.startswith('linux') and os.environ.get('GITHUB_ACTIONS')=='true'):raise ValueError('hosted Ubuntu required')
 root=Path(private);target=Path(v2);prefix=coordinates['prefix'];commit=coordinates['commit']
 match=re.fullmatch(r'format-hosted-inputs/test-(S357|S317)-[0-9]+',prefix)
 if not match or not re.fullmatch(r'[0-9a-f]{40}',commit):raise ValueError('unsafe test coordinates')
 sid=match.group(1)
 if subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()!=commit:raise ValueError('private test commit differs')
 base=root/prefix;raw=(base/'MANIFEST.json').read_bytes()
 if git_blob(raw)!=coordinates['manifest_blob']:raise ValueError('private test manifest differs')
 m=json.loads(raw);rows=m.get('git_files') or []
 paths={r['path'] for r in rows};images=paths-{'TEXT-BUNDLE.json'}
 if m.get('schema')!='agmm-format-historical-test-input-v1' or m.get('id')!=sid or len(paths)!=len(rows) or 'TEXT-BUNDLE.json' not in paths or not images or not all(image_allowed(x,sid) for x in images):raise ValueError('unexpected private test input')
 tree={}
 for line in subprocess.check_output(['git','-C',str(root),'ls-tree','-r','-l','HEAD','--',prefix+'/'],text=True).splitlines():
  info,name=line.split('\t',1);mode,kind,sha,size=info.split();tree[name]=(mode,kind,sha,int(size))
 if set(tree)!={prefix+'/MANIFEST.json'}|{prefix+'/'+r['path'] for r in rows}:raise ValueError('private test tree differs')
 if tree[prefix+'/MANIFEST.json']!=('100644','blob',coordinates['manifest_blob'],len(raw)):raise ValueError('test manifest Git entry differs')
 data={}
 for row in rows:
  rel=row['path'];p=base/rel
  if tree[prefix+'/'+rel]!=('100644','blob',row['git_blob_sha'],row['bytes']) or p.is_symlink() or not p.is_file() or p.stat().st_size!=row['bytes']:raise ValueError('test Git input differs')
  value=p.read_bytes()
  if git_blob(value)!=row['git_blob_sha']:raise ValueError('test source bytes differ')
  data[rel]=value
 bundle=json.loads(data.pop('TEXT-BUNDLE.json'));texts=bundle.get('files') or {}
 if bundle.get('schema')!='agmm-format-test-text-bundle-v1' or not (COMMON_TEXT|{'kit/specs/'+sid+'/story.json'})<=set(texts) or not all(text_allowed(k,sid) for k in texts):raise ValueError('text bundle inventory differs')
 if len(texts)!=len(m.get('text_files') or []) or {r['path'] for r in m['text_files']}!=set(texts):raise ValueError('test text manifest differs')
 recorded={r['path']:r for r in m['text_files']}
 for name,value in texts.items():
  if not isinstance(value,str):raise ValueError('non-text test input')
  json.loads(value);data[name]=value.encode()
  if len(data[name])!=recorded[name]['bytes']:raise ValueError('test text length differs')
 for rel in data:
  dest=target/rel
  if target.is_symlink() or any((target/Path(*Path(rel).parts[:i])).is_symlink() for i in range(1,len(Path(rel).parts))):raise ValueError('linked test input ancestor')
  if dest.exists() and (dest.is_symlink() or not dest.is_file() or dest.read_bytes()!=data[rel]):raise ValueError('test input would overwrite runtime')
 for rel,value in data.items():
  dest=target/rel
  if dest.exists():continue
  dest.parent.mkdir(parents=True,exist_ok=True)
  with dest.open('xb') as f:f.write(value)
 return {'status':'EXACT_HISTORICAL_TEST_INPUTS_STAGED','text_count':len(texts),'image_count':len(images),'production_approval':False}
