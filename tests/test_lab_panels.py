import json
import os
import shlex

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from infotainment_lab.application import MainWindow
from infotainment_lab import lab_panels
from infotainment_lab import config_panel
from infotainment_lab.config_csv import pending as config_pending
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


def test_light_mode_draft_survives_rebuild_and_native_update(window):
    panel = window.services_panel
    control = panel.widgets['exterior_light_mode']
    control.setCurrentIndex(control.findData('Auto'))
    draft = panel.export_draft()
    window.rebuild()
    panel = window.services_panel
    assert panel.field_value('exterior_light_mode') == 'Auto'
    assert 'exterior_light_mode' in panel.dirty
    panel.dirty.clear()
    panel.update_status({'phase': 'running', 'vehicle_services': {'state': {'exterior_light_mode': 'Parking'}}})
    assert panel.field_value('exterior_light_mode') == 'Parking'


def test_light_controls_keep_a_consistent_draft_when_the_user_changes_modes(window):
    panel = window.services_panel
    mode = panel.widgets['exterior_light_mode']
    mode.setCurrentIndex(mode.findData('Auto'))
    panel.widgets['ambient_dark'].setChecked(True)
    assert panel.widgets['headlights'].isChecked()
    panel.widgets['headlights'].setChecked(False)
    assert mode.currentData() == 'Off'
    mode.setCurrentIndex(mode.findData('On'))
    assert panel.widgets['headlights'].isChecked()
    assert 'headlights' not in panel.dirty


def test_wheel_hold_survives_status_poll_and_stops_after_failure(window):
    window.session = {'phase': 'running'}
    window.update_status()
    button = next(b for b in window.wheel_buttons if b.objectName() == 'wheel_volume_up')
    button.setDown(True)
    button.begin_hold()
    assert window.calls[-1] == ('steering', '--button', 'volume_up')
    window.bridge.pending.add('steering')
    window.update_status()
    assert button.isEnabled() and button.holding
    window.bridge.pending.discard('steering')
    window.received('steering', {'ok': False, 'error': 'Instrument disconnected'})
    assert button.isEnabled() and not button.holding and not button.hold_timer.isActive()
    assert 'Instrument disconnected' in window.banner.text()


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


def test_browser_panel_reports_native_media_rejection_without_disabling_browser(window):
    panel = window.browser_panel
    panel.update_status({'phase': 'running', 'components': {'chromium': 'running'},
                         'media': {'state': 'peer-profile-rejected'}})
    assert all(button.isEnabled() for button in panel.buttons)
    assert 'security profile' in panel.media_health.text()


def test_audio_failure_is_visible_without_disabling_browser_controls(window):
    panel = window.browser_panel
    session = {'phase': 'running', 'components': {'chromium': 'running'},
               'audio_transport': {'phase': 'degraded', 'detail': 'Output stalled'}}
    panel.update_status(session)
    assert not panel.audio_health.isHidden()
    assert panel.audio_health.toolTip() == 'Output stalled'
    assert all(button.isEnabled() for button in panel.buttons)
    panel.update_status(session | {'audio_transport': {'phase': 'running'}})
    assert panel.audio_health.isHidden()


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
    assert panel.pending is not None
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


def test_rebuild_preserves_browser_and_service_drafts_without_applying(window):
    window.session = service_session()
    window.update_status()
    window.browser_panel.url.setText('https://example.com/unsubmitted')
    window.services_panel.widgets['battery_percent'].setValue(72)
    window.services_panel.tabs.setCurrentIndex(3)
    window.show_page(1)
    window.calls.clear()
    window.rebuild()
    assert window.browser_panel.url.text() == 'https://example.com/unsubmitted'
    assert window.services_panel.widgets['battery_percent'].value() == 72
    assert window.services_panel.dirty == {'battery_percent'}
    assert window.services_panel.tabs.currentIndex() == 3
    assert window.page_title.text() == 'Vehicle controls'
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
                         'brake_pct': 0, 'steering_deg': 90, 'indicator': 'left',
                         'car_off': False}


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


