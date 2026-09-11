"""Read-only inventory for native media prerequisites; does not establish playback."""
import argparse
import gzip
import json
from pathlib import Path


def inventory(firmware, proc=Path('/proc'), sysfs=Path('/sys')):
    files = (
        'etc/apparmor.compiled/usr.tesla.UI.bin.SpotifyServer',
        'etc/apparmor.compiled/usr.tesla.UI.bin.ChromiumAdapter',
        'etc/apparmor.compiled/usr.lib.tesla-chromium.tesla-chromium',
        'etc/apparmor.compiled/usr.bin.media-webapp-server',
        'etc/apparmor.compiled/usr.tesla.UI.bin.QtCar',
        'etc/chromium/policies/chromium-app/policy.json',
    )
    result = {'files': {}}
    for relative in files:
        try:
            result['files'][relative] = {'bytes': (firmware / relative).stat().st_size}
        except OSError as error:
            result['files'][relative] = {'error': type(error).__name__}
    try:
        result['apparmor_enabled'] = (sysfs / 'module/apparmor/parameters/enabled').read_text().strip()
    except OSError:
        result['apparmor_enabled'] = 'unavailable'
    try:
        result['active_lsm'] = (sysfs / 'kernel/security/lsm').read_text().strip().split(',')
    except OSError:
        result['active_lsm'] = None
    try:
        with gzip.open(proc / 'config.gz', 'rt') as source:
            result['kernel_config'] = [line.strip() for line in source if line.startswith((
                'CONFIG_SECURITY_APPARMOR=', 'CONFIG_DEFAULT_SECURITY_', 'CONFIG_LSM='))]
    except OSError:
        result['kernel_config'] = None
    result['playback_verified'] = False
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('firmware', type=Path, help='Mounted firmware directory')
    args = parser.parse_args()
    if not args.firmware.is_dir():
        parser.error('Firmware directory does not exist')
    print(json.dumps(inventory(args.firmware), indent=2))
