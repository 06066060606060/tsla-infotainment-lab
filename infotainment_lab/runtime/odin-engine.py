"""Stand-in for the vehicle's Odin diagnostic engine, for the firmware Service Mode panel.

The firmware service-ui backend talks to the engine two ways: D-Bus calls to
com.tesla.Odin /Odin (list tasks, execute, running tasks) and a websocket on
127.0.0.1:8080 inside its network namespace, which service-ui-netns.py relays to
this Unix socket. Results of both are sent back over that websocket.

Catalogue requests are answered from the firmware image's own files (task list,
gateway config names, maintenance options). Executing a task always reports that
no vehicle is attached: this talks to no vehicle, runs no diagnostics and
implements no authentication or security access.

When the lab's CAN service is running, each task is first offered to its
emulated gateway as a LAB_gatewayRequest on the party channel, the path a
diagnostic request takes. The gateway only passes it while unlocked and in
Service Mode, and the result names what it decided. No ECU answers it.

It also serves com.tesla.Debug /Debug, the text data-value interface QtCarServer
provides on a car (the lab does not run QtCarServer). The panel sets
GUI_serviceMode through it, e.g. to leave Service Mode.

  odin-engine.py SOCKET ODIN_DIR
"""
import base64
import binascii
import hashlib
import json
from pathlib import Path
import socket
import struct
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vehicle_services import decode_value

WS_GUID = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
NO_VEHICLE = 'Infotainment Lab: no vehicle is attached, so Odin tasks cannot run.'
# LAB_gatewayRequest payload: a lab-defined "run task" code, then the task name's CRC-32.
TASK_REQUEST = 0x31


def log(*parts):
    print(time.strftime('%H:%M:%S'), *parts, flush=True)


# ---------------------------------------------------------------- minimal HTTP / WebSocket
def read_request(stream):
    lines = []
    while (line := stream.readline(65536)) not in (b'\r\n', b'\n', b''):
        lines.append(line.decode('latin-1').rstrip('\r\n'))
    if not lines:
        raise ConnectionError('empty request')
    method, target, _ = lines[0].split(' ', 2)
    headers = {k.strip().lower(): v.strip() for k, v in (l.split(':', 1) for l in lines[1:] if ':' in l)}
    return method, target, headers, stream.read(int(headers.get('content-length') or 0))


def http_response(status: str, body) -> bytes:
    data = json.dumps(body).encode()
    return (f'HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n'
            'Connection: close\r\n\r\n').encode() + data


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1(key.encode() + WS_GUID).digest()).decode()


def ws_frame(data: bytes, opcode=0x1) -> bytes:
    n = len(data)
    if n < 126:
        size = bytes([n])
    elif n < 65536:
        size = bytes([126]) + struct.pack('!H', n)
    else:
        size = bytes([127]) + struct.pack('!Q', n)
    return bytes([0x80 | opcode]) + size + data


def ws_read(stream):
    """One complete message as (opcode, bytes); continuation frames are joined."""
    payload, first = b'', None
    while True:
        head = stream.read(2)
        if len(head) < 2:
            raise ConnectionError('websocket closed')
        n = head[1] & 0x7f
        if n == 126:
            n = struct.unpack('!H', stream.read(2))[0]
        elif n == 127:
            n = struct.unpack('!Q', stream.read(8))[0]
        mask = stream.read(4) if head[1] & 0x80 else b'\0\0\0\0'
        data = bytes(c ^ mask[i % 4] for i, c in enumerate(stream.read(n)))
        opcode = head[0] & 0x0f
        if opcode >= 0x8:  # control frames may arrive between fragments
            return opcode, data
        first = opcode if first is None else first
        payload += data
        if head[0] & 0x80:
            return first, payload


# ---------------------------------------------------------------- engine
def task_frame(task: str) -> dict:
    data = bytes([TASK_REQUEST]) + binascii.crc32(task.encode()).to_bytes(4, 'big') + bytes(3)
    return {'channel': 'party', 'id': '0x641', 'data': data.hex()}


def gateway_outcome(send, task: str) -> tuple[str, str]:
    """(exit reason, message) for a task offered to the lab gateway through `send`."""
    try:
        decision = send({'action': 'send', 'origin': 'ethernet', 'frame': task_frame(task)})
    except (RuntimeError, OSError, ValueError) as exc:
        if 'not running' in str(exc):
            return 'NO_VEHICLE', NO_VEHICLE + ' Start the CAN service to route tasks through the lab gateway.'
        return 'GATEWAY_UNAVAILABLE', f'Infotainment Lab: the lab gateway did not answer ({exc}).'
    if not decision.get('allowed'):
        return 'GATEWAY_REFUSED', (f"Infotainment Lab: the lab gateway refused the request: {decision.get('reason')}. "
                                   'Unlock it under CAN & gateway and stay in Service Mode.')
    return 'NO_ECU', ('Infotainment Lab: the request crossed the lab gateway onto the party channel, '
                      'but no vehicle ECU is attached to answer it.')


