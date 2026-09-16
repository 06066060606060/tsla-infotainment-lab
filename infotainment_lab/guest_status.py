"""Report only live state from the current virtual-hardware session."""
import json
from pathlib import Path
import platform
import subprocess
import time


def session_status(path, *, active, now, boot_time):
    result = {'phase': 'starting' if active else 'failed',
              'mode': 'virtual-hardware', 'kernel': platform.release(),
              'full_firmware_verified': False, 'service_active': active}
    path = Path(path)
    if not active:
        result['detail'] = 'The guest display service is not active.'
    elif path.exists():
        modified = path.stat().st_mtime
        if modified < boot_time or not 0 <= now - modified <= 10:
            result['detail'] = 'Waiting for a fresh session heartbeat.'
        else:
            try:
                saved = json.loads(path.read_text())
                if not isinstance(saved, dict):
                    raise ValueError('Invalid session status.')
                result = dict(saved, **{k: v for k, v in result.items() if k != 'phase'})
            except (ValueError, OSError):
                result['detail'] = 'The session status is unavailable.'
    return result


if __name__ == '__main__':
    now = time.time()
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    active = subprocess.run(['systemctl', 'is-active', '--quiet', 'lab-desktop'],
                            timeout=3).returncode == 0
    print(json.dumps(session_status('/home/lab/session/status.json',
                    active=active, now=now, boot_time=now - uptime)))
