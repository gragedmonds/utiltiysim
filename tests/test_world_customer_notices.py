import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier

import jsonschema
import pytest
from test_world_customer_cashflow import command as cashflow_command
from test_world_customer_finance import ack, advance, delivery, receipt
from test_world_customer_finance import command as finance_command
from test_world_network_faults import world
from test_world_occupancy import schedule

from utilsim.world import World, occupancy
from utilsim.world import customer_cashflow as cashflow
from utilsim.world import customer_finance as finance
from utilsim.world import customer_notices as notices


def command(w, identity='notice-policy', **overrides):
    view = notices.inspect(w)
    return {'schemaVersion': notices.VERSION, 'commandId': identity, 'environmentId': view['environmentId'],
            'runId': view['runId'], 'worldFingerprint': view['worldFingerprint'], 'actorId': 'world-admin',
            'expectedRevision': view['revision'], 'effectiveDate': view['through'], 'action': 'configure',
            'active': True, 'noticeProbabilityPerDay': 1, 'deliveryDelaySeconds': 0,
            'repeatAfterDays': 1, 'maxContacts': 3, 'reason': 'Explicit scenario', 'causalReference': 'scenario', **overrides}


def setup(tmp_path, name='world', **overrides):
    w = world(tmp_path, name)
    finance.command(w, finance_command(w, cashCents=0, essentialReserveCents=0, **overrides))
    finance.receive_delivery(w, delivery(w))
    finance.receive_delivery(w, delivery(w, 'notice-1', kind='notice'))
    notices.command(w, command(w))
    return w


def dump(w):
    with w.db() as db:
        return '\n'.join(db.iterdump())


def items(w):
    return [item['intent'] for item in notices.ready(w)['items']]


def test_absent_feature_readonly_and_delivered_notice_required(tmp_path):
    w = world(tmp_path)
    before = dump(w)
    assert notices.ready(w)['items'] == [] and not notices.inspect(w)['enabled']
    assert dump(w) == before
    notices.command(w, command(w))
    advance(w)  # policy can precede finance without fabricating invoices or contacts
    finance.command(w, finance_command(w, cashCents=0))
    finance.receive_delivery(w, delivery(w))
    advance(w)
    assert items(w) == []
    with pytest.raises(ValueError):
        finance.receive_delivery(w, delivery(w, 'future', kind='notice', deliveredAt='2026-01-04T00:00:00Z'))
    with pytest.raises(ValueError):
        finance.receive_delivery(w, delivery(w, 'unknown', kind='notice', invoiceId='unknown'))
    finance.receive_delivery(w, delivery(w, 'notice-1', kind='notice'))
    advance(w)
    assert len(items(w)) == 1
    assert items(w)[0]['knownAt'] == '2026-01-03T00:00:00Z'
    assert items(w)[0]['noticedAt'] == '2026-01-04T00:00:00Z'


def test_duplicate_notices_do_not_reset_cap_and_schema_filters_truth(tmp_path):
    w = setup(tmp_path)
    advance(w)
    original = items(w)[0]
    finance.receive_delivery(w, delivery(w, 'notice-1', kind='notice', deliveredAt='2026-01-01T00:00:00Z'))
    finance.receive_delivery(w, delivery(w, 'notice-2', kind='notice'))
    advance(w, 5)
    messages = items(w)
    assert len(messages) == 3 and messages[0] == original
    assert {m['episodeId'] for m in messages} == {original['episodeId']}
    assert {m['deliveredDocumentId'] for m in messages} == {'notice-1'}
    assert messages[1]['previousContactId'] == messages[0]['id']
    schema = json.loads(Path('schemas/financial-contact-intent-1.schema.json').read_text())
    for message in messages:
        jsonschema.validate(message, schema)
        assert not {'amountCents', 'cashCents', 'remainingUnreservedCents', 'policy', 'occupancyStamp'} & message.keys()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**messages[0], 'cashCents': 0}, schema)


