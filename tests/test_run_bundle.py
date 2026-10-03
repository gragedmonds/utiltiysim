"""Archives agree with live engine views, survive restart and never reuse damaged output."""

from __future__ import annotations

import csv
import gzip
import io
import json
import subprocess
from pathlib import Path

import orjson
import pytest
from typer.testing import CliRunner

from utilsim.cli import app
from utilsim.io import run_bundle as B
from utilsim.io.snapshot import build_snapshot
from utilsim.m2c import tables, trend, views
from utilsim.m2c.base import M2CTown
from utilsim.m2c.run import M2CRun

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-03-15"
REQUEST = {"asOf": DAY, "seed": "ARCHIVE-1", "episodes": [
    {"id": "EP-1", "title": "Nobody on the queues", "from": "2026-03-01",
     "settings": {"process": {"analysts": 0}}}]}


@pytest.fixture(scope="module")
def archive(town120, tmp_path_factory):
    snap = orjson.loads(orjson.dumps(build_snapshot(town120), option=orjson.OPT_SERIALIZE_NUMPY))
    store = tmp_path_factory.mktemp("archive")
    directory, manifest, reused = B.export_run(snap, REQUEST, store)
    assert not reused
    return snap, store, directory, manifest


def read(directory, name):
    raw = (directory / name).read_bytes()
    return orjson.loads(gzip.decompress(raw) if name.endswith(".gz") else raw)


def test_archive_agrees_with_every_engine_table_and_month_end_view(archive):
    snap, _, directory, manifest = archive
    run = M2CRun(M2CTown.from_snapshot(snap), **{k: v for k, v in REQUEST.items() if k != "asOf"})
    assert manifest["readOnly"] and manifest["tableDates"] == [DAY]
    assert manifest["worklistDates"] == ["2026-01-31", "2026-02-28", DAY]
    assert read(directory, "trend.json") == trend.trend(run, DAY)
    assert read(directory, "scorecard.json") == views.scorecard(run, as_of=DAY)
    master = tables.master_data(snap)
    for spec in tables.SPECS:
        saved = read(directory, f"tables/{spec.name}.json.gz")
        _, table, _ = tables.build(run, master, spec.name, DAY)
        assert saved["rows"] == list(map(list, zip(*table.data))), spec.name
        assert saved["facets"] == table.facets
    for date in manifest["worklistDates"]:
        saved = read(directory, f"worklists/{date}.json.gz")
        live = views.worklist(run, as_of=date, page_size=200)
        assert saved["total"] == live["total"]
        assert saved["rows"][:200] == live["rows"]
        assert read(directory, f"summaries/{date}.json") == B.compact_summary(views.summary(run, date))
    aggregate = read(directory, "aggregates.json")
    assert aggregate["towns"][0]["summary"]["kpis"]["casesOpen"] == read(directory, f"worklists/{DAY}.json.gz")["total"]
    assert "premises" not in aggregate["towns"][0]["summary"]
    assert len((directory / "aggregates.json").read_bytes()) < 100_000


def test_same_effective_inputs_reuse_without_replaying_and_object_order_does_not_matter(archive, monkeypatch):
    snap, store, directory, manifest = archive
    stamp = (directory / "manifest.json").stat().st_mtime_ns
    monkeypatch.setattr(B, "M2CRun", lambda *a, **k: pytest.fail("cached run was replayed"))
    path, result, reused = B.export_run(snap, dict(reversed(list(REQUEST.items()))), store)
    assert reused and path == directory and result == manifest
    assert (directory / "manifest.json").stat().st_mtime_ns == stamp
    regenerated = orjson.loads(orjson.dumps(snap))
    regenerated["stats"]["timingsS"] = {"generation": 999.0}
    assert B.export_run(regenerated, REQUEST, store)[0] == directory
    assert "timingsS" not in read(directory, "snapshot.json.gz")["stats"]
    assert B.run_key("build-1", {"a": 1, "b": {"x": 2, "y": 3}}) == B.run_key("build-1", {"b": {"y": 3, "x": 2}, "a": 1})
    assert B.run_key("build-1", manifest["inputs"]) != B.run_key("build-2", manifest["inputs"])
    for key, value in [("seed", "other"), ("asOf", "2026-03-16"), ("snapshotSha256", "other"), ("episodes", [])]:
        assert B.run_key(manifest["engineBuild"], {**manifest["inputs"], key: value}) != manifest["runKey"]


