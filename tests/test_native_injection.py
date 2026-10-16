import json
from pathlib import Path
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'infotainment_lab'))
from core import atomic_json, load_json
import native_injection as injection
from native_dbc import load, patch


@pytest.fixture
def definitions(tmp_path):
    path = tmp_path / 'example.dbc'
    path.write_text('''BO_ 800 Example: 4 Node
 SG_ mode : 0|4@1+ (1,0) [0|15] ""
 SG_ temperature : 8|8@1- (0.5,-10) [-74|53.5] "C"
 SG_ pressure : 23|16@0+ (0.01,0) [0|655.35] "bar"
''')
    metadata = {800: {'name': 'Example', 'signals': [
        {'name': 'mode', 'unit': '', 'choices': {'2': 'ON'}},
        {'name': 'temperature', 'unit': 'C', 'choices': {}},
        {'name': 'pressure', 'unit': 'bar', 'choices': {}}]}}
    return load(path), metadata


def config(state, rules, revision='v1', operation='save', key='r1'):
    atomic_json(state / 'native-injection-config.json',
                {'revision': revision, 'rules': rules, 'operation': operation, 'key': key})


def rule(enabled=True):
    return {'key': 'r1', 'name': 'Example echo', 'identifier': 800,
            'edits': {'mode': 'ON'}, 'enabled': enabled}


def test_patch_preserves_unselected_bits_and_encodes_units_sign_and_endian(definitions):
    messages, metadata = definitions
    original = bytes.fromhex('F1 FC 01 2C')
    assert patch(messages[800], original, {'mode': 'ON'}, metadata[800]) == bytes.fromhex('F2 FC 01 2C')
    edited = patch(messages[800], original, {'temperature': '-11', 'pressure': '5'}, metadata[800])
    assert edited == bytes.fromhex('F1 FE 01 F4')
    for changes in ({'mode': 16}, {'mode': -1}, {'mode': 1.5}, {'mode': 'NaN'},
                    {'mode': 'Infinity'}, {'mode': 'BAD'}, {'unknown': 0}, {}):
        with pytest.raises(ValueError):
            patch(messages[800], original, changes, metadata[800])


def test_full_64_bit_edits_are_exact(tmp_path):
    path = tmp_path / 'wide.dbc'
    path.write_text('BO_ 1 Wide: 8 Node\n SG_ counter : 0|64@1+ (1,0) [0|0] ""\n')
    metadata = {'name': 'Wide', 'signals': [{'name': 'counter', 'choices': {}}]}
    assert patch(load(path)[1], b'\0' * 8, {'counter': '18446744073709551615'}, metadata) == b'\xff' * 8


def test_inactive_and_ambiguous_mux_overrides_are_refused(tmp_path):
    path = tmp_path / 'mux.dbc'
    path.write_text('''BO_ 1 Mux: 2 Node
 SG_ page M : 0|8@1+ (1,0) [0|255] ""
 SG_ first m1 : 8|8@1+ (1,0) [0|255] ""
 SG_ second m2 : 8|8@1+ (1,0) [0|255] ""
''')
    message = load(path)[1]
    metadata = {'name': 'Mux', 'signals': [{'name': n, 'choices': {}} for n in ('page', 'first', 'second')]}
    assert patch(message, b'\x01\x30', {'first': 7}, metadata) == b'\x01\x07'
    for edits in ({'second': 3}, {'page': 2, 'first': 3}):
        with pytest.raises(ValueError):
            patch(message, b'\x01\x30', edits, metadata)


