import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from infotainment_lab.application import MainWindow
from infotainment_lab import lab_panels
from infotainment_lab.bridge import Bridge
from infotainment_lab.vehicle_services import VehicleServices


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(Bridge, 'call', lambda _, *args: calls.append(args) or True)
    instance = MainWindow(settings=QSettings(str(tmp_path / 'ui.ini'), QSettings.IniFormat))
    for timer in (instance.poll, instance.preview_timer, instance.camera_timer, instance.control_timer):
        timer.stop()
    instance.calls = calls
    yield instance
    for timer in (instance.poll, instance.preview_timer, instance.camera_timer, instance.control_timer):
        timer.stop()
    instance.close()


def payloads(window, action):
    return [json.loads(args[2]) for args in window.calls if args[0] == action]


def replay_session(**changes):
    replay = {'phase': 'playing', 'duration_seconds': 40, 'position_seconds': 10,
              'rate': 1, 'loop': True,
              'telemetry_sample': {'gear': 'D', 'speed_kph': 42, 'throttle_pct': 12,
                                   'brake_pct': 0, 'steering_deg': 30, 'indicator': 'left'}}
    replay.update(changes)
    return {'phase': 'running', 'camera': {'mode': 'replay'}, 'replay': replay}


def service_session(**changes):
    return {'phase': 'running', 'vehicle_services': {'state': VehicleServices().as_dict() | changes}}


@pytest.mark.parametrize('mode', ['browser', 'card', 'theater'])
def test_browser_buttons_route_the_selected_mode_and_trim_only_url_whitespace(window, mode):
    panel = window.browser_panel
    panel.update_status({'phase': 'running', 'components': {'chromium': 'running'}})
    panel.url.setText('  https://example.com/path?q=hello%20world  ')
    panel.buttons[['browser', 'card', 'theater'].index(mode)].click()
    assert window.calls[-1] == ('browser', '--mode', mode, '--url', 'https://example.com/path?q=hello%20world')
    panel.url.clear()
    panel.buttons[['browser', 'card', 'theater'].index(mode)].click()
    assert window.calls[-1] == ('browser', '--mode', mode)


def test_replay_polling_updates_widgets_without_sending_commands(window):
    panel = window.replay_panel
    panel.update_status(replay_session(rate=2, loop=False))
    assert panel.seek.value() == 250
    assert panel.rate.currentData() == 2 and not panel.loop.isChecked()
    assert '42.0 km/h' in panel.feedback.text()
    assert window.calls == []
    panel.play.click()
    assert payloads(window, 'replay') == [{'action': 'pause'}]
    panel.update_status(replay_session(phase='paused'))
    panel.play.click()
    panel.take_over.click()
    assert payloads(window, 'replay')[-2:] == [{'action': 'play'}, {'action': 'manual'}]


def test_replay_drag_is_not_overwritten_by_polling_and_seeks_once_on_release(window):
    panel = window.replay_panel
    panel.update_status(replay_session())
    panel.seek.setSliderDown(True)
    panel.seek.setValue(750)
    panel.update_status(replay_session(position_seconds=11))
    assert panel.seek.value() == 750
    assert window.calls == []
    panel.seek.setSliderDown(False)
    assert payloads(window, 'replay') == [{'action': 'seek', 'position_seconds': 30}]


def test_replay_keyboard_seek_and_rate_loop_changes_send_user_intent(window):
    panel = window.replay_panel
    panel.update_status(replay_session())
    QTest.keyClick(panel.seek, Qt.Key_Right)
    assert payloads(window, 'replay') == [{'action': 'seek', 'position_seconds': pytest.approx(10.04)}]
    panel.rate.setCurrentIndex(panel.rate.findData(.5))
    panel.loop.click()
    assert payloads(window, 'replay')[-2:] == [{'action': 'rate', 'rate': .5}, {'action': 'loop', 'loop': False}]


def test_replay_file_selection_uses_the_camera_pipeline_and_cancel_sends_nothing(window, monkeypatch):
    filename = '/recordings/drive with spaces.mp4'
    monkeypatch.setattr(lab_panels.QFileDialog, 'getOpenFileName', lambda *_: (filename, 'Dashcam (*.mp4)'))
    window.replay_panel.open()
    assert window.calls == [('camera', '--source', 'replay', '--path', filename)]
    monkeypatch.setattr(lab_panels.QFileDialog, 'getOpenFileName', lambda *_: ('', ''))
    window.replay_panel.open()
    assert len(window.calls) == 1


