"""Isolated real-Run acceptance; never imports a private package in production.

Use --virtual-systems to select a reviewed checkout. This script creates only new
fixture databases under --out and reads the existing village pack unchanged.
"""
import argparse
import gzip
import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--virtual-systems', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise ValueError('Use a new empty acceptance directory; existing evidence is preserved.')
    args.out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.virtual_systems.resolve()))
    from synth_runtime import calendars, capacity
    from synth_runtime.store import Run

    from utilsim.world import World, delivery, field_managed, field_reporting, field_travel, water_faults
    from utilsim.world import field_execution as field
    from utilsim.world.runtime import DailyWorld, daily_commands

    pack = next((ROOT/'packs/village').glob('*.snapshot.json.gz'))
    source_hash = digest(pack)
    saved = json.loads(gzip.decompress(pack.read_bytes()))
    world = World(args.out/'world.sqlite')
    world.initialize(saved, 'MANAGED-FIELD-ACCEPTANCE', settings={'annual_meter_failure': 0, 'annual_meter_drift': 0})
    owner = field.FieldExecution(world, args.out/'field.sqlite')
    with world.db() as db:
        meta = world.metadata(db)
        assets = [r[0] for r in db.execute("SELECT id FROM assets WHERE commodity='water' ORDER BY id LIMIT 2")]
    common = {'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'],
              'effectiveDate': meta['through'], 'actorId': 'world-admin', 'causalReference': 'isolated-acceptance'}
    field.command(owner, {**common, 'schemaVersion': field.VERSION, 'commandId': 'crew-config', 'action': 'configure-crew',
        'crewId': 'crew-water', 'expectedRevision': 0, 'skills': ['plumbing'], 'weekdays': [3], 'dailyCapacity': 2})
    for index, asset in enumerate(assets, 1):
        field.command(owner, {**common, 'schemaVersion': field.VERSION, 'commandId': f'accept-{index}', 'action': 'accept',
            'assignmentId': f'A{index}', 'crewId': 'crew-water', 'assetId': asset, 'orderId': f'ORDER-{index}',
            'orderRevision': 1, 'scheduledDate': meta['through'], 'operation': field.OPERATION, 'reportDelayDays': 2})
        water_faults.command(world, {**{k: v for k, v in common.items() if k != 'effectiveDate'},
            'schemaVersion': water_faults.VERSION, 'commandId': f'leak-{index}',
            'action': 'start', 'assetId': asset, 'expectedRevision': 0, 'leakM3PerHour': '0.1',
            'reason': 'Isolated causal fixture'})
    with closing(sqlite3.connect(world.path)) as db, closing(sqlite3.connect(args.out/'baseline.sqlite')) as baseline:
        db.backup(baseline)
    baseline_hash = digest(args.out/'baseline.sqlite')
    delivery.configure(world, meta['environment'])
    run = Run(args.out/'runtime.sqlite')
    run.initialize({'schemaVersion': 'synth-run/1.0', 'runId': meta['environment'], 'seed': 'managed-acceptance',
        'start': '2026-01-01T00:00:00Z', 'timezone': 'America/New_York',
        'models': {'field': field_managed.VERSION}, 'configuration': {}, 'snapshotHash': source_hash})
    admin = run.provision_actor('admin', 'admin', [])
    producer = run.provision_actor('world-field-service', 'system', ['world:advance_day', 'field-world:execute_visit', 'workforce:reserve'])
    observations = run.provision_actor('observations', 'system', ['isu:ingest_v2'])

    def authority(job_id, reservation_id):
        # Trusted composition-root bridge, not a worker receipt. Full job and
        # dependency evidence is read under the runtime's authenticated API.
        with run.db() as db:
            actor = run.authenticate(db, producer, 'field-world:execute_visit')
            run.authenticate(db, producer, 'workforce:reserve')
            state = run.row(db)
            result = {'runId': json.loads(state['manifest'])['runId'], 'clock': state['clock'], 'actorId': actor['id']}
            if job_id is not None:
                row = db.execute('SELECT * FROM jobs WHERE id=? AND actor=?', (job_id, actor['id'])).fetchone()
                if row is None:
                    raise PermissionError('No accepted actor-owned job.')
                result['job'] = {**dict(row), 'payload': json.loads(row['payload'])}
                result['dependencies'] = [{**dict(r), 'payload': json.loads(r['payload'])} for r in db.execute(
                    'SELECT p.* FROM jobs p JOIN job_dependencies d ON p.id=d.dependency WHERE d.job=?', (job_id,))]
        if reservation_id is not None:
            bookings = capacity.query(run, producer, {'id': reservation_id}, limit=1)['rows']
            if len(bookings) != 1:
                raise PermissionError('No accepted actor-owned reservation.')
            result['reservation'] = bookings[0]
        return result

    adapter = field_managed.ManagedField(owner, run.path, authority, calendars.local_instant)
    depot = next(f['id'] for f in saved['facilities'] if f['kind'] == 'depot')
    plans = []
    day_jobs = list(daily_commands(world, '2026-01-04'))
    for day_job in day_jobs:
        run.enqueue(producer, day_job)
    for index in (1, 2):
        quote = {'schemaVersion': field_travel.VERSION, 'environmentId': meta['environment'],
                 'worldFingerprint': meta['fingerprint'], 'assignmentId': f'A{index}', 'depotId': depot,
                 'mobilisationSeconds': 300, 'workSeconds': 1800,
                 'speedsKmh': {'arterial': 60, 'collector': 40, 'local': 36}}
        schedule = {'commandId': f'plan-{index}', 'visitDate': '2026-01-01',
                    'startTime': '09:00:00' if index == 1 else '13:00:00', 'shiftStart': '08:00:00',
                    'shiftEnd': '17:00:00', 'timeZone': 'America/New_York', 'fold': None,
                    'resourceId': 'public-field:local-field:crew-water'}
        plan = adapter.plan(quote, schedule)
        plans.append(plan)
        job = {'id': f'visit-{index}', 'runId': meta['environment'], 'target': field_managed.TARGET,
               'operation': field_managed.OPERATION, 'requestedAt': '2026-01-01T00:00:00Z',
               'availableAt': plan['availableAt'], 'payload': adapter.job_payload(plan, f'booking-{index}'),
               'cause': f'accept-{index}', 'correlation': f'visit-{index}', 'dependsOn': [day_jobs[0]['id']]}
        assert run.enqueue(producer, job)['status'] == 'pending'
        booking = {'id': f'booking-{index}', 'resource': plan['resourceId'], 'job': job['id'], 'start': plan['start'], 'end': plan['end']}
        assert run.reserve(producer, booking)['status'] == 'reserved'
        assert adapter.bind(f'A{index}', job['id'], booking['id']) == adapter.bind(f'A{index}', job['id'], booking['id'])
    assert plans[0]['start'] == '2026-01-01T14:00:00Z'
    assert plans[0]['physicalEffectiveDate'] == '2026-01-02'
    assert field.run_due(owner) == []
    # Actual pre-start cancellation; the original job remains in the Run.
    capacity.cancel(run, producer, {'schemaVersion': 'capacity-cancel/1', 'id': 'cancel-2',
        'runId': meta['environment'], 'actorId': 'world-field-service', 'reservationId': 'booking-2',
        'expectedRevision': 0, 'reason': 'Fixture cancellation before crew departure',
        'requestedAt': '2026-01-01T00:00:00Z', 'cause': 'accept-2', 'correlation': 'visit-2'})
    assert adapter.cancel('A2')['state'] == 'cancelled'
    for day, time in [('2026-03-08', '02:30:00'), ('2026-11-01', '01:30:00')]:
        try:
            calendars.local_instant(day, time, 'America/New_York')
        except ValueError:
            pass
        else:
            raise AssertionError('Expected DST gap/ambiguity rejection.')
    assert calendars.local_instant('2026-11-01', '01:30:00', 'America/New_York', 0) != calendars.local_instant(
        '2026-11-01', '01:30:00', 'America/New_York', 1)

    lost = [False]
    def uncertain_reply(envelope):
        result = adapter(envelope)
        if envelope['id'] == 'visit-1' and not lost[0]:
            lost[0] = True
            raise ConnectionError('Fixture lost acknowledgement after recipient commit')
        return result
    handlers = {'world': DailyWorld(world, lambda c: run.enqueue(observations, c)),
                field_managed.TARGET: uncertain_reply, 'isu': lambda e: {'accepted': e['id'], 'fixtureOnly': True}}
    run.control(admin, 'resume')
    run.advance(admin, '2026-01-01T23:59:59Z', handlers)
    assert all(water_faults.inspect(world, a)['current']['active'] for a in assets)
    run.advance(admin, '2026-01-02T00:00:00Z', handlers)
    assert run.status(admin)['status'] == 'paused'
    assert run.status(admin, filters={'id': 'visit-1'})['jobs'][0]['status'] == 'failed'
    assert water_faults.inspect(world, assets[0])['current']['active'] is None
    first_day = world.export_v2('2026-01-01', '2026-01-02')
    # Restart both recipient and real Run; no replacement job/reservation IDs.
    owner = field.FieldExecution(World(world.path), owner.path)
    world = owner.world
    run = Run(run.path)
    adapter = field_managed.ManagedField(owner, run.path, authority, calendars.local_instant)
    handlers['world'] = DailyWorld(world, lambda c: run.enqueue(observations, c))
    run.retry(admin, 'visit-1')
    run.control(admin, 'resume')
    run.advance(admin, '2026-01-02T00:00:00Z', handlers)
    assert run.status(admin, filters={'id': 'visit-1'})['jobs'][0]['attempts'] == 2
    assert water_faults.inspect(world, assets[1])['current']['active']
    assert not [x for x in field.ready(owner)['items'] if x['envelope']['schema'] == 'field-report/1']
    assert next(r for r in field_reporting.inspect(owner)['items'] if r['assignment']['assignmentId'] == 'A1')['visitDate'] == '2026-01-01'
    run.advance(admin, '2026-01-04T00:00:00Z', handlers)
    reports = [x for x in field.ready(owner)['items'] if x['envelope']['schema'] == 'field-report/1']
    assert len(reports) == 1 and reports[0]['envelope']['data']['submitted_at'] == '2026-01-02T00:00:00Z'
    with world.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='PhysicalWaterLeakRepaired'").fetchone()[0] == 1
    assert world.export_v2('2026-01-01', '2026-01-02') == first_day
    assert digest(pack) == source_hash and digest(args.out/'baseline.sqlite') == baseline_hash
    try:
        capacity.cancel(run, producer, {'schemaVersion': 'capacity-cancel/1', 'id': 'late-cancel-1',
            'runId': meta['environment'], 'actorId': 'world-field-service', 'reservationId': 'booking-1',
            'expectedRevision': 0, 'reason': 'Must reject retroactive capacity release',
            'requestedAt': '2026-01-04T00:00:00Z', 'cause': 'visit-1', 'correlation': 'visit-1'})
    except ValueError as exc:
        assert 'Started capacity' in str(exc)
    else:
        raise AssertionError('Completed reservation was released.')
    # Wrong/revoked credentials fail at the authority boundary, before broker mutation.
    old_producer = producer
    producer = 'invalid-token'
    try:
        adapter.bind('A1', 'visit-1', 'booking-1')
    except PermissionError:
        pass
    else:
        raise AssertionError('Unauthenticated callback unexpectedly succeeded.')
    producer = old_producer
    result = {'passed': True, 'premises': len(saved['premises']), 'plannedVisits': 2, 'physicalRepairs': 1,
              'cancelledVisits': 1, 'runtimeAttempts': 2, 'reportDelayDays': 2, 'sourceAndHistoryPreserved': True,
              'timezone': 'America/New_York', 'dstGapAndFoldChecked': True,
              'privateRecipientIntegration': False, 'virtualSystemsRevision': subprocess.check_output(
                  ['git', '-C', str(args.virtual_systems), 'rev-parse', 'HEAD'], text=True).strip()}
    (args.out/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
