import json
import sqlite3
from contextlib import closing
from copy import deepcopy

import pytest
from test_world_customer_finance import advance, delivery, receipt
from test_world_customer_finance import command as finance_command
from test_world_network_faults import world
from test_world_occupancy import schedule

from utilsim.world import World, occupancy
from utilsim.world import customer_cashflow as cashflow
from utilsim.world import customer_finance as finance


def command(w, identity='cashflow-1', **overrides):
    view = cashflow.inspect(w, 'P1')
    payload = dict(schemaVersion=cashflow.VERSION, commandId=identity, environmentId=view['environmentId'],
                runId=view['runId'], worldFingerprint=view['worldFingerprint'], actorId='world-admin',
                expectedRevision=view['revision'], effectiveDate=view['through'], action='configure',
                premiseId='P1', recipientRef=view['recipientRef'] or 'SIM-HOUSEHOLD-P1', active=True,
                income={'amountCents': 1000, 'firstDate': '2026-01-01', 'intervalDays': 2},
                essentialExpense={'amountCents': 400, 'firstDate': '2026-01-01', 'intervalDays': 1},
                insufficientCashPolicy='available-cash', incomeOverflowPolicy='skip-with-record',
                reason='Illustrative household budget', causalReference='scenario')
    return {**payload, **overrides}


def setup(tmp_path, **overrides):
    w = world(tmp_path)
    finance.command(w, finance_command(w, **overrides))
    return w


def dump(w):
    with w.db() as db:
        return '\n'.join(db.iterdump())


def cash(w):
    view = finance.inspect(w, 'P1')
    return view['cashCents'], view['reservedCashCents'], view['netSettledCashCents'], view['knownOutstandingCents']


def test_absent_model_is_readonly_and_legacy_results_unchanged(tmp_path):
    w, other = world(tmp_path), world(tmp_path, 'other')
    before = dump(w)
    view = cashflow.inspect(w, 'P1')
    assert not view['configured'] and not view['financeConfigured'] and view['history'] == []
    assert dump(w) == before
    for owner in (w, other):
        finance.command(owner, finance_command(owner))
        finance.receive_delivery(owner, delivery(owner))
        advance(owner, 3)
    # Activation records an owner-specific backup filename, but every runtime
    # table and all other metadata remain identical without cashflow activation.
    def runtime(owner):
        return '\n'.join(line for line in dump(owner).splitlines() if 'customerFinanceRollbackBackup' not in line)
    assert runtime(w) == runtime(other)


def test_income_precedes_expense_then_payment_and_cadence_is_exact(tmp_path):
    w = setup(tmp_path, cashCents=0, essentialReserveCents=0)
    finance.receive_delivery(w, delivery(w))
    cashflow.command(w, command(w))
    advance(w)
    assert cash(w) == (600, 600, 0, 9000)
    intent = finance.ready(w)['items'][0]['intent']
    finance.provider_receipt(w, receipt(w, intent))
    advance(w)  # no income; no cash to fund today's essential expense
    history = cashflow.inspect(w, 'P1')['history']
    assert history[0]['incomeDueCents'] == 0 and history[0]['expenseUnfundedCents'] == 400
    advance(w)
    assert cash(w) == (600, 600, 600, 8400)
    history = cashflow.inspect(w, 'P1')['history']
    assert [x['incomeCreditedCents'] for x in history] == [1000, 0, 1000]
    assert len(finance.ready(w)['items']) == 2
    assert len({x['eventId'] for x in history}) == 3


