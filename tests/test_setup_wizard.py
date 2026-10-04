"""Manual environment/utility setup uses the same validation boundary as voice."""
import pytest
from fastapi.testclient import TestClient

from api._agent_config import Proposal, validate_proposal
from api._setup import REGIONS
from api._towns import config_from_ref
from api.index import app


def test_wizard_configuration_without_provider_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/setup/configuration?preset=small_town")
        assert response.status_code == 200
        data = response.json()
        assert data["defaults"]["town"]["town"]["houses"] == 1900
        assert "weather" in data["schemas"]["town"]["properties"]
        assert "field" in data["schemas"]["run"]["properties"]
        assert data["defaults"]["operations"]["crews"]["fieldCrews"] >= 0
        assert data["townSizes"] == [500, 5000, 25000, 50000, 500000]
        assert len(data["regions"]) == 4
        assert "illustrative" in data["regionalNote"]
        assert client.get("/api/setup/configuration?preset=../../etc/passwd").status_code == 422


@pytest.mark.parametrize("region", REGIONS, ids=lambda r: r["id"])
def test_regional_environment_and_utility_inputs_survive_validation(region):
    overrides = {**region["overrides"], "town": {**region["overrides"]["town"], "houses": 240},
                 "gas": {"all_electric_district_share": 1}}
    p = validate_proposal(Proposal(name="Regional utility", preset="small_town", region=region["name"],
                                  townOverrides=overrides, settings={"process": {"analysts": 5},
                                  "contact": {"agents": 3}, "field": {"crew_meter": {"per_1000_premises": .75}}},
                                  summary="Review the environment and utility."))
    cfg = config_from_ref(p["townRef"])
    assert cfg.town.houses == 240
    assert cfg.weather.summer.mean_c == region["overrides"]["weather"]["summer"]["mean_c"]
    assert cfg.housing.pool_rate == region["overrides"]["housing"]["pool_rate"]
    assert cfg.housing.two_storey_share.model_dump() == region["overrides"]["housing"]["two_storey_share"]
    assert cfg.gas.all_electric_district_share == 1
    assert p["settings"]["process"]["analysts"] == 5
    assert p["settings"]["field"]["crew_meter"]["per_1000_premises"] == .75
    assert any(c["path"] == "weather.summer.mean_c" and c["impact"] for c in p["changes"])


def test_cross_field_errors_block_manual_setup():
    with TestClient(app) as client:
        r = client.post("/api/setup-agent/validate", json={"name": "Invalid metering", "preset": "village",
                        "summary": "Review", "townOverrides": {"ami": {"ami_route_share": .9, "amr_route_share": .5}}})
        assert r.status_code == 422
        assert "must not exceed 1" in r.json()["detail"]
        assert "input_value" not in r.json()["detail"]


def test_map_defaults_follow_edited_environment_and_town_crews():
    with TestClient(app) as client:
        r = client.post("/api/setup/operation-defaults", json={"name": "Map defaults", "preset": "village",
                        "summary": "Resolve defaults", "townOverrides": {
                            "weather": {"storm_days_per_year": 40}, "operations": {"gas_crews": 7}}})
        assert r.status_code == 200, r.text
        values = {key: value for group in r.json()["defaults"].values() for key, value in group.items()}
        assert values["stormDaysPerYear"] == 40
        assert values["gasCrews"] == 7


def test_goal_catalogue_maps_only_to_supported_engine_groups_and_guide():
    from utilsim.config.goals import GOALS
    from utilsim.config.model import RUN_GROUPS, SimConfig
    from utilsim.m2c.guide import CAPABILITIES, guide

    assert guide()["testGoals"] == GOALS
    capabilities = {c["id"] for c in CAPABILITIES}
    for goal in GOALS:
        assert set(goal["capabilities"]) <= capabilities
        assert set(goal["run"]) - {"*"} <= set(RUN_GROUPS)
        assert set(goal["town"] + goal["environment"]) - {"*"} <= set(SimConfig.model_fields) - set(RUN_GROUPS)
    p = validate_proposal(Proposal(name="VEE experiment", preset="village", goals=["reading", "vee"], summary="Test reads"))
    assert p["goals"] == ["reading", "vee"]
    with pytest.raises(ValueError):
        Proposal(name="Unsupported", preset="village", goals=["nuclear"], summary="No")
    with pytest.raises(ValueError):
        Proposal(name="Mixed", preset="village", goals=["everything", "vee"], summary="No")
