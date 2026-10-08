"""HTTP boundaries for the independently owned finance, development and field slices."""
import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_world_customer_finance import command as finance_command
from test_world_customer_finance import delivery as invoice_delivery
from test_world_development import plan
from test_world_development import world as development_world
from test_world_field_execution import command as field_command
from test_world_v2 import world
from test_world_water_faults import command as leak_command

from utilsim.world import customer_finance, field_execution, water_faults
from utilsim.world.server import make_server


@contextmanager
def serving(w, field_path=None):
    server = make_server(w, port=0, field_db=field_path)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request(base, path, payload=None, **headers):
    data = None if payload is None else json.dumps(payload).encode()
    options = {"Content-Type": "application/json", "Origin": base, **headers} if data is not None else headers
    try:
        response = urlopen(Request(base + path, data=data, headers=options), timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        raw = response.read()
        content = json.loads(raw) if response.headers.get_content_type() == "application/json" else raw.decode()
        return response.status, content, response.headers


def dump(owner):
    with owner.db() as db:
        return tuple(db.iterdump())


@pytest.fixture
def routes(tmp_path):
    w = world(tmp_path)
    field_path = tmp_path / "field.sqlite"
    with serving(w, field_path) as base:
        yield w, field_execution.FieldExecution(w, field_path), base


@pytest.mark.parametrize("path,content_type", [
    ("/customer-finance", "text/html"), ("/customer-finance.js", "text/javascript"),
    ("/development", "text/html"), ("/development.js", "text/javascript"),
    ("/field-execution", "text/html"), ("/field-execution.js", "text/javascript"),
])
def test_parallel_static_routes_are_local_desktop_assets(routes, path, content_type):
    w, f, base = routes
    before = dump(w), dump(f)
    status, body, headers = request(base, path)
    assert status == 200 and body
    assert headers.get_content_type() == content_type
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert (dump(w), dump(f)) == before


def test_finance_configuration_command_is_durable_and_replayable_over_http(routes):
    w, _, base = routes
    payload = finance_command(w)
    status, result, _ = request(base, "/api/customer-finance", payload)
    assert status == 200
    assert request(base, "/api/customer-finance", payload)[:2] == (200, result)
    status, state, _ = request(base, "/api/customer-finance?premise=P1")
    assert status == 200 and state["configured"]
    assert state["cashCents"] == 10000 and state["knownOutstandingCents"] == 0
    assert request(base, "/api/payment-intents")[1]["items"] == []


def test_development_plan_command_is_durable_and_replayable_over_http(tmp_path):
    w = development_world(tmp_path)
    payload = plan(w)
    with serving(w) as base:
        status, result, _ = request(base, "/api/development", payload)
        assert status == 200
        assert request(base, "/api/development", payload)[:2] == (200, result)
        status, state, _ = request(base, "/api/development?projectId=site-1&offset=0&limit=1")
        assert status == 200
        assert len(state["projects"]) == 1 and state["projects"][0]["phase"] == "planned"


def prepare_visit(w, f, base):
    fault = water_faults.command(w, leak_command(w))
    assert request(base, "/api/field-execution", field_command(f, "crew", "configure-crew"))[0] == 200
    assert request(base, "/api/field-execution", field_command(f))[0] == 200
    view = request(base, "/api/field-execution")[1]
    return fault, {"environmentId": view["environmentId"], "worldFingerprint": view["worldFingerprint"],
                   "effectiveDate": view["through"]}


def test_field_http_commands_execute_physics_without_delivering_report(routes):
    w, f, base = routes
    _, due = prepare_visit(w, f, base)
    status, results, _ = request(base, "/api/field-execution/run-due", due)
    assert status == 200 and len(results) == 1 and results[0]["outcome"] == "completed"
    assert water_faults.inspect(w, "water")["current"]["active"] is None
    assert request(base, "/api/field-execution/run-due", due)[:2] == (200, [])
    item = request(base, "/api/field-execution")[1]["items"][0]
    assert item["state"] == "executed"
    assert len(item["messages"]) == 2
    assert all(m["state"] == "pending" and m["attempts"] == 0 for m in item["messages"])
    execute = field_command(f, "manual-retry", "execute")
    assert request(base, "/api/field-execution", execute)[:2] == (200, results[0])


def test_missing_explicit_field_store_returns_guidance_without_creating_one(tmp_path):
    w = world(tmp_path)
    before = dump(w)
    with serving(w) as base:
        for path, body in [("/api/field-execution", None),
                           ("/api/field-execution", {"environmentId": "TEST"}),
                           ("/api/field-execution/run-due", {"environmentId": "TEST"})]:
            status, error, _ = request(base, path, body)
            assert status == 503 and "--field-db" in error["error"]
        assert request(base, "/field-execution")[0] == 200
    assert dump(w) == before
    assert sorted(p.name for p in tmp_path.glob("*.sqlite")) == ["world.sqlite"]


@pytest.mark.parametrize("change", [
    {"environmentId": "OTHER"}, {"worldFingerprint": "wrong-world"},
    {"effectiveDate": "2025-12-31"}, {"effectiveDate": "2026-01-02"},
    {"actorId": "world-admin"}, {"effectiveDate": None},
])
def test_run_due_rejects_wrong_identity_date_or_fields_without_physical_effects(routes, change):
    w, f, base = routes
    fault, due = prepare_visit(w, f, base)
    before = dump(w), dump(f)
    status, error, _ = request(base, "/api/field-execution/run-due", {**due, **change})
    assert status == 422 and error["error"]
    assert (dump(w), dump(f)) == before
    assert water_faults.inspect(w, "water")["current"]["active"]["id"] == fault["faultId"]


@pytest.mark.parametrize("path", ["/api/customer-finance", "/api/development", "/api/field-execution",
                                   "/api/field-execution/run-due"])
def test_parallel_mutations_reject_foreign_origins_before_dispatch(routes, path):
    w, f, base = routes
    before = dump(w), dump(f)
    status, error, _ = request(base, path, {"environmentId": "TEST"}, Origin="https://untrusted.invalid")
    assert status == 403 and "origin" in error["error"]
    assert (dump(w), dump(f)) == before


@pytest.mark.parametrize("domain", ["customer-finance", "development", "field-execution"])
def test_parallel_commands_reject_unsupported_fields_before_writes(routes, domain):
    w, f, base = routes
    payload = {"customer-finance": lambda: finance_command(w), "development": lambda: plan(w),
               "field-execution": lambda: field_command(f, "crew", "configure-crew")}[domain]()
    before = dump(w), dump(f)
    status, error, _ = request(base, "/api/" + domain, {**payload, "unsupported": "must-not-be-ignored"})
    assert status == 422 and error["error"]
    assert (dump(w), dump(f)) == before


@pytest.mark.parametrize("path", [
    "/api/customer-finance", "/api/customer-finance?premise=P1&premise=P1",
    "/api/customer-finance?premise=P1&limit=1",
    "/api/payment-intents?after=-1", "/api/payment-intents?limit=101", "/api/payment-intents?limit=1&limit=2",
    "/api/development?offset=-1", "/api/development?limit=0", "/api/development?projectId=site-1&unknown=1",
    "/api/field-execution?after=-1", "/api/field-execution?limit=101", "/api/field-execution?after=0&after=1",
])
def test_parallel_selection_and_pagination_reject_invalid_queries(routes, path):
    w, f, base = routes
    before = dump(w), dump(f)
    status, error, _ = request(base, path)
    assert status == 422 and error["error"]
    assert (dump(w), dump(f)) == before


def test_desktop_http_does_not_expose_invoice_or_provider_ingestion(routes, monkeypatch):
    w, f, base = routes
    assert request(base, "/api/customer-finance", finance_command(w))[0] == 200
    invoice = invoice_delivery(w)
    provider = {"schemaVersion": customer_finance.RECEIPT_VERSION, "environmentId": "TEST",
                "receiptId": "external-receipt", "status": "settled"}
    monkeypatch.setattr(customer_finance, "receive_delivery", lambda *a: pytest.fail("HTTP invoked invoice ingestion"))
    monkeypatch.setattr(customer_finance, "provider_receipt", lambda *a: pytest.fail("HTTP invoked provider ingestion"))
    before = dump(w), dump(f)
    for path, payload in [("/api/customer-finance/deliveries", invoice), ("/api/invoice-delivery", invoice),
                          ("/api/customer-finance/provider-receipts", provider), ("/api/payment-provider-receipts", provider)]:
        assert request(base, path)[0] == 404
        assert request(base, path, payload)[0] == 404
    for payload in (invoice, provider):
        assert request(base, "/api/customer-finance", payload)[0] == 422
    assert (dump(w), dump(f)) == before
    assert request(base, "/api/customer-finance?premise=P1")[1]["knownOutstandingCents"] == 0
