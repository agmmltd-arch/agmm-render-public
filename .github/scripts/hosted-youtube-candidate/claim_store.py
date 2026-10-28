"""Candidate optimistic-CAS publishing claims; storage is supplied by caller.

No provider call occurs here. The store must persist a full versioned ledger and
reject updates based on a stale version, across all hosts. No release or retry of
an uncertain provider operation is performed automatically.
"""
from claim_contract import reserve, scheduled


class Conflict(Exception):
    pass


def reserve_atomic(store, *, attempts=4, **identity):
    if attempts < 1 or attempts > 10:
        raise ValueError('invalid contention retry bound')
    for _ in range(attempts):
        version, ledger = store.read()
        updated = reserve(ledger, **identity)
        try:
            store.compare_and_swap(version, updated)
        except Conflict:
            continue
        return identity['intent']
    raise Conflict('claim ledger remained busy; no provider call allowed')


def record_schedule_atomic(store, intent, queue_row, now, attempts=4):
    if attempts < 1 or attempts > 10:
        raise ValueError('invalid contention retry bound')
    for _ in range(attempts):
        version, ledger = store.read()
        updated = scheduled(ledger, intent, queue_row=queue_row, now=now)
        try:
            store.compare_and_swap(version, updated)
        except Conflict:
            continue
        return
    raise Conflict('claim ledger remained busy; reconcile without another upload')
