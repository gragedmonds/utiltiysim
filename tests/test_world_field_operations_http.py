"""HTTP authorization and observable evidence for the four field operations."""
import json

import pytest
from test_world_cruise_http import http, serving
from test_world_field_execution import command
from test_world_network_faults import world

from scripts.check_world_field_operations import setup_faults
from utilsim.world import field_execution as field


@pytest.mark.parametrize('visit_index', [0, 1, 2, 3])
def test_operation_http_identity_skill_retry_and_filtered_report(tmp_path, visit_index):
    w = world(tmp_path)
    _, _, faults, visits = setup_faults(w)
    f = field.FieldExecution(w, tmp_path/'field.sqlite')
    key, operation, asset = visits[visit_index]
    with serving(w, f.path, worker=False) as (_, base):
        route = '/api/field-execution'
        configure = command(f, 'crew', 'configure-crew', skills=list(field.OPERATIONS.values()))
        assert http(base, route, configure)[0] == 200
        accept = command(f, operation=operation, assetId=asset)
        code, accepted = http(base, route, accept)
        assert code == 200
        assert http(base, route, accept) == (200, accepted)
        assert http(base, route, {**accept, 'assetId': 'different'})[0] == 422
        execute = command(f, 'execute', 'execute')
        assert http(base, route, {**execute, 'actorId': 'unassigned-crew'})[0] == 422
        assert http(base, route, {**execute, 'environmentId': 'another-world'})[0] == 422
        assert http(base, route, command(f, 'disable', 'configure-crew', expectedRevision=1, skills=[]))[0] == 200
        assert http(base, route, execute)[0] == 422
        current = http(base, route)[1]
        assert current['items'][0]['state'] == 'accepted'
        assert http(base, route, command(f, 'enable', 'configure-crew', expectedRevision=2,
                                        skills=[field.OPERATIONS[operation]]))[0] == 200
        code, result = http(base, route, execute)
        assert code == 200 and result['outcome'] == 'completed'
        assert http(base, route, execute) == (200, result)
        assert http(base, route, {**execute, 'causalReference': 'changed'})[0] == 422
        state = http(base, route)[1]
        assert state['items'][0]['state'] == 'executed'
        assert len(state['items'][0]['messages']) == 2
        assert all(m['state'] == 'pending' for m in state['items'][0]['messages'])
        assert http(base, '/field-execution')[0] == http(base, '/field-execution.js')[0] == 200
    report = next(r['envelope'] for r in field.ready(f)['items'] if r['envelope']['schema'] == 'field-report/1')
    encoded = json.dumps(report)
    assert report['data']['outcome'] == 'completed'
    assert all(secret not in encoded for secret in [faults[key], 'faultId', 'expectedRevision', 'normal_quantity',
                                                    'unserved_quantity', 'retained', 'field-operations-acceptance'])
    with w.db() as db:
        events = [json.loads(row[0]) for row in db.execute(
            "SELECT payload FROM events WHERE type IN ('PhysicalNetworkRestored','PhysicalSewerCleared','PhysicalWaterLeakRepaired')")]
        assert sum(event.get('faultId') == faults[key] for event in events) == 1
        assert not db.execute("SELECT name FROM sqlite_master WHERE name IN ('invoices','payments','work_orders')").fetchall()


@pytest.mark.parametrize('changes', [
    {'operation': 'restore-magic-supply'},
    {'operation': 'restore-electric-supply', 'assetId': 'electric'},
    {'operation': 'restore-gas-supply', 'assetId': 'gas'},
    {'operation': 'clear-sewer-blockage', 'assetId': 'water'},
])
def test_http_rejects_wrong_operation_target_without_assignment(tmp_path, changes):
    w = world(tmp_path)
    f = field.FieldExecution(w, tmp_path/'field.sqlite')
    field.command(f, command(f, 'crew', 'configure-crew', skills=list(field.OPERATIONS.values())))
    with serving(w, f.path, worker=False) as (_, base):
        assert http(base, '/api/field-execution', command(f, **changes))[0] == 422
        assert http(base, '/api/field-execution')[1]['items'] == []
    assert field.ready(f)['items'] == []
