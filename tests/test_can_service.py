"""State projection onto lab frames, and the service's control contract."""
import os
from pathlib import Path
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='CAN emulation targets the Linux worker')
if os.name != 'nt':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
    import can_database
    import can_service
    import vehicle_can
    from can_bus import SoftwareBus
    from can_frames import Frame
    from simulation import Simulation
    from vehicle_services import VehicleServices


def test_periodic_transmitter_respects_each_period():
    transmitter = vehicle_can.PeriodicTransmitter()
    sim, services = Simulation(gear='D', speed_kph=60), VehicleServices()
    first = {f.identifier for f in transmitter.tick(sim, services, now=0)}
    assert 0x118 in first and 0x352 in first
    soon = {f.identifier for f in transmitter.tick(sim, services, now=.02)}
    assert 0x118 in soon and 0x352 not in soon  # 10 ms versus 200 ms


def test_counter_rolls_over_within_four_bits():
    transmitter = vehicle_can.PeriodicTransmitter()
    message = can_database.message('LAB_driveState')
    counters = [message.decode(transmitter.build(message, {'gear': 'P'}))['counter'] for _ in range(18)]
    assert counters[:3] == [0, 1, 2] and counters[16] == 0


def test_drive_state_frame_carries_the_simulator_values():
    sim = Simulation(gear='R', speed_kph=12.5, throttle_pct=0, brake_pct=30)
    message = can_database.message('LAB_driveState')
    decoded = message.decode(message.encode(vehicle_can.drive_values(sim)))
    assert decoded['gear'] == 'R'
    assert decoded['speed_kph'] == pytest.approx(12.5, abs=.1)
    assert decoded['brake_pressed'] == 1


def test_steering_frame_matches_the_desktop_geometry():
    sim = Simulation(gear='D', speed_kph=36, steering_deg=148)
    message = can_database.message('LAB_steering')
    decoded = message.decode(message.encode(vehicle_can.steering_values(sim)))
    assert decoded['road_wheel_deg'] == pytest.approx(-148 / 14.8, abs=.05)
    assert decoded['yaw_rate'] < 0  # left-hand steering input, forward motion


def test_snapshot_covers_every_periodic_definition():
    frames = vehicle_can.snapshot(Simulation(), VehicleServices())
    periodic = {m.identifier for m in can_database.MESSAGES if m.period_ms}
    assert periodic <= {frame['id'] for frame in frames}


def test_inbound_climate_frame_becomes_a_state_patch():
    message = can_database.message('LAB_climate')
    decoded = message.decode(message.encode({'climate_on': 1, 'ac_on': 1, 'fan_speed': 6,
                                             'driver_temp_c': 19, 'passenger_temp_c': 23,
                                             'cabin_temp_c': 22, 'outside_temp_c': 20}))
    patch = vehicle_can.state_patch('LAB_climate', decoded)
    assert patch['fan_speed'] == 6 and patch['ac_on'] is True
    assert patch['driver_temp_c'] == pytest.approx(19, abs=.2)
    assert VehicleServices().patched(patch).fan_speed == 6


def test_only_request_frames_can_change_local_state():
    message = can_database.message('LAB_driveState')
    assert vehicle_can.state_patch('LAB_driveState', message.decode(message.encode({'gear': 'D'}))) == {}


@pytest.fixture
def service(tmp_path):
    instance = can_service.GatewayService(tmp_path, prefer='software',
                                          endpoint=('127.0.0.1', 0), secret=b'test-secret')
    yield instance
    instance.bus.close()
    if instance.bridge:
        instance.bridge.close()


def test_service_unlock_flow_and_send(service):
    challenge = service.handle({'action': 'challenge'})['challenge']
    response = service.gateway.expected_response(bytes.fromhex(challenge))
    assert service.handle({'action': 'unlock', 'response': response})['unlocked'] is True
    frame = can_database.message('LAB_lighting').encode({'indicator': 'Left', 'light_mode': 'On'})
    decision = service.handle({'action': 'send', 'origin': 'ethernet',
                               'frame': {'channel': 'veh', 'id': '0x3F5', 'data': frame.data.hex()}})
    assert decision['allowed'] is True
    assert service.services.exterior_light_mode == 'On'


