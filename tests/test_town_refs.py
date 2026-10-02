"""Self-describing town references: a generated town is named by its preset plus the settings that differ from it, so
any engine instance (a cold serverless function, a shared link) rebuilds exactly the same town from the name."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.index as hosted
from api._towns import REF_SEP, config_from_ref, town_ref
from api.store import store
from utilsim.config import load_preset

ROOT = Path(__file__).resolve().parents[1]


def _cold() -> None:
    """Forget every built town and cached view, as a fresh function instance would."""
    store._towns.clear()
    store._snap_gz.clear()
    store._configs.clear()
    import utilsim.m2c.base as m2c_base
    from utilsim.ops import opstown

    m2c_base._CACHE.clear()
    for name in dir(opstown):
        fn = getattr(opstown, name)
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()


def _changed():
    data = load_preset("whitby_small").model_dump(mode="json")
    data["seeds"]["master"] = "REF-TEST-1"
    data["operations"]["electric_crews"] = 5
    data["vee"]["accept_confidence"] = 0.9  # a run setting: it does not shape the town, so it is not in the name
    return data


def test_an_unchanged_preset_is_named_by_the_preset():
    assert town_ref(load_preset("ayr")) == "ayr"
    assert town_ref(load_preset("whitby_small")) == "whitby_small"


def test_a_reference_round_trips_to_the_same_town():
    from utilsim.config.model import SimConfig

    cfg = SimConfig.model_validate(_changed())
    ref = town_ref(cfg)
    assert ref.startswith("whitby_small" + REF_SEP) and len(ref) < 400
    assert all(c.isalnum() or c in "_-~" for c in ref)  # safe in a URL path and query
    back = config_from_ref(ref)
    assert back.town_id() == cfg.town_id()
    assert back.seeds.master == "REF-TEST-1" and back.operations.electric_crews == 5


def test_a_cold_instance_builds_the_town_from_its_reference():
    client = TestClient(hosted.app)
    ref = client.post("/api/towns", json={"config": _changed()}).json()["ref"]
    _cold()
    snap = client.get(f"/api/towns/{ref}/snapshot.json?detail=viewer")
    assert snap.status_code == 200 and snap.json()["id"] == config_from_ref(ref).town_id()
    _cold()
    tl = client.post("/api/sim/timeline", json={"town": ref, "date": "2026-07-15", "commands": []})
    assert tl.status_code == 200 and tl.json()["townId"] == config_from_ref(ref).town_id()
    _cold()
    summary = client.post("/api/m2c/summary", json={"town": ref, "asOf": "2026-07-15"})
    assert summary.status_code == 200 and summary.json()["kpis"]["reads"] > 0
    schema = client.get(f"/api/sim/settings/schema?town={ref}")
    assert schema.status_code == 200 and schema.json()["defaults"]["electricCrews"] == 5


def test_bad_references_and_oversized_towns_are_refused(monkeypatch):
    client = TestClient(hosted.app)
    assert client.get("/api/towns/ayr~not-a-reference/snapshot.json").status_code == 404
    assert client.post("/api/sim/timeline", json={"town": "nope~eJwDAAAAAAE", "date": "2026-07-15",
                                                  "commands": []}).status_code == 404
    import api._towns as towns

    monkeypatch.setattr(towns, "MAX_HOUSES", 100)
    r = client.post("/api/towns", json={"preset": "whitby_small"})
    assert r.status_code == 422 and "up to 100 houses" in r.json()["detail"]


@pytest.mark.timeout(300)
def test_the_hosted_function_builds_a_town_without_tables_or_renders():
    # The Vercel function installs api/requirements.txt: scipy, shapely and PyYAML, but not pyarrow or matplotlib.
    code = ("import sys\nfor m in ('pyarrow','matplotlib'):\n    sys.modules[m]=None\n"
            "from fastapi.testclient import TestClient\nimport api.index as h\n"
            "c=TestClient(h.app)\n"
            "r=c.post('/api/towns',json={'preset':'whitby_small','seed':'NO-TABLES-1'})\n"
            "assert r.status_code==201,r.text\nref=r.json()['ref']\n"
            "s=c.get('/api/towns/'+ref+'/snapshot.json?detail=viewer')\nassert s.status_code==200,s.text\n"
            "print('ok')\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=280)
    assert out.returncode == 0 and "ok" in out.stdout, out.stderr[-2000:]
