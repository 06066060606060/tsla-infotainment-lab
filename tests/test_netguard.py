import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest

SHIM = Path(__file__).resolve().parents[1] / 'infotainment_lab/runtime/native-netguard.c'
PROBE = '''
import socket, sys
for name in sys.argv[1:]:
    try:
        print(name, socket.getaddrinfo(name, 443, socket.AF_INET)[0][4][0])
    except socket.gaierror as exc:
        print(name, 'error', exc.errno)
'''


@pytest.mark.skipif(os.name == 'nt' or not shutil.which('gcc'), reason='Linux preload shim')
def test_firmware_lookups_of_tesla_domains_fail_and_media_names_stay_local(tmp_path):
    library = tmp_path / 'netguard.so'
    subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror', str(SHIM), '-o', str(library), '-ldl'],
                   check=True, capture_output=True)
    names = ['hermes.vn.teslamotors.com', 'WWW.Tesla.COM.', 'tesla.services', 'x.vn.cloud.tesla.cn',
             'firmware-media.vn.teslamotors.com', 'localhost', 'notesla.com']
    run = subprocess.run([sys.executable, '-c', PROBE, *names], capture_output=True, text=True, timeout=30,
                         env=dict(os.environ, LD_PRELOAD=str(library)))
    result = dict(line.split(' ', 1) for line in run.stdout.splitlines())
    for name in names[:4]:
        assert result[name] == f'error {socket.EAI_NONAME}'
    assert result['firmware-media.vn.teslamotors.com'] == '127.0.0.1'
    assert result['localhost'] == '127.0.0.1'
    assert 'notesla.com' not in run.stderr  # a lookalike domain is not blocked
    assert 'netguard: blocked lookup of hermes.vn.teslamotors.com' in run.stderr


@pytest.mark.skipif(os.name == 'nt' or not shutil.which('gcc'), reason='Linux preload shim')
@pytest.mark.parametrize('enabled', ['0', '1'])
def test_navigation_rpc_listener_is_local_without_changing_udp_telemetry(tmp_path, enabled):
    library = tmp_path / 'netguard.so'
    subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror', str(SHIM),
                    '-o', str(library), '-ldl'], check=True, capture_output=True)
    probe = '''
import socket
for kind in [socket.SOCK_STREAM, socket.SOCK_DGRAM]:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(('0.0.0.0', 0))
        print(s.getsockname()[0])
'''
    result = subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True, check=True,
        env=dict(os.environ, LD_PRELOAD=str(library), TESLA_NATIVE_SERVICE_LOOPBACK=enabled))
    assert result.stdout.splitlines() == ['127.0.0.1' if enabled == '1' else '0.0.0.0', '0.0.0.0']

