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

The crews work inside the replay (``FieldEngine``, ``run.field``), day by day with the reads, bills and collections.
On-call responders work emergencies around the clock (first come, first served, several crews at once). Meter
technicians, the three utilities' crews and the construction crews work business days from ``shift_start_hour`` for
``shift_hours``: an order is released on its day, and each crew type works its released orders by priority, then due
date. Work the run or an incident has already timed (VEE visits, outage repairs) takes the crews' time on its day
first. A long job carries over to the next day. Customer work (priority 1 and 2) due today or overdue may run into
overtime, up to ``overtime_max_hours`` per crew. With ``routing`` the crews drive the town's streets at the operations
driving speeds (``_Roads``): each crew leaves the depot in the morning, takes of the jobs as urgent as the most
pressing (and due within a day of it) the nearest next, adds ``stop_minutes`` at each stop and drives back at the end
of the day; on-call responders drive from the depot and back. Without it every visit adds ``travel_minutes``.

What the crews do changes the year from that moment:

* **Disconnect, removal:** the service is off (nothing flows). The meter is read as it goes off: the first scheduled
  read in the off period is that final read (taken at the disconnection), so the bill runs to the disconnection;
  later scheduled reads are not taken, so no bill is made for those months. A reconnect switches it back; the next
  bill runs from the final read.
  Collections asks for the disconnect on the earliest day; it happens when the crew (or the remote switch) does it, and
  a customer who paid before the crew arrived is not disconnected.
* **Exchanges** (seal, water meter replacement, AMI conversion) register a new meter: reads are measured on the new
  register, a fault on the old meter ends, an AMI conversion reads the meter as AMI from then on.
* **Deferred maintenance fails:** a module battery not replaced by its anniversary dies and misses reads
  (``dead_battery_miss``); a failed seal lot's meters and water meters past their life under-register until exchanged
  (``failed_lot_drift``, ``old_water_meter_drift``); a pole found needing replacement, a span overdue for trimming (on
  storm days) and a surveyed leak overdue for repair can fail (``deferred_*``): an outage or a public gas leak, with
  its customers, contacts, emergency response and repair.
* **Main renewal:** a renewed segment of cast-iron main breaks and leaks at ``renewed_main_break_factor`` of the old
  main's rate from the day it is finished (the year's drawn breaks and leaks on it are dropped at that share).

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
STATUSES = ("planned", "open", "in_progress", "completed", "cancelled")
REMOTE_MINUTES = 5.0
SURVEY_ROUTE_M = 1000.0
MAIN_SEGMENT_M = 100.0
DESIGN_BDAYS = 15  # a new service: request to construction release (design, locates, permits)
_M64 = 0xFFFFFFFFFFFFFFFF
P_FAIL = 901  # draw key: overdue work failing (apart from the work types' own draws)
P_RENEW = 902  # draw key: a break or leak a renewed main does not have


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
    meter: int = -1  # the meter slot it works on (meter work, disconnects)
    inv: str = ""  # the invoice a disconnect or reconnect is for
    cancelled: bool = False  # called off before a crew started it (paid, held, failed first)
    outcome: str = ""  # what came of it, when not simply done (not needed, skipped: meter off, failed first)
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
    failures: list[dict] = field(default_factory=list)  # overdue work that failed: {t, kind, orderId, incident}


