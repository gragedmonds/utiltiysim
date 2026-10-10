"""Terminal provider evidence releases cash without inventing a payment/refund."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jsonschema
import pytest
from test_world_customer_finance import ack, advance, receipt, setup
from test_world_network_faults import world

from utilsim.world import World
from utilsim.world import customer_finance as finance


def failure(w, intent, **overrides):
    return receipt(w, intent, 'failure-1', schemaVersion=finance.RECEIPT_VERSION_2,
                   status='failed', **overrides)


def amounts(w):
    view = finance.inspect(w, 'P1')
    return tuple(view[k] for k in ('cashCents', 'reservedCashCents', 'netSettledCashCents', 'knownOutstandingCents'))


def dump(w):
    with w.db() as db:
        return '\n'.join(db.iterdump())


def test_terminal_failure_releases_only_reservation_and_later_day_can_retry(tmp_path):
    w = world(tmp_path)
    intent = setup(w)
    failed = failure(w, intent)
    result = finance.provider_receipt(w, failed)
    assert amounts(w) == (10000, 0, 0, 9000)
    assert finance.ready(w)['items'][0]['intent'] == intent
    with w.db() as db:
        assert db.execute('SELECT payment_state FROM customer_finance_intents').fetchone()[0] == 'failed'
        event = db.execute('SELECT type,payload FROM events WHERE id=?', (result['eventId'],)).fetchone()
        assert event['type'] == 'CustomerPaymentFailed'
        assert json.loads(event['payload']) == failed
    w = World(w.path)
    before = dump(w)
    assert finance.provider_receipt(w, failed) == result
    assert dump(w) == before
    advance(w)
    second = finance.ready(w)['items'][1]['intent']
    assert second['id'] != intent['id'] and second['amountCents'] == 4000
    assert amounts(w) == (10000, 4000, 0, 9000)
    # Retrying the old provider receipt must not release the new reservation.
    assert finance.provider_receipt(w, failed) == result
    finance.provider_receipt(w, receipt(w, second, 'new-settlement'))
    assert amounts(w) == (6000, 0, 4000, 5000)


def test_failure_then_lost_transport_ack_preserves_provider_deduplication(tmp_path):
    w = world(tmp_path)
    intent = setup(w)
    failed = failure(w, intent)
    provider_results = []

    def provider(message):
        assert message == intent
        provider_results.append(finance.provider_receipt(w, failed))
        if len(provider_results) == 1:
            raise ConnectionError('lost after terminal provider decision')
        return ack(message)

    assert finance.relay(w, provider)['error'] == 'ConnectionError'
    assert amounts(w) == (10000, 0, 0, 9000)
    w = World(w.path)
    assert finance.relay(w, provider)['accepted'] == 1
    assert provider_results[0] == provider_results[1]
    assert amounts(w) == (10000, 0, 0, 9000)


@pytest.mark.parametrize('change', [
    {'schemaVersion': finance.RECEIPT_VERSION}, {'status': 'timeout'}, {'amountCents': 1},
    {'amountCents': True}, {'intentFingerprint': 'wrong'}, {'intentId': 'unknown'},
    {'environmentId': 'elsewhere'}, {'runId': 'elsewhere'}, {'worldFingerprint': 'wrong'},
    {'occurredAt': '2026-01-01T00:00:00Z'}, {'occurredAt': '2026-03-01T00:00:00Z'},
    {'settlementReceiptId': 'something'}, {'extra': 'unsupported'},
])
def test_invalid_failure_leaves_entire_database_unchanged(tmp_path, change):
    w = world(tmp_path)
    intent = setup(w)
    payload = {**failure(w, intent), **change}
    before = dump(w)
    with pytest.raises(ValueError):
        finance.provider_receipt(w, payload)
    assert dump(w) == before


def test_duplicate_failure_conflicts_and_later_settlement_return_are_rejected(tmp_path):
    w = world(tmp_path)
    intent = setup(w)
    failed = failure(w, intent)
    finance.provider_receipt(w, failed)
    before = dump(w)
    for payload in (
        {**failed, 'receiptId': 'different-failure'},
        {**failed, 'amountCents': 1},
        receipt(w, intent),
        receipt(w, intent, schemaVersion=finance.RECEIPT_VERSION_2),
        receipt(w, intent, 'return', status='returned', settlementReceiptId='failure-1'),
    ):
        with pytest.raises(ValueError):
            finance.provider_receipt(w, payload)
        assert dump(w) == before


@pytest.mark.parametrize('returned', [False, True])
def test_failure_cannot_refund_settled_or_returned_cash(tmp_path, returned):
    w = world(tmp_path)
    intent = setup(w)
    finance.provider_receipt(w, receipt(w, intent))
    if returned:
        finance.provider_receipt(w, receipt(w, intent, 'return', status='returned', settlementReceiptId='settlement-1'))
    before = dump(w)
    with pytest.raises(ValueError):
        finance.provider_receipt(w, failure(w, intent))
    assert dump(w) == before


def test_failure_rolls_back_if_event_recording_is_interrupted(tmp_path, monkeypatch):
    w = world(tmp_path)
    intent = setup(w)
    payload = failure(w, intent)
    before = dump(w)
    original = w.event

    def interrupt(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('process interrupted before commit')

    monkeypatch.setattr(w, 'event', interrupt)
    with pytest.raises(RuntimeError):
        finance.provider_receipt(w, payload)
    assert dump(w) == before
    finance.provider_receipt(World(w.path), payload)
    assert amounts(w) == (10000, 0, 0, 9000)


def test_concurrent_conflicting_provider_decisions_have_one_cash_transition(tmp_path):
    w = world(tmp_path)
    intent = setup(w)
    payloads = [failure(w, intent), receipt(w, intent)]

    def submit(payload):
        try:
            finance.provider_receipt(World(w.path), payload)
            return payload['status']
        except ValueError:
            return 'rejected'

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, payloads))
    assert results.count('rejected') == 1
    assert amounts(w) == ((10000, 0, 0, 9000) if 'failed' in results else (6000, 0, 4000, 5000))


def test_v2_schema_and_existing_full_settlement_return_behavior(tmp_path):
    w = world(tmp_path)
    intent = setup(w)
    schema = json.loads((Path(__file__).parents[1] / 'schemas/customer-finance-provider-receipt-2.schema.json').read_text(encoding='utf-8-sig'))
    settled = receipt(w, intent, schemaVersion=finance.RECEIPT_VERSION_2)
    returned = receipt(w, intent, 'return', schemaVersion=finance.RECEIPT_VERSION_2,
                       status='returned', settlementReceiptId='settlement-1')
    for payload in (failure(w, intent), settled, returned):
        jsonschema.validate(payload, schema, format_checker=jsonschema.FormatChecker())
    for payload in ({**failure(w, intent), 'settlementReceiptId': 'invalid'},
                    {**returned, 'settlementReceiptId': None}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(payload, schema)
    finance.provider_receipt(w, settled)
    assert amounts(w) == (6000, 0, 4000, 5000)
    finance.provider_receipt(w, returned)
    assert amounts(w) == (10000, 0, 0, 9000)
