"""Field work over the year (utilsim/m2c/fieldwork.py): orders follow what happens in the year, the crews work them
by priority within their capacity inside the replay, what they do changes the year (a disconnected or removed meter is
not read or billed, an exchange registers a new meter, maintenance left overdue fails), the settings move the work the
way their explanations say, episodes apply from their day, and the views and tables stay bounded."""

from __future__ import annotations

import numpy as np
import orjson
import pytest
from fastapi.testclient import TestClient

from api._m2c import RunRequest, _master, _town, run_for
from api.index import app
from utilsim.m2c import contact, tables, trend, views
from utilsim.m2c import fieldwork as fwk
from utilsim.m2c.run import BATTERY_REASON, OFF, YEAR_DAYS, M2CRun, parse_day

TOWN = "small_town"
DAY = "2026-12-31"
T_END = YEAR_DAYS - 1e-6


def _run(settings=None, episodes=None, town=TOWN, seed=None):
    return run_for(RunRequest(town=town, settings=settings, episodes=episodes or [], seed=seed))


def _of(fw, key):
    return [o for o in fw.orders if o.type == fwk.IDX[key]]


@pytest.fixture(scope="module")
def base():
    run = _run()
    return run, fwk.fieldwork(run)


def test_orders_are_deterministic_ordered_and_consistent(base):
    run, fw = base
    from api._m2c import _ops_town

    a, b = (fwk.fieldwork(M2CRun(_town("village"), ops_factory=lambda: _ops_town("village"))) for _ in range(2))
    assert [(o.id, o.type, o.created, o.end) for o in a.orders] == [(o.id, o.type, o.created, o.end) for o in b.orders]
    ids = [o.id for o in fw.orders]
    assert len(set(ids)) == len(ids) and len(ids) > 500
    created = [o.created for o in fw.orders]
    assert created == sorted(created) and min(created) >= 0 and max(created) < YEAR_DAYS
    progs = {fwk.TYPES[o.type][2] for o in fw.orders}
    assert progs == set(fwk.PROGRAMS)  # every programme has work in a default year
    for o in fw.orders:
        assert o.release >= o.created - 1e-9 and o.due >= o.release - 1e-9
        if o.end < float("inf"):
            assert o.start >= o.created - 1e-9 and o.end >= o.start - 1e-9 and o.arrive >= o.start - 1e-9
            if not o.fixed and not o.remote and o.crew != "emergency":
                assert o.start >= o.release - 1e-9
        assert o.labour >= 0 and o.materials >= 0 and o.regular >= 0 and o.overtime >= 0


def test_orders_point_at_what_raised_them(base):
    run, fw = base
    cx = contact.contacts(run)
    incidents = {x["id"]: x for x in cx.incidents}
    repairs = _of(fw, "outage_repair")
    assert len(repairs) == len(incidents) and {o.asset for o in repairs} == set(incidents)
    leaks = {x["id"] for x in cx.incidents if x["utility"] == "gas"}
    odour = _of(fw, "gas_odour")
    assert {o.cause for o in odour if o.cause.startswith("INC-")} <= leaks
    rolls = sum(1 for c in run.cases for t, kind, _, _ in c.events if kind == "TRUCK_ROLL" and t < YEAR_DAYS)
    assert len(_of(fw, "meter_investigation")) == rolls > 0
    assert all(o.fixed for o in _of(fw, "meter_investigation"))
    swaps = [x for x in run.installs if x.physical and not x.planned and x.t_reg < YEAR_DAYS]
    assert len(_of(fw, "corrective_exchange")) == len(swaps)
    planned = [x for x in run.installs if x.planned]  # seal and age exchanges registered as new meters
    done = [o for o in _of(fw, "seal_exchange") + _of(fw, "water_meter_replacement") if o.end < YEAR_DAYS
            and not o.outcome and not o.cancelled]
    assert len(planned) == len(done) > 100
    # An exchange on a meter's read day, after the overnight read and before the evening batch: that read is diffed on
    # the old meter and the next one on the new meter, so neither bills the old register's whole dial as use.
    same_day = [(r, x.period[r]) for x in planned for r in x.period
                if 2 <= x.period[r] < 13 and run.town.read_day[r, x.period[r] - 1] == int(x.t)]
    assert same_day
    for r, m in same_day:
        for j in (m - 1, m):
            if not np.isnan(run.cons[r, j]):
                assert 0 <= run.cons[r, j] < 5 * run.expected[r, j] + 50, (r, j)
    # Move visits only at premises with a meter that cannot be read remotely.
    tw = run.town
    for o in _of(fw, "move_in") + _of(fw, "move_out"):
        techs = {tw.meter_tech[m] for m in range(len(tw.meter_ids)) if tw.meter_prem[m] == o.prem}
        assert techs - {"AMI"}
    # Seal exchanges: the lots whose seal ends this year (install year = 2026 - seal years).
    seal = _of(fw, "seal_exchange")
    assert seal and all(int(tw.meter_installed[tw.meter_ids.index(o.asset)]) == 2026 - run.cfg.field.seal_years_electric
                        for o in seal[:50])
    # Inspections raise their repairs; finished new services raise meter sets.
    sets, built = _of(fw, "meter_set"), {o.id for o in _of(fw, "new_set") if o.end < YEAR_DAYS}
    assert len(sets) <= len(built) and {o.cause.split()[0] for o in sets} <= built
    assert all(o.cause.startswith("WO-") for o in _of(fw, "pole_replacement"))
    # No disconnections approved by default: no disconnects, and the summary says why.
    assert not _of(fw, "disconnect") and fwk.summary(run, DAY)["notes"]


