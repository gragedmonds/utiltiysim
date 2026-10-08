import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_world_v2 import snapshot

from utilsim.world import World, delivery
from utilsim.world import network_faults as nf
from utilsim.world.map_view import WorldMap
from utilsim.world.server import make_server


def source(loop=False):
    s = snapshot()
    s['networks'] = {}
    for u in ('electric', 'gas'):
        edges = [('supply', 's', 'a'), ('branch', 'a', 'b'), ('service', 'b', 'm')]
        edges += [('tie', 's', 'b')]
        s['networks'][u] = {'sourceIds': ['s'], 'nodes': [{'id': n} for n in 'sabm'],
                           'edges': [{'id': e, 'from': a, 'to': b, 'kind': e,
                                      'enabled': loop if e == 'tie' else True} for e, a, b in edges]}
        next(sp for sp in s['servicePoints'] if sp['commodity'] == u)['networkNodeId'] = 'm'
    return s


def world(tmp_path, name='world', loop=False, **settings):
    w = World(tmp_path / (name + '.sqlite'))
    w.initialize(source(loop), 'TEST', settings={'annual_meter_failure': 0, 'annual_meter_drift': 0, **settings})
    return w


def command(w, identity='start-1', action='start', **overrides):
    with w.db() as db:
        meta = w.metadata(db)
    extra = {'configure': {'annualProbability': 1}, 'start': {'commodity': 'electric', 'edgeId': 'supply'},
             'restore': {'commodity': 'electric', 'edgeId': 'supply', 'faultId': 'missing', 'workOrderId': 'WO1'}}[action]
    return {'schemaVersion': nf.VERSION, 'commandId': identity, 'environmentId': 'TEST',
            'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin', 'expectedRevision': 0,
            'effectiveDate': meta['through'], 'action': action, 'reason': 'Hidden scenario evidence',
            'causalReference': 'scenario', **extra, **overrides}


@pytest.mark.parametrize('commodity', ['electric', 'gas'])
def test_supply_fault_repair_and_history(tmp_path, commodity):
    w, control = world(tmp_path), world(tmp_path, 'control')
    w.advance('2026-01-02')
    old = w.export_v2('2026-01-01', '2026-01-02')
    original = WorldMap(w).snapshot()
    p = command(w, commodity=commodity)
    fault = nf.command(w, p)
    w.advance('2026-01-04')
    control.advance('2026-01-06')
    baseline = control.export('2026-01-02', '2026-01-04')['observations']
    for observed, normal in zip(w.export('2026-01-02', '2026-01-04')['observations'], baseline, strict=True):
        assert observed['quantity'] == ('0.0000' if observed['commodity'] == commodity else normal['quantity'])
    with w.db() as db:
        effects = list(db.execute('SELECT * FROM network_fault_effects'))
        assert len(effects) == 2
        assert all(float(e['demand_quantity']) > 0 and e['unserved_quantity'] == e['demand_quantity'] for e in effects)
        assert all(json.loads(e['fault_ids']) == [fault['faultId']] for e in effects)
    restore = command(w, 'restore-1', 'restore', commodity=commodity, expectedRevision=1, faultId=fault['faultId'])
    result = nf.command(w, restore)
    w.advance('2026-01-06')
    assert w.export('2026-01-04', '2026-01-06') == control.export('2026-01-04', '2026-01-06')
    assert w.export_v2('2026-01-01', '2026-01-02') == old
    assert WorldMap(w).snapshot() == original
    assert nf.command(w, p) == fault
    assert nf.command(w, restore) == result
    assert nf.inspect(w, commodity, 'supply')['history'][0]['work_order'] == 'WO1'


def test_loops_multiple_faults_and_normally_open_ties(tmp_path):
    w = world(tmp_path, loop=True)
    one = nf.command(w, command(w))
    assert nf.inspect(w, edge='supply')['interruptedServices'] == 0
    two = nf.command(w, command(w, 'start-2', edgeId='tie'))
    assert nf.inspect(w)['interruptedServices'] == 1
    w.advance('2026-01-02')
    with w.db() as db:
        causes = json.loads(db.execute('SELECT fault_ids FROM network_fault_effects').fetchone()[0])
        assert causes == sorted([one['faultId'], two['faultId']])
    # Restoring either supply route restores service; the other fault remains open.
    nf.command(w, command(w, 'restore-1', 'restore', expectedRevision=1, faultId=one['faultId']))
    assert nf.inspect(w)['interruptedServices'] == 0
    assert nf.inspect(w, edge='tie')['selected']['active']['id'] == two['faultId']
    normal = world(tmp_path, 'normal')
    with pytest.raises(ValueError, match='normally enabled'):
        nf.command(normal, command(normal, edgeId='tie'))
    nf.command(normal, command(normal))
    assert nf.inspect(normal)['interruptedServices'] == 1


