"""Apply the local simulator to private displays and measure host connectivity."""
import dbus
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from simulation import Simulation, display_values as driving_values, indicator_values
from vehicle_services import (VehicleServices, REQUEST_FIELDS, CAPABILITIES, DisplayWriter,
                              display_values, equivalent, speed_display_values, replay_location,
                              MEDIA_NETWORK_SERVICES, media_network_values)
from vehicle_services import BodyRequestRouter, BODY_REQUESTS, decode_service_request
from display_bus import connect, call_many

bus = connect(os.environ['DBUS_SESSION_BUS_ADDRESS'])
state = Path(os.environ['TESLA_NATIVE_STATE'])
title_prefix = os.environ.get('TESLA_NATIVE_TITLE', 'Infotainment Lab | Center')
services = os.environ.get('TESLA_DV_SERVICES', 'com.tesla.CenterDisplay').split(',')
storage = state / 'storage'
storage.mkdir(parents=True, exist_ok=True)
snapshot = {'online': False, 'ip': '', 'checked_at': None}
model = VehicleServices()
vehicle_profile = {}
try:
    profile_path = Path(os.environ.get('TESLA_NATIVE_VEHICLE_PROFILE', ''))
    if profile_path.is_file():
        vehicle_profile = json.loads(profile_path.read_text()).get('signals', {})
except (OSError, ValueError, TypeError) as exc:
    print(f'Unable to load vehicle profile: {exc}', flush=True)


def atomic_json(name, value):
    temporary = state / (name + '.new')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(state / name)


def read_json(name, default=None):
    try:
        return json.loads((state / name).read_text())
    except (OSError, ValueError):
        return default


def monitor():
    global snapshot
    while True:
        online, ip, error = False, '', None
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(('1.1.1.1', 443))
                ip = sock.getsockname()[0]
            with urllib.request.urlopen('https://www.google.com/generate_204', timeout=8) as reply:
                online = reply.status == 204
        except (OSError, ValueError) as exc:
            error = str(exc)
        try:
            usage, debian = shutil.disk_usage(storage), shutil.disk_usage(state)
            snapshot = {'online': online, 'ip': ip, 'checked_at': time.time(), 'error': error,
                        'storage_path': str(storage), 'total_bytes': usage.total,
                        'free_bytes': usage.free, 'used_bytes': usage.used,
                        'debian_virtual_free_bytes': debian.free,
                        'battery_percent_simulated': model.battery_percent}
            atomic_json('host-status.json', snapshot)
            title = (f'{title_prefix} | Internet: {"online" if online else "offline"}'
                     f' | Battery: {model.battery_percent:g}% (sim)'
                     f' | Disk: {usage.free/1024**3:.1f} GiB free / {usage.total/1024**4:.2f} TiB')
            env = dict(os.environ, DISPLAY=os.environ.get('TESLA_HOST_DISPLAY', ':0'))
            ids = [] if os.environ.get('TESLA_EXTERNAL_DISPLAY') == '1' else subprocess.check_output(
                ['xdotool', 'search', '--name', '^'+re.escape(title_prefix)],
                env=env, text=True, timeout=3).split()
            for wid in ids:
                subprocess.run(['xdotool', 'set_window', '--name', title, wid], env=env, check=True, timeout=3)
        except (OSError, subprocess.SubprocessError) as exc:
            print(str(exc), flush=True)
        time.sleep(30)


def typed(value):
    if isinstance(value, bool):
        return dbus.Boolean(value, variant_level=1)
    if isinstance(value, int):
        return dbus.Int32(value, variant_level=1)
    if isinstance(value, float):
        return dbus.Double(value, variant_level=1)
    return dbus.String(value, variant_level=1)


def apply_vehicle_profile(interface):
    """Write the named MCU2 values once whenever a display service starts."""
    result = {}
    for name, value in vehicle_profile.items():
        try:
            result[name] = 'accepted' if interface.DataSetValueRequest(name, typed(value), timeout=1) else 'unsupported'
        except dbus.DBusException as exc:
            result[name] = exc.get_dbus_name()
    return result


