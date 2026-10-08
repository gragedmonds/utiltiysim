import json
import math
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_world_network_faults import command as network_command
from test_world_network_faults import world
from test_world_sewer import command as sewer_command
from test_world_water_faults import command as water_command

from utilsim.world import World, hazards, network_faults, sewer, water_faults
from utilsim.world.server import make_server


def command(w, identity='hazards-1', **overrides):
    view = hazards.inspect(w)
    return {'schemaVersion': hazards.VERSION, 'commandId': identity, 'environmentId': view['environmentId'],
            'worldFingerprint': view['worldFingerprint'], 'actorId': 'world-admin', 'expectedRevision': view['policy']['revision'],
            'effectiveDate': view['through'], 'action': 'configure', 'reason': 'Explicit illustrative cohort scenario',
            'causalReference': 'scenario', 'active': True,
            'profiles': {f: {'ageYears': 20, 'annualAgeIncrease': .05, 'coldBelowC': 5, 'coldMultiplier': 3}
                         for f in hazards.FAMILIES}, **overrides}


def enable_faults(w, annual=.2):
    network_faults.command(w, network_command(w, 'net-policy', 'configure', annualProbability=annual))
    water_faults.command(w, water_command(w, 'water-policy', 'configure', annualProbability=annual))
    sewer.command(w, sewer_command(w, 'sewer-policy', 'configure', annualProbability=annual))


def rows(w, table):
    with w.db() as db:
        return [dict(r) for r in db.execute('SELECT * FROM '+table)]


def test_inspection_is_read_only_and_legacy_results_are_identical(tmp_path):
    w, twin = world(tmp_path), world(tmp_path, 'twin')
    for v in (w, twin):
        enable_faults(v, .9)
    view = hazards.inspect(w)
    assert not view['enabled'] and all(p['enabled'] for p in view['basePolicies'].values())
    assert hazards.probability(.9) == 1-(1-.9)**(1/365.2425)
    w.advance('2026-02-01')
    twin.advance('2026-02-01')
    for table in ('events', 'observations', 'truth', 'network_faults', 'water_faults', 'sewer_flows'):
        assert rows(w, table) == rows(twin, table)
    with w.db() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='hazard_days'").fetchone()


def test_daily_age_cold_survival_probability_and_source_lineage(tmp_path):
    w = world(tmp_path, winter_mean_c=-10, summer_mean_c=-10, daily_weather_spread_c=0)
    enable_faults(w, .2)
    p = command(w)
    result = hazards.command(w, p)
    w.advance('2026-01-03')
    v = hazards.inspect(w)
    day = v['history'][0]
    age = 20+1/365.2425
    assert day['temperatureC'] == -10
    assert day['ageYears']['water'] == age
    assert day['multipliers']['water'] == (1+age*.05)*3
    assert day['dailyProbabilities']['water'] == pytest.approx(1-.8**(day['multipliers']['water']/365.2425))
    assert day['policy']['cause'] == result['eventId']
    assert day['basePolicies']['water']['cause'] and day['basePolicies']['sewer']['enabled']
    with w.db() as db:
        meta = w.metadata(db)
        backup = meta['hazardRollbackBackup']
    with closing(sqlite3.connect(backup)) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='hazard_days'").fetchone()


def test_seeded_faults_all_retain_shared_day_cause_and_persist_after_pause(tmp_path):
    w = world(tmp_path)
    enable_faults(w, 1)
    hazards.command(w, command(w))
    w.advance('2026-01-02')
    day = hazards.inspect(w)['history'][0]
    for table in ('network_faults', 'water_faults', 'sewer_faults'):
        assert rows(w, table) and all(f['cause'] == day['eventId'] for f in rows(w, table))
    old = w.export_v2('2026-01-01', '2026-01-02')
    hazards.command(w, command(w, 'pause', active=False))
    w.advance('2026-01-03')
    assert set(hazards.inspect(w)['history'][0]['multipliers'].values()) == {1}
    assert len(rows(w, 'network_faults')) == 6
    assert rows(w, 'water_faults')[0]['repaired_date'] is None
    assert rows(w, 'sewer_faults')[0]['cleared_date'] is None
    assert w.export_v2('2026-01-01', '2026-01-02') == old


