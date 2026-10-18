"""Answer display setting requests that no vehicle module answers in the lab.

On a vehicle the center display writes a ``GUI_<name>Request`` DataValue and a
vehicle module reports the result on a status value the UI binds to. In the lab
nothing answers, so a setting such as an acceleration mode snaps back or shows
nothing. The router watches request names found in the firmware and, when one
changes, writes the accepted value to its status counterparts on the same
display, then reads them back. Routes are either explicit (``request-routes.json``
in the session) or paired by name with status values the display exposes.

It also parses ``dbus-monitor`` error lines, so D-Bus calls the firmware makes to
services the lab does not provide are listed instead of silently dropped.
No vendor protocol, token or value table is embedded here.
"""
from __future__ import annotations

import json
import mmap
import re
import threading
from pathlib import Path

from vehicle_services import decode_value, equivalent

REQUEST_PATTERN = re.compile(rb'(?<![A-Za-z0-9_])GUI_[A-Za-z0-9_]{2,80}Request(?![A-Za-z0-9_])')
SIGNAL_PATTERN = re.compile(rb'(?<![A-Za-z0-9_])(?:VAPI|GUI|LIGHT)_[A-Za-z][A-Za-z0-9_]{2,80}(?![A-Za-z0-9_])')
# Related names that describe the car or a fault, not the setting's state. Writing
# a configuration name would make the firmware restart its UI.
NOT_STATUS = re.compile(r'Request$|Present|Type$|Config|Installed|Available|Capab|Allowed|Supported|'
                        r'Visible|Fault|Error|Enabled$|Req$|Cmd$|Command')
SCAN_LIMIT = 512 * 1024 * 1024


def scan_request_names(ui: Path) -> tuple[list[str], list[str]]:
    """Return the ``GUI_*Request`` names and other DataValue names the firmware UI binaries reference."""
    files = [ui / 'bin/QtCar', *sorted((ui / 'lib').glob('libQtCar*.so*'))]
    names = set()
    for path in files:
        try:
            if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= SCAN_LIMIT:
                continue
            with path.open('rb') as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
                names.update(match.decode() for match in SIGNAL_PATTERN.findall(data))
        except (OSError, ValueError):
            continue
    requests = sorted(name for name in names if REQUEST_PATTERN.fullmatch(name.encode()))
    return requests, sorted(names.difference(requests))


def status_candidates(request: str, known=()) -> list[str]:
    """Status names a request is paired with when no explicit route exists.

    Fixed name patterns first, then firmware names containing the request's stem
    (``GUI_frontFogRequest`` -> ``VAPI_frontFogLights``, ``LIGHT_frontFogLeft``).
    """
    if not (request.startswith('GUI_') and request.endswith('Request')):
        return []
    stem = request[4:-7]
    if not stem:
        return []
    upper = stem[0].upper() + stem[1:]
    fixed = [f'VAPI_{stem}', f'VAPI_{stem}Status', f'VAPI_{stem}State', f'GUI_{stem}',
             f'GUI_{stem}Status', f'GUI_{stem}State', f'VAPI_is{upper}', f'VAPI_{stem}Active']
    if len(stem) < 4:
        return fixed
    related = sorted((name for name in known if stem.lower() in name.lower()
                      and name not in fixed and not NOT_STATUS.search(name)), key=lambda name: (len(name), name))
    return fixed + related[:8]  # ponytail: first 8 by length; an explicit route covers the rest


def converted(value, current):
    """The request value in the status value's kind, or None when they do not pair.

    Flags also pair with On/Off lamp states (``LIGHT_*``). Otherwise only a status
    of the request's kind (flag, number or name) is paired.
    """
    if current is None:
        return value
    if isinstance(value, bool) and current in ('On', 'Off'):
        return 'On' if value else 'Off'
    kind = lambda item: bool if isinstance(item, bool) else float if isinstance(item, (int, float)) else str
    return value if kind(value) is kind(current) else None


def load_routes(path: Path) -> dict:
    """Read user routes: ``{"GUI_xRequest": {"status": [...], "values": {...}}}``.

    ``null`` for a request disables it. ``values`` maps a request value (as text)
    to the status value; unmapped values are copied. Invalid entries are skipped.
    """
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    routes = {}
    for name, route in raw.items() if isinstance(raw, dict) else ():
        if not isinstance(name, str) or not REQUEST_PATTERN.fullmatch(name.encode()):
            continue
        if route is None:
            routes[name] = None
            continue
        if not isinstance(route, dict):
            continue
        status = route.get('status', [])
        values = route.get('values', {})
        if isinstance(status, str):
            status = [status]
        if not isinstance(status, list) or not all(isinstance(item, str) for item in status):
            continue
        if not isinstance(values, dict):
            continue
        routes[name] = {'status': status, 'values': {str(k): v for k, v in values.items()}}
    return routes


