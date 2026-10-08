import json
from datetime import date, timedelta
from pathlib import Path

import jsonschema
import pytest
from test_world_network_faults import world
from test_world_occupancy import schedule

from utilsim.world import World, occupancy
from utilsim.world import customer_finance as finance
from utilsim.world.store import stable


def command(w, identity='finance-config', action='configure', **overrides):
    with w.db() as db:
        meta = w.metadata(db)
    extra = {'active': True, 'customerKind': 'household', 'recipientRef': 'SIM-HOUSEHOLD-P1',
             'cashCents': 10000, 'essentialReserveCents': 3000, 'maxPaymentCents': 4000,
             'paymentProbability': 1} if action == 'configure' else {'amountCents': 5000}
    return {'schemaVersion': finance.VERSION, 'commandId': identity, 'environmentId': meta['environment'],
            'runId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin',
            'expectedRevision': 0, 'effectiveDate': meta['through'], 'action': action, 'premiseId': 'P1',
            'reason': 'Illustrative customer scenario', 'causalReference': 'scenario', **extra, **overrides}


def delivery(w, identity='delivered-invoice-1', **overrides):
    with w.db() as db:
        meta = w.metadata(db)
    return {'schemaVersion': finance.DELIVERY_VERSION, 'deliveryId': identity, 'environmentId': meta['environment'],
            'runId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'premiseId': 'P1',
            'recipientRef': 'SIM-HOUSEHOLD-P1', 'invoiceId': 'INV-1', 'currency': 'USD', 'amountCents': 9000,
            'dueDate': '2026-01-01', 'deliveredAt': meta['through']+'T00:00:00Z', 'kind': 'invoice',
            'status': 'delivered', **overrides}


def advance(w, days=1):
    with w.db() as db:
        day = w.metadata(db)['through']
    w.advance((date.fromisoformat(day)+timedelta(days=days)).isoformat())


def ack(intent):
    return {'id': intent['id'], 'runId': intent['runId'], 'fingerprint': stable(intent),
            'status': 'accepted', 'receiptId': 'ACCEPT-'+intent['id']}


def receipt(w, intent, identity='settlement-1', **overrides):
    with w.db() as db:
        meta = w.metadata(db)
    return {'schemaVersion': finance.RECEIPT_VERSION, 'receiptId': identity, 'environmentId': meta['environment'],
            'runId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'intentId': intent['id'],
            'intentFingerprint': stable(intent), 'status': 'settled', 'amountCents': intent['amountCents'],
            'currency': 'USD', 'occurredAt': meta['through']+'T00:00:00Z', 'settlementReceiptId': None, **overrides}


def setup(w, **overrides):
    finance.command(w, command(w, **overrides))
    finance.receive_delivery(w, delivery(w))
    advance(w)
    return finance.ready(w)['items'][0]['intent']


def test_no_document_no_knowledge_and_future_or_undelivered_rejected(tmp_path):
    w = world(tmp_path)
    finance.command(w, command(w))
    advance(w, 5)
    assert finance.ready(w)['items'] == []
    assert finance.inspect(w, 'P1')['knownOutstandingCents'] == 0
    for change in ({'status': 'accepted'}, {'status': 'failed'}, {'deliveredAt': '2026-02-01T00:00:00Z'},
                   {'kind': 'notice'}, {'recipientRef': 'unknown'}, {'runId': 'OTHER'}, {'amountCents': True},
                   {'currency': 'EUR'}):
        with pytest.raises(ValueError):
            finance.receive_delivery(w, delivery(w, **change))
    finance.receive_delivery(w, delivery(w, deliveredAt='2026-01-01T00:00:00Z'))
    assert finance.ready(w)['items'] == []
    advance(w)
    intent = finance.ready(w)['items'][0]['intent']
    assert intent['createdAt'] == '2026-01-07T00:00:00Z'


def test_reservation_acceptance_settlement_and_return_conserve_cash(tmp_path):
    w = world(tmp_path)
    intent = setup(w)
    view = finance.inspect(w, 'P1')
    assert (view['cashCents'], view['reservedCashCents'], view['netSettledCashCents'], view['knownOutstandingCents']) == (10000, 4000, 0, 9000)
    assert finance.relay(w, ack)['accepted'] == 1
    assert finance.inspect(w, 'P1') == view
    advance(w, 2)
    assert len(finance.ready(w)['items']) == 1
    settled = receipt(w, intent)
    result = finance.provider_receipt(w, settled)
    assert finance.provider_receipt(World(w.path), settled) == result
    view = finance.inspect(w, 'P1')
    assert (view['cashCents'], view['reservedCashCents'], view['netSettledCashCents'], view['knownOutstandingCents']) == (6000, 0, 4000, 5000)
    with pytest.raises(ValueError, match='already settled'):
        finance.provider_receipt(w, {**settled, 'receiptId': 'different-settlement'})
    returned = receipt(w, intent, 'return-1', status='returned', settlementReceiptId='settlement-1')
    result = finance.provider_receipt(w, returned)
    assert finance.provider_receipt(World(w.path), returned) == result
    view = finance.inspect(w, 'P1')
    assert (view['cashCents'], view['reservedCashCents'], view['netSettledCashCents'], view['knownOutstandingCents']) == (10000, 0, 0, 9000)
    with pytest.raises(ValueError):
        finance.provider_receipt(w, {**returned, 'receiptId': 'different-return'})
    assert finance.inspect(w, 'P1') == view
    advance(w)
    assert len(finance.ready(w)['items']) == 2