class _Roads:
    """Drive times on the town's streets for the field crews, at the operations driving speeds: where a crew parks
    for an order (the premise's street access, or the street point nearest the asset) and how long the drive is
    between two such points. A shortest-time tree per street corner is built on first use."""

    def __init__(self, run: M2CRun, ops):
        from utilsim.ops.routing import Router, access_point

        o = ops.ops
        self.g = g = ops.roads
        self.mps = Router(g, (o["speed_kmh_arterial"], o["speed_kmh_collector"], o["speed_kmh_local"])).edge_mps
        self.sec = (g.length / self.mps).tolist()
        self.ops, self.tw, self._point = ops, run.town, access_point
        dep = ops.depot
        self.depot = access_point(g, *dep["access"]) if dep.get("access") else ops.nearest_access(dep["x"], dep["z"])
        self._tree: dict[int, list[float]] = {}
        self._at: dict[int, tuple[int, float] | None] = {}

    def spot(self, o: Order) -> tuple[int, float] | None:
        if o.k not in self._at:
            at = None
            if o.prem >= 0:
                i = self.ops.premise_index.get(self.tw.premise_ids[o.prem])
                if i is not None:
                    at = self._point(self.g, *self.ops.premise_access[i])
            if at is None and math.isfinite(o.x) and math.isfinite(o.z):
                at = self.ops.nearest_access(o.x, o.z)
            self._at[o.k] = at
        return self._at[o.k]

    def _from(self, n: int) -> list[float]:
        tree = self._tree.get(n)
        if tree is None:
            adj, sec = self.g.adj, self.sec
            tree = [INF] * len(self.g.node_xy)
            tree[n] = 0.0
            heap = [(0.0, n)]
            while heap:
                t, v = heapq.heappop(heap)
                if t > tree[v]:
                    continue
                for k, w in adj[v]:
                    nt = t + sec[k]
                    if nt < tree[w]:
                        tree[w] = nt
                        heapq.heappush(heap, (nt, w))
            self._tree[n] = tree
        return tree

    def minutes(self, a: tuple[int, float], b: tuple[int, float]) -> float:
        """The fastest drive from ``a`` to ``b`` (street points), in minutes; inf on separate road islands."""
        g, mps = self.g, self.mps
        (e0, s0), (e1, s1) = a, b
        best = abs(s1 - s0) / mps[e0] if e0 == e1 else INF
        for n0, d0 in ((int(g.a[e0]), s0), (int(g.b[e0]), float(g.length[e0]) - s0)):
            tree, t0 = self._from(n0), d0 / mps[e0]
            for n1, d1 in ((int(g.a[e1]), s1), (int(g.b[e1]), float(g.length[e1]) - s1)):
                best = min(best, t0 + tree[n1] + d1 / mps[e1])
        return float(best) / 60.0


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
        self.main_seg: dict[str, tuple[str, int, float]] = {}  # main renewal segment -> (utility, edge, share)
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
            crew_id: str = "", meter: int = -1) -> Order | None:
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
                  remote=remote, then=then, crew_id=crew_id, meter=int(meter))
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
    def responses(self) -> None:
        """After the year: gas odour and no-supply calls a responder attends (the contact centre's contacts)."""
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

    def repair(self, inc: dict, j: int) -> None:
        """An incident's repair on the utility's crew, timed by the incident model (detection, travel, restoration)."""
        run = self.run
        t0 = float(inc["t"])
        if _u(run, IDX["outage_repair"], j, 0) >= self.w("outage_repair", t0).rate:
            return
        util = inc["utility"]
        crew = util if util in ("electric", "water", "gas") else "electric"  # AMI collectors: line crews
        wt = self.w("outage_repair", t0)
        start = t0 + 30.0 / 1440.0  # detection, dispatch and driving
        back = float(np.max(inc["restoredAt"])) if len(inc["restoredAt"]) else start + wt.minutes / 1440.0
        self.add("outage_repair", t0, prem=-1, asset=inc["id"], xz=(inc["x"], inc["z"]), cause=inc["label"],
                 crew=crew, minutes=max(30.0, (back - start) * 1440.0), fixed=(start, back))

    # ---- service orders -----------------------------------------------------------------------------------------
    def service_meter(self, prem: int) -> int:
        for c in ("electric", "water", "gas"):
            mi = self.prem_meter.get((prem, c))
            if mi is not None:
                return mi
        return -1

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
                         asset=tw.meter_ids[mi], cause=f"{lot} sample", then=("lot", lot), meter=mi)

    def lot_failed(self, lot: str, t: float) -> None:
        """A failed lot's sample is all tested: every other meter of the lot is exchanged by 31 December. Until a
        meter is exchanged it under-registers (``failed_lot_drift``)."""
        run, tw = self.run, self.tw
        state = self.lots[lot]
        self.plan["seal_exchange"]["due"] += len(state["rest"])
        drift = self.fc[min(int(t), YEAR_DAYS - 1)].failed_lot_drift
        for mi in state["rest"]:
            run.set_drift(mi, drift, t)
        days = [d for d in self.bdays if d > t] or [YEAR_DAYS - 1]
        for i, mi in enumerate(state["rest"]):
            day = self.spread(i, len(state["rest"]), days)
            if _u(run, IDX["seal_exchange"], int(tw.meter_keys[mi]), 2) >= self.w("seal_exchange", day).rate:
                self.plan["seal_exchange"]["skipped"] += 1
                continue
            self.add("seal_exchange", t, release=self.morning(day), due=float(YEAR_DAYS),
                     prem=int(tw.meter_prem[mi]), asset=tw.meter_ids[mi], cause=f"{lot} failed", meter=mi)

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
            run.battery_dead[mi] = float(anniv)  # the battery dies on the anniversary unless replaced before
            if _u(run, IDX["ami_battery"], int(tw.meter_keys[mi]), 0) >= self.w("ami_battery", day).rate:
                self.plan["ami_battery"]["skipped"] += 1
                continue
            self.add("ami_battery", 0.0, release=self.morning(day), prem=int(tw.meter_prem[mi]),
                     asset=tw.meter_ids[mi], cause=f"battery {int(tw.meter_battery[mi])}", meter=mi)
        # Water meters at or past their service life.
        old = [mi for mi in range(n_m) if tw.meter_commodity[mi] == "water" and 0 < tw.meter_installed[mi]
               and int(tw.meter_installed[mi]) <= YEAR - fc.water_meter_life_years]
        old.sort(key=lambda m: (self.meter_mru.get(m, ""), int(tw.meter_keys[m])))
        for mi in old:  # an old water meter under-registers until it is replaced
            run.set_drift(mi, fc.old_water_meter_drift, 0.0)
        days = self.days_in(2, 11)
        for i, mi in enumerate(old):
            day = self.spread(i, len(old), days)
            wt = self.w("water_meter_replacement", day)
            self.plan["water_meter_replacement"]["due"] += 1
            if _u(run, IDX["water_meter_replacement"], int(tw.meter_keys[mi]), 0) >= wt.rate:
                self.plan["water_meter_replacement"]["skipped"] += 1
                continue
            self.add("water_meter_replacement", 0.0, release=self.morning(day), prem=int(tw.meter_prem[mi]),
                     asset=tw.meter_ids[mi], cause=f"installed {int(tw.meter_installed[mi])}", meter=mi)
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
                     asset=tw.meter_ids[mi], cause=f"{tw.meter_tech[mi]} to AMI", meter=mi)
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
        streets = sorted({s for s in tw.premise_street if s})
        n = 0
        for t, _, d, j in contact.background_arrivals(run, "new_connection"):
            i = d * 1000 + j  # the request's key: its day and draw
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
                    aid = f"{net.edge_ids[e]}/{j + 1}"
                    self.main_seg[aid] = (u, e, 1.0 / k)
                    segs.append((aid, float(q[0]), float(q[1]), length / k / MAIN_SEGMENT_M, None, None))
        self.programme("main_replacement", segs, days)


