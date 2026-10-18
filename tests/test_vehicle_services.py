"""Contracts for local services and two-display reconciliation, without firmware."""
import pytest

from infotainment_lab.vehicle_services import (
    CAPABILITIES, FIELD_SPECS, DisplayWriter, PreferenceSync, VehicleServices,
    decode_value, display_values, speed_display_values,
    replay_location, equivalent, PREFERENCES, CENTER_CHANNELS, REQUEST_FIELDS, media_network_values,
    navigation_fix, gateway_lock_values, GATEWAY_LOCK_SIGNALS,
)


def test_gateway_lock_values_track_the_unlock_state():
    now = 1_000.0
    # The page reads unlocked as LEVEL_SERVICE with at least ten seconds left.
    unlocked = gateway_lock_values(True, now + 90, now)
    assert unlocked == {'GTW_diagLevel': 'LEVEL_SERVICE', 'GTW_diagRemainingSeconds': 90,
                        'GTW_diagUnlockProcedureActive': False}
    assert set(unlocked) == set(GATEWAY_LOCK_SIGNALS)
    # Fewer than ten seconds left, expired, or locked all read as the locked default.
    assert gateway_lock_values(True, now + 5, now)['GTW_diagLevel'] == 'LEVEL_NORMAL_OPERATION'
    assert gateway_lock_values(True, now - 1, now)['GTW_diagLevel'] == 'LEVEL_NORMAL_OPERATION'
    assert gateway_lock_values(False, 0, now) == {'GTW_diagLevel': 'LEVEL_NORMAL_OPERATION',
                                                  'GTW_diagRemainingSeconds': 0,
                                                  'GTW_diagUnlockProcedureActive': False}


@pytest.mark.parametrize("patch", [
    {"climate_on": "false"}, {"fan_speed": 2.5}, {"battery_percent": 101},
    {"driver_temp_c": float("nan")}, {"volume_pct": True},
    {"nav_destination": "two\nlines"}, {"latitude_deg": 37.5},
    {"latitude_deg": 91, "longitude_deg": 0}, {"can_bus": "can0"},
])
def test_rejects_invalid_or_nonlocal_model_fields(patch):
    with pytest.raises(ValueError):
        VehicleServices.parse(patch)


def test_complete_model_schema_roundtrip_and_partial_updates():
    initial = VehicleServices.parse({})
    assert set(initial.as_dict()) == set(FIELD_SPECS)
    assert initial.battery_percent == 50
    changed = initial.patched({"battery_percent": 73, "driver_temp_c": 23.5})
    assert changed.battery_percent == 73
    assert changed.driver_temp_c == 23.5
    assert changed.volume_pct == initial.volume_pct
    assert VehicleServices.parse(changed.as_dict()) == changed


def test_fsd_ui_simulation_is_explicit_and_does_not_change_vehicle_telemetry():
    initial = VehicleServices.parse({})
    assert initial.fsd_ui_simulation is False
    simulated = initial.patched({'fsd_ui_simulation': True})
    assert simulated.fsd_ui_simulation is True
    assert display_values(simulated) == display_values(initial)
    with pytest.raises(ValueError, match='must be true or false'):
        initial.patched({'fsd_ui_simulation': 'true'})


