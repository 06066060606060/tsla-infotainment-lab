"""Expose the guest firmware with optional private read-only file replacements."""
import json
import re
from pathlib import Path
import subprocess

from firmware_files import entries, member_path


def mount_firmware(options, run=subprocess.run):
    lower, view = Path('/firmware-base'), Path('/firmware')
    relative = options.get('replacements')
    if relative:
        member = member_path(relative)
        if len(member.parts) != 1 or not re.fullmatch(r'firmware-replacements-[a-f0-9]{32}', str(member)):
            raise ValueError('Unknown firmware replacement share.')
        upper = Path('/inputs') / str(member)
        if upper.is_symlink() or not upper.is_dir():
            raise ValueError('The firmware replacement share is unavailable.')
        entries(upper)
        argv = ['fuse-overlayfs', '-o', f'ro,nosuid,nodev,allow_other,lowerdir={upper}:{lower}', str(view)]
    else:
        argv = ['mount', '-o', 'bind,ro', str(lower), str(view)]
    run(argv, check=True, capture_output=True, timeout=30)


if __name__ == '__main__':
    path = Path('/run/user/1000/lab-launch.json')
    mount_firmware(json.loads(path.read_text()) if path.exists() else {})
