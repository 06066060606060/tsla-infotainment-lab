import os
from pathlib import Path

import pytest

from infotainment_lab.qemu_guest import kernel_pair
from infotainment_lab.qemu_virtual import controls, launch_arguments, regular_file, prepared_files


def test_virtual_launch_keeps_firmware_read_only_and_has_no_host_shares(tmp_path):
    files = {name: tmp_path / (name + ',example') for name in ('disk', 'kernel', 'initrd', 'firmware')}
    for path in files.values():
        path.write_bytes(b'hsqs' + bytes(256))
    args = launch_arguments(tmp_path, 'test-identity', **files, internet=False, display='sdl')
    drives = [args[i + 1] for i, value in enumerate(args) if value == '-drive']
    assert len(drives) == 2
    assert 'readonly=on' in drives[1] and 'firmware,,example' in drives[1]
    assert 'restrict=on' in args[args.index('-netdev') + 1]
    assert not {'-virtfs', '-fsdev', '-net', '-nic'} & set(args)
    assert args[args.index('-display') + 1] == 'sdl,gl=on'
    assert 'virtio-vga-gl,max_outputs=1,xres=720,yres=1152' in args


def test_scaled_launch_sizes_both_guest_outputs(tmp_path):
    files = {name: tmp_path / name for name in ('disk', 'kernel', 'initrd', 'firmware')}
    for path in files.values():
        path.write_bytes(b'hsqs' + bytes(256))
    args = launch_arguments(tmp_path, 'id', **files, display_scale=1.5)
    assert 'virtio-vga-gl,max_outputs=1,xres=1080,yres=1728' in args
    assert 'virtio-gpu-pci,id=cluster-gpu,addr=0x08,max_outputs=1,xres=1920,yres=720' in args
    with pytest.raises(ValueError):
        launch_arguments(tmp_path, 'id', **files, display_scale=0.5)


def test_guest_ssh_is_forwarded_on_loopback_only(tmp_path):
    files = {name: tmp_path / name for name in ('disk', 'kernel', 'initrd', 'firmware')}
    for path in files.values():
        path.write_bytes(b'hsqs' + bytes(256))
    netdev = launch_arguments(tmp_path, 'id', **files)[launch_arguments(tmp_path, 'id', **files).index('-netdev') + 1]
    assert 'hostfwd=tcp:127.0.0.1:2222-:22' in netdev


def test_status_does_not_reuse_a_previous_boot_or_dead_session(tmp_path):
    from infotainment_lab.guest_status import session_status
    path = tmp_path / 'status.json'
    path.write_text('{"phase":"running","components":{"center":"running"}}')
    os.utime(path, (100, 100))
    assert session_status(path, active=True, now=110, boot_time=105)['phase'] == 'starting'
    assert session_status(path, active=True, now=120, boot_time=50)['phase'] == 'starting'
    assert session_status(path, active=False, now=101, boot_time=50)['phase'] == 'failed'
    live = session_status(path, active=True, now=101, boot_time=50)
    assert live['phase'] == 'running' and live['full_firmware_verified'] is False


@pytest.mark.skipif(os.name == 'nt', reason='Linux device boundary')
def test_virtual_guest_rejects_host_device_paths():
    with pytest.raises(ValueError, match='regular file'):
        regular_file('/dev/null')


def test_virtual_guest_cannot_attach_firmware_as_the_writable_disk(tmp_path):
    image = tmp_path / 'firmware'
    image.write_bytes(b'hsqs' + bytes(256))
    with pytest.raises(ValueError, match='writable guest disk must be separate'):
        launch_arguments(tmp_path, 'id', disk=image, firmware=image, kernel=image, initrd=image)


def test_kernel_pair_refuses_missing_or_ambiguous_modules(tmp_path):
    (tmp_path / 'boot').mkdir()
    (tmp_path / 'boot/vmlinuz-test').write_bytes(b'kernel')
    with pytest.raises(ValueError, match='matching modules'):
        kernel_pair(tmp_path)
    (tmp_path / 'lib/modules/test').mkdir(parents=True)
    assert kernel_pair(tmp_path)[1] == 'test'
    (tmp_path / 'boot/vmlinuz-other').write_bytes(b'other')
    with pytest.raises(ValueError, match='Select one kernel'):
        kernel_pair(tmp_path)


def test_invalid_controls_are_rejected_before_guest_contact(tmp_path):
    with pytest.raises(ValueError, match='Unknown simulator field'):
        controls(tmp_path, {'external_vehicle_address': 'example'})


def test_prepared_guest_resolves_matching_boot_files_and_rejects_manifest_paths(tmp_path):
    import json
    for name in ('desktop.raw', 'vmlinuz-test', 'initrd.img-test'):
        (tmp_path / name).write_bytes(b'test')
    manifest = tmp_path / 'build.json'
    manifest.write_text(json.dumps({'kernel': 'test'}))
    assert prepared_files(tmp_path)['kernel'] == tmp_path / 'vmlinuz-test'
    manifest.write_text(json.dumps({'kernel': '../host-kernel'}))
    with pytest.raises(ValueError, match='invalid kernel'):
        prepared_files(tmp_path)


def test_media_share_is_read_only_and_cannot_expose_an_arbitrary_host_folder(tmp_path):
    files = {name: tmp_path / name for name in ('disk', 'kernel', 'initrd', 'firmware')}
    for path in files.values():
        path.write_bytes(b'hsqs' + bytes(256))
    share = tmp_path / 'inputs'
    share.mkdir()
    args = launch_arguments(tmp_path, 'id', **files, inputs=share)
    assert 'readonly=on' in args[args.index('-fsdev') + 1]
    with pytest.raises(ValueError, match='private input directory'):
        launch_arguments(tmp_path, 'id', **files, inputs=tmp_path)


def test_selected_media_is_a_separate_snapshot_and_reuses_unchanged_import(tmp_path):
    from infotainment_lab.virtual_inputs import import_media
    vm_dir = tmp_path / 'vm'
    vm_dir.mkdir()
    source = tmp_path / 'recording.mp4'
    source.write_bytes(b'example-clip')
    imported = import_media(vm_dir, str(source), 'video')
    copied = vm_dir / imported.lstrip('/')
    assert copied.read_bytes() == b'example-clip' and not copied.samefile(source)
    assert import_media(vm_dir, str(source), 'video') == imported
    source.write_bytes(b'changed-clip')
    assert copied.read_bytes() == b'example-clip'
    assert import_media(vm_dir, str(source), 'video') != imported
