"""Copied-town browser proof that visits, crew claims and receipt are independent.

The receiver is a test inbox, not an enterprise adapter. A child exits after a
world repair commits, before field commit. Only fresh database copies are changed.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_world_cruise import (  # noqa: E402
    copy_database,
    history,
    request,
    setup_field,
    source_hashes,
    wait_for,
)

from utilsim.world import World, water_faults  # noqa: E402
from utilsim.world import field_execution as field  # noqa: E402
from utilsim.world.map_view import WorldMap  # noqa: E402


def serve(args):
    from utilsim.world.server import make_server
    if args._interrupt:
        original = field._physical
        def interrupted(*values, **keywords):
            result = original(*values, **keywords)
            if result['outcome'] == 'completed':
                (args.out/'interruption.json').write_text(json.dumps({'phase': 'after-world-commit-before-field-commit',
                                                                    'pid': os.getpid()}), encoding='utf-8')
                os._exit(86)
            return result
        field._physical = interrupted
    server = make_server(World(args.db), args._port, args.viewer_dir, args.out/'field.sqlite')
    (args.out/(args._launch+'.json')).write_text(json.dumps({'port': server.server_port, 'pid': os.getpid()}), encoding='utf-8')
    try:
        server.serve_forever()
    finally:
        server.server_close()


class Child:
    def __init__(self, args, database, name, port=0, interrupt=False):
        command = [sys.executable, str(Path(__file__).resolve()), '--db', str(database), '--viewer-dir',
                   str(args.viewer_dir), '--out', str(args.out), '--_serve', '--_launch', name, '--_port', str(port)]
        if interrupt:
            command.append('--_interrupt')
        self.log = (args.out/(name+'.log')).open('w', encoding='utf-8')
        self.process = subprocess.Popen(command, stdout=self.log, stderr=subprocess.STDOUT,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            def started():
                if self.process.poll() is not None:
                    raise AssertionError(f'Acceptance server exited; inspect {name}.log')
                path = args.out/(name+'.json')
                if not path.exists():
                    return None
                state = json.loads(path.read_text(encoding='utf-8'))
                try:
                    request('http://127.0.0.1:'+str(state['port']))
                except (URLError, TimeoutError):
                    return None
                return state
            state = wait_for(started, 'Acceptance server did not start')
            self.port, self.base = state['port'], f"http://127.0.0.1:{state['port']}"
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


def reports(owner):
    with owner.db() as db:
        return [json.loads(r[0]) for r in db.execute('SELECT envelope FROM field_outbox')
                if json.loads(r[0])['schema'] == 'field-report/1']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--viewer-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--_serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--_interrupt', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--_launch', default='server', help=argparse.SUPPRESS)
    parser.add_argument('--_port', type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._serve:
        return serve(args)
    args.out.mkdir(parents=True, exist_ok=False)
    before_source = source_hashes(args.db)
    target, baseline_path = args.out/'world.sqlite', args.out/'baseline.sqlite'
    copy_database(args.db, target)
    copy_database(args.db, baseline_path)
    world, baseline = World(target), World(baseline_path)
    with world.db() as db:
        meta = world.metadata(db)
        sequence = db.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]
    original_map = WorldMap(world).snapshot()
    original_history = history(world, meta['through'], sequence)
    start = date.fromisoformat(meta['through'])
    def day(n):
        return (start+timedelta(days=n)).isoformat()
    owner, assets, faults = setup_field(world, args.out/'field.sqlite', day(0))
    # Default manual-only fault model is explicitly pinned to no seeded faults.
    policy = water_faults.inspect(world, assets[0]['id'])['policy']
    water_faults.command(world, {'schemaVersion': water_faults.VERSION, 'commandId': 'reporting-policy',
        'environmentId': meta['environment'], 'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin',
        'expectedRevision': policy['revision'], 'action': 'configure', 'annualProbability': 0,
        'leakM3PerHour': '0.1', 'reason': 'Deterministic copied-town acceptance', 'causalReference': 'reporting-acceptance'})
    children, errors, external, lost = [], [], [], []
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
                page.goto(child.base+'/field-reporting')
                for i, work_mode in [(0, 'perform'), (1, 'inspect-only')]:
                    expect(page.locator('#assignmentSelect')).to_be_enabled()
                    page.locator('#assignmentSelect').select_option(f'CRUISE-A{i}')
                    page.locator('#reportMode').select_option('manual')
                    page.locator('#workMode').select_option(work_mode)
                    page.locator('#configure').click()
                    expect(page.locator('#message')).to_contain_text('recorded')
                page.goto(child.base+'/cruise')
                expect(page.locator('#start')).to_be_enabled()
                page.locator('#targetDate').fill(day(3))
                page.locator('#reason').fill('Visits progress while manual reports are missing')
                page.locator('#start').click()
                wait_for(lambda: child.process.poll() is not None, 'Post-physical interruption did not occur')
                assert child.process.returncode == 86
                assert water_faults.inspect(world, assets[0]['id'])['current']['active'] is None
                assert field.inspect(owner)['items'][0]['state'] == 'accepted'
                assert reports(owner) == []
                child = Child(args, target, 'restarted-server', port=child.port)
                children.append(child)
                wait_for(lambda: request(child.base)['status'] == 'completed', 'Cruise did not recover and progress')
                assert request(child.base)['through'] == day(3)
                rows = field.inspect(owner)['items']
                assert [r['result']['effectiveDate'] for r in rows] == [day(0), day(1), day(2)]
                assert [r['result']['outcome'] for r in rows] == ['completed', 'not_attempted', 'completed']
                assert rows[0]['result']['reportId'] is rows[1]['result']['reportId'] is None
                assert len(reports(owner)) == 1  # The third legacy automatic visit still reports normally.
                page.goto(child.base+'/field-reporting')
                page.locator('#assignmentSelect').select_option('CRUISE-A0')
                expect(page.locator('#submitReport')).to_be_enabled()
                page.screenshot(path=str(args.out/'report-missing-1440.png'), full_page=True)
                def lose_submit_reply(route):
                    if route.request.method == 'POST' and route.request.post_data_json.get('action') == 'submit':
                        response = route.fetch()
                        assert response.ok, response.text()
                        lost.append({'command': route.request.post_data_json, 'result': response.json()})
                        route.abort()
                    else:
                        route.continue_()
                page.route('**/api/field-reporting', lose_submit_reply)
                page.locator('#claimedOutcome').select_option('completed')
                page.locator('#submitReport').click()
                expect(page.locator('#message')).to_contain_text('uncertain')
                page.unroute('**/api/field-reporting', lose_submit_reply)
                page.reload()
                expect(page.locator('#retry')).to_be_visible()
                page.locator('#retry').click()
                expect(page.locator('#retry')).to_be_hidden()
                assert len(lost) == 1
                assert request(child.base, '/api/field-reporting', lost[0]['command']) == lost[0]['result']
                page.locator('#assignmentSelect').select_option('CRUISE-A1')
                page.locator('#claimedOutcome').select_option('completed')
                page.locator('#submitReport').click()
                expect(page.locator('#message')).to_contain_text('recorded')
                assert water_faults.inspect(world, assets[1]['id'])['current']['active']['id'] == faults[1]
                manual = [r for r in reports(owner) if r['correlation_id'] in ('CRUISE-A0', 'CRUISE-A1')]
                assert len(manual) == 2
                assert all(r['data']['submitted_at'] == day(3)+'T00:00:00Z' for r in manual)
                assert all(r['data']['outcome'] == 'completed' for r in manual)
                assert not any(r['envelope']['id'] in {m['id'] for m in manual} for r in field.ready(owner)['items'])
                with owner.db() as db:
                    for report in manual:
                        assert db.execute('SELECT available_day FROM field_outbox WHERE id=?', (report['id'],)).fetchone()[0] == day(5)
                for width, height in [(1440, 1000), (1024, 768)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(args.out/f'false-claim-pending-{width}.png'), full_page=True)
                page.goto(child.base+'/cruise')
                expect(page.locator('#start')).to_be_enabled()
                page.locator('#targetDate').fill(day(5))
                page.locator('#reason').fill('Observe persistent leak while crew report waits for transport')
                page.locator('#start').click()
                wait_for(lambda: (state := request(child.base))['status'] == 'completed' and state['through'] == day(5), 'Transport delay did not elapse')
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        baseline.advance(day(5))
        with world.db() as db, baseline.db() as control:
            for i in range(5):
                repaired = db.execute('SELECT quantity FROM observations WHERE asset=? AND day=?', (assets[0]['id'], day(i))).fetchone()[0]
                normal = control.execute('SELECT quantity FROM observations WHERE asset=? AND day=?', (assets[0]['id'], day(i))).fetchone()[0]
                assert repaired == normal
                leaking = db.execute('SELECT quantity FROM observations WHERE asset=? AND day=?', (assets[1]['id'], day(i))).fetchone()[0]
                normal = control.execute('SELECT quantity FROM observations WHERE asset=? AND day=?', (assets[1]['id'], day(i))).fetchone()[0]
                assert Decimal(leaking) > Decimal(normal)
            assert db.execute("SELECT COUNT(*) FROM events WHERE type='PhysicalWaterLeakRepaired' AND subject=?", (assets[0]['id'],)).fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM events WHERE type='PhysicalWaterLeakRepaired' AND subject=?", (assets[1]['id'],)).fetchone()[0] == 0
        inbox, attempts = {}, {}
        def receive(envelope):
            identity = envelope['id']
            attempts[identity] = attempts.get(identity, 0)+1
            checksum = field.checksum(envelope)
            if identity in inbox:
                assert inbox[identity]['checksum'] == checksum
            else:
                inbox[identity] = {'id': identity, 'environmentId': envelope['instance_id'], 'checksum': checksum,
                                   'status': 'received', 'receiptId': 'test-inbox-'+identity}
            if identity == manual[0]['id'] and attempts[identity] == 1:
                raise ConnectionError('Injected lost test-inbox receipt after acceptance')
            return inbox[identity]
        field.relay(owner, receive, limit=100)
        field.relay(owner, receive, limit=100)
        assert len(inbox) == 6 and attempts[manual[0]['id']] == 2
        assert all(m['state'] == 'received' for row in field.inspect(owner)['items'] for m in row['messages'])
        assert water_faults.inspect(world, assets[1]['id'])['current']['active']['id'] == faults[1]
        assert source_hashes(args.db) == before_source
        assert WorldMap(world).snapshot() == original_map
        assert history(world, meta['through'], sequence) == original_history
        evidence = {'passed': True, 'premises': len(original_map['premises']), 'from': day(0), 'through': day(5),
                    'manualRepairWithoutReportDuringCruise': True, 'crashRecoveredWithoutManufacturedReport': True,
                    'inspectOnlyUsesCrewCapacity': True, 'falseCompletedClaimLeavesLeakObservable': True,
                    'lostSubmitReplyReloadExactlyOnce': True, 'manualSubmissionDay': day(3), 'manualAvailableDay': day(5),
                    'testInboxMessages': 6, 'testInboxRetryDeduplicated': True, 'actualEnterpriseAdapterTested': False,
                    'sourceHashesUnchanged': True, 'historicalEventsAndObservationsPreserved': True, 'savedMapPreserved': True,
                    'browserErrors': errors, 'viewports': [1440, 1024], 'childPids': [c.process.pid for c in children]}
        (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
        (args.out/'test-inbox.json').write_text(json.dumps(inbox, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(evidence))
    finally:
        for child in reversed(children):
            child.close()
        assert all(c.process.poll() is not None for c in children)


if __name__ == '__main__':
    main()

