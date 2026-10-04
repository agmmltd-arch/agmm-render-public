#!/usr/bin/env python3
"""Stage only the named, sanitized Film05 review payload; never copy a source tree."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
from public_payload_guard import FILM, PayloadError, make_public_payload

def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--evidence",type=Path,required=True)
    ap.add_argument("--scratch",type=Path,required=True)
    ap.add_argument("--project",type=Path,required=True)
    ap.add_argument("--source-manifest",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    result=make_public_payload(evidence=args.evidence,scratch=args.scratch,project=args.project,manifest=args.source_manifest,output=args.output)
    print("PUBLIC_PAYLOAD_ALLOWLIST_PASS "+json.dumps(result,sort_keys=True))

if __name__=="__main__": main()
