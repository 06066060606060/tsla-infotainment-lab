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
