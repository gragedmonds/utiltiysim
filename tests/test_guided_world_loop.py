"""A real wizard-generated town continues through the current physical/field loop."""
from test_guided_setup import request
from test_world_cruise import command as cruise_command
from test_world_field_execution import command as field_command
from test_world_field_execution import receipt, reports
from test_world_water_faults import command as leak_command

from utilsim.worker import guided_setup
from utilsim.worker.worlds import WorldLibrary
from utilsim.world import World, cruise, field_execution, water_faults
from utilsim.world.map_view import WorldMap


def test_guided_world_fault_visit_delayed_report_and_restart(tmp_path):
    library = WorldLibrary(tmp_path)
    setup = request()
    setup['worldSettings'] = {'annual_meter_failure': 0, 'annual_meter_drift': 0}
    created = guided_setup.create(library, setup)
    world = World(library.world(created['id']).path)
    snapshot = WorldMap(world).snapshot()
    with world.db() as db:
        meta = world.metadata(db)
        asset = db.execute("SELECT id FROM assets WHERE commodity='water' AND installed<=? ORDER BY id LIMIT 1",
                           (meta['through'],)).fetchone()[0]
        environment = meta['environment']
    water_faults.command(world, leak_command(world, environmentId=environment, assetId=asset))
    world.advance('2026-02-02')
    prior_observations = world.export_v2('2026-02-01', '2026-02-02')

    field = field_execution.FieldExecution(world, tmp_path / 'field.sqlite')
    field_execution.command(field, field_command(field, 'crew', 'configure-crew'))
    field_execution.command(field, field_command(field, assetId=asset, reportDelayDays=2))
    assert field_execution.run_due(field)[0]['outcome'] == 'completed'
    assert water_faults.inspect(world, asset)['current']['active'] is None
    assert reports(field) == []  # Physical repair precedes report availability.

    cruise.command(world, cruise_command(world, field=field, targetDate='2026-02-04'), field)
    assert cruise.tick(world, field, max_days=1)['progress']['completedDays'] == 1
    world = World(world.path)
    field = field_execution.FieldExecution(world, field.path)
    assert cruise.tick(world, field, max_days=1)['status'] == 'completed'
    assert world.status()['days'] == 3
    assert len(reports(field)) == 1
    assert field_execution.relay(field, receipt)['received'] == 2
    assert field_execution.relay(field, receipt)['received'] == 0
    assert WorldMap(world).snapshot() == snapshot
    assert world.export_v2('2026-02-01', '2026-02-02') == prior_observations
    with world.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='PhysicalWaterLeakRepaired'").fetchone()[0] == 1
    assert guided_setup.create(library, setup) == created
    assert library.world(created['id']).status()['days'] == 3
    assert library.list()['total'] == 1
