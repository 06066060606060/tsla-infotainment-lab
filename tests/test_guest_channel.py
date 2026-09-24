"""Exercise the real local socket framing used for guest-agent replies."""
import base64
from contextlib import nullcontext
import json
import os
import socket
import threading

import pytest

from infotainment_lab import qemu_virtual as vm

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Linux guest-agent Unix socket')


def exchange(tmp_path, monkeypatch, payload, *, wrong_id=False):
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(tmp_path / 'guest-agent.sock'))
    server.listen(1)
    server.settimeout(3)
    requests, failures = [], []

    def serve():
        try:
            with server.accept()[0] as connection, connection.makefile('rwb') as stream:
                for result in ({}, {'pid': 42}, payload):
                    request = json.loads(stream.readline())
                    requests.append(request)
                    reply = json.dumps({'id': 'other' if wrong_id else request['id'], 'return': result})+'\n'
                    # Exercise fragmented responses, including large output.
                    data = reply.encode()
                    for offset in range(0, len(data), 3071):
                        stream.write(data[offset:offset+3071])
                        stream.flush()
                    if wrong_id:
                        break
        except Exception as exc:
            failures.append(exc)
        finally:
            server.close()

    monkeypatch.setattr(vm, 'verify_identity', lambda *args: nullcontext())
    monkeypatch.setattr(vm, 'read_state', lambda *args: {})
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        return vm.guest_execute(tmp_path, ['/usr/bin/example', 'literal argument'], timeout=2), requests
    finally:
        thread.join(4)
        assert not thread.is_alive(), 'Guest protocol server did not terminate'
        assert not failures


def test_buffered_guest_protocol_flushes_requests_and_preserves_large_output(tmp_path, monkeypatch):
    expected = 'dashboard / center\n' * 45000
    payload = {'exited': True, 'exitcode': 0,
               'out-data': base64.b64encode(expected.encode()).decode()}
    output, requests = exchange(tmp_path, monkeypatch, payload)
    assert output == expected
    assert [r['execute'] for r in requests] == ['guest-ping', 'guest-exec', 'guest-exec-status']
    assert requests[1]['arguments']['arg'] == ['literal argument']
    assert requests[2]['arguments'] == {'pid': 42}


@pytest.mark.parametrize('payload, message', [
    ({'exited': True, 'out-truncated': True}, 'truncated'),
    ({'exited': True, 'exitcode': 1, 'err-data': base64.b64encode(b'guest failure').decode()}, 'guest failure'),
])
def test_buffered_guest_protocol_preserves_failure_checks(tmp_path, monkeypatch, payload, message):
    with pytest.raises(RuntimeError, match=message):
        exchange(tmp_path, monkeypatch, payload)


def test_buffered_guest_protocol_rejects_mismatched_response_id(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match='did not acknowledge'):
        exchange(tmp_path, monkeypatch, {}, wrong_id=True)
