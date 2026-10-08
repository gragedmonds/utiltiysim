"""Operate supply interruptions on a fresh copied town; retain evidence and source."""
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
from utilsim.world import World, network_faults  # noqa: E402
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

                for index, utility in enumerate(('electric', 'gas')):
                    edge = next(e['id'] for e in snapshot['networks'][utility]['edges'] if e['kind'] == 'supply')
                    page.goto(base+f'/network-faults?commodity={utility}&edgeId={edge}')
                    expect(page.locator('#current')).to_contain_text('Available')
                    assert network_faults.inspect(world, utility, edge)['additionalInterruptedServices'] > 0
                    def lost_reply(route):
                        if route.request.method == 'POST':
                            assert route.fetch().ok
                            route.abort()
                            page.unroute('**/api/network-faults', lost_reply)
                        else:
                            route.continue_()
                    page.route('**/api/network-faults', lost_reply)
                    page.get_by_label('Fault evidence', exact=True).fill('Saved supply route interrupted')
                    page.get_by_role('button', name='Start physical interruption').click()
                    expect(page.locator('#retry')).to_be_visible()
                    page.reload()
                    page.get_by_role('button', name='Retry the same command').click()
                    expect(page.locator('#message')).to_contain_text('Physical-world command completed')
                    expect(page.locator('#current')).to_contain_text('Fault active')
                    assert len(network_faults.inspect(world, utility, edge)['history']) == 1
                    page.screenshot(path=str(args.out/f'{utility}-active-1440.png'), full_page=True)
                    advance(index*2+1)
                    day = str(start+timedelta(days=index*2))
                    with world.db() as db:
                        counts = db.execute('SELECT COUNT(*) FROM network_fault_effects e JOIN assets a ON a.id=e.asset '
                                            'WHERE e.day=? AND a.commodity=?', (day, utility)).fetchone()[0]
                        assert counts > 0
                        assert not db.execute("SELECT 1 FROM truth t JOIN assets a ON a.id=t.asset WHERE t.day=? "
                                              "AND a.commodity=? AND t.quantity!='0.0000'", (day, utility)).fetchone()
                        premise = db.execute('SELECT a.premise FROM network_fault_effects e JOIN assets a ON a.id=e.asset '
                                             'WHERE e.day=? AND a.commodity=? LIMIT 1', (day, utility)).fetchone()[0]
                    page.goto(base+'/map')
                    page.wait_for_selector('body[data-ready="true"]', timeout=60000)
                    page.get_by_label('Find address or premise').fill(premise)
                    page.get_by_role('button', name='Find', exact=True).click()
                    page.locator('#matches button').first.click()
                    expect(page.locator('#place')).to_contain_text('Last supply loss')
                    page.goto(base+f'/network-faults?commodity={utility}&edgeId={edge}')
                    page.get_by_label('Work order reference').fill('BROWSER-WO-'+utility)
                    page.get_by_label('Restoration evidence').fill('Supply restored, enterprise report withheld')
                    page.get_by_role('button', name='Record physical restoration').click()
                    expect(page.locator('#current')).to_contain_text('Available')
                    page.set_viewport_size({'width': 1024, 'height': 768})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(args.out/f'{utility}-restored-1024.png'), full_page=True)
                    advance(index*2+2)
                    with world.db() as db:
                        assert not db.execute('SELECT 1 FROM network_fault_effects WHERE day=?',
                                              (str(start+timedelta(days=index*2+1)),)).fetchone()
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                server.shutdown()
                server.server_close()
                thread.join()
                world = World(target)
                server = make_server(world, port, args.viewer_dir)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                page.goto(base+'/network-faults')
                expect(page.locator('#summary')).to_contain_text('0 services currently interrupted')
                page.get_by_role('button', name='Next connections').click()
                expect(page.locator('#catalog')).not_to_contain_text('electric-E0 ')
                page.get_by_label('Policy evidence').fill('Retain deliberate scenario controls')
                page.get_by_role('button', name='Save failure policy').click()
                expect(page.locator('#message')).to_contain_text('Physical-world command completed')
                assert network_faults.inspect(world)['policy']['revision'] == 1
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        assert world.export_v2(meta['start'], meta['through']) == old
        assert WorldMap(world).snapshot() == snapshot
        assert hashlib.sha256(args.db.read_bytes()).hexdigest() == digest
        evidence = {'passed': True, 'premises': len(snapshot['premises']), 'sourceModified': False,
                    'historyPreserved': True, 'browserErrors': errors, 'externalRequests': external,
                    'viewports': [1440, 1024], 'checks': ['electric and gas supply faults', 'lost reply/reload/same retry',
                    'zero delivered use + recorded unmet demand', 'map inspection', 'explicit restoration',
                    'restart', 'catalog pagination', 'policy command']}
        (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(evidence))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
