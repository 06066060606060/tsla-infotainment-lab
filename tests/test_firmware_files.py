"""Replacement boundaries, immutable originals and an opt-in synthetic FUSE check."""
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from infotainment_lab import firmware_files as files

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Linux filesystem mounts and ownership')
ID = 'a' * 16


@pytest.fixture
def image(tmp_path):
    root = tmp_path / 'firmware'
    member = root / 'usr/share/test.qml'
    member.parent.mkdir(parents=True)
    member.write_bytes(b'original\x00content')
    member.chmod(0o555)
    source = tmp_path / 'chosen.qml'
    source.write_bytes(b'replacement\x00content')
    return root, member, source


def test_replace_remove_and_per_image_isolation(tmp_path, image):
    root, member, source = image
    data = tmp_path / 'data'
    result = files.put(data, ID, root, '/usr/share/test.qml', source)
    assert result == [{'target': '/usr/share/test.qml', 'bytes': source.stat().st_size}]
    replacement = files.tree(data, ID) / 'usr/share/test.qml'
    assert replacement.read_bytes() == source.read_bytes()
    assert replacement.stat().st_mode & 0o777 == 0o555
    assert member.read_bytes() == b'original\x00content'
    assert files.entries(files.tree(data, 'b' * 16)) == []
    assert files.remove(data, ID, '/usr/share/test.qml') == []
    assert member.read_bytes() == b'original\x00content'


@pytest.mark.parametrize('target', ['', '/', '//etc/file', 'etc/../file', '../outside', '/etc//file', '/etc/./file', 'etc\\file', '/etc/.wh.hidden', '/etc/.pending-file'])
def test_invalid_target_never_reaches_host_files(tmp_path, image, target):
    root, _, source = image
    with pytest.raises(ValueError):
        files.put(tmp_path / 'data', ID, root, target, source)


def test_refuses_symlink_members_and_parent_directories(tmp_path, image):
    root, _, source = image
    (root / 'etc').symlink_to(tmp_path, target_is_directory=True)
    (root / 'alias').symlink_to(source)
    for target in ('/etc/chosen.qml', '/alias'):
        with pytest.raises(ValueError, match='symbolic link'):
            files.put(tmp_path / 'data', ID, root, target, source)
    assert source.read_bytes() == b'replacement\x00content'


def test_refuses_tampered_replacement_storage(tmp_path, image):
    root, _, source = image
    data = tmp_path / 'data'
    upper = files.tree(data, ID)
    (upper / 'usr').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='Symbolic links'):
        files.put(data, ID, root, '/usr/share/test.qml', source)
    with pytest.raises(ValueError, match='Symbolic links'):
        files.remove(data, ID, '/usr/share/test.qml')


def test_missing_original_is_not_added_to_firmware(tmp_path, image):
    root, _, source = image
    with pytest.raises(ValueError, match='existing regular file'):
        files.put(tmp_path / 'data', ID, root, '/missing', source)


def test_changed_source_is_not_published(tmp_path, image, monkeypatch):
    root, _, source = image
    copy = files.shutil.copyfileobj
    def change(input_file, output, size):
        copy(input_file, output, size)
        source.write_bytes(b'changed while copying')
    monkeypatch.setattr(files.shutil, 'copyfileobj', change)
    with pytest.raises(RuntimeError, match='changed while being copied'):
        files.put(tmp_path / 'data', ID, root, '/usr/share/test.qml', source)
    assert files.entries(files.tree(tmp_path / 'data', ID)) == []


