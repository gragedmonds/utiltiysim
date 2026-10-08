import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import Decimal
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_world_v2 import snapshot, world

from utilsim.world import World, delivery, sewer, water_faults
from utilsim.world.map_view import WorldMap
from utilsim.world.server import make_server


def command(w, identity='start-1', action='start', **overrides):
    view = sewer.inspect(w, 'water')
    extra = {'configure': {'annualProbability': 0, 'returnFactor': '0.9', 'storageM3': '0.25', 'blockedCapacityM3PerDay': '0'},
             'start': {'waterAssetId': 'water', 'servicePointId': view['service']['id'], 'capacityM3PerDay': '0'},
             'clear': {'waterAssetId': 'water', 'servicePointId': view['service']['id'], 'faultId': 'missing', 'workOrderId': 'WO1'}}[action]
    return {'schemaVersion': sewer.VERSION, 'commandId': identity, 'environmentId': view['environmentId'],
            'worldFingerprint': view['worldFingerprint'], 'actorId': 'world-admin', 'expectedRevision': 0,
            'effectiveDate': view['through'], 'action': action, 'reason': 'Hidden physical scenario',
            'causalReference': 'scenario', **extra, **overrides}


def assert_balance(rows):
    for f in rows:
        assert Decimal(f['previous_retained'])+Decimal(f['inflow']) == sum(
            Decimal(f[k]) for k in ('transported', 'retained', 'overflow'))
        assert all(Decimal(f[k]) >= 0 for k in ('inflow', 'transported', 'retained', 'overflow'))


def test_blockage_storage_overflow_clearance_and_derived_billing(tmp_path):
    w = world(tmp_path, annual_meter_failure=0, annual_meter_drift=0)
    control = world(tmp_path, 'control', annual_meter_failure=0, annual_meter_drift=0)
    w.advance('2026-01-02')
    old = w.export_v2('2026-01-01', '2026-01-02')
    source = WorldMap(w).snapshot()
    p = command(w)
    first = sewer.command(w, p)
    w.advance('2026-01-05')
    view = sewer.inspect(w, 'water')
    assert len(view['flows']) == 3 and Decimal(view['current']['retained']) == Decimal('0.25')
    assert all(Decimal(f['overflow']) > 0 and Decimal(f['transported']) == 0 for f in view['flows'])
    assert all(f['fault_id'] == first['faultId'] for f in view['flows'])
    assert_balance(view['flows'])
    clear = command(w, 'clear-1', 'clear', expectedRevision=1, faultId=first['faultId'])
    cleared = sewer.command(w, clear)
    assert Decimal(sewer.inspect(w, 'water')['current']['retained']) == Decimal('0.25')
    w.advance('2026-01-06')
    after = sewer.inspect(w, 'water')['flows'][0]
    assert Decimal(after['transported']) == Decimal(after['inflow'])+Decimal('0.25')
    assert Decimal(after['retained']) == Decimal(after['overflow']) == 0
    assert after['previous_day'] == '2026-01-04' and after['fault_id'] is None
    assert_balance([after])
    control.advance('2026-01-06')
    assert w.export_v2('2026-01-01', '2026-01-06') == control.export_v2('2026-01-01', '2026-01-06')
    assert w.export_v2('2026-01-01', '2026-01-02') == old
    assert WorldMap(w).snapshot() == source
    assert sewer.command(w, p) == first and sewer.command(w, clear) == cleared
    exported = next(a for a in w.export_v2('2026-01-01', '2026-01-06')['assets'] if a['commodity'] == 'sewer')
    assert exported['servicePointId'] == view['service']['id']
    assert exported['meterId'] is None
    with w.db() as db:
        assert not db.execute("SELECT 1 FROM assets WHERE commodity='sewer'").fetchone()


def test_partial_capacity_policy_change_and_leak_exclusion(tmp_path):
    from test_world_water_faults import command as leak_command
    w = world(tmp_path, annual_meter_failure=0, annual_meter_drift=0)
    water_faults.command(w, leak_command(w, 'leak-1', leakM3PerHour='0.5'))
    sewer.command(w, command(w, capacityM3PerDay='0.1'))
    w.advance('2026-01-02')
    first = sewer.inspect(w, 'water')['flows'][0]
    assert Decimal(first['excluded_leak']) == 12
    assert Decimal(first['inflow']) == ((Decimal(first['water_quantity'])-12)*Decimal('0.9')).quantize(Decimal('0.0001'))
    assert Decimal(first['transported']) == Decimal('0.1')
    assert_balance([first])
    # A smaller storage policy cannot erase held wastewater; it overflows next day.
    sewer.command(w, command(w, 'policy-1', 'configure', storageM3='0', returnFactor='0', blockedCapacityM3PerDay='99'))
    w.advance('2026-01-03')
    next_day = sewer.inspect(w, 'water')['flows'][0]
    assert Decimal(next_day['inflow']) == Decimal(next_day['retained']) == 0
    assert Decimal(next_day['transported']) == min(Decimal(first['retained']), Decimal('0.1'))
    assert next_day['policy_event'] is not None
    assert_balance([next_day])
    assert sewer.inspect(w, 'water')['current']['active']['capacity'] == '0.1'


