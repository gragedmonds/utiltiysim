"""Connecting other systems: a table of a run as a link (POST /api/m2c/table/link) that any tool can GET page by page,
as CSV or JSON, with the same selection and run date as the Data page; the link carries the run's inputs."""

from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient

from api import _m2c
from api.index import app

CLIENT = TestClient(app)
BODY = {"town": "small_town", "asOf": "2026-10-31", "table": "cases", "sort": "createdAt", "desc": True,
        "episodes": [{"id": "EP-1", "title": "No analysts", "from": "2026-03-01", "to": "2026-04-30",
                      "settings": {"process": {"analysts": 0}}}]}


def link(body=BODY):
    r = CLIENT.post("/api/m2c/table/link", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_link_returns_the_same_table_as_the_data_page():
    lk = link()
    assert lk["schemaVersion"] == _m2c.LINK_VERSION and lk["token"].startswith("r1.") and not lk["tooLarge"]
    assert lk["total"] > 0 and lk["pages"]["csv"] == -(-lk["total"] // 5000)
    # The CSV link's first page is the POST CSV's first page, byte for byte.
    got = CLIENT.get("/api/" + lk["paths"]["csv"])
    want = CLIENT.post("/api/m2c/table.csv", json={**BODY, "page": 1, "pageSize": 5000})
    assert got.status_code == 200 and got.text == want.text
    assert got.headers["x-total-rows"] == str(lk["total"]) and got.headers["x-pages"] == str(lk["pages"]["csv"])
    assert got.headers["content-type"].startswith("text/csv")
    # JSON rows are objects keyed by column, in the Data page's order.
    js = CLIENT.get("/api/" + lk["paths"]["json"]).json()
    page = CLIENT.post("/api/m2c/table", json={**BODY, "page": 1, "pageSize": 500}).json()
    keys = [c["key"] for c in page["columns"]]
    assert js["schemaVersion"] == "m2c-export/1.0" and js["total"] == page["total"] == lk["total"]
    assert [c["key"] for c in js["columns"]] == keys
    assert [[row[k] for k in keys] for row in js["rows"][:500]] == page["rows"]


def test_pages_follow_one_another_to_the_last():
    lk = link()
    small = "/api/" + lk["paths"]["json"].replace("pageSize=1000", "pageSize=100")
    first = CLIENT.get(small)
    js = first.json()
    assert js["pages"] == -(-js["total"] // 100) and js["next"] and 'rel="next"' in first.headers["link"]
    second = CLIENT.get(js["next"]).json()
    assert second["page"] == 2 and second["rows"][0] != js["rows"][0]
    last = CLIENT.get(small.replace("page=1", f"page={js['pages']}")).json()
    assert last["next"] is None and len(last["rows"]) == js["total"] - 100 * (js["pages"] - 1)
    # Stitching the CSV pages gives every row once.
    pages, rows = 1, []
    url = "/api/" + lk["paths"]["csv"].replace("pageSize=5000", "pageSize=300")
    while url:
        r = CLIENT.get(url)
        part = list(csv.reader(io.StringIO(r.text)))
        rows += part[1:]
        url = r.headers.get("link", "").partition("<")[2].partition(">")[0] or None
        pages += 1 if url else 0
    assert len(rows) == lk["total"] and len({tuple(r) for r in rows}) == len(rows)


def test_a_link_carries_the_selection_and_bad_links_are_refused():
    lk = link({**BODY, "filters": {"queue": "ESTIMATION"}, "columns": ["caseId", "queue", "status"]})
    js = CLIENT.get("/api/" + lk["paths"]["json"]).json()
    assert [c["key"] for c in js["columns"]] == ["caseId", "queue", "status"]
    assert js["rows"] and all(r["queue"] == "ESTIMATION" for r in js["rows"])
    assert CLIENT.get("/api/m2c/export/cases.csv?run=nope").status_code == 400
    assert CLIENT.get("/api/m2c/export/cases.csv?run=r1.!!!").status_code == 400
    other = CLIENT.get("/api/m2c/export/invoices.csv?run=" + lk["token"])
    assert other.status_code == 400 and "cases" in other.text  # a link is for its table
    assert CLIENT.get("/api/" + lk["paths"]["csv"].replace("pageSize=5000", "pageSize=5001")).status_code == 422
    # A token that inflates past the limit is refused, not decompressed.
    import base64
    import zlib
    bomb = "r1." + base64.urlsafe_b64encode(zlib.compress(b"[" + b"0," * 3_000_000 + b"0]", 9)).decode().rstrip("=")
    assert len(bomb) < _m2c.LINK_MAX and CLIENT.get(f"/api/m2c/export/cases.csv?run={bomb}").status_code == 400


def test_a_run_too_large_for_a_link_says_so():
    import hashlib

    actions = [{"type": "note", "day": "2026-05-01", "caseId": f"CASE-{i:06d}",
                "note": hashlib.sha256(str(i).encode()).hexdigest() * 4} for i in range(200)]
    req = _m2c.TableRequest.model_validate({**BODY, "actions": actions})
    assert len(_m2c.link_token(req)) > _m2c.LINK_MAX  # the endpoint would answer tooLarge with POST instructions