def test_active_native_session_blocks_replacement_mutation(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
    import backend
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    monkeypatch.setattr(backend, 'library_item', lambda _: {'kind': 'firmware'})
    monkeypatch.setattr(backend, 'status', lambda: {'phase': 'running'})
    monkeypatch.setattr(backend, 'session_config', lambda **_: {'firmware_id': ID})
    with pytest.raises(RuntimeError, match='Stop this firmware session'):
        backend.firmware_replacements(ID, 'remove', '/test')
    assert backend.firmware_replacements(ID)['files'] == []


def test_active_vm_blocks_replacement_mutation(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
    import backend
    import qemu_runtime
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    monkeypatch.setattr(backend, 'library_item', lambda _: {'kind': 'firmware', 'path': '/image'})
    monkeypatch.setattr(backend, 'status', lambda: {'phase': 'stopped'})
    monkeypatch.setattr(backend, 'session_config', lambda **_: {})
    identity = {'pid': 123}
    monkeypatch.setattr(qemu_runtime, 'read_state', lambda _: {'process': identity, 'files': {'firmware': '/image'}})
    monkeypatch.setattr(qemu_runtime, 'process_identity', lambda _: identity)
    with pytest.raises(RuntimeError, match='Stop this firmware VM'):
        backend.firmware_replacements(ID, 'remove', '/test')


def test_stop_releases_views_before_squashfs(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
    import backend
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    for directory in ('views', 'mounts'):
        (tmp_path / directory / ID).mkdir(parents=True)
    monkeypatch.setattr(backend, 'systemctl', lambda *a, **k: SimpleNamespace(stdout='inactive'))
    monkeypatch.setattr(backend, 'status', lambda: {})
    released = []
    monkeypatch.setattr(backend, 'release_mount', lambda path: released.append(path.parent.name) or True)
    backend.stop()
    assert released == ['views', 'mounts']


def test_qemu_stages_explicit_files_in_a_read_only_private_share(tmp_path, image):
    from infotainment_lab.virtual_control import stage_replacements
    from infotainment_lab.core import atomic_json
    root, _, source = image
    data = tmp_path / 'data'
    files.put(data, ID, root, '/usr/share/test.qml', source)
    vm = tmp_path / 'vm'
    vm.mkdir(mode=0o700)
    atomic_json(vm / 'build.json', {'firmware_replacements': True})
    options = {'firmware_id': ID}
    stage_replacements(vm, SimpleNamespace(DATA=data), options)
    snapshot = vm / 'inputs' / options['replacements'] / 'usr/share/test.qml'
    assert snapshot.read_bytes() == source.read_bytes()
    # Editing the next launch's replacements cannot change this staged session.
    files.remove(data, ID, '/usr/share/test.qml')
    assert snapshot.read_bytes() == source.read_bytes()


def test_old_qemu_guest_does_not_silently_ignore_replacements(tmp_path, image):
    from infotainment_lab.virtual_control import stage_replacements
    root, _, source = image
    data = tmp_path / 'data'
    files.put(data, ID, root, '/usr/share/test.qml', source)
    with pytest.raises(RuntimeError, match='Rebuild the QEMU guest'):
        stage_replacements(tmp_path, SimpleNamespace(DATA=data), {'firmware_id': ID})


def test_guest_mount_keeps_original_and_replacements_read_only(monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
    import guest_firmware
    calls = []
    guest_firmware.mount_firmware({}, run=lambda argv, **kw: calls.append(argv))
    assert calls == [['mount', '-o', 'bind,ro', '/firmware-base', '/firmware']]
    monkeypatch.setattr(guest_firmware.Path, 'is_dir', lambda _: True)
    monkeypatch.setattr(guest_firmware.Path, 'is_symlink', lambda _: False)
    monkeypatch.setattr(guest_firmware, 'entries', lambda _: [])
    name = 'firmware-replacements-' + 'a' * 32
    guest_firmware.mount_firmware({'replacements': name}, run=lambda argv, **kw: calls.append(argv))
    assert calls[-1] == ['fuse-overlayfs', '-o', 'ro,nosuid,nodev,allow_other,lowerdir=/inputs/' + name + ':/firmware-base', '/firmware']
    for invalid in ('../escape', '/etc', 'firmware-replacements-a,lowerdir=/etc'):
        with pytest.raises(ValueError):
            guest_firmware.mount_firmware({'replacements': invalid}, run=lambda *a, **k: pytest.fail('Must not mount'))


def test_full_reset_refuses_to_delete_through_held_overlay(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
    import backend
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    view = tmp_path / 'views' / ID
    view.mkdir(parents=True)
    sentinel = view / 'must-preserve'
    sentinel.write_text('protected')
    monkeypatch.setattr(backend, 'stop', lambda: None)
    monkeypatch.setattr(backend, 'release_mount', lambda _: False)
    with pytest.raises(RuntimeError, match='nothing was deleted'):
        backend.factory_reset()
    assert sentinel.read_text() == 'protected'


@pytest.mark.skipif(os.environ.get('LAB_TEST_FUSE') != '1', reason='Explicit opt-in for synthetic FUSE mount')
def test_real_squashfs_overlay_preserves_original_and_refuses_writes(tmp_path, image):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
    import backend
    root, original, source = image
    for command in ('mksquashfs', 'squashfuse', 'fuse-overlayfs', 'fusermount3'):
        assert shutil.which(command), command
    squashfs = tmp_path / 'synthetic.squashfs'
    subprocess.run(['mksquashfs', str(root), str(squashfs), '-noappend', '-quiet'], check=True, capture_output=True)
    before = squashfs.read_bytes()
    lower = tmp_path / 'lower'
    lower.mkdir()
    subprocess.run(['squashfuse', '-o', 'ro', str(squashfs), str(lower)], check=True)
    view = tmp_path / 'view'
    try:
        files.put(tmp_path / 'data', ID, lower, '/usr/share/test.qml', source)
        mounted = files.mount_view(lower, files.tree(tmp_path / 'data', ID), view, backend.run)
        assert (mounted / 'usr/share/test.qml').read_bytes() == source.read_bytes()
        assert (lower / 'usr/share/test.qml').read_bytes() == original.read_bytes()
        with pytest.raises(OSError):
            (mounted / 'must-not-exist').write_text('no')
        assert backend.release_mount(view)
        files.remove(tmp_path / 'data', ID, '/usr/share/test.qml')
        assert files.mount_view(lower, files.tree(tmp_path / 'data', ID), view, backend.run) == lower
        assert squashfs.read_bytes() == before
    finally:
        backend.release_mount(view)
        backend.release_mount(lower)


HVAC_LINES = ('ClimateControlPanel = "HVACPanelSize; X:0; Y:360; BackgroundColor:transparent;"\n'
              'BackgroundView = "CenterDisplayWidth; X:0; Y:360; Height:680;"\n'
              'ViewSwitchStyle = "AlignItems:center; JustifyContent:center; HVAC/HVACViewWidth; X:0; Y:380; PositionType:absolute;"\n'
              'KeepClimatePopupStyleCommon = "BackgroundColor:transparent; X:608; Y:230; PositionType:absolute; Height:100; Width:708;"\n')


def test_layout_layer_lifts_the_controls_and_hvac_panels(tmp_path):
    base = tmp_path / 'firmware'
    styles = base / files.STYLES
    styles.parent.mkdir(parents=True)
    styles.write_text('A = "x"\nControlPanelHeight = "Height:1040;"\nAppWindowHeight = "Height:1040;"\n' + HVAC_LINES)
    layer = files.layout_layer(base, tmp_path / 'layout')
    assert (layer / files.STYLES).read_text() == (
        'A = "x"\nControlPanelHeight = "Height:1140;"\nAppWindowHeight = "Height:1040;"\n'
        + HVAC_LINES.replace('Y:360', 'Y:260').replace('Y:380', 'Y:280').replace('Y:230', 'Y:130'))
    assert styles.read_text().count('1040') == 2  # the image itself is never touched
    assert files.layout_layer(base, tmp_path / 'layout') == layer  # a second start rewrites its read-only copy


def test_layout_layer_patches_the_values_that_match(tmp_path):
    base = tmp_path / 'firmware'
    (base / files.STYLES).parent.mkdir(parents=True)
    (base / files.STYLES).write_text('ControlPanelHeight = "Height:1000;"\n' + HVAC_LINES)
    layer = files.layout_layer(base, tmp_path / 'layout')
    assert (layer / files.STYLES).read_text() == (
        'ControlPanelHeight = "Height:1000;"\n' + HVAC_LINES.replace('Y:360', 'Y:260').replace('Y:380', 'Y:280').replace('Y:230', 'Y:130'))


def test_layout_layer_skips_builds_with_a_different_style_file(tmp_path):
    base = tmp_path / 'firmware'
    assert files.layout_layer(base, tmp_path / 'layout') is None
    (base / files.STYLES).parent.mkdir(parents=True)
    (base / files.STYLES).write_text('ControlPanelHeight = "Height:1000;"\n')
    assert files.layout_layer(base, tmp_path / 'layout') is None
    assert not (tmp_path / 'layout').exists()


def test_layout_layer_leaves_room_under_the_scrolling_lists(tmp_path):
    base = tmp_path / 'firmware'
    page = 'PageLayout = "ControlsPanel/ControlsPanelWidth; FlexDirection:column; JustifyContent:FlexStart; Padding:0,40,0,%d; Margin:20,0,20,0; TouchPadding:20;"\n'
    for member, text in ((files.STYLES, 'TabLayout += "Padding:0,25; TabWidth:420; TabHeight:71;"\n' + page % 0),
                         (files.COMMON, 'ScrollableSettingsPanel = "Flex:1; MaxHeight:800; Margin:0,20,20,20;"\n')):
        (base / member).parent.mkdir(parents=True, exist_ok=True)
        (base / member).write_text(text)
    layer = files.layout_layer(base, tmp_path / 'layout')
    assert (layer / files.STYLES).read_text() == 'TabLayout += "Padding:0,25; Margin:0,0,0,100; TabWidth:420; TabHeight:71;"\n' + page % 100
    assert (layer / files.COMMON).read_text() == 'ScrollableSettingsPanel = "Flex:1; MaxHeight:800; Margin:0,20,20,120;"\n'
