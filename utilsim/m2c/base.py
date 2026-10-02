"""The meter-to-cash view of a town, built from its snapshot (numpy only; also runs in the hosted engine).

One row per register: who it belongs to (premise, meter, service point, installation), how it is read (technology,
route, portion, read hour) and where its dial started. Monthly true consumption comes from ``sim.usage`` on the
snapshot's premise attributes, so registers match the generator's sample reads exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import numpy as np

from utilsim.config.model import SimConfig
from utilsim.core.ids import str_key
from utilsim.core.rng import Purpose, hash_u01
from utilsim.customers.calendar import scheduled_read_date
from utilsim.m2c import registers as regs
from utilsim.sim.usage import KEYS, UsageInputs, monthly_energy
from utilsim.sim.weather import daily_temps

YEAR = 2026
READ_HOUR = {"AMI": (2.0, 0.0), "AMR": (9.5, 5.0), "MANUAL": (9.0, 6.0)}  # base hour, spread × u


def _day(iso: str | None) -> int | None:
    if not iso:
        return None
    return regs.day_of(datetime.fromisoformat(iso.replace("Z", "+00:00")).date())


@dataclass
class M2CTown:
    id: str
    cfg: SimConfig
    timezone: str
    premise_ids: list[str]
    premise_index: dict[str, int]
    address: list[str]
    occupied: np.ndarray
    move_in: np.ndarray  # day index (or very negative)
    move_out: np.ndarray  # day index (or very large)
    normal: dict[str, np.ndarray]  # key -> (13, n) cumulative normal consumption from Jan 1
    december: dict[str, np.ndarray]  # key -> (n,) December consumption (used before 2026)
    # Registers (R rows).
    reg_ids: list[str]
    reg_index: dict[str, int]
    meter_ids: list[str]
    meter_of: np.ndarray  # register -> meter row
    prem: np.ndarray  # register -> premise row
    service_point: list[str]
    installation: list[str]
    commodity: np.ndarray
    direction: np.ndarray
    unit: np.ndarray
    key: np.ndarray  # index into KEYS
    digits: np.ndarray
    multiplier: np.ndarray
    tech: np.ndarray
    mru: list[str]
    portion: np.ndarray
    base: np.ndarray
    hour: np.ndarray
    read_day: np.ndarray  # (R, 13): scheduled read day for Dec 2025 (col 0) and each month of 2026
    contracts: dict[tuple[int, str], list[tuple[int, int, str, str]]]  # (premise, commodity) -> tenancies
    # Meters (M rows).
    meter_prem: np.ndarray
    meter_commodity: np.ndarray
    meter_tech: np.ndarray
    meter_keys: np.ndarray
    # Installations (one per premise and utility) and accounts, for billing.
    inst_ids: list[str]
    inst_of: np.ndarray  # register -> installation row
    inst_rows: list[np.ndarray]
    inst_rate: list[str]  # rate category in billing master data (e.g. RES-E)
    tariffs: dict[str, dict]
    account_method: dict[str, str]
    account_profile: dict[str, str]
    temps: np.ndarray  # daily mean temperature, index 0 = 2025-12-01 (sim.weather)

    @property
    def n_registers(self) -> int:
        return len(self.reg_ids)

    def true_advance(self, rows: np.ndarray, day: np.ndarray, hour: np.ndarray) -> np.ndarray:
        """Normal (anomaly-free) consumption since 2026-01-01 for register rows at (day, hour)."""
        out = np.empty(len(rows))
        for k, name in enumerate(KEYS):
            m = self.key[rows] == k
            if m.any():
                out[m] = regs.advance(self.normal[name], self.december[name], self.prem[rows[m]], day[m], hour[m])
        return out

    def contract_at(self, r: int, day: int) -> tuple[str, str]:
        """(contract id, account id) active for register row ``r`` on ``day`` (the current one if none)."""
        ten = self.contracts.get((int(self.prem[r]), str(self.commodity[r])), [])
        if len(ten) == 1:
            return ten[0][2], ten[0][3]
        for start, end, ctr, acct in ten:
            if start <= day < end:
                return ctr, acct
        return (ten[0][2], ten[0][3]) if ten else ("", "")

    @classmethod
    def from_snapshot(cls, snap: dict) -> M2CTown:
        cfg = SimConfig.model_validate(snap["config"])
        premises = snap["premises"]
        pidx = {p["id"]: i for i, p in enumerate(premises)}
        far = 10 ** 6
        usage = monthly_energy(UsageInputs.from_snapshot(snap), cfg)
        normal = {k: regs.cumulative(v) for k, v in usage.items()}
        december = {k: v[11] for k, v in usage.items()}
        u15 = hash_u01(cfg.seeds.for_("households"), Purpose.CUSTOMER,
                       np.array([str_key(p["uid"]) for p in premises], dtype=np.int64), 15)
        sps = {s["id"]: s for s in snap["servicePoints"]}
        reg_rows = {r["id"]: r for r in snap["registers"]}
        meters = snap["meters"]
        rows: list[tuple] = []
        m_prem, m_comm, m_tech, m_keys = [], [], [], []
        for mi, m in enumerate(meters):
            sp = sps[m["servicePointId"]]
            i = pidx[sp["premiseId"]]
            c = sp["commodity"]
            m_prem.append(i)
            m_comm.append(c)
            m_tech.append(m["technology"])
            m_keys.append(str_key(m["id"]))
            for rid in m["registerIds"]:
                reg = reg_rows[rid]
                d = reg["direction"]
                key = KEYS.index("electric_" + d if c == "electric" else c)
                base_h, spread = READ_HOUR[m["technology"]]
                rows.append((rid, mi, i, sp["id"], sp["installationId"], c, d, reg["unit"], key, int(reg["digits"]),
                             int(m.get("multiplier") or 1), m["technology"], premises[i].get("mruId") or "",
                             int(premises[i].get("billingCycle") or 1),
                             regs.register_base(rid, cfg.seeds.master), base_h + spread * float(u15[i])))
        cols = list(zip(*rows, strict=True)) if rows else [[]] * 16
        portion = np.array(cols[13], dtype=np.int64)
        table = {p: [regs.day_of(scheduled_read_date(YEAR - 1, 12, p))] +
                 [regs.day_of(scheduled_read_date(YEAR, mo, p)) for mo in range(1, 13)] for p in set(portion.tolist())}
        read_day = np.array([table[p] for p in portion], dtype=np.int64).reshape(len(portion), 13)
        inst_prem = {x["id"]: (pidx[x["premiseId"]], x["division"]) for x in snap["installations"]}
        rate_of = {x["id"]: x.get("rateCategory") or "" for x in snap["installations"]}
        inst_ids = list(dict.fromkeys(cols[4])) if rows else []
        inst_index = {x: k for k, x in enumerate(inst_ids)}
        inst_of = np.array([inst_index[x] for x in cols[4]], dtype=np.int64)
        tariffs = {}
        for t in snap.get("tariffs", []):
            base = next((b for b in snap["tariffs"] if b["id"] == t.get("basedOn")), {})
            tariffs[t["id"]] = {**base, **{k: v for k, v in t.items() if k != "basedOn"}}
        profile = {b["id"]: b.get("paymentProfile") or "on_time" for b in snap.get("businessPartners", [])}
        contracts: dict[tuple[int, str], list[tuple[int, int, str, str]]] = {}
        for ctr in snap["contracts"]:
            k = inst_prem.get(ctr["installationId"])
            if k is None:
                continue
            start = _day(ctr.get("validFrom"))
            end = _day(ctr.get("validTo"))
            contracts.setdefault(k, []).append((-far if start is None else start, far if end is None else end,
                                                ctr["id"], ctr["accountId"]))
        return cls(
            id=snap["id"], cfg=cfg, timezone=cfg.town.timezone, premise_ids=[p["id"] for p in premises],
            premise_index=pidx, address=[p.get("address") or p["id"] for p in premises],
            occupied=np.array([bool(p.get("occupied")) for p in premises]),
            move_in=np.array([_day(p.get("moveInAt")) if p.get("moveInAt") else -far for p in premises]),
            move_out=np.array([_day(p.get("moveOutAt")) if p.get("moveOutAt") else far for p in premises]),
            normal=normal, december=december,
            reg_ids=list(cols[0]), reg_index={r: k for k, r in enumerate(cols[0])}, meter_ids=[m["id"] for m in meters],
            meter_of=np.array(cols[1], dtype=np.int64), prem=np.array(cols[2], dtype=np.int64),
            service_point=list(cols[3]), installation=list(cols[4]), commodity=np.array(cols[5]),
            direction=np.array(cols[6]), unit=np.array(cols[7]), key=np.array(cols[8], dtype=np.int64),
            digits=np.array(cols[9], dtype=np.int64), multiplier=np.array(cols[10], dtype=np.int64),
            tech=np.array(cols[11]), mru=list(cols[12]), portion=portion, base=np.array(cols[14], dtype=float),
            hour=np.array(cols[15], dtype=float), read_day=read_day, contracts=contracts,
            meter_prem=np.array(m_prem, dtype=np.int64), meter_commodity=np.array(m_comm),
            meter_tech=np.array(m_tech), meter_keys=np.array(m_keys, dtype=np.int64),
            inst_ids=inst_ids, inst_of=inst_of, inst_rows=[np.flatnonzero(inst_of == k) for k in range(len(inst_ids))],
            inst_rate=[rate_of.get(x, "") for x in inst_ids], tariffs=tariffs,
            account_method={a["id"]: a.get("paymentMethod") or "online" for a in snap.get("accounts", [])},
            account_profile={a["id"]: profile.get(a.get("businessPartnerId"), "on_time") for a in snap.get("accounts", [])},
            temps=daily_temps(cfg))


def date_of(day: int) -> date:
    return date.fromordinal(regs.EPOCH.toordinal() + int(day))


_CACHE: dict[str, M2CTown] = {}


def cached_m2c_town(town_id: str) -> M2CTown | None:
    return _CACHE.get(town_id)


def m2c_town(snap: dict) -> M2CTown:
    """Cached per town id (a warm function instance reuses it across requests)."""
    hit = _CACHE.get(snap["id"])
    if hit is None:
        if len(_CACHE) >= 4:
            _CACHE.pop(next(iter(_CACHE)))
        hit = _CACHE[snap["id"]] = M2CTown.from_snapshot(snap)
    return hit
