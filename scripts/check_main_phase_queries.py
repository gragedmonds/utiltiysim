"""Bounded 25-row main-phase query diagnostic on a fresh saved-town copy.

Creates 1,000 synthetic pending assignments through public APIs. It does not
execute visits, advance physics, deliver messages, or claim enterprise scale.
Stops after reporting any page exceeding two seconds.
"""
import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from contextlib import closing, contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_world_cruise import copy_database, history, source_hashes  # noqa: E402
from check_world_main_field_phases import select_main  # noqa: E402

from utilsim.world import World, field_reporting, field_water_mains  # noqa: E402
from utilsim.world import field_execution as field  # noqa: E402
from utilsim.world.map_view import WorldMap  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path, help='Source saved world; never modified')
    parser.add_argument('--out', required=True, type=Path, help='Fresh output directory')
    parser.add_argument('--query-existing', action='store_true', help='Query the already-created isolated fixture without accepting more work')
    args = parser.parse_args()
    if args.db.resolve() == (args.out/'world.sqlite').resolve():
        parser.error('Source and copied world must be different files.')
    args.out.mkdir(parents=True, exist_ok=args.query_existing)
    began = time.perf_counter()
    original_source = source_hashes(args.db)
    target = args.out/'world.sqlite'
    if not args.query_existing:
        copy_database(args.db, target)
    elif not target.is_file() or not (args.out/'field.sqlite').is_file():
        parser.error('Existing diagnostic needs both copied world and field files.')
    world = World(target)
    owner = field.FieldExecution(world, args.out/'field.sqlite')
    with world.db() as db:
        meta = world.metadata(db)
        sequence = db.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]
        days = db.execute('SELECT COUNT(*) FROM days').fetchone()[0]
    with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro', uri=True)) as source:
        source_identity = {r[0]: json.loads(r[1]) for r in source.execute(
            "SELECT key,value FROM meta WHERE key IN ('environment','fingerprint','through')")}
    assert source_identity == {k: meta[k] for k in source_identity}, 'Source/copy identity or clock mismatch'
    old_history, old_map = history(world, meta['through'], sequence), WorldMap(world).snapshot()
    edge, _, _ = select_main(world)
    common = {'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'],
              'actorId': 'world-admin', 'effectiveDate': meta['through'], 'causalReference': 'synthetic-main-query-diagnostic'}
    result = {'scope': 'Synthetic assignment query diagnostic on copied saved town; no 15000-premise scale claim',
              'copiedPremises': len(old_map['premises']), 'syntheticAssignments': 0, 'crews': 10,
              'executedVisits': 0, 'newSimulatedDays': 0, 'newPhysicalEvents': 0, 'pages': []}
    def save():
        (args.out/'diagnostic.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    if not args.query_existing:
        for crew in range(10):
            field.command(owner, {**common, 'schemaVersion': field.VERSION, 'commandId': f'crew-{crew}',
                'action': 'configure-crew', 'crewId': f'query-crew-{crew}', 'expectedRevision': 0,
                'skills': ['water-main'], 'weekdays': list(range(7)), 'dailyCapacity': 1})
        for i in range(1000):
            if time.perf_counter()-began > 110:
                result.update(stopped='Fixture creation exceeded 110 seconds', elapsedSeconds=time.perf_counter()-began)
                save()
                print(json.dumps({'phase': 'fixture-budget', 'accepted': result['syntheticAssignments'], 'seconds': result['elapsedSeconds']}), flush=True)
                break
            phase = ('isolate', 'repair', 'restore')[i % 3]
            field_water_mains.command(owner, {**common, 'schemaVersion': field_water_mains.VERSION,
                'commandId': f'accept-{i}', 'action': 'accept', 'assignmentId': f'QUERY-{i:04}',
                'crewId': f'query-crew-{i % 10}', 'assetId': edge, 'orderId': f'SYNTHETIC-LOCAL-QUERY-{i:04}',
                'orderRevision': 1, 'scheduledDate': meta['through'], 'operation': phase+'-water-main',
                'reportDelayDays': 0, 'predecessorAssignmentId': None if i % 3 == 0 else f'QUERY-{i-1:04}'})
            result['syntheticAssignments'] += 1
    else:
        with owner.db() as db:
            result['syntheticAssignments'] = db.execute('SELECT COUNT(*) FROM field_assignments').fetchone()[0]
        result['fixtureReused'] = True
        prior = json.loads((args.out/'diagnostic.json').read_text(encoding='utf-8'))
        result['originalFixtureSeconds'] = prior.get('originalFixtureSeconds', prior.get('fixtureSeconds', prior.get('elapsedSeconds')))
        result['originalFixtureStopReason'] = prior.get('originalFixtureStopReason', prior.get('stopped'))
    total = result['syntheticAssignments']
    assert total >= 25, 'Too few accepted assignments for this diagnostic'
    result['fixtureSeconds'] = round(time.perf_counter()-began, 3)
    with owner.db() as db:
        rows = [dict(r) for r in db.execute('SELECT id,crew,payload,state,executed_day FROM field_assignments ORDER BY sequence')]
        assert len(rows) == total and all(r['state'] == 'accepted' and r['executed_day'] is None for r in rows)
        assert [r['id'] for r in rows] == [f'QUERY-{i:04}' for i in range(total)]
        assert Counter(r['crew'] for r in rows) == Counter(f'query-crew-{i % 10}' for i in range(total))
        assert db.execute('SELECT COUNT(*) FROM field_main_phases').fetchone()[0] == total
        assert db.execute('SELECT COUNT(*) FROM field_outbox').fetchone()[0] == total
    print(json.dumps({'phase': 'fixture-ready', **{k: v for k, v in result.items() if k != 'pages'}}), flush=True)
    counts = Counter()
    original_world_db, original_field_db = world.db, owner.db
    def traced(original, label):
        @contextmanager
        def wrapped():
            counts[label+'Connections'] += 1
            with original() as db:
                def trace(sql):
                    if sql.lstrip().upper().startswith('SELECT '):
                        counts[label+'Selects'] += 1
                db.set_trace_callback(trace)
                try:
                    yield db
                finally:
                    db.set_trace_callback(None)
        return wrapped
    world.db, owner.db = traced(original_world_db, 'world'), traced(original_field_db, 'field')
    slow = False
    crew_ids = []
    try:
        specifications = [('execution-admin', 'world-admin', after) for after in (0,total//2-12,total-25)]
        specifications += [('reporting-admin', 'world-admin', after) for after in (0,total//2-12,total-25)]
        specifications += [('reporting-crew', 'query-crew-0', after) for after in (0,241,491,741)]
        specifications += [('reporting-unassigned', 'unassigned-actor', 0)]
        for view, actor, after in specifications:
            counts.clear()
            before = time.perf_counter()
            page = field.inspect(owner, after=after, limit=25) if view == 'execution-admin' else field_reporting.inspect(
                owner, actor_id=actor, after=after, limit=25)
            elapsed = time.perf_counter()-before
            items = page['items']
            expected = [i for i in range(after,total) if actor == 'world-admin' or actor == f'query-crew-{i % 10}'][:25]
            ids = [item['assignment']['assignmentId'] for item in items]
            assert ids == [f'QUERY-{i:04}' for i in expected]
            for i, item in zip(expected, items, strict=True):
                prior = None if i % 3 == 0 else f'QUERY-{i-1:04}'
                assert item['phase'] == {'predecessorAssignmentId': prior}
                assert item['assignment']['predecessorAssignmentId'] == prior
                assert item['assignment']['operation'] == ('isolate','repair','restore')[i % 3]+'-water-main'
                assert item['state'] == 'accepted'
                if view == 'execution-admin':
                    assert item['result'] is None and len(item['messages']) == 1
                    assert item['messages'][0]['state'] == 'pending'
                else:
                    assert item['actualOutcome'] is None and item['claimedOutcome'] is None and item['reportId'] is None
                    assert not item['canSubmit']
                    if actor != 'world-admin':
                        assert item['blockedReason'] is None and not item['canConfigure']
            encoded = json.dumps(page)
            for secret in ['faultId', 'closedEdges', 'closed_edges', '_mainLifecycle', 'predecessorChecksum',
                           'loss_m3', 'unserved_m3', 'demand_m3', 'isolationEdges']:
                assert secret not in encoded, secret
            if actor == 'query-crew-0':
                crew_ids.extend(ids)
            measurement = {'view': view, 'actor': actor, 'after': after, 'items': len(items),
                           'firstId': ids[0] if ids else None, 'lastId': ids[-1] if ids else None,
                           'nextAfter': page['nextAfter'], 'milliseconds': round(elapsed*1000, 3), 'queryWork': dict(counts)}
            result['pages'].append(measurement)
            print(json.dumps(measurement), flush=True)
            if elapsed > 2:
                slow = True
                result['stopped'] = 'A 25-row page exceeded two seconds; further pages were not attempted.'
                save()
                break
    finally:
        world.db, owner.db = original_world_db, original_field_db
    if not slow:
        assert crew_ids == [f'QUERY-{i:04}' for i in range(0,total,10)] and len(set(crew_ids)) == len(range(0,total,10))
    with world.db() as db:
        assert db.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0] == sequence
        assert db.execute('SELECT COUNT(*) FROM days').fetchone()[0] == days
    assert source_hashes(args.db) == original_source
    assert history(world, meta['through'], sequence) == old_history
    assert WorldMap(world).snapshot() == old_map
    result.update(passed=not slow, sourceHashesUnchanged=True, historicalEventsAndObservationsPreserved=True,
                  savedMapPreserved=True, crewPaginationExactlyOnce=not slow,
                  elapsedSeconds=round(time.perf_counter()-began, 3), measuredWithSQLiteTrace=True,
                  sourceIdentityMatched=True, sourceHashes=original_source)
    save()
    print(json.dumps({k: v for k, v in result.items() if k != 'pages'}), flush=True)


if __name__ == '__main__':
    main()


