import os
from pathlib import Path

import pytest

from infotainment_lab import qemu_audio as audio
from infotainment_lab.core import atomic_json


def test_buffering_is_scoped_to_wslg_and_preserves_other_desktop_audio():
    assert audio.required({'WSL_DISTRO_NAME': 'Debian'})
    assert not audio.required({})
    assert not audio.required({'PULSE_SERVER': 'unix:/run/user/1000/pulse/native'})
    assert not audio.required({'WSL_DISTRO_NAME': 'Debian', 'PULSE_SERVER': 'unix:/custom/audio'})


def test_audio_configuration_uses_only_private_socket_and_buffered_desktop_output(tmp_path):
    config = audio.configuration(tmp_path / 'a "quoted" directory')
    assert 'module-null-sink sink_name=lab_vm' in config
    # The tunnel creates its sink asynchronously; routing must wait for it.
    assert 'module-loopback' not in config
    assert '\\"quoted\\"' in config
    assert 'module-native-protocol-tcp' not in config
    assert 'auth-anonymous' not in config
    with pytest.raises(ValueError):
        audio.pulse_value('unix:/desktop\nload-module something')


def test_audio_status_does_not_report_a_previous_vm_or_recycled_process(tmp_path, monkeypatch):
    folder = tmp_path / 'audio'
    folder.mkdir()
    identity = {'pid': 40, 'start_ticks': 50, 'executable': '/usr/bin/python3'}
    atomic_json(folder / 'status.json', {'vm_uuid': 'current', 'process': identity, 'phase': 'running'})
    monkeypatch.setattr(audio, 'process_identity', lambda _: identity)
    assert audio.status(tmp_path, 'previous')['phase'] == 'unavailable'
    assert audio.status(tmp_path, 'current')['phase'] == 'running'
    monkeypatch.setattr(audio, 'process_identity', lambda _: identity | {'start_ticks': 51})
    assert audio.status(tmp_path, 'current')['phase'] == 'failed'


@pytest.mark.skipif(os.name == 'nt', reason='Linux socket ownership')
def test_audio_directory_rejects_shared_permissions_and_symlinks(tmp_path):
    folder = audio.private_directory(tmp_path)
    folder.chmod(0o755)
    with pytest.raises(ValueError, match='private'):
        audio.private_directory(tmp_path)
    folder.rmdir()
    target = tmp_path / 'target'
    target.mkdir(mode=0o700)
    folder.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match='private'):
        audio.private_directory(tmp_path)
