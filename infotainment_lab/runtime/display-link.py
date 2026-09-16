"""Reconcile desktop display preferences and route firmware audio to WSLg."""
import dbus
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vehicle_services import PREFERENCES, CENTER_CHANNELS, PreferenceSync, DisplayWriter, decode_value, equivalent
from display_bus import connect, call_many

state = Path(os.environ['TESLA_NATIVE_STATE'])
firmware = Path(os.environ['TESLA_FIRMWARE']).resolve()
bus = connect(os.environ['DBUS_SESSION_BUS_ADDRESS'])
sync = PreferenceSync()
owners = {}
readers = {}
last_report = last_audio = 0
last_streams = {}
audio = {}


def typed(value):
    if isinstance(value, bool):
        return dbus.Boolean(value, variant_level=1)
    if isinstance(value, (float, int)):
        return dbus.Double(value, variant_level=1)
    return dbus.String(value, variant_level=1)


def get(interface, name, short=None):
    if interface is None:
        return False, None
    if short is not None:
        return readers[short].read(name)
    ok, raw = interface.DataGetValueRequest(name, timeout=.3)
    return bool(ok), decode_value(raw)


def route_audio(values, center):
    if 'GUI_audioVolume' not in values:
        return {}
    ok, maximum = get(center, 'GUI_audioVolumeMax')
    maximum = maximum if ok and isinstance(maximum, (int, float)) and maximum > 0 else 10.333
    percent = round(max(0, min(1, float(values['GUI_audioVolume']) / maximum)) * 100)
    muted = values.get('GUI_muteAudioRequest') is True
    streams = json.loads(subprocess.check_output(['pactl', '-f', 'json', 'list', 'sink-inputs'], text=True, timeout=3))
    owned, present = [], set()
    for stream in streams:
        pid = str(stream.get('properties', {}).get('application.process.id', ''))
        if not pid.isdigit():
            continue
        try:
            actual = (Path('/proc') / pid / 'exe').resolve(strict=True)
        except OSError:
            continue
        # Never alter unrelated desktop or system audio streams.
        if not actual.is_relative_to(firmware):
            continue
        index = str(stream['index'])
        present.add(index)
        settings = (pid, percent, muted)
        if last_streams.get(index) != settings:
            subprocess.run(['pactl', 'set-sink-input-volume', index, f'{percent}%'], check=True, timeout=2)
            subprocess.run(['pactl', 'set-sink-input-mute', index, '1' if muted else '0'], check=True, timeout=2)
            last_streams[index] = settings
        owned.append(index)
    for index in set(last_streams) - present:
        last_streams.pop(index, None)
    return {'wslg_app_volume_percent': percent, 'wslg_app_muted': muted, 'streams': owned}


while True:
    tick = time.monotonic()
    fields, values, errors, interfaces, restarted = {}, {}, {}, {}, set()
    try:
        for short, service in (('center', 'com.tesla.CenterDisplay'), ('cluster', 'com.tesla.ClusterDisplay')):
            owner = str(bus.get_name_owner(service)) if bus.name_has_owner(service) else None
            if owner:
                interfaces[short] = dbus.Interface(bus.get_object(service, '/LocalDataValue'), 'com.tesla.LocalDataValue')
            else:
                interfaces[short] = None
            if owners.get(short) != owner:
                # A restarted display receives the live display's current state.
                # Preserve the common baseline: an unchanged peer remains the
                # authority when the new process has reset to firmware defaults.
                owners[short] = owner
                if owner:
                    restarted.add(short)
                    readers[short] = DisplayWriter(interfaces[short], batch=call_many)
                else:
                    readers.pop(short, None)
        observed, read_errors = {}, {}
        names = (*PREFERENCES, *CENTER_CHANNELS)
        for short, reader in readers.items():
            try:
                observed[short] = reader.read_many(names)
            except (dbus.DBusException, OSError, TypeError, ValueError) as exc:
                read_errors[short] = exc
        for name in names:
            try:
                if read_errors:
                    raise next(iter(read_errors.values()))
                cok, cv = observed.get('center', {}).get(name, (False, None))
                iok, iv = observed.get('cluster', {}).get(name, (False, None))
                record = {'center': cv, 'cluster': iv, 'status': 'unavailable'}
                if not cok or not iok or (cv is None and iv is None):
                    record['status'] = 'unsupported' if interfaces['center'] and interfaces['cluster'] else 'waiting-display'
                    if cok and iok and cv is None and iv is None:
                        record['status'] = 'waiting-value'
                    if cok and cv is not None:
                        values[name] = cv
                    fields[name] = record
                    continue
                if name in CENTER_CHANNELS and cv is None:
                    record['status'] = 'waiting-value'
                    fields[name] = record
                    continue
                source, chosen, conflict = sync.choose(name, cv, iv, restarted)
                record.update(source=source or 'both', conflict=conflict)
                if source:
                    target = 'cluster' if source == 'center' else 'center'
                    accepted = interfaces[target].DataSetValueRequest(name, typed(chosen), timeout=.3)
                    ok, actual = get(interfaces[target], name, target)
                    if accepted and ok and equivalent(actual, chosen):
                        sync.accepted(name, chosen)
                        record[target] = actual
                        record['status'] = 'accepted'
                    else:
                        record['status'] = 'rejected' if not accepted else 'mismatch'
                else:
                    record['status'] = 'synchronized'
                values[name] = chosen
                fields[name] = record
            except (dbus.DBusException, OSError, TypeError, ValueError) as exc:
                fields[name] = {'status': 'error'}
                errors[name] = str(exc)
        if tick >= last_audio + 1:
            last_audio = tick
            try:
                audio = route_audio(values, interfaces['center'])
            except (OSError, ValueError, subprocess.SubprocessError, dbus.DBusException) as exc:
                audio = {'error': str(exc)}
        if tick >= last_report + 1:
            record = {'updated_at': time.time(), 'direction': 'CenterDisplay <-> ClusterDisplay',
                      'values': {name: str(value).lower() if isinstance(value, bool) else str(value) for name, value in values.items()},
                      'fields': fields, 'audio': audio,
                      'connected': {name: bool(owner) for name, owner in owners.items()},
                      'synchronized_count': sum(item['status'] in ('synchronized', 'accepted') for item in fields.values()),
                      'errors': errors}
            record['values'].update({key: value for key, value in audio.items() if key.startswith('wslg_')})
            temp = state / 'display-link.json.new'
            temp.write_text(json.dumps(record, indent=2) + '\n')
            temp.replace(state / 'display-link.json')
            last_report = tick
    except (dbus.DBusException, OSError, TypeError, ValueError) as exc:
        print(str(exc), flush=True)
    time.sleep(max(0, .25 - (time.monotonic() - tick)))
