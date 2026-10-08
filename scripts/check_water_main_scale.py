"""Local physical-water diagnostic; excludes enterprise and workforce processing."""
import argparse
import json
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utilsim.world import World, hazards, sewer, water_mains  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--through', default='2026-01-03')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
    w = World(args.out/'world.sqlite')
    w.initialize(snapshot, 'MAIN-SCALE', settings={'annual_meter_failure': 0, 'annual_meter_drift': 0,
                                                'winter_mean_c': -15, 'summer_mean_c': -15, 'daily_weather_spread_c': 0})
    with w.db() as db:
        meta, cat = w.metadata(db), water_mains.catalog(db)
    common = {'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin',
              'expectedRevision': 0, 'action': 'configure', 'effectiveDate': meta['through'],
              'reason': 'Illustrative local diagnostic', 'causalReference': 'diagnostic'}
    water_mains.command(w, {**common, 'schemaVersion': water_mains.VERSION, 'commandId': 'main-policy',
                           'breaksPer100kmYear': 1000, 'lossM3PerHour': 10})
    sewer.command(w, {**common, 'schemaVersion': sewer.VERSION, 'commandId': 'sewer-policy', 'annualProbability': 0,
                      'returnFactor': '0.9', 'storageM3': '0.25', 'blockedCapacityM3PerDay': '0'})
    hazards.command(w, {**common, 'schemaVersion': hazards.VERSION, 'commandId': 'hazard-policy', 'active': True,
                        'profiles': {f: {'ageYears': 60, 'annualAgeIncrease': .1, 'coldBelowC': 0, 'coldMultiplier': 4}
                                     for f in hazards.FAMILIES}})
    started = time.perf_counter()
    w.advance('2026-01-02')
    with w.db() as db:
        broken = [dict(r) for r in db.execute("SELECT * FROM water_main_faults WHERE status='broken'")]
    isolated = 0
    for fault in broken:
        if water_mains.section(cat, fault['edge']) is None:
            continue
        water_mains.command(w, {**common, 'schemaVersion': water_mains.VERSION, 'commandId': 'isolate-'+fault['id'],
                               'action': 'isolate', 'effectiveDate': '2026-01-02', 'expectedRevision': 1,
                               'edgeId': fault['edge'], 'faultId': fault['id'], 'workOrderId': 'DIAGNOSTIC-WO'})
        isolated += 1
    w.advance(args.through)
    advance_seconds = time.perf_counter()-started
    assert isolated > 0
    started = time.perf_counter()
    view = water_mains.inspect(World(w.path), broken[0]['edge'])
    query_seconds = time.perf_counter()-started
    assert len(view['edges']) <= 25 and query_seconds < 2
    with w.db() as db:
        fault_count = db.execute('SELECT COUNT(*) FROM water_main_faults').fetchone()[0]
        effects = list(db.execute('SELECT * FROM water_main_effects'))
        assert effects and all(Decimal(e['unserved_m3']) >= 0 for e in effects)
        for row in db.execute('SELECT * FROM sewer_flows'):
            assert Decimal(row['previous_retained'])+Decimal(row['inflow']) == sum(Decimal(row[k]) for k in ('transported', 'retained', 'overflow'))
        assert not db.execute("SELECT 1 FROM water_main_days WHERE status!='broken' AND loss_m3!='0.0000'").fetchone()
        for row in db.execute("SELECT payload FROM events WHERE type='PhysicalWaterMainBroken'"):
            evidence = json.loads(row[0])['evidence']
            assert evidence['hazardDay'] and evidence['policy']['cause'] and evidence['multiplier'] > 1
    w = World(w.path)
    old = water_mains.inspect(w, broken[0]['edge'])
    w.advance(args.through)
    assert water_mains.inspect(w, broken[0]['edge']) == old
    result = {'passed': True, 'premises': len(snapshot['premises']),
              'days': (date.fromisoformat(args.through)-date.fromisoformat(meta['start'])).days, 'seededMainBreaks': fault_count,
              'explicitIsolations': isolated, 'unservedServiceDays': len(effects),
              'advanceSeconds': round(advance_seconds, 3), 'querySeconds': round(query_seconds, 3),
              'restartBoundaryReplay': True, 'sewerConservation': True}
    (args.out/'acceptance.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
