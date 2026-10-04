"""Sporadic episodes: a scenario that strikes only some days of its window (a few spikes, or a share of the days
scattered), each day as hard as its drawn strength, so spikes in off days and their knock-on effects can be watched.
The days come from the run's seed; values in between are a share of the way to the episode's; a whole number rounds
up with chance its fraction; days not struck keep the settings in force."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api._agent_config import episode_changes
from api._m2c import RunRequest, run_for
from api.index import app
from utilsim.m2c import daily as daily_mod
from utilsim.m2c import scenarios as sc
from utilsim.m2c import trend
from utilsim.m2c.calendar import calendar
from utilsim.m2c.run import OFF, M2CRun, parse_episodes, resolve_episode_days

CAL = calendar(2026)
DAY = CAL.parse_day


@pytest.fixture(scope="module")
def base() -> M2CRun:
    return run_for(RunRequest(town="small_town"))


def ep(settings, pattern, frm="2026-01-05", to="2026-06-30", title="Sporadic", eid="EP-1"):
    return {"id": eid, "title": title, "from": frm, "to": to, "settings": settings, "pattern": pattern}


HEADEND = {"reading": {"ami_missed_read": 0.9}}
SPIKES = {"kind": "spikes", "count": 6, "length": [1, 2], "strength": [0.7, 1.0]}


def hits(cfg, e, **kw):
    return parse_episodes(cfg, [e], CAL, **kw)[0]["hits"]


def test_spikes_come_every_so_often_on_working_days(base):
    cfg = base.cfg
    h = hits(cfg, ep(HEADEND, SPIKES))
    days = [d for d, _ in h]
    lo, hi = DAY("2026-01-05", 0), DAY("2026-06-30", 0)
    assert 6 <= len(days) <= 12 and all(lo <= d <= hi and CAL.is_bday(d) for d in days)
    assert all(0.7 <= s <= 1.0 for _, s in h)
    # One spike in each sixth of the window's working days, a burst of consecutive working days.
    work = [d for d in range(lo, hi + 1) if CAL.is_bday(d)]
    sixth = [work.index(d) * 6 // len(work) for d in days]
    assert sorted(set(sixth)) == list(range(6))
    for k in range(6):
        idx = [work.index(d) for d, s in zip(days, sixth) if s == k]
        assert 1 <= len(idx) <= 2 and idx == list(range(idx[0], idx[0] + len(idx)))
    # Deterministic; the run's seed moves them, the pattern's own seed holds them; a value change keeps them.
    assert hits(cfg, ep(HEADEND, SPIKES)) == h
    assert hits(cfg, ep(HEADEND, SPIKES), seed="another:m2c") != h
    own = {**SPIKES, "seed": "fixed"}
    assert hits(cfg, ep(HEADEND, own)) == hits(cfg, ep(HEADEND, own), seed="another:m2c")
    assert [d for d, _ in hits(cfg, ep({"reading": {"ami_missed_read": 0.5}}, SPIKES))] == days
    # Calendar days when asked: weekends can be struck.
    every = {**SPIKES, "count": 20, "length": [3, 3], "workdays": False}
    assert any(not CAL.is_bday(d) for d, _ in hits(cfg, ep(HEADEND, every)))


def test_scattered_days_strike_a_share_with_a_strength_each(base):
    cfg = base.cfg
    sick = {"process": {"analysts": "*0.5"}, "contact": {"agents": "*0.5"}}
    pat = {"kind": "days", "share": 0.3, "strength": [0.2, 1.0], "independent": True}
    h = hits(cfg, ep(sick, pat, frm="2026-02-01", to="2026-05-31"))
    work = [d for d in range(DAY("2026-02-01", 0), DAY("2026-05-31", 0) + 1) if CAL.is_bday(d)]
    assert len(h) == round(0.3 * len(work)) and {d for d, _ in h} <= set(work)
    assert all(isinstance(s, list) and len(s) == 2 and all(0.2 <= x <= 1.0 for x in s) for _, s in h)
    assert any(s[0] != s[1] for _, s in h)  # a different mix each day
    one = hits(cfg, ep(sick, {**pat, "independent": False}, frm="2026-02-01", to="2026-05-31"))
    assert all(isinstance(s, float) for _, s in one)


def test_a_strike_goes_part_way_and_whole_numbers_round_by_chance(base):
    cfg = base.cfg.model_copy(update={"process": base.cfg.process.model_copy(update={"analysts": 2})})
    e = ep({"process": {"analysts": "*0.5"}, "vee": {"zero_at_occupied": False}, "reading": {"ami_missed_read": 0.5}},
           {"kind": "days", "share": 1.0, "strength": 0.5}, frm="2026-01-01", to="2026-12-31")
    parsed = parse_episodes(cfg, [e], CAL)
    days = resolve_episode_days(cfg, parsed, CAL)
    struck = [d for d, _ in parsed[0]["hits"]]
    assert len(struck) == sum(CAL.is_bday(d) for d in range(CAL.days))
    for d in struck[:20]:
        c = days[d]
        assert c.reading.ami_missed_read == pytest.approx(cfg.reading.ami_missed_read + (0.5 - cfg.reading.ami_missed_read) * 0.5)
        assert c.vee.zero_at_occupied is False and c.process.analysts in (1, 2)
    short = sum(days[d].process.analysts == 1 for d in struck) / len(struck)
    assert 0.35 < short < 0.65  # 2 → 1.5 on average: one short about half the days
    weekend = next(d for d in range(CAL.days) if not CAL.is_bday(d))
    assert days[weekend].process.analysts == 2 and days[weekend].vee.zero_at_occupied is True


def test_bad_patterns_are_refused(base):
    cfg = base.cfg
    for pattern, msg in [({"kind": "bursts"}, "spikes"), ({"kind": "spikes"}, "count"),
                         ({"kind": "spikes", "count": 61}, "count"), ({"kind": "spikes", "count": 2, "share": 0.2}, "share"),
                         ({"kind": "days", "share": 0}, "share"), ({"kind": "days", "share": 0.2, "length": 2}, "length"),
                         ({"kind": "spikes", "count": 2, "length": [3, 1]}, "length"),
                         ({"kind": "spikes", "count": 2, "length": 1.5}, "whole number"),
                         ({"kind": "spikes", "count": 2, "strength": [0, 0]}, "strength"),
                         ({"kind": "spikes", "count": 2, "strength": 1.5}, "strength"),
                         ({"kind": "spikes", "count": 2, "workdays": "yes"}, "workdays"),
                         ({"kind": "spikes", "count": 2, "colour": "red"}, "unknown pattern"),
                         ({"kind": "spikes", "count": 9}, "do not fit"), ("spikes", "object")]:
        with pytest.raises(ValueError, match=msg):
            parse_episodes(cfg, [ep(HEADEND, pattern, frm="2026-03-02", to="2026-03-06")], CAL)


def test_head_end_hiccups_cascade_from_the_days_struck_only(base):
    e = sc.BY_ID["headend_hiccups"]["episodes"][0]
    run = M2CRun(base.town, ops_factory=base.ops_factory,
                 episodes=[{"id": "EP-1", "title": e["title"], "scenario": "headend_hiccups", "from": "2026-01-05",
                            "to": "2026-07-05", "settings": e["settings"], "pattern": e["pattern"]}])
    struck = {d for d, _ in run.episodes[0]["hits"]}
    first = min(struck)
    tw = base.town
    ami = (base.meter_tech_now[tw.meter_of] == "AMI")[:, None]
    read_day = np.floor(base.read_t[:, 1:]).astype(int)
    on = (base.status[:, 1:] != OFF) & ami

    def missed(r, days):
        sel = on & np.isin(read_day, list(days))
        return int((sel & np.isnan(r.obs[:, 1:])).sum()), int(sel.sum())

    m_run, n = missed(run, struck)
    m_base, _ = missed(base, struck)
    assert n > 0 and m_run > 0.5 * n and m_run > 5 * max(m_base, 1)  # most AMI reads due those days go missing
    quiet = set(range(DAY("2026-01-05", 0), DAY("2026-07-05", 0) + 1)) - struck
    assert missed(run, quiet)[0] <= missed(base, quiet)[0] + 3  # the other days read as usual
    before = read_day < first
    assert np.array_equal(np.isnan(run.obs[:, 1:]) & before, np.isnan(base.obs[:, 1:]) & before)
    # Downstream: more estimates and comm-fail cases after the first strike.
    t, t0 = trend.trend(run, "2026-12-31"), trend.trend(base, "2026-12-31")
    est = sum(m["reads"]["estimated"] for m in t["months"])
    assert est > sum(m["reads"]["estimated"] for m in t0["months"])
    comm = lambda r: sum(1 for c in r.cases if c.created >= first and c.type == "COMM_FAIL")  # noqa: E731
    assert comm(run) > comm(base)
    j = trend.episode_json(run)[0]
    assert j["pattern"]["kind"] == "spikes" and len(j["hits"]) == len(struck)
    assert all(CAL.parse_day(dd, 0) in struck and 0.7 <= s <= 1.0 for dd, s in j["hits"])


def test_sickness_here_and_there_shortens_the_teams_on_some_days(base):
    e = sc.BY_ID["sickness_here_and_there"]["episodes"][0]
    run = M2CRun(base.town, ops_factory=base.ops_factory,
                 episodes=[{"id": "EP-1", "title": e["title"], "from": "2026-02-02", "to": "2026-06-01",
                            "settings": e["settings"], "pattern": e["pattern"]}])
    struck = {d for d, _ in run.episodes[0]["hits"]}
    dl = daily_mod.daily(run)
    people = np.array(dl["staff"]["analysts"]["people"])
    agents = np.array(dl["contact"]["agents"])
    short = {d for d in range(CAL.days) if people[d] < base.cfg.process.analysts or agents[d] < base.cfg.contact.agents}
    assert short and short <= struck  # only on days struck
    assert len(short) < len(struck) + 1 and len(struck) < 0.4 * sum(CAL.is_bday(d) for d in range(CAL.days))
    crews = [run.cfg_at(d).field.crew_meter.per_1000_premises for d in sorted(struck)]
    assert min(crews) < base.cfg.field.crew_meter.per_1000_premises and len(set(crews)) > 2  # strength varies


def test_the_api_and_the_setup_preview_take_patterns(base):
    client = TestClient(app)
    cat = client.get("/api/m2c/scenarios").json()
    assert "sporadic" in {g["id"] for g in cat["groups"]}
    spor = [s for s in cat["scenarios"] if s["group"] == "sporadic"]
    assert len(spor) == 5 and sum(1 for s in spor if s["episodes"][0].get("pattern")) == 4
    body = {"town": "small_town", "asOf": "2026-03-31", "episodes": [ep(HEADEND, SPIKES)]}
    t = client.post("/api/m2c/trend", json=body)
    assert t.status_code == 200
    j = t.json()["episodes"][0]
    assert j["pattern"] == {**SPIKES, "workdays": True, "independent": False} and 6 <= len(j["hits"]) <= 12
    bad = client.post("/api/m2c/trend", json={**body, "episodes": [ep(HEADEND, {"kind": "days", "count": 2})]})
    assert bad.status_code == 422
    rows = episode_changes(base.cfg, [], [ep(HEADEND, SPIKES)])
    assert rows and rows[0]["after"] > 0.5 and "strikes" in rows[0]["period"]
