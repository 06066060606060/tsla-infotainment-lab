"""Frame and signal model for the local CAN emulation.

Nothing here talks to a vehicle. Signal layouts are lab definitions used to
exercise the desktop session: a value encoded here is never presented as proof
of firmware or vehicle behaviour. Layouts follow the usual DBC conventions so a
real .dbc can replace the built-in table without touching the transport.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time

MAX_STANDARD_ID = 0x7FF
MAX_EXTENDED_ID = 0x1FFFFFFF


def crc8(data: bytes, poly: int = 0x2F, init: int = 0xFF, xorout: int = 0xFF) -> int:
    """AUTOSAR-style CRC-8 used by the lab frame definitions that carry one."""
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc ^ xorout


@dataclass(frozen=True)
class Frame:
    """One CAN 2.0 frame on one named channel."""
    identifier: int
    data: bytes = b""
    channel: str = "veh"
    extended: bool = False
    timestamp: float = field(default_factory=time.time, compare=False)

    def __post_init__(self) -> None:
        limit = MAX_EXTENDED_ID if self.extended else MAX_STANDARD_ID
        if not isinstance(self.identifier, int) or not 0 <= self.identifier <= limit:
            raise ValueError("CAN identifier is outside the addressable range.")
        if not isinstance(self.data, (bytes, bytearray)):
            raise ValueError("Frame payload must be bytes.")
        if len(self.data) > 8:
            raise ValueError("A CAN 2.0 payload holds at most 8 bytes.")
        object.__setattr__(self, "data", bytes(self.data))

    @property
    def length(self) -> int:
        return len(self.data)

    def as_dict(self) -> dict:
        return {"channel": self.channel, "id": self.identifier,
                "id_hex": f"{self.identifier:03X}" if not self.extended else f"{self.identifier:08X}",
                "extended": self.extended, "length": self.length,
                "data": self.data.hex(" ").upper(), "timestamp": self.timestamp}

    @classmethod
    def parse(cls, value: dict) -> "Frame":
        """Accept a user-entered frame: hex or decimal id, hex or byte-list data."""
        if not isinstance(value, dict):
            raise ValueError("A frame must be an object.")
        unknown = set(value) - {"channel", "id", "data", "extended", "timestamp"}
        if unknown:
            raise ValueError(f"Unknown frame field: {sorted(unknown)[0]}.")
        raw_id = value.get("id")
        if isinstance(raw_id, str):
            try:
                identifier = int(raw_id.strip().removeprefix("0x").removeprefix("0X"), 16)
            except ValueError as exc:
                raise ValueError("Identifier must be hexadecimal, for example 0x118.") from exc
        elif isinstance(raw_id, int) and not isinstance(raw_id, bool):
            identifier = raw_id
        else:
            raise ValueError("Identifier must be a number or a hexadecimal string.")
        payload = value.get("data", b"")
        if isinstance(payload, str):
            text = payload.replace(" ", "").replace(":", "").replace("-", "")
            if len(text) % 2 or any(c not in "0123456789abcdefABCDEF" for c in text):
                raise ValueError("Payload must be an even number of hexadecimal digits.")
            payload = bytes.fromhex(text)
        elif isinstance(payload, (list, tuple)):
            if any(not isinstance(b, int) or isinstance(b, bool) or not 0 <= b <= 255 for b in payload):
                raise ValueError("Payload bytes must be between 0 and 255.")
            payload = bytes(payload)
        channel = value.get("channel", "veh")
        if not isinstance(channel, str) or not channel:
            raise ValueError("Channel must be a name.")
        extended = value.get("extended", False)
        if type(extended) is not bool:
            raise ValueError("extended must be true or false.")
        return cls(identifier, payload, channel, extended)


@dataclass(frozen=True)
class Signal:
    """A packed value inside a frame, in DBC terms.

    start_bit is the least-significant bit position for little-endian
    (Intel) layouts, and the most-significant bit position for big-endian
    (Motorola) layouts, matching DBC numbering.
    """
    name: str
    start_bit: int
    bit_length: int
    scale: float = 1.0
    offset: float = 0.0
    signed: bool = False
    little_endian: bool = True
    unit: str = ""
    choices: tuple[str, ...] = ()

    def decode(self, data: bytes) -> float | str:
        raw = _extract(data, self.start_bit, self.bit_length, self.little_endian)
        if self.signed and raw >> (self.bit_length - 1):
            raw -= 1 << self.bit_length
        if self.choices:
            return self.choices[raw] if raw < len(self.choices) else f"reserved:{raw}"
        return raw * self.scale + self.offset

    def encode_into(self, buffer: bytearray, value) -> None:
        if self.choices:
            if isinstance(value, str):
                if value not in self.choices:
                    raise ValueError(f"{self.name} has no state named {value!r}.")
                raw = self.choices.index(value)
            else:
                raw = int(value)
        else:
            raw = round((float(value) - self.offset) / self.scale)
        span = 1 << self.bit_length
        if self.signed:
            low, high = -(span // 2), span // 2 - 1
        else:
            low, high = 0, span - 1
        raw = max(low, min(high, raw)) & (span - 1)
        _insert(buffer, self.start_bit, self.bit_length, self.little_endian, raw)


def _bit_positions(start_bit: int, bit_length: int, little_endian: bool):
    """Yield (byte index, bit index) from least significant bit upwards."""
    if bit_length < 1 or bit_length > 64:
        raise ValueError("A signal holds between 1 and 64 bits.")
    if little_endian:
        for step in range(bit_length):
            position = start_bit + step
            yield position // 8, position % 8
    else:
        for step in range(bit_length):
            position = start_bit - step
            byte, bit = divmod(position, 8)
            # DBC big-endian numbering walks forward through the bytes.
            yield start_bit // 8 + (start_bit % 8 - position % 8 + step) // 8, bit


def _motorola_positions(start_bit: int, bit_length: int):
    byte, bit = divmod(start_bit, 8)
    for _ in range(bit_length):
        yield byte, bit
        bit -= 1
        if bit < 0:
            bit, byte = 7, byte + 1


def _extract(data: bytes, start_bit: int, bit_length: int, little_endian: bool) -> int:
    positions = (list(_bit_positions(start_bit, bit_length, True)) if little_endian
                 else list(_motorola_positions(start_bit, bit_length))[::-1])
    raw = 0
    for index, (byte, bit) in enumerate(positions):
        if byte >= len(data):
            continue
        raw |= ((data[byte] >> bit) & 1) << index
    return raw


def _insert(buffer: bytearray, start_bit: int, bit_length: int, little_endian: bool, raw: int) -> None:
    positions = (list(_bit_positions(start_bit, bit_length, True)) if little_endian
                 else list(_motorola_positions(start_bit, bit_length))[::-1])
    for index, (byte, bit) in enumerate(positions):
        if byte >= len(buffer):
            raise ValueError("The signal does not fit inside the frame length.")
        mask = 1 << bit
        if (raw >> index) & 1:
            buffer[byte] |= mask
        else:
            buffer[byte] &= 0xFF - mask


@dataclass(frozen=True)
class Message:
    """A frame definition: fixed layout, optional rolling counter and CRC."""
    name: str
    identifier: int
    length: int
    channel: str
    signals: tuple[Signal, ...]
    period_ms: int = 0
    counter: str = ""
    checksum: str = ""
    checksum_start: int = 0
    extended: bool = False

    def encode(self, values: dict, counter: int = 0) -> Frame:
        buffer = bytearray(self.length)
        for signal in self.signals:
            if signal.name in values:
                signal.encode_into(buffer, values[signal.name])
        if self.counter:
            self.signal(self.counter).encode_into(buffer, counter & 0x0F)
        if self.checksum:
            slot = self.signal(self.checksum)
            body = bytes(b for index, b in enumerate(buffer) if index != slot.start_bit // 8)
            slot.encode_into(buffer, crc8(bytes([self.identifier & 0xFF]) + body))
        return Frame(self.identifier, bytes(buffer), self.channel, self.extended)

    def decode(self, frame: Frame) -> dict:
        return {signal.name: signal.decode(frame.data) for signal in self.signals}

    def signal(self, name: str) -> Signal:
        for signal in self.signals:
            if signal.name == name:
                return signal
        raise KeyError(f"{self.name} has no signal named {name}.")

    def checksum_valid(self, frame: Frame) -> bool:
        if not self.checksum:
            return True
        slot = self.signal(self.checksum)
        index = slot.start_bit // 8
        body = bytes(b for position, b in enumerate(frame.data) if position != index)
        return frame.data[index] == crc8(bytes([self.identifier & 0xFF]) + body)
