"""Bounded vendor-kernel boot checks; this is not a full vehicle VM profile."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import struct
import subprocess

try:
    from .core import atomic_json
    from .qemu_storage import build_storage
    from .qemu_provision import provision
except ImportError:
    from core import atomic_json
    from qemu_storage import build_storage
    from qemu_provision import provision


def kernel_payload(container: bytes) -> bytes:
    """Locate a Linux x86 boot image and retain its declared setup/body only."""
    candidates = []
    start = 0
    while (marker := container.find(b'HdrS', start)) >= 0:
        start = marker + 4
        offset = marker - 0x202
        if offset < 0 or offset + 0x210 > len(container):
            continue
        if container[offset + 510:offset + 512] != b'\x55\xaa':
            continue
        protocol = struct.unpack_from('<H', container, offset + 0x206)[0]
        if not 0x200 <= protocol <= 0x20f:
            continue
        setup = (container[offset + 0x1f1] or 4) + 1
        body = struct.unpack_from('<I', container, offset + 0x1f4)[0] * 16
        length = setup * 512 + body
        if body and offset + length <= len(container):
            candidates.append(container[offset:offset + length])
    if len(candidates) != 1:
        raise ValueError('Expected one complete Linux x86 boot image in the vendor boot container.')
    return candidates[0]


def classify_boot(log: str, *, observing=False) -> dict:
    kernel = 'Linux version ' in log
    init = 'verity-init booting' in log or 'Run /init as init process' in log
    root = 'switching root and executing /sbin/init' in log
    if root and ('Volume group "ivg" not found' in log or 'Failed to find physical volume' in log):
        phase, detail = 'blocked', 'Vendor root booted; guest data-volume provisioning is incomplete.'
    elif 'one or more parent devices never appeared' in log:
        phase, detail = 'blocked', 'Vendor init cannot find its expected parent disk devices. A SquashFS root alone is insufficient.'
    elif 'Kernel panic' in log:
        phase, detail = 'blocked', 'The vendor kernel stopped with a panic; inspect the serial log.'
    elif observing:
        phase, detail = 'unverified', 'Observing the firmware VM; a complete firmware desktop has not been verified.'
    else:
        phase, detail = 'unverified', 'The bounded boot check ended without evidence of a complete firmware desktop.'
    return {'phase': phase, 'kernel_started': kernel, 'vendor_init_started': init,
            'vendor_root_entered': root,
            'desktop_verified': False, 'detail': detail}


def boot_check(image: Path, output: Path) -> dict:
    # Share the persistent manager's lock: a boot check must not replace a
    # kernel or provision a backing disk while a VM is using that directory.
    try:
        from .qemu_runtime import lifecycle_lock, ensure_idle
    except ImportError:
        from qemu_runtime import lifecycle_lock, ensure_idle
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with lifecycle_lock(output) as directory:
        ensure_idle(directory)
        return _boot_check(image, directory)


def _boot_check(image: Path, output: Path) -> dict:
    executable = shutil.which('qemu-system-x86_64')
    if not executable:
        raise RuntimeError('Install qemu-system-x86 in the selected Linux distribution to run the boot check.')
    if not os.access('/dev/kvm', os.R_OK | os.W_OK):
        raise RuntimeError('KVM is unavailable to this Linux user. This bounded check requires /dev/kvm access.')
    image = image.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    member = 'deploy/iasImage-bank_a'
    extracted = subprocess.run(['unsquashfs', '-cat', str(image), member],
                               capture_output=True, timeout=30)
    if extracted.returncode:
        raise ValueError('This image has no supported vendor boot container (deploy/iasImage-bank_a).')
    kernel = output / 'vendor-kernel'
    kernel.write_bytes(kernel_payload(extracted.stdout))
    def member_text(name):
        return subprocess.run(['unsquashfs', '-cat', str(image), name], capture_output=True,
                              text=True, timeout=30, check=True).stdout
    layout = member_text('sbin/mmcblk0.sfdisk')
    provisioning_script = member_text('sbin/check-lvm-parts')
    expansion = re.search(r'^rootfs_bank_exp_mbytes=(\d+)$', provisioning_script, re.MULTILINE)
    if not expansion:
        raise ValueError('The vendor root-bank expansion size could not be identified.')
    disk = output / 'guest-storage.raw'
    manifest = output / 'storage.json'
    if not disk.exists():
        storage = build_storage(image, disk, layout, expansion_bytes=int(expansion[1]) * 1024**2)
        atomic_json(manifest, storage)
    elif not manifest.is_file():
        raise ValueError('Guest disk has no storage manifest; it has been left unchanged.')
    else:
        import json
        storage = json.loads(manifest.read_text())
    if storage['image_bytes'] != image.stat().st_size or storage['disk_bytes'] != disk.stat().st_size:
        raise ValueError('Guest disk metadata does not match this firmware.')
    if not storage.get('volume_group_provisioned'):
        maintenance = output.parents[1] / 'qemu-tools/debian-kernel'
        if maintenance.is_dir():
            storage.update(provision(output, int(expansion[1]), maintenance))
    # No host folders, ports, vehicle interfaces or writable firmware are exposed.
    argv = [executable, '-machine', 'q35,accel=kvm', '-cpu', 'host', '-smp', '4',
            '-m', '2048', '-nodefaults', '-display', 'none', '-monitor', 'none',
            '-serial', 'stdio', '-no-reboot', '-nic', 'none', '-kernel', str(kernel),
            '-append', 'console=ttyS0,115200 earlyprintk=serial bootpart=kernel-a ro panic=0 security=apparmor apparmor=1',
            '-device', 'sdhci-pci',
            '-drive', 'if=none,id=sdcard,file=' + str(disk).replace(',', ',,') + ',format=raw,snapshot=on',
            '-device', 'sd-card,drive=sdcard']
    timed_out = False
    code = None
    log_path = output / 'serial.log'
    with log_path.open('w') as stream:
        try:
            code = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT, timeout=60).returncode
        except subprocess.TimeoutExpired:
            timed_out = True
    log = log_path.read_text(errors='replace')
    result = dict(classify_boot(log), accelerator='kvm', machine='q35',
                  timed_out=timed_out, exit_code=code, boot_container=member,
                  log_path=str(log_path), storage=storage, log_tail=log[-6000:])
    atomic_json(output / 'result.json', result)
    return result
