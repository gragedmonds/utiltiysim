"""Simulation files (utilsim/share.py) over HTTP: the Studio's Export and Import. No store, no key."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from api._agent_config import Proposal, preset_config, validate_proposal
from api._towns import REF_SEP, config_from_ref
from utilsim.io.run_bundle import engine_build
from utilsim.share import SCHEMA, FileError, export_file, filename, handle, read_file

router = APIRouter()


def _detail(exc: ValidationError) -> str:
    return "; ".join(".".join(str(k) for k in e["loc"]) + (": " if e["loc"] else "") + e["msg"].removeprefix("Value error, ")
                     for e in exc.errors())[:3000]


def _diff(base: Any, value: Any) -> Any:
    if isinstance(value, dict) and isinstance(base, dict):
        out = {k: d for k, v in value.items() if (d := _diff(base.get(k), v)) is not None}
        return out or None
    return None if value == base else value


def town_overrides_from_ref(ref: str, preset: str) -> dict | None:
    """The town overrides a simulation's town reference holds (the exact town it runs on, which may have moved on
    from the wizard's overrides), when the reference builds on the same preset."""
    name, sep, _ = str(ref or "").partition(REF_SEP)
    if name != preset:
        return None
    if not sep:
        return {}
    return _diff(preset_config(preset).generation_dict(), config_from_ref(ref).generation_dict()) or {}


def grouped_operations(flat: dict, preset: str, town: dict) -> dict:
    """A simulation's map-day settings as the engine runs them (flat, api/_agent_config.py validate_operations)
    back in the wizard's grouped form."""
    from utilsim.config.model import SimConfig
    from utilsim.config.presets import deep_merge
    from utilsim.ops.settings_schema import settings_schema
    from utilsim.ops.timeline import run_defaults

    cfg = SimConfig.model_validate(deep_merge(preset_config(preset).model_dump(mode="json"), town))
    out = {}
    for group, field in settings_schema(run_defaults(cfg))["properties"].items():
        if field.get("x-flat"):
            values = {k: flat[k] for k in field["properties"] if k in flat}
        else:
            values = flat.get(group) if isinstance(flat.get(group), dict) else None
        if values:
            out[group] = values
    return out


def from_studio(proposal: dict) -> dict:
    """A Studio record's inputs as a proposal: ``townRef`` and ``opsSettings`` (what the simulation runs with)
    take the place of the wizard's ``townOverrides`` and ``operations`` when present."""
    out = {k: v for k, v in proposal.items() if k not in ("townRef", "opsSettings")}
    if proposal.get("townRef") and isinstance(proposal.get("preset"), str):
        town = town_overrides_from_ref(proposal["townRef"], proposal["preset"])
        if town is not None:
            out["townOverrides"] = town
    if isinstance(proposal.get("opsSettings"), dict) and isinstance(proposal.get("preset"), str):
        out["operations"] = grouped_operations(proposal["opsSettings"], proposal["preset"], out.get("townOverrides") or {})
    return out


@router.post("/api/share/export")
def share_export(proposal: dict):
    """The simulation file for a simulation's inputs: a wizard proposal by alias (``summary`` may be left out), with
    a Studio record's ``townRef`` and flat ``opsSettings`` accepted in place of ``townOverrides`` and ``operations``.
    Answers ``{file, filename}``; the file's ``handle`` is its three-word name."""
    try:
        checked = Proposal.model_validate({"summary": "Shared simulation", **from_studio(proposal)})
        validate_proposal(checked)  # only a simulation this engine accepts becomes a file
        simulation = checked.model_dump(by_alias=True)
        return {"schemaVersion": SCHEMA, "file": export_file(simulation, engine_build()), "filename": filename(simulation)}
    except ValidationError as exc:
        raise HTTPException(422, _detail(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)[:3000]) from exc


@router.post("/api/share/import")
def share_import(file: dict):
    """The validated proposal a simulation file holds, in the shape ``POST /api/setup-agent/validate`` answers
    with, plus its ``handle``."""
    try:
        simulation = read_file(file)
        proposal = validate_proposal(Proposal.model_validate(simulation))
    except FileError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(422, "This simulation file holds settings this version does not accept: " + _detail(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, "This simulation file holds settings this version does not accept: " + str(exc)[:2000]) from exc
    return {"schemaVersion": SCHEMA, "handle": handle(simulation), "proposal": proposal}
