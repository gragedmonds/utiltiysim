"""Temporary Windows telemetry locks must not terminate a district's physical/financial work."""
from pathlib import Path

import pytest

from utilsim.batch import run_batch
from utilsim.config import load_preset


@pytest.mark.parametrize('target,error', [('progress', PermissionError), ('progress', FileNotFoundError),
                                         ('result', PermissionError)])
def test_transient_progress_read_lock_does_not_kill_district(tmp_path, monkeypatch, target, error):
    original = Path.read_bytes
    denied = []

    def locked(path):
        matches = path.name.endswith('.progress.json') if target == 'progress' else path.name == 'district-0001.json'
        if matches and not denied:
            denied.append(path)
            raise error('Windows file replacement sharing window')
        return original(path)

    monkeypatch.setattr(Path, 'read_bytes', locked)
    def run():
        return run_batch(load_preset('village'), 20, tmp_path, {'asOf': '2026-01-02'},
                         chunk_size=20, staffing='independent-districts')
    if target == 'result':
        with pytest.raises(PermissionError):
            run()  # Required business results cannot be treated as optional progress.
        assert denied
        return
    _, job = run()
    assert denied, 'The test must actually hit the observer read window.'
    assert job['status'] == 'complete'
    assert len(job['districts']) == 1 and job['districts'][0]['result']['runKey']
