"""Exercise storm controls in a fresh saved town, including lost replies/restart.

Run with a Python containing Playwright; --engine-python selects engine dependencies.
"""
import argparse
import gzip
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
import urllib.request
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def serve(args):
    from utilsim.world import World, network_faults, sewer, water_faults
    from utilsim.world.server import make_server
    target = args.out/'world.sqlite'
    if not target.exists():
        pack = next((ROOT/'packs/village').glob('*.snapshot.json.gz'))
        saved = json.loads(gzip.decompress(pack.read_bytes()))
        owner = World(target)
        owner.initialize(saved, 'STORM-DESKTOP', settings={'annual_meter_failure': 0, 'annual_meter_drift': 0})
        owner.advance('2026-01-02')
        with owner.db() as db:
            meta = owner.metadata(db)
        common = {'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'],
                  'actorId': 'world-admin', 'expectedRevision': 0, 'action': 'configure',
                  'reason': 'Explicit copied-world storm acceptance', 'causalReference': 'storm-browser'}
        for module, extra in ((network_faults, {}), (water_faults, {'leakM3PerHour': '0.02'}),
                              (sewer, {'returnFactor': '0.9', 'storageM3': '0.25', 'blockedCapacityM3PerDay': '0'})):
            module.command(owner, {**common, 'schemaVersion': module.VERSION, 'commandId': module.VERSION+'-baseline',
                **({} if module is water_faults else {'effectiveDate': meta['through']}),
                'annualProbability': .5, **extra})
        with closing(sqlite3.connect(owner.path)) as source, closing(sqlite3.connect(args.out/'baseline.sqlite')) as copy:
            source.backup(copy)
        evidence = {'premises': len(saved['premises']), 'pack': str(pack), 'packSha256': digest(pack),
                    'baselineSha256': digest(args.out/'baseline.sqlite'),
                    'historicalExport': owner.export_v2('2026-01-01', '2026-01-02')}
        (args.out/'fixture.json').write_text(json.dumps(evidence), encoding='utf-8')
    make_server(World(target), args.port, cruise_worker=False).serve_forever()


