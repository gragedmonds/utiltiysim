"""The Data pages' flat tables (utilsim/m2c/tables.py) and their endpoints on the hosted runtime: every table builds
for the small town as of a date, pages stay small, filters, search, sorting and paging agree with the run, CSV pages stitch."""

from __future__ import annotations

import csv
import io

import numpy as np
import orjson
import pytest
from fastapi.testclient import TestClient

from api._m2c import RunRequest, _master, run_for
from api.index import app
from utilsim.m2c import tables as T
from utilsim.m2c import views
from utilsim.m2c.base import date_of

DAY = "2026-08-05"
LIMIT = 4_500_000
RUN_TABLES = [s.name for s in T.SPECS if s.source == "run" and s.name not in ("fieldOrders", "interruptions")]


@pytest.fixture(scope="module")
def run():
    return run_for(RunRequest(town="small_town"))


@pytest.fixture(scope="module")
def master():
    return _master("small_town")


def test_catalog_lists_every_table_once_with_well_formed_columns():
    cat = T.catalog()
    names = [t["name"] for g in cat["groups"] for t in g["tables"]]
    assert sorted(names) == sorted(s.name for s in T.SPECS) and len(set(names)) == len(names)
    assert [g["id"] for g in cat["groups"]] == [g for g, _ in T.GROUPS]
    for s in T.SPECS:
        keys = [c.key for c in s.cols]
        assert len(set(keys)) == len(keys), s.name
        assert all(c.kind in T.KINDS for c in s.cols), s.name
        assert all(c.link in T.LINKS for c in s.cols if c.link), s.name
        assert s.source in ("town", "run", "both") and s.description


def test_every_table_builds_with_bounded_pages(run, master):
    for s in T.SPECS:
        res = T.page(run, master, s.name, as_of=DAY, page_size=T.PAGE_MAX)
        assert res["schemaVersion"] == T.TABLE_VERSION and res["table"] == s.name and res["asOf"] == DAY
        assert [c["key"] for c in res["columns"]] == [c.key for c in s.cols]
        assert all(len(r) == len(s.cols) for r in res["rows"])
        assert len(orjson.dumps(res)) < LIMIT, s.name
        if s.name in RUN_TABLES or s.source != "run":
            assert res["total"] > 0, s.name
        for key, values in res["facets"].items():
            assert sum(v["count"] for v in values) <= res["rowsInTable"] and len(values) <= T.FACET_MAX, (s.name, key)
        csv_text = T.csv_page(run, master, s.name, as_of=DAY, page_size=T.CSV_MAX)
        assert len(csv_text.encode()) < LIMIT, s.name


def test_run_tables_agree_with_the_run(run, master):
    day, Tt = views.as_of_t(run, DAY)
    bk = run.books
    reads = T.page(run, master, "reads", as_of=DAY, page_size=1)
    assert reads["total"] == int((run.read_t[:, 1:] <= Tt).sum())
    docs = T.page(run, master, "billingDocuments", as_of=DAY, page_size=1)
    assert docs["total"] == sum(1 for d in bk.docs if d["created"] <= Tt)
    invoices = T.page(run, master, "invoices", as_of=DAY, page_size=1)
    assert invoices["total"] == sum(1 for inv in bk.invoices if inv["created"] <= Tt)
    payments = T.page(run, master, "payments", as_of=DAY, page_size=1)
    assert payments["total"] == sum(1 for inv in bk.invoices if inv["created"] <= Tt
                                    for p in inv["payments"] if p["at"] <= Tt)
    cases = T.page(run, master, "cases", as_of=DAY, page_size=1)
    assert cases["total"] == sum(1 for c in run.cases if c.created <= Tt)
    # The view date bounds every run table: nothing from after it, and the year grows the tables.
    early = T.page(run, master, "reads", as_of="2026-02-15", page_size=1)["total"]
    late = T.page(run, master, "reads", as_of="2026-12-31", page_size=1)["total"]
    assert 0 < early < reads["total"] < late
    res = T.page(run, master, "reads", as_of=DAY, sort="readDate", desc=True, page_size=5)
    k = [c["key"] for c in res["columns"]].index("readDate")
    assert all(r[k] <= DAY for r in res["rows"])