def test_meter_failure_replacement_and_delayed_export_do_not_reveal_fault(tmp_path):
    w = world(tmp_path, annual_meter_failure=1, annual_meter_drift=0)
    fault = sewer.command(w, command(w))
    delivery.configure(w, 'TEST', delay_seconds=21600)
    w.advance('2026-01-03')
    exported = w.export_v2('2026-01-01', '2026-01-03')
    assert all(o['quantity'] is None and o['registerValue'] is None for o in exported['observations'])
    assert not any(s in json.dumps(exported) for s in ('blockage', 'overflow', 'Hidden physical', fault['faultId']))
    with w.db() as db:
        messages = [json.loads(r[0]) for r in db.execute('SELECT envelope FROM observation_outbox')]
    assert len(messages) == 2 and all(m['availableAt'].endswith('T06:00:00Z') for m in messages)
    assert not any(s in json.dumps(messages) for s in ('overflow', 'Hidden physical', fault['faultId']))
    w.replace_meter('meter-1', 'TEST', 'water', 'new-water', 'WO2', 'Replace failed device')
    current = sewer.inspect(w, 'water')
    assert current['current']['active']['id'] == fault['faultId']
    assert Decimal(current['flows'][0]['overflow']) > 0
    assert next(a for a in WorldMap(w).premise('P1')['assets'] if a['commodity'] == 'water')['sewer']['service']['id'] == current['service']['id']


def test_seeded_shared_handler_restart_disable_and_recurrence(tmp_path, monkeypatch):
    one, chunks = world(tmp_path, 'one'), world(tmp_path, 'chunks')
    sources = []
    original = sewer._start
    def spy(*args):
        sources.append(args[5])
        return original(*args)
    monkeypatch.setattr(sewer, '_start', spy)
    for w in (one, chunks):
        sewer.command(w, command(w, 'policy-1', 'configure', annualProbability=1))
    one.advance('2026-01-10')
    chunks.advance('2026-01-04')
    chunks = World(chunks.path)
    chunks.advance('2026-01-10')
    assert sewer.inspect(one, 'water')['flows'] == sewer.inspect(chunks, 'water')['flows']
    assert one.export_v2('2026-01-01', '2026-01-10') == chunks.export_v2('2026-01-01', '2026-01-10')
    first = sewer.inspect(one, 'water')['current']['active']
    p = command(one, 'clear-1', 'clear', expectedRevision=1, faultId=first['id'])
    result = sewer.command(one, p)
    one.advance('2026-01-11')
    assert sewer.inspect(one, 'water')['current']['active'] is None
    one.advance('2026-01-12')
    second = sewer.inspect(one, 'water')['current']['active']
    assert second['id'] != first['id']
    assert sewer.command(one, p) == result
    with pytest.raises(ValueError, match='active fault'):
        sewer.command(one, command(one, 'stale', 'clear', expectedRevision=3, faultId=first['id']))
    sewer.command(one, command(one, 'policy-2', 'configure', expectedRevision=1, annualProbability=0))
    one.advance('2026-01-14')
    assert sewer.inspect(one, 'water')['current']['active']['id'] == second['id']
    manual = world(tmp_path, 'manual')
    sewer.command(manual, command(manual))
    assert sources == ['seeded', 'seeded', 'seeded', 'manual']


def test_day_storage_fault_outbox_rollback(tmp_path, monkeypatch):
    w = world(tmp_path)
    sewer.command(w, command(w, 'policy-1', 'configure', annualProbability=1))
    delivery.configure(w, 'TEST')
    original = delivery.append_day
    def crash(*args):
        original(*args)
        raise RuntimeError('Interrupted day')
    with monkeypatch.context() as patch:
        patch.setattr(delivery, 'append_day', crash)
        with pytest.raises(RuntimeError):
            w.advance('2026-01-02')
    view = sewer.inspect(w, 'water')
    assert not view['flows'] and not view['history'] and Decimal(view['current']['retained']) == 0
    assert w.status()['days'] == w.status()['observations'] == delivery.status(w)['pending'] == 0
    World(w.path).advance('2026-01-02')
    assert len(sewer.inspect(w, 'water')['flows']) == delivery.status(w)['pending'] == 1