def network_values(current):
    online, connected, free = current['online'], bool(current['ip']), current.get('free_bytes', 0)
    return {
        'CONN_connectedToInternet': online, 'CONN_wifiConnected': connected,
        'CONN_wifiActive': connected, 'CONN_cellConnected': False,
        'CONN_wifiInterfaceIP': current['ip'], 'CONN_wifiInternetCheckFailed': not online,
        'LINK_wifiEnabled': connected, 'LINK_wifiConnectionStatus': 'connected' if connected else 'disconnected',
        'LINK_wifiSsid': 'Local lab network', 'LINK_wifiBars': 4 if online else 0,
        'LINK_wifiState': 'online' if online else 'ready' if connected else 'idle',
        'LINK_linkState': 'wifi' if connected else '', 'LINK_wifiOnlineCheckFailure': not online,
        'WIFI_connected': connected, 'WIFI_powered': connected,
        'WIFI_network': 'Local lab network', 'WIFI_address': current['ip'],
        'WIFI_signalQuality': 100 if online else 0,
        'SYS_CD_freeDiskSpace': f'Local disk: {free/1024**3:.1f} GiB free / {current.get("total_bytes",0)/1024**4:.2f} TiB',
        'SYS_CD_storageRunningLow': free < 5*1024**3,
    }


threading.Thread(target=monitor, daemon=True).start()
time.sleep(float(os.environ.get('TESLA_NATIVE_STATE_DELAY', '10')))
awake = {'GUI_enableDisplayKeepAlive': True, 'VAPI_driverPresent': True,
         'VAPI_icLCDOn': True, 'VAPI_icBacklightOn': True, 'VAPI_vehicleInAccessoryPlus': True,
         'VAPI_carType': os.environ.get('TESLA_NATIVE_CAR_TYPE', '3'),
         'GUI_audioReady': True, 'GUI_serviceModeAudioResetNeeded': False}
if os.environ.get('TESLA_NATIVE_CAR_TYPE') in ('ModelS', 'ModelX'):
    awake |= {'VAPI_driveRailOn': True, 'VAPI_accRailOn': True}
writers, owners, request_baseline = {}, {}, {}
media_writers, media_owners, media_network_report = {}, {}, {}
controls = Simulation()
control_report, service_report, service_details, errors = {}, {}, {}, {}
control_errors = {}
vehicle_profile_report = {}
volume_max, distance_units = {}, {}
config_stamp = None
next_inventory = next_requests = next_services = next_slow = next_network = next_report = 0
last_controls = None
last_gps = None
last_network_stamp = None
service_dirty = True
last_source = 'defaults'
indicator_direction, indicator_since = 'off', time.monotonic()
body_router = BodyRequestRouter()

