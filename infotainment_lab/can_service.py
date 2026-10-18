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
import can_profiles
from core import atomic_json
from can_bus import backend_report, open_bus
from can_frames import Frame
from gateway import DEFAULT_ENDPOINT, DEFAULT_ROUTES, EthernetBridge, SecurityGateway, database_routes
from replay import manual_takeover
from simulation import Simulation
from vehicle_can import (INBOUND, PeriodicTransmitter, controls_patch, database_patches,
                         snapshot, state_patch)
from vehicle_services import VehicleServices

SOCKET_NAME = "can-gateway.sock"
FEEDBACK = "vehicle-services-feedback.json"
# The lock state keep-awake mirrors onto the displays' gateway signals.
GATEWAY_LOCK = "gateway-lock.json"
SERVICE_REVISION = 7  # Bump whenever the service protocol or behaviour changes.
TICK_S = .005
ACTIONS = frozenset(("status", "send", "trace", "challenge", "unlock", "lock",
                     "state", "snapshot", "load-dbc", "stop"))


def socket_path(state: Path) -> Path:
    return Path(state) / SOCKET_NAME


class GatewayService:
    def __init__(self, state: Path, *, prefer="auto", create=False, endpoint=DEFAULT_ENDPOINT,
                 secret: bytes | None = None, profile: str = "lab", databases: Path | None = None):
        self.state = Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.profile = profile
        channels = can_profiles.profile(profile)["channels"]
        messages = (can_database.MESSAGES if profile == "lab"
                    else can_profiles.definitions(profile, databases or self.state.parent / "can-databases"))
        self.bus = open_bus(channels, prefer=prefer, create=create)
        routes = tuple(r for r in DEFAULT_ROUTES if {r.source, r.destination} <= {*channels, "eth"})
        if profile != "lab":
            routes += database_routes(messages, channels)
        self.gateway = SecurityGateway(self.bus, routes=routes, secret=secret, messages=messages)
        self.bridge = EthernetBridge(self.gateway, endpoint) if endpoint else None
        self.transmitter = PeriodicTransmitter(messages=tuple(self.gateway.table.values()))
        self.simulation = Simulation()
        self.services = VehicleServices()
        self.transmit = True
        self.running = True
        self.applied: list[dict] = []
        # The desktop session owns the state the displays receive. Follow its
        # files so a trace always matches the screen, including during replay.
        # keep-awake's feedback carries changes made on the displays themselves
        # (Service Mode entry, native climate), which never reach the desktop file.
        self.sources = {'controls.json': 0, 'vehicle-services.json': 0, FEEDBACK: 0}
        self.follow_session = True
        self._lock_published: tuple | None = None
        self.lock = threading.Lock()
        self.bus.subscribe(self._feedback)

    # -- state feedback ---------------------------------------------------
    def _feedback(self, frame: Frame, origin: str = "send") -> None:
        """Accepted inbound requests update local state, the same as the UI would.

        Frames this service transmits from its own state are ignored: reading
        them back would fight the session, and a drive frame would take
        ownership away from replay on every tick.
        """
        if origin == "periodic":
            return
        definition = can_database.lookup(frame.channel, frame.identifier, self.gateway.table, frame.extended)
        if not definition:
            return
        decoded = definition.decode(frame)
        if definition.name in INBOUND:
            self._apply_controls(definition.name, controls_patch(definition.name, decoded))
            self._apply_services(definition.name, state_patch(definition.name, decoded))
        elif not definition.name.startswith("LAB_"):
            controls, services = database_patches(definition, decoded)
            self._apply_controls(definition.name, controls)
            self._apply_services(definition.name, services)

    def _apply_services(self, name: str, patch: dict) -> None:
        if not patch:
            return
        try:
            with self.lock:
                self.services = self.services.patched(patch)
                self.applied.append({"frame": name, "patch": patch, "at": time.time()})
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
                    elif name == FEEDBACK:
                        # Only a report built on the current desktop file: an older
                        # one would undo a change made since, until the next report.
                        if value.get('config_mtime_ns') == self._config_stamp():
                            self.services = VehicleServices.parse(value['state'])
                    else:
                        self.services = VehicleServices.parse(value)
            except (OSError, ValueError, KeyError, AttributeError, json.JSONDecodeError):
                continue  # A half-written or unrelated file must not stop the bus.
        self.gateway.service_mode = self.services.service_mode

    def _config_stamp(self) -> int | None:
        try:
            return (self.state / 'vehicle-services.json').stat().st_mtime_ns
        except OSError:
            return None

    def _apply_controls(self, name: str, patch: dict) -> None:
        """Move the driving inputs the displays read, taking over from replay."""
        if not patch:
            return
        try:
            with self.lock:
                updated = Simulation.parse(self.simulation.as_dict() | patch)
                if updated == self.simulation:
                    return
                self.simulation = updated
                self.applied.append({"frame": name, "controls": patch, "at": time.time()})
                del self.applied[:-50]
                if not self.follow_session:
                    return
                # controls.json is what the displays read. Release replay
                # ownership the same way a manual control does.
                manual_takeover(self.state, updated.as_dict())
                path = self.state / "controls.json"
                try:
                    self.sources["controls.json"] = path.stat().st_mtime_ns
                except OSError:
                    pass
        except (ValueError, OSError):
            self.gateway.counts["blocked"] += 1

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
                    definition = can_database.lookup(name, item["id"], self.gateway.table, item["extended"])
                    if definition:
                        item = dict(item, name=definition.name,
                                    signals={k: (round(v, 3) if isinstance(v, float) else v)
                                             for k, v in definition.decode(
                                                 Frame(item["id"], bytes.fromhex(item["data"].replace(" ", "")), name,
                                                       item["extended"])).items()})
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
                self.gateway.service_mode = self.services.service_mode
                return {"simulation": self.simulation.as_dict(),
                        "vehicle_services": self.services.as_dict(), "transmit": self.transmit,
                        "follow_session": self.follow_session}
        if action == "snapshot":
            with self.lock:
                return {"frames": snapshot(self.simulation, self.services, self.transmitter.messages)}
        if action == "load-dbc":
            path = Path(request.get("path", "")).expanduser()
            channel = request.get("channel", self.bus.channels and next(iter(self.bus.channels)))
            self.bus.channel(channel)  # Refuse a channel this profile does not open.
            messages = can_database.load(path, channel, int(request.get("period_ms", 0)))
            self.gateway.table.update(can_database.index(messages))
            self.transmitter.messages = tuple(self.gateway.table.values())
            self.gateway.routes += database_routes(messages, (channel,))
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
        return {"service": "running", "revision": SERVICE_REVISION, "profile": self.profile,
                "channels": list(self.bus.channels),
                "environment": backend_report(),
                "bridge": {"endpoint": list(self.bridge.endpoint), "peers": len(self.bridge.peers)} if self.bridge else {},
                "definitions": [{"name": m.name, "channel": m.channel, "id": f"0x{m.identifier:03X}",
                                 "period_ms": m.period_ms, "signals": [s.name for s in m.signals]}
                                for m in self.gateway.table.values()],
                "gateway": self.gateway.status(), **local}

    def publish_lock(self) -> None:
        """Write the gateway's unlock state where keep-awake mirrors it to the displays.

        Only the desktop session's files reach the displays, so the CAN service
        cannot set a data value itself. It records the lock state and lets
        keep-awake project it onto the firmware's gateway signals. The file is
        rewritten only when the state changes (an unlock, a lock, or expiry), so
        the always-running loop does not churn it; the absolute expiry time lets
        keep-awake keep the countdown current on its own.
        """
        if not self.follow_session:
            return
        status = self.gateway.status()
        unlocked = bool(status.get("unlocked"))
        expires_at = float(status.get("unlock_expires_at") or 0.0)
        published = (unlocked, round(expires_at), bool(self.gateway.service_mode))
        if published == self._lock_published:
            return
        self._lock_published = published
        atomic_json(self.state / GATEWAY_LOCK, {
            "unlocked": unlocked, "unlock_expires_at": expires_at,
            "service_mode": bool(self.gateway.service_mode), "updated_at": time.time()})

    # -- loop -------------------------------------------------------------
    def step(self) -> None:
        self.refresh_from_session()
        self.publish_lock()
        self.bus.poll(0)
        if self.bridge:
            self.bridge.service(0)
        if self.transmit:
            with self.lock:
                sim, services = self.simulation, self.services
            for frame in self.transmitter.tick(sim, services):
                self.bus.send(frame, "periodic")

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
    parser.add_argument("--profile", choices=tuple(can_profiles.PROFILES), default="lab")
    parser.add_argument("--databases", help="Directory holding the downloaded public databases.")
    args = parser.parse_args(argv)
    service = GatewayService(Path(args.state), prefer=args.backend, create=args.create_interfaces,
                             endpoint=None if args.no_bridge else ("127.0.0.1", args.bridge_port),
                             profile=args.profile, databases=Path(args.databases) if args.databases else None)
    print(json.dumps({"ok": True, "data": {"listening": str(socket_path(Path(args.state))),
                                           "backend": service.bus.backend}}), flush=True)
    service.serve()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