def status_value(value):
    """A whole number read back as text is written as an integer."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


class RequestRouter:
    """Accept center-display requests into status values, once per change."""
    def __init__(self, watched=(), routes=None, accepted=None, excluded=(), known=()):
        self.watched = set(watched)
        self.known = set(known)  # other firmware DataValue names, for pairing
        self.routes = dict(routes or {})
        self.excluded = set(excluded)
        self.accepted = dict(accepted or {})  # request -> {name: value} last written
        self.baseline = {}
        self.report = {}
        self.log = []
        self.cursor = 0  # next window start when polling with a limit

    def names(self):
        names = (self.watched | {name for name, route in self.routes.items() if route}) - self.excluded
        return sorted(name for name in names if self.routes.get(name, True) is not None)

    def targets(self, request, writer, value):
        """Map each status name to the value it should hold for this request."""
        route = self.routes.get(request)
        if route:
            wanted = status_value(route['values'].get(str(value), value))
            return {name: wanted for name in route['status'] if name not in self.excluded}
        candidates = [name for name in status_candidates(request, self.known) if name not in self.excluded]
        found = writer.read_many(candidates)
        result = {}
        for name in candidates:
            ok, current = found[name]
            wanted = converted(value, current) if ok else None
            if wanted is not None:
                result[name] = status_value(wanted)
        return result

    def restore(self, writer, now=0.0):
        """Write the accepted values again after a display (re)starts."""
        self.baseline = {}
        values = {}
        for request, statuses in self.accepted.items():
            if request in self.excluded or self.routes.get(request, True) is None:
                continue
            values.update(statuses)
        if values:
            report, details = writer.apply({'restore': values})
            self.report['restore'] = details['restore']
        return values

    def poll(self, writer, now=0.0, limit=None):
        """Read the watched names, or with ``limit`` the next window of that many,
        so a large watch list does not hold the display's GUI thread in one go."""
        names = self.names()
        if not names:
            return {}
        if limit and len(names) > limit:
            start = self.cursor % len(names)
            names = (names + names)[start:start + limit]
            self.cursor = start + limit
        accepted = {}
        for request, (ok, value) in writer.read_many(names).items():
            if not ok or value is None:
                continue
            previous = self.baseline.get(request)
            self.baseline[request] = value
            if previous is None or equivalent(previous, value):
                continue  # a value present before connecting is not a new request
            statuses = self.targets(request, writer, value)
            targets = list(statuses)
            details = writer.apply({request: statuses})[1][request] if statuses else {}
            outcome = ('unrouted' if not targets else 'accepted' if set(details.values()) == {'accepted'}
                       else 'partial' if 'accepted' in details.values() else 'rejected')
            if outcome in ('accepted', 'partial'):
                self.accepted[request] = {request: status_value(value),
                                          **{name: statuses[name] for name, result in details.items() if result == 'accepted'}}
            else:
                self.accepted.pop(request, None)
            entry = {'value': value, 'status': details, 'result': outcome}
            refused = [name for name, result in details.items() if result != 'accepted']
            if refused:  # what the display holds instead names the value it expects
                entry['read_back'] = {name: reading[1] for name, reading in writer.read_many(refused).items()}
            if outcome == 'unrouted':
                entry['related'] = [name for name in status_candidates(request, self.known)[8:]]
            self.report[request] = entry
            self.log = (self.log + [{'at': now, 'request': request, **entry}])[-50:]
            accepted[request] = statuses
        return accepted

    def as_dict(self):
        return {'watched': len(self.names()), 'requests': self.report, 'log': self.log,
                'accepted': self.accepted}


ERROR_LINE = re.compile(r'^error\b.*\berror_name=(\S+)')
UNKNOWN_SERVICE = re.compile(r'''name ['"]?([A-Za-z0-9_.:-]+?)['"]?(?: was not provided|: no such name)''')
UNKNOWN_METHOD = re.compile(r'''method ['"]?([^'" ]+)['"]?.*interface ['"]?([^'" ]+)['"]?''', re.I)


class DroppedCalls:
    """Count D-Bus errors from ``dbus-monitor`` output by service or method."""
    INTERESTING = ('org.freedesktop.DBus.Error.ServiceUnknown', 'org.freedesktop.DBus.Error.UnknownMethod',
                   'org.freedesktop.DBus.Error.UnknownObject', 'org.freedesktop.DBus.Error.UnknownInterface',
                   'org.freedesktop.DBus.Error.NameHasNoOwner')

    def __init__(self):
        self.pending = None
        self.counts = {}
        self.lock = threading.Lock()

    def snapshot(self):
        with self.lock:
            return {key: dict(entry) for key, entry in self.counts.items()}

    def feed(self, line, now=0.0):
        with self.lock:
            return self._feed(line, now)

    def _feed(self, line, now):
        match = ERROR_LINE.match(line)
        if match:
            self.pending = match.group(1) if match.group(1) in self.INTERESTING else None
            return None
        if self.pending is None or not line.strip().startswith('string '):
            return None
        text, error = line.strip()[7:].strip('"'), self.pending
        self.pending = None
        service = UNKNOWN_SERVICE.search(text)
        method = UNKNOWN_METHOD.search(text)
        key = (service.group(1) if service else f'{method.group(2)}.{method.group(1)}' if method else text[:160])
        entry = self.counts.setdefault(key, {'error': error.rsplit('.', 1)[-1], 'count': 0,
                                             'first_at': now, 'message': text[:240]})
        entry['count'] += 1
        entry['last_at'] = now
        return key