def test_model_maps_only_display_telemetry_and_reports_unverified_domains():
    model = VehicleServices.parse({"charging": True, "charge_power_kw": 11,
                                   "battery_percent": 62, "volume_pct": 25,
                                   "latitude_deg": 37.5, "longitude_deg": -122.4,
                                   "heading_deg": 360, "passenger_door_open": True})
    values = display_values(model, 8)
    assert values["charge_power_kw"] == {"VAPI_chargerPower": 11.0}
    assert values["battery_percent"]["VAPI_batteryLevel"] == 62
    assert values["volume_pct"] == {"GUI_audioVolume": 2}
    assert values["latitude_deg"]["LOC_geoValidFix"] is True
    assert values['latitude_deg']['LOC_geoLocation'] == [37.5, -122.4]
    assert values["heading_deg"] == {"LOC_geoHdg": 0}
    assert values["driver_door_open"]["VAPI_driverDoorAlert"] is False
    assert values["passenger_door_open"]["VAPI_doorAlert"] is True
    assert values["headlights"]["LIGHT_headlightLeft"] == "Off"
    assert values["alarm_armed"]["VAPI_alarmStatus"] == "Disarmed"
    assert display_values(model.patched({"headlights": True}))["headlights"]["LIGHT_headlightLeft"] == "On"
    assert values['tire_fl_bar'] == {'TPMS_pressureFLConti': 2.9, 'TPMS_pressureFLTesla': 2.9}
    assert CAPABILITIES['tires']['mode'] == 'local-display'
    assert not any(name.startswith(("DAS_", "AUTH_", "CAPI_"))
                   for group in values.values() for name in group)


def test_map_position_follows_the_gps_fix():
    values = display_values(VehicleServices().patched({"latitude_deg": 40.4168, "longitude_deg": -3.7038}))
    assert values["latitude_deg"]["LOC_estimatedLat"] == values["latitude_deg"]["LOC_geoLat"] == 40.4168
    assert values["longitude_deg"]["LOC_estimatedLon"] == values["longitude_deg"]["LOC_geoLon"] == -3.7038


def test_stopped_charging_and_disabled_gps_do_not_fake_active_sources():
    values = display_values(VehicleServices())
    assert values["charge_power_kw"]["VAPI_chargerPower"] == 0
    assert values["latitude_deg"] == {"LOC_geoValidFix": False}
    assert "LOC_geoLat" not in values["latitude_deg"]


def test_four_wheel_pressures_keep_bar_units_and_distinct_wheel_positions():
    model = VehicleServices.parse({'tire_fl_bar': 0, 'tire_fr_bar': 2.7,
                                   'tire_rl_bar': 2.8, 'tire_rr_bar': 5})
    groups = display_values(model)
    pressures = {name: value for field, group in groups.items() if field.startswith('tire_')
                 for name, value in group.items()}
    assert pressures == {'TPMS_pressureFLConti': 0, 'TPMS_pressureFLTesla': 0,
                         'TPMS_pressureFRConti': 2.7, 'TPMS_pressureFRTesla': 2.7,
                         'TPMS_pressureRLConti': 2.8, 'TPMS_pressureRLTesla': 2.8,
                         'TPMS_pressureRRConti': 5, 'TPMS_pressureRRTesla': 5}
    assert 'GUI_tirePressureUnits' not in pressures


def test_park_assist_simulation_is_opt_in_and_clears_distances_when_disabled_or_failed():
    initial = VehicleServices.parse({})
    off = display_values(initial)
    assert off['park_assist_fault'] == {'PARK_status': 'Disabled'}
    assert off['park_front_left_cm'] == {'PARK_frontLeft': -1, 'PARK_USS_frontLeft': -1}
    model = initial.patched({'park_assist_simulation': True, 'park_front_left_cm': 83.5,
                              'park_rear_right_cm': 42})
    healthy = display_values(model)
    assert healthy['park_assist_fault'] == {'PARK_status': 'Enabled'}
    assert healthy['park_assist_simulation'] == {
        'PARK_USS_status': 'Enabled', 'PARK_service': 'None',
        'PARK_sdiActive': True, 'PARK_sdiNoise': 'Nominal'}
    assert healthy['park_front_left_cm'] == {'PARK_frontLeft': 83.5, 'PARK_USS_frontLeft': 83.5}
    assert healthy['park_rear_right_cm'] == {'PARK_rearRight': 42, 'PARK_USS_rearRight': 42}
    assert len([k for k in healthy if k.startswith('park_') and k.endswith('_cm')]) == 10
    fault = display_values(model.patched({'park_assist_fault': True}))
    assert fault['park_assist_fault'] == {'PARK_status': 'TemporaryFailure'}
    assert fault['park_assist_simulation']['PARK_sdiActive'] is False
    assert off['park_assist_simulation']['PARK_sdiActive'] is False
    assert all(value == -1 for key, values in fault.items() if key.startswith('park_') and key.endswith('_cm')
               for value in values.values())
    assert display_values(model.patched({'park_assist_simulation': False}))['park_front_left_cm']['PARK_frontLeft'] == -1
    assert CAPABILITIES['parking']['mode'] == 'local-display'


