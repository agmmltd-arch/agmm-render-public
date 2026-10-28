#!/usr/bin/env python3
"""One isolated hosted race with synthetic identities; never calls a platform."""
import concurrent.futures
import json
import subprocess
import uuid

from claim_store import Conflict, reserve_atomic
from github_claim_store import GitHubClaimStore


def request(method, path, body=None):
    args = ['gh','api','-X',method,path]
    if body is not None: args += ['--input','-']
    p = subprocess.run(args, input=json.dumps(body) if body is not None else None,
                       text=True, capture_output=True)
    if p.returncode:
        if method == 'PATCH' and ('422' in p.stderr or '409' in p.stderr): raise Conflict()
        raise RuntimeError('GitHub test request failed: ' + p.stderr[:200])
    return json.loads(p.stdout) if p.stdout.strip() else {}


def main():
    base = 'repos/' + GitHubClaimStore.REPO
    branch = 'candidate-claims-test-' + uuid.uuid4().hex[:12]
    parent = request('GET',base+'/git/ref/heads/main')['object']['sha']
    tree = request('GET',base+'/git/commits/'+parent)['tree']['sha']
    initial = json.dumps({'schema':'agmm-publish-claims-v1','claims':[]})
    blob = request('POST',base+'/git/blobs',{'content':initial,'encoding':'utf-8'})['sha']
    tree = request('POST',base+'/git/trees',{'base_tree':tree,'tree':[
        {'path':GitHubClaimStore.PATH,'mode':'100644','type':'blob','sha':blob}]})['sha']
    head = request('POST',base+'/git/commits',{'message':'Isolated synthetic claim test',
        'tree':tree,'parents':[parent]})['sha']
    request('POST',base+'/git/refs',{'ref':'refs/heads/'+branch,'sha':head})
    def attempt(n):
        store = GitHubClaimStore(request); store.BRANCH = branch
        try:
            reserve_atomic(store, post_id='synthetic-test',day='2026-11-03',slot='15:00',
                           master_sha256='a'*64,intent=('%032x' % n))
            return 'reserved'
        except ValueError:
            return 'duplicate-refused'
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt,[1,2]))
        store = GitHubClaimStore(request); store.BRANCH = branch
        _, ledger = store.read()
        if sorted(results) != ['duplicate-refused','reserved'] or len(ledger['claims']) != 1:
            raise RuntimeError('race did not produce exactly one persistent claim')
        print(json.dumps({'branch':branch,'results':sorted(results),'claims':len(ledger['claims']),
                          'production_scheduler_changed':False}))
    finally:
        request('DELETE',base+'/git/refs/heads/'+branch)


if __name__ == '__main__': main()
