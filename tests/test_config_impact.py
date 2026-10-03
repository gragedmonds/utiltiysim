"""Every setting says where its effect reaches and how it changes the results (utilsim/config/impact.py); settings
nothing used are gone, and configs written before their removal still load."""

from __future__ import annotations

import pytest

from utilsim.config import SimConfig, load_preset
from utilsim.config.impact import IMPACT, REACHES, REMOVED
from utilsim.config.model import RUN_GROUPS, config_schema
from utilsim.m2c.run import M2C_GROUPS, settings_schema


def _fields() -> set[str]:
    out = set()
    for g, f in SimConfig.model_fields.items():
        if hasattr(f.annotation, "model_fields"):
            out |= {f"{g}.{k}" for k in f.annotation.model_fields}
    return out


def test_every_setting_has_a_reach_and_an_explanation_and_nothing_stale():
    fields = _fields()
    assert set(IMPACT) == fields, (sorted(fields - set(IMPACT)), sorted(set(IMPACT) - fields))
    for path, (reach, text) in IMPACT.items():
        assert reach in REACHES, path
        assert 20 <= len(text) <= 320, path
    for g, keys in REMOVED.items():
        model = SimConfig.model_fields[g].annotation
        assert not set(keys) & set(model.model_fields), g


def test_reaches_match_where_a_setting_lives():
    for path, (reach, _) in IMPACT.items():
        g = path.split(".")[0]
        if g in RUN_GROUPS:  # a run setting cannot need a new town
            assert reach != "town", path
        else:  # a town setting cannot change the year without a new town
            assert reach != "year", path
    for g in M2C_GROUPS:  # the meter-to-cash run groups all change the year, apart from priced-only costs
        assert all(IMPACT[f"{g}.{k}"][0] == "year" for k in SimConfig.model_fields[g].annotation.model_fields), g


def test_schemas_carry_reach_and_explanation():
    defs = config_schema()["$defs"]
    by_class = {f.annotation.__name__: g for g, f in SimConfig.model_fields.items() if hasattr(f.annotation, "model_fields")}
    seen = 0
    for cls, g in by_class.items():
        for key, prop in defs[cls]["properties"].items():
            assert (prop["x-reach"], prop["x-impact"]) == IMPACT[f"{g}.{key}"], (g, key)
            seen += 1
    assert seen == len(IMPACT) and config_schema()["x-reaches"] == REACHES
    run = settings_schema()
    assert run["x-reaches"] == REACHES
    for g in M2C_GROUPS:
        for key, prop in run["properties"][g]["properties"].items():
            assert prop["x-impact"] == IMPACT[f"{g}.{key}"][1]


def test_configs_written_before_a_removal_still_load_and_keep_their_town():
    base = SimConfig()
    data = base.model_dump(mode="json")
    old = {g: dict(v) if isinstance(v, dict) else v for g, v in data.items()}
    stale = {"housing": {"semi_share": {"pre_1945": 0.25, "postwar": 0.08, "modern": 0.18}},
             "electric": {"transmission_kv": 69.0, "severe_turn_deg": 45.0},
             "ami": {"battery_life_years": 15.0, "comm_fail_rate": 0.004},
             "operations": {"drive_by_radius_m": 120.0, "walker_meters_per_hour": 45.0},
             "process": {"sequences": "builtin"}, "scenario": {"tick_minutes": 5}}
    assert {g: tuple(v) for g, v in stale.items()} == REMOVED
    for g, extra in stale.items():
        old[g].update(extra)
    cfg = SimConfig.model_validate(old)
    assert cfg.town_id() == base.town_id() and cfg == base
    # A run's settings with a removed key are accepted too.
    from utilsim.m2c.run import resolve_settings

    assert resolve_settings(base, {"process": {"sequences": "builtin", "analysts": 3}}).process.analysts == 3


def test_an_unknown_setting_is_still_refused():
    data = SimConfig().model_dump(mode="json")
    data["housing"]["semi_detached_share"] = 0.1
    with pytest.raises(ValueError):
        SimConfig.model_validate(data)


def test_us_midwest_preset_still_loads():
    assert load_preset("us_midwest").electric.primary_kv == pytest.approx(12.47)
