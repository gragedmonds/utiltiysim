"""The offline utility remains interactive across processing checkpoints."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from utilsim.worker.jobs import LocalJobs
from utilsim.worker.server import create_app
from utilsim.worker.workspace import actions_for, combine, qualify


@pytest.fixture(scope='module')
def workspace(tmp_path_factory):
    store = tmp_path_factory.mktemp('interactive-utility')
    jobs = LocalJobs(store)
    with TestClient(create_app(jobs, 'test-token'), base_url='http://127.0.0.1') as client:
        auth = {'Authorization': 'Bearer test-token'}
        payload = {'modelId': 'interactive', 'chunkSize': 40, 'proposal': {
            'execution': 'local', 'totalHomes': 80, 'preset': 'village', 'name': 'Interactive test',
            'summary': 'One utility', 'townOverrides': {'town': {'houses': 40}},
            'settings': {'process': {'analysts': 0}}, 'asOf': '2026-06-30'}}
        response = client.post('/local/jobs', headers=auth, json=payload)
        assert response.status_code == 200, response.text
        job = response.json()
        deadline = time.monotonic() + 120
        while jobs.find(job['jobId'])['status'] not in ('complete', 'failed') and time.monotonic() < deadline:
            time.sleep(.1)
        done = jobs.find(job['jobId'])
        assert done['status'] == 'complete', done.get('error')
        yield client, auth, done, payload, jobs


def query(workspace, path, **params):
    client, auth, job, _, _ = workspace
    response = client.post('/local/jobs/' + job['jobId'] + '/query', headers=auth,
                           json={'path': path, 'params': params})
    assert response.status_code == 200, response.text
    return response.json()


def test_one_utility_has_distinct_records_and_global_pagination(workspace):
    table = query(workspace, '/m2c/table', table='premises', pageSize=500)
    assert table['total'] >= 80
    ids = [r[0] for r in table['rows']]
    assert len(set(ids)) == len(ids)
    assert any(x.startswith('district-0001::') for x in ids)
    assert any(x.startswith('district-0002::') for x in ids)
    queue = query(workspace, '/process/queue', status='all', pageSize=500)
    assert queue['total'] > 2
    first = query(workspace, '/process/queue', status='all', pageSize=2)
    second = query(workspace, '/process/queue', status='all', pageSize=2, page=2)
    assert first['rows'] + second['rows'] == queue['rows'][:4]
    row = first['rows'][0]
    assert '::' in row['caseId']
    detail = query(workspace, '/m2c/case', caseId=row['caseId'])
    assert detail['caseId'] == row['caseId']


def test_decisions_replay_only_on_their_record_and_persist_in_revisions(workspace):
    client, auth, job, payload, _ = workspace
    queue = query(workspace, '/process/queue', status='all', pageSize=500)
    case = queue['rows'][0]['caseId']
    action = {'type': 'note', 'caseId': case, 'day': '2026-06-30', 'text': 'Offline investigation'}
    detail = query(workspace, '/m2c/case', caseId=case, actions=[action])
    assert 'Offline investigation' in str(detail)
    clean = query(workspace, '/m2c/case', caseId=case, actions=[])
    assert 'Offline investigation' not in str(clean)
    saved = client.post('/local/jobs', headers=auth, json={**payload, 'actions': [action]})
    assert saved.status_code == 200, saved.text
    assert saved.json()['recipe']['request']['actionsByDistrict'] == {
        case.split('::')[0]: [{**action, 'caseId': case.split('::')[1]}]}
    assert client.post('/local/jobs/' + job['jobId'] + '/query', json={}).status_code == 401


def test_dated_edits_leave_earlier_results_unchanged(workspace):
    episodes = [{'id': 'EP-MIDYEAR', 'from': '2026-07-01', 'settings': {'reading': {'ami_missed_read': 1}}}]
    before = query(workspace, '/m2c/trend', asOf='2026-06-30', episodes=[])
    changed = query(workspace, '/m2c/trend', asOf='2026-06-30', episodes=episodes)
    assert before['months'] == changed['months']
    base = query(workspace, '/m2c/trend', asOf='2026-12-31', episodes=[])
    later = query(workspace, '/m2c/trend', asOf='2026-12-31', episodes=episodes)
    assert base['months'][:6] == later['months'][:6]
    assert base['months'][6:] != later['months'][6:]


def test_pooled_kpis_rates_distributions_and_local_exports(workspace):
    values = query(workspace, '/m2c/kpis')['values']
    assert values['missed_read_share'] is not None
    assert 0 <= values['missed_read_share'] <= 1
    assert values['days_to_invoice'] is not None
    summary = query(workspace, '/m2c/summary')
    assert summary['billing']['avgDaysToInvoice'] == pytest.approx(values['days_to_invoice'])
    for path in ('/m2c/contact', '/m2c/fieldwork', '/vee/scorecard'):
        result = query(workspace, path)
        assert '_pool' not in str(result) and '_samples' not in str(result)
    graph = query(workspace, '/process/graph', month=3)
    nodes = {node['id'] for node in graph['nodes']}
    assert len(nodes) == len(graph['nodes'])
    assert all(edge['from'] in nodes and edge['to'] in nodes for edge in graph['edges'])
    assert all('::' in node['seriesKey'] for node in graph['nodes'])
    costs = query(workspace, '/process/costs')
    assert all(row['perCase'] == pytest.approx((row['activityCost'] + row['carry']) / row['count'], abs=.00501) for row in costs['types'])
    trend = query(workspace, '/m2c/trend')
    for month in trend['months']:
        if month['reads']:
            reads = month['reads']
            assert reads['missedPct'] == pytest.approx(reads['missed'] / reads['scheduled'] if reads['scheduled'] else 0)
    client, auth, job, _, _ = workspace
    response = client.post('/local/jobs/' + job['jobId'] + '/link', headers=auth, json={'table': 'premises'})
    assert response.status_code == 200, response.text
    link = response.json()
    data = client.get(link['paths']['json'].replace('../', '/')).json()
    assert len(data['rows']) == link['total'] and data['next'] is None
    assert len({row['premiseId'] for row in data['rows']}) == link['total']
    csv = client.get(link['paths']['csv'].replace('../', '/'))
    assert csv.status_code == 200 and csv.headers['X-Total-Rows'] == str(link['total'])


def test_new_large_jobs_use_fifty_checkpoints_for_half_a_million_homes():
    from utilsim.batch import district_sizes
    from utilsim.worker.prepare import prepare_job
    job = prepare_job({'modelId': 'large', 'proposal': {'execution': 'local', 'totalHomes': 500000,
                      'name': 'Large', 'summary': 'One utility', 'preset': 'small_town'}}, 1)
    assert job['recipe']['chunkSize'] == 10000
    assert len(district_sizes(500000, job['recipe']['chunkSize'])) == 50


def test_new_billing_measures_upgrade_old_archives_and_pool_counts(workspace):
    import gzip

    import orjson

    _, _, job, _, jobs = workspace
    keys = ['active_services', 'estimated_bill_share', 'active_meterless_accounts']
    originals, statistics = [], []
    try:
        for part in job['result']['districts']:
            path = jobs.store / 'runs' / part['runKey'] / 'utility-views.json.gz'
            original = path.read_bytes()
            originals.append((path, original))
            saved = orjson.loads(gzip.decompress(original))
            statistics.append(saved['/m2c/kpis']['_statistics'])
            # Simulate an installed archive from before this catalogue update.
            saved['/m2c/kpis']['values'] = {k: v for k, v in saved['/m2c/kpis']['values'].items() if k not in keys}
            path.write_bytes(gzip.compress(orjson.dumps(saved)))
        values = query(workspace, '/m2c/kpis', kpis=keys)['values']
        assert values['active_services'] == sum(s['active_services'][0] for s in statistics)
        assert values['active_meterless_accounts'] == sum(s['active_meterless_accounts'][0] for s in statistics)
        numerator = sum(s['estimated_bill_share'][0] for s in statistics)
        denominator = sum(s['estimated_bill_share'][1] for s in statistics)
        assert values['estimated_bill_share'] == pytest.approx(numerator / denominator)
    finally:
        for path, original in originals:
            path.write_bytes(original)


def test_monthly_billing_audit_filters_combined_amounts_and_projects_after_paging(workspace):
    result = query(workspace, '/m2c/table', table='billingAudit', pageSize=12)
    assert result['total'] == result['rowsInTable'] == 6
    assert [row[0] for row in result['rows']] == list(range(1, 7))
    index = next(i for i, c in enumerate(result['columns']) if c['key'] == 'invoicedAmount')
    amount = result['rows'][1][index]
    selected = query(workspace, '/m2c/table', table='billingAudit', columns=['invoicedAmount'],
                     filters={'invoicedAmount': f'{amount - .01}..{amount + .01}'}, pageSize=12)
    assert selected['rowsInTable'] == 6
    assert selected['rows'] == [[r[index]] for r in result['rows'] if abs(r[index] - amount) <= .01]


def test_record_namespace_and_ratios():
    row = qualify({'caseId': 'CASE-1', 'accountId': 'CA-1', 'id': 'EP-1'}, 'district-0001')
    assert row == {'caseId': 'district-0001::CASE-1', 'accountId': 'district-0001::CA-1', 'id': 'EP-1'}
    assert actions_for([{'caseId': row['caseId']}], 'district-0002') == []
    pooled = combine([{'truePositives': 1, 'falsePositives': 1, 'falseNegatives': 0},
                      {'truePositives': 9, 'falsePositives': 0, 'falseNegatives': 5}])
    assert pooled['precision'] == 10 / 11
    assert pooled['recall'] == 10 / 15


def test_saved_tables_and_queues_match_live_selection_without_replaying(workspace, monkeypatch):
    import orjson

    from utilsim.worker.workspace import UtilityWorkspace
    _, _, job, _, jobs = workspace
    live = UtilityWorkspace(jobs)
    selections = [('/m2c/table', {'table': 'premises', 'sort': 'address', 'desc': True, 'search': 'a'}),
                  ('/m2c/table', {'table': 'cases', 'sort': 'createdAt', 'filters': {'commodity': 'water'}}),
                  ('/process/queue', {'status': 'open', 'sort': 'created'}),
                  ('/process/queue', {'status': 'all', 'sort': 'confidence', 'commodity': 'electric'}),
                  ('/process/queue', {'status': 'resolved', 'sort': 'impact'})]
    expected = []
    for path, params in selections:
        outputs = []
        for part in job['result']['districts']:
            inputs = orjson.loads((jobs.store / 'runs' / part['runKey'] / 'inputs.json').read_bytes())
            result = live.call(path, {**inputs, **params, 'town': 'local-run-' + part['runKey'], 'pageSize': 100})
            result = qualify(result, part['id'])
            if path == '/m2c/table':
                for row in result['rows']:
                    for i, col in enumerate(result['columns']):
                        if col['kind'] == 'id' and row[i]:
                            row[i] = part['id'] + '::' + row[i]
            outputs.append(result)
        expected.append(live.page(outputs, path, params, 2, 3))
    def unexpected_replay(*args):
        pytest.fail('An unchanged archived selection replayed the engine.')
    monkeypatch.setattr(UtilityWorkspace, 'call', unexpected_replay)
    for (path, params), want in zip(selections, expected, strict=True):
        got = query(workspace, path, **params, page=2, pageSize=3)
        assert got['total'] == want['total']
        assert got['rows'] == want['rows']
    projected = query(workspace, '/m2c/table', table='premises', sort='address', desc=True, search='a',
                      columns=['premiseId'], page=2, pageSize=3)
    assert projected['rows'] == [[r[0]] for r in expected[0]['rows']]
