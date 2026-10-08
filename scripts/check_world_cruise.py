"""Copied-town cruise browser acceptance with explicit process-loss injection.

Only copies are mutated. The child worker has a test-only 0.75-second cadence so
desktop pause/resume assertions are repeatable; this is not a speed benchmark.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utilsim.world import World, water_faults  # noqa: E402
from utilsim.world import field_execution as field  # noqa: E402
from utilsim.world.map_view import WorldMap  # noqa: E402
from utilsim.world.store import canonical  # noqa: E402


def wait_for(predicate, message, timeout=45):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError(message)


def request(base, path='/api/cruise', payload=None):
    req = Request(base+path, data=canonical(payload).encode() if payload is not None else None,
                  headers={'Content-Type': 'application/json'} if payload is not None else {})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


def copy_database(source, destination):
    with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)


def source_hashes(path):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [path, Path(str(path)+'-wal'), Path(str(path)+'-shm')] if p.exists()}


def history(world, through, max_sequence):
    with world.db() as db:
        events = [dict(row) for row in db.execute('SELECT * FROM events WHERE sequence<=? ORDER BY sequence', (max_sequence,))]
        start = world.metadata(db)['start']
    return hashlib.sha256(canonical({'observations': world.export_v2(start, through), 'events': events}).encode()).hexdigest()


def serve(args):
    from utilsim.world import cruise
    from utilsim.world.server import make_server

    if args._interrupt:
        original = field._enqueue
        def interrupted(*values, **keywords):
            if values[4] == 'report':
                (args.out/'interruption.json').write_text(json.dumps({'phase': 'after-physical-repair-before-field-report',
                                                                    'pid': os.getpid()}), encoding='utf-8')
                os._exit(86)
            return original(*values, **keywords)
        field._enqueue = interrupted
    original_tick = cruise.tick
    def paced_tick(*values, **keywords):
        time.sleep(.75)  # Test-only control window; never a claimed runtime speed.
        return original_tick(*values, **keywords)
    cruise.tick = paced_tick
    server = make_server(World(args.db), args._port, args.viewer_dir,
                         None if args._world_only else args.out/'field.sqlite', cruise_worker=not args._worker_disabled)
    (args.out/(args._launch+'.json')).write_text(json.dumps({'port': server.server_port, 'pid': os.getpid()}), encoding='utf-8')
    try:
        server.serve_forever()
    finally:
        server.server_close()


class Child:
    def __init__(self, args, database, name, port=0, interrupt=False, world_only=False, worker_disabled=False):
        command = [sys.executable, str(Path(__file__).resolve()), '--db', str(database), '--viewer-dir',
                   str(args.viewer_dir), '--out', str(args.out), '--_serve', '--_launch', name, '--_port', str(port)]
        if interrupt:
            command.append('--_interrupt')
        if world_only:
            command.append('--_world-only')
        if worker_disabled:
            command.append('--_worker-disabled')
        self.log = (args.out/(name+'.log')).open('w', encoding='utf-8')
        self.process = subprocess.Popen(command, stdout=self.log, stderr=subprocess.STDOUT,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            def started():
                if self.process.poll() is not None:
                    raise AssertionError(f'Acceptance server exited before startup; inspect {name}.log')
                path = args.out/(name+'.json')
                if not path.exists():
                    return None
                state = json.loads(path.read_text(encoding='utf-8'))
                base = 'http://127.0.0.1:'+str(state['port'])
                try:
                    request(base)
                except (URLError, TimeoutError):
                    return None
                return state
            state = wait_for(started, 'Acceptance server did not become ready.')
            self.port = state['port']
            self.base = f'http://127.0.0.1:{self.port}'
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.log.close()


def setup_field(world, path, day):
    with world.db() as db:
        meta = world.metadata(db)
        assets = [dict(row) for row in db.execute("SELECT * FROM assets WHERE commodity='water' AND installed<=? ORDER BY id", (day,))]
    usable = []
    for asset in assets:
        if json.loads(asset['profile']).get('occupied', True) and water_faults.inspect(world, asset['id'])['current']['active'] is None:
            usable.append(asset)
            if len(usable) == 3:
                break
    assert len(usable) == 3, 'Acceptance needs three occupied commissioned water services without active leaks.'
    owner = field.FieldExecution(world, path)
    common = {'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin',
              'effectiveDate': day, 'causalReference': 'copied-cruise-acceptance'}
    field.command(owner, {**common, 'schemaVersion': field.VERSION, 'commandId': 'cruise-crew', 'action': 'configure-crew',
                          'crewId': 'cruise-plumbing', 'expectedRevision': 0, 'skills': ['plumbing'],
                          'weekdays': list(range(7)), 'dailyCapacity': 1})
    faults = []
    for index, asset in enumerate(usable):
        fault = water_faults.command(world, {'schemaVersion': water_faults.VERSION,
            'commandId': f'cruise-leak-{index}', 'environmentId': meta['environment'],
            'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin', 'action': 'start',
            'assetId': asset['id'], 'expectedRevision': water_faults.inspect(world, asset['id'])['current']['revision'],
            'reason': 'Explicit copied-town acceptance leak', 'causalReference': 'copied-cruise-acceptance', 'leakM3PerHour': '0.1'})
        faults.append(fault['faultId'])
        field.command(owner, {**common, 'schemaVersion': field.VERSION, 'commandId': f'cruise-assignment-{index}',
                              'action': 'accept', 'assignmentId': f'CRUISE-A{index}', 'crewId': 'cruise-plumbing',
                              'assetId': asset['id'], 'orderId': f'SYNTHETIC-CRUISE-ORDER-{index}', 'orderRevision': 1,
                              'scheduledDate': day, 'operation': field.OPERATION, 'reportDelayDays': 2})
    return owner, usable, faults


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True, help='Existing saved source world; never mutated')
    parser.add_argument('--viewer-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='Fresh output directory for copies and evidence')
    parser.add_argument('--_serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--_interrupt', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--_world-only', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--_worker-disabled', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--_launch', default='server', help=argparse.SUPPRESS)
    parser.add_argument('--_port', type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._serve:
        return serve(args)
    args.out.mkdir(parents=True, exist_ok=False)
    before_source = source_hashes(args.db)
    target, world_only_target = args.out/'world.sqlite', args.out/'world-only.sqlite'
    copy_database(args.db, target)
    copy_database(args.db, world_only_target)
    world = World(target)
    with world.db() as db:
        meta = world.metadata(db)
        event_sequence = db.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]
    snapshot = WorldMap(world).snapshot()
    prior_history = history(world, meta['through'], event_sequence)
    start = date.fromisoformat(meta['through'])
    def day(n):
        return (start+timedelta(days=n)).isoformat()
    owner, assets, faults = setup_field(world, args.out/'field.sqlite', day(0))
    children, errors, external = [], [], []
    from playwright.sync_api import expect, sync_playwright
    try:
        child = Child(args, target, 'interrupted-server', interrupt=True)
        children.append(child)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda req: external.append(req.url) if not req.url.startswith('http://127.0.0.1:') else None)
                page.goto(child.base+'/cruise')
                expect(page.locator('#start')).to_be_enabled()
                page.locator('#targetDate').fill(day(6))
                page.locator('#reason').fill('Bounded copied-town cruise acceptance')
                page.locator('#start').click()
                wait_for(lambda: child.process.poll() is not None, 'Injected post-repair process loss did not occur.')
                assert child.process.returncode == 86
                with world.db() as db:
                    assert db.execute("SELECT COUNT(*) FROM events WHERE type='PhysicalWaterLeakRepaired' AND subject=?", (assets[0]['id'],)).fetchone()[0] == 1
                interrupted = field.inspect(owner)
                assert interrupted['items'][0]['state'] == 'accepted'
                restarted = Child(args, target, 'restarted-server', port=child.port)
                children.append(restarted)
                page.goto(restarted.base+'/cruise')
                # Automatic recovery must finish the same day before the next one.
                wait_for(lambda: request(restarted.base)['through'] >= day(1), 'Restart did not recover the interrupted day.')
                page.locator('#refresh').click()
                expect(page.locator('#nextDay')).to_contain_text(day(1))
                page.locator('#reason').fill('Pause copied scenario to inspect finite-capacity backlog')
                active_job = request(restarted.base)
                lost_pause = []
                def lose_pause_reply(route):
                    if route.request.method == 'POST' and route.request.post_data_json.get('action') == 'pause':
                        payload = route.request.post_data_json
                        response = route.fetch()
                        assert response.ok, response.text()
                        lost_pause.append({'command': payload, 'result': response.json()})
                        route.abort()
                    else:
                        route.continue_()
                page.route('**/api/cruise', lose_pause_reply)
                page.locator('#pause').click()
                expect(page.locator('#message')).to_contain_text('outcome is uncertain')
                expect(page.locator('#retry')).to_be_visible()
                page.unroute('**/api/cruise', lose_pause_reply)
                wait_for(lambda: request(restarted.base)['status'] == 'paused', 'Cruise did not pause.')
                paused = request(restarted.base)
                assert len(lost_pause) == 1
                assert paused['jobId'] == active_job['jobId'] and paused['targetDate'] == active_job['targetDate']
                page.reload()
                expect(page.locator('#retry')).to_be_visible()
                page.locator('#retry').click()
                expect(page.locator('#retry')).to_be_hidden()
                retried_pause = request(restarted.base)
                assert retried_pause == paused
                with world.db() as db:
                    pauses = [json.loads(row[0]) for row in db.execute("SELECT payload FROM events WHERE type='CruiseControlChanged'")]
                    assert len([event for event in pauses if event['action'] == 'pause']) == 1
                    persisted = db.execute('SELECT payload,result FROM commands WHERE id=?',
                                           (lost_pause[0]['command']['commandId'],)).fetchone()
                    assert json.loads(persisted['payload']) == lost_pause[0]['command']
                    assert json.loads(persisted['result']) == lost_pause[0]['result']
                paused_day = paused['through']
                assert day(1) <= paused_day < day(6)
                time.sleep(1.1)
                assert request(restarted.base)['through'] == paused_day
                rows = field.inspect(owner)['items']
                assert any(row['state'] == 'accepted' for row in rows), 'Pause must retain the finite-capacity backlog.'
                assert any(row['state'] == 'executed' for row in rows)
                page.screenshot(path=str(args.out/'cruise-paused-1440.png'), full_page=True)
                page.reload()
                expect(page.locator('#resume')).to_be_enabled()
                page.locator('#reason').fill('Resume copied scenario after backlog inspection')
                page.locator('#resume').click()
                wait_for(lambda: request(restarted.base)['through'] == day(6), 'Cruise did not reach the bounded target.')
                wait_for(lambda: request(restarted.base)['status'] == 'completed', 'Cruise did not record target completion.')
                page.locator('#refresh').click()
                expect(page.locator('#completedThrough')).to_contain_text(day(5))
                page.screenshot(path=str(args.out/'cruise-completed-1440.png'), full_page=True)
                page.set_viewport_size({'width': 1024, 'height': 768})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.out/'cruise-completed-1024.png'), full_page=True)
                assert '\ufffd' not in page.locator('body').inner_text()
                rows = field.inspect(owner)['items']
                assert len(rows) == 3 and all(row['state'] == 'executed' for row in rows)
                assert [row['result']['effectiveDate'] for row in rows] == [day(0), day(1), day(2)]
                assert all(message['state'] == 'pending' for row in rows for message in row['messages'])
                with world.db() as db:
                    for asset, fault in zip(assets, faults, strict=True):
                        repairs = db.execute("SELECT payload FROM events WHERE type='PhysicalWaterLeakRepaired' AND subject=?", (asset['id'],)).fetchall()
                        assert sum(json.loads(row[0])['faultId'] == fault for row in repairs) == 1
                    assert not db.execute('SELECT 1 FROM water_fault_effects WHERE asset=? AND day=?', (assets[0]['id'], day(0))).fetchone()
                # A second copied run verifies that absence of a field store is
                # explicit world-only operation, not a fabricated field owner.
                only = Child(args, world_only_target, 'world-only-server', world_only=True)
                children.append(only)
                page.goto(only.base+'/cruise')
                assert request(only.base)['fieldConfigured'] is False
                expect(page.locator('#start')).to_be_enabled()
                page.locator('#targetDate').fill(day(2))
                page.locator('#reason').fill('World-only bounded acceptance')
                page.locator('#start').click()
                wait_for(lambda: request(only.base)['through'] == day(2), 'World-only cruise did not advance.')
                page.locator('#refresh').click()
                page.screenshot(path=str(args.out/'cruise-world-only-1024.png'), full_page=True)
                only.close()
                disabled = Child(args, world_only_target, 'worker-disabled-server', port=only.port,
                                 world_only=True, worker_disabled=True)
                children.append(disabled)
                page.goto(disabled.base+'/cruise')
                expect(page.locator('#failure')).to_be_visible()
                expect(page.locator('#start')).to_be_disabled()
                assert request(disabled.base)['workerEnabled'] is False
                page.screenshot(path=str(args.out/'cruise-worker-disabled-1024.png'), full_page=True)
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        assert history(world, meta['through'], event_sequence) == prior_history
        assert WorldMap(world).snapshot() == snapshot
        assert source_hashes(args.db) == before_source
        evidence = {'passed': True, 'premises': len(snapshot['premises']), 'sourceHashesUnchanged': True,
                    'historicalEventsAndObservationsPreserved': True, 'savedMapPreserved': True,
                    'from': day(0), 'through': day(6), 'worldOnlyThrough': day(2), 'fieldVisits': 3,
                    'repairsPerFault': 1, 'finiteCapacity': 1, 'backlogObserved': True,
                    'pauseReloadResume': True, 'serverExitCode': 86, 'restartRecoveredSamePhysicalRepair': True,
                    'lostPauseReplyReloadRetry': True, 'pauseControlEvents': 1, 'sameJobAndTargetAfterRetry': True,
                    'disabledWorkerVisibleAndStartBlocked': True,
                    'reportsRemainPending': True, 'viewports': [1440, 1024], 'browserErrors': errors,
                    'testOnlyWorkerDelaySeconds': .75, 'performanceBenchmark': False}
        (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(evidence))
    finally:
        for child in reversed(children):
            child.close()


if __name__ == '__main__':
    main()
