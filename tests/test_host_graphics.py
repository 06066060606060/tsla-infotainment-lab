import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from infotainment_lab import host_graphics as graphics


def test_selection_changes_only_the_application_environment(tmp_path):
    path = tmp_path / 'graphics.json'
    path.write_text(json.dumps({'adapter': 'AMD'}))
    original = {'DISPLAY': ':0', 'UNCHANGED': 'value'}
    env = graphics.environment(original, path=path, is_wsl=True)
    assert env['GALLIUM_DRIVER'] == 'd3d12'
    assert env['MESA_D3D12_DEFAULT_ADAPTER_NAME'] == 'AMD'
    assert env['UNCHANGED'] == 'value'
    assert original == {'DISPLAY': ':0', 'UNCHANGED': 'value'}
    assert graphics.environment(original, path=path, is_wsl=False) == original


@pytest.fixture
def wsl_environment(monkeypatch):
    monkeypatch.setattr(graphics.platform, 'release', lambda: '6.18-microsoft-standard-WSL2')
    exists = Path.exists
    monkeypatch.setattr(Path, 'exists', lambda p: True if p.as_posix() == '/dev/dxg' else exists(p))


@pytest.mark.parametrize('renderer,accelerated', [
    ('llvmpipe (LLVM)', 'no'), ('D3D12 (NVIDIA GeForce)', 'yes'),
    ('D3D12 (AMD Radeon)', 'no'), ('llvmpipe AMD', 'yes')])
def test_failed_or_wrong_adapter_check_preserves_saved_selection(tmp_path, monkeypatch, wsl_environment, renderer, accelerated):
    path = tmp_path / 'graphics.json'
    previous = json.dumps({'adapter': 'Intel'})
    path.write_text(previous)
    monkeypatch.setattr(graphics.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=f'Accelerated: {accelerated}\nOpenGL renderer string: {renderer}\n', stderr=''))
    with pytest.raises(RuntimeError, match='previous selection is unchanged'):
        graphics.configure('AMD', path=path)
    assert path.read_text() == previous


def test_verified_host_gpu_is_not_claimed_as_guest_acceleration(tmp_path, monkeypatch, wsl_environment):
    def probe(command, **kwargs):
        assert command == ['glxinfo', '-B']
        assert kwargs['env']['MESA_D3D12_DEFAULT_ADAPTER_NAME'] == 'AMD'
        return SimpleNamespace(returncode=0, stderr='', stdout=
            '  Accelerated: yes\nOpenGL renderer string: D3D12 (AMD Radeon(TM) Graphics)\n')
    monkeypatch.setattr(graphics.subprocess, 'run', probe)
    path = tmp_path / 'graphics.json'
    result = graphics.configure('AMD', path=path)
    assert json.loads(path.read_text()) == result
    assert result['scope'] == 'host-wslg' and result['guest_gpu_verified'] is False
