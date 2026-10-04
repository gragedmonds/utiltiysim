"""Exercise launcher readiness without generating or replaying a simulation."""
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
def running_runner(root):
    root.mkdir()
    ready = root / 'ready.json'
    source = str(Path(__file__).resolve().parents[1])
    script = 'from utilsim.worker.server import serve; import sys; serve(sys.argv[1], 0, ready_file=sys.argv[2])'
    with (root / 'test.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-c', script, str(root), str(ready)], cwd=root,
                                   env={**os.environ, 'PYTHONPATH': source}, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 25
            with httpx.Client(timeout=1, trust_env=False) as client:
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


def test_dynamic_ports_ready_credentials_and_bundled_ui(tmp_path):
    with running_runner(tmp_path / 'first') as (client, origin, headers, ready):
        assert client.get(origin + '/').status_code == 200
        assert client.get(origin + '/assets/runner.js').status_code == 200
        assert client.get(origin + '/local/status').status_code == 401
        assert client.get(origin + '/local/status', headers={**headers, 'Host': 'external.example'}).status_code == 403
        state = client.get(origin + '/local/status', headers=headers).json()
        assert state['schemaVersion'] == 'local-status/1.0' and state['active'] is None
        if os.name != 'nt':
            assert ready.stat().st_mode & 0o077 == 0
        with running_runner(tmp_path / 'second') as (other, second, second_headers, _):
            assert second != origin
            assert other.get(second + '/local/status', headers=headers).status_code == 401
            assert other.get(second + '/local/status', headers=second_headers).status_code == 200
