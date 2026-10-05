"""The dependency atlas follows the engine catalogues and ships with offline readers."""
import re
from pathlib import Path

import orjson
from fastapi.testclient import TestClient

from api.app import app
from utilsim.config.dependencies import KPI_DATA, dependency_graph
from utilsim.config.dependency_explanations import FLOW_RULES, KPI_RULES
from utilsim.config.impact import IMPACT
from utilsim.m2c.kpis import KPIS
from utilsim.ops.settings_schema import settings_schema

ROOT = Path(__file__).resolve().parents[1]


def reachable(graph, source, conditional=True):
    found = {source}
    queue = [source]
    for key in queue:
        for e in graph['edges']:
            if e['source'] != key or (not conditional and e['kind'] == 'conditional') or e['target'] in found:
                continue
            found.add(e['target'])
            queue.append(e['target'])
    return found - {source}


def test_map_covers_settings_nested_parameters_and_every_kpi():
    graph = dependency_graph()
    nodes = {n['id']: n for n in graph['nodes']}
    assert len(nodes) == len(graph['nodes'])
    assert set(IMPACT) <= nodes.keys()
    assert {k.id for k in KPIS} == set(KPI_DATA)
    assert {'kpi:' + k.id for k in KPIS} <= nodes.keys()
    assert 'field.crew_meter.per_1000_premises' in nodes
    assert 'contact.high_bill.handle_min' in nodes
    for group, prop in settings_schema()['properties'].items():
        for key in prop['properties']:
            assert 'ops.' + (key if prop.get('x-flat') else group + '.' + key) in nodes
    for edge in graph['edges']:
        assert edge['source'] in nodes and edge['target'] in nodes
        assert edge['source'] != edge['target']
        assert edge['reference']
        if edge['kind'] == 'conditional':
            assert edge['note']
    for node in graph['nodes']:
        assert (ROOT / node['reference'].split(' · ')[0]).is_file(), node['id']


def test_kpi_influences_and_definition_windows_are_preserved_not_invented_from_related():
    graph = dependency_graph()
    for kpi in KPIS:
        incoming = [e for e in graph['edges'] if e['target'] == 'kpi:' + kpi.id]
        assert {(e['source'], e['direction']) for e in incoming if e['kind'] == 'influence'} == set(kpi.settings)
        assert {e['source'] for e in incoming if e['kind'] == 'definition'} == set(kpi.thresholds)
    assert not any(e['source'].startswith('kpi:') for e in graph['edges'])
    assert reachable(graph, 'kpi.on_time_bill_days') == {'kpi:bills_on_time'}


def test_display_and_conditional_operations_do_not_acquire_false_annual_dependencies():
    graph = dependency_graph()
    for path, (reach, _) in IMPACT.items():
        if reach == 'display':
            assert not any(n.startswith('kpi:') for n in reachable(graph, path)), path
    assert 'kpi:customer_minutes_lost' not in reachable(graph, 'electric.primary_kv', conditional=False)
    assert 'kpi:customer_minutes_lost' in reachable(graph, 'electric.primary_kv', conditional=True)
    assert 'kpi:case_backlog' in reachable(graph, 'process.analysts')
    assert 'engine:usage' in reachable(graph, 'water.lpcd')
    assert 'engine:usage' not in reachable(graph, 'electric.kva_ev', conditional=False)
    assert 'kpi:customer_minutes_lost' not in reachable(graph, 'ops.waterCrews', conditional=False)
    assert 'kpi:customer_minutes_lost' in reachable(graph, 'ops.waterCrews')


def test_prices_and_measurement_targets_do_not_change_events():
    graph = dependency_graph()
    for path in ('contact.agent_cost_per_hour', 'contact.self_serve_cost', 'field.crew_meter.cost_per_hour',
                 'field.crew_meter.overtime_factor', 'field.corrective_exchange.materials', 'reading.read_cost_ami'):
        downstream = reachable(graph, path)
        cost = 'contact_costs' if path.startswith('contact.') else 'field_costs' if path.startswith('field.') else 'costs'
        assert 'engine:' + cost in downstream
        assert 'kpi:carry_per_account' not in downstream
        assert not downstream & {'engine:contact', 'engine:field', 'engine:reading', 'engine:review'}, path
    assert reachable(graph, 'contact.service_target_s') == {'kpi:contact_service_level'}
    assert reachable(graph, 'ops.gasResponseTargetMinutes') == {'engine:day_metrics'}
    assert 'kpi:cost_per_account' not in reachable(graph, 'process.carry_rate_per_day')


def test_api_and_bundled_offline_graph_are_identical_and_all_pages_include_the_entry(monkeypatch):
    import api._ops
    monkeypatch.setattr(api._ops, 'load_snapshot', lambda *_: (_ for _ in ()).throw(AssertionError('No simulation required')))
    result = TestClient(app).get('/api/dependencies')
    assert result.status_code == 200
    bundled = ROOT / 'packages/town-viewer/dist/dependency-graph.json'
    assert result.json() == orjson.loads(bundled.read_bytes()) == dependency_graph()
    for path in (ROOT / 'packages/town-viewer/dist').glob('*.html'):
        assert 'src="./dependencies.js"' in path.read_text(encoding='utf-8'), path.name


def test_every_link_has_grounded_explanation_and_known_setting_names():
    graph = dependency_graph()
    nodes = {n['id']: n for n in graph['nodes']}
    engine_pairs = set()
    for edge in graph['edges']:
        x = edge['explanation']
        assert x['summary'] and x['basis'] and (x['steps'] or x['formula']), edge
        assert x['references'], edge
        for ref in x['references']:
            assert (ROOT / ref.split(' · ')[0]).is_file(), ref
        prose = str({k: v for k, v in x.items() if k != 'references'})
        for key in re.findall(r'\b(?:kpi|process|reading|contact|billing|customers_billing)\.[a-z_0-9]+(?:\.[a-z_0-9]+)*', prose):
            assert key in nodes, (key, edge)
        if edge['source'].startswith('engine:') and edge['target'].startswith('engine:'):
            engine_pairs.add((edge['source'][7:], edge['target'][7:]))
        if edge['kind'] == 'influence':
            assert 'Indirect influence' in x['basis']
            assert any('not a one-to-one' in c for c in x['conditions'])
    assert engine_pairs == set(FLOW_RULES)
    assert set(KPI_RULES) == {k.id for k in KPIS}


def test_schedule_explanations_distinguish_attempt_release_and_invoice_creation():
    edges = {(e['source'], e['target']): e['explanation'] for e in dependency_graph()['edges']}
    reading = edges['engine:schedule', 'engine:reading']
    bills = edges['engine:schedule', 'kpi:bills_on_time']
    invoice = edges['engine:schedule', 'kpi:days_to_invoice']
    assert 'read hour / 24' in reading['formula']
    assert 'fully issued' in bills['formula'] and 'released 11 January' in bills['example']
    assert 'planned issue' in invoice['formula'] and '6 days to issue' in invoice['example']
    assert 'floor' not in invoice['formula']
    assert any('pending cycles' in s.lower() for s in bills['steps'])
    assert edges['engine:accounts', 'kpi:customer_minutes_lost']['summary'].startswith('Supplies the account-count')
    # Print lag now changes the customer-facing invoice issue measure.
    lag = edges['billing.print_lag_days', 'kpi:days_to_invoice']
    assert any('includes that shift' in s for s in lag['steps'])
