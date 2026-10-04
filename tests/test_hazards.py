"""Operations run settings from the town's config (crews, readers, shift, targets, voltage floor, incident rates) and
background incidents: seeded, rare at normal rates, worked like a user's break, and fed to meter-to-cash."""

from __future__ import annotations

import gzip
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import orjson
import pytest
from fastapi.testclient import TestClient

from utilsim.ops.hazards import draw, storm_probability
from utilsim.ops.opstown import OpsTown
from utilsim.ops.timeline import DEFAULTS, TOWN_SETTINGS, Run, run_defaults

ROOT = Path(__file__).resolve().parents[1]
ONLY = {"waterMainBreaksPer100km": 0, "gasMainLeaksPer100km": 0, "gasServiceLeaksPer1000": 0,
        "transformerFailuresPer1000": 0, "overheadFaultsPerKmStormDay": 0, "collectorOutagesPerYear": 0}


@pytest.fixture(scope="module")
def small_town() -> OpsTown:
    index = orjson.loads((ROOT / "packs" / "index.json").read_bytes())
    entry = next(t for t in index["towns"] if t["preset"] == "small_town")
    return OpsTown(orjson.loads(gzip.decompress((ROOT / "packs" / entry["files"]["snapshot"]["path"]).read_bytes())))


def year(ops: OpsTown, settings: dict, seed: str) -> list[tuple[date, list[dict]]]:
    out, d = [], date(2026, 1, 1)
    while d.year == 2026:
        out.append((d, draw(ops, d, settings, seed)[0]))
        d += timedelta(days=1)
    return out


def test_run_settings_default_to_the_towns_config(small_town):
    cfg, d = small_town.sim_config, small_town.run_defaults
    o = cfg.operations
    assert (d["electricCrews"], d["waterCrews"], d["gasCrews"], d["meterTechs"]) == \
        (o.electric_crews, o.water_crews, o.gas_crews, o.meter_techs)
    assert (d["meterWalkers"], d["meterVans"], d["shiftStartHour"], d["gasResponseTargetMinutes"]) == \
        (o.meter_walkers, o.meter_vans, o.shift_start_hour, o.gas_response_target_min)
    assert d["randomIncidents"] is (not cfg.incidents.manual_only) is True
    assert d["waterMainBreaksPer100km"] == cfg.incidents.water_main_breaks_per_100km
    assert d["stormDaysPerYear"] == cfg.weather.storm_days_per_year
    assert d["tieMinVoltage"] == 110.0  # Range A floor (0.95 pu = 114 V) less the 4 V emergency margin
    assert run_defaults(cfg.model_copy(update={"electric": cfg.electric.model_copy(
        update={"voltage_min_pu": 0.9})}))["tieMinVoltage"] == 104.0
    manual = cfg.model_copy(update={"incidents": cfg.incidents.model_copy(update={"manual_only": True})})
    assert run_defaults(manual)["randomIncidents"] is False
    assert set(TOWN_SETTINGS) <= set(DEFAULTS)
    # Crew pools follow the run's settings; readers share the routes in turn.
    run = Run(small_town, [], settings={"electricCrews": 5, "gasCrews": 1, "randomIncidents": False})
    assert len(run.crews["electric"]) == 5 and len(run.crews["gas"]) == 1


def test_settings_schema_takes_its_defaults_from_the_town():
    from api.index import app

    client = TestClient(app)
    body = client.get("/api/sim/settings/schema", params={"town": "small_town"}).json()
    crews = body["schema"]["properties"]["crews"]["properties"]
    assert crews["electricCrews"]["x-town"] == "operations.electric_crews"
    assert crews["electricCrews"]["default"] == body["defaults"]["electricCrews"]
    inc = body["schema"]["properties"]["incidents"]["properties"]
    assert inc["randomIncidents"]["type"] == "boolean" and inc["randomIncidents"]["default"] is True
    assert inc["stormDaysPerYear"]["x-town"] == "weather.storm_days_per_year"
    assert body["schema"]["properties"]["backfeed"]["properties"]["tieMinVoltage"]["x-town"] == "electric.voltage_min_pu"
    assert client.get("/api/sim/settings", params={"town": "small_town"}).json() == body["defaults"]
    assert client.get("/api/sim/settings/schema").json()["defaults"] == DEFAULTS  # no town: config defaults
    # The run seed (top level, or the linked meter-to-cash run's) re-rolls the day's background incidents.
    plain = client.post("/api/sim/timeline", json={"town": "small_town"}).json()
    seeded = client.post("/api/sim/timeline", json={"town": "small_town", "seed": "RUN-1"}).json()
    linked = client.post("/api/sim/timeline", json={"town": "small_town", "m2c": {"seed": "RUN-1"}}).json()
    assert plain["seed"] is None and seeded["seed"] == linked["seed"] == "RUN-1"
    assert seeded["simulationId"] == linked["simulationId"] != plain["simulationId"]
    assert seeded["background"] == linked["background"] and "meterToCash" in linked


