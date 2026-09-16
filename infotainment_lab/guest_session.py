"""Start the existing compatibility runtime on a prepared VM's native X screen."""
from pathlib import Path
import json
import os
import subprocess
import sys

from core import atomic_json, profile_for
from simulation import Simulation


def main():
    firmware = Path('/firmware')
    version = (firmware / 'etc/customer-version').read_text().strip()
    variant = (firmware / 'etc/product-variants').read_text().strip()
    if not variant:
        variant = '_'.join((firmware / ('etc/' + name)).read_text().strip()
                           for name in ('product', 'product-platform'))
    profile = profile_for(version, variant)
    if not profile:
        raise ValueError(f'No compatible application profile for {version} / {variant}.')
    state = Path.home() / 'session'
    state.mkdir(mode=0o700, exist_ok=True)
    single = bool(profile.get('single_display'))
    old = json.loads((state / 'config.json').read_text()) if (state / 'config.json').exists() else {}
    options_path = Path('/run/user/1000/lab-launch.json')
    options = json.loads(options_path.read_text()) if options_path.exists() else {}
    config = dict(firmware=str(firmware), firmware_version=version, profile=profile['id'],
                  state=str(state), single_display=single, cluster=not single and options.get('cluster', True),
                  browser=options.get('browser', True), maps='/maps' if os.path.ismount('/maps') else None,
                  firmware_id=options.get('firmware_id'), map_id=options.get('map_id'),
                  display=':0.0', center_display=':0.0',
                  cluster_display=':1.0', display_backend='provided', cluster_gpu_offload=True,
                  shared_desktop=False, pulse='unix:/run/user/1000/pulse/native', wsl=False)
    atomic_json(state / 'config.json', config)
    atomic_json(state / 'controls.json', Simulation().as_dict())
    camera_path = state / 'camera-source.json'
    if camera_path.exists():
        camera = json.loads(camera_path.read_text())
        if camera.get('mode') == 'replay':
            camera['autoplay'] = False
            atomic_json(camera_path, camera)
    env = dict(os.environ, DISPLAY=':0.0', XDG_RUNTIME_DIR='/run/user/1000')
    # Start the daemon before setting PULSE_SERVER: that variable disables
    # PulseAudio's normal local startup path.
    pulse_env = dict(env)
    pulse_env.pop('PULSE_SERVER', None)
    subprocess.run(['pulseaudio', '--start', '--exit-idle-time=-1'], env=pulse_env, check=True)
    # EDID's legacy 720-wide mode can be interpreted as 720x400. Register
    # the portrait timing explicitly instead of accepting that truncated mode.
    modes = subprocess.run(['xrandr'], env=env, check=True, capture_output=True, text=True).stdout
    output = next(line.split()[0] for line in modes.splitlines() if ' connected' in line)
    mode = '1920x1200' if single else '720x1152_lab'
    if not single and mode not in modes:
        subprocess.run(['xrandr', '--newmode', mode, '68.75', '720', '768', '840', '960',
                        '1152', '1155', '1165', '1195', '-hsync', '+vsync'], env=env, check=True)
        subprocess.run(['xrandr', '--addmode', output, mode], env=env, check=True)
    subprocess.run(['xrandr', '--output', output, '--mode', mode], env=env, check=True)
    if not single:
        subprocess.run(['xrandr', '--auto'], env=dict(env, DISPLAY=':1.0'), check=True)
    env['PULSE_SERVER'] = config['pulse']
    supervisor = Path(__file__).with_name('supervisor.py')
    os.execve(sys.executable, [sys.executable, str(supervisor), str(state / 'config.json')], env)


if __name__ == '__main__':
    main()
