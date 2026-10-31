"""Candidate cross-platform CAS reservation; never creates or seeds a ledger."""
import base64
import json
import re
from claim_contract import token
from claim_store import Conflict
from github_claim_store import GitHubClaimStore
from queue_contract import HEX, london_slot

SCHEMA = 'agmm-cross-platform-claims-v1'
PLATFORMS = frozenset(('youtube', 'tiktok', 'instagram', 'facebook', 'linkedin'))


def reserve(ledger, *, platform, post_id, film_id, master_sha256, original_master_sha256, day, slot, intent, baseline_sha256):
    if (not isinstance(ledger, dict) or ledger.get('schema') != SCHEMA
            or not isinstance(ledger.get('claims'), list) or not HEX.fullmatch(baseline_sha256 or '')
            or ledger.get('baseline_sha256') != baseline_sha256):
        raise ValueError('reconciled shared history baseline unavailable')
    if (platform not in PLATFORMS or not isinstance(post_id, str) or not post_id.strip()
            or not isinstance(film_id, str) or not re.fullmatch(r'[SF][0-9]+', film_id)
            or not HEX.fullmatch(master_sha256 or '') or not HEX.fullmatch(original_master_sha256 or '')
            or not re.fullmatch(r'[a-f0-9]{32}', intent or '')):
        raise ValueError('invalid claim identity')
    when = london_slot(day, slot)
    identity = {'post': token('post', platform + '\0' + post_id),
                'slot': token('slot', platform + '\0' + when.isoformat()),
                'film': token('film', film_id), 'master': token('master', master_sha256),
                'original_master': token('master', original_master_sha256)}
    for row in ledger['claims']:
        if (not isinstance(row, dict) or row.get('state') not in ('RESERVED', 'SCHEDULED', 'VERIFIED_PUBLIC')
                or not re.fullmatch(r'[a-f0-9]{32}', row.get('intent', ''))
                or any(not HEX.fullmatch(row.get(k, '')) for k in identity)):
            raise ValueError('malformed claim history')
        if (row['intent'] == intent or any(row[k] == identity[k] for k in ('post', 'slot', 'film'))
                or {row['master'], row['original_master']} & {identity['master'], identity['original_master']}):
            raise ValueError('post, slot, film, master or intent already claimed')
    updated = dict(ledger)
    updated['claims'] = ledger['claims'] + [dict(identity, intent=intent, state='RESERVED')]
    return updated


class SharedClaimStore(GitHubClaimStore):
    BRANCH = 'agmm-cross-platform-publishing-claims'
    PATH = 'publish-ledger/shared-state.json'

    def read(self):
        base = 'repos/' + self.REPO
        ref = self._request('GET', base + '/git/ref/heads/' + self.BRANCH)
        version = ref['object']['sha']
        item = self._request('GET', base + '/contents/' + self.PATH + '?ref=' + version)
        if item.get('encoding') != 'base64' or item.get('type') != 'file':
            raise ValueError('shared claim history unavailable')
        ledger = json.loads(base64.b64decode(item['content'], validate=False))
        if ledger.get('schema') != SCHEMA or not isinstance(ledger.get('claims'), list):
            raise ValueError('invalid shared claim history')
        return version, ledger


def reserve_atomic(store, *, attempts=4, **identity):
    if not 1 <= attempts <= 10:
        raise ValueError('invalid contention bound')
    for _ in range(attempts):
        version, ledger = store.read()
        updated = reserve(ledger, **identity)
        try:
            store.compare_and_swap(version, updated)
        except Conflict:
            continue
        return identity['intent']
    raise Conflict('shared claim contention; no provider call allowed')
