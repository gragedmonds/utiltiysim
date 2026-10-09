"""Cross-owner storm recovery evidence, without claiming enterprise acceptance."""
import json
from decimal import Decimal

import pytest
from test_world_contacts import command as contact_command
from test_world_field_execution import command as field_command
from test_world_field_execution import reports
from test_world_field_reporting import command as report_command
from test_world_network_faults import command as network_command
from test_world_storms import command as storm_command
from test_world_v2 import snapshot

from utilsim.world import World, contacts, network_faults, storms
from utilsim.world import field_execution as field
from utilsim.world import field_reporting as reporting


def storm_outage(tmp_path, name, edges=1):
    """A tiny explicit serial network; no faults or observations are inserted directly."""
    source = snapshot()
    source['networks'] = {}
    for utility in ('electric', 'gas'):
        source['networks'][utility] = {
            'sourceIds': ['n0'], 'nodes': [{'id': f'n{i}'} for i in range(edges+1)],
            'edges': [{'id': f'edge-{i}', 'from': f'n{i}', 'to': f'n{i+1}',
                       'kind': 'supply' if i == 0 else 'distribution', 'enabled': True} for i in range(edges)]}
        next(p for p in source['servicePoints'] if p['commodity'] == utility)['networkNodeId'] = f'n{edges}'
    w = World(tmp_path/name/'world.sqlite')
    w.initialize(source, 'STORM-RECOVERY', settings={'annual_meter_failure': 0, 'annual_meter_drift': 0})
    contacts.command(w, contact_command(w, repeatAfterDays=1))
    # Probability 1 is an explicit worst-case test fixture, not a forecast that a
    # particular storm multiplier necessarily produces every fault.
    network_faults.command(w, network_command(w, 'baseline', 'configure', environmentId='STORM-RECOVERY'))
    storms.command(w, storm_command(w, endDate='2026-01-02'))
    w.advance('2026-01-02')
    network_faults.command(w, network_command(w, 'stop-new-failures', 'configure', environmentId='STORM-RECOVERY',
                                              expectedRevision=1, annualProbability=0))
    assert contacts.ready(w)['items'] == []  # Observation and contact availability differ.
    assert len(contacts.inspect(w)['items']) == 2
    assert len(storms.inspect(w)['history']) == 1
    with w.db() as db:
        cause = db.execute("SELECT id FROM events WHERE type='InfrastructureHazardDay'").fetchone()[0]
        faults = db.execute('SELECT id,cause FROM network_faults').fetchall()
        assert len(faults) == edges*2 and all(f['cause'] == cause for f in faults)
    return w


def conservation(w):
    with w.db() as db:
        for row in db.execute('SELECT * FROM network_fault_effects'):
            served = Decimal(db.execute('SELECT quantity FROM truth WHERE asset=? AND day=?',
                                        (row['asset'], row['day'])).fetchone()[0])
            assert Decimal(row['demand_quantity']) == served+Decimal(row['unserved_quantity'])
            assert Decimal(row['unserved_quantity']) > 0


@pytest.mark.parametrize('work_mode,actual,claim,still_out', [
    ('perform', 'completed', 'not_found', False),
    ('inspect-only', 'not_attempted', 'completed', True),
])
def test_storm_physics_contact_delay_and_crew_claims_are_separate(tmp_path, work_mode, actual, claim, still_out):
    w = storm_outage(tmp_path, work_mode)
    before = w.export_v2('2026-01-01', '2026-01-02')
    f = field.FieldExecution(w, tmp_path/work_mode/'field.sqlite')
    field.command(f, field_command(f, 'crew', 'configure-crew', skills=['electric']))
    accepted = field.command(f, field_command(f, operation='restore-electric-supply', assetId='edge-0'))
    reporting.command(f, report_command(f, workMode=work_mode, reportMode='manual'))
    executed = field.run_due(f)[0]
    assert executed['outcome'] == actual and executed['reportId'] is None
    assert reports(f) == []  # Missing report cannot negate completed physical work.
    assert bool(network_faults.inspect(w, 'electric', 'edge-0')['selected']['active']) == still_out
    assert network_faults.inspect(w, 'gas', 'edge-0')['selected']['active']
    with w.db() as db:
        repairs = db.execute("SELECT payload FROM events WHERE type='PhysicalNetworkRestored'").fetchall()
        assert len(repairs) == (0 if still_out else 1)
        if repairs:
            assert json.loads(repairs[0][0])['authorizationEventId'] == accepted['eventId']
    w = World(w.path)
    f = field.FieldExecution(w, f.path)
    reporting.command(f, report_command(f, 'late-claim', 'submit', outcome=claim))
    assert reports(f)[0]['data']['outcome'] == claim
    assert bool(network_faults.inspect(w, 'electric', 'edge-0')['selected']['active']) == still_out
    assert reporting.inspect(f)['items'][0]['actualOutcome'] == actual
    w.advance('2026-01-03')
    assert bool(network_faults.inspect(w, 'electric', 'edge-0')['selected']['active']) == still_out
    assert len(storms.inspect(w)['history']) == 1  # End of storm did not repair gas/inspection-only work.
    assert w.export_v2('2026-01-01', '2026-01-02') == before
    conservation(w)
    ready = contacts.ready(w)['items']
    assert len(ready) == 2 and {r['intent']['commodity'] for r in ready} == {'electric', 'gas'}
    # A received observation is not knowledge of the hidden storm or repair.
    encoded = json.dumps([r['intent'] for r in ready])
    assert all(hidden not in encoded for hidden in ('stormId', 'faultId', 'scheduleEventId', 'authorizationEventId', 'sourceTable'))
    assert contacts.inspect(w)['counts'] == {'pending': 3 if not still_out else 4}
    assert all(m['state'] == 'pending' for m in field.inspect(f)['items'][0]['messages'])
    # No enterprise receiver is fabricated or implicitly acknowledged by these tests.


