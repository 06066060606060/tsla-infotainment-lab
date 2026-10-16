"""Prepare an owned offline routing engine from a read-only map package."""
from pathlib import Path
import configparser
import json
import re

from core import atomic_json


def map_layout(root):
    root = Path(root).resolve()
    with (root / 'VERSION').open() as stream:
        metadata = stream.read(16385)
    if not metadata.strip() or len(metadata) > 16384:
        raise ValueError('The selected map package has invalid version metadata.')
    version = metadata.splitlines()[0].strip()
    match = re.fullmatch(r'(NA|EU)-\d{4}(?:\.\d+){1,3}(?:-[A-Za-z0-9]+)?', version)
    if not match or (root / 'NAVENGINE').read_text().strip() != 'TeslaMaps':
        raise ValueError('Offline navigation needs an NA or EU TeslaMaps package.')
    region = match.group(1)
    folder = (root / 'tm' / region).resolve()
    tiles = (folder / 'valhalla').resolve()
    if not folder.is_relative_to(root) or not tiles.is_relative_to(root) or not tiles.is_dir():
        raise ValueError('The selected map package has no contained Valhalla tile directory.')
    address = (folder / 'address.mt').resolve()
    if not address.is_relative_to(root):
        raise ValueError('The map address database is outside its package.')
    if not address.is_file():
        raise ValueError('The selected map package has no address database.')
    return {'root': root, 'version': version, 'region': region,
            'vehicle_region': 'EU' if region == 'EU' else 'USCanada',
            'tiles': tiles, 'address': address}


def private_ipc(value, directory):
    if isinstance(value, dict):
        return {key: private_ipc(item, directory) for key, item in value.items()}
    if isinstance(value, list):
        return [private_ipc(item, directory) for item in value]
    if isinstance(value, str) and value.startswith('ipc:///tmp/'):
        return 'ipc://' + str(directory / value.rsplit('/', 1)[-1])
    return value


def prepare(firmware, maps, state):
    if not maps:
        return None
    firmware, state = Path(firmware), Path(state)
    layout = map_layout(maps)
    for member in ('usr/bin/valhalla_server', 'usr/tesla/UI/bin/QtCarTMServer',
                   'usr/tesla/UI/assets/tesla_maps/valhalla.json'):
        if not (firmware / member).is_file():
            raise ValueError('The firmware has no offline navigation dependency: ' + member)
    directory = state / 'navigation'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    ipc = directory / 'ipc'
    ipc.mkdir(mode=0o700, exist_ok=True)
    source = firmware / 'usr/tesla/UI/assets/tesla_maps/valhalla.json'
    config = private_ipc(json.loads(source.read_text()), ipc)
    config.setdefault('mjolnir', {}).update(tile_dir=str(layout['tiles']),
        map_version_file=str(layout['root'] / 'FILESYNC.VERSION'), override_file='/dev/null')
    for key, name in (('admin', 'admin.sqlite'), ('timezone', 'tz_world.sqlite'), ('transit_dir', 'transit')):
        config['mjolnir'][key] = str(layout['tiles'] / name)
    config.setdefault('additional_data', {})['elevation'] = str(layout['tiles'] / 'elevation')
    config.setdefault('traffic', {})['enable'] = False
    config.setdefault('httpd', {}).setdefault('service', {})['listen'] = 'tcp://127.0.0.1:8002'
    target = directory / 'valhalla.json'
    atomic_json(target, config)
    layout.update(config=target, home=state / 'tmserver-home')
    return layout


def configure_home(home, layout):
    """Use the firmware's own settings for region, map version and address data."""
    if not layout:
        return
    home = Path(home)
    (home / '.Tesla/data').mkdir(parents=True, exist_ok=True, mode=0o700)
    target = home / '.Tesla/car/settings.conf'
    target.parent.mkdir(parents=True, exist_ok=True)
    settings = configparser.ConfigParser(interpolation=None, strict=False)
    settings.optionxform = str
    # Qt INI files allow root keys before their first section. Python's INI
    # reader requires an explicit section; General denotes those root keys in Qt.
    settings.read_string('[General]\n' + (target.read_text() if target.exists() else ''))
    for group in ('nav', 'tm_server'):
        if not settings.has_section(group): settings.add_section(group)
    # The force override creates the native "USING TESLAMAPS" debug banner.
    # The session vehicle profile selects TeslaMaps through VAPI instead.
    settings['nav'].pop('forceNavEngine', None)
    settings['nav'].update(forceMapRegion=layout['vehicle_region'],
        forceSearchEngine='Tesla', mapsVersionFile=str(layout['root'] / 'VERSION'))
    settings['tm_server']['force_address_path'] = str(layout['address'])
    with target.open('w') as stream:
        settings.write(stream)


def engine_arguments(firmware, layout):
    return [Path(firmware) / 'usr/bin/valhalla_server', '--config', layout['config'],
            '--tile_dir', layout['tiles'], '--override_file', '/dev/null']


def status(layout, components, state):
    if not layout:
        return {'state': 'no-map'}
    record = {'state': 'starting', 'version': layout['version'], 'region': layout['region'],
              'offline_routing': False, 'street_imagery': 'network-provider'}
    if any(components.get(n) != 'running' for n in ('valhalla', 'tm-server')):
        record['state'] = 'waiting-services'
        return record
    try:
        with (Path(state) / 'valhalla.log').open('rb') as stream:
            # Read startup, not the tail: subsequent requests can grow the log.
            ready = b'ready..' in stream.read(8192)
    except OSError:
        ready = False
    record.update(state='engine-ready' if ready else 'starting', offline_routing=ready)
    return record
