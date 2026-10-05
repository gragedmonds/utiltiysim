import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from utilsim.cancellation import SimulationStopped, cancellable, check_cancelled
from utilsim.worker.jobs import LocalJobs
from utilsim.worker.server import create_app
from utilsim.worker.workspace import UtilityWorkspace


def test_stop_interrupts_the_actual_batch_child_and_retry_is_available(tmp_path, monkeypatch):
    from utilsim import batch
    def request():
        return {'modelId': 'stop-test', 'chunkSize': 40, 'proposal': {'execution': 'local', 'totalHomes': 80,
                'preset': 'village', 'name': 'Stop test', 'summary': 'Cancellation', 'asOf': '2026-03-31'}}

    started, terminated = threading.Event(), threading.Event()
    class Child:
        returncode = None
        def __init__(self, command):
            started.set()
        def poll(self):
            return self.returncode
        def terminate(self):
            self.returncode = -1
            terminated.set()
        def wait(self, timeout=None):
            return self.returncode
    monkeypatch.setattr(batch.subprocess, 'Popen', Child)
    jobs = LocalJobs(tmp_path)
    with TestClient(create_app(jobs, 'token'), base_url='http://127.0.0.1') as client:
        auth = {'Authorization': 'Bearer token'}
        job = client.post('/local/jobs', headers=auth, json=request()).json()
        assert started.wait(5)
        url = '/local/jobs/' + job['jobId'] + '/stop'
        assert client.post(url).status_code == 401
        assert client.post(url, headers=auth).status_code == 200
        jobs.thread.join(5)
        assert not jobs.thread.is_alive() and terminated.is_set()
        assert jobs.find(job['jobId'])['status'] == 'cancelled'
        assert jobs.find(job['jobId'])['result'] is None
        assert client.get('/local/results/' + job['jobId'], headers=auth).status_code == 404
        assert LocalJobs(tmp_path).find(job['jobId'])['status'] == 'cancelled'
        jobs.set_paused(True)
        assert client.post('/local/jobs/' + job['jobId'] + '/retry', headers=auth).status_code == 200
        assert jobs.find(job['jobId'])['status'] == 'queued'
        assert client.post(url, headers=auth).status_code == 200
        assert jobs.find(job['jobId'])['status'] == 'cancelled'


def test_analysis_stop_cancels_active_and_waiting_requests_but_not_a_later_analysis(tmp_path, monkeypatch):
    jobs = LocalJobs(tmp_path)
    ws = UtilityWorkspace(jobs)
    started = threading.Event()
    def run_query(job_id, path, params):
        started.set()
        while True:
            check_cancelled()
            time.sleep(.005)
    monkeypatch.setattr(ws, '_query_request', run_query)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ws.query, 'one', '/m2c/kpis', {})
        assert started.wait(2)
        second = pool.submit(ws.query, 'one', '/m2c/trend', {})
        deadline = time.monotonic() + 2
        while len(ws.requests) < 2 and time.monotonic() < deadline:
            time.sleep(.005)
        assert len(ws.requests) == 2
        analysis_id = ws.active_request[0]
        assert not ws.stop('stale-id')
        assert ws.stop(analysis_id)
        for result in (first, second):
            with pytest.raises(SimulationStopped):
                result.result(2)
    assert not ws.requests and not ws.cache and ws.active_request is None
    monkeypatch.setattr(ws, '_query_request', lambda *args: {'ok': True})
    assert not ws.stop(analysis_id)
    assert ws.query('one', '/m2c/kpis', {}) == {'ok': True}


def test_cancellation_scope_resets_and_stopping_survives_restart(tmp_path):
    from utilsim.batch import write_json
    signal = threading.Event()
    with pytest.raises(SimulationStopped):
        with cancellable(signal):
            signal.set()
            check_cancelled()
    check_cancelled()  # other work is unaffected
    write_json(tmp_path / 'runner.json', {'jobs': [{'status': 'stopping'}, {'status': 'running'}]})
    assert [j['status'] for j in LocalJobs(tmp_path).state['jobs']] == ['cancelled', 'queued']


def test_cancelled_queries_and_exports_return_a_stopped_response(tmp_path, monkeypatch):
    def stopped(*args, **kwargs):
        raise SimulationStopped()
    monkeypatch.setattr(UtilityWorkspace, 'query', stopped)
    jobs = LocalJobs(tmp_path)
    with TestClient(create_app(jobs, 'token'), base_url='http://127.0.0.1') as client:
        auth = {'Authorization': 'Bearer token'}
        for suffix, body in [('query', {'path': '/m2c/kpis', 'params': {}}), ('link', {})]:
            response = client.post('/local/jobs/test/' + suffix, headers=auth, json=body)
            assert response.status_code == 409 and 'Simulation stopped' in response.json()['detail']


def test_daily_replay_stops_without_caching_an_incomplete_run(monkeypatch):
    from api import _m2c
    from utilsim.m2c.run import M2CRun
    signal = threading.Event()
    original = M2CRun._roll_orders
    visited = []
    def roll(run, day):
        visited.append(day)
        original(run, day)
        if day == 10:
            signal.set()
    request = _m2c.RunRequest(town='village', seed='invoice-stop-regression')
    monkeypatch.setattr(M2CRun, '_roll_orders', roll)
    with pytest.raises(SimulationStopped), cancellable(signal):
        _m2c.run_for(request)
    assert visited[-1] == 10
    monkeypatch.setattr(M2CRun, '_roll_orders', original)
    complete = _m2c.run_for(request)
    assert max(i['created'] for i in complete.books.invoices) > 300