def test_disconnections_happen_when_the_crew_does_them_and_stop_reads_and_bills():
    run = _run({"billing": {"disconnect_rule_share": 1.0}})
    fw = fwk.fieldwork(run)
    by_k = {o.k: o for o in fw.orders}
    disc = [inv["disc"] for inv in run.books.invoices if (inv.get("disc") or {}).get("at") is not None]
    assert len(disc) > 50
    for d in disc:  # each disconnection is the moment its crew (or remote switch) finished
        o = by_k[d["orders"]["disconnect"]]
        assert o.end == pytest.approx(d["at"]) and o.end >= d["scheduled"] - 1e-9
    remote = [o for o in _of(fw, "disconnect") if o.remote]
    assert remote and all(o.crew == "remote" and o.labour == 0 for o in remote)
    assert any(not o.remote for o in _of(fw, "disconnect")) and _of(fw, "reconnect")
    # No read while the service is off, so no bill for those months; the next bill starts from the last read.
    tw, bk = run.town, run.books
    off = np.argwhere(run.status == OFF)
    assert len(off) > 20
    for r, m in off[:200].tolist():
        assert np.isnan(run.obs[r, m]) and bk.doc_of[tw.inst_of[r], m] < 0
        assert run.off_reason(r, float(run.read_t[r, m])) in ("disconnected", "removed")
    gaps = [d for d in bk.docs if d["from"] != d["month"] - 1]
    assert gaps and all(run.status[bk.main[d["inst"]], d["month"] - 1] == OFF for d in gaps)
    # Nothing flows while off: the bill after the gap is below the normal use of its period.
    d = gaps[0]
    r = int(bk.main[d["inst"]])
    normal = tw.true_advance(np.array([r, r]), tw.read_day[r, [d["from"], d["month"]]], tw.hour[[r, r]])
    assert d["qImp"] < 0.95 * (normal[1] - normal[0])
    plain = fwk.fieldwork(_run({"billing": {"disconnect_rule_share": 1.0}, "field": {"remote_switch_share": 0.0}}))
    assert not [o for o in _of(plain, "disconnect") if o.remote]


