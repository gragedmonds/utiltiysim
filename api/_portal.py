"""Workspace-scoped pairing and leased local jobs. No simulation runs in these routes."""
from __future__ import annotations

import copy
import hashlib
import secrets
import time
import uuid

import orjson
from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import ValidationError

from api._portal_store import StoreUnavailable, configured_store
from utilsim.worker.contracts import JobFile, ResultFile, check_job, recipe_key


class PortalRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request):
            try:
                return await handler(request)
            except StoreUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            except (ValueError, KeyError) as exc:
                raise HTTPException(422, str(exc)[:1000]) from exc
        return guarded


router = APIRouter(prefix='/api/portal', tags=['local runner'], route_class=PortalRoute)
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
LEASE_SECONDS = 120


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


def token_id(token):
    wid, _, secret = token.partition('.')
    if len(wid) != 32 or any(c not in 'abcdef0123456789' for c in wid) or len(secret) < 32:
        raise HTTPException(401, 'Open the workspace link or reconnect this computer.')
    return wid


def workspace_auth(state, token, device=False):
    if not state:
        raise HTTPException(401, 'Workspace is unavailable.')
    key = hashed(token)
    if not device:
        if not secrets.compare_digest(state['keyHash'], key):
            raise HTTPException(403, 'This link does not grant access to this workspace.')
        return None
    found = next((d for d in state['devices'].values() if d['keyHash'] == key and not d.get('revoked')), None)
    if not found:
        raise HTTPException(401, 'Computer disconnected. Pair again in Studio.')
    return found


def public_job(job):
    return {k: v for k, v in job.items() if k not in ('lease', 'leaseUntil')}


def public_workspace(state):
    now = time.time()
    return {'schemaVersion': 'local-workspace/1.0', 'id': state['id'],
            'devices': [{k: v for k, v in {**d, 'online': now - d.get('lastSeen', 0) < 60}.items()
                         if k != 'keyHash'} for d in state['devices'].values() if not d.get('revoked')],
            'jobs': [public_job(j) for j in state['jobs'].values()]}