def test_repair_and_meter_replacement_do_not_reset_infrastructure_age(tmp_path):
    w = world(tmp_path)
    enable_faults(w, 1)
    hazards.command(w, command(w))
    w.advance('2026-01-02')
    f = rows(w, 'network_faults')[0]
    network_faults.command(w, network_command(w, 'restore', 'restore', commodity=f['commodity'], edgeId=f['edge'],
                                            expectedRevision=1, faultId=f['id']))
    w.replace_meter('replace', 'TEST', 'water', 'new-water-device', 'WO', 'Physical replacement')
    w.advance('2026-01-03')
    assert hazards.inspect(w)['history'][0]['ageYears']['water'] > 20
    assert len([x for x in rows(w, 'network_faults') if x['edge'] == f['edge'] and x['commodity'] == f['commodity']]) == 1


def test_restart_atomic_day_and_command_retry(tmp_path, monkeypatch):
    w, twin = world(tmp_path), world(tmp_path, 'twin')
    for v in (w, twin):
        enable_faults(v, .8)
        hazards.command(v, command(v))
    p = command(w, 'next', active=False)
    original = w.event
    def fail(*args, **kwargs):
        value = original(*args, **kwargs)
        if args[3] == 'InfrastructureHazardDay':
            raise OSError('interrupted day')
        return value
    monkeypatch.setattr(w, 'event', fail)
    with pytest.raises(OSError):
        w.advance('2026-01-03')
    assert rows(w, 'days') == rows(w, 'hazard_days') == []
    w = World(w.path)
    w.advance('2026-02-01')
    twin.advance('2026-02-01')
    for table in ('events', 'hazard_days', 'observations', 'sewer_flows'):
        assert rows(w, table) == rows(twin, table)
    with pytest.raises(ValueError, match='date or policy'):
        hazards.command(w, p)
    retry = command(w, 'pause', active=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: hazards.command(w, retry), range(2)))
    assert results[0] == results[1]
    w.advance('2026-02-02')
    assert hazards.command(w, retry) == results[0]
    with pytest.raises(ValueError, match='Conflicting'):
        hazards.command(w, {**retry, 'reason': 'changed'})
    page = hazards.inspect(w)
    older = hazards.inspect(w, before=page['nextBefore'])
    assert len(page['history']) == 25 and len(older['history']) == 7
    assert page['policy'] == older['policy']


def test_config_failure_rolls_back_schema_and_journal(tmp_path, monkeypatch):
    w = world(tmp_path)
    original = w.put
    def fail(db, key, value):
        original(db, key, value)
        if key == 'hazardPolicy':
            raise OSError('lost process')
    monkeypatch.setattr(w, 'put', fail)
    with pytest.raises(OSError):
        hazards.command(w, command(w))
    with w.db() as db:
        assert not hazards.enabled(db)
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='hazard_days'").fetchone()
        assert not db.execute('SELECT 1 FROM commands').fetchone()


@pytest.mark.parametrize('override', [
    {'active': 1}, {'expectedRevision': True}, {'expectedRevision': 4}, {'actorId': 'worker'},
    {'worldFingerprint': 'other'}, {'effectiveDate': '2020-01-01'}, {'profiles': {}}, {'profiles': []},
    {'reason': ''}, {'action': 'repair'}, {'extra': 1}, {'environmentId': 'other'}])
def test_invalid_command_preserves_old_world(tmp_path, override):
    w = world(tmp_path)
    with pytest.raises(ValueError):
        hazards.command(w, {**command(w), **override})
    assert not hazards.inspect(w)['enabled']
    assert not list(tmp_path.glob('*.bak'))


