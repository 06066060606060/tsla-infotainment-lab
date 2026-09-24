"""Stand-in for the vehicle's Odin diagnostic engine, for the firmware Service Mode panel.

The firmware service-ui backend talks to the engine two ways: D-Bus calls to
com.tesla.Odin /Odin (list tasks, execute, running tasks) and a websocket on
127.0.0.1:8080 inside its network namespace, which service-ui-netns.py relays to
this Unix socket. Results of both are sent back over that websocket.

Catalogue requests are answered from the firmware image's own files (task list,
gateway config names, maintenance options). Executing a task always reports that
no vehicle is attached: this talks to no vehicle, runs no diagnostics and
implements no authentication or security access.

  odin-engine.py SOCKET ODIN_DIR
"""
import base64
import hashlib
import json
from pathlib import Path
import socket
import struct
import sys
import threading
import time

WS_GUID = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
NO_VEHICLE = 'Infotainment Lab: no vehicle is attached, so Odin tasks cannot run.'


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
class Engine:
    def __init__(self, odin: Path):
        self.odin = odin
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

    def no_vehicle(self, request_id, reason='NO_VEHICLE'):
        # Exit code 2 is what the panel's result dialog shows as "Routine Error", with this message.
        # (service-ui does not forward request_failed to the page, so errors are finished requests too.)
        output = {'exit_code': 2, 'exit_reason': reason, 'user_facing_msg': NO_VEHICLE, 'data': []}
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
        self.later(self.no_vehicle, request_id)
        return True

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


def dbus_service(engine: Engine):
    """com.tesla.Odin on the session's private bus (the lab's system bus)."""
    import dbus
    import dbus.service

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
    name = dbus.service.BusName('com.tesla.Odin', bus, do_not_queue=True)
    return name, Odin(bus, '/Odin')


def main(args):
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    engine = Engine(Path(args[1]))
    DBusGMainLoop(set_as_default=True)
    service = dbus_service(engine)  # noqa: F841 - keeps the name owned
    threading.Thread(target=engine.listen, args=(Path(args[0]),), daemon=True).start()
    log(f'Odin engine stand-in: {len(engine.tasks)} tasks, listening on {args[0]}')
    GLib.MainLoop().run()


if __name__ == '__main__':
    main(sys.argv[1:])
