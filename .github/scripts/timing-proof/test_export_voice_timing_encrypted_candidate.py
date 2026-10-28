import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from test_export_voice_timing import TimingExportTests
from export_voice_timing_encrypted_candidate import export

class EncryptedTimingTests(unittest.TestCase):
    def fixture(self, root, unsafe=False):
        args = list(TimingExportTests().make(root))
        with zipfile.ZipFile(args[4]) as z:
            receipt = z.read('RECEIPT.json')
            words = z.read('generated/S123.words.json')
        tarpath = root / 'source.tar'
        with tarfile.open(tarpath, 'w') as tar:
            for name, data in [('RECEIPT.json', receipt), ('generated/S123.words.json', words), ('generated/S123.wav', b'synthetic')]:
                item = tarfile.TarInfo(name); item.size = len(data); tar.addfile(item, io.BytesIO(data))
            if unsafe:
                item = tarfile.TarInfo('generated/link'); item.type = tarfile.SYMTYPE; item.linkname = '/etc/passwd'; tar.addfile(item)
        encrypted = root / 'voice.enc'
        subprocess.run(['openssl','enc','-aes-256-cbc','-pbkdf2','-pass','env:VOICEFREE_PASS','-in',str(tarpath),'-out',str(encrypted)], check=True)
        with zipfile.ZipFile(args[4], 'w') as z: z.write(encrypted, 'voice-generated.enc')
        digest = 'sha256:' + hashlib.sha256(args[4].read_bytes()).hexdigest()
        args[0]['artifact_digest'] = args[2]['digest'] = digest
        args[0]['request'] = {'selection_producer': {'run_id': 'synthetic'}}
        args[2]['name'] += '-ENC'
        return args
    def test_extracts_only_bound_timing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'VOICEFREE_PASS':'synthetic-test', 'GITHUB_ACTIONS':'true'}), patch('export_voice_timing_encrypted_candidate.sys.platform', 'linux'):
            root = Path(tmp); args = self.fixture(root); out = root / 'out'
            export(*args, out)
            self.assertEqual({p.name for p in out.iterdir()}, {'S123.words.json','TIMING-RECEIPT.json'})
            self.assertFalse(json.loads((out / 'TIMING-RECEIPT.json').read_text())['release_approval'])
    def test_rejects_tampered_or_unsafe_archives(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'VOICEFREE_PASS':'synthetic-test', 'GITHUB_ACTIONS':'true'}), patch('export_voice_timing_encrypted_candidate.sys.platform', 'linux'):
            root = Path(tmp); args = self.fixture(root, unsafe=True)
            with self.assertRaises(ValueError): export(*args, root / 'out')
            args[0]['artifact_digest'] = args[2]['digest'] = 'sha256:' + '0'*64
            with self.assertRaises(ValueError): export(*args, root / 'out')

if __name__ == '__main__': unittest.main()
