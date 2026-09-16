"""Linux worker boundaries with temporary files; no real firmware or services."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Linux worker uses distribution modules')
if os.name != 'nt':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
    import backend
    import supervisor


def test_media_port_conflict_reports_the_port_without_starting_services(monkeypatch):
    import socket
    class BusyPort:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def setsockopt(self, *_): pass
        def bind(self, address):
            if address[1] == 9001:
                raise OSError('Address already in use')
    monkeypatch.setattr(socket, 'socket', lambda *_: BusyPort())
    with pytest.raises(RuntimeError, match='9001'):
        supervisor.check_media_ports()


def test_single_display_preflight_does_not_require_cluster(tmp_path):
    executable = tmp_path / 'usr/tesla/UI/bin/QtCar'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'\x7fELF\x02\x01' + bytes(12) + b'\x3e\x00')
    profile = {'experimental': True, 'single_display': True}
    backend.verify_builds(tmp_path, profile)
    executable.write_bytes(b'\x7fELF\x02\x01' + bytes(12) + b'\xb7\x00')
    with pytest.raises(ValueError, match='architecture'):
        backend.verify_builds(tmp_path, profile)


def test_native_service_directory_is_private_and_rejects_symlinks(tmp_path):
    private = tmp_path / 'dvaccess'
    supervisor.prepare_service_sockets(private)
    assert private.stat().st_mode & 0o777 == 0o700
    supervisor.prepare_service_sockets(private)
    linked = tmp_path / 'alias'
    linked.symlink_to(private, target_is_directory=True)
    with pytest.raises(RuntimeError, match='private directory'):
        supervisor.prepare_service_sockets(linked)
    private.chmod(0o755)
    with pytest.raises(RuntimeError, match='private directory'):
        supervisor.prepare_service_sockets(private)


def test_media_recovery_backs_off_and_stops_after_two_retries(monkeypatch):
    launches = []
    monkeypatch.setattr(supervisor, 'restart_specs', {'spotify': ('args', 'state', 'env')})
    monkeypatch.setattr(supervisor, 'children', {'spotify': SimpleNamespace(poll=lambda: 1)})
    monkeypatch.setattr(supervisor, 'service_retries', {})
    monkeypatch.setattr(supervisor, 'retry_after', {})
    monkeypatch.setattr(supervisor, 'launch', lambda *args: launches.append(args))
    for now in (0, 1, 2, 3, 6, 7, 20, 100):
        supervisor.recover_services(now)
    assert len(launches) == 2
    assert supervisor.service_retries == {'spotify': 2}


def test_changed_image_requires_reimport(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    image = tmp_path / 'original.mcu2'
    image.write_bytes(b'hsqs-data')
    item = {'id': 'a'*16, 'path': str(image), 'bytes': image.stat().st_size, 'mtime_ns': image.stat().st_mtime_ns}
    backend.atomic_json(tmp_path / 'library.json', [item])
    image.write_bytes(b'hsqs-changed-data')
    with pytest.raises(ValueError, match='changed after import'):
        backend.library_item(item['id'])


def test_mount_never_overlays_an_existing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    mount = tmp_path / 'mounts' / ('a'*16)
    mount.mkdir(parents=True)
    sentinel = mount / 'keep.txt'
    sentinel.write_text('preserve')
    with pytest.raises(RuntimeError, match='not empty'):
        backend.mounted_image({'id': 'a'*16, 'path': '/unused'})
    assert sentinel.read_text() == 'preserve'


def test_stop_is_idempotent_and_uses_only_owned_mounts(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    calls = []
    monkeypatch.setattr(backend, 'systemctl', lambda *a, **kw: calls.append(a) or SimpleNamespace(stdout='inactive', returncode=3))
    monkeypatch.setattr(backend, 'status', lambda: backend.load_json(tmp_path / 'session/status.json'))
    assert backend.stop()['phase'] == 'stopped'
    assert ('stop', backend.UNIT) not in calls


def test_build_check_rejects_executable_symlink_outside_mount(tmp_path):
    root = tmp_path / 'mount'
    binary = root / 'usr/tesla/UI/bin/QtCar'
    binary.parent.mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.write_bytes(b'not executable')
    binary.symlink_to(outside)
    with pytest.raises(ValueError, match='outside'):
        backend.verify_builds(root, {})


def test_only_recognized_configuration_kill_is_retried():
    log = '20:12:02.263\t[CarConfigChangeProcessRestarter] INFO Restarting QtCar because of changed DVs: GUI_centerDisplayModel, FEATURE_enableTeslaTtsService'
    assert supervisor.is_configuration_restart(-9, log)
    assert not supervisor.is_configuration_restart(-11, log)
    assert not supervisor.is_configuration_restart(-9, 'Out of memory')


def test_restart_validates_image_before_stopping_working_session(monkeypatch):
    monkeypatch.setattr(backend, 'session_config', lambda: {'firmware_id': 'a'*16, 'maps': None})
    def changed(_):
        raise ValueError('Image changed')
    monkeypatch.setattr(backend, 'library_item', changed)
    stopped = []
    monkeypatch.setattr(backend, 'stop', lambda: stopped.append(True))
    with pytest.raises(ValueError, match='changed'):
        backend.restart()
    assert not stopped


def test_capture_rejects_a_display_outside_session_range(monkeypatch):
    monkeypatch.setattr(backend, 'session_config', lambda: {'center_display': 'remote-host:0', 'cluster': False})
    with pytest.raises(RuntimeError, match='not ready'):
        backend.capture_displays()


def test_rapid_volume_updates_preserve_pending_request_then_accept_native_feedback(tmp_path, monkeypatch):
    from infotainment_lab.steering import execute
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    state = tmp_path / 'session/vehicle-services.json'
    feedback = tmp_path / 'session/vehicle-services-feedback.json'
    backend.atomic_json(feedback, {'state': {'volume_pct': 30}})
    for _ in range(3):
        execute('volume_up', None, None, backend.vehicle_services_state, backend.set_vehicle_services)
    assert backend.load_json(state)['volume_pct'] == 45
    # Once the request is consumed, a subsequent native edit is authoritative.
    backend.atomic_json(feedback, {'state': {'volume_pct': 20}, 'config_mtime_ns': state.stat().st_mtime_ns})
    execute('volume_up', None, None, backend.vehicle_services_state, backend.set_vehicle_services)
    assert backend.load_json(state)['volume_pct'] == 25


def test_shared_desktop_layout_timeout_does_not_stop_the_session(monkeypatch):
    import subprocess
    def stalled(*args, **kwargs):
        raise subprocess.TimeoutExpired('xdotool', 2)
    monkeypatch.setattr(supervisor, 'command', stalled)
    assert supervisor.arrange_cluster({'DISPLAY': ':0.0'}) is False
