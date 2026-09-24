"""Run the firmware Service Mode backend in a private network namespace.

The backend aborts unless it can bind the center display's vehicle-network
address. Adding that address to the host would capture traffic for a real
192.168.90.x network, so the backend gets its own namespace instead (created
by `unshare --map-current-user --keep-caps -n`, no root). Its HTTP port is
relayed to the host through a Unix socket in the session directory. With
ENGINE_SOCKET, the namespace's Odin engine port (127.0.0.1:8080) is relayed
the other way, to the lab's engine stand-in (odin-engine.py).

  ns   mode: service-ui-netns.py ns   SOCKET PORT [ENGINE_SOCKET] -- BACKEND ARGV...
  host mode: service-ui-netns.py host SOCKET PORT
"""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading

CENTER_ADDRESS = '192.168.90.100/32'
ENGINE_PORT = 8080


def pipe(source, target):
    try:
        while data := source.recv(65536):
            target.sendall(data)
    except OSError:
        pass
    finally:
        for sock in (source, target):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def splice(client, connect):
    try:
        upstream = connect()
    except OSError:
        client.close()
        return
    threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
    threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()


def serve(listener, connect):
    """Accept forever; each connection is spliced to a fresh upstream."""
    while True:
        client, _ = listener.accept()
        splice(client, connect)


def unix_listener(path: Path):
    path.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    os.chmod(path, 0o600)
    listener.listen(32)
    return listener


def tcp_listener(port: int):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', port))
    listener.listen(32)
    return listener


def connect_tcp(port):
    def connect():
        sock = socket.create_connection(('127.0.0.1', port), timeout=5)
        sock.settimeout(None)  # the timeout is for connecting; idle websockets stay open
        return sock
    return connect


def connect_unix(path):
    def connect():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(path))
        return sock
    return connect


def namespace(path: Path, port: int, argv: list, engine: Path | None = None) -> int:
    for command in (['ip', 'link', 'set', 'lo', 'up'], ['ip', 'addr', 'add', CENTER_ADDRESS, 'dev', 'lo']):
        subprocess.run(command, check=True)
    threading.Thread(target=serve, args=(unix_listener(path), connect_tcp(port)), daemon=True).start()
    if engine:
        threading.Thread(target=serve, args=(tcp_listener(ENGINE_PORT), connect_unix(engine)), daemon=True).start()
    # Namespace capabilities were only needed for the address; the backend runs without them.
    # If this wrapper is killed outright, the kernel stops the backend with it.
    backend = subprocess.Popen(['setpriv', '--inh-caps=-all', '--ambient-caps=-all', '--pdeathsig=KILL', *argv])
    signal.signal(signal.SIGTERM, lambda *_: backend.terminate())
    code = backend.wait()
    path.unlink(missing_ok=True)
    return code


def host(path: Path, port: int) -> int:
    serve(tcp_listener(port), connect_unix(path))
    return 0


def main(args):
    mode, path, port = args[0], Path(args[1]), int(args[2])
    if mode == 'ns':
        split = args.index('--')
        return namespace(path, port, args[split + 1:], Path(args[3]) if split > 3 else None)
    return host(path, port)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
