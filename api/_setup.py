"""Manual wizard inputs and illustrative regional starting points; no provider calls or town generation."""
from api._agent_config import Proposal, grouped_ops_defaults, preset_config, schemas, validate_proposal
from api._towns import MAX_HOUSES
from utilsim.config.model import RUN_GROUPS, SimConfig

TOWN_SIZES = [500, 5000, 50000, 500000]

REGIONAL_NOTE = ("Regional starters are illustrative modelling assumptions, not measured local statistics. "
                 "Edit them for your service area. Regional choices do not calibrate tariffs or regulations.")


def season(mean, sd, low, high):
    return {"mean_c": mean, "sd_c": sd, "min_c": low, "max_c": high}


REGIONS = [
    {"id": "great_lakes", "name": "Great Lakes / southern Ontario", "description": "Mixed-age neighbourhoods, cold winters and moderate summers.",
     "overrides": {"town": {"units": "ontario", "anchor_lat": 43.3, "anchor_lon": -80.6,
                            "timezone": "America/Toronto", "terrain_relief_m": 15, "era_core_year": 1925, "era_span_years": 85},
                   "housing": {"pool_rate": .06, "ac_rate": .85, "irrigation_rate": .30,
                               "lot_frontage_m": {"pre_1945": 15, "postwar": 18.5, "modern": 16.5},
                               "lot_depth_m": {"pre_1945": 36, "postwar": 35, "modern": 33},
                               "two_storey_share": {"pre_1945": .7, "postwar": .25, "modern": .75}},
                   "weather": {"winter": season(-4.5, 6.5, -28, 12), "spring": season(9, 6, -8, 30),
                               "summer": season(21.5, 4, 10, 37), "fall": season(9.5, 6.5, -10, 28), "storm_days_per_year": 28}}},
    {"id": "upstate_suburban", "name": "Upstate New York / Northeast suburbs", "description": "Older centres, two-storey suburbs, rolling terrain and colder winters.",
     "overrides": {"town": {"units": "us", "anchor_lat": 42.65, "anchor_lon": -73.75,
                            "timezone": "America/New_York", "terrain_relief_m": 35, "era_core_year": 1910, "era_span_years": 100},
                   "housing": {"pool_rate": .07, "ac_rate": .75, "irrigation_rate": .22,
                               "lot_frontage_m": {"pre_1945": 16, "postwar": 22, "modern": 20},
                               "lot_depth_m": {"pre_1945": 38, "postwar": 42, "modern": 38},
                               "two_storey_share": {"pre_1945": .8, "postwar": .5, "modern": .8}},
                   "weather": {"winter": season(-5, 7, -30, 12), "spring": season(9, 6, -10, 30),
                               "summer": season(21, 4, 10, 36), "fall": season(9, 6, -12, 29), "storm_days_per_year": 25}}},
    {"id": "midwest", "name": "Midwest / plains suburbs", "description": "Flatter streets, wider lots, more single-storey homes and hotter summers.",
     "overrides": {"town": {"units": "us", "anchor_lat": 41.6, "anchor_lon": -93.6,
                            "timezone": "America/Chicago", "terrain_relief_m": 8, "era_core_year": 1940, "era_span_years": 75},
                   "housing": {"pool_rate": .04, "ac_rate": .95, "irrigation_rate": .4,
                               "lot_frontage_m": {"pre_1945": 18, "postwar": 24, "modern": 22},
                               "lot_depth_m": {"pre_1945": 38, "postwar": 40, "modern": 38},
                               "two_storey_share": {"pre_1945": .6, "postwar": .2, "modern": .45}},
                   "weather": {"winter": season(-6, 8, -32, 15), "spring": season(11, 7, -10, 33),
                               "summer": season(24, 5, 12, 40), "fall": season(11, 7, -12, 32), "storm_days_per_year": 40}}},
    {"id": "warm_suburban", "name": "Warm southern suburbs", "description": "Newer housing, warm winters, longer cooling demand and more pools.",
     "overrides": {"town": {"units": "us", "anchor_lat": 32.8, "anchor_lon": -96.8,
                            "timezone": "America/Chicago", "terrain_relief_m": 12, "era_core_year": 1960, "era_span_years": 60},
                   "housing": {"pool_rate": .18, "ac_rate": .98, "irrigation_rate": .6,
                               "lot_frontage_m": {"pre_1945": 18, "postwar": 22, "modern": 20},
                               "lot_depth_m": {"pre_1945": 38, "postwar": 40, "modern": 36},
                               "two_storey_share": {"pre_1945": .5, "postwar": .2, "modern": .55}},
                   "weather": {"winter": season(9, 6, -12, 27), "spring": season(20, 5, 2, 36),
                               "summer": season(30, 4, 18, 44), "fall": season(21, 6, 0, 37), "storm_days_per_year": 40}}},
]


def configuration(preset: str) -> dict:
    cfg = preset_config(preset)
    values = cfg.model_dump(mode="json")
    return {"schemas": schemas(), "defaults": {"town": values,
            "run": {k: values[k] for k in RUN_GROUPS}, "operations": grouped_ops_defaults(cfg)},
            "homeLimit": MAX_HOUSES, "townSizes": TOWN_SIZES, "regions": REGIONS, "regionalNote": REGIONAL_NOTE}


def operation_defaults(proposal: Proposal) -> dict:
    from utilsim.config.presets import deep_merge

    validate_proposal(proposal)
    base = preset_config(proposal.preset)
    cfg = SimConfig.model_validate(deep_merge(base.model_dump(mode="json"), proposal.townOverrides))
    return grouped_ops_defaults(cfg)