def test_can_panel_sends_a_frame_through_the_gateway(window):
    panel = window.can_panel
    panel.identifier.setText('0x2E5')
    panel.payload.setText('21 04')
    panel.send_frame()
    payload = payloads(window, 'can')[-1]
    assert payload['action'] == 'send' and payload['origin'] == 'ethernet'
    assert payload['frame'] == {'channel': 'veh', 'id': '0x2E5', 'data': '21 04'}


def test_can_panel_requires_an_identifier(window):
    window.can_panel.send_frame()
    assert payloads(window, 'can') == []


def test_can_panel_answers_a_challenge_with_a_derived_response(window):
    import hashlib
    import hmac

    panel = window.can_panel
    panel.secret.setText('test-secret')
    panel.unlock()
    assert payloads(window, 'can')[-1] == {'action': 'challenge'}
    panel.received('can', {'ok': True, 'data': {'challenge': '00112233445566aa'}})
    sent = payloads(window, 'can')[-1]
    assert sent['action'] == 'unlock'
    assert sent['response'] == hmac.new(b'test-secret', bytes.fromhex('00112233445566aa'),
                                        hashlib.sha256).hexdigest()[:32]


def test_can_panel_reports_a_refusal_and_a_stopped_service(window):
    panel = window.can_panel
    panel.received('can', {'ok': True, 'data': {'allowed': False, 'route': 'eth-to-veh',
                                                'reason': 'the gateway session is locked'}})
    assert 'locked' in panel.result.text()
    panel.received('can-status', {'ok': True, 'data': {'service': 'stopped'}})
    assert 'stopped' in panel.state.text()


def test_can_panel_renders_a_decoded_trace(window):
    panel = window.can_panel
    panel.received('can', {'ok': True, 'now': 5, 'data': {'frames': [
        {'channel': 'veh', 'id': 0x118, 'id_hex': '118', 'data': '21 04 00 00 00 00 00 00',
         'name': 'LAB_driveState', 'signals': {'gear': 'D', 'speed_kph': 80.0}, 'timestamp': 4}],
        'now': 5}})
    assert 'LAB_driveState' in panel.frames.text()
    assert 'gear=D' in panel.trace.text()
    assert panel.since == 5


def cfg_row(panel, name):
    return next(row for row in panel.rows if row['name'] == name)


def cfg_shown(panel):
    return [panel.table.item(i, 0).text() for i in range(panel.table.rowCount())]


def test_config_panel_lists_the_default_keys_and_import_compares_against_them(window):
    from infotainment_lab.config_csv import profile_defaults
    panel = window.config_panel
    assert [row['name'] for row in panel.rows] == list(profile_defaults())
    assert config_pending(panel.rows) == 0
    assert panel.load('Name,Value\nAPP_fsd,0\nAUDIO_a2b,@invalid\nAPTRIAL_force,false\nAPP_fsd,1\nVAPI_carType,ModelS2\n') == (['AUDIO_a2b'], [('APP_fsd', '0', '1')])
    names = [row['name'] for row in panel.rows]
    assert names[:len(profile_defaults())] == list(profile_defaults()) and names[-2:] == ['APP_fsd', 'APTRIAL_force']
    car = cfg_row(panel, 'VAPI_carType')  # compared with the app default: shows the dump value, differs, waits for Apply
    assert (car['value'], car['original'], car['applied']) == ('ModelS2', 'ModelX', 'ModelX')
    assert cfg_row(panel, 'APP_fsd')['applied'] is None and cfg_row(panel, 'APP_fsd')['value'] == '1'  # new key: pending
    assert config_pending(panel.rows) == 3 and '(3)' in panel.apply_button.text() and panel.apply_button.isEnabled()
    panel.changed_only.setChecked(True)
    assert cfg_shown(panel) == ['VAPI_carType']  # "changed" means different from the default
    panel.changed_only.setChecked(False)
    default_column = {panel.table.item(i, 0).text(): panel.table.item(i, 2).text() for i in range(panel.table.rowCount())}
    assert default_column['VAPI_carType'] == 'ModelX' and default_column['APP_fsd'] == ''
    panel.search.setText('force')
    panel.table.selectRow(0)
    panel.set_selected('true')
    assert cfg_row(panel, 'APTRIAL_force')['value'] == 'true'
    window.show_page(8)


