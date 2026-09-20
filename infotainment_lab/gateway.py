"""Emulation of a vehicle gateway MCU: channel routing, filtering and an
Ethernet-to-CAN bridge for the local infotainment session.

What this models
---------------
A gateway sits between several CAN channels and the infotainment Ethernet link.
Traffic does not flow freely: each direction is an explicit route with an
identifier allowlist, and writes arriving from the Ethernet side are refused
unless the session has been unlocked.

What this is not
----------------
It is not a Tesla gateway, does not implement any vehicle authentication scheme,
and contains no vendor keys, certificates or protocol. The unlock below is a
local lab handshake over a shared secret the operator chooses, so that
"locked by default" behaviour can be exercised end to end. Frames it emits are
lab definitions (see can_database) and never evidence about a real vehicle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
import secrets
import socket
import threading
import time

import can_database
from can_bus import Filter, open_bus
from can_frames import Frame

WIRE = 12  # channel byte, 4-byte identifier, length byte, up to 8 data bytes... see pack_wire.
DEFAULT_ENDPOINT = ("127.0.0.1", 20200)
UNLOCK_TTL_S = 300
RATE_LIMIT_PER_S = 400


def pack_wire(frame: Frame, channels: tuple[str, ...]) -> bytes:
    """Bridge framing: index, flags, identifier, length, payload. Local only."""
    index = channels.index(frame.channel)
    header = bytes([index, 1 if frame.extended else 0]) + frame.identifier.to_bytes(4, "big") + bytes([frame.length])
    return header + frame.data


def unpack_wire(payload: bytes, channels: tuple[str, ...]) -> Frame:
    if len(payload) < 7:
        raise ValueError("Truncated bridge message.")
    index, flags = payload[0], payload[1]
    identifier = int.from_bytes(payload[2:6], "big")
    length = payload[6]
    if index >= len(channels):
        raise ValueError("Bridge message names an unknown channel.")
    if length > 8 or len(payload) < 7 + length:
        raise ValueError("Bridge message length does not match its payload.")
    return Frame(identifier, payload[7:7 + length], channels[index], bool(flags & 1))


@dataclass(frozen=True)
class Route:
    """One permitted direction. An empty filter list forwards nothing."""
    name: str
    source: str
    destination: str
    filters: tuple[Filter, ...] = ()
    requires_unlock: bool = False
    description: str = ""

    def accepts(self, frame: Frame) -> bool:
        return any(rule.matches(frame) for rule in self.filters)


def allow(*identifiers: int, mask: int = 0x7FF) -> tuple[Filter, ...]:
    return tuple(Filter(identifier, mask) for identifier in identifiers)


# Read paths are open; anything that reaches a vehicle channel is gated.
DEFAULT_ROUTES: tuple[Route, ...] = (
    Route("pt-to-eth", "pt", "eth", allow(0x118, 0x129),
          description="Drive state and steering to the infotainment session."),
    Route("veh-to-eth", "veh", "eth", allow(0x102, 0x2E5, 0x3D8, 0x3F5),
          description="Closures, climate, tyres and lighting to the display."),
    Route("ch-to-eth", "ch", "eth", allow(0x352),
          description="Energy and charging status to the display."),
    Route("eth-to-veh", "eth", "veh", allow(0x2E5, 0x3F5), requires_unlock=True,
          description="Climate and lighting requests from the display."),
    Route("eth-to-party", "eth", "party", allow(0x641), requires_unlock=True,
          description="Diagnostic requests on the isolated channel."),
    Route("party-to-eth", "party", "eth", allow(0x651),
          description="Diagnostic responses back to the requester."),
    Route("veh-to-pt", "veh", "pt", allow(0x3F5),
          description="Lighting state mirrored onto the powertrain channel."),
)


@dataclass
class Decision:
    frame: Frame
    route: str
    allowed: bool
    reason: str = ""

    def as_dict(self) -> dict:
        return {"frame": self.frame.as_dict(), "route": self.route,
                "allowed": self.allowed, "reason": self.reason}


class SecurityGateway:
    """Route frames between channels and the Ethernet side, with an unlock gate."""

    def __init__(self, bus=None, routes=DEFAULT_ROUTES, secret: bytes | None = None,
                 messages=None, unlock_ttl_s: int = UNLOCK_TTL_S):
        self.bus = bus if bus is not None else open_bus()
        self.routes = tuple(routes)
        self.secret = secret if secret is not None else os.environ.get("LAB_GATEWAY_SECRET", "infotainment-lab").encode()
        self.table = can_database.index(messages) if messages is not None else dict(can_database.BY_ID)
        self.unlock_ttl_s = unlock_ttl_s
        self.channels = tuple(self.bus.channels)
        self.to_ethernet: list[Frame] = []
        self.rejected: list[Decision] = []
        self.counts = {"routed": 0, "blocked": 0, "unknown": 0, "rate_limited": 0}
        self._challenge: bytes | None = None
        self._unlocked_until = 0.0
        self._window_start = time.monotonic()
        self._window_count = 0
        self._lock = threading.RLock()  # re-entered when a routed send loops back through _on_bus_frame
        self.bus.subscribe(self._on_bus_frame)

    # -- session gate ----------------------------------------------------
    @property
    def unlocked(self) -> bool:
        return time.time() < self._unlocked_until

    def challenge(self) -> str:
        """Start one unlock attempt. A new challenge invalidates the previous one."""
        self._challenge = secrets.token_bytes(8)
        return self._challenge.hex()

    def expected_response(self, challenge: bytes) -> str:
        return hmac.new(self.secret, challenge, hashlib.sha256).hexdigest()[:32]

    def unlock(self, response: str) -> dict:
        if not self._challenge:
            raise PermissionError("Request a challenge before sending an unlock response.")
        challenge, self._challenge = self._challenge, None
        if not isinstance(response, str) or not hmac.compare_digest(response.strip().lower(),
                                                                   self.expected_response(challenge)):
            self._unlocked_until = 0
            raise PermissionError("The unlock response did not match this session's challenge.")
        self._unlocked_until = time.time() + self.unlock_ttl_s
        return {"unlocked": True, "expires_in_s": self.unlock_ttl_s}

    def lock(self) -> dict:
        self._challenge, self._unlocked_until = None, 0
        return {"unlocked": False}

    # -- routing ---------------------------------------------------------
    def routes_from(self, source: str) -> tuple[Route, ...]:
        return tuple(route for route in self.routes if route.source == source)

    def _rate_limited(self) -> bool:
        now = time.monotonic()
        if now - self._window_start >= 1:
            self._window_start, self._window_count = now, 0
        self._window_count += 1
        return self._window_count > RATE_LIMIT_PER_S

    def _record(self, decision: Decision) -> Decision:
        if decision.allowed:
            self.counts["routed"] += 1
        else:
            key = "rate_limited" if decision.reason.startswith("rate") else "unknown" if decision.route == "-" else "blocked"
            self.counts[key] += 1
            self.rejected.append(decision)
            del self.rejected[:-200]
        return decision

    def from_ethernet(self, frame: Frame) -> Decision:
        """Handle one frame offered by the infotainment session."""
        with self._lock:
            if self._rate_limited():
                return self._record(Decision(frame, "-", False, "rate limit for the Ethernet side exceeded"))
            candidates = [route for route in self.routes_from("eth") if route.destination == frame.channel]
            if not candidates:
                return self._record(Decision(frame, "-", False, f"no route from the Ethernet side to {frame.channel}"))
            for route in candidates:
                if not route.accepts(frame):
                    continue
                if route.requires_unlock and not self.unlocked:
                    return self._record(Decision(frame, route.name, False, "the gateway session is locked"))
                definition = self.table.get((frame.channel, frame.identifier))
                if definition and not definition.checksum_valid(frame):
                    return self._record(Decision(frame, route.name, False, "frame checksum is invalid"))
                self.bus.send(frame)
                return self._record(Decision(frame, route.name, True))
            return self._record(Decision(frame, candidates[0].name, False,
                                         f"identifier 0x{frame.identifier:03X} is not in the route filter"))

    def _on_bus_frame(self, frame: Frame, origin: str = "send") -> None:
        """Forward a channel frame to the Ethernet queue and any channel mirror."""
        for route in self.routes_from(frame.channel):
            if not route.accepts(frame):
                continue
            if route.destination == "eth":
                with self._lock:
                    self.to_ethernet.append(frame)
                    del self.to_ethernet[:-2048]
                self.counts["routed"] += 1
            elif route.destination != frame.channel:
                self.counts["routed"] += 1
                # A mirror carries the origin, so a periodic frame stays periodic.
                self.bus.send(Frame(frame.identifier, frame.data, route.destination,
                                    frame.extended), origin)

    def drain(self, limit: int = 256) -> list[Frame]:
        with self._lock:
            frames, self.to_ethernet = self.to_ethernet[:limit], self.to_ethernet[limit:]
        return frames

    def decode(self, frame: Frame) -> dict:
        definition = self.table.get((frame.channel, frame.identifier))
        if not definition:
            return {}
        return definition.decode(frame)

    def status(self) -> dict:
        return {"backend": self.bus.backend, "unlocked": self.unlocked,
                "unlock_expires_in_s": max(0, round(self._unlocked_until - time.time())),
                "channels": [self.bus.channel(name).stats() for name in self.channels],
                "routes": [{"name": r.name, "source": r.source, "destination": r.destination,
                            "identifiers": [f"0x{f.identifier:03X}" for f in r.filters],
                            "requires_unlock": r.requires_unlock, "description": r.description}
                           for r in self.routes],
                "counters": dict(self.counts),
                "pending_to_ethernet": len(self.to_ethernet),
                "recent_rejections": [d.as_dict() for d in self.rejected[-10:]]}


class EthernetBridge:
    """UDP endpoint standing in for the infotainment link, bound to the loopback.

    The socket never leaves 127.0.0.1: the bridge exists so the desktop session,
    a test, or an external tool on the same machine can exchange frames with the
    emulated gateway.
    """

    def __init__(self, gateway: SecurityGateway, endpoint=DEFAULT_ENDPOINT):
        host, port = endpoint
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("The Ethernet bridge only binds to the loopback interface.")
        self.gateway = gateway
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))
        self.socket.setblocking(False)
        self.endpoint = self.socket.getsockname()
        self.peers: set = set()

    def service(self, timeout: float = .01) -> dict:
        """Read pending datagrams, then push queued frames to known peers."""
        import select

        received = accepted = 0
        readable, _, _ = select.select([self.socket], [], [], timeout)
        while readable:
            try:
                payload, peer = self.socket.recvfrom(2048)
            except (BlockingIOError, InterruptedError):
                break
            received += 1
            self.peers.add(peer)
            try:
                if payload[:1] == b"{":
                    self._control(json.loads(payload.decode()), peer)
                    continue
                decision = self.gateway.from_ethernet(unpack_wire(payload, self.gateway.channels))
                accepted += int(decision.allowed)
                if not decision.allowed:
                    self._reply(peer, {"ok": False, "error": decision.reason})
            except (ValueError, PermissionError) as exc:
                self._reply(peer, {"ok": False, "error": str(exc)})
            readable, _, _ = select.select([self.socket], [], [], 0)
        sent = 0
        frames = self.gateway.drain()
        for frame in frames:
            payload = pack_wire(frame, self.gateway.channels)
            for peer in tuple(self.peers):
                try:
                    self.socket.sendto(payload, peer)
                    sent += 1
                except OSError:
                    self.peers.discard(peer)
        return {"received": received, "accepted": accepted, "published": sent}

    def _control(self, request: dict, peer) -> None:
        action = request.get("action")
        try:
            if action == "challenge":
                self._reply(peer, {"ok": True, "challenge": self.gateway.challenge()})
            elif action == "unlock":
                self._reply(peer, {"ok": True, **self.gateway.unlock(request.get("response", ""))})
            elif action == "lock":
                self._reply(peer, {"ok": True, **self.gateway.lock()})
            elif action == "status":
                self._reply(peer, {"ok": True, "status": self.gateway.status()})
            else:
                self._reply(peer, {"ok": False, "error": "Unknown bridge control action."})
        except PermissionError as exc:
            self._reply(peer, {"ok": False, "error": str(exc)})

    def _reply(self, peer, payload: dict) -> None:
        try:
            self.socket.sendto(json.dumps(payload).encode(), peer)
        except OSError:
            self.peers.discard(peer)

    def close(self) -> None:
        self.socket.close()
