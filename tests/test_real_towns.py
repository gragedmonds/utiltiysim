"""Real-place presets: frozen extracts pinned by SHA-256, sized by their own streets, and they generate cleanly."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import app
from utilsim.config import SimConfig, list_presets, load_preset
from utilsim.config.presets import deep_merge
from utilsim.gen.pipeline import generate
from utilsim.gen.roads.build import REPO_ROOT
from utilsim.gen.roads.osm import load_osm
from utilsim.gen.sources import list_sources, natural_houses
from utilsim.io.snapshot import build_snapshot
from utilsim.validate import validate_town

DEFAULT_SOURCE = SimConfig().town.osm_source
REAL = [p["name"] for p in list_presets()
        if load_preset(p["name"]).town.skeleton == "osm" and load_preset(p["name"]).town.osm_source != DEFAULT_SOURCE]


def test_real_town_presets_exist():
    assert "ayr" in REAL


@pytest.mark.parametrize("name", REAL)
def test_preset_pins_its_extract(name):
    t = load_preset(name).town
    raw, _ = load_osm(REPO_ROOT / t.osm_source, t.osm_sha256)  # raises if the file changed
    assert raw["attribution"] == "© OpenStreetMap contributors" and "odbl" in raw["license"]
    assert raw["source"] == "Overpass API" and raw["place"]["query"] and len(raw["bbox"]) == 4
    assert t.expansion == "none" and 20 <= t.houses <= 10_000


def test_natural_size_is_reproducible():
    t = load_preset("ayr").town
    base = deep_merge(SimConfig().model_dump(mode="json"),
                      {"town": {"skeleton": "osm", "osm_source": t.osm_source, "osm_sha256": t.osm_sha256}})
    houses, _ = natural_houses(base)
    assert houses == t.houses


def test_ayr_generates_a_valid_town():
    town = generate(load_preset("ayr"))
    res = validate_town(town)
    assert res["valid"], res["errors"][:5]
    assert town.geo.source["type"] == "osm" and town.geo.source["expansion"] == "none"
    assert town.geo.source["label"] == "Ayr street snapshot"
    snap = build_snapshot(town, include_reads=False, detail="viewer", embed_state=False)
    assert snap["homes"] == load_preset("ayr").town.houses and snap["count"] == len(snap["premises"])


def test_sources_listing_and_endpoint():
    files = {s["file"]: s for s in list_sources()}
    ayr = files["data/osm/ayr-ontario.json"]
    assert ayr["place"]["name"] == "Ayr" and [p["preset"] for p in ayr["presets"]] == ["ayr"]
    assert files["data/osm/whitby-roads.json"]["presets"]
    body = TestClient(app).get("/api/sources").json()
    assert {s["file"] for s in body["sources"]} == set(files)


@pytest.mark.slow
@pytest.mark.parametrize("name", REAL)
def test_every_real_town_generates_valid(name):
    town = generate(load_preset(name))
    res = validate_town(town)
    assert res["valid"], res["errors"][:5]
    # Substation exits carry the whole substation: parallel getaway cables when one is not enough.
    for e in town.networks["electric"].edges:
        if e.attrs.get("conductor", "").endswith("duct bank)"):
            assert e.attrs["parallelCables"] >= 2 and e.attrs["capacityKVA"] >= e.attrs["designKVA"]
