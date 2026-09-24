"""Windows display scale for WSLg windows.

WSLg's compositor scales X11 windows only by whole steps by default: at 150%
Windows scaling it applies 1x, so the lab panel and the firmware displays
appear at two thirds of their intended size. Turning on WSLg's fractional
scaling enlarges them by stretching bitmaps, which blurs text and the cursor.

Instead each window is drawn larger at the source. The panel uses
QT_SCALE_FACTOR. The firmware already draws the car's screen at a window
scale (`--window 0.6` gives the 720x1152 center), so the session raises that
scale and sizes its X screens (Xephyr or the QEMU guest outputs) to match.
Absolute pointer input stays aligned because each screen and the firmware
agree on the larger size.

INFOTAINMENT_LAB_SCALE overrides the factor, for example 1.25, or 1 to
leave everything unscaled.
"""
import argparse
import os
from pathlib import Path
import platform
import re
import subprocess

OVERRIDE = 'INFOTAINMENT_LAB_SCALE'
REGISTRY = (('HKCU\\Control Panel\\Desktop\\WindowMetrics', 'AppliedDPI'),
            ('HKCU\\Control Panel\\Desktop', 'LogPixels'))
REG_EXE = ('reg.exe', '/mnt/c/Windows/System32/reg.exe')
SECTION = '[system-distro-env]'
FRACTIONAL = 'WESTON_RDP_FRACTIONAL_HI_DPI_SCALING'


def is_wsl(env=None):
    env = os.environ if env is None else env
    return bool(env.get('WSL_DISTRO_NAME')) or 'microsoft' in platform.release().lower()


def normalize(value, low=1.0):
    """Clamp to low-4 and round to the 25% steps Windows offers."""
    value = float(value)
    if value != value:
        raise ValueError('The display scale must be a number.')
    return min(4.0, max(low, round(value * 4) / 4))


def windows_scale(run=subprocess.run):
    """The signed-in Windows scale (1.0 = 96 DPI), or None when unknown."""
    for executable in REG_EXE:
        if '/' in executable and not Path(executable).exists():
            continue
        for key, value in REGISTRY:
            try:
                result = run([executable, 'query', key, '/v', value], capture_output=True, text=True,
                             encoding='utf-8', errors='replace', timeout=5)
            except (OSError, subprocess.SubprocessError):
                break
            found = re.search(r'\b' + value + r'\s+REG_DWORD\s+0x([0-9a-fA-F]+)', result.stdout or '')
            if not result.returncode and found and int(found.group(1), 16) > 0:
                return normalize(int(found.group(1), 16) / 96)
    return None


