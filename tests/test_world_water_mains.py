import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import Decimal
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_world_hazards import command as hazard_command
from test_world_sewer import command as sewer_command
from test_world_v2 import snapshot
from test_world_water_faults import command as leak_command

from utilsim.world import World, hazards, sewer, water_faults
from utilsim.world import water_mains as wm
from utilsim.world.map_view import WorldMap
from utilsim.world.server import make_server


def source(loop=False):
    s = snapshot()
    edges = [('up', 's', 'a', 'supply'), ('main', 'a', 'b', 'distribution'),
             ('down', 'b', 'c', 'distribution'), ('service', 'b', 'm', 'service'),
             ('tie', 's', 'c', 'supply')]
    s['networks'] = {'water': {'sourceIds': ['s'], 'nodes': [{'id': n} for n in 'sabcm'],
                    'edges': [{'id': e, 'from': a, 'to': b, 'kind': kind, 'lengthM': 1000,
                               'material': 'cast iron', 'enabled': loop if e == 'tie' else True}
                              for e, a, b, kind in edges],
                    'equipment': [{'kind': 'valve', 'edgeId': e} for e in ('up', 'down', 'tie')]}}
    next(sp for sp in s['servicePoints'] if sp['commodity'] == 'water')['networkNodeId'] = 'm'
    return s


def world(tmp_path, name='world', loop=False, **settings):
    w = World(tmp_path/(name+'.sqlite'))
    w.initialize(source(loop), 'TEST', settings={'annual_meter_failure': 0, 'annual_meter_drift': 0, **settings})
    return w


def command(w, identity='break', action='start', **overrides):
    with w.db() as db:
        m = w.metadata(db)
    extras = {'configure': {'breaksPer100kmYear': 100000, 'lossM3PerHour': 10},
              'start': {'edgeId': 'main', 'lossM3PerHour': 10},
              **{a: {'edgeId': 'main', 'faultId': 'missing', 'workOrderId': 'WO1'} for a in wm.TRANSITIONS}}[action]
    return {'schemaVersion': wm.VERSION, 'commandId': identity, 'environmentId': m['environment'],
            'worldFingerprint': m['fingerprint'], 'actorId': 'world-admin', 'expectedRevision': 0,
            'effectiveDate': m['through'], 'action': action, 'reason': 'Physical scenario evidence',
            'causalReference': 'scenario', **extras, **overrides}


def transition(w, result, action, edge='main'):
    return wm.command(w, command(w, edge+'-'+action, action, edgeId=edge,
                                 expectedRevision=result['revision'], faultId=result['faultId']))


def test_complete_lifecycle_unbilled_loss_and_conservation(tmp_path):
    w, control = world(tmp_path), world(tmp_path, 'control')
    w.advance('2026-01-02')
    old, original = w.export_v2('2026-01-01', '2026-01-02'), WorldMap(w).snapshot()
    p = command(w)
    first = wm.command(w, p)
    w.advance('2026-01-03')
    control.advance('2026-01-03')
    assert w.export_v2('2026-01-01', '2026-01-03') == control.export_v2('2026-01-01', '2026-01-03')
    assert wm.inspect(w, 'main')['losses'][0]['loss_m3'] == '240.0000'
    water_faults.command(w, leak_command(w, 'leak', leakM3PerHour='1'))
    sewer.command(w, sewer_command(w, 'sewer-config', 'configure'))
    isolated = transition(w, first, 'isolate')
    w.advance('2026-01-04')
    view = wm.inspect(w, 'main')
    assert view['interruptedServices'] == view['affectedServiceCount'] == 1
    assert view['losses'][0]['loss_m3'] == '0.0000'
    with w.db() as db:
        assert db.execute("SELECT quantity FROM truth WHERE asset='water' AND day='2026-01-03'").fetchone()[0] == '0.0000'
        assert db.execute('SELECT leak_quantity FROM water_fault_effects').fetchone()[0] == '0.0000'
        assert Decimal(db.execute('SELECT inflow FROM sewer_flows').fetchone()[0]) == 0
        assert Decimal(db.execute('SELECT unserved_m3 FROM water_main_effects').fetchone()[0]) > 0
    repaired = transition(w, isolated, 'repair')
    w.advance('2026-01-05')
    assert wm.inspect(w)['interruptedServices'] == 1  # repair does not reopen valves
    transition(w, repaired, 'restore')
    w.advance('2026-01-06')
    assert wm.inspect(w)['interruptedServices'] == 0
    with w.db() as db:
        assert Decimal(db.execute("SELECT leak_quantity FROM water_fault_effects WHERE day='2026-01-05'").fetchone()[0]) == 24
        assert db.execute("SELECT COUNT(*) FROM water_main_effects").fetchone()[0] == 2
    assert wm.command(World(w.path), p) == first
    assert w.export_v2('2026-01-01', '2026-01-02') == old
    assert WorldMap(w).snapshot() == original
    assert WorldMap(w).premise('P1')['assets'][-1]['lastMainInterruption']['day'] == '2026-01-04'
    assert 'Physical scenario evidence' not in json.dumps(w.export_v2('2026-01-01', '2026-01-06'))


