from copy import deepcopy
from types import SimpleNamespace as NS

import numpy as np
import pytest

from utilsim.m2c.billing_quality import METRICS, measure_quality
from utilsim.m2c.billing_reports import REPORTS
from utilsim.m2c.calendar import calendar
from utilsim.m2c.kpis import KPI_IDS
from utilsim.m2c.tables import b_billing_audit
from utilsim.worker.workspace import UtilityWorkspace


@pytest.fixture
def run():
    def doc(k, inst, month, created, released, estimated=False, case=-1):
        return dict(k=k, inst=inst, month=month, created=created, released=released, estimated=estimated,
                    case=case, reversed=None, replaces=-1, rate='R', total=10, qImp=0, qExp=0)
    docs = [doc(0, 0, 1, 31, 31, True), doc(1, 0, 2, 60, 60, True, 0),
            doc(2, 1, 1, 31, None, False, 1), doc(3, 0, 3, 90, 90, True)]
    invoices = [dict(id='i0', account='A', created=32, issued=35, due=55, docs=[0], total=10),
                dict(id='i1', account='A', created=60, issued=62, due=82, docs=[1], total=10)]
    master = {'accounts': [{'id': 'A', 'premiseId': 'P0'}, {'id': 'B', 'premiseId': 'P1'}],
              'contracts': [{'id': 'c0', 'accountId': 'A', 'installationId': 'I0'},
                            {'id': 'c1', 'accountId': 'B', 'installationId': 'I1'}],
              'installations': [{'id': 'I0', 'premiseId': 'P0', 'servicePointId': 'S0'},
                                {'id': 'I1', 'premiseId': 'P1', 'servicePointId': 'S1'}],
              'servicePoints': [{'id': 'S0'}, {'id': 'S1'}],
              'meters': [{'id': 'M0', 'servicePointId': 'S0'}, {'id': 'M1', 'servicePointId': 'S1'}]}
    read_day = np.tile(np.arange(13)*30, (2, 1))
    read_t = read_day.astype(float)
    release = read_t.copy()
    release[0, 2] = 70
    cases = np.full((2, 13), -1)
    cases[0, 2] = 0
    town = NS(read_day=read_day, prem=np.array([0, 1]), move_in=np.array([-1000, 20]),
              move_out=np.array([1000, 1000]), audit_master=master, tariffs={'R': {'fixedMonthly': 20}})
    books = NS(docs=docs, invoices=invoices, main=np.array([0, 1]),
               period=lambda d: ((d['month']-1)*30, d['month']*30), account=lambda d: 'A' if d['inst']==0 else 'B')
    return NS(town=town, books=books, cal=calendar(2026), holds={}, cases=[], read_t=read_t,
              taken_t=lambda rr, mm: read_t[rr, mm],
              release_t=release, obs=read_t.copy(), case_of=cases, status=np.ones((2, 13)),
              cfg=NS(kpi=NS(on_time_bill_days=3, timely_invoice_days=3), customers_billing=NS(due_days=20)))


def test_invoice_populations_wait_for_issue_and_preserve_historical_contents(run):
    values, stats = measure_quality(run, 65, 65.999)
    assert values['estimated_bill_share'] == 1
    assert values['consecutive_estimated_bill_share'] == .5
    assert values['consecutive_zero_bill_share'] == .5
    assert values['active_billing_blocks'] == 1
    # A Jan issue is late; B has two overdue cycles, including Feb with no billing document.
    assert values['delayed_bill_share'] == .75
    assert measure_quality(run, 62, 62.999)[0]['delayed_bill_share'] == .5
    assert stats['estimated_bill_share'] == [2, 2]
    assert set(values) == {m['id'] for m in METRICS}
    run.books.docs[0]['reversed'] = 64
    assert measure_quality(run, 65, 65.999)[0]['estimated_bill_share'] == 1
    assert measure_quality(run, 61, 61.999)[0]['consecutive_estimated_bill_share'] == 0
    assert measure_quality(run, 61, 61.999)[0]['invoices_pending_issue'] == 1


def test_audits_detect_terms_links_and_late_reads_without_confusing_no_population_with_zero(run):
    assert measure_quality(run, 65, 65.999)[0]['service_setup_defects'] == 0
    run.books.invoices[0]['due'] = 34
    run.town.audit_master['meters'].pop()
    run.town.audit_master['meters'].append({'id': 'retired', 'servicePointId': 'missing', 'removedAt': '2026-01-01'})
    run.read_t[0, 1] += 2
    values, _ = measure_quality(run, 65, 65.999)
    assert values['due_date_defect_share'] == .5 and values['net_terms_mismatch_share'] == .5
    assert values['active_meterless_accounts'] == 1 and values['orphaned_meters'] == 0
    assert values['late_read_share'] == .25
    assert values['outstanding_reads'] == 1 and values['active_reading_blocks'] == 1
    empty, _ = measure_quality(run, 0, .999)
    assert empty['estimated_bill_share'] is None and empty['due_date_defect_share'] is None
    assert empty['active_billing_blocks'] == 0
    run.read_t[0, 3] = 64  # An early final read is visible before its scheduled day 90.
    assert measure_quality(run, 65, 65.999)[0]['early_read_share'] == .2


def test_monthly_audit_uses_event_month_and_utility_totals_sum_before_paging(run):
    run.books.docs[0]['reversed'] = 64
    cols = b_billing_audit(NS(run=run, bk=run.books, cal=run.cal, day=65, T=65.999))
    rows = list(map(list, zip(*cols, strict=True)))
    assert rows[1][1] == 2  # February creations (day 31).
    assert rows[2][4] == 1 and rows[2][6] == 10  # March reversal.
    columns = [{'key': 'month' if i == 0 else str(i), 'kind': 'int'} for i in range(len(rows[0]))]
    output = {'rows': rows, 'columns': columns, 'total': 3, 'rowsInTable': 3, 'facets': {}}
    result = UtilityWorkspace.page([output, deepcopy(output)], '/m2c/table', {'table': 'billingAudit'}, 2, 1)
    assert result['total'] == result['rowsInTable'] == 3
    assert result['rows'][0][0] == 2 and result['rows'][0][1] == 4


