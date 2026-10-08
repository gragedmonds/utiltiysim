"""Operate water leaks and repair on a fresh copy, preserving the source world."""
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
from utilsim.world import World, water_faults  # noqa: E402
from utilsim.world.map_view import WorldMap  # noqa: E402
from utilsim.world.server import make_server  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--viewer-dir', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    target = args.out / 'world.sqlite'
    digest = hashlib.sha256(args.db.read_bytes()).hexdigest()
    with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
    world = World(target)
    snapshot = WorldMap(world).snapshot()
    with world.db() as db:
        meta = world.metadata(db)
        asset = dict(db.execute("SELECT * FROM assets WHERE commodity='water' AND condition='healthy' ORDER BY id LIMIT 1").fetchone())
    old = world.export_v2(meta['start'], meta['through'])
    day = date.fromisoformat(meta['through'])
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
                page.goto(base + '/water-faults?assetId=' + asset['id'])
                expect(page.locator('#current')).to_contain_text('No active leak')

                def lost_reply(route):
                    if route.request.method == 'POST':
                        assert route.fetch().ok
                        route.abort()
                        page.unroute('**/api/water-faults', lost_reply)
                    else:
                        route.continue_()
                page.route('**/api/water-faults', lost_reply)
                page.get_by_label('Leak rate (m³/hour)', exact=True).fill('0.1')
                page.get_by_label('Fault evidence').fill('Downstream leak scenario')
                page.get_by_role('button', name='Start physical leak').click()
                expect(page.locator('#retry')).to_be_visible()
                page.reload()
                page.get_by_role('button', name='Retry the same command').click()
                expect(page.locator('#message')).to_contain_text('Physical-world command completed')
                expect(page.locator('#current')).to_contain_text('Active leak: 0.1')
                assert len(water_faults.inspect(world, asset['id'])['history']) == 1
                page.screenshot(path=str(args.out / 'active-1440.png'), full_page=True)

                def advance(days):
                    page.goto(base+'/')
                    page.get_by_label('Simulate up to (exclusive)').fill((day+timedelta(days=days)).isoformat())
                    page.get_by_role('button', name='Advance time', exact=True).click()
                    expect(page.locator('#message')).to_contain_text('World saved through', timeout=60000)
                advance(1)
                with world.db() as db:
                    effect = db.execute('SELECT * FROM water_fault_effects WHERE asset=? AND day=?', (asset['id'], str(day))).fetchone()
                    assert effect['leak_quantity'] == '2.4000'
                page.goto(base+'/map')
                page.wait_for_selector('body[data-ready="true"]', timeout=60000)
                page.get_by_label('Find address or premise').fill(asset['premise'])
                page.get_by_role('button', name='Find', exact=True).click()
                page.locator('#matches button').first.click()
                expect(page.locator('#place')).to_contain_text('0.1 m³/h')
                page.get_by_role('link', name='Manage physical water faults').click()
                page.get_by_label('Work order reference').fill('BROWSER-WO1')
                page.get_by_label('Physical completion evidence').fill('Pipe repaired; enterprise report not submitted')
                page.get_by_role('button', name='Record physical repair').click()
                expect(page.locator('#current')).to_contain_text('No active leak')
                page.set_viewport_size({'width': 1024, 'height': 768})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out / 'repaired-1024.png'), full_page=True)
                page.get_by_label('Annual probability (0–1)').fill('1')
                page.get_by_label('Policy change reason').fill('Deterministic seeded-fault acceptance')
                page.get_by_role('button', name='Save seeded policy').click()
                expect(page.locator('#message')).to_contain_text('Physical-world command completed')
                assert water_faults.inspect(world, asset['id'])['policy']['annualProbability'] == 1
                server.shutdown()
                server.server_close()
                thread.join()
                world = World(target)
                server = make_server(world, port, args.viewer_dir)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                advance(2)
                assert water_faults.inspect(world, asset['id'])['current']['active'] is None
                advance(3)
                page.goto(base+'/water-faults?assetId='+asset['id'])
                expect(page.locator('#current')).to_contain_text('Active leak: 0.05')
                expect(page.locator('#history')).to_contain_text('seeded')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out / 'seeded-1024.png'), full_page=True)
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        assert world.export_v2(meta['start'], meta['through']) == old
        assert WorldMap(world).snapshot() == snapshot
        assert hashlib.sha256(args.db.read_bytes()).hexdigest() == digest
        evidence = {'passed': True, 'premises': len(snapshot['premises']), 'sourceModified': False,
                    'historyPreserved': True, 'browserErrors': errors, 'externalRequests': external,
                    'viewports': [1440, 1024], 'checks': ['lost reply/reload/identical retry', 'manual leak + daily loss',
                    'map current fault', 'physical repair', 'seeded policy', 'restart', 'repair-day protection', 'distinct recurrence']}
        (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(evidence))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
