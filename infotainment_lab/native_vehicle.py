"""Run the firmware vehicle emitter with private output sockets and IPC.

Read the real display's published requests through read-only socket links.
Keep the emitter's default vehicle-state publishers away from the lab UI.
"""
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

from core import atomic_json


def arguments(firmware):
    return [str(Path(firmware) / 'usr/tesla/UI/bin/QtCarVehicle'),
            '--gw', '127.0.0.102', '--cid', '127.0.0.100', '--ic', '127.0.0.101',
            '--ip', '127.0.0.100', '--udp', '127.0.0.100:20101', '--udptx', ':4321']


def isolate(state, source=Path('/tmp/dvaccess')):
    inputs, outputs = state / 'vehicle-observer-inputs', state / 'vehicle-observer-outputs'
    inputs.mkdir(mode=0o700, exist_ok=True)
    outputs.mkdir(mode=0o700, exist_ok=True)
    for directory in (inputs, outputs):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Vehicle observation sockets need private directories owned by this Linux user.')
    subprocess.run(['mount', '--make-rprivate', '/'], check=True)
    subprocess.run(['mount', '--bind', str(source), str(inputs)], check=True)
    subprocess.run(['mount', '-o', 'remount,bind,ro', str(inputs)], check=True)
    # Fresh private symlinks expose existing input sockets. Publisher unlink/bind
    # operates on these private entries, never on the display's original socket.
    for old in outputs.iterdir():
        if old.is_symlink() or old.is_socket():
            old.unlink()
        else:
            raise ValueError('Unexpected file in the owned vehicle observation socket directory.')
    for path in inputs.iterdir():
        if path.is_socket():
            (outputs / path.name).symlink_to(inputs / path.name)
    subprocess.run(['mount', '--bind', str(outputs), str(source)], check=True)


def main():
    state = Path(os.environ['TESLA_NATIVE_STATE'])
    status = state / 'native-vehicle-status.json'
    if '--inside' not in sys.argv:
        atomic_json(status, {'state': 'starting', 'pid': os.getpid()})
        # The namespaces disappear with this owned process tree. Host socket
        # mounts, System V shared memory and the real display are unchanged.
        os.execvp('unshare', ['unshare', '--user', '--map-root-user', '--mount', '--ipc',
                             '/usr/bin/python3', __file__, '--inside'])
    try:
        isolate(state)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        atomic_json(status, {'state': 'failed', 'error': str(exc)})
        raise
    process = None
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True
        if process is not None and process.poll() is None:
            process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for attempt in range(4):
            if stopping:
                break
            with (state / 'native-vehicle.log').open('w') as log:
                process = subprocess.Popen(arguments(os.environ['TESLA_FIRMWARE']), env=dict(os.environ),
                    cwd=os.environ['TESLA_HOME'], stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                atomic_json(status, {'state': 'running', 'pid': process.pid, 'configuration_restarts': attempt})
                while process.poll() is None and not stopping:
                    time.sleep(.2)
                if stopping:
                    break
            text = (state / 'native-vehicle.log').read_text(errors='replace')[-64000:]
            if 'Restarting QtCarVehicle because of changed DVs:' not in text:
                atomic_json(status, {'state': 'exited', 'code': process.returncode})
                break
        else:
            atomic_json(status, {'state': 'failed', 'error': 'Vehicle emitter kept restarting its configuration.'})
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if stopping:
            atomic_json(status, {'state': 'stopped'})


if __name__ == '__main__':
    main()