@pytest.mark.parametrize('patch', [{'park_front_middle_cm': -1}, {'park_rear_left_cm': 251},
                                  {'park_rear_middle_cm': float('nan')}, {'park_assist_simulation': 1}])
def test_invalid_park_simulation_input_is_refused(patch):
    with pytest.raises(ValueError):
        VehicleServices.parse(patch)


def test_navigation_origin_uses_the_requested_or_replay_fix_and_fresh_clock():
    assert navigation_fix(VehicleServices(), 1234) == {'LOC_estimatedGPSValid': False}
    model = VehicleServices.parse({'latitude_deg': -12.5, 'longitude_deg': 34.6})
    fix = navigation_fix(model, 1234)
    assert fix['LOC_estimatedLat'] == -12.5 and fix['LOC_estimatedLon'] == 34.6
    assert fix['LOC_estimatedGPSValid'] and fix['LOC_estimatedHdg'] == 0
    assert fix['LOC_estimatedGeoTimestamp'] == 1234.0
    assert isinstance(fix['LOC_estimatedGeoTimestamp'], float)
    assert navigation_fix(model, 1235)['LOC_estimatedGeoTimestamp'] == 1235.0
    assert navigation_fix(model.patched({'heading_deg': 360}), 1235)['LOC_estimatedHdg'] == 0


def test_control_api_units_are_independent_of_native_display_units():
    metric = speed_display_values(100, "Kilometers")
    imperial = speed_display_values(100, "Miles")
    assert metric["VAPI_vehicleSpeed"] == imperial["VAPI_vehicleSpeed"] == pytest.approx(27.7777778)
    assert metric["VAPI_displaySpeed"] == 100
    assert imperial["VAPI_displaySpeed"] == 62
    assert metric['VAPI_speedUnits'] == 1
    assert imperial['VAPI_speedUnits'] == 0
    assert speed_display_values(39.28, "Miles")["VAPI_displaySpeed"] == 24
    assert speed_display_values(39.28, "Kilometers")["VAPI_displaySpeed"] == 39
    assert speed_display_values(39.8, "Kilometers")["VAPI_displaySpeed"] == 40


def test_readback_tolerance_is_half_the_rendered_fractional_digit():
    assert equivalent(10.911, 39.28 / 3.6)
    assert equivalent(1.001, 1.0005)
    assert not equivalent(1.001, 1.0004)


def test_preference_sync_propagates_both_ways_without_bouncing():
    sync = PreferenceSync()
    assert sync.choose("units", "Miles", "Kilometers") == ("center", "Miles", False)
    sync.accepted("units", "Miles")
    assert sync.choose("units", "Miles", "Miles") == (None, "Miles", False)
    assert sync.choose("units", "Miles", "Kilometers") == ("cluster", "Kilometers", False)
    sync.accepted("units", "Kilometers")
    assert sync.choose("units", "Kilometers", "Kilometers") == (None, "Kilometers", False)
    assert sync.choose("units", "Miles", "Kilometers") == ("center", "Miles", False)


def test_simultaneous_changes_are_explicit_and_restarts_keep_live_peer_values():
    sync = PreferenceSync()
    sync.accepted("volume", 4)
    assert sync.choose("volume", 5, 6) == ("center", 5, True)
    assert sync.choose("volume", 4, 3, {"cluster"}) == ("center", 4, False)
    assert sync.choose("volume", 3, 4, {"center"}) == ("cluster", 4, False)


