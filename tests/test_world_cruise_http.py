"""HTTP/supervisor boundaries; backend state-machine tests live separately."""
import json
import threading
import time
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_world_field_execution import setup as field_setup
from test_world_v2 import snapshot, world

from utilsim.world import World, cruise, delivery
from utilsim.world.server import make_server


@contextmanager
def serving(w, field_db=None, worker=True):
    server = make_server(w, 0, field_db=field_db, cruise_worker=worker)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
        assert not thread.is_alive()
        if server.cruise_thread:
            assert not server.cruise_thread.is_alive()


def http(base, path='/api/cruise', body=None, headers=None):
    request = Request(base+path, data=json.dumps(body).encode() if body is not None else None,
                      headers={**({'Content-Type': 'application/json'} if body is not None else {}), **(headers or {})})
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw.decode()
    except HTTPError as error:
        return error.code, json.load(error)


def command(w, identity='start-http', action='start', **changes):
    state = cruise.inspect(w)
    extra = {'targetDate': '2026-01-03'} if action == 'start' else {}
    return {'schemaVersion': 'world-cruise/1', 'commandId': identity,
            'environmentId': state['environmentId'], 'worldFingerprint': state['worldFingerprint'],
            'actorId': 'world-admin', 'expectedRevision': state['revision'], 'effectiveDate': state['through'],
            'action': action, 'reason': 'HTTP acceptance fixture', 'causalReference': 'test-http', **extra, **changes}


def await_state(base, predicate):
    deadline = time.monotonic()+10
    while time.monotonic() < deadline:
        code, value = http(base)
        assert code == 200
        if predicate(value):
            return value
        time.sleep(.02)
    raise AssertionError('HTTP cruise state did not reach the expected condition.')


def test_idle_read_pages_and_http_security_do_not_start_run(tmp_path):
    w = world(tmp_path)
    with serving(w, worker=False) as (_, base):
        code, state = http(base)
        assert code == 200 and state['status'] == 'idle'
        assert state['fieldConfigured'] is False and state['workerEnabled'] is False
        assert http(base, '/cruise')[0] == http(base, '/cruise.js')[0] == 200
        assert http(base, '/api/cruise?unexpected=1')[0] == 422
        assert http(base, headers={'Host': 'attacker.invalid'})[0] == 403
        payload = command(w)
        assert http(base, body=payload, headers={'Origin': 'https://attacker.invalid'})[0] == 403
        assert http(base, body=payload, headers={'Content-Type': 'text/plain'})[0] == 415
        assert http(base, body=[])[0] == 422
        assert http(base, body={**payload, 'environmentId': 'ANOTHER'})[0] == 422
        assert http(base, body=payload)[0] == 503
        assert http(base)[1]['through'] == '2026-01-01'
        assert http(base)[1]['status'] == 'idle'


def test_supervised_world_only_run_reaches_target_and_retries_once(tmp_path):
    w = world(tmp_path, annual_meter_failure=0, annual_meter_drift=0)
    payload = command(w)
    with serving(w) as (_, base):
        code, result = http(base, body=payload)
        assert code == 200
        complete = await_state(base, lambda value: value['status'] == 'completed')
        assert complete['through'] == '2026-01-03'
        assert complete['fieldConfigured'] is False
        assert complete['progress']['completedDays'] == 2
        assert http(base, body=payload) == (200, result)
        assert http(base, body={**payload, 'targetDate': '2026-01-04'})[0] == 422
        with w.db() as db:
            assert db.execute('SELECT COUNT(*) FROM days').fetchone()[0] == 2
        assert http(base)[1]['through'] == '2026-01-03'


def test_managed_cruise_blocks_manual_world_and_field_steps_until_cancel(tmp_path):
    w, field = field_setup(tmp_path)
    cruise.command(w, command(w), field)
    with serving(w, field.path, worker=False) as (_, base):
        assert http(base)[1]['fieldConfigured'] is True
        manual = {'environmentId': 'TEST', 'through': '2026-01-02'}
        assert http(base, '/api/advance', manual)[0] == 422
        identity = {'environmentId': 'TEST', 'worldFingerprint': cruise.inspect(w, field)['worldFingerprint'],
                    'effectiveDate': '2026-01-01'}
        assert http(base, '/api/field-execution/run-due', identity)[0] == 422
        assert http(base, body=command(w, 'pause-http', 'pause'))[0] == 200
        assert http(base)[1]['status'] == 'paused'
        assert http(base, '/api/advance', manual)[0] == 422
        assert http(base, body=command(w, 'resume-http', 'resume'))[0] == 503
        assert http(base, body=command(w, 'cancel-http', 'cancel'))[0] == 200
        assert http(base, '/api/advance', manual)[0] == 200


def test_shared_delivery_world_cannot_start_local_cruise(tmp_path):
    w = world(tmp_path)
    delivery.configure(w, 'TEST')
    with serving(w) as (_, base):
        state = http(base)[1]
        assert state['available'] is False and state['unavailableReason']
        assert http(base, body=command(w))[0] == 422
        assert http(base)[1]['through'] == '2026-01-01'


def test_worker_failure_visible_and_stop_controls_remain_available(tmp_path, monkeypatch):
    w = world(tmp_path)
    cruise.command(w, command(w))
    def failed_worker(*args, **kwargs):
        raise RuntimeError('Synthetic worker startup failure')
    monkeypatch.setattr(cruise, 'tick', failed_worker)
    with serving(w) as (_, base):
        state = await_state(base, lambda value: value['workerError'] is not None)
        assert state['workerError'] == 'RuntimeError'
        assert http(base, body=command(w, 'pause-http', 'pause'))[0] == 200
        assert http(base, body=command(w, 'resume-http', 'resume'))[0] == 503
        assert http(base, body=command(w, 'cancel-http', 'cancel'))[0] == 200
        assert http(base)[1]['through'] == '2026-01-01'


def test_server_worker_survives_uninitialized_world_then_initialization(tmp_path):
    w = World(tmp_path/'empty.sqlite')
    with serving(w) as (_, base):
        state = http(base)[1]
        assert state['available'] is False and state['workerError'] is None
        assert http(base, '/api/init', {'snapshot': snapshot(), 'environmentId': 'TEST',
                                       'start': '2026-01-01'})[0] == 200
        assert http(base)[1]['workerError'] is None
        assert http(base, body=command(w))[0] == 200
        complete = await_state(base, lambda value: value['status'] == 'completed')
        assert complete['through'] == '2026-01-03' and complete['workerError'] is None
