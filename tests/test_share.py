"""Simulation codes: everything that shapes a simulation, as one uppercase code any copy of the app rebuilds it from."""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from api._agent_config import Proposal, validate_proposal
from api._setup import REGIONS
from api.app import app
from utilsim.config.presets import deep_merge
from utilsim.m2c.scenarios import BY_ID
from utilsim.share import (
    CodeError,
    b32decode,
    b32encode,
    build_dictionary,
    dated_episodes,
    decode,
    dictionary,
    encode,
    grouped,
)

# The committed dictionary is part of the code format: a change here is a new version, not a regeneration.
DICTIONARY_SHA256 = "cfae08c8e08a2d89913a82a6963d01b056a0acecd015b66b9f5751c16a87d0f6"


def typical():
    chaos = dated_episodes(BY_ID["starter_chaos"], "2026-01-01")
    flu = dated_episodes(BY_ID["flu_spikes"], "2026-02-02")
    flu[0]["to"] = "2026-05-29"
    flu[0]["pattern"] = {**flu[0]["pattern"], "seed": "local:3f2a"}
    return {"execution": "local", "totalHomes": 5000, "name": "Can VEE cope with a rough winter?", "goals": ["vee", "billing"],
            "region": REGIONS[0]["name"], "preset": "small_town", "seed": "WINTER-7", "asOf": "2026-06-30",
            "townOverrides": deep_merge({"town": {"houses": 2000}, "customers_billing": {"services": ["electric", "water"]}},
                                        REGIONS[0]["overrides"]),
            "settings": {"process": {"analysts": 5}, "contact": {"agents": 3}, "reading": {"ami_missed_read": 0.05}},
            "operations": {}, "summary": "A rough winter",
            "episodes": chaos + flu + [{"title": "Half staff", "from": "2026-09-01", "to": "2026-09-30", "ramp": 3,
                                        "settings": {"process": {"analysts": "*0.5"}}}]}


def same_simulation(a, b):
    """Two validated proposals that run the same simulation: town, homes, settings, seed, date and every episode."""
    keys = ("townRef", "townId", "homes", "settings", "opsSettings", "seed", "asOf", "goals", "execution", "totalHomes")
    return all(a[k] == b[k] for k in keys) and a["episodes"] == b["episodes"]


def test_a_code_rebuilds_the_same_simulation_and_stays_short():
    p = typical()
    code = encode(p)
    assert code.startswith("UTS1") and code == code.upper() and code.isalnum()
    assert len(code) < 400, len(code)  # a region, three settings, a seed and five episodes
    back = decode(code)
    assert same_simulation(validate_proposal(Proposal.model_validate(p)), validate_proposal(Proposal.model_validate(back)))
    assert back["name"] == p["name"] and back["region"] == p["region"] and back["episodes"][2]["pattern"]["seed"] == "local:3f2a"
    # A plain small town is far shorter; the name is most of it.
    small = encode({"name": "Winter VEE", "preset": "small_town", "townOverrides": {"town": {"houses": 500}}, "summary": "x"})
    assert len(small) < 90, len(small)
    assert decode(small)["townOverrides"] == {"town": {"houses": 500}} and decode(small)["asOf"] == "2026-03-31"


def test_codes_survive_how_people_paste_them():
    code = encode(typical())
    shown = grouped(code)
    assert shown.startswith("UTS1-") and shown.replace("-", "") == code and all(len(g) <= 5 for g in shown.split("-")[1:])
    assert decode(shown.lower()) == decode(code)
    assert decode(" " + shown.replace("-", " \n") + " ") == decode(code)
    # Crockford: a 0 read as O, a 1 read as I or L, decode the same.
    assert decode(code.replace("0", "O").replace("1", "I")) == decode(code)


def test_damage_and_other_versions_are_refused_with_a_reason():
    code = encode(typical())
    for bad, reason in ((code[:-4] + "AAAA", "damaged"), (code[:40], "damaged"), ("UTS9" + code[4:], "newer version"),
                        ("hello", "starts with UTS1"), ("UTS1", "too short"), ("UTS1" + "U" * 20, "cannot appear")):
        with pytest.raises(CodeError, match=reason):
            decode(bad)
    assert b32decode(b32encode(b"\x00\xff\x10")) == b"\x00\xff\x10"
    with pytest.raises(CodeError):
        decode("UTS1" + b32encode(b"\xff" * 20))


def test_overrides_equal_to_the_preset_are_not_carried():
    base = typical()
    base["townOverrides"]["housing"] = {"pool_rate": validate_proposal(Proposal.model_validate(base))["changes"] and 0.06}
    noisy = dict(base, settings={**base["settings"], "vee": {"high_ratio": 1.75}})  # whatever the preset already has
    from api._agent_config import preset_config
    noisy["settings"]["vee"] = {"high_ratio": preset_config("small_town").vee.high_ratio}
    assert len(encode(noisy)) <= len(encode(base)) + 2


def test_the_dictionary_is_frozen():
    assert hashlib.sha256(dictionary()).hexdigest() == DICTIONARY_SHA256
    # What the next version would be built from still fits zlib's window; regenerating v1 in place is not allowed.
    assert len(build_dictionary()) <= 32768


def test_the_studio_endpoints():
    client = TestClient(app)
    r = client.post("/api/share/encode", json={k: v for k, v in typical().items() if k != "summary"})
    assert r.status_code == 200, r.text
    assert r.json()["chars"] == len(r.json()["code"]) and r.json()["grouped"].startswith("UTS1-")
    r2 = client.post("/api/share/decode", json={"code": r.json()["grouped"]})
    assert r2.status_code == 200 and r2.json()["proposal"]["homes"] == 5000 and r2.json()["proposal"]["townRef"].startswith("small_town~")
    assert client.post("/api/share/decode", json={"code": "nope"}).status_code == 422
    assert "UTS1" in client.post("/api/share/decode", json={"code": "nope"}).json()["detail"]
    bad = typical()
    bad["townOverrides"]["town"]["houses"] = 10**7
    assert client.post("/api/share/encode", json=bad).status_code == 422