@pytest.mark.parametrize(('policy', 'paid'), [('available-cash', 500), ('all-or-nothing', 0)])
def test_expense_can_use_payment_floor_but_never_reserved_money(tmp_path, policy, paid):
    w = setup(tmp_path, cashCents=4500, essentialReserveCents=0)
    finance.receive_delivery(w, delivery(w))
    advance(w)
    assert cash(w) == (4500, 4000, 0, 9000)
    revision = finance.inspect(w, 'P1')['revision']
    finance.command(w, finance_command(w, 'protect-necessities', cashCents=4500,
                                     essentialReserveCents=4400, expectedRevision=revision))
    cashflow.command(w, command(w, insufficientCashPolicy=policy,
                               income={'amountCents': 0, 'firstDate': '2026-01-02', 'intervalDays': 1},
                               essentialExpense={'amountCents': 1000, 'firstDate': '2026-01-02', 'intervalDays': 1}))
    advance(w)
    assert cash(w) == (4500-paid, 4000, 0, 9000)
    record = cashflow.inspect(w, 'P1')['history'][0]
    assert (record['expensePaidCents'], record['expenseUnfundedCents']) == (paid, 1000-paid)


def test_payment_pause_does_not_pause_cashflow_and_cash_limit_does_not_stall_day(tmp_path):
    w = setup(tmp_path, active=False, cashCents=finance.MAX_CENTS-500)
    cashflow.command(w, command(w))
    advance(w)
    record = cashflow.inspect(w, 'P1')['history'][0]
    assert record['incomeStatus'] == 'cash_limit' and record['incomeSkippedCents'] == 1000
    assert record['expensePaidCents'] == 400
    assert cash(w)[0] == finance.MAX_CENTS-900
    assert finance.ready(w)['items'] == []


def test_pause_resumes_original_cadence_without_catchup_and_history_is_immutable(tmp_path):
    w = setup(tmp_path)
    original = command(w)
    original_result = cashflow.command(w, original)
    advance(w)
    initial = cashflow.inspect(w, 'P1')['history'][0]
    paused = command(w, 'pause', active=False)
    cashflow.command(w, paused)
    advance(w, 3)
    assert cash(w)[0] == 10600
    cashflow.command(w, command(w, 'resume'))
    advance(w)
    assert cash(w)[0] == 11200  # day 5 income+expense, no catch-up for days 2..4
    assert cashflow.inspect(w, 'P1')['history'][-1] == initial
    before = dump(w)
    assert cashflow.command(World(w.path), original) == original_result
    assert dump(w) == before
    with pytest.raises(ValueError, match='Conflicting'):
        cashflow.command(w, {**original, 'active': False})


@pytest.mark.parametrize('change', [
    {'active': 1}, {'actorId': 'worker'}, {'recipientRef': 'other'}, {'expectedRevision': 1},
    {'runId': 'other'}, {'worldFingerprint': 'other'}, {'effectiveDate': '2026-01-02'},
    {'incomeOverflowPolicy': 'clamp'}, {'insufficientCashPolicy': 'borrow'}, {'unknown': 1},
    {'income': {'amountCents': True, 'firstDate': '2026-01-01', 'intervalDays': 1}},
    {'income': {'amountCents': 1.5, 'firstDate': '2026-01-01', 'intervalDays': 1}},
    {'income': {'amountCents': 0, 'firstDate': '2025-12-31', 'intervalDays': 1}},
    {'income': {'amountCents': 0, 'firstDate': '2026-01-01', 'intervalDays': True}},
    {'income': {'amountCents': 0, 'firstDate': '2026-01-01', 'intervalDays': 0}},
    {'income': {'amountCents': 0, 'firstDate': '2026-01-01', 'intervalDays': 367}},
])
def test_invalid_initial_configuration_has_no_mutation_or_migration(tmp_path, change):
    w = setup(tmp_path)
    payload = {**command(w), **change}
    before = dump(w)
    with pytest.raises(ValueError):
        cashflow.command(w, payload)
    assert dump(w) == before
    assert not list(tmp_path.glob('*.pre-customer-cashflow-*.bak'))


def test_profile_required_and_new_historical_anchor_cannot_be_introduced(tmp_path):
    w = world(tmp_path)
    with pytest.raises(ValueError, match='profile first'):
        cashflow.command(w, command(w))
    finance.command(w, finance_command(w))
    cashflow.command(w, command(w))
    advance(w, 3)
    old = command(w, 'edit')
    cashflow.command(w, old)  # unchanged historical anchors are retained
    old = command(w, 'bad-edit')
    old['income']['firstDate'] = '2026-01-02'
    before = dump(w)
    with pytest.raises(ValueError, match='anchor'):
        cashflow.command(w, old)
    assert dump(w) == before