@pytest.mark.parametrize(('cash_amount', 'reserved_amount', 'expected'), [(9000, 9000, 0), (5000, 5000, 1), (10000, 4000, 0)])
def test_pending_provider_amount_is_not_counted_twice(tmp_path, cash_amount, reserved_amount, expected):
    w = world(tmp_path)
    finance.command(w, finance_command(w, cashCents=cash_amount, essentialReserveCents=0, maxPaymentCents=reserved_amount))
    finance.receive_delivery(w, delivery(w))
    advance(w)
    assert finance.inspect(w, 'P1')['reservedCashCents'] == reserved_amount
    finance.receive_delivery(w, delivery(w, 'notice', kind='notice'))
    notices.command(w, command(w))
    advance(w)
    assert len(items(w)) == expected
    assert finance.inspect(w, 'P1')['reservedCashCents'] == reserved_amount


def test_cashflow_can_remove_shortfall_before_notice_decision(tmp_path):
    w = setup(tmp_path)
    cashflow.command(w, cashflow_command(w, income={'amountCents': 10000, 'firstDate': '2026-01-01', 'intervalDays': 1},
                                        essentialExpense={'amountCents': 1000, 'firstDate': '2026-01-01', 'intervalDays': 1}))
    advance(w)
    assert items(w) == []
    assert finance.inspect(w, 'P1')['reservedCashCents'] == 4000


def test_finance_pause_is_independent_and_no_due_no_reaction(tmp_path):
    w = world(tmp_path)
    finance.command(w, finance_command(w, cashCents=0, active=False))
    for kind in ('invoice', 'notice'):
        finance.receive_delivery(w, delivery(w, kind, kind=kind, dueDate='2026-01-03'))
    notices.command(w, command(w))
    advance(w, 2)
    assert items(w) == []
    advance(w)
    assert len(items(w)) == 1 and finance.ready(w)['items'] == []


def test_settlement_return_and_extra_notice_retain_episode_attempt_budget(tmp_path):
    w = setup(tmp_path)
    advance(w)
    first = items(w)[0]
    finance.command(w, finance_command(w, 'credit', action='credit', amountCents=9000,
                                     expectedRevision=finance.inspect(w, 'P1')['revision']))
    finance.command(w, finance_command(w, 'large-payment', cashCents=9000, essentialReserveCents=0, maxPaymentCents=9000,
                                     expectedRevision=finance.inspect(w, 'P1')['revision']))
    advance(w)
    payment = finance.ready(w)['items'][0]['intent']
    finance.provider_receipt(w, receipt(w, payment))
    advance(w)
    assert len(items(w)) == 1
    finance.provider_receipt(w, receipt(w, payment, 'returned', status='returned', settlementReceiptId='settlement-1'))
    # Returned cash covers the returned balance: that alone is not a new shortfall.
    advance(w)
    assert len(items(w)) == 1
    # Spend only unreserved funds via explicit cashflow after failed new payment.
    payment2 = finance.ready(w)['items'][1]['intent']
    finance.provider_receipt(w, receipt(w, payment2, 'failed', schemaVersion=finance.RECEIPT_VERSION_2, status='failed'))
    today = notices.inspect(w)['through']
    cashflow.command(w, cashflow_command(w, income={'amountCents': 0, 'firstDate': today, 'intervalDays': 1},
                                        essentialExpense={'amountCents': 9000, 'firstDate': today, 'intervalDays': 1}))
    finance.receive_delivery(w, delivery(w, 'second-notice', kind='notice'))
    advance(w, 5)
    assert len(items(w)) == 3 and items(w)[1]['episodeId'] == first['episodeId']
    assert items(w)[1]['attempt'] == 2


def test_cohort_change_blocks_new_notices_but_preserves_delayed_contact(tmp_path):
    w = setup(tmp_path)
    notices.command(w, command(w, 'delay', deliveryDelaySeconds=172800))
    advance(w)
    assert items(w) == []
    occupancy.command(w, schedule(w, effectiveDate='2026-01-02', occupied=True, occupants=3))
    advance(w, 3)
    assert len(items(w)) == 1
    with pytest.raises(ValueError):
        finance.receive_delivery(w, delivery(w, 'new-cohort', kind='notice'))


