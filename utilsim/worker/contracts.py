"""Portable recipes and small result receipts; executable code and paths are never inputs."""
from __future__ import annotations

import hashlib
from typing import Any, Literal

import orjson
from pydantic import BaseModel, ConfigDict, Field

PROTOCOL = 'local-job/1.0'


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Recipe(Strict):
    schemaVersion: Literal['local-job/1.0'] = PROTOCOL
    name: str = Field(min_length=1, max_length=100)
    modelId: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
    homes: int = Field(ge=20, le=500_000)
    chunkSize: int = Field(default=10000, ge=20, le=10000)
    staffing: Literal['independent-districts']
    config: dict[str, Any]
    request: dict[str, Any]
    proposal: dict[str, Any] = Field(default_factory=dict)


def digest(value):
    # Browser JSON round-trips turn 2.0 into 2. Canonicalize equal numeric values.
    def canonical(v):
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, dict):
            return {k: canonical(x) for k, x in v.items()}
        if isinstance(v, list):
            return [canonical(x) for x in v]
        return v
    return hashlib.sha256(orjson.dumps(canonical(value), option=orjson.OPT_SORT_KEYS)).hexdigest()


def recipe_key(recipe):
    return digest({k: v for k, v in recipe.items() if k not in ('name', 'modelId', 'proposal')})


class JobFile(Strict):
    schemaVersion: Literal['local-job-file/1.0'] = 'local-job-file/1.0'
    jobId: str = Field(pattern=r'^[a-f0-9]{32}$')
    revision: int = Field(ge=1)
    recipeKey: str = Field(pattern=r'^[a-f0-9]{64}$')
    recipe: Recipe


class DistrictReceipt(Strict):
    id: str = Field(pattern=r'^district-\d{4,5}$')
    runKey: str = Field(pattern=r'^[a-f0-9]{64}$')
    manifestSha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    homes: int = Field(ge=20, le=10000)


class ResultFile(Strict):
    schemaVersion: Literal['local-result-file/1.0'] = 'local-result-file/1.0'
    jobId: str = Field(pattern=r'^[a-f0-9]{32}$')
    revision: int = Field(ge=1)
    recipeKey: str = Field(pattern=r'^[a-f0-9]{64}$')
    engineBuild: str = Field(pattern=r'^[a-f0-9]{64}$')
    districts: list[DistrictReceipt] = Field(min_length=1, max_length=25000)
    rollup: dict[str, Any]
    timings: dict[str, Any]


def check_job(value):
    job = JobFile.model_validate(value).model_dump()
    if recipe_key(job['recipe']) != job['recipeKey']:
        raise ValueError('Job inputs do not match their checksum.')
    # Same bounded engine validation for online and manually imported jobs.
    from api._m2c import RunRequest
    from utilsim.config.model import SimConfig
    from utilsim.m2c.run import parse_episodes, resolve_episode_days, resolve_settings

    cfg = SimConfig.model_validate(job['recipe']['config'])
    req = job['recipe']['request']
    if set(req) - {'settings', 'episodes', 'seed', 'asOf', 'actionsByDistrict'}:
        raise ValueError('Unsupported batch inputs.')
    import re

    from api._m2c import Action
    for district, actions in req.get('actionsByDistrict', {}).items():
        if not re.fullmatch(r'district-\d{4,5}', district):
            raise ValueError('Invalid record checkpoint.')
        for action in actions:
            Action.model_validate(action)
    parsed = RunRequest.model_validate({'town': 'district', **req})
    resolved = resolve_settings(cfg, parsed.settings)
    resolve_episode_days(resolved, parse_episodes(resolved, [e.model_dump(by_alias=True) for e in parsed.episodes]))
    return job
