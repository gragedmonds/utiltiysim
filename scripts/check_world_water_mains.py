"""Browser lifecycle acceptance on a private copy of an existing world."""
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
from utilsim.world import World, sewer, water_faults, water_mains  # noqa: E402
from utilsim.world.map_view import WorldMap  # noqa: E402
from utilsim.world.server import make_server  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--viewer-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    target = args.out/'world.sqlite'
    digest = hashlib.sha256(args.db.read_bytes()).hexdigest()
    with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
    world = World(target)
    with world.db() as db:
        meta, cat = world.metadata(db), water_mains.catalog(db)
        commissioned = {r[0] for r in db.execute("SELECT id FROM assets WHERE installed<=?", (meta['through'],))}
    old = world.export_v2(meta['start'], meta['through'])
    snapshot = WorldMap(world).snapshot()
    for edge in cat['edges']:
        if edge['kind'] not in ('trunk', 'distribution') or not edge['enabled']:
            continue
        closed = water_mains.section(cat, edge['id'])
        if not closed:
            continue
        reached = water_mains._supply(cat, [{'status': 'isolated', 'closed_edges': json.dumps(closed)}])
        affected = [s for s in cat['services'] if s['node'] not in reached and s['asset'] in commissioned]
        if len(affected) >= 5:
            break
    else:
        raise AssertionError('Fixture needs a valve-bounded neighborhood of at least five commissioned services.')
    asset = affected[0]['asset']
    common = {'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin',
              'expectedRevision': 0, 'reason': 'Copied acceptance world only', 'causalReference': 'acceptance'}
    water_faults.command(world, {**common, 'schemaVersion': water_faults.VERSION, 'commandId': 'test-leak',
                                'action': 'start', 'assetId': asset, 'leakM3PerHour': '1'})
    sewer.command(world, {**common, 'schemaVersion': sewer.VERSION, 'commandId': 'test-sewer',
                          'action': 'configure', 'effectiveDate': meta['through'], 'annualProbability': 0,
                          'returnFactor': '0.9', 'storageM3': '0.25', 'blockedCapacityM3PerDay': '0'})
    start = date.fromisoformat(meta['through'])
    server = make_server(world, 0, args.viewer_dir)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{port}'
    from playwright.sync_api import expect, sync_playwright
    errors, external = [], []
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
                    page.goto(base+'/water-mains?edgeId='+edge['id'])
                    expect(page.locator('#current')).to_contain_text(edge['id'])
                page.goto(base+'/water-mains?edgeId='+edge['id'])
                expect(page.locator('#current')).to_contain_text('revision 0')
                assert '\ufffd' not in page.locator('body').inner_text()
                page.get_by_label('Break evidence').fill('Observed main break scenario')
                def lose_reply(route):
                    if route.request.method == 'POST':
                        assert route.fetch().ok
                        route.abort()
                        page.unroute('**/api/water-mains', lose_reply)
                    else:
                        route.continue_()
                page.route('**/api/water-mains', lose_reply)
                page.get_by_role('button', name='Record main break', exact=True).click()
                expect(page.locator('#retry')).to_be_visible()
                page.reload()
                page.get_by_role('button', name='Retry the same command').click()
                expect(page.locator('#current')).to_contain_text('broken')
                assert water_mains.inspect(world, edge['id'])['selected']['revision'] == 1
                advance(1)
                assert water_mains.inspect(world, edge['id'])['losses'][0]['loss_m3'] == '240.0000'
                for action, status, days in [('isolate', 'isolated', 2), ('repair', 'repaired', 3), ('restore', 'Available', 4)]:
                    page.get_by_label('Physical action', exact=True).select_option(action)
                    page.get_by_label('Work order reference').fill('ACCEPTANCE-WO')
                    page.get_by_label('Completion evidence').fill('Recorded '+action+'; flushing confirmed on restoration')
                    page.get_by_role('button', name='Record physical action', exact=True).click()
                    expect(page.locator('#current')).to_contain_text(status)
                    if action == 'isolate':
                        page.screenshot(path=str(args.out/'isolated-1440.png'), full_page=True)
                    advance(days)
                    if action != 'restore':
                        assert water_mains.inspect(world)['interruptedServices'] == len(affected)
                assert water_mains.inspect(world)['interruptedServices'] == 0
                page.set_viewport_size({'width': 1024, 'height': 768})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out/'restored-1024.png'), full_page=True)
                server.shutdown()
                server.server_close()
                thread.join()
                world = World(target)
                server = make_server(world, port, args.viewer_dir)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                page.reload()
                expect(page.locator('#current')).to_contain_text('revision 4')
                with world.db() as db:
                    for offset in (1, 2):
                        day = (start+timedelta(days=offset)).isoformat()
                        assert db.execute('SELECT COUNT(*) FROM water_main_effects WHERE day=?', (day,)).fetchone()[0] == len(affected)
                        assert all(Decimal(r[0]) == 0 for r in db.execute(
                            'SELECT t.quantity FROM truth t JOIN water_main_effects e ON e.asset=t.asset AND e.day=t.day WHERE t.day=?', (day,)))
                        assert Decimal(db.execute('SELECT leak_quantity FROM water_fault_effects WHERE asset=? AND day=?', (asset, day)).fetchone()[0]) == 0
                    last = (start+timedelta(days=3)).isoformat()
                    assert Decimal(db.execute('SELECT leak_quantity FROM water_fault_effects WHERE asset=? AND day=?', (asset, last)).fetchone()[0]) == 24
                    for row in db.execute('SELECT * FROM sewer_flows'):
                        assert Decimal(row['previous_retained'])+Decimal(row['inflow']) == sum(Decimal(row[k]) for k in ('transported', 'retained', 'overflow'))
                    assert db.execute('SELECT COUNT(*) FROM water_main_faults').fetchone()[0] == 1
                page.goto(base+'/map?map=iso')
                expect(page.locator('#date')).to_contain_text('World saved through')
                page.get_by_label('Find address or premise').fill(affected[0]['premise'])
                page.get_by_role('button', name='Find', exact=True).click()
                page.locator('#matches button').first.click()
                expect(page.locator('#place')).to_contain_text('Last main isolation')
                expect(page.locator('#place')).to_contain_text('Leak rate when supplied')
                page.screenshot(path=str(args.out/'map-1024.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        assert world.export_v2(meta['start'], meta['through']) == old
        assert WorldMap(world).snapshot() == snapshot
        assert hashlib.sha256(args.db.read_bytes()).hexdigest() == digest
        evidence = {'passed': True, 'premises': len(snapshot['premises']), 'main': edge['id'],
                    'interruptedServices': len(affected), 'viewports': [1440, 1024], 'sourceModified': False,
                    'historyPreserved': True, 'browserErrors': errors, 'externalRequests': external,
                    'checks': ['lost reply/reload/retry', 'unbilled main loss', 'valve isolation', 'repair retains isolation',
                               'flush/restore', 'household leak resumes', 'sewer conservation', 'restart', 'isometric property inspection']}
        (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(evidence))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
