"""Local diagnostic for explainable hazard progression; not a full-platform scale claim."""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utilsim.world import World, hazards, network_faults, sewer, water_faults  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--through', default='2026-01-03')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
    w = World(args.out/'world.sqlite')
    w.initialize(snapshot, 'HAZARD-SCALE', settings={'annual_meter_failure': 0, 'annual_meter_drift': 0})
    with w.db() as db:
        meta = w.metadata(db)
    common = {'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin',
              'expectedRevision': 0, 'action': 'configure', 'reason': 'Local diagnostic assumptions', 'causalReference': 'diagnostic'}
    for owner, extra in [(network_faults, {}), (water_faults, {'leakM3PerHour': '0.02'}),
                         (sewer, {'returnFactor': '0.9', 'storageM3': '0.25', 'blockedCapacityM3PerDay': '0'})]:
        owner.command(w, {**common, 'schemaVersion': owner.VERSION, 'commandId': owner.VERSION+'-baseline',
                          **({} if owner is water_faults else {'effectiveDate': meta['through']}),
                          'annualProbability': .1, **extra})
    hazards.command(w, {**common, 'schemaVersion': hazards.VERSION, 'commandId': 'hazard-policy',
                        'effectiveDate': meta['through'], 'active': True,
                        'profiles': {f: {'ageYears': 60, 'annualAgeIncrease': .1, 'coldBelowC': 10, 'coldMultiplier': 4}
                                     for f in hazards.FAMILIES}})
    started = time.perf_counter()
    w.advance(args.through)
    advance_seconds = time.perf_counter()-started
    started = time.perf_counter()
    view = hazards.inspect(World(w.path))
    query_seconds = time.perf_counter()-started
    days = (date.fromisoformat(args.through)-date.fromisoformat(meta['start'])).days
    expected_age = 60+days/365.2425
    assert all(abs(a-expected_age) < 1e-10 for a in view['currentAges'].values())
    assert query_seconds < 2 and len(view['history']) <= 25
    with w.db() as db:
        assert db.execute('SELECT COUNT(*) FROM hazard_days').fetchone()[0] == days
        counts = {}
        for table in ('network_faults', 'water_faults', 'sewer_faults'):
            counts[table] = db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
            assert not db.execute('SELECT 1 FROM '+table+' f LEFT JOIN hazard_days h ON f.cause=h.event_id '
                                  'WHERE h.event_id IS NULL LIMIT 1').fetchone()
        assert not db.execute("SELECT 1 FROM assets WHERE commodity='sewer'").fetchone()
    # Reopening and requesting the completed boundary must have no new effects.
    w = World(w.path)
    old = hazards.inspect(w)
    w.advance(args.through)
    assert hazards.inspect(w) == old
    result = {'passed': True, 'premises': len(snapshot['premises']), 'days': days,
              'advanceSeconds': round(advance_seconds, 3), 'querySeconds': round(query_seconds, 3),
              'ageYears': expected_age, 'faultsWithDailyCauses': counts, 'restartBoundaryReplay': True}
    (args.out/'acceptance.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
