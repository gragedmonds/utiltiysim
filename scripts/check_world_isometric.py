"""Verify the restored isometric world map against a copied physical world."""
import argparse
import hashlib
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
    digest = hashlib.sha256(args.db.read_bytes()).hexdigest()
    target = args.out / 'world.sqlite'
    with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
    world = World(target)
    snapshot = WorldMap(world).snapshot()
    premise = snapshot['premises'][0]
    original = WorldMap(world).premise(premise['id'])
    server = make_server(world, 0, args.viewer_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    errors, external = [], []
    from playwright.sync_api import expect, sync_playwright
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.add_init_script('''window.worldMapDraws=0;
                    for(const kind of ['WebGLRenderingContext','WebGL2RenderingContext']){
                      const proto=window[kind]?.prototype;if(!proto)continue;
                      for(const key of ['drawArrays','drawElements','drawArraysInstanced','drawElementsInstanced']){
                        const original=proto[key];if(!original)continue;
                        proto[key]=function(...args){window.worldMapDraws++;return original.apply(this,args);};
                      }
                    }''')
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('request', lambda r: external.append(r.url) if not r.url.startswith(base) else None)
                page.goto(base+'/map')
                page.wait_for_selector('body[data-ready="true"]', timeout=60000)
                expect(page.locator('#map')).to_have_attribute('data-renderer', 'iso')
                expect(page.locator('#map canvas')).to_have_class('iso-map')
                expect(page.locator('#map')).to_have_attribute('data-view', 'ne')
                # Wait for one painted picture after the asynchronous atlas is ready.
                page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                page.screenshot(path=str(args.out/'whole-town-1440.png'))
                page.get_by_label('Find address or premise').fill(premise['id'])
                page.get_by_role('button', name='Find', exact=True).click()
                page.locator('#matches button').first.click()
                expect(page.locator('#place')).to_contain_text(premise['id'])
                assert page.get_by_role('link', name='Manage physical occupancy').count() == 1
                page.screenshot(path=str(args.out/'property-1440.png'))
                pictures = []
                for expected_view in ('nw', 'sw', 'se', 'ne'):
                    page.get_by_role('button', name='Rotate', exact=True).click()
                    expect(page.locator('#map')).to_have_attribute('data-view', expected_view)
                    page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                    pictures.append(hashlib.sha256(page.locator('#map canvas').screenshot()).hexdigest())
                assert len(set(pictures)) == 4, 'Camera turns must change the rendered picture'
                page.get_by_role('button', name='Plan view', exact=True).click()
                expect(page.locator('#top')).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('#map')).to_have_attribute('data-view', 'top')
                page.locator('#map canvas').focus()
                page.keyboard.press('t')
                expect(page.locator('#map')).to_have_attribute('data-view', 'ne')
                page.keyboard.press('r')
                expect(page.locator('#map')).to_have_attribute('data-view', 'nw')
                page.get_by_label('Water', exact=True).check()
                page.get_by_role('button', name='Refresh world').click()
                expect(page.get_by_role('button', name='Refresh world')).to_be_enabled()
                expect(page.locator('#place')).to_contain_text(premise['id'])
                page.set_viewport_size({'width': 1024, 'height': 768})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out/'property-1024.png'))
                page.get_by_label('Map style', exact=True).select_option('3d')
                page.wait_for_selector('body[data-ready="true"]', timeout=60000)
                expect(page.locator('#map')).to_have_attribute('data-renderer', '3d')
                expect(page.locator('#rotate')).to_be_hidden()
                page.wait_for_function('window.worldMapDraws>0')
                draw_count = page.evaluate('window.worldMapDraws')
                page.evaluate('new Promise(resolve=>{let n=0;function frame(){if(++n===20)resolve();else requestAnimationFrame(frame);}requestAnimationFrame(frame);})')
                assert page.evaluate('window.worldMapDraws') == draw_count, 'Idle physical map must not render continuously'
                page.get_by_label('Find address or premise').fill(premise['id'])
                page.get_by_role('button', name='Find', exact=True).click()
                page.locator('#matches button').first.click()
                expect(page.locator('#place')).to_contain_text(premise['id'])
                page.wait_for_function('window.worldMapDraws>'+str(draw_count))
                draw_count = page.evaluate('window.worldMapDraws')
                page.get_by_role('button', name='Top view', exact=True).click()
                page.wait_for_function('window.worldMapDraws>'+str(draw_count))
                draw_count = page.evaluate('window.worldMapDraws')
                page.get_by_label('Water', exact=True).check()
                page.wait_for_function('window.worldMapDraws>'+str(draw_count))
                draw_count = page.evaluate('window.worldMapDraws')
                page.set_viewport_size({'width': 1200, 'height': 850})
                page.wait_for_function('window.worldMapDraws>'+str(draw_count))
                page.get_by_label('Map style', exact=True).select_option('iso')
                page.wait_for_selector('body[data-ready="true"]', timeout=60000)
                # A missing atlas must produce a useful error, not a false-ready blank map.
                page.route('**/viewer/iso/atlas.json', lambda route: route.fulfill(status=404, body='{}'))
                page.reload()
                expect(page.locator('#status')).to_contain_text('Isometric artwork could not load')
                assert page.locator('body[data-ready="true"]').count() == 0
                assert page.locator('#map canvas').count() == 0
                page.unroute('**/viewer/iso/atlas.json')
                page.reload()
                page.wait_for_selector('body[data-ready="true"]', timeout=60000)
                assert not errors, errors
                assert not external, external
            except Exception:
                (args.out/'failure.json').write_text(json.dumps({'url': page.url, 'errors': errors,
                    'status': page.locator('#status').text_content()}, indent=2), encoding='utf-8')
                page.screenshot(path=str(args.out/'failure.png'))
                raise
            finally:
                browser.close()
        assert WorldMap(world).snapshot() == snapshot
        assert WorldMap(world).premise(premise['id']) == original
        assert hashlib.sha256(args.db.read_bytes()).hexdigest() == digest
        result = {'passed': True, 'premises': len(snapshot['premises']), 'sourceModified': False,
                  'physicalRecordsModified': False, 'views': ['ne', 'se', 'sw', 'nw', 'top', '3d'],
                  'viewports': [1440, 1024], 'browserErrors': errors, 'externalRequests': external}
        (args.out/'acceptance.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
