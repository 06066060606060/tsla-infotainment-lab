import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import pytest
from infotainment_lab import qemu_runtime as runtime


def test_process_identity_rejects_missing_pid():
    assert runtime.process_identity(-1) is None


def test_unconfigured_vm_is_stopped(tmp_path):
    assert runtime.status(tmp_path) == {'phase': 'stopped', 'desktop_verified': False}


def test_pid_reuse_does_not_control_another_process(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'process_identity', lambda _: {'pid': 12, 'start_ticks': 99})
    with pytest.raises(RuntimeError, match='no longer running'):
        runtime.verify_identity(tmp_path, {'process': {'pid': 12, 'start_ticks': 20}})


def test_boot_check_preserves_active_vm_files(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from infotainment_lab import qemu_boot
    identity = {'pid': 12, 'start_ticks': 20}
    (tmp_path / 'vm.json').write_text(json.dumps({'process': identity}))
    kernel = tmp_path / 'vendor-kernel'
    kernel.write_bytes(b'existing kernel')
    monkeypatch.setattr(runtime, 'process_identity', lambda _: identity)
    monkeypatch.setattr(runtime, 'lifecycle_lock', lambda directory: nullcontext(directory))
    monkeypatch.setattr(qemu_boot, '_boot_check', lambda *_: pytest.fail('Active guest files must not be prepared again'))
    with pytest.raises(RuntimeError, match='still running'):
        qemu_boot.boot_check(tmp_path / 'firmware', tmp_path)
    assert kernel.read_bytes() == b'existing kernel'


def test_unknown_socket_failure_does_not_allow_reprovisioning(tmp_path, monkeypatch):
    (tmp_path / 'vm-qmp.sock').touch()
    def unavailable(*_):
        raise TimeoutError('temporarily unresponsive')
    monkeypatch.setattr(runtime, 'QMP', unavailable)
    with pytest.raises(RuntimeError, match='could not be verified'):
        runtime.ensure_idle(tmp_path)


def test_stale_legacy_socket_is_usable_only_after_process_exit(tmp_path, monkeypatch):
    (tmp_path / 'runtime-qmp.sock').touch()
    (tmp_path / 'runtime.pid').write_text('1234')
    def disconnected(*_):
        raise ConnectionRefusedError()
    monkeypatch.setattr(runtime, 'QMP', disconnected)
    monkeypatch.setattr(runtime, 'process_identity', lambda _: {'pid': 1234})
    with pytest.raises(RuntimeError, match='still present'):
        runtime.ensure_idle(tmp_path)
    monkeypatch.setattr(runtime, 'process_identity', lambda _: None)
    runtime.ensure_idle(tmp_path)


def test_vm_arguments_keep_the_vendor_kernel_and_persistent_disk(tmp_path):
    args = runtime.launch_arguments(tmp_path, str(uuid.uuid4()))
    assert args[args.index('-kernel') + 1] == str(tmp_path / 'vendor-kernel')
    assert 'snapshot=on' not in ' '.join(args)
    assert 'guest-runtime.qcow2' in ' '.join(args)
    local_net = args[args.index('-nic') + 1]
    assert '192.168.90.0/24' in local_net and 'restrict=on' in local_net
    assert args.count('-nic') == 1
    assert 'tpm-tis,tpmdev=tpm0' in args
    assert '-virtfs' not in args and '-initrd' not in args


def test_upstream_is_separate_from_the_firmware_local_network(tmp_path):
    args = runtime.launch_arguments(tmp_path, str(uuid.uuid4()), internet=True)
    networks = [args[i + 1] for i, arg in enumerate(args) if arg == '-nic']
    assert len(networks) == 2
    assert 'restrict=on' in networks[0]
    assert networks[1] == 'user,model=igb'


def test_boot_milestones_survive_a_long_formatting_log(tmp_path):
    log = tmp_path / 'vm-serial.log'
    log.write_text('Linux version 5.4\nverity-init booting\nswitching root and executing /sbin/init\n' + 'formatting\n' * 20000)
    evidence = runtime.classify_boot(runtime.boot_evidence(log))
    assert evidence['kernel_started'] and evidence['vendor_root_entered']
    assert evidence['desktop_verified'] is False


@pytest.mark.skipif(not shutil.which('qemu-system-x86_64') or os.name != 'posix', reason='Requires local Linux QEMU')
def test_real_qmp_identity_status_and_shutdown_request(tmp_path):
    # A paused empty machine exercises the actual control protocol without a
    # vendor image, mounted host storage or a network interface.
    identifier = str(uuid.uuid4())
    socket_path = tmp_path / 'vm-qmp.sock'
    if len(str(socket_path).encode()) > 100:
        pytest.skip('Test temporary path exceeds the Unix socket length limit')
    process = subprocess.Popen(['qemu-system-x86_64', '-machine', 'q35,accel=tcg',
        '-S', '-nodefaults', '-display', 'none', '-monitor', 'none', '-nic', 'none',
        '-uuid', identifier, '-qmp', f'unix:{socket_path},server=on,wait=off'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(50):
            if socket_path.exists(): break
            assert process.poll() is None
            time.sleep(.05)
        state = {'uuid': identifier, 'process': runtime.process_identity(process.pid), 'started_at': time.time()}
        (tmp_path / 'vm.json').write_text(json.dumps(state))
        actual = runtime.status(tmp_path)
        assert actual['qemu_status'] == 'prelaunch'
        assert actual['desktop_verified'] is False
        with pytest.raises(RuntimeError, match='different VM'):
            runtime.verify_identity(tmp_path, dict(state, uuid=str(uuid.uuid4())))
        reply = runtime.shutdown(tmp_path)
        assert 'shutdown_requested_at' in reply
        assert process.poll() is None  # A request is not an asserted shutdown.
    finally:
        process.terminate()
        process.wait(timeout=5)
