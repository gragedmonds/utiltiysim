"""The networks above a utility's districts (``utility-network/1.0``) and their events of a year.

Each district generates its own distribution networks with one supply point per utility (its substation, its water
supply, its gas regulator). Above them the utility runs shared assets, each feeding a run of neighbouring districts:

* **electric:** transmission circuits, each feeding ``per_circuit`` districts' substations;
* **water:** one treatment plant feeding every district, through transmission mains each feeding ``per_main``
  districts (a main break dries those districts; the plant all of them);
* **gas:** gate stations, each feeding ``per_gate`` districts.

``events(layout, seed, cal)`` draws the year's events per asset (a counter-based draw per asset and day, rates per
asset-year, a duration and a start hour) and hands each district the ones that reach it, as its ``upstream`` input;
``storm_seed`` gives the districts one weather. The same layout, seed and year give the same events.
"""

from __future__ import annotations

import math

import numpy as np

from utilsim.core.ids import str_key
from utilsim.core.rng import Purpose, hash_u01

LAYOUT_VERSION = "utility-network/1.0"
# Per asset-year rate, duration range (hours), label.
ASSETS = {
    "circuit": ("electric", 0.8, (0.5, 4.0), "Transmission circuit {name} tripped"),
    "plant": ("water", 0.15, (6.0, 30.0), "Treatment plant {name} offline"),
    "main": ("water", 0.4, (8.0, 36.0), "Transmission main {name} broke"),
    "gate": ("gas", 0.08, (2.0, 10.0), "Gate station {name} shut in"),
}
_KIND = {k: i for i, k in enumerate(ASSETS)}


def layout(districts: list[str], *, per_circuit: int = 4, per_main: int = 4, per_gate: int = 6) -> dict:
    """The shared assets over ``districts`` (in order: neighbours share assets) and the districts each one feeds."""
    if not districts:
        raise ValueError("a utility needs at least one district")
    if min(per_circuit, per_main, per_gate) < 1:
        raise ValueError("each shared asset feeds at least one district")

    def runs(prefix: str, kind: str, size: int) -> list[dict]:
        return [{"id": f"{prefix}{k + 1}", "kind": kind, "districts": districts[i:i + size]}
                for k, i in enumerate(range(0, len(districts), size))]

    assets = [*runs("T", "circuit", per_circuit), {"id": "P1", "kind": "plant", "districts": list(districts)},
              *runs("M", "main", per_main), *runs("G", "gate", per_gate)]
    for a in assets:
        a["utility"] = ASSETS[a["kind"]][0]
    return {"schemaVersion": LAYOUT_VERSION, "districts": list(districts), "assets": assets}


def events(lay: dict, seed: str, cal, *, rate_factor: float = 1.0) -> dict[str, list[dict]]:
    """Each district's upstream events of ``cal``'s year (``upstream/1.0`` events, time order)."""
    out: dict[str, list[dict]] = {d: [] for d in lay["districts"]}
    days = np.arange(cal.days)
    for a in lay["assets"]:
        util, rate, (h0, h1), label = ASSETS[a["kind"]]
        key = str_key(a["id"])
        p = 1.0 - math.exp(-max(0.0, rate * rate_factor) / cal.days)
        hit = hash_u01(seed, Purpose.UTILITY, cal.year, _KIND[a["kind"]], key, days) < p
        for d in days[hit].tolist():
            u_start = float(hash_u01(seed, Purpose.UTILITY, cal.year, _KIND[a["kind"]], key, d, 1))
            u_len = float(hash_u01(seed, Purpose.UTILITY, cal.year, _KIND[a["kind"]], key, d, 2))
            start = int(u_start * 86399.0)
            hours = h0 * (h1 / h0) ** u_len  # log-uniform: most are short
            ev = {"id": f"UP-{a['id']}-{cal.date_of(d).strftime('%Y%m%d')}", "utility": util,
                  "day": cal.date_of(d).isoformat(), "start": start, "end": start + round(hours * 3600.0),
                  "label": label.format(name=a["id"])}
            for district in a["districts"]:
                out[district].append(dict(ev))
    for evs in out.values():
        evs.sort(key=lambda e: (e["day"], e["start"], e["id"]))
    return out


def upstream_inputs(lay: dict, seed: str, cal, *, storm_seed: str | None = None,
                    rate_factor: float = 1.0) -> dict[str, dict]:
    """Each district's ``upstream`` input: its events and the utility's storm seed."""
    evs = events(lay, seed, cal, rate_factor=rate_factor)
    return {d: {"stormSeed": storm_seed or f"{seed}:storms", "events": evs[d]} for d in lay["districts"]}
