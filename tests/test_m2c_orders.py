"""Utility Studio work on the meter-to-cash run: field service orders, case notes and ownership, invoice holds,
clarification categories and the lookups behind the SAP query screens (hosted runtime)."""

from __future__ import annotations

import orjson
import pytest
from fastapi.testclient import TestClient

from api._m2c import RunRequest, _town, run_for
from api.app import app
from utilsim.m2c import catalog as cat
from utilsim.m2c import lookups, views
from utilsim.m2c import orders as ords
from utilsim.m2c.calendar import calendar
from utilsim.m2c.run import ActionError, M2CRun

CAL = calendar(2026)
add_bdays = CAL.add_bdays
date_of = CAL.date_of

SLOW = {"process": {"analysts": 0, "rpa_coverage": 0}}  # nothing resolves cases but you (and supervisors, crews)
LIMIT = 4_500_000


def iso(day: int) -> str:
    return date_of(day).isoformat()


def form(start: str, **kw) -> dict:
    return {"orderType": "FS01 · Field service", "shortText": "Investigate high usage", "plant": "SM01 · Small Town",
            "plannerGroup": "MR · Meter services", "workCenter": "METER-ELECTRIC", "activityType": "Meter investigation",
            "startDate": start, "finishDate": start, "priority": "2 · Normal", "longText": "Customer disputes the bill.",
            "operation": "Inspect the meter and its seals", "duration": 45, "accessNotes": "Side gate; dog in the yard",
            **kw}


SEAL = [{"description": "Meter seal", "quantity": 2, "unit": "EA"}]


@pytest.fixture(scope="module")
def town():
    return _town("small_town")


@pytest.fixture(scope="module")
def base(town) -> M2CRun:
    return run_for(RunRequest(town="small_town", settings=SLOW))


@pytest.fixture(scope="module")
def source(base):
    """An implausible-value case that stays open in VEE review (nobody works it in the SLOW run)."""
    return next(c for c in base.cases if c.type not in cat.MISSING_TYPES and c.doc < 0 and 90 < c.created < 140
                and c.resolved is None and c.queue == "VEE_REVIEW")


@pytest.fixture(scope="module")
def plan(source):
    d0 = add_bdays(int(source.created), 1)
    d1 = add_bdays(d0, 1)
    start = add_bdays(d1, 2)
    oid = f"WO-{date_of(d0):%y%m%d}-0001"
    actions = [
        {"id": "A1", "day": iso(d0), "type": "order_save", "sourceCaseId": source.id,
         "fields": {"shortText": "Check the meter"}},  # an incomplete draft
        {"id": "A2", "day": iso(d0), "type": "note", "caseId": source.id, "text": "Customer called about the bill"},
        {"id": "A3", "day": iso(d1), "type": "order_save", "orderId": oid, "fields": form(iso(start)),
         "components": SEAL},
        {"id": "A4", "day": iso(d1), "type": "order_release", "orderId": oid},
        {"id": "A5", "day": iso(d1), "type": "order_dispatch", "orderId": oid},
        {"id": "A6", "day": iso(start), "type": "order_complete", "orderId": oid, "note": "Seals intact; read 4182"},
        {"id": "A7", "day": iso(start), "type": "assign", "caseId": source.id, "assignee": "Dana"},
    ]
    return {"d0": d0, "d1": d1, "start": start, "oid": oid, "actions": actions}


@pytest.fixture(scope="module")
def lifecycle(plan) -> M2CRun:
    return run_for(RunRequest(town="small_town", settings=SLOW, actions=plan["actions"]))


# ---- the order form -------------------------------------------------------------------------------------------
def release_of(town, fields: dict, components: list | None = None, day: str = "2026-05-04") -> list[dict]:
    return [{"day": day, "type": "order_save", "sourceCaseId": "CASE-any", "fields": fields,
             **({"components": components} if components is not None else {})},
            {"day": day, "type": "order_release", "orderId": "WO-260504-0001"}]