def test_partial_restoration_does_not_erase_second_serial_fault(tmp_path):
    w = world(tmp_path)
    a = nf.command(w, command(w))
    b = nf.command(w, command(w, 'start-2', edgeId='service'))
    nf.command(w, command(w, 'restore-1', 'restore', expectedRevision=1, faultId=a['faultId']))
    assert nf.inspect(w)['interruptedServices'] == 1
    w.advance('2026-01-02')
    with w.db() as db:
        assert json.loads(db.execute('SELECT fault_ids FROM network_fault_effects').fetchone()[0]) == [b['faultId']]


def test_failed_meter_and_replacement_preserve_hidden_fault(tmp_path):
    w = world(tmp_path, annual_meter_failure=1)
    fault = nf.command(w, command(w))
    delivery.configure(w, 'TEST', delay_seconds=21600)
    w.advance('2026-01-02')
    exported = w.export_v2('2026-01-01', '2026-01-02')
    assert all(o['quantity'] is None for o in exported['observations'])
    assert not any(word in json.dumps(exported) for word in ('fault', 'Hidden scenario', 'unserved'))
    with w.db() as db:
        messages = [json.loads(r[0]) for r in db.execute('SELECT envelope FROM observation_outbox')]
        assert messages[0]['availableAt'].endswith('T06:00:00Z')
        assert not any(word in json.dumps(messages) for word in ('fault', 'Hidden scenario', 'unserved'))
    w.replace_meter('replace-1', 'TEST', 'electric', 'new-electric', 'WO2', 'Meter replaced')
    assert nf.inspect(w, edge='supply')['selected']['active']['id'] == fault['faultId']
    assert next(a for a in WorldMap(w).premise('P1')['assets'] if a['commodity'] == 'electric')['true_quantity'] == '0.0000'


def test_seeded_restart_shared_handler_and_disable(tmp_path, monkeypatch):
    one, chunks = world(tmp_path, 'one'), world(tmp_path, 'chunks')
    sources = []
    original = nf._start
    def spy(*args):
        sources.append(args[5])
        return original(*args)
    monkeypatch.setattr(nf, '_start', spy)
    for w in (one, chunks):
        nf.command(w, command(w, 'policy-1', 'configure'))
    one.advance('2026-01-10')
    chunks.advance('2026-01-04')
    chunks = World(chunks.path)
    chunks.advance('2026-01-10')
    assert one.export_v2('2026-01-01', '2026-01-10') == chunks.export_v2('2026-01-01', '2026-01-10')
    assert nf.inspect(one, edge='supply')['history'] == nf.inspect(chunks, edge='supply')['history']
    nf.command(one, command(one, 'policy-2', 'configure', annualProbability=0, expectedRevision=1))
    assert nf.inspect(one)['interruptedServices'] == 2
    manual = world(tmp_path, 'manual')
    nf.command(manual, command(manual))
    assert sources.count('seeded') == 12 and sources.count('manual') == 1


def test_restore_retry_cannot_restore_later_recurrence(tmp_path):
    w = world(tmp_path)
    nf.command(w, command(w, 'policy-1', 'configure'))
    w.advance('2026-01-02')
    first = nf.inspect(w, edge='supply')['selected']['active']
    p = command(w, 'restore-1', 'restore', expectedRevision=1, faultId=first['id'])
    result = nf.command(w, p)
    w.advance('2026-01-03')
    assert nf.inspect(w, edge='supply')['selected']['active'] is None
    w.advance('2026-01-04')
    second = nf.inspect(w, edge='supply')['selected']['active']
    assert first['id'] != second['id']
    assert nf.command(w, p) == result
    with pytest.raises(ValueError, match='active fault'):
        nf.command(w, command(w, 'stale', 'restore', expectedRevision=3, faultId=first['id']))


def test_day_and_outbox_rollback_together(tmp_path, monkeypatch):
    w = world(tmp_path)
    nf.command(w, command(w, 'policy-1', 'configure'))
    delivery.configure(w, 'TEST')
    original = delivery.append_day
    def crash(*args):
        original(*args)
        raise RuntimeError('Crash after outbox write')
    with monkeypatch.context() as patch:
        patch.setattr(delivery, 'append_day', crash)
        with pytest.raises(RuntimeError):
            w.advance('2026-01-02')
    assert not nf.inspect(w, edge='supply')['history']
    assert w.status()['days'] == w.status()['observations'] == delivery.status(w)['pending'] == 0
    World(w.path).advance('2026-01-02')
    assert len(nf.inspect(w, edge='supply')['history']) == delivery.status(w)['pending'] == 1


def test_backup_inspection_and_first_command_rollback(tmp_path, monkeypatch):
    w = world(tmp_path)
    w.advance('2026-01-02')
    original = w.export_v2('2026-01-01', '2026-01-02')
    nf.inspect(w)
    with w.db() as db:
        assert not nf.enabled(db)
    with monkeypatch.context() as patch:
        patch.setattr(w, 'event', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('crash')))
        with pytest.raises(RuntimeError):
            nf.command(w, command(w))
    with w.db() as db:
        assert not nf.enabled(db)
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'network_%'").fetchall()
    nf.command(w, command(w))
    with w.db() as db:
        backup = w.metadata(db)['networkFaultRollbackBackup']
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert World(backup).export_v2('2026-01-01', '2026-01-02') == original


