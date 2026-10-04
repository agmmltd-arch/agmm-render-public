#!/usr/bin/env python3
"""Add bounded, sanitized S83 text receipts and bind the final packet."""
import argparse, hashlib, json, shutil
from pathlib import Path

NAMES={'SOURCE-CLOCK-RECEIPT.json','MIX-QUALITY-RECEIPT.json','PROTECTED-INPUT-VERIFICATION.json','RUNTIME-RECEIPT.json'}
def main():
 p=argparse.ArgumentParser(); p.add_argument('--packet',required=True,type=Path); p.add_argument('--receipts',required=True,type=Path); a=p.parse_args()
 for name in NAMES:
  src=a.receipts/name
  if src.is_symlink() or not src.is_file(): raise ValueError('required text receipt missing: '+name)
  obj=json.loads(src.read_text())
  if obj.get('schema') is None: raise ValueError('invalid receipt schema: '+name)
  shutil.copyfile(src,a.packet/name)
 rows=[]
 for f in sorted(a.packet.iterdir()):
  if f.name=='SHA256SUMS.txt': continue
  if f.is_symlink() or not f.is_file(): raise ValueError('packet contains non-file entry')
  rows.append(f'{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}')
 (a.packet/'SHA256SUMS.txt').write_text('\n'.join(rows)+'\n')
 print('S83_PRODUCTION_PACKET_SEALED added_text_receipts=4')
if __name__=='__main__': main()
