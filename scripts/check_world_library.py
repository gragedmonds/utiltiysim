"""Exercise Studio's saved-world library and restart on a disposable source backup."""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utilsim.world import World  # noqa: E402
from utilsim.world.map_view import WorldMap  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def worker(command, store, iteration):
    ready = store / f'ready-{iteration}.json'
    with (store / f'server-{iteration}.log').open('w') as log:
        process = subprocess.Popen([*command, '--store', str(store),
                                    '--ready-file', str(ready)], cwd=ROOT, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 60
            while not ready.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Worker did not start; inspect its local log.')
                time.sleep(.1)
            address = json.loads(ready.read_text())['url']
            parsed = urlsplit(address)
            while True:
                try:
                    with urlopen(parsed.scheme + '://' + parsed.netloc + '/health', timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Worker never accepted requests.') from None
                    time.sleep(.1)
            yield address
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            ready.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    engine = parser.add_mutually_exclusive_group(required=True)
    engine.add_argument('--engine-python')
    engine.add_argument('--engine-executable')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    command = ([args.engine_executable] if args.engine_executable else
               [args.engine_python, '-m', 'utilsim.worker.entry'])
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    target = args.out / 'world.sqlite'
    with closing(sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
    original = hashlib.sha256(target.read_bytes()).hexdigest()
    world = World(target)
    snap = WorldMap(world).snapshot()
    home = snap['premises'][0]['id']
    before = WorldMap(world).premise(home)
    store = args.out / 'library'
    store.mkdir()
    errors, external, origins = [], [], set()
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: external.append(r.url) if
                    (urlsplit(r.url).scheme, urlsplit(r.url).netloc) not in origins else None)
            for iteration in (1, 2):
                with worker(command, store, iteration) as address:
                    url = urlsplit(address)
                    base = url.scheme + '://' + url.netloc
                    origins.add((url.scheme, url.netloc))
                    assert page.request.get(base + '/local/worlds').status == 401
                    page.goto(address)
                    page.get_by_role('link', name='Saved world maps', exact=True).click()
                    if iteration == 1:
                        page.get_by_label('Existing world database').fill(str(target))
                        page.get_by_role('button', name='Add saved world', exact=True).click()
                    expect(page.locator('.world')).to_have_count(1)
                    page.screenshot(path=str(args.out / f'library-{iteration}.png'))
                    page.get_by_role('link', name='Open map', exact=True).click()
                    page.wait_for_selector('body[data-ready="true"]', timeout=60000)
                    assert page.request.get(base + '/local/worlds/' + page.url.split('world=')[1] + '/map/status').status == 401
                    expect(page.locator('#map canvas')).to_be_visible()
                    page.get_by_label('Find address or premise').fill(home)
                    page.get_by_role('button', name='Find', exact=True).click()
                    page.locator('#matches button').first.click()
                    expect(page.locator('#place')).to_contain_text(home)
                    if iteration == 1:
                        assert hashlib.sha256(target.read_bytes()).hexdigest() == original
                        meter = before['assets'][0]
                        world.replace_meter('library-check', before['environmentId'], meter['id'],
                                            'library-replacement', 'library-order', 'Disposable browser acceptance')
                        page.get_by_role('button', name='Refresh world', exact=True).click()
                    expect(page.locator('#place')).to_contain_text('library-replacement')
                    page.set_viewport_size({'width': 1024, 'height': 768})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(args.out / f'map-{iteration}.png'))
                    page.get_by_role('link', name='Saved worlds', exact=True).click()
                    if iteration == 2:
                        page.get_by_role('button', name='Remove entry', exact=True).click()
                        expect(page.locator('.world')).to_have_count(0)
                        assert target.is_file()
        finally:
            browser.close()
    assert not errors, errors
    assert not external, external
    assert WorldMap(world).snapshot() == snap
    assert world.status()['through'] == before['through']
    result = {'passed': True, 'premises': len(snap['premises']), 'sourceModified': False,
              'checks': ['Studio navigation', 'register', 'authorized map', 'read-only open', 'live refresh',
                         'worker restart', 'persisted library', 'small desktop', 'remove without delete'],
              'browserErrors': errors, 'externalRequests': external}
    (args.out / 'acceptance.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
