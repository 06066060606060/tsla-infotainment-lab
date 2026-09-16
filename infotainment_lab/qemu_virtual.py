"""Experimental virtual-hardware guest, separate from vendor-kernel boot checks.

Requires a prepared Linux guest disk with this project's local display runtime.
The firmware is a separate read-only disk. No vehicle transport is implemented.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid

from .core import atomic_json, validate_image
from .host_graphics import environment
from .qemu_runtime import (ensure_idle, lifecycle_lock, option_path,
                           process_identity, read_state, verify_identity)
from .simulation import Simulation


def regular_file(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Select a regular file, not a host device.')
    return path


def prepared_files(directory):
    """Resolve the builder's outputs without guessing a kernel ABI."""
    directory = Path(directory).resolve(strict=True)
    manifest = json.loads((directory / 'build.json').read_text())
    version = manifest.get('kernel', '')
    if not isinstance(version, str) or not version or Path(version).name != version or '/' in version or '\\' in version:
        raise ValueError('The guest build manifest has an invalid kernel version.')
    return {name: regular_file(directory / filename) for name, filename in (
        ('disk', 'desktop.raw'), ('kernel', 'vmlinuz-' + version), ('initrd', 'initrd.img-' + version))}


def launch_arguments(directory, identifier, *, disk, kernel, initrd, firmware, internet=True, display='sdl', single_display=False, options_file=None, maps=None, inputs=None):
    directory = Path(directory)
    for path in (disk, kernel, initrd, firmware):
        regular_file(path)
    if any(Path(disk).samefile(path) for path in (firmware, kernel, initrd)):
        raise ValueError('The writable guest disk must be separate from firmware and boot files.')
    validate_image(Path(firmware))
    if display not in ('gtk', 'sdl'):
        raise ValueError('Select the GTK or SDL native display.')
    extras = []
    if inputs:
        expected = (directory / 'inputs').absolute()
        if Path(inputs).resolve(strict=True) != expected or not expected.is_dir():
            raise ValueError('Only this VM\'s private input directory can be shared.')
        extras += ['-fsdev', f'local,id=labinputs,path={option_path(inputs)},security_model=none,readonly=on',
                   '-device', 'virtio-9p-pci,fsdev=labinputs,mount_tag=lab-inputs']
    if options_file:
        regular_file(options_file)
        extras += ['-fw_cfg', 'name=opt/tsla-lab/config,file=' + option_path(options_file)]
    if maps:
        validate_image(regular_file(maps))
        if Path(disk).samefile(maps):
            raise ValueError('The map image must be separate from the writable guest disk.')
        extras += ['-drive', f'file={option_path(maps)},if=none,id=labmaps,format=raw,readonly=on',
                   '-device', 'virtio-blk-pci,drive=labmaps,serial=lab-maps']
    return ['qemu-system-x86_64', '-name', 'Infotainment Lab | ' + identifier[:8],
            '-uuid', identifier, '-machine', 'q35,accel=kvm', '-cpu', 'host',
            '-smp', '4', '-m', '4096', '-kernel', str(kernel), '-initrd', str(initrd),
            '-append', 'console=tty0 console=ttyS0,115200 root=/dev/vda rw loglevel=4',
            '-drive', f'file={option_path(disk)},if=virtio,format=raw',
            '-drive', f'file={option_path(firmware)},if=virtio,format=raw,readonly=on',
            '-device', 'virtio-vga-gl,max_outputs=1,' + ('xres=1920,yres=1200' if single_display else 'xres=720,yres=1152'),
            '-device', 'virtio-gpu-pci,id=cluster-gpu,addr=0x08,max_outputs=1,xres=1280,yres=480',
            '-display', 'sdl,gl=on' if display == 'sdl' else 'gtk,gl=on,show-cursor=on,show-tabs=on',
            '-netdev', 'user,id=net0' + ('' if internet else ',restrict=on'),
            '-device', 'virtio-net-pci,netdev=net0',
            '-device', 'qemu-xhci', '-device', 'usb-tablet',
            '-audiodev', 'pa,id=audio0,out.frequency=48000,out.latency=60000,out.buffer-length=120000', '-device', 'intel-hda',
            '-device', 'hda-output,audiodev=audio0', '-device', 'virtio-serial-pci',
            '-chardev', f'socket,path={option_path(directory / "guest-agent.sock")},server=on,wait=off,id=qga0',
            '-device', 'virtserialport,chardev=qga0,name=org.qemu.guest_agent.0',
            '-qmp', f'unix:{option_path(directory / "vm-qmp.sock")},server=on,wait=off',
            '-serial', f'file:{directory / "vm-serial.log"}', '-monitor', 'none', *extras]


