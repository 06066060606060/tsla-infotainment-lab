"""Clocked audio for one local VM, buffered before the desktop sound server.

QEMU writes to a private PulseAudio null sink. Its PCM monitor is forwarded to
the desktop server only while sound is present. This keeps WSLg's RDP sink out
of QEMU's timing loop and releases idle output streams.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import selectors
import subprocess
import sys
import time

from .core import atomic_json, load_json
from .audio_playback import DesktopPlayback
from .qemu_runtime import process_identity, read_state


def required(env=None):
    env = os.environ if env is None else env
    return bool(env.get('WSL_DISTRO_NAME')) and env.get('PULSE_SERVER', 'unix:/mnt/wslg/PulseServer') in (
        'unix:/mnt/wslg/PulseServer', '/mnt/wslg/PulseServer')


def private_directory(directory):
    path = Path(directory) / 'audio'
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError('The VM audio directory must be private and owned by this user.')
    return path


def pulse_value(value):
    value = str(value)
    if any(c in value for c in '\n\r\x00'):
        raise ValueError('Invalid audio server or socket path.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def configuration(path):
    return '\n'.join([
        'load-module module-native-protocol-unix socket=' + pulse_value(path / 'pulse.sock'),
        'load-module module-null-sink sink_name=lab_vm rate=48000 channels=2',
        'set-default-sink lab_vm', '',
    ])


def status(directory, identifier):
    state = load_json(Path(directory) / 'audio/status.json', {})
    if state.get('vm_uuid') != identifier:
        return {'phase': 'unavailable', 'detail': 'The VM audio service is not connected.'}
    process = state.get('process', {})
    if state.get('phase') in ('ready', 'running', 'degraded') and process_identity(process.get('pid', 0)) != process:
        return {'phase': 'failed', 'detail': 'The VM audio service has stopped.'}
    return {key: state[key] for key in ('phase', 'detail', 'buffer_ms', 'playing', 'written_bytes', 'dropped_bytes') if key in state}


def stop_previous(directory):
    state = load_json(Path(directory) / 'audio/status.json', {})
    process = state.get('process', {})
    if not process or process_identity(process.get('pid', 0)) != process:
        return
    # Only stop this helper in this directory, never an arbitrary stored PID.
    argv = (Path('/proc') / str(process['pid']) / 'cmdline').read_bytes().split(b'\0')
    expected = [b'-m', b'infotainment_lab.qemu_audio', os.fsencode(str(directory))]
    if argv[1:4] != expected:
        raise RuntimeError('The previous audio process does not match this VM.')
    os.kill(process['pid'], signal.SIGTERM)
    deadline = time.monotonic() + 8
    while process_identity(process['pid']) == process:
        if time.monotonic() >= deadline:
            raise RuntimeError('The previous VM audio service is still stopping.')
        time.sleep(.1)


def start(directory, identifier, env):
    directory = Path(directory).resolve(strict=True)
    path = private_directory(directory)
    stop_previous(directory)
    with (path / 'service.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, '-m', 'infotainment_lab.qemu_audio',
                                  str(directory), identifier],
                                 cwd=Path(__file__).resolve().parents[1], env=env,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 start_new_session=True)
    try:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            state = load_json(path / 'status.json', {})
            if state.get('vm_uuid') == identifier:
                if state.get('phase') == 'ready':
                    return child, 'unix:' + str(path / 'pulse.sock')
                if state.get('phase') == 'failed':
                    raise RuntimeError(state.get('detail', 'VM audio preparation failed.'))
            if child.poll() is not None:
                raise RuntimeError('VM audio preparation failed; inspect audio/service.log.')
            time.sleep(.1)
        raise RuntimeError('The VM audio service did not become ready.')
    except Exception:
        child.terminate()
        child.wait(timeout=8)
        raise


def serve(directory, identifier):
    os.umask(0o077)
    path = private_directory(directory)
    identity = process_identity(os.getpid())
    stopping = False
    child = None
    recorder = None
    playback = None
    failed = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    def report(phase, detail=''):
        atomic_json(path / 'status.json', {'vm_uuid': identifier, 'process': identity,
                    'phase': phase, 'detail': detail, 'buffer_ms': 120, 'updated_at': time.time(),
                    'playing': bool(playback and playback.player is not None),
                    'written_bytes': playback.written_bytes if playback else 0,
                    'dropped_bytes': playback.dropped_bytes if playback else 0})

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    report('starting')
    try:
        host = os.environ.get('PULSE_SERVER') or 'unix:' + str(Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'pulse/native')
        probe = subprocess.run(['pactl', '--server=' + host, 'info'],
                               capture_output=True, text=True, timeout=4)
        if probe.returncode:
            raise RuntimeError('The desktop sound server is unavailable. Restore desktop audio and retry.')
        config = path / 'default.pa'
        pulse_value(host)  # Reject malformed values before passing them to a client.
        config.write_text(configuration(path))
        env = dict(os.environ, XDG_RUNTIME_DIR=str(path))
        env.pop('PULSE_SERVER', None)
        child = subprocess.Popen(['pulseaudio', '-n', '-F', str(config), '--daemonize=no',
                                  '--exit-idle-time=-1', '--use-pid-file=no', '--log-level=notice'], env=env)
        server = 'unix:' + str(path / 'pulse.sock')
        deadline = time.monotonic() + 6
        while not stopping:
            if child.poll() is not None:
                raise RuntimeError('The private audio server exited; inspect audio/service.log.')
            probe = subprocess.run(['pactl', '--server=' + server, 'list', 'short', 'sinks'],
                                   capture_output=True, text=True, timeout=2)
            if probe.returncode == 0 and '\tlab_vm\t' in probe.stdout:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('The buffered audio output did not become available.')
            time.sleep(.1)
        if stopping:
            return
        playback = DesktopPlayback(host)
        recorder = subprocess.Popen(['parec', '--server=' + server, '--device=lab_vm.monitor',
                                     '--raw', '--format=s16le', '--rate=48000', '--channels=2',
                                     '--latency-msec=40'], stdout=subprocess.PIPE)
        report('ready')
        deadline = time.monotonic() + 45
        vm_process = None
        next_report = 0
        partial_frame = bytearray()
        with selectors.DefaultSelector() as poll:
            poll.register(recorder.stdout, selectors.EVENT_READ)
            while not stopping:
                if child.poll() is not None or recorder.poll() is not None:
                    raise RuntimeError('The private audio service stopped unexpectedly.')
                now = time.monotonic()
                if vm_process is None:
                    state = read_state(directory)
                    if state.get('uuid') == identifier:
                        vm_process = state.get('process')
                    elif now >= deadline:
                        raise RuntimeError('The VM did not start; its audio service was stopped.')
                if vm_process and process_identity(vm_process['pid']) != vm_process:
                    break
                if poll.select(.05):
                    data = os.read(recorder.stdout.fileno(), 8192)
                    if not data:
                        raise RuntimeError('The private audio monitor closed.')
                    partial_frame.extend(data)
                    complete = len(partial_frame) // 4 * 4
                    playback.feed(partial_frame[:complete])
                    del partial_frame[:complete]
                else:
                    playback.flush()
                if vm_process and now >= next_report:
                    report('degraded' if playback.detail else 'running', playback.detail)
                    next_report = now + 1
    except subprocess.TimeoutExpired:
        failed = True
        report('failed', 'The audio service did not respond. Restore desktop audio and retry.')
    except Exception as exc:
        failed = True
        report('failed', str(exc))
    finally:
        if playback:
            playback.close()
        if recorder is not None and recorder.poll() is None:
            recorder.terminate()
            try:
                recorder.wait(timeout=3)
            except subprocess.TimeoutExpired:
                recorder.kill()
                recorder.wait(timeout=3)
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
        if not failed:
            report('stopped')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('identifier')
    args = parser.parse_args()
    serve(args.directory.resolve(strict=True), args.identifier)
