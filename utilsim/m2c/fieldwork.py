"""Field work across the year: the orders the field crews work, where they come from, and how the crews keep up.

Every order follows something that happens in the replayed year (``utilsim/m2c/run.py``) or the town itself:

=========================  ===========================================================================================
order (program)            raised by
=========================  ===========================================================================================
gas_odour (emergency)      a gas leak's first odour report, and every background odour report (contact centre)
no_supply (emergency)      single-premise outage reports (the contact centre's background outage contacts)
outage_repair (emergency)  the year's outages and leaks (``incidents.py``), timed by the incident model
disconnect, reconnect      the year's disconnections and reconnections (collections); AMI electric meters with a
(service)                  remote switch are switched remotely, without a truck
move_out, move_in          account closings and openings at premises with a meter that cannot be read remotely
(service)                  (a move-in the day after a move-out at the same premise is the same visit)
meter_investigation,       the run's VEE field visits (truck rolls) and the meters they exchange; the run decides
corrective_exchange        when, so they take the meter technicians' time on their day
seal_exchange (meter)      meters whose seal period ends this year, by lot (commodity, model, install year): the
                           sample of every lot is pulled and tested; a lot that fails (decided when its last sample
                           is tested) has every other meter exchanged by 31 December
ami_battery (meter)        gas and water radio modules (AMI and AMR) whose battery reaches its life this year
water_meter_replacement    water meters at or past their service life
removal (meter)            meters removed at vacant premises (service abandoned)
ami_conversion (meter)     AMR and manually read meters converted to AMI, route by route
pole_inspection ...        preventative maintenance on the town's assets: poles, overhead spans, valves, hydrants,
(maintenance)              gas main and regulator stations; inspections find defects that raise repairs
new_set, meter_set         new-connection requests (contact centre) that go ahead: the service is built in the
(construction)             construction season, then a meter technician sets the meter
service_upgrade            homes with an EV or electric heat upgrading their electric service
main_replacement           100 m segments of cast-iron water and gas main renewed in the construction season
=========================  ===========================================================================================

The crews: on-call responders work emergencies around the clock (first come, first served, several crews at once).
Meter technicians, the three utilities' crews and the construction crews work business days from
``shift_start_hour`` for ``shift_hours``: an order is released on its day, and each crew type works its released
orders by priority, then due date. Work the run or an incident has already timed (VEE visits, outage repairs) takes
the crews' time on its day first. A long job carries over to the next day. Customer work (priority 1 and 2) due today
or overdue may run into overtime, up to ``overtime_max_hours`` per crew.

Field settings never change the rest of the year: reads, cases, bills, collections and contacts are the same with
any field settings (a test checks). Field work does not feed back into the year yet: a late disconnect does not move
the collections timeline, and a removal does not end the premise's billing.

Every draw is a counter-based hash of the run seed and the order's identity, so episodes on ``field`` settings apply
from their day.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np

from utilsim.core.ids import str_key
from utilsim.core.rng import Purpose, normalize_seed
from utilsim.m2c.base import date_of
from utilsim.m2c.run import YEAR_DAYS, M2CRun, add_bdays

FIELD_VERSION = "m2c-fieldwork/1.0"
P = Purpose.FIELD
YEAR = 2026
INF = float("inf")
PROGRAMS = {"emergency": "Customer emergencies", "service": "Service orders", "meter": "Meter maintenance",
            "maintenance": "Preventative maintenance", "construction": "Capital construction"}
CREWS = {"emergency": "On-call responders", "meter": "Meter technicians", "electric": "Electric line crews",
         "water": "Water crews", "gas": "Gas crews", "construction": "Construction crews"}
CREW_CODE = {"emergency": "ER", "meter": "MT", "electric": "EL", "water": "WA", "gas": "GA", "construction": "CN"}
DAY_CREWS = ("meter", "electric", "water", "gas", "construction")  # business-day crews (the queue simulation)
# (key, label, program, crew (None: the asset's utility), priority)
TYPES = (("gas_odour", "Gas odour", "emergency", "emergency", 1),
         ("no_supply", "No supply", "emergency", "emergency", 1),
         ("outage_repair", "Outage and leak repair", "emergency", None, 1),
         ("disconnect", "Disconnect", "service", "meter", 2),
         ("reconnect", "Reconnect", "service", "meter", 2),
         ("move_out", "Move-out read", "service", "meter", 2),
         ("move_in", "Move-in read", "service", "meter", 2),
         ("meter_investigation", "Meter investigation", "service", "meter", 2),
         ("corrective_exchange", "Corrective exchange", "service", "meter", 2),
         ("seal_exchange", "Seal exchange", "meter", "meter", 3),
         ("ami_battery", "Module battery", "meter", "meter", 3),
         ("water_meter_replacement", "Water meter replacement", "meter", "meter", 3),
         ("removal", "Meter removal", "meter", "meter", 3),
         ("ami_conversion", "AMI conversion", "meter", "meter", 4),
         ("pole_inspection", "Pole inspection", "maintenance", "electric", 3),
         ("pole_replacement", "Pole replacement", "maintenance", "electric", 3),
         ("tree_trimming", "Tree trimming", "maintenance", "electric", 3),
         ("valve_exercise", "Valve exercise", "maintenance", None, 3),
         ("valve_repair", "Valve repair", "maintenance", None, 3),
         ("hydrant_flush", "Hydrant flushing", "maintenance", "water", 3),
         ("hydrant_repair", "Hydrant repair", "maintenance", "water", 3),
         ("leak_survey", "Leak survey", "maintenance", "gas", 3),
         ("gas_leak_repair", "Gas leak repair", "maintenance", "gas", 3),
         ("regulator_inspection", "Regulator inspection", "maintenance", "gas", 3),
         ("new_set", "New service", "construction", "construction", 4),
         ("meter_set", "Meter set", "construction", "meter", 2),
         ("service_upgrade", "Service upgrade", "construction", "electric", 4),
         ("main_replacement", "Main renewal", "construction", "construction", 4))
KEYS = tuple(t[0] for t in TYPES)
IDX = {k: i for i, k in enumerate(KEYS)}
PROGRAM_KEYS = tuple(PROGRAMS)
EMERGENCY = ("gas_odour", "no_supply")  # response times (dispatch to on site)
PLANNED = ("seal_exchange", "ami_battery", "water_meter_replacement", "ami_conversion", "pole_inspection",
           "tree_trimming", "valve_exercise", "hydrant_flush", "leak_survey", "regulator_inspection",
           "service_upgrade", "main_replacement")  # orders from a programme plan (compliance)
FINDINGS = {"pole_inspection": "pole_replacement", "valve_exercise": "valve_repair", "hydrant_flush": "hydrant_repair",
            "leak_survey": "gas_leak_repair", "new_set": "meter_set"}
STATUSES = ("planned", "open", "in_progress", "completed")
REMOTE_MINUTES = 5.0
SURVEY_ROUTE_M = 1000.0
MAIN_SEGMENT_M = 100.0
DESIGN_BDAYS = 15  # a new service: request to construction release (design, locates, permits)
_M64 = 0xFFFFFFFFFFFFFFFF


def _mix(z: int) -> int:
    z = (z + 0x9E3779B97F4A7C15) & _M64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M64
    return z ^ (z >> 31)


def _u(run: M2CRun, *keys) -> float:
    """A uniform draw in [0, 1) keyed by the run seed, the field purpose and integer keys."""
    z = run.__dict__.get("_field_seed")
    if z is None:
        z = run.__dict__["_field_seed"] = _mix(normalize_seed(run.seed) ^ int(P))
    for k in keys:
        z = _mix(z ^ (int(k) & _M64))
    return (z >> 11) / 9007199254740992.0


def _poisson(lam: float, u: float) -> int:
    """A Poisson count by inversion of one uniform draw (small means)."""
    if lam <= 0:
        return 0
    k, p = 0, math.exp(-lam)
    s = p
    while u > s and k < 200:
        k += 1
        p *= lam / k
        s += p
    return k


def crews_on(fc, crew: str, premises: int) -> float:
    """Crews of a type on a day: ``per_1000_premises`` per 1,000 premises. On-call responders are whole crews (at
    least one when above zero); the business-day crews may be part of a crew (its share of the day on this work)."""
    c = getattr(fc, f"crew_{crew}")
    if c.per_1000_premises <= 0:
        return 0.0
    n = c.per_1000_premises * premises / 1000.0
    return float(max(1, int(round(n)))) if crew == "emergency" else round(n, 3)


@dataclass(eq=False, slots=True)
class Order:
    k: int
    type: int
    crew: str
    prio: int
    created: float
    release: float
    due: float
    minutes: float
    travel: float
    materials: float
    prem: int = -1
    asset: str = ""
    x: float = math.nan
    z: float = math.nan
    cause: str = ""
    fixed: bool = False
    remote: bool = False
    start: float = INF
    arrive: float = INF
    end: float = INF
    left: float = 0.0
    regular: float = 0.0  # crew minutes in shift
    overtime: float = 0.0  # crew minutes after hours
    labour: float = 0.0
    crew_id: str = ""
    then: tuple | None = None  # follow-up raised on completion
    parent: int = -1  # the order whose finding raised this one
    id: str = ""


@dataclass
class FieldWork:
    """The year's field orders (time order of creation) and per-day crew figures."""

    orders: list[Order]
    crews: dict  # crew -> {"crews", "availableMin", "busyMin", "overtimeMin"} arrays per day
    plan: dict  # planned type -> {"due": items due this year, "skipped": items the rate left out}
    premises: int
    notes: list[str]
    cols: dict = field(default_factory=dict)  # column arrays over orders, for the views