def field_errors(town, actions: list[dict]) -> dict:
    with pytest.raises(ActionError) as exc:
        M2CRun(town, SLOW, actions)  # the form is checked before the year is simulated
    return exc.value.detail["fieldErrors"]


def test_release_needs_every_required_field(town):
    assert set(field_errors(town, release_of(town, {}))) == set(ords.REQUIRED)
    assert len(ords.REQUIRED) == 13 and not {"responsible", "contactName", "contactPhone"} & set(ords.REQUIRED)
    assert not ords.validate(form("2026-05-06"), SEAL, 123, ("SM01 · Small Town",), CAL)


@pytest.mark.parametrize(("change", "components", "field"), [
    ({"orderType": "ZZ01 · Mystery"}, None, "orderType"),
    ({"plant": "VI01 · Village"}, None, "plant"),  # another town's planning plant
    ({"workCenter": "METER-STEAM"}, None, "workCenter"),
    ({"priority": "0 · Panic"}, None, "priority"),
    ({"startDate": "2026-05-01"}, None, "startDate"),  # before the action day
    ({"startDate": "2026-02-30", "finishDate": "2026-05-06"}, None, "startDate"),
    ({"startDate": "06/05/2026", "finishDate": "2026-05-06"}, None, "startDate"),
    ({"finishDate": "2026-05-05"}, None, "finishDate"),  # before the start
    ({"duration": 0}, None, "duration"),
    ({"duration": "-15"}, None, "duration"),
    ({"duration": "soon"}, None, "duration"),
    ({"longText": "   "}, None, "longText"),
    ({"accessNotes": ""}, None, "accessNotes"),
    ({}, [{"description": " ", "quantity": 1, "unit": "EA"}], "components"),
    ({}, [{"description": "Seal", "quantity": 0, "unit": "EA"}], "components"),
    ({}, [{"description": "Seal", "quantity": "two", "unit": "EA"}], "components"),
    ({}, [{"description": "Cable", "quantity": 3, "unit": "KG"}], "components"),
])
def test_each_release_rule_rejects_with_a_field_error(town, change, components, field):
    errors = field_errors(town, release_of(town, form("2026-05-06", **change), components))
    assert list(errors) == [field], errors


def test_a_draft_may_be_incomplete_but_well_formed(town):
    with pytest.raises(ActionError) as exc:
        M2CRun(town, SLOW, [{"day": "2026-05-04", "type": "order_save", "sourceCaseId": "CASE-any",
                             "fields": {"colour": "red", "duration": True}}])
    assert set(exc.value.detail["fieldErrors"]) == {"colour", "duration"}
    with pytest.raises(ActionError, match="one source"):
        M2CRun(town, SLOW, [{"day": "2026-05-04", "type": "order_save", "fields": {}}])
    with pytest.raises(ActionError, match="unknown read"):
        M2CRun(town, SLOW, [{"day": "2026-05-04", "type": "order_save", "readId": "READ-nope"}])


@pytest.mark.parametrize(("steps", "match"), [
    (["order_dispatch"], "release order .* before dispatch"),
    (["order_complete"], "dispatch order .* before completing"),
    (["order_release", "order_complete"], "dispatch order .* before completing"),
    (["order_release", "order_dispatch", "order_complete"], "starts on 2026-05-06"),  # before the basic start
    (["order_release", "order_release"], "already Ready for dispatch"),
    (["order_release", "order_save"], "only a Draft can be saved"),
])
def test_lifecycle_steps_follow_the_contract(town, steps, match):
    oid = "WO-260504-0001"
    actions = [{"day": "2026-05-04", "type": "order_save", "sourceCaseId": "CASE-any", "fields": form("2026-05-06")}]
    actions += [{"day": "2026-05-04", "type": s, "orderId": oid, "note": "done"} for s in steps]
    with pytest.raises(ActionError, match=match):
        M2CRun(town, SLOW, actions)


