"""Service Mode backend namespace wrapper and port relay, without firmware or root."""
import importlib.util
import os
from pathlib import Path
import socket
import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Linux runtime worker')
ROOT = Path(__file__).resolve().parents[1] / 'infotainment_lab'
spec = importlib.util.spec_from_file_location('service_ui_netns', ROOT / 'runtime/service-ui-netns.py')
netns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(netns)
if os.name != 'nt':
    sys.path.insert(0, str(ROOT))
    import supervisor


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def test_relay_carries_a_connection_from_the_host_port_through_the_socket(tmp_path):
    backend = socket.socket()
    backend.bind(('127.0.0.1', 0))
    backend.listen()

    def echo():
        conn, _ = backend.accept()
        with conn:
            conn.sendall(b'backend:' + conn.recv(100))
    threading.Thread(target=echo, daemon=True).start()

    path = tmp_path / 'service-ui.sock'
    # Namespace side: Unix socket to the backend's port. Host side: the browser's port to the socket.
    inside = netns.unix_listener(path)
    threading.Thread(target=netns.serve, args=(inside, netns.connect_tcp(backend.getsockname()[1])), daemon=True).start()
    host_port = free_port()
    outside = netns.tcp_listener(host_port)
    threading.Thread(target=netns.serve, args=(outside, netns.connect_unix(path)), daemon=True).start()

    with socket.create_connection(('127.0.0.1', host_port), timeout=5) as client:
        client.sendall(b'GET /')
        assert client.recv(100) == b'backend:GET /'
    assert oct(path.stat().st_mode & 0o777) == '0o600'
    backend.close()


def test_relay_closes_the_client_when_the_backend_is_down(tmp_path):
    path = tmp_path / 'missing.sock'
    host_port = free_port()
    threading.Thread(target=netns.serve, args=(netns.tcp_listener(host_port), netns.connect_unix(path)), daemon=True).start()
    with socket.create_connection(('127.0.0.1', host_port), timeout=5) as client:
        assert client.recv(10) == b''


def test_backend_runs_in_its_own_namespace_as_the_current_user(tmp_path):
    backend, relay, engine = supervisor.service_ui_commands(tmp_path / 'odin', tmp_path / 'state')
    assert backend[:4] == ['unshare', '--map-current-user', '--keep-caps', '-n']
    assert backend[-2:] == ['--', tmp_path / 'odin/service-ui']
    assert backend[backend.index('ns') + 1] == relay[relay.index('host') + 1] == tmp_path / 'state/service-ui.sock'
    assert relay[-1] == '8000'
    # The namespace's engine port goes to the stand-in's socket, before the backend argv.
    assert backend[backend.index('ns') + 3] == engine[2] == tmp_path / 'state/odin-engine.sock'
    assert engine[-1] == tmp_path / 'odin'


def test_namespace_relays_the_engine_port_only_when_given_a_socket(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(netns, 'namespace', lambda path, port, argv, engine=None: started.append((argv, engine)) or 0)
    netns.main(['ns', str(tmp_path / 's.sock'), '8000', str(tmp_path / 'odin-engine.sock'), '--', 'service-ui'])
    netns.main(['ns', str(tmp_path / 's.sock'), '8000', '--', 'service-ui'])
    assert started == [(['service-ui'], tmp_path / 'odin-engine.sock'), (['service-ui'], None)]


def test_relayed_connections_have_no_idle_timeout():
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen()
    upstream = netns.connect_tcp(server.getsockname()[1])()
    try:
        assert upstream.gettimeout() is None
    finally:
        upstream.close()
        server.close()


def test_every_confined_firmware_process_has_a_local_peer_profile():
    import re
    profiles = set(re.findall(r'^profile (\S+) ', (ROOT / 'runtime/media-apparmor.profile').read_text(), re.M))
    confined = set(re.findall(r"confined\(f?[\"'](/usr/tesla/UI/bin/[^\"'{]+)", (ROOT / 'supervisor.py').read_text()))
    confined |= {'/usr/tesla/UI/bin/SpotifyServer', '/usr/tesla/UI/bin/ChromiumAdapter'}  # built from a loop
    assert '/usr/tesla/UI/bin/QtCarDvServer' in confined
    assert confined <= profiles
