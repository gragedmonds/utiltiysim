import gzip
import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_world_cruise_http import http, serving
from test_world_field_execution import command
from test_world_v2 import snapshot
from test_world_water_faults import command as leak_command

from utilsim.world import World, field_execution, field_travel, sewer, water_faults


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


def sewer_assignment(world, owner):
    identity = sewer.inspect(world, 'water')['service']['id']
    field_execution.command(owner, command(owner, 'sewer-crew', 'configure-crew',
                                           crewId='crew-sewer', skills=['sewer']))
    field_execution.command(owner, command(owner, 'sewer-assignment', assignmentId='SEWER-A1',
                                           crewId='crew-sewer', assetId=identity, orderId='SEWER-ORDER',
                                           operation='clear-sewer-blockage'))
    return identity


def test_sewer_uses_its_own_saved_water_service_mapping_without_fault_truth(tmp_path):
    saved = town()
    # The sewer assignment must follow its installation, not the first premise.
    other = deepcopy(saved['premises'][0])
    other.update(id='OTHER', t=0.25)
    saved['premises'].insert(0, other)
    world, owner = setup(tmp_path, saved)
    identity = sewer_assignment(world, owner)
    before = dump(world), dump(owner)
    quote = field_travel.quote(owner, request(owner, assignmentId='SEWER-A1'))
    water_quote = field_travel.quote(owner, request(owner))
    assert quote['status'] == 'ready'
    assert quote['assetId'] == identity and quote['crewId'] == 'crew-sewer'
    assert quote['operation'] == 'clear-sewer-blockage'
    assert quote['accessBinding'] == {'kind': 'saved-premise', 'premiseId': 'P1', 'waterAssetId': 'water'}
    assert quote['destination'] == {'roadId': 'R1', 't': 1}
    assert quote['outbound'] == water_quote['outbound']
    assert quote['quoteId'] != water_quote['quoteId']
    assert (dump(world), dump(owner)) == before
    reopened = field_execution.FieldExecution(World(world.path), owner.path)
    before = dump(world), dump(owner)
    assert field_travel.quote(reopened, request(reopened, assignmentId='SEWER-A1')) == quote
    assert (dump(world), dump(owner)) == before
    assert all(secret not in json.dumps(quote) for secret in ('faultId', 'capacityM3PerDay', 'active', 'overflow'))


def test_sewer_does_not_substitute_another_premise_for_missing_access(tmp_path):
    saved = town()
    saved['premises'][0].pop('roadId')
    world, owner = setup(tmp_path, saved)
    sewer_assignment(world, owner)
    before = dump(world), dump(owner)
    result = field_travel.quote(owner, request(owner, assignmentId='SEWER-A1'))
    assert result['status'] == 'unavailable' and 'road access' in result['reason']
    assert 'quoteId' not in result
    assert (dump(world), dump(owner)) == before


def test_sewer_committed_visit_is_unavailable_before_field_crash_recovery(tmp_path, monkeypatch):
    from test_world_sewer import command as sewer_command

    world, owner = setup(tmp_path)
    sewer_assignment(world, owner)
    sewer.command(world, sewer_command(world))
    enqueue = field_execution._enqueue

    def crash(*args):
        if args[4] == 'report':
            raise RuntimeError('physical commit then process loss')
        return enqueue(*args)

    monkeypatch.setattr(field_execution, '_enqueue', crash)
    with pytest.raises(RuntimeError):
        field_execution.command(owner, command(owner, 'sewer-execute', 'execute',
                                               assignmentId='SEWER-A1', actorId='crew-sewer'))
    before = dump(world), dump(owner)
    result = field_travel.quote(owner, request(owner, assignmentId='SEWER-A1'))
    assert result['status'] == 'unavailable' and 'already committed' in result['reason']
    assert (dump(world), dump(owner)) == before