def test_loop_and_overlapping_isolation(tmp_path):
    w = world(tmp_path, loop=True)
    one = wm.command(w, command(w))
    two = wm.command(w, command(w, 'break2', edgeId='down'))
    one = transition(w, one, 'isolate')
    two = transition(w, two, 'isolate', 'down')
    assert wm.inspect(w)['interruptedServices'] == 1
    one = transition(w, one, 'repair')
    transition(w, one, 'restore')
    assert wm.inspect(w)['interruptedServices'] == 1
    two = transition(w, two, 'repair', 'down')
    transition(w, two, 'restore', 'down')
    assert wm.inspect(w)['interruptedServices'] == 0


def test_unbounded_section_rejected_without_mutation(tmp_path):
    w = World(tmp_path/'bad.sqlite')
    s = source()
    s['networks']['water']['equipment'] = []
    w.initialize(s, 'TEST')
    first = wm.command(w, command(w))
    with pytest.raises(ValueError, match='do not bound'):
        transition(w, first, 'isolate')
    assert wm.inspect(w, 'main')['selected']['revision'] == 1


@pytest.mark.parametrize('change', [dict(actorId='analyst'), dict(expectedRevision=1), dict(expectedRevision=True),
    dict(lossM3PerHour=float('nan')), dict(lossM3PerHour=0), dict(lossM3PerHour=True), dict(lossM3PerHour=10001),
    dict(worldFingerprint='other'), dict(effectiveDate='2025-01-01'), dict(edgeId='service'), dict(extra='unknown')])
def test_rejected_command_does_not_migrate(tmp_path, change):
    w = world(tmp_path)
    with pytest.raises(ValueError):
        wm.command(w, command(w, **change))
    with w.db() as db:
        assert not wm.enabled(db)
    assert not list(tmp_path.glob('*.bak'))


def test_backup_conflict_and_concurrent_retry(tmp_path):
    w = world(tmp_path)
    p = command(w)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda _: wm.command(w, p), range(2)))
    assert a == b
    with pytest.raises(ValueError, match='Conflicting'):
        wm.command(w, {**p, 'reason': 'different'})
    with pytest.raises(ValueError, match='lifecycle'):
        transition(w, a, 'restore')
    backups = list(tmp_path.glob('*.bak'))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as db:
        assert not db.execute("SELECT 1 FROM meta WHERE key='waterMainModelVersion'").fetchone()


def test_seeded_chunking_cold_lineage_and_pause(tmp_path):
    a, b = world(tmp_path, 'a', winter_mean_c=-20, summer_mean_c=-20), world(tmp_path, 'b', winter_mean_c=-20, summer_mean_c=-20)
    for w in (a, b):
        wm.command(w, command(w, 'policy', 'configure'))
        hazards.command(w, hazard_command(w))
    a.advance('2026-02-01')
    b.advance('2026-01-04')
    b = World(b.path)
    b.advance('2026-02-01')
    assert a.export_v2('2026-01-01', '2026-02-01') == b.export_v2('2026-01-01', '2026-02-01')
    with a.db() as da, b.db() as db:
        for table in ('water_main_faults', 'water_main_days', 'events'):
            assert [dict(r) for r in da.execute('SELECT * FROM '+table)] == [dict(r) for r in db.execute('SELECT * FROM '+table)]
        events = list(da.execute("SELECT payload FROM events WHERE type='PhysicalWaterMainBroken'"))
        assert events
        for e in events:
            evidence = json.loads(e[0])['evidence']
            assert evidence['hazardDay'] and evidence['multiplier'] > 1 and evidence['weightedKm'] == 2
    wm.command(a, command(a, 'pause', 'configure', expectedRevision=1, breaksPer100kmYear=0))
    a.advance('2026-02-02')
    assert wm.inspect(a, 'main')['selected']['active']


