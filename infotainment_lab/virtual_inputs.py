"""Explicitly selected media and a live RGB relay for a private read-only share."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from .camera_source import FRAME_BYTES, source_config
from .core import atomic_json, load_json
from .qemu_runtime import process_identity, read_state


def share_directory(directory):
    directory = Path(directory).resolve(strict=True)
    target = directory / 'inputs'
    target.mkdir(mode=0o700, exist_ok=True)
    if target.is_symlink() or target.resolve() != target:
        raise ValueError('The private input directory must not be a symbolic link.')
    return target


def import_media(directory, filename, mode):
    checked = source_config(mode, filename)
    source = Path(checked['path']).resolve(strict=True)
    before = source.stat()
    key = hashlib.sha256(f'{source}:{before.st_size}:{before.st_mtime_ns}:{before.st_ctime_ns}'.encode()).hexdigest()[:24]
    parent = share_directory(directory) / key
    parent.mkdir(mode=0o700, exist_ok=True)
    target = parent / source.name
    if target.is_symlink():
        raise ValueError('The staged input must not be a symbolic link.')
    if not target.exists():
        temporary = parent / (uuid.uuid4().hex + '.partial')
        try:
            shutil.copyfile(source, temporary)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise RuntimeError('The selected recording changed while being copied. Retry once its writer has finished.')
            temporary.chmod(0o600)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return '/inputs/' + key + '/' + source.name


def stop_relay(directory):
    atomic_json(Path(directory) / 'input-source.json', {'source': None})


def connect_raw(directory, filename):
    directory = Path(directory).resolve(strict=True)
    checked = source_config('raw', filename)
    share = share_directory(directory)
    source = Path(checked['path']).resolve()
    if source.is_relative_to(share):
        raise ValueError('Select the upstream writer file, not a staged VM input.')
    state = read_state(directory)
    identity = state.get('process', {})
    if process_identity(identity.get('pid', 0)) != identity:
        raise RuntimeError('Start the virtual machine before connecting its live feed.')
    atomic_json(directory / 'input-source.json', {'source': str(source), 'vm_uuid': state['uuid']})
    relay = load_json(directory / 'input-relay.json', {})
    process = relay.get('process', {})
    if relay.get('vm_uuid') != state['uuid'] or process_identity(process.get('pid', 0)) != process:
        with (directory / 'input-relay.log').open('ab') as log:
            child = subprocess.Popen([sys.executable, '-m', 'infotainment_lab.virtual_inputs', str(directory)],
                                     cwd=Path(__file__).resolve().parent.parent, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=log, start_new_session=True)
        atomic_json(directory / 'input-relay.json', {'process': process_identity(child.pid), 'vm_uuid': state['uuid']})
    return '/inputs/live.rgb'


def relay(directory):
    state = read_state(directory)
    identity = state['process']
    share = share_directory(directory)
    last = None
    frames = 0
    while process_identity(identity['pid']) == identity:
        source = load_json(directory / 'input-source.json', {})
        if source.get('vm_uuid') != state['uuid'] or not source.get('source'):
            return
        try:
            path = Path(source['source'])
            stat = path.stat()
            stamp = (str(path), stat.st_ino, stat.st_mtime_ns, stat.st_size)
            if stamp != last:
                data = path.read_bytes() if stat.st_size == FRAME_BYTES else b''
                if len(data) != FRAME_BYTES:
                    raise ValueError('Waiting for a complete RGB24 frame.')
                with (share / '.live.pending').open('wb') as output:
                    output.write(data)
                os.replace(share / '.live.pending', share / 'live.rgb')
                frames += 1
                last = stamp
                atomic_json(directory / 'input-status.json', {'phase': 'live', 'frames': frames, 'updated_at': time.time()})
        except (OSError, ValueError) as exc:
            atomic_json(directory / 'input-status.json', {'phase': 'waiting', 'detail': str(exc), 'updated_at': time.time()})
        time.sleep(1 / 24)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    relay(parser.parse_args().directory.resolve(strict=True))
