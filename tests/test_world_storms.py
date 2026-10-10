import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest
from test_world_hazards import command as hazard_command
from test_world_hazards import enable_faults, rows
from test_world_network_faults import world

from utilsim.world import World, hazards, storms


def command(w, identity='storm-1', **overrides):
    view = storms.inspect(w)
    return {'schemaVersion': storms.VERSION, 'commandId': identity, 'environmentId': view['environmentId'],
            'worldFingerprint': view['worldFingerprint'], 'actorId': 'world-admin',
            'expectedRevision': view['revision'], 'effectiveDate': view['through'], 'action': 'schedule',
            'reason': 'Explicit winter storm exercise', 'causalReference': 'scenario',
            'startDate': view['through'], 'endDate': '2026-01-04', 'temperatureOffsetC': -15,
            'multipliers': dict.fromkeys(storms.FAMILIES, 3), **overrides}


def cancel(w, storm_id='storm-1', identity='cancel-1'):
    p = command(w, identity)
    return {**{k: p[k] for k in storms.COMMON}, 'action': 'cancel', 'stormId': storm_id}


def test_absent_model_leaves_legacy_exactly_unchanged_and_inspection_is_readonly(tmp_path):
    a, b = world(tmp_path), world(tmp_path, 'b')
    prior = Path(a.path).read_bytes()
    assert not storms.inspect(a)['enabled']
    assert Path(a.path).read_bytes() == prior
    for w in (a, b):
        enable_faults(w, .5)
        w.advance('2026-01-10')
    for table in ('events', 'days', 'truth', 'observations', 'network_faults', 'water_faults', 'sewer_flows'):
        assert rows(a, table) == rows(b, table)
    with a.db() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='storm_days'").fetchone()


def test_shared_temperature_finite_dates_and_future_schedule_preserve_prior_history(tmp_path):
    a, b = world(tmp_path), world(tmp_path, 'b')
    for w in (a, b):
        w.advance('2026-01-02')
    old = a.export_v2('2026-01-01', '2026-01-02')
    result = storms.command(a, command(a, startDate='2026-01-03', endDate='2026-01-05'))
    for w in (a, b):
        w.advance('2026-01-07')
    actual, baseline = rows(a, 'days'), rows(b, 'days')
    for x, y in zip(actual, baseline, strict=True):
        assert x['temperature'] == (round(y['temperature']-15, 2) if '2026-01-03' <= x['day'] < '2026-01-05' else y['temperature'])
    history = storms.inspect(a)['history']
    assert [x['day'] for x in history] == ['2026-01-04', '2026-01-03']
    assert all(x['scheduleEventId'] == result['eventId'] for x in history)
    assert a.export_v2('2026-01-01', '2026-01-02') == old
    assert a.export('2026-01-05', '2026-01-07') == b.export('2026-01-05', '2026-01-07')
    # Storm risk does not silently activate any existing fault model.
    with a.db() as db:
        assert all(not x['enabled'] for x in hazards.base_policies(a.metadata(db)).values())
        assert not hazards.enabled(db)
        meta = a.metadata(db)
    with closing(sqlite3.connect(meta['stormRollbackBackup'])) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='storm_days'").fetchone()


def test_existing_fault_owners_use_storm_lineage_without_hazard_optin(tmp_path):
    w = world(tmp_path)
    enable_faults(w, 1)
    scheduled = storms.command(w, command(w, endDate='2026-01-02'))
    w.advance('2026-01-02')
    daily = storms.inspect(w)['history'][0]
    risk = next(r for r in rows(w, 'events') if r['type'] == 'InfrastructureHazardDay')
    payload = json.loads(risk['payload'])
    assert risk['cause'] == daily['eventId']
    assert payload['storm']['scheduleEventId'] == scheduled['eventId']
    assert set(payload['multipliers'].values()) == {3}
    for table in ('network_faults', 'water_faults', 'sewer_faults'):
        assert rows(w, table) and all(f['cause'] == risk['id'] for f in rows(w, table))
    counts = {t: len(rows(w, t)) for t in ('network_faults', 'water_faults', 'sewer_faults')}
    w.advance('2026-01-03')
    assert len(storms.inspect(w)['history']) == 1
    for t, count in counts.items():
        assert len(rows(w, t)) == count
    assert rows(w, 'water_faults')[0]['repaired_date'] is None


