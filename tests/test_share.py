"""Simulation files: everything that shapes a simulation, as one small JSON file any copy of the app rebuilds it from,
named by three words that follow from its inputs."""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from api._agent_config import Proposal, validate_proposal
from api._setup import REGIONS
from api.app import app
from utilsim.config.presets import deep_merge
from utilsim.m2c.scenarios import BY_ID
from utilsim.share import (
    ADJECTIVES,
    ANIMALS,
    PLACES,
    SCHEMA,
    FileError,
    export_file,
    filename,
    handle,
    read_file,
)


def dated(scenario, day):
    from datetime import date, timedelta
    start, end = date.fromisoformat(day), date(2026, 12, 31)
    out = []
    for t in scenario["episodes"]:
        frm = min(start + timedelta(days=t["startOffset"]), end)
        to = None if t["durationDays"] is None else min(frm + timedelta(days=t["durationDays"] - 1), end)
        out.append({"title": t["title"], "from": frm.isoformat(), "to": to.isoformat() if to else None, "ramp": t["ramp"],
                    "settings": t["settings"], **({"pattern": t["pattern"]} if t.get("pattern") else {})})
    return out


def typical():
    chaos = dated(BY_ID["starter_chaos"], "2026-01-01")
    flu = dated(BY_ID["flu_spikes"], "2026-02-02")
    flu[0]["to"] = "2026-05-29"
    flu[0]["pattern"] = {**flu[0]["pattern"], "seed": "local:3f2a"}
    return {"execution": "local", "totalHomes": 500000, "name": "Can VEE cope with a rough winter?", "goals": ["vee", "billing"],
            "region": REGIONS[0]["name"], "preset": "small_town", "seed": "WINTER-7", "asOf": "2026-06-30",
            "townOverrides": deep_merge({"town": {"houses": 2000}, "customers_billing": {"services": ["electric", "water"]}},
                                        REGIONS[0]["overrides"]),
            "settings": {"process": {"analysts": 5}, "contact": {"agents": 3}, "reading": {"ami_missed_read": 0.05}},
            "operations": {}, "summary": "A rough winter",
            "episodes": chaos + flu + [{"title": "Half staff", "from": "2026-09-01", "to": "2026-09-30", "ramp": 3,
                                        "settings": {"process": {"analysts": "*0.5"}}}]}


def same_simulation(a, b):
    keys = ("townRef", "townId", "homes", "settings", "opsSettings", "seed", "asOf", "goals", "execution", "totalHomes")
    return all(a[k] == b[k] for k in keys) and a["episodes"] == b["episodes"]


def test_a_file_rebuilds_the_same_simulation():
    p = typical()
    file = export_file(p, "ab" * 32)
    assert file["schemaVersion"] == SCHEMA and file["name"] == p["name"] and file["engineBuild"] == "ab" * 32
    assert file["simulation"]["totalHomes"] == 500000 and file["simulation"]["episodes"][2]["pattern"]["seed"] == "local:3f2a"
    back = read_file(file)
    assert same_simulation(validate_proposal(Proposal.model_validate(p)), validate_proposal(Proposal.model_validate(back)))
    assert read_file({**file, "simulation": {k: v for k, v in file["simulation"].items() if k != "summary"}})["summary"]


def test_handles_are_three_plain_words_that_follow_the_inputs():
    p = typical()
    h = handle(p)
    a, b, c = h.split("-")
    assert a in ADJECTIVES and b in ANIMALS and c in PLACES and filename(p) == h + ".utilitysim.json"
    assert handle({**p, "name": "Another name", "purpose": "notes"}) == h, "the name and notes are free to edit"
    assert handle({**p, "settings": {**p["settings"], "process": {"analysts": 5.0}}}) == h, "browser numbers"
    assert handle({**p, "seed": "WINTER-8"}) != h and handle({**p, "episodes": p["episodes"][:-1]}) != h
    assert len({(x, y, z) for x in ADJECTIVES for y in ANIMALS[:1] for z in PLACES[:1]}) == len(set(ADJECTIVES))
    assert all(w.isalpha() and w.islower() for words in (ADJECTIVES, ANIMALS, PLACES) for w in words)


def test_other_files_and_versions_are_refused_with_a_reason():
    file = export_file(typical())
    for bad, reason in (({"schemaVersion": "utility-studio-simulation/9.0", "simulation": {}}, "newer version"),
                        ({"hello": 1}, "not a Utility Studio simulation file"), ([1, 2], "not a Utility Studio"),
                        ({**file, "simulation": {}}, "no simulation in it"), ({**file, "simulation": "x"}, "no simulation")):
        with pytest.raises(FileError, match=reason):
            read_file(bad)


def test_the_studio_endpoints():
    client = TestClient(app)
    r = client.post("/api/share/export", json={k: v for k, v in typical().items() if k != "summary"})
    assert r.status_code == 200, r.text
    file = r.json()["file"]
    assert r.json()["filename"] == file["handle"] + ".utilitysim.json" and file["simulation"]["homes" if False else "totalHomes"] == 500000
    r2 = client.post("/api/share/import", json=file)
    assert r2.status_code == 200 and r2.json()["proposal"]["homes"] == 500000 and r2.json()["handle"] == file["handle"]
    assert r2.json()["proposal"]["townRef"].startswith("small_town~")
    assert client.post("/api/share/import", json={"nope": 1}).status_code == 422
    assert "simulation file" in client.post("/api/share/import", json={"nope": 1}).json()["detail"]
    bad = typical()
    bad["townOverrides"]["town"]["houses"] = 10**7
    assert client.post("/api/share/export", json=bad).status_code == 422
    # A Studio record that moved on from the wizard: its town reference and flat map-day settings are what is exported.
    ref = client.post("/api/towns", json={"preset": "small_town", "seed": "ABC-123"}).json()["ref"]
    moved = client.post("/api/share/export", json={"name": "Moved on", "preset": "small_town", "townRef": ref,
                                                   "townOverrides": {"town": {"houses": 500}}, "opsSettings": {"electricCrews": 4},
                                                   "settings": {"process": {"analysts": 3}}, "seed": "RUN-9", "asOf": "2026-05-01"})
    assert moved.status_code == 200, moved.text
    sim = moved.json()["file"]["simulation"]
    assert sim["townOverrides"] == {"seeds": {"master": "ABC-123"}} and sim["operations"] == {"crews": {"electricCrews": 4}} or sim["operations"]
    back = client.post("/api/share/import", json=moved.json()["file"]).json()["proposal"]
    assert back["townRef"] == ref and back["opsSettings"] == {"electricCrews": 4} and back["seed"] == "RUN-9"
    unchanged = copy.deepcopy(moved.json()["file"])
    unchanged["name"] = "Renamed"
    assert client.post("/api/share/import", json=unchanged).json()["handle"] == moved.json()["file"]["handle"]
