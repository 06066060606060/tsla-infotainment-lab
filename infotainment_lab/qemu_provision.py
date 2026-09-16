"""Prepare filesystem metadata inside a separate, networkless maintenance VM.

This initramfs is only for disk preparation. Vendor boot subsequently uses the
original embedded init; maintenance boot is never counted as firmware startup.
"""
from pathlib import Path, PurePosixPath
import re
import lzma
import stat
import subprocess
import json

try:
    from .core import atomic_json
except ImportError:
    from core import atomic_json


def newc(files: dict[str, bytes]) -> bytes:
    entries = {}
    for name, data in files.items():
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Archive paths must remain relative.')
        for parent in path.parents:
            if str(parent) != '.':
                entries.setdefault(str(parent), (stat.S_IFDIR | 0o755, b''))
        entries[name] = (stat.S_IFREG | 0o755, data)
    archive = bytearray()
    def append(name, mode, data, ino):
        name = name.encode() + b'\0'
        fields = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name), 0]
        archive.extend(b'070701' + b''.join(f'{v:08x}'.encode() for v in fields) + name)
        archive.extend(b'\0' * (-len(archive) % 4))
        archive.extend(data)
        archive.extend(b'\0' * (-len(archive) % 4))
    for ino, (name, (mode, data)) in enumerate(sorted(entries.items(), key=lambda pair: (pair[0].count('/'), pair[0])), 1):
        append(name, mode, data, ino)
    append('TRAILER!!!', 0, b'', len(entries) + 1)
    return bytes(archive)


def preparation_archive(expansion_mib: int, kernel_root: Path, version: str) -> bytes:
    if not 1 <= expansion_mib <= 4096:
        raise ValueError('Invalid root-bank reservation.')
    files = {}
    module_commands = []
    for module in ('sdhci-pci', 'mmc_block', 'dm_mod'):
        dependencies = subprocess.run(['modprobe', '-d', str(kernel_root), '-S', version,
                                       '--show-depends', module], capture_output=True, text=True,
                                      timeout=10, check=True).stdout
        for line in dependencies.splitlines():
            if not line.startswith('insmod '):
                continue
            path = Path(line.split()[1])
            data = path.read_bytes()
            name = path.name
            if path.suffix == '.xz':
                data, name = lzma.decompress(data), path.stem
            target = 'lab-modules/' + name
            if target not in files:
                files[target] = data
                module_commands.append('busybox insmod /' + target)
    for command in ['/usr/bin/busybox', '/usr/sbin/lvm', '/usr/sbin/mkfs.ext2']:
        files[command.lstrip('/')] = Path(command).read_bytes()
        deps = subprocess.run(['ldd', command], capture_output=True, text=True, timeout=10)
        if deps.returncode and 'not a dynamic executable' not in deps.stdout + deps.stderr:
            raise ValueError(f'Cannot identify runtime dependencies for {command}.')
        for dep in re.findall(r'(/[\w/+.\-]+)', deps.stdout):
            path = Path(dep)
            if path.is_file():
                files[dep.lstrip('/')] = path.read_bytes()
    # The embedded vendor initramfs defines lib64 as a symlink to lib.
    files['lib/ld-linux-x86-64.so.2'] = Path('/lib64/ld-linux-x86-64.so.2').read_bytes()
    files['init'] = ('''#!/usr/bin/busybox sh
set -eu
export PATH=/usr/bin:/usr/sbin
busybox mkdir -p /dev /proc /sys
busybox mount -t devtmpfs devtmpfs /dev
busybox mount -t proc proc /proc
busybox mount -t sysfs sysfs /sys
busybox mkdir -p /run/lvm /run/lock/lvm /etc/lvm /dev/mapper
LOAD_MODULES
n=0
while [ ! -b /dev/mmcblk0p4 ]; do
 n=$((n+1)); [ "$n" -lt 20 ] || exit 1; busybox sleep 1
done
printf 'devices { use_devicesfile=0 }\nactivation { udev_sync=0 udev_rules=0 }\nbackup { backup=0 archive=0 }\n' > /etc/lvm/lvm.conf
sectors=$(busybox cat /sys/block/mmcblk0/mmcblk0p4/size)
pv_sectors=$(( (sectors / 8 * 8 - EXPANSION_MIB * 2 * 2048) / 8192 * 8192 ))
[ "$pv_sectors" -gt 0 ]
echo LAB_PROVISION_BEGIN
if ! busybox blkid /dev/mmcblk0p1 | busybox grep -q 'TYPE="ext2"'; then
 mkfs.ext2 -F -L boot /dev/mmcblk0p1
fi
if ! lvm pvs /dev/mmcblk0p4; then
 lvm pvcreate --setphysicalvolumesize "${pv_sectors}s" --zero y --yes /dev/mmcblk0p4
fi
if ! lvm vgs ivg; then
 lvm vgcreate ivg /dev/mmcblk0p4
fi
lvm vgchange -an ivg
busybox sync
echo LAB_PROVISION_COMPLETE
busybox poweroff -f
'''.replace('EXPANSION_MIB', str(expansion_mib)).replace('LOAD_MODULES', '\n'.join(module_commands))).encode()
    return newc(files)


def provision(output: Path, expansion_mib: int, kernel_root: Path) -> dict:
    output = output.resolve(strict=True)
    disk = output / 'guest-storage.raw'
    if disk.is_symlink() or not disk.is_file() or not (output / 'storage.json').is_file():
        raise ValueError('Provisioning requires an application-created regular guest disk and manifest.')
    initrd = output / 'provision.cpio'
    kernels = list((kernel_root / 'boot').glob('vmlinuz-*'))
    if len(kernels) != 1:
        raise ValueError('Select a prepared maintenance kernel directory containing one vmlinuz image.')
    version = kernels[0].name.removeprefix('vmlinuz-')
    initrd.write_bytes(preparation_archive(expansion_mib, kernel_root, version))
    argv = ['qemu-system-x86_64', '-machine', 'q35,accel=kvm', '-cpu', 'host', '-smp', '2',
            '-m', '2048', '-nodefaults', '-display', 'none', '-monitor', 'none', '-serial', 'stdio',
            '-no-reboot', '-nic', 'none', '-kernel', str(kernels[0]),
            '-initrd', str(initrd), '-append', 'console=ttyS0,115200 panic=0',
            '-device', 'sdhci-pci', '-drive', 'if=none,id=sdcard,file=' + str(disk).replace(',', ',,') + ',format=raw',
            '-device', 'sd-card,drive=sdcard']
    log_path = output / 'provision.log'
    with log_path.open('w') as stream:
        try:
            result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT, timeout=40)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f'Guest disk preparation timed out; inspect {log_path}.') from exc
    log = log_path.read_text(errors='replace')
    if result.returncode != 0 or 'LAB_PROVISION_COMPLETE' not in log:
        raise RuntimeError(f'Guest disk preparation did not complete; inspect {log_path}.')
    completed = {'boot_filesystem_provisioned': True, 'volume_group_provisioned': True,
                 'data_volumes_provisioned': False, 'provision_log': str(log_path),
                 'maintenance_kernel_version': version}
    metadata = json.loads((output / 'storage.json').read_text())
    metadata.update(completed)
    atomic_json(output / 'storage.json', metadata)
    return completed
