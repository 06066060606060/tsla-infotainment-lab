"""The CAN and gateway service: one loop, one private control socket.

The loop owns the transport, the emulated gateway, the periodic transmitter and
the Ethernet bridge. Everything else — the GUI, the Linux worker, the guest
helper — speaks to it through a Unix socket with one JSON request per
connection, the same shape the rest of the project already uses.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import sys
import threading
import time

import can_database
from core import atomic_json
from can_bus import backend_report, open_bus
from can_frames import Frame
from gateway import DEFAULT_ENDPOINT, EthernetBridge, SecurityGateway
from simulation import Simulation
from vehicle_can import INBOUND, PeriodicTransmitter, snapshot, state_patch
from vehicle_services import VehicleServices

SOCKET_NAME = "can-gateway.sock"
TICK_S = .005
ACTIONS = frozenset(("status", "send", "trace", "challenge", "unlock", "lock",
                     "state", "snapshot", "load-dbc", "stop"))


def socket_path(state: Path) -> Path:
    return Path(state) / SOCKET_NAME


class GatewayService:
    def __init__(self, state: Path, *, prefer="auto", create=False, endpoint=DEFAULT_ENDPOINT,
                 secret: bytes | None = None):
        self.state = Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.bus = open_bus(prefer=prefer, create=create)
        self.gateway = SecurityGateway(self.bus, secret=secret)
        self.bridge = EthernetBridge(self.gateway, endpoint) if endpoint else None
        self.transmitter = PeriodicTransmitter()
        self.simulation = Simulation()
        self.services = VehicleServices()
        self.transmit = True
        self.running = True
        self.applied: list[dict] = []
        # The desktop session owns the state the displays receive. Follow its
        # files so a trace always matches the screen, including during replay.
        self.sources = {'controls.json': 0, 'vehicle-services.json': 0}
        self.follow_session = True
        self.lock = threading.Lock()
        self.bus.subscribe(self._feedback)

    # -- state feedback ---------------------------------------------------
    def _feedback(self, frame: Frame) -> None:
        """Accepted inbound requests update local state, the same as the UI would."""
        definition = can_database.lookup(frame.channel, frame.identifier, self.gateway.table)
        if not definition or definition.name not in INBOUND:
            return
        patch = state_patch(definition.name, definition.decode(frame))
        if not patch:
            return
        try:
            with self.lock:
                self.services = self.services.patched(patch)
                self.applied.append({"frame": definition.name, "patch": patch, "at": time.time()})
                del self.applied[:-50]
                # Close the loop: the session file is what the displays read, so
                # an accepted request reaches the screen like a panel change.
                if self.follow_session:
                    path = self.state / 'vehicle-services.json'
                    atomic_json(path, self.services.as_dict())
                    try:
                        self.sources['vehicle-services.json'] = path.stat().st_mtime_ns
                    except OSError:
                        pass
        except ValueError:
            self.gateway.counts["blocked"] += 1

    def refresh_from_session(self) -> None:
        """Adopt the session's own state whenever one of its files changes."""
        if not self.follow_session:
            return
        for name in tuple(self.sources):
            path = self.state / name
            try:
                stamp = path.stat().st_mtime_ns
            except OSError:
                continue
            if stamp == self.sources[name]:
                continue
            self.sources[name] = stamp
            try:
                value = json.loads(path.read_text(encoding='utf-8'))
                with self.lock:
                    if name == 'controls.json':
                        self.simulation = Simulation.parse(value)
                    else:
                        self.services = VehicleServices.parse(value)
            except (OSError, ValueError, json.JSONDecodeError):
                continue  # A half-written or unrelated file must not stop the bus.

    # -- control ----------------------------------------------------------
    def handle(self, request: dict) -> dict:
        action = request.get("action", "status")
        if action not in ACTIONS:
            raise ValueError("Unknown CAN gateway action.")
        if action == "status":
            return self.status()
        if action == "send":
            frame = Frame.parse(request.get("frame", {}))
            origin = request.get("origin", "ethernet")
            if origin == "ethernet":
                return self.gateway.from_ethernet(frame).as_dict()
            if origin != "bus":
                raise ValueError("Origin must be ethernet or bus.")
            # A frame presented as if another ECU had produced it.
            return {"frame": self.bus.inject(frame).as_dict(), "route": "injected", "allowed": True}
        if action == "trace":
            channel = request.get("channel", "")
            names = [channel] if channel else list(self.bus.channels)
            limit = max(1, min(int(request.get("limit", 100)), 1000))
            since = float(request.get("since", 0))
            frames = []
            for name in names:
                for item in self.bus.channel(name).trace(limit, since):
                    definition = can_database.lookup(name, item["id"], self.gateway.table)
                    if definition:
                        item = dict(item, name=definition.name,
                                    signals={k: (round(v, 3) if isinstance(v, float) else v)
                                             for k, v in definition.decode(
                                                 Frame(item["id"], bytes.fromhex(item["data"].replace(" ", "")), name)).items()})
                    frames.append(item)
            frames.sort(key=lambda item: item["timestamp"])
            return {"frames": frames[-limit:], "now": time.time()}
        if action == "challenge":
            return {"challenge": self.gateway.challenge()}
        if action == "unlock":
            return self.gateway.unlock(request.get("response", ""))
        if action == "lock":
            return self.gateway.lock()
        if action == "state":
            with self.lock:
                if "simulation" in request:
                    self.simulation = Simulation.parse(request["simulation"])
                if "vehicle_services" in request:
                    self.services = self.services.patched(request["vehicle_services"])
                if 'follow_session' in request:
                    if type(request['follow_session']) is not bool:
                        raise ValueError('follow_session must be true or false.')
                    self.follow_session = request['follow_session']
                if "transmit" in request:
                    if type(request["transmit"]) is not bool:
                        raise ValueError("transmit must be true or false.")
                    self.transmit = request["transmit"]
                return {"simulation": self.simulation.as_dict(),
                        "vehicle_services": self.services.as_dict(), "transmit": self.transmit,
                        "follow_session": self.follow_session}
        if action == "snapshot":
            with self.lock:
                return {"frames": snapshot(self.simulation, self.services)}
        if action == "load-dbc":
            path = Path(request.get("path", "")).expanduser()
            messages = can_database.load_dbc(path, request.get("channel", "veh"),
                                             int(request.get("period_ms", 0)))
            self.gateway.table.update(can_database.index(messages))
            return {"loaded": [m.name for m in messages], "count": len(messages)}
        self.running = False
        return {"stopped": True}

    def status(self) -> dict:
        with self.lock:
            local = {"simulation": self.simulation.as_dict(),
                     "vehicle_services": self.services.as_dict(),
                     "transmit": self.transmit, "follow_session": self.follow_session,
                     "state_source": "session" if self.follow_session else "panel",
                     "recent_state_changes": self.applied[-5:]}
        return {"service": "running", "environment": backend_report(),
                "bridge": {"endpoint": list(self.bridge.endpoint), "peers": len(self.bridge.peers)} if self.bridge else {},
                "definitions": [{"name": m.name, "channel": m.channel, "id": f"0x{m.identifier:03X}",
                                 "period_ms": m.period_ms, "signals": [s.name for s in m.signals]}
                                for m in self.gateway.table.values()],
                "gateway": self.gateway.status(), **local}

    # -- loop -------------------------------------------------------------
    def step(self) -> None:
        self.refresh_from_session()
        self.bus.poll(0)
        if self.bridge:
            self.bridge.service(0)
        if self.transmit:
            with self.lock:
                sim, services = self.simulation, self.services
            for frame in self.transmitter.tick(sim, services):
                self.bus.send(frame)

    def serve(self) -> None:
        path = socket_path(self.state)
        if path.exists() or path.is_symlink():
            path.unlink()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        listener.listen(8)
        listener.settimeout(TICK_S)
        try:
            while self.running:
                self.step()
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    continue
                with connection:
                    connection.settimeout(2)
                    try:
                        payload = connection.recv(65536).decode("utf-8", "replace").strip()
                        reply = {"ok": True, "data": self.handle(json.loads(payload or "{}"))}
                    except Exception as exc:  # one bad request must not stop the bus
                        reply = {"ok": False, "error": str(exc)}
                    try:
                        connection.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode())
                    except OSError:
                        pass
        finally:
            if self.bridge:
                self.bridge.close()
            self.bus.close()
            listener.close()
            path.unlink(missing_ok=True)