@pytest.mark.parametrize('override', [
    {'commodity': 'water'}, {'commodity': 'sewer'}, {'edgeId': 'unknown'}, {'edgeId': 'tie'},
    {'worldFingerprint': 'other'}, {'actorId': 'worker'}, {'expectedRevision': True}, {'expectedRevision': 1},
    {'reason': ''}, {'action': []}, {'unexpected': 1}, {'effectiveDate': '2026-01-02'},
])
def test_invalid_command_leaves_no_changes(tmp_path, override):
    w = world(tmp_path)
    with pytest.raises(ValueError):
        nf.command(w, {**command(w), **override})
    with w.db() as db:
        assert not nf.enabled(db)
        assert db.execute('SELECT count(*) FROM commands').fetchone()[0] == 0
    assert not list(tmp_path.glob('*.bak'))


def test_concurrent_retries_history_and_disabled_baseline(tmp_path):
    w = world(tmp_path)
    p = command(w)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: nf.command(w, p), range(2)))
    assert responses[0] == responses[1]
    with pytest.raises(ValueError, match='Conflicting'):
        nf.command(w, {**p, 'reason': 'Changed'})
    for i in range(26):
        current = nf.inspect(w, edge='supply')['selected']
        nf.command(w, command(w, f'restore-{i}', 'restore', expectedRevision=current['revision'], faultId=current['active']['id']))
        nf.command(w, command(w, f'start-{i+2}', expectedRevision=current['revision']+1))
    first = nf.inspect(w, edge='supply')
    second = nf.inspect(w, edge='supply', before=first['nextBefore'])
    assert len(first['history']) == 25 and len(second['history']) == 2
    assert len(nf.inspect(w, limit=2)['edges']) == 2
    assert len(nf.inspect(w, after=nf.inspect(w, limit=2)['nextAfter'])['edges']) == 2
    one, control = world(tmp_path, 'one'), world(tmp_path, 'control')
    nf.command(one, command(one, 'configure-1', 'configure', annualProbability=0))
    for item in (one, control):
        item.advance('2026-02-01')
    assert one.export_v2('2026-01-01', '2026-02-01') == control.export_v2('2026-01-01', '2026-02-01')


def test_incomplete_topology_rejected_without_migration(tmp_path):
    s = source()
    s['servicePoints'][0]['networkNodeId'] = 'missing'
    w = World(tmp_path / 'bad.sqlite')
    w.initialize(s, 'TEST')
    with pytest.raises(ValueError, match='connected network node'):
        nf.command(w, command(w))
    assert not list(tmp_path.glob('*.bak'))


def test_future_meter_has_no_current_impact_or_read_until_commissioned(tmp_path):
    s = source()
    s['meters'][0]['installedAt'] = '2026-01-03'
    w = World(tmp_path/'future.sqlite')
    w.initialize(s, 'TEST', settings={'annual_meter_failure': 0, 'annual_meter_drift': 0})
    nf.command(w, command(w))
    assert nf.inspect(w)['interruptedServices'] == 0
    w.advance('2026-01-03')
    with w.db() as db:
        assert not db.execute('SELECT 1 FROM network_fault_effects').fetchone()
    assert nf.inspect(w)['interruptedServices'] == 1
    w.advance('2026-01-04')
    with w.db() as db:
        assert [r[0] for r in db.execute('SELECT day FROM network_fault_effects')] == ['2026-01-03']


def test_all_supply_sources_and_service_impact_pagination(tmp_path):
    s = source()
    s['networks']['electric']['sourceIds'].append('b')
    w = World(tmp_path/'sources.sqlite')
    w.initialize(s, 'TEST')
    nf.command(w, command(w))
    assert nf.inspect(w)['interruptedServices'] == 0
    nf.command(w, command(w, 'last-route', edgeId='service'))
    view = nf.inspect(w, edge='service', limit=1)
    assert view['affectedServiceCount'] == 1 and view['affectedSample'][0]['asset'] == 'electric'
    assert nf.inspect(w, edge='service', service_after='electric')['affectedSample'] == []


def test_http_operation_and_guards(tmp_path):
    w = world(tmp_path)
    server = make_server(w, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base+'/network-faults') as r:
            assert b'Start physical interruption' in r.read()
        with urlopen(base+'/api/network-faults?edgeId=supply') as r:
            assert json.load(r)['additionalInterruptedServices'] == 1
        p = command(w)
        with urlopen(Request(base+'/api/network-faults', json.dumps(p).encode(), {'Content-Type': 'application/json'})) as r:
            assert json.load(r)['status'] == 'completed'
        for request, status in [(Request(base+'/api/network-faults', headers={'Host': 'foreign'}), 403),
                                (Request(base+'/api/network-faults?commodity=water'), 422),
                                (Request(base+'/api/network-faults?before=0'), 422),
                                (Request(base+'/api/network-faults', json.dumps(p).encode(),
                                         {'Content-Type': 'application/json', 'Origin': 'https://foreign'}), 403)]:
            with pytest.raises(HTTPError) as error:
                urlopen(request)
            assert error.value.code == status
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