def test_continuous_echo_only_uses_new_confirmed_sends_and_cannot_observe_itself(tmp_path, definitions, monkeypatch):
    messages, metadata = definitions
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(('127.0.0.102', 0))
        receiver.settimeout(.05)
        monkeypatch.setattr(injection, 'DESTINATION', receiver.getsockname())
        engine = injection.InjectionEngine(tmp_path)
        try:
            config(tmp_path, [rule()])
            engine.update(messages, metadata, {800: bytes.fromhex('F1 FC 01 2C')}, 'dbc-v1')
            # Enabling does not replay the old sample.
            with pytest.raises(socket.timeout):
                receiver.recv(100)
            port = receiver.getsockname()[1]
            engine.observe(2, 800, bytes.fromhex('F1 FC 01 2C'), port, 1)
            engine.observe(1, 801, bytes.fromhex('F1 FC 01 2C'), port, 2)
            engine.observe(1, 800, bytes.fromhex('F1 FC 01 2C'), 1, 3)
            engine.observe(1, 800, bytes.fromhex('F1 FC 01 2C'), port, 4)
            assert receiver.recv(100) == bytes.fromhex('23 20 F2 FC 01 2C 00 00 00 00')
            engine.observe(1, 800, bytes.fromhex('A1 FA 01 2D'), port, 5)
            assert receiver.recv(100) == bytes.fromhex('23 20 A2 FA 01 2D 00 00 00 00')
            with pytest.raises(socket.timeout):
                receiver.recv(100)
            assert engine.rules[0]['echoes'] == 2
            assert engine.rules[0]['last_sequence'] == 5
            config(tmp_path, [rule(False)], 'v2', operation='stop')
            engine.update(messages, metadata, {800: b'\0' * 4}, 'dbc-v1')
            engine.observe(1, 800, b'\0' * 4, port, 6)
            assert engine.rules[0]['echoes'] == 2
        finally:
            engine.close()


def test_restart_dbc_change_and_unrelated_edits_do_not_resume_echoes(tmp_path, definitions):
    messages, metadata = definitions
    config(tmp_path, [rule()])
    engine = injection.InjectionEngine(tmp_path)
    try:
        engine.update(messages, metadata, {800: b'\0' * 4}, 'dbc-v1')
        assert not engine.rules[0]['enabled']
        config(tmp_path, [rule()], 'v2', operation='enable')
        engine.update(messages, metadata, {800: b'\0' * 4}, 'dbc-v1')
        assert engine.rules[0]['enabled']
        engine.update(messages, metadata, {800: b'\0' * 4}, 'dbc-v2')
        assert not engine.rules[0]['enabled']
        config(tmp_path, [rule()], 'v3', operation='save', key='other')
        engine.update(messages, metadata, {800: b'\0' * 4}, 'dbc-v2')
        assert not engine.rules[0]['enabled']
    finally:
        engine.close()


def test_invalid_override_is_reported_and_stays_disabled(tmp_path, definitions):
    messages, metadata = definitions
    engine = injection.InjectionEngine(tmp_path)
    try:
        invalid = rule()
        invalid['edits'] = {'mode': 500}
        config(tmp_path, [invalid])
        engine.update(messages, metadata, {800: b'\0' * 4}, 'dbc-v1')
        assert not engine.rules[0]['enabled']
        assert 'range' in engine.rules[0]['error']
    finally:
        engine.close()


def test_config_command_waits_for_worker_readback_and_reports_rejection(tmp_path, definitions):
    messages, metadata = definitions
    atomic_json(tmp_path / 'status.json', {'phase': 'running'})
    engine = injection.InjectionEngine(tmp_path)
    stopping = threading.Event()

    def worker():
        while not stopping.is_set():
            engine.update(messages, metadata, {800: b'\0' * 4}, 'dbc-v1')
            atomic_json(tmp_path / 'native-traffic.json', {'updated_at': time.time(), 'injection': engine.snapshot()})
            stopping.wait(.02)

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        deadline = time.monotonic() + 1
        while not (tmp_path / 'native-traffic.json').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        saved = injection.change_config(tmp_path, {'operation': 'save', 'name': 'My echo',
                                'identifier': 800, 'edits': {'mode': 'ON'}})
        key = saved['rules'][0]['key']
        assert saved['injection'] and not saved['error'] and not saved['rules'][0]['enabled']
        enabled = injection.change_config(tmp_path, {'operation': 'enable', 'key': key})
        assert enabled['rules'][0]['enabled']
        stopped = injection.change_config(tmp_path, {'operation': 'stop'})
        assert not stopped['rules'][0]['enabled']
        rejected = injection.change_config(tmp_path, {'operation': 'save', 'name': 'Invalid',
                                    'identifier': 800, 'edits': {'mode': 'bad'}})
        assert rejected['error']
        assert not any(r['enabled'] for r in rejected['rules'])
    finally:
        stopping.set()
        thread.join(2)
        engine.close()


def test_stopped_device_cannot_accept_rule_activation(tmp_path):
    with pytest.raises(ValueError, match='Start or restart'):
        injection.change_config(tmp_path, {'operation': 'enable', 'key': 'old'})
