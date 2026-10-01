"""Presets: YAML overrides deep-merged onto SimConfig defaults. Scenario presets only touch ``scenario``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from utilsim.config.model import SimConfig

PRESET_DIR = Path(__file__).parent / "presets"

SCENARIOS: dict[str, dict[str, Any]] = {
    "normal": {"name": "normal", "hour": 8.0},
    "solar_noon": {"name": "solar_noon", "hour": 12.0},
    "leak": {"name": "leak", "hour": 8.0, "leak_m3h": 0.65},
    "substation_outage": {"name": "substation_outage", "hour": 19.0},
}


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def list_presets() -> list[dict[str, str]]:
    out = []
    for p in sorted(PRESET_DIR.glob("*.yaml")):
        d = yaml.safe_load(p.read_text()) or {}
        out.append({"name": p.stem, "description": d.get("description", "")})
    return out


def load_preset(name: str, overrides: dict[str, Any] | None = None, seed: str | int | None = None,
                houses: int | None = None, scenario: str | None = None) -> SimConfig:
    path = PRESET_DIR / f"{name}.yaml"
    if not path.exists():
        raise KeyError(f"unknown preset {name!r}; available: {[p['name'] for p in list_presets()]}")
    data = deep_merge(SimConfig().model_dump(mode="json"), yaml.safe_load(path.read_text()) or {})
    if overrides:
        data = deep_merge(data, overrides)
    if seed is not None:
        data["seeds"]["master"] = str(seed)
    if houses is not None:
        data["town"]["houses"] = int(houses)
    if scenario is not None:
        if scenario not in SCENARIOS:
            raise KeyError(f"unknown scenario {scenario!r}; available: {sorted(SCENARIOS)}")
        data["scenario"] = deep_merge(data["scenario"], SCENARIOS[scenario])
    return SimConfig.model_validate(data)
