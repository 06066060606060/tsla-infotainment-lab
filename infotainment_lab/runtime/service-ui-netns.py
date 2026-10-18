"""Run the firmware Service Mode backend in a private network namespace.

The backend aborts unless it can bind the center display's vehicle-network
address. Adding that address to the host would capture traffic for a real
192.168.90.x network, so the backend gets its own namespace instead (created
by `unshare --map-current-user --keep-caps -n`, no root). Its HTTP port is
relayed to the host through a Unix socket in the session directory. With
ENGINE_SOCKET, the namespace's Odin engine port (127.0.0.1:8080) is relayed
the other way, to the lab's engine stand-in (odin-engine.py).

The firmware alert daemon (alertd) needs the same addresses but no relay: run
mode. Both backends also use fixed paths under root-owned directories
(/home/alertd, /var/log/udsdebug.log); --bind gives them a session file or
directory there, visible only in the namespace (add `-m` to unshare).

  ns   mode: service-ui-netns.py ns   SOCKET PORT [ENGINE_SOCKET] [--bind TARGET=SOURCE]... -- BACKEND ARGV...
  run  mode: service-ui-netns.py run  [--bind TARGET=SOURCE]... -- BACKEND ARGV...
  host mode: service-ui-netns.py host SOCKET PORT
"""
import ctypes
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading

# The backend also binds its CAN-over-Ethernet listener to the subnet broadcast
# address; without it that task panics at start.
ADDRESSES = ('192.168.90.100/32', '192.168.90.255/32')
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


MS_BIND, MS_REC = 0x1000, 0x4000


def mount(source: str, target: Path, fstype: str | None = None, flags: int = 0):
    # mount(8) refuses a non-root uid, and the namespace keeps the user's own uid.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.mount(source.encode(), str(target).encode(), fstype and fstype.encode(), flags, None):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


def bind_private(target: Path, source: Path):
    """Show SOURCE at TARGET in this mount namespace only. TARGET's parent becomes
    a tmpfs holding its previous entries, bound back, plus TARGET."""
    parent = target.parent
    # Open everything first: the source itself may live under the parent (/home).
    entries = {entry.name: (os.readlink(entry.path) if entry.is_symlink() else os.open(entry.path, os.O_PATH))
               for entry in os.scandir(parent) if entry.name != target.name}
    entries[target.name] = os.open(source, os.O_PATH)
    mount('tmpfs', parent, 'tmpfs')
    for name, kept in entries.items():
        path = parent / name
        if isinstance(kept, str):
            path.symlink_to(kept)
            continue
        if os.path.isdir(f'/proc/self/fd/{kept}'):
            path.mkdir(exist_ok=True)
        else:
            path.touch()
        mount(f'/proc/self/fd/{kept}', path, flags=MS_BIND | MS_REC)
        os.close(kept)


def namespace(path: Path | None, port: int | None, argv: list, engine: Path | None = None, binds=()) -> int:
    subprocess.run(['ip', 'link', 'set', 'lo', 'up'], check=True)
    for address in ADDRESSES:
        subprocess.run(['ip', 'addr', 'add', address, 'dev', 'lo'], check=True)
    for target, source in binds:
        bind_private(target, source)
    if path:
        threading.Thread(target=serve, args=(unix_listener(path), connect_tcp(port)), daemon=True).start()
    if engine:
        threading.Thread(target=serve, args=(tcp_listener(ENGINE_PORT), connect_unix(engine)), daemon=True).start()
    # Namespace capabilities were only needed for the address; the backend runs without them.
    # If this wrapper is killed outright, the kernel stops the backend with it.
    backend = subprocess.Popen(['setpriv', '--inh-caps=-all', '--ambient-caps=-all', '--pdeathsig=KILL', *argv])
    signal.signal(signal.SIGTERM, lambda *_: backend.terminate())
    code = backend.wait()
    if path:
        path.unlink(missing_ok=True)
    return code


def host(path: Path, port: int) -> int:
    serve(tcp_listener(port), connect_unix(path))
    return 0


def main(args):
    mode = args[0]
    if mode == 'host':
        return host(Path(args[1]), int(args[2]))
    split = args.index('--')
    head, binds = [], []
    options = iter(args[1:split])
    for arg in options:
        if arg == '--bind':
            target, source = next(options).split('=', 1)
            binds.append((Path(target), Path(source)))
        else:
            head.append(arg)
    if mode == 'run':
        return namespace(None, None, args[split + 1:], binds=binds)
    return namespace(Path(head[0]), int(head[1]), args[split + 1:], Path(head[2]) if len(head) > 2 else None, binds)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
