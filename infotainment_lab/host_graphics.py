"""Verified, application-scoped WSLg adapter selection.

This selects the host renderer. It does not install a driver in a firmware VM
or make the selected Windows GPU available as a guest PCI device.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import time

try:
    from .core import atomic_json, load_json
except ImportError:
    from core import atomic_json, load_json

ADAPTERS = ('AMD', 'NVIDIA', 'Intel')


def selection_path():
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'tsla-infotainment-lab/graphics.json'


def selection(path=None):
    saved = load_json(Path(path) if path else selection_path(), {})
    if not isinstance(saved, dict) or saved.get('adapter') not in ADAPTERS:
        return {}
    return saved


def environment(base=None, *, path=None, is_wsl=None):
    env = dict(os.environ if base is None else base)
    if is_wsl is None:
        is_wsl = 'microsoft' in platform.release().lower()
    saved = selection(path) if is_wsl else {}
    if saved:
        env.update(GALLIUM_DRIVER='d3d12', MESA_LOADER_DRIVER_OVERRIDE='d3d12',
                   MESA_D3D12_DEFAULT_ADAPTER_NAME=saved['adapter'])
    return env


def configure(adapter, *, path=None):
    if adapter not in ADAPTERS:
        raise ValueError('Choose AMD, NVIDIA or Intel.')
    if 'microsoft' not in platform.release().lower() or not Path('/dev/dxg').exists():
        raise RuntimeError('This adapter selector requires the WSLg GPU interface.')
    env = dict(os.environ, GALLIUM_DRIVER='d3d12', MESA_LOADER_DRIVER_OVERRIDE='d3d12',
               MESA_D3D12_DEFAULT_ADAPTER_NAME=adapter)
    result = subprocess.run(['glxinfo', '-B'], env=env, capture_output=True, text=True, timeout=20)
    fields = dict(line.strip().split(':', 1) for line in result.stdout.splitlines() if ':' in line)
    renderer = fields.get('OpenGL renderer string', '').strip()
    accelerated = fields.get('Accelerated', '').strip() == 'yes'
    if result.returncode or not accelerated or 'D3D12' not in renderer or adapter.lower() not in renderer.lower():
        raise RuntimeError(f'{adapter} hardware rendering was not verified; the previous selection is unchanged. '
                           f'Renderer: {renderer or "unavailable"}. {result.stderr.strip()[-500:]}')
    saved = {'adapter': adapter, 'renderer': renderer, 'accelerated': True,
             'verified_at': time.time(), 'scope': 'host-wslg', 'guest_gpu_verified': False}
    atomic_json(Path(path) if path else selection_path(), saved)
    return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('adapter', choices=ADAPTERS)
    args = parser.parse_args()
    print(json.dumps(configure(args.adapter), indent=2))


if __name__ == '__main__':
    main()
