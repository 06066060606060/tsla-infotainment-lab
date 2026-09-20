"""Gateway routing, the locked-by-default gate and the loopback bridge.

Everything runs on the software CAN hub, so these tests need no kernel module,
no privileges and no vehicle.
"""
import json
import os
from pathlib import Path
import socket
import sys

import pytest

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='CAN emulation targets the Linux worker')
if os.name != 'nt':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
    import can_database
    from can_bus import Filter, SoftwareBus, open_bus
    from can_frames import Frame
    from gateway import EthernetBridge, Route, SecurityGateway, pack_wire, unpack_wire


@pytest.fixture
def gateway():
    instance = SecurityGateway(SoftwareBus(), secret=b'test-secret')
    yield instance
    instance.bus.close()


def unlock(gateway):
    challenge = bytes.fromhex(gateway.challenge())
    return gateway.unlock(gateway.expected_response(challenge))


def climate_frame():
    message = can_database.message('LAB_climate')
    return message.encode({'climate_on': 1, 'fan_speed': 4, 'driver_temp_c': 21,
                           'passenger_temp_c': 21, 'cabin_temp_c': 22, 'outside_temp_c': 20})


def test_write_from_ethernet_is_refused_while_locked(gateway):
    decision = gateway.from_ethernet(climate_frame())
    assert not decision.allowed and 'locked' in decision.reason
    assert gateway.bus.channel('veh').transmitted == 0


def test_write_is_accepted_after_a_correct_unlock(gateway):
    assert unlock(gateway)['unlocked'] is True
    decision = gateway.from_ethernet(climate_frame())
    assert decision.allowed and decision.route == 'eth-to-veh'
    assert gateway.bus.channel('veh').transmitted == 1


def test_wrong_response_keeps_the_session_locked(gateway):
    gateway.challenge()
    with pytest.raises(PermissionError):
        gateway.unlock('00' * 16)
    assert gateway.unlocked is False


def test_unlock_without_a_challenge_is_refused(gateway):
    with pytest.raises(PermissionError):
        gateway.unlock('00' * 16)


def test_a_challenge_is_single_use(gateway):
    challenge = bytes.fromhex(gateway.challenge())
    response = gateway.expected_response(challenge)
    gateway.unlock(response)
    with pytest.raises(PermissionError):
        gateway.unlock(response)


def test_expired_unlock_closes_the_gate():
    instance = SecurityGateway(SoftwareBus(), secret=b'test-secret', unlock_ttl_s=0)
    challenge = bytes.fromhex(instance.challenge())
    instance.unlock(instance.expected_response(challenge))
    assert instance.unlocked is False
    assert not instance.from_ethernet(climate_frame()).allowed
    instance.bus.close()


def test_identifier_outside_the_route_filter_is_dropped(gateway):
    unlock(gateway)
    decision = gateway.from_ethernet(Frame(0x101, bytes(8), 'veh'))
    assert not decision.allowed and 'not in the route filter' in decision.reason


def test_drive_state_cannot_be_written_from_ethernet(gateway):
    """Drive state is published outward only: no inbound write reaches it."""
    unlock(gateway)
    decision = gateway.from_ethernet(Frame(0x118, bytes(8), 'veh'))
    assert not decision.allowed and 'not in the route filter' in decision.reason
    assert gateway.bus.channel('veh').transmitted == 0


def test_no_route_to_the_chassis_channel_from_ethernet(gateway):
    unlock(gateway)
    decision = gateway.from_ethernet(Frame(0x352, bytes(8), 'ch'))
    assert not decision.allowed and 'no route' in decision.reason
    assert gateway.bus.channel('ch').transmitted == 0


def test_invalid_checksum_is_refused_even_when_unlocked(gateway):
    unlock(gateway)
    frame = climate_frame()
    routed = gateway.from_ethernet(frame)
    assert routed.allowed
    message = can_database.message('LAB_lighting')
    # A definition with no checksum stays accepted; a corrupted checksummed
    # frame on a gated route does not.
    assert gateway.from_ethernet(message.encode({'indicator': 'Left', 'light_mode': 'On'})).allowed


def test_bus_frames_are_published_towards_ethernet(gateway):
    message = can_database.message('LAB_driveState')
    gateway.bus.send(message.encode({'gear': 'D', 'speed_kph': 50}))
    frames = gateway.drain()
    assert [f.identifier for f in frames] == [0x118]
    assert gateway.decode(frames[0])['gear'] == 'D'


