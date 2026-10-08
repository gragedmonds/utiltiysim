import pytest
from test_world_occupancy import schedule
from test_world_v2 import world

from utilsim.world import occupancy


def test_internal_schedule_participates_in_outer_transaction(tmp_path):
    w = world(tmp_path)
    payload = schedule(w)
    with pytest.raises(RuntimeError, match='development day failed'):
        with w.db() as db:
            occupancy.command_in_transaction(w, db, payload)
            raise RuntimeError('development day failed')
    assert occupancy.inspect(w, 'P1')['changes'] == []
    with w.db() as db:
        result = occupancy.command_in_transaction(w, db, payload)
    assert occupancy.command(w, payload) == result
    w.advance('2026-01-04')
    assert occupancy.inspect(w, 'P1')['current']['occupied'] is False


def test_internal_development_context_requires_a_reserved_plan(tmp_path):
    w = world(tmp_path)
    payload = schedule(w)
    with pytest.raises(ValueError, match='No development reservation'):
        with w.db() as db:
            occupancy.command_in_transaction(w, db, payload, development_context='invented')
    assert occupancy.inspect(w, 'P1')['changes'] == []
    with pytest.raises(ValueError, match='contract'):
        occupancy.command(w, {**payload, 'development_context': 'invented'})
