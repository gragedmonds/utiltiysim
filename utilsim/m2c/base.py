"""The meter-to-cash view of a town, built from its snapshot (numpy only; also runs in the hosted engine).

One row per register: who it belongs to (premise, meter, service point, installation), how it is read (technology,
route, portion, read hour) and where its dial started. Monthly true consumption comes from ``sim.usage`` on the
snapshot's premise attributes, so registers match the generator's sample reads exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np

from utilsim.config.model import SimConfig
from utilsim.core.ids import str_key
from utilsim.core.rng import Purpose, hash_u01
from utilsim.customers.calendar import scheduled_read_date
from utilsim.m2c import registers as regs
from utilsim.m2c.calendar import FIRST_YEAR, RunCalendar, calendar
from utilsim.sim.usage import KEYS, UsageInputs, monthly_energy
from utilsim.sim.weather import START as WEATHER_START
from utilsim.sim.weather import daily_temps

YEAR = FIRST_YEAR  # the snapshot's year: a town built without a year is in it
READ_HOUR = {"AMI": (2.0, 0.0), "AMR": (9.5, 5.0), "MANUAL": (9.0, 6.0)}  # base hour, spread × u


def _day(iso: str | None, cal: RunCalendar) -> int | None:
    if not iso:
        return None
    return cal.day_of(datetime.fromisoformat(iso.replace("Z", "+00:00")).date())


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
    december: dict[str, np.ndarray]  # key -> (n,) December consumption (used before the year)
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
    read_day: np.ndarray  # (R, 13): scheduled read day for the December before (col 0) and each month
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
    temps: np.ndarray  # daily mean temperature, index 0 = 1 December of the year before (sim.weather)
    # Master data for the lookup screens (installation, contract, account, business partner).
    name: str = ""  # town name (e.g. "Small Town"), for the planning plant of field service orders
    inst_index: dict[str, int] = field(default_factory=dict)
    inst_meta: list[dict] = field(default_factory=list)  # per installation row: premise, division, MRU, status...
    inst_contracts: list[list[dict]] = field(default_factory=list)  # per installation row: its contracts
    accounts: dict[str, dict] = field(default_factory=dict)
    partners: dict[str, dict] = field(default_factory=dict)
    account_insts: dict[str, list[int]] = field(default_factory=dict)  # account -> installation rows
    # AMI network: the collector each AMI meter reports through (None for AMR and walked meters), and the collectors.
    meter_collector: list[str | None] = field(default_factory=list)
    collectors: dict[str, dict] = field(default_factory=dict)  # id -> {mountedOn, mountId, x, z}
    # Field work (utilsim/m2c/fieldwork.py): when each meter was installed (decimal year), its AMI battery's install
    # year (0: none) and model; each premise's position, street and the attributes that drive its work.
    meter_installed: np.ndarray = field(default_factory=lambda: np.zeros(0))
    meter_battery: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    meter_model: list[str] = field(default_factory=list)
    premise_xz: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    premise_street: list[str] = field(default_factory=list)
    premise_attrs: dict[str, np.ndarray] = field(default_factory=dict)  # yearBuilt, hasEV, electricHeat, residential
    cal: RunCalendar = field(default_factory=calendar)  # the calendar year the town's days count in
    # A chained year (utilsim/m2c/yearclose.py): the device on each meter slot at the year's start and the device
    # changes made on it so far (empty: the snapshot's own meters, none changed).
    meter_device: list[str] = field(default_factory=list)
    device_count: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))

    def collector_of(self, r: int) -> str | None:
        """The AMI collector register row ``r``'s meter reports through, if any."""
        return self.meter_collector[int(self.meter_of[r])] if self.meter_collector else None

    @property
    def n_registers(self) -> int:
        return len(self.reg_ids)

    def true_advance(self, rows: np.ndarray, day: np.ndarray, hour: np.ndarray) -> np.ndarray:
        """Normal (anomaly-free) consumption since 1 January of the town's year for register rows at (day, hour)."""
        out = np.empty(len(rows))
        for k, name in enumerate(KEYS):
            m = self.key[rows] == k
            if m.any():
                out[m] = regs.advance(self.normal[name], self.december[name], self.prem[rows[m]], day[m], hour[m],
                                      self.cal.month_start)
        return out

    def read_id(self, r: int, m: int) -> str:
        return f"READ-{self.id}-{self.reg_ids[r]}-{self.cal.date_of(int(self.read_day[r, m])).isoformat()}"

    def find_read(self, read_id: str) -> tuple[int, int]:
        """(register row, month) of a read id of the year ``READ-{townId}-{registerId}-{YYYY-MM-DD}``; KeyError if
        unknown."""
        prefix = f"READ-{self.id}-"
        r = self.reg_index.get(read_id[len(prefix):-11]) if read_id.startswith(prefix) and len(read_id) > \
            len(prefix) + 11 else None
        if r is not None:
            for m in range(1, 13):
                if self.read_id(r, m) == read_id:
                    return r, m
        raise KeyError(read_id)

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
    def from_snapshot(cls, snap: dict, year: int = YEAR) -> M2CTown:
        """The town in calendar ``year``: its read schedule, usage and weather for that year (2026: the snapshot's
        own year)."""
        cal = calendar(year)
        cfg = SimConfig.model_validate(snap["config"])
        premises = snap["premises"]
        pidx = {p["id"]: i for i, p in enumerate(premises)}
        far = 10 ** 6
        usage = monthly_energy(UsageInputs.from_snapshot(snap), cfg, cal.year)
        normal = {k: regs.cumulative(v) for k, v in usage.items()}
        december = {k: v[11] for k, v in usage.items()}
        u15 = hash_u01(cfg.seeds.for_("households"), Purpose.CUSTOMER,
                       np.array([str_key(p["uid"]) for p in premises], dtype=np.int64), 15)
        sps = {s["id"]: s for s in snap["servicePoints"]}
        reg_rows = {r["id"]: r for r in snap["registers"]}
        meters = snap["meters"]
        rows: list[tuple] = []
        m_prem, m_comm, m_tech, m_keys, m_inst = [], [], [], [], []
        for mi, m in enumerate(meters):
            m_inst.append(_year(m.get("installedAt")))
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
        table = {p: [cal.day_of(scheduled_read_date(cal.year - 1, 12, p))] +
                 [cal.day_of(scheduled_read_date(cal.year, mo, p)) for mo in range(1, 13)]
                 for p in set(portion.tolist())}
        read_day = np.array([table[p] for p in portion], dtype=np.int64).reshape(len(portion), 13)
        inst_prem = {x["id"]: (pidx[x["premiseId"]], x["division"]) for x in snap["installations"]}
        rate_of = {x["id"]: x.get("rateCategory") or "" for x in snap["installations"]}
        inst_raw = {x["id"]: x for x in snap["installations"]}
        inst_ids = list(dict.fromkeys(cols[4])) if rows else []
        inst_index = {x: k for k, x in enumerate(inst_ids)}
        inst_of = np.array([inst_index[x] for x in cols[4]], dtype=np.int64)
        tariffs = {}
        for t in snap.get("tariffs", []):
            base = next((b for b in snap["tariffs"] if b["id"] == t.get("basedOn")), {})
            tariffs[t["id"]] = {**base, **{k: v for k, v in t.items() if k != "basedOn"}}
        profile = {b["id"]: b.get("paymentProfile") or "on_time" for b in snap.get("businessPartners", [])}
        contracts: dict[tuple[int, str], list[tuple[int, int, str, str]]] = {}
        inst_contracts: list[list[dict]] = [[] for _ in inst_ids]
        account_insts: dict[str, list[int]] = {}
        for ctr in snap["contracts"]:
            k_inst = inst_index.get(ctr["installationId"])
            if k_inst is not None:
                inst_contracts[k_inst].append({x: ctr.get(x) for x in ("id", "accountId", "validFrom", "validTo",
                                                                       "status")})
                account_insts.setdefault(ctr["accountId"], []).append(k_inst)
            k = inst_prem.get(ctr["installationId"])
            if k is None:
                continue
            start = _day(ctr.get("validFrom"), cal)
            end = _day(ctr.get("validTo"), cal)
            contracts.setdefault(k, []).append((-far if start is None else start, far if end is None else end,
                                                ctr["id"], ctr["accountId"]))
        return cls(
            id=snap["id"], cfg=cfg, timezone=cfg.town.timezone, premise_ids=[p["id"] for p in premises],
            premise_index=pidx, address=[p.get("address") or p["id"] for p in premises],
            occupied=np.array([bool(p.get("occupied")) for p in premises]),
            move_in=np.array([_day(p.get("moveInAt"), cal) if p.get("moveInAt") else -far for p in premises]),
            move_out=np.array([_day(p.get("moveOutAt"), cal) if p.get("moveOutAt") else far for p in premises]),
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
            temps=daily_temps(cfg, through=cal.year)[(date(cal.year - 1, 12, 1) - WEATHER_START).days:],
            name=town_name(snap), inst_index=inst_index, cal=cal,
            inst_meta=[{x: meta.get(x) for x in INST_FIELDS} for meta in (inst_raw.get(i, {}) for i in inst_ids)],
            inst_contracts=inst_contracts,
            accounts={a["id"]: {x: a.get(x) for x in ACCOUNT_FIELDS} for a in snap.get("accounts", [])},
            partners={b["id"]: {x: b.get(x) for x in PARTNER_FIELDS} for b in snap.get("businessPartners", [])},
            account_insts={a: sorted(set(v)) for a, v in account_insts.items()},
            meter_collector=[((m.get("ami") or {}).get("collectorId") if m["technology"] == "AMI" else None)
                             for m in meters],
            collectors={c["id"]: {x: c.get(x) for x in ("mountedOn", "mountId", "x", "z")}
                        for c in (snap.get("amiNetwork") or {}).get("collectors") or []},
            meter_installed=np.array(m_inst, dtype=float),
            meter_battery=np.array([int(m.get("batteryInstallYear") or 0) for m in meters], dtype=np.int64),
            meter_model=[str(m.get("model") or m["technology"]) for m in meters],
            premise_xz=np.array([(float(p.get("x") or 0.0), float(p.get("z") or 0.0)) for p in premises],
                                dtype=float).reshape(len(premises), 2),
            premise_street=[str(p.get("street") or "") for p in premises],
            premise_attrs={"yearBuilt": np.array([int(p.get("yearBuilt") or 0) for p in premises], dtype=np.int64),
                           "hasEV": np.array([bool(p.get("hasEV")) for p in premises]),
                           "electricHeat": np.array([bool(p.get("electricHeat")) for p in premises]),
                           "residential": np.array([p.get("premiseType", "residential") == "residential"
                                                    for p in premises])})


