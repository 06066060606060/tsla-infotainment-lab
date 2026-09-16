"""Run the desktop's existing operations inside the local QEMU guest."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time

import backend
from guest_status import session_status

ACTIONS = frozenset(('status', 'controls', 'preview', 'capture', 'camera-preview',
                     'camera', 'replay', 'vehicle-services', 'browser', 'steering', 'logs', 'focus'))


def configure():
    backend.DATA = Path('/home/lab')
    backend.UNIT = 'lab-desktop.service'
    backend.systemctl = lambda *args, check=False: backend.run(['systemctl', *args], check=check)
    os.environ.update(XAUTHORITY='/run/user/1000/lab.xauth', DISPLAY=':0.0',
                      XDG_RUNTIME_DIR='/run/user/1000', PULSE_SERVER='unix:/run/user/1000/pulse/native')


def handle(action, payload):
    if action not in ACTIONS:
        raise ValueError('Unknown guest desktop operation.')
    configure()
    if action == 'status':
        now = time.time()
        uptime = float(Path('/proc/uptime').read_text().split()[0])
        active = backend.systemctl('is-active', backend.UNIT).returncode == 0
        fresh = session_status(backend.DATA / 'session/status.json', active=active,
                               now=now, boot_time=now - uptime)
        if not active:
            unit = backend.systemctl('show', backend.UNIT, '-p', 'LoadState', '-p', 'ExecMainStartTimestampMonotonic').stdout
            fields = dict(line.split('=', 1) for line in unit.splitlines() if '=' in line)
            if fields.get('LoadState') == 'loaded' and fields.get('ExecMainStartTimestampMonotonic') == '0':
                fresh.update(phase='booting', detail='Waiting for the guest display service to start.')
        if fresh.get('phase') not in ('running', 'degraded', 'starting') or fresh.get('detail'):
            return fresh
        return dict(backend.status(), **fresh)
    if action == 'controls':
        value = backend.Simulation.parse(payload).as_dict()
        return backend.manual_takeover(backend.DATA / 'session', value)
    if action in ('preview', 'capture'):
        return backend.capture_displays(action == 'preview')
    if action == 'camera-preview':
        return backend.camera_preview()
    if action == 'camera':
        return backend.set_camera(payload.get('source', 'pattern'), payload.get('path'))
    if action == 'replay':
        return backend.set_replay(payload)
    if action == 'vehicle-services':
        return backend.set_vehicle_services(payload)
    if action == 'browser':
        return backend.open_browser(payload.get('mode', 'browser'), payload.get('url'))
    if action == 'steering':
        return backend.steering_button(payload['button'])
    if action == 'focus':
        return backend.focus_display(payload.get('display', 'center'))
    logs = {}
    for path in (backend.DATA / 'session').glob('*.log'):
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 12000))
            logs[path.name] = stream.read(12000).decode(errors='replace')
    return {'logs': logs}


if __name__ == '__main__':
    try:
        print(json.dumps({'ok': True, 'data': handle(sys.argv[1], json.loads(sys.argv[2]))}))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