def test_service_polling_does_not_create_edits_or_apply_requests(window):
    panel = window.services_panel
    panel.update_status(service_session(climate_on=False, battery_percent=63, latitude_deg=37.5, longitude_deg=-122))
    assert not panel.widgets['climate_on'].isChecked()
    assert panel.widgets['battery_percent'].value() == 63
    assert panel.widgets['latitude_deg'].text() == '37.5'
    assert panel.dirty == set() and window.calls == []
    panel.apply()
    assert window.calls == []


def test_service_apply_patches_only_edits_and_preserves_them_through_old_feedback(window):
    panel = window.services_panel
    old = service_session()
    panel.update_status(old)
    panel.widgets['battery_percent'].setValue(72)
    panel.apply()
    assert payloads(window, 'vehicle-services') == [{'battery_percent': 72}]
    assert not panel.apply_button.isEnabled()
    panel.update_status(old)
    assert panel.widgets['battery_percent'].value() == 72
    panel.acknowledge(True)
    panel.update_status(old)
    assert panel.widgets['battery_percent'].value() == 72
    panel.update_status(service_session(battery_percent=72))
    assert panel.dirty == set() and panel.pending is None and panel.awaiting == {}


def test_service_backend_failure_keeps_edits_and_an_edit_during_apply_survives_ack(window):
    panel = window.services_panel
    panel.update_status(service_session())
    panel.widgets['battery_percent'].setValue(72)
    panel.apply()
    window.received('vehicle-services', {'ok': False, 'error': 'Worker is unavailable'})
    panel.update_status(service_session())
    assert panel.pending is None and panel.dirty == {'battery_percent'}
    assert panel.widgets['battery_percent'].value() == 72
    panel.apply()
    panel.widgets['battery_percent'].setValue(73)
    window.received('vehicle-services', {'ok': True, 'data': VehicleServices(battery_percent=72).as_dict()})
    panel.update_status(service_session(battery_percent=72))
    assert panel.widgets['battery_percent'].value() == 73 and panel.dirty == {'battery_percent'}


def test_invalid_location_is_not_sent_and_still_can_be_edited(window):
    panel = window.services_panel
    panel.update_status(service_session())
    QTest.keyClicks(panel.widgets['latitude_deg'], 'not a number')
    panel.apply()
    assert payloads(window, 'vehicle-services') == []
    assert 'valid number' in window.banner.text()
    assert panel.dirty == {'latitude_deg'}


def test_language_rebuild_preserves_browser_and_service_drafts_without_applying(window):
    window.session = service_session()
    window.update_status()
    window.browser_panel.url.setText('https://example.com/unsubmitted')
    window.services_panel.widgets['battery_percent'].setValue(72)
    window.services_panel.tabs.setCurrentIndex(3)
    window.show_page(6)
    window.calls.clear()
    window.change_language(1)
    assert window.browser_panel.url.text() == 'https://example.com/unsubmitted'
    assert window.services_panel.widgets['battery_percent'].value() == 72
    assert window.services_panel.dirty == {'battery_percent'}
    assert window.services_panel.tabs.currentIndex() == 3
    assert window.page_title.text() == '车辆服务'
    assert payloads(window, 'vehicle-services') == [] and payloads(window, 'replay') == []


def test_replay_control_takeover_starts_from_the_recorded_state(window):
    window.session = replay_session()
    window.update_status()
    assert window.sim.gear == 'D' and window.sliders['speed_kph'].value() == 42
    assert window.indicator.currentData() == 'left'
    assert payloads(window, 'controls') == []
    window.sliders['steering_deg'].setValue(90)
    window.send_controls()
    requested = payloads(window, 'controls')[-1]
    assert requested == {'gear': 'D', 'speed_kph': 42, 'throttle_pct': 12,
                         'brake_pct': 0, 'steering_deg': 90, 'indicator': 'left'}


def test_stale_replay_poll_does_not_replace_a_manual_edit_while_it_is_debounced(window):
    window.session = replay_session()
    window.update_status()
    window.sliders['steering_deg'].setValue(90)
    window.session = replay_session(position_seconds=10.2)
    window.session['replay']['telemetry_sample']['steering_deg'] = 35
    window.update_status()
    assert window.sliders['steering_deg'].value() == 90
    window.send_controls()
    assert payloads(window, 'controls')[-1]['steering_deg'] == 90
