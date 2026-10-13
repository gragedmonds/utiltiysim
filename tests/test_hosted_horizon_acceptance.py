"""Exercise the acceptance runner against real HTTP and isolated source copies."""
import pytest
from test_hosted_worlds import setup  # noqa: F401

from scripts.check_hosted_horizon import run


def test_http_horizon_reopens_same_world_and_preserves_template(setup, tmp_path):  # noqa: F811
    _, template, _, _ = setup
    output = tmp_path / 'evidence'
    result = run(template, output, '2026-01-01', '2026-01-04', 2)
    assert result['status'] == 'passed'
    assert result['completedDays'] == 3
    assert result['observations'] == result['samplePremiseHistoryRows'] == 9
    assert result['restartCount'] == 2 and result['serverStopped']
    assert result['revalidatedWindows'] == 2
    assert result['sourceUnchanged']
    assert [b['observations'] for b in result['batches']] == [6, 3]


def test_refuse_reusing_evidence_or_nesting_source(setup, tmp_path):  # noqa: F811
    _, template, _, _ = setup
    protected = tmp_path / 'evidence'
    protected.mkdir()
    marker = protected / 'original.txt'
    marker.write_text('preserve')
    for output in (protected, template / 'new-output'):
        with pytest.raises(ValueError, match='new output directory'):
            run(template, output, '2026-01-01', '2026-01-02')
    assert marker.read_text() == 'preserve'
    assert not (template / 'new-output').exists()


def test_changed_source_refused_before_any_output(setup, tmp_path):  # noqa: F811
    _, template, _, _ = setup
    (template / 'source-snapshot.json').write_text('{}')
    output = tmp_path / 'evidence'
    with pytest.raises(ValueError, match='checksum'):
        run(template, output, '2026-01-01', '2026-01-02')
    assert not output.exists()


@pytest.mark.parametrize('start,through,batch', [
    ('20260101', '2026-01-02', 1), ('2026-01-02', '2026-01-01', 1),
    ('2026-01-01', '2028-01-01', 31), ('2026-01-01', '2026-01-02', 32),
])
def test_invalid_horizon_refused_without_touching_source(tmp_path, start, through, batch):
    with pytest.raises(ValueError):
        run(tmp_path / 'missing-template', tmp_path / 'evidence', start, through, batch)
    assert not (tmp_path / 'evidence').exists()