class Portal:
    def __init__(self, store):
        self.store = store

    def create(self):
        wid = uuid.uuid4().hex
        token = wid + '.' + secrets.token_urlsafe(32)
        value = {'id': wid, 'keyHash': hashed(token), 'devices': {}, 'pairings': {}, 'jobs': {}}
        self.store.update('workspace:' + wid, lambda old: (value, None))
        return {'schemaVersion': 'local-workspace-link/1.0', 'token': token, 'id': wid}

    def read(self, token):
        state = self.store.get('workspace:' + token_id(token))
        workspace_auth(state, token)
        return public_workspace(state)

    def change(self, token, function, *, device=False):
        def apply(state):
            who = workspace_auth(state, token, device)
            return state, function(state, who)
        return self.store.update('workspace:' + token_id(token), apply)

    def pairing(self, token):
        code = ''.join(secrets.choice(ALPHABET) for _ in range(8))
        expires = time.time() + 600
        def add(state, _):
            state['pairings'] = {k: v for k, v in state['pairings'].items() if v > time.time()}
            if len(state['pairings']) >= 5:
                raise HTTPException(429, 'Use an existing code or wait for it to expire.')
            state['pairings'][hashed(code)] = expires
            return {'schemaVersion': 'local-pairing/1.0', 'code': code, 'expiresAt': expires}
        result = self.change(token, add)
        self.store.update('pair:' + hashed(code), lambda old: ({'workspace': token_id(token), 'expires': expires}, None))
        return result

    def redeem(self, code, name):
        code = code.upper().replace('-', '').replace(' ', '')
        if len(code) != 8 or any(c not in ALPHABET for c in code):
            raise HTTPException(422, 'Enter the eight-character code shown in Studio.')
        pair = self.store.get('pair:' + hashed(code))
        if not pair or pair['expires'] <= time.time():
            raise HTTPException(410, 'Code expired or already used. Generate another in Studio.')
        token = pair['workspace'] + '.' + secrets.token_urlsafe(32)
        device_id = uuid.uuid4().hex
        def consume(state):
            if not state or state['pairings'].pop(hashed(code), 0) <= time.time():
                raise HTTPException(410, 'Code expired or already used. Generate another in Studio.')
            state['devices'][device_id] = {'id': device_id, 'name': name[:100], 'keyHash': hashed(token), 'lastSeen': time.time()}
            return state, {'schemaVersion': 'local-device/1.0', 'token': token, 'id': device_id}
        return self.store.update('workspace:' + pair['workspace'], consume)

    def revoke(self, token, device_id):
        def remove(state, _):
            d = state['devices'].get(device_id)
            if not d:
                raise HTTPException(404, 'Computer not found.')
            d['revoked'] = True
            for job in state['jobs'].values():
                if job.get('deviceId') == device_id and job['status'] in ('running', 'queued'):
                    job.update(status='queued', leaseUntil=0, lease=None, deviceId=None)
            return {'ok': True}
        return self.change(token, remove)

    def queue(self, token, job_file):
        job_file = check_job(job_file)
        def add(state, _):
            if job_file['jobId'] in state['jobs']:
                old = state['jobs'][job_file['jobId']]
                if old['recipeKey'] != job_file['recipeKey']:
                    raise HTTPException(409, 'Job id already belongs to different inputs.')
                return public_job(old)
            same = [j for j in state['jobs'].values() if j['recipe']['modelId'] == job_file['recipe']['modelId']]
            if len(state['jobs']) >= 100:
                raise HTTPException(422, 'This workspace has 100 saved revisions. Start another workspace.')
            revision = max((j['revision'] for j in same), default=0) + 1
            if job_file['revision'] != revision:
                raise HTTPException(409, 'A newer revision exists. Refresh before queuing these edits.')
            job = {**job_file, 'status': 'queued', 'createdAt': time.time(), 'progress': {}, 'result': None}
            state['jobs'][job_file['jobId']] = job
            return public_job(job)
        return self.change(token, add)

    def claim(self, token, active=None, readiness=None):
        now = time.time()
        def take(state, device):
            device.update(lastSeen=now, readiness=readiness or 'Ready')
            available = [j for j in state['jobs'].values() if j['status'] == 'queued' or
                         (j['status'] == 'running' and (j.get('leaseUntil', 0) < now or j.get('deviceId') == device['id']))]
            if active:
                available.sort(key=lambda j: j['jobId'] != active)
            if not available:
                return {'job': None}
            job = available[0]
            if job.get('deviceId') != device['id'] or not job.get('lease'):
                job['lease'] = secrets.token_urlsafe(32)
            job.update(status='running', deviceId=device['id'], leaseUntil=now + LEASE_SECONDS)
            return {'job': copy.deepcopy(job)}
        return self.change(token, take, device=True)

    def report(self, token, job_id, lease, progress=None, result=None, error=None):
        if not isinstance(lease, str) or (progress is not None and not isinstance(progress, dict)) or (error is not None and not isinstance(error, str)):
            raise HTTPException(422, 'Invalid worker progress payload.')
        if result:
            result = ResultFile.model_validate(result).model_dump()
        def receive(state, device):
            device['lastSeen'] = time.time()
            job = state['jobs'].get(job_id)
            if not job or job.get('deviceId') != device['id'] or not secrets.compare_digest(job.get('lease') or '', lease):
                raise HTTPException(409, 'This job has been reassigned. The local result remains saved.')
            if job['status'] == 'complete':
                if result and job['result'] != result:
                    raise HTTPException(409, 'Completed results are immutable.')
                return {'ok': True}
            if job['status'] != 'running':
                raise HTTPException(409, 'This job is no longer running.')
            job['leaseUntil'] = time.time() + LEASE_SECONDS
            if progress is not None:
                job['progress'] = progress
            if result:
                self.validate_result(job, result)
                job.update(status='complete', result=result, completedAt=time.time())
            if error:
                job.update(status='failed', error=error[:500])
            return {'ok': True}
        return self.change(token, receive, device=True)

    @staticmethod
    def validate_result(job, result):
        if any(result[k] != job[k] for k in ('jobId', 'recipeKey', 'revision')):
            raise HTTPException(409, 'Results belong to a different job revision.')
        districts = result['districts']
        if len({d['id'] for d in districts}) != len(districts) or sum(d['homes'] for d in districts) != job['recipe']['homes']:
            raise HTTPException(422, 'Result districts do not cover this job.')
        rollup = result['rollup']
        if not rollup.get('complete') or rollup.get('totalHomes') != job['recipe']['homes'] or rollup.get('completedDistricts') != len(districts):
            raise HTTPException(422, 'Only complete, matching results can be imported.')

    def import_result(self, token, value):
        result = ResultFile.model_validate(value).model_dump()
        def receive(state, _):
            job = state['jobs'].get(result['jobId'])
            if not job:
                raise HTTPException(404, 'Import the job file into this workspace first.')
            self.validate_result(job, result)
            if job['status'] == 'complete' and job['result'] != result:
                raise HTTPException(409, 'Completed results are immutable.')
            job.update(status='complete', result=result, completedAt=time.time(), imported=True, lease=None)
            return public_job(job)
        return self.change(token, receive)