def test_usage_matches_billed_use_and_sums_to_the_year(run, master):
    day, Tt = views.as_of_t(run, DAY)
    spec, tbl, _ = T.build(run, master, "usage", DAY)
    keys = [c.key for c in tbl.cols]
    reg, ytd, months = keys.index("registerId"), keys.index("yearToDate"), [keys.index(m) for m in T.MONTHS]
    for i in range(0, tbl.n, 211):
        r = run.town.reg_index[tbl.data[reg][i]]
        vals = [tbl.data[m][i] for m in months]
        for m, v in enumerate(vals, start=1):
            done = run.read_t[r, m] <= Tt and run.release_t[r, m] <= Tt
            assert (v is None) == (not done)
            if done:
                assert abs(v - round(views.billed_use(run, r, m), 3)) < 1e-6
        total = tbl.data[ytd][i]
        assert total is None or abs(total - sum(v for v in vals if v is not None)) < 1e-3


def test_collections_phases_cover_every_account_with_an_invoice(run, master):
    res = T.page(run, master, "collectionsAccounts", as_of=DAY, page_size=1)
    phases = {v["value"]: v["count"] for v in res["facets"]["phase"]}
    assert set(phases) <= set(T.PHASES) and "current" in phases
    assert sum(phases.values()) == res["total"]
    assert {"reminder", "overdue notice", "disconnection notice"} & set(phases), phases
    accounts = T.page(run, master, "accounts", as_of=DAY, page_size=1)
    assert accounts["total"] == len(master["accounts"])
    assert {v["value"] for v in accounts["facets"]["phase"]} <= set(T.PHASES)


def test_filters_search_sort_and_paging(run, master):
    whole = T.page(run, master, "invoices", as_of=DAY, page_size=1)
    overdue = T.page(run, master, "invoices", as_of=DAY, filters={"status": "overdue"}, sort="outstanding",
                     desc=True, page_size=50)
    facet = next(v["count"] for v in whole["facets"]["status"] if v["value"] == "overdue")
    assert 0 < overdue["total"] == facet < whole["total"]
    keys = [c["key"] for c in overdue["columns"]]
    s, o = keys.index("status"), keys.index("outstanding")
    assert all(r[s] == "overdue" for r in overdue["rows"])
    amounts = [r[o] for r in overdue["rows"]]
    assert amounts == sorted(amounts, reverse=True)
    # Paging covers the selection once, in order.
    seen, page, ids = [], 1, keys.index("invoiceId")
    while True:
        res = T.page(run, master, "invoices", as_of=DAY, filters={"status": "overdue"}, sort="outstanding",
                     desc=True, page=page, page_size=50)
        seen += [r[ids] for r in res["rows"]]
        if page * 50 >= res["total"]:
            break
        page += 1
    assert len(seen) == overdue["total"] == len(set(seen))
    # Search by address (a street of this town, lower case), a date prefix on a date column and a number range.
    first = T.page(run, master, "reads", as_of=DAY, filters={"readDate": "2026-06"}, page_size=1)
    rk = [c["key"] for c in first["columns"]]
    street = first["rows"][0][rk.index("address")].split(" ", 1)[1]  # "12 Maple Street" → "Maple Street"
    reads = T.page(run, master, "reads", as_of=DAY, search=street.lower(), filters={"readDate": "2026-06"},
                   page_size=200)
    assert reads["total"] > 0 and all(street in r[rk.index("address")] and r[rk.index("readDate")][:7] ==
                                      "2026-06" for r in reads["rows"])
    big = T.page(run, master, "reads", as_of=DAY, filters={"consumption": "1000.."}, page_size=200)
    assert big["total"] > 0 and all(r[rk.index("consumption")] >= 1000 for r in big["rows"])
    blank = T.page(run, master, "reads", as_of=DAY, filters={"caseId": ""}, page_size=1)
    withcase = T.page(run, master, "reads", as_of=DAY, filters={"veeStatus": "estimated"}, page_size=1)
    assert blank["total"] + withcase["total"] <= reads["rowsInTable"] and withcase["total"] > 0
    # Only some columns, in the asked order; None sorts last both ways.
    sub = T.page(run, master, "cases", as_of=DAY, columns=["caseId", "impact"], sort="impact", page_size=5)
    assert [c["key"] for c in sub["columns"]] == ["caseId", "impact"] and all(len(r) == 2 for r in sub["rows"])
    asc = T.page(run, master, "cases", as_of=DAY, columns=["assignee"], sort="assignee", page_size=T.PAGE_MAX)
    vals = [r[0] for r in asc["rows"]]
    assert vals.index(None) if None in vals else True
    assert all(v is not None for v in vals[: vals.index(None)]) if None in vals else True
    with pytest.raises(KeyError):
        T.page(run, master, "nope", as_of=DAY)
    with pytest.raises(ValueError):
        T.page(run, master, "reads", as_of=DAY, sort="nope")
    with pytest.raises(ValueError):
        T.page(run, master, "reads", as_of=DAY, filters={"nope": "x"})


