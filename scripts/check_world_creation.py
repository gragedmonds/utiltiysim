"""Create and reopen a world through Studio without altering the supplied snapshot."""
import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from check_world_library import worker

from utilsim.world import World
from utilsim.world.map_view import WorldMap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    engines = parser.add_mutually_exclusive_group(required=True)
    engines.add_argument('--engine-python')
    engines.add_argument('--engine-executable')
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    source_digest = hashlib.sha256(args.snapshot.read_bytes()).hexdigest()
    saved = root / ('snapshot.json.gz' if args.snapshot.suffix == '.gz' else 'snapshot.json')
    shutil.copyfile(args.snapshot, saved)
    opener = gzip.open if saved.suffix == '.gz' else open
    with opener(saved, 'rt', encoding='utf-8') as stream:
        snapshot = json.load(stream)
    store = root / 'library'
    store.mkdir()
    command = ([args.engine_executable] if args.engine_executable else
               [args.engine_python, '-m', 'utilsim.worker.entry'])
    errors, external, origins = [], [], set()
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: external.append(r.url) if
                    (urlsplit(r.url).scheme, urlsplit(r.url).netloc) not in origins else None)
            for iteration in (1, 2):
                with worker(command, store, iteration) as address:
                    parsed = urlsplit(address)
                    origins.add((parsed.scheme, parsed.netloc))
                    page.goto(address)
                    page.get_by_role('link', name='Saved world maps', exact=True).click()
                    if iteration == 1:
                        page.get_by_label('Saved town snapshot', exact=True).fill(str(saved))
                        page.get_by_label('New environment name').fill('CREATION-BROWSER')
                        page.get_by_label('World start date').fill('2026-03-01')
                        page.get_by_role('button', name='Create world', exact=True).click()
                    expect(page.locator('.world')).to_have_count(1, timeout=30000)
                    expect(page.locator('.world')).to_contain_text('CREATION-BROWSER')
                    page.screenshot(path=str(root / f'library-{iteration}.png'), full_page=True)
                    page.get_by_role('link', name='Open map', exact=True).click()
                    page.wait_for_selector('body[data-ready="true"]', timeout=60000)
                    identity = parse_qs(urlsplit(page.url).query)['world'][0]
                    if iteration == 1:
                        with closing(sqlite3.connect(store / 'world-library.sqlite')) as db:
                            target = db.execute('SELECT path FROM worlds WHERE id=?', (identity,)).fetchone()[0]
                        world = World(target)
                        assert world.status()['days'] == world.status()['observations'] == 0
                        assert world.status()['through'] == '2026-03-01'
                        world.advance('2026-03-03')
                        page.get_by_role('button', name='Refresh world', exact=True).click()
                        saved.unlink()  # Restart must not depend on the input remaining available.
                    expect(page.locator('#date')).to_contain_text('2026-03-03')
                    page.get_by_label('Find address or premise').fill(snapshot['premises'][0]['id'])
                    page.get_by_role('button', name='Find', exact=True).click()
                    page.locator('#matches button').first.click()
                    expect(page.locator('#place')).to_contain_text('2026-03-02')
                    page.set_viewport_size({'width': 1024, 'height': 768})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(root / f'map-{iteration}.png'))
            assert WorldMap(world).snapshot() == snapshot
        finally:
            browser.close()
    assert not errors, errors
    assert not external, external
    assert hashlib.sha256(args.snapshot.read_bytes()).hexdigest() == source_digest
    evidence = {'passed': True, 'premises': len(snapshot['premises']), 'sourceModified': False,
                'through': world.status()['through'], 'observations': world.status()['observations'],
                'checks': ['create in Studio', 'zero initial history', 'original snapshot', 'physical advance refresh',
                           'restart after source disappearance', 'property inspection', 'small desktop'],
                'browserErrors': errors, 'externalRequests': external}
    (root / 'acceptance.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
