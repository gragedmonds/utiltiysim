"""Collections worklists and work, outage follow-up, AMI collector links and period statistics on the meter-to-cash
run (hosted runtime). Accounts, invoices, cases and premises are discovered from the run, never hard-coded."""

from __future__ import annotations

import orjson
import pytest
from fastapi.testclient import TestClient

from api._m2c import RunRequest, run_for
from api.index import app
from utilsim.m2c import catalog as cat
from utilsim.m2c import collections as colls
from utilsim.m2c import followup, views
from utilsim.m2c.calendar import calendar
from utilsim.m2c.run import ActionError, M2CRun

CAL = calendar(2026)
date_of = CAL.date_of
parse_day = CAL.parse_day

DAY = "2026-08-05"  # the day the analyst works the Collections lists
D = parse_day(DAY, 0)
LIMIT = 4_500_000


def iso(day: int) -> str:
    return date_of(day).isoformat()


@pytest.fixture(scope="module")
def base() -> M2CRun:
    return run_for(RunRequest(town="small_town"))


def _rows(run, kind, **kw):
    out, page = [], 1
    while True:
        res = colls.collections_list(run, kind, as_of=DAY, page=page, page_size=200, **kw)
        out += res["rows"]
        if page * 200 >= res["total"]:
            return out
        page += 1


@pytest.fixture(scope="module")
def plan(base) -> dict:
    """Distinct accounts and invoices for each collections action on DAY, found in the lists of the base run."""
    used: set[str] = set()

    def pick(rows, ok):
        hit = next(r for r in rows if r["accountId"] not in used and ok(r))
        used.add(hit["accountId"])
        return hit

    overdue = _rows(base, "overdue", sort="amount")
    notices = _rows(base, "disconnect")
    arr = pick(overdue, lambda r: "payment_arrangement" in r["actions"] and not any(r["flags"].values()))
    approve = pick(notices, lambda r: "disconnect_approve" in r["actions"] and r["state"] == "pending")
    cancel = pick(notices, lambda r: "disconnect_cancel" in r["actions"] and r["state"] == "pending")
    waive = pick(notices, lambda r: "waive_fee:late_fee" in r["actions"])
    referral = pick(overdue, lambda r: "low_income_referral" in r["actions"] and r["flags"]["lowIncome"] is None)
    budget = pick(overdue, lambda r: "budget_billing" in r["actions"])

    def next_step(acct):  # an unpaid invoice whose next dunning step falls within 30 days of DAY
        for inv in base.books.collections.accounts[acct].invs:
            if inv["issued"] <= D and (inv.get("paid") or 999) > D and any(D < t < D + 30 for t, _ in inv["dunning"]):
                return inv
        return None

    hold = pick(overdue, lambda r: "dunning_hold" in r["actions"] and next_step(r["accountId"]) is not None)
    extend = None
    for r in overdue:  # an invoice you may extend today whose overdue notice comes later
        if r["accountId"] in used:
            continue
        now = {i["invoiceId"]: i for i in colls.account_view(base, r["accountId"], as_of=DAY)["invoices"]}
        for i in colls.account_view(base, r["accountId"], as_of="2026-12-31")["invoices"]:
            if "extend_due" in now.get(i["invoiceId"], {}).get("actions", []) and any(
                    d["type"] == "DUNNING_NOTICE" and d["at"][:10] > DAY for d in i["dunning"]):
                extend = now[i["invoiceId"]]
                break
        if extend is not None:
            used.add(r["accountId"])
            break
    assert extend is not None
    actions = [
        {"id": "C1", "day": DAY, "type": "payment_arrangement", "accountId": arr["accountId"], "instalments": 4,
         "note": "Four monthly instalments agreed by phone"},
        {"id": "C2", "day": DAY, "type": "disconnect_approve", "invoiceId": approve["invoiceId"]},
        {"id": "C3", "day": DAY, "type": "disconnect_cancel", "invoiceId": cancel["invoiceId"],
         "note": "Medical certificate on file"},
        {"id": "C4", "day": DAY, "type": "extend_due", "invoiceId": extend["invoiceId"], "days": 20},
        {"id": "C5", "day": DAY, "type": "dunning_hold", "accountId": hold["accountId"], "days": 30,
         "note": "Bill dispute under review"},
        {"id": "C6", "day": DAY, "type": "waive_fee", "invoiceId": waive["invoiceId"], "fee": "late_fee"},
        {"id": "C7", "day": DAY, "type": "low_income_referral", "accountId": referral["accountId"]},
        {"id": "C8", "day": DAY, "type": "budget_billing", "accountId": budget["accountId"]},
        {"id": "C9", "day": DAY, "type": "note", "caseId": f"CASE-{date_of(D):%y%m%d}-L0007",
         "text": "Customer sent the application form"},
    ]
    return {"arr": arr, "approve": approve, "cancel": cancel, "extend": extend, "hold": hold, "waive": waive,
            "referral": referral, "budget": budget, "actions": actions}