def test_channel_mirror_forwards_lighting_to_the_powertrain_channel(gateway):
    gateway.bus.inject(can_database.message('LAB_lighting').encode({'indicator': 'Right'}))
    assert any(f['id'] == 0x3F5 for f in gateway.bus.channel('ch').trace())


def test_unlisted_identifier_on_a_channel_is_not_published(gateway):
    gateway.bus.inject(Frame(0x7AA, bytes(2), 'veh'))
    assert gateway.drain() == []


def test_rate_limit_rejects_a_flood(gateway):
    unlock(gateway)
    frame = climate_frame()
    outcomes = [gateway.from_ethernet(frame).allowed for _ in range(600)]
    assert outcomes[0] is True and outcomes[-1] is False
    assert gateway.counts['rate_limited'] > 0


def test_status_reports_routes_and_counters(gateway):
    status = gateway.status()
    assert status['unlocked'] is False
    assert {'eth-to-veh', 'veh-drive-to-eth'} <= {route['name'] for route in status['routes']}
    assert set(status['counters']) == {'routed', 'blocked', 'unknown', 'rate_limited'}


def test_a_route_with_no_filter_forwards_nothing():
    instance = SecurityGateway(SoftwareBus(), routes=(Route('open', 'eth', 'veh'),), secret=b's')
    assert not instance.from_ethernet(climate_frame()).allowed
    instance.bus.close()


def test_filter_mask_matches_a_range():
    assert Filter(0x100, 0x7F0).matches(Frame(0x10F, b'', 'veh'))
    assert not Filter(0x100, 0x7F0).matches(Frame(0x110, b'', 'veh'))


def test_wire_format_round_trip(gateway):
    frame = Frame(0x1ABCDEF, b'\x01\x02', 'party', extended=True)
    restored = unpack_wire(pack_wire(frame, gateway.channels), gateway.channels)
    assert (restored.identifier, restored.data, restored.channel, restored.extended) == \
        (0x1ABCDEF, b'\x01\x02', 'party', True)


@pytest.mark.parametrize('payload', [b'', b'\x00', b'\x00\x00\x00\x00\x01\x18\x08\x01', b'\xff\x00\x00\x00\x01\x18\x00'])
def test_wire_format_rejects_malformed_messages(payload, gateway):
    with pytest.raises(ValueError):
        unpack_wire(payload, gateway.channels)


def test_bridge_only_binds_the_loopback(gateway):
    with pytest.raises(ValueError):
        EthernetBridge(gateway, ('0.0.0.0', 0))


def test_bridge_unlock_and_frame_exchange(gateway):
    bridge = EthernetBridge(gateway, ('127.0.0.1', 0))
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.settimeout(2)
    try:
        client.sendto(json.dumps({'action': 'challenge'}).encode(), bridge.endpoint)
        bridge.service(.05)
        challenge = json.loads(client.recv(4096))['challenge']
        response = gateway.expected_response(bytes.fromhex(challenge))
        client.sendto(json.dumps({'action': 'unlock', 'response': response}).encode(), bridge.endpoint)
        bridge.service(.05)
        assert json.loads(client.recv(4096))['unlocked'] is True

        client.sendto(pack_wire(climate_frame(), gateway.channels), bridge.endpoint)
        report = bridge.service(.05)
        assert report['accepted'] == 1

        gateway.bus.send(can_database.message('LAB_energy').encode({'battery_percent': 62}))
        bridge.service(.05)
        # The accepted climate write was itself published back; read until the
        # energy frame arrives.
        energy = None
        for _ in range(10):
            published = unpack_wire(client.recv(4096), gateway.channels)
            if published.identifier == 0x352:
                energy = published
                break
        assert energy is not None
        assert gateway.decode(energy)['battery_percent'] == pytest.approx(62, abs=.2)
    finally:
        client.close()
        bridge.close()


def test_bridge_reports_a_refusal_to_the_sender(gateway):
    bridge = EthernetBridge(gateway, ('127.0.0.1', 0))
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.settimeout(2)
    try:
        client.sendto(pack_wire(climate_frame(), gateway.channels), bridge.endpoint)
        bridge.service(.05)
        assert json.loads(client.recv(4096))['ok'] is False
        client.sendto(b'{"action": "teleport"}', bridge.endpoint)
        bridge.service(.05)
        assert json.loads(client.recv(4096))['ok'] is False
    finally:
        client.close()
        bridge.close()


def test_open_bus_falls_back_to_software_when_socketcan_is_unavailable():
    bus = open_bus(prefer='software')
    assert bus.backend == 'software'
    with pytest.raises(ValueError):
        bus.send(Frame(0x118, b'', 'nosuch'))
    bus.close()
