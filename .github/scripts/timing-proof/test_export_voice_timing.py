import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from export_voice_timing import WORKFLOW, export

class TimingExportTests(unittest.TestCase):
    def make(self, root):
        timing = b'{"words": [{"word": "test", "start": 0.1, "end": 0.3}]}'
        receipt = {'status': 'NATIVE_CHECKS_COMPLETED_REVIEW_REQUIRED', 'id': 'S123',
                   'intent': 'voice-S123-test', 'run_id': '12345', 'run_attempt': '1',
                   'runtime_commit': 'abc', 'generated': [{'path': 'S123.words.json',
                   'bytes': len(timing), 'sha256': hashlib.sha256(timing).hexdigest()}]}
        raw = json.dumps(receipt).encode()
        archive = root / 'test.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('RECEIPT.json', raw)
            z.writestr('generated/S123.words.json', timing)
            z.writestr('generated/S123.wav', b'synthetic non-media bytes')
        digest = 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest()
        pointer = {'id': 'S123', 'intent': 'voice-S123-test', 'run_id': 12345,
                   'artifact_id': 67890, 'artifact_digest': digest,
                   'receipt_sha256': hashlib.sha256(raw).hexdigest(),
                   'voice_checks_complete': True, 'producer_git_blobs': {WORKFLOW:'blob'}}
        run = {'id':12345, 'path':WORKFLOW, 'event':'workflow_dispatch', 'run_attempt':1,
               'status':'completed', 'conclusion':'success', 'head_sha':'abc'}
        artifact = {'id':67890, 'workflow_run':{'id':12345}, 'name':'voice-S123-test-GENERATED',
                    'expired':False, 'digest':digest}
        return pointer, run, artifact, {WORKFLOW:'blob'}, archive

    def test_bound_export_contains_only_timing_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); args = self.make(root); output = root / 'out'
            export(*args, output)
            self.assertEqual({p.name for p in output.iterdir()}, {'S123.words.json', 'TIMING-RECEIPT.json'})
            self.assertFalse(json.loads((output / 'TIMING-RECEIPT.json').read_text())['release_approval'])

    def test_refuses_unqualified_or_mismatched_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = self.make(root)
            for index, key, value in ((0,'voice_checks_complete',False),(1,'conclusion','failure'),
                                      (2,'expired',True),(0,'receipt_sha256','0'*64)):
                args = list(copy.deepcopy(base)); args[index][key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    export(*args, root / 'out')
            args = list(base); args[3] = {WORKFLOW:'wrong'}
            with self.assertRaises(ValueError): export(*args, root / 'out')

if __name__ == '__main__': unittest.main()
