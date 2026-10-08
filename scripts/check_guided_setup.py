"""Exercise the desktop wizard against an isolated local engine and save screenshots.

Run with a Python that has Playwright; --engine-python can select the project's environment.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine-python', default=sys.executable)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8769)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    args.out = args.out.resolve()
    (args.out / 'store').mkdir()
    root = Path(__file__).resolve().parents[1]
    token = 'isolated-guided-setup-browser-test'
    code = ('import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; '
            'from utilsim.worker.jobs import LocalJobs; from utilsim.worker.server import create_app; '
            'import uvicorn; uvicorn.run(create_app(LocalJobs(Path(sys.argv[2])), sys.argv[3]), '
            'host="127.0.0.1", port=int(sys.argv[4]), log_level="warning")')
    base = f'http://127.0.0.1:{args.port}'
    with (args.out / 'engine.log').open('w', encoding='utf-8') as log:
        engine = subprocess.Popen([args.engine_python, '-c', code, str(root), str(args.out / 'store'), token,
                                   str(args.port)], cwd=root, stdout=log, stderr=log)
        try:
            for _ in range(120):
                if engine.poll() is not None:
                    raise RuntimeError('Engine stopped; see engine.log')
                try:
                    urllib.request.urlopen(base + '/api/setup/configuration?preset=small_town', timeout=1).close()
                    break
                except OSError:
                    time.sleep(.5)
            from playwright.sync_api import expect, sync_playwright
            errors = []
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(base + '/#token=' + token)
                expect(page.locator('.gw')).to_be_visible(timeout=30000)
                page.locator('#gw-name').fill('Northstar Water')
                expect(page.locator('[data-pace="quick"]')).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('.gw nav [data-jump]')).to_have_count(6)
                page.screenshot(path=str(args.out / '01-start.png'), full_page=True)

                def jump(section, label):
                    details = page.locator('.gw nav details').filter(has=page.locator('summary', has_text=section)).first
                    if details.get_attribute('open') is None:
                        details.locator('summary').click()
                    details.get_by_role('button', name=label, exact=True).click()

                jump('Start', 'Commodities')
                page.locator('[data-service="electric"]').click()
                page.locator('[data-service="gas"]').click()
                expect(page.locator('[data-service="water"]')).to_have_attribute('aria-pressed', 'true')
                jump('Place', 'Town size')
                page.locator('.gw-exact summary').click()
                page.locator('[data-input="town:town.houses"]').fill('20')
                page.locator('#gw-next').click()
                expect(page.locator('[data-jump="region"]')).to_have_attribute('aria-current', 'step')
                page.locator('[data-choice="great_lakes"]').click()
                page.locator('#gw-next').click()
                page.locator('[data-mix-choice="mixed"]').click()
                page.locator('#gw-next').click()
                expect(page.locator('.gw-review-hero')).to_contain_text('Quick setup')
                page.locator('#gw-next').click()
                expect(page.locator('.gw-validated')).to_be_visible(timeout=30000)
                page.screenshot(path=str(args.out / '08-quick-review.png'), full_page=True)
                page.locator('#gw-pace-switch').click()
                jump('Homes', 'Home ages')
                page.locator('[data-choice="new"]').click()
                noise = page.locator('[data-card="town:town.era_noise_years"]')
                noise.locator('summary').first.click()
                noise.locator('[data-input]').fill('7')
                page.locator('[data-choice="historic"]').click()
                expect(page.locator('[data-input="town:town.era_noise_years"]')).to_have_value('7')
                noise.locator('[data-reset]').click()
                expect(page.locator('[data-input="town:town.era_noise_years"]')).to_have_value('10')
                page.screenshot(path=str(args.out / '02-home-ages.png'), full_page=True)
                jump('Networks', 'Infrastructure age')
                page.locator('[data-choice="mature"]').click()
                page.screenshot(path=str(args.out / '03-infrastructure.png'), full_page=True)
                jump('Meters', 'AMI · AMR · Manual')
                page.locator('[data-mix-choice="mixed"]').click()
                handle = page.locator('[data-boundary="0"]')
                bounds = handle.bounding_box()
                x = bounds['x'] + 17 + (bounds['width'] - 34) * .4
                y = bounds['y'] + bounds['height'] / 2
                page.mouse.move(x, y)
                page.mouse.down()
                page.mouse.move(bounds['x'] + 17 + (bounds['width'] - 34) * .6, y, steps=12)
                page.mouse.up()
                expect(page.locator('[data-mix-value="0"]')).to_have_text('60%')
                expect(page.locator('[data-mix-value="2"]')).to_have_text('20%')
                handle.focus()
                page.keyboard.press('ArrowLeft')
                expect(page.locator('[data-mix-value="0"]')).to_have_text('59%')
                page.screenshot(path=str(args.out / '04-meter-mix.png'), full_page=True)
                page.locator('.gw-exact summary').click()
                for i, value in enumerate(['50', '50', '50']):
                    page.locator(f'[data-mix-exact="{i}"]').fill(value)
                page.locator('#gw-apply-mix').click()
                expect(page.locator('#gw-mix-error')).to_contain_text('100%')
                for mix in ([0, 0, 100], [100, 0, 0], [0, 100, 0], [40, 40, 20]):
                    for i, value in enumerate(mix):
                        page.locator(f'[data-mix-exact="{i}"]').fill(str(value))
                    page.locator('#gw-apply-mix').click()
                    for i, value in enumerate(mix):
                        expect(page.locator(f'[data-mix-value="{i}"]')).to_have_text(f'{value}%')
                page.reload()
                expect(page.locator('[data-mix-value="0"]')).to_have_text('40%')
                jump('Meters', 'Meter condition')
                page.locator('[data-choice="worn"]').click()
                page.set_viewport_size({'width': 960, 'height': 800})
                page.screenshot(path=str(args.out / '05-small-desktop.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.locator('#gw-pace-switch').click()
                page.locator('#gw-review').click()
                expect(page.locator('.gw-review-list')).to_contain_text('Annual base failure probability')
                expect(page.locator('.gw-review-list')).to_contain_text('0.04')
                page.locator('#gw-next').click()
                expect(page.locator('.gw-validated')).to_be_visible(timeout=30000)
                page.screenshot(path=str(args.out / '06-review.png'), full_page=True)
                page.locator('#gw-next').click()
                page.wait_for_url('**/world-map?world=*', timeout=120000)
                expect(page.locator('#map canvas')).to_be_visible(timeout=60000)
                page.screenshot(path=str(args.out / '07-created-world.png'), full_page=True)
                world_id = page.url.split('world=')[1]
                response = page.request.get(base + '/local/worlds/' + world_id + '/map/status', headers={'Authorization': 'Bearer ' + token})
                assert response.ok, response.text()
                snapshot = page.request.get(base + '/local/worlds/' + world_id + '/map/snapshot', headers={'Authorization': 'Bearer ' + token}).json()
                assert {s['commodity'] for s in snapshot['servicePoints']} == {'water'}
                page.goto(base + '/#/simulations')
                expect(page.get_by_role('button', name='Open simulation', exact=False)).to_be_visible()
                page.get_by_role('button', name='Open simulation', exact=False).click()
                page.wait_for_url('**/world-map?world=' + world_id)
                # A second setup exercises every Studio page and preserves a whole-utility total.
                page.goto(base + '/#/new')
                expect(page.locator('.gw')).to_be_visible()
                page.locator('#gw-name').fill('Studio coverage')
                page.locator('[data-pace="full"]').click()
                page.locator('[data-mode="studio"]').click()
                jump('Place', 'Town size')
                page.locator('[data-choice="total-25000"]').click()
                expect(page.locator('[data-input="town:town.houses"]')).to_have_value('25000')
                page_ids = page.locator('.gw nav [data-jump]').evaluate_all('(elements)=>elements.map(e=>e.dataset.jump)')
                for identity in page_ids:
                    target = page.locator('.gw nav [data-jump="' + identity + '"]')
                    details = target.locator('..')
                    if details.get_attribute('open') is None:
                        details.locator('summary').click()
                    target.click()
                    assert page.locator('.gw h1').inner_text()
                    assert page.locator('[aria-invalid="true"]').count() == 0
                expect(page.locator('.gw-review-hero')).to_contain_text('25,000 homes')
                page.locator('#gw-next').click()
                expect(page.locator('.gw-validated')).to_be_visible(timeout=30000)
                page.locator('#gw-next').click()
                page.wait_for_url('**/local-runs.html?model=*', timeout=30000)
                saved = page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('utility-studio-simulation:')).map(k=>JSON.parse(localStorage.getItem(k)))")
                studio = next(s for s in saved if s['name'] == 'Studio coverage')
                assert studio['status'] == 'ready' and studio['totalHomes'] == 25000
                assert studio['townOverrides']['town']['houses'] == 10000
                assert studio['guidedSetup']['mode'] == 'studio'
                hosted = browser.new_page(viewport={'width': 1440, 'height': 1000})
                hosted.on('pageerror', lambda e: errors.append(str(e)))
                hosted.goto(base + '/#/new')
                expect(hosted.locator('[data-mode="world"]')).to_be_disabled()
                hosted.locator('.gw nav details').filter(has=hosted.locator('summary', has_text='Place')).locator('summary').click()
                hosted.locator('[data-jump="size"]').click()
                hosted.locator('.gw-exact summary').click()
                hosted.locator('[data-input="town:town.houses"]').fill('20')
                hosted.locator('#gw-review').click()
                hosted.locator('#gw-next').click()
                expect(hosted.locator('.gw-validated')).to_be_visible(timeout=30000)
                assert not errors, errors
                (args.out / 'result.json').write_text(json.dumps({'worldId': world_id, 'studioPagesVisited': len(page_ids), 'hostedValidated': True, 'errors': errors, 'status': response.json()}, indent=2), encoding='utf-8')
                browser.close()
        finally:
            engine.terminate()
            engine.wait(timeout=20)


if __name__ == '__main__':
    main()
