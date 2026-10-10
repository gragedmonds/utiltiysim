"""Broker invariants with a deliberately explicit trusted-runtime fixture."""
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from test_world_field_execution import command
from test_world_field_travel import request, setup
from test_world_water_faults import command as leak_command

from utilsim.world import World, delivery, field_execution, field_managed, field_reporting, water_faults


def utc(day, clock, zone, fold):
    assert zone == 'UTC'
    return datetime.fromisoformat(day + 'T' + clock).replace(tzinfo=UTC).isoformat().replace('+00:00', 'Z')


class Authority:
    def __init__(self):
        self.state = {'runId': 'TEST', 'actorId': 'crew-runtime', 'clock': '2026-01-01T00:00:00Z'}

    def __call__(self, job, reservation):
        return deepcopy(self.state)

    def accept(self, adapter, plan, cancelled=False):
        self.state.update(job={'id': 'visit-1', 'actor': 'crew-runtime', 'target': field_managed.TARGET,
                              'operation': field_managed.OPERATION, 'payload': adapter.job_payload(plan, 'booking-1'),
                              'available': plan['availableAt'], 'status': 'pending'},
                          reservation={'id': 'booking-1', 'actor': 'crew-runtime', 'job': 'visit-1',
                                       'resource': plan['resourceId'], 'start': plan['start'], 'end': plan['end'],
                                       'cancelled': cancelled},
                          dependencies=[{'target': 'world', 'operation': 'advance_day',
                                         'payload': {'through': plan['physicalEffectiveDate']}, 'status': 'pending'}])

    def dispatch(self, world, plan):
        world.advance(plan['physicalEffectiveDate'])
        self.state['clock'] = plan['availableAt']
        self.state['job']['status'] = 'delivering'
        self.state['dependencies'][0]['status'] = 'completed'
        return {**self.state['job'], 'runId': 'TEST', 'processingAt': self.state['clock']}


def configured(tmp_path, **schedule_changes):
    world, owner = setup(tmp_path)
    delivery.configure(world, 'TEST')
    authority = Authority()
    adapter = field_managed.ManagedField(owner, tmp_path / 'runtime.sqlite', authority, utc)
    schedule = {'commandId': 'plan-1', 'visitDate': '2026-01-01', 'startTime': '09:00:00',
                'shiftStart': '08:00:00', 'shiftEnd': '17:00:00', 'timeZone': 'UTC', 'fold': None,
                'resourceId': 'field:local-field:crew-plumbing', **schedule_changes}
    return world, owner, authority, adapter, schedule


def bound(tmp_path):
    world, owner, authority, adapter, schedule = configured(tmp_path)
    water_faults.command(world, leak_command(world))
    plan = adapter.plan(request(owner), schedule)
    authority.accept(adapter, plan)
    adapter.bind('A1', 'visit-1', 'booking-1')
    return world, owner, authority, adapter, schedule, plan


def test_roundtrip_boundary_capacity_reports_and_restart(tmp_path):
    world, owner, auth, adapter, schedule, plan = bound(tmp_path)
    assert plan['end'] == '2026-01-01T09:38:22Z'
    assert plan['physicalEffectiveDate'] == '2026-01-02'
    assert field_execution.run_due(owner) == []
    with pytest.raises(ValueError, match='shared runtime'):
        field_execution.command(owner, command(owner, 'local', 'execute'))
    envelope = {**auth.state['job'], 'runId': 'TEST', 'processingAt': auth.state['clock']}
    with pytest.raises(ValueError, match='physical-day|clock'):
        adapter(envelope)
    assert water_faults.inspect(world, 'water')['current']['active']
    envelope = auth.dispatch(world, plan)
    result = adapter(envelope)
    assert result['visitDate'] == '2026-01-01' and result['effectiveDate'] == '2026-01-02'
    assert result['outcome'] == 'completed'
    assert water_faults.inspect(world, 'water')['current']['active'] is None
    with owner.db() as db:
        assert db.execute('SELECT executed_day FROM field_assignments').fetchone()[0] == '2026-01-01'
    assert field_reporting.inspect(owner)['items'][0]['visitDate'] == '2026-01-01'
    restarted = field_execution.FieldExecution(World(world.path), owner.path)
    again = field_managed.ManagedField(restarted, adapter.runtime_path, auth, utc)
    assert again(envelope) == result
    assert again.plan(request(restarted), schedule) == plan
    assert again.bind('A1', 'visit-1', 'booking-1')['jobId'] == 'visit-1'
    with pytest.raises(ValueError, match='Completed physical'):
        again.cancel('A1')
    report = [r for r in field_execution.ready(owner)['items'] if r['envelope']['schema'] == 'field-report/1'][0]
    assert report['envelope']['data']['submitted_at'] == '2026-01-02T00:00:00Z'


def test_crash_after_physical_commit_recovers_one_visit(tmp_path, monkeypatch):
    world, owner, auth, adapter, _, plan = bound(tmp_path)
    envelope = auth.dispatch(world, plan)
    original = field_execution._enqueue
    def crash(*args):
        if args[4] == 'report':
            raise RuntimeError('lost process after physical commit')
        return original(*args)
    monkeypatch.setattr(field_execution, '_enqueue', crash)
    with pytest.raises(RuntimeError):
        adapter(envelope)
    assert water_faults.inspect(world, 'water')['current']['active'] is None
    monkeypatch.setattr(field_execution, '_enqueue', original)
    # Even a later cancelled booking cannot undo or release committed work.
    auth.state['reservation']['cancelled'] = True
    result = adapter(envelope)
    assert result['visitDate'] == '2026-01-01' and result['outcome'] == 'completed'
    with world.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='PhysicalWaterLeakRepaired'").fetchone()[0] == 1
    assert adapter(envelope) == result


