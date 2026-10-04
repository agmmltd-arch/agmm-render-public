#!/usr/bin/env python3
"""Payload guard regression tests: positive control plus archive, renamed media, and unsafe path negatives."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from public_payload_guard import FILM, PayloadError, validate_tree

FAKE_RENDER=b"\x00\x00\x00\x18ftypisom"+b"rendered-review-picture"*3
FAKE_PNG=b"\x89PNG\r\n\x1a\n"+b"test pixels"
FAKE_JPEG=b"\xff\xd8\xff"+b"test sheet\xff\xd9"

def safe_tree(root:Path):
    (root/"stills").mkdir(parents=True)
    (root/"contact-sheets").mkdir()
    (root/"receipts").mkdir()
    (root/FILM).write_bytes(FAKE_RENDER)
    for i in range(31): (root/"stills"/f"native-{i:02d}.png").write_bytes(FAKE_PNG)
    for i in range(1,19): (root/"contact-sheets"/f"sheet-{i:03d}.jpg").write_bytes(FAKE_JPEG)
    texts={
      "SOURCE-RECEIPT.json": {"all_raw_source_media_excluded":True},
      "FINAL-VIDEO-RECEIPT.json": {"sha256":hashlib.sha256(FAKE_RENDER).hexdigest()},
      "HYPERFRAMES-CHECK-SUMMARY.json": {"ok":True},
      "FRAME-COUNT.txt": "837 frames\n",
      "FRAME-REVIEW-INDEX.csv": "frame,time\n0,0.0\n",
      "BLACK-FREEZE-SCAN.txt": "No events reported.\n",
      "PREIMAGE-GATE.md": "31 stills\n",
      "PUBLIC-PAYLOAD-GUARD-RECEIPT.txt": "PASS\n",
    }
    for name,value in texts.items():
        p=root/"receipts"/name
        p.write_text(json.dumps(value) if isinstance(value,dict) else value,encoding="utf-8")

class PublicPayloadGuardTests(unittest.TestCase):
    def test_exact_synchronized_review_allowlist_passes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);safe_tree(root)
            result=validate_tree(root,blocked_hashes=set(),expected_film_sha256=hashlib.sha256(FAKE_RENDER).hexdigest())
            self.assertEqual((result["files"],result["stills"],result["contact_sheets"]),(58,31,18))

    def test_raw_archive_is_rejected_even_with_text_extension(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);safe_tree(root)
            (root/"receipts"/"SOURCE-RECEIPT.json").write_bytes(b"\x1f\x8b"+b"raw private archive bytes")
            with self.assertRaises(PayloadError):
                validate_tree(root,blocked_hashes=set(),expected_film_sha256=hashlib.sha256(FAKE_RENDER).hexdigest())

    def test_unlisted_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);safe_tree(root)
            (root/"private-project.tar.gz").write_bytes(b"\x1f\x8b"+b"raw private archive bytes")
            with self.assertRaises(PayloadError):
                validate_tree(root,blocked_hashes=set(),expected_film_sha256=hashlib.sha256(FAKE_RENDER).hexdigest())

    def test_renamed_raw_video_is_rejected_even_with_image_extension(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);safe_tree(root)
            (root/"stills"/"native-00.png").write_bytes(b"\x00\x00\x00\x18ftypisom"+b"raw pexels source")
            with self.assertRaises(PayloadError):
                validate_tree(root,blocked_hashes=set(),expected_film_sha256=hashlib.sha256(FAKE_RENDER).hexdigest())

    def test_unsafe_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);safe_tree(root)
            (root/"receipts"/"outside.txt").symlink_to("/etc/passwd")
            with self.assertRaises(PayloadError):
                validate_tree(root,blocked_hashes=set(),expected_film_sha256=hashlib.sha256(FAKE_RENDER).hexdigest())

    def test_unsafe_fifo_is_rejected(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);safe_tree(root)
            os.mkfifo(root/"receipts"/"fifo.txt")
            with self.assertRaises(PayloadError):
                validate_tree(root,blocked_hashes=set(),expected_film_sha256=hashlib.sha256(FAKE_RENDER).hexdigest())

    def test_raw_source_bytes_cannot_masquerade_as_synchronized_film(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);safe_tree(root)
            raw=b"\x00\x00\x00\x18ftypisom"+b"exact raw source payload"
            (root/FILM).write_bytes(raw)
            with self.assertRaises(PayloadError):
                validate_tree(root,blocked_hashes={hashlib.sha256(raw).hexdigest()},expected_film_sha256=hashlib.sha256(raw).hexdigest())

if __name__=="__main__": unittest.main(verbosity=2)