def test_exact_deliveries_notices_and_command_retries(tmp_path):
    w = world(tmp_path)
    payload = command(w)
    result = finance.command(w, payload)
    assert finance.command(World(w.path), payload) == result
    with pytest.raises(ValueError, match='Conflicting'):
        finance.command(w, {**payload, 'cashCents': 123})
    msg = delivery(w)
    result = finance.receive_delivery(w, msg)
    assert finance.receive_delivery(w, msg) == result
    finance.receive_delivery(w, delivery(w, 'notice-1', kind='notice'))
    finance.receive_delivery(w, delivery(w, 'invoice-redelivery'))
    assert finance.inspect(w, 'P1')['knownOutstandingCents'] == 9000
    with pytest.raises(ValueError, match='Conflicting'):
        finance.receive_delivery(w, {**msg, 'amountCents': 1})
    with pytest.raises(ValueError, match='Conflicting invoice'):
        finance.receive_delivery(w, delivery(w, 'replacement', amountCents=1))
    with pytest.raises(ValueError, match='revision'):
        finance.command(w, command(w, 'stale'))
    revision = finance.inspect(w, 'P1')['revision']
    with pytest.raises(ValueError, match='reset cash'):
        finance.command(w, command(w, 'reset', expectedRevision=revision, cashCents=100))


def test_cash_constraints_credit_installments_and_business(tmp_path):
    w = world(tmp_path)
    finance.command(w, command(w, customerKind='business', cashCents=3000))
    finance.receive_delivery(w, delivery(w))
    advance(w)
    assert finance.ready(w)['items'] == []
    p = command(w, 'cash-in', 'credit', expectedRevision=2, amountCents=5000)
    result = finance.command(w, p)
    assert finance.command(w, p) == result
    advance(w)
    first = finance.ready(w)['items'][0]['intent']
    assert first['amountCents'] == 4000 and first['customerKind'] == 'business'
    finance.provider_receipt(w, receipt(w, first))
    advance(w)
    second = finance.ready(w)['items'][1]['intent']
    assert second['amountCents'] == 1000
    finance.provider_receipt(w, receipt(w, second, 'settlement-2'))
    advance(w)
    view = finance.inspect(w, 'P1')
    assert (view['cashCents'], view['netSettledCashCents'], view['knownOutstandingCents']) == (3000, 5000, 4000)


@pytest.mark.parametrize('change', [dict(amountCents=100), dict(status='accepted'), dict(status='failed'),
                                   dict(intentFingerprint='bad'), dict(runId='another-run'),
                                   dict(occurredAt='2026-02-01T00:00:00Z'), dict(occurredAt='2026-01-01T00:00:00Z'),
                                   dict(status='returned', settlementReceiptId='unknown')])
def test_unsupported_receipts_do_not_move_cash(tmp_path, change):
    w = world(tmp_path)
    intent = setup(w)
    before = finance.inspect(w, 'P1')
    with pytest.raises(ValueError):
        finance.provider_receipt(w, receipt(w, intent, **change))
    assert finance.inspect(w, 'P1') == before


def test_lost_ack_retry_reopen_filter_schema_and_no_private_finance(tmp_path):
    w = world(tmp_path)
    intent = setup(w)
    recipient = {}
    def lose_ack(value):
        recipient.setdefault(value['id'], ack(value))
        raise ConnectionError('SECRET remote details')
    assert finance.relay(w, lose_ack)['error'] == 'ConnectionError'
    w = World(w.path)
    assert finance.relay(w, lambda value: recipient[value['id']])['accepted'] == 1
    assert finance.relay(w, ack)['accepted'] == 0
    assert len(recipient) == 1
    assert finance.inspect(w, 'P1')['reservedCashCents'] == intent['amountCents']
    schema = json.loads((Path(__file__).parents[1]/'schemas/payment-intent-1.schema.json').read_text())
    jsonschema.validate(intent, schema, format_checker=jsonschema.FormatChecker())
    for filename, value in [('customer-finance-delivery-1.schema.json', delivery(w)),
                            ('customer-finance-provider-receipt-1.schema.json', receipt(w, intent)),
                            ('customer-finance-provider-receipt-1.schema.json', receipt(w, intent, 'returned', status='returned', settlementReceiptId='s'))]:
        contract = json.loads((Path(__file__).parents[1]/'schemas'/filename).read_text())
        jsonschema.validate(value, contract, format_checker=jsonschema.FormatChecker())
    assert not set(intent) & {'cashCents', 'essentialReserveCents', 'paymentProbability', 'policyCause', 'occupancyStamp', 'paid'}
    with w.db() as db:
        assert 'SECRET' not in str([tuple(row) for row in db.execute('SELECT * FROM customer_finance_intents')])
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not tables & {'invoices', 'payments', 'journal', 'financial_transactions', 'collections_queue'}


