"""Contracts for local services and two-display reconciliation, without firmware."""
import pytest

from infotainment_lab.vehicle_services import (
    CAPABILITIES, FIELD_SPECS, DisplayWriter, PreferenceSync, VehicleServices,
    decode_value, display_values, speed_display_values,
    replay_location, equivalent, PREFERENCES, CENTER_CHANNELS, media_network_values,
)


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
    assert values["heading_deg"] == {"LOC_geoHdg": 0}
    assert values["driver_door_open"]["VAPI_driverDoorAlert"] is False
    assert values["passenger_door_open"]["VAPI_doorAlert"] is True
    assert values["headlights"]["LIGHT_headlightLeft"] == "Off"
    assert values["alarm_armed"]["VAPI_alarmStatus"] == "Disarmed"
    assert display_values(model.patched({"headlights": True}))["headlights"]["LIGHT_headlightLeft"] == "On"
    assert values["tire_fl_bar"] == {}
    assert CAPABILITIES["tires"]["mode"] == "local-model"
    assert not any(name.startswith(("DAS_", "AUTH_", "CAPI_"))
                   for group in values.values() for name in group)


def test_stopped_charging_and_disabled_gps_do_not_fake_active_sources():
    values = display_values(VehicleServices())
    assert values["charge_power_kw"]["VAPI_chargerPower"] == 0
    assert values["latitude_deg"] == {"LOC_geoValidFix": False}
    assert "LOC_geoLat" not in values["latitude_deg"]


def test_control_api_units_are_independent_of_native_display_units():
    metric = speed_display_values(100, "Kilometers")
    imperial = speed_display_values(100, "Miles")
    assert metric["VAPI_vehicleSpeed"] == imperial["VAPI_vehicleSpeed"] == pytest.approx(27.7777778)
    assert metric["VAPI_displaySpeed"] == 100
    assert imperial["VAPI_displaySpeed"] == 62
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


def test_display_acknowledgement_requires_readback_not_just_set_success():
    display = FakeDisplay()
    writer = DisplayWriter(display)
    report, detail = writer.apply({"drive": {"speed": 22}, "settings": {"mute": True},
                                   "absent": {"unknown": 1}, "refused": {"rejected": 2},
                                   "not_applied": {"ignored": 3}, "stored": {}})
    assert report == {"drive": "accepted", "settings": "accepted", "absent": "unsupported",
                      "refused": "rejected", "not_applied": "mismatch", "stored": "local-model"}
    assert detail["not_applied"] == {"ignored": "mismatch"}
    assert "ignored" not in writer.cache


def test_unchanged_control_frames_do_no_bus_io_but_periodic_verification_recovers_drift():
    display = FakeDisplay()
    writer = DisplayWriter(display)
    values = {"drive": {"speed": 50}}
    writer.apply(values)
    before = len(display.reads), len(display.writes)
    writer.apply(values)
    assert (len(display.reads), len(display.writes)) == before
    display.values["speed"] = 0
    writer.apply(values, verify_cached=True)
    assert display.values["speed"] == 50
    assert len(display.writes) == before[1] + 1


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