class _Build:
    def __init__(self, run: M2CRun):
        from utilsim.m2c import contact

        self.run, self.tw = run, run.town
        tw = self.tw
        self.n_prem = len(tw.premise_ids)
        self.fc = [run.cfg_at(d).field for d in range(YEAR_DAYS)]
        self.orders: list[Order] = []
        self.plan = {k: {"due": 0, "skipped": 0} for k in PLANNED}
        self.notes: list[str] = []
        self.ops = contact._ops(run)
        self.bdays = [d for d in range(YEAR_DAYS) if add_bdays(d, 0) == d]
        self.prem_meter: dict[tuple[int, str], int] = {}
        self.prem_meters: dict[int, list[int]] = {}
        for mi, (p, c) in enumerate(zip(tw.meter_prem.tolist(), tw.meter_commodity.tolist(), strict=True)):
            self.prem_meter.setdefault((p, c), mi)
            self.prem_meters.setdefault(p, []).append(mi)
        self.meter_mru = {}
        for r in range(tw.n_registers):
            self.meter_mru.setdefault(int(tw.meter_of[r]), tw.mru[r])

    # ---- helpers ------------------------------------------------------------------------------------------------
    def w(self, key: str, day: float):
        return getattr(self.fc[min(max(int(day), 0), YEAR_DAYS - 1)], key)

    def days_in(self, m0: int, m1: int) -> list[int]:
        """Business days from month ``m0`` to month ``m1`` (inclusive)."""
        return [d for d in self.bdays if m0 <= date_of(d).month <= m1] or self.bdays

    def season(self, day: int) -> list[int]:
        fc = self.fc[min(max(day, 0), YEAR_DAYS - 1)]
        return self.days_in(fc.construction_start_month, fc.construction_end_month)

    @staticmethod
    def spread(i: int, n: int, days: list[int]) -> int:
        """The ``i``-th of ``n`` items spread evenly over ``days``."""
        return days[min(len(days) - 1, int((i + 0.5) * len(days) / max(1, n)))]

    def morning(self, day: int) -> float:
        return day + self.fc[min(max(day, 0), YEAR_DAYS - 1)].shift_start_hour / 24.0

    def add(self, key: str, created: float, *, release: float | None = None, due: float | None = None,
            prem: int = -1, asset: str = "", xz: tuple | None = None, cause: str = "", crew: str | None = None,
            minutes: float | None = None, materials: float | None = None, travel: bool = True,
            fixed: tuple[float, float] | None = None, remote: bool = False, then: tuple | None = None,
            crew_id: str = "") -> Order | None:
        if not 0 <= created < YEAR_DAYS:
            return None
        _, _, _, tcrew, prio = TYPES[IDX[key]]
        wt = self.w(key, created)
        release = created if release is None else release
        if due is None:  # emergencies: calendar time; other work: the end of the business day it is due
            due = release + wt.target_days if prio == 1 else \
                add_bdays(int(math.floor(release)), int(math.ceil(wt.target_days - 1e-9))) + 1.0
        fc = self.fc[min(int(created), YEAR_DAYS - 1)]
        if xz is None and prem >= 0:
            xz = tuple(self.tw.premise_xz[prem]) if len(self.tw.premise_xz) else (math.nan, math.nan)
        o = Order(k=len(self.orders), type=IDX[key], crew=crew or tcrew or "meter", prio=prio, created=float(created),
                  release=float(release), due=float(due), minutes=float(wt.minutes if minutes is None else minutes),
                  travel=fc.travel_minutes if travel and not remote else 0.0,
                  materials=float(wt.materials if materials is None else materials), prem=int(prem), asset=asset,
                  x=float(xz[0]) if xz else math.nan, z=float(xz[1]) if xz else math.nan, cause=cause,
                  remote=remote, then=then, crew_id=crew_id)
        o.left = o.minutes + o.travel
        if remote:
            o.crew, o.start = "remote", float(release)
            o.arrive = o.end = o.start + REMOTE_MINUTES / 1440.0
            o.left, o.materials, o.crew_id = 0.0, 0.0, "AMI"
        elif fixed is not None:
            o.fixed, o.start = True, float(fixed[0])
            o.arrive = o.start + o.travel / 2880.0
            o.end = max(float(fixed[1]), o.arrive)
            o.left = 0.0
        self.orders.append(o)
        return o

    # ---- customer emergencies -----------------------------------------------------------------------------------
    def emergencies(self) -> None:
        from utilsim.m2c import contact

        run = self.run
        cx = contact.contacts(run)
        odour, outage = contact.IDX["gas_odour"], contact.IDX["outage"]
        seen: set[str] = set()
        for i in np.flatnonzero(((cx.reason == odour) | (cx.reason == outage)) & (cx.attempt == 1) & ~cx.repeat):
            t, trig, p = float(cx.t[i]), cx.trigger[i], int(cx.prem[i])
            if cx.reason[i] == odour:
                if trig != "background":
                    if trig in seen:
                        continue  # one responder per leak: the first report
                    seen.add(trig)
                if _u(run, IDX["gas_odour"], i, 0) < self.w("gas_odour", t).rate:
                    self.add("gas_odour", t, prem=p, cause=trig if trig != "background" else "odour report")
            elif trig == "background" and _u(run, IDX["no_supply"], i, 0) < self.w("no_supply", t).rate:
                self.add("no_supply", t, prem=p, cause="no supply report")
        for j, inc in enumerate(cx.incidents):
            t0 = float(inc["t"])
            if _u(run, IDX["outage_repair"], j, 0) >= self.w("outage_repair", t0).rate:
                continue
            util = inc["utility"]
            crew = util if util in ("electric", "water", "gas") else "electric"  # AMI collectors: line crews
            wt = self.w("outage_repair", t0)
            start = t0 + 30.0 / 1440.0  # detection, dispatch and driving
            back = float(np.max(inc["restoredAt"])) if len(inc["restoredAt"]) else start + wt.minutes / 1440.0
            self.add("outage_repair", t0, prem=-1, asset=inc["id"], xz=(inc["x"], inc["z"]),
                     cause=inc["label"], crew=crew, minutes=max(30.0, (back - start) * 1440.0),
                     fixed=(start, back))

    # ---- service orders -----------------------------------------------------------------------------------------
    def service_meter(self, prem: int) -> int:
        for c in ("electric", "water", "gas"):
            mi = self.prem_meter.get((prem, c))
            if mi is not None:
                return mi
        return -1

    def collections(self) -> None:
        run, tw = self.run, self.tw
        col = run.books.collections
        for aid, A in col.accounts.items():
            p = tw.premise_index.get((tw.accounts.get(aid) or {}).get("premiseId"), -1)
            if p < 0:
                continue
            mi = self.service_meter(p)
            for inv in A.invs:
                d = inv.get("disc")
                if not d or d.get("at") is None:
                    continue
                n = str_key(inv["id"])
                switch = mi >= 0 and tw.meter_tech[mi] == "AMI" and tw.meter_commodity[mi] == "electric"
                for key, t in (("disconnect", d["at"]), ("reconnect", d.get("reconnected"))):
                    if t is None or not 0 <= t < YEAR_DAYS:
                        continue
                    if _u(run, IDX[key], n, 0) >= self.w(key, t).rate:
                        continue
                    remote = switch and _u(run, IDX["disconnect"], int(tw.meter_keys[mi]), 1) < \
                        self.fc[int(t)].remote_switch_share
                    self.add(key, t, prem=p, asset=tw.meter_ids[mi] if mi >= 0 else "", cause=inv["id"],
                             remote=remote)

    def moves(self) -> None:
        run, tw = self.run, self.tw
        from utilsim.m2c.base import _day

        visits = {p: [tw.meter_ids[m] for m in ms if tw.meter_tech[m] != "AMI"] for p, ms in self.prem_meters.items()}
        outs: set[tuple[int, int]] = set()
        rows = []
        for aid, acct in tw.accounts.items():
            p = tw.premise_index.get(acct.get("premiseId"), -1)
            if p < 0 or not visits.get(p):
                continue
            for key, iso in (("move_out", acct.get("validTo")), ("move_in", acct.get("validFrom"))):
                day = _day(iso) if iso else None
                if day is not None and 0 <= day < YEAR_DAYS:
                    rows.append((key != "move_out", day, aid, p, key))
        for _, day, aid, p, key in sorted(rows):
            if key == "move_out":
                outs.add((p, day))
            elif (p, day) in outs or (p, day - 1) in outs:
                continue  # the move-out's visit read the meter for the new account too
            if _u(run, IDX[key], str_key(aid), 0) >= self.w(key, day).rate:
                continue
            release = self.morning(day)
            self.add(key, max(0.0, release - 5.0), release=release, prem=p, asset=", ".join(visits[p]), cause=aid)

    def visits(self) -> None:
        """The run's own field visits: VEE truck rolls (meter investigations) and the meters they exchanged."""
        run, tw = self.run, self.tw
        for case in run.cases:
            for t, kind, payload, _ in case.events:
                if kind != "TRUCK_ROLL" or not 0 <= t < YEAR_DAYS:
                    continue
                if _u(run, IDX["meter_investigation"], case.idx, int(t * 1440)) >= self.w("meter_investigation", t).rate:
                    continue
                wt = self.w("meter_investigation", t)
                travel = self.fc[int(t)].travel_minutes
                self.add("meter_investigation", t, prem=int(tw.prem[case.r]), asset=tw.meter_ids[tw.meter_of[case.r]],
                         cause=case.id, fixed=(t, t + (wt.minutes + travel) / 1440.0),
                         crew_id=str(payload.get("crew") or ""))
        for x in run.installs:
            if not x.physical or not 0 <= x.t_reg < YEAR_DAYS:
                continue
            if _u(run, IDX["corrective_exchange"], int(tw.meter_keys[x.meter]), int(x.t_reg * 1440)) >= \
                    self.w("corrective_exchange", x.t_reg).rate:
                continue
            wt = self.w("corrective_exchange", x.t_reg)
            self.add("corrective_exchange", x.t_reg, prem=int(tw.meter_prem[x.meter]), asset=x.device,
                     cause=x.case or x.order or x.previous, travel=False,
                     fixed=(x.t_reg, x.t_reg + wt.minutes / 1440.0), crew_id=x.by)

    # ---- meter maintenance --------------------------------------------------------------------------------------
    def seals(self) -> None:
        run, tw, fc = self.run, self.tw, self.fc[0]
        lots: dict[tuple[str, str, int], list[int]] = {}
        for mi in range(len(tw.meter_ids)):
            c = str(tw.meter_commodity[mi])
            if c not in ("electric", "gas") or tw.meter_installed[mi] <= 0:
                continue
            years = fc.seal_years_electric if c == "electric" else fc.seal_years_gas
            if int(tw.meter_installed[mi]) == YEAR - years:
                lots.setdefault((c, tw.meter_model[mi], int(tw.meter_installed[mi])), []).append(mi)
        self.lots: dict[str, dict] = {}
        window = self.days_in(1, 4)
        for n, key in enumerate(sorted(lots)):
            ms = sorted(lots[key], key=lambda m: _u(run, IDX["seal_exchange"], int(tw.meter_keys[m]), 0))
            lot = f"LOT-{key[0][0].upper()}-{key[1]}-{key[2]}"
            sample = ms[:min(fc.seal_sample_size, len(ms))]
            self.plan["seal_exchange"]["due"] += len(sample)
            state = {"rest": ms[len(sample):], "left": 0, "failed": None, "id": lot}
            self.lots[lot] = state
            first = self.spread(n, len(lots), window)
            for i, mi in enumerate(sample):
                day = add_bdays(first, i // 8)
                if _u(run, IDX["seal_exchange"], int(tw.meter_keys[mi]), 2) >= self.w("seal_exchange", day).rate:
                    self.plan["seal_exchange"]["skipped"] += 1
                    continue
                state["left"] += 1
                self.add("seal_exchange", 0.0, release=self.morning(day), prem=int(tw.meter_prem[mi]),
                         asset=tw.meter_ids[mi], cause=f"{lot} sample", then=("lot", lot))

    def lot_failed(self, lot: str, t: float) -> None:
        """A failed lot's sample is all tested: every other meter of the lot is exchanged by 31 December."""
        run, tw = self.run, self.tw
        state = self.lots[lot]
        self.plan["seal_exchange"]["due"] += len(state["rest"])
        days = [d for d in self.bdays if d > t] or [YEAR_DAYS - 1]
        for i, mi in enumerate(state["rest"]):
            day = self.spread(i, len(state["rest"]), days)
            if _u(run, IDX["seal_exchange"], int(tw.meter_keys[mi]), 2) >= self.w("seal_exchange", day).rate:
                self.plan["seal_exchange"]["skipped"] += 1
                continue
            self.add("seal_exchange", t, release=self.morning(day), due=float(YEAR_DAYS),
                     prem=int(tw.meter_prem[mi]), asset=tw.meter_ids[mi], cause=f"{lot} failed")

    def meters(self) -> None:
        run, tw, fc = self.run, self.tw, self.fc[0]
        n_m = len(tw.meter_ids)
        # Radio module batteries (AMI and AMR, gas and water) reaching their life this year, before the anniversary.
        for mi in range(n_m):
            if tw.meter_tech[mi] == "MANUAL" or tw.meter_commodity[mi] == "electric":
                continue
            if tw.meter_battery[mi] <= 0 or tw.meter_battery[mi] + fc.battery_years != YEAR:
                continue
            frac = tw.meter_installed[mi] - int(tw.meter_installed[mi]) if tw.meter_installed[mi] > 0 else 0.5
            anniv = int(frac * YEAR_DAYS)
            wt = self.w("ami_battery", anniv)
            day = add_bdays(max(0, int(anniv - wt.target_days * 7 / 5)), 0)  # due by the anniversary
            self.plan["ami_battery"]["due"] += 1
            if _u(run, IDX["ami_battery"], int(tw.meter_keys[mi]), 0) >= self.w("ami_battery", day).rate:
                self.plan["ami_battery"]["skipped"] += 1
                continue
            self.add("ami_battery", 0.0, release=self.morning(day), prem=int(tw.meter_prem[mi]),
                     asset=tw.meter_ids[mi], cause=f"battery {int(tw.meter_battery[mi])}")
        # Water meters at or past their service life.
        old = [mi for mi in range(n_m) if tw.meter_commodity[mi] == "water" and 0 < tw.meter_installed[mi]
               and int(tw.meter_installed[mi]) <= YEAR - fc.water_meter_life_years]
        old.sort(key=lambda m: (self.meter_mru.get(m, ""), int(tw.meter_keys[m])))
        days = self.days_in(2, 11)
        for i, mi in enumerate(old):
            day = self.spread(i, len(old), days)
            wt = self.w("water_meter_replacement", day)
            self.plan["water_meter_replacement"]["due"] += 1
            if _u(run, IDX["water_meter_replacement"], int(tw.meter_keys[mi]), 0) >= wt.rate:
                self.plan["water_meter_replacement"]["skipped"] += 1
                continue
            self.add("water_meter_replacement", 0.0, release=self.morning(day), prem=int(tw.meter_prem[mi]),
                     asset=tw.meter_ids[mi], cause=f"installed {int(tw.meter_installed[mi])}")
        # AMI conversion, route by route through the construction season.
        conv = [mi for mi in range(n_m) if tw.meter_tech[mi] in ("AMR", "MANUAL")]
        conv.sort(key=lambda m: (self.meter_mru.get(m, ""), int(tw.meter_keys[m])))
        days = self.season(0)
        for i, mi in enumerate(conv):
            day = self.spread(i, len(conv), days)
            if _u(run, IDX["ami_conversion"], int(tw.meter_keys[mi]), 0) >= self.w("ami_conversion", day).rate:
                continue
            self.plan["ami_conversion"]["due"] += 1
            self.add("ami_conversion", 0.0, release=self.morning(day), prem=int(tw.meter_prem[mi]),
                     asset=tw.meter_ids[mi], cause=f"{tw.meter_tech[mi]} to AMI")
        # Removals at vacant premises (service abandoned).
        vacant = [p for p in range(self.n_prem) if not tw.occupied[p] and self.prem_meters.get(p)]
        done: set[int] = set()
        for d in self.bdays:
            lam = self.w("removal", d).rate * self.n_prem / 1000.0 / len(self.bdays)
            for j in range(_poisson(lam, _u(run, IDX["removal"], d, 0))):
                pool = [p for p in vacant if p not in done]
                if not pool:
                    break
                p = pool[int(_u(run, IDX["removal"], d, j, 1) * len(pool))]
                done.add(p)
                ms = self.prem_meters[p]
                self.add("removal", float(d), release=self.morning(d), prem=p,
                         asset=", ".join(tw.meter_ids[m] for m in ms), cause="vacant premise",
                         minutes=self.w("removal", d).minutes * len(ms))

    # ---- preventative maintenance -------------------------------------------------------------------------------
    def programme(self, key: str, assets: list[tuple], days: list[int], crew: str | None = None) -> None:
        """Orders for a share (the rate on the scheduled day) of ``assets`` (id, x, z, minutes factor, then) spread
        over ``days`` in asset order."""
        run = self.run
        for i, (aid, x, z, f, then, acrew) in enumerate(assets):
            day = self.spread(i, len(assets), days)
            wt = self.w(key, day)
            if _u(run, IDX[key], str_key(aid), 0) >= wt.rate:
                continue
            self.plan[key]["due"] += 1
            self.add(key, 0.0, release=self.morning(day), asset=aid, xz=(x, z), crew=acrew or crew,
                     minutes=wt.minutes * f, materials=wt.materials * f, then=then, cause="programme")

    def maintenance(self) -> None:
        ops = self.ops
        if ops is None:
            self.notes.append("No network for this run: preventative maintenance, main renewal and outage repairs "
                              "have no assets.")
            return
        el, wa, ga = ops.nets["electric"], ops.nets["water"], ops.nets["gas"]

        def mid(net, e: int) -> tuple[float, float]:
            pts = net.points[e]
            return float(pts[len(pts) // 2][0]), float(pts[len(pts) // 2][1])

        year = self.bdays
        poles = [(q["id"], q["x"], q["z"], 1.0, ("find", "pole_replacement", q["id"]), None)
                 for q in el.equipment if q["kind"] == "pole"]
        self.programme("pole_inspection", poles, year)
        spans = [(el.edge_ids[e], *mid(el, e), 1.0, None, None) for e in range(len(el.edge_ids))
                 if el.placement and el.placement[e] == "overhead" and el.kind[e] in ("distribution", "trunk")]
        self.programme("tree_trimming", spans, year)
        valves = [(q["id"], q["x"], q["z"], 1.0, ("find", "valve_repair", q["id"]), u)
                  for u, net in (("water", wa), ("gas", ga)) for q in net.equipment if q["kind"] == "valve"]
        self.programme("valve_exercise", valves, year, crew="water")
        hydrants = [(q["id"], q["x"], q["z"], 1.0, ("find", "hydrant_repair", q["id"]), None)
                    for q in wa.equipment if q["kind"] == "hydrant"]
        self.programme("hydrant_flush", hydrants, self.days_in(5, 10))
        # Leak survey routes: consecutive gas main edges, about a kilometre each.
        routes, cur, length = [], [], 0.0
        for e in range(len(ga.edge_ids)):
            if ga.kind[e] not in ("distribution", "trunk"):
                continue
            cur.append(e)
            length += float(ga.length[e])
            if length >= SURVEY_ROUTE_M:
                routes.append((cur, length))
                cur, length = [], 0.0
        if cur:
            routes.append((cur, length))
        survey = [(f"LS-{k + 1:03d}", *mid(ga, es[len(es) // 2]), km / 1000.0,
                   ("leaks", km / 1000.0, tuple(es)), None) for k, (es, km) in enumerate(routes)]
        self.programme("leak_survey", survey, self.days_in(4, 11))
        regs = [(ga.node_ids[i], float(ga.node_xy[i][0]), float(ga.node_xy[i][1]), 1.0, None, None)
                for i, kind in enumerate(ga.node_kind) if "regulator" in kind]
        self.programme("regulator_inspection", regs, year)

    def finding(self, o: Order) -> None:
        """An inspection's finding raises its repair (the rate on the completion day)."""
        kind = o.then[0]
        t = o.end
        day = add_bdays(int(t), 1 if kind != "lot" else 0)
        if kind == "lot":  # the lot passes or fails when its last sample meter is tested (the pass rate that day)
            state = self.lots[o.then[1]]
            state["left"] -= 1
            if state["left"] == 0:
                state["failed"] = _u(self.run, IDX["seal_exchange"], str_key(state["id"]), 1) >= \
                    self.fc[min(int(t), YEAR_DAYS - 1)].seal_lot_pass_rate
                if state["failed"]:
                    self.lot_failed(o.then[1], t)
            return
        if kind == "find":
            key, aid = o.then[1], o.then[2]
            if _u(self.run, IDX[key], str_key(aid), 1) < self.w(key, t).rate:
                x = self.add(key, t, release=self.morning(add_bdays(int(t), 5)), asset=aid, xz=(o.x, o.z),
                             crew=o.crew)
                if x is not None:
                    x.parent = o.k
        elif kind == "leaks":
            km, edges = o.then[1], o.then[2]
            n = _poisson(self.w("gas_leak_repair", t).rate * km, _u(self.run, IDX["gas_leak_repair"], o.k, 0))
            ga = self.ops.nets["gas"]
            for j in range(n):
                e = edges[int(_u(self.run, IDX["gas_leak_repair"], o.k, j, 1) * len(edges))]
                pts = ga.points[e]
                x = self.add("gas_leak_repair", t, release=self.morning(day), asset=ga.edge_ids[e],
                             xz=(float(pts[0][0]), float(pts[0][1])))
                if x is not None:
                    x.parent = o.k
        elif kind == "set":
            if _u(self.run, IDX["meter_set"], o.k, 0) < self.w("meter_set", t).rate:
                x = self.add("meter_set", t, release=self.morning(day), asset=o.asset, xz=(o.x, o.z))
                if x is not None:
                    x.parent = o.k

    # ---- capital construction -----------------------------------------------------------------------------------
    def construction(self) -> None:
        from utilsim.m2c import contact

        run, tw = self.run, self.tw
        cx = contact.contacts(run)
        streets = sorted({s for s in tw.premise_street if s})
        req = np.flatnonzero((cx.reason == contact.IDX["new_connection"]) & (cx.attempt == 1) & ~cx.repeat)
        n = 0
        for i in req.tolist():
            t = float(cx.t[i])
            if _u(run, IDX["new_set"], i, 0) >= self.w("new_set", t).rate:
                continue
            n += 1
            ready = add_bdays(int(t), DESIGN_BDAYS)
            season = [d for d in self.season(ready) if d >= ready]
            release = self.morning(season[0]) if season else float(YEAR_DAYS + 1)
            street = streets[int(_u(run, IDX["new_set"], i, 1) * len(streets))] if streets else ""
            on = [p for p, s in enumerate(tw.premise_street) if s == street]
            p = on[int(_u(run, IDX["new_set"], i, 2) * len(on))] if on else -1
            xz = tuple(tw.premise_xz[p] + 15.0) if p >= 0 else None
            self.add("new_set", t, release=release, asset=f"NEW-{n:03d}", xz=xz,
                     cause=f"new connection on {street}" if street else "new connection", then=("set",))
        # Electric service upgrades: homes with an EV or electric heat, through the season.
        at = tw.premise_attrs
        homes = [p for p in range(self.n_prem) if len(at) and at["residential"][p] and (at["hasEV"][p] or
                                                                                     at["electricHeat"][p])
                 and (p, "electric") in self.prem_meter]
        days = self.season(0)
        for i, p in enumerate(homes):
            day = self.spread(i, len(homes), days)
            if _u(run, IDX["service_upgrade"], p, 0) >= self.w("service_upgrade", day).rate:
                continue
            self.plan["service_upgrade"]["due"] += 1
            self.add("service_upgrade", 0.0, release=self.morning(day), prem=p,
                     asset=tw.meter_ids[self.prem_meter[(p, "electric")]],
                     cause="EV charger" if at["hasEV"][p] else "electric heat")
        if self.ops is None:
            return
        segs = []
        for u in ("water", "gas"):
            net = self.ops.nets[u]
            for e in range(len(net.edge_ids)):
                if net.kind[e] != "distribution" or (net.material[e] or "") != "cast iron":
                    continue
                length = float(net.length[e])
                k = max(1, int(math.ceil(length / MAIN_SEGMENT_M)))
                pts = net.points[e]
                for j in range(k):
                    q = pts[min(len(pts) - 1, int((j + 0.5) * len(pts) / k))]
                    segs.append((f"{net.edge_ids[e]}/{j + 1}", float(q[0]), float(q[1]), length / k / MAIN_SEGMENT_M,
                                 None, None))
        self.programme("main_replacement", segs, days)

    # ---- the crews ----------------------------------------------------------------------------------------------
    def simulate(self) -> dict:
        orders = self.orders
        crews = {c: {"crews": np.zeros(YEAR_DAYS), "availableMin": np.zeros(YEAR_DAYS),
                     "busyMin": np.zeros(YEAR_DAYS), "overtimeMin": np.zeros(YEAR_DAYS)} for c in CREWS}
        for d, fc in enumerate(self.fc):
            for c in CREWS:
                crews[c]["crews"][d] = crews_on(fc, c, self.n_prem)
        # On-call responders: around the clock, first come first served, several crews at once.
        em = sorted((o for o in orders if o.crew == "emergency"), key=lambda o: (o.created, o.k))
        free = np.zeros(max(1, int(crews["emergency"]["crews"].max())))
        for o in em:
            d = min(int(o.created), YEAR_DAYS - 1)
            fc = self.fc[d]
            n = int(crews["emergency"]["crews"][d])
            if n <= 0:
                continue
            i = int(np.argmin(free[:n]))
            o.start = max(o.created, float(free[i]))
            sd = min(int(o.start), YEAR_DAYS - 1)
            h = (o.start - sd) * 24.0
            in_shift = add_bdays(sd, 0) == sd and fc.shift_start_hour <= h < fc.shift_start_hour + fc.shift_hours
            o.arrive = o.start + (o.travel / 2.0 + (0.0 if in_shift else fc.callout_minutes)) / 1440.0
            o.end = o.arrive + o.minutes / 1440.0
            free[i] = o.end + o.travel / 2880.0
            o.crew_id = f"ER-{i + 1}"
            mins = o.minutes + o.travel
            cost = fc.crew_emergency.cost_per_hour
            if in_shift:
                o.regular, o.labour = mins, mins / 60.0 * cost
            else:
                o.overtime, o.labour = mins, mins / 60.0 * cost * fc.crew_emergency.overtime_factor
            crews["emergency"]["busyMin"][sd] += mins
            o.left = 0.0
        for d in range(YEAR_DAYS):
            crews["emergency"]["availableMin"][d] = crews["emergency"]["crews"][d] * 1440.0
        # Work timed elsewhere (VEE visits, outage repairs): the crews' time on its day first.
        fixed_on: dict[tuple[str, int], float] = {}
        for o in orders:
            if not o.fixed:
                continue
            fc = self.fc[min(int(o.start), YEAR_DAYS - 1)]
            c = getattr(fc, f"crew_{o.crew}")
            sd = min(int(o.start), YEAR_DAYS - 1)
            mins = max(0.0, (o.end - o.start) * 1440.0)
            h = (o.start - sd) * 24.0
            shift_end = fc.shift_start_hour + fc.shift_hours
            if add_bdays(sd, 0) == sd and fc.shift_start_hour <= h < shift_end:
                reg = min(mins, (shift_end - h) * 60.0)
            else:
                reg = 0.0
            o.regular, o.overtime = reg, mins - reg
            o.labour = (reg + (mins - reg) * c.overtime_factor) / 60.0 * c.cost_per_hour
            fixed_on[(o.crew, sd)] = fixed_on.get((o.crew, sd), 0.0) + reg
            crews[o.crew]["overtimeMin"][sd] += mins - reg
        # The business-day crews: released work by priority, then due date.
        pending = [(o.release, o.k) for o in orders if not o.fixed and not o.remote and o.crew in DAY_CREWS]
        heapq.heapify(pending)
        queues: dict[str, list] = {c: [] for c in DAY_CREWS}
        for d in range(YEAR_DAYS):
            fc = self.fc[d]
            shift_end = fc.shift_start_hour + fc.shift_hours
            while pending and pending[0][0] < d + shift_end / 24.0:
                _, k = heapq.heappop(pending)
                o = orders[k]
                heapq.heappush(queues[o.crew], (o.prio, o.due, o.release, o.k))
            if add_bdays(d, 0) != d:
                continue
            spawned: list[Order] = []
            for c in DAY_CREWS:
                n = float(crews[c]["crews"][d])
                if n <= 0:
                    continue
                slots = max(1, math.ceil(n))
                cc = getattr(fc, f"crew_{c}")
                cap = n * fc.shift_hours * 60.0
                crews[c]["availableMin"][d] = cap
                used = min(cap, fixed_on.get((c, d), 0.0))
                q = queues[c]
                t0 = d + fc.shift_start_hour / 24.0
                started = 0
                while q and used < cap - 1e-9:
                    o = orders[q[0][3]]
                    if o.start == INF:
                        o.start = max(o.release, t0 + used / n / 1440.0)
                        o.arrive = o.start + o.travel / 2880.0
                        o.crew_id = f"{CREW_CODE[c]}-{started % slots + 1}"
                        started += 1
                    take = min(o.left, cap - used)
                    used += take
                    o.left -= take
                    o.regular += take
                    o.labour += take / 60.0 * cc.cost_per_hour
                    if o.left > 1e-9:
                        break
                    heapq.heappop(q)
                    o.end = max(o.arrive, t0 + used / n / 1440.0)
                    if o.then:
                        spawned.append(o)
                ot_cap, ot = n * fc.overtime_max_hours * 60.0, 0.0
                while q and ot < ot_cap - 1e-9:
                    o = orders[q[0][3]]
                    if o.prio > 2 or o.due > d + 1:
                        break
                    if o.start == INF:
                        o.start = max(o.release, d + shift_end / 24.0)
                        o.arrive = o.start + o.travel / 2880.0
                        o.crew_id = f"{CREW_CODE[c]}-{started % slots + 1}"
                        started += 1
                    take = min(o.left, ot_cap - ot)
                    ot += take
                    o.left -= take
                    o.overtime += take
                    o.labour += take / 60.0 * cc.cost_per_hour * cc.overtime_factor
                    if o.left > 1e-9:
                        break
                    heapq.heappop(q)
                    o.end = max(o.arrive, d + shift_end / 24.0 + ot / n / 1440.0)
                    if o.then:
                        spawned.append(o)
                crews[c]["busyMin"][d] += used
                crews[c]["overtimeMin"][d] += ot
            for o in spawned:  # follow-ups (repairs, lot exchanges, meter sets) from tomorrow
                before = len(orders)
                self.finding(o)
                for k in range(before, len(orders)):
                    x = orders[k]
                    if x.crew in DAY_CREWS and not x.fixed and not x.remote:
                        heapq.heappush(pending, (x.release, x.k))
        return crews


def _columns(fw: FieldWork) -> dict:
    o = fw.orders
    return {"type": np.array([x.type for x in o], dtype=np.int64),
            "program": np.array([PROGRAM_KEYS.index(TYPES[x.type][2]) for x in o], dtype=np.int64),
            "crew": np.array([x.crew for x in o]),
            "created": np.array([x.created for x in o], dtype=float),
            "release": np.array([x.release for x in o], dtype=float),
            "due": np.array([x.due for x in o], dtype=float),
            "start": np.array([x.start for x in o], dtype=float),
            "arrive": np.array([x.arrive for x in o], dtype=float),
            "end": np.array([x.end for x in o], dtype=float),
            "regular": np.array([x.regular for x in o], dtype=float),
            "overtime": np.array([x.overtime for x in o], dtype=float),
            "labour": np.array([x.labour for x in o], dtype=float),
            "materials": np.array([x.materials for x in o], dtype=float),
            "remote": np.array([x.remote for x in o], dtype=bool),
            # when an order meets its due date: on site for an emergency, finished for everything else
            "met": np.array([x.arrive if KEYS[x.type] in EMERGENCY else x.end for x in o], dtype=float)}


def fieldwork(run: M2CRun) -> FieldWork:
    """The year's field work (computed once per run, after the replay and the contact centre)."""
    hit = run.__dict__.get("_fieldwork")
    if hit is not None:
        return hit
    b = _Build(run)
    b.emergencies()
    b.collections()
    b.moves()
    b.visits()
    b.seals()
    b.meters()
    b.maintenance()
    b.construction()
    crews = b.simulate()
    orders = sorted(b.orders, key=lambda o: (o.created, o.release, o.k))
    for n, o in enumerate(orders, start=1):
        o.id = f"WO-{n:06d}"
    by_k = {o.k: o for o in orders}
    for o in orders:  # a finding's repair names the inspection (or new service) that raised it
        if o.parent >= 0:
            p = by_k[o.parent]
            o.cause = f"{p.id} {TYPES[p.type][1].lower()}"
    fw = FieldWork(orders=orders, crews=crews, plan=b.plan, premises=b.n_prem, notes=b.notes)
    fw.cols = _columns(fw)
    run.__dict__["_fieldwork"] = fw
    return fw


# ---- views --------------------------------------------------------------------------------------------------------
def status_at(o: Order, T: float) -> str | None:
    """An order's status at ``T`` (None before it is created)."""
    if o.created > T:
        return None
    if o.end <= T:
        return "completed"
    if o.start <= T:
        return "in_progress"
    return "open" if o.release <= T else "planned"


def _r(x, n: int = 2) -> float:
    return round(float(x), n)


def _stats(fw: FieldWork, k: np.ndarray, T: float, lo: float) -> dict:
    """Figures for the orders selected by ``k``: created and completed in [lo, T], open and overdue at T."""
    c = fw.cols
    made = k & (c["created"] >= lo) & (c["created"] <= T)
    done = k & (c["end"] >= lo) & (c["end"] <= T)
    live = k & (c["created"] <= T) & (c["end"] > T)
    released = live & (c["release"] <= T)
    overdue = released & (c["due"] < T)
    ontime = done & (c["met"] <= c["due"] + 1e-9)
    em = done & np.isin(c["type"], [IDX[x] for x in EMERGENCY])
    resp = (c["arrive"][em] - c["created"][em]) * 1440.0
    lab, mat = float(c["labour"][done].sum()), float(c["materials"][done].sum())
    n_done = int(done.sum())
    return {"created": int(made.sum()), "completed": n_done, "open": int(released.sum()),
            "planned": int((live & (c["release"] > T)).sum()), "overdue": int(overdue.sum()),
            "onTimePct": round(int(ontime.sum()) / n_done, 4) if n_done else None,
            "remote": int((done & c["remote"]).sum()),
            "responseMin": round(float(resp.mean()), 1) if len(resp) else None,
            "responseP90Min": round(float(np.percentile(resp, 90)), 1) if len(resp) else None,
            "hours": _r((c["regular"][done].sum() + c["overtime"][done].sum()) / 60.0, 1),
            "overtimeHours": _r(c["overtime"][done].sum() / 60.0, 1),
            "daysToComplete": round(float((c["end"][done & ~c["remote"]] - c["release"][done & ~c["remote"]]).mean()),
                                    2) if (done & ~c["remote"]).any() else None,
            "cost": {"labour": _r(lab), "materials": _r(mat), "total": _r(lab + mat)}}


def _crew_stats(fw: FieldWork, crew: str, d0: int, d1: int) -> dict:
    cr = fw.crews[crew]
    s = slice(d0, d1 + 1)
    avail, busy = float(cr["availableMin"][s].sum()), float(cr["busyMin"][s].sum())
    return {"availableHours": _r(avail / 60.0, 1), "busyHours": _r(busy / 60.0, 1),
            "overtimeHours": _r(cr["overtimeMin"][s].sum() / 60.0, 1),
            "utilisationPct": round(busy / avail, 4) if avail else None}


def monthly(run: M2CRun, day: int, T: float, starts) -> list[dict | None]:
    """Field figures per month to ``T`` (``None`` for months that have not started), for the trend."""
    fw = fieldwork(run)
    c = fw.cols
    every = np.ones(len(fw.orders), dtype=bool)
    out = []
    for m in range(1, 13):
        start, end_excl = int(starts[m]), int(starts[m + 1])
        if start > day:
            out.append(None)
            continue
        end_day = min(end_excl - 1, day)
        Tm = min(end_day + 1 - 1e-6, T)
        s = _stats(fw, every, Tm, start)
        s["byProgram"] = {p: _stats(fw, c["program"] == i, Tm, start)["completed"] for i, p in enumerate(PROGRAM_KEYS)}
        s["backlog"] = {p: int(((c["program"] == i) & (c["release"] <= Tm) & (c["end"] > Tm)).sum())
                        for i, p in enumerate(PROGRAM_KEYS)}
        busy = sum(float(fw.crews[x]["busyMin"][start:end_day + 1].sum()) for x in DAY_CREWS)
        avail = sum(float(fw.crews[x]["availableMin"][start:end_day + 1].sum()) for x in DAY_CREWS)
        s["utilisationPct"] = round(busy / avail, 4) if avail else None
        out.append(s)
    return out


def summary(run: M2CRun, as_of: str | None = None) -> dict:
    """``m2c-fieldwork/1.0``: the field work to date (KPIs, programmes, work types, crews, the maintenance plan and
    the last 60 days)."""
    from utilsim.m2c import views

    day, T = views.as_of_t(run, as_of)
    fw = fieldwork(run)
    c = fw.cols
    every = np.ones(len(fw.orders), dtype=bool)
    fc = run.cfg_at(day).field
    kpis = _stats(fw, every, T, 0.0)
    busy = sum(float(fw.crews[x]["busyMin"][:day + 1].sum()) for x in DAY_CREWS)
    avail = sum(float(fw.crews[x]["availableMin"][:day + 1].sum()) for x in DAY_CREWS)
    kpis["utilisationPct"] = round(busy / avail, 4) if avail else None
    programs = [{"id": p, "label": PROGRAMS[p], **_stats(fw, c["program"] == i, T, 0.0)}
                for i, p in enumerate(PROGRAM_KEYS)]
    types = []
    for i, (key, label, prog, crew, prio) in enumerate(TYPES):
        s = _stats(fw, c["type"] == i, T, 0.0)
        types.append({"id": key, "label": label, "program": prog, "crew": crew or "by utility", "priority": prio,
                      **s, "settings": getattr(fc, key).model_dump(mode="json")})
    crews = []
    for crew, label in CREWS.items():
        k = c["crew"] == crew
        lab = float(c["labour"][k & (c["end"] <= T)].sum())
        cc = getattr(fc, f"crew_{crew}")
        crews.append({"id": crew, "label": label, "crews": crews_on(fc, crew, fw.premises), **_crew_stats(fw, crew, 0, day),
                      "orders": int((k & (c["end"] <= T)).sum()), "labour": _r(lab),
                      "settings": cc.model_dump(mode="json")})
    plan = []
    for key in PLANNED:
        i = IDX[key]
        k = c["type"] == i
        due_now = k & (c["due"] <= T)
        done_ontime = due_now & (c["end"] <= c["due"] + 1e-9)
        p = fw.plan[key]
        plan.append({"id": key, "label": TYPES[i][1], "program": TYPES[i][2], "due": p["due"],
                     "skipped": p["skipped"], "orders": int((k & (c["created"] <= T)).sum()),
                     "completed": int((k & (c["end"] <= T)).sum()), "dueByNow": int(due_now.sum()),
                     "onTime": int(done_ontime.sum()),
                     "compliancePct": round(int(done_ontime.sum()) / int(due_now.sum()), 4) if due_now.any() else None})
    first = max(0, day - 59)
    series = []
    for d in range(first, day + 1):
        Td = min(d + 1 - 1e-6, T)
        s = _stats(fw, every, Td, float(d))
        series.append({"date": date_of(d).isoformat(), "created": s["created"], "completed": s["completed"],
                       "open": s["open"], "overdue": s["overdue"],
                       "backlog": {p: int(((c["program"] == i) & (c["release"] <= Td) & (c["end"] > Td)).sum())
                                   for i, p in enumerate(PROGRAM_KEYS)}})
    notes = list(fw.notes)
    if not run.cfg.billing.disconnect_rule_share and not any(a["type"] == "disconnect_approve" for a in run.actions):
        notes.append("Disconnects and reconnects follow the disconnections you approve in Collections (or the "
                     "collections rule, billing.disconnect_rule_share); none are approved in this run.")
    return {"schemaVersion": FIELD_VERSION, "simulationId": run.simulation_id, "asOf": date_of(day).isoformat(),
            "kpis": kpis, "programs": programs, "types": types, "crews": crews, "plan": plan, "daily": series,
            "labels": {"programs": PROGRAMS, "crews": CREWS}, "notes": notes}
