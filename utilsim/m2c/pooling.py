"""Sufficient statistics for combining local views without averaging district averages."""
from __future__ import annotations

import numpy as np


def ratio(row, field, numerator, denominator):
    row.setdefault('_pool', {})[field] = [float(numerator), float(denominator)]


def mean(row, field, values):
    ratio(row, field, sum(values), len(values))


def contact_stats(run, row, start, end, reason=None):
    from utilsim.m2c.contact import contacts
    cx = contacts(run)
    mask = (cx.t >= start) & (cx.t <= end)
    if reason is not None:
        mask &= cx.reason == reason
    answered = mask & (cx.channel == 1) & (cx.outcome <= 1)
    handle = mask & np.isin(cx.channel, [1, 2]) & (cx.outcome <= 1)
    waits = cx.wait[answered]
    targets = np.array([run.cfg_at(int(t)).contact.service_target_s for t in cx.t[answered]])
    for field, values in [('asaS', waits), ('avgHandleMin', cx.handle[handle] / 60)]:
        if field in row:
            mean(row, field, values)
    if 'serviceLevelPct' in row:
        ratio(row, 'serviceLevelPct', int((waits <= targets).sum()), len(waits))
    if 'occupancyPct' in row:
        days = slice(int(start), int(end) + 1)
        ratio(row, 'occupancyPct', cx.daily['busyS'][days].sum(), cx.daily['availableS'][days].sum())


def field_stats(run, row, start, end, mask=None):
    from utilsim.m2c.fieldwork import DAY_CREWS, EMERGENCY, IDX, fieldwork
    fw = fieldwork(run)
    c = fw.cols
    done = ~c['cancelled'] & (c['end'] >= start) & (c['end'] <= end)
    if mask is not None:
        done &= mask
    em = done & np.isin(c['type'], [IDX[x] for x in EMERGENCY])
    resp = (c['arrive'][em] - c['created'][em]) * 1440
    local = done & ~c['remote']
    if 'onTimePct' in row:
        ratio(row, 'onTimePct', int((done & (c['met'] <= c['due'] + 1e-9)).sum()), int(done.sum()))
    if 'daysToComplete' in row:
        mean(row, 'daysToComplete', c['end'][local] - c['release'][local])
    if 'responseMin' in row:
        mean(row, 'responseMin', resp)
        row.setdefault('_samples', {})['responseP90Min'] = resp.tolist()
    if 'utilisationPct' in row:
        days = slice(int(start), int(end) + 1)
        ratio(row, 'utilisationPct', sum(fw.crews[x]['busyMin'][days].sum() for x in DAY_CREWS),
              sum(fw.crews[x]['availableMin'][days].sum() for x in DAY_CREWS))


def attach(path, result, run, params):
    """Add private merge data; the workspace strips it before returning a view."""
    from utilsim.m2c import fieldwork, views
    day, end = views.as_of_t(run, params.get('asOf'))
    if path == '/m2c/trend':
        for row in result['months']:
            if row.get('contact'):
                start = run.cal.parse_day(row['start'], 0)
                until = min(end, run.cal.parse_day(row['end'], day) + 1 - 1e-6)
                contact_stats(run, row['contact'], start, until)
                field_stats(run, row['field'], start, until)
    elif path == '/m2c/contact':
        contact_stats(run, result['kpis'], 0, end)
        for i, row in enumerate(result['reasons']):
            contact_stats(run, row, 0, end, i)
        for row in result['daily']:
            start = run.cal.parse_day(row['date'], 0)
            contact_stats(run, row, start, min(end, start + 1 - 1e-6))
    elif path == '/m2c/fieldwork':
        field_stats(run, result['kpis'], 0, end)
        cols = fieldwork.fieldwork(run).cols
        for i, row in enumerate(result['programs']):
            field_stats(run, row, 0, end, cols['program'] == i)
        for i, row in enumerate(result['types']):
            field_stats(run, row, 0, end, cols['type'] == i)
    elif path == '/m2c/summary':
        tw, bk = run.town, run.books
        mean(result['kpis'], 'avgDaysToRelease', [c.resolved - float(tw.read_day[c.r, c.month])
             for c in run.cases if c.work is None and c.resolved is not None and c.resolved <= end])
        issued = [inv for inv in bk.invoices if 0 <= inv['created'] <= end]
        from utilsim.m2c.invoice_metrics import issue_delays, issued_invoices
        mean(result['billing'], 'avgDaysToInvoice', issue_delays(run, issued_invoices(run, end)))
        mean(result['billing'], 'avgDaysToPay', [inv['paid'] - inv['issued'] for inv in issued
             if inv.get('paid') is not None and inv['paid'] <= end])
        for utility, row in result.get('reliability', {}).items():
            ratio(row, 'saidiMinutes', row['customerMinutes'], len(np.unique(tw.prem[tw.commodity == utility])))
        if result.get('window'):
            start = run.cal.parse_day(params['since'], 0)
            mean(result['window']['kpis'], 'avgDaysToRelease', [c.resolved - float(tw.read_day[c.r, c.month])
                 for c in run.cases if c.work is None and c.resolved is not None and start <= c.resolved <= end])
    elif path == '/process/costs':
        for row in result['types']:
            mean(row, 'avgDaysToRelease', [c.resolved - float(run.town.read_day[c.r, c.month]) for c in run.cases
                 if c.type == row['type'] and c.work is None and c.resolved is not None and 0 <= c.created <= end and c.resolved <= end])
            ratio(row, 'perCase', row['activityCost'] + row['carry'], row['count'])
    elif path == '/vee/scorecard':
        distributions = {}
        result = views.scorecard(run, as_of=params.get('asOf'), distributions=distributions)
        for row in result['anomalies']:
            if row['anomaly'] in distributions:
                row['_samples'] = {'medianDaysToFlag': distributions[row['anomaly']]}
    return result


def strip(value):
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in ('_pool', '_samples')}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value
