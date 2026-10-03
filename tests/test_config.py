import pytest
from pydantic import ValidationError

from utilsim.config import SimConfig, config_schema, list_presets, load_preset


def test_defaults_validate_and_town_id_is_stable():
    a, b = SimConfig(), SimConfig()
    assert a.town_id() == b.town_id() and a.town_id().startswith("town-")
    # Informational fields and scenario do not change the town.
    c = SimConfig(name="x", description="y")
    c.scenario.hour = 12
    assert c.town_id() == a.town_id()


def test_town_id_changes_with_generation_inputs():
    a = SimConfig()
    b = SimConfig.model_validate({"seeds": {"master": "other"}})
    c = SimConfig.model_validate({"housing": {"solar_rate": {"pre_1945": 0.5, "postwar": 0.5, "modern": 0.5}}})
    assert len({a.town_id(), b.town_id(), c.town_id()}) == 3


def test_bounds_and_cross_field_validation():
    with pytest.raises(ValidationError):
        SimConfig.model_validate({"town": {"houses": 19}})
    with pytest.raises(ValidationError):
        SimConfig.model_validate({"town": {"houses": 10_001}})
    with pytest.raises(ValidationError):
        SimConfig.model_validate({"ami": {"ami_route_share": 0.8, "amr_route_share": 0.3}})
    with pytest.raises(ValidationError):
        SimConfig.model_validate({"unknown_group": {}})


def test_presets_load_and_override():
    names = {p["name"] for p in list_presets()}
    assert {"whitby_small", "whitby_town", "whitby_large", "ontario_small", "ontario_large", "us_midwest"} <= names
    cfg = load_preset("whitby_small", seed="abc", houses=120, scenario="solar_noon")
    assert cfg.town.houses == 120 and cfg.seeds.master == "abc" and cfg.scenario.name == "solar_noon"
    assert load_preset("us_midwest").electric.primary_kv == 12.47
    with pytest.raises(KeyError):
        load_preset("nope")


def test_schema_has_ui_hints():
    s = config_schema()
    defs = s["$defs"]
    town = defs["TownConfig"]
    assert town["x-group"] is True and "x-order" in town
    assert town["properties"]["houses"]["maximum"] == 10_000
    assert "x-effects" in town["properties"]["houses"]
    assert defs["ElectricConfig"]["properties"]["primary_kv"]["x-unit"] == "kV"


def test_groups_say_whether_a_change_regenerates_the_town():
    from utilsim.config import SimConfig

    defs = config_schema()["$defs"]
    applies = {k: v["x-applies"] for k, v in defs.items() if v.get("x-group")}
    assert applies["ScenarioConfig"] == "run" and applies["TownConfig"] == "town"
    assert set(applies.values()) == {"town", "run"}
    # "run" groups must really be outside the town id.
    base = SimConfig()
    assert base.model_copy(update={"scenario": base.scenario.model_copy(update={"hour": 19.0})}).town_id() == \
        base.town_id()


def test_fields_say_when_a_run_setting_overrides_them_or_they_are_not_modelled():
    from utilsim.ops.timeline import DEFAULTS, TOWN_SETTINGS

    defs = config_schema()["$defs"]
    hinted = {(g, f): p for g, d in defs.items() if d.get("x-group") for f, p in d["properties"].items()
              if "x-status" in p or "x-run-setting" in p}
    status = {k: p["x-status"] for k, p in hinted.items() if "x-status" in p}
    assert status == {}  # settings nothing used were removed (utilsim/config/impact.py REMOVED)
    runs = {k: p["x-run-setting"] for k, p in hinted.items() if "x-run-setting" in p}
    assert set(runs.values()) <= set(DEFAULTS) and len(runs) == len(TOWN_SETTINGS) == 18
    assert runs[("IncidentConfig", "manual_only")] == "randomIncidents"
    assert runs[("WeatherConfig", "storm_days_per_year")] == "stormDaysPerYear"
    assert len([f for g, f in runs if g == "IncidentConfig"]) == 7  # every incident rate is a live run default
