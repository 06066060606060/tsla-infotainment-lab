import importlib.util
import io
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('guest_builder', Path(__file__).resolve().parents[1] / 'scripts/build-virtual-guest.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_private_vm_displays_stay_awake_without_changing_host_power_settings(tmp_path):
    import shlex
    builder.configure_displays(tmp_path)
    for filename, prefix in [('lab-xclient', 'Xorg :1'), ('lab-xorg', 'exec xinit ')]:
        content = (tmp_path / 'usr/local/bin' / filename).read_text()
        line = next(line for line in content.splitlines() if line.startswith(prefix))
        argv = shlex.split(line)
        assert argv[argv.index('-s') + 1] == '0'
        assert '-dpms' in argv
        assert '-auth' in argv and argv[argv.index('-nolisten') + 1] == 'tcp'
    assert set(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*') if p.is_file()) == {
        'etc/X11/lab-center.conf', 'etc/X11/lab-cluster.conf',
        'usr/local/bin/lab-xclient', 'usr/local/bin/lab-xorg'}


def test_package_integrity_is_checked_before_any_guest_install(tmp_path, monkeypatch):
    monkeypatch.setattr(builder.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(b'wrong package'))
    calls = []
    monkeypatch.setattr(builder, 'run', lambda *args: calls.append(args))
    with pytest.raises(ValueError, match='checksum'):
        builder.install_virtualgl(tmp_path)
    assert not calls and not list(tmp_path.iterdir())


def test_verified_package_installs_only_in_guest_and_is_removed_after_failure(tmp_path, monkeypatch):
    data = b'test package'
    monkeypatch.setattr(builder, 'VGL_SHA256', builder.hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(builder.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(data))
    (tmp_path / 'tmp').mkdir()
    def fail(*args):
        assert args[:2] == ('chroot', tmp_path)
        assert (tmp_path / args[-1].lstrip('/')).read_bytes() == data
        raise RuntimeError('installation failed')
    monkeypatch.setattr(builder, 'run', fail)
    with pytest.raises(RuntimeError, match='installation failed'):
        builder.install_virtualgl(tmp_path)
    assert not list((tmp_path / 'tmp').iterdir())
