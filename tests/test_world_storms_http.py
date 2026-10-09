"""Desktop boundary tests for dated storm controls and controller ownership."""
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_world_cruise import command as cruise_command
from test_world_network_faults import world

from utilsim.world import cruise, storms
from utilsim.world.server import make_server


@pytest.fixture
def desktop(tmp_path):
    owner = world(tmp_path)
    server = make_server(owner, 0, cruise_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield owner, f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def payload(owner, identity='http-storm'):
    state = storms.inspect(owner)
    return {'schemaVersion': 'world-storms/1', 'commandId': identity,
            'environmentId': state['environmentId'], 'worldFingerprint': state['worldFingerprint'],
            'actorId': 'world-admin', 'expectedRevision': state['revision'],
            'effectiveDate': state['through'], 'action': 'schedule', 'reason': 'Explicit test weather',
            'causalReference': 'http-acceptance', 'startDate': '2026-01-02', 'endDate': '2026-01-04',
            'temperatureOffsetC': -15, 'multipliers': dict.fromkeys(('electric', 'gas', 'water', 'sewer'), 3)}


def get(base, path):
    with urlopen(base+path) as response:
        return json.load(response)


def post(base, value, **headers):
    request = Request(base+'/api/storms', json.dumps(value).encode(),
                      {'Content-Type': 'application/json', **headers})
    with urlopen(request) as response:
        return json.load(response)


def test_desktop_schedule_exact_retry_and_history(desktop):
    owner, base = desktop
    before = get(base, '/api/storms')
    assert before['enabled'] is False
    with urlopen(base+'/') as response:
        assert b'href="/storms"' in response.read()
    for path, fragment in (('/storms', b'<html'), ('/storms.js', b'/api/storms')):
        with urlopen(base+path) as response:
            assert fragment in response.read()
            assert response.headers['X-Content-Type-Options'] == 'nosniff'
    command = payload(owner)
    first = post(base, command)
    assert post(base, command) == first
    owner.advance('2026-01-05')
    assert post(base, command) == first
    state = get(base, '/api/storms')
    assert state['through'] == '2026-01-05'
    assert state['revision'] == 1
    assert state['history']
    assert state == storms.inspect(owner)


@pytest.mark.parametrize('headers,code', [({'Origin': 'https://external.invalid'}, 403),
                                         ({'Host': 'external.invalid'}, 403),
                                         ({'Content-Type': 'text/plain'}, 415)])
def test_untrusted_browser_cannot_schedule(desktop, headers, code):
    owner, base = desktop
    before = storms.inspect(owner)
    with pytest.raises(HTTPError) as error:
        post(base, payload(owner), **headers)
    assert error.value.code == code
    assert storms.inspect(owner) == before


@pytest.mark.parametrize('query', ['?other=1', '?before=2026-01-02&before=2026-01-03',
                                  '?eventsBefore=invalid', '?before=invalid'])
def test_invalid_history_queries_fail_without_mutation(desktop, query):
    owner, base = desktop
    before = storms.inspect(owner)
    with pytest.raises(HTTPError) as error:
        get(base, '/api/storms'+query)
    assert error.value.code == 422
    assert storms.inspect(owner) == before


def test_storm_edits_wait_for_local_cruise_owner(desktop):
    owner, base = desktop
    command = payload(owner)
    cruise.command(owner, cruise_command(owner))
    before = storms.inspect(owner)
    with pytest.raises(HTTPError) as error:
        post(base, command)
    assert error.value.code == 422
    assert storms.inspect(owner) == before
    cruise.command(owner, cruise_command(owner, 'cancel'))
    assert post(base, command)['status'] == 'completed'
