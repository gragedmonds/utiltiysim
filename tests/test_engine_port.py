"""The app opens the same storage folder at the same address every start: the browser keeps the simulation list
per address, so a fresh port each launch would show an empty Studio."""
import json
import socket

from utilsim.worker.server import stable_port


def test_the_folder_keeps_its_address(tmp_path):
    saved = tmp_path / 'engine-port.json'
    with socket.socket() as first:
        port = stable_port(tmp_path, first)
        assert 1024 <= port <= 65535 and json.loads(saved.read_text()) == {'port': port}
    with socket.socket() as again:
        assert stable_port(tmp_path, again) == port, 'free again, so the same address'
    with socket.socket() as busy, socket.socket() as moved:
        busy.bind(('127.0.0.1', port))
        busy.listen()
        other = stable_port(tmp_path, moved)
        assert other != port and json.loads(saved.read_text()) == {'port': other}, 'taken, so a new one, remembered'
    with socket.socket() as explicit:
        assert stable_port(tmp_path, explicit, other) == other
    saved.write_text('not json')
    with socket.socket() as recovered:
        chosen = stable_port(tmp_path, recovered)
        assert json.loads(saved.read_text()) == {'port': chosen}
