from pathlib import Path
import pytest
from infotainment_lab.browser import MODES, browser_arguments, browser_url, media_browser_arguments, media_health


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
    assert resolver.count('127.0.0.1') == 2
    assert 'spotify.com' not in resolver and '*' not in resolver
    assert '--disable-web-security' not in args
    assert '--disable-cors-preflight' not in args
    assert '--ignore-certificate-errors' not in args
    assert '--unsafely-treat-insecure-origin-as-secure=http://firmware-media.vn.teslamotors.com:9000' in args
    assert f'--policy-config-dir={tmp_path / "fw/etc/chromium/policies/chromium-app"}' in args
    normal = browser_arguments(tmp_path / 'fw', tmp_path / 'state', tmp_path / 'runtime', 'browser')
    assert not any('treat-insecure-origin' in value for value in normal)