def test_service_refuses_an_unknown_action(service):
    with pytest.raises(ValueError):
        service.handle({'action': 'flash-firmware'})


def test_service_state_updates_and_transmits(service):
    service.handle({'action': 'state', 'simulation': {'gear': 'D', 'speed_kph': 80}})
    service.step()
    trace = service.handle({'action': 'trace', 'channel': 'pt', 'limit': 50})['frames']
    drive = [item for item in trace if item['id'] == 0x118]
    assert drive and drive[-1]['signals']['speed_kph'] == pytest.approx(80, abs=.1)
    assert drive[-1]['name'] == 'LAB_driveState'


def test_service_can_pause_transmission(service):
    assert service.handle({'action': 'state', 'transmit': False})['transmit'] is False
    service.step()
    assert service.handle({'action': 'trace'})['frames'] == []
    with pytest.raises(ValueError):
        service.handle({'action': 'state', 'transmit': 'off'})


def test_injected_frame_appears_on_the_channel_trace(service):
    service.handle({'action': 'send', 'origin': 'bus',
                    'frame': {'channel': 'veh', 'id': '0x102', 'data': '01'}})
    trace = service.handle({'action': 'trace', 'channel': 'veh'})['frames']
    assert any(item['id'] == 0x102 and item['name'] == 'LAB_closures' for item in trace)


def test_service_rejects_an_unparsable_frame(service):
    with pytest.raises(ValueError):
        service.handle({'action': 'send', 'frame': {'id': 'nope'}})


def test_status_lists_definitions_and_environment(service):
    status = service.status()
    assert status['service'] == 'running'
    assert 'LAB_driveState' in {item['name'] for item in status['definitions']}
    assert 'socketcan_available' in status['environment']
    assert status['gateway']['unlocked'] is False


def test_load_dbc_extends_the_table(service, tmp_path):
    path = tmp_path / 'extra.dbc'
    path.write_text('BO_ 100 EXTRA_state: 8 VECTOR__INDEPENDENT\n'
                    ' SG_ Value : 0|8@1+ (1,0) [0|255] "" Receiver\n', encoding='utf-8')
    result = service.handle({'action': 'load-dbc', 'path': str(path), 'channel': 'veh'})
    assert result['loaded'] == ['EXTRA_state']
    assert can_database.lookup('veh', 100, service.gateway.table) is not None