def test_order_actions_need_a_known_order_and_an_outcome(town):
    with pytest.raises(ActionError, match="unknown order"):
        M2CRun(town, SLOW, [{"day": "2026-05-04", "type": "order_release", "orderId": "WO-260504-0009"}])
    actions = [{"day": "2026-05-04", "type": "order_save", "sourceCaseId": "CASE-any", "fields": form("2026-05-04")},
               *({"day": "2026-05-04", "type": s, "orderId": "WO-260504-0001"} for s in
                 ("order_release", "order_dispatch", "order_complete"))]
    with pytest.raises(ActionError, match="field outcome"):
        M2CRun(town, SLOW, actions)
    with pytest.raises(ActionError, match="note text is required"):
        M2CRun(town, SLOW, [{"day": "2026-05-04", "type": "note", "caseId": "CASE-any", "text": "  "}])
    with pytest.raises(ActionError, match="caseId or the accountId"):
        M2CRun(town, SLOW, [{"day": "2026-05-04", "type": "invoice_hold", "note": "why"}])


# ---- the lifecycle in the run ---------------------------------------------------------------------------------
def test_order_lifecycle_links_a_field_work_case_and_keeps_the_source_open(base, lifecycle, source, plan):
    run, oid, start = lifecycle, plan["oid"], plan["start"]
    assert not run.warnings
    o = run.orders[oid]
    assert [s for _, s, _, _ in o.stages] == list(ords.STAGES)
    fw = o.case
    assert fw.work == "order" and fw.source == source.id and fw.id == f"CASE-{date_of(plan['d0']):%y%m%d}-F0001"
    kinds = [e[1] for e in fw.events]
    assert kinds[:2] == ["FIELD_SERVICE", "EXCEPTION_QUEUED"] and "TRUCK_ROLL" in kinds
    roll = next(e for e in fw.events if e[1] == "TRUCK_ROLL")
    assert roll[0] == pytest.approx(start + 7 / 24) and roll[2]["orderId"] == oid
    assert int(fw.resolved) == start and fw.outcome == "completed"
    # The source exception stays open in its own queue and category; its read is not released.
    src = run.case_index[source.id]
    assert src.resolved is None and src.queue == "VEE_REVIEW" and src.orders == [oid]
    assert not run.release_t[src.r, src.month] <= start + 1 and not base.release_t[src.r, src.month] <= start + 1
    end = iso(start)
    row = views.worklist(run, None, as_of=end, search=source.id)["rows"][0]
    assert row["category"] == "MR Implausibles" and row["linkedOrderIds"] == [oid]
    assert row["assignee"] == row["owner"] == "Dana"
    cv = views.case_view(run, source.id, as_of=end)
    # The order's outcome is written back to its source case (an older list's note alone: a remark).
    assert [n["text"] for n in cv["notes"]] == ["Customer called about the bill", "Seals intact; read 4182"]
    assert cv["orders"][0]["stage"] == "Completed" and "order_save" not in cv["studioActions"]
    draft = views.case_view(run, fw.id, as_of=iso(plan["d0"]))
    assert draft["status"] == "draft" and draft["studioActions"] == ["note", "assign", "order_save", "order_release"]
    fv = views.case_view(run, fw.id, as_of=end)
    assert fv["category"] == "Field Work" and fv["order"]["outcome"]["text"] == "Seals intact; read 4182"
    assert fv["order"]["outcome"]["kind"] == "remark" and fv["order"]["outcome"]["by"] == "you"
    assert fv["order"]["visit"]["activity"] == "meter_investigation" and fv["order"]["components"] == SEAL
    field = views.worklist(run, None, as_of=end, status="all", category="Field Work")["rows"]
    assert fw.id in [r["caseId"] for r in field]
    # As of each day, the order shows the stage it had then.
    stages = [views.order_view(run, order_id=oid, as_of=iso(d))["order"]["stage"] for d in (plan["d0"], plan["d1"], start)]
    assert stages == ["Draft", "Dispatched", "Completed"]
    with pytest.raises(KeyError):
        views.order_view(run, order_id=oid, as_of=iso(plan["d0"] - 1))


