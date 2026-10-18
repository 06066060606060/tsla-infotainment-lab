"""Service Mode backend namespace wrapper and port relay, without firmware or root."""
import importlib.util
import os
from pathlib import Path
import socket
import sys
import threading
from types import SimpleNamespace

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
    backend, relay, engine, alertd = supervisor.service_ui_commands(tmp_path / 'odin', tmp_path / 'state')
    assert backend[:5] == ['unshare', '--map-current-user', '--keep-caps', '-n', '-m']
    assert backend[-2:] == ['--', tmp_path / 'odin/service-ui']
    assert backend[backend.index('ns') + 1] == relay[relay.index('host') + 1] == tmp_path / 'state/service-ui.sock'
    assert relay[-1] == '8000'
    # The namespace's engine port goes to the stand-in's socket, before the backend argv.
    assert backend[backend.index('ns') + 3] == engine[2] == tmp_path / 'state/odin-engine.sock'
    assert engine[-1] == tmp_path / 'odin'


def test_backend_is_capped_in_a_scope_bound_to_the_session(tmp_path, monkeypatch, capsys):
    cgroup = tmp_path / 'cgroup'
    cgroup.write_text('0::/user.slice/user@1000.service/app.slice/tsla-infotainment-lab.service\n')
    monkeypatch.setattr(supervisor.shutil, 'which', lambda name: '/usr/bin/systemd-run')
    probe = SimpleNamespace(returncode=0)
    monkeypatch.setattr(supervisor, 'command', lambda argv, **kw: probe)
    argv = supervisor.cpu_limited(['unshare', 'x'], cgroup=cgroup)
    assert argv[:2] == ['/usr/bin/systemd-run', '--user'] and argv[-3:] == ['--', 'unshare', 'x']
    assert '--property=CPUQuota=25%' in argv and '--property=BindsTo=tsla-infotainment-lab.service' in argv
    # Without a working user manager, or outside a session unit, the backend still starts.
    probe.returncode = 1
    assert supervisor.cpu_limited(['unshare', 'x'], cgroup=cgroup) == ['unshare', 'x']
    probe.returncode = 0
    cgroup.write_text('0::/user.slice/user-1000.slice/session-2.scope\n')
    assert supervisor.cpu_limited(['unshare', 'x'], cgroup=cgroup) == ['unshare', 'x']
    assert 'without a CPU limit' in capsys.readouterr().out


def test_service_backend_layout_is_detected_separately_from_odin_engine_assets(tmp_path):
    assert supervisor.service_ui_directory(tmp_path) is None
    for folder in ('opt/odin', 'opt/diag'):
        directory = tmp_path / folder
        directory.mkdir(parents=True)
        (directory / 'service-ui').touch()
        # A binary without its web assets cannot supply the native panel.
        if folder == 'opt/odin':
            assert supervisor.service_ui_directory(tmp_path) is None
        (directory / 'service_ui').mkdir()
        (directory / 'service_ui/index.html').touch()
        assert supervisor.service_ui_directory(tmp_path) == directory
    odin = tmp_path / 'opt/odin'
    diag = supervisor.service_ui_directory(tmp_path)
    backend, relay, engine, _ = supervisor.service_ui_commands(odin, tmp_path / 'state', backend_directory=diag)
    assert backend[-1] == tmp_path / 'opt/diag/service-ui'
    assert engine[-1] == odin


def test_namespace_relays_the_engine_port_only_when_given_a_socket(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(netns, 'namespace', lambda path, port, argv, engine=None, binds=(): started.append((argv, engine)) or 0)
    netns.main(['ns', str(tmp_path / 's.sock'), '8000', str(tmp_path / 'odin-engine.sock'), '--', 'service-ui'])
    netns.main(['ns', str(tmp_path / 's.sock'), '8000', '--', 'service-ui'])
    assert started == [(['service-ui'], tmp_path / 'odin-engine.sock'), (['service-ui'], None)]


def test_binds_are_parsed_and_run_mode_has_no_relay(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(netns, 'namespace', lambda *args, **kw: started.append((args, kw)) or 0)
    netns.main(['ns', 's.sock', '8000', 'e.sock', '--bind', '/var/log/x.log=/s/x.log', '--', 'service-ui'])
    netns.main(['run', '--bind', '/home/alertd=/s/alertd-home', '--', 'alertd'])
    assert started[0][0] == (Path('s.sock'), 8000, ['service-ui'], Path('e.sock'), [(Path('/var/log/x.log'), Path('/s/x.log'))])
    assert started[1] == ((None, None, ['alertd']), {'binds': [(Path('/home/alertd'), Path('/s/alertd-home'))]})


def test_alertd_stand_in_serves_the_session_and_service_ui_gets_an_empty_uds_log(tmp_path):
    backend, _, _, alertd = supervisor.service_ui_commands(tmp_path / 'odin', tmp_path / 'state')
    assert alertd[1:] == [supervisor.RUNTIME / 'alertd.py', tmp_path / 'state']
    assert f'/var/log/udsdebug.log={tmp_path / "state/udsdebug.log"}' in backend
    assert {'alertd'} <= supervisor.OPTIONAL & supervisor.RECOVERABLE


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


def test_namespace_owns_the_center_and_broadcast_addresses(tmp_path, monkeypatch):
    # The backend's CAN-over-Ethernet task binds 192.168.90.255 and panics without it.
    commands = []
    monkeypatch.setattr(netns.subprocess, 'run', lambda argv, check: commands.append(argv))
    monkeypatch.setattr(netns.subprocess, 'Popen', lambda argv: type('P', (), {'wait': lambda self: 0, 'terminate': lambda self: None})())
    monkeypatch.setattr(netns.signal, 'signal', lambda *_: None)
    netns.namespace(tmp_path / 's.sock', free_port(), ['service-ui'])
    added = [argv[3] for argv in commands if argv[:3] == ['ip', 'addr', 'add']]
    assert added == ['192.168.90.100/32', '192.168.90.255/32']


def test_bind_private_opens_the_source_before_covering_its_parent(tmp_path, monkeypatch):
    # alertd's source directory lives under /home, the directory the tmpfs covers.
    parent = tmp_path / 'home'
    (parent / 'user/session/alertd-home').mkdir(parents=True)
    events, real_open = [], os.open
    monkeypatch.setattr(netns, 'mount', lambda source, target, fstype=None, flags=0: events.append(('mount', Path(target))))
    monkeypatch.setattr(netns.os, 'open', lambda path, flags: events.append(('open', Path(path))) or real_open(path, flags))
    netns.bind_private(parent / 'alertd', parent / 'user/session/alertd-home')
    covered = events.index(('mount', parent))
    assert ('open', parent / 'user/session/alertd-home') in events[:covered]
    assert all(kind == 'mount' for kind, _ in events[covered:])
    assert (parent / 'alertd').is_dir()
