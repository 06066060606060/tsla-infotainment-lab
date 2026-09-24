"""Profiles for the firmware's ordinary desktop Chromium instances."""
from pathlib import Path
import re
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


# Tesla's own domains never resolve in the lab's browsers. Chromium uses its own
# resolver, so this is separate from native-netguard. The first matching rule wins.
TESLA_DOMAINS = ('tesla.com', 'teslamotors.com', 'tesla.services', 'tesla.cn')


def resolver_rules(*loopback: str) -> str:
    rules = [f'MAP {host} 127.0.0.1' for host in loopback]
    rules += [f'MAP {pattern}{domain} ~NOTFOUND' for domain in TESLA_DOMAINS for pattern in ('', '*.')]
    return '--host-resolver-rules=' + ', '.join(rules)


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
            '--tesla-dbus-observe-loading', f'--class=TeslaMCU2-{mode}', '--enable-logging=stderr', resolver_rules(),
            (runtime / 'welcome.html').as_uri()]


def media_browser_arguments(firmware: Path, state: Path, runtime: Path) -> list[str]:
    argv = browser_arguments(firmware, state, runtime, 'media')
    # The firmware media app is served by our loopback-only local process.
    # Scope name resolution to this browser; do not change host DNS or hosts.
    argv[argv.index(resolver_rules())] = resolver_rules('firmware-media.vn.teslamotors.com', 'firmware-media-adapter.vn.teslamotors.com')
    argv[-1:] = [
                 # Match the vendor's secure-context declaration for this one
                 # loopback media origin. EME needs a secure context even though
                 # the HTTP server itself is only listening on localhost.
                 '--unsafely-treat-insecure-origin-as-secure=http://firmware-media.vn.teslamotors.com:9000',
                 f'--policy-config-dir={firmware / "etc/chromium/policies/chromium-app"}',
                 '--tesla-dbus-observe-navigation', '--user-agent-suffix= TeslaMusic/2026.26.6.1',
                 'http://firmware-media.vn.teslamotors.com:9000']
    return argv


def supported_flags(usage: str) -> set[str]:
    """Flag names from a Go program's -h output ("  -name type")."""
    return set(re.findall(r'^\s+-([A-Za-z0-9_]+)', usage, re.M))


def media_webapp_arguments(firmware: Path, version: str, usage: str = '') -> tuple[list[str], list[str]]:
    """Server command line, keeping only flags this firmware's server defines.

    Server flags differ between firmware releases; an undefined flag makes the
    server print its usage and exit, leaving the native media card loading.
    Returns (argv, dropped flag names). An unreadable usage keeps every flag."""
    flags = [('bind', '127.0.0.1'), ('port', '9000'), ('secondary_port', '9007'),
             ('tertiary_port', '9009'), ('platform_type', 'intel'), ('chassis_type', 'mx'),
             ('firmware_version', version), ('cache_exp_secs', '900'),
             ('oauth_reverse_proxy', 'https://activate.apple.com/'),
             ('qq_music_api_reverse_proxy', 'https://qplaycloud.y.qq.com/rpc_proxy/fcgi-bin/music_open_api.fcg'),
             ('qq_music_report_reverse_proxy', 'https://stat.y.qq.com/open/fcgi-bin/music_monitor_api.fcg'),
             ('dir', str(firmware / 'opt/media-webapp'))]
    known = supported_flags(usage)
    dropped = [name for name, _ in flags if known and name not in known]
    argv = [str(firmware / 'usr/bin/media-webapp-server')]
    argv += [f'-{name}={value}' for name, value in flags if name not in dropped]
    return argv, dropped


def odin_browser_arguments(firmware: Path, state: Path) -> list[str]:
    """The Service Mode panel's browser, mirroring the firmware's chromium-odin service.

    QtCar embeds the ChromiumOdin window in its Service card; the page is served by
    the firmware's own service-ui backend on localhost:8000."""
    return [str(firmware / 'usr/lib/tesla-chromium/tesla-chromium-main'),
            '--ozone-platform=x11', '--force-device-scale-factor=1.25', '--disable-setuid-sandbox',
            '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-notifications',
            '--disable-crashpad-for-testing', '--disable-breakpad', '--disable-crash-reporter',
            '--in-process-gpu', '--use-angle=gl', '--ignore-gpu-blocklist', '--disable-accelerated-video-decode',
            f'--user-data-dir={state / "chromium-odin-profile"}', '--window-size=1200,1920', '--window-position=10000,0',
            '--window-title=ChromiumOdin', '--user-agent-prefix=Tesla-Chromium', '--keyboard-app-name=chromium-odin',
            '--disable-pinch', '--enable-features=NetworkServiceInProcess2',
            '--disable-features=AudioServiceOutOfProcess,OverscrollHistoryNavigation,PersistentHistograms',
            '--disable-tab-strip', '--disable-toolbar', '--disable-location-bar', '--hide-crash-restore-bubble',
            '--tesla-dbus-service-name=com.tesla.ChromiumOdin', '--tesla-dbus-interface-name=com.tesla.ChromiumOdin',
            '--tesla-dbus-object-path=/ChromiumOdin',
            f'--policy-config-dir={firmware / "etc/chromium/policies/chromium-odin"}',
            '--class=TeslaMCU2-odin', '--enable-logging=stderr', resolver_rules(), 'http://localhost:8000']
