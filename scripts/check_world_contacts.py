"""Copied-town browser and isolated recipient-inbox acceptance for contact intents."""
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
from utilsim.world import World, contacts, network_faults  # noqa: E402
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
    target = args.out/'world.sqlite'
    digest = hashlib.sha256(args.db.read_bytes()).hexdigest()
    with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
    world = World(target)
    with world.db() as db:
        meta = world.metadata(db)
        cat = network_faults._catalog(db)
    old = world.export_v2(meta['start'], meta['through'])
    snapshot = WorldMap(world).snapshot()
    edge = next(e for e in cat[0] if e['commodity'] == 'electric' and e['kind'] == 'supply' and e['enabled'])
    start = date.fromisoformat(meta['through'])
    base_command = {'schemaVersion': network_faults.VERSION, 'environmentId': meta['environment'],
                    'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin', 'commodity': 'electric',
                    'edgeId': edge['id'], 'causalReference': 'acceptance', 'reason': 'Copied outage experience'}
    fault = network_faults.command(world, {**base_command, 'commandId': 'experience-outage', 'action': 'start',
                                          'effectiveDate': meta['through'], 'expectedRevision': 0})
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
                    page.goto(base+'/contacts')
                    expect(page.locator('#state')).to_contain_text('Contact generation')
                page.goto(base+'/')
                page.get_by_role('link', name='Customer awareness', exact=True).click()
                expect(page.locator('#state')).to_contain_text('Model not enabled')
                page.get_by_label('Generate contact intents').check()
                page.get_by_label('Daily notice probability').fill('1')
                page.get_by_label('Delivery delay').fill('86400')
                page.get_by_label('Repeat after days').fill('1')
                page.get_by_label('Maximum contacts').fill('3')
                page.get_by_label('Policy evidence').fill('Explicit copied-town customer experience scenario')
                def lose_reply(route):
                    if route.request.method == 'POST':
                        assert route.fetch().ok
                        route.abort()
                        page.unroute('**/api/contacts', lose_reply)
                    else:
                        route.continue_()
                page.route('**/api/contacts', lose_reply)
                page.get_by_role('button', name='Save contact behavior').click()
                expect(page.locator('#retry')).to_be_visible()
                page.reload()
                page.get_by_role('button', name='Retry the same command').click()
                expect(page.locator('#state')).to_contain_text('revision 1')
                advance(1)
                assert contacts.ready(world)['items'] == []
                first_count = contacts.inspect(world)['counts']['pending']
                assert first_count > 25
                expect(page.locator('#history tr')).to_have_count(25)
                expect(page.locator('#history')).to_contain_text('Delayed')
                page.screenshot(path=str(args.out/'delayed-1440.png'), full_page=True)
                page.get_by_role('button', name='Next contacts').click()
                expect(page.locator('#history tr')).to_have_count(25)
                advance(2)
                assert contacts.ready(world)['items']
                # Restore physical supply; generated contacts persist, further repeats stop.
                network_faults.command(world, {**base_command, 'commandId': 'experience-restore', 'action': 'restore',
                    'effectiveDate': (start+timedelta(days=2)).isoformat(), 'expectedRevision': 1,
                    'faultId': fault['faultId'], 'workOrderId': 'ACCEPTANCE-WO'})
                advance(3)
                total = contacts.inspect(world)['counts']['pending']
                assert total == first_count*2
                # Real separate local inbox used only for protocol acceptance, not a fake ticket.
                inbox_path = args.out/'recipient-inbox.sqlite'
                with closing(sqlite3.connect(inbox_path)) as inbox:
                    inbox.execute('CREATE TABLE received(id TEXT PRIMARY KEY,fingerprint TEXT,payload TEXT)')
                    inbox.commit()
                def receive(intent):
                    with closing(sqlite3.connect(inbox_path)) as inbox:
                        fingerprint = stable(intent)
                        old_row = inbox.execute('SELECT fingerprint FROM received WHERE id=?', (intent['id'],)).fetchone()
                        if old_row:
                            assert old_row[0] == fingerprint
                        else:
                            inbox.execute('INSERT INTO received VALUES(?,?,?)', (intent['id'], fingerprint, json.dumps(intent)))
                            inbox.commit()
                    return {'id': intent['id'], 'environmentId': intent['environmentId'], 'fingerprint': fingerprint,
                            'status': 'accepted', 'receiptId': 'INBOX-'+intent['id']}
                def lost_ack(intent):
                    receive(intent)
                    raise ConnectionError('Lost acknowledgment')
                assert contacts.relay(world, lost_ack, limit=1)['blocked']
                server.shutdown()
                server.server_close()
                thread.join()
                world = World(target)
                server = make_server(world, port, args.viewer_dir)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                while contacts.relay(world, receive, limit=100)['accepted']:
                    pass
                assert contacts.inspect(world)['counts'] == {'accepted': total}
                with closing(sqlite3.connect(inbox_path)) as inbox:
                    assert inbox.execute('SELECT COUNT(*) FROM received').fetchone()[0] == total
                    for (raw,) in inbox.execute('SELECT payload FROM received'):
                        assert fault['faultId'] not in raw
                        assert all(k not in json.loads(raw) for k in ('sourceTable', 'assetId', 'quantity', 'policy'))
                page.reload()
                expect(page.locator('#summary')).to_contain_text('0 pending intents')
                page.get_by_label('Generate contact intents').uncheck()
                page.get_by_label('Policy evidence').fill('Pause new intent generation')
                page.get_by_role('button', name='Save contact behavior').click()
                expect(page.locator('#state')).to_contain_text('paused')
                page.set_viewport_size({'width': 1024, 'height': 768})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert '\ufffd' not in page.locator('body').inner_text()
                page.screenshot(path=str(args.out/'acknowledged-1024.png'), full_page=True)
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        assert world.export_v2(meta['start'], meta['through']) == old
        assert WorldMap(world).snapshot() == snapshot
        assert hashlib.sha256(args.db.read_bytes()).hexdigest() == digest
        evidence = {'passed': True, 'premises': len(snapshot['premises']), 'experiencedCallers': first_count,
                    'acceptedIntents': total, 'viewports': [1440, 1024], 'sourceModified': False,
                    'historyPreserved': True, 'browserErrors': errors, 'externalRequests': external,
                    'checks': ['lost policy reply/reload/retry', 'future availability filter', 'bounded pages',
                               'repeat memory', 'physical restoration retains intents', 'lost receipt/restart/dedup',
                               'separate recipient inbox', 'hidden causes excluded']}
        (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(evidence))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
