import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_queue_contract import APPROVAL, RECEIPT, MASTER, META, THUMB


class ReconcileTests(unittest.TestCase):
    def test_receipt_uses_original_slot_even_after_it_has_passed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, value in [('approval', APPROVAL), ('receipt', RECEIPT), ('rows', [])]:
                (root / name).write_text(json.dumps(value))
            cmd = [sys.executable, 'hosted_queue_cli.py', '--approval', str(root/'approval'),
                   '--receipt', str(root/'receipt'), '--existing-rows', str(root/'rows'),
                   '--source-run-id', '123456789', '--artifact-name', 'example',
                   '--video-name', 'MASTER.mp4', '--master-sha256', MASTER,
                   '--metadata-sha256', META, '--caption-sha256', 'e'*64,
                   '--thumbnail-sha256', THUMB, '--date', '2026-10-05',
                   '--candidate-slots', '["15:00", "19:00"]', '--post-id', 'example',
                   '--out', str(root/'out')]
            absent = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(absent.returncode, 0)
            good = subprocess.run(cmd + ['--selected-slot', '15:00'], capture_output=True, text=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(json.loads((root/'out').read_text())['slot'], '15:00')
            wrong = subprocess.run(cmd + ['--selected-slot', '19:00'], capture_output=True, text=True)
            self.assertNotEqual(wrong.returncode, 0)


if __name__ == '__main__':
    unittest.main()