class Engine:
    def __init__(self, odin: Path, gateway=None):
        self.odin = odin
        self.gateway = gateway  # send(request) to the lab CAN service, or None
        self.tasks = json.loads((odin / 'odin_bundle/odin_bundle/networks/task_data.py').read_text())
        self.clients = {}  # socket -> send lock
        self.lock = threading.Lock()

    def maintenance(self, locale='en'):
        folder = self.odin / 'core/engine/assets/json'
        for name in (locale.replace('-', '_'), locale.split('-')[0].split('_')[0], 'en'):
            path = folder / f'maintenance_history_{name}.json'
            if path.is_file():
                return json.loads(path.read_text())
        return []

    def gateway_configs(self):
        # The names are the firmware's gateway-config allowlist; the values live on a vehicle's
        # gateway and are not in the image, so every value is a clearly marked placeholder.
        path = self.odin / 'core/engine/assets/whitelist/rmi-gtw-config-allowlist.yaml'
        names = [l[2:].strip() for l in path.read_text().splitlines() if l.startswith('- ')] if path.is_file() else []
        configs = {}
        for index, name in enumerate(names):
            options = ['NO', 'YES'] if name.endswith(('installed', 'ok')) else ['DEFAULT', 'OPTION_1', 'OPTION_2']
            configs[name] = {'description': f'{name} (simulated, no gateway attached)', 'current_value': options[0],
                             'is_editable': False, 'accessId': 1000 + index,
                             'content': {'enums': [{'codeKey': o, 'value': v, 'description': o}
                                                   for v, o in enumerate(options)]}}
        return configs

    # -- replies travel over every connected engine websocket, as on the vehicle
    def broadcast(self, message: dict):
        frame = ws_frame(json.dumps(message).encode())
        with self.lock:
            clients = list(self.clients.items())
        for sock, send_lock in clients:
            try:
                with send_lock:
                    sock.sendall(frame)
            except OSError:
                pass

    def finish(self, request_id, response):
        self.broadcast({'message_type': 'request_finished', 'request_id': request_id, 'response': response})

    def no_vehicle(self, request_id, reason='NO_VEHICLE', message=NO_VEHICLE):
        # Exit code 2 is what the panel's result dialog shows as "Routine Error", with this message.
        # (service-ui does not forward request_failed to the page, so errors are finished requests too.)
        output = {'exit_code': 2, 'exit_reason': reason, 'user_facing_msg': message, 'data': []}
        self.finish(request_id, {'exit_code': 2, 'service_output': output})

    def later(self, action, *args):
        """Reply after the D-Bus call has returned, as the engine does."""
        threading.Timer(0.05, action, args).start()

    # -- D-Bus methods
    def list_tasks(self, request_id, locale):
        log('list tasks', request_id, locale)
        self.later(self.finish, request_id, self.tasks)
        return True

    def execute(self, task, params, request_id, locale):
        log('execute', task, request_id, params[:200])
        self.later(self.run, task, request_id)
        return True

    def run(self, task, request_id):
        if self.gateway is None:
            self.no_vehicle(request_id)
            return
        reason, message = gateway_outcome(self.gateway, task)
        log('gateway', task, reason)
        self.no_vehicle(request_id, reason, message)

    # -- websocket commands
    def command(self, message: dict):
        command, request_id = message.get('command'), message.get('request_id')
        log('command', command, request_id)
        replies = {'list_configs': self.gateway_configs, 'read_service_history': list,
                   'read_maintenance_history_options': self.maintenance}
        if command in replies:
            self.finish(request_id, replies[command]())
        else:
            self.no_vehicle(request_id, f'UNSUPPORTED_{str(command).upper()}')

    def http(self, method, target):
        log('http', method, target)
        path = target.split('?', 1)[0]
        known = {'/api/v1/running_tasks': {}, '/api/v1/task_history': [], '/api/v1/query_task_history': [],
                 '/api/v1/get_update_map': {}}
        return ('200 OK', known[path]) if path in known else ('404 Not Found', {})

    # -- connections
    def serve_client(self, sock):
        stream = sock.makefile('rb')
        try:
            method, target, headers, _ = read_request(stream)
            if headers.get('upgrade', '').lower() != 'websocket':
                sock.sendall(http_response(*self.http(method, target)))
                return
            sock.sendall(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                          f'Sec-WebSocket-Accept: {accept_key(headers["sec-websocket-key"])}\r\n\r\n').encode())
            send_lock = threading.Lock()
            with self.lock:
                self.clients[sock] = send_lock
            log('websocket connected')
            while True:
                opcode, data = ws_read(stream)
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    with send_lock:
                        sock.sendall(ws_frame(data, 0xA))
                elif opcode == 0x1:
                    try:
                        message = json.loads(data)
                    except ValueError:
                        continue
                    if isinstance(message, dict):
                        self.command(message)
        except (OSError, ValueError, KeyError) as exc:
            log('connection ended:', exc)
        finally:
            with self.lock:
                self.clients.pop(sock, None)
            sock.close()

    def listen(self, path: Path):
        path.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        path.chmod(0o600)
        listener.listen(16)
        while True:
            sock, _ = listener.accept()
            threading.Thread(target=self.serve_client, args=(sock,), daemon=True).start()