def test_config_panel_remove_selected_resets_a_default_key_and_drops_others(window):
    panel = window.config_panel
    panel.load('Name,Value\nAPP_fsd,0\n')
    cfg_row(panel, 'VAPI_carType')['value'] = 'ModelS'
    panel.search.setText('_')
    panel.table.selectAll()
    panel.remove_selected()
    assert cfg_row(panel, 'VAPI_carType')['value'] == 'ModelX'
    assert 'APP_fsd' not in {row['name'] for row in panel.rows} and 'APP_fsd' in panel.removed


def test_config_panel_apply_sends_typed_values_live_and_shows_firmware_status(window, monkeypatch):
    panel = window.config_panel
    panel.load('Name,Value\nAPP_fsd,0\nVAPI_flag,false\n')
    panel.update_status({'phase': 'running'})
    window.calls.clear()
    cfg_row(panel, 'VAPI_flag')['value'] = 'true'
    cfg_row(panel, 'APP_fsd')['value'] = '3'
    panel.refresh()
    panel.apply()
    assert payloads(window, 'config-values') == [{'values': {'APP_fsd': 3, 'VAPI_flag': True}, 'explicit': [], 'remove': []}]
    assert not panel.apply_button.isEnabled()
    panel.acknowledge(True)
    assert config_pending(panel.rows) == 0
    window.calls.clear()
    firmware = {'com.tesla.CenterDisplay': {'VAPI_flag': 'accepted', 'APP_fsd': 'unsupported', 'GUI_one': 'unsupported'},
                'com.tesla.ClusterDisplay': {'VAPI_flag': 'accepted', 'APP_fsd': 'unsupported', 'GUI_one': 'accepted'}}
    panel.load('Name,Value\nAPP_fsd,0\nVAPI_flag,false\nGUI_one,1\n')
    panel.acknowledge(True) if panel.pending else None
    for row in panel.rows: row['applied'] = row['value']  # as if applied
    panel.update_status({'phase': 'running', 'config_values': {'firmware': firmware}})
    names = {row['name'] for row in panel.rows}
    assert 'APP_fsd' not in names  # no display knows it: removed
    assert 'GUI_one' in names  # one display accepts it: kept
    assert [alert[1:] for alert in window.alerts] == [('The firmware does not know 1 config key(s); they were removed from the list.', ['APP_fsd'])]
    assert payloads(window, 'config-values') == [{'values': {}, 'remove': ['APP_fsd']}]
    status = {panel.table.item(i, 0).text(): panel.table.item(i, 3).text() for i in range(panel.table.rowCount())}
    assert status['VAPI_flag'] == '✓ Applied' and status['GUI_one'] == 'Not supported'


def test_config_panel_failed_apply_stays_pending_and_restart_resends(window):
    panel = window.config_panel
    panel.load('Name,Value\nVAPI_flag,false\n')
    panel.update_status({'phase': 'running'})
    cfg_row(panel, 'VAPI_flag')['value'] = 'true'
    panel.apply()
    panel.acknowledge(False)
    assert panel.apply_button.isEnabled()
    panel.acknowledge(True)
    panel.apply()
    panel.acknowledge(True)
    panel.update_status({'phase': 'stopped'})
    window.calls.clear()
    panel.update_status({'phase': 'running'})
    assert payloads(window, 'config-values') == [{'values': {'VAPI_flag': True}, 'explicit': []}]


def test_config_panel_cell_edit_keeps_the_edited_item_and_updates_state(window):
    panel = window.config_panel
    panel.load('Name,Value\nAPP_fsd,0\n')
    panel.apply()
    panel.search.setText('VAPI_carType')
    item = panel.table.item(0, 1)
    item.setText('ModelS')
    assert panel.table.item(0, 1) is item  # not rebuilt from inside its own signal
    assert cfg_row(panel, 'VAPI_carType')['value'] == 'ModelS' and item.font().bold()
    assert '1 changed' in panel.summary.text() and '(1)' in panel.apply_button.text()
    item.setText('ModelX')
    assert not item.font().bold() and '0 changed' in panel.summary.text()


