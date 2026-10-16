"""DBC decoding and selective edits of observed packets, independent of LAB_* frames."""
from pathlib import Path
import re
from decimal import Decimal, InvalidOperation, localcontext

from can_frames import _extract, _insert

HEADER = re.compile(r'^\s*BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)')
SIGNAL = re.compile(r'^\s*SG_\s+(\w+)(?:\s+(M|m\d+M?))?\s*:\s*(\d+)\|(\d+)@([01])([+-])'
                    r'\s*\(([-+\d.eE]+),\s*([-+\d.eE]+)\)\s*\[[^]]*\]\s*"([^"]*)"')
VALUES = re.compile(r'^\s*VAL_\s+(\d+)\s+(\w+)\s+(.+);')
MULTIPLEX = re.compile(r'^\s*SG_MUL_VAL_\s+(\d+)\s+(\w+)\s+(\w+)\s+(.+);')


def load(path):
    path = Path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('The observation DBC must be smaller than 32 MiB.')
    text = path.read_text(encoding='utf-8-sig', errors='replace')
    messages, current, enum, multiplex = {}, None, [], []
    for line in text.splitlines():
        if match := HEADER.match(line):
            ident, name, length = match.groups()
            identifier = int(ident) & 0x1fffffff
            if identifier in messages:
                raise ValueError('The DBC contains duplicate message identifiers.')
            current = {'id': identifier, 'name': name, 'length': int(length), 'signals': []}
            messages[identifier] = current
        elif match := SIGNAL.match(line):
            if current is None:
                continue
            name, mux, start, bits, endian, sign, factor, offset, unit = match.groups()
            if not 1 <= int(bits) <= 64:
                continue
            current['signals'].append({'name': name, 'mux': mux or '', 'start': int(start),
                'bits': int(bits), 'little': endian == '1', 'signed': sign == '-',
                'factor': float(factor), 'offset': float(offset), 'unit': unit, 'choices': {}, 'selectors': {}})
        elif match := VALUES.match(line):
            enum.append(match.groups())
        elif match := MULTIPLEX.match(line):
            multiplex.append(match.groups())
    if not messages:
        raise ValueError('No message definitions were found in the DBC.')
    for ident, name, entries in enum:
        message = messages.get(int(ident) & 0x1fffffff, {})
        for field in message.get('signals', []):
            if field['name'] == name:
                field['choices'] = {int(v): label for v, label in re.findall(r'(-?\d+)\s+"([^"]*)"', entries)}
    for ident, name, selector, ranges in multiplex:
        for field in messages.get(int(ident) & 0x1fffffff, {}).get('signals', []):
            if field['name'] == name:
                field['selectors'][selector] = [(int(a), int(b)) for a, b in re.findall(r'(\d+)\s*-\s*(\d+)', ranges)]
    for message in messages.values():
        fields = message['signals']
        selectors = [f['name'] for f in fields if f['mux'] == 'M']
        for field in fields:
            if field['mux'].startswith('m') and not field['selectors']:
                if len(selectors) == 1:
                    value = int(field['mux'][1:].rstrip('M'))
                    field['selectors'][selectors[0]] = [(value, value)]
                else:
                    field['unsupported'] = 'Multiplexor definition missing'
            positions = []
            pos = field['start']
            for _ in range(field['bits']):
                positions.append(pos)
                pos = pos + 1 if field['little'] else (pos - 1 if pos % 8 else pos + 15)
            field['positions'] = set(positions)
            if max(positions) >= message['length'] * 8:
                field['unsupported'] = 'Signal exceeds declared length'
        # An incomplete reverse-engineered DBC can omit multiplex conditions.
        # Refuse ambiguous fields rather than showing several meanings at once.
        plain = [f for f in fields if not f['mux'] and not f['selectors']]
        for n, field in enumerate(plain):
            for other in plain[n + 1:]:
                if field['positions'] & other['positions']:
                    field['unsupported'] = other['unsupported'] = 'Overlapping fields without multiplexing'
    return messages