def wslg_config_path(run=subprocess.run):
    """Path of the Windows user's .wslgconfig as seen from WSL, or None."""
    try:
        cwd = '/mnt/c' if Path('/mnt/c').is_dir() else None
        profile = run(['cmd.exe', '/d', '/c', 'echo %USERPROFILE%'], capture_output=True, text=True,
                      encoding='utf-8', errors='replace', timeout=5, cwd=cwd).stdout.strip()
        if not re.fullmatch(r'[A-Za-z]:\\[^%\r\n]*', profile):
            return None
        path = run(['wslpath', '-u', profile], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(path) / '.wslgconfig' if path.startswith('/') else None


def wslg_settings(text):
    """KEY=value pairs from the [system-distro-env] section of .wslgconfig."""
    settings, section = {}, ''
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('['):
            section = line.lower()
        elif section == SECTION and '=' in line and not line.startswith(('#', ';')):
            key, _, value = line.partition('=')
            settings[key.strip()] = value.strip()
    return settings


def compositor_scale(windows, settings):
    """The factor WSLg's compositor applies, following weston-mirror's RDP backend."""
    def flag(name, default):
        return {'true': True, '1': True, 'false': False, '0': False}.get(settings.get(name, ''), default)
    if not flag('WESTON_RDP_HI_DPI_SCALING', True):
        return 1.0
    debug = settings.get('WESTON_RDP_DEBUG_DESKTOP_SCALING_FACTOR', '')
    if debug.isdigit() and 100 <= int(debug) <= 500:
        return int(debug) / 100
    if flag(FRACTIONAL, False):
        return windows
    if flag(FRACTIONAL + '_ROUNDUP', False):
        return float(int(windows + .5))
    return float(max(1, int(windows)))


def scale_factor(env=None, *, run=subprocess.run):
    """Qt factor that makes the panel match the Windows scale on top of WSLg's own."""
    env = os.environ if env is None else env
    requested = env.get(OVERRIDE, '').strip()
    if requested:
        try:
            return normalize(requested, .5)
        except ValueError:
            pass
    if not is_wsl(env):
        return 1.0
    windows = windows_scale(run)
    if not windows:
        return 1.0
    path = wslg_config_path(run)
    try:
        text = path.read_text(encoding='utf-8', errors='replace') if path else ''
    except OSError:
        text = ''
    return normalize(windows / compositor_scale(windows, wslg_settings(text)), .5)


def qt_environment(env=None, *, run=subprocess.run):
    """Qt variables for this scale; an explicit QT_SCALE_FACTOR is left alone."""
    env = os.environ if env is None else env
    if env.get('QT_SCALE_FACTOR') or env.get('QT_ENABLE_HIGHDPI_SCALING') == '0':
        return {}
    scale = scale_factor(env, run=run)
    return {'QT_SCALE_FACTOR': f'{scale:g}'} if scale != 1 else {}


STEP = 16  # 720, 1152, 1280, 480, 1920 and 1200 are all multiples of 16.


def fit_scale(scale, screen, sizes):
    """Largest scale up to `scale`, in 1/16 steps, at which every size fits the screen."""
    if screen:
        for width, height in sizes:
            # Leave room for the Windows taskbar and a title bar.
            scale = min(scale, (screen[0] - 16) / width, (screen[1] - 96) / height)
    return max(1.0, int(scale * STEP + 1e-9) / STEP)


def scaled(size, scale):
    """A WxH size at this scale, as integers."""
    return round(size[0] * scale), round(size[1] * scale)


def screen_size(env=None, *, run=subprocess.run):
    """This X desktop's size in pixels, or None."""
    try:
        result = run(['xdotool', 'getdisplaygeometry'], capture_output=True, text=True, timeout=3,
                     env=dict(os.environ if env is None else env))
        width, height = (int(n) for n in result.stdout.split()[:2])
        return (width, height) if width > 0 and height > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def firmware_scale(single_display, env=None, *, run=subprocess.run):
    """Scale for the firmware displays of a session starting on this desktop."""
    scale = scale_factor(env, run=run)
    if scale <= 1:
        return 1.0
    sizes = [(1920, 1200)] if single_display else [(720, 1152), (1280, 480)]
    return fit_scale(scale, screen_size(env, run=run), sizes)


def disable_fractional(text):
    """.wslgconfig text without the fractional scaling line an earlier lab version added."""
    lines = [line for line in text.splitlines() if line.strip().partition('=')[0].strip() != FRACTIONAL]
    return '\n'.join(lines) + '\n' if lines else ''


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--disable-wslg-scaling', action='store_true',
                        help=f"Remove {FRACTIONAL} from the Windows user's .wslgconfig.")
    args = parser.parse_args()
    windows = windows_scale()
    path = wslg_config_path()
    if args.disable_wslg_scaling:
        if not path:
            raise SystemExit('The Windows user profile could not be found from this WSL distribution.')
        text = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
        updated = disable_fractional(text)
        if updated != text:
            path.write_text(updated, encoding='utf-8')
        print(f'{path}: {FRACTIONAL} removed. Run "wsl --shutdown" from Windows, then start the lab again.')
        return
    text = path.read_text(encoding='utf-8', errors='replace') if path and path.exists() else ''
    print(f'Windows scale: {windows or "unknown"}')
    print(f'WSLg window scale: {compositor_scale(windows or 1.0, wslg_settings(text)):g}')
    print(f'Panel QT_SCALE_FACTOR: {scale_factor():g}')
    print(f'Firmware display scale: {firmware_scale(False):g}')


if __name__ == '__main__':
    main()
