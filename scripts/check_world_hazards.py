"""Verify age/weather controls and downstream physical faults on a copied world."""
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
from utilsim.world import World, hazards, network_faults, sewer, water_faults  # noqa: E402
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
    with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
    world = World(target)
    with world.db() as db:
        meta = world.metadata(db)
    old = world.export_v2(meta['start'], meta['through'])
    snapshot = WorldMap(world).snapshot()
    start = date.fromisoformat(meta['through'])
    for owner, extra in [(network_faults, {}), (water_faults, {'leakM3PerHour': '0.02'}),
                         (sewer, {'returnFactor': '0.9', 'storageM3': '0.25', 'blockedCapacityM3PerDay': '0'})]:
        owner.command(world, {'schemaVersion': owner.VERSION, 'commandId': owner.VERSION+'-acceptance',
            'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin',
            'expectedRevision': 0, **({} if owner is water_faults else {'effectiveDate': meta['through']}), 'action': 'configure',
            'reason': 'Copied-world hazard acceptance', 'causalReference': 'acceptance', 'annualProbability': .5, **extra})
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
                page.goto(base+'/')
                page.get_by_role('link', name='Infrastructure risk', exact=True).click()
                expect(page.locator('#state')).to_contain_text('Model not enabled')
                assert '\ufffd' not in page.locator('body').inner_text()
                page.get_by_label('Apply age and cold-weather effects').check()
                for label in ('Electricity', 'Gas', 'Water', 'Sewer'):
                    page.get_by_label(label+' Age', exact=True).fill('80')
                    page.get_by_label(label+' Annual age increase', exact=True).fill('0.2')
                    page.get_by_label(label+' Cold threshold', exact=True).fill('60')
                    page.get_by_label(label+' Cold multiplier', exact=True).fill('10')
                page.get_by_label('Policy evidence').fill('Explicit old-infrastructure cold stress scenario')
                def lose_reply(route):
                    if route.request.method == 'POST':
                        assert route.fetch().ok
                        route.abort()
                        page.unroute('**/api/hazards', lose_reply)
                    else:
                        route.continue_()
                page.route('**/api/hazards', lose_reply)
                page.get_by_role('button', name='Save infrastructure risk').click()
                expect(page.locator('#retry')).to_be_visible()
                page.reload()
                page.get_by_role('button', name='Retry the same command').click()
                expect(page.locator('#state')).to_contain_text('effects active')
                assert hazards.inspect(world)['policy']['revision'] == 1
                advance(2)
                page.goto(base+'/hazards')
                expect(page.locator('#history tr')).to_have_count(2)
                page.screenshot(path=str(args.out/'active-1440.png'), full_page=True)
                view = hazards.inspect(world)
                assert all(a > 80 for a in view['currentAges'].values())
                causes = {h['eventId'] for h in view['history']}
                with world.db() as db:
                    faults = {t: [dict(r) for r in db.execute('SELECT * FROM '+t)]
                              for t in ('network_faults', 'water_faults', 'sewer_faults')}
                assert all(faults.values())
                assert all(f['cause'] in causes for values in faults.values() for f in values)
                page.get_by_label('Apply age and cold-weather effects').uncheck()
                page.get_by_label('Policy evidence').fill('Pause modifiers while retaining existing damage')
                page.get_by_role('button', name='Save infrastructure risk').click()
                expect(page.locator('#state')).to_contain_text('Modifiers paused')
                assert {f: p['ageYears'] for f, p in hazards.inspect(world)['policy']['profiles'].items()} == view['currentAges']
                server.shutdown()
                server.server_close()
                thread.join()
                world = World(target)
                server = make_server(world, port, args.viewer_dir)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                advance(3)
                page.goto(base+'/hazards')
                expect(page.locator('#history tr')).to_have_count(3)
                assert set(hazards.inspect(world)['history'][0]['multipliers'].values()) == {1}
                page.set_viewport_size({'width': 1024, 'height': 768})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out/'paused-1024.png'), full_page=True)
                with world.db() as db:
                    for table, field in [('network_faults', 'restored_date'), ('water_faults', 'repaired_date'),
                                          ('sewer_faults', 'cleared_date')]:
                        assert not db.execute('SELECT 1 FROM '+table+' WHERE '+field+' IS NOT NULL').fetchone()
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        assert world.export_v2(meta['start'], meta['through']) == old
        assert WorldMap(world).snapshot() == snapshot
        assert hashlib.sha256(args.db.read_bytes()).hexdigest() == digest
        evidence = {'passed': True, 'premises': len(snapshot['premises']), 'viewports': [1440, 1024],
                    'faultsWithDayLineage': {t: len(v) for t, v in faults.items()}, 'sourceModified': False,
                    'historyPreserved': True, 'browserErrors': errors, 'externalRequests': external,
                    'checks': ['lost response/reload/retry', 'age/cold multipliers', 'four-domain fault causes',
                               'pause retains physical faults', 'restart', 'immutable history']}
        (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps(evidence))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
