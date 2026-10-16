"""Offline routing preparation uses synthetic map and firmware fixtures only."""
import configparser
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'infotainment_lab'))
import navigation


@pytest.fixture
def inputs(tmp_path):
    maps, firmware, state = (tmp_path / n for n in ('maps with spaces', 'firmware', 'session'))
    (maps / 'tm/EU/valhalla').mkdir(parents=True)
    (maps / 'tm/EU/address.mt').write_bytes(b'synthetic address data')
    (maps / 'VERSION').write_text('EU-2026.8-12345\nsynthetic build details\n')
    (maps / 'NAVENGINE').write_text('TeslaMaps\n')
    (maps / 'FILESYNC.VERSION').write_text('synthetic\n')
    for member in ('usr/bin/valhalla_server', 'usr/tesla/UI/bin/QtCarTMServer'):
        target = firmware / member
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    target = firmware / 'usr/tesla/UI/assets/tesla_maps/valhalla.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({'mjolnir': {'max_cache_size': 123},
        'loki': {'service': {'proxy': 'ipc:///tmp/loki'}},
        'httpd': {'service': {'listen': 'tcp://*:8002'}}, 'traffic': {'enable': True}}))
    return firmware, maps, state


def test_offline_setup_uses_the_selected_map_and_private_endpoints(inputs):
    firmware, maps, state = inputs
    plan = navigation.prepare(firmware, maps, state)
    data = json.loads(plan['config'].read_text())
    assert plan['vehicle_region'] == 'EU' and plan['version'] == 'EU-2026.8-12345'
    assert data['mjolnir']['tile_dir'] == str(maps / 'tm/EU/valhalla')
    assert data['mjolnir']['max_cache_size'] == 123
    assert data['loki']['service']['proxy'].startswith('ipc://' + str(state))
    assert data['httpd']['service']['listen'] == 'tcp://127.0.0.1:8002'
    assert data['traffic']['enable'] is False
    argv = navigation.engine_arguments(firmware, plan)
    assert argv[argv.index('--tile_dir') + 1] == maps / 'tm/EU/valhalla'


def test_settings_keep_root_keys_and_existing_features(inputs):
    firmware, maps, state = inputs
    plan = navigation.prepare(firmware, maps, state)
    target = plan['home'] / '.Tesla/car/settings.conf'
    target.parent.mkdir(parents=True)
    target.write_text('enable_external_compositor=true\n[gui]\nforce_has_automation_app=true\n[nav]\nforceNavEngine=Tesla\n')
    navigation.configure_home(plan['home'], plan)
    settings = configparser.ConfigParser()
    settings.read(target)
    assert settings['General']['enable_external_compositor'] == 'true'
    assert settings['gui']['force_has_automation_app'] == 'true'
    assert settings['nav']['forcemapregion'] == 'EU'
    assert 'forcenavengine' not in settings['nav']
    assert settings['tm_server']['force_address_path'] == str(maps / 'tm/EU/address.mt')


def test_no_map_does_not_launch_or_modify_navigation(inputs):
    firmware, _, state = inputs
    assert navigation.prepare(firmware, None, state) is None
    assert not state.exists()
    assert navigation.status(None, {}, state) == {'state': 'no-map'}


def test_missing_tiles_and_links_outside_package_are_rejected(inputs, tmp_path):
    _, maps, _ = inputs
    (maps / 'tm/EU/valhalla').rmdir()
    with pytest.raises(ValueError, match='tile directory'):
        navigation.map_layout(maps)
    (maps / 'tm/EU/valhalla').mkdir()
    (maps / 'tm/EU/address.mt').unlink()
    (maps / 'tm/EU/address.mt').symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError, match='outside'):
        navigation.map_layout(maps)


def test_readiness_waits_for_owned_processes_and_engine_initialization(inputs):
    firmware, maps, state = inputs
    plan = navigation.prepare(firmware, maps, state)
    assert not navigation.status(plan, {}, state)['offline_routing']
    (state / 'valhalla.log').write_text('valhalla_server 2.4.3 ready..\n')
    report = navigation.status(plan, {'valhalla': 'running', 'tm-server': 'running'}, state)
    assert report['offline_routing'] and report['street_imagery'] == 'network-provider'
    with (state / 'valhalla.log').open('a') as stream:
        stream.write('route requests\n' * 1000)
    assert navigation.status(plan, {'valhalla': 'running', 'tm-server': 'running'}, state)['offline_routing']


def test_tiles_symlink_cannot_escape_package(inputs, tmp_path):
    _, maps, _ = inputs
    tiles = maps / 'tm/EU/valhalla'
    tiles.rmdir()
    outside = tmp_path / 'external tiles'
    outside.mkdir()
    tiles.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='tile directory'):
        navigation.map_layout(maps)
