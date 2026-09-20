"""Local CAN transport for the lab: SocketCAN when available, otherwise a
pure-software hub.

Two backends share one interface so the same gateway code runs on a Linux host
with `vcan` interfaces and inside WSLg or a container where the kernel module is
missing. Neither backend reaches a vehicle: `vcan` is a virtual kernel loopback
interface, and the software hub keeps frames inside this process tree.
"""
from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import threading
import time

from can_frames import Frame

# struct can_frame: id, len, flags, res0, res1, 8 data bytes.
CAN_FRAME = struct.Struct("=IBBBB8s")
CAN_RAW = 1
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x000007FF
CAN_EFF_MASK = 0x1FFFFFFF
DEFAULT_CHANNELS = ("veh", "ch", "party")


def vcan_supported() -> bool:
    return hasattr(socket, "AF_CAN") and Path("/sys/class/net").is_dir()


def interface_present(name: str) -> bool:
    return (Path("/sys/class/net") / name).exists()


def create_vcan(name: str) -> dict:
    """Bring up one virtual CAN interface. Requires CAP_NET_ADMIN once."""
    if not shutil.which("ip"):
        raise RuntimeError("iproute2 is not installed; the software CAN hub remains available.")
    if not interface_present(name):
        subprocess.run(["ip", "link", "add", "dev", name, "type", "vcan"], check=True,
                       capture_output=True, text=True, timeout=15)
    subprocess.run(["ip", "link", "set", "up", name], check=True,
                   capture_output=True, text=True, timeout=15)
    return {"interface": name, "state": "up"}


@dataclass(frozen=True)
class Filter:
    """A gateway acceptance rule, evaluated against the raw identifier."""
    identifier: int
    mask: int = CAN_SFF_MASK

    def matches(self, frame: Frame) -> bool:
        return frame.identifier & self.mask == self.identifier & self.mask


class Channel:
    """One logical CAN channel. Transport is chosen by the owning Bus."""

    def __init__(self, name: str, interface: str = "", bitrate_kbps: int = 500, history: int = 4096):
        self.name, self.interface, self.bitrate_kbps = name, interface or f"vcan-{name}", bitrate_kbps
        self.history = history
        self.received: list[Frame] = []
        self.transmitted = 0
        self.dropped = 0
        self.errors = 0
        self._lock = threading.Lock()

    def record(self, frame: Frame) -> None:
        with self._lock:
            self.received.append(frame)
            if len(self.received) > self.history:
                del self.received[:len(self.received) - self.history]
                self.dropped += 1

    def trace(self, limit: int = 200, since: float = 0) -> list[dict]:
        with self._lock:
            frames = [f for f in self.received if f.timestamp > since]
        return [f.as_dict() for f in frames[-limit:]]

    def stats(self) -> dict:
        with self._lock:
            return {"channel": self.name, "interface": self.interface,
                    "bitrate_kbps": self.bitrate_kbps, "received": len(self.received),
                    "transmitted": self.transmitted, "dropped": self.dropped, "errors": self.errors}


class SoftwareBus:
    """In-process hub: every writer's frame is delivered to the channel trace.

    Used when SocketCAN is unavailable and for deterministic tests.
    """
    backend = "software"

    def __init__(self, channels=DEFAULT_CHANNELS):
        self.channels = {name: Channel(name, interface=f"soft:{name}") for name in channels}
        self.listeners: list = []
        self._lock = threading.Lock()

    def channel(self, name: str) -> Channel:
        try:
            return self.channels[name]
        except KeyError as exc:
            raise ValueError(f"Unknown CAN channel {name!r}.") from exc

    def _dispatch(self, frame: Frame, origin: str) -> None:
        """Hand a frame to every listener, saying where it came from.

        Listeners need the origin: a frame this process transmits from its own
        state must not be read back as a request to change that state.
        """
        with self._lock:
            listeners = list(self.listeners)
        for listener in listeners:
            listener(frame, origin)

    def send(self, frame: Frame, origin: str = "send") -> Frame:
        channel = self.channel(frame.channel)
        channel.transmitted += 1
        channel.record(frame)
        self._dispatch(frame, origin)
        return frame

    def inject(self, frame: Frame) -> Frame:
        """Present a frame as if another ECU had produced it."""
        channel = self.channel(frame.channel)
        channel.record(frame)
        self._dispatch(frame, "inject")
        return frame

    def subscribe(self, callback) -> None:
        with self._lock:
            self.listeners.append(callback)

    def poll(self, timeout: float = 0) -> list[Frame]:
        if timeout:
            time.sleep(min(timeout, .05))
        return []

    def close(self) -> None:
        self.listeners.clear()