def check_evidence(args):
    from utilsim.world import World, storms
    fixture = json.loads((args.out/'fixture.json').read_text(encoding='utf-8'))
    world = World(args.out/'world.sqlite')
    state = storms.inspect(world)
    assert state['through'] == '2026-01-07'
    assert state['revision'] == 3
    assert [x['day'] for x in state['history']] == ['2026-01-03', '2026-01-02']
    assert all(x['temperatureC'] == round(x['baselineTemperatureC']-15, 2) for x in state['history'])
    weather_causes = {x['eventId'] for x in state['history']}
    with world.db() as db:
        causes = {r['id'] for r in db.execute("SELECT id FROM events WHERE type='InfrastructureHazardDay' AND cause IN (?,?)",
                                             tuple(weather_causes))}
        assert len(causes) == 2
        faults = {table: db.execute('SELECT COUNT(*) FROM '+table+' WHERE cause IN (?,?)', tuple(causes)).fetchone()[0]
                  for table in ('network_faults', 'water_faults', 'sewer_faults')}
        assert all(faults.values()), faults
        for table, column in (('network_faults', 'restored_date'), ('water_faults', 'repaired_date'),
                              ('sewer_faults', 'cleared_date')):
            assert not db.execute('SELECT 1 FROM '+table+' WHERE '+column+' IS NOT NULL').fetchone()
        assert json.loads(db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()[0]) == json.loads(
            gzip.decompress(Path(fixture['pack']).read_bytes()))
    assert world.export_v2('2026-01-01', '2026-01-02') == fixture['historicalExport']
    assert digest(args.out/'baseline.sqlite') == fixture['baselineSha256']
    assert digest(Path(fixture['pack'])) == fixture['packSha256']
    print(json.dumps({'passed': True, 'premises': fixture['premises'], 'stormDays': 2,
                      'faultsWithStormLineage': faults, 'sourceAndHistoryPreserved': True,
                      'futureCancellation': True, 'noAutomaticRepairs': True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine-python', default=sys.executable)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8783)
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    args.out = args.out.resolve()
    if args.serve:
        return serve(args)
    if args.verify:
        return check_evidence(args)
    args.out.mkdir(parents=True, exist_ok=False)
    base = f'http://127.0.0.1:{args.port}'
    common = [args.engine_python, str(Path(__file__).resolve()), '--out', str(args.out), '--port', str(args.port)]
    with (args.out/'engine.log').open('w', encoding='utf-8') as log:
        def start():
            engine = subprocess.Popen([*common, '--serve'], cwd=ROOT, stdout=log, stderr=log)
            for _ in range(120):
                if engine.poll() is not None:
                    raise RuntimeError('Storm engine stopped; inspect engine.log')
                try:
                    urllib.request.urlopen(base+'/api/storms', timeout=1).close()
                    return engine
                except OSError:
                    time.sleep(.5)
            engine.terminate()
            engine.wait(timeout=15)
            raise RuntimeError('Storm engine did not become ready.')
        engine = start()
        try:
            from playwright.sync_api import expect, sync_playwright
            errors, external = [], []
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda request: external.append(request.url)
                            if not request.url.startswith(base) else None)
                    page.goto(base+'/')
                    page.get_by_role('link', name='Storm scenarios', exact=True).click()
                    expect(page.locator('#save')).to_be_enabled()
                    page.locator('#start').fill('2026-01-02')
                    page.locator('#end').fill('2026-01-04')
                    page.locator('#temperature').fill('-15')
                    for family in ('electric', 'gas', 'water', 'sewer'):
                        page.locator('#'+family).fill('100')
                    page.locator('#reason').fill('Two-day severe cold storm with explicit risk assumptions')
                    def lose_reply(route):
                        if route.request.method == 'POST':
                            assert route.fetch().ok
                            route.abort()
                            page.unroute('**/api/storms', lose_reply)
                        else:
                            route.continue_()
                    page.route('**/api/storms', lose_reply)
                    page.locator('#save').click()
                    expect(page.locator('#retry')).to_be_visible()
                    page.reload()
                    page.locator('#retry').click()
                    expect(page.locator('#retry')).to_be_hidden()
                    assert page.request.get(base+'/api/storms').json()['revision'] == 1
                    page.screenshot(path=str(args.out/'01-scheduled-desktop.png'), full_page=True)
                    # Advance through actual world controls, never fabricating daily rows.
                    def advance(through):
                        page.goto(base+'/')
                        page.get_by_label('Simulate up to (exclusive)').fill(through)
                        page.get_by_role('button', name='Advance time', exact=True).click()
                        expect(page.locator('#message')).to_contain_text('World saved through', timeout=60000)
                    advance('2026-01-05')
                    page.goto(base+'/storms')
                    expect(page.locator('#history')).to_contain_text('2026-01-03')
                    page.set_viewport_size({'width': 960, 'height': 850})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert '\ufffd' not in page.locator('body').inner_text()
                    page.screenshot(path=str(args.out/'02-history-small-desktop.png'), full_page=True)
                    page.locator('#start').fill('2026-01-06')
                    page.locator('#end').fill('2026-01-07')
                    page.locator('#reason').fill('Future event cancelled before physical processing')
                    page.locator('#save').click()
                    expect(page.locator('#message')).to_contain_text('revision 2')
                    page.get_by_role('button', name='Cancel before start', exact=True).click()
                    expect(page.locator('#events')).to_contain_text('Cancelled')
                    engine.terminate()
                    engine.wait(timeout=15)
                    engine = start()
                    advance('2026-01-07')
                    page.goto(base+'/storms')
                    expect(page.locator('#history')).to_contain_text('2026-01-03')
                    assert not errors, errors
                    assert not external, external
                finally:
                    browser.close()
            engine.terminate()
            engine.wait(timeout=15)
            result = subprocess.run([*common, '--verify'], cwd=ROOT, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError('Saved storm verification failed:\n'+result.stderr)
            evidence = {**json.loads(result.stdout), 'viewports': [1440, 960], 'browserErrors': errors,
                        'externalRequests': external, 'lostReplyRecovery': True, 'restart': True}
            (args.out/'result.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
            print(json.dumps(evidence))
        finally:
            if engine.poll() is None:
                engine.terminate()
                engine.wait(timeout=15)


if __name__ == '__main__':
    main()
