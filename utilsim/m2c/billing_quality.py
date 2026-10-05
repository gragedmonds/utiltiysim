"""Billing assurance measures. Populations and windows are explicit; no missing data becomes zero."""
from __future__ import annotations

from collections import defaultdict

import numpy as np


def metric(id, title, unit, definition, formula, sources, *, better='lower', family='billing', thresholds=()):
    return {'id': id, 'title': title, 'family': family, 'unit': unit, 'better': better,
            'goals': ('billing', 'reading') if family == 'reading' else ('billing',),
            'definition': definition, 'formula': formula, 'sources': sources, 'thresholds': thresholds,
            'where': ('Command Center · Your KPIs', 'Workspace · Run statistics')}


METRICS = (
    metric('active_services', 'Active services', 'count', 'Supply contracts active on the view date. A multi-service account contributes one contract per service.', 'count(active supply contracts)', ['accounts'], better='context'),
    metric('service_setup_defects', 'Active service setup defects', 'count', 'Active contracts with a missing account or installation, a premise mismatch, or overlapping active contracts for one installation.', 'count(active contracts failing reference or uniqueness checks)', ['accounts', 'meters']),
    metric('move_ins', 'Move-ins', 'count', 'Premises with a recorded move-in date this year through the view date.', 'count(0 ≤ move-in day ≤ view day)', ['accounts'], better='context'),
    metric('move_outs', 'Move-outs', 'count', 'Premises with a recorded move-out date this year through the view date.', 'count(0 ≤ move-out day ≤ view day)', ['accounts'], better='context'),
    metric('net_terms_mismatch_share', 'Invoice net-term mismatches', 'share', 'Created invoices whose original due date minus issue date differs from the configured payment term. Later payment arrangements do not count as defects.', 'invoices with original due − issued ≠ configured due days ÷ created invoices', ['invoices']),
    metric('delayed_bill_share', 'Delayed invoices', 'share', 'Scheduled account-month cycles with any service invoiced after its deadline, or still awaiting issue after that deadline. Includes reads and billing documents held upstream, and invoice print lag. Each service uses its own scheduled read day; an account-cycle is counted once.', 'late or overdue unissued account-cycles ÷ scheduled account-cycles', ['invoices', 'bills', 'schedule'], thresholds=('kpi.timely_invoice_days',)),
    metric('estimated_bill_share', 'Estimated invoices', 'share', 'Issued invoices containing at least one estimated service charge. A multi-service invoice counts once. Subsequent reversals do not rewrite what was originally issued.', 'issued invoices containing an estimated charge ÷ issued invoices', ['invoices', 'bills', 'released']),
    metric('move_boundary_estimate_share', 'Move-boundary invoices estimated', 'share', 'Issued invoices containing an estimated service period spanning a recorded move-in or move-out, among invoices with such a boundary. This is not a separate first/final settlement workflow.', 'issued invoices with an estimated move-boundary charge ÷ issued move-boundary invoices', ['invoices', 'bills', 'accounts']),
    metric('consecutive_estimated_bill_share', 'Consecutive estimated invoices', 'share', 'Issued invoices containing an estimated charge for a month whose immediately preceding account-month was also estimated on a previously issued invoice. Missing months break the sequence; multiple services, corrective versions and two months on one invoice do not add consecutive cycles. Previously issued corrections update the preceding cycle for later invoices.', 'issued invoices continuing a 2+ month estimate sequence ÷ issued invoices', ['invoices', 'bills']),
    metric('consecutive_zero_bill_share', 'Consecutive zero-use invoices', 'share', 'Issued invoices with all-zero import and export charges whose preceding account-month on a previously issued invoice was also all zero. Missing months break the sequence. Fixed charges may still apply.', 'issued invoices continuing a 2+ month zero-use sequence ÷ issued invoices', ['invoices', 'bills']),
    metric('bill_period_defect_share', 'Invoice period defects', 'share', 'Issued invoices containing a non-finite, non-positive or overlapping service period for the same installation and account. Corrective versions of the same period and different services are not overlaps.', 'issued invoices with a defective service period ÷ issued invoices', ['invoices', 'bills', 'schedule']),
    metric('due_date_defect_share', 'Invoice due-date defects', 'share', 'Created invoices with missing/non-finite issue or due dates, or an original due date before issue.', 'invoices with invalid original due or issue dates ÷ created invoices', ['invoices']),
    metric('rebill_share', 'Corrective invoices', 'share', 'Issued invoices correcting a charge on a previously issued invoice. Document corrections made before first issue are excluded; their reversals remain visible in billing documents.', 'issued invoices replacing a previously invoiced charge ÷ issued invoices', ['invoices', 'bills']),
    metric('multiple_invoice_cycle_share', 'Cycles with multiple invoices', 'share', 'Account/cycle-month combinations represented on more than one issued invoice. Staggered services and corrective invoices can legitimately produce this; it is an audit indicator.', 'account/cycle combinations with 2+ invoices ÷ invoiced account/cycle combinations', ['invoices', 'bills'], better='context'),
    metric('zero_customer_charge_share', 'Invoices without a customer charge', 'share', 'Issued invoices with no non-zero fixed charge across their service lines, reconstructed from the tariff calculation. Zero-fixed-charge tariffs are included; this does not detect an external print omission.', 'issued invoices with no non-zero computed fixed charge ÷ issued invoices', ['invoices', 'bills']),
    metric('move_prorated_charge_count', 'Invoices with move-boundary prorated charges', 'count', 'Issued invoices with at least one move-boundary charge prorated by read-period duration. Each invoice counts once. Proration uses read days, not a separate move settlement period.', 'count(issued invoices with a non-zero move-boundary fixed charge)', ['invoices', 'bills', 'accounts'], better='context'),
    metric('invoices_pending_issue', 'Invoices awaiting issue', 'count', 'Invoices already created whose planned issue day is after the view date. This is print-lag workload; the engine does not record actual print completion.', 'count(created invoices with planned issue after view time)', ['invoices'], better='context'),
    metric('billing_exceptions', 'Billing exceptions raised', 'count', 'Billing-check and billing-dispute cases raised this year through the view date, including subsequently resolved cases. This is the model equivalent of a billing exception workload, not SAP BPEM telemetry.', 'count(year-to-date billing check and dispute cases)', ['cases']),
    metric('active_billing_blocks', 'Active billing-document blocks', 'count', 'Current documents with a billing case that remain unreleased at the view date. Account-level invoice holds are counted separately.', 'count(current case-blocked documents not released by view time)', ['bills', 'cases']),
    metric('active_invoice_holds', 'Active invoice holds', 'count', 'Account-level invoice holds in force at the view date.', 'count(hold start ≤ view time < hold end)', ['cases', 'invoices']),
    metric('meterless_billed_accounts', 'Invoiced accounts without a linked meter', 'count', 'Active accounts with invoices issued this year that have no meter linked through an active supply contract on the view date. This is a reference-integrity check, not a zero-consumption check.', 'count(active invoiced accounts without a current linked meter)', ['accounts', 'meters', 'invoices']),
    metric('active_reading_blocks', 'Active read-release blocks', 'count', 'Scheduled active register periods whose read was attempted, has a case, and remains unreleased. These are VEE/review holds; administrative meter-reading blocks are not separately modelled.', 'count(attempted register periods with a case and release after view time)', ['reads', 'released', 'cases'], family='reading'),
    metric('outstanding_reads', 'Open scheduled reads', 'count', 'Scheduled active register periods due by the view date without a released value, including missing and held reads. Future and service-off periods are excluded.', 'count(due active register periods with release after view time)', ['schedule', 'released'], family='reading'),
    metric('early_read_share', 'Reads taken early', 'share', 'Actual observations taken on a calendar day before the scheduled read day. Estimates and missing observations are excluded.', 'early actual observations ÷ actual observations taken by view time', ['schedule', 'reads'], family='reading', better='context'),
    metric('late_read_share', 'Reads taken late', 'share', 'Actual observations taken on a calendar day after the scheduled read day. Same-day time-of-day differences do not count as late.', 'late actual observations ÷ actual observations taken by view time', ['schedule', 'reads'], family='reading'),
    metric('active_implausibles', 'Open implausible-read cases', 'count', 'Unresolved VEE anomaly cases at the view date. Missing-read, billing, field-order and invoice-hold cases are excluded.', 'count(open VEE anomaly cases)', ['cases', 'decisions'], family='reading'),
    metric('active_meterless_accounts', 'Active accounts without a linked meter', 'count', 'Active accounts without a meter linked through an active contract, installation and service point. An unmetered tariff may be intentional; review the account.', 'count(active accounts with no current meter association)', ['accounts', 'meters'], family='reading'),
    metric('orphaned_meters', 'Meters without an active account', 'count', 'Installed active meter records with no active supply contract linked to a known active account. Vacancies can be legitimate; retired meters are excluded.', 'count(active installed meters with no active account association)', ['meters', 'accounts'], family='reading', better='context'),
)