@pytest.fixture(scope="module")
def worked(plan) -> M2CRun:
    run = run_for(RunRequest(town="small_town", actions=plan["actions"]))
    assert not run.warnings
    return run


# ---- the lists -----------------------------------------------------------------------------------------------------
def test_collections_lists_are_paged_filtered_and_sorted(base):
    for kind in colls.LISTS:  # (in August nothing is held for the winter any more: all, not open)
        first = colls.collections_list(base, kind, as_of=DAY, status="all", page_size=7)
        assert first["total"] > 0 and set(first["counts"]) == set(colls.LISTS), kind
        assert first["counts"][kind] == sum(r["open"] for r in _rows(base, kind, status="all"))
        pages, ids = -(-first["total"] // 7), []
        for p in range(1, min(pages, 4) + 1):
            rows = colls.collections_list(base, kind, as_of=DAY, status="all", page=p, page_size=7)["rows"]
            ids += [r.get("invoiceId", r["accountId"]) + r.get("rejectedAt", "") for r in rows]
            assert all(isinstance(r["actions"], list) and set(r["flags"]) >= {"arrangementId", "lowIncome"}
                       for r in rows)
        assert len(ids) == len(set(ids))  # pages never overlap
        money = "overdue" if kind == "overdue" else "outstanding"
        big = colls.collections_list(base, kind, as_of=DAY, sort="amount", page_size=50)["rows"]
        assert [r[money] for r in big] == sorted((r[money] for r in big), reverse=True)
    old = colls.collections_list(base, "overdue", as_of=DAY, sort="age", page_size=50)["rows"]
    assert [r["ageDays"] for r in old] == sorted((r["ageDays"] for r in old), reverse=True)
    one = old[3]
    hit = colls.collections_list(base, "overdue", as_of=DAY, search=one["accountId"].lower())
    assert [r["accountId"] for r in hit["rows"]] == [one["accountId"]]
    # A pending notice is unpaid; a paid one is closed.
    for r in _rows(base, "disconnect", status="all"):
        assert r["open"] == (r["state"] in ("pending", "approved", "disconnected"))
        assert r["outstanding"] > 0 if r["state"] == "pending" else r["state"] != "paid" or r["outstanding"] == 0
    with pytest.raises(ValueError):
        colls.collections_list(base, "nope")
    big = colls.collections_list(base, "disconnect", as_of="2026-12-31", status="all", page_size=200)
    assert len(orjson.dumps(big)) < LIMIT


def test_the_winter_moratorium_holds_notices_until_may(base):
    held = colls.collections_list(base, "moratorium", as_of="2026-03-31", status="all", page_size=200)
    assert held["total"] > 0 and all(r["heldUntil"] == "2026-05-01" for r in held["rows"])
    assert all(set(r["commodities"]) & {"electric", "water"} for r in held["rows"])
    later = {r["invoiceId"]: r for r in colls.collections_list(base, "moratorium", as_of="2026-05-15", status="all",
                                                               page_size=200)["rows"]}
    for r in held["rows"]:  # nothing stays held past the moratorium, unless other collections work holds it
        after = later[r["invoiceId"]]
        assert after["state"] in ("paid", "notice issued") or after["heldBy"], after
        if after["state"] == "notice issued":
            assert after["noticeAt"][:10] >= "2026-05-01"


def test_rejected_payments_carry_their_nsf_fee(base):
    rows = _rows(base, "rejected", status="all")
    assert rows and all(r["nsfFee"] == base.cfg.billing.nsf_fee for r in rows if r["rejectedAt"][:10] < "2026-08-01")
    assert all(r["repaidAt"] for r in rows if r["state"] == "repaid")
    assert any("waive_fee:nsf_fee" in r["actions"] for r in rows)


# ---- the simulated call centre fills Low Income Process and Budget Bill Cases ----------------------------------------
def test_low_income_and_budget_categories_fill_at_the_run_rates(base):
    li = views.worklist(base, None, as_of="2026-12-31", status="all", category="Low Income Process", page_size=200)
    bb = views.worklist(base, None, as_of="2026-12-31", status="all", category="Budget Bill Cases", page_size=200)
    assert li["total"] > 0 and bb["total"] > 0
    assert {r["type"] for r in li["rows"]} == {"LOW_INCOME"} and {r["type"] for r in bb["rows"]} == {"BUDGET_BILL"}
    assert all(r["createdBy"] == "collections" and r["queue"] == "COLLECTIONS" for r in li["rows"] + bb["rows"])
    done = [r for r in li["rows"] if r["resolvedAt"]]
    assert done and {r["outcome"] for r in done} <= {"approved", "declined"}
    c = views.case_view(base, done[0]["caseId"], as_of="2026-12-31")
    assert c["collections"]["referral"]["outcome"] == done[0]["outcome"] and c["decision"] is None
    assert c["studioActions"] == [] and c["readHistory"] == [] and c["history"] == []
    open_ = views.worklist(base, None, as_of=DAY, category="Low Income Process")
    assert all(r["status"] != "resolved" for r in open_["rows"])
    off = run_for(RunRequest(town="small_town", settings={"billing": {"low_income_referral_rate": 0,
                                                                "budget_billing_offer_rate": 0}}))
    for k in ("Low Income Process", "Budget Bill Cases"):
        assert views.worklist(off, None, as_of="2026-12-31", status="all", category=k)["total"] == 0
    assert views.summary(off, "2026-12-31")["billing"]["collections"]["lowIncome"]["referred"] == 0


# ---- your collections work changes the books from its day on --------------------------------------------------------
def test_collections_actions_never_change_the_past(base, worked):
    before = iso(D - 1)
    a, b = views.summary(base, before), views.summary(worked, before)
    for k in ("kpis", "billing", "queues"):
        assert a[k] == b[k], k
    for kind in colls.LISTS:
        assert colls.collections_list(base, kind, as_of=before)["rows"] == \
            colls.collections_list(worked, kind, as_of=before)["rows"]


def test_a_payment_arrangement_replaces_dunning_with_instalments(base, worked, plan):
    acct = plan["arr"]["accountId"]
    v = colls.account_view(worked, acct, as_of="2026-12-31")
    (arr,) = v["arrangements"]
    t9 = D + 9.0 / 24
    owed = sum(colls.owed(i, t9) for i in base.books.collections.accounts[acct].invs if colls.is_overdue(i, t9))
    assert arr["instalments"] == 4 and len(arr["schedule"]) == 4 and arr["amount"] == pytest.approx(owed, abs=0.01)
    assert arr["schedule"][0]["dueAt"] == iso(D + 7) and round(sum(s["amount"] for s in arr["schedule"]), 2) == \
        arr["amount"]
    paid = [p for i in v["invoices"] for p in i["payments"] if p["status"] == "instalment"]
    assert paid and all(p["at"][:10] > DAY for p in paid)
    end = arr["endedAt"] or "2026-12-31T23:59:59Z"
    for inv in v["invoices"]:  # no dunning on the covered bills while the arrangement runs
        if inv["invoiceId"] in arr["invoiceIds"]:
            assert not [d for d in inv["dunning"] if DAY < d["at"][:10] and d["at"] < end
                        and d["type"] in (*colls.STEPS, "MORATORIUM_HOLD")]
    assert v["log"][0]["type"] == "PAYMENT_ARRANGEMENT" and v["log"][0]["note"].startswith("Four")
    flags = colls.account_view(worked, acct, as_of=iso(D + 1))["flags"]
    assert flags["arrangementId"] == arr["arrangementId"]
    # A second arrangement while one runs is refused, and says why.
    with pytest.raises(ActionError, match="already has payment arrangement"):
        M2CRun(worked.town, None, [*plan["actions"], {"id": "X", "day": iso(D + 1), "type": "payment_arrangement",
                                                     "accountId": acct}])


def test_disconnections_need_your_approval(base, worked, plan):
    def row(run, inv, at="2026-12-31"):
        return colls.collections_list(run, "disconnect", as_of=at, status="all", search=inv)["rows"][0]

    ok = row(worked, plan["approve"]["invoiceId"])
    assert ok["approvedAt"][:10] == DAY and ok["state"] in ("disconnected", "reconnected", "paid")
    if ok["disconnectedAt"]:
        assert ok["disconnectedAt"][:10] >= max(DAY, ok["earliestDisconnectAt"])
        assert row(base, plan["approve"]["invoiceId"])["disconnectedAt"] is None  # never without approval
    assert row(worked, plan["cancel"]["invoiceId"])["state"] == "cancelled"
    assert all(r["state"] != "disconnected" for r in _rows(base, "disconnect", status="all"))
    with pytest.raises(ActionError, match="was cancelled"):
        M2CRun(worked.town, None, [*plan["actions"], {"id": "X", "day": iso(D + 1), "type": "disconnect_approve",
                                                     "invoiceId": plan["cancel"]["invoiceId"]}])


def test_an_extension_and_a_hold_postpone_dunning(base, worked, plan):
    iid = plan["extend"]["invoiceId"]
    acct = colls.invoice_account(iid)

    def inv(run, at="2026-12-31"):
        return next(i for i in colls.account_view(run, acct, as_of=at)["invoices"] if i["invoiceId"] == iid)

    a, b = inv(base), inv(worked)
    assert date_of(parse_day(b["dueAt"], 0)) == date_of(parse_day(a["dueAt"], 0) + 20)
    assert inv(worked, iso(D - 1))["dueAt"] == a["dueAt"]  # as of the day before, the old due date
    notice = [d["at"] for d in a["dunning"] if d["type"] == "DUNNING_NOTICE"]
    later = [d["at"] for d in b["dunning"] if d["type"] == "DUNNING_NOTICE"]
    assert not later or later[0][:10] >= iso(parse_day(notice[0], 0) + 20)
    acct = plan["hold"]["accountId"]
    v = colls.account_view(worked, acct, as_of="2026-12-31")
    assert v["holds"][0]["until"] == iso(D + 30) and v["holds"][0]["note"] == "Bill dispute under review"
    for i in v["invoices"]:
        assert not [d for d in i["dunning"] if DAY < d["at"][:10] < iso(D + 30) and d["type"] in colls.STEPS]


def test_a_waived_fee_leaves_the_balance(base, worked, plan):
    iid = plan["waive"]["invoiceId"]
    acct = colls.invoice_account(iid)
    fee = plan["waive"]["fees"]["late_fee"]
    led = [e for e in colls.account_view(worked, acct, as_of="2026-12-31")["ledger"] if e["type"] == "fee_waived"]
    assert [e["amount"] for e in led] == [-fee] and led[0]["ref"] == iid
    assert worked.books.balance(acct, D + 0.5) == pytest.approx(base.books.balance(acct, D + 0.5) - fee, abs=0.01)
    with pytest.raises(ActionError, match="no late fee to waive"):
        M2CRun(worked.town, None, [*plan["actions"], {"id": "X", "day": iso(D + 1), "type": "waive_fee",
                                                     "invoiceId": iid}])


def test_your_referral_and_enrolment_open_cases_you_can_note(base, worked, plan):
    cid = f"CASE-{date_of(D):%y%m%d}-L0007"
    c = views.case_view(worked, cid, as_of=iso(D + 1))
    assert c["category"] == "Low Income Process" and c["accountId"] == plan["referral"]["accountId"]
    assert c["createdBy"] == "studio" and c["owner"] == "you" and c["studioActions"] == ["note", "assign"]
    assert [n["text"] for n in c["notes"]] == ["Customer sent the application form"]
    assert c["actions"] == [] and c["collections"]["referral"]["outcome"] is None
    li = views.worklist(worked, None, as_of=iso(D + 1), category="Low Income Process", status="all")
    li0 = views.worklist(base, None, as_of=iso(D + 1), category="Low Income Process", status="all")
    assert li["total"] == li0["total"] + 1
    done = views.case_view(worked, cid, as_of="2026-12-31")
    assert done["resolvedAt"] and done["outcome"] in ("approved", "declined")
    if done["outcome"] == "approved":
        assert done["collections"]["referral"]["grant"] > 0
    acct = plan["budget"]["accountId"]
    v = colls.account_view(worked, acct, as_of="2026-12-31")
    p = v["budgetPlan"]
    assert p["source"] == "you" and p["active"] and p["startsAt"][:10] > DAY
    after = [i for i in v["invoices"] if i["issuedAt"] > p["startsAt"][:10]]
    assert after and all(i["amountDue"] == p["instalment"] and i["budgetBilling"] for i in after)
    assert any(e["type"] == "budget_deferral" for e in v["ledger"])
    bb = views.case_view(worked, f"CASE-{date_of(D):%y%m%d}-B0008", as_of="2026-12-31")
    assert bb["category"] == "Budget Bill Cases" and bb["outcome"] == "plan_created"
    master = next(a for a, m in worked.town.accounts.items() if m.get("budgetBilling")
                  and a in worked.books.collections.accounts)
    with pytest.raises(ActionError, match="on budget billing"):
        M2CRun(worked.town, None, [*plan["actions"], {"id": "X", "day": iso(D + 1), "type": "budget_billing",
                                                     "accountId": master}])


# ---- outages: last gasps, lost use and the reads they cost --------------------------------------------------------
@pytest.fixture(scope="module")
def outages(base):
    """An electric outage over a read day's AMI electric premises (02:00 read) and, another read day, a collector
    outage over one collector's premises."""
    tw = base.town
    days = sorted(base.batches)
    d1 = next(d for d in days if d > 60 and d in base.bday_set)
    m, rows = base.batches[d1]
    ami = rows[(tw.tech[rows] == "AMI") & (tw.commodity[rows] == "electric")]
    power = sorted({tw.premise_ids[p] for p in tw.prem[ami].tolist()})[:12]
    d2 = next(d for d in days if d > d1 + 3 and d in base.bday_set)
    m2, rows2 = base.batches[d2]
    by_col: dict[str, set] = {}
    for r in rows2[tw.tech[rows2] == "AMI"].tolist():
        by_col.setdefault(tw.collector_of(r), set()).add(tw.premise_ids[tw.prem[r]])
    col = max((c for c in by_col if c), key=lambda c: len(by_col[c]))
    out = [{"day": iso(d1), "utility": "electric", "start": 1800, "end": 4 * 3600, "premiseIds": power},
           {"day": iso(d2), "utility": "ami", "start": 3600, "end": 6 * 3600, "premiseIds": sorted(by_col[col])}]
    return {"d1": d1, "d2": d2, "power": power, "col": col, "silent": sorted(by_col[col]),
            "run": run_for(RunRequest(town="small_town", outages=out))}


def test_outage_followup_lists_last_gasps_lost_use_and_missed_reads(outages):
    run = outages["run"]
    f = followup.outage_followup(run, as_of="2026-12-31", page_size=200)
    carried = [o for o in f["outages"] if o["outageId"].startswith("OUT-")]  # the year's own incidents are INC-
    by = {o["utility"]: o for o in carried}
    assert by["electric"]["premises"] == len(outages["power"]) and by["electric"]["lastGasps"] == len(outages["power"])
    assert by["electric"]["lostUse"] > 0 and by["electric"]["missedReads"] > 0
    assert by["ami"]["collectorOutage"] and by["ami"]["lostUse"] == 0 and by["ami"]["missedReads"] > 0
    rows = followup.outage_followup(run, as_of="2026-12-31", outage=by["electric"]["outageId"], page_size=200)["rows"]
    assert rows and all(r["lastGasp"] and r["lostUse"] > 0 and r["unit"] == "kWh" for r in rows)
    hit = next(r for r in rows if r["missedReads"])
    read = hit["missedReads"][0]
    c = views.case_view(run, read["caseId"], as_of="2026-12-31")
    assert c["type"] == "COMM_FAIL" and c["cause"]["code"] == "power_outage" and c["readId"] == read["readId"]
    assert c["premiseId"] == hit["premiseId"] and hit["outageId"] == by["electric"]["outageId"]
    silent = followup.outage_followup(run, as_of="2026-12-31", utility="ami", kind="missed_read", page_size=200)
    assert silent["total"] and all(r["missedReads"][0]["reasonCode"] == "SIM_COLLECTOR_OUTAGE"
                                   for r in silent["rows"])
    assert sum(r["collectorId"] == outages["col"] for r in silent["rows"]) > silent["total"] / 2
    page = followup.outage_followup(run, as_of="2026-12-31", page=2, page_size=5)
    assert page["page"] == 2 and len(page["rows"]) <= 5 and page["total"] == f["total"]
    assert followup.outage_followup(run, as_of=iso(outages["d1"] - 1), outage="OUT-1")["total"] == 0  # not yet
    with pytest.raises(ValueError):
        followup.outage_followup(run, kind="nope")


def test_comm_fails_link_to_their_collector(outages):
    run, col, d2 = outages["run"], outages["col"], outages["d2"]
    g = followup.collector_groups(run, as_of=iso(d2 + 1), status="all", collector=col)
    group = next(x for x in g["groups"] if x["day"] == iso(d2))
    assert group["cases"] >= 2 and group["cause"]["code"] == "collector_outage"
    assert group["label"] == f"{group['cases']} cases on collector {col}" and group["streets"]
    assert any(c["collectorId"] == col and c["meters"] > 0 for c in g["collectors"])
    rows, page, total = [], 1, 1
    while len(rows) < total:
        res = views.worklist(run, None, as_of=iso(d2 + 1), status="all", collector=col, created_on=iso(d2),
                             page=page, page_size=200)
        rows, page, total = rows + res["rows"], page + 1, res["total"]
    assert set(group["caseIds"]) == {r["caseId"] for r in rows if r["type"] in cat.MISSING_TYPES}
    assert all(r["collectorId"] == col and r["createdAt"][:10] == iso(d2) for r in rows)
    assert all(r["collectorCases"] == group["cases"] for r in rows if r["caseId"] in group["caseIds"])
    c = views.case_view(run, group["caseIds"][0], as_of=iso(d2 + 1))
    net = c["network"]
    assert net["collectorId"] == col and net["cases"] == group["cases"] and net["day"] == iso(d2)
    related = {x["caseId"] for x in net["relatedCases"]}  # the others on that collector that day (at most 50)
    assert related <= set(group["caseIds"]) - {c["caseId"]} and len(related) == min(50, group["cases"] - 1)
    # Rows of meters that are not AMI have no collector.
    other = views.worklist(run, None, as_of=iso(d2 + 1), status="all", page_size=200)["rows"]
    assert all(r["collectorId"] is None for r in other if r["technology"] != "AMI")


# ---- run statistics for a period --------------------------------------------------------------------------------------
def test_run_statistics_for_a_period(base):
    ytd = views.summary(base, DAY, since="2026-01-01")
    w = ytd["window"]
    assert w["since"] == "2026-01-01" and w["days"] == D + 1
    for k in ("reads", "actual", "missing", "casesOpened", "casesResolved", "fieldOrders", "truckRolls"):
        assert w["kpis"][k] == ytd["kpis"][k], k
    for k in ("documents", "invoices", "collected"):
        assert w["billing"][k] == pytest.approx(ytd["billing"][k], abs=0.01), k
    assert w["billing"]["dunning"] == ytd["billing"]["dunning"]
    assert w["kpis"]["costs"]["total"] == pytest.approx(ytd["kpis"]["costs"]["total"], abs=0.05)
    a = views.summary(base, "2026-06-30", since="2026-01-01")["window"]
    b = views.summary(base, DAY, since="2026-07-01")["window"]
    for k in ("reads", "casesOpened", "fieldOrders"):
        assert a["kpis"][k] + b["kpis"][k] == w["kpis"][k], k
    assert a["billing"]["collected"] + b["billing"]["collected"] == pytest.approx(w["billing"]["collected"], abs=0.05)
    assert b["billing"]["overdueAtStart"] == pytest.approx(a["billing"]["overdue"], abs=0.01)
    assert b["kpis"]["casesOpenAtStart"] == a["kpis"]["casesOpen"]
    assert "window" not in views.summary(base, DAY)


# ---- the API --------------------------------------------------------------------------------------------------------
def test_collections_api(plan):
    client = TestClient(app)
    body = {"town": "small_town", "asOf": DAY}
    vocab = client.get("/api/m2c/vocabulary", params={"town": "small_town"}).json()
    assert vocab["actions"]["collections"] == list(colls.ACTIONS) and vocab["collections"]["lists"] == list(colls.LISTS)
    assert "Low Income Process" in vocab["categories"] and "Low Income Process" not in vocab["emptyCategories"]
    schema = client.get("/api/m2c/settings").json()["schema"]
    billing = schema["properties"]["billing"]["properties"]
    for k in ("low_income_referral_rate", "budget_billing_offer_rate", "disconnect_notice_days",
              "arrangement_break_rate", "low_income_approval_rate"):
        assert "default" in billing[k] and ("maximum" in billing[k] or billing[k].get("type") == "boolean"), k
    res = client.post("/api/m2c/collections", json={**body, "list": "overdue", "sort": "amount", "pageSize": 5})
    assert res.status_code == 200 and res.json()["schemaVersion"] == "m2c-collections/1.0"
    acct = res.json()["rows"][0]["accountId"]
    view = client.post("/api/m2c/collections/account", json={**body, "accountId": acct}).json()
    assert view["schemaVersion"] == "m2c-collections-account/1.0" and view["overdue"] > 0 and view["invoices"]
    assert client.post("/api/m2c/collections/account", json={**body, "accountId": "CA-nope"}).status_code == 404
    assert client.post("/api/m2c/collections", json={**body, "list": "nope"}).status_code == 422
    fu = client.post("/api/m2c/outage-followup", json=body).json()  # no outages carried in: the year's own
    assert fu["total"] > 0 and all(r["outageId"].startswith("INC-") for r in fu["rows"])
    assert client.post("/api/m2c/collector-groups", json={**body, "status": "all"}).json()["schemaVersion"] == \
        "m2c-collector-groups/1.0"
    s = client.post("/api/m2c/summary", json={**body, "since": "2026-07-06"}).json()
    assert s["window"]["since"] == "2026-07-06" and s["window"]["days"] == 31
    act = {**body, "actions": [plan["actions"][0]], "list": "overdue", "search": plan["arr"]["accountId"]}
    row = client.post("/api/m2c/collections", json=act).json()["rows"][0]
    assert row["flags"]["arrangementId"] and "payment_arrangement" not in row["actions"]
    bad = {**body, "actions": [{**plan["actions"][0], "instalments": 40}]}
    assert client.post("/api/m2c/summary", json=bad).status_code == 422
    late = {**body, "actions": [{"day": "2026-01-02", "type": "payment_arrangement", "accountId": acct}]}
    r = client.post("/api/m2c/summary", json=late)
    assert r.status_code == 422 and "nothing overdue" in r.json()["detail"]
    q = client.post("/api/process/queue", json={**body, "queue": "COLLECTIONS", "status": "all"}).json()
    assert q["total"] > 0 and all(r["category"] in ("Low Income Process", "Budget Bill Cases") for r in q["rows"])
    assert all(r["type"] in cat.COLLECTION_TYPES for r in q["rows"])