# ---- the field engine (steps with the run's days) ------------------------------------------------------------------
WATCH = ("pole_replacement", "gas_leak_repair", "tree_trimming")  # overdue work that can fail
STORM_POLE = 10.0  # a pole overdue for replacement is ten times as likely to fail on a storm day


class FieldEngine:
    """The field crews inside the replay (``run.field``). Built before the first day with the planned work; each day
    ``step`` draws the day's incidents and the failures overdue maintenance causes, takes in the work the run and
    collections raised (VEE visits, corrective exchanges, disconnects, reconnects) and lets the business-day crews
    work. What a crew finishes changes the year from then on: a disconnect or removal switches the service off (no
    read, so no bill), a reconnect switches it back, an exchange registers a new meter, a battery keeps a module
    reading, a repair removes a defect before it fails."""

    def __init__(self, run: M2CRun):
        self.run = run
        b = self.b = _Build(run)
        b.engine = self
        b.moves()
        b.seals()
        b.meters()
        b.maintenance()
        b.construction()
        self.ops = b.ops
        self.crews = {c: {"crews": np.zeros(YEAR_DAYS), "availableMin": np.zeros(YEAR_DAYS),
                          "busyMin": np.zeros(YEAR_DAYS), "overtimeMin": np.zeros(YEAR_DAYS)} for c in CREWS}
        for d, fc in enumerate(b.fc):
            for c in CREWS:
                self.crews[c]["crews"][d] = crews_on(fc, c, b.n_prem)
        self.pending: list = []
        self.queues: dict[str, list] = {c: [] for c in DAY_CREWS}
        self.fixed_on: dict[tuple[str, int], float] = {}
        self.scan = 0
        self.watch: list[int] = []
        self.incidents: list[dict] = []
        self.storm = np.zeros(YEAR_DAYS, dtype=bool)
        self.failures: list[dict] = []  # {t, kind, orderId k, incident id}
        self.responded = False
        self._roads: _Roads | bool | None = None
        self.renewed: dict[tuple[str, int], float] = {}  # (utility, main edge) -> share renewed so far

    @property
    def orders(self) -> list[Order]:
        return self.b.orders

    # ---- work the run and collections raise -----------------------------------------------------------------------
    def vee_visit(self, case, t: float, crew: str) -> None:
        """A VEE truck roll (the run timed it): the meter technicians' time on its day."""
        run, b = self.run, self.b
        tw = run.town
        if not 0 <= t < YEAR_DAYS or _u(run, IDX["meter_investigation"], case.idx, int(t * 1440)) >= \
                b.w("meter_investigation", t).rate:
            return
        wt = b.w("meter_investigation", t)
        travel = b.fc[int(t)].travel_minutes
        b.add("meter_investigation", t, prem=int(tw.prem[case.r]), asset=tw.meter_ids[tw.meter_of[case.r]],
              cause=case.id, fixed=(t, t + (wt.minutes + travel) / 1440.0), crew_id=str(crew or ""),
              meter=int(tw.meter_of[case.r]))

    def exchanged(self, x) -> None:
        """A meter a crew swapped on a VEE visit or your order (the run timed it)."""
        run, b = self.run, self.b
        tw = run.town
        if not 0 <= x.t_reg < YEAR_DAYS or _u(run, IDX["corrective_exchange"], int(tw.meter_keys[x.meter]),
                                              int(x.t_reg * 1440)) >= b.w("corrective_exchange", x.t_reg).rate:
            return
        wt = b.w("corrective_exchange", x.t_reg)
        b.add("corrective_exchange", x.t_reg, prem=int(tw.meter_prem[x.meter]), asset=x.device,
              cause=x.case or x.order or x.previous, travel=False, fixed=(x.t_reg, x.t_reg + wt.minutes / 1440.0),
              crew_id=x.by, meter=int(x.meter))

    def request(self, kind: str, inv: dict, release: float, now: float) -> Order | None:
        """A disconnect or reconnect collections needs at ``release`` (asked at ``now``): an AMI electric meter with
        a remote switch is switched at ``release``; anything else goes to the meter technicians. None when the work
        is not done (its ``rate``) or the account has no meter."""
        run, b = self.run, self.b
        tw = run.town
        p = tw.premise_index.get((tw.accounts.get(inv["account"]) or {}).get("premiseId"), -1)
        mi = b.service_meter(p) if p >= 0 else -1
        if mi < 0 or not 0 <= release < YEAR_DAYS:
            return None
        n = str_key(inv["id"])
        if _u(run, IDX[kind], n, 0) >= b.w(kind, release).rate:
            return None
        remote = str(run.meter_tech_now[mi]) == "AMI" and tw.meter_commodity[mi] == "electric" and \
            _u(run, IDX["disconnect"], int(tw.meter_keys[mi]), 1) < b.fc[int(release)].remote_switch_share
        o = b.add(kind, min(now, release), release=release, prem=p, asset=tw.meter_ids[mi], cause=inv["id"],
                  remote=remote, meter=mi)
        if o is not None:
            o.inv = inv["id"]
        return o

    def cancel(self, o: Order, t: float, why: str) -> None:
        """Call off an order no crew has started (paid, held, or the asset failed first)."""
        if o.start == INF and not o.fixed and not o.remote:
            o.cancelled, o.outcome = True, why
            o.end = o.start = o.arrive = float(t)
            o.left = 0.0

    # ---- the day ------------------------------------------------------------------------------------------------
    def step(self, day: int) -> None:
        run, b = self.run, self.b
        if self.ops is not None:
            from utilsim.m2c import incidents as incs

            todays, storm = incs.draw_day(run, self.ops, day, keep=self._renewal(day))
            self.storm[day] = storm
            failed = self._failures(day, storm)
            for inc, background in [*((x, True) for x in todays), *((x, False) for x in failed)]:
                self.incidents.append(inc)
                b.repair(inc, len(self.incidents) - 1)
                run.incident_outage(inc, background)  # customers out: no use, dark AMI meters
        self._absorb(day)
        if add_bdays(day, 0) == day:
            self._work(day)
        self._absorb(day)

    def _absorb(self, day: int) -> None:
        """Orders raised since the last look: queued for their crew, or their timed work booked on its day."""
        orders, b = self.b.orders, self.b
        while self.scan < len(orders):
            o = orders[self.scan]
            self.scan += 1
            key = KEYS[o.type]
            if key in WATCH:
                self.watch.append(o.k)
            if o.remote:
                if KEYS[o.type] in ("disconnect", "reconnect"):
                    self._done(o)
                continue
            if o.fixed:
                if o.crew == "emergency":
                    continue
                sd = min(int(o.start), YEAR_DAYS - 1)
                fc = b.fc[sd]
                c = getattr(fc, f"crew_{o.crew}")
                mins = max(0.0, (o.end - o.start) * 1440.0)
                h = (o.start - sd) * 24.0
                shift_end = fc.shift_start_hour + fc.shift_hours
                reg = min(mins, (shift_end - h) * 60.0) if add_bdays(sd, 0) == sd and \
                    fc.shift_start_hour <= h < shift_end else 0.0
                o.regular, o.overtime = reg, mins - reg
                o.labour = (reg + (mins - reg) * c.overtime_factor) / 60.0 * c.cost_per_hour
                self.fixed_on[(o.crew, sd)] = self.fixed_on.get((o.crew, sd), 0.0) + reg
                self.crews[o.crew]["overtimeMin"][sd] += mins - reg
                continue
            if o.crew in DAY_CREWS:
                heapq.heappush(self.pending, (o.release, o.k))

    def roads(self, day: int) -> _Roads | None:
        """The street drive times when the crews route on ``day`` (None without routing or streets)."""
        if self.ops is None or not self.b.fc[min(max(day, 0), YEAR_DAYS - 1)].routing:
            return None
        if self._roads is None:
            try:
                self._roads = _Roads(self.run, self.ops)
            except (KeyError, IndexError, ValueError, StopIteration):  # a town without a usable street graph
                self._roads = False
        return self._roads or None

    def _work(self, day: int) -> None:
        """The business-day crews: timed work first, then released orders by priority and due date, overtime for
        customer work due today or overdue. With routing each crew leaves the depot in the morning, drives job to job
        (of the jobs as urgent and due within a day of the most pressing, the nearest next) and drives back."""
        orders, fc = self.b.orders, self.b.fc[day]
        shift_end = fc.shift_start_hour + fc.shift_hours
        while self.pending and self.pending[0][0] < day + shift_end / 24.0:
            _, k = heapq.heappop(self.pending)
            o = orders[k]
            heapq.heappush(self.queues[o.crew], (o.prio, o.due, o.release, o.k))
        roads = self.roads(day)
        for c in DAY_CREWS:
            if self.crews[c]["crews"][day] > 0:
                self._crew_day(day, c, roads)

    def _crew_day(self, day: int, c: str, roads: _Roads | None) -> None:
        """One crew type's business day."""
        orders, fc = self.b.orders, self.b.fc[day]
        shift_end = fc.shift_start_hour + fc.shift_hours
        n = float(self.crews[c]["crews"][day])
        slots = max(1, math.ceil(n))
        cc = getattr(fc, f"crew_{c}")
        cap = n * fc.shift_hours * 60.0
        self.crews[c]["availableMin"][day] = cap
        used = min(cap, self.fixed_on.get((c, day), 0.0))
        q = self.queues[c]
        t0 = day + fc.shift_start_hour / 24.0
        pos = [roads.depot] * slots if roads else []
        last: list[Order | None] = [None] * slots
        started = 0

        def pick(slot: int, due_max: float) -> None:
            """Bring the nearest of the jobs as urgent as the queue's head, and due within a day of it, to the
            front (the crew's next stop)."""
            p0, d0 = q[0][0], q[0][1]
            lim = min(d0 + 1.0, due_max) + 1e-9
            best, bi = INF, 0
            for i, e in enumerate(q):
                if e[0] != p0 or e[1] > lim:
                    continue
                x = orders[e[3]]
                if x.cancelled or x.start != INF:
                    continue
                spot = roads.spot(x)
                d = roads.minutes(pos[slot], spot) if spot is not None else INF
                if d < best:
                    best, bi = d, i
            if bi:
                e = q[bi]
                q[bi] = q[-1]
                q.pop()
                heapq.heapify(q)
                heapq.heappush(q, (p0, d0, -INF, e[3]))

        def begin(o: Order, at: float) -> None:
            nonlocal started
            slot = started % slots
            started += 1
            o.start = max(o.release, at)
            o.crew_id = f"{CREW_CODE[c]}-{slot + 1}"
            drive = INF
            if roads is not None:
                spot = roads.spot(o)
                if spot is not None:
                    drive = roads.minutes(pos[slot], spot)
                    if math.isfinite(drive):
                        pos[slot] = spot
                last[slot] = o
            if math.isfinite(drive):
                o.travel = drive + fc.stop_minutes
                o.left = o.minutes + o.travel
                o.arrive = o.start + drive / 1440.0
            else:
                o.arrive = o.start + o.travel / 2880.0

        while q and used < cap - 1e-9:
            o = orders[q[0][3]]
            if o.cancelled:
                heapq.heappop(q)
                continue
            if o.start == INF:
                if roads is not None:
                    pick(started % slots, INF)
                    o = orders[q[0][3]]
                begin(o, t0 + used / n / 1440.0)
            take = min(o.left, cap - used)
            used += take
            o.left -= take
            o.regular += take
            o.labour += take / 60.0 * cc.cost_per_hour
            if o.left > 1e-9:
                break
            heapq.heappop(q)
            o.end = max(o.arrive, t0 + used / n / 1440.0)
            self._done(o)
        ot_cap, ot = n * fc.overtime_max_hours * 60.0, 0.0
        while q and ot < ot_cap - 1e-9:
            o = orders[q[0][3]]
            if o.cancelled:
                heapq.heappop(q)
                continue
            if o.prio > 2 or o.due > day + 1:
                break
            if o.start == INF:
                if roads is not None:
                    pick(started % slots, day + 1.0)
                    o = orders[q[0][3]]
                begin(o, day + shift_end / 24.0)
            take = min(o.left, ot_cap - ot)
            ot += take
            o.left -= take
            o.overtime += take
            o.labour += take / 60.0 * cc.cost_per_hour * cc.overtime_factor
            if o.left > 1e-9:
                break
            heapq.heappop(q)
            o.end = max(o.arrive, day + shift_end / 24.0 + ot / n / 1440.0)
            self._done(o)
        for slot, o in enumerate(last):  # each crew drives back to the depot
            if o is None:
                continue
            back = roads.minutes(pos[slot], roads.depot)
            if not math.isfinite(back):
                continue
            reg = min(back, max(0.0, cap - used))
            o.travel += back
            o.regular += reg
            o.overtime += back - reg
            o.labour += (reg + (back - reg) * cc.overtime_factor) / 60.0 * cc.cost_per_hour
            used += reg
            ot += back - reg
        self.crews[c]["busyMin"][day] += used
        self.crews[c]["overtimeMin"][day] += ot

    # ---- what a finished order changes ----------------------------------------------------------------------------
    def _done(self, o: Order) -> None:
        run, b = self.run, self.b
        tw = run.town
        key = KEYS[o.type]
        if key in ("disconnect", "reconnect"):
            col = run.books.collections
            inv = col.invoice.get(o.inv)
            if inv is not None:
                col._push(col._account(inv["account"]), o.end, "field_done", inv, key, o.k)
        elif key == "removal" and o.prem >= 0:
            rows = np.flatnonzero(np.isin(tw.meter_of, b.prem_meters.get(o.prem, [])))
            run.service_off(rows, o.end, "removed")
        elif key in ("seal_exchange", "water_meter_replacement", "ami_conversion") and o.meter >= 0:
            x = run.exchange_meter(o.meter, o.end, by=o.crew_id or "MT", note=TYPES[o.type][1],
                                   tech="AMI" if key == "ami_conversion" else None)
            if x is None:
                o.outcome = "skipped: the meter was off, already read on a new register, or not the registered meter"
        elif key == "main_replacement" and o.asset in b.main_seg:
            u, e, share = b.main_seg[o.asset]
            self.renewed[(u, e)] = min(1.0, self.renewed.get((u, e), 0.0) + share)
        elif key == "ami_battery" and o.meter >= 0:
            if o.end < run.battery_dead[o.meter]:
                run.battery_dead[o.meter] = INF  # replaced before it died
            else:
                run.battery_new[o.meter] = o.end
        if o.then:
            b.finding(o)

    def _renewal(self, day: int):
        """A filter for the day's drawn breaks and leaks: one on a main the construction crews renewed (in part)
        happens at ``renewed_main_break_factor`` of the old main's rate."""
        if not self.renewed:
            return None
        f = self.b.fc[day].renewed_main_break_factor

        def keep(item: dict, n: int) -> bool:
            share = self.renewed.get((item.get("utility"), item.get("edge")), 0.0) \
                if item.get("kind") in ("water_main_break", "gas_leak") else 0.0
            return not share or _u(self.run, P_RENEW, day, n) >= share * (1.0 - f)
        return keep

    # ---- overdue maintenance fails ----------------------------------------------------------------------------------
    def _failures(self, day: int, storm: bool) -> list[dict]:
        """Overdue work that fails today: a pole found needing replacement, a span overdue for trimming (storm
        days), a surveyed leak overdue for repair. Each failure is an incident (an outage, or a public gas leak)."""
        from utilsim.m2c import incidents as incs

        run, b, orders = self.run, self.b, self.b.orders
        fc = b.fc[day]
        out, keep = [], []
        for k in self.watch:
            o = orders[k]
            if o.cancelled or o.end <= day:
                continue
            keep.append(k)
            if o.due > day:
                continue
            key = KEYS[o.type]
            if key == "pole_replacement":
                p = fc.deferred_pole_failures / 365.0 * (STORM_POLE if storm else 1.0)
                kind = "pole_failure"
            elif key == "gas_leak_repair":
                p, kind = fc.deferred_leak_escalation / 365.0, "gas_leak_escalated"
            else:
                p, kind = (fc.deferred_tree_faults if storm else 0.0), "tree_contact"
            if p <= 0 or _u(run, P_FAIL, o.k, day) >= p:
                continue
            edge = self._edge(o)
            t0 = day + 0.05 + 0.9 * _u(run, P_FAIL, o.k, day, 1)
            ident = f"INC-{date_of(day).strftime('%Y%m%d')}-F{len(self.failures) + 1}"
            out.append(incs.consequence(run, self.ops, kind, t0, o.x, o.z, edge=edge, ident=ident, storm=storm))
            self.failures.append({"t": t0, "kind": kind, "order": o.k, "incident": ident})
            if key != "tree_trimming":  # the emergency repair replaces the pole or fixes the leak
                self.cancel(o, t0, f"failed first ({ident})")
        self.watch = keep
        return out

    def _edge(self, o: Order) -> int | None:
        """The electric span a pole stands on, or the span itself (tree trimming)."""
        el = self.ops.nets["electric"]
        if KEYS[o.type] == "tree_trimming":
            return el.edge_index.get(o.asset)
        if KEYS[o.type] == "pole_replacement":
            if not hasattr(self, "_pole_edge"):
                self._pole_edge = {q["id"]: el.edge_index.get(q.get("edgeId")) for q in el.equipment
                                   if q["kind"] == "pole"}
            return self._pole_edge.get(o.asset)
        return None

    def finish(self) -> None:
        """After the last day: the year's incidents (background and failures) for the contact centre."""
        self.incidents.sort(key=lambda r: r["t"])
        self.run.__dict__["_year_incidents"] = self.incidents

    # ---- after the year: the on-call responders ---------------------------------------------------------------------
    def respond(self) -> None:
        """Gas odour and no-supply calls (the contact centre's contacts) for the on-call responders: around the
        clock, first come first served, several crews at once; after hours a responder first gets on the road."""
        if self.responded:
            return
        self.responded = True
        b = self.b
        start = len(b.orders)
        b.responses()
        crews = self.crews["emergency"]
        em = sorted(b.orders[start:], key=lambda o: (o.created, o.k))
        free = np.zeros(max(1, int(crews["crews"].max())))
        for o in em:
            d = min(int(o.created), YEAR_DAYS - 1)
            fc = b.fc[d]
            n = int(crews["crews"][d])
            if n <= 0:
                continue
            i = int(np.argmin(free[:n]))
            o.start = max(o.created, float(free[i]))
            sd = min(int(o.start), YEAR_DAYS - 1)
            h = (o.start - sd) * 24.0
            in_shift = add_bdays(sd, 0) == sd and fc.shift_start_hour <= h < fc.shift_start_hour + fc.shift_hours
            callout = 0.0 if in_shift else fc.callout_minutes
            roads, drive = self.roads(d), INF
            if roads is not None and (spot := roads.spot(o)) is not None:
                drive = roads.minutes(roads.depot, spot)
            if math.isfinite(drive):  # from the depot and back
                o.travel = 2.0 * drive + fc.stop_minutes
                o.arrive = o.start + (drive + callout) / 1440.0
                o.end = o.arrive + (fc.stop_minutes + o.minutes) / 1440.0
                free[i] = o.end + drive / 1440.0
            else:
                o.arrive = o.start + (o.travel / 2.0 + callout) / 1440.0
                o.end = o.arrive + o.minutes / 1440.0
                free[i] = o.end + o.travel / 2880.0
            o.crew_id = f"ER-{i + 1}"
            mins = o.minutes + o.travel
            cost = fc.crew_emergency.cost_per_hour
            if in_shift:
                o.regular, o.labour = mins, mins / 60.0 * cost
            else:
                o.overtime, o.labour = mins, mins / 60.0 * cost * fc.crew_emergency.overtime_factor
            crews["busyMin"][sd] += mins
            o.left = 0.0
        for d in range(YEAR_DAYS):
            crews["availableMin"][d] = crews["crews"][d] * 1440.0


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
            "cancelled": np.array([x.cancelled for x in o], dtype=bool),
            # when an order meets its due date: on site for an emergency, finished for everything else
            "met": np.array([x.arrive if KEYS[x.type] in EMERGENCY else x.end for x in o], dtype=float)}


