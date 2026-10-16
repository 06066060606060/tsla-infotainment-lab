"""Continuous selective echo of observed OS Ethernet records to the local gateway."""
import fcntl
import socket
import time
import uuid
from pathlib import Path

from core import atomic_json, load_json
import native_dbc

DESTINATION = ('127.0.0.102', 4321)
MAX_RULES = 16


def change_config(state, payload):
    """Serialize GUI edits and wait for the observer's applied-state readback."""
    state = Path(state)
    status = load_json(state / 'native-traffic.json', {})
    phase = load_json(state / 'status.json', {}).get('phase')
    if phase in ('stopped', 'failed') or time.time() - status.get('updated_at', 0) > 5:
        raise ValueError('Start or restart the device before configuring frame injection.')
    with (state / 'native-injection.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = load_json(state / 'native-injection-config.json', {'rules': []})
        rules = config['rules']
        operation = payload.get('operation')
        key = payload.get('key')
        if operation == 'save':
            identifier, edits = payload.get('identifier'), payload.get('edits')
            name = payload.get('name', '')
            name = name.strip() if isinstance(name, str) else ''
            if type(identifier) is not int or not 0 <= identifier <= 0x7ff:
                raise ValueError('Select an observed standard Ethernet message.')
            if not name or len(name) > 80 or not isinstance(edits, dict) or not 1 <= len(edits) <= 64:
                raise ValueError('Enter a rule name and select 1–64 signal overrides.')
            if any(not isinstance(k, str) or len(k) > 160 or
                   not isinstance(v, (str, int, float)) or isinstance(v, bool) or len(str(v)) > 160
                   for k, v in edits.items()):
                raise ValueError('Invalid signal override.')
            if key and not any(r['key'] == key for r in rules):
                raise ValueError('The selected rule no longer exists.')
            key = key or uuid.uuid4().hex
            rules = [r for r in rules if r['key'] != key]
            if len(rules) >= MAX_RULES:
                raise ValueError(f'At most {MAX_RULES} injection rules are supported.')
            # Saving an edit always leaves the rule disabled until explicitly enabled.
            rules.append({'key': key, 'name': name, 'identifier': identifier,
                          'edits': edits, 'enabled': False})
        elif operation in ('enable', 'disable', 'delete'):
            if not any(r['key'] == key for r in rules):
                raise ValueError('Select an existing rule first.')
            if operation == 'delete':
                rules = [r for r in rules if r['key'] != key]
            else:
                for rule in rules:
                    if rule['key'] == key:
                        rule['enabled'] = operation == 'enable'
        elif operation == 'stop':
            for rule in rules:
                rule['enabled'] = False
        else:
            raise ValueError('Unknown frame injection operation.')
        revision = uuid.uuid4().hex
        atomic_json(state / 'native-injection-config.json', {'revision': revision, 'rules': rules,
                    'operation': operation, 'key': key})
        # Hold the edit lock through acknowledgement so another panel cannot
        # overwrite the revision before it has been read back.
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            result = load_json(state / 'native-traffic.json', {}).get('injection', {})
            if result.get('revision') == revision:
                selected = next((r for r in result.get('rules', []) if r['key'] == key), {})
                error = selected.get('error') if operation in ('save', 'enable') else ''
                return dict(result, error=error or '', injection=True)
            time.sleep(.05)
        raise RuntimeError('The observer did not acknowledge the rule change. Refresh its applied state.')


class InjectionEngine:
    """Lives in the observer, which is not preloaded with the capture adapter.

    Only successful OS sends trigger echoes. API copies and our own socket
    writes never enter this path; each incoming event is processed just once.
    """
    def __init__(self, state, sender=None):
        self.state = Path(state)
        self.socket = sender or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        self.rules, self.revision, self.token = [], None, None
        self.definitions, self.metadata = {}, {}
        with (self.state / 'native-injection.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            config = load_json(self.state / 'native-injection-config.json', {'rules': []})
            for rule in config['rules']:
                rule['enabled'] = False
            config['revision'] = uuid.uuid4().hex
            atomic_json(self.state / 'native-injection-config.json', config)

    def update(self, definitions, metadata, latest, token):
        if token != self.token:
            for rule in self.rules:
                rule['enabled'] = False
                rule['error'] = 'DBC changed; save and enable the rule again.'
            self.token = token
        self.definitions, self.metadata = definitions, metadata
        config = load_json(self.state / 'native-injection-config.json', {})
        if config.get('revision') == self.revision:
            return
        old = {r['key']: r for r in self.rules}
        self.rules = []
        for entry in config.get('rules', [])[:MAX_RULES]:
            rule = dict(entry)
            previous = old.get(rule['key'], {})
            if previous and not previous['enabled'] and not (
                    config.get('operation') == 'enable' and config.get('key') == rule['key']):
                rule['enabled'] = False
            rule.update(echoes=previous.get('echoes', 0), skipped=previous.get('skipped', 0),
                        last_data=previous.get('last_data', ''), last_source=previous.get('last_source', ''),
                        last_sequence=previous.get('last_sequence'), error='')
            identifier = rule['identifier']
            rule['message'] = metadata.get(identifier, {}).get('name', '')
            try:
                self.edited(rule, latest[identifier])
            except (KeyError, ValueError) as exc:
                rule['enabled'] = False
                rule['error'] = str(exc) if isinstance(exc, ValueError) else 'A matching OS network frame and DBC definition are required.'
            self.rules.append(rule)
        self.revision = config.get('revision')

    def edited(self, rule, data):
        ident = rule['identifier']
        return native_dbc.patch(self.definitions[ident], data, rule['edits'], self.metadata[ident])

    def observe(self, kind, identifier, data, port, sequence):
        if kind != 1 or port != DESTINATION[1] or identifier is None:
            return
        for rule in self.rules:
            if not rule['enabled'] or rule['identifier'] != identifier:
                continue
            try:
                edited = self.edited(rule, data)
                record = ((len(edited) << 11) | identifier).to_bytes(2, 'big') + edited.ljust(8, b'\0')
                if self.socket.sendto(record, DESTINATION) != len(record):
                    raise OSError('Incomplete local UDP send')
                rule['echoes'] += 1
                rule['last_data'], rule['last_source'] = edited.hex(' ').upper(), data.hex(' ').upper()
                rule['last_sequence'], rule['error'] = sequence, ''
            except (OSError, KeyError, ValueError) as exc:
                rule['skipped'] += 1
                rule['error'] = str(exc)

    def snapshot(self):
        return {'revision': self.revision, 'rules': self.rules,
                'destination': f'{DESTINATION[0]}:{DESTINATION[1]}',
                'notice': 'Local Gateway Ethernet echo only. UDP send does not prove receipt by the OS or a physical CAN bus. '
                          'Unselected bits, counters and checksums are preserved; no checksum is recalculated.'}

    def close(self):
        for rule in self.rules:
            rule['enabled'] = False
        self.socket.close()
