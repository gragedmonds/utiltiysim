"""Durable, bounded-memory local runs of a utility's districts.

Each district is a complete engine run in its own process (bounded memory). By default every district has its own
teams and networks (``independent-districts``). A utility above them (utilsim/utility/) can also:

* **share one workforce** (``staffing="shared"``): a first pass replays every district at its own staffing and
  measures its days (``run-daily/1.0``); the coordinator then staffs all of them from one pool, a home team in each
  and a float team sent each working day where the work waits; the final pass replays each district with its
  schedule (``staffing.json``);
* **connect the networks** (``network="connected"``): transmission circuits, the treatment plant and its mains and
  the gas gate stations feed runs of neighbouring districts; their events of the year reach every district they
  feed, and the districts share one weather (storm days).

No percentages are extrapolated.
"""
from __future__ import annotations

import hashlib
import math
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import orjson

VERSION = "utility-batch/1.0"
STAFFING = "independent-districts"
STAFFING_MODES = (STAFFING, "shared")
NETWORKS = ("independent", "connected")


def district_sizes(homes: int, chunk_size: int = 2000) -> list[int]:
    if not 20 <= homes <= 500_000 or not 20 <= chunk_size <= 5000:
        raise ValueError("Choose 20–500,000 total homes and 20–5,000 homes per district.")
    count = math.ceil(homes / chunk_size)
    size, extra = divmod(homes, count)
    if size < 20:
        raise ValueError("Increase the district size so every district has at least 20 homes.")
    return [size + (i < extra) for i in range(count)]