def test_backup_read_only_inspection_and_first_command_rollback(tmp_path, monkeypatch):
    w = world(tmp_path)
    w.advance('2026-01-02')
    old = w.export_v2('2026-01-01', '2026-01-02')
    assert sewer.inspect(w, 'water')['enabled'] is False
    with w.db() as db:
        assert not sewer.enabled(db)
    with monkeypatch.context() as patch:
        patch.setattr(w, 'event', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('crash')))
        with pytest.raises(RuntimeError):
            sewer.command(w, command(w))
    with w.db() as db:
        assert not sewer.enabled(db)
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'sewer_%'").fetchall()
    sewer.command(w, command(w))
    with w.db() as db:
        backup = w.metadata(db)['sewerRollbackBackup']
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert World(backup).export_v2('2026-01-01', '2026-01-02') == old


@pytest.mark.parametrize('override', [{'annualProbability': True}, {'annualProbability': -1},
    {'annualProbability': float('inf')}, {'returnFactor': '1.01'}, {'storageM3': '-1'},
    {'blockedCapacityM3PerDay': 'NaN'}])
def test_invalid_policy_preserves_legacy_world(tmp_path, override):
    w = world(tmp_path)
    with pytest.raises(ValueError):
        sewer.command(w, command(w, 'policy-1', 'configure', **override))
    assert sewer.inspect(w, 'water')['enabled'] is False
    assert not list(tmp_path.glob('*.bak'))


def test_zero_exponent_is_canonical_and_bounded(tmp_path):
    w = world(tmp_path)
    sewer.command(w, command(w, capacityM3PerDay='0e-999999'))
    assert sewer.inspect(w, 'water')['current']['active']['capacity'] == '0'


def test_four_domain_faults_and_independent_physical_recovery(tmp_path):
    from test_world_network_faults import command as network_command
    from test_world_network_faults import world as network_world
    from test_world_water_faults import command as leak_command

    from utilsim.world import network_faults
    w = network_world(tmp_path)
    electric = network_faults.command(w, network_command(w, 'electric-outage'))
    gas = network_faults.command(w, network_command(w, 'gas-outage', commodity='gas'))
    leak = water_faults.command(w, leak_command(w, 'water-leak', leakM3PerHour='0.5'))
    blocked = sewer.command(w, command(w, 'sewer-block'))
    delivery.configure(w, 'TEST')
    w.advance('2026-01-03')
    exported = w.export_v2('2026-01-01', '2026-01-03')
    readings = exported['observations']
    assert {o['commodity'] for o in readings} == {'electric', 'gas', 'water', 'sewer'}
    assert all(Decimal(o['quantity']) == 0 for o in readings if o['commodity'] in ('electric', 'gas'))
    assert all(Decimal(o['quantity']) > 12 for o in readings if o['commodity'] == 'water')
    for derived in (o for o in readings if o['commodity'] == 'sewer'):
        source = next(o for o in readings if o['sourceId'] == derived['sourceObservationIds'][0])
        assert Decimal(derived['quantity']) == Decimal(source['quantity'])*Decimal('0.9')
        assert derived['meterId'] is None
    first = sewer.inspect(w, 'water')
    assert all(Decimal(f['inflow']) < 1 and Decimal(f['overflow']) > 0 for f in first['flows'])
    w = World(w.path)
    network_faults.command(w, network_command(w, 'gas-restore', 'restore', commodity='gas',
                                             expectedRevision=1, faultId=gas['faultId']))
    water_faults.command(w, leak_command(w, 'water-repair', 'repair', expectedRevision=1, faultId=leak['faultId']))
    w.advance('2026-01-04')
    next_reads = w.export_v2('2026-01-03', '2026-01-04')['observations']
    assert next(o['quantity'] for o in next_reads if o['commodity'] == 'electric') == '0.0000'
    assert Decimal(next(o['quantity'] for o in next_reads if o['commodity'] == 'gas')) > 0
    assert Decimal(next(o['quantity'] for o in next_reads if o['commodity'] == 'water')) < 1
    assert sewer.inspect(w, 'water')['current']['active']['id'] == blocked['faultId']
    sewer.command(w, command(w, 'sewer-clear', 'clear', expectedRevision=1, faultId=blocked['faultId']))
    w.advance('2026-01-05')
    latest = sewer.inspect(w, 'water')['flows'][0]
    assert Decimal(latest['retained']) == Decimal(latest['overflow']) == 0
    assert_balance([latest])
    assert network_faults.inspect(w, edge='supply')['selected']['active']['id'] == electric['faultId']
    assert delivery.status(w)['pending'] == 4
    assert w.export_v2('2026-01-01', '2026-01-03') == exported