def test_corrupt_files_and_traversal_are_refused(archive, tmp_path):
    import shutil

    _, _, source, _ = archive
    directory = tmp_path / "copy"
    shutil.copytree(source, directory)
    (directory / "trend.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="integrity"):
        B.read_manifest(directory)
    manifest = orjson.loads((directory / "manifest.json").read_bytes())
    manifest["files"][0]["name"] = "../outside.json"
    (directory / "manifest.json").write_bytes(orjson.dumps(manifest))
    with pytest.raises(ValueError, match="file name"):
        B.read_manifest(directory)


def test_failed_export_is_not_published(archive, monkeypatch, tmp_path):
    snap, _, _, _ = archive

    def fail(*args):
        raise RuntimeError("disk writer failed")

    monkeypatch.setattr(B, "_open_worklist", fail)
    with pytest.raises(RuntimeError, match="disk writer"):
        B.export_run(snap, REQUEST, tmp_path)
    assert list((tmp_path / "runs").iterdir()) == []


@pytest.mark.parametrize("date", ["2027-01-01", "2025-12-31", "2026-02-30", "2026-03-15T00:00:00"])
def test_dates_outside_the_engine_calendar_are_refused(archive, tmp_path, date):
    with pytest.raises(ValueError):
        B.export_run(archive[0], {"asOf": date}, tmp_path)


def test_cli_uses_studio_inputs_and_saved_snapshot(archive, tmp_path):
    snap, _, directory, _ = archive
    snapshot = tmp_path / "snapshot.json.gz"
    snapshot.write_bytes(gzip.compress(orjson.dumps(snap)))
    input_file = tmp_path / "viewer-run.json"
    input_file.write_bytes(orjson.dumps({"schemaVersion": "viewer-m2c-run/1.0", "town": "whitby_small",
                                       "townId": snap["id"], **REQUEST}))
    cli = CliRunner()
    result = cli.invoke(app, ["export-run", "--input", str(input_file), "--snapshot", str(snapshot),
                             "--store", str(tmp_path / "store")])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["runKey"] == directory.name
    input_file.write_bytes(orjson.dumps({"townId": "wrong"}))
    result = cli.invoke(app, ["export-run", "--input", str(input_file), "--snapshot", str(snapshot)])
    assert result.exit_code != 0 and "different town" in result.output
    result = cli.invoke(app, ["export-run", "--town", "missing-town"])
    assert result.exit_code != 0 and "unknown town" in result.output


def test_browser_reader_matches_engine_selection_and_csv_without_api(archive, tmp_path):
    snap, _, directory, _ = archive
    run = M2CRun(M2CTown.from_snapshot(snap), **{k: v for k, v in REQUEST.items() if k != "asOf"})
    master = tables.master_data(snap)
    queries = [
        {"table": "reads", "page": 2, "pageSize": 50, "sort": "consumption", "desc": True,
         "filters": {"commodity": "water"}},
        {"table": "accounts", "search": snap["accounts"][0]["id"], "pageSize": 100},
        {"table": "reads", "filters": {"readDate": "2026-02"}, "sort": "readDate"},
        {"table": "reads", "filters": {"consumption": "0..100"}, "sort": "consumption"},
    ]
    expected = []
    for q in queries:
        kwargs = {"as_of": DAY, "page": q.get("page", 1), "page_size": q.get("pageSize", 100),
                  "sort": q.get("sort"), "desc": q.get("desc", False), "filters": q.get("filters"),
                  "search": q.get("search")}
        page = tables.page(run, master, q["table"], **kwargs)
        expected.append({"rows": page["rows"], "total": page["total"],
                         "csv": tables.csv_page(run, master, q["table"], **kwargs)})
    payload = tmp_path / "expected.json"
    payload.write_bytes(orjson.dumps({"queries": queries, "expected": expected}))
    script = """
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {RunBundle,SavedM2C} from './packages/town-viewer/dist/run-bundle.js';
const [directory,payload]=process.argv.slice(2);
const manifest=JSON.parse(await fs.readFile(directory+'/manifest.json','utf8'));
const bundle=new RunBundle(manifest,name=>fs.readFile(directory+'/'+name));
const client=new SavedM2C(bundle),{queries,expected}=JSON.parse(await fs.readFile(payload,'utf8'));
const csv=[];
for(let i=0;i<queries.length;i++){
 const q=queries[i],actual=await client.table(q);
 assert.deepEqual(actual.rows,expected[i].rows);assert.equal(actual.total,expected[i].total);
 csv.push(await client.tableCsv({...q,pageSize:q.pageSize||100}));
}
assert.equal(await bundle.verify(),manifest.files.length);
assert.throws(()=>client.setAsOf('2026-04-01'),/read-only/);
assert.equal(client.canAct(),false);
console.log(JSON.stringify(csv));
"""
    result = subprocess.run(["node", "--input-type=module", "-", str(directory), str(payload)],
                            input=script, cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    for q, actual, live in zip(queries, json.loads(result.stdout), expected):
        got, want = list(csv.reader(io.StringIO(actual))), list(csv.reader(io.StringIO(live["csv"])))
        assert got[0] == want[0] and len(got) == len(want)
        kinds = [c.kind for c in tables.BY_NAME[q["table"]].cols]
        for a, b in zip(got[1:], want[1:]):
            assert len(a) == len(b)
            for x, y, kind in zip(a, b, kinds):
                # JSON has a single number type: 0 and 0.0 must carry the same CSV value.
                assert x == y or (kind in ("int", "num", "money", "pct") and x and y and float(x) == float(y))