def test_reopening_returns_the_same_order_and_never_a_second(town, lifecycle, source, plan):
    run, oid = lifecycle, plan["oid"]
    read_id = run.read_id(source.r, source.month)
    for kw in ({"case_id": source.id}, {"read_id": read_id}, {"case_id": run.orders[oid].case.id}):
        assert views.order_view(run, as_of=iso(plan["start"]), **kw)["order"]["orderId"] == oid
    fresh = views.order_view(run, case_id=source.id, as_of=iso(plan["d0"] - 1))
    assert fresh["order"] is None and fresh["proposal"]["plant"] == "SM01 · Small Town"
    # Saving again from the same source edits the same draft; a second source path to the same read is refused.
    d0 = iso(plan["d0"])
    again = [plan["actions"][0], {"day": d0, "type": "order_save", "sourceCaseId": source.id,
                                  "fields": {"longText": "More detail"}}]
    run2 = run_for(RunRequest(town="small_town", settings=SLOW, actions=again))
    assert list(run2.orders) == [oid] and run2.orders[oid].fields == {"shortText": "Check the meter",
                                                                       "longText": "More detail"}
    with pytest.raises(ActionError, match=f"already has field service order {oid}"):
        M2CRun(town, SLOW, [*again, {"day": d0, "type": "order_save", "readId": read_id}])


def test_actions_stay_append_only(base, lifecycle, plan):
    d0 = plan["d0"]
    before = [(c.id, [e for e in c.events if e[0] < d0]) for c in base.cases if c.created < d0]
    assert before == [(c.id, [e for e in c.events if e[0] < d0]) for c in lifecycle.cases if c.created < d0]
    assert views.summary(lifecycle, iso(d0 - 1))["kpis"] == views.summary(base, iso(d0 - 1))["kpis"]


def test_a_dispatched_order_is_an_operations_crew_job_on_its_start_date(plan, lifecycle):
    client = TestClient(app)
    oid, fw = plan["oid"], lifecycle.orders[plan["oid"]].case
    tl = client.post("/api/sim/timeline", json={"town": "small_town", "date": iso(plan["start"]),
                                                "m2c": {"settings": SLOW, "actions": plan["actions"]}})
    assert tl.status_code == 200, tl.text
    job = next(j for j in tl.json()["jobs"] if j.get("orderId") == oid)
    assert job["kind"] == "field_order" and job["caseId"] == fw.id and job["activity"] == "meter_investigation"
    assert job["crewId"].startswith("FIELD") and job["requestedAt"] == pytest.approx(7 * 3600, abs=1)
    assert job["workSeconds"] == pytest.approx(45 * 60) and job["label"].startswith("Investigate high usage")
    before = client.post("/api/sim/timeline", json={"town": "small_town", "date": iso(plan["d1"]),
                                                    "m2c": {"settings": SLOW, "actions": plan["actions"]}}).json()
    assert not any(j.get("orderId") == oid for j in before["jobs"])  # not before its basic start


