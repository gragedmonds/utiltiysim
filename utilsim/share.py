"""Simulation files: one simulation's complete inputs as a small JSON file to copy to another Utility Studio.

A file carries everything that shapes a simulation: the prepared town (preset) and the town settings that differ from
it, the number of homes, the run seed, the run and map-day settings, the goals, the results date, the name, and every
episode on the year (the starting scenario's and the ones inflicted later, each with its dates, ramp, settings and
sporadic pattern with its seed). Nothing is looked up anywhere: the same engine build rebuilds the same simulation
from the file alone, offline. The file is plain JSON, so it is readable and can be kept, mailed or versioned.

Every file has a handle, three plain words with an animal in the middle ("brave-otter-harbour"), derived from what
the simulation runs on: two people holding the same simulation see the same handle, and a changed setting changes it.
It names the file and labels the simulation; the data is in the file.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import orjson

SCHEMA = "utility-studio-simulation/1.0"
SUFFIX = ".utilitysim.json"
MAX_FILE_BYTES = 2_000_000

ADJECTIVES = ("amber", "bold", "brave", "bright", "brisk", "calm", "clever", "cosy", "crisp", "daring", "deft", "eager",
              "early", "fair", "fancy", "fierce", "fond", "frosty", "gentle", "glad", "golden", "grand", "happy", "hardy",
              "hazel", "humble", "jolly", "keen", "kind", "lively", "lucky", "merry", "mighty", "misty", "modest", "nimble",
              "noble", "patient", "plucky", "proud", "quick", "quiet", "rapid", "ready", "rosy", "rustic", "sage", "sharp",
              "silver", "sleepy", "smart", "snowy", "spry", "steady", "stout", "sunny", "swift", "tidy", "trusty", "vivid",
              "warm", "wise", "witty", "zesty")
ANIMALS = ("badger", "beaver", "bison", "bobcat", "camel", "cougar", "coyote", "crane", "deer", "dingo", "dolphin",
           "donkey", "eagle", "egret", "falcon", "ferret", "finch", "fox", "gannet", "gecko", "gibbon", "goose", "hare",
           "heron", "hornet", "ibis", "impala", "jackal", "jaguar", "kestrel", "koala", "lemur", "lynx", "magpie", "marmot",
           "marten", "moose", "narwhal", "newt", "ocelot", "orca", "osprey", "otter", "owl", "panda", "parrot", "pelican",
           "penguin", "pika", "plover", "puffin", "quail", "rabbit", "raven", "robin", "salmon", "seal", "sparrow", "stoat",
           "swan", "tapir", "toucan", "walrus", "wombat")
PLACES = ("abbey", "arbour", "bay", "beacon", "bend", "bluff", "bridge", "brook", "canal", "cape", "cove", "creek", "dale",
          "delta", "dune", "falls", "fen", "field", "ford", "forge", "garden", "glen", "grove", "harbour", "haven", "heath",
          "hill", "hollow", "inlet", "island", "junction", "knoll", "lagoon", "lake", "landing", "lane", "ledge", "marsh",
          "meadow", "mill", "moor", "orchard", "park", "pass", "peak", "pier", "plain", "point", "pond", "quarry", "quay",
          "ravine", "reach", "ridge", "river", "shore", "spring", "square", "station", "strand", "summit", "valley", "wharf",
          "wood")

# What the handle is made of: the inputs that change a run (not the name or notes, which are free to edit).
IDENTITY = ("preset", "execution", "totalHomes", "townOverrides", "settings", "operations", "seed", "asOf", "episodes")


def _canonical(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():  # browser JSON turns 2.0 into 2
        return int(value)
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def handle(simulation: dict) -> str:
    """Three words from a digest of the simulation's run-changing inputs: adjective, animal, place."""
    identity = {k: _canonical(simulation.get(k)) for k in IDENTITY}
    digest = hashlib.sha256(orjson.dumps(identity, option=orjson.OPT_SORT_KEYS)).digest()
    n = int.from_bytes(digest[:4], "big")
    return "-".join((ADJECTIVES[n % len(ADJECTIVES)], ANIMALS[n // 64 % len(ANIMALS)], PLACES[n // 4096 % len(PLACES)]))


def filename(simulation: dict) -> str:
    return handle(simulation) + SUFFIX


def export_file(simulation: dict, engine_build: str | None = None) -> dict:
    """The file for a validated proposal (by alias)."""
    from api._agent_config import Proposal

    keep = Proposal.model_validate(simulation).model_dump(by_alias=True)
    return {"schemaVersion": SCHEMA, "handle": handle(keep), "name": keep["name"],
            "exported": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            **({"engineBuild": engine_build} if engine_build else {}), "simulation": keep}


class FileError(ValueError):
    """The file cannot be read; the message is for the person who chose it."""


def read_file(data: Any) -> dict:
    """The proposal (by alias) a file holds; validate it with api/_agent_config.py validate_proposal afterwards."""
    if not isinstance(data, dict) or data.get("schemaVersion") != SCHEMA:
        version = data.get("schemaVersion") if isinstance(data, dict) else None
        if isinstance(version, str) and version.startswith("utility-studio-simulation/"):
            raise FileError("This simulation file was made with a newer version of Utility Studio. Update the app to open it.")
        raise FileError("This is not a Utility Studio simulation file.")
    simulation = data.get("simulation")
    if not isinstance(simulation, dict) or not isinstance(simulation.get("preset"), str):
        raise FileError("This simulation file has no simulation in it.")
    if not isinstance(simulation.get("summary"), str) or not simulation["summary"]:
        simulation = {**simulation, "summary": "Imported from a simulation file."}
    return simulation
