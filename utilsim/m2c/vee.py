"""VEE: the five-test battery (VEE v5 shape), vectorised over one read batch.

Each test returns a risk contribution in [0, 0.25] and an outcome (passed, failed, not_applicable).
Confidence is 1 − 2·Σ risk, clipped to [0, 1]: one hard validation failure (≥ 0.14) drops a read below the default
accept cutoff, while soft signals alone do not. The disposition comes from the configured cutoffs and the bill impact:
- a register regression is rejected;
- at or above ``accept_confidence`` the read is accepted;
- below ``reject_confidence`` it is rejected;
- if the impact is at least ``escalate_impact`` it is escalated;
- otherwise it goes to review.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from utilsim.m2c.catalog import CODE_LIST

MIN_EXPECTED = {"kWh": 30.0, "m3": 1.0}  # below this expected period use, low/zero checks do not apply


@dataclass
class Batch:
    cons: np.ndarray  # observed consumption since the previous released read (nan = missing)
    regression: np.ndarray  # register lower than previous, not a rollover
    days: np.ndarray  # period length
    expected: np.ndarray  # expected consumption for the period
    unit: np.ndarray
    export: np.ndarray  # export register (zero is normal)
    occupied: np.ndarray
    moved: np.ndarray  # move-in or move-out inside the period
    consec: np.ndarray  # estimates in a row before this read
    prior_cases: np.ndarray  # implausible-value cases on this register in the last 180 days
    low_streak: np.ndarray  # released reads in a row below trend_ratio of expected (before this one)
    manual: np.ndarray
    price: np.ndarray  # $ per unit incl. tax (bill impact)


@dataclass
class Result:
    risk: np.ndarray  # (B, 5)
    applicable: np.ndarray  # (B, 5) bool
    code: np.ndarray  # index into CODE_LIST or -1
    ratio: np.ndarray
    confidence: np.ndarray
    disposition: np.ndarray  # 0 accept, 1 review, 2 escalate, 3 reject
    exception: np.ndarray  # exception type name ('' when accepted)
    impact: np.ndarray


def run(b: Batch, vee) -> Result:
    n = len(b.cons)
    ratio = np.where(b.expected > 0, b.cons / np.maximum(b.expected, 1e-9), np.where(b.cons > 0, np.inf, 1.0))
    floor = np.array([MIN_EXPECTED.get(u, 1.0) for u in b.unit]) if n else np.zeros(0)
    big = b.expected >= floor
    risk = np.zeros((n, 5))
    code = np.full(n, -1)
    # 1. SAP VEE diagnosis (simulated codes).
    high = ratio > vee.high_ratio
    low = (ratio < vee.low_ratio) & big & ~b.export & (b.cons > 0)
    zero = (b.cons == 0) & big & ~b.export & b.occupied & bool(vee.zero_at_occupied)
    t1 = np.zeros(n)
    t1 = np.where(high, 0.14 + 0.11 * np.minimum(1.0, (ratio - vee.high_ratio) / vee.high_ratio), t1)
    t1 = np.where(low, 0.15, t1)
    t1 = np.where(zero, 0.20, t1)
    t1 = np.where(b.regression, 0.25, t1)
    code = np.where(high, CODE_LIST.index("SIM-T01"), code)
    code = np.where(low, CODE_LIST.index("SIM-T02"), code)
    code = np.where(zero, CODE_LIST.index("SIM-Z01"), code)
    code = np.where(b.regression, CODE_LIST.index("SIM-C01"), code)
    lifecycle = b.moved & (code < 0)
    code = np.where(lifecycle, CODE_LIST.index("SIM-L01"), code)
    t1 = np.where(lifecycle, 0.05, t1)
    t1 = np.where(b.moved & ~b.regression, t1 * 0.5, t1)  # a move explains part of a change in use
    risk[:, 0] = t1
    # 2. Temporal validity.
    off = (b.days < vee.min_period_days) | (b.days > vee.max_period_days)
    risk[:, 1] = np.where(b.days > 2 * vee.max_period_days, 0.2, np.where(off, 0.1, 0.0))
    # 3. Consistency (erratic band, recent estimates).
    erratic = big & ((ratio > 1.6) | (ratio < 0.55)) & ~b.export
    risk[:, 2] = np.where(erratic, np.where(b.consec > 0, 0.12, 0.08), np.where(b.consec > 0, 0.03, 0.0))
    # Persistent under-registration: this read and the previous ones all below trend_ratio of expected.
    trend = big & ~b.export & (ratio < vee.trend_ratio) & (b.low_streak + 1 >= vee.trend_periods)
    risk[:, 2] = np.where(trend, np.maximum(risk[:, 2], 0.16), risk[:, 2])
    # 4. Process corroboration (repeat exceptions on the device). History strengthens a signal in this read; alone it
    # stays soft, or every read after a run of cases would raise another one.
    signal = (t1 > 0) | (risk[:, 1] > 0) | (risk[:, 2] > 0)
    risk[:, 3] = np.where(signal, np.minimum(0.25, 0.06 * b.prior_cases), np.minimum(0.05, 0.01 * b.prior_cases))
    # 5. Context signals (vacancy, technology).
    vacant_use = ~b.occupied & ~b.export & (ratio > 3.0) & (b.cons > floor)
    risk[:, 4] = np.minimum(0.25, np.where(vacant_use, 0.2, 0.0) + np.where(b.manual & (t1 > 0.1), 0.05, 0.0))
    applicable = np.ones((n, 5), dtype=bool)
    confidence = np.clip(1.0 - 2.0 * risk.sum(1), 0.0, 1.0)
    impact = np.abs(np.nan_to_num(b.cons) - b.expected) * b.price
    disp = np.where(confidence >= vee.accept_confidence, 0,
                    np.where(confidence < vee.reject_confidence, 3,
                             np.where(impact >= vee.escalate_impact, 2, 1)))
    disp = np.where(b.regression, 3, disp)
    exc = np.full(n, "", dtype=object)
    exc = np.where(risk[:, 2] > 0, "ERRATIC", exc)
    exc = np.where(trend, "PERSISTENT_LOW", exc)
    exc = np.where(risk[:, 1] > 0, "PERIOD_LENGTH", exc)
    exc = np.where(low, "LOW_USAGE", exc)
    exc = np.where(high, "HIGH_USAGE", exc)
    exc = np.where(vacant_use, "VACANT_CONSUMING", exc)
    exc = np.where(zero, "ZERO_USAGE", exc)
    exc = np.where(b.regression, "REGISTER_REGRESSION", exc)
    exc = np.where((exc == "") & (disp > 0), "ERRATIC", exc)
    exc = np.where(disp == 0, "", exc)
    return Result(risk, applicable, code, ratio, confidence, disp, exc, impact)


def explain(test: int, risk: float, *, code: str | None, ratio: float, days: float, expected: float, unit: str,
            consec: int, prior_cases: int, occupied: bool, moved: bool, manual: bool, vee,
            outage_h: float = 0.0) -> str:
    """One-line rationale for a test outcome (built when a decision is viewed)."""
    if test == 0:
        if code is None:
            return f"No validation code: {ratio:.2f}× expected ({expected:.1f} {unit}) is within tolerance."
        tail = " (half weight: a move in the period explains some change)" if moved and code != "SIM-C01" else ""
        return {"SIM-C01": "Register went backwards and the previous value was not near rollover.",
                "SIM-T01": f"{ratio:.2f}× expected use is above the high tolerance ({vee.high_ratio}×){tail}.",
                "SIM-T02": f"{ratio:.2f}× expected use is below the low tolerance ({vee.low_ratio}×){tail}.",
                "SIM-Z01": "No consumption at an occupied premise where use is expected.",
                "SIM-L01": "A move-in or move-out falls inside this read period.",
                }.get(code, code)
    if test == 1:
        if risk == 0:
            return f"{days:.0f}-day period is within {vee.min_period_days}–{vee.max_period_days} days."
        return f"{days:.0f}-day period is outside {vee.min_period_days}–{vee.max_period_days} days."
    if test == 2:
        parts = []
        if risk >= 0.16 and ratio < vee.trend_ratio:
            parts.append(f"use has stayed below {vee.trend_ratio:.0%} of expected for {vee.trend_periods}+ periods")
        if risk and (ratio > 1.6 or ratio < 0.55):
            parts.append(f"use is erratic against history ({ratio:.2f}×)")
        if consec:
            parts.append(f"follows {consec} estimate{'s' if consec > 1 else ''}")
        return ("Consistent with history." if not parts else "; ".join(parts).capitalize() + ".")
    if test == 3:
        if not prior_cases:
            return "No recent exceptions on this register."
        n = f"{prior_cases} exception{'s' if prior_cases > 1 else ''} on this register in the last 180 days"
        return n + (" corroborate this read's other signals." if risk > 0.05 else
                    "; with no other signal in this read they weigh lightly.")
    parts = []
    if not occupied:
        parts.append("premise is vacant" + (" but consuming" if risk >= 0.2 else ""))
    if manual:
        parts.append("walked read (keyed by hand)")
    if moved:
        parts.append("move inside the period")
    if outage_h > 0 and vee.oms_events:
        parts.append(f"{outage_h:.1f} h without service in the period (outage events lowered the expected use)")
    return ("No context concerns." if not parts else "; ".join(parts).capitalize() + ".")
