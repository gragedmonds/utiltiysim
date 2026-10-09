"""HTTP guard and recovery checks for local phase cancellation/replacement."""
import json

import pytest
from test_world_cruise_http import http, serving
from test_world_field_execution import command as field_command
from test_world_field_reporting_http import command as report_command
from test_world_main_field_phases_http import accept, setup

from utilsim.world import field_execution as field
from utilsim.world import field_reporting, field_water_mains, water_mains


def lifecycle(f, identity='cancel', action='cancel', **changes):
    with f.db() as db:
        meta = f.metadata(db)
    return {'schemaVersion': 'field-assignment-lifecycle/1', 'commandId': identity,
            'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'],
            'actorId': 'world-admin', 'effectiveDate': meta['through'], 'action': action,
            'causalReference': 'cancellation-http', 'reason': 'Retire an explicitly reviewed local phase branch',
            **({'assignmentIds': ['repair','restore'], 'expectedRevisions': {'repair':0,'restore':0}} if action == 'cancel' else {}),
            **changes}


def chain(tmp_path, inspect_only=False):
    w, f, fault = setup(tmp_path)
    for phase in ['isolate','repair','restore']:
        field_water_mains.command(f, accept(f, phase))
    if inspect_only:
        field_reporting.command(f, report_command(f, assignmentId='isolate', workMode='inspect-only'))
        field.run_due(f)
    return w, f, fault


def test_http_cancel_requires_explicit_descendants_and_preserves_accept_retry(tmp_path):
    w, f, _ = chain(tmp_path, inspect_only=True)
    with serving(w, f.path, worker=False) as (_, base):
        route = '/api/field-assignment-lifecycle'
        incomplete = lifecycle(f, assignmentIds=['repair'], expectedRevisions={'repair':0})
        assert http(base, route, incomplete)[0] == 422
        payload = lifecycle(f)
        code, result = http(base, route, payload)
        assert code == 200
        assert http(base, route, payload) == (200, result)
        assert http(base, route, {**payload, 'reason':'changed retry'})[0] == 422
        for phase in ['repair','restore']:
            assert http(base, '/api/field-execution', field_command(f, 'execute-'+phase, 'execute', assignmentId=phase))[0] == 422
            assert http(base, '/api/field-reporting', report_command(f, 'configure-'+phase, assignmentId=phase))[0] == 422
            assert http(base, '/api/field-main-phases', accept(f, phase))[0] == 200
        rows = field.inspect(f)['items']
        assert [r['state'] for r in rows] == ['executed','cancelled','cancelled']
        assert field.run_due(f) == []
        with f.db() as db:
            assert db.execute('SELECT COUNT(*) FROM field_outbox').fetchone()[0] == 3


@pytest.mark.parametrize('changes', [{'reason':''}, {'actorId':'crew-plumbing'}, {'expectedRevisions':{'repair':1,'restore':0}},
                                    {'expectedRevisions':{'repair':0}}, {'expectedChecksum':'invented'}, {'environmentId':'OTHER'}])
def test_http_cancel_rejects_invalid_identity_reason_revision_and_contract(tmp_path, changes):
    w, f, _ = chain(tmp_path, inspect_only=True)
    with serving(w, f.path, worker=False) as (_, base):
        assert http(base, '/api/field-assignment-lifecycle', lifecycle(f, **changes))[0] == 422
        assert [r['state'] for r in field.inspect(f)['items']] == ['executed','accepted','accepted']


