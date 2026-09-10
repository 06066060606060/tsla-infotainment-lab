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