def test_registered_but_unset_preferences_receive_the_valid_peer_value():
    sync = PreferenceSync()
    assert sync.choose("timezone", "America/Los_Angeles", None) == ("center", "America/Los_Angeles", False)
    assert sync.choose("timezone", None, "Asia/Shanghai") == ("cluster", "Asia/Shanghai", False)


def test_santa_can_be_enabled_disabled_and_survive_either_display_restart():
    name = 'GUI_HoHoHoMode'
    assert name in PREFERENCES
    sync = PreferenceSync()
    sync.choose(name, 0, 0)
    assert sync.choose(name, 1, 0) == ('center', 1, False)
    sync.accepted(name, 1)
    assert sync.choose(name, 1, 0, {'cluster'}) == ('center', 1, False)
    assert sync.choose(name, 0, 1, {'center'}) == ('cluster', 1, False)
    assert sync.choose(name, 0, 1) == ('center', 0, False)
    sync.accepted(name, 0)
    assert sync.choose(name, 0, 0) == (None, 0, False)


def test_playback_is_center_owned_and_empty_strings_clear_instrument_metadata():
    sync = PreferenceSync()
    for name in CENTER_CHANNELS:
        assert sync.choose(name, 'new', 'stale', {'center'}) == ('center', 'new', False)
        assert sync.choose(name, None, 'stale') == (None, None, False)
        assert sync.choose(name, '', 'stale') == ('center', '', False)
    display = FakeDisplay()
    display.values['title'] = ''
    assert DisplayWriter(display).read('title') == (True, '')


def test_service_mode_is_center_owned_and_propagates_to_the_cluster():
    sync = PreferenceSync()
    assert 'GUI_serviceMode' in CENTER_CHANNELS
    assert sync.choose('GUI_serviceMode', True, False) == ('center', True, False)
    assert sync.choose('GUI_serviceMode', False, True) == ('center', False, False)


def test_transport_showroom_and_dyno_modes_are_off_by_default_and_map_to_firmware_names():
    model = VehicleServices()
    assert (model.transport_mode, model.showroom_mode, model.dyno_mode) == (False, False, False)
    assert all(FIELD_SPECS[name]['group'] == 'modes' for name in ('transport_mode', 'showroom_mode', 'dyno_mode'))
    on = display_values(model.patched({'transport_mode': True, 'showroom_mode': True, 'dyno_mode': True}))
    assert on['transport_mode'] == {'GUI_transportMode': True, 'MCU_transportModeOn': True}
    assert on['showroom_mode'] == {'GUI_showroomMode': True, 'MCU_showroomModeOn': True}
    assert on['dyno_mode'] == {'VAPI_dynoMode': True}
    assert REQUEST_FIELDS['transport_mode'] == 'GUI_transportMode'
    with pytest.raises(ValueError):
        model.patched({'dyno_mode': 'on'})


class FakeDisplay:
    def __init__(self):
        self.values = {"speed": 0.0, "mute": False, "rejected": 0.0, "ignored": 0.0}
        self.writes = []
        self.reads = []

    def DataGetValueRequest(self, name, timeout):
        self.reads.append(name)
        value = self.values.get(name)
        return name in self.values, str(value).lower() if isinstance(value, bool) else str(value)

    def DataSetValueRequest(self, name, value, timeout):
        self.writes.append((name, value))
        if name == "rejected":
            return False
        if name != "ignored":
            self.values[name] = value
        return True


def batch_calls(interface, method, arguments):
    result = {}
    for name, args in arguments.items():
        value = getattr(interface, method)(*args, timeout=.3)
        result[name] = value if isinstance(value, tuple) else (value,)
    return result