@pytest.mark.parametrize('override', [
    {'waterAssetId': 'electric'}, {'servicePointId': 'foreign'}, {'worldFingerprint': 'other'}, {'actorId': 'worker'},
    {'expectedRevision': True}, {'expectedRevision': 1}, {'capacityM3PerDay': '-1'}, {'capacityM3PerDay': 'NaN'},
    {'capacityM3PerDay': '0.00001'}, {'capacityM3PerDay': '10001'}, {'capacityM3PerDay': 1},
    {'reason': ''}, {'action': []}, {'unexpected': 1}, {'effectiveDate': '2026-01-02'},
])
def test_invalid_command_cannot_enable_or_modify_world(tmp_path, override):
    w = world(tmp_path)
    with pytest.raises(ValueError):
        sewer.command(w, {**command(w), **override})
    with w.db() as db:
        assert not sewer.enabled(db)
        assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0] == 0
    assert not list(tmp_path.glob('*.bak'))


def test_concurrent_retries_paged_faults_and_daily_history(tmp_path):
    w = world(tmp_path)
    p = command(w)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sewer.command(w, p), range(2)))
    assert results[0] == results[1]
    with pytest.raises(ValueError, match='Conflicting'):
        sewer.command(w, {**p, 'capacityM3PerDay': '0.1'})
    for i in range(26):
        current = sewer.inspect(w, 'water')['current']
        sewer.command(w, command(w, f'clear-{i}', 'clear', expectedRevision=current['revision'], faultId=current['active']['id']))
        sewer.command(w, command(w, f'start-{i+2}', expectedRevision=current['revision']+1))
    first = sewer.inspect(w, 'water')
    second = sewer.inspect(w, 'water', before=first['nextBefore'])
    assert len(first['history']) == 25 and len(second['history']) == 2
    w.advance('2026-02-01')
    first = sewer.inspect(w, 'water')
    second = sewer.inspect(w, 'water', before_day=first['nextDay'])
    assert len(first['flows']) == 25 and len(second['flows']) == 6
    assert_balance(first['flows']+second['flows'])


def test_future_commissioning(tmp_path):
    source = snapshot()
    source['meters'][-1]['installedAt'] = '2026-01-03'
    w = World(tmp_path/'future.sqlite')
    w.initialize(source, 'TEST')
    with pytest.raises(ValueError, match='commissioning'):
        sewer.command(w, command(w))
    sewer.command(w, command(w, 'policy-1', 'configure', annualProbability=1))
    w.advance('2026-01-03')
    assert sewer.inspect(w, 'water')['history'] == sewer.inspect(w, 'water')['flows'] == []
    w.advance('2026-01-04')
    assert sewer.inspect(w, 'water')['flows'][0]['day'] == '2026-01-03'


def test_http_commands_and_local_guards(tmp_path):
    w = world(tmp_path)
    server = make_server(w, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base+'/sewer') as response:
            assert b'Start physical blockage' in response.read()
        with urlopen(base+'/api/sewer?waterAssetId=water') as response:
            assert json.load(response)['view'] == 'administrator-truth'
        p = command(w)
        with urlopen(Request(base+'/api/sewer', json.dumps(p).encode(), {'Content-Type': 'application/json'})) as response:
            assert json.load(response)['status'] == 'completed'
        for req, status in [(Request(base+'/api/sewer?waterAssetId=water', headers={'Host': 'foreign'}), 403),
                            (Request(base+'/api/sewer?waterAssetId=water&before=0'), 422),
                            (Request(base+'/api/sewer?waterAssetId=electric'), 422),
                            (Request(base+'/api/sewer', json.dumps(p).encode(),
                                     {'Content-Type': 'application/json', 'Origin': 'https://foreign'}), 403)]:
            with pytest.raises(HTTPError) as error:
                urlopen(req)
            assert error.value.code == status
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
