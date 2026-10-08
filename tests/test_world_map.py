import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_world_v2 import world

from utilsim.world import delivery
from utilsim.world.map_view import WorldMap
from utilsim.world.server import make_server


def test_projection_preserves_snapshot_and_distinguishes_truth_from_missing_observations(tmp_path):
    w = world(tmp_path, annual_meter_failure=1, annual_meter_drift=0)
    view = WorldMap(w)
    original = view.snapshot()
    assert view.premise('P1')['lastCompletedDay'] is None
    w.advance('2026-01-03')
    before = w.export_v2('2026-01-01', '2026-01-03')
    p = view.premise('P1')
    assert p['view'] == 'administrator-truth'
    assert p['lastCompletedDay'] == '2026-01-02'
    assert len(p['assets']) == 3
    assert all(a['true_quantity'] is not None and a['observed_quantity'] is None for a in p['assets'])
    assert all(a['condition'] == 'failed' for a in p['assets'])
    w.replace_meter('replace-1', 'TEST', 'water', 'water-new', 'order-1', 'Physical replacement')
    water = next(a for a in WorldMap(w).premise('P1')['assets'] if a['commodity'] == 'water')
    assert (water['device'], water['condition'], water['observed_device']) == ('water-new', 'healthy', 'water')
    assert view.snapshot() == original
    assert w.export_v2('2026-01-01', '2026-01-03') == before
    assert 'condition' not in json.dumps(before) and 'true_quantity' not in json.dumps(before)
    with pytest.raises(ValueError, match='Unknown premise'):
        view.premise('foreign')


def test_map_http_boundaries_and_managed_clock(tmp_path):
    w = world(tmp_path, annual_meter_failure=0)
    assets = tmp_path / 'viewer'
    (assets / 'vendor').mkdir(parents=True)
    (assets / 'vendor/three.module.js').write_text('// test static asset')
    (assets / 'iso').mkdir()
    (assets / 'iso/atlas.json').write_text('{"version":"iso-atlas/1.0"}')
    (assets / 'private.json').write_text('{"secret":"must not be served"}')
    (tmp_path / 'private.json').write_text('{"secret":"must not be served"}')
    server = make_server(w, 0, assets)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:' + str(server.server_port)

    def request(path, payload=None, headers=None):
        req = Request(base + path, data=None if payload is None else json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            response = urlopen(req, timeout=3)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, response.read()

    try:
        assert request('/map')[0] == 200
        assert request('/map.js')[0] == 200
        assert request('/viewer/vendor/three.module.js')[0] == 200
        assert json.loads(request('/viewer/iso/atlas.json')[1]) == {'version': 'iso-atlas/1.0'}
        assert request('/viewer/private.json')[0] == 403
        assert request('/viewer/%2e%2e/private.json')[0] == 403
        assert request('/viewer/missing.js')[0] == 404
        assert request('/api/map/snapshot', headers={'Host': 'untrusted.example'})[0] == 403
        assert json.loads(request('/api/map/snapshot')[1]) == WorldMap(w).snapshot()
        for query in ('', '?id=', '?id=P1&id=P1', '?id=P1&extra=x', '?id=foreign'):
            assert request('/api/map/premise' + query)[0] == 422
        assert request('/api/map/premise?id=P1')[0] == 200
        state = json.loads(request('/api/map/status')[1])
        assert 'events' not in state and isinstance(state['assets'], int)
        assert not state['managedDelivery']
        assert request('/api/advance', {'environmentId': 'TEST', 'through': '2026-01-02'})[0] == 200
        delivery.configure(w, 'TEST')
        assert json.loads(request('/api/state')[1])['managedDelivery']
        assert json.loads(request('/api/map/status')[1])['managedDelivery']
        assert request('/api/advance', {'environmentId': 'TEST', 'through': '2026-01-03'})[0] == 422
        assert w.status()['through'] == '2026-01-02'
        (assets / 'vendor/three.module.js').unlink()
        assert request('/map')[0] == 503
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
