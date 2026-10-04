"""The contact centre (utilsim/m2c/contact.py) and the year's outages and leaks (utilsim/m2c/incidents.py): contacts
follow what happens in the year, the settings move them the way their explanations say, episodes apply from their day,
the year's own results do not change, and the views and tables stay bounded."""

from __future__ import annotations

import numpy as np
import orjson
import pytest
from fastapi.testclient import TestClient

from api._m2c import RunRequest, _master, _town, run_for
from api.index import app
from utilsim.m2c import contact, fieldwork, tables, trend, views
from utilsim.m2c.base import date_of
from utilsim.m2c.run import M2CRun, parse_day

TOWN = "small_town"
DAY = "2026-12-31"
K = {k: i for i, k in enumerate(contact.KEYS)}
CH = {k: i for i, k in enumerate(contact.CHANNELS)}
OUT = {k: i for i, k in enumerate(contact.OUTCOMES)}


def _run(settings=None, episodes=None, town=TOWN):
    return run_for(RunRequest(town=town, settings=settings, episodes=episodes or []))


@pytest.fixture(scope="module")
def base():
    run = _run()
    return run, contact.contacts(run)


def test_contacts_are_deterministic_in_time_order_and_in_the_year(base):
    run, cx = base
    again = contact.contacts(M2CRun(run.town, ops_factory=run.ops_factory))  # the replay again, from scratch
    assert np.array_equal(again.t, cx.t) and np.array_equal(again.reason, cx.reason)
    assert np.array_equal(again.outcome, cx.outcome) and again.case == cx.case
    assert len(cx.t) > 1000 and (np.diff(cx.t) >= 0).all() and cx.t.min() >= 0 and cx.t.max() < 365
    assert set(np.unique(cx.reason)) <= set(range(len(contact.REASONS)))
    per_account = len(cx.t) / len(cx.accounts)
    assert 0.5 < per_account < 3.0  # utilities see about one to two contacts per customer a year


def test_triggered_contacts_point_at_what_caused_them(base):
    run, cx = base
    bk = run.books
    inv = {i["id"]: i for i in bk.invoices}
    high = [i for i in np.flatnonzero((cx.reason == K["high_bill"]) & (cx.attempt == 1) & ~cx.repeat).tolist()
            if cx.trigger[i] != "background"]
    assert high
    for i in high:
        invoice = inv[cx.trigger[i]]
        expected = sum(bk.docs[k]["expectedTotal"] for k in invoice["docs"])
        assert invoice["total"] >= max(1.5 * expected, expected + 40.0) - 1e-6
        assert cx.t[i] >= invoice["issued"]
    for i in np.flatnonzero((cx.reason == K["move_in"]) & (cx.attempt == 1) & ~cx.repeat).tolist():
        start = parse_day(cx.trigger[i].split(" opens ")[1], 0)
        assert cx.t[i] < start + 1
    incidents = {x["id"]: x for x in cx.incidents}
    outages = np.flatnonzero((cx.reason == K["outage"]) & (cx.attempt == 1) & ~cx.repeat).tolist()
    assert any(cx.trigger[i] in incidents for i in outages)
    for i in outages:
        if cx.trigger[i] in incidents:
            x = incidents[cx.trigger[i]]
            assert cx.prem[i] in set(x["premises"].tolist()) and cx.t[i] >= x["t"]
    gas = np.flatnonzero(cx.reason == K["gas_odour"])
    assert len(gas) and (cx.channel[gas] == CH["emergency"]).all() and (cx.outcome[gas] == OUT["dispatched"]).all()


def test_agents_hours_and_self_service_move_the_queue_the_way_they_say(base):
    run, cx = base
    s0 = contact.summary(run, DAY)["kpis"]
    more = contact.summary(_run({"contact": {"agents": 3}}), DAY)["kpis"]
    assert more["abandoned"] < s0["abandoned"] and more["asaS"] <= s0["asaS"]
    assert more["cost"]["staff"] == pytest.approx(3 * s0["cost"]["staff"])
    short = contact.summary(_run({"contact": {"close_hour": 12.0}}), DAY)["kpis"]
    assert short["abandoned"] > s0["abandoned"] and short["occupancyPct"] > s0["occupancyPct"]
    no_ivr = contact.summary(_run({"contact": {"self_serve_factor": 0}}), DAY)["kpis"]
    assert no_ivr["selfServed"] == 0 and no_ivr["toAgents"] > s0["toAgents"]
    busy = contact.summary(_run({"contact": {"volume_factor": 2.0}}), DAY)["kpis"]
    assert 1.6 < busy["contacts"] / s0["contacts"] < 2.4
    wrong = contact.summary(_run({"contact": {"bill_wrong": {"per_event": 1.0, "per_1000": 0.3, "self_serve": 0.0,
                                                             "handle_min": 11.0, "resolved": 0.6}}}), DAY)
    assert wrong["kpis"]["byReason"]["bill_wrong"] > s0["byReason"]["bill_wrong"]


OFF = {"frustration_threshold": 0, "dispute_cases": 0.0, "complaint_cases": False}  # the contact feedback switched off


