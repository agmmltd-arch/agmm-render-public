"""Candidate GitHub-backed CAS store on a dedicated, pre-provisioned branch.

Only hashed claim identifiers are persisted. No branch is created automatically;
an absent or invalid ledger fails closed. This module never contacts Studio.
"""
import base64
import json
import os
import urllib.error
import urllib.request

from claim_store import Conflict


class GitHubClaimStore:
    REPO = 'agmmltd-arch/agmm-render-public'
    BRANCH = 'agmm-publishing-claims'
    PATH = 'publish-ledger/state.json'

    def __init__(self, request=None):
        self._request = request or self._api

    @staticmethod
    def _api(method, path, body=None):
        token = os.environ.get('GH_TOKEN')
        if not token:
            raise RuntimeError('GH_TOKEN unavailable')
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request('https://api.github.com/' + path, data=data, method=method,
            headers={'Accept':'application/vnd.github+json', 'Authorization':'Bearer ' + token,
                     'Content-Type':'application/json', 'X-GitHub-Api-Version':'2022-11-28'})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if method == 'PATCH' and exc.code in (409, 422):
                raise Conflict('ledger ref changed or update refused') from None
            raise RuntimeError('GitHub ledger API HTTP %d' % exc.code) from None

    def read(self):
        base = 'repos/' + self.REPO
        ref = self._request('GET', base + '/git/ref/heads/' + self.BRANCH)
        version = ref['object']['sha']
        item = self._request('GET', base + '/contents/' + self.PATH + '?ref=' + version)
        if item.get('encoding') != 'base64' or item.get('type') != 'file':
            raise ValueError('ledger file unavailable')
        ledger = json.loads(base64.b64decode(item['content'], validate=False))
        if ledger.get('schema') != 'agmm-publish-claims-v2' or not isinstance(ledger.get('claims'), list):
            raise ValueError('invalid ledger')
        return version, ledger

    def compare_and_swap(self, version, ledger):
        base = 'repos/' + self.REPO
        current = self._request('GET', base + '/git/ref/heads/' + self.BRANCH)['object']['sha']
        if current != version:
            raise Conflict('ledger ref changed')
        parent = self._request('GET', base + '/git/commits/' + version)
        payload = json.dumps(ledger, sort_keys=True, separators=(',', ':')) + '\n'
        blob = self._request('POST', base + '/git/blobs', {'content':payload,'encoding':'utf-8'})['sha']
        tree = self._request('POST', base + '/git/trees', {'base_tree':parent['tree']['sha'],
            'tree':[{'path':self.PATH,'mode':'100644','type':'blob','sha':blob}]})['sha']
        commit = self._request('POST', base + '/git/commits', {'message':'Reserve publishing intent',
            'tree':tree,'parents':[version]})['sha']
        self._request('PATCH', base + '/git/refs/heads/' + self.BRANCH,
                      {'sha':commit,'force':False})