def test_config_import_reports_what_differs_and_what_was_removed(window, monkeypatch, tmp_path):
    shown = []
    monkeypatch.setattr(config_panel.QMessageBox, 'exec', lambda box: shown.append((box.text(), box.detailedText())))
    path = tmp_path / 'export.csv'
    path.write_text('Name,Value\nAPP_fsd,0\nAUDIO_a2b,@invalid\nAPP_fsd,1\nVAPI_carType,ModelS\n')
    monkeypatch.setattr(config_panel.QFileDialog, 'getOpenFileName', lambda *a: (str(path), ''))
    window.config_panel.open_file()
    text, details = shown[0]
    assert 'Imported 2 entries: 1 differ from the app defaults, 1 are new keys' in text
    assert 'Skipped 1 @invalid' in text and 'removed 1 duplicates' in text
    assert '  AUDIO_a2b' in details and 'APP_fsd: 0 → 1' in details


def test_config_defaults_drop_foreign_keys_and_add_key_adds_one(window, monkeypatch):
    from infotainment_lab.config_csv import profile_defaults
    monkeypatch.setattr(config_panel.QMessageBox, 'question', lambda *a, **k: config_panel.QMessageBox.Yes)
    panel = window.config_panel
    panel.update_status({'phase': 'running'})
    panel.load('Name,Value\nAPP_other,3\n')
    panel.new_name.setText('VAPI_myFlag')
    panel.new_value.setText('true')
    panel.add_key()
    assert {row['name'] for row in panel.rows} == set(profile_defaults()) | {'APP_other', 'VAPI_myFlag'}
    window.calls.clear()
    panel.apply()
    assert payloads(window, 'config-values') == [{'values': {'APP_other': 3, 'VAPI_myFlag': True}, 'explicit': ['VAPI_myFlag'], 'remove': []}]
    panel.acknowledge(True)
    panel.revert()
    assert [row['name'] for row in panel.rows] == list(profile_defaults())
    assert panel.removed == {'APP_other', 'VAPI_myFlag'}
    window.calls.clear()
    panel.apply()
    assert payloads(window, 'config-values') == [{'values': {}, 'explicit': [], 'remove': ['APP_other', 'VAPI_myFlag']}]
    panel.acknowledge(True)
    assert panel.removed == set()
    panel.new_name.setText('bad name')
    panel.add_key()
    assert 'letters' in window.banner.text()


def test_config_apply_of_car_config_asks_then_saves_and_restarts_the_device_once(window, monkeypatch):
    panel = window.config_panel
    panel.update_status({'phase': 'running'})
    asked = []
    monkeypatch.setattr(config_panel.QMessageBox, 'question', lambda *a, **k: asked.append(a[2]) or config_panel.QMessageBox.No)
    cfg_row(panel, 'VAPI_carType')['value'] = 'ModelS'
    panel.refresh()
    window.calls.clear()
    panel.apply()
    assert len(asked) == 1 and 'VAPI_carType' in asked[0] and 'restart once' in asked[0] and payloads(window, 'config-values') == []
    assert panel.apply_button.isEnabled()  # declined: still pending, nothing restarted
    monkeypatch.setattr(config_panel.QMessageBox, 'question', lambda *a, **k: config_panel.QMessageBox.Yes)
    panel.apply()
    assert payloads(window, 'config-values') == [{'values': {'VAPI_carType': 'ModelS'}, 'explicit': [], 'remove': []}]
    assert not any(call[0] == 'restart' for call in window.calls)  # only after the save is acknowledged
    panel.acknowledge(True)
    assert [call[0] for call in window.calls if call[0] == 'restart'] == ['restart']
    window.busy = False  # the restart is mocked; a real one would clear this when it finishes
    panel.acknowledge(True)
    assert [call[0] for call in window.calls].count('restart') == 1
    panel.load('Name,Value\nAPP_free,1\n')
    cfg_row(panel, 'APP_free')['value'] = '2'  # not car config: applied live, no prompt, no restart
    monkeypatch.setattr(config_panel.QMessageBox, 'question', lambda *a, **k: (_ for _ in ()).throw(AssertionError('asked')))
    window.calls.clear()
    panel.apply()
    panel.acknowledge(True)
    assert not any(call[0] == 'restart' for call in window.calls)