INST_FIELDS = ("premiseId", "servicePointId", "division", "mruId", "readCycle", "rateCategory", "billingClass",
               "status")
ACCOUNT_FIELDS = ("businessPartnerId", "premiseId", "sapContractAccount", "paymentMethod", "budgetBilling", "currency",
                  "validFrom", "validTo")
PARTNER_FIELDS = ("name", "kind", "sapPartner", "since")


def town_name(snap: dict) -> str:
    """The town's preset name for people ("Small Town" for ``small_town``), else "Utility"."""
    name = str((snap.get("config") or {}).get("name") or "")
    return name.replace("_", " ").title() if name and name != "custom" else "Utility"


def _year(iso: str | None) -> float:
    """A timestamp as a decimal year (2015-07-02 -> 2015.5); 0 when missing."""
    if not iso:
        return 0.0
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).date()
    return d.year + (d.timetuple().tm_yday - 1) / 365.0



_CACHE: dict[str, M2CTown] = {}


def cached_m2c_town(town_id: str) -> M2CTown | None:
    return _CACHE.get(town_id)


def m2c_town(snap: dict, year: int = YEAR) -> M2CTown:
    """Cached per town id and year (a warm function instance reuses it across requests)."""
    key = snap["id"] if year == YEAR else f"{snap['id']}@{year}"
    hit = _CACHE.get(key)
    if hit is None:
        if len(_CACHE) >= 4:
            _CACHE.pop(next(iter(_CACHE)))
        hit = _CACHE[key] = M2CTown.from_snapshot(snap, year)
    return hit