@pytest.mark.parametrize('change', [{'active': 1}, {'actorId': 'worker'}, {'expectedRevision': 1},
                                 {'runId': 'other'}, {'worldFingerprint': 'other'}, {'effectiveDate': '2026-01-02'},
                                 {'noticeProbabilityPerDay': True}, {'noticeProbabilityPerDay': float('nan')},
                                 {'deliveryDelaySeconds': -1}, {'maxContacts': 11}, {'repeatAfterDays': 0}, {'extra': 1}])
def test_invalid_command_does_not_migrate(tmp_path, change):
    w = world(tmp_path)
    before = dump(w)
    with pytest.raises(ValueError):
        notices.command(w, command(w, **change))
    assert dump(w) == before
    assert not list(tmp_path.glob('*.pre-customer-notices-*.bak'))


def test_exact_retry_stale_revision_and_paused_generation(tmp_path):
    w = setup(tmp_path)
    old = command(w, 'pause', active=False)
    result = notices.command(w, old)
    advance(w, 3)
    assert items(w) == []
    assert notices.command(w, old) == result
    with pytest.raises(ValueError, match='Conflicting'):
        notices.command(w, {**old, 'active': True})
    with pytest.raises(ValueError, match='revision'):
        notices.command(w, command(w, 'stale', expectedRevision=1))
    notices.command(w, command(w, 'resume'))
    advance(w)
    assert len(items(w)) == 1


def test_daily_interruption_rolls_back_projection_contact_and_physical_day(tmp_path, monkeypatch):
    w = setup(tmp_path)
    before = dump(w)
    original = w.event

    def interrupt(db, env, day, kind, *args, **kwargs):
        result = original(db, env, day, kind, *args, **kwargs)
        if kind == 'CustomerFinancialContactIntended':
            raise RuntimeError('forced interruption')
        return result

    monkeypatch.setattr(w, 'event', interrupt)
    with pytest.raises(RuntimeError):
        advance(w)
    assert dump(w) == before
    advance(World(w.path))
    assert len(items(w)) == 1


def test_restart_and_reordered_delay_feed_pagination(tmp_path):
    a, b = setup(tmp_path, 'a'), setup(tmp_path, 'b')
    for w in (a, b):
        notices.command(w, command(w, 'slow', deliveryDelaySeconds=172800))
        advance(w)
        notices.command(w, command(w, 'fast', deliveryDelaySeconds=0))
    advance(a, 4)
    advance(b, 1)
    b = World(b.path)
    advance(b, 3)
    assert items(a) == items(b)
    assert [i['attempt'] for i in items(a)] == [2, 1, 3]
    fetched, cursor = [], None
    while True:
        page = notices.ready(a, after=cursor, limit=1)
        fetched.extend(i['intent'] for i in page['items'])
        cursor = page['nextAfter']
        if cursor is None:
            break
    assert fetched == items(a)
    before = dump(a)
    a.advance(notices.inspect(a)['through'])
    assert dump(a) == before
    with a.db() as db:
        plan = db.execute('EXPLAIN QUERY PLAN SELECT * FROM customer_notice_outbox WHERE (available_at,sequence)>(?,?) '
                          'AND available_at<=? ORDER BY available_at,sequence LIMIT 25', ('', 0, '2026-01-06T00:00:00Z')).fetchall()
        assert any('customer_notice_available' in r[3] for r in plan)


