"""Lab frame table plus a minimal .dbc reader.

The built-in table is a small, self-authored set of frame definitions that carry
the same quantities the desktop simulator already exposes. Names are lab names.
They are deliberately not a vehicle database: nothing here was extracted from a
car or from firmware, and a decoded value proves only what this lab encoded.

Point the gateway at a real .dbc with `load_dbc()` when you have one you are
allowed to use; the transport and the gateway logic do not change.
"""
from __future__ import annotations

from pathlib import Path
import re

from can_frames import Message, Signal

GEARS = ("Invalid", "P", "R", "N", "D")
INDICATORS = ("Off", "Left", "Right", "Both")
LIGHT_MODES = ("Off", "Parking", "On", "Auto")

MESSAGES: tuple[Message, ...] = (
    Message("LAB_driveState", 0x118, 8, "pt", period_ms=10, counter="counter", checksum="checksum",
            signals=(
                Signal("gear", 0, 3, choices=GEARS),
                Signal("speed_kph", 8, 12, scale=.1, unit="km/h"),
                Signal("throttle_pct", 20, 10, scale=.4, unit="%"),
                Signal("brake_pressed", 30, 1),
                Signal("counter", 48, 4),
                Signal("checksum", 56, 8),
            )),
    Message("LAB_steering", 0x129, 8, "pt", period_ms=10, counter="counter", checksum="checksum",
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


def lookup(channel: str, identifier: int, table=None) -> Message | None:
    table = table if table is not None else BY_ID
    return table.get((channel, identifier))


def index(messages) -> dict:
    return {(m.channel, m.identifier): m for m in messages}


_DBC_MESSAGE = re.compile(r"^BO_\s+(\d+)\s+([\w.]+)\s*:\s*(\d+)\s+(\S+)")
_DBC_SIGNAL = re.compile(
    r"^\s*SG_\s+([\w.]+)\s*:\s*(\d+)\|(\d+)@(\d)([+-])\s*"
    r"\(([-\d.eE+]+),([-\d.eE+]+)\)\s*\[([-\d.eE+]*)\|([-\d.eE+]*)\]\s*\"([^\"]*)\"")


def load_dbc(path: Path, channel: str = "veh", period_ms: int = 0) -> tuple[Message, ...]:
    """Read frame layouts from a .dbc file. Value tables and multiplexing are ignored."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    messages, current, signals = [], None, []

    def flush():
        if current:
            identifier, name, length = current
            extended = identifier > 0x7FF
            messages.append(Message(name, identifier & (0x1FFFFFFF if extended else 0x7FF),
                                    min(length, 8), channel, tuple(signals),
                                    period_ms=period_ms, extended=extended))

    for line in text.splitlines():
        header = _DBC_MESSAGE.match(line)
        if header:
            flush()
            current = (int(header.group(1)) & 0x1FFFFFFF, header.group(2), int(header.group(3)))
            signals = []
            continue
        if current:
            found = _DBC_SIGNAL.match(line)
            if found:
                signals.append(Signal(found.group(1), int(found.group(2)), int(found.group(3)),
                                      scale=float(found.group(6)), offset=float(found.group(7)),
                                      signed=found.group(5) == "-",
                                      little_endian=found.group(4) == "1", unit=found.group(10)))
    flush()
    if not messages:
        raise ValueError("No frame definitions were found in this .dbc file.")
    return tuple(messages)
