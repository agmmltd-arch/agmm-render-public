"""Pure claim rules for an append-only hosted publishing ledger.

The caller must persist the complete updated ledger with an atomic compare-and-swap
before contacting Studio. This module is a candidate, not an active publisher.
"""
import hashlib
import re

from queue_contract import HEX, london_slot


def token(kind, value):
    return hashlib.sha256((kind + '\0' + value).encode('utf-8')).hexdigest()


def reserve(ledger, *, post_id, day, slot, master_sha256, film_id, intent):
    if ledger.get('schema') != 'agmm-publish-claims-v2' or not isinstance(ledger.get('claims'), list):
        raise ValueError('invalid claim ledger')
    if not post_id or not re.fullmatch(r'[a-f0-9]{32}', intent or ''):
        raise ValueError('missing post identity or random intent')
    if not HEX.fullmatch(master_sha256 or ''):
        raise ValueError('invalid master pin')
    if not isinstance(film_id, str) or not re.fullmatch(r'[SF][0-9]+', film_id):
        raise ValueError('invalid film identity')
    when = london_slot(day, slot)
    identity = {'post': token('post', post_id), 'slot': token('slot', 'youtube\0' + when.isoformat()),
                'master': token('master', master_sha256), 'film': token('film', film_id)}
    for row in ledger['claims']:
        if (not isinstance(row, dict) or row.get('state') not in ('RESERVED', 'SCHEDULED')
                or not re.fullmatch(r'[a-f0-9]{32}', row.get('intent', ''))
                or any(not HEX.fullmatch(row.get(k, '')) for k in ('post', 'slot', 'master', 'film'))):
            raise ValueError('invalid existing claim; refuse publishing')
        if row.get('intent') == intent or any(row.get(k) == v for k, v in identity.items()):
            raise ValueError('post, slot, master, film or intent already claimed')
    return {'schema': ledger['schema'], 'claims': ledger['claims'] + [
        dict(identity, intent=intent, state='RESERVED')]}


def scheduled(ledger, intent, *, queue_row, now):
    from hosted_route import hosted_route_result
    result = hosted_route_result(queue_row, now)
    if not result or result['status'] not in ('scheduled_awaiting_public', 'hosted_schedule_due_requires_publication_receipt'):
        raise ValueError('verified provider receipt required')
    rows = ledger.get('claims', [])
    hits = [i for i, row in enumerate(rows) if row.get('intent') == intent]
    if len(hits) != 1 or rows[hits[0]].get('state') != 'RESERVED':
        raise ValueError('one reserved intent required')
    row = rows[hits[0]]
    when = london_slot(queue_row['date'], queue_row['slot'])
    if (row['post'] != token('post', queue_row['post_id'])
            or row['slot'] != token('slot', 'youtube\0' + when.isoformat())
            or row['master'] != token('master', queue_row['video_sha256'])
            or row['film'] != token('film', queue_row['film_id'])):
        raise ValueError('provider receipt does not match reserved claim')
    updated = [dict(row) for row in rows]
    updated[hits[0]]['state'] = 'SCHEDULED'
    return {'schema': ledger['schema'], 'claims': updated}
