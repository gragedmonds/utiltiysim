"""The app's job queue: a revision of a simulation becomes a checked job, runs district by district on this computer,
and its result summary and run bundles are served to the Studio pages the same process serves."""
from __future__ import annotations

import copy
import time

import pytest
from fastapi.testclient import TestClient

from utilsim.worker.contracts import check_job, recipe_key
from utilsim.worker.jobs import LocalJobs
from utilsim.worker.prepare import prepare_job, prepare_recipe
from utilsim.worker.server import create_app

PROPOSAL = {'execution': 'local', 'totalHomes': 80, 'name': 'Local test', 'summary': 'Test offline delivery',
            'preset': 'village', 'townOverrides': {'town': {'houses': 40}}, 'asOf': '2026-03-31'}


def request(homes=80, **extra):
    return {'proposal': {**PROPOSAL, 'totalHomes': homes, **extra}, 'modelId': 'test-model', 'chunkSize': 40}


def wait(jobs, job_id, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = jobs.find(job_id)
        if job['status'] in ('complete', 'failed'):
            return job
        time.sleep(.2)
    raise AssertionError(jobs.snapshot())


def test_500k_recipe_is_prepared_and_tampering_is_rejected():
    job = prepare_job(request(500000), 1)
    assert job['recipe']['homes'] == 500000 and job['revision'] == 1
    job['recipe']['homes'] = 499999
    with pytest.raises(ValueError, match='checksum'):
        check_job(job)
    recipe = prepare_recipe(request())
    assert recipe['proposal']['townRef'].startswith('village~') and recipe['request']['seed'] is None


def test_revisions_run_in_order_and_baselines_are_reused(tmp_path):
    store = tmp_path / 'library'
    store.mkdir()
    jobs = LocalJobs(store)
    with TestClient(create_app(jobs, 'token'), base_url='http://127.0.0.1') as client:
        auth = {'Authorization': 'Bearer token'}
        assert client.post('/local/jobs', json=request()).status_code == 401
        first = client.post('/local/jobs', headers=auth, json=request()).json()
        assert first['revision'] == 1 and first['status'] in ('queued', 'running')
        assert client.get('/local/jobs?model=test-model', headers=auth).json()['jobs'][0]['jobId'] == first['jobId']
        bad = {'proposal': {**PROPOSAL, 'townOverrides': {'town': {'houses': 10**7}}}, 'modelId': 'x'}
        assert client.post('/local/jobs', headers=auth, json=bad).status_code == 422
        done = wait(jobs, first['jobId'])
        assert done['status'] == 'complete', done['error']
        result = done['result']
        assert result['rollup']['complete'] and len(result['districts']) == 2
        # The result summary and every district's run bundle are served for the Studio and the saved-results reader.
        assert client.get('/local/results/' + first['jobId'], headers=auth).json()['jobId'] == first['jobId']
        for d in result['districts']:
            manifest = client.get('/runs/' + d['runKey'] + '/manifest.json')
            assert manifest.status_code == 200 and manifest.json()['runKey'] == d['runKey']
        assert len(client.get('/local/library', headers=auth).json()['runs']) == 2
        cache = {str(p): p.stat().st_mtime_ns for p in (store / 'baselines').glob('*/snapshot.json.gz')}
        assert len(cache) == 2
        # A changed year makes revision 2; it reuses the baselines instead of generating the towns again.
        second = client.post('/local/jobs', headers=auth, json=request(settings={'process': {'analysts': 0}})).json()
        assert second['revision'] == 2 and second['recipeKey'] != first['recipeKey']
        again = wait(jobs, second['jobId'])
        assert again['status'] == 'complete', again['error']
        assert cache == {str(p): p.stat().st_mtime_ns for p in (store / 'baselines').glob('*/snapshot.json.gz')}
        assert 'baseline.verify_reuse' in again['result']['timings']['stagesSeconds']
        assert 'generation.roads' not in again['result']['timings']['stagesSeconds']
        status = client.get('/local/status', headers=auth).json()
        assert status['active'] is None and [j['revision'] for j in status['jobs']] == [1, 2]
        # Pause holds the queue; a removed revision is gone.
        assert client.post('/local/pause', headers=auth, json={'paused': True}).json()['paused'] is True
        third = client.post('/local/jobs', headers=auth, json=request(asOf='2026-06-30')).json()
        time.sleep(.5)
        assert jobs.find(third['jobId'])['status'] == 'queued'
        assert client.delete('/local/jobs/' + third['jobId'], headers=auth).status_code == 200
        assert client.delete('/local/jobs/' + third['jobId'], headers=auth).status_code == 404
    # The queue is on disk: a new process sees the same revisions.
    assert [j['revision'] for j in LocalJobs(store).revisions('test-model')] == [1, 2]


def test_browser_json_numbers_do_not_change_recipe_identity():
    import json
    import subprocess
    file = prepare_job(request(), 1)
    roundtrip = subprocess.check_output(['node', '-e', 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>console.log(JSON.stringify(JSON.parse(s))))'],
                                       input=json.dumps(file), text=True)
    assert check_job(json.loads(roundtrip))['recipeKey'] == file['recipeKey']
    other = copy.deepcopy(file)
    other['recipe']['request']['settings'] = {'process': {'analysts': 2}}
    assert recipe_key(other['recipe']) != file['recipeKey']


def test_a_missing_drive_stops_the_queue_instead_of_writing_elsewhere(tmp_path):
    missing = tmp_path / 'unplugged'
    jobs = LocalJobs.__new__(LocalJobs)
    jobs.store = missing
    jobs.state = {'paused': False, 'jobs': []}
    import threading
    jobs.lock = threading.RLock()
    with pytest.raises(OSError):
        jobs.save()
    assert not missing.exists()