class SocketCanBus(SoftwareBus):
    """SocketCAN transport over virtual interfaces, one raw socket per channel."""
    backend = "socketcan"

    def __init__(self, channels=DEFAULT_CHANNELS, prefix="vcan", create=False):
        super().__init__(channels)
        if not vcan_supported():
            raise RuntimeError("This kernel does not expose SocketCAN. Use the software CAN hub.")
        self.sockets: dict[str, socket.socket] = {}
        for index, name in enumerate(self.channels):
            interface = f"{prefix}{index}"
            if create and not interface_present(interface):
                create_vcan(interface)
            if not interface_present(interface):
                raise RuntimeError(f"{interface} does not exist. Run the CAN setup action once, or use the software hub.")
            handle = socket.socket(socket.AF_CAN, socket.SOCK_RAW, CAN_RAW)
            handle.bind((interface,))
            handle.setblocking(False)
            self.sockets[name] = handle
            self.channels[name].interface = interface

    def _write(self, frame: Frame) -> None:
        identifier = frame.identifier | (CAN_EFF_FLAG if frame.extended else 0)
        payload = CAN_FRAME.pack(identifier, frame.length, 0, 0, 0, frame.data.ljust(8, b"\0"))
        try:
            self.sockets[frame.channel].send(payload)
        except OSError as exc:
            self.channels[frame.channel].errors += 1
            if exc.errno not in (errno.ENOBUFS, errno.EAGAIN):
                raise

    def send(self, frame: Frame, origin: str = "send") -> Frame:
        """Write to the interface, then trace and dispatch it locally.

        A raw CAN socket does not read back its own frames, so local traffic is
        recorded and dispatched here. Doing it in software instead of enabling
        CAN_RAW_RECV_OWN_MSGS keeps the origin of each frame exact.
        """
        channel = self.channel(frame.channel)
        self._write(frame)
        channel.transmitted += 1
        channel.record(frame)
        self._dispatch(frame, origin)
        return frame

    def inject(self, frame: Frame) -> Frame:
        self.channel(frame.channel).record(frame)
        self._write(frame)
        self._dispatch(frame, "inject")
        return frame

    def poll(self, timeout: float = .01) -> list[Frame]:
        """Drain every channel socket once and dispatch to listeners."""
        import select

        handles = {handle.fileno(): name for name, handle in self.sockets.items()}
        readable, _, _ = select.select(list(handles), [], [], timeout)
        frames = []
        for fileno in readable:
            name = handles[fileno]
            handle = self.sockets[name]
            while True:
                try:
                    payload = handle.recv(CAN_FRAME.size)
                except (BlockingIOError, InterruptedError):
                    break
                if len(payload) < CAN_FRAME.size:
                    break
                identifier, length, _, _, _, data = CAN_FRAME.unpack(payload)
                if identifier & (CAN_ERR_FLAG | CAN_RTR_FLAG):
                    self.channels[name].errors += 1
                    continue
                extended = bool(identifier & CAN_EFF_FLAG)
                frame = Frame(identifier & (CAN_EFF_MASK if extended else CAN_SFF_MASK),
                              data[:min(length, 8)], name, extended)
                self.channels[name].record(frame)
                frames.append(frame)
        for frame in frames:
            self._dispatch(frame, "recv")  # Produced outside this process.
        return frames

    def close(self) -> None:
        super().close()
        for handle in self.sockets.values():
            handle.close()
        self.sockets.clear()


def open_bus(channels=DEFAULT_CHANNELS, *, prefer: str = "auto", create: bool = False):
    """Return the best available transport. `prefer` is auto, socketcan or software."""
    if prefer not in ("auto", "socketcan", "software"):
        raise ValueError("Choose auto, socketcan or software for the CAN backend.")
    if prefer == "software":
        return SoftwareBus(channels)
    try:
        return SocketCanBus(channels, create=create)
    except (RuntimeError, OSError, PermissionError, subprocess.SubprocessError):
        if prefer == "socketcan":
            raise
        return SoftwareBus(channels)


def backend_report() -> dict:
    """What the host can offer, without changing anything."""
    interfaces = sorted(p.name for p in Path("/sys/class/net").glob("*can*")) if Path("/sys/class/net").is_dir() else []
    return {"socketcan_available": vcan_supported(), "vcan_interfaces": interfaces,
            "iproute2": bool(shutil.which("ip")), "privileged": os.geteuid() == 0 if hasattr(os, "geteuid") else False}