def start(directory, **files):
    from . import qemu_audio
    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise ValueError('Use a private VM directory owned by this Linux user.')
    with lifecycle_lock(directory):
        ensure_idle(directory)
        inputs = directory / 'inputs'
        inputs.mkdir(mode=0o700, exist_ok=True)
        files.setdefault('inputs', inputs)
        identifier = str(uuid.uuid4())
        args = launch_arguments(directory, identifier, **files)
        if not os.access('/dev/kvm', os.R_OK | os.W_OK) or not os.environ.get('DISPLAY'):
            raise RuntimeError('KVM access and a Linux X11 desktop or WSLg are required.')
        env = dict(environment(), GDK_BACKEND='x11', SDL_VIDEODRIVER='x11')
        if Path('/mnt/wslg/PulseServer').exists():
            env.setdefault('PULSE_SERVER', 'unix:/mnt/wslg/PulseServer')
        audio = None
        if qemu_audio.required(env):
            audio, server = qemu_audio.start(directory, identifier, env)
            args[args.index('-audiodev') + 1] += ',server=' + option_path(server)
        child = None
        try:
            with (directory / 'vm-launch.log').open('ab') as log:
                child = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log,
                                         stderr=log, env=env, start_new_session=True)
            state = {'uuid': identifier, 'process': process_identity(child.pid),
                     'started_at': time.time(), 'mode': 'virtual-hardware',
                     'audio_buffered': audio is not None,
                     'files': {k: str(v) if isinstance(v, Path) else v for k, v in files.items()}}
            last_error = ''
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError('QEMU exited; inspect vm-launch.log.')
                try:
                    with verify_identity(directory, state):
                        break
                except (OSError, RuntimeError) as exc:
                    last_error = str(exc)
                    time.sleep(.1)
            else:
                raise RuntimeError('QEMU did not expose its verified control channel: ' + last_error)
            atomic_json(directory / 'vm.json', state)
        except Exception:
            if child is not None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            if audio is not None:
                audio.terminate()
                audio.wait(timeout=8)
            raise
    return {'phase': 'booting', 'mode': 'virtual-hardware', 'uuid': identifier}


@contextmanager
def guest_channel_lock(directory, timeout):
    """The serial guest-agent transport accepts one connected client at a time."""
    import fcntl
    with (Path(directory) / 'guest-channel.lock').open('a') as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('The guest command channel is busy; no command was sent.')
                time.sleep(.02)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def guest_execute(directory, argv, timeout=15):
    """Execute in this identified local guest using the standard guest agent."""
    directory = Path(directory)
    with guest_channel_lock(directory, timeout):
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(timeout)
            # Keep identity verification and connection atomic with lifecycle
            # changes. Once connected, this socket belongs to that same guest.
            with lifecycle_lock(directory):
                with verify_identity(directory, read_state(directory)):
                    sock.connect(str(directory / 'guest-agent.sock'))
            with sock.makefile('rwb', buffering=0) as stream:
                def call(name, **arguments):
                    token = uuid.uuid4().hex
                    stream.write((json.dumps({'execute': name, 'arguments': arguments,
                                              'id': token}) + '\n').encode())
                    line = stream.readline(8 * 1024 * 1024)
                    if not line or len(line) >= 8 * 1024 * 1024:
                        raise RuntimeError('Guest agent closed or exceeded the response limit.')
                    result = json.loads(line)
                    if result.get('id') != token or 'error' in result:
                        raise RuntimeError('Guest agent did not acknowledge the request: ' + str(result.get('error', '')))
                    return result['return']
                call('guest-ping')
                pid = call('guest-exec', path=argv[0], arg=argv[1:], **{'capture-output': True})['pid']
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    result = call('guest-exec-status', pid=pid)
                    if result.get('exited'):
                        if result.get('out-truncated') or result.get('err-truncated'):
                            raise RuntimeError('The guest command output was truncated.')
                        output = base64.b64decode(result.get('out-data', '')).decode(errors='replace')
                        if result.get('exitcode') != 0:
                            error = base64.b64decode(result.get('err-data', '')).decode(errors='replace')
                            raise RuntimeError(error or f'Guest command failed: {result}')
                        return output
                    time.sleep(.1)
                raise TimeoutError('Guest command is still pending; completion has not been established.')


