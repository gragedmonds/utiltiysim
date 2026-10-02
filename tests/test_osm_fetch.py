"""OSM fetcher and real-place presets, offline: Nominatim and Overpass answers are recorded samples."""

from __future__ import annotations

import io
import json
import random
import urllib.error

import pytest
import yaml

from utilsim.gen.roads import fetch
from utilsim.gen.roads.osm import OsmError, load_osm, parse_osm

NOMINATIM = [{"osm_type": "node", "osm_id": 18058784, "lat": "43.2855122", "lon": "-80.4507012", "type": "village",
              "name": "Ayr", "display_name": "Ayr, North Dumfries, Region of Waterloo, Ontario, Canada"}]


def overpass_grid(n: int = 6, spacing_deg: float = 0.0012, lat0: float = 43.2825, lon0: float = -80.4545) -> dict:
    """A small street grid in Overpass ``out body`` shape, with noise the fetcher must drop."""
    els, nid = [], 1000
    ids = {}
    for i in range(n):
        for j in range(n):
            ids[i, j] = nid
            els.append({"type": "node", "id": nid, "lat": lat0 + i * spacing_deg, "lon": lon0 + j * spacing_deg,
                        "tags": {"highway": "stop"} if (i, j) == (1, 1) else {}})
            nid += 1
    wid = 1
    for i in range(n):
        hw = "secondary" if i == n // 2 else "residential"
        els.append({"type": "way", "id": wid, "nodes": [ids[i, j] for j in range(n)],
                    "tags": {"highway": hw, "name": f"Row {i} Street", "maxspeed": "50", "surface": "asphalt"}})
        wid += 1
    for j in range(n):
        els.append({"type": "way", "id": wid, "nodes": [ids[i, j] for i in range(n)],
                    "tags": {"highway": "tertiary" if j == 0 else "residential", "name": f"Column {j} Avenue"}})
        wid += 1
    els.append({"type": "way", "id": 900, "nodes": [ids[0, 0], ids[1, 1]], "tags": {"highway": "service"}})
    els.append({"type": "way", "id": 901, "nodes": [ids[2, 2], ids[3, 3]], "tags": {"highway": "footway"}})
    return {"version": 0.6, "generator": "Overpass API", "osm3s": {"timestamp_osm_base": "2026-10-01T22:59:00Z",
                                                                  "copyright": "ODbL"}, "elements": els}


def fake_get(overpass: dict, calls: list | None = None):
    def get(url: str, data: bytes | None = None) -> bytes:
        if calls is not None:
            calls.append((url, data))
        if url.startswith(fetch.NOMINATIM_URL):
            return json.dumps(NOMINATIM).encode()
        assert url == fetch.OVERPASS_URL and data
        return json.dumps(overpass).encode()
    return get


def test_slug_bbox_and_query():
    assert fetch.slugify("Ayr, Ontario") == "ayr-ontario"
    assert fetch.slugify("Saint-Rémi, Québec") == "saint-remi-quebec"
    w, s, e, n = fetch.bbox_around(43.2855, -80.4507, 1500)
    assert w < -80.4507 < e and s < 43.2855 < n
    assert (n - s) * 111_320 == pytest.approx(3000, abs=2)
    with pytest.raises(OsmError):
        fetch.bbox_around(43.0, -80.0, 50_000)
    q = fetch.overpass_query([w, s, e, n])
    assert f"[bbox:{s},{w},{n},{e}]" in q  # Overpass wants south,west,north,east
    assert "residential" in q and "service" not in q and "out body" in q


def test_fetch_normalises_to_a_stable_api06_document():
    calls: list = []
    raw = overpass_grid()
    doc = fetch.fetch_extract("Ayr, Ontario", 1500, get=fake_get(raw, calls))
    assert [c[0].split("?")[0] for c in calls] == [fetch.NOMINATIM_URL, fetch.OVERPASS_URL]
    assert doc["source"] == "Overpass API" and doc["snapshot_date"] == "2026-10-01"
    assert doc["label"] == "Ayr street snapshot" and doc["place"]["osmId"] == 18058784
    assert doc["attribution"] == fetch.ATTRIBUTION and "odbl" in doc["license"]
    ways = [e for e in doc["elements"] if e["type"] == "way"]
    assert {w["tags"]["highway"] for w in ways} == {"residential", "secondary", "tertiary"}  # service/footway gone
    assert all(set(w["tags"]) <= set(fetch.KEEP_TAGS) for w in ways)
    nodes = [e for e in doc["elements"] if e["type"] == "node"]
    assert all("tags" not in n for n in nodes)
    assert [n["id"] for n in nodes] == sorted(n["id"] for n in nodes)

    # Same OSM data in any order → identical bytes.
    shuffled = dict(raw, elements=random.Random(3).sample(raw["elements"], len(raw["elements"])))
    doc2 = fetch.fetch_extract("Ayr, Ontario", 1500, get=fake_get(shuffled))
    assert fetch.dumps(doc) == fetch.dumps(doc2)