def test_socket_control_round_trip(tmp_path):
    instance = can_service.GatewayService(tmp_path, prefer='software', endpoint=None, secret=b'test-secret')
    thread = threading.Thread(target=instance.serve, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not can_service.socket_path(tmp_path).exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert can_service.running(tmp_path)
        status = can_service.request(tmp_path, {'action': 'status'})
        assert status['gateway']['backend'] == 'software'
        with pytest.raises(RuntimeError):
            can_service.request(tmp_path, {'action': 'unlock', 'response': 'x'})
    finally:
        try:
            can_service.request(tmp_path, {'action': 'stop'})
        except (RuntimeError, OSError):
            pass
        thread.join(timeout=5)
    assert not can_service.socket_path(tmp_path).exists()


def test_request_without_a_service_explains_itself(tmp_path):
    with pytest.raises(RuntimeError, match='not running'):
        can_service.request(tmp_path, {'action': 'status'})


def test_service_follows_the_session_state_files(service, tmp_path):
    from core import atomic_json

    atomic_json(tmp_path / 'controls.json', {'gear': 'D', 'speed_kph': 97.5})
    atomic_json(tmp_path / 'vehicle-services.json', dict(VehicleServices().as_dict(), battery_percent=71))
    service.step()
    assert service.simulation.gear == 'D'
    assert service.services.battery_percent == 71
    trace = service.handle({'action': 'trace', 'channel': 'pt'})['frames']
    assert [item for item in trace if item['id'] == 0x118][-1]['signals']['speed_kph'] == pytest.approx(97.5, abs=.1)


def test_a_malformed_session_file_does_not_stop_the_bus(service, tmp_path):
    (tmp_path / 'controls.json').write_text('{ not json', encoding='utf-8')
    service.step()
    assert service.simulation.gear == 'P'
    assert service.handle({'action': 'trace'})['frames']


def test_following_the_session_can_be_turned_off(service, tmp_path):
    from core import atomic_json

    assert service.handle({'action': 'state', 'follow_session': False})['follow_session'] is False
    atomic_json(tmp_path / 'controls.json', {'gear': 'R', 'speed_kph': 5})
    service.step()
    assert service.simulation.gear == 'P'
    with pytest.raises(ValueError):
        service.handle({'action': 'state', 'follow_session': 'yes'})


def test_an_accepted_request_is_written_back_for_the_displays(service, tmp_path):
    import json as json_module

    challenge = service.handle({'action': 'challenge'})['challenge']
    service.handle({'action': 'unlock', 'response': service.gateway.expected_response(bytes.fromhex(challenge))})
    frame = can_database.message('LAB_lighting').encode({'indicator': 'Off', 'light_mode': 'Parking'})
    service.handle({'action': 'send', 'frame': {'channel': 'veh', 'id': '0x3F5', 'data': frame.data.hex()}})
    written = json_module.loads((tmp_path / 'vehicle-services.json').read_text())
    assert written['exterior_light_mode'] == 'Parking'
    service.step()  # the write-back must not be read as an external change
    assert service.services.exterior_light_mode == 'Parking'


def test_injected_drive_frame_moves_the_controls_the_displays_read(service, tmp_path):
    import json as json_module

    frame = can_database.message('LAB_driveState').encode(
        {'gear': 'D', 'speed_kph': 64.3, 'throttle_pct': 18, 'brake_pressed': 0})
    service.handle({'action': 'send', 'origin': 'bus',
                    'frame': {'channel': 'pt', 'id': '0x118', 'data': frame.data.hex()}})
    assert service.simulation.gear == 'D'
    assert service.simulation.speed_kph == pytest.approx(64.3, abs=.1)
    written = json_module.loads((tmp_path / 'controls.json').read_text())
    assert written['gear'] == 'D' and written['speed_kph'] == pytest.approx(64.3, abs=.1)
    # Replay ownership is released, exactly as a manual control does.
    assert json_module.loads((tmp_path / 'replay-request.json').read_text())['action'] == 'manual'


def test_injected_steering_and_indicator_reach_the_controls(service):
    steering = can_database.message('LAB_steering')
    service.handle({'action': 'send', 'origin': 'bus', 'frame': {
        'channel': 'pt', 'id': '0x129',
        'data': steering.encode(vehicle_can.steering_values(Simulation(steering_deg=-120))).data.hex()}})
    assert service.simulation.steering_deg == pytest.approx(-120, abs=.2)
    lighting = can_database.message('LAB_lighting')
    service.handle({'action': 'send', 'origin': 'bus', 'frame': {
        'channel': 'veh', 'id': '0x3F5', 'data': lighting.encode({'indicator': 'Both'}).data.hex()}})
    assert service.simulation.indicator == 'hazard'


def test_an_impossible_drive_frame_is_counted_not_applied(service):
    frame = can_database.message('LAB_driveState').encode({'gear': 'Invalid', 'speed_kph': 40})
    service.handle({'action': 'send', 'origin': 'bus',
                    'frame': {'channel': 'pt', 'id': '0x118', 'data': frame.data.hex()}})
    # Gear P forces a standstill, so the frame cannot claim 40 km/h in park.
    assert service.simulation.gear == 'P' and service.simulation.speed_kph == 0


def test_controls_write_back_is_skipped_when_not_following_the_session(service, tmp_path):
    service.handle({'action': 'state', 'follow_session': False})
    frame = can_database.message('LAB_driveState').encode({'gear': 'N', 'speed_kph': 10})
    service.handle({'action': 'send', 'origin': 'bus',
                    'frame': {'channel': 'pt', 'id': '0x118', 'data': frame.data.hex()}})
    assert service.simulation.gear == 'N'
    assert not (tmp_path / 'controls.json').exists()