# ---- notes, ownership, invoice holds ---------------------------------------------------------------------------
def test_invoice_hold_defers_invoices_and_blocks_the_outsort_release(town, base):
    def invoiced(run: M2CRun, acct: str, a: int, b: int) -> bool:
        return any(inv["account"] == acct and a <= inv["created"] < b for inv in run.books.invoices)

    # An open billing outsort whose account (other installations) is invoiced in the month after it.
    bc, acct, h0, h1 = next((c, a, d, add_bdays(d, 30)) for c in base.cases
                            if c.type in ("HIGH_BILL", "BILL_CREDIT") and c.resolved is None and 60 < c.created < 200
                            for a, d in [(base.account_of(c), add_bdays(int(c.created), 1))]
                            if invoiced(base, a, d, add_bdays(d, 30)))
    hold = {"day": iso(h0), "type": "invoice_hold", "caseId": bc.id, "note": "Customer disputes the bill"}
    with pytest.raises(ActionError, match="invoice hold"):  # releasing the outsort while the hold is on
        M2CRun(town, SLOW, [hold, {"day": iso(h0), "type": "accept", "caseId": bc.id, "note": "Looks fine"}])
    with pytest.raises(ActionError, match="already on hold"):
        M2CRun(town, SLOW, [hold, {**hold, "caseId": None, "accountId": acct}])
    actions = [hold, {"day": iso(h1), "type": "invoice_unhold", "accountId": acct, "note": "Dispute settled"},
               {"day": iso(h1), "type": "accept", "caseId": bc.id, "note": "Usage confirmed with the customer"}]
    run = run_for(RunRequest(town="small_town", settings=SLOW, actions=actions))
    assert not run.warnings
    hc = next(c for c in run.cases if c.work == "hold")
    assert hc.ref == acct and hc.source == bc.id and int(hc.resolved) == h1
    assert not invoiced(run, acct, h0, h1)
    deferred = [x for e in hc.events if e[1] == "INVOICE_DEFERRED" for x in e[2]["billingDocumentIds"]]
    assert deferred
    after = [inv for inv in run.books.invoices if inv["account"] == acct and inv["created"] >= h1]
    issued = {run.books.doc_id(run.books.docs[k]) for inv in after for k in inv["docs"]}
    assert set(deferred) <= issued
    released = run.case_index[bc.id]
    assert released.outcome == "release" and int(released.resolved) == h1
    # The same day works too: hold, settle the dispute, then release (all three land at 09:00, in order).
    same = [hold, {"day": iso(h0), "type": "invoice_unhold", "caseId": bc.id, "note": "Settled on the phone"},
            {"day": iso(h0), "type": "accept", "caseId": bc.id, "note": "Usage confirmed"}]
    run_same = M2CRun(town, SLOW, same)
    assert run_same.case_index[bc.id].outcome == "release" and int(run_same.case_index[bc.id].resolved) == h0
    rehold = M2CRun(town, SLOW, [hold, same[1], {**hold, "note": "Second dispute"}])  # a new hold after the unhold
    assert sum(c.work == "hold" for c in rehold.cases) == 2
    mid = views.case_view(run, bc.id, as_of=iso(h0))
    assert mid["invoiceHold"]["caseId"] == hc.id and mid["category"] == "Billing Outsorts"
    assert "accept" not in mid["actions"] and "invoice_unhold" in mid["studioActions"]
    assert views.case_view(run, hc.id, as_of=iso(h0))["category"] == "Invoice Outsorts"
    notes = [n["text"] for n in views.case_view(run, bc.id, as_of=iso(h1))["notes"]]
    assert notes == ["Usage confirmed with the customer"]
    held = views.worklist(run, None, as_of=iso(h0), category="Invoice Outsorts")
    assert [r["caseId"] for r in held["rows"]] == [hc.id] and held["rows"][0]["accountId"] == acct


