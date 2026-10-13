"""Advance a fresh isolated physical owner over HTTP; never target a live service.

This is backend acceptance, not WorkOS/browser, connected billing or scale proof.
The caller supplies an already reviewed, hash-pinned hosted template directory.
"""
import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from utilsim.hosted.templates import verify
from utilsim.world.store import canonical

REPO = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def hashes(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob('*')) if p.is_file()}


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def run(template, output, start, through, batch_days=14):
    template, output = Path(template).resolve(), Path(output).resolve()
    first, end = date.fromisoformat(start), date.fromisoformat(through)
    if first.isoformat() != start or end.isoformat() != through or not 1 <= (end - first).days <= 366:
        raise ValueError('Use canonical dates spanning one to 366 days.')
    if type(batch_days) is not int or not 1 <= batch_days <= 31:
        raise ValueError('Use batches of one to 31 days.')
    if output.exists() or output.is_relative_to(template) or template.is_relative_to(output):
        raise ValueError('Choose a new output directory separate from the source template.')
    manifest = verify(template, template.name)
    before = hashes(template)
    snapshot = json.loads((template / 'source-snapshot.json').read_text(encoding='utf-8'))
    output.mkdir(parents=True)
    data = output / 'data'
    shutil.copytree(template, data / 'templates' / manifest['sourceId'] / template.name)
    report = {'schemaVersion': 'hosted-horizon-acceptance/1', 'status': 'running',
              'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
              'runnerSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'sourceRevision': template.name, 'start': start, 'through': through,
              'counts': manifest['counts'], 'sourceOccupants': sum(p.get('occupants', 0) for p in snapshot['premises']),
              'scope': 'isolated physical HTTP; no browser, enterprise controller or financial processing',
              'batches': [], 'restartCount': 0, 'sourceHashes': before}
    write(output / 'result.json', report)
    with socket.socket() as available:
        available.bind(('127.0.0.1', 0))
        port = available.getsockname()[1]
    token = secrets.token_urlsafe(48)
    env = {k: v for k, v in os.environ.items() if not k.startswith('UTILITYSIM_')}
    env.update(UTILITYSIM_DATA_ROOT=str(data), UTILITYSIM_RUNTIME_TOKEN=token, PYTHONPATH=str(REPO))
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
               'X-UtilitySim-User-Id': 'isolated-horizon-qa',
               'X-UtilitySim-Grants': canonical([{'role': 'owner', 'town': manifest['grantTownId']}])}
    opener = build_opener(ProxyHandler({}))
    process = None
    log = (output / 'server.log').open('w', encoding='utf-8')

    def call(path, value=None):
        request = Request(f'http://127.0.0.1:{port}' + path, headers=headers,
                          data=None if value is None else canonical(value).encode())
        with opener.open(request, timeout=600) as response:
            return json.load(response)

    def boot():
        nonlocal process
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn',
            'utilsim.hosted.server:from_environment', '--factory', '--host', '127.0.0.1',
            '--port', str(port)], cwd=REPO, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        until = time.monotonic() + 60
        while time.monotonic() < until:
            if process.poll() is not None:
                raise RuntimeError('QA producer exited; inspect server.log.')
            try:
                if call('/hosted/health')['status'] == 'ready':
                    return
            except (URLError, ConnectionError):
                time.sleep(.1)
        raise TimeoutError('QA producer did not become ready.')

    def stop():
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)

    began = time.monotonic()
    try:
        boot()
        command = {'commandId': str(uuid.uuid4()), 'sourceId': manifest['sourceId'],
                   'sourceRevision': template.name, 'name': 'Isolated physical horizon acceptance',
                   'start': start, 'configuration': {}}
        created = call('/hosted/worlds', command)
        assert created['available'] and created['days'] == 0
        identity = created['id']
        base = '/hosted/worlds/' + identity
        report.update(worldId=identity, environmentId=created['environmentId'], configuration=created['configuration'])
        bindings = call(base + '/map/bindings')
        assert call(base + '/map/snapshot') == snapshot
        cursor = first
        prefix_path = None
        prefix_digest = None
        observed = 0
        commodities = set()
        while cursor < end:
            target = min(cursor + timedelta(days=batch_days), end)
            advance_started = time.monotonic()
            state = call(base + '/advance', {'through': target.isoformat()})
            assert state['id'] == identity and state['environmentId'] == created['environmentId']
            assert state['through'] == target.isoformat() and state['days'] == (target - first).days
            observation_path = base + '/observations?' + urlencode({'start': cursor.isoformat(), 'end': target.isoformat()})
            feed = call(observation_path)
            rows = feed['observations']
            assert len({r['sourceId'] for r in rows}) == len(rows)
            assert all(cursor.isoformat() < r['end'] <= target.isoformat() for r in rows)
            commodities.update(r['commodity'] for r in rows)
            observed += len(rows)
            assert observed == state['observations'], 'Missing or duplicate observations across completed batches.'
            # Repeat the original date after a real process restart. No DB/API shortcut.
            if prefix_path is None:
                prefix_path, prefix_digest = observation_path, digest(feed)
                stop()
                boot()
                report['restartCount'] += 1
                assert call('/hosted/worlds', command)['id'] == identity
            retried = call(base + '/advance', {'through': target.isoformat()})
            assert retried == state, 'Exact-date retry changed physical state.'
            assert digest(call(observation_path)) == digest(feed)
            assert digest(call(prefix_path)) == prefix_digest, 'Earlier observations changed.'
            report['batches'].append({'start': cursor.isoformat(), 'through': target.isoformat(),
                'days': state['days'], 'observations': len(rows), 'observationHash': digest(feed),
                'elapsedSeconds': round(time.monotonic() - advance_started, 3)})
            write(output / 'result.json', report)
            print(canonical(report['batches'][-1]), flush=True)
            cursor = target
        # Paged history covers exactly the completed days, without repeated source IDs.
        premise = snapshot['premises'][0]['id']
        history_ids = set()
        for offset in range(0, state['days'], 31):
            page = call(base + '/premises/' + premise + '/history?' + urlencode({'offset': offset, 'limit': 31}))
            assert page['totalDays'] == state['days']
            ids = {r['observationId'] for r in page['readings']}
            assert len(ids) == len(page['readings']) and not ids.intersection(history_ids)
            history_ids.update(ids)
        assert call(base + '/map/snapshot') == snapshot
        assert call(base + '/map/bindings') == bindings
        assert call('/hosted/worlds')['total'] == 1
        # Final restart confirms the entire horizon, not just the first interval.
        stop()
        boot()
        report['restartCount'] += 1
        assert call(base) == state
        for batch in report['batches']:
            historical = call(base + '/observations?' + urlencode({
                'start': batch['start'], 'end': batch['through']}))
            assert digest(historical) == batch['observationHash'], 'Recorded observation window changed.'
        assert hashes(template) == before
        report.update(status='passed', completedDays=state['days'], observations=observed,
                      commodities=sorted(commodities), samplePremiseHistoryRows=len(history_ids),
                      revalidatedWindows=len(report['batches']), sourceUnchanged=True,
                      elapsedSeconds=round(time.monotonic() - began, 3))
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        stop()
        log.close()
        report['serverStopped'] = process is None or process.poll() is not None
        write(output / 'result.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', default='2026-01-01')
    parser.add_argument('--through', default='2026-06-01')
    parser.add_argument('--batch-days', type=int, default=14)
    options = parser.parse_args()
    result = run(options.template, options.output, options.start, options.through, options.batch_days)
    print(canonical({k: result[k] for k in ('status', 'completedDays', 'observations', 'sourceUnchanged')}))