while True:
    tick = time.monotonic()
    try:
        if tick >= next_inventory:
            next_inventory = tick + .5
            for service in MEDIA_NETWORK_SERVICES:
                try:
                    owner = str(bus.get_name_owner(service)) if bus.name_has_owner(service) else None
                    if not owner:
                        media_writers.pop(service, None)
                        media_owners.pop(service, None)
                        media_network_report.pop(service, None)
                    elif media_owners.get(service) != owner:
                        iface = dbus.Interface(bus.get_object(service, '/LocalDataValue'), 'com.tesla.LocalDataValue')
                        media_writers[service], media_owners[service] = DisplayWriter(iface, typed, batch=call_many), owner
                        next_network = 0
                except dbus.DBusException as exc:
                    errors[service] = str(exc)
            for service in services:
                try:
                    owner = str(bus.get_name_owner(service)) if bus.name_has_owner(service) else None
                    if owner is None:
                        writers.pop(service, None)
                        owners.pop(service, None)
                        control_report.pop(service, None)
                        control_errors.pop(service, None)
                        service_report.pop(service, None)
                        service_details.pop(service, None)
                        if service == 'com.tesla.CenterDisplay':
                            body_router = BodyRequestRouter()
                        continue
                    if owners.get(service) != owner:
                        iface = dbus.Interface(bus.get_object(service, '/LocalDataValue'), 'com.tesla.LocalDataValue')
                        vehicle_profile_report[service] = apply_vehicle_profile(iface)
                        writer = DisplayWriter(iface, typed, batch=call_many)
                        ok, maximum = writer.read('GUI_audioVolumeMax')
                        volume_max[service] = maximum if ok and isinstance(maximum, (float, int)) and maximum > 0 else 10.333
                        request_baseline[service] = {}
                        writers[service], owners[service] = writer, owner
                        if service == 'com.tesla.CenterDisplay':
                            body_router = BodyRequestRouter()
                        service_dirty = True
                        next_slow = 0
                        next_network = 0
                        last_controls = None
                except dbus.DBusException as exc:
                    errors[service] = str(exc)
        # Changes from the desktop control panel are authoritative for this tick.
        try:
            stamp = (state / 'vehicle-services.json').stat().st_mtime_ns
            changed_config = stamp != config_stamp
            if changed_config:
                model = VehicleServices.parse(read_json('vehicle-services.json'))
                config_stamp, service_dirty, last_source = stamp, True, 'desktop'
                errors.pop('config', None)
        except FileNotFoundError:
            changed_config = False
        except (ValueError, TypeError) as exc:
            changed_config = False
            errors['config'] = str(exc)

        # Native climate and audio controls update the same local model. Compare
        # against each display's last observed state to avoid a feedback loop.
        if tick >= next_requests:
            next_requests = tick + .25
            changes = {}
            body_readings = None
            for service in reversed(services):  # Center wins simultaneous changes.
                writer = writers.get(service)
                if not writer:
                    continue
                baseline = request_baseline.setdefault(service, {})
                try:
                    names = ['GUI_distanceUnits', *REQUEST_FIELDS.values()]
                    if service == 'com.tesla.CenterDisplay':
                        names.extend(BODY_REQUESTS)
                    readings = writer.read_many(names)
                    if service == 'com.tesla.CenterDisplay':
                        body_readings = readings
                    ok, units = readings['GUI_distanceUnits']
                    if distance_units.get(service) != units:
                        last_controls = None
                    distance_units[service] = units if ok else 'Miles'
                    for field, name in REQUEST_FIELDS.items():
                        ok, value = readings[name]
                        if not ok or value is None:
                            continue
                        old = baseline.get(name)
                        baseline[name] = value
                        value = decode_service_request(field, value, volume_max[service])
                        if changed_config:
                            continue
                        if old is None or not equivalent(old, baseline[name]):
                            try:
                                model.patched({field: value})
                                changes[field] = value
                            except (TypeError, ValueError):
                                pass
                except (dbus.DBusException, OSError) as exc:
                    errors[service] = str(exc)
            if changes:
                updated = model.patched(changes)
                if updated != model:
                    model, service_dirty, last_source = updated, True, 'native-ui'
            center_writer = writers.get('com.tesla.CenterDisplay')
            if center_writer and body_readings is not None:
                updated = body_router.poll(center_writer.interface, model, typed,
                                           desktop_changed=changed_config, readings=body_readings)
                if updated != model:
                    model, service_dirty, last_source = updated, True, 'native-ui'

        controls = Simulation.parse(read_json('controls.json', {}))
        current_controls = controls.as_dict()
        if controls.indicator != indicator_direction:
            indicator_direction, indicator_since = controls.indicator, tick
        if snapshot.get('checked_at') != last_network_stamp:
            next_network = 0
        replay = read_json('replay-status.json', {}) or {}
        request = read_json('replay-request.json', {}) or {}
        gps = replay_location(replay, request, time.time())
        current_gps = gps.as_dict() if gps else None
        if current_gps is None and last_gps is not None:
            service_dirty = True

        for service, writer in tuple(writers.items()):
            try:
                if current_controls != last_controls or tick >= next_slow or service in control_errors:
                    driving = driving_values(controls)
                    driving['indicator'] = indicator_values(controls.indicator, tick - indicator_since)
                    # Keep ApViz motion inputs (signed/replay speed) while
                    # applying the display-unit-specific speedometer values.
                    driving['speed_kph'].update(
                        speed_display_values(controls.speed_kph, distance_units.get(service, 'Miles')))
                    control_report[service], _ = writer.apply(
                        driving, verify_cached=tick >= next_slow or service in control_errors)
                    control_errors.pop(service, None)
                indicator_report, _ = writer.apply({'indicator': indicator_values(controls.indicator, tick - indicator_since)})
                control_report.setdefault(service, {}).update(indicator_report)
                if (current_gps != last_gps or tick >= next_slow) and gps:
                    gps_signals = {k: v for k, v in display_values(gps).items()
                                   if k in ('latitude_deg', 'longitude_deg', 'heading_deg')}
                    gps_report, gps_details = writer.apply(gps_signals)
                    service_report.setdefault(service, {}).update(gps_report)
                    service_details.setdefault(service, {}).update(gps_details)
                if service_dirty or tick >= next_services:
                    signals = display_values(model, volume_max.get(service, 10.333))
                    if gps:
                        signals = {k: v for k, v in signals.items() if k not in ('latitude_deg', 'longitude_deg', 'heading_deg')}
                    report, details = writer.apply(signals, verify_cached=tick >= next_services)
                    service_report.setdefault(service, {}).update(report)
                    service_details.setdefault(service, {}).update(details)
                    # Record our writes immediately, so they cannot be mistaken
                    # for a user request in the next 250ms native-input poll.
                    request_baseline[service] = {name: result[1] for name, result in
                                                 writer.read_many(REQUEST_FIELDS.values()).items()}
                if tick >= next_slow:
                    writer.apply({'awake': awake}, verify_cached=True)
                if tick >= next_network:
                    writer.apply({'network': network_values(snapshot)}, verify_cached=True)
                errors.pop(service, None)
            except (dbus.DBusException, OSError, ValueError, TypeError) as exc:
                errors[service] = str(exc)
                control_errors[service] = str(exc)
                control_report[service] = {field: 'error' for field in current_controls}
        last_controls, last_gps = current_controls, current_gps
        if tick >= next_services or service_dirty:
            next_services, service_dirty = tick + 2, False
        if tick >= next_slow:
            next_slow = tick + 2
        if tick >= next_network:
            for service, writer in tuple(media_writers.items()):
                try:
                    _, detail = writer.apply({'network': media_network_values(snapshot)}, verify_cached=True)
                    media_network_report[service] = detail['network']
                    errors.pop(service, None)
                except (dbus.DBusException, OSError, ValueError, TypeError) as exc:
                    errors[service] = str(exc)
            next_network = tick + 30
            last_network_stamp = snapshot.get('checked_at')
        if tick >= next_report:
            now = time.time()
            atomic_json('controls-feedback.json', {'requested': current_controls, 'firmware': control_report,
                                                   'errors': control_errors,
                                                   'updated_at': now, 'tick_ms': 50,
                                                   'apply_duration_ms': round((time.monotonic()-tick)*1000, 1)})
            atomic_json('vehicle-services-feedback.json', {
                'state': model.as_dict(), 'requested': model.as_dict(), 'source': last_source,
                'config_mtime_ns': config_stamp,
                'firmware': service_report, 'signals': service_details, 'capabilities': CAPABILITIES,
                'gps_source': 'dashcam' if gps else 'desktop', 'errors': errors, 'updated_at': now,
                'media_network': media_network_report,
                'vehicle_profile': vehicle_profile_report,
                'body_requests': body_router.report,
            })
            next_report = tick + .5
    except (dbus.DBusException, OSError, ValueError, TypeError) as exc:
        print(str(exc), flush=True)
    time.sleep(max(0, .05 - (time.monotonic() - tick)))