def test_background_incidents_are_rare_seeded_and_scale_with_the_town(small_town):
    s, seed = small_town.run_defaults, small_town.sim_config.seeds.for_("incidents")
    days = year(small_town, s, seed)
    n = sum(len(items) for _, items in days)
    quiet = sum(1 for _, items in days if not items)
    assert 3 <= n <= 30 and quiet > 0.9 * len(days)  # the small town expects about 14 a year: most days are quiet
    assert days == year(small_town, s, seed)  # deterministic per (town seed, day)
    other = year(small_town, s, seed + "|RUN-2")
    assert [b["at"] for _, items in other for b in items] != [b["at"] for _, items in days for b in items]
    assert sum(len(i) for _, i in year(small_town, {**s, **ONLY}, seed)) == 0
    # Storm days follow the season; the year's expected count is the setting.
    p = [storm_probability(date(2026, 1, 1) + timedelta(days=k), 28.0) for k in range(365)]
    assert sum(p) == pytest.approx(28.0) and p[195] > 20 * p[15]
    _, info = draw(small_town, date(2026, 7, 15), s, seed)
    ex = info["exposure"]
    assert ex["transformers"] == sum(1 for k in small_town.nets["electric"].kind if k == "transformer")
    assert info["expected"]["water_main_break"] == pytest.approx(
        s["waterMainBreaksPer100km"] / 100 * (ex["waterMainKm"] + ex["castIronWaterMainKm"]) / 365, rel=1e-3)


def test_a_background_incident_is_worked_like_a_break(small_town):
    s, seed = small_town.run_defaults, small_town.sim_config.seeds.for_("incidents")
    day = next(d for d, items in year(small_town, s, seed) if any(b["kind"] == "water_main_break" for b in items))
    tl = Run(small_town, [], day=day.isoformat()).timeline()
    inc = next(i for i in tl["incidents"] if i["kind"] == "water_main_break")
    assert inc["source"] == "background" and inc["id"].startswith("INC-BG-") and inc["commandId"] is None
    assert tl["background"]["enabled"] and inc["id"] in tl["background"]["incidentIds"]
    assert inc["detectedAt"] < inc["isolatedAt"] < inc["restoredAt"]
    job = next(j for j in tl["jobs"] if j["incidentId"] == inc["id"])
    assert job["crewId"].startswith("WATER") and tl["commands"] == []
    kinds = [e["eventType"] for e in tl["events"] if e["correlationId"] == inc["id"]]
    assert kinds[:3] == ["asset.damaged", "leak.started", "incident.detected"] and "service.restored" in kinds
    assert Run(small_town, [], day=day.isoformat(), settings={"randomIncidents": False}).timeline()["incidents"] == []
    # A user's incident keeps its own numbering next to background ones.
    net = small_town.nets["electric"]
    pole = next(q for q in net.equipment if q["kind"] == "pole")
    cmd = {"id": "C", "at": 1.0, "type": "break_asset", "payload": {"id": pole["id"], "kind": "pole",
                                                                  "utility": "electric", "edgeId": pole["edgeId"]}}
    mixed = Run(small_town, [cmd], day=day.isoformat()).timeline()
    assert {i["id"] for i in mixed["incidents"]} == {"INC-1", *tl["background"]["incidentIds"]}
    assert next(i for i in mixed["incidents"] if i["id"] == "INC-1")["source"] == "user"


