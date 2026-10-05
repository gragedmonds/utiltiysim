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
    assert len(items) == len({o["code"] for o in items}) == 28
    assert len(data["groups"]) == 9
    for item in items:
        assert item["group"] in data["groups"]
        assert item["status"] in data["statuses"]
        assert set(item["engineTypes"]) <= set(KEYS) & FieldConfig.model_fields.keys()
        assert set(item["manualActivities"]) <= set(orders.CHOICES["activityType"])
        assert item["behaviour"]
        if item["status"] != "covered":
            assert item["gap"]
    gaps = {o["code"] for o in items if o["status"] == "not_modelled"}
    assert gaps == {"302", "309", "106", "111"}
    assert all(not o["engineTypes"] and not o["manualActivities"] for o in items if o["code"] in gaps)
    assert "not been imported" in data["timingNote"]


def test_crosswalk_is_available_from_packaged_offline_api_without_a_run(tmp_path):
    jobs = LocalJobs(tmp_path)
    with TestClient(create_app(jobs, "coverage-test"), base_url="http://127.0.0.1") as client:
        response = client.get("/api/m2c/kpis")
        assert response.status_code == 200
        assert response.json()["serviceOrders"] == catalogue()
        assert client.get("/service-order-coverage.js").status_code == 200
    assert not list(tmp_path.glob("runs/*"))