def request(state: Path, payload: dict, timeout: float = 3) -> dict:
    """Call a running service. Raises if it is not listening."""
    path = socket_path(state)
    if not path.exists():
        raise RuntimeError("The CAN gateway service is not running. Start it from the CAN panel.")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall(json.dumps(payload).encode())
        chunks = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if chunks[-1].endswith(b"\n"):
                break
    reply = json.loads(b"".join(chunks).decode("utf-8", "replace") or "{}")
    if not reply.get("ok"):
        raise RuntimeError(reply.get("error", "The CAN gateway service refused the request."))
    return reply.get("data", {})


def running(state: Path) -> bool:
    try:
        request(state, {"action": "status"}, timeout=1)
        return True
    except (RuntimeError, OSError, ValueError):
        return False


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default=str(Path.home() / ".local/share/tsla-infotainment-lab/session"))
    parser.add_argument("--backend", choices=("auto", "socketcan", "software"), default="auto")
    parser.add_argument("--create-interfaces", action="store_true")
    parser.add_argument("--bridge-port", type=int, default=DEFAULT_ENDPOINT[1])
    parser.add_argument("--no-bridge", action="store_true")
    args = parser.parse_args(argv)
    service = GatewayService(Path(args.state), prefer=args.backend, create=args.create_interfaces,
                             endpoint=None if args.no_bridge else ("127.0.0.1", args.bridge_port))
    print(json.dumps({"ok": True, "data": {"listening": str(socket_path(Path(args.state))),
                                           "backend": service.bus.backend}}), flush=True)
    service.serve()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