def test_transformer_failures_and_service_leaks_stay_local(small_town):
    over = {**ONLY, "transformerFailuresPer1000": 100, "gasServiceLeaksPer1000": 50}
    days = year(small_town, {**small_town.run_defaults, **over}, small_town.sim_config.seeds.for_("incidents"))
    tx_day = next(d for d, items in days if any(b["kind"] == "transformer_failure" for b in items))
    tl = Run(small_town, [], day=tx_day.isoformat(), settings=over).timeline()
    inc = next(i for i in tl["incidents"] if i["kind"] == "transformer_failure")
    assert inc["device"]["kind"] == "transformer_fuse" and inc["device"]["edgeId"] == inc["edgeId"]
    assert 0 < inc["unsupplied"]["atFault"] == inc["unsupplied"]["afterIsolation"] <= 20  # only its own customers
    leak_day = next(d for d, items in days if any(b["kind"] == "gas_service_leak" for b in items))
    tl = Run(small_town, [], day=leak_day.isoformat(), settings=over).timeline()
    inc = next(i for i in tl["incidents"] if i["kind"] == "gas_service_leak")
    assert inc["unsupplied"]["afterIsolation"] == 1 and inc["response"]["targetMinutes"] == 60.0
    closed = next(e for e in tl["events"] if e["correlationId"] == inc["id"] and e["eventType"] == "section.isolated")
    assert closed["payload"]["closedEdgeIds"] == [inc["edgeId"]]  # its own shut-off, not a section of main
    leak = next(e for e in tl["events"] if e["correlationId"] == inc["id"] and e["eventType"] == "leak.started")
    assert leak["payload"]["m3h"] == small_town.run_defaults["leakM3h"]["gas_service"]


def test_a_collector_outage_silences_its_meters_until_the_day_shift(small_town):
    from api._m2c import RunRequest, run_for
    from utilsim.m2c import views
    from utilsim.m2c.base import date_of

    s, seed = {**small_town.run_defaults, **ONLY, "collectorOutagesPerYear": 50}, small_town.sim_config.seeds.for_("incidents")
    night = next(d for d, items in year(small_town, s, seed)
                 if any(b["kind"] == "collector_outage" and b["at"] > 16 * 3600 for b in items))
    tl = Run(small_town, [], day=night.isoformat(), settings={k: s[k] for k in ONLY}).timeline()
    inc = next(i for i in tl["incidents"] if i["kind"] == "collector_outage" and i["createdAt"] > 16 * 3600)
    job = next(j for j in tl["jobs"] if j["incidentId"] == inc["id"])
    assert inc["utility"] == "ami" and job["crewId"].startswith("TECH") and inc["premiseIds"]
    assert job["requestedAt"] >= 86400 + 7 * 3600  # detected after the shift: worked next morning
    gap = next(x for x in tl["interruptions"] if x.get("incidentId") == inc["id"])
    assert gap["utility"] == "ami" and gap["start"] == inc["createdAt"] and gap["end"] == pytest.approx(inc["restoredAt"])
    assert not any(c["at"] for c in tl["stateChanges"] if c["unsupplied"])  # service went on
    # Meter-to-cash: an AMI read inside a collector outage is missed (use goes on); the case shows why.
    base = run_for(RunRequest(town="small_town"))
    tw = base.town
    ami = np.flatnonzero((tw.tech == "AMI") & (tw.commodity == "water"))
    r = int(ami[0])
    m = 4
    t = float(base.read_t[r, m])
    d = int(t)
    pid = tw.premise_ids[tw.prem[r]]
    outage = {"day": date_of(d).isoformat(), "utility": "ami", "start": (t - d) * 86400 - 1800,
              "end": (t - d) * 86400 + 1800, "premiseIds": [pid]}
    run = run_for(RunRequest(town="small_town", outages=[outage]))
    assert np.isnan(run.obs[r, m]) and run.reason[r, m] == "SIM_COLLECTOR_OUTAGE"
    assert np.array_equal(run.truth[r], base.truth[r])  # nothing stopped flowing
    case = run.cases[int(run.case_of[r, m])]
    assert case.type == "COMM_FAIL" and case.events[0][1] == "AMI_COLLECTOR_OUTAGE"
    # No service was interrupted: reliability counts only the year's own outages (none on that day).
    assert not [o for o in base.outage_log if int(o["t0"]) == d]
    assert views.summary(run, "2026-12-31")["reliability"] == views.summary(base, "2026-12-31")["reliability"]
    assert views.premise(run, pid, as_of="2026-12-31")["outages"][0]["collectorOutage"]