@pytest.mark.parametrize('change', ['crew', 'job', 'actor', 'reservation', 'missing-cancellation', 'clock', 'dependency', 'late-world'])
def test_stale_authority_fails_without_effect(tmp_path, change):
    world, owner, auth, adapter, _, plan = bound(tmp_path)
    envelope = auth.dispatch(world, plan)
    if change == 'crew':
        field_execution.command(owner, command(owner, 'crew2', 'configure-crew', expectedRevision=1))
    elif change == 'job':
        auth.state['job']['payload']['planId'] = 'forged'
    elif change == 'actor':
        envelope['actor'] = 'forged'
    elif change == 'reservation':
        auth.state['reservation']['end'] = auth.state['reservation']['start']
    elif change == 'missing-cancellation':
        del auth.state['reservation']['cancelled']
    elif change == 'clock':
        auth.state['clock'] = '2026-01-01T23:59:59Z'
    elif change == 'dependency':
        auth.state['dependencies'] = []
    else:
        world.advance('2026-01-03')
    with pytest.raises(ValueError):
        adapter(envelope)
    assert water_faults.inspect(world, 'water')['current']['active']


def test_actual_cancellation_releases_hold_but_never_repairs(tmp_path):
    world, owner, auth, adapter, _, plan = bound(tmp_path)
    with pytest.raises(ValueError, match='actual runtime'):
        adapter.cancel('A1')
    auth.state['reservation']['cancelled'] = True
    assert adapter.cancel('A1')['state'] == 'cancelled'
    assert adapter(auth.dispatch(world, plan))['state'] == 'cancelled'
    assert water_faults.inspect(world, 'water')['current']['active']
    assert field_execution.run_due(owner) == []


def test_plan_holds_daily_capacity_and_abandonment_is_explicit(tmp_path):
    world, owner, auth, adapter, schedule = configured(tmp_path)
    adapter.plan(request(owner), schedule)
    field_execution.command(owner, command(owner, 'second', assignmentId='A2', orderId='ORDER2'))
    with pytest.raises(ValueError, match='capacity'):
        adapter.plan(request(owner, assignmentId='A2'), {**schedule, 'commandId': 'plan-2', 'startTime': '11:00:00'})
    adapter.cancel('A1')
    assert adapter.plan(request(owner, assignmentId='A2'), {**schedule, 'commandId': 'plan-2'})['assignmentId'] == 'A2'


@pytest.mark.parametrize('changes', [{'shiftEnd': '09:30:00'}, {'startTime': '07:00:00'}, {'fold': True}])
def test_invalid_shift_has_no_plan(tmp_path, changes):
    _, owner, _, adapter, schedule = configured(tmp_path, **changes)
    with pytest.raises(ValueError):
        adapter.plan(request(owner), schedule)
    assert field_managed.inspect(owner)['enabled'] is False


def test_distinct_stores_and_exact_plan_binding_retries(tmp_path):
    world, owner, auth, adapter, schedule, plan = bound(tmp_path)
    for path in (world.path, owner.path):
        with pytest.raises(ValueError, match='separate'):
            field_managed.ManagedField(owner, path, auth, utc)
    with pytest.raises(ValueError, match='Conflicting managed plan'):
        adapter.plan(request(owner), {**schedule, 'startTime': '10:00:00'})
    with pytest.raises(ValueError, match='Conflicting managed binding'):
        adapter.bind('A1', 'other', 'booking-1')
    assert field_managed.inspect(owner)['items'][0]['plan'] == plan


def test_original_weekday_not_boundary_weekday(tmp_path):
    world, owner, auth, adapter, schedule = configured(tmp_path)
    field_execution.command(owner, command(owner, 'thursday', 'configure-crew', expectedRevision=1, weekdays=[3]))
    plan = adapter.plan(request(owner), schedule)
    auth.accept(adapter, plan)
    adapter.bind('A1', 'visit-1', 'booking-1')
    assert adapter(auth.dispatch(world, plan))['visitDate'] == '2026-01-01'


def test_cancellation_rechecks_concurrent_binding(tmp_path):
    _, owner, auth, adapter, schedule = configured(tmp_path)
    plan = adapter.plan(request(owner), schedule)
    auth.accept(adapter, plan)
    def concurrent_bind(job, reservation):
        adapter.authority = auth
        adapter.bind('A1', 'visit-1', 'booking-1')
        return auth(job, reservation)
    adapter.authority = concurrent_bind
    with pytest.raises(ValueError, match='binding changed'):
        adapter.cancel('A1')
    assert field_managed.inspect(owner)['items'][0]['result'] is None


def test_abandoned_plan_cannot_be_bound(tmp_path):
    _, owner, auth, adapter, schedule = configured(tmp_path)
    plan = adapter.plan(request(owner), schedule)
    adapter.cancel('A1')
    auth.accept(adapter, plan)
    with pytest.raises(ValueError, match='abandoned'):
        adapter.bind('A1', 'visit-1', 'booking-1')


def test_crew_resource_mapping_cannot_change_to_evade_overlap(tmp_path):
    _, owner, _, adapter, schedule = configured(tmp_path)
    adapter.plan(request(owner), schedule)
    adapter.cancel('A1')
    field_execution.command(owner, command(owner, 'second', assignmentId='A2', orderId='ORDER2'))
    with pytest.raises(ValueError, match='resource mapping'):
        adapter.plan(request(owner, assignmentId='A2'), {**schedule, 'commandId': 'plan-2', 'resourceId': 'different-resource'})
