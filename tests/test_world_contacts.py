import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import jsonschema
import pytest
from test_world_network_faults import command as network_command
from test_world_network_faults import world
from test_world_occupancy import schedule as occupancy_command
from test_world_sewer import command as sewer_command
from test_world_water_faults import command as leak_command
from test_world_water_mains import command as main_command
from test_world_water_mains import transition
from test_world_water_mains import world as main_world

from utilsim.world import World, contacts, network_faults, occupancy, sewer, water_faults, water_mains
from utilsim.world.server import make_server
from utilsim.world.store import stable


def command(w, identity='contact-policy', **overrides):
    with w.db() as db:
        meta = w.metadata(db)
    return {'schemaVersion': contacts.VERSION, 'commandId': identity, 'environmentId': meta['environment'],
            'worldFingerprint': meta['fingerprint'], 'actorId': 'world-admin', 'expectedRevision': 0,
            'effectiveDate': meta['through'], 'action': 'configure', 'reason': 'Contact scenario policy',
            'causalReference': 'scenario', 'active': True, 'noticeProbabilityPerDay': 1,
            'deliveryDelaySeconds': 86400, 'repeatAfterDays': 2, 'maxContacts': 3, **overrides}


def acknowledge(intent):
    return {'id': intent['id'], 'environmentId': intent['environmentId'], 'fingerprint': stable(intent),
            'status': 'accepted', 'receiptId': 'RECEIPT-'+intent['id']}


def test_delayed_awareness_filtered_contract_and_repeats(tmp_path):
    w = world(tmp_path)
    contacts.command(w, command(w))
    fault = network_faults.command(w, network_command(w))
    w.advance('2026-01-02')
    view = contacts.inspect(w)
    assert len(view['items']) == 1 and not view['items'][0]['available']
    assert contacts.ready(w)['items'] == []
    assert contacts.relay(w, lambda _: pytest.fail('Future contact delivered'))['accepted'] == 0
    w.advance('2026-01-04')
    first = contacts.ready(w)['items'][0]['intent']
    assert first['noticedAt'] == first['observedAt'] == '2026-01-02T00:00:00Z'
    assert first['availableAt'] == '2026-01-03T00:00:00Z'
    assert first['attempt'] == 1 and first['previousContactId'] is None
    schema = json.loads((Path(__file__).parents[1]/'schemas/customer-contact-intent-1.schema.json').read_text())
    jsonschema.validate(first, schema, format_checker=jsonschema.FormatChecker())
    assert fault['faultId'] not in json.dumps(contacts.ready(w))
    assert all(word not in first for word in ('faultId', 'sourceTable', 'rate', 'quantity', 'policy', 'assetId'))
    point = next(a['servicePointId'] for a in w.export_v2('2026-01-01', '2026-01-02')['assets'] if a['commodity'] == 'electric')
    assert first['servicePointId'] == point
    assert contacts.relay(w, acknowledge)['accepted'] == 1
    w.advance('2026-01-12')
    all_rows = contacts.inspect(w)['items']
    assert len(all_rows) == 3  # delivered is not resolved; persistent symptoms repeat
    assert [r['intent']['attempt'] for r in all_rows] == [1, 2, 3]
    assert all_rows[1]['intent']['previousContactId'] == first['id']
    assert all_rows[2]['intent']['reason'] == 'repeat_service_problem'


@pytest.mark.parametrize('commodity', ['electric', 'gas'])
def test_recovery_stops_new_contacts_without_erasing_old_intents(tmp_path, commodity):
    w = world(tmp_path)
    contacts.command(w, command(w, deliveryDelaySeconds=864000))
    f = network_faults.command(w, network_command(w, commodity=commodity))
    w.advance('2026-01-02')
    network_faults.command(w, network_command(w, 'restore', 'restore', commodity=commodity,
                                             expectedRevision=1, faultId=f['faultId']))
    w.advance('2026-01-15')
    assert len(contacts.ready(w)['items']) == 1
    with w.db() as db:
        assert db.execute('SELECT ended_day FROM contact_episodes').fetchone()[0] == '2026-01-02'
    assert contacts.inspect(w)['counts'] == {'pending': 1}


def test_hidden_leak_missing_meter_and_vacancy_do_not_invent_contacts(tmp_path):
    w = world(tmp_path, annual_meter_failure=1)
    contacts.command(w, command(w))
    water_faults.command(w, leak_command(w, 'hidden-leak', leakM3PerHour='1'))
    w.advance('2026-01-04')
    assert not contacts.inspect(w)['items']
    occupancy.command(w, occupancy_command(w, effectiveDate='2026-01-04', occupied=False, occupants=0))
    network_faults.command(w, network_command(w))
    w.advance('2026-01-06')
    assert not contacts.inspect(w)['items']