def test_crews_and_rates_move_the_work_the_way_they_say(base):
    run, fw = base
    s = fwk.summary(run, DAY)
    short = _run({"field": {"crew_meter": {"per_1000_premises": 0.08}, "overtime_max_hours": 0}})
    s2 = fwk.summary(short, DAY)
    meter = lambda x: next(p for p in x["programs"] if p["id"] == "meter")  # noqa: E731
    assert meter(s2)["open"] + meter(s2)["overdue"] > meter(s)["open"] + meter(s)["overdue"]
    assert meter(s2)["onTimePct"] < meter(s)["onTimePct"]
    crew = lambda x: next(c for c in x["crews"] if c["id"] == "meter")  # noqa: E731
    assert crew(s2)["utilisationPct"] > crew(s)["utilisationPct"]
    none = fwk.fieldwork(_run({"field": {"pole_inspection": {"rate": 0}, "ami_conversion": {"rate": 0.5},
                                         "seal_lot_pass_rate": 0.0}}))
    assert not _of(none, "pole_inspection") and not _of(none, "pole_replacement")
    assert len(_of(none, "ami_conversion")) > 100
    assert len(_of(none, "seal_exchange")) > len(_of(fw, "seal_exchange"))  # failed lots: every meter exchanged
    assert any(o.cause.endswith("failed") for o in _of(none, "seal_exchange"))


def test_deferred_maintenance_fails_and_shows_in_reads_and_bills(base):
    run, fw = base
    short = _run({"field": {"crew_meter": {"per_1000_premises": 0.1}, "crew_electric": {"per_1000_premises": 0.03},
                            "crew_gas": {"per_1000_premises": 0.02}, "deferred_pole_failures": 40,
                            "deferred_tree_faults": 0.5, "deferred_leak_escalation": 40}})
    fs = fwk.fieldwork(short)
    e0, e1 = fwk.summary(run, DAY)["effects"], fwk.summary(short, DAY)["effects"]
    # Batteries not replaced by their anniversary die and miss reads; old and failed-lot meters keep drifting.
    assert e1["deadBatteryMisses"] > e0["deadBatteryMisses"] and e1["deadBatteryMisses"] > 50
    assert int((short.reason == BATTERY_REASON).sum()) == e1["deadBatteryMisses"]
    assert e1["driftingMeters"] > e0["driftingMeters"]
    # Overdue poles, spans and leaks fail: incidents with customers out and their repairs.
    assert e1["failures"] > 0 and len(fs.failures) == e1["failures"]
    incs = {x["id"]: x for x in contact.contacts(short).incidents}
    for f in fs.failures:
        assert f["incident"] in incs and incs[f["incident"]]["kind"] == f["kind"]
    assert {o.asset for o in _of(fs, "outage_repair")} >= {f["incident"] for f in fs.failures}
    # Each failure cuts its customers' supply in the replay: their use stops while they are out.
    out = [o for o in short.outage_log if o.get("incident") in {f["incident"] for f in fs.failures}]
    assert out and all(len(o["prem"]) and o["t1"] > o["t0"] for o in out)
    rows = np.concatenate([o["rows"] for o in out])
    rows = rows[short.town.direction[rows] == "import"]
    assert short._outage_loss(rows, np.full(len(rows), float(YEAR_DAYS)))[0].sum() > 0
    # So do the year's background incidents, in the default run too: the reliability KPIs count them.
    assert any(o.get("incident") for o in run.outage_log) and views.reliability(run, float(YEAR_DAYS))
    # Less revenue against the truth when meters drift longer.
    gap = lambda r: sum(d["total"] - d["truthTotal"] for d in r.books.docs if d["reversed"] is None)  # noqa: E731
    assert gap(short) < gap(run)
    # A converted meter is read as AMI from its exchange.
    conv = _run({"field": {"ami_conversion": {"rate": 0.6}}})
    moved = np.flatnonzero(conv.meter_tech_now != conv.town.meter_tech)
    assert len(moved) > 100 and set(conv.meter_tech_now[moved].tolist()) == {"AMI"}


def test_an_episode_applies_from_its_day():
    day = "2026-07-01"
    run = _run(episodes=[{"title": "No meter technicians", "from": day,
                          "settings": {"field": {"crew_meter": {"per_1000_premises": 0}}}}])
    fw = fwk.fieldwork(run)
    d0 = parse_day(day, 0)
    queued = [o for o in fw.orders if o.crew == "meter" and not o.fixed and not o.remote]
    assert any(o.end < d0 for o in queued)
    assert not [o for o in queued if d0 <= o.start < YEAR_DAYS]  # nobody starts meter work from that day
    assert [o for o in _of(fw, "meter_investigation") if o.start >= d0]  # VEE visits still happen (the run times them)
    base = fwk.fieldwork(_run())
    before = [o.id for o in base.orders if o.end < d0 and o.crew == "meter"]
    assert before == [o.id for o in fw.orders if o.end < d0 and o.crew == "meter"]