def test_transaction_rollback_and_decision_dedup(tmp_path):
    w = world(tmp_path)
    finance.command(w, command(w))
    finance.receive_delivery(w, delivery(w))
    with pytest.raises(RuntimeError):
        with w.db() as db:
            finance.daily(w, db, w.metadata(db))
            raise RuntimeError('Day interrupted')
    assert finance.inspect(w, 'P1')['reservedCashCents'] == 0
    with w.db() as db:
        meta = w.metadata(db)
        finance.daily(w, db, meta)
        finance.daily(w, db, meta)
    assert finance.ready(w)['items'] == []  # committed intent still waits for clock
    advance(w)
    assert len(finance.ready(w)['items']) == 1
    assert finance.inspect(w, 'P1')['reservedCashCents'] == 4000


def test_seeded_reopen_chunking_and_cash_never_invents_invoice(tmp_path):
    a, b = world(tmp_path, 'a'), world(tmp_path, 'b')
    for w in (a, b):
        finance.command(w, command(w, paymentProbability=.15))
        finance.receive_delivery(w, delivery(w))
    advance(a, 30)
    advance(b, 7)
    b = World(b.path)
    advance(b, 23)
    assert finance.inspect(a, 'P1') == finance.inspect(b, 'P1')
    assert finance.ready(a) == finance.ready(b)


def test_occupancy_change_freezes_new_behavior_but_old_cash_can_settle_return(tmp_path):
    w = world(tmp_path)
    intent = setup(w)
    occupancy.command(w, schedule(w, effectiveDate='2026-01-02', occupied=True, occupants=3))
    advance(w)
    assert finance.inspect(w, 'P1')['cohortBlocked']
    with pytest.raises(ValueError, match='cohort'):
        finance.receive_delivery(w, delivery(w, 'new-delivery'))
    settled = receipt(w, intent)
    finance.provider_receipt(w, settled)
    finance.provider_receipt(w, receipt(w, intent, 'return-1', status='returned', settlementReceiptId='settlement-1'))
    advance(w, 3)
    assert len(finance.ready(w)['items']) == 1
    assert finance.inspect(w, 'P1')['cashCents'] == 10000


def test_multiple_invoices_cannot_over_reserve_cash(tmp_path):
    w = world(tmp_path)
    finance.command(w, command(w))
    for n in range(5):
        finance.receive_delivery(w, delivery(w, f'delivery-{n}', invoiceId=f'INV-{n}'))
    advance(w)
    intents = [item['intent'] for item in finance.ready(w)['items']]
    assert [intent['amountCents'] for intent in intents] == [4000, 3000]
    assert finance.inspect(w, 'P1')['spendableCashCents'] == 0
    assert finance.ready(w, limit=1)['nextAfter'] == 1
    assert finance.ready(w, after=1, limit=1)['items'][0]['intent'] == intents[1]


def test_daily_bounds_snapshot_work_for_300_profiles(tmp_path):
    w = world(tmp_path)
    finance.command(w, command(w))
    with w.db() as db:
        snapshot = json.loads(db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()[0])
        source = dict(db.execute('SELECT * FROM customer_finance_profiles').fetchone())
        for n in range(2, 301):
            premise = f'P{n}'
            snapshot['premises'].append({**snapshot['premises'][0], 'id': premise})
            db.execute('INSERT INTO customer_finance_profiles(premise,recipient,stamp,policy,cash,revision,cause) VALUES(?,?,?,?,?,?,?)',
                       (premise, f'SIM-{n}', source['stamp'], source['policy'], source['cash'], 1, source['cause']))
        w.put(db, 'snapshot', snapshot)
        queries = []
        db.set_trace_callback(queries.append)
        finance.daily(w, db, w.metadata(db))
        db.set_trace_callback(None)
        assert len([q for q in queries if "key='snapshot'" in q]) == 1
        assert db.execute('SELECT COUNT(*) FROM customer_finance_decisions').fetchone()[0] == 300
        plan = db.execute('EXPLAIN QUERY PLAN SELECT * FROM customer_finance_invoices WHERE premise=? AND due<=? ORDER BY due,id',
                          ('P1', '2026-01-01')).fetchall()
        assert any('customer_finance_invoice_due' in row['detail'] for row in plan)


def test_paused_future_due_and_final_installment_cap(tmp_path):
    w = world(tmp_path)
    finance.command(w, command(w, active=False))
    finance.receive_delivery(w, delivery(w, dueDate='2026-01-04', amountCents=1500))
    advance(w)
    assert finance.ready(w)['items'] == []
    finance.command(w, command(w, 'activate', expectedRevision=2))
    advance(w, 2)
    assert finance.ready(w)['items'] == []
    advance(w)
    intent = finance.ready(w)['items'][0]['intent']
    assert intent['amountCents'] == 1500
    finance.provider_receipt(w, receipt(w, intent))
    advance(w, 2)
    assert len(finance.ready(w)['items']) == 1
    assert finance.inspect(w, 'P1')['knownOutstandingCents'] == 0
