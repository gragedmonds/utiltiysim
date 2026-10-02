"""Operations settings schema: every default is described, and form overrides become timeline settings."""

from __future__ import annotations

from fastapi.testclient import TestClient

from utilsim.ops.settings_schema import settings_schema, to_settings
from utilsim.ops.timeline import DEFAULTS


def test_every_operations_default_has_a_described_field():
    schema = settings_schema()
    covered = set()
    for group, g in schema["properties"].items():
        assert g["title"] and g["properties"]
        if g.get("x-flat"):
            covered.update(g["properties"])
        else:
            covered.add(group)
            assert set(g["properties"]) == set(DEFAULTS[group])
        for key, f in g["properties"].items():
            assert f["title"] and f["type"] in ("boolean", "integer", "number")
            if f["type"] != "boolean":
                assert f["minimum"] <= f["default"] <= f["maximum"], (group, key)
    assert covered == set(DEFAULTS)


def test_form_overrides_become_timeline_settings():
    assert to_settings({"crews": {"fieldCrews": 5}, "detectSeconds": {"water": 600}, "backfeed": {"tieBackfeed": False}}) \
        == {"fieldCrews": 5, "tieBackfeed": False, "detectSeconds": {"water": 600}}


def test_hosted_settings_schema_endpoint():
    from api.index import app

    body = TestClient(app).get("/api/sim/settings/schema").json()
    assert body["defaults"] == DEFAULTS and "backfeed" in body["schema"]["properties"]
