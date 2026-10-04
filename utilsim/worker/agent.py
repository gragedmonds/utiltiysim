"""Outbound-only worker. A persisted inbox/outbox survives restarts and offline processing."""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import orjson

from utilsim.worker import vault
from utilsim.worker.contracts import check_job
from utilsim.worker.execute import execute


def portal_url(value):
    url = urlparse(value)
    if url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
        raise ValueError('Use the Studio origin, without a path or workspace key.')
    if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost')):
        raise ValueError('Studio must use HTTPS (localhost is allowed for development).')
    return value.rstrip('/')


class Agent:
    def __init__(self, store: Path):
        self.store = Path(store).resolve()
        self.state_path = self.store / 'runner.json'
        self.lock = threading.RLock()
        self.state = orjson.loads(self.state_path.read_bytes()) if self.state_path.exists() else {'paused': False}
        self.token = vault.read(self.store / '.device-credential')
        self.thread = None
        self.shutdown = threading.Event()
        self.status = 'Ready' if self.token else 'Not paired'
        self.progress = {}
        self.result = None
        self.error = None
        self.last_sync = 0

    def save(self):
        from utilsim.batch import write_json
        with self.lock:
            if not self.store.is_dir():
                raise OSError('Storage drive unavailable.')
            write_json(self.state_path, self.state)

    def request(self, path, data, *, authenticated=True):
        headers = {'Authorization': 'Bearer ' + self.token} if authenticated and self.token else {}
        with httpx.Client(timeout=15) as client:
            response = client.post(self.state['portal'] + '/api/portal/' + path, json=data, headers=headers)
        response.raise_for_status()
        self.last_sync = time.time()
        return response.json()

    def pair(self, portal, code):
        if self.thread and self.thread.is_alive() or self.state.get('active'):
            raise ValueError('Finish or sync the current job before switching workspaces.')
        previous = self.state.get('portal')
        self.state['portal'] = portal_url(portal)
        try:
            data = self.request('redeem', {'code': code, 'name': socket.gethostname()}, authenticated=False)
        except Exception:
            self.state['portal'] = previous
            raise
        vault.save(self.store / '.device-credential', data['token'])
        self.token = data['token']
        self.state['deviceId'] = data['id']
        self.save()
        self.status = 'Ready'

    def import_job(self, value):
        job = check_job(value)
        with self.lock:
            if self.state.get('active'):
                raise ValueError('A job is already active. Finish it before importing another.')
            self.state['active'] = job
            self.state['manual'] = True
            self.save()
        self.start_job()

    def start_job(self):
        with self.lock:
            if self.thread and self.thread.is_alive() or not self.state.get('active') or self.state.get('paused'):
                return
            self.result = self.error = None
            self.status = 'Processing'
            def work():
                try:
                    job = {k: self.state['active'][k] for k in ('schemaVersion', 'jobId', 'revision', 'recipeKey', 'recipe')}
                    result_path = self.store / 'results' / (job['jobId'] + '.result.json')
                    if result_path.exists():
                        self.result = orjson.loads(result_path.read_bytes())
                    else:
                        self.result = execute(job, self.store, lambda p: setattr(self, 'progress', p),
                                              lambda: self.state.get('paused') or self.shutdown.is_set())
                    self.status = 'Results saved' if self.result else 'Paused'
                except Exception as exc:
                    self.error = str(exc)[:500]
                    self.status = 'Needs attention'
            self.thread = threading.Thread(target=work, daemon=True)
            self.thread.start()

    def tick(self):
        if not self.store.is_dir():
            self.status = 'Storage drive unavailable'
            return
        active = self.state.get('active')
        if active:
            if not self.thread:
                self.start_job()
            running = self.thread and self.thread.is_alive()
            if not self.state.get('manual') and self.token:
                data = {'lease': active['lease'], 'progress': self.progress}
                if self.result:
                    data['result'] = self.result
                elif self.error:
                    data['error'] = self.error
                self.request('jobs/' + active['jobId'] + '/report', data)
            if not running and (self.result or self.error):
                with self.lock:
                    self.state['lastJob'] = active['jobId']
                    self.state.pop('active', None)
                    self.state.pop('manual', None)
                    self.save()
                    self.thread = None
                return
            if not running and not self.state.get('paused') and not self.error:
                self.start_job()
            return
        if self.token and not self.state.get('paused'):
            reply = self.request('claim', {'readiness': 'Ready'})
            if reply['job']:
                with self.lock:
                    self.state['active'] = reply['job']
                    self.state['manual'] = False
                    self.save()
                self.start_job()

    def loop(self):
        while not self.shutdown.is_set():
            try:
                if self.state.get('active') and not self.thread:
                    self.start_job()
                if self.token and not self.state.get('manual'):
                    from utilsim.worker.details import page
                    for item in self.request('device/details', {})['requests']:
                        payload = {'id': item['id']}
                        try:
                            payload['result'] = page(self.store, item['query'])
                        except (ValueError, OSError) as exc:
                            payload['error'] = str(exc)[:500]
                        self.request('device/details', payload)
                self.tick()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 401:
                    self.status = 'Computer disconnected; saved work is kept'
                elif exc.response.status_code == 409 and self.state.get('active'):
                    self.state['manual'] = True
                    self.save()
                    self.status = 'Job reassigned; results will be kept locally'
                else:
                    self.status = 'Sync unavailable; computation continues locally'
            except (httpx.HTTPError, OSError, ValueError):
                self.status = 'Offline; computation and saved results stay local'
            self.shutdown.wait(5)

    def snapshot(self):
        active = self.state.get('active')
        return {'schemaVersion': 'local-status/1.0', 'paired': bool(self.token), 'status': self.status,
                'storage': str(self.store), 'paused': bool(self.state.get('paused')), 'lastSync': self.last_sync,
                'active': {'name': active['recipe']['name'], 'revision': active['revision']} if active else None,
                'progress': self.progress, 'error': self.error,
                'results': [p.name for p in sorted((self.store / 'results').glob('*.result.json'))]}