def write_json(path: Path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as f:
        f.write(orjson.dumps(value, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2))
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


class StageRecorder:
    """Disjoint wall-time phases, outside deterministic run archives."""

    def __init__(self, path: Path, clock=time.monotonic):
        self.path, self.clock = path, clock
        self.stage = None
        self.started = clock()
        self.timings = {}

    def start(self, stage):
        now = self.clock()
        if self.stage is not None:
            self.timings[self.stage] = self.timings.get(self.stage, 0) + now - self.started
        self.stage, self.started = stage, now
        write_json(self.path, {"stage": stage, "startedMonotonic": now,
                              "timingsSeconds": self.timings})

    def finish(self):
        self.start(None)
        return {name: round(seconds, 4) for name, seconds in self.timings.items()}


def timing_totals(job):
    totals = {}
    for district in job["districts"]:
        for name, seconds in district.get("result", {}).get("timingsSeconds", {}).items():
            totals[name] = round(totals.get(name, 0) + seconds, 4)
    return dict(sorted(totals.items(), key=lambda item: -item[1]))


@contextmanager
def job_lock(path: Path):
    """OS lock releases on process exit, including crashes, on Windows and Unix."""
    with path.open("a+b") as f:
        f.write(b"0")
        f.flush()
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("This batch job is already running in another process.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def progress(job: dict, elapsed: float = 0, stage: dict | None = None) -> dict:
    completed = [d for d in job["districts"] if d.get("result")]
    done_homes = sum(d["homes"] for d in completed)
    remaining = job["homes"] - done_homes
    seconds_per_home = sum(d["seconds"] for d in completed) / done_homes if done_homes else None
    expected = remaining * seconds_per_home if seconds_per_home is not None else None
    return {"status": job["status"], "completed": len(completed), "total": len(job["districts"]),
            "completedHomes": done_homes, "totalHomes": job["homes"], "activeSeconds": round(elapsed),
            "activeDistrict": job.get("activeDistrict"),
            "stage": (stage or {}).get("stage"),
            "stageSeconds": round(max(0, time.monotonic() - stage["startedMonotonic"]), 1) if stage and stage.get("stage") else None,
            "stageTimingsSeconds": (stage or {}).get("timingsSeconds", {}),
            "completedStageTotalsSeconds": timing_totals(job),
            "etaSeconds": round(max(0, expected - elapsed)) if expected is not None and job["status"] != "finalizing" else None,
            "overrun": expected is not None and elapsed > expected,
            "etaBasis": "Measured completed districts; includes generation, replay and archive writing."}


def utility_days(job: dict, store: Path) -> dict:
    """The utility day by day: its districts' days (``run-daily/1.0``) added up (the oldest waiting work is the
    oldest anywhere)."""
    import gzip

    total: dict = {}

    def add(into: dict, key: str, values: list, how: str = "sum") -> None:
        cur = into.get(key)
        into[key] = list(values) if cur is None else [
            (a + b) if how == "sum" else max(a, b) for a, b in zip(cur, values, strict=True)]

    for district in job["districts"]:
        if not district.get("result"):
            continue
        path = store / "runs" / district["result"]["runKey"] / "daily.json.gz"
        if not path.exists():
            continue
        d = orjson.loads(gzip.decompress(path.read_bytes()))
        total.setdefault("start", d["start"])
        total.setdefault("days", d["days"])
        for q, s in d["queues"].items():
            for k, v in s.items():
                add(total.setdefault("queues", {}).setdefault(q, {}), k, v)
        for who, s in d["staff"].items():
            for k, v in s.items():
                if k != "workday":
                    add(total.setdefault("staff", {}).setdefault(who, {}), k, v, "max" if k == "oldestDays" else "sum")
        for crew, s in d["crews"].items():
            for k, v in s.items():
                add(total.setdefault("crews", {}).setdefault(crew, {}), k, v, "max" if k == "oldestDays" else "sum")
        for k, v in d["contact"].items():
            add(total.setdefault("contact", {}), k, v)
        for u, s in d["outages"].items():
            for k, v in s.items():
                add(total.setdefault("outages", {}).setdefault(u, {}), k, v)
    return total


def rollup(job: dict, store: Path) -> dict:
    """Only additive measures; no average-of-averages or cross-district record joins."""
    from utilsim.io.run_bundle import read_manifest

    months = {}
    accounts = registers = done = 0
    for district in job["districts"]:
        if not district.get("result"):
            continue
        directory = store / "runs" / district["result"]["runKey"]
        manifest = read_manifest(directory)
        accounts += sum(t["accounts"] for t in manifest["towns"])
        registers += sum(t["registers"] for t in manifest["towns"])
        done += 1
        for month in orjson.loads((directory / "trend.json").read_bytes())["months"]:
            if month["billing"] is None or month["cases"] is None:
                continue
            row = months.setdefault(month["month"], {"month": month["month"], "billing": {}, "cases": {}})
            for group, fields in (("billing", ("documents", "blocked", "billed", "invoices", "invoiced", "collected", "overdue", "receivable")),
                                  ("cases", ("opened", "resolved", "backlog", "escalated", "fieldOrders"))):
                for field in fields:
                    row[group][field] = round(row[group].get(field, 0) + month[group][field], 2)
    return {"schemaVersion": VERSION, "complete": done == len(job["districts"]),
            "asOf": job["inputs"]["request"]["asOf"], "totalHomes": job["homes"],
            "completedHomes": sum(d["homes"] for d in job["districts"] if d.get("result")),
            "generatedHomes": sum(d["result"]["generatedHomes"] for d in job["districts"] if d.get("result")),
            "completedDistricts": done, "accounts": accounts, "registers": registers,
            "months": list(months.values()), "daily": utility_days(job, store),
            "staffing": job["inputs"]["staffing"], "network": job["inputs"].get("network", "independent"),
            "note": ("Additive results from districts sharing one workforce, coordinated daily (staffing.json)."
                     if job["inputs"]["staffing"] == "shared" else
                     "Additive results from independent districts. Teams are not shared.")
            + (" Their upstream networks are connected (network.json)." if job["inputs"].get("network") == "connected"
               else " Networks are not connected.") + " All money uses the same base configuration."}


def run_batch(cfg, homes: int, store: Path, request: dict | None = None, *,
              chunk_size: int = 2000, staffing: str, map_data: bool = False, max_batches: int | None = None,
              network: str = "independent", float_share: float = 0.3, on_progress=lambda _: None, should_pause=lambda: False):
    from api._m2c import RunRequest
    from utilsim.io.run_bundle import engine_build, read_manifest
    from utilsim.m2c.calendar import calendar
    from utilsim.m2c.run import parse_episodes, resolve_episode_days, resolve_settings

    if staffing not in STAFFING_MODES:
        raise ValueError(f"Staffing is {' or '.join(STAFFING_MODES)} (shared: one workforce, coordinated daily).")
    if network not in NETWORKS:
        raise ValueError(f"Network is {' or '.join(NETWORKS)}.")
    if not 0.0 <= float_share <= 1.0:
        raise ValueError("The float share is 0 to 1.")
    sizes = district_sizes(homes, chunk_size)
    if max_batches is not None and max_batches < 1:
        raise ValueError("max-batches must be positive.")
    request = {} if request is None else request
    if not isinstance(request, dict):
        raise ValueError("Batch input must be a JSON object.")
    if set(request) - {"settings", "episodes", "seed", "asOf"}:
        raise ValueError("Batch input accepts settings, episodes, seed and asOf only; town-specific actions cannot be copied across districts.")
    req = RunRequest.model_validate({**request, "town": "district", "asOf": request.get("asOf") or "2026-12-31"})
    cal = calendar()  # district batches replay the snapshot's year
    if not cal.in_year(cal.parse_day(req.asOf, -1)):
        raise ValueError(f"Choose a view date in {cal.year}.")
    resolved = resolve_settings(cfg, req.settings)
    episodes = [e.model_dump(by_alias=True, exclude_none=True) for e in req.episodes]
    resolve_episode_days(resolved, parse_episodes(resolved, episodes))
    request = {"settings": req.settings, "episodes": episodes, "seed": req.seed, "asOf": req.asOf}
    inputs = {"config": cfg.model_dump(mode="json"), "homes": homes, "sizes": sizes, "request": request,
              "staffing": staffing, "mapData": map_data, "engineBuild": engine_build(), "schemaVersion": VERSION}
    if staffing == "shared":
        inputs["floatShare"] = float_share
    if network == "connected":
        inputs["network"] = network
    key = hashlib.sha256(orjson.dumps(inputs, option=orjson.OPT_SORT_KEYS)).hexdigest()
    store = Path(store).expanduser().resolve()
    directory = store / "batches" / key
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "job.json"
    with job_lock(directory / "job.lock"):
        if path.exists():
            job = orjson.loads(path.read_bytes())
            if job["inputs"] != inputs:
                raise ValueError("Saved batch inputs do not match this run.")
        else:
            job = {"schemaVersion": VERSION, "key": key, "homes": homes, "inputs": inputs, "status": "queued",
                   "districts": [{"id": f"district-{i+1:04d}", "homes": n} for i, n in enumerate(sizes)]}
            if network == "connected":
                from utilsim.utility import network as nw

                lay = nw.layout([d["id"] for d in job["districts"]])
                seed = f"{cfg.seeds.master}:utility"
                ups = nw.upstream_inputs(lay, seed, cal)
                write_json(directory / "network.json", {**lay, "seed": seed, "upstream": ups})
            write_json(path, job)
        completed_now = 0
        try:
            passes = ("probe", "final") if staffing == "shared" else ("final",)
            for mode in passes:
                if mode == "final" and staffing == "shared" and not (directory / "staffing.json").exists():
                    if not all(d.get("probe") for d in job["districts"]):
                        break  # paused in the first pass
                    write_json(directory / "staffing.json", _coordinate(job, directory, float_share))
                done_key = "probe" if mode == "probe" else "result"
                for index, district in enumerate(job["districts"]):
                    if district.get(done_key):
                        if mode == "final":
                            read_manifest(store / "runs" / district["result"]["runKey"])
                        continue
                    if should_pause() or (max_batches is not None and completed_now >= max_batches):
                        break
                    job["status"] = "running"
                    job["pass"] = mode
                    job["activeDistrict"] = district["id"]
                    write_json(path, job)
                    stage_path = directory / f"{district['id']}.progress.json"
                    stage_path.unlink(missing_ok=True)
                    started = time.monotonic()
                    on_progress(progress(job))
                    # Process isolation releases all generation/replay memory before the next district.
                    command = [sys.executable, "--batch-worker"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "utilsim.batch"]
                    child = subprocess.Popen([*command, str(path), str(index), mode])
                    try:
                        while child.poll() is None:
                            time.sleep(1)
                            stage = orjson.loads(stage_path.read_bytes()) if stage_path.exists() else None
                            on_progress(progress(job, time.monotonic() - started, stage))
                        if child.returncode:
                            raise RuntimeError(f"{district['id']} failed. Completed districts are saved; rerun to resume.")
                    except BaseException:
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
                        raise
                    out = orjson.loads((directory / f"{district['id']}.{'probe.' if mode == 'probe' else ''}json")
                                       .read_bytes())
                    if mode == "probe":
                        district["probe"] = out
                        district["probeSeconds"] = round(time.monotonic() - started, 3)
                    else:
                        district["result"] = out
                        district["seconds"] = round(time.monotonic() - started, 3)
                    write_json(path, job)
                    completed_now += 1
            job.pop("pass", None)
            final_status = "complete" if all(d.get("result") for d in job["districts"]) else "paused"
            job["status"] = "finalizing"
            job.pop("activeDistrict", None)
            write_json(path, job)
            on_progress(progress(job))
            finalizing = time.monotonic()
            write_json(directory / "rollup.json", rollup(job, store))
            job["finalizationSeconds"] = round(time.monotonic() - finalizing, 4)
            write_json(directory / "timings.json", {"stagesSeconds": timing_totals(job),
                       "finalizationSeconds": job["finalizationSeconds"],
                       "districtWallSeconds": sum(d.get("seconds", 0) for d in job["districts"]),
                       "note": "Worker phases are disjoint wall times; process startup and parent polling are additional."})
            job["status"] = final_status
        except BaseException:
            job["status"] = "paused"
            raise
        finally:
            job.pop("activeDistrict", None)
            write_json(path, job)
            on_progress(progress(job))
    return directory, job


def _coordinate(job: dict, directory: Path, float_share: float) -> dict:
    """One workforce for every district, from the first pass's measured days (``utility-staffing/1.0``)."""
    import gzip

    from utilsim.utility import coordinator as co

    districts = [{"id": d["id"], "premises": d["probe"]["premises"],
                  "daily": orjson.loads(gzip.decompress((directory / f"{d['id']}.daily.json.gz").read_bytes()))}
                 for d in job["districts"]]
    minutes = {"analysts": districts[0]["daily"]["staffMinutes"]["analysts"],
               "supervisors": districts[0]["daily"]["staffMinutes"]["supervisors"]}
    return co.plan(districts, float_share=float_share, minutes=minutes)


def district_worker(path: Path, index: int, mode: str = "final"):
    import gzip

    from utilsim.config.model import SimConfig
    from utilsim.io.run_bundle import export_run

    job = orjson.loads(path.read_bytes())
    district = job["districts"][index]
    recorder = StageRecorder(path.parent / f"{district['id']}.progress.json")
    recorder.start("worker.prepare")
    cached = path.parent / f"{district['id']}.snapshot.json.gz"
    detail = "full" if job["inputs"].get("mapData", False) else "analysis"
    if cached.exists():  # generated in the first pass
        snapshot = orjson.loads(gzip.decompress(cached.read_bytes()))
    else:
        from utilsim.gen.pipeline import generate
        from utilsim.io.snapshot import build_snapshot

        config = job["inputs"]["config"]
        config["town"]["houses"] = district["homes"]
        master = config["seeds"]["master"]
        # Shared weather draw; unique geography, customers and incident draws in each district.
        for group in ("master", "town", "households", "incidents", "anomalies"):
            source = config["seeds"].get(group) or master
            config["seeds"][group] = hashlib.sha256(f"{source}:{district['id']}".encode()).hexdigest()[:32]
        config["seeds"]["weather"] = config["seeds"].get("weather") or master
        cfg = SimConfig.model_validate(config)
        from utilsim.io.run_bundle import engine_build
        from utilsim.worker.contracts import digest

        detail = "full" if job["inputs"].get("mapData", False) else "analysis"
        baseline_key = digest({"config": config, "engineBuild": engine_build(), "detail": detail})
        cache = path.parents[2] / "baselines" / baseline_key
        cache.mkdir(parents=True, exist_ok=True)
        snapshot_path = cache / "snapshot.json.gz"
        marker = cache / "manifest.json"
        with job_lock(cache / "cache.lock"):
            if marker.exists():
                recorder.start("baseline.verify_reuse")
                data = snapshot_path.read_bytes()
                if hashlib.sha256(data).hexdigest() != orjson.loads(marker.read_bytes())["sha256"]:
                    raise ValueError("Saved baseline failed its checksum. Choose another library or restore the baseline.")
                snapshot = orjson.loads(gzip.decompress(data))
            else:
                town = generate(cfg, on_stage=recorder.start)
                recorder.start(f"snapshot.{detail}")
                snapshot = build_snapshot(town, detail=detail)
                snapshot.get("stats", {}).pop("timingsS", None)
                recorder.start("baseline.save")
                data = gzip.compress(orjson.dumps(snapshot, option=orjson.OPT_SERIALIZE_NUMPY), compresslevel=3, mtime=0)
                temporary = cache / "snapshot.tmp"
                temporary.write_bytes(data)
                os.replace(temporary, snapshot_path)
                write_json(marker, {"sha256": hashlib.sha256(data).hexdigest(), "key": baseline_key})
    request = dict(job["inputs"]["request"])
    if request.get("seed"):
        request["seed"] = hashlib.sha256(f"{request['seed']}:{district['id']}".encode()).hexdigest()[:32]
    net = path.parent / "network.json"
    if net.exists():  # the utility's upstream networks: this district's events and the shared weather
        request["upstream"] = orjson.loads(net.read_bytes())["upstream"][district["id"]]
    if mode == "probe":
        from utilsim.m2c import daily as dl
        from utilsim.m2c.base import M2CTown
        from utilsim.m2c.run import M2CRun
        from utilsim.ops.opstown import ops_town

        cached.write_bytes(gzip.compress(orjson.dumps(snapshot, option=orjson.OPT_SERIALIZE_NUMPY), compresslevel=6,
                                         mtime=0))
        recorder.start("probe.replay")
        town = M2CTown.from_snapshot(snapshot)
        run = M2CRun(town, request.get("settings"), seed=request.get("seed"), episodes=request.get("episodes") or [],
                     upstream=request.get("upstream"), strict=True, ops_factory=lambda: ops_town(snapshot))
        days = dl.daily(run)
        days["staffMinutes"] = {"analysts": run.cfg.process.analyst_hours_per_day * 60.0,
                                "supervisors": run.cfg.process.supervisor_hours_per_day * 60.0}
        (path.parent / f"{district['id']}.daily.json.gz").write_bytes(
            gzip.compress(orjson.dumps(days, option=orjson.OPT_SERIALIZE_NUMPY), compresslevel=6, mtime=0))
        write_json(path.parent / f"{district['id']}.probe.json",
                   {"premises": len(town.premise_ids), "timingsSeconds": recorder.finish()})
        return
    plan = path.parent / "staffing.json"
    if plan.exists():  # one workforce: this district's people day by day
        request["staffing"] = orjson.loads(plan.read_bytes())["schedules"][district["id"]]
    directory, manifest, reused = export_run(snapshot, request, path.parents[2], on_stage=recorder.start)
    cached.unlink(missing_ok=True)  # the bundle keeps the snapshot
    write_json(path.parent / f"{district['id']}.json", {"runKey": manifest["runKey"],
               "timingsSeconds": recorder.finish(), "mapData": detail == "full",
               "townId": snapshot["id"], "directory": str(directory), "reused": reused,
               "namespace": district["id"], "requestedHomes": district["homes"],
               "generatedHomes": snapshot["stats"]["houses"]})


if __name__ == "__main__":
    district_worker(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "final")
