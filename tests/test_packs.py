"""Committed town packs (packs/) are current: same town ids as the presets, files present, snapshots intact."""

from __future__ import annotations

import gzip
from pathlib import Path

import orjson
import pytest

from utilsim.config import load_preset
from utilsim.io.pack import PACK_VERSION, read_index
from utilsim.version import GENERATOR_VERSION

PACKS = Path(__file__).resolve().parents[1] / "packs"
INDEX = read_index(PACKS)


def test_index_is_current():
    assert INDEX["schemaVersion"] == PACK_VERSION and INDEX["generatorVersion"] == GENERATOR_VERSION
    assert {t["preset"] for t in INDEX["towns"]} >= {"village", "small_town"}


@pytest.mark.parametrize("town", INDEX["towns"], ids=lambda t: t["preset"])
def test_pack_matches_its_preset(town):
    assert town["townId"] == load_preset(town["preset"]).town_id(), \
        "stale pack: run `uv run utilsim pack` after changing the generator or a preset"
    for kind, f in town["files"].items():
        path = PACKS / f["path"]
        assert path.name.startswith(town["townId"] + ".") and path.stat().st_size == f["bytes"], kind
    snap = orjson.loads(gzip.decompress((PACKS / town["files"]["snapshot"]["path"]).read_bytes()))
    assert snap["id"] == town["townId"] and snap["homes"] == town["homes"]
    assert snap["topologyRevision"] == town["topologyRevision"] and snap["indexRevision"] == town["indexRevision"]
    listed = {Path(f["path"]).name for f in town["files"].values()}
    stray = sorted(p.name for p in (PACKS / town["preset"]).iterdir() if p.name not in listed)
    assert not stray, f"old pack files left behind: {stray}"
