"""Copied-town acceptance for three independent water-main field visits."""
import argparse
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_world_cruise import copy_database, history, request, source_hashes, wait_for  # noqa: E402
from check_world_field_reporting import Child  # noqa: E402

from utilsim.world import World, sewer, water_faults, water_mains  # noqa: E402
from utilsim.world import field_execution as field  # noqa: E402
from utilsim.world.map_view import WorldMap  # noqa: E402


def main_command(world, identity, action, **changes):
    with world.db() as db:
        meta = world.metadata(db)
    return {'schemaVersion': water_mains.VERSION, 'commandId': identity, 'environmentId': meta['environment'],
            'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin', 'effectiveDate': meta['through'],
            'expectedRevision': 0, 'action': action, 'reason': 'Copied-town phase acceptance',
            'causalReference': 'main-field-acceptance', **changes}


def select_main(world):
    with world.db() as db:
        meta, catalog = world.metadata(db), water_mains.catalog(db)
        assets = {r['id']: dict(r) for r in db.execute('SELECT * FROM assets WHERE installed<=?', (meta['through'],))}
    for edge in catalog['edges']:
        if edge['kind'] not in ('trunk', 'distribution') or not edge['enabled']:
            continue
        closed = water_mains.section(catalog, edge['id'])
        if not closed:
            continue
        reached = water_mains._supply(catalog, [{'status': 'isolated', 'closed_edges': json.dumps(closed)}])
        affected = [s for s in catalog['services'] if s['node'] not in reached and s['asset'] in assets]
        occupied = [s['asset'] for s in affected if assets[s['asset']]['condition'] == 'healthy'
                    and json.loads(assets[s['asset']]['profile']).get('occupied', True)]
        if len(affected) >= 5 and occupied:
            return edge['id'], affected, occupied[0]
    raise AssertionError('Need a saved valve-bounded main with five commissioned services.')


