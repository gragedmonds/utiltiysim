"""The local runner's year: the days a sporadic episode strikes, without a run (POST /api/m2c/episodes/preview), are
the days a run strikes; a job's sporadic episodes get the model's own pattern seed, so every district (a separate
town with its own run seed) strikes the same days."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api._m2c import RunRequest, run_for
from api._portal import pattern_seed, prepare_recipe
from api.index import app
from utilsim.m2c import trend
from utilsim.worker.contracts import JobFile, check_job, recipe_key

HEADEND = {"reading": {"ami_missed_read": 0.9}}
# As the Studio's "When it strikes" controls send it (year-page.js draftPattern).
SPIKES = {"kind": "spikes", "count": 6, "length": [1, 2], "strength": [0.7, 1.0], "workdays": True,
          "independent": False}
SEEDED = {**SPIKES, "seed": pattern_seed("model-a")}


def ep(settings, pattern=None, frm="2026-01-05", to="2026-06-30", title="Head end down", eid="EP-1"):
    out = {"id": eid, "title": title, "from": frm, "to": to, "settings": settings}
    return {**out, "pattern": pattern} if pattern is not None else out


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_preview_marks_the_days_a_run_strikes(client):
    eps = [ep(HEADEND, SEEDED), ep({"process": {"analysts": 1}}, frm="2026-09-01", to=None, title="Short", eid="EP-2")]
    r = client.post("/api/m2c/episodes/preview", json={"town": "small_town", "year": 2026, "episodes": eps})
    assert r.status_code == 200, r.text
    got = {e["id"]: e for e in r.json()["episodes"]}
    # A run on another seed (a district's own) strikes the same days: the pattern's seed holds them.
    run = run_for(RunRequest(town="small_town", episodes=eps, seed="district-0007"))
    want = {e["id"]: e for e in trend.episode_json(run)}
    sporadic = got["EP-1"]
    assert sporadic["hits"] == want["EP-1"]["hits"] and 6 <= len(sporadic["hits"]) <= 12
    assert sporadic["pattern"] == want["EP-1"]["pattern"] == SEEDED
    assert (sporadic["from"], sporadic["to"], sporadic["title"]) == ("2026-01-05", "2026-06-30", "Head end down")
    # A steady episode has no pattern and no hits; an open end is the year's last day.
    assert got["EP-2"] == {"id": "EP-2", "title": "Short", "from": "2026-09-01", "to": "2026-12-31"}
    # The town defaults to small_town; nothing to preview is an empty list.
    assert client.post("/api/m2c/episodes/preview", json={"episodes": eps}).json()["episodes"] == r.json()["episodes"]
    assert client.post("/api/m2c/episodes/preview", json={}).json()["episodes"] == []


def test_a_bad_episode_is_refused_with_the_engines_message(client):
    tight = ep(HEADEND, {**SEEDED, "count": 9}, frm="2026-01-05", to="2026-01-07")
    r = client.post("/api/m2c/episodes/preview", json={"episodes": [tight]})
    assert r.status_code == 422 and r.json()["detail"] == "episode EP-1: 9 spikes do not fit in 3 working days"
    unknown = client.post("/api/m2c/episodes/preview", json={"episodes": [ep({"reading": {"nope": 1}}, SEEDED)]})
    assert unknown.status_code == 422 and "unknown setting reading.nope" in unknown.json()["detail"]
    shape = client.post("/api/m2c/episodes/preview", json={"episodes": [ep(HEADEND, {"kind": "days", "count": 2})]})
    assert shape.status_code == 422  # the request model refuses it before the engine sees it


def local_job(episodes, model_id="model-a"):
    return prepare_recipe({"proposal": {"execution": "local", "totalHomes": 25000, "name": "Regional utility",
                                        "summary": "Year scenarios", "preset": "small_town", "asOf": "2026-06-30",
                                        "episodes": episodes},
                           "modelId": model_id, "chunkSize": 2000, "staffing": "independent-districts"})


def test_prepare_gives_sporadic_episodes_the_models_seed():
    steady = {"title": "Half staff", "from": "2026-03-02", "to": "2026-03-31", "ramp": 2,
              "settings": {"process": {"analysts": "*0.5"}}}
    own = {"title": "Own days", "from": "2026-02-02", "to": "2026-05-29", "settings": HEADEND,
           "pattern": {**SPIKES, "seed": "mine"}}
    plain = {"title": "Head end down", "from": "2026-01-05", "to": "2026-06-30", "settings": HEADEND,
             "pattern": SPIKES}
    recipe = local_job([plain, steady, own])
    request = recipe["request"]["episodes"]
    assert [e["pattern"] and e["pattern"].get("seed") for e in request] == ["local:model-a", None, "mine"]
    assert recipe["proposal"]["episodes"][0]["pattern"] == SEEDED  # the revision's proposal says so too
    # An episode without a pattern is unchanged.
    assert request[1] == {**steady, "id": "EP-2", "pattern": None}
    assert plain["pattern"] == SPIKES and "seed" not in SPIKES  # the caller's value is not changed
    # The seed is what a job file with the seed already in it would carry: one recipe either way.
    assert recipe_key(local_job([{**plain, "pattern": SEEDED}, steady, own])) == recipe_key(recipe)
    job = JobFile(jobId="a" * 32, revision=1, recipeKey=recipe_key(recipe), recipe=recipe).model_dump()
    assert check_job(job)["recipe"]["request"]["episodes"][0]["pattern"]["seed"] == "local:model-a"
    # Without episodes nothing is added.
    assert local_job([])["request"]["episodes"] == []
    assert pattern_seed("x" * 100) == ("local:" + "x" * 100)[:64]


def test_a_library_scenario_with_a_pattern_makes_a_job():
    """The scenario library's sporadic templates leave the strike flags out; a job made from them (the setup wizard,
    an imported job) passes the job checks, which see the unset flags as null."""
    from utilsim.m2c import scenarios as sc

    t = sc.BY_ID["sickness_here_and_there"]["episodes"][0]
    assert "workdays" not in t["pattern"]
    recipe = local_job([{"title": t["title"], "from": "2026-02-02", "to": "2026-06-01", "settings": t["settings"],
                         "pattern": t["pattern"]}])
    job = JobFile(jobId="b" * 32, revision=1, recipeKey=recipe_key(recipe), recipe=recipe).model_dump()
    assert check_job(job)["recipe"]["request"]["episodes"][0]["pattern"]["kind"] == "days"