def test_isolation_preserves_missing_meter_and_sewer(tmp_path):
    w = world(tmp_path, annual_meter_failure=1)
    result = wm.command(w, command(w))
    transition(w, result, 'isolate')
    w.advance('2026-01-02')
    assert all(o['quantity'] is None for o in w.export_v2('2026-01-01', '2026-01-02')['observations'])


def test_day_failure_rolls_back_and_retries(tmp_path, monkeypatch):
    w = world(tmp_path)
    wm.command(w, command(w))
    original = sewer.flow
    def fail(*args):
        raise RuntimeError('interrupted day')
    monkeypatch.setattr(sewer, 'flow', fail)
    with pytest.raises(RuntimeError):
        w.advance('2026-01-02')
    with w.db() as db:
        assert db.execute('SELECT COUNT(*) FROM water_main_days').fetchone()[0] == 0
    monkeypatch.setattr(sewer, 'flow', original)
    w.advance('2026-01-02')
    assert len(wm.inspect(w, 'main')['losses']) == 1


def test_http_scope_and_contract(tmp_path):
    w = world(tmp_path)
    server = make_server(w, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base+'/water-mains') as response:
            assert 'Unbilled water losses' in response.read().decode()
        with urlopen(base+'/api/water-mains?edgeId=main') as response:
            assert json.load(response)['selected']['id'] == 'main'
        for path, headers in [('/api/water-mains?unexpected=x', {}), ('/api/water-mains', {'Host': 'evil.test'})]:
            with pytest.raises(HTTPError):
                urlopen(Request(base+path, headers=headers))
        p = json.dumps(command(w)).encode()
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base+'/api/water-mains', data=p, headers={'Content-Type': 'application/json', 'Origin': 'https://evil.test'}))
        assert error.value.code == 403
        with urlopen(Request(base+'/api/water-mains', data=p, headers={'Content-Type': 'application/json'})) as response:
            assert json.load(response)['status'] == 'completed'
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_read_only_pages_and_loss_history(tmp_path):
    w = world(tmp_path)
    page = wm.inspect(w, limit=1)
    assert len(page['edges']) == 1 and page['nextAfter']
    other = wm.inspect(w, after=page['nextAfter'], limit=1)
    assert other['edges'][0]['id'] != page['edges'][0]['id']
    assert not list(tmp_path.glob('*.bak'))
    with w.db() as db:
        assert not wm.enabled(db)
    first = wm.command(w, command(w))
    w.advance('2026-02-01')
    page = wm.inspect(w, 'main')
    assert len(page['losses']) == 25
    earlier = wm.inspect(w, 'main', before_day=page['nextDay'])
    assert len(earlier['losses']) == 6
    assert {r['day'] for r in page['losses']}.isdisjoint(r['day'] for r in earlier['losses'])
    first = transition(w, first, 'isolate')
    first = transition(w, first, 'repair')
    transition(w, first, 'restore')
    wm.command(w, command(w, 'new-break', expectedRevision=4))
    page = wm.inspect(w, 'main', limit=1)
    assert page['nextBefore']
    previous = wm.inspect(w, 'main', before=page['nextBefore'], limit=1)
    assert previous['history'][0]['status'] == 'restored'


def test_future_commissioning_and_stale_command(tmp_path):
    s = source()
    next(m for m in s['meters'] if m['id'] == 'water')['installedAt'] = '2026-01-03'
    w = World(tmp_path/'future.sqlite')
    w.initialize(s, 'TEST', settings={'annual_meter_failure': 0, 'annual_meter_drift': 0})
    result = wm.command(w, command(w))
    result = transition(w, result, 'isolate')
    assert wm.inspect(w)['interruptedServices'] == 0
    stale = command(w, 'stale-repair', 'repair', expectedRevision=2, faultId=result['faultId'])
    w.advance('2026-01-04')
    with pytest.raises(ValueError, match='date changed'):
        wm.command(w, stale)
    with w.db() as db:
        effects = list(db.execute('SELECT day FROM water_main_effects'))
        assert [r[0] for r in effects] == ['2026-01-03']
    assert wm.inspect(w)['interruptedServices'] == 1


def test_paused_policy_has_no_effect_on_prior_world(tmp_path):
    a, b = world(tmp_path, 'a'), world(tmp_path, 'b')
    wm.command(a, command(a, 'policy', 'configure', breaksPer100kmYear=0))
    a.advance('2026-02-01')
    b.advance('2026-02-01')
    assert a.export_v2('2026-01-01', '2026-02-01') == b.export_v2('2026-01-01', '2026-02-01')
    with a.db() as db:
        assert not db.execute('SELECT 1 FROM water_main_faults').fetchone()