def test_composes_age_cold_and_storm_once_with_cap_and_zero_baseline(tmp_path):
    w = world(tmp_path, winter_mean_c=10, summer_mean_c=10, daily_weather_spread_c=0)
    enable_faults(w, .2)
    hazards.command(w, hazard_command(w))
    storms.command(w, command(w))
    w.advance('2026-01-02')
    day = hazards.inspect(w)['history'][0]
    assert day['temperatureC'] == -5
    assert day['multipliers']['water'] == 2*3*3
    assert day['dailyProbabilities']['water'] == pytest.approx(hazards.probability(.2, 18))
    w = world(tmp_path, 'cap')
    p = hazard_command(w)
    for profile in p['profiles'].values():
        profile.update(ageYears=10000, annualAgeIncrease=1, coldBelowC=60, coldMultiplier=100)
    hazards.command(w, p)
    storms.command(w, command(w, multipliers=dict.fromkeys(storms.FAMILIES, 100)))
    w.advance('2026-01-02')
    day = hazards.inspect(w)['history'][0]
    assert set(day['multipliers'].values()) == {10000}
    assert set(day['dailyProbabilities'].values()) == {0}


def test_paused_age_policy_still_allows_explicit_storm_and_adjacent_events(tmp_path):
    w = world(tmp_path)
    enable_faults(w, .2)
    hazards.command(w, hazard_command(w, active=False))
    storms.command(w, command(w, endDate='2026-01-02'))
    storms.command(w, command(w, 'adjacent', startDate='2026-01-02', endDate='2026-01-03',
                              multipliers=dict.fromkeys(storms.FAMILIES, 4)))
    w.advance('2026-01-04')
    days = hazards.inspect(w)['history']
    assert [h['multipliers']['electric'] for h in days] == [1, 4, 3]
    assert all(not h['policy']['active'] for h in days)


def test_water_mains_reuse_composite_water_risk_and_keep_causal_evidence(tmp_path):
    from test_world_water_mains import command as main_command
    from test_world_water_mains import world as main_world

    from utilsim.world import water_mains

    w = main_world(tmp_path)
    water_mains.command(w, main_command(w, 'main-policy', 'configure'))
    storms.command(w, command(w, multipliers={'electric': 1, 'gas': 1, 'water': 7, 'sewer': 1}))
    w.advance('2026-01-02')
    hazard = next(r for r in rows(w, 'events') if r['type'] == 'InfrastructureHazardDay')
    faults = [r for r in rows(w, 'events') if r['type'] == 'PhysicalWaterMainBroken']
    assert faults
    assert all(json.loads(r['payload'])['evidence']['multiplier'] == 7 for r in faults)
    assert all(json.loads(r['payload'])['evidence']['hazardDay'] == hazard['id'] for r in faults)
    assert 'Explicit winter storm exercise' not in json.dumps(w.export_v2('2026-01-01', '2026-01-02'))


def test_command_retry_concurrent_cancel_overlap_and_no_retrospective_edit(tmp_path):
    w = world(tmp_path)
    p = command(w, startDate='2026-01-02')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: storms.command(w, p), range(2)))
    assert results[0] == results[1]
    with pytest.raises(ValueError, match='Conflicting'):
        storms.command(w, {**p, 'reason': 'different'})
    with pytest.raises(ValueError, match='overlap'):
        storms.command(w, command(w, 'overlap'))
    c = cancel(w)
    cancelled = storms.command(w, c)
    assert storms.command(w, c) == cancelled
    with pytest.raises(ValueError, match='unstarted'):
        storms.command(w, cancel(w, identity='cancel-again'))
    new = command(w, 'replacement', startDate='2026-01-02')
    storms.command(w, new)
    old_schedule = deepcopy(storms.inspect(w)['events'][0])
    w.advance('2026-01-03')
    assert storms.command(w, p) == results[0]
    assert storms.inspect(w)['events'][0] == old_schedule
    with pytest.raises(ValueError, match='unstarted'):
        storms.command(w, cancel(w, 'replacement', 'too-late'))
    with pytest.raises(ValueError, match='already processed'):
        storms.command(w, command(w, 'past', startDate='2026-01-01'))