def test_daily_interruption_rolls_back_cash_records_and_payments(tmp_path, monkeypatch):
    w = setup(tmp_path, cashCents=0, essentialReserveCents=0)
    finance.receive_delivery(w, delivery(w))
    cashflow.command(w, command(w))
    before = dump(w)
    original = w.event

    def interrupt(db, env, day, kind, *args, **kwargs):
        result = original(db, env, day, kind, *args, **kwargs)
        if kind == 'CustomerPaymentIntended':
            raise RuntimeError('interruption after cashflow and before day commit')
        return result

    monkeypatch.setattr(w, 'event', interrupt)
    with pytest.raises(RuntimeError):
        advance(w)
    assert dump(w) == before
    w = World(w.path)
    advance(w)
    assert cash(w) == (600, 600, 0, 9000)
    assert len(cashflow.inspect(w, 'P1')['history']) == 1


def test_failed_configuration_rolls_back_tables_and_backup_retains_prior_state(tmp_path, monkeypatch):
    w = setup(tmp_path)
    payload = command(w)
    before = dump(w)
    original = w.event
    monkeypatch.setattr(w, 'event', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('interrupted activation')))
    with pytest.raises(RuntimeError):
        cashflow.command(w, payload)
    assert dump(w) == before
    monkeypatch.setattr(w, 'event', original)
    cashflow.command(w, payload)
    with w.db() as db:
        backup = json.loads(db.execute("SELECT value FROM meta WHERE key='customerCashflowRollbackBackup'").fetchone()[0])
    with closing(sqlite3.connect(backup)) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='customer_cashflow_days'").fetchone()
        assert db.execute('SELECT cash FROM customer_finance_profiles').fetchone()[0] == 10000


def test_history_is_bounded_and_restart_conserves_sixty_days(tmp_path):
    a, b = world(tmp_path, 'a'), world(tmp_path, 'b')
    for w in (a, b):
        finance.command(w, finance_command(w))
        cashflow.command(w, command(w))
    advance(a, 60)
    advance(b, 30)
    b = World(b.path)
    advance(b, 30)
    assert cash(a) == cash(b) == (16000, 0, 0, 0)
    records, cursor = [], None
    while True:
        view = cashflow.inspect(b, 'P1', before=cursor)
        records.extend(view['history'])
        assert len(view['history']) <= 25
        cursor = view['nextBefore']
        if cursor is None:
            break
    assert len(records) == len({r['day'] for r in records}) == 60
    assert records == cashflow.inspect(a, 'P1', limit=100)['history']
    before = dump(b)
    b.advance('2026-03-02')  # already complete (Jan 1 + 60 days)
    assert dump(b) == before
    with b.db() as db:
        plan = db.execute('EXPLAIN QUERY PLAN SELECT payload FROM customer_cashflow_days '
                          'WHERE premise=? AND day<? ORDER BY day DESC LIMIT 26', ('P1', '2026-03-02')).fetchall()
        assert any('INDEX' in r[3] for r in plan)


def test_terminal_failure_does_not_refund_expenses_or_duplicate_income(tmp_path):
    w = setup(tmp_path, cashCents=0, essentialReserveCents=0)
    finance.receive_delivery(w, delivery(w))
    cashflow.command(w, command(w))
    advance(w)
    intent = finance.ready(w)['items'][0]['intent']
    failed = receipt(w, intent, 'failure', schemaVersion=finance.RECEIPT_VERSION_2, status='failed')
    finance.provider_receipt(w, failed)
    assert cash(w) == (600, 0, 0, 9000)
    advance(w)
    assert cash(w) == (200, 200, 0, 9000)
    finance.provider_receipt(w, failed)
    assert cash(w) == (200, 200, 0, 9000)


