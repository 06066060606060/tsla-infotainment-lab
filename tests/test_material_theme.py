"""Theme changes must preserve controls and remain readable in either mode."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from infotainment_lab.application import MainWindow
from infotainment_lab.bridge import Bridge
from infotainment_lab.material_widgets import MaterialSwitch
from infotainment_lab.theme import ACCENTS, colors


@pytest.fixture(scope='session', autouse=True)
def qt_application():
    # Qt's native display connection must outlive every widget test.
    app = QApplication.instance() or QApplication([])
    yield app


def luminance(hex_color):
    values = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
    return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))


def test_qemu_selection_is_saved_and_live_guest_prevents_accidental_mode_change(tmp_path, monkeypatch):
    monkeypatch.setattr(Bridge, 'call', lambda *args: True)
    settings = QSettings(str(tmp_path / 'qemu.ini'), QSettings.IniFormat)
    w = MainWindow(settings=settings)
    w.engine_box.setCurrentIndex(w.engine_box.findData('qemu'))
    w.vm_directory.setText('/home/lab/virtual-desktop')
    w.change_vm_directory()
    assert w.bridge.engine == 'qemu'
    assert w.bridge.vm_directory == '/home/lab/virtual-desktop'
    assert not w.vm_options.isHidden()
    w.session = {'phase': 'booting'}
    w.update_status()
    assert not w.engine_box.isEnabled() and w.stop_button.isEnabled()
    w.close()
    reopened = MainWindow(settings=settings)
    assert reopened.bridge.engine == 'qemu'
    assert reopened.vm_directory.text() == '/home/lab/virtual-desktop'
    reopened.close()


def test_bridge_ignores_responses_from_previous_mode():
    bridge = Bridge()
    received = []
    bridge.finished.connect(lambda action, result: received.append((action, result)))
    old_epoch = bridge.epoch
    bridge.configure('qemu', '/tmp/test-guest')
    bridge.pending.add('status')
    bridge.complete('status', {'ok': True, 'data': {'phase': 'running'}, '_bridge_epoch': old_epoch})
    assert received == []
    assert 'status' in bridge.pending
    bridge.complete('status', {'ok': True, 'data': {'phase': 'starting'}, '_bridge_epoch': bridge.epoch})
    assert received[0][1]['data']['phase'] == 'starting'
    assert 'status' not in bridge.pending


@pytest.mark.parametrize('mode', ['light', 'dark'])
@pytest.mark.parametrize('accent', ACCENTS)
def test_text_roles_have_normal_text_contrast(mode, accent):
    c = colors(mode, accent)
    for foreground, background in (('on_surface', 'surface'), ('muted', 'container'),
                                   ('on_primary', 'primary'), ('on_primary_container', 'primary_container'),
                                   ('on_secondary_container', 'secondary_container'),
                                   ('on_error_container', 'error_container')):
        bright, dark = sorted((luminance(c[foreground]), luminance(c[background])), reverse=True)
        assert (bright + .05) / (dark + .05) >= 4.5, (mode, accent, foreground)


def test_appearance_preserves_live_controls_drafts_and_selection(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []
    monkeypatch.setattr(Bridge, 'call', lambda _, *args: calls.append(args) or True)
    settings = QSettings(str(tmp_path / 'theme.ini'), QSettings.IniFormat)
    w = MainWindow(settings=settings)
    w.show()
    QTest.qWaitForWindowExposed(w)
    QTest.qWait(100)  # Let the window manager finish the initial configure.
    w.set_gear('D')
    w.sliders['speed_kph'].setValue(42)
    w.browser_panel.url.setText('https://example.org/')
    w.services_panel.widgets['battery_percent'].setValue(61)
    draft = w.services_panel.export_draft()
    w.show_page(5)
    slider = w.sliders['speed_kph']
    calls.clear()
    w.appearance.setCurrentIndex(w.appearance.findData('dark'))
    w.accent.setCurrentIndex(w.accent.findData('blue'))
    assert calls == []
    assert w.current_page == 5 and w.sliders['speed_kph'] is slider
    assert slider.value() == 42
    assert w.browser_panel.url.text() == 'https://example.org/'
    assert w.services_panel.export_draft() == draft
    w.resize(960, 680)
    # X11 acknowledges window geometry asynchronously.
    for _ in range(25):
        QTest.qWait(20)
        if w.compact_settings.isVisible():
            break
    assert w.compact_settings.isVisible(), (w.size().toTuple(), w.minimumSizeHint().toTuple(), w.sidebar.width())
    assert w.nav_group.button(5).accessibleName()
    w.close()
    assert not w.poll.isActive() and not w.control_timer.isActive()
    reopened = MainWindow(settings=settings)
    assert reopened.appearance.currentData() == 'dark'
    assert reopened.accent.currentData() == 'blue'
    reopened.close()
    w.deleteLater()
    reopened.deleteLater()


def test_native_switch_keyboard_and_disabled_semantics():
    app = QApplication.instance() or QApplication([])
    switch = MaterialSwitch('Instrument display')
    switch.show()
    switch.setFocus()
    app.processEvents()
    QTest.keyClick(switch, Qt.Key_Space)
    assert switch.isChecked()
    switch.setEnabled(False)
    QTest.keyClick(switch, Qt.Key_Space)
    assert switch.isChecked()
    switch.close()
    switch.deleteLater()


def test_closing_before_startup_cancels_the_delayed_probe(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(Bridge, 'call', lambda _, *args: calls.append(args) or True)
    w = MainWindow(settings=QSettings(str(tmp_path / 'closed.ini'), QSettings.IniFormat))
    w.close()
    calls.clear()
    QTest.qWait(250)
    assert calls == []
    w.deleteLater()
