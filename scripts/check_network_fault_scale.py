"""Measure paginated supply-fault inspection and one physical day on a new world."""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utilsim.world import World, network_faults  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--start', default='2026-01-01')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
    world = World(args.out/'world.sqlite')
    world.initialize(snapshot, 'NETWORK-SCALE', start=args.start,
                     settings={'annual_meter_failure': 0, 'annual_meter_drift': 0})
    edge = next(e['id'] for e in snapshot['networks']['electric']['edges'] if e.get('kind') == 'supply')
    started = time.perf_counter()
    first = network_faults.inspect(world, edge=edge)
    initial_seconds = time.perf_counter()-started
    payload = {'schemaVersion': network_faults.VERSION, 'commandId': 'supply-fault',
               'environmentId': first['environmentId'], 'worldFingerprint': first['worldFingerprint'],
               'actorId': 'world-admin', 'expectedRevision': 0, 'effectiveDate': first['through'],
               'action': 'start', 'reason': 'Saved-topology scale acceptance', 'causalReference': 'acceptance',
               'commodity': 'electric', 'edgeId': edge}
    network_faults.command(world, payload)
    started = time.perf_counter()
    active = network_faults.inspect(world, edge=edge)
    active_seconds = time.perf_counter()-started
    assert active['interruptedServices'] == first['additionalInterruptedServices']
    seen, cursor = set(), ''
    while True:
        page = network_faults.inspect(world, edge=edge, service_after=cursor)
        identities = {s['asset'] for s in page['affectedSample']}
        assert not seen & identities
        seen |= identities
        cursor = page['nextServiceAfter']
        if not cursor:
            break
    assert len(seen) == active['affectedServiceCount']
    started = time.perf_counter()
    world.advance(str(date.fromisoformat(args.start)+timedelta(days=1)))
    day_seconds = time.perf_counter()-started
    with world.db() as db:
        assert db.execute('SELECT COUNT(*) FROM network_fault_effects').fetchone()[0] == len(seen)
        assert not db.execute("SELECT 1 FROM network_fault_effects e JOIN truth t ON t.asset=e.asset AND t.day=e.day "
                              "WHERE t.quantity!='0.0000'").fetchone()
        assert db.execute("SELECT COUNT(*) FROM truth t JOIN assets a ON a.id=t.asset WHERE a.commodity='water' "
                          "AND CAST(t.quantity AS REAL)>0").fetchone()[0] > 0
    evidence = {'passed': True, 'premises': len(snapshot['premises']), 'interruptedCommissionedServices': len(seen),
                'initialInspectionSeconds': round(initial_seconds, 3), 'activeInspectionSeconds': round(active_seconds, 3),
                'daySeconds': round(day_seconds, 3), 'queryTargetSeconds': 2}
    assert initial_seconds < 2 and active_seconds < 2, evidence
    (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