def test_atomic_day_rollback_restart_and_replay(tmp_path, monkeypatch):
    w, twin = world(tmp_path), world(tmp_path, 'twin')
    for v in (w, twin):
        enable_faults(v, .9)
        storms.command(v, command(v))
    original = w.event
    def fail(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[3] == 'InfrastructureHazardDay':
            raise OSError('interrupted')
        return result
    monkeypatch.setattr(w, 'event', fail)
    with pytest.raises(OSError):
        w.advance('2026-01-02')
    assert rows(w, 'storm_days') == rows(w, 'days') == []
    w = World(w.path)
    for v in (w, twin):
        v.advance('2026-01-06')
    for table in ('storm_days', 'events', 'days', 'truth', 'observations', 'network_faults', 'sewer_flows'):
        assert rows(w, table) == rows(twin, table)


def test_command_failure_rolls_back_schema_and_journal(tmp_path, monkeypatch):
    w = world(tmp_path)
    p = command(w)
    original = w.put
    def fail(db, key, value):
        original(db, key, value)
        if key == 'stormRevision':
            raise OSError('interrupted')
    monkeypatch.setattr(w, 'put', fail)
    with pytest.raises(OSError):
        storms.command(w, p)
    assert not storms.inspect(w)['enabled']
    with w.db() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='storm_days'").fetchone()
        assert not db.execute('SELECT 1 FROM commands').fetchone()


def test_bounded_history_pages_include_cancelled_same_date_schedules(tmp_path):
    w = world(tmp_path)
    for n in range(27):
        storms.command(w, command(w, f'storm-{n}', endDate='2026-02-01'))
        if n != 26:
            storms.command(w, cancel(w, f'storm-{n}', f'cancel-{n}'))
    first = storms.inspect(w)
    older = storms.inspect(w, events_before=first['nextEventsBefore'])
    assert len(first['events']) == 25 and len(older['events']) == 2
    assert len({s['stormId'] for s in first['events']+older['events']}) == 27
    w.advance('2026-02-01')
    first = storms.inspect(w)
    older = storms.inspect(w, before=first['nextBefore'])
    assert len(first['history']) == 25 and len(older['history']) == 6


@pytest.mark.parametrize('override', [
    {'expectedRevision': True}, {'expectedRevision': 2}, {'actorId': 'worker'}, {'environmentId': 'other'},
    {'worldFingerprint': 'other'}, {'effectiveDate': '2026-01-02'}, {'startDate': '2025-12-31'},
    {'endDate': '2026-01-01'}, {'endDate': '2027-01-01'}, {'startDate': '20260101'}, {'multipliers': {}},
    {'temperatureOffsetC': 41}, {'temperatureOffsetC': True}, {'temperatureOffsetC': float('nan')},
    {'temperatureOffsetC': 10**500}, {'reason': ''}, {'extra': 1}, {'action': 'repair'},
    {'multipliers': {'electric': 3, 'gas': 3, 'water': float('inf'), 'sewer': 3}},
])
def test_invalid_commands_leave_legacy_without_activation_or_backup(tmp_path, override):
    w = world(tmp_path)
    with pytest.raises(ValueError):
        storms.command(w, command(w, **override))
    assert not storms.inspect(w)['enabled']
    assert not list(tmp_path.glob('*.bak'))


@pytest.mark.parametrize('cursor', [True, '01', -1, [], '2026-01-01', '9'*100, '٠١'])
def test_invalid_history_cursors(tmp_path, cursor):
    with pytest.raises(ValueError):
        storms.inspect(world(tmp_path), events_before=cursor)


def test_uninitialized_world_has_clear_inspection_error(tmp_path):
    with pytest.raises(ValueError, match='Initialize a world first'):
        storms.inspect(World(tmp_path/'empty.sqlite'))