def test_config_panel_resets_values_the_supervisor_dropped_after_repeated_restarts(window):
    panel = window.config_panel
    row = cfg_row(panel, 'VAPI_carType')
    row['value'] = row['applied'] = 'ModelS'
    panel.update_status({'phase': 'starting', 'config_values': {'conflicts': ['VAPI_carType']}})
    assert row['value'] == row['applied'] == row['original'] == 'ModelX'
    assert window.alerts[-1][2] == ['VAPI_carType'] and 'kept restarting' in window.alerts[-1][1]
    row['value'] = 'ModelS'
    panel.update_status({'phase': 'starting', 'config_values': {'conflicts': ['VAPI_carType']}})
    assert row['value'] == 'ModelS'  # reported once, not on every poll


def test_config_panel_reverts_and_lists_entries_the_backend_refused(window, monkeypatch):
    panel = window.config_panel
    panel.load('Name,Value\nGUI_ok,1\nGUI_big,2\n')
    panel.update_status({'phase': 'running'})
    panel.apply()
    panel.acknowledge(True, {'count': 1, 'rejected': ['GUI_big']})
    assert {row['name'] for row in panel.rows} >= {'GUI_ok'} and 'GUI_big' not in {row['name'] for row in panel.rows}
    assert cfg_row(panel, 'GUI_ok')['applied'] == '1'
    assert [alert[2] for alert in window.alerts] == [['GUI_big']]
    assert window.alert_rows.count() == 1 and window.nav_group.button(3).text() == 'Diagnostics  (1)'
    window.clear_alerts()
    assert window.nav_group.button(3).text() == 'Diagnostics'
    assert window.alert_rows.count() == 0 and not window.alert_box.isHidden() and not window.alert_empty.isHidden()
    assert not window.clear_alerts_button.isEnabled()


def test_config_panel_alerts_say_why_the_firmware_restarted(window):
    panel = window.config_panel
    history = [{'at': 10.0, 'display': 'center', 'names': ['VAPI_trim', 'GUI_x'], 'dropped': []},
               {'at': 11.0, 'display': 'instruments', 'names': [], 'dropped': []}]
    panel.update_status({'phase': 'starting', 'config_values': {'restarts': history}})
    assert [alert[1:] for alert in window.alerts] == [
        ('The center display restarted its UI because 2 car-config value(s) changed.', ['VAPI_trim', 'GUI_x']),
        ('The instrument cluster restarted its UI to apply settings; the firmware did not name the values.', [])]
    panel.update_status({'phase': 'running', 'config_values': {'restarts': history}})
    assert len(window.alerts) == 2  # each restart is reported once


def test_banner_names_the_values_a_configuration_restart_applies(window):
    window.session = {'phase': 'starting', 'configuration_restart': True, 'changed_dvs': ['VAPI_trim']}
    window.update_status()
    assert 'VAPI_trim' in window.banner.text()


def test_config_panel_refuses_a_personal_key_before_sending_it(window):
    panel = window.config_panel
    panel.new_name.setText('GUI_valetModePassword')
    panel.new_value.setText('1234')
    panel.add_key()
    assert 'GUI_valetModePassword' not in {row['name'] for row in panel.rows}
    assert 'personal data' in window.alerts[0][1]


