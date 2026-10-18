"""Public signal databases, bus profiles and the state they carry.

No network: the database files are small hand-written stand-ins placed where
a download would have put them.
"""
import json
import os
from pathlib import Path
import sys

import pytest

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='CAN emulation targets the Linux worker')
if os.name != 'nt':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
    import can_database
    import can_profiles
    import can_service
    import vehicle_can
    from can_frames import Frame, tesla_sum
    from gateway import database_routes
    from simulation import Simulation
    from vehicle_services import VehicleServices

MODEL3_VEHICLE = '''BO_ 280 DI_systemStatus: 8 VEH
 SG_ DI_systemStatusChecksum : 0|8@1+ (1,0) [0|255] "" X
 SG_ DI_systemStatusCounter : 8|4@1+ (1,0) [0|15] "" X
 SG_ DI_gear : 21|3@1+ (1,0) [0|7] "" X
 SG_ DI_accelPedalPos : 32|8@1+ (0.4,0) [0|100] "%" X
BO_ 258 VCLEFT_doorStatus: 8 VEH
 SG_ VCLEFT_frontLatchStatus : 0|4@1+ (1,0) [0|8] "" X
BO_ 962 VCLEFT_switchStatus: 8 VEH
 SG_ VCLEFT_switchStatusIndex M : 0|2@1+ (1,0) [0|2] "" X
 SG_ VCLEFT_hazardButtonPressed m0 : 3|1@1+ (1,0) [0|1] "" X
 SG_ VCLEFT_swcLeftPressed m1 : 3|1@1+ (1,0) [0|1] "" X
BO_ 646 UI_request: 8 ETH
 SG_ UI_value : 0|8@1+ (1,0) [0|255] "" X
VAL_ 280 DI_gear 1 "DI_GEAR_P" 0 "DI_GEAR_INVALID" 7 "DI_GEAR_SNA" 2 "DI_GEAR_R" 3 "DI_GEAR_N" 4 "DI_GEAR_D" ;
VAL_ 258 VCLEFT_frontLatchStatus 2 "LATCH_CLOSED" 1 "LATCH_OPENED" 0 "LATCH_SNA" ;
BA_ "GenMsgCycleTime" BO_ 258 50;
'''

MODELS_ETH = {'busMetadata': {'name': 'ETH'}, 'messages': {
    'DI_torque2': {'message_id': 4, 'length_bytes': 8, 'cycle_time': 100, 'senders': ['gtw'],
                   'messageValidation': {'messageCounter': 'DI_torque2Counter', 'messageChecksum': 'DI_torque2Checksum'},
                   'signals': {
                       'DI_vehicleSpeed': {'start_position': 16, 'width': 12, 'endianness': 'LITTLE', 'scale': .05,
                                           'offset': -25, 'signedness': 'UNSIGNED', 'units': 'MPH',
                                           'value_description': {'SNA': 4095}, 'start_value': 500.0},
                       'DI_gear': {'start_position': 12, 'width': 3, 'endianness': 'LITTLE', 'scale': 1, 'offset': 0,
                                   'signedness': 'UNSIGNED', 'units': '',
                                   'value_description': {'DI_GEAR_P': 1, 'DI_GEAR_R': 2, 'DI_GEAR_N': 3, 'DI_GEAR_D': 4}},
                       'DI_torque2Counter': {'start_position': 52, 'width': 4, 'endianness': 'LITTLE', 'scale': 1,
                                             'offset': 0, 'signedness': 'UNSIGNED', 'units': ''},
                       'DI_torque2Checksum': {'start_position': 63, 'width': 8, 'endianness': 'BIG', 'scale': 1,
                                              'offset': 0, 'signedness': 'UNSIGNED', 'units': ''}}},
    'MCU_request': {'message_id': 0x32, 'length_bytes': 2, 'cycle_time': 0, 'senders': ['mcu'],
                    'signals': {'MCU_LeftTempSetpoint_DegC': {'start_position': 0, 'width': 8, 'endianness': 'LITTLE',
                                                              'scale': .5, 'offset': 0, 'signedness': 'UNSIGNED',
                                                              'units': 'degC'}}}}}


@pytest.fixture
def model3(tmp_path):
    path = tmp_path / 'vehicle.dbc'
    path.write_text(MODEL3_VEHICLE, encoding='utf-8')
    return can_database.load_dbc(path, 'veh', period_ms=100)


def test_dbc_reader_handles_value_names_multiplexing_counters_and_cycle_times(model3):
    status, doors, switches, request = model3
    assert status.counter == 'DI_systemStatusCounter' and status.checksum == 'DI_systemStatusChecksum'
    assert status.signal('DI_gear').choices[4] == 'DI_GEAR_D'
    assert doors.period_ms == 50 and status.period_ms == 100
    assert switches.multiplexer == 'VCLEFT_switchStatusIndex' and switches.mux_values == (0, 1)
    assert request.sender == 'ETH'
    page1 = switches.decode(switches.encode({'VCLEFT_switchStatusIndex': 1, 'VCLEFT_swcLeftPressed': 1}))
    assert page1 == {'VCLEFT_switchStatusIndex': 1, 'VCLEFT_swcLeftPressed': 1}


def test_tesla_checksum_is_the_additive_one_and_is_enforced(model3):
    status = model3[0]
    frame = status.encode({'DI_gear': 'DI_GEAR_D'}, counter=3)
    assert frame.data[0] == tesla_sum(0x118, frame.data[1:])
    assert status.checksum_valid(frame)
    assert not status.checksum_valid(Frame(0x118, bytes([frame.data[0] ^ 1]) + frame.data[1:], 'veh'))


