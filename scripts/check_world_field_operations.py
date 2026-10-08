"""Copied-town, four-domain field/browser acceptance. No source database writes."""
import argparse
import json
import sys
from collections import deque
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_world_cruise import Child, copy_database, history, request, source_hashes, wait_for  # noqa: E402

from utilsim.world import World, sewer, water_faults  # noqa: E402
from utilsim.world import field_execution as field  # noqa: E402
from utilsim.world import network_faults as network
from utilsim.world.map_view import WorldMap  # noqa: E402


def serial_target(world, commodity):
    """Find two genuine saved bridges on a commissioned service's supply path."""
    with world.db() as db:
        edges, services, sources = network._catalog(db)
        assets = {r['id']: dict(r) for r in db.execute('SELECT * FROM assets')}
        through = world.metadata(db)['through']
    edges = [e for e in edges if e['commodity'] == commodity]
    roots = [r['node'] for r in sources if r['commodity'] == commodity]
    adjacency = {}
    for e in edges:
        if e['enabled']:
            adjacency.setdefault(e['a'], []).append((e['b'], e['id']))
            adjacency.setdefault(e['b'], []).append((e['a'], e['id']))
    parents = {r: None for r in roots}
    queue = deque(roots)
    while queue:
        node = queue.popleft()
        for other, edge in adjacency.get(node, []):
            if other not in parents:
                parents[other] = (node, edge)
                queue.append(other)
    for service in services:
        asset = assets[service['asset']]
        if (service['commodity'] != commodity or asset['installed'] > through
                or asset['condition'] != 'healthy' or not json.loads(asset['profile']).get('occupied', True)):
            continue
        node, bridges = service['node'], []
        while parents[node] is not None:
            previous, edge = parents[node]
            if service['node'] not in network._reachable(edges, roots, [edge])[0]:
                bridges.append(edge)
            node = previous
            if len(bridges) == 2:
                return {'asset': service['asset'], 'edges': bridges}
    raise AssertionError(f'Need two serial enabled bridges for a healthy {commodity} service.')


def setup_faults(world):
    with world.db() as db:
        meta = world.metadata(db)
        waters = [dict(r) for r in db.execute("SELECT * FROM assets WHERE commodity='water' AND installed<=? ORDER BY id", (meta['through'],))]
    water = next(a['id'] for a in waters if json.loads(a['profile']).get('occupied', True))
    common = {'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'],
              'actorId': 'world-admin', 'expectedRevision': 0, 'reason': 'Explicit copied-town manual acceptance fault',
              'causalReference': 'field-operations-acceptance'}
    dated = {**common, 'effectiveDate': meta['through']}
    network.command(world, {**dated, 'schemaVersion': network.VERSION, 'commandId': 'policy-network',
                            'action': 'configure', 'annualProbability': 0,
                            'expectedRevision': meta.get('networkFaultPolicy', network.DEFAULT_POLICY)['revision']})
    water_faults.command(world, {**common, 'schemaVersion': water_faults.VERSION, 'commandId': 'policy-water',
                               'action': 'configure', 'annualProbability': 0, 'leakM3PerHour': '0.1',
                               'expectedRevision': meta.get('waterFaultPolicy', water_faults.DEFAULT_POLICY)['revision']})
    sewer.command(world, {**dated, 'schemaVersion': sewer.VERSION, 'commandId': 'policy-sewer', 'action': 'configure',
                         'annualProbability': 0, 'returnFactor': '0.9', 'storageM3': '0.25', 'blockedCapacityM3PerDay': '0',
                         'expectedRevision': meta.get('sewerPolicy', sewer.DEFAULT_POLICY)['revision']})
    targets = {u: serial_target(world, u) for u in ['electric', 'gas']}
    faults = {}
    for commodity, target in targets.items():
        for i, edge in enumerate(target['edges']):
            with world.db() as db:
                revision = network.state(db, commodity, edge)['revision']
            faults[f'{commodity}-{i}'] = network.command(world, {**dated, 'schemaVersion': network.VERSION,
                'commandId': f'fault-{commodity}-{i}', 'action': 'start', 'commodity': commodity, 'edgeId': edge,
                'expectedRevision': revision})['faultId']
    faults['water'] = water_faults.command(world, {**common, 'schemaVersion': water_faults.VERSION,
        'commandId': 'fault-water', 'action': 'start', 'assetId': water, 'leakM3PerHour': '0.1',
        'expectedRevision': water_faults.inspect(world, water)['current']['revision']})['faultId']
    view = sewer.inspect(world, water)
    faults['sewer'] = sewer.command(world, {**dated, 'schemaVersion': sewer.VERSION,
        'commandId': 'fault-sewer', 'action': 'start', 'waterAssetId': water, 'servicePointId': view['service']['id'],
        'capacityM3PerDay': '0', 'expectedRevision': view['current']['revision']})['faultId']
    visits = [('electric-0', 'restore-electric-supply', targets['electric']['edges'][0]),
              ('gas-0', 'restore-gas-supply', targets['gas']['edges'][0]),
              ('water', 'repair-water-leak', water), ('sewer', 'clear-sewer-blockage', view['service']['id']),
              ('electric-1', 'restore-electric-supply', targets['electric']['edges'][1]),
              ('gas-1', 'restore-gas-supply', targets['gas']['edges'][1])]
    return targets, water, faults, visits


