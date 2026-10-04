"""Loopback-only runner UI, authenticated independently from the hosted workspace."""
from __future__ import annotations

import secrets
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from utilsim.worker.agent import Agent


def assets():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
    return root / 'packages/town-viewer/dist'


def create_app(agent, local_token):
    @asynccontextmanager
    async def lifespan(app):
        thread = threading.Thread(target=agent.loop, daemon=True)
        thread.start()
        yield
        agent.shutdown.set()
        thread.join(timeout=20)

    app = FastAPI(lifespan=lifespan)

    @app.middleware('http')
    async def guard(request, call_next):
        if request.url.hostname not in ('127.0.0.1', 'localhost'):
            return JSONResponse({'detail': 'Loopback access only.'}, 403)
        if request.url.path.startswith('/local/') and not secrets.compare_digest(
                request.headers.get('authorization', ''), 'Bearer ' + local_token):
            return JSONResponse({'detail': 'Reopen the runner from its launcher.'}, 401)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/')
    def index():
        return FileResponse(assets() / 'runner.html')

    @app.get('/local/status')
    def status():
        return agent.snapshot()

    @app.post('/local/pair')
    async def pair(request: Request):
        from api._portal import body
        data = await body(request)
        try:
            agent.pair(data['portal'], data['code'])
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, 'Pairing failed. Check the code and Studio address.') from exc
        return agent.snapshot()

    @app.post('/local/pause')
    async def pause(request: Request):
        data = await request.json()
        if type(data.get('paused')) is not bool:
            raise HTTPException(422, 'Expected paused true or false.')
        agent.state['paused'] = data['paused']
        agent.save()
        return agent.snapshot()

    @app.post('/local/import')
    async def import_job(request: Request):
        from api._portal import body
        try:
            agent.import_job(await body(request))
        except ValueError as exc:
            raise HTTPException(422, str(exc)[:500]) from exc
        return agent.snapshot()

    @app.get('/local/results/{job_id}')
    def result(job_id: str):
        if len(job_id) != 32 or any(c not in 'abcdef0123456789' for c in job_id):
            raise HTTPException(404)
        path = agent.store / 'results' / (job_id + '.result.json')
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, filename=path.name)

    @app.get('/local/library')
    def library():
        from utilsim.io.run_bundle import read_manifest
        entries = []
        for path in sorted((agent.store / 'runs').glob('*/manifest.json')):
            manifest = read_manifest(path.parent, verify=False)
            entries.append({'runKey': manifest['runKey'], 'asOf': manifest['asOf'], 'towns': manifest['towns']})
        return {'runs': entries}

    @app.get('/health')
    def health():
        return HTMLResponse('Utility Studio runner')

    app.mount('/assets', StaticFiles(directory=assets()), name='assets')
    return app


def serve(store, port=8010, open_browser=True):
    import uvicorn

    from utilsim.batch import job_lock

    root = Path(store).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('The selected storage folder must exist. Reconnect the drive or choose an existing folder.')
    token = secrets.token_urlsafe(32)
    with job_lock(root / 'runner.lock'):
        agent = Agent(root)
        if open_browser:
            threading.Timer(1.2, lambda: webbrowser.open(f'http://127.0.0.1:{port}/#token={token}')).start()
        uvicorn.run(create_app(agent, token), host='127.0.0.1', port=port, access_log=False)
