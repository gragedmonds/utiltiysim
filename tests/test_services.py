"""A utility that provides some of the services (``customers_billing.services``): the networks are generated either way
(another utility runs the rest), but the utility's customers, meters, reads, bills, crews, maintenance, incidents and
calls cover only what it serves. Serving everything changes nothing: the same town ids, snapshots and runs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api._m2c import RunRequest, run_for
from api._towns import town_ref
from utilsim.config import load_preset
from utilsim.config.model import SERVICES, SimConfig
from utilsim.m2c import contact, fieldwork
from utilsim.utility import network as nw


def config(services, preset="small_town") -> SimConfig:
    d = load_preset(preset).model_dump(mode="json")
    d["customers_billing"]["services"] = services
    return SimConfig.model_validate(d)


@pytest.fixture(scope="module")
def electric():
    return run_for(RunRequest(town=town_ref(config(["electric"])), asOf="2026-12-31"))


@pytest.fixture(scope="module")
def gas():
    return run_for(RunRequest(town=town_ref(config(["gas"])), asOf="2026-12-31"))


def test_serving_everything_is_the_town_as_before():
    cfg = load_preset("small_town")
    assert cfg.customers_billing.services == list(SERVICES)
    assert "services" not in cfg.generation_dict()["customers_billing"]  # ids, packs and refs unchanged
    assert config(["gas", "electric", "water"]).town_id() == cfg.town_id()
    assert config(["gas", "electric"]).customers_billing.services == ["electric", "gas"]  # canonical order
    assert config(["electric"]).town_id() != cfg.town_id()
    for bad in ([], ["electric", "electric"], ["steam"]):
        with pytest.raises(ValidationError):
            config(bad)


def test_an_electric_utility_has_only_electric_customers_and_work(electric):
    run, tw = electric, electric.town
    assert set(tw.commodity.tolist()) == {"electric"} and tw.n_registers > 0
    snap_prem = run.ops_factory().premises
    assert all(set(p["services"]) == {"electric"} and p["accountId"] for p in snap_prem)
    assert all(p["connections"][:2] == ["electric", "water"] for p in snap_prem)  # still on the water (and gas) mains
    fw = fieldwork.summary(run, "2026-12-31")
    crews = {c["id"]: c["crews"] for c in fw["crews"]}
    assert crews["water"] == crews["gas"] == 0 and crews["electric"] > 0 and crews["meter"] > 0
    due = {p["id"]: p.get("due") for p in fw["plan"]}
    assert due["pole_inspection"] and due["tree_trimming"]
    assert not any(due[k] for k in ("hydrant_flush", "leak_survey", "regulator_inspection", "valve_exercise",
                                    "water_meter_replacement", "main_replacement"))
    assert {i["utility"] for i in run.field.incidents} <= {"electric", "ami"}
    cx = contact.summary(run, "2026-12-31")
    assert next(r for r in cx["reasons"] if r["id"] == "gas_odour")["contacts"] == 0


def test_a_gas_utility_serves_the_premises_on_gas_mains(gas):
    run, tw = gas, gas.town
    assert set(tw.commodity.tolist()) == {"gas"}
    prem = run.ops_factory().premises
    customers = [p for p in prem if p["services"]]
    assert customers and all(set(p["services"]) == {"gas"} and p["accountId"] for p in customers)
    others = [p for p in prem if not p["services"]]  # all-electric homes: another utility's customers only
    assert all(p["accountId"] is None and "gas" not in p["connections"] for p in others)
    crews = {c["id"]: c["crews"] for c in fieldwork.summary(run, "2026-12-31")["crews"]}
    assert crews["electric"] == crews["water"] == 0 and crews["gas"] > 0
    assert {i["utility"] for i in run.field.incidents} <= {"gas", "ami"}


def test_other_utilities_events_are_left_out(electric):
    tw = electric.town
    pid = tw.premise_ids[0]
    run = run_for(RunRequest(town=town_ref(config(["electric"])), asOf="2026-06-30",
                             outages=[{"day": "2026-05-04", "utility": "water", "start": 3600, "end": 7200,
                                       "premiseIds": [pid]}]))
    assert run.outages == [] and any("another utility" in w for w in run.warnings)
    lay = nw.layout(["d1", "d2", "d3"], services=["electric"])
    assert {a["utility"] for a in lay["assets"]} == {"electric"}


def test_a_gas_utility_needs_gas_mains():
    d = load_preset("small_town").model_dump(mode="json")
    d["customers_billing"]["services"] = ["gas"]
    d["gas"]["all_electric_district_share"] = 1.0
    d["town"]["houses"] = 3000  # several districts, so the share can leave no gas mains at all
    from utilsim.gen.pipeline import generate

    with pytest.raises(ValueError, match="no premise takes the services"):
        generate(SimConfig.model_validate(d))
