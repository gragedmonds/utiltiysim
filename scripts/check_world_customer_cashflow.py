"""Desktop acceptance for cashflow controls using a copied town and real owners."""
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
    from utilsim.world import World, customer_finance
    from utilsim.world.server import make_server

    target = args.out/'world.sqlite'
    if not target.exists():
        pack = next((ROOT/'packs/village').glob('*.snapshot.json.gz'))
        snapshot = json.loads(gzip.decompress(pack.read_bytes()))
        owner = World(target)
        owner.initialize(snapshot, 'CASHFLOW-DESKTOP', settings={'annual_meter_failure': 0, 'annual_meter_drift': 0})
        premise = next(p['id'] for p in snapshot['premises'] if p.get('occupied', True))
        with owner.db() as db:
            meta = owner.metadata(db)
        common = {'environmentId': meta['environment'], 'runId': meta['environment'],
                  'worldFingerprint': meta['fingerprint'], 'premiseId': premise, 'recipientRef': 'SIM-CASHFLOW'}
        customer_finance.command(owner, {**common, 'schemaVersion': customer_finance.VERSION,
            'commandId': 'fixture-finance', 'actorId': 'world-admin', 'expectedRevision': 0,
            'effectiveDate': meta['through'], 'action': 'configure', 'active': True,
            'customerKind': 'household', 'cashCents': 10000, 'essentialReserveCents': 3000,
            'maxPaymentCents': 4000, 'paymentProbability': 1, 'reason': 'Explicit copied-world scenario',
            'causalReference': 'desktop-acceptance'})
        # Trusted fixture delivery, never a live enterprise document or provider.
        customer_finance.receive_delivery(owner, {**common, 'schemaVersion': customer_finance.DELIVERY_VERSION,
            'deliveryId': 'fixture-delivered-invoice', 'invoiceId': 'FIXTURE-INVOICE', 'currency': 'USD',
            'amountCents': 9000, 'dueDate': meta['through'], 'deliveredAt': meta['through']+'T00:00:00Z',
            'kind': 'invoice', 'status': 'delivered'})
        owner.advance('2026-01-02')
        assert customer_finance.inspect(owner, premise)['reservedCashCents'] == 4000
        with closing(sqlite3.connect(owner.path)) as source, closing(sqlite3.connect(args.out/'baseline.sqlite')) as target:
            source.backup(target)
        (args.out/'fixture.json').write_text(json.dumps({'premise': premise, 'premises': len(snapshot['premises']),
            'pack': str(pack), 'packSha256': digest(pack), 'baselineSha256': digest(args.out/'baseline.sqlite'),
            'historicalExport': owner.export_v2('2026-01-01', '2026-01-02')}), encoding='utf-8')
    make_server(World(args.out/'world.sqlite'), args.port, cruise_worker=False).serve_forever()


