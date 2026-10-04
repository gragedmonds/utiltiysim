"""Persistent, content-addressed meter-to-cash results. No hosted API or network is needed.

The manifest is the commit marker: a bundle becomes visible only after all its files have
been written. Readers use the saved outputs, never a pickle or a reconstructed engine run.
"""

from __future__ import annotations

import calendar
import gzip
import hashlib
import os
import shutil
import tempfile
from importlib.metadata import version
from pathlib import Path

import orjson

from utilsim.m2c import daily, tables, trend, views
from utilsim.m2c.base import M2CTown
from utilsim.m2c.run import M2C_GROUPS, M2CRun, run_seed, town_seed
from utilsim.version import GENERATOR_VERSION

MANIFEST_VERSION = "run-manifest/1.0"
AGGREGATES_VERSION = "run-aggregates/1.0"
TABLE_VERSION = "run-table/1.0"
WORKLIST_VERSION = "run-worklist/1.0"


def _json(value) -> bytes:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS | orjson.OPT_SERIALIZE_NUMPY)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def engine_build() -> str:
    """Distinguish builds even if a version bump was missed; do not depend on Git being installed."""
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    # Validation belongs to the run contract too. Package these sources with the executable.
    from api import _m2c

    digest.update(Path(_m2c.__file__).read_bytes())
    for package in ("numpy", "pydantic", "orjson"):
        digest.update(f"{package}={version(package)}\0".encode())
    return digest.hexdigest()


def run_key(engine: str, inputs: dict) -> str:
    """Ordering of object keys is irrelevant; ordering of actions and episodes is significant."""
    return hashlib.blake2b(engine.encode() + b"\0" + _json(inputs), digest_size=32).hexdigest()


def snapshot_dates(as_of: str) -> list[str]:
    """Month ends through the export date, with a partial last month when appropriate."""
    year, month, _ = map(int, as_of.split("-"))
    return [f"{year}-{m:02d}-{calendar.monthrange(year, m)[1]:02d}" for m in range(1, month)] + [as_of]


def compact_summary(summary: dict) -> dict:
    """Only aggregates belong online: leave premise arrays and daily series in local details."""
    return {**{k: v for k, v in summary.items() if k not in ("premises", "queues", "weather")},
            "queues": [{k: v for k, v in q.items() if k != "series"} for q in summary["queues"]],
            "weather": {k: v for k, v in summary["weather"].items() if k != "series"}}


def read_manifest(directory: str | Path, *, verify: bool = True) -> dict:
    """Validate an archive before reuse; a corrupt cache must never count as a completed run."""
    directory = Path(directory)
    manifest = orjson.loads((directory / "manifest.json").read_bytes())
    if manifest.get("schemaVersion") != MANIFEST_VERSION:
        raise ValueError("unsupported run manifest")
    names = set()
    for item in manifest["files"]:
        name = item["name"]
        if not isinstance(name, str) or "\\" in name or name.startswith("/") or any(
            p in ("", ".", "..") for p in name.split("/")
        ) or name in names:
            raise ValueError("invalid or duplicate bundle file name")
        names.add(name)
        path = directory / name
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("bundle file leaves the archive")
        if verify:
            data = path.read_bytes()
            if len(data) != item["bytes"] or _sha(data) != item["sha256"]:
                raise ValueError(f"bundle integrity check failed: {name}")
    if not {"inputs.json", "aggregates.json", "trend.json", "scorecard.json", "tables/catalog.json"} <= names:
        raise ValueError("incomplete run bundle")
    inputs = orjson.loads((directory / "inputs.json").read_bytes())
    if manifest["runKey"] != run_key(manifest["engineBuild"], inputs) or inputs != manifest["inputs"]:
        raise ValueError("run key does not match the saved inputs")
    return manifest


def _open_worklist(run: M2CRun, as_of: str) -> dict:
    _, until = views.as_of_t(run, as_of)
    # One pass, rather than re-sorting the entire worklist for each API-sized page.
    rows = [views._row(run, case, until) for case in run.cases
            if case.created <= until and (case.resolved is None or case.resolved > until)]
    rows.sort(key=lambda row: (-row["ageDays"], row["caseId"]))
    return {"schemaVersion": WORKLIST_VERSION, "simulationId": run.simulation_id, "asOf": as_of,
            "status": "open", "total": len(rows), "rows": rows}