def test_startup_profile_verifies_readback_and_respects_overrides():
    # Load only this worker function, without starting its D-Bus loop or threads.
    import ast
    from pathlib import Path
    path = Path(__file__).parents[1] / 'infotainment_lab/runtime/keep-awake.py'
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'apply_vehicle_profile')
    profile = {'speed': 1, 'ignored': 5, 'rejected': 4, 'unknown': 2}
    scope = {'os': __import__('os'), 'vehicle_profile': profile, 'config_values': {'speed': 10, 'GUI_language': 'English'},
             'car_config': lambda: set(profile), 'DisplayWriter': DisplayWriter,
             'typed': lambda v: v, 'call_many': batch_calls}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
    display = FakeDisplay()
    result = scope['apply_vehicle_profile'](display)
    assert result == {'speed': 'accepted', 'ignored': 'mismatch', 'rejected': 'rejected', 'unknown': 'unsupported'}
    assert display.values['speed'] == 10 and 'GUI_language' not in display.values
    assert display.reads.count('ignored') == 2  # A successful setter with unchanged readback is not accepted.


@pytest.mark.parametrize('batch', [None, batch_calls])
def test_explicit_local_fsd_setting_recovers_from_later_native_default(batch):
    from infotainment_lab.config_csv import pending_overrides
    display = FakeDisplay()
    display.values['FEATURE_fullSelfDriving'] = False
    requested = {'FEATURE_fullSelfDriving': True}
    writer = DisplayWriter(display, batch=batch)
    assert writer.apply({'config': requested})[0] == {'config': 'accepted'}
    display.values['FEATURE_fullSelfDriving'] = False  # A later firmware publisher replaces it.
    todo = pending_overrides(requested, requested, set(), requested, refresh=True)
    report, details = writer.apply({'config': todo}, verify_cached=True)
    assert report == {'config': 'accepted'}
    assert details['config']['FEATURE_fullSelfDriving'] == 'accepted'
    assert display.values['FEATURE_fullSelfDriving'] is True
    assert len(display.writes) == 2


def test_numeric_vehicle_enum_labels_keep_their_string_type_on_readback():
    display = FakeDisplay()
    display.values.update(VAPI_chassisType='Y', VAPI_trim='74')
    writer = DisplayWriter(display, batch=batch_calls)
    report, details = writer.apply({'profile': {'VAPI_chassisType': '3', 'VAPI_trim': '74'}})
    assert report == {'profile': 'accepted'}
    assert details['profile'] == {'VAPI_chassisType': 'accepted', 'VAPI_trim': 'accepted'}
    assert display.writes == [('VAPI_chassisType', '3')]
    assert writer.read('VAPI_chassisType') == (True, '3')


def test_native_coordinate_pair_has_verified_readback_and_restores_lost_location():
    class CoordinateDisplay(FakeDisplay):
        def __init__(self):
            super().__init__()
            self.values['LOC_geoLocation'] = '(0.000000 N, 0.000000 E)'

        def DataSetValueRequest(self, name, value, timeout):
            self.writes.append((name, value))
            lat, lon = value
            self.values[name] = f"({abs(lat):.6f} {'N' if lat >= 0 else 'S'}, {abs(lon):.6f} {'E' if lon >= 0 else 'W'})"
            return True

    display = CoordinateDisplay()
    writer = DisplayWriter(display)
    requested = {'gps': {'LOC_geoLocation': [-12.345678, 34.567891]}}
    assert writer.apply(requested)[0] == {'gps': 'accepted'}
    assert writer.read('LOC_geoLocation') == (True, [-12.345678, 34.567891])
    display.values['LOC_geoLocation'] = '(0.000000 N, 0.000000 E)'
    assert writer.apply(requested, verify_cached=True)[0] == {'gps': 'accepted'}
    assert len(display.writes) == 2


