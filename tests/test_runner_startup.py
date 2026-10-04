"""The app's server starts without generating or replaying anything: a free port, a readiness file with the per-launch
credential, the Studio pages, the packs, the engine API and the job queue behind the token."""
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx


@contextmanager
def running_app(root):
    root.mkdir()
    ready = root / 'ready.json'
    source = str(Path(__file__).resolve().parents[1])
    script = 'from utilsim.worker.server import serve; import sys; serve(sys.argv[1], 0, ready_file=sys.argv[2])'
    with (root / 'test.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-c', script, str(root), str(ready)], cwd=root,
                                   env={**os.environ, 'PYTHONPATH': source}, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 40
            with httpx.Client(timeout=5, trust_env=False) as client:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise AssertionError((root / 'test.log').read_text())
                    try:
                        address = urlparse(json.loads(ready.read_text())['url'])
                        headers = {'Authorization': 'Bearer ' + parse_qs(address.fragment)['token'][0]}
                        origin = 'http://' + address.netloc
                        response = client.get(origin + '/local/status', headers=headers)
                        if response.status_code == 200:
                            break
                    except (OSError, ValueError, httpx.HTTPError):
                        pass
                    time.sleep(.1)
                else:
                    raise AssertionError('No authenticated readiness response: ' + (root / 'test.log').read_text())
                yield client, origin, headers, ready
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def test_dynamic_port_credentials_pages_packs_and_engine(tmp_path):
    with running_app(tmp_path / 'first') as (client, origin, headers, ready):
        page = client.get(origin + '/')
        assert page.status_code == 200 and 'setup.js' in page.text  # the Studio entry (the setup wizard)
        assert client.get(origin + '/setup.js').status_code == 200
        assert client.get(origin + '/runs.html').status_code == 200
        assert client.get(origin + '/packs/index.json').json()['schemaVersion'] == 'town-pack/1.0'
        health = client.get(origin + '/api/health').json()
        assert health['engine'] == 'local' and 'small_town' in health['towns']
        assert client.get(origin + '/api/setup/configuration?preset=small_town').status_code == 200
        assert client.get(origin + '/api/setup-agent/status').json()['available'] is False
        assert client.get(origin + '/local/status').status_code == 401
        assert client.get(origin + '/local/status', headers={**headers, 'Host': 'external.example'}).status_code == 403
        state = client.get(origin + '/local/status', headers=headers).json()
        assert state['schemaVersion'] == 'local-status/2.0' and state['active'] is None and state['jobs'] == []
        assert client.get(origin + '/local/claude-key', headers=headers).json() == {'configured': False, 'fromEnvironment': False}
        if os.name != 'nt':
            assert ready.stat().st_mode & 0o077 == 0
        # Another library gets its own server on its own port.
        with running_app(tmp_path / 'second') as (_, other, *_rest):
            assert other != origin