@pytest.mark.parametrize('commodity,operation', [('electric', 'restore-electric-supply'), ('gas', 'restore-gas-supply')])
def test_network_edge_never_borrows_connected_customer_premise_access(tmp_path, commodity, operation):
    from test_world_network_faults import source

    saved = town()
    network = source()
    saved['networks'], saved['servicePoints'] = network['networks'], network['servicePoints']
    world, owner = setup(tmp_path, saved)
    field_execution.command(owner, command(owner, 'network-crew', 'configure-crew',
                                           crewId='network-crew', skills=[commodity]))
    field_execution.command(owner, command(owner, 'network-assignment', assignmentId='NETWORK-A1',
                                           crewId='network-crew', assetId='supply', operation=operation, orderId='NETWORK-ORDER'))
    before = dump(world), dump(owner)
    result = field_travel.quote(owner, request(owner, assignmentId='NETWORK-A1'))
    assert result['status'] == 'unavailable' and 'road-access binding' in result['reason']
    assert 'quoteId' not in result and 'premiseId' not in result
    assert (dump(world), dump(owner)) == before


def test_water_main_phases_do_not_invent_work_site_access(tmp_path):
    from test_world_field_water_mains import chain
    from test_world_field_water_mains import setup as main_setup

    world, owner = main_setup(tmp_path)
    chain(owner)
    before = dump(world), dump(owner)
    for phase in ('isolate', 'repair', 'restore'):
        result = field_travel.quote(owner, request(owner, assignmentId=phase))
        assert result['status'] == 'unavailable' and 'road-access binding' in result['reason']
        assert 'quoteId' not in result and 'premiseId' not in result
    assert (dump(world), dump(owner)) == before


def network_assignment(tmp_path, commodity='electric', saved_change=None):
    from test_world_network_faults import source

    saved = town()
    network = source()
    saved['networks'], saved['servicePoints'] = network['networks'], network['servicePoints']
    if saved_change:
        saved_change(saved)
    world, owner = setup(tmp_path, saved)
    field_execution.command(owner, command(owner, 'network-crew', 'configure-crew',
                                           crewId='network-crew', skills=[commodity]))
    field_execution.command(owner, command(owner, 'network-assignment', assignmentId='NETWORK-A1',
        crewId='network-crew', assetId='supply', operation=f'restore-{commodity}-supply', orderId='NETWORK-ORDER'))
    return world, owner


def site_request(owner, **extra):
    return request(owner, schemaVersion=field_travel.WORK_SITE_VERSION, assignmentId='NETWORK-A1',
                   workSite={'roadId': 'R1', 't': 0.5}, **extra)


@pytest.mark.parametrize('commodity', ['electric', 'gas'])
def test_explicit_network_work_site_binds_planning_assumption_and_preserves_stores(tmp_path, commodity):
    world, owner = network_assignment(tmp_path, commodity)
    before = dump(world), dump(owner)
    value = field_travel.quote(owner, site_request(owner))
    assert value['status'] == 'ready'
    assert value['accessBinding'] == {'kind': 'administrator-selected', 'assetId': 'supply',
                                     'operation': f'restore-{commodity}-supply', 'roadId': 'R1', 't': 0.5}
    assert 'not a verified physical work site' in value['locationNotice']
    assert value['orderId'] == 'NETWORK-ORDER' and value['orderRevision'] == 1
    assert 'premiseId' not in value
    assert value['outbound']['lengthMeters'] == pytest.approx(500)
    assert (dump(world), dump(owner)) == before
    alternate = field_travel.quote(owner, {**site_request(owner), 'workSite': {'roadId': 'R1', 't': 0.75}})
    assert alternate['quoteId'] != value['quoteId']
    assert alternate['outbound']['lengthMeters'] == pytest.approx(750)
    assert (dump(world), dump(owner)) == before
    reopened = field_execution.FieldExecution(World(world.path), owner.path)
    before = dump(world), dump(owner)
    assert field_travel.quote(reopened, site_request(reopened)) == value
    assert (dump(world), dump(owner)) == before
    with serving(world, owner.path, worker=False) as (_, base):
        assert http(base, '/api/field-travel/quote', site_request(owner)) == (200, value)


