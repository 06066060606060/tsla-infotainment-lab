"""Build an experimental VM disk; no firmware is copied or distributed.

Run as root in Debian/WSL: --directory must be new, --owner is a normal user.
All mounts happen in a private mount namespace and are removed before packing.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

REPO = Path(__file__).resolve().parents[1]
PACKAGES = ('systemd-sysv systemd-resolved dracut udev dbus dbus-x11 xserver-xorg-core xserver-xorg-input-libinput '
            'xinit xauth mesa-utils libgl1-mesa-dri libegl1 libglx-mesa0 libopengl0 '
            'pulseaudio pulseaudio-utils alsa-utils libasound2-plugins '
            'iproute2 iputils-ping curl ca-certificates python3 python3-dbus python3-gi python3-pil '
            'qemu-guest-agent procps x11-xserver-utils x11-utils fonts-noto-cjk '
            'gcc libc6-dev binutils libx11-dev xserver-xephyr xdotool libnss3 libgbm1 libatk-bridge2.0-0t64 '
            'libxkbcommon-x11-0 libxcb-cursor0 ffmpeg apparmor apparmor-utils '
            'gstreamer1.0-tools gstreamer1.0-alsa gstreamer1.0-plugins-base gstreamer1.0-plugins-good '
            'squashfs-tools squashfuse fuse3 libxtst6 libxv1 libglu1-mesa').split()

VGL_VERSION = '3.1.5'
VGL_SHA256 = 'df3f7788ce41b182a47c0d298e5cd6d2d63579522cb41825970b7726e825485e'


def install_virtualgl(root):
    """Install the pinned upstream package only inside the new guest image."""
    name = f'virtualgl_{VGL_VERSION}_amd64.deb'
    url = f'https://github.com/VirtualGL/virtualgl/releases/download/{VGL_VERSION}/{name}'
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(32 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != VGL_SHA256:
        raise ValueError('VirtualGL package checksum did not match the pinned release.')
    package = root / 'tmp' / name
    package.write_bytes(data)
    try:
        run('chroot', root, 'apt-get', 'install', '-y', '--no-install-recommends', '/tmp/' + name)
    finally:
        package.unlink(missing_ok=True)


def run(*args):
    subprocess.run([str(v) for v in args], check=True,
                   env=dict(os.environ, DEBIAN_FRONTEND='noninteractive', LC_ALL='C'))


def configure_displays(root):
    """Private VM screens stay awake while inputs arrive outside X11.

    Driving controls and replay use local IPC, so they do not reset Xorg's
    keyboard/mouse idle timer. DPMS on these virtual outputs can stall the
    center's EGL buffer queue. Host desktop power settings remain independent.
    """
    def write(name, content, mode=0o644):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        p.chmod(mode)

    for name, bus in (('center', 'PCI:0:1:0'), ('cluster', 'PCI:0:8:0')):
        write('etc/X11/lab-' + name + '.conf', f'''Section "ServerFlags"
 Option "AutoAddGPU" "false"
 Option "AutoBindGPU" "false"
EndSection
Section "Device"
 Identifier "LabGPU"
 Driver "modesetting"
 BusID "{bus}"
EndSection
Section "Screen"
 Identifier "LabScreen"
 Device "LabGPU"
 DefaultDepth 24
EndSection
''')
    write('usr/local/bin/lab-xclient', '''#!/bin/sh
set -eu
Xorg :1 -config /etc/X11/lab-cluster.conf -isolateDevice PCI:0:8:0 vt1 -sharevts -novtswitch -noreset -s 0 -dpms -nolisten tcp -auth "$XAUTHORITY" >/var/log/lab-cluster-xorg.log 2>&1 &
cluster_pid=$!
trap 'kill "$cluster_pid" 2>/dev/null || true' EXIT
ready=false
for n in $(seq 1 40); do
 if DISPLAY=:1 xdpyinfo >/dev/null 2>&1; then ready=true; break; fi
 kill -0 "$cluster_pid" 2>/dev/null || break
 sleep .25
done
if [ "$ready" != true ]; then echo "Instrument display did not start" >&2; exit 1; fi
runuser -u lab -- dbus-run-session -- python3 /opt/infotainment-lab/guest_session.py
''', 0o755)
    write('usr/local/bin/lab-xorg', '''#!/bin/sh
set -eu
install -d -m 0700 -o lab -g lab /run/user/1000
export XDG_RUNTIME_DIR=/run/user/1000
export XAUTHORITY=/run/user/1000/lab.xauth
modprobe qemu_fw_cfg
modprobe 9pnet_virtio
for tag in /sys/bus/virtio/drivers/9pnet_virtio/virtio*/mount_tag; do
 if [ -f "$tag" ] && [ "$(cat "$tag")" = lab-inputs ]; then
  mkdir -p /inputs
  mountpoint -q /inputs || mount -t 9p -o trans=virtio,version=9p2000.L,ro,cache=none,msize=1048576 lab-inputs /inputs
 fi
done
if [ -f /sys/firmware/qemu_fw_cfg/by_name/opt/tsla-lab/config/raw ]; then
 install -m 0600 -o lab -g lab /sys/firmware/qemu_fw_cfg/by_name/opt/tsla-lab/config/raw /run/user/1000/lab-launch.json
fi
if [ -b /dev/disk/by-id/virtio-lab-maps ]; then
 mkdir -p /maps
 mountpoint -q /maps || mount -t squashfs -o ro /dev/disk/by-id/virtio-lab-maps /maps
fi
cookie=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \\n')
xauth -f "$XAUTHORITY" add :0 . "$cookie"
xauth -f "$XAUTHORITY" add :1 . "$cookie"
chown lab:lab "$XAUTHORITY"
exec xinit /usr/local/bin/lab-xclient -- /usr/bin/Xorg :0 -config /etc/X11/lab-center.conf -isolateDevice PCI:0:1:0 vt1 -s 0 -dpms -nolisten tcp -keeptty -auth "$XAUTHORITY"
''', 0o755)


def build(directory, owner):
    directory = directory.resolve()
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    root = directory / 'guest-root'
    run('debootstrap', '--variant=minbase', '--include=' + ','.join(PACKAGES),
        'trixie', root, 'https://deb.debian.org/debian')
    finish_image(directory, owner)


def finish_image(directory, owner):
    root = directory / 'guest-root'
    def write(name, content, mode=0o644):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        p.chmod(mode)

    write('usr/sbin/policy-rc.d', '#!/bin/sh\nexit 101\n', 0o755)
    # A newly installed resolved package may leave an absolute guest symlink.
    # Replace it before chroot package operations; do not follow it on the host.
    resolver = root / 'etc/resolv.conf'
    resolver.unlink(missing_ok=True)
    resolver.write_text(Path('/etc/resolv.conf').read_text())
    write('etc/apt/sources.list.d/backports.list',
          'deb https://deb.debian.org/debian trixie-backports main\n')
    mounted = []
    try:
        for kind in ('proc', 'sysfs'):
            target = root / ('proc' if kind == 'proc' else 'sys')
            run('mount', '-t', kind, '-o', 'ro,nosuid,nodev,noexec', kind, target)
            mounted.append(target)
        run('chroot', root, 'apt-get', 'update')
        run('chroot', root, 'apt-get', 'install', '-y', '--no-install-recommends',
            '-t', 'trixie-backports', 'linux-image-amd64')
        install_virtualgl(root)
        kernels = list((root / 'boot').glob('vmlinuz-*'))
        if len(kernels) != 1:
            raise ValueError('Expected exactly one installed guest kernel.')
        version = kernels[0].name.removeprefix('vmlinuz-')
        run('chroot', root, 'dracut', '--force', '--no-hostonly',
            '/boot/initrd.img-' + version, version)
        run('chroot', root, 'apt-get', 'clean')
    finally:
        for mount in reversed(mounted):
            run('umount', mount)

    run('chroot', root, 'groupadd', '--system', 'dvaccess')
    run('chroot', root, 'groupadd', '--system', 'dvshm')
    run('chroot', root, 'useradd', '-m', '-u', '1000', '-s', '/bin/bash',
        '-G', 'audio,video,render,input,dvaccess,dvshm', 'lab')
    shutil.copytree(REPO / 'infotainment_lab', root / 'opt/infotainment-lab',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.so'))
    shutil.copyfile(REPO / 'infotainment_lab/runtime/media-apparmor.profile',
                    root / 'etc/apparmor.d/tsla-infotainment-lab-media')
    write('etc/hostname', 'infotainment-vm\n')
    write('etc/pulse/daemon.conf.d/10-infotainment-vm.conf',
          'default-sample-rate = 48000\nalternate-sample-rate = 48000\n'
          'default-fragments = 4\ndefault-fragment-size-msec = 20\n')
    write('etc/hosts', '127.0.0.1 localhost\n127.0.1.1 infotainment-vm\n')
    write('etc/fstab', '/dev/vda / ext4 defaults 0 1\n/dev/vdb /firmware squashfs ro 0 0\n')
    (root / 'firmware').mkdir()
    write('etc/systemd/network/20-wired.network', '[Match]\nName=en* eth*\n[Network]\nDHCP=yes\n')
    (root / 'etc/resolv.conf').unlink(missing_ok=True)
    (root / 'etc/resolv.conf').symlink_to('/run/systemd/resolve/stub-resolv.conf')
    write('etc/tmpfiles.d/lab.conf', ''.join(f'd {p} 0755 lab lab -\n' for p in (
        '/run/chromium', '/run/chromium/policies', '/run/chromium/policies/chromium',
        '/run/chromium/policies/chromium-card', '/run/chromium/policies/chromium-fullscreen',
        '/opt/games/run', '/opt/games/run/chromium-cache-files', '/opt/games/run/i2v')))
    configure_displays(root)
    write('etc/systemd/system/lab-desktop.service', '''[Unit]
Description=Infotainment Lab virtual-hardware session
After=systemd-user-sessions.service apparmor.service network-online.target
Wants=network-online.target
RequiresMountsFor=/firmware
Conflicts=getty@tty1.service
[Service]
ExecStart=/usr/local/bin/lab-xorg
StandardOutput=journal+console
StandardError=journal+console
TTYPath=/dev/tty1
StandardInput=tty
[Install]
WantedBy=multi-user.target
''')
    run('chroot', root, 'systemctl', 'enable', 'lab-desktop', 'qemu-guest-agent', 'systemd-networkd', 'systemd-resolved')
    disk = directory / 'desktop.raw'
    with disk.open('xb') as stream:
        stream.truncate(16 * 1024**3)
    run('mkfs.ext4', '-q', '-F', '-L', 'lab-root', '-d', root, disk)
    for name in ('vmlinuz-' + version, 'initrd.img-' + version):
        shutil.copyfile(root / 'boot' / name, directory / name)
        os.chown(directory / name, owner.pw_uid, owner.pw_gid)
    (directory / 'build.json').write_text(json.dumps({'kernel': version, 'mode': 'virtual-hardware',
        'firmware_included': False, 'packages': PACKAGES, 'virtualgl': VGL_VERSION,
        'full_firmware_verified': False}, indent=2))
    for p in (directory, disk, directory / 'build.json'):
        os.chown(p, owner.pw_uid, owner.pw_gid)
    print('Guest files prepared in', directory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--private-namespace', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('Run this image builder inside Debian or another Linux guest environment.')
    import pwd
    if os.geteuid() != 0:
        parser.error('Run this image builder as root inside Debian; start QEMU as the normal user.')
    owner = pwd.getpwnam(args.owner)
    if owner.pw_uid < 1000:
        parser.error('Choose a normal desktop user as --owner.')
    if not args.private_namespace:
        run('unshare', '--mount', '--propagation', 'private', sys.executable, __file__,
            *sys.argv[1:], '--private-namespace')
    else:
        build(args.directory, owner)
