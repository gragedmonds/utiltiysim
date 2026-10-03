"""Claude's configuration boundary: inspect live schemas; validate proposals without running a simulation."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api._ops import pack_index
from api._towns import MAX_HOUSES, town_ref
from utilsim.config.model import RUN_GROUPS, SimConfig, config_schema
from utilsim.m2c.run import (
    parse_episodes,
    resolve_episode_days,
    resolve_settings,
    settings_schema,
)
from utilsim.ops.settings_schema import settings_schema as ops_schema
from utilsim.ops.settings_schema import to_settings
from utilsim.ops.timeline import run_defaults


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def year_day(value: str) -> str:
    if date.fromisoformat(value).year != 2026 or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Choose a date in 2026.")
    return value


class AgentEpisode(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    from_: str = Field(alias="from")
    to: str | None = None
    ramp: int = Field(0, ge=0, le=365)
    settings: dict[str, dict[str, Any]]

    @field_validator("from_", "to")
    @classmethod
    def dates(cls, value):
        return year_day(value) if value is not None else None


class Proposal(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    purpose: str = Field(default="", max_length=500)
    region: str = Field(default="", max_length=200)
    preset: str = Field(description="A preset from the supplied prepared-town catalogue.")
    seed: str = Field(default="", max_length=64)
    asOf: str = Field(default="2026-03-31")
    townOverrides: dict[str, Any] = Field(default_factory=dict, description="Generation groups only; never filesystem paths.")
    settings: dict[str, dict[str, Any]] = Field(default_factory=dict, description="Base meter-to-cash settings.")
    operations: dict[str, dict[str, Any]] = Field(default_factory=dict, description="Grouped operations overrides, as in inspect_configuration.")
    episodes: list[AgentEpisode] = Field(default_factory=list, max_length=40)
    summary: str = Field(min_length=1, max_length=2000)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("asOf")
    @classmethod
    def day(cls, value):
        return year_day(value)

    @field_validator("assumptions", "limitations")
    @classmethod
    def short_items(cls, value):
        if any(len(item) > 500 for item in value):
            raise ValueError("Keep each explanation under 500 characters.")
        return value


class AssignedEpisode(AgentEpisode):
    id: str


class ConfigurationChange(StrictModel):
    path: str
    before: Any
    after: Any


class ValidatedProposal(Proposal):
    episodes: list[AssignedEpisode] = Field(default_factory=list, max_length=40)
    opsSettings: dict
    townRef: str
    townId: str
    townName: str
    homes: int
    changes: list[ConfigurationChange]


class AgentReply(StrictModel):
    message: str = Field(min_length=1, max_length=4000, description="Speak to the user plainly. Ask at most two useful follow-up questions, or explain the proposal.")
    proposal: Proposal | None = None


def presets() -> list[dict]:
    return [{"preset": t["preset"], "name": (t.get("place") or {}).get("name") or (t.get("source") or {}).get("label", t["preset"]).removesuffix(" street snapshot"),
             "homes": t["homes"], "townId": t["townId"]} for t in pack_index()["towns"]]


def preset_config(preset: str) -> SimConfig:
    from utilsim.config.presets import load_preset

    if preset not in {t["preset"] for t in presets()}:
        raise ValueError("Choose a prepared town from the catalogue.")
    return load_preset(preset)


def schemas() -> dict:
    return {"town": config_schema(), "run": settings_schema(), "operations": ops_schema()}


def expand(schema: dict, root: dict) -> dict:
    return {**root.get("$defs", {}).get(schema.get("$ref", "").split("/")[-1], {}), **schema}


def group_index() -> dict:
    return {scope: {name: {k: expand(s, root).get(k) for k in ("title", "description", "x-applies")}
                    for name, s in root["properties"].items()} for scope, root in schemas().items()}


def inspect_configuration(scope: Literal["town", "run", "operations"], groups: list[str], preset: str) -> dict:
    cfg = preset_config(preset)
    root = schemas()[scope]
    if not 1 <= len(groups) <= 6 or any(g not in root["properties"] for g in groups):
        raise ValueError("Choose one to six groups from the configuration index.")
    defaults = cfg.model_dump(mode="json") if scope != "operations" else run_defaults(cfg)
    return {"scope": scope, "schema": {**root, "properties": {g: root["properties"][g] for g in groups}},
            "defaults": {g: defaults.get(g) if scope != "operations" or not root["properties"][g].get("x-flat")
                         else {k: defaults.get(k) for k in root["properties"][g]["properties"]} for g in groups}}


def supported_fields(values: dict, schema: dict, root: dict | None = None, path: str = "") -> None:
    """Unknown and not-modelled knobs are never silently accepted, including nested properties."""
    root = root or schema
    schema = expand(schema, root)
    for key, value in values.items():
        name = f"{path}.{key}" if path else key
        if key not in schema.get("properties", {}):
            raise ValueError(f"Unknown setting: {name}")
        field = expand(schema["properties"][key], root)
        if field.get("x-status") in ("not-modelled", "deprecated"):
            raise ValueError(f"{name}: {field.get('x-status-reason', 'not supported')}")
        if isinstance(value, dict):
            supported_fields(value, field, root, name)


def validate_operations(values: dict, cfg: SimConfig) -> dict:
    from jsonschema import Draft202012Validator

    schema = ops_schema(run_defaults(cfg))
    supported_fields(values, schema)
    Draft202012Validator(schema).validate(values)
    actual = to_settings(values)
    full = {**run_defaults(cfg), **actual}
    if full["shiftEndHour"] <= full["shiftStartHour"]:
        raise ValueError("Operations shift end must be after its start.")
    return actual


def changes(before: dict, after: dict, prefix: str = "") -> list[dict]:
    out = []
    for key, value in after.items():
        path = f"{prefix}.{key}" if prefix else key
        old = before.get(key)
        if isinstance(value, dict) and isinstance(old, dict):
            out.extend(changes(old, value, path))
        elif old != value:
            out.append({"path": path, "before": old, "after": value})
    return out


def validate_proposal(proposal: Proposal) -> dict:
    from utilsim.config.presets import deep_merge

    base = preset_config(proposal.preset)
    town = proposal.townOverrides
    if any(not isinstance(v, dict) for v in town.values()):
        raise ValueError("Each town override group must be an object.")
    if any(k in RUN_GROUPS or k not in SimConfig.model_fields or k in ("name", "description") for k in town):
        raise ValueError("townOverrides only accepts generation groups; put run changes in settings or operations.")
    if any(k in town.get("town", {}) for k in ("osm_source", "osm_sha256")):
        raise ValueError("Street sources must come from a prepared town, not a supplied file path.")
    supported_fields(town, config_schema())
    cfg = SimConfig.model_validate(deep_merge(base.model_dump(mode="json"), town))
    if cfg.town.houses > MAX_HOUSES:
        raise ValueError(f"This engine supports at most {MAX_HOUSES} homes, not customer accounts.")
    try:
        ZoneInfo(cfg.town.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Choose a valid IANA timezone.") from exc
    supported_fields(proposal.settings, settings_schema())
    run_cfg = resolve_settings(cfg, proposal.settings)
    episodes = [{**ep.model_dump(by_alias=True), "id": f"EP-{i+1}"} for i, ep in enumerate(proposal.episodes)]
    for ep in episodes:
        supported_fields(ep["settings"], settings_schema())
    # This is the same daily bounds/dependency validation the engine uses, without generating customers or results.
    resolve_episode_days(run_cfg, parse_episodes(run_cfg, episodes))
    ops = validate_operations(proposal.operations, cfg)
    ref = town_ref(cfg)
    if len(ref) > 4000:
        raise ValueError("Town changes are too large for a portable reference. Use fewer town overrides.")
    pack = next(t for t in presets() if t["preset"] == proposal.preset)
    limits = list(proposal.limitations)[:16]
    for note in ("The engine models calendar year 2026 only.",
                 "Prepared towns and baseline assumptions are Ontario-based; regional calibration is not automatic.",
                 "Homes are not the same count as customer accounts."):
        if note not in limits:
            limits.append(note)
    if ops:
        note = "Operations settings affect simulated map days; Year does not automatically simulate every operations day."
        if note not in limits:
            limits.append(note)
    return {**proposal.model_dump(by_alias=True), "episodes": episodes, "opsSettings": ops,
            "townRef": ref, "townId": pack["townId"] if ref == proposal.preset else cfg.town_id(),
            "townName": pack["name"] + (" · customised" if ref != proposal.preset else ""),
            "homes": cfg.town.houses, "limitations": limits,
            "changes": changes(base.model_dump(mode="json"), run_cfg.model_dump(mode="json"))
                       + changes(run_defaults(cfg), {**run_defaults(cfg), **ops}, "operations")}