def test_every_report_is_mapped_and_unmodelled_sources_are_explicit():
    assert len(REPORTS) == len({r['code'] for r in REPORTS}) == 31
    for r in REPORTS:
        assert set(r['kpis']) <= KPI_IDS
        if r['status'] != 'available':
            assert r['note']
    assert {r['code'] for r in REPORTS if r['status'] == 'needs_data'} == {'BR-ACC-07', 'BR-BIL-15'}


def test_multiple_services_count_one_invoice_and_rebills_do_not_add_cycles(run):
    from utilsim.m2c.invoice_metrics import issued_invoices, quality_counts
    docs, invoices = run.books.docs, run.books.invoices
    # Add a second estimated service to the first account's first invoice.
    extra = {**docs[0], 'k': len(docs), 'inst': 1}
    docs.append(extra)
    invoices[0]['docs'].append(extra['k'])
    q = quality_counts(run, issued_invoices(run, 65))
    assert q['estimated'] == 2 and q['consecutive_estimated'] == 1
    # An actual correction to January, issued BEFORE February, resets the history.
    correction = {**docs[0], 'k': len(docs), 'estimated': False, 'replaces': 0}
    docs.append(correction)
    invoices.append(dict(id='correction', account='A', created=50, issued=51, docs=[correction['k']]))
    # The other estimated service still makes January estimated.
    assert quality_counts(run, issued_invoices(run, 65))['consecutive_estimated'] == 1
    extra['estimated'] = False
    q = quality_counts(run, issued_invoices(run, 65))
    assert q['consecutive_estimated'] == 0 and q['replacement'] == 1
    assert q['multiple_cycles'] == 1 and q['cycles'] == 2


def test_missing_month_and_months_on_one_invoice_cannot_fake_a_sequence(run):
    from utilsim.m2c.invoice_metrics import issued_invoices, quality_counts
    run.books.invoices = [dict(id='combined', account='A', created=91, issued=92, docs=[0, 1, 3])]
    assert quality_counts(run, issued_invoices(run, 93))['consecutive_estimated'] == 0
    run.books.invoices = [dict(id='jan', account='A', created=32, issued=35, docs=[0]),
                         dict(id='mar', account='A', created=91, issued=92, docs=[3])]
    q = quality_counts(run, issued_invoices(run, 93))
    assert q['consecutive_estimated'] == q['consecutive_zero'] == 0


def test_preissue_document_corrections_are_not_customer_rebills(run):
    from utilsim.m2c.invoice_metrics import issued_invoices, quality_counts
    # February is fixed before it reaches the customer; its original version was never invoiced.
    corrected = {**run.books.docs[1], 'k': len(run.books.docs), 'replaces': 1, 'estimated': False}
    run.books.docs.append(corrected)
    run.books.invoices[1]['docs'] = [corrected['k']]
    assert quality_counts(run, issued_invoices(run, 65))['replacement'] == 0


def test_invoice_periods_and_correction_truth_are_audited_at_issue(run):
    from utilsim.m2c.invoice_metrics import invoice_error, issued_invoices, quality_counts
    run.books.period = lambda d: (0, 30) if d['month'] == 1 else (25, 60)
    q = quality_counts(run, issued_invoices(run, 65))
    assert q['bad_period'] == 1
    original = run.books.docs[0]
    original.update(total=15, truthTotal=10, invoice=0)
    correction = {**original, 'k': len(run.books.docs), 'replaces': 0, 'total': 12, 'truthTotal': 10}
    run.books.docs.append(correction)
    assert invoice_error(run, [dict(total=-3, docs=[correction['k']])]) == (2, 3)
    correction['total'] = correction['truthTotal']
    assert invoice_error(run, [dict(total=-5, docs=[correction['k']])]) == (0, 5)


def test_deadline_accounts_for_print_lag_uncreated_invoices_and_account_grouping(run):
    from utilsim.m2c.invoice_metrics import expected_cycles, timing_counts
    # Both services belong to A. Its blocked second service must not disappear.
    run.books.account = lambda d: 'A'
    counts = timing_counts(expected_cycles(run, 65.999), 65.999, 3)
    assert counts == (0, 2, 2)
    # January is late at issue; February pending inside its window is not late yet.
    assert timing_counts(expected_cycles(run, 62.999), 62.999, 3) == (0, 1, 2)
    # A correction issued later cannot erase the original late customer invoice.
    run.books.docs[0]['reversed'] = 36
    assert timing_counts(expected_cycles(run, 65.999), 65.999, 3) == counts


def test_fit_window_keeps_preceding_invoice_history_and_existing_backlog(run):
    values, stats = measure_quality(run, 65, 65.999, since=60)
    assert stats['estimated_bill_share'] == [1, 1]
    assert values['consecutive_estimated_bill_share'] == 1
    assert values['consecutive_zero_bill_share'] == 1
    assert stats['delayed_bill_share'] == [1, 2]
    # January's unresolved block still exists, but the old move-in is not a new event.
    assert values['active_billing_blocks'] == 1 and values['move_ins'] == 0
    assert measure_quality(run, 65, 65.999, since=64)[0]['estimated_bill_share'] is None
    assert measure_quality(run, 65, 65.999, since=60, timely_days=1)[1]['delayed_bill_share'] == [2, 2]
