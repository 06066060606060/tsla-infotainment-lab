"""Parse, filter and export Name,Value configuration dumps (local data only)."""
import csv
import io
from functools import lru_cache
import json
from pathlib import Path
import re

INVALID = '@invalid'
# Categories an import queues. Everything else in a dump mirrors hardware or live telemetry (display power,
# battery, radio…); writing it makes the simulated hardware misbehave, so it is listed but not sent.
SETTING_PREFIXES = ('FEATURE', 'GUI', 'VAPI', 'APP', 'APTRIAL', 'GTW', 'OPTION', 'AUTONAVDEBUG')
# Watched by the firmware but not in the vehicle profile: seen restarting it (the supervisor learns more).
# GTW_dasHw has no default: a value the imported car lacks makes the firmware re-derive its Autopilot features.
# The market switch's keys (market.py) are here too, so a fresh start applies them without relying on the learned list.
CAR_CONFIG_EXTRA = frozenset({'VAPI_packConfig', 'VAPI_tpmsType', 'VAPI_restraintControlsType', 'GUI_navigationEngine', 'GTW_dasHw',
                              'GUI_applyEceR79', 'GUI_distanceUnits', 'GUI_temperatureUnits', 'GUI_tirePressureUnits',
                              'GUI_language', 'GUI_locale', 'GUI_manualLanguage', 'VAPI_carVersionString'})

# These opt-in display simulation inputs can be replaced by firmware service
# defaults after startup. Recheck explicit overrides without replaying commands
# or vehicle configuration changes that restart the native UI.
LOCAL_FSD_UI_SETTINGS = frozenset({
    'FEATURE_fullSelfDriving', 'FEATURE_hasFullSelfDrivingNavMaps',
    'GUI_enableFSDFunctions', 'GUI_fsdControlEnabled',
    'GUI_enableStartFsdFromPark', 'GUI_isOnNavigationMap',
})


def pending_overrides(values, sent, car_config, explicit=(), refresh=False):
    """Select changed overrides plus periodic, explicitly opted-in UI inputs."""
    held = LOCAL_FSD_UI_SETTINGS.intersection(explicit) if refresh else set()
    return {name: value for name, value in values.items()
            if name not in car_config and (name not in sent or sent[name] != value or name in held)}


# Personal data a vehicle dump can carry: account logins, PINs, keys, device and network
# identifiers, and places. Never imported, stored or written, whatever its prefix.
PRIVATE = re.compile(
    r'(?i:password|passcode|username|secret|token$|cert|privatekey|publickey|key$|pin$|imei|iccid|imsi'
    r'|serialnumber|macaddress|address$|ssid|psk|email|accountid|profilename|placehistory|location$'
    r'|contacts$|callhistory|phonebook)'
    r'|(Lat|Lon|Latitude|Longitude)$')
# Live hardware state: listed for reference but never written, even under a setting prefix.
# Another car's readings drive the display power state machine (it power-cycles).
LIVE = re.compile(r'^POWER_|DeviceState$')


def private(name):
    return bool(PRIVATE.search(name))


def live(name):
    return bool(LIVE.search(name))


def unsupported_car(values, single_display):
    """Why these values cannot be used on this layout, or ''. The S/X layout has no Model 3 interface."""
    if str(values.get('VAPI_carType')) in ('Model3', 'ModelY') and not single_display:
        return 'This is a Model 3/Y configuration. This firmware image has only the Model S/X interface, so it cannot be imported.'
    if single_display and str(values.get('VAPI_carType')) in ('ModelS', 'ModelS2', 'ModelX'):
        return 'This is a Model S/X configuration. This firmware image uses the Model 3 interface, so it cannot be imported.'
    return ''


PROFILE = Path(__file__).parent / 'runtime' / 'vehicle-profile-model-x-mcu2.json'
MODEL3_PROFILE = PROFILE.with_name('vehicle-profile-model-3-mcu2.json')
MODELY_PROFILE = PROFILE.with_name('vehicle-profile-model-y-mcu2.json')


def profile_path(single_display=False, car=None):
    """The base vehicle profile; `car` (the saved VAPI_carType) picks Model Y on the Model 3/Y layout."""
    if single_display:
        return MODELY_PROFILE if car == 'ModelY' else MODEL3_PROFILE
    return PROFILE


