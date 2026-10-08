"""HTTP acceptance for assignment-bound water-main phase predecessors."""
import json

import pytest
from test_world_cruise_http import command as cruise_command
from test_world_cruise_http import http, serving
from test_world_field_execution import command as field_command
from test_world_field_reporting_http import command as reporting_command
from test_world_water_mains import command as main_command
from test_world_water_mains import world

from utilsim.world import cruise, water_mains
from utilsim.world import field_execution as field


def setup(tmp_path):
    w = world(tmp_path)
    f = field.FieldExecution(w, tmp_path/'field.sqlite')
    field.command(f, field_command(f, 'crew', 'configure-crew', skills=['water-main']))
    fault = water_mains.command(w, main_command(w))
    return w, f, fault


def accept(f, phase, **changes):
    previous = {'isolate': None, 'repair': 'isolate', 'restore': 'repair'}[phase]
    return {**field_command(f, 'accept-'+phase, assignmentId=phase, orderId='LOCAL-'+phase,
                            assetId='main', operation=phase+'-water-main'),
            'schemaVersion': 'field-main-phases/1', 'predecessorAssignmentId': previous, **changes}


def test_http_main_chain_missing_report_retries_and_original_physical_success(tmp_path):
    w, f, fault = setup(tmp_path)
    with serving(w, f.path, worker=False) as (_, base):
        route = '/api/field-main-phases'
        for phase in ['isolate', 'repair', 'restore']:
            payload = accept(f, phase)
            code, result = http(base, route, payload)
            assert code == 200
            assert http(base, route, payload) == (200, result)
            assert http(base, route, {**payload, 'orderId': 'conflict'})[0] == 422
        policy = reporting_command(f, assignmentId='isolate')
        assert http(base, '/api/field-reporting', policy)[0] == 200
        cruise.command(w, cruise_command(w, targetDate='2026-01-04'), f)
        for through, status in [('2026-01-02','isolated'), ('2026-01-03','repaired'), ('2026-01-04',None)]:
            cruise.tick(w, f, max_days=1)
            assert cruise.inspect(w, f)['through'] == through
            active = water_mains.inspect(w, 'main')['selected']['active']
            assert (active['status'] if active else None) == status
        rows = http(base, '/api/field-execution')[1]['items']
        assert all(row['state'] == 'executed' for row in rows)
        assert [row['result']['effectiveDate'] for row in rows] == ['2026-01-01','2026-01-02','2026-01-03']
        assert rows[0]['result']['reportId'] is None
        assert http(base, route, accept(f, 'repair', effectiveDate='2026-01-01', scheduledDate='2026-01-01'))[0] == 200
        with f.db() as db:
            assert db.execute('SELECT COUNT(*) FROM field_assignments').fetchone()[0] == 3
            reports = [json.loads(r[0]) for r in db.execute('SELECT envelope FROM field_outbox')
                       if json.loads(r[0])['schema'] == 'field-report/1']
        assert len(reports) == 2
        assert fault['faultId'] not in json.dumps(reports)
        assert 'closedEdges' not in json.dumps(reports)
        assert all(message['state'] == 'pending' for row in rows for message in row['messages'])


def test_http_false_completed_predecessor_cannot_unlock_main_successor(tmp_path):
    w, f, fault = setup(tmp_path)
    with serving(w, f.path, worker=False) as (_, base):
        for phase in ['isolate', 'repair', 'restore']:
            assert http(base, '/api/field-main-phases', accept(f, phase))[0] == 200
        assert http(base, '/api/field-reporting', reporting_command(f, assignmentId='isolate', workMode='inspect-only'))[0] == 200
        cruise.command(w, cruise_command(w, targetDate='2026-01-04'), f)
        cruise.tick(w, f, max_days=1)
        assert http(base, '/api/field-reporting', reporting_command(f, 'false', 'submit', assignmentId='isolate'))[0] == 200
        cruise.tick(w, f, max_days=2)
        rows = http(base, '/api/field-execution')[1]['items']
        assert rows[0]['result']['outcome'] == 'not_attempted'
        assert all(row['state'] == 'accepted' and row['blockedReason'] for row in rows[1:])
        selected = water_mains.inspect(w, 'main')['selected']
        assert selected['active']['id'] == fault['faultId'] and selected['active']['status'] == 'broken'
        assert selected['revision'] == 1
        with w.db() as db:
            assert not db.execute("SELECT 1 FROM events WHERE type='WaterMainPhysicalAction'").fetchone()


@pytest.mark.parametrize('changes', [
    {'predecessorAssignmentId': None}, {'predecessorAssignmentId': 'unknown'},
    {'predecessorAssignmentId': 'repair'}, {'assetId': 'down'},
])
def test_http_rejects_unbound_wrong_phase_and_cross_main_predecessors(tmp_path, changes):
    w, f, _ = setup(tmp_path)
    with serving(w, f.path, worker=False) as (_, base):
        assert http(base, '/api/field-main-phases', accept(f, 'isolate'))[0] == 200
        assert http(base, '/api/field-main-phases', accept(f, 'repair', **changes))[0] == 422
        assert len(field.inspect(f)['items']) == 1


def test_http_phase_authorization_targets_and_existing_accept_cannot_bypass_binding(tmp_path):
    w, f, _ = setup(tmp_path)
    with serving(w, f.path, worker=False) as (_, base):
        route = '/api/field-main-phases'
        payload = accept(f, 'isolate')
        for changes in [{'actorId': 'crew-plumbing'}, {'assetId': 'water'}, {'assetId': 'service'},
                        {'environmentId': 'OTHER'}, {'worldFingerprint': 'wrong'}, {'predecessorAssignmentId': 'anything'}]:
            assert http(base, route, {**payload, **changes})[0] == 422
        assert http(base, route, payload, headers={'Origin':'https://attacker.invalid'})[0] == 403
        assert http(base, route, payload, headers={'Content-Type':'text/plain'})[0] == 415
        assert http(base, '/api/field-execution', field_command(f, operation='repair-water-main', assetId='main'))[0] == 422
        assert http(base, '/api/field-execution', payload)[0] == 422
        assert field.inspect(f)['items'] == []
        assert http(base, route, payload)[0] == 200
        wrong_crew = field_command(f, 'execute-wrong', 'execute', assignmentId='isolate', actorId='wrong-crew')
        assert http(base, '/api/field-execution', wrong_crew)[0] == 422
        assert water_mains.inspect(w, 'main')['selected']['active']['status'] == 'broken'