def decode(message, payload, metadata=None):
    if len(payload) != message['length']:
        return [], 'Payload length differs from the DBC definition'
    fields = {f['name']: f for f in message['signals']}
    raw, active = {}, {}
    for name, field in fields.items():
        value = _extract(payload, field['start'], field['bits'], field['little'])
        if field['signed'] and value & (1 << (field['bits'] - 1)):
            value -= 1 << field['bits']
        raw[name] = value

    def enabled(name, seen=()):
        if name in active:
            return active[name]
        field = fields.get(name)
        if not field or field.get('unsupported') or name in seen:
            return False
        valid = all(enabled(selector, (*seen, name)) and
                    any(low <= raw[selector] <= high for low, high in ranges)
                    for selector, ranges in field['selectors'].items())
        active[name] = valid
        return valid

    native = {s['name']: s for s in (metadata or {}).get('signals', [])}
    result = []
    for name, field in fields.items():
        if not enabled(name):
            continue
        if metadata and name not in native:
            continue
        choices = field['choices']
        if name in native and native[name]['choices']:
            choices = {int(k): v for k, v in native[name]['choices'].items() if v}
        numeric = raw[name] if field['factor'] == 1 and field['offset'] == 0 else raw[name] * field['factor'] + field['offset']
        result.append({'signal': name, 'value': choices.get(raw[name], numeric),
                       'raw': raw[name], 'unit': native.get(name, {}).get('unit') or field['unit']})
    skipped = sum(bool(f.get('unsupported')) for f in fields.values())
    return result, f'{skipped} ambiguous or unsupported signals omitted' if skipped else ''


def patch(message, payload, changes, metadata):
    """Copy a received payload and change only unambiguous, active signal bits.

    Numbers use physical DBC units; enumeration labels use the native catalogue.
    Counters and checksums are preserved unless explicitly selected for editing.
    """
    if not isinstance(changes, dict) or not changes:
        raise ValueError('Select at least one signal override.')
    if message['name'] != metadata['name']:
        raise ValueError('The DBC message differs from the running firmware.')
    decoded, _ = decode(message, payload, metadata)
    active = {v['signal'] for v in decoded}
    fields = {f['name']: f for f in message['signals']}
    native = {s['name']: s for s in metadata['signals']}
    result = bytearray(payload)
    for name, value in changes.items():
        if name not in active:
            raise ValueError(f'{name}: signal is inactive, ambiguous or unavailable in this frame.')
        field = fields[name]
        # Refuse overlapping active fields even if an incomplete DBC claims mux support.
        if any(other != name and fields[other]['positions'] & field['positions'] for other in active):
            raise ValueError(f'{name}: overlapping active signal fields.')
        choices = {int(k): v for k, v in native[name].get('choices', {}).items() if v}
        choices = choices or field['choices']
        labels = [raw for raw, label in choices.items() if label == value]
        if len(labels) > 1:
            raise ValueError(f'{name}: ambiguous enumeration label; enter a numeric value.')
        try:
            with localcontext() as context:
                context.prec = 80  # preserve full 64-bit integer edits
                raw_float = (Decimal(labels[0]) if labels else
                             (Decimal(str(value)) - Decimal(str(field['offset']))) / Decimal(str(field['factor'])))
                if isinstance(value, bool) or not raw_float.is_finite():
                    raise ValueError()
                raw = round(raw_float)
        except (TypeError, ValueError, OverflowError, ZeroDivisionError, InvalidOperation) as exc:
            raise ValueError(f'{name}: enter a finite number or an enumeration label.') from exc
        low = -(1 << (field['bits'] - 1)) if field['signed'] else 0
        high = (1 << (field['bits'] - (1 if field['signed'] else 0))) - 1
        if not low <= raw <= high or abs(raw_float - raw) > Decimal('0.0000001'):
            raise ValueError(f'{name}: value is outside the signal range or resolution.')
        _insert(result, field['start'], field['bits'], field['little'], raw & ((1 << field['bits']) - 1))
    edited, _ = decode(message, bytes(result), metadata)
    if not changes.keys() <= {v['signal'] for v in edited}:
        raise ValueError('The edited multiplexor makes an overridden signal inactive.')
    return bytes(result)
