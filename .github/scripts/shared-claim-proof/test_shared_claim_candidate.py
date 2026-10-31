import threading
import unittest
from shared_claim_candidate import reserve, reserve_atomic
from claim_store import Conflict

BASE = {'schema': 'agmm-cross-platform-claims-v1', 'baseline_sha256': 'c' * 64, 'claims': []}

def identity(platform, film, master, intent):
    return dict(platform=platform, post_id=platform + '-post', film_id=film,
                master_sha256=master, original_master_sha256=master, day='2026-11-01', slot='10:00',
                intent=intent, baseline_sha256='c' * 64)

class Store:
    def __init__(self):
        self.version, self.ledger, self.lock = 0, BASE, threading.Lock()
    def read(self):
        with self.lock:
            return self.version, self.ledger
    def compare_and_swap(self, version, ledger):
        with self.lock:
            if version != self.version:
                raise Conflict()
            self.version += 1
            self.ledger = ledger

class TestShared(unittest.TestCase):
    def test_identity_and_baseline(self):
        held = reserve(BASE, **identity('youtube', 'S100', 'a' * 64, '1' * 32))
        for other in (identity('tiktok', 'S100', 'b' * 64, '2' * 32),
                      identity('tiktok', 'S101', 'a' * 64, '2' * 32)):
            with self.assertRaises(ValueError):
                reserve(held, **other)
        derivative = identity('tiktok', 'S101', 'b' * 64, '2' * 32)
        derivative['original_master_sha256'] = 'a' * 64
        with self.assertRaises(ValueError):
            reserve(held, **derivative)
        other = identity('tiktok', 'S101', 'b' * 64, '2' * 32)
        self.assertEqual(len(reserve(held, **other)['claims']), 2)
        other['baseline_sha256'] = 'd' * 64
        with self.assertRaises(ValueError):
            reserve(held, **other)

    def test_concurrent_cross_platform_film(self):
        store, outcomes, gate = Store(), [], threading.Barrier(2)
        def work(platform, master, intent):
            gate.wait()
            try:
                reserve_atomic(store, **identity(platform, 'S100', master, intent))
                outcomes.append('reserved')
            except ValueError:
                outcomes.append('refused')
        workers = [threading.Thread(target=work, args=('youtube', 'a' * 64, '1' * 32)),
                   threading.Thread(target=work, args=('tiktok', 'b' * 64, '2' * 32))]
        for worker in workers: worker.start()
        for worker in workers: worker.join()
        self.assertCountEqual(outcomes, ['reserved', 'refused'])

if __name__ == '__main__': unittest.main()
