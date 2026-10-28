#!/usr/bin/env python3
"""Candidate hosted reservation before Studio and receipt-bound completion."""
import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from claim_store import record_schedule_atomic, reserve_atomic
from github_claim_store import GitHubClaimStore


def main():
    p=argparse.ArgumentParser(); p.add_argument('operation',choices=('reserve','record'))
    p.add_argument('--row',type=Path,required=True); p.add_argument('--intent-file',type=Path,required=True)
    a=p.parse_args(); row=json.loads(a.row.read_text()); store=GitHubClaimStore()
    if a.operation=='reserve':
        if row.get('status')!='HELD_AWAITING_PROVIDER_SCHEDULE': raise ValueError('held row required')
        if a.intent_file.exists() or a.intent_file.is_symlink(): raise ValueError('intent file already exists')
        intent=uuid.uuid4().hex
        fd=os.open(a.intent_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:
            f.write(intent+'\n'); f.flush(); os.fsync(f.fileno())
        reserve_atomic(store,post_id=row['post_id'],day=row['date'],slot=row['slot'],
                       master_sha256=row['master_sha256'],intent=intent)
        print('Reservation committed; provider operation may proceed')
    else:
        intent=a.intent_file.read_text().strip()
        record_schedule_atomic(store,intent,row,datetime.now(timezone.utc))
        print('Verified provider schedule bound to existing claim')


if __name__=='__main__':main()
