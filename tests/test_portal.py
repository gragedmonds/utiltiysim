"""Durable pairing, immutable revisions, stale lease fencing and manual-file equivalence."""
from __future__ import annotations

import concurrent.futures
import copy
import time
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api._portal import Portal, prepare_recipe
from api._portal_store import Documents
from api.index import app
from utilsim.worker.contracts import JobFile, check_job, recipe_key


def job_file(homes=80):
    recipe = prepare_recipe({'proposal': {'execution': 'local', 'totalHomes': homes, 'name': 'Local test',
                             'summary': 'Test offline delivery', 'preset': 'village',
                             'townOverrides': {'town': {'houses': 40}}, 'asOf': '2026-03-31'},
                             'modelId': 'test-model', 'chunkSize': 40, 'staffing': 'independent-districts'})
    return JobFile(jobId=uuid.uuid4().hex, revision=1, recipeKey=recipe_key(recipe), recipe=recipe).model_dump()


@pytest.fixture
def portal(tmp_path):
    return Portal(Documents(path=str(tmp_path / 'portal.db')))


def pair(portal, token):
    return portal.redeem(portal.pairing(token)['code'], 'Test computer')['token']


def test_pair_consumption_is_atomic_and_credentials_never_listed(portal):
    token = portal.create()['token']
    code = portal.pairing(token)['code']
    def redeem(_):
        try:
            return portal.redeem(code, 'Runner')
        except HTTPException as exc:
            return exc.status_code
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(redeem, range(4)))
    assert sum(isinstance(v, dict) for v in values) == 1
    assert values.count(410) == 3
    state = portal.read(token)
    assert 'keyHash' not in str(state) and token not in str(state)
    other = portal.create()['token']
    with pytest.raises(HTTPException):
        portal.read(token.split('.')[0] + '.' + other.split('.')[1])


def test_restart_reconnect_revision_and_stale_lease(portal):
    owner = portal.create()['token']
    first, second = pair(portal, owner), pair(portal, owner)
    file = job_file()
    portal.queue(owner, file)
    old = portal.claim(first)['job']
    assert portal.claim(second)['job'] is None
    def expire(state, _):
        state['jobs'][file['jobId']]['leaseUntil'] = time.time() - 1
    portal.change(owner, expire)
    new = portal.claim(second)['job']
    assert old['lease'] != new['lease']
    with pytest.raises(HTTPException) as exc:
        portal.report(first, file['jobId'], old['lease'], {'completed': 99})
    assert exc.value.status_code == 409
    portal.report(second, file['jobId'], new['lease'], {'completed': 1})
    restarted = Portal(Documents(path=portal.store.path))
    assert restarted.claim(second)['job']['lease'] == new['lease']
    assert restarted.read(owner)['jobs'][0]['progress']['completed'] == 1
    changed = copy.deepcopy(file)
    changed.update(jobId=uuid.uuid4().hex, revision=2)
    changed['recipe']['request']['settings'] = {'process': {'analysts': 2}}
    changed['recipeKey'] = recipe_key(changed['recipe'])
    portal.queue(owner, changed)
    assert portal.read(owner)['jobs'][0]['recipe']['request']['settings'] == {}


def test_500k_recipe_is_local_only_and_tampering_is_rejected():
    job = job_file(500000)
    assert check_job(job)['recipe']['homes'] == 500000
    job['recipe']['homes'] = 499999
    with pytest.raises(ValueError, match='checksum'):
        check_job(job)


def test_api_without_database_exposes_manual_flow(monkeypatch):
    monkeypatch.setenv('VERCEL', '1')
    for name in ['UTILSIM_PORTAL_DB', 'UPSTASH_REDIS_REST_URL', 'UPSTASH_REDIS_REST_TOKEN', 'KV_REST_API_URL', 'KV_REST_API_TOKEN']:
        monkeypatch.delenv(name, raising=False)
    with TestClient(app) as client:
        assert client.get('/api/portal/status').json()['available'] is False
        assert client.post('/api/portal/workspaces').status_code == 503
        assert client.post('/api/portal/check-file', json=job_file()).status_code == 200
        assert client.post('/api/portal/check-file', json={'bad': 'payload'}).status_code == 422