@lru_cache(maxsize=2)
def profile_defaults(single_display=False):
    """The app's own defaults: the values the vehicle profile writes on every display start."""
    try:
        signals = json.loads(profile_path(single_display).read_text()).get('signals', {})
    except (OSError, ValueError, AttributeError):
        return {}
    return {name: str(value).lower() if isinstance(value, bool) else str(value) for name, value in signals.items()}


def parse(text, defaults=None, withheld=None):
    """Return (rows, invalid, duplicates) from Name,Value CSV text.

    Rows whose value is @invalid carry no usable setting and are not imported;
    `invalid` lists their names. A name that repeats is kept once, at its first
    position, with its last value; `duplicates` lists (name, replaced, kept).
    A name the app has a default for (`defaults`) is compared against it: the
    row holds the CSV value, and differs from its default until it is applied.
    Any other name is new, so it is pending (`applied` None) until applied.
    Personal values (`private`) are dropped; their names are added to `withheld`
    when a list is given. Live hardware state (`live`) is listed but never queued.
    """
    defaults = defaults or {}
    rows, skipped, duplicates, seen = [], [], [], {}
    for record in csv.reader(io.StringIO(text.lstrip('﻿'))):
        if len(record) < 2 or not record[0].strip():
            continue
        if record[0].strip().lower() == 'name' and record[1].strip().lower() == 'value':
            continue  # a header, including one repeated where dumps were joined
        if record[1] == INVALID:
            skipped.append(record[0].strip())
            continue
        name = record[0].strip()
        if private(name):
            if withheld is not None and name not in withheld: withheld.append(name)
            continue
        if name in seen:
            row = rows[seen[name]]
            duplicates.append((name, row['value'], record[1]))
            row['value'] = record[1]
            if name not in defaults: row['original'] = record[1]
            if row['applied'] is not None and name not in defaults:
                # A listed-only row (live telemetry such as POWER_*) is never queued, repeated or not.
                row['applied'] = record[1]
            continue
        seen[name] = len(rows)
        known = name in defaults
        queued = known or (prefix(name) in SETTING_PREFIXES and not live(name))
        rows.append({'name': name, 'value': record[1], 'original': defaults[name] if known else record[1],
                     'applied': defaults[name] if known else None if queued else record[1]})
    return rows, skipped, duplicates


def car_config(learned=(), single_display=False):
    """Names the firmware restarts its UI for, so they are applied at start rather than live."""
    return set(profile_defaults(single_display)) | CAR_CONFIG_EXTRA | set(learned)


def coerce(value, name='', single_display=False):
    """Type a CSV string for the display bus: bool, int, float or str."""
    text = value.strip()
    # ICE/MRB enum labels can themselves be numbers: chassis '3' is ordinal 2,
    # while ordinal 3 is Model Y. Battery trim '74' is also a label, not ordinal 74.
    if single_display and ((name == 'VAPI_chassisType' and text == '3') or
                           (name == 'VAPI_trim' and text in ('50', '62', '74'))):
        return text
    if text.lower() in ('true', 'false'):
        return text.lower() == 'true'
    for cast in (int, float):
        try:
            number = cast(text)
        except ValueError:
            continue
        if cast is float and number != number or number in (float('inf'), float('-inf')):
            break
        return float(number) if cast is int and not -2**31 <= number < 2**31 else number
    return value


def prefix(name):
    return name.split('_', 1)[0] if '_' in name else ''


NAME = r'[A-Za-z][A-Za-z0-9_]{0,127}'


def is_changed(row):
    return row['value'] != row['original'] or bool(row.get('added'))


def default_rows(defaults):
    """Exactly the keys of the app's default file, at their default values."""
    return [{'name': name, 'value': value, 'original': value, 'applied': value} for name, value in defaults.items()]


def matches(row, query='', changed_only=False):
    if changed_only and not is_changed(row): return False
    query = query.strip().lower()
    return not query or query in row['name'].lower() or query in row['value'].lower()


def pending(rows):
    return sum(row['value'] != row['applied'] for row in rows)


def export(rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(('Name', 'Value'))
    writer.writerows((row['name'], row['value']) for row in rows)
    return out.getvalue()
