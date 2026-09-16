import importlib.util
import io
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('guest_builder', Path(__file__).resolve().parents[1] / 'scripts/build-virtual-guest.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


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
