"""Recompute golden digests (run after an intentional output change, together with a GENERATOR_VERSION bump)."""

import hashlib
import json
from pathlib import Path

import orjson

from utilsim.config import load_preset
from utilsim.gen.pipeline import generate
from utilsim.io.snapshot import build_snapshot
from utilsim.version import GENERATOR_VERSION

CASES = {"village-120-T120": ("village", "T120", 120), "village-600-42": ("village", "42", 600)}
SECTIONS = ["roads", "premises", "buildings", "parcels", "facilities", "networks", "accounts", "contracts", "meters",
            "registers", "mrus", "sampleReads"]


def digests(preset: str, seed: str, houses: int) -> dict:
    snap = build_snapshot(generate(load_preset(preset, seed=seed, houses=houses)))
    out = {k: hashlib.sha256(orjson.dumps(snap[k], option=orjson.OPT_SORT_KEYS)).hexdigest()[:16] for k in SECTIONS}
    out["townId"] = snap["id"]
    return out


def main() -> None:
    data = {"generatorVersion": GENERATOR_VERSION, "cases": {k: digests(*v) for k, v in CASES.items()}}
    p = Path(__file__).resolve().parents[1] / "tests" / "golden" / "digests.json"
    p.write_text(json.dumps(data, indent=2) + "\n")
    print(p)


if __name__ == "__main__":
    main()
