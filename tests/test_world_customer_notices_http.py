"""Administrator controls and filtered financial-contact feed boundaries."""
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_world_cruise import command as cruise_command
from test_world_customer_finance import advance
from test_world_customer_notices import command, setup

from utilsim.world import cruise, customer_notices, delivery
from utilsim.world.server import make_server


@pytest.fixture
def desktop(tmp_path):
    owner = setup(tmp_path)
    server = make_server(owner, 0, cruise_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield owner, f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get(base, path='/api/customer-notices'):
    with urlopen(base+path) as response:
        return json.load(response)


def post(base, value, **headers):
    with urlopen(Request(base+'/api/customer-notices', json.dumps(value).encode(),
                         {'Content-Type': 'application/json', **headers})) as response:
        return json.load(response)


def test_policy_static_and_filtered_delayed_feed(desktop):
    owner, base = desktop
    for path, fragment in [('/customer-notices', b'<html'), ('/customer-notices.js', b'/api/customer-notices'),
                           ('/customer-finance', b'href="/customer-notices"')]:
        with urlopen(base+path) as response:
            assert fragment in response.read()
            assert response.headers['X-Content-Type-Options'] == 'nosniff'
    payload = command(owner, 'http-policy', deliveryDelaySeconds=86400)
    result = post(base, payload)
    assert post(base, payload) == result
    advance(owner)
    assert get(base)['items'][0]['available'] is False
    assert get(base, '/api/financial-contact-intents')['items'] == []
    advance(owner)
    assert len(get(base, '/api/financial-contact-intents')['items']) == 1
    assert post(base, payload) == result
    page = get(base, '/api/customer-notices?limit=1')
    assert len(page['items']) == 1 and page['nextAfter'] == 1
    assert len(get(base, '/api/customer-notices?after=1')['items']) == 1


@pytest.mark.parametrize('headers,code', [({'Origin': 'https://external.invalid'}, 403),
                                        ({'Host': 'external.invalid'}, 403), ({'Content-Type': 'text/plain'}, 415)])
def test_external_browser_cannot_change_notices(desktop, headers, code):
    owner, base = desktop
    before = customer_notices.inspect(owner)
    with pytest.raises(HTTPError) as error:
        post(base, command(owner, 'rejected'), **headers)
    assert error.value.code == code and customer_notices.inspect(owner) == before


@pytest.mark.parametrize('path', ['/api/customer-notices?unknown=x', '/api/customer-notices?after=1&after=2',
                                  '/api/customer-notices?limit=101', '/api/customer-notices?after=-1',
                                  '/api/financial-contact-intents?after=broken', '/api/financial-contact-intents?limit=0',
                                  '/api/financial-contact-intents?asOf=2099-01-01'])
def test_invalid_queries_rejected(desktop, path):
    owner, base = desktop
    before = customer_notices.inspect(owner)
    with pytest.raises(HTTPError) as error:
        get(base, path)
    assert error.value.code == 422 and customer_notices.inspect(owner) == before


def test_cruise_guard_and_managed_world_clock(desktop):
    owner, base = desktop
    payload = command(owner, 'paused-policy', active=False)
    cruise.command(owner, cruise_command(owner))
    with pytest.raises(HTTPError) as error:
        post(base, payload)
    assert error.value.code == 422
    cruise.command(owner, cruise_command(owner, 'cancel'))
    delivery.configure(owner, 'TEST')
    assert post(base, payload)['status'] == 'completed'
    assert get(base)['through'] == payload['effectiveDate']