@pytest.mark.parametrize('site', [None, {}, {'roadId': 'R1', 't': -0.01}, {'roadId': 'R1', 't': 1.01},
    {'roadId': 'R1', 't': float('nan')}, {'roadId': 'R1', 't': True}, {'roadId': '', 't': 0.5},
    {'roadId': 'R1', 't': 0.5, 'assetId': 'other'}])
def test_selected_site_contract_rejects_invalid_assumptions(tmp_path, site):
    world, owner = network_assignment(tmp_path)
    before = dump(world), dump(owner)
    with pytest.raises(ValueError):
        field_travel.quote(owner, {**site_request(owner), 'workSite': site})
    assert (dump(world), dump(owner)) == before


def test_selected_site_cannot_override_premise_or_snap_to_unknown_road(tmp_path):
    world, owner = network_assignment(tmp_path)
    before = dump(world), dump(owner)
    with pytest.raises(ValueError, match='saved premise access'):
        field_travel.quote(owner, {**site_request(owner), 'assignmentId': 'A1'})
    result = field_travel.quote(owner, {**site_request(owner), 'workSite': {'roadId': 'UNKNOWN', 't': 0.5}})
    assert result['status'] == 'unavailable' and 'quoteId' not in result
    assert (dump(world), dump(owner)) == before


def test_selected_site_rejects_disconnected_roads(tmp_path):
    def island(saved):
        saved['roads'].append({'id': 'ISLAND', 'a': 'N3', 'b': 'N4', 'roadClass': 'local',
                               'points': [{'x': 2000, 'z': 0}, {'x': 3000, 'z': 0}]})
    world, owner = network_assignment(tmp_path, saved_change=island)
    before = dump(world), dump(owner)
    result = field_travel.quote(owner, {**site_request(owner), 'workSite': {'roadId': 'ISLAND', 't': 0.5}})
    assert result['status'] == 'unavailable' and 'separate road islands' in result['reason']
    assert 'quoteId' not in result
    assert (dump(world), dump(owner)) == before


def test_main_phase_planning_quotes_do_not_execute_or_bypass_predecessors(tmp_path):
    from test_world_field_water_mains import chain
    from test_world_water_mains import source

    saved = town()
    mains = source()
    saved['networks'], saved['servicePoints'] = mains['networks'], mains['servicePoints']
    world, owner = setup(tmp_path, saved)
    field_execution.command(owner, command(owner, 'main-crew', 'configure-crew', expectedRevision=1,
                                           skills=['plumbing', 'water-main']))
    chain(owner)
    before = dump(world), dump(owner)
    ids = set()
    for phase in ('isolate', 'repair', 'restore'):
        result = field_travel.quote(owner, {**site_request(owner), 'assignmentId': phase})
        assert result['status'] == 'ready'
        assert result['accessBinding']['operation'] == phase + '-water-main'
        assert result['assetId'] == 'main'
        ids.add(result['quoteId'])
    assert len(ids) == 3
    assert (dump(world), dump(owner)) == before
    pending = {item['assignment']['assignmentId']: item for item in field_execution.inspect(owner)['items']}
    assert 'Waiting' in pending['repair']['blockedReason']
    assert 'Waiting' in pending['restore']['blockedReason']


def test_selected_site_does_not_requote_committed_network_visit_after_crash(tmp_path, monkeypatch):
    world, owner = network_assignment(tmp_path)
    enqueue = field_execution._enqueue

    def crash(*args):
        if args[4] == 'report':
            raise RuntimeError('physical commit then process loss')
        return enqueue(*args)

    monkeypatch.setattr(field_execution, '_enqueue', crash)
    with pytest.raises(RuntimeError):
        field_execution.command(owner, command(owner, 'network-execute', 'execute',
                                               assignmentId='NETWORK-A1', actorId='network-crew'))
    before = dump(world), dump(owner)
    result = field_travel.quote(owner, site_request(owner))
    assert result['status'] == 'unavailable' and 'already committed' in result['reason']
    assert 'quoteId' not in result
    assert (dump(world), dump(owner)) == before
