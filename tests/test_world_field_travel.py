import gzip
import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_world_cruise_http import http, serving
from test_world_field_execution import command
from test_world_v2 import snapshot
from test_world_water_faults import command as leak_command

from utilsim.world import World, field_execution, field_travel, water_faults


def town():
    saved = snapshot()
    saved['premises'][0].update(roadId='R1', t=1)
    saved['facilities'] = [{'id': 'D1', 'kind': 'depot', 'roadId': 'R1', 't': 0}]
    saved['roads'] = [{'id': 'R1', 'a': 'N1', 'b': 'N2', 'roadClass': 'local',
                       'points': [{'x': 0, 'z': 0}, {'x': 1000, 'z': 0}]}]
    return saved


def setup(tmp_path, saved=None):
    world = World(tmp_path / 'world.sqlite')
    world.initialize(saved if saved is not None else town(), 'TEST', settings={'annual_meter_failure': 0})
    owner = field_execution.FieldExecution(world, tmp_path / 'field.sqlite')
    field_execution.command(owner, command(owner, 'crew', 'configure-crew'))
    field_execution.command(owner, command(owner))
    return world, owner


def request(owner, **extra):
    with owner.db() as db:
        meta = owner.metadata(db)
    return {'schemaVersion': field_travel.VERSION, 'environmentId': meta['environment'],
            'worldFingerprint': meta['fingerprint'], 'assignmentId': 'A1', 'depotId': 'D1',
            'mobilisationSeconds': 300, 'workSeconds': 1800,
            'speedsKmh': {'arterial': 60, 'collector': 40, 'local': 36}, **extra}


def dump(owner):
    with owner.db() as db:
        return '\n'.join(db.iterdump())


def test_saved_route_round_trip_and_restart_preserve_both_owners(tmp_path):
    world, owner = setup(tmp_path)
    before = dump(world), dump(owner)
    result = field_travel.quote(owner, request(owner))
    assert result['status'] == 'ready'
    assert result['outbound']['lengthMeters'] == pytest.approx(1000)
    assert result['return']['lengthMeters'] == pytest.approx(1000)
    # Router adds a millisecond per vertex for interpolation; round up each leg.
    assert result['durationSeconds'] == {'mobilisation': 300, 'outbound': 101, 'work': 1800, 'return': 101}
    assert result['totalSeconds'] == 2302
    assert result['outbound']['points'][0]['z'] > 0
    assert result['return']['points'][0]['z'] < 0
    assert (dump(world), dump(owner)) == before
    reopened = field_execution.FieldExecution(World(world.path), owner.path)
    assert field_travel.quote(reopened, request(reopened)) == result
    assert field_execution.inspect(owner)['items'][0]['state'] == 'accepted'
    slower = field_travel.quote(owner, request(owner, speedsKmh={'arterial': 60, 'collector': 40, 'local': 18}))
    assert slower['totalSeconds'] == result['totalSeconds'] + 200
    assert slower['quoteId'] != result['quoteId']
    assert all(secret not in json.dumps(result) for secret in ('faultId', 'leakM3PerHour', 'normal_quantity', 'meterCondition'))


@pytest.mark.parametrize('change', ['missing-roads', 'missing-depot', 'missing-access', 'bad-fraction',
                                   'disconnected', 'duplicate-road', 'zero-length', 'invalid-coordinate', 'broken-junction', 'unknown-class'])
def test_unavailable_geometry_never_invents_a_visit(tmp_path, change):
    saved = town()
    if change == 'missing-roads':
        saved.pop('roads')
    elif change == 'missing-depot':
        saved['facilities'] = []
    elif change == 'missing-access':
        saved['premises'][0].pop('roadId')
    elif change == 'bad-fraction':
        saved['premises'][0]['t'] = 1.5
    elif change in ('disconnected', 'broken-junction'):
        saved['roads'].append({'id': 'R2', 'a': 'N3' if change == 'disconnected' else 'N2', 'b': 'N4', 'roadClass': 'local',
                               'points': [{'x': 2000, 'z': 0}, {'x': 3000, 'z': 0}]})
        saved['premises'][0]['roadId'] = 'R2'
    elif change == 'duplicate-road':
        saved['roads'].append(deepcopy(saved['roads'][0]))
    elif change == 'zero-length':
        saved['roads'][0]['points'][1]['x'] = 0
    elif change == 'unknown-class':
        saved['roads'][0]['roadClass'] = 'unknown'
    else:
        saved['roads'][0]['points'][1]['x'] = 'invalid'
    world, owner = setup(tmp_path, saved)
    before = dump(world), dump(owner)
    result = field_travel.quote(owner, request(owner))
    assert result['status'] == 'unavailable'
    if change == 'disconnected':
        assert 'separate road islands' in result['reason']
    assert 'quoteId' not in result and 'totalSeconds' not in result
    assert (dump(world), dump(owner)) == before


