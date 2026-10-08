"""One deterministic local capacity fixture; no enterprise staffing inference."""
import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from check_world_cruise import copy_database, source_hashes  # noqa: E402

from utilsim.world import World, cruise, sewer, water_faults  # noqa: E402
from utilsim.world import field_execution as field  # noqa: E402
from utilsim.world import network_faults as network  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path, help='Saved source world, read only')
    parser.add_argument('--out', required=True, type=Path, help='New output directory; existing directories are refused')
    args = parser.parse_args()
    source = args.db.resolve()
    out = args.out.resolve()
    if not source.is_file():
        raise ValueError('Source database must exist.')
    if out.exists():
        raise ValueError('Output directory already exists; choose a fresh output directory.')
    out.mkdir(parents=True, exist_ok=False)
    before = source_hashes(source)
    copy_database(source, out / 'seed.sqlite')
    seed = World(out / 'seed.sqlite')
    with seed.db() as db:
        meta = seed.metadata(db)
        snapshot = json.loads(db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()[0])
        waters = [r[0] for r in db.execute("SELECT id FROM assets WHERE commodity='water' AND installed<=? ORDER BY id", (meta['through'],))]
    start = meta['through']
    common = dict(environmentId=meta['environment'], worldFingerprint=meta['fingerprint'], actorId='world-admin',
                  expectedRevision=0, reason='Fixed deterministic capacity fixture', causalReference='capacity-fixture')
    water_faults.command(seed, {**common, 'schemaVersion': water_faults.VERSION, 'commandId': 'fixture-water-policy', 'action': 'configure',
        'annualProbability': 0, 'leakM3PerHour': '0.1', 'expectedRevision': meta.get('waterFaultPolicy', water_faults.DEFAULT_POLICY)['revision']})
    network.command(seed, {**common, 'schemaVersion': network.VERSION, 'effectiveDate': start, 'commandId': 'fixture-network-policy',
        'action': 'configure', 'annualProbability': 0, 'expectedRevision': meta.get('networkFaultPolicy', network.DEFAULT_POLICY)['revision']})
    sewer.command(seed, {**common, 'schemaVersion': sewer.VERSION, 'effectiveDate': start, 'commandId': 'fixture-sewer-policy',
        'action': 'configure', 'annualProbability': 0, 'returnFactor': '0.9', 'storageM3': '0.25', 'blockedCapacityM3PerDay': '0',
        'expectedRevision': meta.get('sewerPolicy', sewer.DEFAULT_POLICY)['revision']})
    targets = []
    with seed.db() as db:
        for asset in waters:
            if len([t for t in targets if t['operation'] == field.OPERATION]) == 9:
                break
            if not water_faults.state(db, asset)['active']:
                targets.append(dict(operation=field.OPERATION, assetId=asset))
        catalog = network._catalog(db)
        for utility in ('electric', 'gas'):
            selected = []
            for edge in catalog[0]:
                if edge['commodity'] != utility or not edge['enabled'] or network.state(db, utility, edge['id'])['active']:
                    continue
                field._target(db, meta, f'restore-{utility}-supply', edge['id'], start)
                selected.append(dict(operation=f'restore-{utility}-supply', assetId=edge['id']))
                if len(selected) == 9:
                    break
            targets.extend(selected)
        selected = []
        for asset in waters:
            service = sewer._service(db, asset, meta['environment'])
            if not sewer.state(db, service['id'])['active']:
                selected.append(dict(operation='clear-sewer-blockage', assetId=service['id'], waterAssetId=asset))
            if len(selected) == 8:
                break
        targets.extend(selected)
    assert len(targets) == 35
    for n, target in enumerate(targets):
        operation, asset = target['operation'], target['assetId']
        payload = {**common, 'commandId': f'fixture-fault-{n}', 'action': 'start'}
        with seed.db() as db:
            if operation == field.OPERATION:
                revision = water_faults.state(db, asset)['revision']
            elif operation == 'clear-sewer-blockage':
                revision = sewer.state(db, asset)['revision']
            else:
                revision = network.state(db, field.OPERATIONS[operation], asset)['revision']
        payload['expectedRevision'] = revision
        if operation == field.OPERATION:
            result = water_faults.command(seed, {**payload, 'schemaVersion': water_faults.VERSION, 'assetId': asset, 'leakM3PerHour': '0.1'})
        elif operation == 'clear-sewer-blockage':
            result = sewer.command(seed, {**payload, 'schemaVersion': sewer.VERSION, 'effectiveDate': start, 'servicePointId': asset,
                                         'waterAssetId': target['waterAssetId'], 'capacityM3PerDay': '0'})
        else:
            result = network.command(seed, {**payload, 'schemaVersion': network.VERSION, 'effectiveDate': start,
                                           'commodity': field.OPERATIONS[operation], 'edgeId': asset})
        target['faultId'] = result['faultId']
    with seed.db() as db:
        initial_digest = hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
    evidence = dict(scope='Single deterministic local capacity diagnostic, not a whole-workforce comparison or repeated-run uncertainty estimate',
        fixtureAllocation='Round-robin by fixed assignment sequence; explicit fixture assumption, not operational dispatch',
        source=str(source), sourceHashesBefore=before, premises=len(snapshot['premises']), start=start,
        preRunWorldDumpHash=initial_digest, equalExternalConditions=True, targets=targets, scenarios=[])
    for crews in (7, 5):
        path = out / f'crews-{crews}.sqlite'
        copy_database(Path(seed.path), path)
        w = World(path)
        with w.db() as db:
            assert hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest() == initial_digest
        f = field.FieldExecution(w, out / f'field-{crews}.sqlite')
        base = dict(schemaVersion=field.VERSION, environmentId=meta['environment'], worldFingerprint=meta['fingerprint'],
                    actorId='world-admin', effectiveDate=start, causalReference='capacity-fixture')
        for n in range(crews):
            field.command(f, {**base, 'commandId': f'crew-{n}', 'action': 'configure-crew', 'crewId': f'crew-{n}',
                'expectedRevision': 0, 'skills': list(field.OPERATIONS.values()), 'weekdays': list(range(7)), 'dailyCapacity': 1})
        for n, target in enumerate(targets):
            field.command(f, {**base, 'commandId': f'assign-{n}', 'action': 'accept', 'assignmentId': f'A{n}', 'orderId': f'O{n}',
                'orderRevision': 1, 'crewId': f'crew-{n % crews}', 'operation': target['operation'], 'assetId': target['assetId'],
                'scheduledDate': start, 'reportDelayDays': 0})
        cruise.command(w, {**base, 'schemaVersion': cruise.VERSION, 'commandId': 'cruise', 'action': 'start',
            'expectedRevision': 0, 'reason': 'Fixed capacity diagnostic',
            'targetDate': (date.fromisoformat(start) + timedelta(days=10)).isoformat()}, f)
        scenario = dict(crews=crews, dailyCapacityPerCrew=1, weekdays=list(range(7)), completionDay=None, daily=[])
        evidence['scenarios'].append(scenario)
        for day in range(1, 11):
            state = cruise.tick(w, f)
            assert state['status'] in ('running', 'completed'), state
            with f.db() as db:
                backlog = db.execute("SELECT COUNT(*) FROM field_assignments WHERE state='accepted'").fetchone()[0]
                pending_reports = db.execute("SELECT COUNT(*) FROM field_outbox WHERE state='pending' AND json_extract(envelope,'$.schema')='field-report/1'").fetchone()[0]
                assert db.execute('SELECT SUM(attempts) FROM field_outbox').fetchone()[0] == 0
            with w.db() as db:
                remaining = sum(bool((water_faults.state(db, t['assetId']) if t['operation'] == field.OPERATION else
                    sewer.state(db, t['assetId']) if t['operation'] == 'clear-sewer-blockage' else
                    network.state(db, field.OPERATIONS[t['operation']], t['assetId']))['active']) for t in targets)
            assert remaining == backlog
            with w.db() as db:
                flows = db.execute('SELECT * FROM sewer_flows WHERE day>=? AND day<?', (start, state['through'])).fetchall()
            for flow in flows:
                values = {k: Decimal(flow[k]) for k in ('previous_retained', 'inflow', 'transported', 'retained', 'overflow')}
                assert values['previous_retained'] + values['inflow'] == sum(values[k] for k in ('transported', 'retained', 'overflow'))
                assert all(value >= 0 for value in values.values())
            scenario['sewerConservationRowsChecked'] = len(flows)
            scenario['daily'].append(dict(day=day, through=state['through'], backlog=backlog, resolvedFaults=35-remaining,
                                         pendingReports=pending_reports, deliveredReports=0))
            if backlog == 0 and scenario['completionDay'] is None:
                scenario['completionDay'] = day
            evidence['sourceHashesUnchanged'] = source_hashes(source) == before
            (out / 'result.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        # Exact expectation for this fixed fixture, not a general staffing claim.
        assert scenario['completionDay'] == (5 if crews == 7 else 7)
    assert evidence['sourceHashesUnchanged']
    evidence['sourceHashesAfter'] = source_hashes(source)
    evidence['completed'] = True
    (out / 'result.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps([dict(crews=s['crews'], completionDay=s['completionDay']) for s in evidence['scenarios']]))


if __name__ == "__main__":
    main()