def test_written_extract_loads_and_keeps_provenance(tmp_path):
    doc = fetch.fetch_extract("Ayr, Ontario", 1500, get=fake_get(overpass_grid()))
    path = tmp_path / "ayr-ontario.json"
    sha = fetch.write_extract(doc, path)
    raw, sha2 = load_osm(path, sha)
    assert sha == sha2
    ex = parse_osm(raw, sha)
    assert ex.label == "Ayr street snapshot" and ex.snapshot_date == "2026-10-01"
    assert ex.raw_counts["ways_used"] == 12 and ex.omitted_nodes == 0
    with pytest.raises(OsmError):
        load_osm(path, "0" * 64)


def test_overpass_errors_are_clear():
    with pytest.raises(OsmError, match="no streets"):
        fetch.normalise({"elements": [{"type": "node", "id": 1, "lat": 1.0, "lon": 1.0}]}, place=None,
                        bbox=[0, 0, 1, 1], query="")
    grid = overpass_grid()
    grid["elements"] = [e for e in grid["elements"] if not (e["type"] == "node" and e["id"] == 1000)]
    with pytest.raises(OsmError, match="missing 1 referenced"):
        fetch.normalise(grid, place=None, bbox=[0, 0, 1, 1], query="")
    with pytest.raises(OsmError, match="no place"):
        fetch.geocode("Nowhere", get=lambda url, data=None: b"[]")


def test_http_get_retries_busy_servers(monkeypatch):
    answers = [urllib.error.HTTPError("u", 504, "Gateway Timeout", {}, None), ConnectionResetError("reset"),
               io.BytesIO(b"ok")]
    waits: list[float] = []

    def urlopen(req, timeout):
        assert req.get_header("User-agent").startswith("utilsim/")
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(fetch.urllib.request, "urlopen", urlopen)
    assert fetch.http_get("https://overpass-api.de/api/interpreter", b"data=x", sleep=waits.append) == b"ok"
    assert waits == list(fetch.RETRY_WAITS_S[:2])

    monkeypatch.setattr(fetch.urllib.request, "urlopen",
                        lambda req, timeout: (_ for _ in ()).throw(urllib.error.HTTPError("u", 400, "Bad", {}, None)))
    with pytest.raises(OsmError, match="HTTP 400"):
        fetch.http_get("https://overpass-api.de/api/interpreter", sleep=waits.append)

    monkeypatch.setattr(fetch.urllib.request, "urlopen",
                        lambda req, timeout: (_ for _ in ()).throw(urllib.error.HTTPError("u", 429, "Slow", {}, None)))
    with pytest.raises(OsmError, match="busy or unreachable"):
        fetch.http_get("https://overpass-api.de/api/interpreter", waits=(0.0, 0.0), sleep=lambda s: None)


def test_register_preset_with_fixed_size(tmp_path):
    from utilsim.gen.sources import register_preset

    doc = fetch.fetch_extract("Ayr, Ontario", 1500, get=fake_get(overpass_grid()))
    path = tmp_path / "ayr-ontario.json"
    sha = fetch.write_extract(doc, path)
    res = register_preset(path, houses=120, preset_dir=tmp_path / "presets", timezone="America/Toronto")
    assert res["preset"] == "ayr_ontario" and res["houses"] == 120 and res["osmSha256"] == sha
    y = yaml.safe_load((tmp_path / "presets" / "ayr_ontario.yaml").read_text())
    assert y["town"] == {"houses": 120, "skeleton": "osm", "osm_source": str(path.resolve()), "osm_sha256": sha,
                         "expansion": "none", "timezone": "America/Toronto"}
    assert "Ayr, Ontario" in y["description"]
    with pytest.raises(FileExistsError):
        register_preset(path, houses=120, preset_dir=tmp_path / "presets")
    with pytest.raises(OsmError):
        register_preset(path, name="bad name!", houses=120, preset_dir=tmp_path / "presets2")


def test_saved_overpass_answer_gives_the_same_extract(tmp_path):
    raw = overpass_grid()
    saved = tmp_path / "overpass.json"
    saved.write_text(json.dumps(raw))
    calls: list = []
    from_file = fetch.fetch_extract("Ayr, Ontario", 1500, get=fake_get(raw, calls), overpass_file=saved)
    assert [c[0].split("?")[0] for c in calls] == [fetch.NOMINATIM_URL]  # geocode only
    assert fetch.dumps(from_file) == fetch.dumps(fetch.fetch_extract("Ayr, Ontario", 1500, get=fake_get(raw)))
    url = fetch.overpass_url(from_file["query"])
    assert url.startswith(fetch.OVERPASS_URL + "?data=") and "%5Bbbox%3A" in url
