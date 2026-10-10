import gzip
import json
from pathlib import Path

import pytest

from scripts.benchmark_world_scale import arguments, run


def source(tmp_path):
    # A real minimal physical world with one customer-owned water meter.
    snapshot = {'schemaVersion': 'utility-town/2.0', 'id': 'scale-test-town', 'seed': 'scale-test',
                'accounts': [{'id': 'A1'}],
                'premises': [{'id': 'P1', 'occupied': True, 'dailyWaterM3': 1}],
                'meters': [{'id': 'M1', 'installedAt': '2026-01-01'}],
                'servicePoints': [{'commodity': 'water', 'premiseId': 'P1', 'meterId': 'M1',
                                   'installationId': 'I1'}]}
    path = tmp_path / 'source.json'
    path.write_text(json.dumps(snapshot), encoding='utf-8')
    return path


def args(path, out, *extra):
    return arguments(['--snapshot', str(path), '--out', str(out), '--days', '2',
                      '--minimum-accounts', '1', '--max-seconds', '20', *extra])


def test_resume_preserves_sources_and_completed_boundary(tmp_path):
    path, out = source(tmp_path), tmp_path / 'measurement'
    original = path.read_bytes()
    first = run(args(path, out, '--max-seconds', '0.000001'))
    assert not first['targetReached'] and first['stopReason'] == 'wall_time_budget'
    result = run(args(path, out, '--resume'))
    assert result['targetReached'] and not result['integratedAcceptance']
    assert result['districts'][0]['truthRows'] == 2
    assert result['districts'][0]['completedBoundaryReplayUnchanged']
    before = Path(result['districts'][0]['database']).read_bytes()
    retry = run(args(path, out, '--resume'))
    assert retry['measuredDistrictDaysThisInvocation'] == 0
    assert Path(result['districts'][0]['database']).read_bytes() == before
    assert path.read_bytes() == original


def test_same_town_cannot_be_counted_twice_by_reencoding(tmp_path):
    path = source(tmp_path)
    compressed = tmp_path / 'reencoded.json.gz'
    compressed.write_bytes(gzip.compress(json.dumps(json.loads(path.read_text()), indent=2).encode()))
    out = tmp_path / 'duplicate'
    with pytest.raises(ValueError, match='distinct saved districts'):
        run(args(path, out, '--snapshot', str(compressed)))
    assert not out.exists()


def test_changed_source_or_missing_saved_district_refuses_resume(tmp_path):
    path, out = source(tmp_path), tmp_path / 'measurement'
    run(args(path, out))
    original = path.read_bytes()
    database = out / 'district-1.sqlite'
    before = database.read_bytes()
    path.write_bytes(original + b' ')
    with pytest.raises(ValueError, match='Resume must match'):
        run(args(path, out, '--resume'))
    assert database.read_bytes() == before
    path.write_bytes(original)
    database.rename(out / 'preserved.sqlite')
    with pytest.raises(ValueError, match='database is missing'):
        run(args(path, out, '--resume'))
    assert not database.exists()
    assert (out / 'preserved.sqlite').read_bytes() == before


def test_concurrent_run_lock_does_not_open_or_change_saved_database(tmp_path):
    path, out = source(tmp_path), tmp_path / 'measurement'
    run(args(path, out))
    before = (out / 'district-1.sqlite').read_bytes()
    lock = out / 'running.lock'
    lock.write_text('another-process', encoding='utf-8')
    with pytest.raises(FileExistsError):
        run(args(path, out, '--resume'))
    assert lock.read_text() == 'another-process'
    assert (out / 'district-1.sqlite').read_bytes() == before