def test_water_main_and_sewer_symptoms_remain_distinct(tmp_path):
    w = main_world(tmp_path)
    contacts.command(w, command(w, deliveryDelaySeconds=0))
    sewer.command(w, sewer_command(w))
    w.advance('2026-01-03')
    assert {r['intent']['commodity'] for r in contacts.ready(w)['items']} == {'sewer'}
    f = water_mains.command(w, main_command(w))
    transition(w, f, 'isolate')
    w.advance('2026-01-04')
    intents = [r['intent'] for r in contacts.ready(w)['items']]
    assert any(i['commodity'] == 'water' and i['condition'] == 'no_supply' for i in intents)
    assert all(i['servicePointId'].startswith('SEWER-SP-') for i in intents if i['commodity'] == 'sewer')


def test_notice_is_not_backdated_to_hidden_episode_start(tmp_path):
    w = world(tmp_path)
    contacts.command(w, command(w, noticeProbabilityPerDay=0))
    network_faults.command(w, network_command(w))
    w.advance('2026-01-05')
    assert contacts.inspect(w)['items'] == []
    contacts.command(w, command(w, 'notice-now', expectedRevision=1, deliveryDelaySeconds=0))
    w.advance('2026-01-06')
    intent = contacts.ready(w)['items'][0]['intent']
    assert intent['noticedAt'] == intent['observedAt'] == '2026-01-06T00:00:00Z'
    assert 'experiencedFrom' not in intent


def test_occupancy_change_starts_new_experience_memory(tmp_path):
    w = world(tmp_path)
    contacts.command(w, command(w, maxContacts=1, deliveryDelaySeconds=0))
    network_faults.command(w, network_command(w))
    w.advance('2026-01-02')
    occupancy.command(w, occupancy_command(w, effectiveDate='2026-01-02', occupied=True, occupants=3))
    w.advance('2026-01-03')
    items = contacts.ready(w)['items']
    assert len(items) == 2
    assert {r['intent']['attempt'] for r in items} == {1}
    assert len({r['intent']['experienceId'] for r in items}) == 2


def test_chunking_reopen_and_unchanged_physical_export(tmp_path):
    a, b, control = (world(tmp_path, name) for name in ('a', 'b', 'control'))
    for w in (a, b, control):
        network_faults.command(w, network_command(w))
    for w in (a, b):
        contacts.command(w, command(w, noticeProbabilityPerDay=.4))
    a.advance('2026-02-01')
    b.advance('2026-01-04')
    b = World(b.path)
    b.advance('2026-02-01')
    control.advance('2026-02-01')
    assert contacts.inspect(a) == contacts.inspect(b)
    assert a.export_v2('2026-01-01', '2026-02-01') == control.export_v2('2026-01-01', '2026-02-01')


def test_lost_acknowledgment_retry_and_recipient_dedup(tmp_path):
    w = world(tmp_path)
    p = command(w, deliveryDelaySeconds=0)
    assert contacts.command(w, p) == contacts.command(w, p)
    network_faults.command(w, network_command(w))
    w.advance('2026-01-02')
    recipient = {}
    def lose_ack(intent):
        recipient.setdefault(intent['id'], acknowledge(intent))
        raise ConnectionError('Sensitive provider text must not be persisted')
    assert contacts.relay(w, lose_ack)['error'] == 'ConnectionError'
    assert 'Sensitive' not in json.dumps(contacts.inspect(w))
    assert contacts.relay(World(w.path), lambda i: recipient[i['id']])['accepted'] == 1
    assert len(recipient) == 1
    assert contacts.inspect(w)['items'][0]['attempts'] == 2
    assert contacts.relay(w, acknowledge)['accepted'] == 0


def test_available_cursor_handles_shorter_later_delays(tmp_path):
    w = world(tmp_path)
    contacts.command(w, command(w, deliveryDelaySeconds=864000, repeatAfterDays=1))
    network_faults.command(w, network_command(w))
    w.advance('2026-01-02')
    contacts.command(w, command(w, 'short-delay', expectedRevision=1, deliveryDelaySeconds=0, repeatAfterDays=1))
    w.advance('2026-01-03')
    first = contacts.ready(w)['items'][0]
    assert first['intent']['attempt'] == 2
    w.advance('2026-01-15')
    later = contacts.ready(w, after=first['cursor'])['items']
    assert [r['intent']['attempt'] for r in later] == [3, 1]


def test_concurrent_relays_share_one_recipient_effect(tmp_path):
    w = world(tmp_path)
    contacts.command(w, command(w, deliveryDelaySeconds=0))
    network_faults.command(w, network_command(w))
    w.advance('2026-01-02')
    barrier, lock, recipient = threading.Barrier(2), threading.Lock(), {}
    def receive(intent):
        barrier.wait(timeout=10)
        with lock:
            return recipient.setdefault(intent['id'], acknowledge(intent))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: contacts.relay(World(w.path), receive, limit=1), range(2)))
    assert len(recipient) == 1
    assert sum(r['accepted'] for r in results) == 1
    row = contacts.inspect(w)['items'][0]
    assert row['attempts'] == 2 and row['state'] == 'accepted'