@pytest.mark.parametrize('field,value', [('ageYears', -1), ('coldMultiplier', 0), ('coldBelowC', 100),
                                         ('annualAgeIncrease', float('nan')), ('ageYears', True), ('ageYears', '10'), ('ageYears', 10**500)])
def test_invalid_profiles_fail_before_migration(tmp_path, field, value):
    w = world(tmp_path)
    p = command(w)
    p['profiles']['water'][field] = value
    with pytest.raises(ValueError):
        hazards.command(w, p)
    assert not hazards.inspect(w)['enabled']


def test_age_and_cold_increase_explainable_risk_without_forcing_faults(tmp_path):
    w, control = world(tmp_path, winter_mean_c=-10, summer_mean_c=-10, daily_weather_spread_c=0), world(tmp_path, 'control', winter_mean_c=-10, summer_mean_c=-10, daily_weather_spread_c=0)
    for v in (w, control):
        enable_faults(v, .5)
    p = command(w)
    for profile in p['profiles'].values():
        profile.update(ageYears=100, annualAgeIncrease=1, coldMultiplier=100)
    hazards.command(w, p)
    w.advance('2026-01-04')
    control.advance('2026-01-04')
    assert sum(len(rows(w, t)) for t in ('network_faults', 'water_faults', 'sewer_faults')) > sum(
        len(rows(control, t)) for t in ('network_faults', 'water_faults', 'sewer_faults'))
    assert hazards.probability(0, 10000) == 0
    assert hazards.probability(1, 10000) == 1
    assert math.isfinite(hazards.probability(.999, 10000))
    assert max(hazards.inspect(w)['history'][0]['multipliers'].values()) <= 10000


def test_profile_edits_do_not_change_historical_policy_or_enable_fault_models(tmp_path):
    w = world(tmp_path)
    p = command(w)
    hazards.command(w, p)
    w.advance('2026-01-02')
    old = deepcopy(hazards.inspect(w)['history'][0])
    next_p = command(w, 'change')
    next_p['profiles']['gas']['ageYears'] = 50
    hazards.command(w, next_p)
    w.advance('2026-01-03')
    v = hazards.inspect(w)
    assert v['history'][1] == old
    assert v['history'][0]['ageYears']['gas'] == 50
    assert all(not x['enabled'] for x in v['basePolicies'].values())
    assert not any(v['history'][0]['dailyProbabilities'].values())
    with pytest.raises(ValueError):
        hazards.inspect(w, before='not-a-date')


def test_http_actions_and_loopback_guards(tmp_path):
    w = world(tmp_path)
    server = make_server(w, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        assert b'Aging infrastructure' in urlopen(base+'/hazards').read()
        p = command(w)
        with urlopen(Request(base+'/api/hazards', json.dumps(p).encode(), {'Content-Type': 'application/json'})) as r:
            assert json.load(r)['status'] == 'completed'
        for request, code in [(Request(base+'/api/hazards?before='), 422),
                              (Request(base+'/api/hazards?before=2026-01-01&before=2026-01-02'), 422),
                              (Request(base+'/api/hazards', headers={'Host': 'foreign'}), 403),
                              (Request(base+'/api/hazards', json.dumps(p).encode(),
                                       {'Content-Type': 'application/json', 'Origin': 'https://foreign'}), 403)]:
            with pytest.raises(HTTPError) as error:
                urlopen(request)
            assert error.value.code == code
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_warm_days_remove_cold_effect_without_removing_age(tmp_path):
    w = world(tmp_path, winter_mean_c=20, summer_mean_c=20, daily_weather_spread_c=0)
    enable_faults(w)
    hazards.command(w, command(w))
    w.advance('2026-01-02')
    h = hazards.inspect(w)['history'][0]
    assert set(h['multipliers'].values()) == {2}
    assert h['temperatureC'] == 20
    assert hazards.age({'ageYears': 15}, '2024-01-01', '2029-01-01') == pytest.approx(15+1827/365.2425)
