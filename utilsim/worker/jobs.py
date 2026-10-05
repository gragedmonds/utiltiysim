"""The app's job queue: revisions of a simulation run one at a time, on this computer, with everything saved under
the storage folder. Nothing syncs anywhere: the Studio pages served by the same process read this queue directly."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import orjson

from utilsim.cancellation import SimulationStopped, cancellable
from utilsim.worker.estimates import initial_estimate, progress_estimate
from utilsim.worker.execute import execute

STATUS_SCHEMA = 'local-status/2.0'
MAX_JOBS = 200


class LocalJobs:
    def __init__(self, store: Path):
        self.store = Path(store).resolve()
        self.state_path = self.store / 'runner.json'
        self.lock = threading.RLock()
        self.state = {'paused': False, 'jobs': []}
        if self.state_path.exists():
            saved = orjson.loads(self.state_path.read_bytes())
            self.state.update({k: saved[k] for k in ('paused', 'jobs') if k in saved})
        for job in self.state['jobs']:
            if job['status'] == 'stopping':
                job['status'] = 'cancelled'
            if job['status'] == 'running':  # the process stopped mid-run; its districts are checkpointed
                job['status'] = 'queued'
        self.thread = None
        self.shutdown = threading.Event()
        self.progress = {}
        self.error = None
        self.stop_signals = {}

    # ---- persistence -----------------------------------------------------------------------------------------
    def save(self):
        from utilsim.batch import write_json
        with self.lock:
            if not self.store.is_dir():
                raise OSError('Storage drive unavailable.')
            write_json(self.state_path, self.state)

    def find(self, job_id):
        return next((j for j in self.state['jobs'] if j['jobId'] == job_id), None)

    # ---- the queue -------------------------------------------------------------------------------------------
    def revisions(self, model_id):
        return sorted((j for j in self.state['jobs'] if j['recipe']['modelId'] == model_id), key=lambda j: j['revision'])

    def queue(self, value):
        """Prepare and queue the next revision of a simulation from ``{proposal, modelId, chunkSize?}``."""
        from utilsim.worker.prepare import prepare_job
        with self.lock:
            if len(self.state['jobs']) >= MAX_JOBS:
                raise ValueError(f'This library holds {MAX_JOBS} revisions. Remove some before queueing more.')
            rows = self.revisions(value['modelId'])
            job = prepare_job(value, (rows[-1]['revision'] if rows else 0) + 1)
            entry = {**job, 'status': 'queued', 'progress': {}, 'result': None, 'error': None, 'createdAt': time.time()}
            self.state['jobs'].append(entry)
            self.save()
        self.start()
        return self.public(entry)

    def retry(self, job_id):
        with self.lock:
            job = self.find(job_id)
            if not job:
                raise KeyError(job_id)
            if job['status'] in ('failed', 'cancelled'):
                job.update(status='queued', error=None)
                self.save()
        self.start()

    def remove(self, job_id):
        with self.lock:
            job = self.find(job_id)
            if not job:
                raise KeyError(job_id)
            if job['status'] in ('running', 'stopping'):
                raise ValueError('Stop this revision and wait for it to stop before removing it.')
            self.state['jobs'].remove(job)
            self.save()

    def set_paused(self, paused):
        with self.lock:
            self.state['paused'] = bool(paused)
            self.save()
        self.start()

    def stop(self, job_id):
        with self.lock:
            job = self.find(job_id)
            if not job:
                raise KeyError(job_id)
            if job['status'] == 'queued':
                job.update(status='cancelled', error=None)
            elif job['status'] in ('running', 'stopping'):
                job['status'] = 'stopping'
                self.stop_signals[job_id].set()
            self.save()

    # ---- running ---------------------------------------------------------------------------------------------
    def next_job(self):
        return next((j for j in self.state['jobs'] if j['status'] == 'queued'), None)

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive() or self.state['paused'] or not self.next_job():
                return
            self.thread = threading.Thread(target=self.work, daemon=True)
            self.thread.start()

    def work(self):
        while not self.shutdown.is_set():
            with self.lock:
                job = None if self.state['paused'] else self.next_job()
                if not job:
                    return
                job['status'] = 'running'
                signal = self.stop_signals[job['jobId']] = threading.Event()
                self.progress, self.error = {}, None
                self.save()
            try:
                with cancellable(signal):
                    result = execute({k: job[k] for k in ('schemaVersion', 'jobId', 'revision', 'recipeKey', 'recipe')},
                                     self.store, lambda p, j=job: self.on_progress(j, p),
                                     lambda: self.state['paused'] or self.shutdown.is_set())
                with self.lock:
                    if signal.is_set():
                        job.update(status='cancelled', result=None, error=None)
                    elif result:
                        job.update(status='complete', result=result, progress=self.progress, error=None)
                    else:
                        job['status'] = 'queued'  # paused or shutting down: its finished districts are kept
                    self.save()
            except SimulationStopped:
                with self.lock:
                    job.update(status='cancelled', result=None, error=None)
                    self.save()
            except Exception as exc:
                with self.lock:
                    job.update(status='failed', error=str(exc)[:500])
                    try:
                        self.save()
                    except OSError:
                        pass
            finally:
                with self.lock:
                    self.stop_signals.pop(job['jobId'], None)

    def on_progress(self, job, progress):
        self.progress = progress_estimate(progress, initial_estimate(job['recipe'], self.state['jobs']))
        job['progress'] = self.progress

    # ---- what the Studio sees ---------------------------------------------------------------------------------
    def public(self, job):
        return job

    def snapshot(self):
        with self.lock:
            active = next((j for j in self.state['jobs'] if j['status'] in ('running', 'stopping')), None)
            return {'schemaVersion': STATUS_SCHEMA, 'storage': str(self.store), 'paused': bool(self.state['paused']),
                    'storageAvailable': self.store.is_dir(),
                    'active': {'jobId': active['jobId'], 'modelId': active['recipe']['modelId'], 'name': active['recipe']['name'],
                               'revision': active['revision'], 'stopping': active['status'] == 'stopping', 'progress': active.get('progress') or
                               progress_estimate({}, initial_estimate(active['recipe'], self.state['jobs']))} if active else None,
                    'queued': sum(j['status'] == 'queued' for j in self.state['jobs']),
                    'jobs': [{k: j[k] for k in ('jobId', 'revision', 'status', 'createdAt')} | {'modelId': j['recipe']['modelId'], 'name': j['recipe']['name']}
                             for j in self.state['jobs']]}
