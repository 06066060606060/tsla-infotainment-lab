from pathlib import Path
import pytest
from infotainment_lab.browser import MODES, browser_arguments, browser_url, media_browser_arguments, media_health, media_webapp_arguments, odin_browser_arguments


def test_media_health_distinguishes_live_processes_from_rejected_native_transport():
    components = {n: 'running' for n in ('spotify', 'media-adapter', 'media-webapp', 'chromium-media')}
    assert media_health(components, '')['state'] == 'services-running'
    unrelated = '[VehicleDataListener] ERROR [PEERSEC] Incorrect security profile'
    assert media_health(components, unrelated)['state'] == 'services-running'
    failure = '[SpotifyServerDataListener] ERROR [PEERSEC] Incorrect security profile. private-log-text'
    result = media_health(components, failure)
    assert result == {'state': 'peer-profile-rejected', 'services': ['SpotifyServerDataListener']}
    assert media_health(components | {'spotify': 'exited'}, failure)['state'] == 'waiting-services'
    assert media_health({}, failure)['state'] == 'disabled'


def test_all_browser_instances_have_distinct_profiles_and_bus_names(tmp_path):
    profiles, names = [], []
    for mode in MODES:
        argv = browser_arguments(tmp_path / 'firmware', tmp_path / 'state', tmp_path / 'runtime', mode)
        profiles.append(next(a for a in argv if a.startswith('--user-data-dir=')))
        names.append(next(a for a in argv if a.startswith('--tesla-dbus-service-name=')))
        assert argv[-1] == (tmp_path / 'runtime/welcome.html').as_uri()
    assert len(set(profiles)) == len(set(names)) == 3


@pytest.mark.parametrize('value', ['file:///private/file', 'javascript:alert(1)', 'https://', '',
                                  'https://user:password@example.com/', 'https://example.com/\nheader'])
def test_browser_address_rejects_non_website_input(value):
    with pytest.raises(ValueError): browser_url(value)


def test_browser_preserves_normal_website_path_and_query():
    assert browser_url(' https://example.com/a?q=hello%20world ') == 'https://example.com/a?q=hello%20world'


def test_media_window_uses_its_own_profile_and_only_maps_local_firmware_services(tmp_path):
    args = media_browser_arguments(tmp_path / 'fw', tmp_path / 'state', tmp_path / 'runtime')
    assert '--tesla-dbus-service-name=com.tesla.ChromiumApp' in args
    assert '--keyboard-app-name=ChromiumApp' in args
    assert any('chromium-media-profile' in item for item in args)
    resolver = next(item for item in args if item.startswith('--host-resolver-rules='))
    local = [rule for rule in resolver.split('=', 1)[1].split(', ') if not rule.endswith('~NOTFOUND')]
    assert local == ['MAP firmware-media.vn.teslamotors.com 127.0.0.1',
                     'MAP firmware-media-adapter.vn.teslamotors.com 127.0.0.1']
    assert 'MAP *.tesla.com ~NOTFOUND' in resolver and 'MAP *.teslamotors.com ~NOTFOUND' in resolver
    assert resolver.index('firmware-media-adapter') < resolver.index('~NOTFOUND')  # first match wins
    assert sum(item.startswith('--host-resolver-rules=') for item in args) == 1
    assert '--disable-web-security' not in args
    assert '--disable-cors-preflight' not in args
    assert '--ignore-certificate-errors' not in args
    assert '--unsafely-treat-insecure-origin-as-secure=http://firmware-media.vn.teslamotors.com:9000' in args
    assert f'--policy-config-dir={tmp_path / "fw/etc/chromium/policies/chromium-app"}' in args
    normal = browser_arguments(tmp_path / 'fw', tmp_path / 'state', tmp_path / 'runtime', 'browser')
    assert not any('treat-insecure-origin' in value for value in normal)


def test_media_server_omits_flags_the_firmware_does_not_define(tmp_path):
    usage = ('flag provided but not defined: -secondary_port\n'
             'Usage of media-webapp-server:\n  -bind string\n        IP address to bind to\n'
             '  -cache_exp_secs int\n  -chassis_type string\n  -dir string\n  -firmware_version string\n'
             '        customer facing firmware version name\n  -is_development_car\n'
             '  -oauth_reverse_proxy string\n  -platform_type string\n  -port int\n'
             '        port number to listen on (default -1)\n'
             '  -qq_music_api_reverse_proxy string\n  -qq_music_report_reverse_proxy string\n')
    argv, dropped = media_webapp_arguments(tmp_path, '2026.1', usage)
    assert dropped == ['secondary_port', 'tertiary_port']
    assert argv[0] == str(tmp_path / 'usr/bin/media-webapp-server')
    assert '-port=9000' in argv and '-firmware_version=2026.1' in argv
    assert not any(value.startswith(('-secondary_port', '-tertiary_port', '-is_development_car')) for value in argv)


def test_media_server_keeps_every_flag_without_usage(tmp_path):
    argv, dropped = media_webapp_arguments(tmp_path, '2026.1', '')
    assert dropped == [] and '-secondary_port=9007' in argv and '-tertiary_port=9009' in argv


def test_service_mode_browser_mirrors_the_firmware_chromium_odin(tmp_path):
    argv = odin_browser_arguments(tmp_path / 'fw', tmp_path / 'state')
    assert argv[0] == str(tmp_path / 'fw/usr/lib/tesla-chromium/tesla-chromium-main')
    assert argv[-1] == 'http://localhost:8000'
    for flag in ('--window-title=ChromiumOdin', '--keyboard-app-name=chromium-odin',
                 '--tesla-dbus-service-name=com.tesla.ChromiumOdin', '--tesla-dbus-object-path=/ChromiumOdin',
                 '--force-device-scale-factor=1.25', '--class=TeslaMCU2-odin', '--window-position=10000,0'):
        assert flag in argv
    assert f'--user-data-dir={tmp_path / "state/chromium-odin-profile"}' in argv
    assert f'--policy-config-dir={tmp_path / "fw/etc/chromium/policies/chromium-odin"}' in argv
    # Like the other firmware browsers: an out-of-process network service
    # crashes with an FD ownership violation on the desktop.
    assert '--enable-features=NetworkServiceInProcess2' in argv
    assert sum(value.startswith('--disable-features=') for value in argv) == 1


def test_every_browser_refuses_tesla_domains(tmp_path):
    for mode in ('browser', 'card', 'theater'):
        args = browser_arguments(tmp_path / 'fw', tmp_path / 'state', tmp_path / 'runtime', mode)
        assert 'MAP *.tesla.services ~NOTFOUND' in next(a for a in args if a.startswith('--host-resolver-rules='))
    assert 'MAP *.tesla.cn ~NOTFOUND' in ' '.join(odin_browser_arguments(tmp_path / 'fw', tmp_path / 'state'))