@pytest.mark.parametrize('batch', [None, batch_calls])
def test_display_acknowledgement_requires_readback_not_just_set_success(batch):
    display = FakeDisplay()
    writer = DisplayWriter(display, batch=batch)
    report, detail = writer.apply({"drive": {"speed": 22}, "settings": {"mute": True},
                                   "absent": {"unknown": 1}, "refused": {"rejected": 2},
                                   "not_applied": {"ignored": 3}, "stored": {}})
    assert report == {"drive": "accepted", "settings": "accepted", "absent": "unsupported",
                      "refused": "rejected", "not_applied": "mismatch", "stored": "local-model"}
    assert detail["not_applied"] == {"ignored": "mismatch"}
    assert "ignored" not in writer.cache


@pytest.mark.parametrize('label,value', [('Forwards', 0), ('Backwards', 1)])
def test_vehicle_direction_normalizes_the_native_enum_readback(label, value):
    display = FakeDisplay()
    display.values['VAPI_vehicleDirection'] = label
    writer = DisplayWriter(display)
    report, _ = writer.apply({'gear': {'VAPI_vehicleDirection': value}})
    assert report['gear'] == 'accepted'
    assert display.writes == []


@pytest.mark.parametrize('label,value', [('MPH', 0), ('KPH', 1)])
def test_speed_unit_enum_readback_matches_the_requested_display_label(label, value):
    display = FakeDisplay()
    display.values['VAPI_speedUnits'] = label
    report, _ = DisplayWriter(display).apply({'speed_kph': {'VAPI_speedUnits': value}})
    assert report['speed_kph'] == 'accepted'
    assert display.writes == []


@pytest.mark.parametrize('batch', [None, batch_calls])
def test_unchanged_control_frames_do_no_bus_io_but_periodic_verification_recovers_drift(batch):
    display = FakeDisplay()
    writer = DisplayWriter(display, batch=batch)
    values = {"drive": {"speed": 50}}
    writer.apply(values)
    before = len(display.reads), len(display.writes)
    writer.apply(values)
    assert (len(display.reads), len(display.writes)) == before
    display.values["speed"] = 0
    writer.apply(values, verify_cached=True)
    assert display.values["speed"] == 50
    assert len(display.writes) == before[1] + 1


def test_batch_write_uses_three_roundtrips_and_keeps_failed_values_retryable():
    display = FakeDisplay()
    calls = []

    def batch(interface, method, arguments):
        calls.append((method, tuple(arguments)))
        return batch_calls(interface, method, arguments)

    writer = DisplayWriter(display, batch=batch)
    writer.apply({'drive': {'speed': 25}, 'sound': {'mute': True}})
    assert calls == [('DataGetValueRequest', ('speed', 'mute')),
                     ('DataSetValueRequest', ('speed', 'mute')),
                     ('DataGetValueRequest', ('speed', 'mute'))]
    display.values['speed'] = 0

    def failing_batch(interface, method, arguments):
        if method == 'DataSetValueRequest':
            raise TimeoutError('display temporarily unresponsive')
        return batch_calls(interface, method, arguments)

    writer.batch = failing_batch
    with pytest.raises(TimeoutError):
        writer.apply({'drive': {'speed': 25}}, verify_cached=True)
    assert 'speed' not in writer.cache
    assert writer.supported['speed'] is True
    writer.batch = batch_calls
    assert writer.apply({'drive': {'speed': 25}})[0]['drive'] == 'accepted'
    assert display.values['speed'] == 25


def test_failed_batch_read_does_not_poison_support_detection():
    def batch(interface, method, arguments):
        raise TimeoutError('display temporarily unresponsive')

    display = FakeDisplay()
    writer = DisplayWriter(display, batch=batch)
    with pytest.raises(TimeoutError):
        writer.read_many(['speed', 'unknown'])
    assert writer.supported == {}
    writer.batch = batch_calls
    assert writer.read_many(['speed', 'unknown']) == {'speed': (True, 0), 'unknown': (False, None)}