def crew_backlog(tmp_path, name, crew_count):
    w = storm_outage(tmp_path, name, edges=7)
    f = field.FieldExecution(w, tmp_path/name/'field.sqlite')
    for number in range(crew_count):
        field.command(f, field_command(f, f'crew-{number}', 'configure-crew', crewId=f'crew-{number}',
                                       skills=['electric', 'gas'], dailyCapacity=1))
    for number in range(14):
        utility = 'electric' if number < 7 else 'gas'
        field.command(f, field_command(f, f'accept-{number:02}', assignmentId=f'A{number:02}',
                                       orderId=f'ORDER-{number:02}', assetId=f'edge-{number % 7}',
                                       crewId=f'crew-{number % crew_count}', operation=f'restore-{utility}-supply',
                                       reportDelayDays=2))
    return w, f


def run_recovery(w, f, restart=False):
    backlog, completions = [], []
    for through in ('2026-01-03', '2026-01-04', '2026-01-05'):
        done = field.run_due(f)
        assert all(r['outcome'] == 'completed' for r in done)
        completions.append(len(done))
        assert field.run_due(f) == []  # No repeated polling can create extra daily slots.
        backlog.append(sum(a['state'] == 'accepted' for a in field.inspect(f)['items']))
        w.advance(through)
        if restart:
            w = World(w.path)
            f = field.FieldExecution(w, f.path)
    conservation(w)
    with w.db() as db:
        physical = [dict(r) for r in db.execute('SELECT * FROM events ORDER BY sequence')]
        unserved = {utility: sum(Decimal(r[0]) for r in db.execute(
            'SELECT unserved_quantity FROM network_fault_effects WHERE asset=?', (utility,)))
                    for utility in ('electric', 'gas')}
    assert network_faults.inspect(w)['interruptedServices'] == network_faults.inspect(w, 'gas')['interruptedServices'] == 0
    assert all(m['state'] == 'pending' for a in field.inspect(f)['items'] for m in a['messages'])
    return {'backlog': backlog, 'completions': completions, 'events': physical,
            'unserved': unserved, 'export': w.export_v2('2026-01-01', '2026-01-05'),
            'contacts': contacts.inspect(w), 'field': field.inspect(f)}


def test_seven_vs_five_daily_crews_changes_real_storm_backlog_and_restart_is_identical(tmp_path):
    seven = run_recovery(*crew_backlog(tmp_path, 'seven', 7))
    reopened = run_recovery(*crew_backlog(tmp_path, 'reopened', 7), restart=True)
    five = run_recovery(*crew_backlog(tmp_path, 'five', 5))
    assert seven == reopened
    assert seven['completions'] == [7, 7, 0]
    assert seven['backlog'] == [7, 0, 0]
    assert five['completions'] == [5, 5, 4]
    assert five['backlog'] == [9, 4, 0]
    assert all(five['unserved'][utility] >= seven['unserved'][utility] for utility in ('electric', 'gas'))
    assert any(five['unserved'][utility] > seven['unserved'][utility] for utility in ('electric', 'gas'))
    # kWh and gas m3 remain separate; this is not a business-loss metric or SCN sign-off.
