"""Boot support for the user-authorized virtual-hardware kernel route.

This is separate from the original-kernel diagnostic mode. The chosen Linux
kernel and its matching modules supply virtual devices used by QEMU.
"""
from pathlib import Path
import lzma
import subprocess

from .qemu_provision import newc


def kernel_pair(kernel_root):
    kernel_root = Path(kernel_root).resolve(strict=True)
    kernels = list((kernel_root / 'boot').glob('vmlinuz-*'))
    if len(kernels) != 1:
        raise ValueError('Select one kernel and its matching module directory.')
    kernel = kernels[0]
    version = kernel.name.removeprefix('vmlinuz-')
    if not (kernel_root / 'lib/modules' / version).is_dir():
        raise ValueError('The selected kernel has no matching modules.')
    return kernel, version


def boot_archive(kernel_root):
    """Create a small initramfs that mounts a virtual ext4 root disk."""
    kernel_root = Path(kernel_root).resolve(strict=True)
    _, version = kernel_pair(kernel_root)
    files = {'usr/bin/busybox': Path('/usr/bin/busybox').read_bytes()}
    dependencies = subprocess.run(['ldd', '/usr/bin/busybox'], capture_output=True, text=True, timeout=10)
    if 'not a dynamic executable' not in dependencies.stdout + dependencies.stderr:
        raise ValueError('The virtual-hardware initramfs requires busybox-static.')
    commands = []
    for module in ('virtio_pci', 'virtio_blk', 'ext4'):
        result = subprocess.run(['modprobe', '-d', str(kernel_root), '-S', version,
                                 '--show-depends', module], capture_output=True,
                                text=True, check=True, timeout=10)
        for line in result.stdout.splitlines():
            if not line.startswith('insmod '):
                continue
            source = Path(line.split()[1])
            data, name = source.read_bytes(), source.name
            if source.suffix == '.xz':
                data, name = lzma.decompress(data), source.stem
            target = 'lab-modules/' + name
            if target not in files:
                files[target] = data
                commands.append('busybox insmod /' + target)
    files['init'] = ('''#!/usr/bin/busybox sh
set -eu
export PATH=/usr/bin
busybox mkdir -p /dev /proc /sys /newroot
busybox mount -t devtmpfs devtmpfs /dev
busybox mount -t proc proc /proc
busybox mount -t sysfs sysfs /sys
LOAD_MODULES
count=0
while [ ! -b /dev/vda ]; do
 count=$((count+1)); [ "$count" -lt 30 ] || exit 1
 busybox sleep 1
done
busybox mount -t ext4 -o rw /dev/vda /newroot
busybox mount --move /dev /newroot/dev
busybox mount --move /proc /newroot/proc
busybox mount --move /sys /newroot/sys
echo LAB_VIRTUAL_HARDWARE_ROOT_READY
exec busybox switch_root /newroot /sbin/init
'''.replace('LOAD_MODULES', '\n'.join(commands))).encode()
    return newc(files)
