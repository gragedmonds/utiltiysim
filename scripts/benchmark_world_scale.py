"""Resumable physical-world scale preflight; never full-platform acceptance.

Multiple saved districts have separate environment namespaces. Account counts
describe the source snapshots; they are not evidence of enterprise onboarding.
"""
import argparse
import gzip
import hashlib
import json
import shutil
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utilsim.world import World  # noqa: E402

VERSION = 'world-scale-preflight/1'


def file_hash(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', action='append', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--start', default='2026-01-01')
    parser.add_argument('--days', type=int, default=1826)
    parser.add_argument('--minimum-accounts', type=int, default=15000)
    parser.add_argument('--max-seconds', type=float, default=300)
    parser.add_argument('--max-gib', type=float, default=30)
    parser.add_argument('--minimum-free-gib', type=float, default=10)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    if (not 1 <= args.days <= 3653 or args.minimum_accounts < 1 or
            not 0 < args.max_seconds <= 86400 or not 0 < args.max_gib <= 1000 or
            not 0 < args.minimum_free_gib <= 1000):
        parser.error('Use bounded positive budgets, 1–3653 days and a positive account target.')
    if date.fromisoformat(args.start).isoformat() != args.start:
        parser.error('Use a canonical start date.')
    return args


def run(args):
    started = time.perf_counter()
    snapshots, sources = [], []
    for path in args.snapshot:
        path = path.resolve(strict=True)
        with (gzip.open(path, 'rt', encoding='utf-8') if path.suffix == '.gz'
              else path.open(encoding='utf-8')) as stream:
            snapshot = json.load(stream)
        if snapshot.get('schemaVersion') != 'utility-town/2.0' or not snapshot.get('accounts'):
            raise ValueError('A saved full town with explicit account records is required.')
        if len({a['id'] for a in snapshot['accounts']}) != len(snapshot['accounts']):
            raise ValueError('Source account identities must be unique within each district.')
        snapshots.append(snapshot)
        sources.append({'path': str(path), 'sha256': file_hash(path), 'town': snapshot['id'],
                        'accounts': len(snapshot['accounts']), 'premises': len(snapshot['premises']),
                        'sourceServicePoints': len(snapshot['servicePoints'])})
    if (len({s['sha256'] for s in sources}) != len(sources) or
            len({s['town'] for s in sources}) != len(sources)):
        raise ValueError('Use distinct saved districts rather than counting the same source twice.')
    accounts = sum(s['accounts'] for s in sources)
    if accounts < args.minimum_accounts:
        raise ValueError(f'Sources contain {accounts} accounts, below requested {args.minimum_accounts}.')
    plan = {'schemaVersion': VERSION, 'start': args.start, 'days': args.days,
            'minimumAccounts': args.minimum_accounts, 'sources': sources,
            'scope': 'physical-world districts; no enterprise customer processing'}
    if args.resume:
        if json.loads((args.out / 'plan.json').read_text(encoding='utf-8')) != plan:
            raise ValueError('Resume must match original sources, hashes, dates and account target.')
        if not all((args.out / f'district-{index + 1}.sqlite').is_file() for index in range(len(sources))):
            raise ValueError('A saved district database is missing; do not silently recreate lost progress.')
    else:
        args.out.mkdir(parents=True, exist_ok=False)
        save(args.out / 'plan.json', plan)
    # Exclusive lock survives an interrupted process. Inspect/remove that exact
    # lock only after confirming its process is gone; never overlap two runners.
    lock = args.out / 'running.lock'
    import os
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    os.write(descriptor, str(os.getpid()).encode())
    os.close(descriptor)
    try:
        worlds = []
        for index, snapshot in enumerate(snapshots):
            owner = World(args.out / f'district-{index + 1}.sqlite')
            owner.initialize(snapshot, f'SCALE-{index + 1}-{sources[index]["sha256"][:12]}', start=args.start)
            # Initialize the derived register-cache checkpoint before timing or
            # comparing a zero-day stop/reopen. No physical day is consumed.
            worlds.append(World(owner.path))
        del snapshots
        target = date.fromisoformat(args.start) + timedelta(days=args.days)
        samples = []
        reason = 'target_reached'
        while True:
            pending = []
            for owner in worlds:
                with owner.db() as db:
                    through = date.fromisoformat(owner.metadata(db)['through'])
                if through < target:
                    pending.append((through, owner))
            if not pending:
                break
            total_bytes = sum(p.stat().st_size for p in args.out.glob('district-*.sqlite*'))
            if time.perf_counter() - started >= args.max_seconds:
                reason = 'wall_time_budget'
                break
            if total_bytes >= args.max_gib * 1024**3:
                reason = 'storage_budget'
                break
            if shutil.disk_usage(args.out).free < args.minimum_free_gib * 1024**3:
                reason = 'free_space_budget'
                break
            # Keep district dates as close as possible; complete each day's
            # existing atomic transaction even if a soft budget expires in it.
            day, owner = min(pending, key=lambda item: (item[0], item[1].path))
            tick = time.perf_counter()
            result = owner.advance((day + timedelta(days=1)).isoformat())
            elapsed = time.perf_counter() - tick
            sample = {'district': Path(owner.path).name, 'day': day.isoformat(),
                      'seconds': elapsed, 'observations': result['observations'],
                      'databaseBytes': Path(owner.path).stat().st_size}
            samples.append(sample)
            with (args.out / 'measurements.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(sample) + '\n')
            print(json.dumps(sample), flush=True)
        districts = []
        for owner in worlds:
            before = file_hash(Path(owner.path))
            owner = World(owner.path)
            with owner.db() as db:
                meta = owner.metadata(db)
                through = meta['through']
                quick_check = db.execute('PRAGMA quick_check').fetchone()[0]
                truth = db.execute('SELECT COUNT(*) FROM truth').fetchone()[0]
                observations = db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
                assets = db.execute('SELECT COUNT(*) FROM assets').fetchone()[0]
                # The production observation index supports this bounded page.
                sql = 'SELECT id,day,status FROM observations WHERE day>=? ORDER BY day,id LIMIT 25'
                latest = (date.fromisoformat(through) - timedelta(days=1)).isoformat()
                query_started = time.perf_counter()
                page = db.execute(sql, (latest,)).fetchall()
                query_seconds = time.perf_counter() - query_started
                query_plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + sql, (latest,))]
                expected = sum(max(0, (date.fromisoformat(through) -
                                      max(date.fromisoformat(row[0]), date.fromisoformat(args.start))).days)
                               for row in db.execute('SELECT installed FROM assets'))
            owner.advance(through)
            assert quick_check == 'ok'
            assert truth == observations == expected, (truth, observations, expected)
            assert len(page) <= 25
            assert file_hash(Path(owner.path)) == before, 'Completed-boundary reopen changed the database.'
            districts.append({'database': str(Path(owner.path).resolve()), 'through': through,
                              'days': (date.fromisoformat(through) - date.fromisoformat(args.start)).days,
                              'assets': assets, 'truthRows': truth, 'observationRows': observations,
                              'databaseBytes': Path(owner.path).stat().st_size,
                              'sqliteQuickCheck': quick_check, 'completedBoundaryReplayUnchanged': True,
                              'latestPageRows': len(page), 'latestPageSeconds': query_seconds,
                              'latestPageQueryPlan': query_plan})
        assert all(file_hash(Path(source['path'])) == source['sha256'] for source in sources)
        durations = [sample['seconds'] for sample in samples]
        result = {'schemaVersion': VERSION, 'scope': plan['scope'], 'integratedAcceptance': False,
                  'sourceAccounts': accounts, 'sourcePremises': sum(s['premises'] for s in sources),
                  'targetDays': args.days, 'stopReason': reason,
                  'targetReached': all(d['days'] == args.days for d in districts),
                  'invocationSeconds': time.perf_counter() - started,
                  'measuredDistrictDaysThisInvocation': len(samples),
                  'medianDistrictDaySeconds': statistics.median(durations) if durations else None,
                  'sourceHashesUnchanged': True, 'districts': districts,
                  'limits': ['Source accounts are not onboarded enterprise recipients.',
                             'Districts run sequentially in independent worlds, not one shared utility clock.',
                             'Only baseline physical demand, meter aging and observations participate.',
                             'No bills, payments, calls, field jobs, workforce or live AI are exercised.',
                             'Completed-boundary replay is not interrupted cross-system recovery.',
                             'Budgets are soft at a daily transaction boundary; no extrapolated pass.']}
        save(args.out / 'result.json', result)
        return result
    finally:
        lock.unlink()


if __name__ == '__main__':
    print(json.dumps(run(arguments()), indent=2))