def test_signal_json_reader_keeps_layout_start_values_and_validation(tmp_path):
    path = tmp_path / 'ModelS_ETH.compact.json.json'
    path.write_text(json.dumps(MODELS_ETH), encoding='utf-8')
    torque, request = can_database.load(path, 'ethbus')
    assert torque.period_ms == 100 and torque.counter == 'DI_torque2Counter'
    assert torque.checksum == 'DI_torque2Checksum' and torque.checksum_kind == 'tesla'
    assert torque.signal('DI_vehicleSpeed').initial == pytest.approx(0)  # raw 500 → 0 mph
    assert not torque.signal('DI_torque2Checksum').little_endian
    assert request.sender == 'mcu' and request.period_ms == 0
    # A sentinel name does not turn a continuous signal into an enum.
    assert torque.decode(torque.encode({'DI_vehicleSpeed': 30}))['DI_vehicleSpeed'] == pytest.approx(30)


def test_session_state_is_encoded_and_read_back_through_the_bindings(model3, tmp_path):
    status, doors = model3[:2]
    sim = Simulation.parse({'gear': 'D', 'throttle_pct': 40})
    services = VehicleServices().patched({'driver_door_open': True})
    decoded = status.decode(status.encode(vehicle_can.database_values(status, sim, services)))
    assert decoded['DI_gear'] == 'DI_GEAR_D' and decoded['DI_accelPedalPos'] == pytest.approx(40)
    assert doors.decode(doors.encode(vehicle_can.database_values(doors, sim, services)))['VCLEFT_frontLatchStatus'] == 'LATCH_OPENED'
    assert vehicle_can.database_patches(status, {'DI_gear': 'DI_GEAR_R', 'DI_accelPedalPos': 0.0}) == \
        ({'gear': 'R', 'throttle_pct': 0.0}, {})
    path = tmp_path / 'eth.json'
    path.write_text(json.dumps(MODELS_ETH), encoding='utf-8')
    torque = can_database.load(path, 'ethbus')[0]
    mph = torque.decode(torque.encode(vehicle_can.database_values(torque, Simulation.parse({'gear': 'D', 'speed_kph': 80}), services)))
    assert mph['DI_vehicleSpeed'] == pytest.approx(80 / 1.609344, abs=.05)
    assert vehicle_can.database_patches(torque, mph)[0]['speed_kph'] == pytest.approx(80, abs=.1)


def test_generated_routes_open_reads_and_gate_infotainment_writes(model3):
    routes = {route.name: route for route in database_routes(model3, ('veh', 'ch'))}
    assert set(routes) == {'veh-to-eth', 'eth-to-veh'}
    assert routes['veh-to-eth'].accepts(Frame(0x118, b'', 'veh'))
    assert routes['eth-to-veh'].requires_unlock
    assert routes['eth-to-veh'].accepts(Frame(646, b'', 'veh'))
    assert not routes['eth-to-veh'].accepts(Frame(0x118, b'', 'veh'))


def place(root, url, text):
    path = can_profiles.local_path(url, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def test_profile_service_runs_the_full_table_and_feeds_injected_frames_back(tmp_path):
    databases = tmp_path / 'can-databases'
    place(databases, can_profiles.OPENDBC + 'tesla_model3_vehicle.dbc', MODEL3_VEHICLE)
    place(databases, can_profiles.OPENDBC + 'tesla_model3_party.dbc', 'BO_ 1 P: 1 PARTY\n SG_ v : 0|8@1+ (1,0) [0|255] "" X\n')
    service = can_service.GatewayService(tmp_path / 'session', prefer='software', endpoint=None,
                                         secret=b's', profile='model3', databases=databases)
    try:
        assert service.status()['profile'] == 'model3'
        service.handle({'action': 'state', 'simulation': {'gear': 'D'}, 'follow_session': False})
        service.step()
        trace = service.handle({'action': 'trace', 'channel': 'veh'})['frames']
        status = [item for item in trace if item.get('name') == 'DI_systemStatus']
        assert status and status[-1]['signals']['DI_gear'] == 'DI_GEAR_D'
        # The lab drive frame on 0x118 was replaced, not sent alongside.
        assert not [item for item in trace if item.get('name') == 'LAB_driveState']
        message = can_database.lookup('veh', 0x118, service.gateway.table)
        service.handle({'action': 'send', 'origin': 'bus', 'frame': {
            'channel': 'veh', 'id': '0x118', 'data': message.encode({'DI_gear': 'DI_GEAR_R'}).data.hex()}})
        assert service.simulation.gear == 'R'
    finally:
        service.bus.close()


def test_a_profile_without_its_databases_explains_how_to_fetch_them(tmp_path):
    with pytest.raises(RuntimeError, match='has not been downloaded'):
        can_profiles.definitions('model3', tmp_path)


def test_fetch_downloads_each_pinned_file_once(tmp_path):
    opened = []

    class Response:
        def __init__(self, url):
            opened.append(url)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'BO_ 1 X: 1 VEH\n'

    fetched = can_profiles.fetch('model3', tmp_path, opener=lambda url, timeout: Response(url))
    assert len(fetched) == 2 and all('28015820859e8ba4c53c11d1668a52068a5e5039' in url for url in opened)
    assert can_profiles.fetch('model3', tmp_path, opener=lambda url, timeout: Response(url)) == []
    assert len(opened) == 2
