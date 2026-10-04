"""Published JSON Schemas (``schemas/``) and validation helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import orjson
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
NAMES = {
    "local-job-1.0": "local-job-1.0.schema.json",
    "local-result-1.0": "local-result-1.0.schema.json",
    "utility-town-2.0": "utility-town-2.0.schema.json",
    "utility-state-1.0": "utility-state-1.0.schema.json",
    "utility-replay-1.0": "utility-replay-1.0.schema.json",
    "meter-read-1.1": "meter-read-1.1.schema.json",
    "vee-input-fixture-1.1": "vee-input-fixture-1.1.schema.json",
    "config": "config.schema.json",
    "openapi": "openapi.json",
}


def load(name: str) -> dict:
    return orjson.loads((SCHEMA_DIR / NAMES[name]).read_bytes())


@lru_cache(maxsize=1)
def registry() -> Registry:
    resources = []
    for name in ("utility-town-2.0", "utility-state-1.0", "utility-replay-1.0", "meter-read-1.1",
                 "vee-input-fixture-1.1"):
        doc = load(name)
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load(name), registry=registry())


def errors(name: str, doc: dict, limit: int = 10) -> list[str]:
    out = []
    for e in validator(name).iter_errors(doc):
        out.append(f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message[:200]}")
        if len(out) >= limit:
            break
    return out


def generated() -> dict[str, dict]:
    """Schemas generated from code (config UI-hint schema, OpenAPI)."""
    from api.app import app
    from utilsim.config import config_schema

    return {"config": config_schema(), "openapi": app.openapi()}


def write_generated(out: Path | None = None) -> list[Path]:
    out = out or SCHEMA_DIR
    paths = []
    for name, doc in generated().items():
        p = out / NAMES[name]
        p.write_bytes(orjson.dumps(doc, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS) + b"\n")
        paths.append(p)
    return paths