def configure_physics(world, asset):
    with world.db() as db:
        meta = world.metadata(db)
    common = {'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'],
              'actorId': 'world-admin', 'reason': 'Explicit copied acceptance fixture',
              'causalReference': 'main-field-acceptance', 'expectedRevision': 0}
    water_mains.command(world, main_command(world, 'main-policy', 'configure', breaksPer100kmYear=0,
        lossM3PerHour=10, expectedRevision=meta.get('waterMainPolicy', water_mains.DEFAULT_POLICY)['revision']))
    sewer.command(world, {**common, 'schemaVersion': sewer.VERSION, 'commandId': 'sewer-policy', 'action': 'configure',
        'effectiveDate': meta['through'], 'annualProbability': 0, 'returnFactor': '0.9', 'storageM3': '0.25',
        'blockedCapacityM3PerDay': '0', 'expectedRevision': meta.get('sewerPolicy', sewer.DEFAULT_POLICY)['revision']})
    water_faults.command(world, {**common, 'schemaVersion': water_faults.VERSION, 'commandId': 'leak-policy',
        'action': 'configure', 'annualProbability': 0, 'leakM3PerHour': '1',
        'expectedRevision': meta.get('waterFaultPolicy', water_faults.DEFAULT_POLICY)['revision']})
    water_faults.command(world, {**common, 'schemaVersion': water_faults.VERSION, 'commandId': 'downstream-leak',
        'action': 'start', 'assetId': asset, 'leakM3PerHour': '1',
        'expectedRevision': water_faults.inspect(world, asset)['current']['revision']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--viewer-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    original_source = source_hashes(args.db)
    target, baseline_path = args.out/'world.sqlite', args.out/'baseline.sqlite'
    copy_database(args.db, target)
    copy_database(args.db, baseline_path)
    world, baseline = World(target), World(baseline_path)
    with world.db() as db:
        meta = world.metadata(db)
        sequence = db.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]
    original_map, old_history = WorldMap(world).snapshot(), history(world, meta['through'], sequence)
    start = date.fromisoformat(meta['through'])
    def day(n):
        return (start+timedelta(days=n)).isoformat()
    edge, affected, asset = select_main(world)
    configure_physics(world, asset)
    configure_physics(baseline, asset)
    first = water_mains.command(world, main_command(world, 'first-break', 'start', edgeId=edge,
        lossM3PerHour=10, expectedRevision=water_mains.inspect(world, edge)['selected']['revision']))
    world.advance(day(1))
    assert water_mains.inspect(world, edge)['losses'][0]['loss_m3'] == '240.0000'
    owner = field.FieldExecution(world, args.out/'field.sqlite')
    children, errors, external, lost = [], [], [], []
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
                page.locator('#crew [name=crewId]').fill('main-crew')
                page.locator('#crew [name=crewId]').dispatch_event('change')
                page.locator('#crew [name=skillPlumbing]').uncheck()
                page.locator('#crew [name=skillWaterMain]').check()
                page.locator('#crew [name=dailyCapacity]').fill('1')
                page.locator('#crew [name=weekdays]').select_option('0,1,2,3,4,5,6')
                page.locator('#crew button').click()
                expect(page.locator('#message')).to_contain_text('recorded')
                def lose_accept_reply(route):
                    if route.request.method == 'POST':
                        response = route.fetch()
                        assert response.ok, response.text()
                        lost.append({'command': route.request.post_data_json, 'result': response.json()})
                        route.abort()
                    else:
                        route.continue_()
                def accept_chain(prefix, scheduled, lose=False):
                    page.goto(child.base+'/field-execution')
                    for i, phase in enumerate(['isolate', 'repair', 'restore']):
                        page.locator('#operation').select_option(phase+'-water-main')
                        for name, value in {'assignmentId': prefix+'-'+phase, 'crewId': 'main-crew', 'assetId': edge,
                            'orderId': 'SYNTHETIC-'+prefix+'-'+phase, 'orderRevision': '1', 'scheduledDate': scheduled,
                            'reportDelayDays': '2'}.items():
                            page.locator(f'#assignment [name={name}]').fill(value)
                        if i:
                            page.locator('#predecessorAssignmentId').fill(prefix+'-'+['isolate', 'repair'][i-1])
                        if lose and i == 1:
                            page.route('**/api/field-main-phases', lose_accept_reply)
                        page.locator('#assignment button').click()
                        if lose and i == 1:
                            expect(page.locator('#message')).to_contain_text('uncertain')
                            page.unroute('**/api/field-main-phases', lose_accept_reply)
                            page.reload()
                            expect(page.locator('#retry')).to_be_visible()
                            expect(page.locator('#predecessorAssignmentId')).to_have_value(prefix+'-isolate')
                            page.locator('#retry').click()
                        expect(page.locator('#message')).to_contain_text('recorded')
                def manual_isolation(prefix, mode):
                    page.goto(child.base+'/field-reporting')
                    page.locator('#assignmentSelect').select_option(prefix+'-isolate')
                    page.locator('#reportMode').select_option('manual')
                    page.locator('#workMode').select_option(mode)
                    page.locator('#configure').click()
                    expect(page.locator('#message')).to_contain_text('recorded')
                def start_cruise(target_day):
                    page.goto(child.base+'/cruise')
                    expect(page.locator('#start')).to_be_enabled()
                    page.locator('#targetDate').fill(target_day)
                    page.locator('#reason').fill('Bounded copied-town main phase acceptance')
                    page.locator('#start').click()
                def finished(target_day):
                    wait_for(lambda: (s := request(child.base))['status'] == 'completed' and s['through'] == target_day,
                             'Cruise did not finish its bounded target')
                accept_chain('ACTUAL', day(1), lose=True)
                assert len(lost) == 1
                assert request(child.base, '/api/field-main-phases', lost[0]['command']) == lost[0]['result']
                manual_isolation('ACTUAL', 'perform')
                start_cruise(day(2))
                wait_for(lambda: child.process.poll() is not None, 'Post-isolation process interruption missing')
                assert child.process.returncode == 86
                assert water_mains.inspect(world, edge)['selected']['active']['status'] == 'isolated'
                assert field.inspect(owner)['items'][0]['state'] == 'accepted'
                child = Child(args, target, 'restarted-server', port=child.port)
                children.append(child)
                finished(day(2))
                actual = field.inspect(owner)['items']
                assert actual[0]['result']['effectiveDate'] == day(1)
                assert actual[0]['result']['reportId'] is None
                assert all(r['state'] == 'accepted' for r in actual[1:])
                for offset, status in [(3, 'repaired'), (4, None)]:
                    start_cruise(day(offset))
                    finished(day(offset))
                    active = water_mains.inspect(world, edge)['selected']['active']
                    assert (active['status'] if active else None) == status
                    assert water_mains.inspect(world)['interruptedServices'] == (len(affected) if status else 0)
                actual = field.inspect(owner)['items']
                assert [r['result']['effectiveDate'] for r in actual] == [day(1), day(2), day(3)]
                assert actual[0]['result']['reportId'] is None
                second = water_mains.command(world, main_command(world, 'second-break', 'start', edgeId=edge,
                    lossM3PerHour=10, expectedRevision=water_mains.inspect(world, edge)['selected']['revision']))
                accept_chain('CLAIM', day(4))
                manual_isolation('CLAIM', 'inspect-only')
                start_cruise(day(5))
                finished(day(5))
                page.goto(child.base+'/field-reporting')
                page.locator('#assignmentSelect').select_option('CLAIM-isolate')
                page.locator('#claimedOutcome').select_option('completed')
                page.locator('#submitReport').click()
                expect(page.locator('#message')).to_contain_text('recorded')
                assert water_mains.inspect(world, edge)['selected']['active']['status'] == 'broken'
                page.screenshot(path=str(args.out/'false-isolation-claim-1440.png'), full_page=True)
                start_cruise(day(7))
                finished(day(7))
                rows = field.inspect(owner)['items']
                assert len(rows) == 6 and rows[3]['result']['outcome'] == 'not_attempted'
                assert all(r['state'] == 'accepted' and r['blockedReason'] for r in rows[4:])
                assert water_mains.inspect(world, edge)['selected']['active']['id'] == second['faultId']
                page.goto(child.base+'/field-execution')
                expect(page.locator('#history')).to_contain_text('CLAIM-restore')
                for width, height in [(1440, 1000), (1024, 768)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(args.out/f'phase-backlog-{width}.png'), full_page=True)
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        baseline.advance(day(7))
        with world.db() as db, baseline.db() as control:
            events = [json.loads(r[0]) for r in db.execute("SELECT payload FROM events WHERE type='WaterMainPhysicalAction'")]
            assert len(events) == 3
            assert sorted(p['action'] for p in events) == ['isolate', 'repair', 'restore']
            assert all(p['faultId'] == first['faultId'] for p in events)
            for offset in range(7):
                observed = db.execute('SELECT quantity FROM observations WHERE asset=? AND day=?', (asset, day(offset))).fetchone()[0]
                normal = control.execute('SELECT quantity FROM observations WHERE asset=? AND day=?', (asset, day(offset))).fetchone()[0]
                leak = Decimal(db.execute('SELECT leak_quantity FROM water_fault_effects WHERE asset=? AND day=?', (asset, day(offset))).fetchone()[0])
                effects = list(db.execute('SELECT * FROM water_main_effects WHERE day=?', (day(offset),)))
                if offset in (1, 2):
                    assert Decimal(observed) == leak == 0 and len(effects) == len(affected)
                    assert all(e['unserved_m3'] == e['demand_m3'] for e in effects)
                    assert sum(Decimal(e['unserved_m3']) for e in effects) > 0
                    for service in affected:
                        assert Decimal(db.execute('SELECT inflow FROM sewer_flows WHERE water_asset=? AND day=?', (service['asset'], day(offset))).fetchone()[0]) == 0
                else:
                    assert observed == normal and leak == 24 and not effects
                losses = list(db.execute('SELECT loss_m3 FROM water_main_days WHERE day=?', (day(offset),)))
                assert sum(Decimal(r[0]) for r in losses) == (240 if offset in (0,4,5,6) else 0)
            for flow in db.execute('SELECT * FROM sewer_flows WHERE day>=?', (day(0),)):
                assert Decimal(flow['previous_retained'])+Decimal(flow['inflow']) == sum(Decimal(flow[k]) for k in ('transported','retained','overflow'))
        rows = field.inspect(owner)['items']
        assert all(m['state'] == 'pending' for row in rows for m in row['messages'])
        inbox = {}
        def receive(envelope):
            identity = envelope['id']
            receipt = {'id': identity, 'environmentId': envelope['instance_id'], 'checksum': field.checksum(envelope),
                       'status': 'received', 'receiptId': 'test-inbox-'+identity}
            if identity in inbox:
                assert inbox[identity] == receipt
            inbox[identity] = receipt
            return receipt
        field.relay(owner, receive, limit=100)
        assert len(inbox) == 9
        assert all(m['state'] == 'received' for row in field.inspect(owner)['items'] for m in row['messages'])
        assert field.run_due(owner) == []
        assert all(r['state'] == 'accepted' for r in field.inspect(owner)['items'][4:])
        assert water_mains.inspect(world, edge)['selected']['active']['status'] == 'broken'
        (args.out/'test-inbox.json').write_text(json.dumps(inbox, indent=2)+'\n', encoding='utf-8')
        assert source_hashes(args.db) == original_source
        assert WorldMap(world).snapshot() == original_map
        assert history(world, meta['through'], sequence) == old_history
        evidence = {'passed': True, 'premises': len(original_map['premises']), 'edge': edge, 'affectedServices': len(affected),
                    'from': day(0), 'through': day(7), 'phaseVisits': 3, 'inspectOnlyVisits': 1, 'blockedSuccessors': 2,
                    'dailyCapacity': 1, 'lostAcceptReplyReloadRetry': True, 'isolationCrashExit': 86,
                    'originalVisitDateRecovered': True, 'physicalEventsPerPhase': 1,
                    'missingReportDoesNotBlockActualSuccessors': True, 'falseClaimDoesNotUnlockSuccessors': True,
                    'mainLossUnbilled': True, 'sewerConserved': True, 'testInboxMessages': 9, 'actualEnterpriseAdapterTested': False,
                    'sourceHashesUnchanged': True, 'historicalEventsAndObservationsPreserved': True, 'savedMapPreserved': True,
                    'browserErrors': errors, 'viewports': [1440,1024], 'childPids': [c.process.pid for c in children]}
        (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(evidence))
    finally:
        for child in reversed(children):
            child.close()
        assert all(c.process.poll() is not None for c in children)


if __name__ == '__main__':
    main()

