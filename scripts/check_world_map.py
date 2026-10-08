"""Browser acceptance on a new SQLite backup; the source world is read-only."""
import argparse
import json
import sqlite3
import sys
import threading
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utilsim.world import World  # noqa: E402
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
    with closing(sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
    world = World(target)
    snapshot = WorldMap(world).snapshot()
    home = snapshot['premises'][0]
    original = WorldMap(world).premise(home['id'])
    if not original['assets']:
        raise ValueError('Select a source world whose first premise has a meter.')
    server = make_server(world, 0, args.viewer_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:' + str(server.server_port)
    errors, external = [], []
    from playwright.sync_api import expect, sync_playwright
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('request', lambda r: external.append(r.url) if not r.url.startswith(base) else None)
                page.goto(base + '/map')
                page.wait_for_function("document.body.dataset.ready === 'true' || document.querySelector('#status').classList.contains('error')", timeout=60000)
                assert page.locator('body').get_attribute('data-ready') == 'true', page.locator('#status').inner_text()
                expect(page.locator('#map canvas')).to_be_visible()
                page.screenshot(path=str(args.out / 'town-1440.png'))
                page.get_by_label('Find address or premise').fill(home['id'])
                page.get_by_role('button', name='Find', exact=True).click()
                page.locator('#matches button').first.click()
                expect(page.locator('#place')).to_contain_text(home['id'])
                expect(page.locator('#place .asset')).to_have_count(len(original['assets']))
                page.get_by_label('Water', exact=True).check()
                page.get_by_role('button', name='Top view', exact=True).click()
                meter = original['assets'][0]
                world.replace_meter('map-check-replace', original['environmentId'], meter['id'],
                                    'map-check-device', 'map-check-work', 'Copied world browser acceptance')
                page.get_by_role('button', name='Refresh world', exact=True).click()
                expect(page.locator('#place')).to_contain_text('map-check-device')
                page.set_viewport_size({'width': 1024, 'height': 768})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out / 'property-1024.png'))
                page.reload()
                page.wait_for_selector('body[data-ready="true"]')
                page.get_by_label('Find address or premise').fill(home['id'])
                page.get_by_role('button', name='Find', exact=True).click()
                page.locator('#matches button').first.click()
                expect(page.locator('#place')).to_contain_text('map-check-device')
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        assert WorldMap(World(target)).snapshot() == snapshot
        assert world.status()['through'] == original['through']
        evidence = {'passed': True, 'town': snapshot['id'], 'premises': len(snapshot['premises']),
                    'through': original['through'], 'selectedPremise': home['id'], 'sourceModified': False,
                    'browserErrors': errors, 'externalRequests': external, 'viewports': [1440, 1024],
                    'checks': ['original renderer', 'property search', 'network layer', 'camera control',
                               'physical replacement refresh', 'reload persistence', 'immutable snapshot']}
        (args.out / 'acceptance.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(evidence))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
