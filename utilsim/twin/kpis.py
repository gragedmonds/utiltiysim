"""The twin's KPI dictionary: the figures a utility knows about its year, each pinned to one measure of a
meter-to-cash run over a window of days.

A utility's "invoice timeliness" or "exceptions" can mean several things; the twin fits the definition written
here, and says so in its report. Shares are 0 to 1, rates are per 1,000 accounts in the year (annualised over the
window), days are calendar days. ``measure`` computes every KPI from one run in one pass, so a replay serves every
target at once.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from utilsim.m2c import catalog as cat
from utilsim.m2c import collections as colls
from utilsim.m2c.billing_quality import METRICS as BILLING_METRICS
from utilsim.m2c.run import OFF, M2CRun

SHARE, DAYS, PER_1000, COUNT = "share", "days", "per_1000_accounts_year", "count"

# A case a person touched: an analyst, a supervisor or you. RPA and automatic estimates are not people.
PERSON_EVENTS = frozenset(k for k in cat.EVENTS if k.startswith(("ANALYST_", "SUPERVISOR_")) or k == "USER_ACTION")
# VEE's own exceptions: not the missing reads it estimates, not the billing blocks.
VEE_TYPES = tuple(k for k in cat.EXCEPTIONS if k not in cat.MISSING_TYPES and k not in cat.BILL_TYPES)


@dataclass(frozen=True)
class Kpi:
    """One observable figure. ``levers``: the named levers that move it, most direct first, each with +1 when
    raising the lever raises the KPI and -1 when it lowers it. ``tolerance``: the residual the fit accepts (for a
    rate, a share of the target, see ``tolerance_for``)."""

    id: str
    label: str
    unit: str
    description: str
    better: str
    tolerance: float
    levers: tuple[tuple[str, int], ...]
    unfitted_note: str = ""  # what to tell a reader when the fit cannot reach the observed value


KPIS: tuple[Kpi, ...] = (
    Kpi("invoice_timeliness", "Invoice timeliness", SHARE,
        "Share of scheduled account-month cycles fully issued within N calendar days of each service's scheduled "
        "read (timelyDays, 5 by default). Includes upstream holds and print lag; pending cycles are not timely.",
        "higher", 0.005,
        (("print_lag", -1), ("automation", 1), ("vee_strictness", -1), ("pickup_lag", -1), ("analyst_hours", 1), ("missed_reads", -1),
         ("field_capacity", 1)),
        "Timeliness measures invoice issue, not whether the charges were estimated."),
    Kpi("missed_read_share", "Missed reads", SHARE,
        "Share of scheduled billing reads with no read taken (AMI dropouts, drive-by misses, no access).", "lower",
        0.005, (("missed_reads", 1),)),
    Kpi("estimated_read_share", "Estimated reads", SHARE,
        "Share of scheduled billing reads released to billing as an estimate.", "lower", 0.005,
        (("missed_reads", 1), ("field_capacity", -1), ("anomalies", 1))),
    Kpi("exceptions_all", "Exceptions, every case", PER_1000,
        "Every clarification case opened, per 1,000 accounts a year: missed reads, VEE exceptions, billing blocks, "
        "disputes and complaints, whoever resolved them.", "lower", 0.05,
        (("missed_reads", 1), ("anomalies", 1), ("vee_strictness", 1))),
    Kpi("exceptions_worked", "Exceptions a person worked", PER_1000,
        "Cases an analyst, a supervisor or you touched, per 1,000 accounts a year. What a billing team usually "
        "counts as its exceptions: automation's own resolutions are left out.", "lower", 0.05,
        (("automation", -1), ("vee_strictness", 1), ("anomalies", 1), ("missed_reads", 1))),
    Kpi("exceptions_vee", "VEE exceptions", PER_1000,
        "Cases VEE's own tests raised (high, low, zero and erratic use, register regression, odd periods, "
        "persistent low use, vacant but consuming), per 1,000 accounts a year.", "lower", 0.05,
        (("vee_strictness", 1), ("anomalies", 1))),
    Kpi("case_backlog", "Open cases", PER_1000,
        "Cases open at the end of the window, per 1,000 accounts.", "lower", 0.05,
        (("analyst_hours", -1), ("automation", -1), ("pickup_lag", 1), ("vee_strictness", 1), ("missed_reads", 1))),
    Kpi("days_to_release", "Days to release a held read", DAYS,
        "Average calendar days from the scheduled read to the day its case released it to billing, for cases "
        "resolved in the window.", "lower", 0.5,
        (("pickup_lag", 1), ("automation", -1), ("analyst_hours", -1), ("field_capacity", -1))),
    Kpi("days_to_pay", "Days to pay", DAYS,
        "Average days from an invoice's issue to its payment in full, for invoices created in the window and paid "
        "by its end. No run lever moves it: payer behaviour is a town setting (on-time and late payer shares), so "
        "the twin reports it but cannot fit it yet.", "lower", 0.5, ()),
    Kpi("collected_share", "Cash collected", SHARE,
        "Payments received in the window as a share of the amount invoiced in it. Not fitted yet (payer behaviour "
        "is a town setting).", "higher", 0.01, ()),
    Kpi("billing_error_share", "Invoice amount error", SHARE,
        "Absolute net invoice error against simulated truth, divided by absolute net amounts issued in the window. "
        "Corrective invoices include credits in both the actual and truth totals.", "lower", 0.002, (("vee_strictness", -1), ("anomalies", 1))),
)
# Use the same assurance definitions as the Command Center. Only assign fitting levers
# with an engine connection; structural audits remain useful comparison observations.
QUALITY_LEVERS = {
    'delayed_bill_share': (("print_lag", 1), ("pickup_lag", 1), ("analyst_hours", -1)),
    'estimated_bill_share': (("missed_reads", 1), ("anomalies", 1), ("field_capacity", -1)),
    'consecutive_estimated_bill_share': (("missed_reads", 1), ("anomalies", 1), ("field_capacity", -1)),
    'consecutive_zero_bill_share': (("anomalies", 1),),
    'move_boundary_estimate_share': (("missed_reads", 1), ("anomalies", 1)),
    'invoices_pending_issue': (("print_lag", 1),),
    'active_billing_blocks': (("analyst_hours", -1), ("automation", -1), ("pickup_lag", 1)),
    'active_reading_blocks': (("analyst_hours", -1), ("automation", -1), ("pickup_lag", 1)),
    'outstanding_reads': (("missed_reads", 1), ("analyst_hours", -1), ("field_capacity", -1)),
    'active_implausibles': (("anomalies", 1), ("vee_strictness", 1), ("analyst_hours", -1)),
}
KPIS += tuple(Kpi(m['id'], m['title'], m['unit'], m['definition'], m['better'],
                  .05 if m['unit'] == COUNT else .005, QUALITY_LEVERS.get(m['id'], ()))
              for m in BILLING_METRICS)
KPI_BY_ID: dict[str, Kpi] = {k.id: k for k in KPIS}


def tolerance_for(kpi: Kpi, target: float, given: float | None = None) -> float:
    """The residual the fit accepts: the spec's, else the dictionary's (for a rate, a share of the target, at least
    10 per 1,000)."""
    if given is not None:
        return float(given)
    if kpi.unit in (PER_1000, COUNT):
        return max(10.0 if kpi.unit == PER_1000 else 1.0, kpi.tolerance * abs(target))
    return kpi.tolerance


def kpi_json(kpi: Kpi) -> dict:
    from utilsim.m2c.kpis import KPI_BY_ID as CATALOGUE
    d = asdict(kpi)
    d['family'] = CATALOGUE[kpi.id].family
    d['fitMode'] = 'adjustable' if kpi.levers else 'comparison'
    d['fitNote'] = ('The fit can adjust engine settings that influence this KPI.' if kpi.levers else
                    'The current fitter has no adjustable setting for this KPI. '
                    'Your observation is retained and compared with the simulation; no change is promised.')
    if kpi.unit == COUNT:
        d['fitNote'] += ' Enter the count across your utility. Calibration counts are scaled by customer accounts.'
    if kpi.id in {m['id'] for m in BILLING_METRICS}:
        d['fitNote'] += ' Event measures use the selected period; active and outstanding counts use its final day.'
    d["levers"] = [{"lever": lever, "direction": direction} for lever, direction in kpi.levers]
    return d


@dataclass(frozen=True)
class Window:
    """Run days ``d0`` to ``day`` inclusive; ``T`` is the end of the last day."""

    d0: int
    day: int
    T: float

    @property
    def days(self) -> int:
        return self.day - self.d0 + 1


def window(run: M2CRun, since: str | None = None, until: str | None = None) -> Window:
    """The window from ``since`` (a date of the run's year; default 1 January) to ``until`` (default 31 December)."""
    cal = run.cal
    d0 = min(max(cal.parse_day(since, 0), 0), cal.days - 1)
    day = min(max(cal.parse_day(until, cal.days - 1), d0), cal.days - 1)
    return Window(d0, day, day + 1 - 1e-6)


def _mean(values: list[float]) -> float | None:
    return round(float(np.mean(values)), 4) if values else None


def measure(run: M2CRun, w: Window, timely_days: int = 5, accounts: int | None = None,
            statistics: dict | None = None, *, cycles=None, include_quality=True) -> dict[str, float | None]:
    """Every KPI of ``run`` inside ``w`` (None when the window holds nothing to measure). ``accounts`` is the
    denominator of the rates: by default the town's accounts in the year."""
    tw, bk = run.town, run.books
    n_acc = accounts or len(tw.account_method)
    per_year = run.cal.days / w.days
    months = slice(1, 13)
    read_day, read_t = tw.read_day[:, months], run.read_t[:, months]
    obs, status, release = run.obs[:, months], run.status[:, months], run.release_t[:, months]
    sched = (read_day >= w.d0) & (read_day <= w.day) & (read_t <= w.T) & (status != OFF)
    n_sched = int(sched.sum())
    missed = int((sched & np.isnan(obs)).sum())
    estimated = int((sched & (status == 2) & (release <= w.T)).sum())
    invoices = [inv for inv in bk.invoices if w.d0 <= inv["created"] <= w.T]
    from utilsim.m2c.invoice_metrics import expected_cycles, invoice_error, issued_invoices, timing_counts
    cycles = expected_cycles(run, w.T, w.d0) if cycles is None else cycles
    timely, _, n_cycles = timing_counts(cycles, w.T, timely_days)
    to_pay = [inv["paid"] - inv["issued"] for inv in invoices if inv.get("paid") is not None and inv["paid"] <= w.T]
    invoiced = float(sum(inv["total"] for inv in invoices))
    collected = float(sum(p["amount"] for inv in bk.invoices if inv["created"] <= w.T for p in inv["payments"]
                          if w.d0 <= p["at"] <= w.T and p["status"] in colls.PAID))
    opened = [c for c in run.cases if w.d0 <= c.created <= w.T]
    worked = sum(1 for c in opened if any(k in PERSON_EVENTS and t <= w.T for t, k, _, _ in c.events))
    vee = sum(1 for c in opened if c.type in VEE_TYPES)
    backlog = sum(1 for c in run.cases if c.created <= w.T and (c.resolved is None or c.resolved > w.T))
    release_days = [c.resolved - float(tw.read_day[c.r, c.month]) for c in run.cases
                    if c.work is None and c.resolved is not None and w.d0 <= c.resolved <= w.T]
    error, billed = invoice_error(run, issued_invoices(run, w.T, w.d0))

    if statistics is not None:
        statistics.update({
            'invoice_timeliness': [timely, n_cycles],
            'missed_read_share': [missed, n_sched], 'estimated_read_share': [estimated, n_sched],
            'exceptions_all': [len(opened) * 1000 * per_year, n_acc],
            'exceptions_worked': [worked * 1000 * per_year, n_acc],
            'exceptions_vee': [vee * 1000 * per_year, n_acc], 'case_backlog': [backlog * 1000, n_acc],
            'days_to_release': [sum(release_days), len(release_days)],
            'days_to_pay': [sum(to_pay), len(to_pay)], 'collected_share': [collected, invoiced],
            'billing_error_share': [error, billed],
        })

    def rate(count: int) -> float:
        return round(count / n_acc * 1000.0 * per_year, 2)

    def share(count: float, total: float, digits: int = 4) -> float | None:
        return round(count / total, digits) if total else None

    values = {
        "invoice_timeliness": share(timely, n_cycles),
        "missed_read_share": share(missed, n_sched),
        "estimated_read_share": share(estimated, n_sched),
        "exceptions_all": rate(len(opened)),
        "exceptions_worked": rate(worked),
        "exceptions_vee": rate(vee),
        "case_backlog": round(backlog / n_acc * 1000.0, 2),
        "days_to_release": _mean(release_days),
        "days_to_pay": _mean(to_pay),
        "collected_share": share(collected, invoiced),
        "billing_error_share": share(error, billed, 5),
    }
    if include_quality:
        from utilsim.m2c.billing_quality import measure_quality
        quality, quality_stats = measure_quality(run, w.day, w.T, cycles=cycles, since=w.d0,
                                                 timely_days=timely_days)
        values.update(quality)
        if statistics is not None:
            statistics.update(quality_stats)
    return values
