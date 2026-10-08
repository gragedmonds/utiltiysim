"""Copied-town desktop acceptance for development, customer cash and field work."""
import argparse
import hashlib
import json
import sqlite3
import sys
import threading
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utilsim.world import World, development, occupancy, water_faults  # noqa: E402
from utilsim.world import customer_finance as finance
from utilsim.world import field_execution as field
from utilsim.world.map_view import WorldMap  # noqa: E402
from utilsim.world.server import make_server  # noqa: E402
from utilsim.world.store import stable  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--viewer-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256(args.db.read_bytes()).hexdigest()
    target = args.out/'world.sqlite'
    with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
    world = World(target)
    with world.db() as db:
        meta = world.metadata(db)
        assets = [dict(r) for r in db.execute('SELECT * FROM assets WHERE installed<=?', (meta['through'],))]
    source_snapshot = WorldMap(world).snapshot()
    previous = world.export_v2(meta['start'], meta['through'])
    occupied = next(a for a in assets if a['commodity'] == 'water' and json.loads(a['profile']).get('occupied', True))
    vacant = next(a for a in assets if a['commodity'] == 'water' and not json.loads(a['profile']).get('occupied', True))
    start = date.fromisoformat(meta['through'])
    def day(n):
        return (start+timedelta(days=n)).isoformat()
    common = {'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin',
              'expectedRevision': 0, 'reason': 'Copied browser scenario', 'causalReference': 'ui-acceptance'}
    water_faults.command(world, {**common, 'schemaVersion': water_faults.VERSION, 'commandId': 'ui-leak',
                                'action': 'start', 'assetId': occupied['id'], 'leakM3PerHour': '0.1'})
    field_path = args.out/'field.sqlite'
    server = make_server(world, 0, args.viewer_dir, field_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    errors, external = [], []
    from playwright.sync_api import expect, sync_playwright
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('request', lambda r: external.append(r.url) if not r.url.startswith(base) else None)

                def advance(n):
                    page.goto(base+'/')
                    page.get_by_label('Simulate up to (exclusive)').fill(day(n))
                    page.get_by_role('button', name='Advance time', exact=True).click()
                    expect(page.locator('#message')).to_contain_text('World saved through', timeout=60000)

                def load_cash():
                    page.goto(base+'/customer-finance')
                    page.get_by_label('Premise ID', exact=True).fill(occupied['premise'])
                    page.get_by_role('button', name='Load premise').click()
                    expect(page.locator('#overview')).to_be_visible()

                load_cash()
                form = page.locator('#policy')
                form.get_by_label('Simulated recipient reference').fill('BROWSER-COHORT')
                form.get_by_label('Cash balance (cents)').fill('10000')
                form.get_by_label('Essential cash reserve (cents)').fill('3000')
                form.get_by_label('Maximum installment (cents)').fill('4000')
                form.get_by_label('Generate payment intentions').check()
                form.get_by_label('Reason', exact=True).fill('Explicit browser-test cash assumption')
                form.get_by_role('button', name='Save behavior').click()
                expect(page.locator('#message')).to_contain_text('Saved.')
                assert finance.ready(world)['items'] == []
                credit = page.locator('#credit')
                credit.get_by_label('Cash credit (cents)').fill('500')
                credit.get_by_label('Reason', exact=True).fill('Scenario cash inflow')
                credit.get_by_role('button', name='Credit customer cash').click()
                expect(page.locator('#balances')).to_contain_text('$105.00')
                # Test-producer fixture only: no route/button invents invoice delivery.
                finance.receive_delivery(world, {'schemaVersion': finance.DELIVERY_VERSION, 'deliveryId': 'UI-DELIVERY',
                    'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'runId': meta['environment'],
                    'premiseId': occupied['premise'], 'recipientRef': 'BROWSER-COHORT', 'invoiceId': 'TEST-INVOICE',
                    'currency': 'USD', 'amountCents': 9000, 'dueDate': day(0), 'deliveredAt': day(0)+'T00:00:00Z',
                    'kind': 'invoice', 'status': 'delivered'})

                page.goto(base+'/development')
                expect(page.locator('#message')).to_contain_text('Plan a saved vacant property')
                form = page.locator('#plan')
                for label, value in [('Project ID', 'BROWSER-SITE'), ('Saved premise ID', vacant['premise']),
                                     ('Construction start', day(0)), ('Work days', '1'),
                                     ('Earliest utility-ready day', day(2)), ('Earliest move-in day', day(3)),
                                     ('Reason / evidence', 'Saved vacant property development')]:
                    form.get_by_label(label, exact=True).fill(value)
                def lose_reply(route):
                    if route.request.method == 'POST':
                        assert route.fetch().ok
                        route.abort()
                        page.unroute('**/api/development', lose_reply)
                    else:
                        route.continue_()
                page.route('**/api/development', lose_reply)
                form.get_by_role('button', name='Plan development').click()
                expect(page.locator('#retry')).to_be_visible()
                page.reload()
                page.get_by_role('button', name='Retry the same command').click()
                expect(page.locator('#projects')).to_contain_text('BROWSER-SITE')
                advance(1)
                assert not occupancy.inspect(world, vacant['premise'])['current']['occupied']
                load_cash()
                expect(page.locator('#balances')).to_contain_text('$40.00')
                intent = finance.ready(world)['items'][0]['intent']
                receipt = {'schemaVersion': finance.RECEIPT_VERSION, 'receiptId': 'UI-SETTLEMENT',
                    'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'runId': meta['environment'],
                    'intentId': intent['id'], 'intentFingerprint': stable(intent), 'status': 'settled', 'currency': 'USD',
                    'amountCents': 4000, 'occurredAt': day(1)+'T00:00:00Z', 'settlementReceiptId': None}
                finance.provider_receipt(world, receipt)
                load_cash()
                expect(page.locator('#balances')).to_contain_text('$65.00')
                finance.provider_receipt(world, {**receipt, 'receiptId': 'UI-RETURN', 'status': 'returned',
                                                'settlementReceiptId': receipt['receiptId']})
                load_cash()
                expect(page.locator('#balances')).to_contain_text('$105.00')
                assert finance.inspect(world, occupied['premise'])['knownOutstandingCents'] == 9000
                page.screenshot(path=str(args.out/'cash-1440.png'), full_page=True)

                page.goto(base+'/field-execution')
                expect(page.locator('#message')).to_contain_text('Administrator scenario controls are ready')
                page.locator('#crew').get_by_label('Shift weekdays').select_option('0,1,2,3,4,5,6')
                page.get_by_role('button', name='Save crew').click()
                expect(page.locator('#crews')).to_contain_text('1 visits/day')
                page.reload()
                expect(page.locator('#crew').get_by_label('Shift weekdays')).to_have_value('0,1,2,3,4,5,6')
                expect(page.locator('#crew').get_by_label('Visits per day')).to_have_value('1')
                assignment = page.locator('#assignment')
                for n in (1, 2):
                    assignment.get_by_label('Assignment ID', exact=True).fill(f'UI-A{n}')
                    assignment.get_by_label('Water service meter ID').fill(occupied['id'])
                    assignment.get_by_label('Order reference', exact=True).fill(f'ILLUSTRATIVE-ORDER-{n}')
                    assignment.get_by_label('Report delivery delay (days)').fill('2')
                    assignment.get_by_role('button', name='Accept assignment').click()
                    expect(page.locator('#history')).to_contain_text(f'UI-A{n}')
                page.get_by_role('button', name='Run due visits').click()
                expect(page.locator('#history')).to_contain_text('completed')
                expect(page.locator('#history')).to_contain_text('capacity is exhausted')
                assert water_faults.inspect(world, occupied['id'])['current']['active'] is None
                f = field.FieldExecution(world, field_path)
                assert len(field.inspect(f)['items']) == 2
                assert all(item['envelope']['schema'] != 'field-report/1' for item in field.ready(f)['items'])
                page.screenshot(path=str(args.out/'field-1440.png'), full_page=True)

                page.goto(base+'/development')
                page.get_by_role('button', name='Inspect / manage').click()
                page.get_by_role('button', name='Pause', exact=True).click()
                expect(page.locator('#detailState')).to_contain_text('Held: pause')
                advance(2)
                assert development.inspect(world, 'BROWSER-SITE')['projects'][0]['work_days'] == 0
                page.goto(base+'/development')
                page.get_by_role('button', name='Inspect / manage').click()
                page.get_by_role('button', name='Resume', exact=True).click()
                expect(page.locator('#detailState')).to_contain_text('Active')
                page.goto(base+'/field-execution')
                page.get_by_role('button', name='Run due visits').click()
                expect(page.locator('#history')).to_contain_text('not_found')
                advance(4)
                assert occupancy.inspect(world, vacant['premise'])['current']['occupied']
                assert len(development.available_notices(world, day(4)+'T00:00:00Z')['items']) == 1
                page.goto(base+'/development')
                page.get_by_role('button', name='Inspect / manage').click()
                expect(page.locator('#detailState')).to_contain_text('occupied')
                page.screenshot(path=str(args.out/'development-1440.png'), full_page=True)
                for path, name in [('/development', 'development'), ('/field-execution', 'field'),
                                   ('/customer-finance', 'cash')]:
                    if name == 'cash':
                        load_cash()
                    else:
                        page.goto(base+path)
                        expect(page.locator('#message')).not_to_contain_text('Loading')
                    page.set_viewport_size({'width': 1024, 'height': 768})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert '\ufffd' not in page.locator('body').inner_text()
                    page.screenshot(path=str(args.out/(name+'-1024.png')), full_page=True)
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        assert world.export_v2(meta['start'], meta['through']) == previous
        assert WorldMap(world).snapshot() == source_snapshot
        assert hashlib.sha256(args.db.read_bytes()).hexdigest() == digest
        evidence = {'passed': True, 'premises': len(source_snapshot['premises']), 'sourceUnchanged': True,
                    'historyPreserved': True, 'cashRestoredAfterReturnCents': 10500,
                    'developmentOccupied': vacant['premise'], 'fieldVisits': 2,
                    'finiteCapacityBacklog': True, 'reportsIndependent': True,
                    'browserErrors': errors, 'externalRequests': external, 'viewports': [1440, 1024],
                    'limitation': 'Test invoice/provider fixtures; no actual enterprise recipient connected'}
        (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(evidence))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
