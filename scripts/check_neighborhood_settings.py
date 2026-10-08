"""Verify street selection persists in Studio and the town API uses that choice."""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_world_library import worker  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine-python', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    from playwright.sync_api import expect, sync_playwright
    errors, external = [], []
    with worker([args.engine_python, '-m', 'utilsim.worker.entry'], args.out, 1) as address:
        parsed = urlsplit(address)
        base = parsed.scheme+'://'+parsed.netloc
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: external.append(request.url)
                        if not request.url.startswith(base) else None)
                page.goto(address)
                page.locator('#new-simulation, #setup-name').first.wait_for()
                if page.locator('#new-simulation').count():
                    page.locator('#new-simulation').click()
                page.get_by_label('Simulation name', exact=True).fill('Neighborhood street acceptance')
                page.get_by_role('button', name='Continue', exact=False).click()
                page.locator('input[name="test-goal"][value="everything"]').check()
                page.get_by_role('button', name='Choose environment', exact=False).click()
                page.locator('#stage-advanced > summary').click()
                page.locator('details[data-group="town"] > summary').click()
                choice = page.locator('[data-path="town.street_pattern"] select')
                expect(choice).to_have_value('legacy')
                choice.select_option('neighborhoods')
                expect(choice).to_have_value('neighborhoods')
                choice.scroll_into_view_if_needed()
                page.screenshot(path=str(args.out/'settings-1440.png'))
                page.reload()
                page.get_by_role('button', name='Continue setup', exact=False).click()
                choice = page.locator('[data-path="town.street_pattern"] select')
                expect(choice).to_have_value('neighborhoods')
                # Read the persisted choice from the real form for the generation request.
                selected = choice.input_value()
                page.set_viewport_size({'width': 1024, 'height': 768})
                for selector in ('#stage-advanced', 'details[data-group="town"]'):
                    if page.locator(selector).get_attribute('open') is None:
                        page.locator(selector+' > summary').click()
                choice.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out/'settings-1024.png'))
                request = {'preset': 'village', 'seed': 'STREETS-UI', 'houses': 20,
                           'overrides': {'town': {'street_pattern': selected}}}
                response = page.request.post(base+'/api/towns', data=request)
                assert response.status in (201, 202), response.text()
                town_id = response.json()['townId']
                deadline = time.monotonic()+90
                while True:
                    response = page.request.get(base+'/api/towns/'+town_id)
                    if response.status == 200 and response.json().get('status') == 'ready':
                        break
                    assert time.monotonic() < deadline, response.text()
                    time.sleep(.25)
                response = page.request.get(base+'/api/towns/'+town_id+'/snapshot.json')
                assert response.status == 200
                snapshot = response.json()
                assert snapshot['config']['town']['street_pattern'] == selected
                assert snapshot['source']['streetModel'] == 'neighborhood-streets/1'
                assert snapshot['stats']['houses'] == 20
                (args.out/'generated-town.json').write_text(json.dumps(snapshot), encoding='utf-8')
                assert not errors and not external, (errors, external)
                result = {'passed': True, 'persistedSetting': selected, 'townId': town_id,
                          'houses': 20, 'source': snapshot['source'], 'viewports': [1440, 1024],
                          'browserErrors': errors, 'externalRequests': external}
                (args.out/'acceptance.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
                print(json.dumps(result))
            finally:
                browser.close()


if __name__ == '__main__':
    main()
