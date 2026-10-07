"""Diagnostics explain drift without converting geometric similarity into a pass."""
from copy import deepcopy

import pytest

from scripts.diagnose_goldens import SECTIONS, compare, polygon_difference, write_new


def snapshot():
    value = {key: [] for key in SECTIONS}
    value.update(id="town-test", generatorVersion="0.10.0", config={"seed": "test"},
                 networks={"water": {"nodes": [], "edges": []}},
                 parcels=[{"id": "LOT-P1", "polygon": [{"x": 0, "z": 0}, {"x": 2, "z": 0},
                                                         {"x": 2, "z": 2}, {"x": 0, "z": 2}], "areaM2": 4.0}])
    return value


def test_identical_and_dictionary_order():
    a = snapshot()
    b = deepcopy(a)
    b["networks"]["water"] = {"edges": [], "nodes": []}
    assert compare(a, b)["exactMatch"]


def test_rotated_ring_remains_an_exact_failure():
    a = snapshot()
    b = deepcopy(a)
    ring = b["parcels"][0]["polygon"]
    b["parcels"][0]["polygon"] = ring[2:] + ring[:2]
    report = compare(a, b)
    assert not report["exactMatch"]
    section = report["sections"]["parcels"]
    assert section["ringOrderOnly"] == 1
    assert section["differentVertices"] == 0
    assert section["details"][0]["geometry"]["symmetricDifferenceM2"] == 0
    assert polygon_difference(ring, ring[::-1])["classification"] == "ring-order-only"


def test_small_boundary_change_is_not_waived_or_confused_with_area_rounding():
    a = snapshot()
    b = deepcopy(a)
    b["parcels"][0]["polygon"][1]["x"] += .01
    b["parcels"][0]["areaM2"] = 4.1
    report = compare(a, b)
    assert not report["exactMatch"]
    section = report["sections"]["parcels"]
    assert section["differentVertices"] == 1
    assert section["details"][0]["fields"] == ["areaM2", "polygon"]
    assert section["details"][0]["geometry"]["hausdorffM"] == pytest.approx(.01)
    assert section["details"][0]["geometry"]["symmetricDifferenceM2"] == pytest.approx(.01)


def test_zero_detail_limit_still_counts_all_failures_and_membership():
    a = snapshot()
    b = deepcopy(a)
    b["parcels"][0]["areaM2"] = 4.1
    b["parcels"].append({"id": "LOT-P2", "polygon": [], "areaM2": 0})
    report = compare(a, b, detail_limit=0)
    section = report["sections"]["parcels"]
    assert not report["exactMatch"]
    assert section["changedRecords"] == section["detailsOmitted"] == 1
    assert section["details"] == []
    assert section["added"] == ["LOT-P2"]
    assert compare(b, a)["sections"]["parcels"]["removed"] == ["LOT-P2"]


def test_metadata_record_order_and_signed_zero_are_detected():
    a = snapshot()
    b = deepcopy(a)
    b["config"]["seed"] = "different"
    assert not compare(a, b)["exactMatch"]
    b = deepcopy(a)
    b["parcels"][0]["polygon"][0]["x"] = -0.0
    assert not compare(a, b)["exactMatch"]
    a["accounts"] = [{"id": "A1"}, {"id": "A2"}]
    b = deepcopy(a)
    b["accounts"].reverse()
    section = compare(a, b)["sections"]["accounts"]
    assert not section["exactMatch"]
    assert section["recordOrderChanged"]
    assert section["changedRecords"] == 0


def test_duplicate_identity_and_overwriting_evidence_are_rejected(tmp_path):
    a = snapshot()
    b = deepcopy(a)
    b["parcels"].append(deepcopy(b["parcels"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        compare(a, b)
    path = tmp_path / "reference.json"
    write_new(path, a)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_new(path, b)
    assert path.read_bytes() == original
