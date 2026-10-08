"""Operate physical sewer blockages on a copied saved world through its screens."""
import argparse
import hashlib
import json
import sqlite3
import sys
import threading
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utilsim.world import World, sewer  # noqa: E402
from utilsim.world.map_view import WorldMap  # noqa: E402
from utilsim.world.server import make_server  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--viewer-dir', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    target = args.out/'world.sqlite'
    digest = hashlib.sha256(args.db.read_bytes()).hexdigest()
    with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
    world = World(target)
    snapshot = WorldMap(world).snapshot()
    with world.db() as db:
        meta = world.metadata(db)
        asset = dict(db.execute("SELECT * FROM assets WHERE commodity='water' AND installed<=? ORDER BY id LIMIT 1",
                                (meta['through'],)).fetchone())
    old = world.export_v2(meta['start'], meta['through'])
    start = date.fromisoformat(meta['through'])
    server = make_server(world, 0, args.viewer_dir)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{port}'
    errors, external = [], []
    from playwright.sync_api import expect, sync_playwright
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('request', lambda r: external.append(r.url) if not r.url.startswith(base) else None)
                def advance(days):
                    page.goto(base+'/')
                    page.get_by_label('Simulate up to (exclusive)').fill((start+timedelta(days=days)).isoformat())
                    page.get_by_role('button', name='Advance time', exact=True).click()
                    expect(page.locator('#message')).to_contain_text('World saved through', timeout=60000)
                path = '/sewer?waterAssetId='+asset['id']
                page.goto(base+path)
                expect(page.locator('#current')).to_contain_text('Lateral model not enabled')
                def lost_reply(route):
                    if route.request.method == 'POST':
                        assert route.fetch().ok
                        route.abort()
                        page.unroute('**/api/sewer', lost_reply)
                    else:
                        route.continue_()
                page.route('**/api/sewer', lost_reply)
                page.get_by_label('Blockage evidence').fill('Physical sanitary blockage scenario')
                page.get_by_role('button', name='Start physical blockage').click()
                expect(page.locator('#retry')).to_be_visible()
                page.reload()
                page.get_by_role('button', name='Retry the same command').click()
                expect(page.locator('#message')).to_contain_text('Physical-world command completed')
                expect(page.locator('#current')).to_contain_text('Blocked: 0')
                assert len(sewer.inspect(world, asset['id'])['history']) == 1
                advance(2)
                view = sewer.inspect(world, asset['id'])
                assert Decimal(view['current']['retained']) > 0
                assert any(Decimal(f['overflow']) > 0 for f in view['flows'])
                page.goto(base+'/map')
                page.wait_for_selector('body[data-ready="true"]', timeout=60000)
                page.get_by_label('Find address or premise').fill(asset['premise'])
                page.get_by_role('button', name='Find', exact=True).click()
                page.locator('#matches button').first.click()
                expect(page.locator('#place')).to_contain_text('Sewer lateral: Blocked')
                page.get_by_role('link', name='Manage sewer lateral').click()
                expect(page.locator('#flows tr')).to_have_count(2)
                page.screenshot(path=str(args.out/'blocked-1440.png'), full_page=True)
                retained = view['current']['retained']
                page.get_by_label('Work order reference').fill('BROWSER-SEWER-WO1')
                page.get_by_label('Clearance evidence').fill('Physical blockage cleared; enterprise report withheld')
                page.get_by_role('button', name='Record physical clearance').click()
                expect(page.locator('#current')).to_contain_text('Clear lateral')
                assert sewer.inspect(world, asset['id'])['current']['retained'] == retained
                server.shutdown()
                server.server_close()
                thread.join()
                world = World(target)
                server = make_server(world, port, args.viewer_dir)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                advance(3)
                page.goto(base+path)
                view = sewer.inspect(world, asset['id'])
                flow = view['flows'][0]
                assert Decimal(flow['retained']) == Decimal(flow['overflow']) == 0
                assert Decimal(flow['transported']) == Decimal(flow['inflow'])+Decimal(retained)
                page.set_viewport_size({'width': 1024, 'height': 768})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out/'cleared-1024.png'), full_page=True)
                page.get_by_label('Annual blockage probability (0–1)').fill('1')
                page.get_by_label('Policy evidence').fill('Seeded recurrence acceptance')
                page.get_by_role('button', name='Save sewer policy').click()
                expect(page.locator('#message')).to_contain_text('Physical-world command completed')
                advance(4)
                page.goto(base+path)
                expect(page.locator('#history')).to_contain_text('seeded')
                assert len(sewer.inspect(world, asset['id'])['history']) == 2
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        assert world.export_v2(meta['start'], meta['through']) == old
        assert WorldMap(world).snapshot() == snapshot
        assert hashlib.sha256(args.db.read_bytes()).hexdigest() == digest
        with world.db() as db:
            balances = [dict(row) for row in db.execute('SELECT * FROM sewer_flows')]
            assert not db.execute("SELECT 1 FROM assets WHERE commodity='sewer'").fetchone()
        for row in balances:
            assert Decimal(row['previous_retained'])+Decimal(row['inflow']) == sum(
                Decimal(row[key]) for key in ('transported', 'retained', 'overflow'))
        evidence = {'passed': True, 'premises': len(snapshot['premises']), 'balancesChecked': len(balances),
                    'sourceModified': False, 'historyPreserved': True, 'browserErrors': errors, 'externalRequests': external,
                    'viewports': [1440, 1024], 'checks': ['lost reply/reload/same retry', 'blockage/storage/overflow',
                    'map inspection', 'clearance and retained-water drainage', 'restart', 'seeded recurrence', 'mass conservation']}
        (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(evidence))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
