"""Warm backend workers: reused between calls, replaced when they die, never cross runners."""
import json
import sys

from infotainment_lab import bridge

STUB = "import json, os, sys\nfor line in sys.stdin:\n    print(json.dumps({'pid': os.getpid(), 'argv': json.loads(line)}), flush=True)\n"


def call(runner, *tail):
    return json.loads(bridge.warm_call(runner, list(tail), 10))


def release():
    for proc in bridge.IDLE: proc.kill()
    bridge.IDLE.clear()


def test_worker_is_reused_and_replaced_after_dying(tmp_path):
    stub = tmp_path / 'stub.py'
    stub.write_text(STUB)
    runner = [sys.executable, str(stub)]
    release()
    first = call(runner, 'status')
    assert call(runner, 'debug') == {'pid': first['pid'], 'argv': ['debug']}
    bridge.IDLE[0].kill()
    bridge.IDLE[0].wait()
    assert call(runner, 'status')['pid'] != first['pid']
    release()


def test_real_backend_serves_requests_and_survives_a_bad_one():
    runner = [sys.executable, str(bridge.BACKEND)]
    release()
    assert call(runner, 'can', '--payload', 'not json')['ok'] is False
    assert call(runner, 'can', '--payload', 'not json')['ok'] is False
    assert len(bridge.IDLE) == 1
    release()
