"""Claude's configuration boundary: inspect live schemas; validate proposals without running a simulation."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api._ops import pack_index
from api._towns import DEFAULT_BASE, MAX_HOUSES, config_from_ref, town_ref
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
    scope: str = "run"
    episodeIndex: int | None = None
    input: Any = None
    title: str = ""
    impact: str = ""
    reach: str = ""
    unit: str = ""
    percentage: bool = False
    valueType: str = ""
    minimum: float | None = None
    maximum: float | None = None
    choices: list[Any] = Field(default_factory=list)
    beforeRange: list[Any] = Field(default_factory=list)
    afterRange: list[Any] = Field(default_factory=list)
    period: str = ""


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


class ExistingEpisode(AgentEpisode):
    id: str = Field(min_length=1, max_length=80)
    scenario: str | None = None


class RunContext(StrictModel):
    name: str = Field(default="", max_length=100)
    region: str = Field(default="", max_length=200)
    purpose: str = Field(default="", max_length=500)
    townRef: str = Field(min_length=1, max_length=4000)
    settings: dict[str, dict[str, Any]] = Field(default_factory=dict)
    episodes: list[ExistingEpisode] = Field(default_factory=list, max_length=40)
    asOf: str = "2026-03-31"
    startDate: str = "2026-03-31"

    @field_validator("asOf", "startDate")
    @classmethod
    def dates(cls, value):
        return year_day(value)


class InflictProposal(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=2000)
    episodes: list[AgentEpisode] = Field(min_length=1, max_length=10)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("assumptions", "limitations")
    @classmethod
    def short_items(cls, value):
        return Proposal.short_items(value)


class ValidatedInflictProposal(InflictProposal):
    runTo: str
    changes: list[ConfigurationChange] = Field(default_factory=list)


class InflictReply(StrictModel):
    message: str = Field(min_length=1, max_length=4000)
    proposal: InflictProposal | None = None


def run_config(context: RunContext) -> SimConfig:
    """Resolve a known town without generating it or reading supplied street paths."""
    name = context.townRef.partition("~")[0]
    if name == DEFAULT_BASE:
        base = SimConfig()
    else:
        base = preset_config(name)
    cfg = config_from_ref(context.townRef) if "~" in context.townRef else base
    supported_fields(context.settings, settings_schema())
    return resolve_settings(cfg, context.settings)


def validate_infliction(proposal: InflictProposal, context: RunContext) -> dict:
    cfg = run_config(context)
    if len(context.episodes) + len(proposal.episodes) > 40:
        raise ValueError("At most 40 episodes in a year. Remove an existing episode before adding more.")
    existing = [ep.model_dump(by_alias=True) for ep in context.episodes]
    used = {ep["id"] for ep in existing}
    additions = []
    n = 1
    for ep in proposal.episodes:
        if not ep.settings or not any(ep.settings.values()):
            raise ValueError("Each proposed episode must change at least one Year setting.")
        while f"EP-{n}" in used:
            n += 1
        additions.append({**ep.model_dump(by_alias=True), "id": f"EP-{n}"})
        used.add(f"EP-{n}")
    for ep in existing + additions:
        supported_fields(ep["settings"], settings_schema())
    # Validate the combined timeline, including interactions with the current base and earlier episodes.
    resolve_episode_days(cfg, parse_episodes(cfg, existing + additions))
    summary = episode_changes(cfg, existing, additions)
    limits = list(proposal.limitations)[:17]
    for note in ("These tweaks add dated Year episodes; your town and base configuration stay the same.",
                 "The engine models calendar year 2026 only; direct map commands use the map controls.",
                 "Annual outages/leaks feed contact demand; they do not automatically change meter reads."):
        if note not in limits:
            limits.append(note)
    return {**proposal.model_dump(by_alias=True), "limitations": limits,
            "runTo": max(context.asOf, *(ep.to or "2026-12-31" for ep in proposal.episodes)), "changes": summary}


def presets() -> list[dict]:
    return [{"preset": t["preset"], "name": t["preset"].replace("_", " ").capitalize(),
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
    cfg = SimConfig() if preset == DEFAULT_BASE else preset_config(preset)
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


def leaf_values(values: dict, prefix: str = ""):
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from leaf_values(value, path)
        else:
            yield path, value


def at_path(values: dict, path: str):
    for key in path.split("."):
        values = values[key]
    return values


def input_changes(values: dict, before: dict, after: dict, schema: dict, scope: str, index=None) -> list[dict]:
    out = []
    for path, value in leaf_values(values):
        field = schema
        for key in path.split("."):
            field = expand(field, schema)["properties"][key]
        field = expand(field, schema)
        unit = field.get("x-unit", "")
        percentage = (field.get("type") == "number" and not unit
                      and field.get("minimum", -1) >= 0 and field.get("maximum", 2) <= 1)
        out.append({"path": path, "scope": scope, "episodeIndex": index, "input": value,
                    "before": at_path(before, path), "after": at_path(after, path),
                    "title": " · ".join([k.replace("_", " ").capitalize() for k in path.split(".")[:-1]]
                                         + [field.get("title", path.split(".")[-1].replace("_", " ").capitalize())]),
                    "impact": field.get("x-impact") or field.get("description") or "See the configuration definition.",
                    "reach": field.get("x-reach", "operations" if scope == "operations" else "year"),
                    "unit": unit, "percentage": percentage, "valueType": field.get("type", ""),
                    "minimum": field.get("minimum"), "maximum": field.get("maximum"), "choices": field.get("enum", [])})
    return out


def episode_changes(cfg: SimConfig, existing: list[dict], additions: list[dict]) -> list[dict]:
    out = []
    prior = list(existing)
    before_days = resolve_episode_days(cfg, parse_episodes(cfg, prior))
    for index, ep in enumerate(additions):
        after_days = resolve_episode_days(cfg, parse_episodes(cfg, prior + [ep]))
        start = (date.fromisoformat(ep["from"]) - date(2026, 1, 1)).days
        end = (date.fromisoformat(ep.get("to") or "2026-12-31") - date(2026, 1, 1)).days
        rows = input_changes(ep["settings"], before_days[start].model_dump(mode="json"),
                             after_days[end].model_dump(mode="json"), settings_schema(), "episode", index)
        for row in rows:
            row["period"] = f"{ep['title']} · {ep['from']} → {ep.get('to') or '2026-12-31'}"
            for key, days in (("beforeRange", before_days), ("afterRange", after_days)):
                values = [at_path(days[d].model_dump(mode="json"), row["path"]) for d in range(start, end + 1)]
                if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                    row[key] = [min(values), max(values)]
        out.extend(rows)
        prior.append(ep)
        before_days = after_days
    return out


def grouped_ops_defaults(cfg: SimConfig) -> dict:
    root = ops_schema(run_defaults(cfg))
    full = run_defaults(cfg)
    return {g: {k: full[k] for k in field["properties"]} if field.get("x-flat") else full.get(g)
            for g, field in root["properties"].items()}


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
    limits = list(proposal.limitations)[:15]
    for note in ("The engine models calendar year 2026 only.",
                 "Prepared towns and baseline assumptions are Ontario-based; regional calibration is not automatic.",
                 "Homes are not the same count as customer accounts.",
                 "Annual outages/leaks feed contact demand; they do not automatically change meter reads."):
        if note not in limits:
            limits.append(note)
    if ops:
        note = "Operations settings affect map days; Year annual incidents are configured separately through outages settings."
        if note not in limits:
            limits.append(note)
    return {**proposal.model_dump(by_alias=True), "episodes": episodes, "opsSettings": ops,
            "townRef": ref, "townId": pack["townId"] if ref == proposal.preset else cfg.town_id(),
            "townName": pack["name"] + (" · customised" if ref != proposal.preset else ""),
            "homes": cfg.town.houses, "limitations": limits,
            "changes": input_changes(town, base.model_dump(mode="json"), cfg.model_dump(mode="json"), config_schema(), "town")
                       + input_changes(proposal.settings, cfg.model_dump(mode="json"), run_cfg.model_dump(mode="json"), settings_schema(), "run")
                       + input_changes(proposal.operations, grouped_ops_defaults(cfg),
                                       deep_merge(grouped_ops_defaults(cfg), proposal.operations), ops_schema(run_defaults(cfg)), "operations")
                       + episode_changes(run_cfg, [], episodes)}