def export_run(snapshot: dict, request: dict, store: str | Path, *, on_stage=lambda _: None) -> tuple[Path, dict, bool]:
    """Write ``store/runs/<key>``; identical inputs reuse a verified bundle before replaying.

    ``request`` accepts the Studio's viewer-m2c-run/1.0 export or the usual RunRequest fields (``year`` and
    ``previous``: a later year of a chain, replayed from the first). The snapshot digest, effective settings and seed
    resolve aliases and defaults in the key.
    """
    from api._m2c import RunRequest, chain_of
    from utilsim.m2c import yearclose
    from utilsim.m2c.calendar import FIRST_YEAR

    on_stage("archive.prepare")
    snapshot = orjson.loads(_json(snapshot))
    # Generation timings describe the machine, not the town. Keep archived snapshots and
    # their identity stable when a self-describing town is rebuilt on another machine.
    snapshot.get("stats", {}).pop("timingsS", None)
    req = RunRequest.model_validate({**request, "town": snapshot["id"]})
    chain = chain_of(req)
    year = FIRST_YEAR + len(chain) - 1
    town = M2CTown.from_snapshot(snapshot, year)
    # Resolve settings without simulating, using the engine's own validation.
    from utilsim.m2c.run import resolve_settings

    cfg = resolve_settings(town.cfg, req.settings)
    as_of = req.asOf or cfg.scenario.date
    cal = town.cal
    day = cal.parse_day(as_of, -1)
    if not cal.in_year(day) or as_of != cal.date_of(day).isoformat():
        raise ValueError(f"an export needs a date in {cal.year}")
    as_of = cal.date_of(day).isoformat()
    seed = run_seed(town.cfg, req.seed) or town_seed(town.cfg)
    inputs = {"town": town.id, "snapshotSha256": _sha(_json(snapshot)),
              "settings": {g: getattr(cfg, g).model_dump(mode="json") for g in M2C_GROUPS},
              "seed": seed, "asOf": as_of,
              "actions": [a.model_dump(exclude_none=True) for a in req.actions],
              "outages": [o.model_dump(exclude_none=True) for o in req.outages],
              "episodes": [e.model_dump(by_alias=True, exclude_none=True) for e in req.episodes]}
    if req.staffing:
        inputs["staffing"] = req.staffing
    if req.upstream:
        inputs["upstream"] = req.upstream
    if year > FIRST_YEAR:  # a later year: the years it opens on are part of what it is
        inputs.update(year=year, previous=chain[:-1])
    build = engine_build()
    key = run_key(build, inputs)
    runs = Path(store).expanduser() / "runs"
    destination = runs / key
    if destination.exists():
        on_stage("archive.verify_reused")
        return destination, read_manifest(destination), True

    on_stage("replay.reads_vee_billing")

    def _ops():  # the networks: the year's incidents, the field crews' assets, overdue maintenance failing
        from utilsim.ops.opstown import ops_town

        return ops_town(snapshot)

    if year == FIRST_YEAR:
        run = M2CRun(town, inputs["settings"], inputs["actions"], inputs["outages"], seed=seed,
                     episodes=inputs["episodes"], staffing=inputs.get("staffing"), upstream=inputs.get("upstream"),
                     strict=True, ops_factory=_ops)
    else:
        last = {k: inputs[k] for k in ("settings", "actions", "outages", "episodes", "staffing", "upstream")
                if k in inputs}
        run = yearclose.replay(snapshot, [*inputs["previous"], last], seed=seed, strict=True, ops_factory=_ops)
    runs.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".tmp-{key}-", dir=runs))
    files = []

    def write(name, data):
        raw = _json(data)
        if name.endswith(".gz"):
            raw = gzip.compress(raw, compresslevel=6, mtime=0)
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        files.append({"name": name, "bytes": len(raw), "sha256": _sha(raw), "uploaded": False})

    try:
        write("inputs.json", inputs)
        on_stage("analysis.annual_trends")
        yearly = trend.trend(run, as_of)
        on_stage("analysis.summary")
        summary = compact_summary(views.summary(run, as_of))
        on_stage("analysis.scorecard")
        scorecard = views.scorecard(run, as_of=as_of)
        dates = snapshot_dates(as_of)
        aggregates = {"schemaVersion": AGGREGATES_VERSION, "runKey": key,
                      "engineVersion": GENERATOR_VERSION, "engineBuild": build, "asOf": as_of,
                      "towns": [{"id": town.id, "name": town.name, "summary": summary,
                                 "trend": yearly, "scorecard": scorecard}], "episodes": yearly["episodes"]}
        on_stage("archive.aggregates")
        write("aggregates.json", aggregates)
        write("trend.json", yearly)
        on_stage("analysis.daily")
        write("daily.json.gz", daily.daily(run))
        write("scorecard.json", scorecard)
        on_stage("archive.snapshot")
        write("snapshot.json.gz", snapshot)
        write("tables/catalog.json", tables.catalog())
        on_stage("archive.master_data")
        master = tables.master_data(snapshot)
        for spec in tables.SPECS:
            on_stage("archive.table." + spec.name)
            _, table, _ = tables.build(run, master, spec.name, as_of)
            write(f"tables/{spec.name}.json.gz",
                  {"schemaVersion": TABLE_VERSION, "simulationId": run.simulation_id, "asOf": as_of,
                   "table": spec.name, **spec.json(), "columns": [c.json() for c in table.cols],
                   "searchColumns": [i for i, c in enumerate(table.cols) if c.search],
                   "facets": table.facets, "rows": list(map(list, zip(*table.data)))})
        on_stage("archive.month_end_views")
        for date in dates:
            write(f"worklists/{date}.json.gz", _open_worklist(run, date))
            write(f"summaries/{date}.json", compact_summary(views.summary(run, date)))
        manifest = {"schemaVersion": MANIFEST_VERSION, "runKey": key,
                    "engineVersion": GENERATOR_VERSION, "engineBuild": build, "inputs": inputs,
                    "simulationId": run.simulation_id, "asOf": as_of, "worklistDates": dates,
                    "towns": [{"id": town.id, "name": town.name, "accounts": len(town.accounts),
                               "registers": town.n_registers}], "files": files,
                    "aggregates": "aggregates.json", "tableDates": [as_of],
                    "readOnly": True}
        (staging / "manifest.json").write_bytes(_json(manifest))
        on_stage("archive.verify")
        read_manifest(staging)
        try:
            os.rename(staging, destination)
        except OSError:
            if not destination.exists():
                raise
            # Another exporter completed the same key while this one was working.
            manifest = read_manifest(destination)
        return destination, manifest, False
    finally:
        if staging.exists():
            shutil.rmtree(staging)
