"""Paired saved-town backup acceptance for cancellation and replacement phases."""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_world_cruise import Child as DisabledChild  # noqa: E402
from check_world_cruise import copy_database, history, request, source_hashes, wait_for  # noqa: E402
from check_world_field_reporting import Child  # noqa: E402

from utilsim.world import World, water_mains  # noqa: E402
from utilsim.world import field_execution as field  # noqa: E402
from utilsim.world.map_view import WorldMap  # noqa: E402


def cancel_payload(owner, identity, ids):
    with owner.db() as db:
        meta = owner.metadata(db)
    return {'schemaVersion':'field-assignment-lifecycle/1', 'commandId':identity,
            'environmentId':meta['environment'], 'worldFingerprint':meta['fingerprint'],
            'actorId':'world-admin', 'effectiveDate':meta['through'], 'action':'cancel',
            'reason':'Explicit acceptance attempt against committed work', 'causalReference':'cancellation-acceptance',
            'assignmentIds':ids, 'expectedRevisions':{key:0 for key in ids}}


def rejected(base, payload):
    try:
        request(base, '/api/field-assignment-lifecycle', payload)
    except HTTPError as error:
        assert error.code == 422, error.read().decode()
        return
    raise AssertionError('Cancellation of committed work should reject')


def perform_ui_changes(page, child, owner, edge, day, expect, lost):
    expect(page.locator('#cancelAssignments')).to_be_enabled()
    page.locator('#cancelAssignments').select_option(['CLAIM-repair','CLAIM-restore'])
    page.locator('#lifecycleReason').fill('Explicitly retire both phases blocked by inspection-only isolation')
    def lose_reply(route):
        if route.request.method == 'POST' and route.request.post_data_json.get('action') == 'cancel':
            response = route.fetch()
            assert response.ok, response.text()
            lost.append({'command':route.request.post_data_json,'result':response.json()})
            route.abort()
        else:
            route.continue_()
    page.route('**/api/field-assignment-lifecycle', lose_reply)
    page.locator('#cancelSelected').click()
    expect(page.locator('#message')).to_contain_text('uncertain')
    page.unroute('**/api/field-assignment-lifecycle', lose_reply)
    page.reload()
    expect(page.locator('#retry')).to_be_visible()
    page.locator('#retry').click()
    expect(page.locator('#retry')).to_be_hidden()
    assert len(lost) == 1
    assert request(child.base, '/api/field-assignment-lifecycle', lost[0]['command']) == lost[0]['result']
    with owner.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='FieldAssignmentCancelled'").fetchone()[0] == 2
    for phase, predecessor in [('isolate',None),('repair','REPLACEMENT-isolate'),('restore','REPLACEMENT-repair')]:
        if predecessor:
            page.locator('#replacementSelect').select_option('CLAIM-'+phase)
            page.locator('#lifecycleReason').fill('Authorize fresh phase with an explicitly chosen physical predecessor')
            page.locator('#prepareReplacement').click()
        else:
            page.locator('#operation').select_option(phase+'-water-main')
        for name,value in {'assignmentId':'REPLACEMENT-'+phase,'crewId':'main-crew','assetId':edge,
            'orderId':'SYNTHETIC-REPLACEMENT-'+phase,'orderRevision':'1','scheduledDate':day(0),'reportDelayDays':'2'}.items():
            if predecessor and name == 'assetId':
                expect(page.locator(f'#assignment [name={name}]')).to_have_value(value)
                expect(page.locator(f'#assignment [name={name}]')).to_be_disabled()
            else:
                page.locator(f'#assignment [name={name}]').fill(value)
        if predecessor:
            page.locator('#predecessorAssignmentId').fill(predecessor)
        page.locator('#assignment button').click()
        expect(page.locator('#message')).to_contain_text('recorded')
    rows = {r['assignment']['assignmentId']:r for r in field.inspect(owner)['items']}
    assert len(rows) == 9
    for phase in ['repair','restore']:
        assert rows['CLAIM-'+phase]['state'] == 'cancelled'
        assert rows['CLAIM-'+phase]['lifecycle']['replacementAssignmentId'] == 'REPLACEMENT-'+phase
        assert rows['REPLACEMENT-'+phase]['lifecycle']['replacesAssignmentId'] == 'CLAIM-'+phase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--field-db', required=True, type=Path)
    parser.add_argument('--viewer-dir', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    before_source = {**source_hashes(args.db), **source_hashes(args.field_db)}
    target = args.out/'world.sqlite'
    copy_database(args.db, target)
    copy_database(args.field_db, args.out/'field.sqlite')
    world = World(target)
    owner = field.FieldExecution(world, args.out/'field.sqlite')
    with world.db() as db:
        meta = world.metadata(db)
        max_event = db.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]
    with owner.db() as db:
        old_events = [dict(r) for r in db.execute('SELECT * FROM events ORDER BY sequence')]
        old_messages = [dict(r) for r in db.execute('SELECT * FROM field_outbox ORDER BY sequence')]
        old_bindings = [dict(r) for r in db.execute('SELECT * FROM field_main_phases ORDER BY assignment')]
        old_assignments = {r['id']:{k:r[k] for k in ('payload','checksum','accepted_event','result','executed_day')}
                           for r in db.execute('SELECT * FROM field_assignments')}
    original_map, old_history = WorldMap(world).snapshot(), history(world, meta['through'], max_event)
    original_rows = {r['assignment']['assignmentId']:r for r in field.inspect(owner)['items']}
    assert original_rows['CLAIM-isolate']['result']['outcome'] == 'not_attempted'
    assert all(original_rows[key]['state'] == 'accepted' for key in ['CLAIM-repair','CLAIM-restore'])
    edge = original_rows['CLAIM-isolate']['assignment']['assetId']
    active_fault = water_mains.inspect(world, edge)['selected']['active']['id']
    start = date.fromisoformat(meta['through'])
    def day(n):
        return (start+timedelta(days=n)).isoformat()
    children, errors, external, lost = [], [], [], []
    from playwright.sync_api import expect, sync_playwright
    try:
        child = Child(args, target, 'interrupted-server', interrupt=True)
        children.append(child)
        rejected(child.base, cancel_payload(owner, 'reject-original-completed', ['ACTUAL-isolate']))
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width':1440,'height':1000})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda req: external.append(req.url) if not req.url.startswith('http://127.0.0.1:') else None)
                page.goto(child.base+'/field-execution')
                perform_ui_changes(page, child, owner, edge, day, expect, lost)
                page.goto(child.base+'/cruise')
                expect(page.locator('#start')).to_be_enabled()
                page.locator('#targetDate').fill(day(3))
                page.locator('#reason').fill('Fresh local replacement chain after explicit cancellation')
                page.locator('#start').click()
                wait_for(lambda: child.process.poll() is not None, 'Replacement isolation interruption did not occur')
                assert child.process.returncode == 86
                assert water_mains.inspect(world, edge)['selected']['active']['status'] == 'isolated'
                disabled = DisabledChild(args, target, 'guard-server', port=child.port, worker_disabled=True)
                children.append(disabled)
                rejected(disabled.base, cancel_payload(owner, 'reject-crash-committed',
                                                       ['REPLACEMENT-isolate','REPLACEMENT-repair','REPLACEMENT-restore']))
                assert water_mains.inspect(world, edge)['selected']['active']['id'] == active_fault
                disabled.close()
                child = Child(args, target, 'restarted-server', port=child.port)
                children.append(child)
                wait_for(lambda: (s := request(child.base))['status'] == 'completed' and s['through'] == day(3),
                         'Replacement chain did not complete')
                rows = {r['assignment']['assignmentId']:r for r in field.inspect(owner)['items']}
                assert all(rows[key]['state'] == 'cancelled' for key in ['CLAIM-repair','CLAIM-restore'])
                for n, phase in enumerate(['isolate','repair','restore']):
                    row = rows['REPLACEMENT-'+phase]
                    assert row['state'] == 'executed' and row['result']['outcome'] == 'completed'
                    assert row['result']['effectiveDate'] == day(n)
                assert water_mains.inspect(world, edge)['selected']['active'] is None
                page.goto(child.base+'/field-execution')
                expect(page.locator('#history')).to_contain_text('REPLACEMENT-restore')
                for width,height in [(1440,1000),(1024,768)]:
                    page.set_viewport_size({'width':width,'height':height})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(args.out/f'cancelled-and-replaced-{width}.png'), full_page=True)
                assert not errors, errors
                assert not external, external
            finally:
                browser.close()
        with world.db() as db:
            physical = [json.loads(r[0]) for r in db.execute("SELECT payload FROM events WHERE type='WaterMainPhysicalAction' AND sequence>?", (max_event,))]
            assert len(physical) == 3 and all(p['faultId'] == active_fault for p in physical)
            assert sorted(p['action'] for p in physical) == ['isolate','repair','restore']
        with owner.db() as db:
            assert [dict(r) for r in db.execute('SELECT * FROM events WHERE sequence<=? ORDER BY sequence',
                    (old_events[-1]['sequence'],))] == old_events
            assert [dict(r) for r in db.execute('SELECT * FROM field_outbox WHERE sequence<=? ORDER BY sequence',
                    (old_messages[-1]['sequence'],))] == old_messages
            for binding in old_bindings:
                assert dict(db.execute('SELECT * FROM field_main_phases WHERE assignment=?', (binding['assignment'],)).fetchone()) == binding
            for identity, original in old_assignments.items():
                row = db.execute('SELECT * FROM field_assignments WHERE id=?', (identity,)).fetchone()
                assert {key:row[key] for key in original} == original
        assert source_hashes(args.db) | source_hashes(args.field_db) == before_source
        assert history(world, meta['through'], max_event) == old_history
        assert WorldMap(world).snapshot() == original_map
        evidence = {'passed':True, 'premises':len(original_map['premises']), 'from':day(0), 'through':day(3),
                    'explicitlyCancelledPhases':2, 'replacementVisits':3, 'lostCancelReplyReloadRetry':True,
                    'completedCancellationRejected':True, 'postPhysicalCrashCancellationRejected':True,
                    'originalCapacityDateRecovered':True, 'physicalEventsPerReplacementPhase':1,
                    'oldBindingsAndMessagesPreserved':True, 'bothSourceHashesUnchanged':True,
                    'historicalEventsAndObservationsPreserved':True, 'savedMapPreserved':True,
                    'browserErrors':errors, 'viewports':[1440,1024], 'actualEnterpriseAdapterTested':False,
                    'childPids':[c.process.pid for c in children]}
        (args.out/'acceptance.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(evidence))
    finally:
        for child in reversed(children):
            child.close()
        assert all(c.process.poll() is not None for c in children)


if __name__ == '__main__':
    main()