def test_unsupported_reads_are_cached_until_the_display_owner_restarts():
    display = FakeDisplay()
    writer = DisplayWriter(display)
    assert writer.read("clockFormat") == (False, None)
    assert writer.read("clockFormat") == (False, None)
    assert display.reads.count("clockFormat") == 1
    display.values["clockFormat"] = "24h"
    assert writer.read("clockFormat") == (False, None)
    assert DisplayWriter(display).read("clockFormat") == (True, "24h")


def test_decoder_preserves_boolean_and_drops_invalid_values():
    assert decode_value("false") is False
    assert decode_value("true") is True
    assert decode_value("12.500") == 12.5
    assert decode_value("<invalid>") is None
    assert decode_value("nan") is None
    assert decode_value("Miles") == "Miles"


def test_media_network_clears_online_state_after_connectivity_is_lost():
    online = media_network_values({'online': True, 'ip': '192.0.2.1'})
    local_only = media_network_values({'online': False, 'ip': '192.0.2.1'})
    offline = media_network_values({'online': False, 'ip': ''})
    assert online['CONN_connectedToInternet'] is True
    assert online['LINK_wifiState'] == 'online'
    assert local_only['CONN_connectedToInternet'] is False
    assert local_only['CONN_wifiConnected'] is True
    assert local_only['LINK_wifiState'] == 'ready'
    assert offline['CONN_wifiConnected'] is False and offline['LINK_linkState'] == ''
    assert offline['LINK_wifiState'] == 'idle'
    assert not any(name.startswith(('AUTH_', 'VAPI_', 'CAPI_')) for name in online)


def test_replay_gps_requires_committed_fresh_frame_and_respects_takeover():
    status = {"phase": "playing", "frame_ready": True, "updated_at": 100,
              "request_id": "old", "recorded_metadata": {"latitude_deg": 37, "longitude_deg": -122, "heading_deg": 80}}
    assert replay_location(status, {}, 100.2).latitude_deg == 37
    assert replay_location(status, {"action": "manual", "id": "old"}, 100.2) is not None
    assert replay_location(status, {"action": "manual", "id": "new"}, 100.2) is None
    assert replay_location(status, {}, 101.1) is None
    assert replay_location(status | {"phase": "seeking-playing"}, {}, 100.2) is None
    assert replay_location(status | {"phase": "manual"}, {}, 100.2) is None
    assert replay_location(status | {"frame_ready": False}, {}, 100.2) is None


@pytest.mark.parametrize('batch', [None, batch_calls])
def test_skipped_names_are_left_to_the_user_override(batch):
    display = FakeDisplay()
    writer = DisplayWriter(display, batch=batch)
    writer.skip = {'speed'}
    report, detail = writer.apply({'drive': {'speed': 22}, 'settings': {'mute': True}, 'config': {'speed': 5}})
    assert detail['drive'] == {} and detail['settings'] == {'mute': 'accepted'}
    assert detail['config'] == {'speed': 'accepted'} and display.values['speed'] == 5


def test_power_meter_accepts_drive_and_regen_kilowatts():
    assert VehicleServices.parse({"power_level": 400}).power_level == 400
    model = VehicleServices.parse({"power_level": -100})
    assert display_values(model)["power_level"] == {"VAPI_powerLevel": -100.0}
    for value in (400.5, -100.5):
        with pytest.raises(ValueError, match="power_level"):
            VehicleServices.parse({"power_level": value})


def test_odometer_is_sent_in_miles_for_the_service_panel():
    # The Service Mode panel reads VAPI_odometer in miles and shows "mi / km".
    model = VehicleServices.parse({"odometer_km": 16093.44})
    assert display_values(model)["odometer_km"] == {"VAPI_odometer": pytest.approx(10000)}
    assert VehicleServices().odometer_km == 10000
    for value in (-1, 2000001):
        with pytest.raises(ValueError, match="odometer_km"):
            VehicleServices.parse({"odometer_km": value})
