import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
import pytest
from infotainment_lab import application
from infotainment_lab.bridge import Bridge, wsl_path_argument
from infotainment_lab.application import MainWindow


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(application, 'QSettings', lambda *_: QSettings(str(tmp_path / 'ui.ini'), QSettings.IniFormat))


def ready_environment():
    return {'architecture': 'x86_64', 'missing': [], 'runtime_ready': True, 'display_available': True,
            'systemd_available': True, 'fuse_available': True, 'root_user': False}


def device():
    return {'id': 'a'*16, 'sha256': 'a'*64, 'kind': 'firmware', 'version': '2026.26.6.1',
            'variant': 'modelsx_info2', 'supported': True, 'bytes': 100}


def test_bridge_releases_queue_before_emitting_result():
    app = QApplication.instance() or QApplication([])
    bridge = Bridge()
    bridge.pending.add('import')
    seen = []
    bridge.finished.connect(lambda action, _: seen.append(action in bridge.pending))
    bridge.complete('import', {'ok': True})
    assert seen == [False]


def test_windows_bridge_preserves_explicit_linux_camera_paths():
    converted = []
    def convert(path):
        converted.append(path)
        return '/mnt/c/converted'
    assert wsl_path_argument('/tmp/tesla-sim/v4l2-back.rgb', convert) == '/tmp/tesla-sim/v4l2-back.rgb'
    assert converted == []
    assert wsl_path_argument('C:/Clips/back.mp4', convert) == '/mnt/c/converted'
    assert wsl_path_argument('//wsl.localhost/Debian/home/back.mp4', convert) == '/mnt/c/converted'
    assert len(converted) == 2


def test_rebuild_preserves_controls_and_park_reconciles_sliders(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(Bridge, 'call', lambda *a: True)
    window = MainWindow()
    window.set_gear('D')
    window.sliders['speed_kph'].setValue(42)
    window.indicator.setCurrentIndex(2)
    window.rebuild()
    assert window.sim.speed_kph == 42
    assert window.indicator.currentData() == 'right'
    window.set_gear('P')
    window.sliders['speed_kph'].setValue(30)
    assert window.sim.speed_kph == 0
    assert window.sliders['speed_kph'].value() == 0
    window.close()


def test_launch_is_gated_by_environment_and_has_an_actionable_reason(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(Bridge, 'call', lambda *a: True)
    window = MainWindow()
    window.library = [device()]
    window.environment = ready_environment() | {'display_available': False}
    window.refresh_library()
    assert not window.start_button.isEnabled()
    assert 'display' in window.banner.text()
    window.environment['display_available'] = True
    window.update_status()
    assert window.start_button.isEnabled()
    window.close()


def test_errors_survive_background_status_until_dismissed(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(Bridge, 'call', lambda *a: True)
    window = MainWindow()
    window.received('import', {'ok': False, 'error': 'This file is not a SquashFS image.'})
    window.received('status', {'ok': True, 'data': {'phase': 'running'}})
    assert 'SquashFS' in window.banner.text()
    window.dismiss_notice()
    assert 'SquashFS' not in window.banner.text()
    window.close()


def test_launch_options_survive_rebuild_and_reopen(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(Bridge, 'call', lambda *a: True)
    window = MainWindow()
    window.library = [device()]
    window.refresh_library()
    window.cluster_box.setChecked(False)
    window.browser_box.setChecked(False)
    window.rebuild()
    assert not window.cluster_box.isChecked() and not window.browser_box.isChecked()
    window.close()
    reopened = MainWindow()
    reopened.library = [device()]
    reopened.refresh_library()
    assert not reopened.cluster_box.isChecked() and not reopened.browser_box.isChecked()
    reopened.close()


def test_camera_routes_sources_to_worker_and_reports_actual_health(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []
    monkeypatch.setattr(Bridge, 'call', lambda _, *args: calls.append(args) or True)
    window = MainWindow()
    window.show_pattern()
    assert calls[-1] == ('camera', '--source', 'pattern')
    window.camera_path.setText('/tmp/tesla-sim/v4l2-back.rgb')
    window.connect_camera_pipeline()
    assert calls[-1] == ('camera', '--source', 'raw', '--path', '/tmp/tesla-sim/v4l2-back.rgb')
    window.session = {'phase': 'running', 'camera': {'mode': 'raw', 'source_ready': True, 'firmware_receiving': False}}
    window.update_status()
    assert 'Source ready' in window.camera_status.text()
    window.session['camera'].update(firmware_receiving=True, fps=24)
    window.update_status()
    assert 'Firmware receiving' in window.camera_status.text()
    window.rebuild()
    assert 'Firmware receiving' in window.camera_status.text()
    assert window.camera_path.text() == '/tmp/tesla-sim/v4l2-back.rgb'
    window.close()
