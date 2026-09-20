"""Signal packing, frame parsing and the lab frame table. No transport here."""
import os
from pathlib import Path
import sys

import pytest

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='CAN emulation targets the Linux worker')
if os.name != 'nt':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
    import can_database
    from can_frames import Frame, Message, Signal, crc8


def test_little_endian_signal_round_trip():
    signal = Signal('speed_kph', 8, 12, scale=.1)
    buffer = bytearray(8)
    signal.encode_into(buffer, 123.4)
    assert signal.decode(bytes(buffer)) == pytest.approx(123.4, abs=.05)


def test_big_endian_signal_round_trip():
    signal = Signal('pressure', 7, 16, scale=.02, little_endian=False)
    buffer = bytearray(8)
    signal.encode_into(buffer, 2.9)
    assert signal.decode(bytes(buffer)) == pytest.approx(2.9, abs=.02)


def test_signed_signal_keeps_sign():
    signal = Signal('angle', 0, 14, scale=.1, signed=True)
    buffer = bytearray(8)
    signal.encode_into(buffer, -181.3)
    assert signal.decode(bytes(buffer)) == pytest.approx(-181.3, abs=.05)


def test_value_outside_range_is_clamped_not_wrapped():
    signal = Signal('fan', 0, 4)
    buffer = bytearray(1)
    signal.encode_into(buffer, 99)
    assert signal.decode(bytes(buffer)) == 15


def test_enumerated_signal_uses_state_names():
    signal = Signal('gear', 0, 3, choices=('Invalid', 'P', 'R', 'N', 'D'))
    buffer = bytearray(1)
    signal.encode_into(buffer, 'D')
    assert signal.decode(bytes(buffer)) == 'D'
    with pytest.raises(ValueError):
        signal.encode_into(buffer, 'Launch')


def test_frame_rejects_impossible_payload_and_identifier():
    with pytest.raises(ValueError):
        Frame(0x118, bytes(9))
    with pytest.raises(ValueError):
        Frame(0x800)
    assert Frame(0x1FFFFFFF, b'', extended=True).length == 0


@pytest.mark.parametrize('value', [
    {'id': '0x118', 'data': '01 02 03'},
    {'id': 280, 'data': [1, 2, 3]},
    {'id': '118', 'data': '010203'},
])
def test_frame_parse_accepts_operator_input(value):
    frame = Frame.parse(value)
    assert frame.identifier == 0x118 and frame.data == b'\x01\x02\x03'


@pytest.mark.parametrize('value', [
    {'id': 'zz'}, {'id': 0x118, 'data': 'abc'}, {'id': 0x118, 'data': [300]},
    {'id': 0x118, 'bus': 'veh'}, {'id': True}, {'id': 0x118, 'extended': 'yes'},
])
def test_frame_parse_rejects_invalid_input(value):
    with pytest.raises(ValueError):
        Frame.parse(value)


def test_counter_and_checksum_are_produced_and_verified():
    message = can_database.message('LAB_driveState')
    frame = message.encode({'gear': 'D', 'speed_kph': 88.8, 'throttle_pct': 40, 'brake_pressed': 0}, counter=7)
    decoded = message.decode(frame)
    assert decoded['gear'] == 'D'
    assert decoded['speed_kph'] == pytest.approx(88.8, abs=.1)
    assert decoded['counter'] == 7
    assert message.checksum_valid(frame)
    damaged = Frame(frame.identifier, bytes([frame.data[0] ^ 0xFF]) + frame.data[1:], frame.channel)
    assert not message.checksum_valid(damaged)


def test_crc8_is_deterministic_and_order_sensitive():
    assert crc8(b'\x01\x02') == crc8(b'\x01\x02')
    assert crc8(b'\x01\x02') != crc8(b'\x02\x01')


def test_every_lab_definition_fits_its_length():
    for message in can_database.MESSAGES:
        for signal in message.signals:
            assert signal.start_bit + signal.bit_length <= message.length * 8, (message.name, signal.name)


def test_dbc_reader_parses_layout(tmp_path):
    path = tmp_path / 'lab.dbc'
    path.write_text(
        'BO_ 291 EXAMPLE_status: 8 VECTOR__INDEPENDENT\n'
        ' SG_ Speed : 8|12@1+ (0.1,0) [0|400] "km/h" Receiver\n'
        ' SG_ Angle : 24|14@1- (0.1,0) [-800|800] "deg" Receiver\n', encoding='utf-8')
    messages = can_database.load_dbc(path, channel='veh', period_ms=20)
    assert [m.name for m in messages] == ['EXAMPLE_status']
    message = messages[0]
    assert (message.identifier, message.channel, message.period_ms) == (291, 'veh', 20)
    frame = message.encode({'Speed': 55.5, 'Angle': -90.1})
    decoded = message.decode(frame)
    assert decoded['Speed'] == pytest.approx(55.5, abs=.1)
    assert decoded['Angle'] == pytest.approx(-90.1, abs=.1)


def test_dbc_reader_rejects_a_file_without_definitions(tmp_path):
    path = tmp_path / 'empty.dbc'
    path.write_text('VERSION ""\n', encoding='utf-8')
    with pytest.raises(ValueError):
        can_database.load_dbc(path)
