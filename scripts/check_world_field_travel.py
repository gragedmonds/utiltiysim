"""Verify saved-road travel estimates in a disposable desktop world."""
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def serve(args):
    sys.path.insert(0, str(ROOT))
    from utilsim.world import World, field_execution, sewer
    from utilsim.world.server import make_server
    saved = json.loads(gzip.decompress(next((ROOT / 'packs/village').glob('*.snapshot.json.gz')).read_bytes()))
    world = World(args.out / 'world.sqlite')
    world.initialize(saved, 'TRAVEL-DESKTOP', settings={'annual_meter_failure': 0, 'annual_meter_drift': 0})
    owner = field_execution.FieldExecution(world, args.out / 'field.sqlite')
    with owner.db() as db:
        meta = owner.metadata(db)
    with world.db() as db:
        asset = db.execute("SELECT id FROM assets WHERE commodity='water' AND installed<='2026-01-01' ORDER BY id LIMIT 1").fetchone()[0]
    common = {'schemaVersion': field_execution.VERSION, 'environmentId': meta['environment'],
              'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin', 'effectiveDate': meta['through'],
              'causalReference': 'travel-browser-acceptance'}
    field_execution.command(owner, {**common, 'commandId': 'crew', 'action': 'configure-crew',
        'crewId': 'plumbing-1', 'expectedRevision': 0, 'skills': ['plumbing'], 'weekdays': list(range(7)), 'dailyCapacity': 1})
    field_execution.command(owner, {**common, 'commandId': 'assignment', 'action': 'accept',
        'assignmentId': 'VISIT-1', 'crewId': 'plumbing-1', 'assetId': asset, 'orderId': 'LOCAL-TRAVEL-1',
        'orderRevision': 1, 'scheduledDate': meta['through'], 'operation': 'repair-water-leak', 'reportDelayDays': 0})
    service = sewer.inspect(world, asset)['service']['id']
    field_execution.command(owner, {**common, 'commandId': 'sewer-crew', 'action': 'configure-crew',
        'crewId': 'sewer-1', 'expectedRevision': 0, 'skills': ['sewer'], 'weekdays': list(range(7)), 'dailyCapacity': 1})
    field_execution.command(owner, {**common, 'commandId': 'sewer-assignment', 'action': 'accept',
        'assignmentId': 'SEWER-VISIT-1', 'crewId': 'sewer-1', 'assetId': service, 'orderId': 'LOCAL-SEWER-TRAVEL-1',
        'orderRevision': 1, 'scheduledDate': meta['through'], 'operation': 'clear-sewer-blockage', 'reportDelayDays': 0})
    edge = next(e['id'] for e in saved['networks']['electric']['edges'] if e.get('enabled', True))
    field_execution.command(owner, {**common, 'commandId': 'network-crew', 'action': 'configure-crew',
        'crewId': 'electric-1', 'expectedRevision': 0, 'skills': ['electric'], 'weekdays': list(range(7)), 'dailyCapacity': 1})
    field_execution.command(owner, {**common, 'commandId': 'network-assignment', 'action': 'accept',
        'assignmentId': 'NETWORK-VISIT-1', 'crewId': 'electric-1', 'assetId': edge, 'orderId': 'LOCAL-NETWORK-TRAVEL-1',
        'orderRevision': 1, 'scheduledDate': meta['through'], 'operation': 'restore-electric-supply', 'reportDelayDays': 0})
    evidence = {'premises': len(saved['premises']), 'assetId': asset,
                'before': {name: digest(args.out / name) for name in ('world.sqlite', 'field.sqlite')}}
    (args.out / 'fixture.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    make_server(world, args.port, field_db=owner.path, cruise_worker=False).serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine-python', default=sys.executable)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8781)
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args()
    args.out = args.out.resolve()
    if args.serve:
        return serve(args)
    args.out.mkdir(parents=True, exist_ok=False)
    base = f'http://127.0.0.1:{args.port}'
    with (args.out / 'engine.log').open('w', encoding='utf-8') as log:
        engine = subprocess.Popen([args.engine_python, str(Path(__file__).resolve()), '--serve', '--out', str(args.out),
                                   '--port', str(args.port)], cwd=ROOT, stdout=log, stderr=log)
        try:
            for _ in range(120):
                if engine.poll() is not None:
                    raise RuntimeError('Engine stopped; see engine.log')
                try:
                    urllib.request.urlopen(base + '/api/field-execution', timeout=1).close()
                    break
                except OSError:
                    time.sleep(.5)
            else:
                raise RuntimeError('Engine did not become ready.')
            from playwright.sync_api import expect, sync_playwright
            errors = []
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base + '/field-execution')
                page.get_by_role('link', name='Estimate travel').click()
                expect(page.locator('#submit')).to_be_enabled()
                page.locator('[name=assignmentId]').fill('VISIT-1')
                page.locator('#submit').click()
                expect(page.locator('#summary')).to_contain_text('Total visit:')
                first = page.locator('#binding').inner_text()
                first_duration = page.locator('#summary').inner_text()
                assert page.locator('#route polyline').count() == 1
                page.screenshot(path=str(args.out / '01-desktop.png'), full_page=True)
                page.locator('[name=work]').fill('60')
                expect(page.locator('#result')).to_be_hidden()
                page.locator('#submit').click()
                expect(page.locator('#result')).to_be_visible()
                assert page.locator('#summary').inner_text() != first_duration
                page.reload()
                expect(page.locator('#submit')).to_be_enabled()
                page.locator('[name=assignmentId]').fill('VISIT-1')
                page.locator('#submit').click()
                expect(page.locator('#binding')).to_have_text(first)
                page.set_viewport_size({'width': 960, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out / '02-small-desktop.png'), full_page=True)
                page.locator('[name=assignmentId]').fill('SEWER-VISIT-1')
                expect(page.locator('#result')).to_be_hidden()
                assert page.locator('#assignments option[value="SEWER-VISIT-1"]').count() == 1
                page.locator('#submit').click()
                expect(page.locator('#binding')).to_contain_text('Sewer blockage clearance')
                expect(page.locator('#summary')).to_have_text(first_duration)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                sewer_binding = page.locator('#binding').inner_text()
                page.screenshot(path=str(args.out / '03-sewer-small-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.screenshot(path=str(args.out / '04-sewer-desktop.png'), full_page=True)
                page.locator('[name=assignmentId]').fill('NETWORK-VISIT-1')
                page.locator('#submit').click()
                expect(page.locator('#message')).to_contain_text('no defined saved road-access binding')
                expect(page.locator('#route')).to_be_hidden()
                # The operator explicitly chooses access; the app has not auto-selected a site.
                assert page.locator('[name=workSiteRoad]').input_value() == ''
                chosen = page.locator('[name=workSiteRoad] option').nth(1).get_attribute('value')
                page.locator('[name=workSiteRoad]').select_option(chosen)
                page.locator('[name=workSiteFraction]').fill('0.35')
                page.locator('#submit').click()
                expect(page.locator('#location-notice')).to_contain_text('not a verified physical work site')
                expect(page.locator('#binding')).to_contain_text('Electric supply restoration')
                expect(page.locator('#binding')).to_contain_text('at 0.35')
                network_binding = page.locator('#binding').inner_text()
                assert page.locator('#route polyline').count() == 1
                page.screenshot(path=str(args.out / '05-network-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 960, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out / '06-network-small-desktop.png'), full_page=True)
                # A slow reply must not restore an estimate after its assumptions change.
                def change_during_quote(route):
                    response = route.fetch()
                    page.locator('[name=work]').fill('45')
                    route.fulfill(response=response)

                page.route('**/api/field-travel/quote', change_during_quote)
                page.locator('#submit').click()
                expect(page.locator('#submit')).to_be_enabled()
                expect(page.locator('#result')).to_be_hidden()
                expect(page.locator('#message')).to_contain_text('Assumptions changed')
                page.unroute('**/api/field-travel/quote', change_during_quote)
                page.locator('[name=assignmentId]').fill('UNKNOWN')
                page.locator('#submit').click()
                expect(page.locator('#message')).to_contain_text('Unknown accepted assignment')
                expect(page.locator('#result')).to_be_hidden()
                assert not errors, errors
                browser.close()
        finally:
            engine.terminate()
            engine.wait(timeout=15)
    evidence = json.loads((args.out / 'fixture.json').read_text(encoding='utf-8'))
    evidence.update(browserErrors=errors, staleResponseSuppressed=True,
                    sewerEstimateVerified=True, sewerQuoteBinding=sewer_binding,
                    selectedNetworkSiteVerified=True, networkQuoteBinding=network_binding,
                    firstEstimate=first_duration, quoteBinding=first,
                    after={name: digest(args.out / name) for name in ('world.sqlite', 'field.sqlite')})
    assert evidence['before'] == evidence['after'], 'An estimate changed a saved owner.'
    evidence['passed'] = True
    (args.out / 'result.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
