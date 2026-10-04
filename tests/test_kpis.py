"""The KPI catalogue: every figure the Studio can watch, its definition and influences, the threshold settings that
define it, and the figures of a run."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api._agent_config import Proposal
from api.app import app
from utilsim.config.goals import GOAL_IDS
from utilsim.config.model import SimConfig, config_schema
from utilsim.m2c.kpis import FAMILY_IDS, KPI_IDS, KPIS, catalogue, for_goals, scenarios_for
from utilsim.m2c.run import settings_schema
from utilsim.m2c.scenarios import BY_ID


def _paths(schema: dict) -> set[str]:
    """``group.field`` and ``group.field.sub`` for every setting in a run or town schema (groups may be ``$ref``s)."""
    defs = schema.get("$defs", {})

    def resolve(node: dict) -> dict:
        ref = node.get("$ref") or next((a["$ref"] for a in node.get("allOf", []) if "$ref" in a), None)
        return defs[ref.rsplit("/", 1)[-1]] if ref else node

    out = set()
    for g, group in schema["properties"].items():
        for k, field in resolve(group).get("properties", {}).items():
            out.add(f"{g}.{k}")
            for sub in resolve(field).get("properties", {}):  # one level of nesting (field.crew_meter.per_1000_premises)
                out.add(f"{g}.{k}.{sub}")
    return out


def test_the_catalogue_is_consistent():
    ids = [k.id for k in KPIS]
    assert len(ids) == len(set(ids)) and len(ids) >= 30
    run_paths, town_paths = _paths(settings_schema()), _paths(config_schema())
    for k in KPIS:
        assert k.family in FAMILY_IDS and k.better in ("lower", "higher") and k.goals, k.id
        assert set(k.goals) <= GOAL_IDS - {"everything"}, k.id
        for path, direction in k.settings:
            assert path in run_paths | town_paths, (k.id, path)
            assert direction in (1, -1)
        for path in k.thresholds:
            assert path in run_paths, (k.id, path)
        assert set(k.related) <= KPI_IDS, k.id
        assert k.where and k.definition and k.formula
    # The twin's figures are all here, under their own ids.
    from utilsim.twin.kpis import KPIS as TWIN
    assert {t.id for t in TWIN} <= KPI_IDS and all(k.twin for k in KPIS if k.id in {t.id for t in TWIN})
    # Scenarios are derived from the settings their episodes change.
    assert "no_access_season" in scenarios_for("missed_read_share")
    assert "vee_tightened" in scenarios_for("exceptions_vee") and BY_ID["vee_tightened"]
    assert scenarios_for("days_to_pay") == []
    # Goals pick figures; everything picks all.
    assert {k.family for k in for_goals(["contact"])} == {"contact"}
    assert len(for_goals(["everything"])) == len(KPIS) == len(for_goals([]))
    assert set(for_goals(["billing", "collections"])) > set(for_goals(["collections"]))


def test_thresholds_are_settings_with_defaults_and_bounds():
    cat = catalogue()
    assert cat["schemaVersion"] == "m2c-kpis/1.0" and cat["settingsGroup"] == "kpi"
    assert cat["thresholds"]["kpi.on_time_bill_days"]["value"] == 3
    assert cat["thresholds"]["kpi.on_time_bill_days"]["unit"] == "days"
    assert cat["thresholds"]["contact.service_target_s"]["value"] == SimConfig().contact.service_target_s
    kpi = settings_schema()["properties"]["kpi"]
    assert kpi["x-applies"] == "run" and set(kpi["properties"]) == {
        "on_time_bill_days", "timely_invoice_days", "read_release_days", "payment_grace_days", "case_resolution_days"}
    with pytest.raises(ValidationError):
        SimConfig.model_validate({"kpi": {"on_time_bill_days": 99}})


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_a_runs_figures_and_how_the_windows_move_them(client):
    base = {"town": "small_town", "asOf": "2026-06-30"}
    r = client.post("/api/m2c/kpis", json=base)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["schemaVersion"] == "m2c-kpis/1.0" and d["asOf"] == "2026-06-30" and set(d["values"]) == KPI_IDS
    v = d["values"]
    for k in KPIS:
        x = v[k.id]
        if k.unit == "share" and x is not None:
            assert 0.0 <= x <= 1.0, (k.id, x)
    assert v["bills_on_time"] > 0.9 and v["missed_read_share"] > 0 and v["cost_per_account"] > 0
    assert d["thresholds"]["kpi.on_time_bill_days"] == 3
    # Tighter windows make fewer things on time; looser ones more. A zero-day bill window still counts same-day bills.
    def figures(kpi_settings, ids):
        out = client.post("/api/m2c/kpis", json={**base, "settings": {"kpi": kpi_settings}, "kpis": ids}).json()
        assert set(out["values"]) == set(ids)
        return out["values"]
    tight = figures({"on_time_bill_days": 0, "read_release_days": 0, "payment_grace_days": 0, "case_resolution_days": 1},
                    ["bills_on_time", "reads_released_promptly", "paid_on_time", "cases_resolved_in_time"])
    loose = figures({"on_time_bill_days": 30, "read_release_days": 60, "payment_grace_days": 30, "case_resolution_days": 30},
                    ["bills_on_time", "reads_released_promptly", "paid_on_time", "cases_resolved_in_time"])
    for key in tight:
        assert tight[key] <= v[key] <= loose[key], (key, tight[key], v[key], loose[key])
    assert tight["bills_on_time"] > 0.5
    assert client.post("/api/m2c/kpis", json={**base, "kpis": ["nope"]}).status_code == 422
    # The catalogue for a town carries that town's threshold values.
    cat = client.get("/api/m2c/kpis?town=small_town").json()
    assert cat["thresholds"]["kpi.payment_grace_days"]["value"] == 3 and len(cat["kpis"]) == len(KPIS)
    assert all("scenarios" in k and "settings" in k for k in cat["kpis"])


def test_a_proposal_names_its_kpis_from_the_catalogue():
    p = Proposal.model_validate({"name": "n", "summary": "s", "preset": "small_town", "kpis": ["bills_on_time", "days_to_pay"]})
    assert p.kpis == ["bills_on_time", "days_to_pay"]
    with pytest.raises(ValueError, match="catalogue"):
        Proposal.model_validate({"name": "n", "summary": "s", "preset": "small_town", "kpis": ["on_time_bills"]})
    with pytest.raises(ValueError):
        Proposal.model_validate({"name": "n", "summary": "s", "preset": "small_town", "kpis": ["days_to_pay", "days_to_pay"]})
