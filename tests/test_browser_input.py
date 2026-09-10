"""Exercise normal X11 events without launching firmware or visiting a site."""
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest


@pytest.mark.skipif(os.name == 'nt', reason='Linux X11 compatibility adapter')
def test_browser_drag_release_wheel_and_geometry_on_private_x_server(tmp_path):
    gcc = shutil.which('gcc')
    xvfb, xephyr = shutil.which('Xvfb'), shutil.which('Xephyr')
    if not gcc or not shutil.which('xdpyinfo') or not (xvfb or (xephyr and os.environ.get('DISPLAY'))):
        pytest.skip('Requires gcc and Xvfb, or Xephyr with a host display')
    pkg_config = shutil.which('pkg-config')
    if not pkg_config or subprocess.run([pkg_config, '--exists', 'x11'], capture_output=True).returncode:
        pytest.skip('Requires X11 development headers')
    root = Path(__file__).resolve().parents[1]
    fixture = root / 'tests/browser_input_harness.c'
    flags = [gcc, '-Wall', '-Wextra', '-Werror']
    stub = tmp_path / 'libui-stub.so'
    adapter = tmp_path / 'browser-input.so'
    harness = tmp_path / 'browser-input-test'
    subprocess.run(flags + ['-shared', '-fPIC', '-DUI_STUB', str(fixture), '-o', str(stub)], check=True)
    subprocess.run(flags + ['-shared', '-fPIC', str(root / 'infotainment_lab/runtime/native-browser-input.c'),
                           '-o', str(adapter), '-lX11', '-ldl'], check=True)
    subprocess.run(flags + [str(fixture), '-o', str(harness), '-L' + str(tmp_path), '-lui-stub',
                           '-Wl,-rpath,' + str(tmp_path), '-lX11'], check=True)

    # WSLg's X socket directory can be read-only. A numbered server permits its
    # normal Linux abstract socket; -displayfd requires every transport to bind.
    slots = [n for n in range(90, 190) if not Path(f'/tmp/.X{n}-lock').exists()
             and not Path(f'/tmp/.X11-unix/X{n}').exists()]
    assert slots, 'No private X11 test display slot is available.'
    display_number = str(slots[0])
    arguments = [xvfb or xephyr, ':' + display_number, '-nolisten', 'tcp', '-noreset', '-pn']
    if xvfb:
        arguments += ['-screen', '0', '1100x900x24']
    else:
        arguments += ['-screen', '1100x900', '-title', 'Infotainment Lab input test']
    with (tmp_path / 'x-server.log').open('w') as log:
        server = subprocess.Popen(arguments, stdout=log, stderr=log)
        try:
            environment = dict(os.environ, DISPLAY=':' + display_number, LD_PRELOAD=str(adapter))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and server.poll() is None:
                if subprocess.run(['xdpyinfo', '-display', ':' + display_number], capture_output=True, timeout=2).returncode == 0:
                    break
                time.sleep(.05)
            else:
                pytest.fail((tmp_path / 'x-server.log').read_text()[-3000:])
            assert server.poll() is None
            assert Path(f'/tmp/.X{display_number}-lock').read_text().strip() == str(server.pid)
            result = subprocess.run([str(harness)], env=environment, capture_output=True, text=True, timeout=15)
            assert result.returncode == 0, result.stdout + result.stderr
            assert 'drag, release, wheel and resize passed' in result.stdout
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
