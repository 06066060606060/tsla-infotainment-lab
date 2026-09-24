"""Qt worker routing for the managed virtual-hardware desktop."""
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import subprocess
import sys
import time

from . import qemu_virtual as vm
from .core import atomic_json, profile_for
from .display_scale import firmware_scale
from .qemu_runtime import read_state, verify_identity


def build_manifest(directory):
    try:
        manifest = json.loads((Path(directory) / 'build.json').read_text())
    except (OSError, ValueError):
        return {}
    return manifest if isinstance(manifest, dict) else {}


def directory_for(args, backend):
    return Path(args.vm_directory).expanduser().resolve() if args.vm_directory else backend.DATA / 'virtual-desktop'


def probe(directory, backend):
    from .qemu_audio import required
    dependencies = ['qemu-system-x86_64', 'xdotool', 'unsquashfs', 'pactl']
    if required():
        dependencies += ['pulseaudio', 'parec', 'pacat']
    missing = [name for name in dependencies if not shutil.which(name)]
    try:
        vm.prepared_files(directory)
        prepared, detail = True, ''
    except (OSError, ValueError, KeyError) as exc:
        prepared, detail = False, str(exc)
    return {'engine': 'qemu', 'platform': 'QEMU / ' + ('WSLg' if os.environ.get('WSL_DISTRO_NAME') else 'Linux'),
            'architecture': platform.machine(), 'missing': missing, 'runtime_ready': prepared,
            'display_available': bool(os.environ.get('DISPLAY')), 'root_user': os.getuid() == 0,
            'kvm_available': os.access('/dev/kvm', os.R_OK | os.W_OK),
            'vm_directory': str(directory), 'preparation_detail': detail,
            'library': backend.load_json(backend.DATA / 'library.json', []),
            'status': vm.status(directory) if directory.exists() else {'phase': 'stopped'}}


def focus(directory, name, backend):
    if name not in ('center', 'cluster'):
        raise ValueError('Unknown display.')
    state = read_state(directory)
    with verify_identity(directory, state):
        pass
    title = 'Infotainment Lab | ' + state['uuid'][:8] + ('-0' if name == 'center' else '-1')
    matches = backend.run(['xdotool', 'search', '--onlyvisible', '--name', re.escape(title)], check=False).stdout.split()
    if not matches:
        raise RuntimeError('The QEMU display window is not available yet.')
    for wid in matches:
        backend.run(['xdotool', 'windowraise', wid])
        backend.run(['xdotool', 'windowfocus', wid], check=False)
    return {'display': name}


def prepare(args, directory, backend):
    if os.geteuid() != 0:
        raise RuntimeError('Preparing a guest image requires administrator access.')
    owner = pwd.getpwuid(args.uid)
    if owner.pw_uid < 1000:
        raise ValueError('Choose a normal desktop user.')
    if not args.vm_directory:
        directory = Path(owner.pw_dir) / '.local/share/tsla-infotainment-lab/virtual-desktop'
    if directory.exists():
        raise ValueError('Choose a new guest directory. Existing VM disks are preserved.')
    directory.parent.mkdir(parents=True, exist_ok=True)
    backend.run(['apt-get', 'update'], timeout=300)
    dependencies = ['debootstrap', 'qemu-system-x86', 'qemu-system-gui',
                    'e2fsprogs', 'squashfs-tools', 'xdotool', 'pulseaudio-utils']
    from .qemu_audio import required
    if required():
        dependencies.append('pulseaudio')
    backend.run(['apt-get', 'install', '-y', *dependencies], timeout=900)
    builder = Path(__file__).resolve().parents[1] / 'scripts/build-virtual-guest.py'
    backend.run([sys.executable, builder, '--directory', directory, '--owner', owner.pw_name], timeout=1800)
    return {'installed': True, 'vm_directory': str(directory)}


def dispatch(args, backend):
    directory = directory_for(args, backend)
    action = args.action
    if action == 'probe':
        return probe(directory, backend)
    if action == 'setup':
        return prepare(args, directory, backend)
    if action == 'status':
        return vm.status(directory) if directory.exists() else {'phase': 'stopped', 'mode': 'virtual-hardware'}
    if action == 'report':
        environment = probe(directory, backend)
        return backend.public_report(environment['status'], environment)
    if action == 'ssh-key':
        if vm.status(directory)['phase'] == 'stopped':
            raise RuntimeError('Start the virtual CID first, then set up the SSH key.')
        key = vm.ensure_ssh_key()
        vm.install_ssh_key(directory, Path(str(key) + '.pub').read_text())
        return {'installed': True}
    if action == 'start':
        item = backend.library_item(args.id or '')
        profile = profile_for(item['version'], item['variant'])
        if item['kind'] != 'firmware' or not profile:
            raise ValueError('Select firmware with a compatible launch profile.')
        current = vm.status(directory)
        if current['phase'] != 'stopped':
            previous = read_state(directory).get('files', {}).get('firmware')
            if previous and Path(previous).resolve() == Path(item['path']).resolve():
                return current
            raise RuntimeError('Stop the current virtual machine before changing firmware.')
        files = vm.prepared_files(directory)
        single = bool(profile.get('single_display'))
        # Older guest images draw at the default size whatever the host asks.
        scale = firmware_scale(single) if build_manifest(directory).get('display_scale') else 1.0
        options = {'firmware_id': item['id'], 'browser': not args.no_browser,
                   'cluster': not args.no_cluster, 'map_id': args.map_id, 'display_scale': scale}
        options_file = directory / 'launch-options.json'
        atomic_json(options_file, options)
        maps = None
        if args.map_id:
            selected_map = backend.library_item(args.map_id)
            if selected_map['kind'] != 'map':
                raise ValueError('Select a map image for the map slot.')
            maps = Path(selected_map['path'])
        return vm.start(directory, **files, firmware=Path(item['path']), options_file=options_file,
                        single_display=single, maps=maps, display_scale=scale)
    if action == 'stop':
        if vm.status(directory)['phase'] == 'stopped':
            return {'phase': 'stopped', 'mode': 'virtual-hardware'}
        vm.shutdown(directory)
        return {'phase': 'stopping', 'mode': 'virtual-hardware'}
    if action == 'restart':
        previous = read_state(directory)
        vm.shutdown(directory)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            identity = previous.get('process', {})
            if vm.process_identity(identity.get('pid', 0)) != identity:
                files = previous['files']
                for key in ('single_display', 'internet'):
                    if isinstance(files.get(key), str):
                        files[key] = files[key] == 'True'
                return vm.start(directory, **files)
            time.sleep(.25)
        raise RuntimeError('Shutdown is still in progress. Wait for the VM to stop before starting again.')
    if action == 'focus':
        vm.guest_action(directory, 'focus', {'display': args.display})
        return focus(directory, args.display, backend)
    if action == 'browser':
        result = vm.guest_action(directory, action, {'mode': args.mode, 'url': args.url})
        focus(directory, 'center', backend)
        return result
    if action == 'steering':
        payload = {'button': args.button}
    elif action == 'camera':
        payload = {'source': args.source}
        from .virtual_inputs import import_media, connect_raw, stop_relay
        if args.source in ('video', 'replay'):
            payload['path'] = import_media(directory, args.path, args.source)
            stop_relay(directory)
        elif args.source == 'raw':
            payload['path'] = connect_raw(directory, args.path)
        else:
            stop_relay(directory)
    else:
        payload = json.loads(args.payload)
    return vm.guest_action(directory, action, payload)
