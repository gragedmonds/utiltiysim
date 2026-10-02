"""Bill calculation for installation periods, vectorised (one call per tariff and batch).

Charges follow the snapshot's tariffs (``RES-E``, ``RES-G``, ``RES-W`` and the ``COM-*`` variants):
- fixed charges are prorated by days over an average month (365/12), and electric energy blocks the same way;
- volumetric prices change by ``billing.rate_change_pct`` from ``billing.rate_change_date``, and consumption is split
  linearly by days across the change;
- a negative quantity (a true-up after an over-estimate) is credited at the first price;
- net-metered exports are credited;
- commercial electric adds a demand charge on an estimated peak (load factor 0.45);
- tax applies to a positive subtotal.

Every line is rounded half-up to the cent. ``charges`` returns the components; ``lines`` turns one document's
components into display lines, so totals and lines always agree.
"""

from __future__ import annotations

import numpy as np

MONTH_DAYS = 365.0 / 12.0
LOAD_FACTOR = 0.45


def cents(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    return np.sign(x) * np.floor(np.abs(x) * 100.0 + 0.5 + 1e-9) / 100.0


def charges(tariff: dict, commodity: str, q_imp: np.ndarray, q_exp: np.ndarray, start: np.ndarray, end: np.ndarray,
            change: float, pct: float, net: np.ndarray) -> tuple[list[tuple], np.ndarray, np.ndarray]:
    """Components [(type, description, quantity, unit, rate, amount)] (arrays over the batch), subtotal and tax."""
    days = np.maximum(end - start, 0.0)
    month = days / MONTH_DAYS
    after = np.clip((end - change) / np.maximum(days, 1e-9), 0.0, 1.0)
    segs = [(1.0 - after, 1.0, ""), (after, 1.0 + pct / 100.0, " (new rates)")]
    out: list[tuple] = []
    zero = np.zeros_like(days)

    def add(kind, text, qty, unit, rate, amount):
        out.append((kind, text, np.asarray(qty, dtype=float) + zero, unit, np.asarray(rate, dtype=float) + zero,
                    cents(np.asarray(amount, dtype=float) + zero)))

    fixed = float(tariff.get("fixedMonthly", 0.0))
    add("fixed", "Fixed charge", month, "months", fixed, fixed * month)
    if commodity == "electric":
        blocks = tariff.get("energyBlocks", [])
        first = blocks[0]["price"] if blocks else 0.0
        delivery = float(tariff.get("variableDelivery", 0.0))
        pos = np.maximum(q_imp, 0.0)
        for share, factor, tag in segs:
            q, scale = pos * share, month * share
            lower = zero.copy()
            for k, block in enumerate(blocks):
                upper = np.full_like(q, np.inf) if block.get("up_to") is None else block["up_to"] * scale
                take = np.maximum(0.0, np.minimum(q, upper) - lower)
                add("energy", f"Energy tier {k + 1}{tag}", take, "kWh", block["price"] * factor,
                    take * block["price"] * factor)
                lower = np.minimum(np.maximum(lower, upper), q)
            add("delivery", f"Variable delivery{tag}", q, "kWh", delivery * factor, q * delivery * factor)
        neg = np.minimum(q_imp, 0.0)
        add("trueup", "Estimate true-up", neg, "kWh", first + delivery, neg * (first + delivery))
        if tariff.get("demandChargePerKW"):
            peak = pos / np.maximum(days * 24.0, 1e-9) / LOAD_FACTOR
            rate = float(tariff["demandChargePerKW"])
            add("demand", "Demand (estimated peak)", peak, "kW", rate * month, peak * rate * month)
        credit = float(tariff.get("netMeteringCredit", 0.0))
        exp = np.where(net, np.maximum(q_exp, 0.0), 0.0)
        add("credit", "Net-metering credit", exp, "kWh", -credit, -exp * credit)
    else:
        price = float(tariff.get("pricePerM3", 0.0))
        ratio = float(tariff.get("wastewaterRatio", 0.0)) if commodity == "water" else 0.0
        pos = np.maximum(q_imp, 0.0)
        name = "Water use" if commodity == "water" else "Gas use"
        for share, factor, tag in segs:
            add("volume", f"{name}{tag}", pos * share, "m3", price * factor, pos * share * price * factor)
            if ratio:
                add("wastewater", f"Wastewater{tag}", pos * share, "m3", price * ratio * factor,
                    pos * share * price * ratio * factor)
        neg = np.minimum(q_imp, 0.0)
        add("trueup", "Estimate true-up", neg, "m3", price * (1 + ratio), neg * price * (1 + ratio))
    subtotal = cents(sum(c[5] for c in out)) if out else zero
    tax = cents(np.maximum(subtotal, 0.0) * float(tariff.get("taxRate", 0.0)))
    return out, subtotal, tax


def lines(components: list[tuple], k: int) -> list[dict]:
    """Display lines of document ``k`` in a batch (zero lines omitted)."""
    return [{"type": kind, "description": text, "quantity": round(float(q[k]), 3), "unit": unit,
             "rate": round(float(r[k]), 5), "amount": float(a[k])}
            for kind, text, q, unit, r, a in components if a[k] != 0 or (kind == "fixed")]
