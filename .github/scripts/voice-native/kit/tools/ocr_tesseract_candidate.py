#!/usr/bin/env python3
"""Candidate Ubuntu OCR adapter; NOT qualified as a replacement for Vision.

Returns the existing line-box JSON shape. It is intentionally not wired into
production: detection and bounding-box parity must first be assessed on held-out
approved and deliberately clipped material on Ubuntu.
"""
import csv,io,json,subprocess,sys
from collections import OrderedDict

def parse_tsv(tsv):
    lines=OrderedDict()
    for row in csv.DictReader(io.StringIO(tsv),delimiter='\t'):
        if row.get('level')!='5' or not (row.get('text') or '').strip():continue
        try:
            conf=float(row['conf']); x=int(row['left']); y=int(row['top']); w=int(row['width']); h=int(row['height'])
        except (ValueError,KeyError):raise ValueError('invalid OCR TSV')
        if conf<0 or w<=0 or h<=0:continue
        key=tuple(row[k] for k in ('page_num','block_num','par_num','line_num'))
        lines.setdefault(key,[]).append({'text':row['text'].strip(),'x':x,'y':y,'w':w,'h':h,'conf':max(0.0,min(1.0,conf/100.0))})
    result=[]
    for words in lines.values():
        x=min(w['x'] for w in words);y=min(w['y'] for w in words)
        right=max(w['x']+w['w'] for w in words);bottom=max(w['y']+w['h'] for w in words)
        result.append({'text':' '.join(w['text'] for w in words),'x':x,'y':y,'w':right-x,'h':bottom-y,
                       'conf':sum(w['conf'] for w in words)/len(words)})
    return result

def main(paths):
    if not sys.platform.startswith('linux'):raise SystemExit('candidate runs only on hosted Ubuntu')
    from PIL import Image
    for path in paths:
        try:
            with Image.open(path) as image:w,h=image.size
            p=subprocess.run(['tesseract',path,'stdout','-l','eng','--psm','11','tsv'],capture_output=True,text=True,check=True)
            print(json.dumps({'file':path,'w':w,'h':h,'lines':parse_tsv(p.stdout)}))
        except Exception as error:
            print(json.dumps({'file':path,'error':str(error)[:200]}))
            return 1
    return 0
if __name__=='__main__':sys.exit(main(sys.argv[1:]))