def test_with_its_feedback_off_how_the_contact_centre_answers_never_changes_the_year():
    run = _run({"contact": OFF})
    other = _run({"contact": {**OFF, "agents": 0, "handle_factor": 3.0, "self_serve_factor": 0.0, "patience_s": 30.0}})
    a, b = views.summary(run, DAY), views.summary(other, DAY)
    for key in ("kpis", "billing", "queues", "exceptions"):
        assert orjson.dumps(a[key], option=orjson.OPT_SERIALIZE_NUMPY) == \
            orjson.dumps(b[key], option=orjson.OPT_SERIALIZE_NUMPY), key


def test_disputes_and_complaints_open_cases_the_analysts_work(base):
    run, cx = base
    bk = run.books
    cases = [c for c in run.cases if c.created_by == "contact_centre"]
    disputes = [c for c in cases if c.type == "BILL_DISPUTE"]
    complaints = [c for c in cases if c.type == "COMPLAINT"]
    assert disputes and complaints
    # Every one was opened by an answered contact (an agent or a call back), and names it.
    opened = [i for i, c in enumerate(cx.case) if c]
    assert sorted(cx.case[i] for i in opened) == sorted(c.id for c in cases)
    assert all(cx.channel[i] in (CH["agent"], CH["callback"]) and cx.outcome[i] <= OUT["unresolved"] for i in opened)
    rebilled = 0
    for c in disputes:
        doc = bk.docs[c.doc]
        assert doc["invoice"] >= 0 and c.ref == bk.account(doc) and c.queue in ("BILLING", "SUPERVISOR", None)
        A = bk.collections.accounts[c.ref]
        hold = next(h for h in A.holds if h.get("caseId") == c.id)  # dunning paused while it waits
        assert hold["start"] == c.created and (c.resolved is None or hold["end"] <= max(c.resolved, hold["start"]) + 30)
        if c.outcome == "check_rebill":  # the customer was right: rebilled on the quantities a check read finds
            rebilled += 1
            new = next(d for d in bk.docs if d.get("replaces") == doc["k"] and d.get("checkRead"))
            ti, te = bk.quantities(np.array([doc["inst"]]), np.array([doc["month"]]), run.truth,
                                   sm=np.array([doc.get("from", doc["month"] - 1)]))
            assert new["qImp"] == pytest.approx(float(ti[0])) and new["qExp"] == pytest.approx(float(te[0]))
            if new["invoice"] >= 0:  # the next invoice credits the version it replaces
                assert bk.invoices[new["invoice"]]["credited"] == pytest.approx(sum(
                    bk.docs[bk.docs[k]["replaces"]]["total"] for k in bk.invoices[new["invoice"]]["docs"]
                    if bk.docs[k].get("replaces", -1) >= 0 and bk.docs[bk.docs[k]["replaces"]]["invoice"] >= 0))
    assert rebilled > 0
    assert all(c.work == "complaint" and (c.resolved is None or "COMPLAINT_ANSWERED" in [e[1] for e in c.events])
               for c in complaints)
    # A credit invoice settles the account's open bills (not cash), and the summary counts it all.
    credits = [i for i in bk.invoices if i["total"] < 0 and i.get("credited")]
    assert credits and all(i["paid"] == i["issued"] or i["paid"] >= i["issued"] for i in credits)
    f = contact.summary(run, DAY)["feedback"]
    assert f["disputes"] == len(disputes) and f["complaints"] == len(complaints) and f["rebilled"] == rebilled
    assert f["creditInvoices"] == len(credits) and f["credited"] > 0
    # Workspace categories: disputes are Bill Correction, complaints Customer Complaints.
    bc = views.worklist(run, None, as_of=DAY, status="all", category="Bill Correction", page_size=200)
    last_queue = lambda c: [q for _, q, _ in c.moves if q][-1]  # noqa: E731
    assert bc["total"] == sum(last_queue(c) != "SUPERVISOR" for c in disputes)  # escalated ones are Escalations
    cc = views.worklist(run, None, as_of=DAY, status="all", category="Customer Complaints", page_size=200)
    assert cc["total"] == len(complaints) and all(r["type"] == "COMPLAINT" for r in cc["rows"])


def test_bad_service_makes_customers_pay_later(base):
    run, _ = base
    none = _run({"contact": {"agents": 0}})  # nobody answers: hang-ups, retries, complaints that never get through
    f0, f1 = contact.feedback(run, 0.0, 365.0), contact.feedback(none, 0.0, 365.0)
    assert f1["payLater"] > 5 * max(1, f0["payLater"]) and f1["autopayCancelled"] > 0
    assert f1["disputes"] == 0 and f1["complaints"] == 0  # nothing answered, nothing opened
    col = none.books.collections
    tipped = [A for A in col.accounts.values() if A.risk_at is not None]
    assert tipped and all(A.bad >= none.cfg.contact.frustration_threshold for A in tipped)
    notices = lambda r: sum(1 for i in r.books.invoices for _, k in i["dunning"] if k == "DUNNING_NOTICE")  # noqa: E731
    assert notices(none) > notices(run)  # they pay later: more overdue notices