def test_views_trend_and_tables_are_bounded(base):
    run, fw = base
    s = fwk.summary(run, "2026-08-05")
    assert s["schemaVersion"] == fwk.FIELD_VERSION and s["asOf"] == "2026-08-05"
    assert sum(p["created"] for p in s["programs"]) == s["kpis"]["created"]
    assert sum(t["created"] for t in s["types"]) == s["kpis"]["created"]
    assert len(s["daily"]) == 60 and len(orjson.dumps(s)) < 200_000
    assert {c["id"] for c in s["crews"]} == set(fwk.CREWS) and {p["id"] for p in s["plan"]} == set(fwk.PLANNED)
    months = trend.trend(run, "2026-08-05")["months"]
    assert all(m["field"] is None for m in months[8:])
    assert sum(m["field"]["created"] for m in months[:8]) == s["kpis"]["created"]
    assert sum(m["field"]["completed"] for m in months[:8]) == s["kpis"]["completed"]
    master = _master(TOWN)
    for name in ("workOrders", "crewDays", "maintenancePlan"):
        page = tables.page(run, master, name, as_of="2026-08-05", page_size=tables.PAGE_MAX)
        assert page["rowsInTable"] > 0 and len(orjson.dumps(page)) < 4_500_000, name
    orders = tables.page(run, master, "workOrders", as_of="2026-08-05", page_size=5)
    assert orders["rowsInTable"] == s["kpis"]["created"]
    days = tables.page(run, master, "crewDays", as_of="2026-08-05", page_size=5)
    assert days["rowsInTable"] == (parse_day("2026-08-05", 0) + 1) * len(fwk.CREWS)
    full = fwk.summary(run, DAY)
    assert full["kpis"]["completed"] > 0.9 * full["kpis"]["created"]
    assert 0 < full["kpis"]["utilisationPct"] < 1 and full["kpis"]["cost"]["total"] > 0
    assert full["kpis"]["responseMin"] is not None and full["kpis"]["onTimePct"] > 0.5


def test_without_networks_field_work_has_no_assets():
    run = M2CRun(_town(TOWN), seed="NO-NETWORK-FIELD")  # no ops_factory: a town without networks
    fw = fwk.fieldwork(run)
    assert not _of(fw, "pole_inspection") and not _of(fw, "outage_repair") and not _of(fw, "main_replacement")
    assert _of(fw, "seal_exchange") and fwk.summary(run, DAY)["notes"]


def test_hosted_fieldwork_endpoint():
    client = TestClient(app)
    r = client.post("/api/m2c/fieldwork", json={"town": "village", "asOf": "2026-06-30"})
    assert r.status_code == 200
    body = r.json()
    assert body["schemaVersion"] == fwk.FIELD_VERSION and body["kpis"]["created"] > 0
    bad = client.post("/api/m2c/fieldwork", json={"town": "village", "settings": {"field": {"shift_hours": 40}}})
    assert bad.status_code == 422
    sch = client.get("/api/m2c/settings").json()["schema"]["properties"]["field"]
    assert {"crew_meter", "seal_lot_pass_rate", "new_set"} <= set(sch["properties"])


