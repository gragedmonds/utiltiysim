"""Batch boundaries, measured estimates and shared-resource semantics."""
import pytest

from utilsim.batch import district_sizes, job_lock, progress, run_batch
from utilsim.config.model import SimConfig


@pytest.mark.parametrize("homes", [500, 5000, 50000, 500000, 500001 - 2, 2001])
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


def test_shared_staffing_cannot_silently_become_independent_districts(tmp_path):
    with pytest.raises(ValueError, match="Shared teams"):
        run_batch(SimConfig(), 50000, tmp_path, staffing="shared")
    with pytest.raises(ValueError, match="town-specific actions"):
        run_batch(SimConfig(), 50000, tmp_path, {"actions": [{"id": "one"}]}, staffing="independent-districts")
    assert not list(tmp_path.iterdir())


def test_duplicate_job_lock_is_refused_and_released(tmp_path):
    path = tmp_path / "lock"
    with job_lock(path):
        with pytest.raises(ValueError, match="already running"):
            with job_lock(path):
                pass
    with job_lock(path):
        pass
