"""Local desktop transport/security for recurring customer cashflow."""
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_world_cruise import command as cruise_command
from test_world_customer_finance import command as finance_command
from test_world_network_faults import world

from utilsim.world import cruise, customer_cashflow, customer_finance, delivery
from utilsim.world.server import make_server


@pytest.fixture
def desktop(tmp_path):
    owner = world(tmp_path)
    customer_finance.command(owner, finance_command(owner))
    server = make_server(owner, 0, cruise_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield owner, f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def payload(owner, identity='http-cashflow'):
    state = customer_cashflow.inspect(owner, 'P1')
    return {'schemaVersion': customer_cashflow.VERSION, 'commandId': identity,
            'environmentId': state['environmentId'], 'runId': state['runId'],
            'worldFingerprint': state['worldFingerprint'], 'actorId': 'world-admin',
            'expectedRevision': state['revision'], 'effectiveDate': state['through'], 'action': 'configure',
            'premiseId': 'P1', 'recipientRef': state['recipientRef'], 'active': True,
            'income': {'amountCents': 10001, 'firstDate': state['through'], 'intervalDays': 14},
            'essentialExpense': {'amountCents': 3001, 'firstDate': state['through'], 'intervalDays': 1},
            'insufficientCashPolicy': 'available-cash', 'incomeOverflowPolicy': 'skip-with-record',
            'reason': 'Explicit HTTP cashflow scenario', 'causalReference': 'http-acceptance'}


def get(base, path='/api/customer-cashflow?premise=P1'):
    with urlopen(base+path) as response:
        return json.load(response)


def post(base, value, **headers):
    request = Request(base+'/api/customer-cashflow', json.dumps(value).encode(),
                      {'Content-Type': 'application/json', **headers})
    with urlopen(request) as response:
        return json.load(response)


def test_configure_exact_retry_and_bounded_occurrence_history(desktop):
    owner, base = desktop
    assert get(base)['configured'] is False
    with urlopen(base+'/customer-finance') as response:
        assert b'href="/customer-cashflow"' in response.read()
    for path, fragment in (('/customer-cashflow', b'<html'), ('/customer-cashflow.js', b'/api/customer-cashflow')):
        with urlopen(base+path) as response:
            assert fragment in response.read()
            assert response.headers['X-Content-Type-Options'] == 'nosniff'
    command = payload(owner)
    accepted = post(base, command)
    assert post(base, command) == accepted
    owner.advance('2026-02-01')
    assert post(base, command) == accepted
    state = get(base)
    assert state['revision'] == 1 and len(state['history']) == 25
    older = get(base, '/api/customer-cashflow?premise=P1&before='+state['nextBefore'])
    assert len(older['history']) == 6
    assert state == customer_cashflow.inspect(owner, 'P1')
    assert all(r['closingCashCents'] >= r['reservedCashCents'] for r in state['history'])


@pytest.mark.parametrize('headers,code', [({'Origin': 'https://external.invalid'}, 403),
                                        ({'Host': 'external.invalid'}, 403),
                                        ({'Content-Type': 'text/plain'}, 415)])
def test_external_browser_cannot_change_cashflow(desktop, headers, code):
    owner, base = desktop
    before = customer_cashflow.inspect(owner, 'P1')
    with pytest.raises(HTTPError) as error:
        post(base, payload(owner), **headers)
    assert error.value.code == code
    assert customer_cashflow.inspect(owner, 'P1') == before


@pytest.mark.parametrize('query', ['', '?premise=', '?premise=P1&unknown=x', '?premise=P1&premise=P1',
                                  '?premise=P1&before=invalid', '?premise=P1&before=2026-01-02&before=2026-01-03'])
def test_invalid_history_queries_do_not_mutate_world(desktop, query):
    owner, base = desktop
    before = customer_cashflow.inspect(owner, 'P1')
    with pytest.raises(HTTPError) as error:
        get(base, '/api/customer-cashflow'+query)
    assert error.value.code == 422
    assert customer_cashflow.inspect(owner, 'P1') == before


def test_local_cruise_owner_blocks_cashflow_edit_until_cancel(desktop):
    owner, base = desktop
    command = payload(owner)
    cruise.command(owner, cruise_command(owner))
    with pytest.raises(HTTPError) as error:
        post(base, command)
    assert error.value.code == 422 and not get(base)['configured']
    cruise.command(owner, cruise_command(owner, 'cancel'))
    assert post(base, command)['status'] == 'completed'


def test_managed_clock_world_allows_atomic_admin_configuration_without_advancing(desktop):
    owner, base = desktop
    command = payload(owner)
    delivery.configure(owner, 'TEST')
    assert post(base, command)['status'] == 'completed'
    assert get(base)['through'] == command['effectiveDate']
    assert get(base)['cashCents'] == 10000 and get(base)['history'] == []
    with pytest.raises(HTTPError) as error:
        with urlopen(Request(base+'/api/advance', json.dumps({'environmentId': 'TEST', 'through': '2026-01-02'}).encode(),
                             {'Content-Type': 'application/json'})):
            pass
    assert error.value.code == 422
    assert 'shared delivery' in json.load(error.value)['error']
