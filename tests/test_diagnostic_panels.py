import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from infotainment_lab.application import MainWindow
from infotainment_lab.bridge import Bridge


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []
    monkeypatch.setattr(Bridge, 'call', lambda _, *args: calls.append(args) or True)
    window = MainWindow(settings=QSettings(str(tmp_path / 'ui.ini'), QSettings.IniFormat))
    window.calls = calls
    for timer in (window.poll, window.preview_timer, window.camera_timer, window.probe_timer, window.debug_timer):
        timer.stop()
    yield window
    window.close()


def test_debug_is_below_diagnostics_and_polling_is_visible_page_only(window):
    nav = window.nav_group.buttons()
    assert nav[nav.index(window.nav_group.button(3)) + 1].text() == 'Debug'
    window.debug_timer.timeout.emit()
    assert not any(call[0] == 'debug' for call in window.calls)
    window.show_page(9)
    assert window.page_title.text() == 'Debug'
    assert window.calls[-1] == ('debug',)
    window.calls.clear()
    window.debug_panel.auto.setChecked(False)
    window.debug_timer.timeout.emit()
    assert not window.calls


def test_debug_response_filter_and_source_do_not_overwrite_diagnostics(window):
    window.log_view.setPlainText('environment report')
    window.received('debug', {'ok': True, 'data': {'logs': {'serial': '<error>\nboot', 'center.log': 'render error\nready'}, 'context': 'QEMU guest OS'}})
    assert '<error>' in window.debug_panel.view.toPlainText()
    assert window.log_view.toPlainText() == 'environment report'
    window.debug_panel.filter.setText('error')
    assert 'boot' not in window.debug_panel.view.toPlainText()
    window.debug_panel.sources.setCurrentIndex(window.debug_panel.sources.findData('center.log'))
    assert 'render error' in window.debug_panel.view.toPlainText()
    assert '<error>' not in window.debug_panel.view.toPlainText()
    window.received('debug', {'ok': False, 'error': 'journal unavailable'})
    assert 'journal unavailable' in window.debug_panel.caption.text()


def test_replacement_controls_restore_original_and_gate_running_session(window):
    panel = window.firmware_files_panel
    identifier = 'a' * 16
    panel.update_library([{'id': identifier, 'kind': 'firmware', 'version': '2026.8.3'}])
    panel.pending_id = identifier
    window.received('firmware-files', {'ok': True, 'data': {'id': identifier, 'files': [{'target': '/usr/file', 'bytes': 4}]}})
    panel.files.setCurrentRow(0)
    assert panel.target.text() == '/usr/file'
    panel.restore()
    assert window.calls[-1] == ('firmware-files', '--id', identifier, '--replacement-operation', 'remove', '--target', '/usr/file')
    panel.update_status({'phase': 'running'})
    assert not panel.replace.isEnabled() and not panel.remove.isEnabled()
