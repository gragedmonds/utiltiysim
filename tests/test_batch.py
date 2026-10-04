"""Batch boundaries, measured estimates and shared-resource semantics."""
import pytest

from utilsim.batch import district_sizes, job_lock, progress, run_batch
from utilsim.config.model import SimConfig


@pytest.mark.parametrize("homes", [500, 5000, 25000, 50000, 49999, 2001])
def test_bounded_districts_cover_every_home_once(homes):
    sizes = district_sizes(homes)
    assert sum(sizes) == homes
    assert min(sizes) >= 20
    assert max(sizes) <= 2000
    assert max(sizes) - min(sizes) <= 1
    assert sizes == district_sizes(homes)


def test_eta_unknown_until_a_full_batch_finishes():
    job = {"homes": 4000, "status": "running", "districts": [{"homes": 2000}, {"homes": 2000}]}
    assert progress(job)["etaSeconds"] is None
    job["districts"][0].update(result={"runKey": "one"}, seconds=100)
    assert progress(job, 25)["etaSeconds"] == 75
    assert progress(job, 110)["overrun"] is True


def test_staffing_and_network_modes_are_explicit(tmp_path):
    with pytest.raises(ValueError, match="independent-districts or shared"):
        run_batch(SimConfig(), 50000, tmp_path, staffing="pooled")
    with pytest.raises(ValueError, match="independent or connected"):
        run_batch(SimConfig(), 50000, tmp_path, staffing="shared", network="meshed")
    with pytest.raises(ValueError, match="float share"):
        run_batch(SimConfig(), 50000, tmp_path, staffing="shared", float_share=2.0)
    with pytest.raises(ValueError, match="town-specific actions"):
        run_batch(SimConfig(), 50000, tmp_path, {"actions": [{"id": "one"}]}, staffing="independent-districts")
    assert not list(tmp_path.iterdir())


def test_a_utility_shares_its_workforce_and_networks(tmp_path):
    """Three small districts, one workforce, connected networks: a first pass measures each district, the coordinator
    staffs them from one pool, the final pass replays each with its schedule and its upstream events; a paused run
    resumes where it stopped."""
    import orjson

    from utilsim.cli import _cfg

    cfg = _cfg("small_town", None, None, None, None)
    kw = dict(chunk_size=30, staffing="shared", network="connected", float_share=0.5)
    directory, job = run_batch(cfg, 90, tmp_path, {"asOf": "2026-12-31"}, max_batches=2, **kw)
    assert job["status"] == "paused" and sum(1 for d in job["districts"] if d.get("probe")) == 2
    assert not (directory / "staffing.json").exists()
    directory, job = run_batch(cfg, 90, tmp_path, {"asOf": "2026-12-31"}, **kw)
    assert job["status"] == "complete" and all(d.get("result") for d in job["districts"])
    plan = orjson.loads((directory / "staffing.json").read_bytes())
    net = orjson.loads((directory / "network.json").read_bytes())
    staff = plan["staff"]["analysts"]
    assert {sum(day) for day in zip(*staff, strict=True)} == {plan["pools"]["analysts"]["total"]}
    for d in job["districts"]:
        inputs = orjson.loads((tmp_path / "runs" / d["result"]["runKey"] / "inputs.json").read_bytes())
        assert inputs["staffing"] == plan["schedules"][d["id"]]
        assert inputs["upstream"] == net["upstream"][d["id"]]
        assert not (directory / f"{d['id']}.snapshot.json.gz").exists()  # the bundle keeps it
    roll = orjson.loads((directory / "rollup.json").read_bytes())
    assert roll["complete"] and roll["staffing"] == "shared" and roll["network"] == "connected"
    assert roll["daily"]["staff"]["analysts"]["people"][5] == plan["pools"]["analysts"]["total"]
    assert sum(roll["daily"]["contact"]["contacts"]) > 0
    again = run_batch(cfg, 90, tmp_path, {"asOf": "2026-12-31"}, **kw)[1]  # done: nothing replays
    assert [d["result"]["runKey"] for d in again["districts"]] == [d["result"]["runKey"] for d in job["districts"]]


def test_duplicate_job_lock_is_refused_and_released(tmp_path):
    path = tmp_path / "lock"
    with job_lock(path):
        with pytest.raises(ValueError, match="already running"):
            with job_lock(path):
                pass
    with job_lock(path):
        pass


def test_limit_and_disjoint_stage_timing(tmp_path):
    import orjson

    from utilsim.batch import StageRecorder, timing_totals

    with pytest.raises(ValueError, match="50,000"):
        district_sizes(50001)
    ticks = iter([0, 1, 4, 9])
    recorder = StageRecorder(tmp_path / "progress.json", clock=lambda: next(ticks))
    recorder.start("generation")
    recorder.start("replay")
    assert recorder.finish() == {"generation": 3, "replay": 5}
    assert orjson.loads(recorder.path.read_bytes())["stage"] is None
    job = {"districts": [{"result": {"timingsSeconds": recorder.timings}},
                         {"result": {"timingsSeconds": {"replay": 2}}}, {}]}
    assert timing_totals(job) == {"replay": 7, "generation": 3}