def fieldwork(run: M2CRun) -> FieldWork:
    """The year's field work: the orders the crews worked during the replay (``run.field``) and, after the year, the
    gas odour and no-supply calls the on-call responders attended (cached per run)."""
    hit = run.__dict__.get("_fieldwork")
    if hit is not None:
        return hit
    eng = run.field if getattr(run, "field", None) is not None else None
    if eng is None:  # a run replayed before field work joined the replay
        raise ValueError("this run has no field engine")
    eng.respond()
    b = eng.b
    orders = sorted(b.orders, key=lambda o: (o.created, o.release, o.k))
    for n, o in enumerate(orders, start=1):
        o.id = f"WO-{n:06d}"
    by_k = {o.k: o for o in orders}
    for o in orders:  # a finding's repair names the inspection (or new service) that raised it
        if o.parent >= 0:
            p = by_k[o.parent]
            o.cause = f"{p.id} {TYPES[p.type][1].lower()}"
    fw = FieldWork(orders=orders, crews=eng.crews, plan=b.plan, premises=b.n_prem, notes=b.notes)
    fw.failures = [{**f, "orderId": by_k[f["order"]].id, "work": TYPES[by_k[f["order"]].type][1]}
                   for f in eng.failures]
    fw.cols = _columns(fw)
    run.__dict__["_fieldwork"] = fw
    return fw