@pytest.mark.parametrize('change', [
    {'mobilisationSeconds': -1}, {'workSeconds': 0}, {'workSeconds': True},
    {'speedsKmh': {'arterial': 60, 'collector': 40, 'local': 0}},
    {'speedsKmh': {'arterial': 60, 'collector': 40, 'local': float('inf')}},
    {'speedsKmh': {'arterial': 60}}, {'environmentId': 'another'}, {'worldFingerprint': 'another'},
    {'assignmentId': 'unknown'}, {'unexpected': 1}])
def test_invalid_requests_have_no_effect(tmp_path, change):
    world, owner = setup(tmp_path)
    before = dump(world), dump(owner)
    with pytest.raises(ValueError):
        field_travel.quote(owner, request(owner, **change))
    assert (dump(world), dump(owner)) == before


def test_committed_physical_visit_cannot_be_quoted_again_after_crash(tmp_path, monkeypatch):
    world, owner = setup(tmp_path)
    water_faults.command(world, leak_command(world))
    enqueue = field_execution._enqueue

    def crash(*args):
        if args[4] == 'report':
            raise RuntimeError('physical commit then process loss')
        return enqueue(*args)

    monkeypatch.setattr(field_execution, '_enqueue', crash)
    with pytest.raises(RuntimeError):
        field_execution.command(owner, command(owner, 'execute', 'execute'))
    assert field_execution.inspect(owner)['items'][0]['state'] == 'accepted'
    before = dump(world), dump(owner)
    result = field_travel.quote(owner, request(owner))
    assert result['status'] == 'unavailable' and 'already committed' in result['reason']
    assert (dump(world), dump(owner)) == before
    monkeypatch.setattr(field_execution, '_enqueue', enqueue)
    field_execution.run_due(owner)
    assert 'no longer pending' in field_travel.quote(owner, request(owner))['reason']


def test_http_quotes_require_separate_field_owner_and_world_identity(tmp_path):
    world, owner = setup(tmp_path)
    before = dump(world), dump(owner)
    route = '/api/field-travel/quote'
    with serving(world, owner.path, worker=False) as (_, base):
        assert http(base, route, request(owner)) == (200, field_travel.quote(owner, request(owner)))
        assert http(base, route, request(owner, environmentId='OTHER'))[0] == 422
        assert http(base, route, request(owner, workSeconds=0))[0] == 422
    assert (dump(world), dump(owner)) == before
    with serving(world, None, worker=False) as (_, base):
        assert http(base, route, request(owner))[0] == 503


def test_complete_saved_town_has_real_depot_to_service_route(tmp_path):
    pack = next((Path(__file__).parents[1] / 'packs/village').glob('*.snapshot.json.gz'))
    saved = json.loads(gzip.decompress(pack.read_bytes()))
    world = World(tmp_path / 'town.sqlite')
    world.initialize(saved, 'SAVED-TRAVEL')
    owner = field_execution.FieldExecution(world, tmp_path / 'field.sqlite')
    with world.db() as db:
        asset = db.execute("SELECT id FROM assets WHERE commodity='water' AND installed<='2026-01-01' ORDER BY id LIMIT 1").fetchone()[0]
    field_execution.command(owner, command(owner, 'crew', 'configure-crew'))
    field_execution.command(owner, command(owner, assetId=asset))
    before = dump(world), dump(owner)
    depot = next(d['id'] for d in saved['facilities'] if d['kind'] == 'depot')
    result = field_travel.quote(owner, request(owner, depotId=depot))
    assert result['status'] == 'ready', result
    assert result['outbound']['lengthMeters'] > 0
    assert len(result['outbound']['points']) > 2
    assert result['totalSeconds'] > 2100
    assert (dump(world), dump(owner)) == before