def test_relay_lost_ack_has_no_lock_and_acceptance_does_not_resolve_episode(tmp_path):
    w = setup(tmp_path)
    advance(w)
    inbox = {}

    def receiver(intent):
        # A second connection can write: sender does not retain its transaction.
        with World(w.path).db() as db:
            w.put(db, 'testReceiverVisited', True)
        prior = inbox.setdefault(intent['id'], ack(intent))
        if len(inbox) == 1 and not receiver.failed:
            receiver.failed = True
            raise TimeoutError('after recipient commit')
        return prior

    receiver.failed = False
    assert notices.relay(w, receiver)['error'] == 'TimeoutError'
    assert notices.relay(World(w.path), receiver)['accepted'] == 1
    assert len(inbox) == 1
    advance(w)
    assert len(items(w)) == 2
    before = notices.inspect(w)['items'][1]
    assert notices.relay(w, lambda intent: {**ack(intent), 'extra': True})['error'] == 'ValueError'
    assert notices.inspect(w)['items'][1]['state'] == before['state'] == 'pending'


def test_stored_payload_corruption_fails_closed_and_cursors_are_strict(tmp_path):
    w = setup(tmp_path)
    advance(w)
    for cursor in ('bad', '20260102|1', '2026-01-02T00:00:00Z|-1', '2026-01-02T00:00:00Z|01'):
        with pytest.raises(ValueError):
            notices.ready(w, after=cursor)
    with w.db() as db:
        db.execute("UPDATE customer_notice_outbox SET envelope='{}'")
    with pytest.raises(ValueError, match='checksum'):
        notices.ready(w)
    with pytest.raises(ValueError, match='checksum'):
        notices.relay(w, ack)


@pytest.mark.parametrize('change', [{'id': 'foreign'}, {'runId': 'foreign'}, {'fingerprint': 'foreign'},
                                 {'status': 'resolved'}, {'receiptId': ''}, {'receiptId': ' '},
                                 {'receiptId': 123}, {'receiptId': 'x'*513}, {'extra': True}])
def test_exact_recipient_acknowledgment_required(tmp_path, change):
    w = setup(tmp_path)
    advance(w)
    result = notices.relay(w, lambda intent: {**ack(intent), **change})
    assert result['accepted'] == 0 and result['error'] == 'ValueError'
    assert notices.inspect(w)['items'][0]['state'] == 'pending'
    assert notices.relay(w, ack)['accepted'] == 1


def test_concurrent_relays_preserve_one_acknowledgment(tmp_path):
    w = setup(tmp_path)
    advance(w)
    barrier = Barrier(2)

    def receiver(intent):
        barrier.wait(timeout=10)
        return ack(intent)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: notices.relay(World(w.path), receiver, limit=1), range(2)))
    assert sum(r['accepted'] for r in results) == 1
    row = notices.inspect(w)['items'][0]
    assert row['attempts'] == 2 and row['state'] == 'accepted'
    assert notices.relay(w, ack)['accepted'] == 0


def test_first_activation_backup_and_interruption_are_atomic(tmp_path, monkeypatch):
    w = world(tmp_path)
    payload, before = command(w), dump(w)
    original = w.event
    monkeypatch.setattr(w, 'event', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('interrupted activation')))
    with pytest.raises(RuntimeError):
        notices.command(w, payload)
    assert dump(w) == before
    monkeypatch.setattr(w, 'event', original)
    notices.command(w, payload)
    with w.db() as db:
        backup = json.loads(db.execute("SELECT value FROM meta WHERE key='customerNoticesRollbackBackup'").fetchone()[0])
    with closing(sqlite3.connect(backup)) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='customer_notice_outbox'").fetchone()


def test_essential_floor_and_zero_probability_are_explicit_assumptions(tmp_path):
    w = world(tmp_path)
    finance.command(w, finance_command(w, cashCents=10000, essentialReserveCents=2000))
    for kind in ('invoice', 'notice'):
        finance.receive_delivery(w, delivery(w, kind, kind=kind))
    notices.command(w, command(w, noticeProbabilityPerDay=0))
    advance(w)
    assert items(w) == []
    notices.command(w, command(w, 'notice-now'))
    advance(w)
    # 9,000 due minus 4,000 reserved = 5,000; 10,000 cash minus
    # 4,000 reserved minus 2,000 essential floor = 4,000 available.
    assert len(items(w)) == 1