# ---- categories and worklists -----------------------------------------------------------------------------------
def test_categories_partition_the_worklist(base):
    end = "2026-09-30"
    every = views.worklist(base, None, as_of=end, status="all", page_size=1)["total"]
    totals = {k: views.worklist(base, None, as_of=end, status="all", category=k, page_size=200)
              for k in cat.CATEGORIES}
    assert sum(w["total"] for w in totals.values()) == every
    for k, w in totals.items():
        assert all(r["category"] == k for r in w["rows"]), k
    assert all(r["type"] in cat.MISSING_TYPES for r in totals["Meter Read Follow-Up"]["rows"])
    assert all(r["type"] == "RATE_CLASS" for r in totals["Billing Errors"]["rows"])
    assert totals["Invoice Outsorts"]["total"] == 0  # nobody placed a hold
    for k in cat.NO_ENGINE_CATEGORIES:
        assert views.worklist(base, None, as_of=end, status="all", category=k)["total"] == 0
    with pytest.raises(ValueError):
        views.worklist(base, None, category="Nope")
    row = totals["MR Implausibles"]["rows"][0]
    assert {"meterId", "readType", "observed", "previous", "consumption", "expected", "validationText"} <= set(row)


# ---- lookups ------------------------------------------------------------------------------------------------------
def test_installation_and_read_document_lookups(base, source):
    tw = base.town
    inst = tw.installation[source.r]
    view = lookups.installation(base, inst, as_of="2026-09-30")
    regs = {g["registerId"] for m in view["meters"] for g in m["registers"]}
    assert tw.reg_ids[source.r] in regs and all(rd["registerId"] in regs for rd in view["reads"])
    assert view["billingDocuments"] and all(d["installationId"] == inst for d in view["billingDocuments"])
    assert all(d["lines"] for d in view["billingDocuments"])
    accounts = {a["accountId"] for a in view["accounts"]}
    assert {c["accountId"] for c in view["contracts"]} == accounts and view["accounts"][0]["businessPartner"]
    docs = {d["id"] for d in view["billingDocuments"]}
    assert view["invoices"] and all(docs & set(inv["billingDocumentIds"]) for inv in view["invoices"])
    assert source.id in [c["caseId"] for c in view["cases"]]
    early = lookups.installation(base, inst, as_of="2026-02-01")
    assert len(early["reads"]) < len(view["reads"]) and len(early["billingDocuments"]) < len(view["billingDocuments"])
    with pytest.raises(KeyError):
        lookups.installation(base, "IN-nope")
    read_id = base.read_id(source.r, source.month)
    doc = lookups.read_document(base, read_id, as_of="2026-09-30")
    assert doc["installationId"] == inst and doc["read"]["id"] == read_id and doc["case"]["caseId"] == source.id
    assert doc["decision"]["readId"] == read_id and doc["contractId"] in {c["contractId"] for c in view["contracts"]}
    assert doc["businessPartnerId"] == tw.accounts[doc["accountId"]]["businessPartnerId"]
    with pytest.raises(KeyError):  # not read yet on that date
        lookups.read_document(base, read_id, as_of=iso(int(source.created) - 2))


def test_possible_entries_are_paged_and_bounded(base, source):
    tw = base.town
    inst = tw.installation[source.r]
    hit = lookups.possible_entries(base, "installation", inst)
    assert hit["entries"][0]["id"] == inst and tw.address[tw.prem[source.r]] in hit["entries"][0]["text"]
    reads = lookups.possible_entries(base, "read", tw.meter_ids[tw.meter_of[source.r]], as_of="2026-09-30")
    assert base.read_id(source.r, source.month) in [e["id"] for e in reads["entries"]]
    p1 = lookups.possible_entries(base, "premise", "street", page=1, page_size=5)
    p2 = lookups.possible_entries(base, "premise", "street", page=2, page_size=5)
    assert p1["total"] > 10 and len(p1["entries"]) == 5 and p1["entries"] != p2["entries"]
    assert len(lookups.possible_entries(base, "read", "", page_size=500)["entries"]) == lookups.PAGE_MAX
    acct = tw.accounts[next(iter(tw.accounts))]["sapContractAccount"]
    assert lookups.possible_entries(base, "account", acct)["total"] >= 1
    with pytest.raises(ValueError):
        lookups.possible_entries(base, "meter", "")