def verify(args):
    from utilsim.world import World, customer_cashflow, customer_finance

    fixture = json.loads((args.out/'fixture.json').read_text(encoding='utf-8'))
    owner = World(args.out/'world.sqlite')
    view = customer_cashflow.inspect(owner, fixture['premise'])
    assert view['through'] == '2026-02-05' and view['revision'] == 2
    assert view['cashCents'] == view['reservedCashCents'] == 4000 and not view['policy']['active']
    first = customer_cashflow.inspect(owner, fixture['premise'], before='2026-01-03')['history'][0]
    assert (first['openingCashCents'], first['incomeCreditedCents'], first['expenseDueCents'],
            first['expensePaidCents'], first['expenseUnfundedCents'], first['closingCashCents']) == (
                10000, 10001, 20001, 16001, 4000, 4000)
    assert len(view['history']) == 25 and view['nextBefore']
    older = customer_cashflow.inspect(owner, fixture['premise'], before=view['nextBefore'])
    assert len(older['history']) == 9
    records = view['history']+older['history']
    assert all(r['closingCashCents'] == r['openingCashCents']+r['incomeCreditedCents']-r['expensePaidCents'] for r in records)
    assert all(r['closingCashCents'] >= r['reservedCashCents'] for r in records)
    assert all(r['incomeCreditedCents'] == r['expensePaidCents'] == 0 for r in records if r['day'] >= '2026-01-06')
    assert owner.export_v2('2026-01-01', '2026-01-02') == fixture['historicalExport']
    assert digest(Path(fixture['pack'])) == fixture['packSha256']
    assert digest(args.out/'baseline.sqlite') == fixture['baselineSha256']
    profile = customer_finance.inspect(owner, fixture['premise'])
    assert profile['knownOutstandingCents'] == 9000 and profile['netSettledCashCents'] == 0
    with owner.db() as db:
        assert json.loads(db.execute("SELECT value FROM meta WHERE key='snapshot'").fetchone()[0]) == json.loads(
            gzip.decompress(Path(fixture['pack']).read_bytes()))
    print(json.dumps({'passed': True, 'premises': fixture['premises'], 'occurrences': len(records),
                      'reservedCentsProtected': 4000, 'exactIncomeCents': 10001, 'unfundedExpenseCents': 4000,
                      'sourceAndHistoryPreserved': True, 'pausedDays': 30, 'noProviderSettlementInvented': True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--engine-python', default=sys.executable)
    parser.add_argument('--port', type=int, default=8784)
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    args.out = args.out.resolve()
    if args.serve:
        return serve(args)
    if args.verify:
        return verify(args)
    args.out.mkdir(parents=True, exist_ok=False)
    base = f'http://127.0.0.1:{args.port}'
    common = [args.engine_python, str(Path(__file__).resolve()), '--out', str(args.out), '--port', str(args.port)]
    with (args.out/'engine.log').open('w', encoding='utf-8') as log:
        def start():
            engine = subprocess.Popen([*common, '--serve'], cwd=ROOT, stdout=log, stderr=log)
            for _ in range(180):
                if engine.poll() is not None:
                    raise RuntimeError('Cashflow engine stopped; inspect engine.log')
                try:
                    urllib.request.urlopen(base+'/customer-cashflow', timeout=1).close()
                    return engine
                except OSError:
                    time.sleep(.5)
            engine.terminate()
            engine.wait(timeout=15)
            raise RuntimeError('Cashflow engine did not become ready.')
        engine = start()
        try:
            fixture = json.loads((args.out/'fixture.json').read_text(encoding='utf-8'))
            premise = fixture['premise']
            from playwright.sync_api import expect, sync_playwright

            errors, external = [], []
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(base) else None)
                    page.goto(base+'/customer-finance')
                    page.get_by_role('link', name='Income and living costs').click()
                    page.locator('#premise').fill(premise)
                    page.locator('#load').click()
                    expect(page.locator('#save')).to_be_enabled()
                    page.locator('#incomeAmount').fill('100.001')
                    page.locator('#expenseAmount').fill('200.01')
                    page.locator('#reason').fill('Explicit fortnightly earnings and daily costs')
                    page.locator('#active').check()
                    page.locator('#save').click()
                    expect(page.locator('#message')).to_contain_text('at most two decimal places')
                    page.locator('#incomeAmount').fill('100.01')
                    def lose_reply(route):
                        if route.request.method == 'POST':
                            assert route.fetch().ok
                            route.abort()
                        else:
                            route.continue_()
                    page.route('**/api/customer-cashflow', lose_reply, times=1)
                    page.locator('#save').click()
                    expect(page.locator('#retry')).to_be_visible()
                    expect(page.locator('#message')).to_contain_text('Outcome uncertain')
                    expect(page.locator('#retry')).to_be_enabled()
                    page.reload()
                    expect(page.locator('#retry')).to_be_visible()
                    page.locator('#retry').click()
                    expect(page.locator('#retry')).to_be_hidden()
                    expect(page.locator('#identity')).to_contain_text('revision 1')
                    page.screenshot(path=str(args.out/'01-configured-desktop.png'), full_page=True)
                    response = page.request.post(base+'/api/advance', data={'environmentId': 'CASHFLOW-DESKTOP', 'through': '2026-01-06'})
                    assert response.ok, response.text()
                    page.locator('#latest').click()
                    expect(page.locator('#history tr')).to_have_count(4)
                    page.locator('#active').uncheck()
                    page.locator('#reason').fill('Pause future recurring income and expenses')
                    page.locator('#save').click()
                    expect(page.locator('#state')).to_contain_text('paused')
                    engine.terminate()
                    engine.wait(timeout=15)
                    engine = start()
                    page.goto(base+'/customer-cashflow?premise='+premise)
                    expect(page.locator('#state')).to_contain_text('paused')
                    response = page.request.post(base+'/api/advance', data={'environmentId': 'CASHFLOW-DESKTOP', 'through': '2026-02-05'})
                    assert response.ok, response.text()
                    page.locator('#latest').click()
                    expect(page.locator('#history tr')).to_have_count(25)
                    page.locator('#older').click()
                    expect(page.locator('#history tr')).to_have_count(9)
                    page.set_viewport_size({'width': 960, 'height': 900})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(args.out/'02-history-small-desktop.png'), full_page=True)
                    assert not errors, errors
                    assert not external, external
                finally:
                    browser.close()
            result = subprocess.run([*common, '--verify'], cwd=ROOT, capture_output=True, text=True, check=True)
            evidence = {**json.loads(result.stdout), 'desktopWidths': [1440, 960], 'lostReplyExactRetry': True,
                        'restart': True, 'invalidPrecisionRejected': True, 'pageErrors': errors, 'externalRequests': external}
            (args.out/'result.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
            print(json.dumps(evidence))
        finally:
            engine.terminate()
            engine.wait(timeout=15)


if __name__ == '__main__':
    main()
