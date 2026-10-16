from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'infotainment_lab'))
from native_dbc import decode, load


def test_scaled_signed_motorola_enums_and_mux_are_decoded_without_lab_definitions(tmp_path):
    path = tmp_path / 'owned.dbc'
    path.write_text('''BO_ 800 Example: 4 Node
 SG_ page M : 0|4@1+ (1,0) [0|15] ""
 SG_ temperature m1 : 8|8@1- (0.5,-10) [-74|53.5] "C"
 SG_ state m2 : 8|8@1+ (1,0) [0|255] ""
 SG_ pressure : 23|16@0+ (0.01,0) [0|655.35] "bar"
VAL_ 800 state 7 "ACTIVE";
''')
    message = load(path)[800]
    values, warning = decode(message, bytes.fromhex('01 FC 01 2C'))
    assert not warning
    assert {v['signal']: v['value'] for v in values} == {'page': 1, 'temperature': -12, 'pressure': 3}
    values, _ = decode(message, bytes.fromhex('02 07 01 2C'))
    assert {v['signal']: v['value'] for v in values} == {'page': 2, 'state': 'ACTIVE', 'pressure': 3}


def test_partial_dbc_overlap_and_short_packets_are_not_silently_decoded(tmp_path):
    path = tmp_path / 'partial.dbc'
    path.write_text('''BO_ 7 Example: 2 Node
 SG_ selector : 0|8@1+ (1,0) [0|255] ""
 SG_ first : 8|8@1+ (1,0) [0|255] ""
 SG_ second : 8|8@1+ (1,0) [0|255] ""
''')
    message = load(path)[7]
    values, warning = decode(message, b'\x01\x20')
    assert [v['signal'] for v in values] == ['selector']
    assert '2 ambiguous' in warning
    assert decode(message, b'\x01')[0] == []


def test_extended_mux_ranges_native_enum_and_unknown_fields(tmp_path):
    path = tmp_path / 'mux.dbc'
    path.write_text('''BO_ 30 Example: 2 Node
 SG_ selector M : 0|8@1+ (1,0) [0|255] ""
 SG_ mode m0 : 8|8@1+ (1,0) [0|255] ""
 SG_MUL_VAL_ 30 mode selector 2-4;
''')
    message = load(path)[30]
    native = {'signals': [{'name': 'mode', 'unit': '', 'choices': {'7': 'CURRENT_FIRMWARE_NAME'}}]}
    values, _ = decode(message, b'\x03\x07', native)
    assert [v['value'] for v in values] == ['CURRENT_FIRMWARE_NAME']
    assert decode(message, b'\x01\x07', native)[0] == []