def test_csv_pages_stitch_into_the_table(run, master):
    first = T.page(run, master, "dunning", as_of=DAY, page_size=1)
    rows, page = [], 1
    while True:
        text = T.csv_page(run, master, "dunning", as_of=DAY, page=page, page_size=1000)
        body = list(csv.reader(io.StringIO(text)))
        assert body[0] == [c.key for c in T.BY_NAME["dunning"].cols]
        rows += body[1:]
        if page * 1000 >= first["total"]:
            break
        page += 1
    assert len(rows) == first["total"]
    keys = body[0]
    assert all(r[keys.index("at")] <= DAY for r in rows)
    assert set(r[keys.index("type")] for r in rows) <= {"DUNNING_REMINDER", "DUNNING_NOTICE", "DISCONNECT_NOTICE",
                                                         "MORATORIUM_HOLD", "PAYMENT_REJECTED"}


def test_tariffs_carry_both_rate_versions(run, master):
    res = T.page(run, master, "tariffs", as_of=DAY, page_size=50)
    keys = [c["key"] for c in res["columns"]]
    by = {(r[keys.index("tariffId")], r[keys.index("version")]): r for r in res["rows"]}
    v1, v2 = by[("RES-E", 1)], by[("RES-E", 2)]
    pct = run.cfg.billing.rate_change_pct
    assert v2[keys.index("effectiveFrom")] == str(run.cfg.billing.rate_change_date)[:10]
    assert v1[keys.index("effectiveTo")] == date_of(views.parse_day(v2[keys.index("effectiveFrom")], 0) - 1).isoformat()
    assert abs(v2[keys.index("tier1Price")] - round(v1[keys.index("tier1Price")] * (1 + pct / 100), 5)) < 1e-9
    assert v1[keys.index("fixedMonthly")] == v2[keys.index("fixedMonthly")]
    assert by[("COM-E", 1)][keys.index("demandChargePerKW")] == 9.5
    assert by[("RES-W", 1)][keys.index("wastewaterRatio")] == 1.05


def test_endpoints_on_the_hosted_app():
    client = TestClient(app)
    cat = client.get("/api/m2c/tables")
    assert cat.status_code == 200 and cat.json()["schemaVersion"] == T.CATALOG_VERSION
    assert cat.json()["pageMax"] == T.PAGE_MAX and len(cat.json()["groups"]) == len(T.GROUPS)
    res = client.post("/api/m2c/table", json={"town": "small_town", "table": "accounts", "asOf": DAY, "pageSize": 5,
                                              "sort": "balance", "desc": True})
    assert res.status_code == 200
    body = res.json()
    assert body["table"] == "accounts" and len(body["rows"]) == 5 and body["total"] > 5
    k = [c["key"] for c in body["columns"]].index("balance")
    assert [r[k] for r in body["rows"]] == sorted((r[k] for r in body["rows"]), reverse=True)
    too_big = client.post("/api/m2c/table", json={"town": "small_town", "table": "reads", "pageSize": T.PAGE_MAX + 1})
    assert too_big.status_code == 422
    assert client.post("/api/m2c/table", json={"town": "small_town", "table": "nope"}).status_code == 404
    assert client.post("/api/m2c/table", json={"town": "small_town", "table": "reads", "sort": "nope"}).status_code == 422
    csv_res = client.post("/api/m2c/table.csv", json={"town": "small_town", "table": "tariffs", "asOf": DAY})
    assert csv_res.status_code == 200 and csv_res.headers["content-type"].startswith("text/csv")
    lines = csv_res.text.strip().splitlines()
    assert lines[0].split(",")[0] == "tariffId" and len(lines) == 1 + len(T.page(run_for(RunRequest(town="small_town")),
                                                                                  _master("small_town"), "tariffs",
                                                                                  as_of=DAY)["rows"])
    assert client.post("/api/m2c/table.csv", json={"town": "small_town", "table": "reads", "pageSize": T.CSV_MAX + 1}
                       ).status_code == 422


def test_numbers_are_plain_json(run, master):
    res = T.page(run, master, "reads", as_of=DAY, page_size=200)
    for r in res["rows"]:
        for v in r:
            assert v is None or isinstance(v, (str, bool, int, float)), type(v)
            assert not (isinstance(v, float) and not np.isfinite(v))
