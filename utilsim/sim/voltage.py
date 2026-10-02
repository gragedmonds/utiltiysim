"""Radial power flow for the electric network: voltage, loading and losses (numpy only).

Linearised DistFlow on the frame's energized forest. Each edge's voltage drop, in per unit, is
``factor · (P·R + Q·X) / (1000 · V²)``:
- P and Q are the real and reactive power flowing through the edge (kW, kvar) to everything beyond it. P is net of
  rooftop solar, so reverse flow raises the voltage downstream.
- R and X come from the conductor tables (``net.tables``) and the edge length, divided by its parallel circuits.
- V is the line-to-line kV for three-phase edges; single-phase edges use the line-to-neutral kV and ``factor`` 2
  (out and back). Services are 120/240 V split-phase, so V = 0.24 kV with ``factor`` 2.
- A distribution transformer drops ``(P·R% + Q·X%) / (100 · kVA rating)``.

The substation's tap changer holds its bus at ``SOURCE_PU``. Loads run at power factor ``PF``. A premise's service
voltage is reported on a 120 V base; ANSI C84.1 Range A is 114–126 V. Loading is apparent power over the edge's
thermal capacity (conductor ampacity × circuits, or the transformer rating).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

from utilsim.net.tables import OH_CONDUCTORS, SECONDARY, UG_CONDUCTORS, conductor_kva

PF = 0.95
TAN_PHI = math.tan(math.acos(PF))
SOURCE_PU = 1.03  # substation tap changer set point (line-drop compensation for the feeders)
TX_R_PCT, TX_X_PCT = 1.1, 1.6  # distribution transformer impedance on its own rating
TX_NO_LOAD_PCT = 0.2  # core loss as % of rating
BASE_V = 120.0
RANGE_A = (0.95, 1.05)
_TABLE = sorted(OH_CONDUCTORS + UG_CONDUCTORS + SECONDARY, key=lambda c: -len(c.label))
_CIRCUITS = re.compile(r"^(\d+)\s*×\s*")


def conductor_of(label: str | None):
    """(conductor, circuits) for an exported label such as ``2 × 4/0 AL 15 kV XLPE (shared feeder duct bank)``."""
    if not label:
        return None, 1
    m = _CIRCUITS.match(label)
    n = int(m.group(1)) if m else 1
    text = label[m.end():] if m else label
    for c in _TABLE:
        if text.startswith(c.label):
            return c, n
    return None, n


@dataclass
class ElecParams:
    r: np.ndarray  # ohm per edge (series)
    x: np.ndarray
    denom: np.ndarray  # 1000 · V² / factor; inf where an edge has no drop model
    tx_kva: np.ndarray  # transformer rating (nan elsewhere)
    cap_kva: np.ndarray  # thermal capacity (nan if unknown)
    loss_k: np.ndarray  # losses (kW) = loss_k · S²
    bus: np.ndarray  # regulated substation bus nodes

    @classmethod
    def from_edges(cls, edges: list[dict], node_kinds: list[str]) -> ElecParams:
        n = len(edges)
        r, x = np.zeros(n), np.zeros(n)
        denom, tx, cap, loss_k = np.full(n, np.inf), np.full(n, np.nan), np.full(n, np.nan), np.zeros(n)
        for k, e in enumerate(edges):
            kind = e.get("kind")
            if kind == "supply":
                continue  # transmission: the tap changer regulates the bus below it
            if kind == "transformer":
                rating = float(e.get("ratingKVA") or 0) or np.nan
                tx[k] = cap[k] = rating
                loss_k[k] = TX_R_PCT / 100.0 / rating if rating == rating else 0.0
                continue
            c, circuits = conductor_of(e.get("conductor"))
            if c is None:
                continue
            km = float(e.get("lengthM") or 0.0) / 1000.0
            r[k], x[k] = c.r_ohm_km * km / circuits, c.x_ohm_km * km / circuits
            kv = float(e.get("voltageKV") or 0.24)
            phases = int(e.get("phases") or (1 if kind == "service" else 3))
            if kind == "service":
                v, factor = kv, 2.0
            elif phases == 3:
                v, factor = kv, 1.0
            else:
                v, factor = kv / math.sqrt(3), 2.0
            denom[k] = 1000.0 * v * v / factor
            loss_k[k] = r[k] / denom[k]
            if kind == "service":
                cap[k] = kv * c.ampacity_a * circuits  # 240 V split-phase
            else:
                cap[k] = float(e.get("capacityKVA") or conductor_kva(c, kv, phases) * circuits)
        bus = np.array([i for i, kind in enumerate(node_kinds) if kind == "substation"], dtype=np.int64)
        return cls(r, x, denom, tx, cap, loss_k, bus)


@dataclass
class VoltageResult:
    node_pu: np.ndarray  # per node (nan where unreached)
    loading: np.ndarray  # per edge, apparent power / capacity (nan unknown or dead)
    losses_kw: float
    premise_v: np.ndarray  # service voltage per premise on a 120 V base (nan if unsupplied)


def solve(params: ElecParams, forest, p_down: np.ndarray, load_down: np.ndarray, meter: np.ndarray,
          n_premises: int) -> VoltageResult:
    """``p_down`` and ``load_down`` are net and gross kW beyond each node (the flow model's aggregation);
    ``meter`` maps nodes to premises."""
    has = forest.pedge >= 0
    kids = np.flatnonzero(has)
    e = forest.pedge[kids]
    p = p_down[kids]
    q = load_down[kids] * TAN_PHI
    tx = ~np.isnan(params.tx_kva[e])
    drop = np.where(tx, (p * TX_R_PCT + q * TX_X_PCT) / (100.0 * np.where(tx, params.tx_kva[e], 1.0)),
                    (p * params.r[e] + q * params.x[e]) / params.denom[e])
    dv = np.zeros(len(forest.parent))
    dv[kids] = drop
    v = np.full(len(forest.parent), np.nan)
    for lvl in forest.levels:
        root = forest.parent[lvl] < 0
        v[lvl[root]] = SOURCE_PU
        child = lvl[~root]
        if len(child):
            v[child] = np.where(np.isin(child, params.bus), SOURCE_PU, v[forest.parent[child]] - dv[child])
    s = np.hypot(p, q)
    loading = np.full(len(params.r), np.nan)
    loading[e] = s / params.cap_kva[e]
    losses = float(np.sum(params.loss_k[e] * s * s) + np.nansum(params.tx_kva[e]) * TX_NO_LOAD_PCT / 100.0)
    prem = np.full(n_premises, np.nan)
    m = (meter >= 0) & forest.reached
    prem[meter[m]] = v[m] * BASE_V
    return VoltageResult(v, loading, losses, prem)
