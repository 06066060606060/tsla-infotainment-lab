"""Odin engine stand-in for the Service Mode panel, with a synthetic catalogue (no firmware, no D-Bus)."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Linux runtime worker')
ROOT = Path(__file__).resolve().parents[1] / 'infotainment_lab'
spec = importlib.util.spec_from_file_location('odin_engine', ROOT / 'runtime/odin-engine.py')
odin_engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(odin_engine)

TASKS = [{'title': 'Lab task', 'message': {'command': 'execute', 'args': {'name': 'Common/tasks/LAB_TASK'}}}]


@pytest.fixture
def engine(tmp_path):
    odin = tmp_path / 'odin'
    (odin / 'odin_bundle/odin_bundle/networks').mkdir(parents=True)
    (odin / 'odin_bundle/odin_bundle/networks/task_data.py').write_text(json.dumps(TASKS))
    (odin / 'core/engine/assets/json').mkdir(parents=True)
    (odin / 'core/engine/assets/json/maintenance_history_en.json').write_text('[{"name": "Tyre rotation"}]')
    (odin / 'core/engine/assets/json/maintenance_history_de.json').write_text('[{"name": "Reifenwechsel"}]')
    (odin / 'core/engine/assets/whitelist').mkdir(parents=True)
    (odin / 'core/engine/assets/whitelist/rmi-gtw-config-allowlist.yaml').write_text('- audiotype\n- tpmsinstalled\n')
    engine = odin_engine.Engine(odin)
    path = tmp_path / 'engine.sock'
    threading.Thread(target=engine.listen, args=(path,), daemon=True).start()
    for _ in range(100):
        if path.exists():
            break
        time.sleep(0.01)
    engine.path = path
    return engine


def connect(path):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(path))
    sock.settimeout(5)
    return sock


def open_websocket(engine):
    sock = connect(engine.path)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(f'GET /api/v1/products/current/messages/commands HTTP/1.1\r\nHost: 127.0.0.1:8080\r\n'
                 f'Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n'
                 'Sec-WebSocket-Version: 13\r\n\r\n'.encode())
    stream = sock.makefile('rb')
    head = b''
    while not head.endswith(b'\r\n\r\n'):
        head += stream.read(1)
    assert head.startswith(b'HTTP/1.1 101')
    assert odin_engine.accept_key(key).encode() in head
    for _ in range(100):  # registered for broadcasts
        if engine.clients:
            break
        time.sleep(0.01)
    return sock, stream


def send(sock, message):
    """A masked client text frame, as service-ui sends."""
    data, mask = json.dumps(message).encode(), os.urandom(4)
    sock.sendall(bytes([0x81, 0x80 | len(data)]) + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))


def receive(stream):
    opcode, data = odin_engine.ws_read(stream)
    assert opcode == 0x1
    return json.loads(data)


def test_catalogue_commands_finish_with_the_image_data(engine):
    sock, stream = open_websocket(engine)
    with sock:
        send(sock, {'command': 'read_maintenance_history_options', 'request_id': 'r1'})
        assert receive(stream) == {'message_type': 'request_finished', 'request_id': 'r1',
                                   'response': [{'name': 'Tyre rotation'}]}
        send(sock, {'command': 'read_service_history', 'request_id': 'r2'})
        assert receive(stream)['response'] == []
        send(sock, {'command': 'list_configs', 'request_id': 'r3'})
        configs = receive(stream)['response']
        assert set(configs) == {'audiotype', 'tpmsinstalled'}
        assert [e['codeKey'] for e in configs['tpmsinstalled']['content']['enums']] == ['NO', 'YES']
        assert not configs['audiotype']['is_editable'] and 'simulated' in configs['audiotype']['description']


def test_dbus_requests_are_answered_on_the_websocket(engine):
    sock, stream = open_websocket(engine)
    with sock:
        assert engine.list_tasks('r1', 'en-US') is True
        assert receive(stream) == {'message_type': 'request_finished', 'request_id': 'r1', 'response': TASKS}
        # Tasks never run: they finish as a routine error that says why.
        assert engine.execute('Common/tasks/LAB_TASK', '{}', 'r2', 'en-US') is True
        reply = receive(stream)
        assert reply['request_id'] == 'r2' and reply['response']['exit_code'] == 2
        assert 'no vehicle is attached' in reply['response']['service_output']['user_facing_msg']
        send(sock, {'command': 'set_ecu_config', 'request_id': 'r3'})
        assert receive(stream)['response']['service_output']['exit_reason'] == 'UNSUPPORTED_SET_ECU_CONFIG'


def test_maintenance_options_follow_the_locale_with_an_english_fallback(engine):
    assert engine.maintenance('de-DE') == [{'name': 'Reifenwechsel'}]
    assert engine.maintenance('xx') == [{'name': 'Tyre rotation'}]


def test_http_endpoints_report_no_running_tasks_or_history(engine):
    for path, expected in (('/api/v1/running_tasks', {}), ('/api/v1/task_history', []),
                           ('/api/v1/query_task_history?limit=5', [])):
        with connect(engine.path) as sock:
            sock.sendall(f'GET {path} HTTP/1.1\r\nHost: x\r\n\r\n'.encode())
            reply = b''
            while chunk := sock.recv(4096):
                reply += chunk
        head, body = reply.split(b'\r\n\r\n', 1)
        assert head.startswith(b'HTTP/1.1 200') and json.loads(body) == expected
    with connect(engine.path) as sock:
        sock.sendall(b'GET /api/v1/unknown HTTP/1.1\r\n\r\n')
        assert sock.recv(100).startswith(b'HTTP/1.1 404')


def test_frames_use_the_extended_length_for_large_catalogues():
    big = b'x' * 70000
    frame = odin_engine.ws_frame(big)
    assert frame[1] == 127 and struct.unpack('!Q', frame[2:10])[0] == 70000
    assert odin_engine.ws_frame(b'x' * 300)[1] == 126
