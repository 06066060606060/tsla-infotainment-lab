"""Lab frame table plus a minimal .dbc reader.

The built-in table is a small, self-authored set of frame definitions that carry
the same quantities the desktop simulator already exposes. Names are lab names.
They are deliberately not a vehicle database: nothing here was extracted from a
car or from firmware, and a decoded value proves only what this lab encoded.

Point the gateway at a real .dbc with `load_dbc()` when you have one you are
allowed to use; the transport and the gateway logic do not change.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from can_frames import Message, Signal

GEARS = ("Invalid", "P", "R", "N", "D")
INDICATORS = ("Off", "Left", "Right", "Both")
LIGHT_MODES = ("Off", "Parking", "On", "Auto")

MESSAGES: tuple[Message, ...] = (
    Message("LAB_driveState", 0x118, 8, "veh", period_ms=10, counter="counter", checksum="checksum",
            signals=(
                Signal("gear", 0, 3, choices=GEARS),
                Signal("speed_kph", 8, 12, scale=.1, unit="km/h"),
                Signal("throttle_pct", 20, 10, scale=.4, unit="%"),
                Signal("brake_pressed", 30, 1),
                Signal("counter", 48, 4),
                Signal("checksum", 56, 8),
            )),
    Message("LAB_steering", 0x129, 8, "veh", period_ms=10, counter="counter", checksum="checksum",
            signals=(
                Signal("steering_deg", 0, 14, scale=.1, offset=-819.2, signed=False, unit="deg"),
                Signal("road_wheel_deg", 16, 12, scale=.05, offset=-102.4, unit="deg"),
                Signal("yaw_rate", 28, 14, scale=.001, offset=-8.192, unit="rad/s"),
                Signal("counter", 48, 4),
                Signal("checksum", 56, 8),
            )),
    Message("LAB_lighting", 0x3F5, 8, "veh", period_ms=100,
            signals=(
                Signal("indicator", 0, 2, choices=INDICATORS),
                Signal("left_lamp", 2, 1),
                Signal("right_lamp", 3, 1),
                Signal("headlights", 4, 1),
                Signal("high_beams", 5, 1),
                Signal("light_mode", 6, 2, choices=LIGHT_MODES),
                Signal("ambient_dark", 8, 1),
            )),
    Message("LAB_closures", 0x102, 8, "veh", period_ms=100,
            signals=(
                Signal("driver_door", 0, 1), Signal("passenger_door", 1, 1),
                Signal("rear_left_door", 2, 1), Signal("rear_right_door", 3, 1),
                Signal("front_trunk", 4, 1), Signal("rear_trunk", 5, 1),
                Signal("locked", 6, 1), Signal("alarm_armed", 7, 1),
            )),
    Message("LAB_climate", 0x2E5, 8, "veh", period_ms=200,
            signals=(
                Signal("climate_on", 0, 1),
                Signal("ac_on", 1, 1),
                Signal("rear_defrost", 2, 1),
                Signal("fan_speed", 4, 4),
                Signal("cabin_temp_c", 8, 10, scale=.1, offset=-40, unit="degC"),
                Signal("outside_temp_c", 18, 10, scale=.1, offset=-50, unit="degC"),
                Signal("driver_temp_c", 28, 8, scale=.2, offset=15, unit="degC"),
                Signal("passenger_temp_c", 36, 8, scale=.2, offset=15, unit="degC"),
            )),
    Message("LAB_energy", 0x352, 8, "ch", period_ms=200,
            signals=(
                Signal("battery_percent", 0, 10, scale=.2, unit="%"),
                Signal("charge_limit_pct", 10, 10, scale=.2, unit="%"),
                Signal("charging", 20, 1),
                Signal("charge_power_kw", 24, 12, scale=.05, unit="kW"),
            )),
    Message("LAB_tyres", 0x3D8, 8, "veh", period_ms=500,
            signals=(
                Signal("tire_fl_bar", 0, 9, scale=.02, unit="bar"),
                Signal("tire_fr_bar", 16, 9, scale=.02, unit="bar"),
                Signal("tire_rl_bar", 32, 9, scale=.02, unit="bar"),
                Signal("tire_rr_bar", 48, 9, scale=.02, unit="bar"),
            )),
    # The session's operating modes, as the displays show them (GUI_serviceMode and friends).
    Message("LAB_vehicleModes", 0x5E1, 8, "veh", period_ms=500,
            signals=(
                Signal("service_mode", 0, 1), Signal("developer_mode", 1, 1),
                Signal("factory_mode", 2, 1), Signal("transport_mode", 3, 1),
                Signal("showroom_mode", 4, 1), Signal("dyno_mode", 5, 1),
            )),
    # Diagnostic pair used by the gateway's emulated authentication session.
    Message("LAB_gatewayRequest", 0x641, 8, "party", signals=(Signal("payload", 0, 8),)),
    Message("LAB_gatewayResponse", 0x651, 8, "party", signals=(Signal("payload", 0, 8),)),
)

BY_NAME = {message.name: message for message in MESSAGES}
BY_ID = {(message.channel, message.identifier): message for message in MESSAGES}


def message(name: str) -> Message:
    try:
        return BY_NAME[name]
    except KeyError as exc:
        raise ValueError(f"Unknown frame definition {name!r}.") from exc


def lookup(channel: str, identifier: int, table=None, extended: bool = False) -> Message | None:
    table = table if table is not None else BY_ID
    found = table.get((channel, identifier))
    return found if found and found.extended == extended else None


def index(messages) -> dict:
    return {(m.channel, m.identifier): m for m in messages}


_DBC_MESSAGE = re.compile(r"^BO_\s+(\d+)\s+([\w.]+)\s*:\s*(\d+)\s+(\S+)")
_DBC_SIGNAL = re.compile(
    r"^\s*SG_\s+([\w.]+)\s*(M|m\d+)?\s*:\s*(\d+)\|(\d+)@(\d)([+-])\s*"
    r"\(([-\d.eE+]+),([-\d.eE+]+)\)\s*\[([-\d.eE+]*)\|([-\d.eE+]*)\]\s*\"([^\"]*)\"")
_DBC_VALUES = re.compile(r"^VAL_\s+(\d+)\s+([\w.]+)\s+(.*?)\s*;")
_DBC_CYCLE = re.compile(r'^BA_\s+"GenMsgCycleTime"\s+BO_\s+(\d+)\s+(\d+)\s*;')
_VALUE_PAIR = re.compile(r'(-?\d+)\s+"([^"]*)"')


def _counter_or_checksum(signals) -> tuple[str, str]:
    """Pick the rolling counter and checksum by the names public databases use."""
    counter = next((s.name for s in signals if s.mux < 0 and s.bit_length <= 8
                    and (s.name.endswith("Counter") or s.name.startswith("MC_"))), "")
    checksum = next((s.name for s in signals if s.mux < 0 and s.bit_length == 8 and s.start_bit % 8 in (0, 7)
                     and (s.name.endswith(("Checksum", "Crc", "CRC")) or s.name.startswith("CRC_"))), "")
    return counter, checksum


def load_dbc(path: Path, channel: str = "veh", period_ms: int = 0) -> tuple[Message, ...]:
    """Read frame layouts from a .dbc file.

    Supports simple multiplexing (M / mN), VAL_ value names, GenMsgCycleTime and
    the counter/checksum naming used by the public opendbc Tesla files, whose
    checksum is additive. Extended multiplexing and CAN FD lengths are ignored.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    headers, signals, values, cycles = [], {}, {}, {}
    current = None
    for line in text.splitlines():
        header = _DBC_MESSAGE.match(line)
        if header:
            current = int(header.group(1))
            headers.append((current, header.group(2), int(header.group(3)), header.group(4)))
            signals[current] = []
            continue
        found = _DBC_SIGNAL.match(line) if current is not None else None
        if found:
            signals[current].append(found)
            continue
        if not line.startswith(" "):
            current = None
        named = _DBC_VALUES.match(line)
        if named:
            pairs = {int(k): v for k, v in _VALUE_PAIR.findall(named.group(3))}
            values[(int(named.group(1)), named.group(2))] = pairs
        cycle = _DBC_CYCLE.match(line)
        if cycle:
            cycles[int(cycle.group(1))] = int(cycle.group(2))

    messages = []
    for raw_id, name, length, sender in headers:
        parsed, multiplexer = [], ""
        for found in signals[raw_id]:
            mux = found.group(2) or ""
            if mux == "M":
                multiplexer = found.group(1)
            choices = _choices(values.get((raw_id, found.group(1)), {}))
            parsed.append(Signal(found.group(1), int(found.group(3)), int(found.group(4)),
                                 scale=float(found.group(7)), offset=float(found.group(8)),
                                 signed=found.group(6) == "-", little_endian=found.group(5) == "1",
                                 unit=found.group(11), choices=choices,
                                 mux=int(mux[1:]) if mux.startswith("m") else -1))
        # DBC marks an extended identifier with bit 31.
        extended = bool(raw_id & 0x80000000) or raw_id & 0x1FFFFFFF > 0x7FF
        counter, checksum = _counter_or_checksum(parsed)
        messages.append(Message(name, raw_id & (0x1FFFFFFF if extended else 0x7FF), min(length, 8),
                                channel, tuple(parsed), period_ms=cycles.get(raw_id, period_ms),
                                counter=counter, checksum=checksum, extended=extended,
                                checksum_kind="tesla", multiplexer=multiplexer, sender=sender))
    if not messages:
        raise ValueError("No frame definitions were found in this .dbc file.")
    return tuple(messages)


