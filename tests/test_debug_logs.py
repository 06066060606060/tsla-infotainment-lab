import os
from types import SimpleNamespace

import pytest
from infotainment_lab import debug_logs


def test_tail_is_bounded_and_reads_binary_utf8_safely(tmp_path):
    log = tmp_path / 'center.log'
    log.write_bytes(b'x' * 100000 + b'latest\xff')
    text = debug_logs.tail(log)
    assert len(text) < debug_logs.MAX_BYTES + 100
    assert text.startswith('[Earlier output omitted.]')
    assert text.endswith('latest\ufffd')


@pytest.mark.skipif(os.name == 'nt', reason='POSIX no-follow and FIFO boundaries')
def test_log_symlink_and_fifo_do_not_read_outside_or_block(tmp_path):
    private = tmp_path / 'private'
    private.write_text('must not read this')
    linked = tmp_path / 'linked.log'
    linked.symlink_to(private)
    assert 'must not read this' not in debug_logs.tail(linked)
    fifo = tmp_path / 'pipe.log'
    os.mkfifo(fifo)
    assert 'not a regular file' in debug_logs.tail(fifo)


def test_native_and_guest_journals_are_labelled_and_scoped(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(debug_logs, 'journal', lambda args: calls.append(args) or 'journal')
    (tmp_path / 'center.log').write_text('firmware output')
    native = debug_logs.snapshot(tmp_path, 'owned.service')
    assert native['logs']['center.log'] == 'firmware output'
    assert '--user' in calls[0] and 'owned.service' in calls[0]
    assert 'Host kernel (native runtime)' in native['logs']
    calls.clear()
    guest = debug_logs.snapshot(tmp_path, 'lab-desktop.service', guest=True)
    assert '--user' not in calls[0] and 'lab-desktop.service' in calls[0]
    assert 'Guest kernel' in guest['logs'] and 'Guest OS journal' in guest['logs']


def test_unavailable_journal_returns_a_readable_notice(monkeypatch):
    monkeypatch.setattr(debug_logs.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stderr='Permission denied'))
    assert 'Permission denied' in debug_logs.journal(['-k'])


def test_qemu_serial_remains_available_when_guest_agent_is_not_ready(tmp_path, monkeypatch):
    from infotainment_lab import virtual_control
    (tmp_path / 'vm-serial.log').write_text('kernel boot message')
    def unavailable(*a, **k):
        raise ConnectionRefusedError('Guest not ready')
    monkeypatch.setattr(virtual_control.vm, 'guest_action', unavailable)
    args = SimpleNamespace(vm_directory=str(tmp_path), action='debug')
    result = virtual_control.dispatch(args, SimpleNamespace())
    assert result['logs']['vm-serial.log'] == 'kernel boot message'
    assert 'Guest journals unavailable' in result['notice']


def test_qemu_debug_merges_serial_and_guest_sources(tmp_path, monkeypatch):
    from infotainment_lab import virtual_control
    (tmp_path / 'vm-serial.log').write_text('serial')
    monkeypatch.setattr(virtual_control.vm, 'guest_action', lambda *a, **k: {'logs': {'Guest kernel': 'guest journal'}})
    result = virtual_control.dispatch(SimpleNamespace(vm_directory=str(tmp_path), action='debug'), SimpleNamespace())
    assert result['logs'] == {'vm-serial.log': 'serial', 'Guest / Guest kernel': 'guest journal'}