def test_http_cannot_cancel_physically_committed_visit_after_field_commit_loss(tmp_path, monkeypatch):
    w, f, _ = chain(tmp_path)
    original = field._physical
    def interrupted(*args, **kwargs):
        result = original(*args, **kwargs)
        if result['outcome'] == 'completed':
            raise SystemExit('After physical commit, before field commit')
        return result
    monkeypatch.setattr(field, '_physical', interrupted)
    with pytest.raises(SystemExit):
        field.run_due(f)
    monkeypatch.setattr(field, '_physical', original)
    assert water_mains.inspect(w, 'main')['selected']['active']['status'] == 'isolated'
    with serving(w, f.path, worker=False) as (_, base):
        payload = lifecycle(f, assignmentIds=['isolate','repair','restore'], expectedRevisions={'isolate':0,'repair':0,'restore':0})
        assert http(base, '/api/field-assignment-lifecycle', payload)[0] == 422
        assert field.inspect(f)['items'][0]['state'] != 'cancelled'
        field.run_due(f)
        rows = field.inspect(f)['items']
        assert rows[0]['state'] == 'executed' and rows[0]['result']['effectiveDate'] == '2026-01-01'
        assert all(row['state'] == 'accepted' for row in rows[1:])
        assert http(base, '/api/field-assignment-lifecycle', payload)[0] == 422
    with w.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='WaterMainPhysicalAction'").fetchone()[0] == 1


def test_http_replacement_acceptance_is_atomic_and_does_not_retarget_old_binding(tmp_path):
    w, f, _ = chain(tmp_path, inspect_only=True)
    with serving(w, f.path, worker=False) as (_, base):
        route = '/api/field-assignment-lifecycle'
        assert http(base, route, lifecycle(f))[0] == 200
        new_isolate = accept(f, 'isolate', commandId='new-isolate', assignmentId='new-isolate', orderId='NEW-ISOLATE')
        assert http(base, '/api/field-main-phases', new_isolate)[0] == 200
        replacement = accept(f, 'repair', commandId='new-repair', assignmentId='new-repair', orderId='NEW-REPAIR',
                             predecessorAssignmentId='new-isolate', causalReference='cancellation-http')
        payload = lifecycle(f, 'replace', 'replace', assignmentId='repair', expectedRevision=1, replacement=replacement)
        assert http(base, route, {**payload, 'replacement':{**replacement, 'assetId':'down'}})[0] == 422
        assert len(field.inspect(f)['items']) == 4
        code, result = http(base, route, payload)
        assert code == 200
        assert http(base, route, payload) == (200, result)
        assert http(base, route, {**payload, 'replacement':{**replacement, 'orderId':'MUTATED'}})[0] == 422
        with f.db() as db:
            old = json.loads(db.execute("SELECT payload FROM field_assignments WHERE id='repair'").fetchone()[0])
            assert old['predecessorAssignmentId'] == 'isolate'
            assert db.execute("SELECT predecessor FROM field_main_phases WHERE assignment='new-repair'").fetchone()[0] == 'new-isolate'
            assert db.execute('SELECT COUNT(*) FROM field_assignments').fetchone()[0] == 5


def test_http_cancel_remaining_work_keeps_real_isolation_until_replacements_finish(tmp_path):
    w, f, fault = chain(tmp_path)
    field.run_due(f)
    with serving(w, f.path, worker=False) as (_, base):
        route = '/api/field-assignment-lifecycle'
        assert http(base, route, lifecycle(f))[0] == 200
        active = water_mains.inspect(w, 'main')['selected']['active']
        assert active['id'] == fault['faultId'] and active['status'] == 'isolated'
        for phase, predecessor in [('repair','isolate'),('restore','replacement-repair')]:
            replacement = accept(f, phase, commandId='new-'+phase, assignmentId='replacement-'+phase,
                                 orderId='REPLACEMENT-'+phase, predecessorAssignmentId=predecessor,
                                 causalReference='cancellation-http')
            payload = lifecycle(f, 'replace-'+phase, 'replace', assignmentId=phase, expectedRevision=1,
                                replacement=replacement)
            assert http(base, route, payload)[0] == 200
        w.advance('2026-01-02')
        field.run_due(f)
        assert water_mains.inspect(w, 'main')['selected']['active']['status'] == 'repaired'
        assert water_mains.inspect(w)['interruptedServices'] == 1
        w.advance('2026-01-03')
        field.run_due(f)
        assert water_mains.inspect(w, 'main')['selected']['active'] is None
        assert water_mains.inspect(w)['interruptedServices'] == 0
    with w.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='WaterMainPhysicalAction'").fetchone()[0] == 3