def test_config_panel_marks_only_deliberate_edits_as_explicit(window):
    panel = window.config_panel
    panel.update_status({'phase': 'running'})
    panel.load('Name,Value\nVAPI_batteryLevel,10\nVAPI_isLocked,true\n')  # an import: the app's model stays in charge
    assert not any(row.get('explicit') for row in panel.rows)
    panel.search.setText('VAPI_batteryLevel')
    panel.table.item(0, 1).setText('30')  # a deliberate edit: this value wins over the app's model
    assert cfg_row(panel, 'VAPI_batteryLevel')['explicit'] and not cfg_row(panel, 'VAPI_isLocked').get('explicit')
    window.calls.clear()
    panel.apply()
    assert payloads(window, 'config-values') == [{'values': {'VAPI_batteryLevel': 30, 'VAPI_isLocked': True}, 'explicit': ['VAPI_batteryLevel'], 'remove': []}]


def test_console_screen_applies_carriage_return_backspace_and_line_erase(window):
    panel = window.console_panel
    panel.feed('abcd\b\bX\r> \x1b[K')  # overwrite, back up, redraw the line and erase its tail
    assert panel.rows[-1] == '> '
    panel.feed('\none\ntwo\x1b]0;title\x07!')
    assert panel.rows[-2:] == ['one', 'two!']
    assert panel.output.textCursor().position() == len(panel.output.toPlainText())


def test_qemu_console_enters_the_firmware_root_in_the_guest(window, monkeypatch):
    started = []
    monkeypatch.setattr(lab_panels.QProcess, 'start', lambda self, program, args: started.append([program, *args]))
    panel = window.console_panel
    window.bridge.engine = 'qemu'
    panel.key_ready = True
    panel.toggle()
    script = started[0][-1].split('; ', 1)[1]
    ssh = shlex.split(script.split('exec ', 1)[1])
    assert ssh[0] == 'ssh' and ssh[-2] == 'lab@127.0.0.1'
    assert ssh[-1] == lab_panels.GUEST_CID_SHELL  # one remote argument, quoted intact
    assert 'R=/firmware' in ssh[-1] and 'chroot "$R"' in ssh[-1]
    panel.disconnect_now()


def test_service_edits_apply_on_their_own_and_modes_tab_replaces_service_mode_notes(window):
    panel = window.services_panel
    panel.update_status(service_session())
    assert not hasattr(panel, "apply_button")
    assert panel.tabs.tabText(panel.tabs.count() - 1) == "Modes"
    panel.widgets["developer_mode"].setChecked(True)
    assert panel.timer.isActive()
    panel.timer.timeout.emit()
    assert payloads(window, "vehicle-services") == [{"developer_mode": True}]


def test_a_new_full_import_starts_from_the_defaults_so_nothing_carries_over(window, monkeypatch):
    monkeypatch.setattr(config_panel.QMessageBox, 'question', lambda *a, **k: config_panel.QMessageBox.Yes)
    panel = window.config_panel
    panel.update_status({'phase': 'running'})
    panel.load('Name,Value\nVAPI_carType,ModelS2\nAPP_old,1\nAPP_both,1\nPOWER_state,on\n')
    panel.apply()
    panel.acknowledge(True)
    window.busy = False  # the car-config change restarted the device; it is back up
    panel.update_status({'phase': 'running'})
    assert config_pending(panel.rows) == 0
    panel.load('Name,Value\nAPP_both,1\nAPP_new,2\n')
    car = cfg_row(panel, 'VAPI_carType')  # set by the old file only: back to its default, written on Apply
    assert (car['value'], car['applied']) == ('ModelX', 'ModelS2')
    assert cfg_row(panel, 'APP_both')['applied'] == '1'  # already applied with the same value: nothing to send
    assert {row['name'] for row in panel.rows} >= {'APP_both', 'APP_new'} and 'APP_old' not in {row['name'] for row in panel.rows}
    assert panel.removed == {'APP_old'}  # listed-only telemetry was never sent, so there is nothing to remove
    window.calls.clear()
    panel.apply()
    assert payloads(window, 'config-values') == [{'values': {'VAPI_carType': 'ModelX', 'APP_new': 2}, 'explicit': [], 'remove': ['APP_old']}]
