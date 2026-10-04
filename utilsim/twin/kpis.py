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
from utilsim.m2c.run import OFF, M2CRun

SHARE, DAYS, PER_1000 = "share", "days", "per_1000_accounts_year"

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
        "Share of invoices created within N days of the last scheduled read they bill (N is the spec's timelyDays, "
        "5 by default). The engine bills on an estimate rather than holding a bill, so this measure has a floor "
        "near 96 percent under heavy stress; a utility that counts an estimated bill as late wants "
        "estimated_read_share instead.", "higher", 0.005,
        (("automation", 1), ("vee_strictness", -1), ("pickup_lag", -1), ("analyst_hours", 1), ("missed_reads", -1),
         ("field_capacity", 1)),
        "The engine bills on an estimate rather than holding the bill, so read-to-invoice timeliness stays near or "
        "above 96 percent however stressed the year; a figure that counts an estimated bill as late is "
        "estimated_read_share (1 minus the share of bills on actual reads)."),
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
    Kpi("billing_error_share", "Billing error", SHARE,
        "Absolute difference between released bills and the simulation's true bills, as a share of the amount "
        "billed in the window.", "lower", 0.002, (("vee_strictness", -1), ("anomalies", 1))),
)
KPI_BY_ID: dict[str, Kpi] = {k.id: k for k in KPIS}


def tolerance_for(kpi: Kpi, target: float, given: float | None = None) -> float:
    """The residual the fit accepts: the spec's, else the dictionary's (for a rate, a share of the target, at least
    10 per 1,000)."""
    if given is not None:
        return float(given)
    return max(10.0, kpi.tolerance * abs(target)) if kpi.unit == PER_1000 else kpi.tolerance


def kpi_json(kpi: Kpi) -> dict:
    d = asdict(kpi)
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


def measure(run: M2CRun, w: Window, timely_days: int = 5, accounts: int | None = None) -> dict[str, float | None]:
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
    to_invoice = np.array([inv["created"] - max(float(tw.read_day[bk.main[bk.docs[k]["inst"]], bk.docs[k]["month"]])
                                                for k in inv["docs"]) for inv in invoices], dtype=float)
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
    docs = [d for d in bk.docs if d["released"] is not None and w.d0 <= d["released"] <= w.T]
    billed = float(sum(d["total"] for d in docs))
    error = float(sum(abs(d["total"] - d["truthTotal"]) for d in docs))

    def rate(count: int) -> float:
        return round(count / n_acc * 1000.0 * per_year, 2)

    def share(count: float, total: float, digits: int = 4) -> float | None:
        return round(count / total, digits) if total else None

    return {
        "invoice_timeliness": share(float((to_invoice <= timely_days).sum()), len(to_invoice)),
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
