"""Customer invoice populations, distinct from the upstream installation billing documents.

Issue is the engine's planned issue day (there is no external print acknowledgement).
Historical invoice contents never change when their documents are subsequently reversed.
"""
from __future__ import annotations

import math
from collections import defaultdict


def issue_time(invoice):
    issued = invoice.get('issued')
    if not isinstance(issued, (int, float)) or not math.isfinite(issued):
        return math.inf
    return max(invoice['created'], issued)


def issued_invoices(run, T, since=0):
    return sorted((i for i in run.books.invoices if since <= issue_time(i) <= T),
                  key=lambda i: (issue_time(i), i['id']))


def scheduled_day(run, doc):
    if doc.get('carried'):
        return run.books.period(doc)[1]
    return float(run.town.read_day[run.books.main[doc['inst']], doc['month']])


def issue_delays(run, invoices):
    return [max(0, issue_time(i) - max(scheduled_day(run, run.books.docs[k]) for k in i['docs']))
            for i in invoices if i['docs']]


def corrective_invoices(run, invoices):
    """A customer correction replaces a charge on a previously issued invoice."""
    dates = {k: issue_time(i) for i in run.books.invoices for k in i['docs']}
    return {i['id'] for i in invoices if any(
        (previous := run.books.docs[k].get('replaces', -1)) >= 0 and previous not in i['docs']
        and dates.get(previous, math.inf) <= issue_time(i) for k in i['docs'])}


def invoice_error(run, invoices):
    """Net invoice versus net truth, including the credit for a previously invoiced version."""
    bk = run.books
    error, amount = 0., 0.
    for inv in invoices:
        truth = 0.
        for k in inv['docs']:
            d = bk.docs[k]
            truth += d['truthTotal']
            previous = d.get('replaces', -1)
            if previous >= 0 and bk.docs[previous].get('invoice', -1) >= 0:
                # The customer is credited what they were actually charged before.
                # A correct refund of an old overcharge is not a fresh invoice error.
                truth -= bk.docs[previous]['total']
        error += abs(inv['total'] - truth)
        amount += abs(inv['total'])
    return error, amount


def expected_cycles(run, T, since=0):
    """Account/month obligations, including reads that have not produced a document yet.

    Each service keeps its own scheduled deadline. Multiple registers, services and
    replacement documents cannot inflate the account-cycle denominator. A correction
    does not erase an original late issue or count as a new scheduled obligation.
    """
    bk, tw = run.books, run.town
    cycles = defaultdict(dict)
    for inst, row in enumerate(bk.main):
        for month in range(1, 13):
            scheduled = float(tw.read_day[row, month])
            if not since <= scheduled <= T or run.status[row, month] == 6:
                continue
            doc = {'inst': inst, 'month': month}
            account = bk.account(doc)
            cycles[account, month][inst] = {'scheduled': scheduled, 'issued': math.inf, 'blocked': False}
    for d in bk.docs:
        if d['created'] > T or d.get('carried'):
            continue
        services = cycles.get((bk.account(d), d['month']))
        if services and d['inst'] in services:
            services[d['inst']]['blocked'] |= d['case'] >= 0
    for inv in bk.invoices:
        at = issue_time(inv)
        if at > T:
            continue
        for k in inv['docs']:
            d = bk.docs[k]
            services = cycles.get((inv['account'], d['month'])) if not d.get('carried') else None
            if services and d['inst'] in services:
                service = services[d['inst']]
                service['issued'] = min(service['issued'], at)
    return list(cycles.values())


def timing_counts(cycles, T, days):
    """Whole calendar-day deadlines; pending obligations still inside their window are neither late nor timely."""
    on_time = late = 0
    for services in cycles:
        on_time += all(math.isfinite(s['issued']) and math.floor(s['issued']) - s['scheduled'] <= days
                       for s in services.values())
        late += any((math.floor(s['issued']) - s['scheduled'] > days if math.isfinite(s['issued'])
                     else T >= s['scheduled'] + days + 1) for s in services.values())
    return int(on_time), int(late), len(cycles)


def quality_counts(run, invoices):
    """One observation per issued invoice; preceding cycles use only evidence issued before it."""
    bk, tw = run.books, run.town
    history = defaultdict(dict)
    counts = dict.fromkeys(('estimated', 'consecutive_estimated', 'consecutive_zero', 'bad_period',
                            'boundary', 'boundary_estimated', 'prorated', 'replacement', 'no_fixed'), 0)
    cycles = defaultdict(set)
    corrections = corrective_invoices(run, invoices)
    for inv in invoices:
        docs = [bk.docs[k] for k in inv['docs']]
        flags = {k: False for k in counts}
        flags['estimated'] = any(d.get('estimated') for d in docs)
        flags['replacement'] = inv['id'] in corrections
        fixed = []
        # Check all lines before updating history: two months on ONE invoice are not consecutive invoices.
        for d in docs:
            start, end = bk.period(d)
            cycle = (inv['account'], d['month'])
            previous = list(history.get((inv['account'], d['month'] - 1), {}).values())
            if not d.get('carried'):
                flags['consecutive_estimated'] |= bool(d.get('estimated') and any(p.get('estimated') for p in previous))
                flags['consecutive_zero'] |= bool(previous and all(p['qImp'] == p['qExp'] == 0 for p in previous + docs))
            prior = [history[inv['account'], month][d['inst']] for month in range(1, d['month'])
                     if d['inst'] in history.get((inv['account'], month), {})]
            prior += [p for p in docs if p['inst'] == d['inst'] and p['month'] < d['month']]
            flags['bad_period'] |= (not math.isfinite(start + end) or end <= start or
                                    any(start < bk.period(p)[1] - 1e-7 for p in prior))
            premise = tw.prem[bk.main[d['inst']]]
            boundary = any(start <= move < end for move in (tw.move_in[premise], tw.move_out[premise]))
            charge = float(tw.tariffs.get(d['rate'], {}).get('fixedMonthly', 0)) * max(0, end - start) / (365 / 12)
            fixed.append(charge)
            flags['boundary'] |= boundary
            flags['boundary_estimated'] |= bool(boundary and d.get('estimated'))
            flags['prorated'] |= boundary and charge != 0
            if not d.get('carried'):
                cycles[cycle].add(inv['id'])
        flags['no_fixed'] = bool(docs) and not any(fixed)
        for d in docs:
            if not d.get('carried'):
                history[inv['account'], d['month']][d['inst']] = d
        for key, flag in flags.items():
            counts[key] += int(flag)
    counts['multiple_cycles'] = sum(len(v) > 1 for v in cycles.values())
    counts['cycles'] = len(cycles)
    return counts
