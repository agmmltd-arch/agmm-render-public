import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import claim_cli
from test_queue_contract import row, RECEIPT


class Store:
    def __init__(self):self.version=0;self.ledger={'schema':'agmm-publish-claims-v1','claims':[]}
    def read(self):return self.version,self.ledger
    def compare_and_swap(self,version,ledger):
        assert version==self.version
        self.version+=1;self.ledger=ledger


class ClaimCLITests(unittest.TestCase):
    def test_held_to_receipt_bound_schedule(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'held').write_text(json.dumps(row()));(p/'armed').write_text(json.dumps(row(provider_receipt=RECEIPT)))
            store=Store()
            def call(op,source):
                with patch.object(claim_cli,'GitHubClaimStore',return_value=store), \
                     patch.object(sys,'argv',['claim_cli',op,'--row',str(p/source),'--intent-file',str(p/'intent')]):
                    claim_cli.main()
            call('reserve','held');self.assertEqual(store.ledger['claims'][0]['state'],'RESERVED')
            call('record','armed');self.assertEqual(store.ledger['claims'][0]['state'],'SCHEDULED')
            with self.assertRaises(ValueError):call('reserve','held')


if __name__=='__main__':unittest.main()
