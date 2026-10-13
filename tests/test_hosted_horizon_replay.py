"""Detect physical divergence even when per-world counts and lineage are valid."""
import sqlite3

import pytest
from test_world_v2 import snapshot

from scripts.check_hosted_horizon_replay import compare, file_hash
from utilsim.world.store import World


@pytest.fixture
def pair(tmp_path):
    left, right = tmp_path / 'left.sqlite', tmp_path / 'right.sqlite'
    for path, environment in ((left, 'LEFT'), (right, 'RIGHT')):
        world = World(path)
        world.initialize(snapshot(), environment)
        world.advance('2026-01-03')
        world = World(path)
        world.advance('2026-01-06')
    return left, right


def test_distinct_lineage_same_physical_results_without_writes(pair):
    before = [file_hash(p) for p in pair]
    result = compare(*pair)
    assert result['status'] == 'passed' and result['distinctWorldLineageVerified']
    assert result['left']['projections']['observations']['rows'] == 15
    assert [file_hash(p) for p in pair] == before


@pytest.mark.parametrize('sql', [
    "UPDATE days SET temperature=temperature+1 WHERE day='2026-01-03'",
    "UPDATE truth SET quantity='999' WHERE day='2026-01-03'",
    "UPDATE observations SET quantity='999' WHERE day='2026-01-03'",
    "UPDATE assets SET condition='failed' WHERE commodity='gas'",
    "UPDATE observed_register_state SET value='999' WHERE device='gas'",
    "UPDATE observed_register_values SET value='999' WHERE observation IN "
    "(SELECT id FROM observations WHERE day='2026-01-03')",
])
def test_middle_day_or_final_state_divergence_is_not_masked(pair, sql):
    with sqlite3.connect(pair[1]) as db:
        db.execute(sql)
    before = [file_hash(p) for p in pair]
    with pytest.raises(ValueError, match='Physical replay differs'):
        compare(*pair)
    assert [file_hash(p) for p in pair] == before


def test_invalid_lineage_is_not_normalized_away(pair):
    with sqlite3.connect(pair[1]) as db:
        db.execute("UPDATE observations SET id='forged' WHERE id=(SELECT id FROM observations LIMIT 1)")
    with pytest.raises(ValueError, match='Observation lineage'):
        compare(*pair)


def test_missing_register_is_rejected_even_if_other_world_matches(pair):
    for path in pair:
        with sqlite3.connect(path) as db:
            db.execute('DELETE FROM observed_register_values WHERE observation=(SELECT id FROM observations LIMIT 1)')
    with pytest.raises(ValueError, match='Register records'):
        compare(*pair)


def test_one_file_cannot_be_its_own_replay(pair):
    with pytest.raises(ValueError, match='two separate'):
        compare(pair[0], pair[0])