def test_offline_execution_result_import_and_baseline_reuse(tmp_path, portal):
    import orjson

    from utilsim.worker.execute import execute

    store = tmp_path / 'library'
    store.mkdir()
    owner = portal.create()['token']
    file = job_file()
    portal.queue(owner, file)
    result = execute(file, store)
    portal.import_result(owner, result)
    assert portal.read(owner)['jobs'][0]['status'] == 'complete'
    cache = {str(p): p.stat().st_mtime_ns for p in (store / 'baselines').glob('*/snapshot.json.gz')}
    assert len(cache) == 2
    edited = copy.deepcopy(file)
    edited.update(jobId=uuid.uuid4().hex, revision=2)
    edited['recipe']['request']['settings'] = {'process': {'analysts': 0}}
    edited['recipeKey'] = recipe_key(edited['recipe'])
    portal.queue(owner, edited)
    again = execute(edited, store)
    assert cache == {str(p): p.stat().st_mtime_ns for p in (store / 'baselines').glob('*/snapshot.json.gz')}
    assert 'baseline.verify_reuse' in again['timings']['stagesSeconds']
    assert 'generation.roads' not in again['timings']['stagesSeconds']
    with pytest.raises(HTTPException):
        portal.import_result(owner, {**result, 'jobId': edited['jobId']})
    assert orjson.loads((store / 'results' / (edited['jobId'] + '.result.json')).read_bytes()) == again


def test_browser_json_numbers_do_not_change_recipe_identity():
    import json
    import subprocess
    file = job_file()
    roundtrip = subprocess.check_output(['node', '-e', 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>console.log(JSON.stringify(JSON.parse(s))))'],
                                       input=json.dumps(file), text=True)
    assert check_job(json.loads(roundtrip))['recipeKey'] == file['recipeKey']


def test_worker_keeps_receipt_offline_and_syncs_after_restart(tmp_path, portal, monkeypatch):
    import httpx

    from utilsim.worker import vault
    from utilsim.worker.agent import Agent

    root = tmp_path / 'computer'
    root.mkdir()
    owner = portal.create()['token']
    device = pair(portal, owner)
    file = job_file(40)
    portal.queue(owner, file)
    claimed = portal.claim(device)['job']
    vault.save(root / '.device-credential', device)
    worker = Agent(root)
    worker.state.update(portal='https://example.test', active=claimed, manual=False)
    worker.save()
    worker.start_job()
    worker.thread.join(timeout=60)
    assert worker.result and not worker.error
    def offline(*args, **kwargs):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(worker, 'request', offline)
    with pytest.raises(httpx.ConnectError):
        worker.tick()
    assert worker.state.get('active')
    restarted = Agent(root)
    def online(path, data, **kwargs):
        return portal.report(device, file['jobId'], data['lease'], data.get('progress'), data.get('result'), data.get('error'))
    monkeypatch.setattr(restarted, 'request', online)
    restarted.start_job()
    restarted.thread.join(timeout=10)
    restarted.tick()
    assert not restarted.state.get('active')
    assert portal.read(owner)['jobs'][0]['status'] == 'complete'


def test_revoke_fences_an_active_worker_and_drive_loss_does_not_fall_back(tmp_path, portal):
    from utilsim.worker.agent import Agent
    owner = portal.create()['token']
    device = pair(portal, owner)
    portal.queue(owner, job_file())
    job = portal.claim(device)['job']
    portal.revoke(owner, job['deviceId'])
    with pytest.raises(HTTPException) as exc:
        portal.report(device, job['jobId'], job['lease'], {})
    assert exc.value.status_code == 401
    missing = tmp_path / 'unplugged'
    worker = Agent(missing)
    worker.tick()
    assert worker.status == 'Storage drive unavailable'
    assert not missing.exists()
