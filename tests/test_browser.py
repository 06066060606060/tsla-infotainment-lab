from pathlib import Path
import pytest
from infotainment_lab.browser import MODES, browser_arguments, browser_url


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