def service():
    try:
        return Portal(configured_store())
    except StoreUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


def bearer(request):
    value = request.headers.get('authorization', '')
    if not value.startswith('Bearer '):
        raise HTTPException(401, 'Open a workspace link to continue.')
    return value[7:]


async def body(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 2_000_000:
            raise HTTPException(413, 'Job metadata is too large. Keep full archives on the local computer.')
    try:
        value = orjson.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except ValueError as exc:
        raise HTTPException(422, 'Expected a JSON object.') from exc


def limited(request, label, limit):
    store = service().store
    address = request.client.host if request.client else 'unknown'
    if not store.rate(label + ':' + hashed(address), limit):
        raise HTTPException(429, 'Too many attempts. Try again in ten minutes.')


def prepare_recipe(value):
    from api._agent_config import Proposal, preset_config, validate_proposal
    from utilsim.config.presets import deep_merge
    from utilsim.worker.contracts import Recipe

    proposal = Proposal.model_validate(value['proposal'])
    validated = validate_proposal(proposal)
    config = deep_merge(preset_config(proposal.preset).model_dump(mode='json'), proposal.townOverrides)
    return Recipe(name=proposal.name, modelId=value['modelId'], homes=proposal.totalHomes or validated['homes'],
                  chunkSize=value.get('chunkSize', 2000), staffing=value['staffing'], config=config,
                  proposal={**proposal.model_dump(by_alias=True), 'townRef': validated['townRef']}, request={'settings': proposal.settings, 'episodes': validated['episodes'],
                                                        'seed': proposal.seed or None, 'asOf': proposal.asOf}).model_dump()


@router.get('/status')
def status():
    try:
        service().store.get('health')
        return {'schemaVersion': 'local-portal-status/1.0', 'available': True}
    except (HTTPException, StoreUnavailable):
        return {'schemaVersion': 'local-portal-status/1.0', 'available': False,
                'message': 'Shared pairing and job sync need Upstash Redis. Manual files work without it.'}


@router.post('/workspaces')
def create(request: Request):
    limited(request, 'create', 10)
    return service().create()


@router.get('/workspace')
def read(request: Request):
    return service().read(bearer(request))


@router.post('/pairings')
def pairing(request: Request):
    limited(request, 'pair', 30)
    return service().pairing(bearer(request))


@router.post('/redeem')
async def redeem(request: Request):
    limited(request, 'redeem', 30)
    data = await body(request)
    if not isinstance(data.get('code'), str) or not isinstance(data.get('name'), str):
        raise HTTPException(422, 'Enter a code and computer name.')
    return service().redeem(data['code'], data['name'])


@router.post('/devices/{device_id}/revoke')
def revoke(device_id: str, request: Request):
    return service().revoke(bearer(request), device_id)


@router.post('/prepare')
async def prepare(request: Request):
    data = await body(request)
    try:
        recipe = prepare_recipe(data)
        job = JobFile(jobId=uuid.uuid4().hex, revision=data.get('revision', 1), recipeKey=recipe_key(recipe), recipe=recipe)
        return check_job(job.model_dump())
    except (ValueError, KeyError, ValidationError) as exc:
        raise HTTPException(422, str(exc)[:1000]) from exc


@router.post('/jobs')
async def queue(request: Request):
    return service().queue(bearer(request), await body(request))


@router.post('/claim')
async def claim(request: Request):
    data = await body(request)
    return service().claim(bearer(request), data.get('active'), data.get('readiness'))


@router.post('/jobs/{job_id}/report')
async def report(job_id: str, request: Request):
    data = await body(request)
    return service().report(bearer(request), job_id, data.get('lease', ''), data.get('progress'), data.get('result'), data.get('error'))


@router.post('/results/import')
async def import_result(request: Request):
    return service().import_result(bearer(request), await body(request))


@router.post('/check-file')
async def check_file(request: Request):
    return check_job(await body(request))


@router.post('/check-result')
async def check_result(request: Request):
    value = await body(request)
    raw = value['job']
    job = check_job({k: raw[k] for k in ('schemaVersion', 'jobId', 'revision', 'recipeKey', 'recipe')})
    result = ResultFile.model_validate(value['result']).model_dump()
    Portal.validate_result(job, result)
    return result


@router.post('/jobs/{job_id}/retry')
def retry(job_id: str, request: Request):
    def change(state, _):
        job = state['jobs'].get(job_id)
        if not job or job['status'] != 'failed':
            raise HTTPException(409, 'Only failed jobs can be retried.')
        job.update(status='queued', lease=None, leaseUntil=0)
        job.pop('error', None)
        return public_job(job)
    return service().change(bearer(request), change)


@router.post('/details')
async def detail_request(request: Request):
    from utilsim.worker.details import DetailQuery
    query = DetailQuery.model_validate(await body(request)).model_dump()
    def add(state, _):
        job = state['jobs'].get(query['jobId'])
        if not job or job['status'] != 'complete':
            raise HTTPException(422, 'Choose a completed revision.')
        if not job.get('deviceId'):
            raise HTTPException(409, 'These results were imported manually. Open the run folder in the local reader.')
        if query['runKey'] not in {d['runKey'] for d in job['result']['districts']}:
            raise HTTPException(422, 'District does not belong to this revision.')
        now = time.time()
        requests = {k: v for k, v in state.get('details', {}).items() if v['expires'] > now}
        if len(requests) >= 5:
            raise HTTPException(429, 'Wait for an existing detail request to expire (five minutes).')
        rid = uuid.uuid4().hex
        requests[rid] = {'id': rid, 'query': query, 'deviceId': job['deviceId'], 'expires': now + 300,
                         'status': 'queued', 'result': None}
        state['details'] = requests
        return requests[rid]
    return service().change(bearer(request), add)


@router.get('/details/{rid}')
def detail_read(rid: str, request: Request):
    def get(state, _):
        value = state.get('details', {}).get(rid)
        if not value or value['expires'] < time.time():
            raise HTTPException(404, 'Detail request expired. Request it again.')
        return value
    return service().change(bearer(request), get)


@router.post('/device/details')
async def device_details(request: Request):
    value = await body(request)
    def change(state, device):
        pending = state.get('details', {})
        if value.get('id'):
            old = pending.get(value['id'])
            if not old or old['deviceId'] != device['id'] or old['expires'] < time.time():
                raise HTTPException(409, 'Detail request is no longer assigned to this computer.')
            if len(orjson.dumps(value.get('result'))) > 500_000:
                raise HTTPException(422, 'Page too large. Keep the full table on the local computer.')
            old.update(status='complete', result=value.get('result'), error=str(value.get('error') or '')[:500])
        return {'requests': [r for r in pending.values() if r['deviceId'] == device['id'] and
                             r['expires'] > time.time() and r['status'] == 'queued'][:1]}
    return service().change(bearer(request), change, device=True)