# ---- hosted API ---------------------------------------------------------------------------------------------------
def test_hosted_studio_api(source, plan):
    client = TestClient(app)
    voc = client.get("/api/m2c/vocabulary", params={"town": "small_town"}).json()
    assert voc["order"]["choices"]["plant"] == ["SM01 · Small Town"] and voc["order"]["components"]["units"] == ["EA", "M"]
    assert set(voc["order"]["required"]) == set(ords.REQUIRED) and "Field Work" in voc["categories"]
    assert "order_release" in client.get("/api/m2c/settings").json()["actionTypes"]
    body = {"town": "small_town", "settings": SLOW, "asOf": iso(plan["d1"])}
    bad = [plan["actions"][0], {"day": iso(plan["d0"]), "type": "order_release", "orderId": plan["oid"]}]
    r = client.post("/api/m2c/summary", json={**body, "actions": bad})
    assert r.status_code == 422 and r.json()["detail"]["fieldErrors"]["plant"] == "Planning plant is required."
    ok = client.post("/api/m2c/order", json={**body, "actions": plan["actions"][:5], "sourceCaseId": source.id})
    assert ok.status_code == 200 and ok.json()["order"]["stage"] == "Dispatched"
    q = client.post("/api/process/queue", json={**body, "queue": "BILLING", "pageSize": 3})
    assert q.status_code == 200 and all(row["queue"] == "BILLING" for row in q.json()["rows"])
    cats = client.post("/api/process/queue", json={**body, "category": "Meter Read Follow-Up", "pageSize": 3}).json()
    assert cats["category"] == "Meter Read Follow-Up" and cats["total"] > 0
    assert client.post("/api/process/queue", json={**body, "category": "Nope"}).status_code == 422
    assert client.post("/api/m2c/installation", json={**body, "installationId": "IN-nope"}).status_code == 404
    assert client.post("/api/m2c/read-document", json={**body, "readId": "READ-nope"}).status_code == 404
    assert client.post("/api/m2c/order", json={**body, "orderId": "WO-nope"}).status_code == 404
    pe = client.post("/api/m2c/possible-entries", json={**body, "kind": "read", "query": "", "pageSize": 51})
    assert pe.status_code == 422


def test_studio_responses_fit_the_hosted_limit_on_cobourg():
    client = TestClient(app)
    town = _town("large_town")
    read_id = town.read_id(0, 11)
    acct = next(iter(town.accounts))
    actions = [{"day": "2026-12-01", "type": "order_save", "readId": read_id, "fields": {"shortText": "Visit"}},
               {"day": "2026-12-01", "type": "invoice_hold", "accountId": acct, "note": "Disputed"}]
    run = {"town": "large_town", "asOf": "2026-12-01", "actions": actions}
    field = client.post("/api/process/queue", json={**run, "category": "Field Work", "search": "WO-261201-0001"})
    work = field.json()["rows"][0]
    assert work["orderId"] == "WO-261201-0001" and work["readId"] == read_id
    inst = town.installation[0]
    replies = [field, client.post("/api/m2c/summary", json=run),
               client.post("/api/process/queue", json={**run, "status": "all", "pageSize": 200}),
               client.post("/api/process/queue", json={**run, "category": "Field Work", "status": "all",
                                                       "pageSize": 200}),
               client.post("/api/m2c/case", json={**run, "caseId": work["caseId"]}),
               client.post("/api/m2c/order", json={**run, "readId": read_id}),
               client.post("/api/m2c/installation", json={**run, "installationId": inst}),
               client.post("/api/m2c/read-document", json={**run, "readId": read_id}),
               client.post("/api/m2c/possible-entries", json={**run, "kind": "read", "pageSize": 50}),
               client.post("/api/process/queue", json={**run, "category": "Invoice Outsorts"})]
    for r in replies:
        assert r.status_code == 200 and len(r.content) < LIMIT, r.text[:200]
    assert orjson.loads(replies[5].content)["order"]["stage"] == "Draft"
    assert orjson.loads(replies[-1].content)["total"] == 1
