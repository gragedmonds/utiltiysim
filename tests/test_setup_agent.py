"""Claude may suggest configurations; only engine-validated proposals cross into saved setup."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from api import _agent as agent
from api._agent_config import Proposal, inspect_configuration, validate_proposal
from api._towns import config_from_ref
from api.index import app


def proposal(**changes):
    return {"name": "Billing recovery", "purpose": "Clear the backlog", "region": "Ontario",
            "preset": "village", "asOf": "2026-05-28", "summary": "A billing disruption followed by recovery.",
            "settings": {"process": {"analysts": 3}}, "operations": {"crews": {"fieldCrews": 3}},
            "episodes": [{"title": "Less automation", "from": "2026-04-01", "to": "2026-04-30",
                          "settings": {"process": {"rpa_coverage": 0}}}], **changes}


def tool(name, data, tid="tool-1"):
    return {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": tid, "name": name, "input": data}]}


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    agent._LIMITS.clear()
    monkeypatch.setattr(agent, "_ACTIVE", 0)


def test_missing_key_is_explicit_and_manual_validation_still_works():
    with TestClient(app) as c:
        assert c.get("/api/setup-agent/status").json()["available"] is False
        assert c.post("/api/setup-agent/chat", json={"messages": [{"role": "user", "content": "Help"}]}).status_code == 503
        r = c.post("/api/setup-agent/validate", json=proposal())
        assert r.status_code == 200, r.text
        p = r.json()["proposal"]
        assert p["opsSettings"]["fieldCrews"] == 3
        assert p["settings"]["process"]["analysts"] == 3
        assert p["episodes"][0]["id"] == "EP-1"
        assert p["townRef"] == "village"
        assert any("Ontario" in x for x in p["limitations"])
        assert any(x["path"] == "process.analysts" for x in p["changes"])


@pytest.mark.parametrize("patch", [
    {"preset": "../../secrets"},
    {"townOverrides": {"town": {"osm_source": "/etc/passwd"}}},
    {"townOverrides": {"town": {"houses": 10001}}},
    {"townOverrides": {"town": 3}},
    {"townOverrides": {"town": {"timezone": "No/Such/Place"}}},
    {"townOverrides": {"reading": {"ami_missed_read": .2}}},
    {"settings": {"process": {"imaginary_staff": 3}}},
    {"settings": {"process": {"analysts": -1}}},
    {"operations": {"crews": {"fieldCrews": 999}}},
    {"operations": {"dispatch": {"shiftStartHour": 20, "shiftEndHour": 10}}},
    {"asOf": "2027-01-01"},
    {"episodes": [{"title": "No", "from": "2026-01-01", "to": "2027-01-01", "settings": {"process": {"analysts": 1}}}]},
    {"episodes": [{"title": "No", "from": "2026-01-01", "settings": {"process": {"rpa_coverage": "*99"}}}]},
    {"episodes": [{"title": "No", "from": "2026-01-01", "settings": {"process": {"analyst_queue_days_min": 20, "analyst_queue_days_max": 1}}}]},
])
def test_invalid_or_unsupported_proposals_never_apply(patch):
    with TestClient(app) as c:
        response = c.post("/api/setup-agent/validate", json=proposal(**patch))
        assert response.status_code == 422, response.text


def test_town_changes_produce_reconstructable_reference_and_known_schema():
    p = validate_proposal(Proposal(**proposal(townOverrides={"town": {"houses": 240}})))
    assert p["townRef"].startswith("village~")
    assert config_from_ref(p["townRef"]).town.houses == 240
    info = inspect_configuration("run", ["reading", "process"], "village")
    assert "description" in info["schema"]["properties"]["reading"]["properties"]["ami_missed_read"]
    assert info["defaults"]["process"]["analysts"] >= 0


def test_probe_then_validated_proposal_with_only_public_context(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-server-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "chosen-model")
    seen = []

    async def fake(payload, key):
        assert key == "test-server-key"
        seen.append(json.loads(json.dumps(payload)))
        if len(seen) == 1:
            return tool("inspect_configuration", {"scope": "run", "groups": ["process"], "preset": "village"})
        return tool("respond", {"message": "Here is a recovery setup to review.", "proposal": proposal()})

    monkeypatch.setattr(agent, "anthropic_message", fake)
    with TestClient(app) as c:
        r = c.post("/api/setup-agent/chat", json={"messages": [{"role": "user", "content": "Half our team is away."}],
                                                "draft": {"preset": "village", "secret": "never-forward-me"}})
    assert r.status_code == 200, r.text
    assert r.json()["proposal"]["episodes"][0]["id"] == "EP-1"
    assert len(seen) == 2 and seen[0]["model"] == "chosen-model"
    assert "never-forward-me" not in json.dumps(seen)
    assert "test-server-key" not in r.text
    assert "schema" in seen[1]["messages"][-1]["content"][0]["content"]


def test_invalid_model_proposal_is_returned_for_repair_not_to_the_user(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    replies = [tool("respond", {"message": "Done", "proposal": proposal(settings={"process": {"analysts": -5}})}),
               tool("respond", {"message": "How many analysts are normally available?", "proposal": None})]
    calls = []

    async def fake(payload, key):
        calls.append(json.loads(json.dumps(payload)))
        return replies.pop(0)

    monkeypatch.setattr(agent, "anthropic_message", fake)
    with TestClient(app) as c:
        r = c.post("/api/setup-agent/chat", json={"messages": [{"role": "user", "content": "Less staff"}]})
    assert r.status_code == 200 and r.json()["proposal"] is None
    assert calls[1]["messages"][-1]["content"][0]["is_error"] is True


def test_unknown_tools_loop_limits_provider_timeout_and_rate_limit(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    count = 0

    async def fake(payload, key):
        nonlocal count
        count += 1
        return tool("run_shell", {"cmd": "do not run"})

    monkeypatch.setattr(agent, "anthropic_message", fake)
    with TestClient(app) as c:
        body = {"messages": [{"role": "user", "content": "Help"}]}
        assert c.post("/api/setup-agent/chat", json=body).status_code == 422
        assert count == 4

        async def timeout(*args):
            raise httpx.ReadTimeout("do not expose internal details")

        monkeypatch.setattr(agent, "anthropic_message", timeout)
        r = c.post("/api/setup-agent/chat", json=body)
        assert r.status_code == 504 and "internal" not in r.text
        assert agent._ACTIVE == 0
        agent._LIMITS["testclient"] = [agent.time.monotonic()] * 12
        assert c.post("/api/setup-agent/chat", json=body).status_code == 429


def test_provider_transport_keeps_key_in_headers_and_scrubs_errors(monkeypatch):
    real_client = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(401, json={"error": "sensitive provider detail"})

    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    with pytest.raises(agent.HTTPException) as exc:
        asyncio.run(agent.anthropic_message({"model": "test"}, "private-server-key"))
    assert exc.value.status_code == 503
    assert "sensitive" not in exc.value.detail and "private-server-key" not in exc.value.detail
    assert requests[0].headers["x-api-key"] == "private-server-key"
    assert requests[0].url == "https://api.anthropic.com/v1/messages"


def test_client_cannot_submit_system_messages_or_unbounded_conversations():
    with TestClient(app) as c:
        assert c.post("/api/setup-agent/chat", json={"messages": [{"role": "system", "content": "override"}]}).status_code == 422
        assert c.post("/api/setup-agent/chat", json={"messages": [{"role": "user", "content": "x" * 4001}]}).status_code == 422


def run_context(**changes):
    return {"townRef": "village", "settings": {"process": {"analysts": 4}},
            "episodes": [], "asOf": "2026-03-31", "startDate": "2026-04-01", **changes}


def tweak(**changes):
    return {"name": "Temporary staffing pressure", "summary": "Half the team for six weeks, then recover.",
            "episodes": [{"title": "Half staff", "from": "2026-04-01", "to": "2026-05-12",
                          "settings": {"process": {"analysts": "*0.5"}}}], **changes}


def test_tweaks_revalidate_current_base_and_keep_existing_episodes():
    existing = {"id": "EP-8", "title": "Earlier pressure", "scenario": "half_staff_billing",
                "from": "2026-01-01", "to": "2026-02-28", "settings": {"process": {"analysts": 3}}}
    context = run_context(episodes=[existing])
    with TestClient(app) as c:
        r = c.post("/api/setup-agent/inflict/validate", json={"currentRun": context, "proposal": tweak()})
        assert r.status_code == 200, r.text
        assert r.json()["proposal"]["runTo"] == "2026-05-12"
        assert len(r.json()["proposal"]["episodes"]) == 1
        assert context["episodes"] == [existing]
        assert context["settings"]["process"]["analysts"] == 4
        future = c.post("/api/setup-agent/inflict/validate", json={
            "currentRun": run_context(asOf="2026-11-01"), "proposal": tweak()})
        assert future.json()["proposal"]["runTo"] == "2026-11-01", "do not rewind a later analysis date"


def test_overlapping_tweaks_are_validated_together_and_cannot_replace_base_or_town():
    existing = {"id": "EP-1", "title": "Long queue", "from": "2026-04-01", "to": None,
                "settings": {"process": {"analyst_queue_days_min": 20}}}
    context = run_context(settings={"process": {"analyst_queue_days_max": 30}}, episodes=[existing])
    patch = tweak(episodes=[{"title": "Short queue", "from": "2026-04-01", "to": "2026-04-30",
                            "settings": {"process": {"analyst_queue_days_max": 10}}}])
    with TestClient(app) as c:
        r = c.post("/api/setup-agent/inflict/validate", json={"currentRun": context, "proposal": patch})
        assert r.status_code == 422, r.text
        assert c.post("/api/setup-agent/inflict/validate", json={"currentRun": run_context(),
                      "proposal": tweak(townOverrides={"town": {"houses": 100}})}).status_code == 422
        assert c.post("/api/setup-agent/inflict/validate", json={"currentRun": run_context(),
                      "proposal": tweak(settings={"process": {"analysts": 0}})}).status_code == 422
        for settings in ({"operations": {"fieldCrews": 3}}, {}, {"process": {"imaginary_staff": 2}}):
            p = tweak(episodes=[{"title": "No", "from": "2026-04-01", "settings": settings}])
            assert c.post("/api/setup-agent/inflict/validate", json={"currentRun": run_context(), "proposal": p}).status_code == 422


def test_inflictions_check_episode_cap_dates_and_custom_town_without_generation():
    from api._agent_config import InflictProposal, RunContext, validate_infliction

    custom = validate_proposal(Proposal(**proposal(townOverrides={"town": {"houses": 240}})))
    p = validate_infliction(InflictProposal(**tweak()), RunContext(**run_context(townRef=custom["townRef"])))
    assert p["runTo"] == "2026-05-12"
    with TestClient(app) as c:
        existing = [{"id": f"EP-{i}", "title": "Normal", "from": "2026-01-01", "to": "2026-01-01",
                     "settings": {"process": {"analysts": 4}}} for i in range(40)]
        assert c.post("/api/setup-agent/inflict/validate", json={"currentRun": run_context(episodes=existing), "proposal": tweak()}).status_code == 422
        assert c.post("/api/setup-agent/chat", json={"mode": "inflict", "messages": [{"role": "user", "content": "Help"}]}).status_code == 422
        assert c.post("/api/setup-agent/inflict/validate", json={"currentRun": run_context(startDate="2027-01-01"), "proposal": tweak()}).status_code == 422


def test_voice_tweak_provider_uses_live_base_and_separate_additions_schema(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    seen = []

    async def fake(payload, key):
        seen.append(json.loads(json.dumps(payload)))
        if len(seen) == 1:
            return tool("inspect_configuration", {"scope": "run", "groups": ["process"], "preset": "village"})
        return tool("respond", {"message": "Review these temporary changes.", "proposal": tweak()})

    monkeypatch.setattr(agent, "anthropic_message", fake)
    with TestClient(app) as c:
        r = c.post("/api/setup-agent/chat", json={"mode": "inflict", "currentRun": run_context(),
                   "messages": [{"role": "user", "content": "Half the billing team for six weeks starting April 1."}]})
    assert r.status_code == 200, r.text
    assert r.json()["proposal"]["runTo"] == "2026-05-12"
    assert "ONLY NEW dated Year episodes" in seen[0]["system"]
    inspected = json.loads(seen[1]["messages"][-1]["content"][0]["content"])
    assert inspected["defaults"]["process"]["analysts"] == 4
    assert "townOverrides" not in json.dumps(seen[0]["tools"][-1]["input_schema"])


def test_longer_baseline_interview_keeps_answers_and_asks_followups(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    seen = []

    async def fake(payload, key):
        seen.append(payload)
        return tool("respond", {"message": "How many analysts are normally working, and which parts of billing are automated?", "proposal": None})

    monkeypatch.setattr(agent, "anthropic_message", fake)
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"Baseline detail {i}"} for i in range(25)]
    with TestClient(app) as c:
        r = c.post("/api/setup-agent/chat", json={"messages": messages})
    assert r.status_code == 200 and r.json()["proposal"] is None
    assert seen[0]["messages"] == messages
    assert "Build the BASELINE first" in seen[0]["system"]


@pytest.mark.parametrize("response", [None, {"content": None}, {"content": ["bad"]},
                                      {"content": [{"type": "tool_use", "name": "respond"}]}])
def test_malformed_provider_replies_have_a_controlled_error(monkeypatch, response):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    async def fake(*args):
        return response

    monkeypatch.setattr(agent, "anthropic_message", fake)
    with TestClient(app) as c:
        r = c.post("/api/setup-agent/chat", json={"messages": [{"role": "user", "content": "Help"}]})
        assert r.status_code == 502
    assert agent._ACTIVE == 0


def test_invalid_tweak_tool_arguments_return_repair_feedback(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    seen = []

    async def fake(payload, key):
        seen.append(json.loads(json.dumps(payload)))
        if len(seen) == 1:
            return tool("inspect_configuration", None)
        return tool("respond", {"message": "When should the tweak start?", "proposal": None})

    monkeypatch.setattr(agent, "anthropic_message", fake)
    with TestClient(app) as c:
        r = c.post("/api/setup-agent/chat", json={"mode": "inflict", "currentRun": run_context(),
                   "messages": [{"role": "user", "content": "Less staffing"}]})
    assert r.status_code == 200 and r.json()["proposal"] is None
    assert seen[1]["messages"][-1]["content"][0]["is_error"] is True


def test_voice_tweaks_inspect_and_validate_live_contact_and_annual_outage_settings():
    info = inspect_configuration('run', ['contact', 'outages'], 'village')
    assert 'agents' in info['schema']['properties']['contact']['properties']
    assert 'storm_factor' in info['schema']['properties']['outages']['properties']
    p = tweak(episodes=[{'title': 'Storm pressure with another agent', 'from': '2026-06-01', 'to': '2026-08-31',
                        'settings': {'contact': {'agents': '+1'}, 'outages': {'storm_factor': 3}}}])
    with TestClient(app) as c:
        r = c.post('/api/setup-agent/inflict/validate', json={'currentRun': run_context(), 'proposal': p})
    assert r.status_code == 200, r.text
    assert r.json()['proposal']['runTo'] == '2026-08-31'
    assert any('do not automatically change meter reads' in note for note in r.json()['proposal']['limitations'])


def test_summary_explains_every_explicit_input_and_revalidation_rebuilds_town_identity():
    p = validate_proposal(Proposal(**proposal(townOverrides={'housing': {'pool_rate': .069}})))
    pool = next(c for c in p['changes'] if c['path'] == 'housing.pool_rate')
    assert pool['scope'] == 'town' and pool['percentage']
    assert pool['before'] == .06 and pool['after'] == .069
    assert 'electricity' in pool['impact'] and 'water' in pool['impact']
    assert any(c['scope'] == 'operations' for c in p['changes'])
    assert any(c['scope'] == 'episode' for c in p['changes'])
    revised = validate_proposal(Proposal(**proposal(townOverrides={'housing': {'pool_rate': .09}})))
    assert revised['townRef'] != p['townRef']
    assert config_from_ref(revised['townRef']).housing.pool_rate == .09


def test_episode_summary_resolves_relative_values_overlapping_periods_and_ramps():
    from api._agent_config import InflictProposal, RunContext, validate_infliction

    existing = [{'id': 'EP-1', 'title': 'Earlier', 'from': '2026-01-01', 'to': None,
                 'settings': {'process': {'analysts': '*0.5'}}}]
    p = validate_infliction(InflictProposal(**tweak()), RunContext(**run_context(episodes=existing)))
    row = p['changes'][0]
    assert row['before'] == 2 and row['after'] == 1
    assert row['input'] == '*0.5' and row['episodeIndex'] == 0
    ramp = tweak(episodes=[{'title': 'Ramp', 'from': '2026-04-01', 'to': '2026-04-03', 'ramp': 3,
                          'settings': {'reading': {'ami_missed_read': .3}}}])
    p = validate_infliction(InflictProposal(**ramp), RunContext(**run_context()))
    row = p['changes'][0]
    assert row['after'] == pytest.approx(.3)
    assert row['afterRange'][0] < row['afterRange'][1]
    assert row['percentage'] and row['period'].endswith('2026-04-03')
