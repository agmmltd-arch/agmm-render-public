import unittest
from datetime import datetime, timezone

from claim_contract import reserve, scheduled
from claim_store import Conflict, reserve_atomic
from test_queue_contract import row, RECEIPT


class ClaimTests(unittest.TestCase):
    def test_older_ledger_is_not_silently_upgraded(self):
        with self.assertRaisesRegex(ValueError, 'invalid claim ledger'):
            reserve({'schema':'agmm-publish-claims-v1','claims':[]}, post_id='x', day='2026-10-29',
                    slot='15:00', master_sha256='a'*64, film_id='F04', intent='1'*32)

    def test_concurrent_duplicate_loser_must_reread_and_refuse(self):
        class Store:
            def __init__(self):
                self.ledger = {'schema':'agmm-publish-claims-v2','claims':[]}
                self.version = 0
            def read(self): return self.version, self.ledger
            def compare_and_swap(self, version, updated):
                if self.version == 0:
                    self.ledger = updated
                    self.version = 1
                    raise Conflict('other worker committed the same claim')
                self.ledger = updated
        store = Store()
        with self.assertRaisesRegex(ValueError, 'already claimed'):
            reserve_atomic(store, post_id='id-1', day='2026-10-29', slot='15:00',
                           master_sha256='a'*64, film_id='F04', intent='1'*32)
        self.assertEqual(len(store.ledger['claims']), 1)

    def test_duplicate_is_refused_even_if_prior_outcome_unknown(self):
        args = dict(post_id='id-1', day='2026-10-29', slot='15:00',
                    master_sha256='a'*64, film_id='F04', intent='1'*32)
        held = reserve({'schema':'agmm-publish-claims-v2','claims':[]}, **args)
        for change in ({'intent':'2'*32}, {'post_id':'id-2','intent':'2'*32},
                       {'post_id':'id-2','slot':'16:00','intent':'2'*32}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                reserve(held, **dict(args, **change))
        self.assertEqual(held['claims'][0]['state'], 'RESERVED')
        with self.assertRaisesRegex(ValueError, 'already claimed'):
            reserve(held, **dict(args, post_id='id-3', slot='17:00', master_sha256='b'*64, intent='3'*32))

    def test_only_verified_provider_receipt_finishes_claim(self):
        held = reserve({'schema':'agmm-publish-claims-v2','claims':[]}, post_id='20261005-1500-F04',
                       day='2026-10-05', slot='15:00', master_sha256='a'*64, film_id='F04', intent='1'*32)
        now = datetime(2026,10,5,12,0,tzinfo=timezone.utc)
        with self.assertRaises(ValueError): scheduled(held, '1'*32, queue_row={}, now=now)
        approved = row(provider_receipt=RECEIPT)
        self.assertEqual(scheduled(held, '1'*32, queue_row=approved, now=now)['claims'][0]['state'], 'SCHEDULED')
        approved['post_id']='wrong'
        with self.assertRaisesRegex(ValueError, 'does not match'): scheduled(held, '1'*32, queue_row=approved, now=now)


if __name__ == '__main__': unittest.main()
