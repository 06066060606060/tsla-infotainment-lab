"""Observe OS gateway traffic and apply explicitly enabled local echo rules."""
from collections import deque
import json
import os
from pathlib import Path
import signal
import socket
import struct
import time

from core import atomic_json, load_json
import native_catalog
import native_dbc
from native_injection import InjectionEngine

HEADER = struct.Struct('=4sBQ4sHH')
MAX_PACKET = 4096
HISTORY = 256


def unpack(payload):
    if len(payload) < HEADER.size:
        raise ValueError('Truncated observation packet.')
    magic, kind, stamp, ip, port, size = HEADER.unpack_from(payload)
    data = payload[HEADER.size:]
    if magic != b'NTR2' or kind not in (1, 2) or not 0 < size <= MAX_PACKET or len(data) != size or ip != b'\x7f\0\0\x66':
        raise ValueError('Invalid observation packet.')
    return kind, stamp, port, data


def gateway_records(data):
    """The observed Model 3 sender packs fixed ten-byte Ethernet records.

    Its big-endian header holds an 11-bit message number and a payload length.
    This is the ETH catalogue's number space; no physical CAN bus is encoded.
    """
    records = []
    if len(data) % 10:
        return []
    for offset in range(0, len(data), 10):
        word = int.from_bytes(data[offset:offset + 2], 'big')
        length = word >> 11
        if length > 8:
            return []
        records.append((word & 0x7ff, data[offset + 2:offset + 2 + length]))
    return records


def snapshot(state):
    state = Path(state)
    result = load_json(state / 'native-traffic.json', {})
    if not isinstance(result, dict):
        result = {}
    phase = load_json(state / 'status.json', {}).get('phase')
    if phase in ('stopped', 'failed') or time.time() - result.get('updated_at', 0) > 5:
        return {'state': 'stopped', 'frames': [], 'notice': 'Start or restart the device to observe its OS traffic.'}
    (state / 'native-traffic-viewer').touch()
    return result


def set_dbc(state, path):
    path = Path(path).expanduser().resolve(strict=True)
    messages = native_dbc.load(path)
    atomic_json(Path(state) / 'native-traffic-config.json', {'dbc': str(path)})
    return {'dbc': str(path), 'messages': len(messages)}


def run():
    state, firmware = Path(os.environ['TESLA_NATIVE_STATE']), Path(os.environ['TESLA_FIRMWARE'])
    path = state / 'native-traffic.sock'
    # The supervisor owns this private session directory and its process tree.
    path.unlink(missing_ok=True)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    sock.bind(str(path))
    path.chmod(0o600)
    sock.settimeout(.1)
    try:
        catalogue = native_catalog.extract(firmware / 'usr/tesla/UI/lib/libQtCarCANData.so')
        atomic_json(state / 'native-can-catalog.json', {'messages': catalogue})
        metadata = {m['id']: m for m in catalogue if m['bus'] == 'ETH'}
        catalog_error = ''
    except (OSError, ValueError, UnicodeError, KeyError, IndexError) as exc:
        catalogue, metadata, catalog_error = [], {}, str(exc)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    frames = deque(maxlen=HISTORY)
    sequence = rejected = datagrams = unparsed = 0
    started = time.monotonic_ns()
    published = 0
    dbc_path, dbc_stamp, definitions, dbc_error = '', None, {}, ''
    injection = InjectionEngine(state)
    latest = {}
    try:
        while not stopping:
            try:
                payload, ancillary, flags, address = sock.recvmsg(HEADER.size + MAX_PACKET, socket.CMSG_SPACE(12))
                creds = next((struct.unpack('3i', value) for level, kind, value in ancillary
                              if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS), None)
                if not creds or creds[1] != os.getuid() or flags & socket.MSG_TRUNC:
                    raise ValueError('Untrusted or truncated observation.')
                kind, stamp, port, raw = unpack(payload)
                datagrams += 1
                records = gateway_records(raw)
                if not records:
                    unparsed += 1
                    records = [(None, raw)]
                for identifier, data in records:
                    sequence += 1
                    if kind == 1 and port == 4321 and identifier is not None:
                        latest[identifier] = data
                    injection.observe(kind, identifier, data, port, sequence)
                    message = metadata.get(identifier, {})
                    frames.append({'sequence': sequence, 'timestamp_ms': max(0, (stamp - started) // 1000000),
                        'bus': 'gateway', 'transport': 'Ethernet' if kind == 1 else 'Gateway API',
                        'direction': 'TX' if kind == 1 else 'TX request', 'pid': creds[0],
                        'id': identifier, 'id_hex': f'0x{identifier:03X}' if identifier is not None else '',
                        'extended': None, 'rtr': None, 'length': len(data), 'data': data.hex(' ').upper(),
                        'message': message.get('name', 'Unknown gateway message'),
                        'signals': [], 'decode_note': '', 'port': port})
            except socket.timeout:
                pass
            except ValueError:
                rejected += 1
            now = time.monotonic()
            if now - published < .5:
                continue
            config = load_json(state / 'native-traffic-config.json', {})
            selected = config.get('dbc', '') if isinstance(config, dict) else ''
            try:
                stamp = (selected, Path(selected).stat().st_mtime_ns) if selected else None
                if stamp != dbc_stamp:
                    definitions = native_dbc.load(selected) if selected else {}
                    dbc_path, dbc_stamp, dbc_error = selected, stamp, ''
                    frames.clear()  # never show old values under a newly selected definition
            except (OSError, ValueError) as exc:
                definitions, dbc_path, dbc_stamp, dbc_error = {}, selected, None, str(exc)
            injection.update(definitions, metadata, latest, dbc_stamp)
            try:
                viewed = time.time() - (state / 'native-traffic-viewer').stat().st_mtime < 5
            except OSError:
                viewed = False
            visible = []
            if viewed:
                for frame in frames:
                    frame = dict(frame)
                    message, definition = metadata.get(frame['id']), definitions.get(frame['id'])
                    if definition and message and definition['name'] == message['name']:
                        frame['signals'], frame['decode_note'] = native_dbc.decode(
                            definition, bytes.fromhex(frame['data']), message)
                    elif definition and message:
                        frame['decode_note'] = 'DBC message name differs from the selected firmware'
                    visible.append(frame)
            atomic_json(state / 'native-traffic.json', {
                'state': 'observing', 'updated_at': time.time(), 'started_monotonic_ns': started,
                'frames': visible, 'datagrams': datagrams, 'records': sequence,
                'rejected': rejected, 'unparsed': unparsed,
                'catalog_messages': len(catalogue), 'catalog_signals': sum(len(m['signals']) for m in catalogue),
                'catalog_buses': sorted(set(m['bus'] for m in catalogue)), 'catalog_error': catalog_error,
                'dbc': dbc_path, 'dbc_messages': len(definitions), 'dbc_error': dbc_error,
                'injection': injection.snapshot(),
                'emitter': load_json(state / 'native-vehicle-status.json', {}),
                'notice': 'Observed OS gateway calls; TX request does not confirm a socket send or CAN delivery. '
                          'ETH message numbers do not identify Party, Chassis or Body.'})
            published = now
    finally:
        injection.close()
        sock.close()
        path.unlink(missing_ok=True)


if __name__ == '__main__':
    run()