def test_vacancy_and_new_occupant_cannot_inherit_cashflows(tmp_path):
    w = setup(tmp_path)
    original = command(w)
    result = cashflow.command(w, original)
    vacancy = schedule(w, 'vacate', effectiveDate='2026-01-01', occupied=False, occupants=0)
    occupancy.command(w, vacancy)
    advance(w)
    assert cash(w)[0] == 10000 and cashflow.inspect(w, 'P1')['cohortBlocked']
    assert cashflow.inspect(w, 'P1')['history'][0]['status'] in ('vacant', 'cohort_changed')
    move_in = schedule(w, 'move-in', effectiveDate='2026-01-02', expectedRevision=1, occupied=True, occupants=3)
    occupancy.command(w, move_in)
    advance(w)
    assert cash(w)[0] == 10000
    with pytest.raises(ValueError, match='cohort'):
        cashflow.command(w, command(w, 'change'))
    assert cashflow.command(w, original) == result


def test_zero_streams_and_future_anchor_do_not_create_money(tmp_path):
    w = setup(tmp_path)
    p = command(w)
    p['income']['firstDate'] = '2026-01-10'
    p['essentialExpense']['amountCents'] = 0
    cashflow.command(w, p)
    advance(w, 3)
    assert cash(w)[0] == 10000
    assert all(r['status'] == 'no_occurrence' for r in cashflow.inspect(w, 'P1')['history'])
    invalid = deepcopy(p)
    invalid['income']['extra'] = 1
    with pytest.raises(ValueError):
        cashflow.command(w, invalid)


def test_inspection_guards_do_not_enable_or_mutate_model(tmp_path):
    empty = World(tmp_path / 'empty.sqlite')
    before = dump(empty)
    with pytest.raises(ValueError, match='Initialize'):
        cashflow.inspect(empty, 'P1')
    assert dump(empty) == before
    w = setup(tmp_path)
    before = dump(w)
    for kwargs in ({'premise': 'missing'}, {'premise': 'P1', 'limit': True},
                   {'premise': 'P1', 'limit': 101}, {'premise': 'P1', 'before': '20260101'}):
        with pytest.raises(ValueError):
            cashflow.inspect(w, **kwargs)
    assert dump(w) == before


def test_net_zero_movement_advances_finance_revision_and_interval_changes_are_prospective(tmp_path):
    w = setup(tmp_path)
    stream = {'amountCents': 1000, 'firstDate': '2026-01-01', 'intervalDays': 2}
    cashflow.command(w, command(w, income=stream, essentialExpense=stream))
    revision = finance.inspect(w, 'P1')['revision']
    advance(w)
    assert cash(w)[0] == 10000
    assert finance.inspect(w, 'P1')['revision'] == revision + 1
    advance(w, 2)
    # Keep the original anchor, change only future cadence; do not recalculate days 1..3.
    prior = cashflow.inspect(w, 'P1')['history']
    stream = {**stream, 'intervalDays': 3}
    cashflow.command(w, command(w, 'new-cadence', income=stream, essentialExpense=stream))
    advance(w)
    history = cashflow.inspect(w, 'P1')['history']
    assert history[0]['incomeCreditedCents'] == 1000 and history[0]['policyRevision'] == 2
    assert history[1:] == prior


def test_old_provider_receipt_after_replacement_does_not_resume_cashflow(tmp_path):
    w = setup(tmp_path, cashCents=0, essentialReserveCents=0)
    finance.receive_delivery(w, delivery(w))
    cashflow.command(w, command(w))
    advance(w)
    intent = finance.ready(w)['items'][0]['intent']
    occupancy.command(w, schedule(w, effectiveDate='2026-01-02', occupied=True, occupants=3))
    advance(w)
    finance.provider_receipt(w, receipt(w, intent))
    assert cash(w) == (0, 0, 600, 8400)
    advance(w)
    assert cash(w) == (0, 0, 600, 8400)
    assert cashflow.inspect(w, 'P1')['history'][0]['status'] == 'cohort_changed'
