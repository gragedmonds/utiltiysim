"""The app's server: Utility Studio and the whole engine API on a loopback port, with the job queue, all offline.

One process serves the Studio pages (packages/town-viewer/dist at /), the prebuilt town packs (/packs), the engine
API Studio talks to (/api, api/app.py: setup, towns, operations, meter-to-cash, simulation codes), the run bundles
every finished district writes (/runs/<runKey>/…, for the saved-results reader) and this computer's job queue and
settings (/local/…). /local needs the per-launch bearer token the launcher passes in the page URL; everything binds
to 127.0.0.1 and refuses other Host headers. There is no CORS: only pages this process serves may call it.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from utilsim.worker.jobs import LocalJobs

KEY_FILE = '.claude-key'


def bundle_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))


def assets():
    return bundle_root() / 'packages/town-viewer/dist'


def create_app(jobs: LocalJobs, local_token, on_ready=None):
    from api import _agent
    from api.app import app as engine
    from utilsim.worker import vault

    key_path = jobs.store / KEY_FILE
    _agent.KEY_SOURCES.append(lambda: vault.read(key_path))

    @asynccontextmanager
    async def lifespan(app):
        jobs.start()
        try:
            if on_ready:
                on_ready()
            yield
        finally:
            jobs.shutdown.set()
            if jobs.thread:
                jobs.thread.join(timeout=20)

    app = FastAPI(lifespan=lifespan, title='Utility Studio', docs_url=None, redoc_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=2048)

    @app.middleware('http')
    async def guard(request, call_next):
        if request.url.hostname not in ('127.0.0.1', 'localhost'):
            return JSONResponse({'detail': 'Loopback access only.'}, 403)
        if request.url.path.startswith('/local/') and not secrets.compare_digest(
                request.headers.get('authorization', ''), 'Bearer ' + local_token):
            return JSONResponse({'detail': 'Reopen Utility Studio from its launcher.'}, 401)
        response = await call_next(request)
        response.headers['Referrer-Policy'] = 'no-referrer'
        if not request.url.path.startswith('/runs/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    app.include_router(engine.router)  # the engine API, /api/…

    # ---- this computer: the queue -------------------------------------------------------------------------------
    @app.get('/local/status')
    def status():
        return jobs.snapshot()

    @app.get('/local/jobs')
    def list_jobs(model: str):
        return {'jobs': jobs.revisions(model)}

    @app.post('/local/jobs')
    async def queue(request: Request):
        from pydantic import ValidationError

        from utilsim.worker.prepare import body
        data = await body(request)
        try:
            return jobs.queue({'proposal': data['proposal'], 'modelId': str(data['modelId']),
                               'chunkSize': int(data.get('chunkSize', 2000))})
        except ValidationError as exc:
            raise HTTPException(422, '; '.join(e['msg'].removeprefix('Value error, ') for e in exc.errors())[:3000]) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)[:3000]) from exc

    @app.post('/local/jobs/{job_id}/retry')
    def retry(job_id: str):
        try:
            jobs.retry(job_id)
        except KeyError as exc:
            raise HTTPException(404) from exc
        return jobs.snapshot()

    @app.delete('/local/jobs/{job_id}')
    def remove(job_id: str):
        try:
            jobs.remove(job_id)
        except KeyError as exc:
            raise HTTPException(404) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return jobs.snapshot()

    @app.post('/local/pause')
    async def pause(request: Request):
        data = await request.json()
        if type(data.get('paused')) is not bool:
            raise HTTPException(422, 'Expected paused true or false.')
        jobs.set_paused(data['paused'])
        return jobs.snapshot()

    @app.get('/local/results/{job_id}')
    def result(job_id: str):
        if len(job_id) != 32 or any(c not in 'abcdef0123456789' for c in job_id):
            raise HTTPException(404)
        path = jobs.store / 'results' / (job_id + '.result.json')
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, filename=path.name)

    @app.get('/local/library')
    def library():
        from utilsim.io.run_bundle import read_manifest
        entries = []
        for path in sorted((jobs.store / 'runs').glob('*/manifest.json')):
            manifest = read_manifest(path.parent, verify=False)
            entries.append({'runKey': manifest['runKey'], 'asOf': manifest['asOf'], 'towns': manifest['towns']})
        return {'runs': entries}

    # ---- this computer: Talk it through -------------------------------------------------------------------------
    @app.get('/local/claude-key')
    def claude_key():
        env = bool(os.environ.get('ANTHROPIC_API_KEY'))
        return {'configured': env or bool(vault.read(key_path)), 'fromEnvironment': env}

    @app.post('/local/claude-key')
    async def save_claude_key(request: Request):
        data = await request.json()
        key = str(data.get('key') or '').strip()
        if key:
            if len(key) > 400 or not key.isascii() or any(c.isspace() for c in key):
                raise HTTPException(422, 'That does not look like an Anthropic API key.')
            vault.save(key_path, key)
        else:
            vault.clear(key_path)
        return {'configured': bool(key) or bool(os.environ.get('ANTHROPIC_API_KEY'))}

    @app.get('/health')
    def health():
        return {'ok': True}

    # ---- pages and files ----------------------------------------------------------------------------------------
    (jobs.store / 'runs').mkdir(exist_ok=True)
    app.mount('/runs', StaticFiles(directory=jobs.store / 'runs'), name='runs')
    app.mount('/packs', StaticFiles(directory=bundle_root() / 'packs'), name='packs')
    app.mount('/', StaticFiles(directory=assets(), html=True), name='studio')
    return app


def serve(store, port=0, open_browser=True, ready_file=None):
    import uvicorn

    from utilsim.batch import job_lock

    root = Path(store).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('The selected storage folder must exist. Reconnect the drive or choose an existing folder.')
    os.environ.setdefault('UTILSIM_CACHE', str(root / 'cache'))  # generated towns' snapshots stay in the library too
    token = secrets.token_urlsafe(32)
    with job_lock(root / 'runner.lock'), socket.socket() as listener:
        listener.bind(('127.0.0.1', port))
        port = listener.getsockname()[1]
        jobs = LocalJobs(root)
        url = f'http://127.0.0.1:{port}/#token={token}'

        def ready():
            if ready_file:
                fd = os.open(ready_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    json.dump({'url': url}, stream)
            elif open_browser:
                threading.Timer(1.2, lambda: webbrowser.open(url)).start()

        config = uvicorn.Config(create_app(jobs, token, ready), access_log=False)
        uvicorn.Server(config).run(sockets=[listener])
