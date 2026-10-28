import base64
import json
import unittest

from claim_store import Conflict, reserve_atomic
from github_claim_store import GitHubClaimStore


class FakeGit:
    def __init__(self):
        self.head = 'old'
        self.ledger = {'schema':'agmm-publish-claims-v1','claims':[]}
        self.staged = None
    def __call__(self, method, path, body=None):
        if method == 'GET' and '/git/ref/heads/' in path: return {'object':{'sha':self.head}}
        if method == 'GET' and '/contents/' in path:
            return {'type':'file','encoding':'base64',
                    'content':base64.b64encode(json.dumps(self.ledger).encode()).decode()}
        if method == 'GET' and '/git/commits/' in path: return {'tree':{'sha':'base-tree'}}
        if method == 'POST' and path.endswith('/git/blobs'):
            self.staged = json.loads(body['content']); return {'sha':'blob'}
        if method == 'POST' and path.endswith('/git/trees'): return {'sha':'tree'}
        if method == 'POST' and path.endswith('/git/commits'):
            assert body['parents'] == [self.head]; return {'sha':'new'}
        if method == 'PATCH':
            assert body == {'sha':'new','force':False}
            self.head = 'new'; self.ledger = self.staged; return {}
        raise AssertionError((method,path))


class GitStoreTests(unittest.TestCase):
    def test_reservation_survives_a_fresh_store_read_and_prevents_duplicate(self):
        remote = FakeGit(); store = GitHubClaimStore(remote)
        args = dict(post_id='post', day='2026-10-29', slot='15:00',
                    master_sha256='a'*64, intent='1'*32)
        reserve_atomic(store, **args)
        with self.assertRaisesRegex(ValueError, 'already claimed'):
            reserve_atomic(GitHubClaimStore(remote), **dict(args, intent='2'*32))
        self.assertEqual(len(remote.ledger['claims']), 1)
        self.assertNotIn('post', json.dumps(remote.ledger['claims'][0].values().__repr__()))

    def test_stale_version_fails_before_write(self):
        remote = FakeGit(); store = GitHubClaimStore(remote)
        with self.assertRaises(Conflict): store.compare_and_swap('stale', remote.ledger)


if __name__ == '__main__': unittest.main()