def test_new_connection_requests_are_the_field_crews_new_services(base):
    run, _ = base
    busy = _run({"contact": {"volume_factor": 3.0}})
    sets = [sum(1 for o in r.field.orders if o.type == fieldwork.IDX["new_set"]) for r in (run, busy)]
    assert 0 < sets[0] < sets[1]  # three times the requests: more new services for the crews to build


def test_outages_follow_their_settings(base):
    run, cx = base
    off = contact.contacts(_run({"outages": {"enabled": False}}))
    assert off.incidents == []
    assert not any(t != "background" for t, r in zip(off.trigger, off.reason.tolist()) if r == K["outage"])
    stormy = contact.contacts(_run({"outages": {"storm_factor": 8.0}}))
    faults = sum(x["kind"] == "line_fault" for x in cx.incidents)
    assert sum(x["kind"] == "line_fault" for x in stormy.incidents) > faults
    assert (stormy.reason == K["outage"]).sum() > (cx.reason == K["outage"]).sum()
    slow = contact.contacts(_run({"outages": {"restore_factor": 3.0}}))
    hours = [float((x["restoredAt"] - x["t"]).mean()) for x in cx.incidents if len(x["restoredAt"])]
    slow_hours = [float((x["restoredAt"] - x["t"]).mean()) for x in slow.incidents if len(x["restoredAt"])]
    assert slow_hours == pytest.approx([3 * h for h in hours])


def test_an_episode_changes_contacts_only_from_its_day(base):
    run, cx = base
    ep = [{"id": "EP-1", "title": "Phones until 1 pm", "from": "2026-06-01", "to": "2026-06-30",
           "settings": {"contact": {"close_hour": 13.0}}}]
    other = _run(episodes=ep)
    ox = contact.contacts(other)
    start = parse_day("2026-06-01", 0)
    before, obefore = cx.t < start, ox.t < start
    assert np.array_equal(cx.t[before], ox.t[obefore]) and np.array_equal(cx.outcome[before], ox.outcome[obefore])
    june = lambda c: (c.t >= start) & (c.t < start + 30) & (c.channel == CH["agent"])  # noqa: E731
    late = lambda c: june(c) & (((c.t - np.floor(c.t)) * 24) >= 13)  # noqa: E731
    assert late(ox).sum() == 0 and late(cx).sum() > 0


def test_summary_trend_and_tables_are_bounded_and_agree(base):
    run, cx = base
    s = contact.summary(run, "2026-08-05")
    assert s["schemaVersion"] == contact.CONTACT_VERSION and s["asOf"] == "2026-08-05"
    assert s["kpis"]["contacts"] == int((cx.t <= parse_day("2026-08-05", 0) + 1 - 1e-9).sum()) or \
        s["kpis"]["contacts"] == int((cx.t <= views.as_of_t(run, "2026-08-05")[1]).sum())
    assert sum(r["contacts"] for r in s["reasons"]) == s["kpis"]["contacts"]
    assert len(s["daily"]) == 60 and len(orjson.dumps(s, option=orjson.OPT_SERIALIZE_NUMPY)) < 200_000
    t = trend.trend(run, "2026-08-05")
    months = t["months"]
    assert all(m["contact"] is None for m in months[8:]) and months[7]["contact"]["contacts"] > 0
    assert sum(m["contact"]["contacts"] for m in months[:8]) == s["kpis"]["contacts"]
    master = _master(TOWN)
    for name in ("contacts", "contactDaily", "yearIncidents"):
        page = tables.page(run, master, name, as_of="2026-08-05", page_size=tables.PAGE_MAX)
        assert page["rowsInTable"] > 0 and len(orjson.dumps(page)) < 4_500_000, name
    calls = tables.page(run, master, "contacts", as_of="2026-08-05", page_size=5)
    assert calls["rowsInTable"] == s["kpis"]["contacts"]
    daily = tables.page(run, master, "contactDaily", as_of="2026-08-05", page_size=5)
    assert daily["rowsInTable"] == parse_day("2026-08-05", 0) + 1 and daily["rows"][0][0] == "2026-08-05"


def test_without_networks_contacts_still_come_but_no_incidents():
    run = M2CRun(_town(TOWN), seed="NO-NETWORK")  # no ops_factory: a town without networks
    s = contact.summary(run, DAY)
    assert s["incidents"]["count"] == 0 and s["notes"] and s["kpis"]["contacts"] > 0


def test_endpoint_on_the_hosted_engine():
    client = TestClient(app)
    res = client.post("/api/m2c/contact", json={"town": "village", "asOf": "2026-03-31"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schemaVersion"] == contact.CONTACT_VERSION and body["kpis"]["contacts"] > 0
    assert [r["id"] for r in body["reasons"]] == list(contact.KEYS)
    assert date_of(parse_day(body["asOf"], 0)).isoformat() == "2026-03-31"
    bad = client.post("/api/m2c/contact", json={"town": "village", "settings": {"contact": {"agents": -1}}})
    assert bad.status_code == 422