# ---- views --------------------------------------------------------------------------------------------------------
def status_at(o: Order, T: float) -> str | None:
    """An order's status at ``T`` (None before it is created)."""
    if o.created > T:
        return None
    if o.cancelled and o.end <= T:
        return "cancelled"
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
    gone = k & c["cancelled"] & (c["end"] >= lo) & (c["end"] <= T)
    done = k & ~c["cancelled"] & (c["end"] >= lo) & (c["end"] <= T)
    live = k & (c["created"] <= T) & (c["end"] > T)
    released = live & (c["release"] <= T)
    overdue = released & (c["due"] < T)
    ontime = done & (c["met"] <= c["due"] + 1e-9)
    em = done & np.isin(c["type"], [IDX[x] for x in EMERGENCY])
    resp = (c["arrive"][em] - c["created"][em]) * 1440.0
    lab, mat = float(c["labour"][done].sum()), float(c["materials"][done].sum())
    n_done = int(done.sum())
    return {"created": int(made.sum()), "completed": n_done, "cancelled": int(gone.sum()), "open": int(released.sum()),
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


def effects(run: M2CRun, fw: FieldWork, T: float, lo: float = 0.0) -> dict:
    """What the field work did to the rest of the year in [lo, T]: reads not taken because the service was off,
    disconnections and reconnections, removals, meters exchanged and converted, reads a dead module battery missed,
    meters under-registering at T, and overdue maintenance that failed."""
    from utilsim.m2c.run import BATTERY_REASON, OFF

    rt = run.read_t[:, 1:]
    win = (rt >= lo) & (rt <= T)
    c = fw.cols
    done = ~c["cancelled"] & (c["end"] >= lo) & (c["end"] <= T)

    def n(*keys: str) -> int:
        return int((done & np.isin(c["type"], [IDX[k] for k in keys])).sum())

    disc = [i["disc"] for i in run.books.invoices if i.get("disc")]
    m = np.arange(len(run.drift_k))
    fails = [f for f in fw.failures if lo <= f["t"] <= T]
    by_kind: dict[str, int] = {}
    for f in fails:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
    return {"readsOff": int((win & (run.status[:, 1:] == OFF)).sum()),
            "disconnected": sum(1 for d in disc if d.get("at") is not None and lo <= d["at"] <= T),
            "reconnected": sum(1 for d in disc if d.get("reconnected") is not None and lo <= d["reconnected"] <= T),
            "remote": int((done & c["remote"]).sum()), "removed": n("removal"),
            "exchanged": n("seal_exchange", "water_meter_replacement", "ami_conversion"),
            "convertedToAmi": n("ami_conversion"), "batteries": n("ami_battery"),
            "deadBatteryMisses": int((win & (run.reason[:, 1:] == BATTERY_REASON)).sum()),
            "driftingMeters": int(((run.drift_k > 0) & (run.drift_t <= T) & (run.drift_end > T)).sum()) if len(m) else 0,
            "failures": len(fails), "failuresByKind": by_kind}


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
        s["effects"] = effects(run, fw, Tm, float(start))
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
    fails = [{**f, "date": date_of(int(f["t"])).isoformat(), "kind": f["kind"]} for f in fw.failures if f["t"] <= T]
    return {"schemaVersion": FIELD_VERSION, "simulationId": run.simulation_id, "asOf": date_of(day).isoformat(),
            "kpis": kpis, "effects": effects(run, fw, T), "failures": [
                {"date": f["date"], "kind": f["kind"], "incidentId": f["incident"], "orderId": f["orderId"],
                 "work": f["work"]} for f in fails[-50:]],
            "programs": programs, "types": types, "crews": crews, "plan": plan, "daily": series,
            "labels": {"programs": PROGRAMS, "crews": CREWS}, "notes": notes}