def test_crews_drive_the_streets_from_the_depot(base):
    run, fw = base
    from utilsim.ops.routing import Router

    eng = run.field
    roads = eng.roads(100)
    assert roads is not None
    # Drive times are the operations router's fastest routes, the same both ways.
    o = run.cfg_at(0).field
    spots = [roads.spot(x) for x in fw.orders[:400] if roads.spot(x) is not None][:12]
    ops = eng.ops.ops
    router = Router(eng.ops.roads, (ops["speed_kmh_arterial"], ops["speed_kmh_collector"], ops["speed_kmh_local"]))
    for a, b in zip(spots, spots[1:], strict=False):
        m = roads.minutes(a, b)
        assert m == pytest.approx(roads.minutes(b, a), abs=1e-6)
        assert m == pytest.approx(router.route(a, b).seconds / 60.0, rel=0.02, abs=0.05)
    assert roads.minutes(spots[0], spots[0]) == 0.0
    # Every routed visit carries its drive and the stop; the day's last job also the drive back to the depot.
    day = [x for x in fw.orders if x.crew in fwk.DAY_CREWS and not x.fixed and not x.remote and not x.cancelled
           and x.end < YEAR_DAYS]
    assert len(day) > 200 and all(x.travel >= o.stop_minutes - 1e-9 for x in day)
    assert len({round(x.travel, 3) for x in day}) > 50  # not one flat time
    assert all(x.arrive >= x.start for x in day)
    # On-call responders drive from the depot and back: response is the drive (plus the call-out after hours).
    em = [x for x in fw.orders if fwk.KEYS[x.type] in fwk.EMERGENCY and x.end < YEAR_DAYS]
    assert em
    for x in em[:30]:
        drive = roads.minutes(roads.depot, roads.spot(x))
        assert x.travel == pytest.approx(2 * drive + o.stop_minutes)
        assert (x.arrive - x.start) * 1440 == pytest.approx(drive, abs=1e-6) or \
            (x.arrive - x.start) * 1440 == pytest.approx(drive + o.callout_minutes, abs=1e-6)
    # Without routing every visit adds the flat travel time again.
    flat = fwk.fieldwork(_run({"field": {"routing": False}}))
    fday = [x for x in flat.orders if x.crew in fwk.DAY_CREWS and not x.fixed and not x.remote and not x.cancelled
            and x.end < YEAR_DAYS]
    assert fday and {x.travel for x in fday} == {o.travel_minutes}


def test_a_meter_is_read_when_its_service_goes_off():
    run = _run({"billing": {"disconnect_rule_share": 1.0}})
    tw, bk = run.town, run.books
    final = np.argwhere(run.final)
    assert len(final) > 10
    for r, m in final.tolist():
        t = float(run.final_t[r, m])
        span = run.off_span(r, t)
        assert span is not None and span[0] == t  # read the moment the service went off
        assert t <= run.read_t[r, m] and run.off_span(r, float(run.read_t[r, m])) is span  # off at its schedule
        assert not np.isnan(run.obs[r, m]) and run.status[r, m] != OFF
        assert views.final_reason(run, r, m) in ("disconnection", "device_removal")
        for j in range(m + 1, 13):  # later reads in the same span are not taken
            if span[0] <= run.read_t[r, j] < span[1]:
                assert run.status[r, j] == OFF and np.isnan(run.obs[r, j])
    # The final read's period is billed: the bill runs to the disconnection.
    billed = [(r, m) for r, m in final.tolist() if bk.doc_of[tw.inst_of[r], m] >= 0]
    assert len(billed) >= 0.8 * len(final)
    rows = tables.build(run, _master(TOWN), "reads", DAY)[1]
    col = [c.key for c in rows.cols].index("readType")
    assert "final" in rows.data[col]


def test_renewed_mains_break_less():
    hot = {"outages": {"incident_factor": 30}}
    renew = {"main_replacement": {"rate": 1.0}}

    def mains(run):
        fwk.fieldwork(run)
        return [x["id"] for x in contact.contacts(run).incidents if x["kind"] in ("water_main_break", "gas_leak")]

    old = mains(_run({**hot, "field": {**renew, "renewed_main_break_factor": 1.0}}))
    none = mains(_run({**hot, "field": {"main_replacement": {"rate": 0.0}}}))
    new = mains(_run({**hot, "field": {**renew, "renewed_main_break_factor": 0.0}}))
    assert old == none  # a renewed main as likely to break as the old one: the same year
    assert set(new) < set(old)  # renewed mains drop some breaks and leaks; every other keeps its id
    run = _run({**hot, "field": {**renew, "renewed_main_break_factor": 0.0}})
    eng = (fwk.fieldwork(run), run.field)[1]
    assert eng.renewed and all(0 < v <= 1.0 for v in eng.renewed.values())
