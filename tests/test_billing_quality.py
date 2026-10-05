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
    docs = [doc(0, 0, 1, 31, 31, True), doc(1, 0, 2, 59, 70, True, 0),
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
              cfg=NS(kpi=NS(on_time_bill_days=3), customers_billing=NS(due_days=20)))


def test_bill_populations_exclude_future_versions_and_distinguish_current_from_ever_blocked(run):
    values, stats = measure_quality(run, 65, 65.999)
    assert values['estimated_bill_share'] == .6667
    assert values['consecutive_estimated_bill_share'] == .3333
    assert values['consecutive_zero_bill_share'] == .3333
    assert values['active_billing_blocks'] == 2
    assert values['delayed_bill_share'] == .6667
    assert measure_quality(run, 62, 62.999)[0]['delayed_bill_share'] == .3333
    assert stats['estimated_bill_share'] == [2, 3]
    assert set(values) == {m['id'] for m in METRICS}
    run.books.docs[0]['reversed'] = 64
    later = measure_quality(run, 65, 65.999)[0]
    assert later['estimated_bill_share'] == .5
    assert later['consecutive_estimated_bill_share'] == 0
    assert measure_quality(run, 63, 63.999)[0]['consecutive_estimated_bill_share'] == .3333


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