def _choices(table: dict) -> tuple[str, ...]:
    """A sparse value table as a raw-indexed tuple; gaps are unnamed and decode as numbers."""
    if not table or min(table) < 0 or max(table) > 255:
        return ()
    return tuple(table.get(i, "") for i in range(max(table) + 1))


def load_signal_json(path: Path, channel: str = "veh") -> tuple[Message, ...]:
    """Read the per-bus JSON layout used by the public tesla_can_signals project.

    Each message carries start position, width, endianness (DBC numbering),
    scale, offset, value names, cycle time, idle start values, multiplexing
    and named counter/checksum signals. The checksum algorithm is not part of
    that format; the additive one from opendbc is assumed.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    messages = []
    for name, spec in data.get("messages", {}).items():
        signals, multiplexer = [], ""
        for signal_name, s in spec.get("signals", {}).items():
            if s.get("is_muxer"):
                multiplexer = signal_name
            table = {int(v): k for k, v in (s.get("value_description") or {}).items()
                     if isinstance(v, int) and not isinstance(v, bool)}
            choices = _choices(table)
            initial = s.get("start_value")  # A raw value in this format.
            if isinstance(initial, (int, float)):
                named = choices[int(initial)] if 0 <= initial < len(choices) else ""
                initial = named or initial * float(s.get("scale", 1)) + float(s.get("offset", 0))
            signals.append(Signal(signal_name, int(s["start_position"]), int(s["width"]),
                                  scale=float(s.get("scale", 1)), offset=float(s.get("offset", 0)),
                                  signed=s.get("signedness") == "SIGNED",
                                  little_endian=s.get("endianness") != "BIG", unit=s.get("units", ""),
                                  choices=choices, mux=int(s["mux_id"]) if s.get("mux_id") is not None else -1,
                                  initial=initial))
        validation = spec.get("messageValidation", {})
        known = {signal.name for signal in signals}
        counter, checksum = _counter_or_checksum(signals)
        counter = validation.get("messageCounter", counter) if validation.get("messageCounter", counter) in known else ""
        checksum = validation.get("messageChecksum", checksum) if validation.get("messageChecksum", checksum) in known else ""
        identifier = int(spec["message_id"])
        extended = identifier > 0x7FF
        senders = spec.get("senders") or [spec.get("originNode", "")]
        messages.append(Message(name, identifier, min(int(spec.get("length_bytes", 8)), 8), channel,
                                tuple(signals), period_ms=int(spec.get("cycle_time") or 0),
                                counter=counter, checksum=checksum, extended=extended,
                                checksum_kind="tesla", multiplexer=multiplexer,
                                sender=",".join(senders)))
    if not messages:
        raise ValueError("No frame definitions were found in this signal file.")
    return tuple(messages)


def load(path: Path, channel: str = "veh", period_ms: int = 0) -> tuple[Message, ...]:
    """Read a .dbc or a tesla_can_signals JSON file, chosen by its suffix."""
    if Path(path).suffix.lower() == ".json":
        return load_signal_json(path, channel)
    return load_dbc(path, channel, period_ms)
