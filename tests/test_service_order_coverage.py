"""Keep the report crosswalk grounded in actual engine and manual-order capabilities."""

from fastapi.testclient import TestClient

from utilsim.config.model import FieldConfig
from utilsim.m2c import orders
from utilsim.m2c.fieldwork import KEYS
from utilsim.m2c.service_orders import catalogue
from utilsim.worker.jobs import LocalJobs
from utilsim.worker.server import create_app


def test_reference_types_resolve_to_real_work_without_changing_the_engine():
    data = catalogue()
    items = data["orders"]
    assert len(items) == len({o["code"] for o in items}) == 21
    assert len(data["groups"]) == 6
    codes = [code for w in data["workTypes"] for code in w["codes"]]
    assert len(codes) == len(set(codes)) == len(items)
    assert set(codes) == {o["code"] for o in items}
    assert not set(codes) & {"106", "105", "111", "107", "227", "315", "219"}
    by_code = {o["code"]: o for o in items}
    assert {by_code[k]["workType"] for k in ("300", "301", "302", "309")} == {"service_on"}
    assert {by_code[k]["workType"] for k in ("216", "217", "238", "236")} == {"meter_visit"}
    assert by_code["206"]["workType"] == by_code["213"]["workType"] == "meter_exchange"
    assert by_code["206"]["accounting"] != by_code["213"]["accounting"]
    for item in items:
        assert item["group"] in data["groups"]
        assert item["status"] in data["statuses"]
        assert set(item["engineTypes"]) <= set(KEYS) & FieldConfig.model_fields.keys()
        assert set(item["manualActivities"]) <= set(orders.CHOICES["activityType"])
        assert item["behaviour"]
        if item["status"] != "covered":
            assert item["gap"]
    gaps = {o["code"] for o in items if o["status"] == "not_modelled"}
    assert gaps == {"302", "309"}
    assert all(not o["engineTypes"] and not o["manualActivities"] for o in items if o["code"] in gaps)
    assert "not been imported" in data["timingNote"]


def test_manual_work_types_preserve_every_legacy_purpose():
    vocabulary = orders.vocabulary(["Test"])
    groups = vocabulary["workTypes"]
    assert [g["id"] for g in groups] == ["meter_visit", "meter_exchange"]
    assert {p["activity"] for g in groups for p in g["purposes"]} == set(orders.CHOICES["activityType"])
    for activity in orders.CHOICES["activityType"]:
        profile = orders.work_profile(activity)
        assert profile["id"] == ("meter_exchange" if activity == "Meter exchange" else "meter_visit")
    assert orders.work_profile(None) is None  # incomplete drafts are still allowed
    turn_off = next(w for w in catalogue()["workTypes"] if w["id"] == "service_off")
    assert next(c for c in turn_off["connections"] if "Move-out" in c["trigger"])["status"] == "planned"


def test_crosswalk_is_available_from_packaged_offline_api_without_a_run(tmp_path):
    jobs = LocalJobs(tmp_path)
    with TestClient(create_app(jobs, "coverage-test"), base_url="http://127.0.0.1") as client:
        response = client.get("/api/m2c/kpis")
        assert response.status_code == 200
        assert response.json()["serviceOrders"] == catalogue()
        assert client.get("/service-order-coverage.js").status_code == 200
    assert not list(tmp_path.glob("runs/*"))