# ---------------------------------------------------------------- com.tesla.Debug
def set_if(read, write, name, value, if_it_matches, unless_it_matches):
    """QtCarServer's guarded write: an empty guard is ignored, a failed one skips the write."""
    if if_it_matches or unless_it_matches:
        ok, current = read(name)
        current = current if ok else ''
        if (if_it_matches and current != if_it_matches) or (unless_it_matches and current == unless_it_matches):
            return False
    return write(name, value)


def dump(read, names, fmt, show_invalid):
    """(mime type, body): name=value lines, or a JSON object when fmt is 'json'."""
    values = {}
    for name in names:
        ok, value = read(name)
        valid = ok and value not in ('', '<invalid>')
        if valid or show_invalid:
            values[name] = value if valid else '<invalid>'
    if fmt == 'json':
        return 'application/json', json.dumps(values, indent=1, sort_keys=True)
    return 'text/plain', ''.join(f'{name}={value}\n' for name, value in sorted(values.items()))


def dbus_service(engine: Engine, state: Path):
    """com.tesla.Odin and com.tesla.Debug on the session's private bus (the lab's system bus)."""
    import dbus
    import dbus.service

    def values(service):
        return dbus.Interface(dbus.SessionBus().get_object(service, '/LocalDataValue', introspect=False),
                              'com.tesla.LocalDataValue')

    def reader(service):
        def read(name):
            ok, value = values(service).DataGetValueRequest(name, timeout=1)
            return bool(ok), str(value)
        return read

    def write(name, text):
        value = decode_value(text)
        variant = (dbus.Boolean(value, variant_level=1) if isinstance(value, bool)
                   else dbus.Double(value, variant_level=1) if isinstance(value, float)
                   else dbus.String(text, variant_level=1))
        return bool(values('com.tesla.CenterDisplay').DataSetValueRequest(name, variant, timeout=1))

    class Debug(dbus.service.Object):
        # Single values go to the center display, so a write reaches the lab's model
        # exactly as a touch there does (keep-awake follows the display).
        @dbus.service.method('com.tesla.Debug', in_signature='s', out_signature='bs')
        def get_data_value(self, name):
            return reader('com.tesla.CenterDisplay')(str(name))

        # The full listing is read from QtCarDvServer's store: ~3k reads would hold
        # the center's GUI thread for seconds. No metadata is available here.
        @dbus.service.method('com.tesla.Debug', in_signature='sbb', out_signature='ss')
        def get_data_values(self, fmt, show_invalid, show_metadata):
            try:
                names = json.loads((state / 'display-request-names.json').read_text())['known']
            except (OSError, ValueError, KeyError):
                names = []
            return dump(reader('com.tesla.DvServer'), names, str(fmt), bool(show_invalid))

        @dbus.service.method('com.tesla.Debug', in_signature='ssss', out_signature='b')
        def set_data_value(self, name, value, if_it_matches, unless_it_matches):
            log('debug set', name, value)
            return set_if(reader('com.tesla.CenterDisplay'), write, str(name), str(value),
                          str(if_it_matches), str(unless_it_matches))

    class Odin(dbus.service.Object):
        @dbus.service.method('com.tesla.Odin', in_signature='', out_signature='a{ss}')
        def GetRunningTasks(self):
            return {}

        @dbus.service.method('com.tesla.Odin', in_signature='ssbs', out_signature='b')
        def ServiceUIListTask(self, request_id, token, include_non_executable, locale):
            return engine.list_tasks(str(request_id), str(locale))

        @dbus.service.method('com.tesla.Odin', in_signature='sssss', out_signature='b')
        def ServiceUIExecute(self, task, params, request_id, token, locale):
            return engine.execute(str(task), str(params), str(request_id), str(locale))

    bus = dbus.SessionBus()
    names = [dbus.service.BusName(name, bus, do_not_queue=True) for name in ('com.tesla.Odin', 'com.tesla.Debug')]
    return names, Odin(bus, '/Odin'), Debug(bus, '/Debug')


def main(args):
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    import can_service

    state = Path(args[0]).parent  # the session directory, where the CAN service listens
    engine = Engine(Path(args[1]), lambda request: can_service.request(state, request, timeout=2))
    DBusGMainLoop(set_as_default=True)
    service = dbus_service(engine, state)  # noqa: F841 - keeps the names owned
    threading.Thread(target=engine.listen, args=(Path(args[0]),), daemon=True).start()
    log(f'Odin engine stand-in: {len(engine.tasks)} tasks, listening on {args[0]}')
    GLib.MainLoop().run()


if __name__ == '__main__':
    main(sys.argv[1:])
