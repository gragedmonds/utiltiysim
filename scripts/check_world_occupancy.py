"""Exercise dated occupancy controls on a disposable copy of a populated world."""
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
from utilsim.world import World, occupancy  # noqa: E402
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
    with closing(sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
    world = World(target)
    snapshot = WorldMap(world).snapshot()
    home = next(p for p in snapshot['premises'] if p.get('occupied') and p.get('occupants', 0) > 0)
    original = WorldMap(world).premise(home['id'])
    with world.db() as db:
        meta = world.metadata(db)
    old_export = world.export_v2(meta['start'], meta['through'])
    day = date.fromisoformat(meta['through'])
    errors, external = [], []
    server = make_server(world, 0, args.viewer_dir)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{port}'
    from playwright.sync_api import expect, sync_playwright

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('request', lambda r: external.append(r.url) if not r.url.startswith(base) else None)
                page.goto(base + '/occupancy?premiseId=' + home['id'])
                expect(page.locator('#current')).to_contain_text(home['id'])

                def schedule(when, occupied, people, reason):
                    page.get_by_label('Effective date').fill(when.isoformat())
                    page.get_by_label('Occupancy', exact=True).select_option('true' if occupied else 'false')
                    if occupied:
                        page.get_by_label('People', exact=True).fill(str(people))
                    page.get_by_label('Reason / evidence').fill(reason)
                    page.get_by_role('button', name='Schedule change', exact=True).click()

                # Commit the real command, then lose only its reply. The reload
                # must retain the same ID/payload and recover the same acceptance.
                def lost_reply(route):
                    if route.request.method == 'POST':
                        response = route.fetch()
                        assert response.ok
                        route.abort()
                        page.unroute('**/api/occupancy', lost_reply)
                    else:
                        route.continue_()
                page.route('**/api/occupancy', lost_reply)
                schedule(day, False, 0, 'Browser move-out with lost reply')
                expect(page.locator('#retry')).to_be_visible()
                page.reload()
                expect(page.locator('#retry')).to_be_visible()
                page.get_by_role('button', name='Retry the same command').click()
                expect(page.locator('#message')).to_contain_text('Command accepted at revision 1')
                assert len(occupancy.inspect(world, home['id'])['changes']) == 1
                page.get_by_role('button', name=f'Cancel change on {day}').click()
                expect(page.locator('#message')).to_contain_text('revision 2')
                schedule(day, False, 0, 'Move-out confirmed')
                expect(page.locator('#message')).to_contain_text('revision 3')
                schedule(day + timedelta(days=2), True, home['occupants']*2, 'Larger household arrives')
                expect(page.locator('#message')).to_contain_text('revision 4')
                page.screenshot(path=str(args.out / 'scheduled-1440.png'), full_page=True)
                page.get_by_role('link', name='World controls', exact=True).click()
                page.get_by_label('Simulate up to (exclusive)').fill((day + timedelta(days=1)).isoformat())
                page.get_by_role('button', name='Advance time', exact=True).click()
                expect(page.locator('#message')).to_contain_text('World saved through', timeout=60000)
                page.get_by_role('link', name='Occupancy changes', exact=True).click()
                page.get_by_label('Premise ID').fill(home['id'])
                page.get_by_role('button', name='Load property').click()
                expect(page.locator('#current')).to_contain_text('Vacant · 0 people')
                page.set_viewport_size({'width': 1024, 'height': 768})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out / 'vacant-1024.png'), full_page=True)

                server.shutdown()
                server.server_close()
                thread.join()
                world = World(target)
                server = make_server(world, port, args.viewer_dir)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                page.goto(base + '/')
                page.get_by_label('Simulate up to (exclusive)').fill((day + timedelta(days=3)).isoformat())
                page.get_by_role('button', name='Advance time', exact=True).click()
                expect(page.locator('#message')).to_contain_text('World saved through', timeout=60000)
                page.goto(base + '/map')
                page.wait_for_selector('body[data-ready="true"]', timeout=60000)
                page.get_by_label('Find address or premise').fill(home['id'])
                page.get_by_role('button', name='Find', exact=True).click()
                page.locator('#matches button').first.click()
                expect(page.locator('#place')).to_contain_text(f"{home['occupants']*2} occupants")
                page.get_by_role('link', name='Manage physical occupancy').click()
                expect(page.locator('#current')).to_contain_text(f"Occupied · {home['occupants']*2} people")
                page.screenshot(path=str(args.out / 'occupied-1024.png'), full_page=True)
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        assert world.export_v2(meta['start'], meta['through']) == old_export
        assert WorldMap(world).snapshot() == snapshot
        state = occupancy.inspect(world, home['id'])
        assert [c['status'] for c in state['changes']] == ['applied', 'applied', 'cancelled']
        assert hashlib.sha256(args.db.read_bytes()).hexdigest() == digest
        evidence = {'passed': True, 'premises': len(snapshot['premises']), 'sourceModified': False,
                    'originalThrough': original['through'], 'through': world.status()['through'],
                    'historyPreserved': True, 'browserErrors': errors, 'externalRequests': external,
                    'viewports': [1440, 1024], 'checks': ['lost reply + reload + identical command retry',
                    'cancel and replace', 'vacancy', 'dated move-in', 'server restart', 'map current occupancy']}
        (args.out / 'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(evidence))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