def test_supply_experience_does_not_require_meter_telemetry(tmp_path):
    w = world(tmp_path, annual_meter_failure=1)
    contacts.command(w, command(w, deliveryDelaySeconds=0))
    network_faults.command(w, network_command(w))
    w.advance('2026-01-02')
    assert contacts.ready(w)['items'][0]['intent']['condition'] == 'no_supply'
    with w.db() as db:
        row = db.execute('SELECT id,envelope FROM contact_outbox LIMIT 1').fetchone()
        corrupt = json.loads(row['envelope'])
        corrupt['condition'] = 'invented'
        db.execute('UPDATE contact_outbox SET envelope=? WHERE id=?', (json.dumps(corrupt), row['id']))
    with pytest.raises(ValueError, match='checksum'):
        contacts.ready(w)
    with pytest.raises(ValueError, match='checksum'):
        contacts.relay(w, lambda _: pytest.fail('Corrupt contact delivered'))


@pytest.mark.parametrize('change', [dict(active=1), dict(noticeProbabilityPerDay=True), dict(noticeProbabilityPerDay=float('nan')),
    dict(noticeProbabilityPerDay=2), dict(deliveryDelaySeconds=-1), dict(repeatAfterDays=0), dict(maxContacts=11),
    dict(actorId='worker'), dict(expectedRevision=True), dict(worldFingerprint='wrong'), dict(effectiveDate='2020-01-01')])
def test_rejected_policy_preserves_original_database(tmp_path, change):
    w = world(tmp_path)
    with pytest.raises(ValueError):
        contacts.command(w, command(w, **change))
    assert not list(tmp_path.glob('*.bak'))
    assert contacts.ready(w)['items'] == []


def test_concurrent_policy_retry_and_day_rollback(tmp_path, monkeypatch):
    w = world(tmp_path)
    p = command(w)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda _: contacts.command(w, p), range(2)))
    assert a == b and len(list(tmp_path.glob('*.bak'))) == 1
    with pytest.raises(ValueError, match='Conflicting'):
        contacts.command(w, {**p, 'reason': 'different'})
    network_faults.command(w, network_command(w))
    original = contacts.daily
    def fail(*args):
        original(*args)
        raise RuntimeError('interrupted')
    monkeypatch.setattr(contacts, 'daily', fail)
    with pytest.raises(RuntimeError):
        w.advance('2026-01-02')
    assert contacts.inspect(w)['items'] == []
    monkeypatch.setattr(contacts, 'daily', original)
    w.advance('2026-01-02')
    assert len(contacts.inspect(w)['items']) == 1


def test_bad_receipt_cannot_accept_or_resolve_and_pause_retains_pending(tmp_path):
    w = world(tmp_path)
    contacts.command(w, command(w, deliveryDelaySeconds=0))
    network_faults.command(w, network_command(w))
    w.advance('2026-01-02')
    assert contacts.relay(w, lambda i: {**acknowledge(i), 'environmentId': 'other'})['error'] == 'ValueError'
    assert contacts.relay(w, lambda i: {**acknowledge(i), 'fingerprint': 'wrong'})['error'] == 'ValueError'
    contacts.command(w, command(w, 'pause', active=False, expectedRevision=1))
    w.advance('2026-02-01')
    assert contacts.inspect(w)['counts'] == {'pending': 1}


def test_http_clock_and_origin_boundaries(tmp_path):
    w = world(tmp_path)
    server = make_server(w, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base+'/contacts') as r:
            assert 'Customer awareness' in r.read().decode()
        for path in ('/api/contact-intents?asOf=2099-01-01', '/api/contact-intents?after=invalid', '/api/contacts?after=-1',
                     '/api/contact-intents?limit=101', '/api/contacts?limit=0', '/api/contacts?limit=25&limit=50'):
            with pytest.raises(HTTPError) as e:
                urlopen(base+path)
            assert e.value.code == 422
        payload = json.dumps(command(w)).encode()
        with pytest.raises(HTTPError) as e:
            urlopen(Request(base+'/api/contacts', data=payload, headers={'Content-Type': 'application/json', 'Origin': 'https://evil.test'}))
        assert e.value.code == 403
        with urlopen(Request(base+'/api/contacts', data=payload, headers={'Content-Type': 'application/json'})) as r:
            assert json.load(r)['status'] == 'completed'
        network_faults.command(w, network_command(w))
        w.advance('2026-01-06')
        for path in ('/api/contacts?limit=1', '/api/contact-intents?limit=1'):
            with urlopen(base+path) as r:
                page = json.load(r)
                assert len(page['items']) == 1 and page['nextAfter'] is not None
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
