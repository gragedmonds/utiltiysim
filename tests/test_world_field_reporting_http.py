"""HTTP boundaries for independent manual crew reports and active world clocks."""
import json

from test_world_cruise_http import command as cruise_command
from test_world_cruise_http import http, serving
from test_world_field_execution import command as visit_command
from test_world_field_execution import setup
from test_world_water_faults import command as leak_command

from utilsim.world import cruise, water_faults
from utilsim.world import field_execution as field


def command(f, identity='policy', action='configure', **changes):
    with f.db() as db:
        meta = f.metadata(db)
    extra = {'reportMode': 'manual', 'workMode': 'perform'} if action == 'configure' else {'outcome': 'completed'}
    return {'schemaVersion': 'field-reporting/1', 'commandId': identity, 'environmentId': meta['environment'],
            'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin' if action == 'configure' else 'crew-plumbing',
            'effectiveDate': meta['through'], 'action': action, 'causalReference': 'reporting-http',
            'assignmentId': 'A1', 'expectedRevision': 0 if action == 'configure' else 1, **extra, **changes}


def accepted(tmp_path):
    w, f = setup(tmp_path)
    fault = water_faults.command(w, leak_command(w))
    field.command(f, visit_command(f, reportDelayDays=2))
    return w, f, fault


def envelopes(f):
    with f.db() as db:
        return [json.loads(r[0]) for r in db.execute('SELECT envelope FROM field_outbox')
                if json.loads(r[0])['schema'] == 'field-report/1']


def test_http_manual_repair_missing_report_then_late_submit_during_active_cruise(tmp_path):
    w, f, fault = accepted(tmp_path)
    with serving(w, f.path, worker=False) as (_, base):
        route = '/api/field-reporting'
        policy = command(f)
        assert http(base, route, policy)[0] == 200
        assert http(base, route, command(f, 'early', 'submit'))[0] == 422
        field.run_due(f)
        assert envelopes(f) == []
        assert water_faults.inspect(w, 'water')['current']['active'] is None
        w.advance('2026-01-04')
        cruise.command(w, cruise_command(w, targetDate='2026-01-06'), f)
        submit = command(f, 'submit', 'submit')
        code, result = http(base, route, submit)
        assert code == 200
        assert cruise.inspect(w, f)['status'] == 'running'
        assert http(base, route, submit) == (200, result)
        assert http(base, route, {**submit, 'outcome': 'not_found'})[0] == 422
        assert http(base, route, command(f, 'second', 'submit'))[0] == 422
        report, = envelopes(f)
        assert report['data']['submitted_at'] == '2026-01-04T00:00:00Z'
        assert report['data']['outcome'] == 'completed'
        assert fault['faultId'] not in json.dumps(report)
        with f.db() as db:
            assert db.execute('SELECT available_day FROM field_outbox WHERE id=?', (report['id'],)).fetchone()[0] == '2026-01-06'
        assert not any(item['envelope']['id'] == report['id'] for item in field.ready(f)['items'])
        assert http(base, '/field-reporting')[0] == http(base, '/field-reporting.js')[0] == 200


def test_http_rejects_wrong_crew_stale_revision_date_and_admin_claim(tmp_path):
    w, f, _ = accepted(tmp_path)
    with serving(w, f.path, worker=False) as (_, base):
        route = '/api/field-reporting'
        assert http(base, route, command(f))[0] == 200
        field.run_due(f)
        good = command(f, 'submit', 'submit')
        for changes in [{'actorId': 'other-crew'}, {'actorId': 'world-admin'}, {'expectedRevision': 0},
                        {'effectiveDate': '2026-01-02'}, {'environmentId': 'OTHER'}, {'worldFingerprint': 'wrong'}]:
            assert http(base, route, {**good, **changes})[0] == 422
        assert envelopes(f) == []
        assert http(base, route, good)[0] == 200
        assert len(envelopes(f)) == 1


def test_http_inspect_only_false_completed_does_not_repair_or_change_visit_truth(tmp_path):
    w, f, fault = accepted(tmp_path)
    with serving(w, f.path, worker=False) as (_, base):
        route = '/api/field-reporting'
        assert http(base, route, command(f, workMode='inspect-only'))[0] == 200
        field.run_due(f)
        physical = field.inspect(f)['items'][0]['result']
        assert physical['outcome'] == 'not_attempted' and physical['physicalEventId'] is None
        assert envelopes(f) == []
        assert http(base, route, command(f, 'reconfigure', expectedRevision=1))[0] == 422
        assert http(base, route, command(f, 'false-claim', 'submit'))[0] == 200
        assert field.inspect(f)['items'][0]['result']['outcome'] == 'not_attempted'
        assert envelopes(f)[0]['data']['outcome'] == 'completed'
        assert water_faults.inspect(w, 'water')['current']['active']['id'] == fault['faultId']
        w.advance('2026-01-02')
        with w.db() as db:
            effect = db.execute('SELECT * FROM water_fault_effects WHERE asset=?', ('water',)).fetchone()
            assert effect and float(effect['leak_quantity']) > 0
            assert not db.execute("SELECT 1 FROM events WHERE type='PhysicalWaterLeakRepaired'").fetchone()


def test_http_clock_advance_rejects_stale_new_submission_but_retains_success_retry(tmp_path):
    w, f, _ = accepted(tmp_path)
    with serving(w, f.path, worker=False) as (_, base):
        route = '/api/field-reporting'
        assert http(base, route, command(f))[0] == 200
        field.run_due(f)
        stale = command(f, 'submit', 'submit')
        cruise.command(w, cruise_command(w, targetDate='2026-01-03'), f)
        cruise.tick(w, f, max_days=1)
        assert http(base, route, stale)[0] == 422
        assert envelopes(f) == []
        fresh = command(f, 'submit-fresh', 'submit')
        code, result = http(base, route, fresh)
        assert code == 200
        cruise.tick(w, f, max_days=1)
        assert http(base, route, fresh) == (200, result)
        assert len(envelopes(f)) == 1


def test_http_reporting_security_missing_owner_and_read_only_inspection(tmp_path):
    w, f, _ = accepted(tmp_path)
    with serving(w, worker=False) as (_, base):
        assert http(base, '/api/field-reporting')[0] == 503
        assert http(base, '/api/field-reporting', command(f))[0] == 503
    with serving(w, f.path, worker=False) as (_, base):
        route = '/api/field-reporting'
        assert http(base, route)[0] == 200
        assert http(base, route+'?unexpected=1')[0] == 422
        assert http(base, route, headers={'Host': 'attacker.invalid'})[0] == 403
        assert http(base, route, command(f), headers={'Origin': 'https://attacker.invalid'})[0] == 403
        assert http(base, route, command(f), headers={'Content-Type': 'text/plain'})[0] == 415
        assert http(base, route, [])[0] == 422
        assert field.inspect(f)['items'][0]['state'] == 'accepted'
        assert envelopes(f) == []

