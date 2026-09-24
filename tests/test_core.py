import json
import math
from pathlib import Path

import pytest

from infotainment_lab.core import atomic_json, load_json, profile_for, public_report, safe_id, validate_image
from infotainment_lab.simulation import Simulation, display_values


@pytest.mark.parametrize('value', ['../mount', '/etc/passwd', 'A'*16, '', 'abc', '0'*17])
def test_library_identifier_cannot_escape_its_directory(value):
    with pytest.raises(ValueError):
        safe_id(value)


def test_profile_requires_both_version_and_variant():
    assert profile_for('2026.26.6.1', 'modelsx_info2')
    assert profile_for('2026.26.6.1', 'ryzen') is None
    assert profile_for('2026.26.6.5', 'modelsx_info2')['experimental'] is True
    assert profile_for('2026.26.6.1', 'modelsx_info2').get('experimental') is None
    assert profile_for('invalid', 'modelsx_info2') is None


def test_ice_profile_requires_identified_platform():
    profile = profile_for('2026.26.6.5', 'ice_mrb')
    assert profile['single_display'] and profile['experimental']
    assert profile_for('2026.26.6.5', '') is None
    assert profile_for('2026.26.6.5', 'ice_unknown') is None


def test_import_does_not_trust_extension(tmp_path):
    image = tmp_path / 'firmware.mcu2'
    image.write_bytes(b'not firmware')
    with pytest.raises(ValueError, match='SquashFS'):
        validate_image(image)
    image.write_bytes(b'hsqs' + bytes(100))
    assert validate_image(image) == image.resolve()


def test_atomic_write_preserves_unicode_and_leaves_no_temp_files(tmp_path):
    dest = tmp_path / 'with space' / 'state.json'
    atomic_json(dest, {'state': 'ready'})
    atomic_json(dest, {'state': 'running'})
    assert load_json(dest)['state'] == 'running'
    assert list(dest.parent.iterdir()) == [dest]


@pytest.mark.parametrize('payload', [
    {'speed_kph': math.nan}, {'brake_pct': float('inf')}, {'steering_deg': 541},
    {'throttle_pct': -1}, {'gear': 'X'}, {'indicator': 'unknown'}, {'vehicle_address': 'remote'}, [],
])
def test_simulator_rejects_invalid_inputs(payload):
    with pytest.raises((ValueError, TypeError)):
        Simulation.parse(payload)


def test_park_resets_motion_and_telemetry_has_explicit_units():
    parked = Simulation.parse({'gear': 'P', 'speed_kph': 80, 'throttle_pct': 90})
    assert parked.speed_kph == parked.throttle_pct == 0
    moving = Simulation.parse({'gear': 'D', 'speed_kph': 36, 'brake_pct': 25, 'indicator': 'hazard', 'steering_deg': 90})
    values = display_values(moving)
    assert values['speed_kph']['VAPI_vehicleSpeed'] == 10
    assert values['speed_kph']['VAPI_signedVehicleSpeed'] == 10
    assert values['speed_kph']['LOC_playbackGPS_vehicleSpeed'] == 10
    assert values['speed_kph']['VAPI_displaySpeed'] == 36
    assert values['gear']['LOC_playbackShiftState'] == 'D'
    assert values['gear']['VAPI_vehicleDirection'] == 0
    assert values['steering_deg']['VAPI_roadWheelAngle'] == pytest.approx(-90 / 14.8)
    assert values['steering_deg']['VAPI_steeringAngle'] == -90
    assert values['steering_deg']['LOC_playbackSteeringAngle'] == 90
    assert values['steering_deg']['VAPI_yawRate'] < 0
    assert values['brake_pct']['VAPI_brakePedal'] is True
    assert values['indicator']['VAPI_turnSignalActive'] == 'Both'
    assert values['indicator']['LIGHT_turnIndicatorLeft'] == values['indicator']['LIGHT_turnIndicatorRight'] == 'On'
    assert 20 < moving.turning_radius_m() < 40

    reversing = display_values(Simulation.parse({'gear': 'R', 'speed_kph': 18, 'steering_deg': 150}))
    assert reversing['speed_kph']['VAPI_signedVehicleSpeed'] == -5
    assert reversing['gear']['VAPI_vehicleDirection'] == 1
    assert reversing['steering_deg']['VAPI_yawRate'] > 0


def test_export_omits_sensitive_runtime_context():
    status = {'phase': 'running', 'host': {'ip': 'private-address'}, 'error': '/home/private/path',
              'logs': 'secret', 'browser_profile': 'secret', 'components': {'center': 'running'}}
    env = {'platform': 'Linux', 'library': [{'path': '/private/firmware'}]}
    report = json.dumps(public_report(status, env))
    assert 'secret' not in report and '/private' not in report and '/home' not in report
    assert 'private-address' not in report
    assert 'running' in report
