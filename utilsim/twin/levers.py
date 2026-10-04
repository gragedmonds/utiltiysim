"""The twin's levers: a handful of named, one-dimensional causes the fit may move, each setting a few run
settings together (the way the scenario library's episodes do). Fitting named levers instead of a hundred settings
keeps the answer identifiable and explainable: "missed reads at 2.4 times the default" says what happened.

Every lever's default reproduces the engine's defaults exactly, so a lever the fit never moved changes nothing. All
levers are run settings: the fit replays the same town, never regenerates it. Town settings a utility knows (AMI
share, payer mix, services) are inputs, not levers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from utilsim.config.model import AnomaliesConfig, SimConfig
from utilsim.config.presets import deep_merge

DEFAULTS = SimConfig()
ANOMALY_RATES = ("leak", "stuck_meter", "slow_meter", "transposed_digits", "misread", "consecutive_estimates",
                 "missing_read", "exchange_registration_failure", "vacant_consuming", "tamper")
# VEE tolerances from loose (0) through the engine's defaults (0.5) to tight (1): high ratio, low ratio, accept
# confidence. The ends are the scenario library's "VEE loosened" and "VEE tightened".
VEE_LOOSE, VEE_TIGHT = (3.5, 0.15, 0.60), (1.25, 0.70, 0.95)


def _upper(key: str) -> float:
    for m in AnomaliesConfig.model_fields[key].metadata:
        if getattr(m, "le", None) is not None:
            return float(m.le)
    return float("inf")


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def _missed_reads(k: float) -> dict:
    r = DEFAULTS.reading
    return {"reading": {"ami_missed_read": round(_clamp(r.ami_missed_read * k, 0.0, 1.0), 6),
                        "amr_missed_read": round(_clamp(r.amr_missed_read * k, 0.0, 1.0), 6),
                        "manual_no_access": round(_clamp(r.manual_no_access * k, 0.0, 1.0), 6)}}


def _anomalies(k: float) -> dict:
    a = DEFAULTS.anomalies
    return {"anomalies": {key: round(_clamp(getattr(a, key) * k, 0.0, _upper(key)), 6) for key in ANOMALY_RATES}}


def _vee_strictness(s: float) -> dict:
    v = DEFAULTS.vee
    mid = (v.high_ratio, v.low_ratio, v.accept_confidence)
    if s <= 0.5:
        t = s / 0.5
        high, low, accept = (a + t * (b - a) for a, b in zip(VEE_LOOSE, mid))
    else:
        t = (s - 0.5) / 0.5
        high, low, accept = (a + t * (b - a) for a, b in zip(mid, VEE_TIGHT))
    return {"vee": {"high_ratio": round(high, 4), "low_ratio": round(low, 4), "accept_confidence": round(accept, 4)}}


def _automation(v: float) -> dict:
    return {"process": {"rpa_coverage": round(v, 4)}}


def _pickup_lag(v: float) -> dict:
    lag = max(1, int(round(v)))
    return {"process": {"analyst_queue_days_min": lag, "analyst_queue_days_max": min(20, lag + 2)}}


def _analyst_hours(v: float) -> dict:
    return {"process": {"analyst_hours_per_day": round(v, 3)}}


def _field_capacity(v: float) -> dict:
    return {"process": {"field_orders_per_day": int(round(v))}}


@dataclass(frozen=True)
class Lever:
    """``patch(value)`` is the run settings the lever sets at ``value``; ``step`` is the fit's first probe."""

    id: str
    label: str
    description: str
    lo: float
    hi: float
    default: float
    step: float
    unit: str
    _patch: Callable[[float], dict]

    def patch(self, value: float) -> dict:
        return self._patch(_clamp(float(value), self.lo, self.hi))

    def json(self) -> dict:
        return {"id": self.id, "label": self.label, "description": self.description, "min": self.lo, "max": self.hi,
                "default": self.default, "step": self.step, "unit": self.unit,
                "settings": sorted(f"{g}.{k}" for g, vals in self.patch(self.default).items() for k in vals)}


LEVERS: dict[str, Lever] = {lever.id: lever for lever in (
    Lever("missed_reads", "Missed reads", "A multiplier on the chance a billing read is missed: AMI reads still "
          "missing after the retry window, drive-by misses and manual no-access, together.", 0.0, 12.0, 1.0, 1.0,
          "× default", _missed_reads),
    Lever("anomalies", "Meter and read anomalies", "A multiplier on every injected anomaly rate: leaks, stuck and "
          "slow meters, transposed digits, misreads, consecutive estimates, missing documents, failed exchange "
          "registrations, vacant premises consuming, tamper.", 0.0, 8.0, 1.0, 1.0, "× default", _anomalies),
    Lever("vee_strictness", "VEE strictness", "How tightly VEE flags: 0 is the loosened battery (wide tolerances, "
          "a low auto-accept bar), 0.5 the engine's defaults, 1 the tightened one (narrow tolerances, a high "
          "auto-accept bar).", 0.0, 1.0, 0.5, 0.25, "0–1", _vee_strictness),
    Lever("automation", "Automation", "The share of exception types an RPA rule resolves without a person.", 0.0,
          1.0, float(DEFAULTS.process.rpa_coverage), 0.25, "share", _automation),
    Lever("pickup_lag", "Pickup lag", "Business days a new exception waits before an analyst picks it up (the "
          "shortest wait; the longest is two days more).", 1.0, 10.0, float(DEFAULTS.process.analyst_queue_days_min),
          3.0, "days", _pickup_lag),
    Lever("analyst_hours", "Analyst hours", "Productive queue hours per analyst per business day. Known when the "
          "spec gives the billers: then it is set from them and not fitted.", 0.5, 10.0,
          float(DEFAULTS.process.analyst_hours_per_day), 2.0, "h/day", _analyst_hours),
    Lever("field_capacity", "Field capacity", "Meter investigations, re-reads and exchanges the field completes per "
          "business day.", 0.0, 100.0, float(DEFAULTS.process.field_orders_per_day), 6.0, "orders/day",
          _field_capacity),
)}


def patches(values: dict[str, float]) -> dict:
    """The run settings of several levers at their values, deep-merged (levers touch distinct settings)."""
    out: dict = {}
    for lever_id, value in values.items():
        out = deep_merge(out, LEVERS[lever_id].patch(value))
    return out