def status(directory):
    directory = Path(directory)
    state = read_state(directory)
    process = state.get('process')
    if not process or process_identity(process['pid']) != process:
        return {'phase': 'stopped', 'mode': 'virtual-hardware'}
    try:
        result = guest_action(directory, 'status')
        from . import qemu_audio
        result['audio_transport'] = (qemu_audio.status(directory, state['uuid'])
                                     if state.get('audio_buffered', qemu_audio.required())
                                     else {'phase': 'direct'})
        if state.get('shutdown_requested_at'):
            result['phase'] = 'stopping'
        return result
    except (OSError, RuntimeError, ValueError) as exc:
        return {'phase': 'booting', 'mode': 'virtual-hardware', 'detail': str(exc),
                'full_firmware_verified': False}


def guest_action(directory, action, payload=None):
    allowed = {'status', 'controls', 'preview', 'capture', 'camera-preview', 'camera',
               'replay', 'vehicle-services', 'browser', 'steering', 'logs', 'focus'}
    if action not in allowed:
        raise ValueError('Unknown guest desktop operation.')
    result = json.loads(guest_execute(directory, ['/usr/sbin/runuser', '-u', 'lab', '--',
                        '/usr/bin/python3', '/opt/infotainment-lab/guest_bridge.py',
                        action, json.dumps(payload or {})]))
    if not result.get('ok'):
        raise RuntimeError(result.get('error', 'Guest operation failed.'))
    return result['data']


def controls(directory, payload):
    value = Simulation.parse(payload).as_dict()
    script = """import json,sys
from pathlib import Path
sys.path.insert(0,'/opt/infotainment-lab')
from replay import manual_takeover
manual_takeover(Path('/home/lab/session'),json.loads(sys.argv[1]))
"""
    guest_execute(directory, ['/usr/sbin/runuser', '-u', 'lab', '--',
                              '/usr/bin/python3', '-c', script, json.dumps(value)])
    return {'requested': value, 'accepted_by_firmware': None}


def shutdown(directory):
    directory = Path(directory)
    with lifecycle_lock(directory):
        state = read_state(directory)
        with verify_identity(directory, state) as qmp:
            qmp.command('system_powerdown')
        state['shutdown_requested_at'] = time.time()
        atomic_json(directory / 'vm.json', state)
    return {'phase': 'shutdown-requested', 'exited': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'status', 'stop', 'controls'))
    parser.add_argument('--directory', type=Path, required=True)
    for name in ('disk', 'kernel', 'initrd', 'firmware'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--single-display', action='store_true', help='Use the landscape center resolution for single-display firmware.')
    parser.add_argument('--display', choices=('gtk', 'sdl'), default='sdl')
    parser.add_argument('--payload', default='{}')
    args = parser.parse_args()
    if args.action == 'start':
        files = {key: getattr(args, key) for key in ('disk', 'kernel', 'initrd', 'firmware')}
        if not files['firmware']:
            parser.error('start requires --firmware')
        if any(files[key] is None for key in ('disk', 'kernel', 'initrd')):
            defaults = prepared_files(args.directory)
            files.update({key: value for key, value in defaults.items() if files[key] is None})
        result = start(args.directory, **files, internet=not args.offline, display=args.display, single_display=args.single_display)
    elif args.action == 'controls':
        result = controls(args.directory, json.loads(args.payload))
    else:
        result = (status if args.action == 'status' else shutdown)(args.directory)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
