"""Profiles for the firmware's ordinary desktop Chromium instances."""
from pathlib import Path
from urllib.parse import urlsplit

MODES = {
    'browser': ('Chromium', 'Chromium', 'chromium'),
    'card': ('ChromiumCard', 'ChromiumCard', 'chromium-card'),
    'theater': ('ChromiumFullscreen', 'Theater', 'chromium-fullscreen'),
}


def media_health(components, center_log):
    required = ('spotify', 'media-adapter', 'media-webapp', 'chromium-media')
    if not any(name in components for name in required):
        return {'state': 'disabled'}
    missing = [name for name in required if components.get(name) != 'running']
    if missing:
        return {'state': 'waiting-services', 'services': missing}
    peers = ('SpotifyServerDataListener', 'ChromiumAdapterServiceDataListener')
    rejected = sorted({peer for line in center_log.splitlines()
                       if '[PEERSEC] Incorrect security profile' in line
                       for peer in peers if '[' + peer + ']' in line})
    if rejected:
        return {'state': 'peer-profile-rejected', 'services': rejected}
    # Running processes alone do not establish native readiness or playback.
    return {'state': 'services-running'}


def browser_url(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 8192 or any(ord(c) < 32 for c in value):
        raise ValueError('Enter a website URL.')
    parsed = urlsplit(value)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname:
        raise ValueError('Use an http:// or https:// website address.')
    if parsed.username or parsed.password:
        raise ValueError('Use the website sign-in page instead of credentials in its URL.')
    return value


def browser_arguments(firmware: Path, state: Path, runtime: Path, mode: str) -> list[str]:
    service, title, instance = ('ChromiumApp', 'ChromiumApp', 'ChromiumApp') if mode == 'media' else MODES[mode]
    profile = state / ('chromium-profile' if mode == 'browser' else 'chromium-' + mode + '-profile')
    return [str(firmware / 'usr/lib/tesla-chromium/tesla-chromium-main'),
            '--ozone-platform=x11', '--force-device-scale-factor=1', '--disable-setuid-sandbox',
            '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-notifications',
            '--disable-crashpad-for-testing', '--disable-breakpad', '--disable-crash-reporter',
            '--enable-features=NetworkServiceInProcess2', '--disable-features=AudioServiceOutOfProcess',
            '--in-process-gpu', '--use-angle=gl', '--ignore-gpu-blocklist', '--alsa-output-device=browser',
            f'--user-data-dir={profile}', '--window-size=1200,1920', '--window-position=10000,0',
            f'--window-title={title}', f'--app-window-name={instance}', f'--keyboard-app-name={instance}',
            '--supports-active-window', f'--tesla-dbus-service-name=com.tesla.{service}',
            f'--tesla-dbus-interface-name=com.tesla.{service}', f'--tesla-dbus-object-path=/{service}',
            '--tesla-dbus-observe-loading', f'--class=TeslaMCU2-{mode}', '--enable-logging=stderr',
            (runtime / 'welcome.html').as_uri()]


def media_browser_arguments(firmware: Path, state: Path, runtime: Path) -> list[str]:
    argv = browser_arguments(firmware, state, runtime, 'media')
    # The firmware media app is served by our loopback-only local process.
    # Scope name resolution to this browser; do not change host DNS or hosts.
    argv[-1:] = ['--host-resolver-rules=MAP firmware-media.vn.teslamotors.com 127.0.0.1, MAP firmware-media-adapter.vn.teslamotors.com 127.0.0.1',
                 # Match the vendor's secure-context declaration for this one
                 # loopback media origin. EME needs a secure context even though
                 # the HTTP server itself is only listening on localhost.
                 '--unsafely-treat-insecure-origin-as-secure=http://firmware-media.vn.teslamotors.com:9000',
                 f'--policy-config-dir={firmware / "etc/chromium/policies/chromium-app"}',
                 '--tesla-dbus-observe-navigation', '--user-agent-suffix= TeslaMusic/2026.26.6.1',
                 'http://firmware-media.vn.teslamotors.com:9000']
    return argv