def measure_quality(run, day, T, *, cycles=None, since=0, timely_days=None):
    """Events in [since, T]; outstanding work and reference audits at T, including older work."""
    from utilsim.m2c.catalog import BILL_TYPES
    from utilsim.twin.kpis import VEE_TYPES

    tw, bk, cal = run.town, run.books, run.cal
    pairs = {}
    def count(key, value):
        pairs[key] = [int(value), 1]
    def share(key, value, denominator):
        pairs[key] = [int(value), int(denominator)]

    docs = [d for d in bk.docs if 0 <= d['created'] <= T]
    current = [d for d in docs if d['reversed'] is None or d['reversed'] > T]
    from utilsim.m2c.invoice_metrics import (
        expected_cycles,
        issue_time,
        issued_invoices,
        quality_counts,
        timing_counts,
    )
    all_issued = issued_invoices(run, T)
    invoices = [i for i in all_issued if issue_time(i) >= since]
    all_created = [i for i in bk.invoices if 0 <= i['created'] <= T]
    created = [i for i in all_created if i['created'] >= since]
    q = quality_counts(run, all_issued, since=since)
    _, late, total = timing_counts(expected_cycles(run, T, since) if cycles is None else cycles, T,
                                  run.cfg.kpi.timely_invoice_days if timely_days is None else timely_days)
    share('estimated_bill_share', q['estimated'], len(invoices))
    share('delayed_bill_share', late, total)
    share('consecutive_estimated_bill_share', q['consecutive_estimated'], len(invoices))
    share('consecutive_zero_bill_share', q['consecutive_zero'], len(invoices))
    share('bill_period_defect_share', q['bad_period'], len(invoices))
    share('move_boundary_estimate_share', q['boundary_estimated'], q['boundary'])
    count('move_prorated_charge_count', q['prorated'])
    share('rebill_share', q['replacement'], len(invoices))
    count('active_billing_blocks', sum(d['case'] >= 0 and (d['released'] is None or d['released'] > T) for d in current))
    count('active_invoice_holds', sum(start <= T and (end is None or T < end) for holds in run.holds.values() for start, end, _ in holds))
    import math
    def invalid(v):
        return not isinstance(v, (int, float)) or not math.isfinite(v)
    share('due_date_defect_share', sum(invalid(i.get('due')) or invalid(i.get('issued')) or i['due'] < i['issued'] for i in created), len(created))
    share('net_terms_mismatch_share', sum(invalid(i.get('due')) or invalid(i.get('issued')) or abs(i['due'] - i['issued'] - run.cfg.customers_billing.due_days) > 1e-7 for i in created), len(created))
    count('invoices_pending_issue', sum(not invalid(i.get('issued')) and i['issued'] > T for i in all_created))
    share('zero_customer_charge_share', q['no_fixed'], len(invoices))
    share('multiple_invoice_cycle_share', q['multiple_cycles'], q['cycles'])
    count('billing_exceptions', sum(since <= c.created <= T and c.type in (*BILL_TYPES, 'BILL_DISPUTE') for c in run.cases))
    count('active_implausibles', sum(c.created <= T and c.type in VEE_TYPES and not c.work and (c.resolved is None or c.resolved > T) for c in run.cases))
    scheduled, observed = tw.read_day[:, 1:], run.taken_t(slice(None), slice(1, None))
    due = (scheduled <= day) & (run.status[:, 1:] != 6)
    unreleased = run.release_t[:, 1:] > T
    count('outstanding_reads', np.sum(due & unreleased))
    count('active_reading_blocks', np.sum(due & unreleased & (observed <= T) & (run.case_of[:, 1:] >= 0)))
    actual = (run.status[:, 1:] != 6) & (observed >= since) & (observed <= T) & np.isfinite(run.obs[:, 1:])
    share('early_read_share', np.sum(actual & (np.floor(observed) < scheduled)), np.sum(actual))
    share('late_read_share', np.sum(actual & (np.floor(observed) > scheduled)), np.sum(actual))
    count('move_ins', np.sum((tw.move_in >= since) & (tw.move_in <= day)))
    count('move_outs', np.sum((tw.move_out >= since) & (tw.move_out <= day)))
    master = tw.audit_master
    def active(row):
        return (row.get('status') not in ('inactive', 'retired', 'cancelled') and
                cal.parse_day((row.get('validFrom') or '')[:10], -10**6) <= day < cal.parse_day((row.get('validTo') or '')[:10], 10**6))
    accounts = {a['id']: a for a in master.get('accounts', []) if active(a)}
    installations = {i['id']: i for i in master.get('installations', [])}
    contracts = [c for c in master.get('contracts', []) if active(c)]
    meters = {m['id']: m for m in master.get('meters', []) if active(m) and
              cal.parse_day((m.get('installedAt') or '')[:10], -10**6) <= day <
              cal.parse_day((m.get('removedAt') or '')[:10], 10**6)}
    service_points = {s['id']: s for s in master.get('servicePoints', [])}
    per_inst = defaultdict(list)
    for c in contracts:
        per_inst[c['installationId']].append(c)
    linked_accounts, linked_meters, defects = set(), set(), 0
    by_sp = defaultdict(list)
    for m in meters.values():
        by_sp[m.get('servicePointId')].append(m['id'])
    for c in contracts:
        account, inst = accounts.get(c.get('accountId')), installations.get(c['installationId'])
        bad = account is None or inst is None or account.get('premiseId') != inst.get('premiseId') or len(per_inst[c['installationId']]) > 1
        defects += bad
        if account is not None and inst is not None and inst.get('servicePointId') in service_points:
            associated = by_sp.get(inst['servicePointId'], [])
            if associated:
                linked_accounts.add(c['accountId'])
                linked_meters.update(associated)
    count('active_services', len(contracts))
    count('service_setup_defects', defects)
    count('active_meterless_accounts', len(set(accounts) - linked_accounts))
    count('meterless_billed_accounts', len(({i['account'] for i in invoices} & set(accounts)) - linked_accounts))
    count('orphaned_meters', len(set(meters) - linked_meters))
    units = {m['id']: m['unit'] for m in METRICS}
    return {k: n if units[k] == 'count' else round(n / d, 4) if d else None for k, (n, d) in pairs.items()}, pairs
