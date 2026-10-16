import os
from pathlib import Path
import socket
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'infotainment_lab'))
import native_vehicle


@pytest.mark.skipif(os.name == 'nt', reason='Unix socket paths required')
def test_emitter_socket_namespace_only_removes_private_links_and_keeps_inputs_read_only(tmp_path, monkeypatch):
    source = tmp_path / 'original'
    source.mkdir()
    outputs = tmp_path / 'vehicle-observer-outputs'
    outputs.mkdir(mode=0o700)
    protected = tmp_path / 'must-remain'
    protected.write_text('original data')
    (outputs / 'stale.sock').symlink_to(protected)
    calls, handles = [], []

    def run(args, **kwargs):
        calls.append(args)
        if args[:2] == ['mount', '--bind'] and args[2] == str(source):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.bind(str(Path(args[3]) / 'in.sock'))
            handles.append(sock)

    monkeypatch.setattr(native_vehicle.subprocess, 'run', run)
    try:
        native_vehicle.isolate(tmp_path, source)
        assert protected.read_text() == 'original data'
        assert not (outputs / 'stale.sock').exists()
        assert (outputs / 'in.sock').is_symlink()
        assert ['mount', '-o', 'remount,bind,ro', str(tmp_path / 'vehicle-observer-inputs')] in calls
        assert calls[-1] == ['mount', '--bind', str(outputs), str(source)]
    finally:
        for sock in handles:
            sock.close()


def test_vehicle_emitter_uses_only_owned_loopback_endpoints(tmp_path):
    args = native_vehicle.arguments(tmp_path)
    assert args[0] == str(tmp_path / 'usr/tesla/UI/bin/QtCarVehicle')
    for flag in ('--gw', '--cid', '--ic', '--ip'):
        assert args[args.index(flag) + 1].startswith('127.')


@pytest.mark.skipif(os.name == 'nt', reason='Unix directory ownership required')
def test_observer_does_not_follow_a_socket_directory_symlink(tmp_path):
    outside = tmp_path / 'unrelated'
    outside.mkdir()
    protected = outside / 'keep'
    protected.write_text('untouched')
    (tmp_path / 'vehicle-observer-outputs').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='private directories'):
        native_vehicle.isolate(tmp_path, tmp_path)
    assert protected.read_text() == 'untouched'