def assert_physics(world, control, targets, water, day):
    evidence = {}
    with world.db() as db, control.db() as baseline:
        for commodity, restored_day in [('electric', 4), ('gas', 5)]:
            asset = targets[commodity]['asset']
            observations = []
            for i in range(6):
                observed = db.execute('SELECT quantity,status FROM observations WHERE asset=? AND day=?', (asset, day(i))).fetchone()
                normal = baseline.execute('SELECT quantity,status FROM observations WHERE asset=? AND day=?', (asset, day(i))).fetchone()
                assert observed['status'] == normal['status'] and observed['quantity'] is not None
                effect = db.execute('SELECT * FROM network_fault_effects WHERE asset=? AND day=?', (asset, day(i))).fetchone()
                if i < restored_day:
                    assert Decimal(observed['quantity']) == 0
                    assert effect and Decimal(effect['demand_quantity']) > 0
                    assert effect['unserved_quantity'] == effect['demand_quantity']
                else:
                    assert tuple(observed) == tuple(normal) and Decimal(observed['quantity']) > 0
                    assert effect is None
                observations.append({'day': day(i), 'quantity': observed['quantity'], 'remainingFaultsKeepSupplyOff': i < restored_day})
            evidence[commodity] = observations
        flows = [dict(r) for r in db.execute('SELECT * FROM sewer_flows WHERE water_asset=? AND day>=? ORDER BY day', (water, day(0)))]
        assert len(flows) == 6
        for i, flow in enumerate(flows):
            d = {k: Decimal(flow[k]) for k in ['inflow', 'previous_retained', 'transported', 'retained', 'overflow', 'water_quantity', 'excluded_leak', 'return_factor']}
            assert d['previous_retained'] + d['inflow'] == d['transported'] + d['retained'] + d['overflow']
            assert d['inflow'] == ((d['water_quantity']-d['excluded_leak'])*d['return_factor']).quantize(Decimal('.0001'))
            assert all(d[k] >= 0 for k in ['inflow', 'transported', 'retained', 'overflow'])
            if i < 3:
                assert d['transported'] == 0 and flow['fault_id']
            else:
                assert d['retained'] == d['overflow'] == 0 and flow['fault_id'] is None
            assert (d['excluded_leak'] > 0) == (i < 2)
        assert Decimal(flows[3]['previous_retained']) > 0
        evidence['sewer'] = flows
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--viewer-dir', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    source_before = source_hashes(args.db)
    target, baseline_path = args.out/'world.sqlite', args.out/'baseline.sqlite'
    copy_database(args.db, target)
    copy_database(args.db, baseline_path)
    world, baseline = World(target), World(baseline_path)
    with world.db() as db:
        meta = world.metadata(db)
        sequence = db.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]
    snapshot = WorldMap(world).snapshot()
    original_history = history(world, meta['through'], sequence)
    start = date.fromisoformat(meta['through'])
    def day(n):
        return (start+timedelta(days=n)).isoformat()
    targets, water, faults, visits = setup_faults(world)
    owner = field.FieldExecution(world, args.out/'field.sqlite')
    children, errors, external = [], [], []
    from playwright.sync_api import expect, sync_playwright
    try:
        child = Child(args, target, 'interrupted-server', interrupt=True)
        children.append(child)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda req: external.append(req.url) if not req.url.startswith('http://127.0.0.1:') else None)
                page.goto(child.base+'/field-execution')
                expect(page.locator('#crew button')).to_be_enabled()
                page.locator('#crew [name=crewId]').fill('acceptance-multiskill')
                page.locator('#crew [name=crewId]').dispatch_event('change')
                for name in ['skillPlumbing', 'skillElectric', 'skillGas', 'skillSewer']:
                    page.locator(f'#crew [name={name}]').check()
                page.locator('#crew [name=dailyCapacity]').fill('1')
                page.locator('#crew [name=weekdays]').select_option('0,1,2,3,4,5,6')
                page.locator('#crew button').click()
                expect(page.locator('#message')).to_contain_text('Field command recorded')
                page.reload()
                for name in ['skillPlumbing', 'skillElectric', 'skillGas', 'skillSewer']:
                    expect(page.locator(f'#crew [name={name}]')).to_be_checked()
                expect(page.locator('#crew [name=weekdays]')).to_have_value('0,1,2,3,4,5,6')
                expect(page.locator('#crew [name=dailyCapacity]')).to_have_value('1')
                lost = []
                def lose_accept_reply(route):
                    if route.request.method == 'POST' and route.request.post_data_json.get('action') == 'accept':
                        response = route.fetch()
                        assert response.ok, response.text()
                        lost.append({'command': route.request.post_data_json, 'result': response.json()})
                        route.abort()
                    else:
                        route.continue_()
                for i, (_key, operation, asset) in enumerate(visits):
                    page.locator('#assignment [name=operation]').select_option(operation)
                    for name, value in {'assignmentId': f'OPS-{i}', 'crewId': 'acceptance-multiskill', 'assetId': asset,
                        'orderId': f'SYNTHETIC-OPS-{i}', 'orderRevision': '1', 'scheduledDate': day(0), 'reportDelayDays': '2'}.items():
                        page.locator(f'#assignment [name={name}]').fill(value)
                    if i == 0:
                        page.route('**/api/field-execution', lose_accept_reply)
                    page.locator('#assignment button').click()
                    if i == 0:
                        expect(page.locator('#message')).to_contain_text('outcome is uncertain')
                        page.unroute('**/api/field-execution', lose_accept_reply)
                        page.reload()
                        expect(page.locator('#retry')).to_be_visible()
                        expect(page.locator('#assignment [name=operation]')).to_have_value(operation)
                        expect(page.locator('#assignment [name=assetId]')).to_have_value(asset)
                        page.locator('#retry').click()
                    expect(page.locator('#message')).to_contain_text('Field command recorded')
                rows = field.inspect(owner)['items']
                assert len(rows) == 6 and all(row['state'] == 'accepted' for row in rows)
                assert len(lost) == 1
                assert request(child.base, '/api/field-execution', lost[0]['command']) == lost[0]['result']
                page.screenshot(path=str(args.out/'field-accepted-1440.png'), full_page=True)
                for n in range(6):
                    page.goto(child.base+'/cruise')
                    expect(page.locator('#start')).to_be_enabled()
                    page.locator('#targetDate').fill(day(n+1))
                    page.locator('#reason').fill('One-day copied-town four-domain field acceptance')
                    page.locator('#start').click()
                    if n == 0:
                        wait_for(lambda child=child: child.process.poll() is not None, 'Injected electric report interruption missing')
                        assert child.process.returncode == 86
                        with world.db() as db:
                            assert db.execute("SELECT COUNT(*) FROM events WHERE type='PhysicalNetworkRestored' AND subject=?", (visits[0][2],)).fetchone()[0] == 1
                        assert field.inspect(owner)['items'][0]['state'] == 'accepted'
                        child = Child(args, target, 'restarted-server', port=child.port)
                        children.append(child)
                    wait_for(lambda child=child, n=n: (state := request(child.base))['status'] == 'completed' and state['through'] == day(n+1), 'One-day cruise did not complete')
                    assert request(child.base)['through'] == day(n+1)
                    rows = field.inspect(owner)['items']
                    assert sum(row['state'] == 'executed' for row in rows) == n+1
                    assert all(row['result']['effectiveDate'] == day(i) for i, row in enumerate(rows[:n+1]))
                page.goto(child.base+'/field-execution')
                expect(page.locator('#history')).to_contain_text('completed')
                for width, height in [(1440, 1000), (1024, 768)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(args.out/f'field-completed-{width}.png'), full_page=True)
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        rows = field.inspect(owner)['items']
        assert all(message['state'] == 'pending' for row in rows for message in row['messages'])
        assert all(row['result']['outcome'] == 'completed' for row in rows)
        with world.db() as db:
            physical = [json.loads(r[0]) for r in db.execute("SELECT payload FROM events WHERE type IN ('PhysicalNetworkRestored','PhysicalSewerCleared','PhysicalWaterLeakRepaired')")]
            for fault in faults.values():
                assert sum(p.get('faultId') == fault for p in physical) == 1
            assert not db.execute("SELECT name FROM sqlite_master WHERE name IN ('payments','invoices','work_orders')").fetchall()
        with owner.db() as db:
            assert db.execute('SELECT COUNT(*) FROM field_assignments').fetchone()[0] == 6
            assert db.execute('SELECT COUNT(*) FROM field_outbox').fetchone()[0] == 12
        baseline.advance(day(6))
        physics = assert_physics(world, baseline, targets, water, day)
        assert source_hashes(args.db) == source_before
        assert history(world, meta['through'], sequence) == original_history
        assert WorldMap(world).snapshot() == snapshot
        evidence = {'passed': True, 'premises': len(snapshot['premises']), 'from': day(0), 'through': day(6),
                    'operations': sorted(field.OPERATIONS), 'fieldVisits': 6, 'dailySharedCapacity': 1,
                    'oneDayCruiseRuns': 6, 'pendingMessages': 12, 'physicalEventsPerFault': 1,
                    'lostAcceptReplyRetriedExactly': True, 'electricRepairProcessExit': 86,
                    'sourceHashesUnchanged': True, 'historicalEventsAndObservationsPreserved': True,
                    'savedMapPreserved': True, 'browserErrors': errors, 'viewports': [1440, 1024],
                    'downstreamEvidence': physics, 'childPids': [c.process.pid for c in children]}
        (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({k: v for k, v in evidence.items() if k != 'downstreamEvidence'}))
    finally:
        for child in reversed(children):
            child.close()
        assert all(c.process.poll() is not None for c in children)


if __name__ == '__main__':
    main()



