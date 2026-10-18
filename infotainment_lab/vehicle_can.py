"""Bind the existing local simulator state to the lab CAN frame definitions.

The desktop already owns the authoritative state (Simulation and
VehicleServices). This module only projects that state onto periodic lab frames
and turns accepted inbound frames back into a state patch, so the gateway path
can be exercised without inventing a second source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import time

import can_database
from can_frames import Frame
from simulation import STEERING_RATIO, WHEELBASE_M, Simulation
from vehicle_services import VehicleServices

# Frames whose content is allowed to feed back into local state, and which
# part of the desktop state each one owns.
INBOUND_SERVICES = {"LAB_climate", "LAB_lighting"}
INBOUND_CONTROLS = {"LAB_driveState", "LAB_steering", "LAB_lighting"}
INBOUND = INBOUND_SERVICES | INBOUND_CONTROLS


def drive_values(sim: Simulation) -> dict:
    return {"gear": sim.gear, "speed_kph": sim.speed_kph,
            "throttle_pct": sim.throttle_pct, "brake_pressed": int(sim.brake_pct > 0)}


def steering_values(sim: Simulation) -> dict:
    road_wheel_deg = max(-36.0, min(36.0, -sim.steering_deg / STEERING_RATIO))
    speed_mps = sim.speed_kph / 3.6
    signed = -speed_mps if sim.gear == "R" else speed_mps
    yaw_rate = signed / WHEELBASE_M * math.tan(math.radians(road_wheel_deg))
    return {"steering_deg": sim.steering_deg, "road_wheel_deg": road_wheel_deg, "yaw_rate": yaw_rate}


def lighting_values(sim: Simulation, services: VehicleServices, elapsed: float = 0) -> dict:
    direction = sim.indicator
    left, right = direction in ("left", "hazard"), direction in ("right", "hazard")
    lit = int(max(0, elapsed) / .4) % 2 == 0
    return {"indicator": {"off": "Off", "left": "Left", "right": "Right", "hazard": "Both"}[direction],
            "left_lamp": int(left and lit), "right_lamp": int(right and lit),
            "headlights": int(services.headlights), "high_beams": int(services.high_beams),
            "light_mode": services.exterior_light_mode, "ambient_dark": int(services.ambient_dark)}


def closure_values(services: VehicleServices) -> dict:
    return {"driver_door": int(services.driver_door_open), "passenger_door": int(services.passenger_door_open),
            "rear_left_door": int(services.rear_left_door_open), "rear_right_door": int(services.rear_right_door_open),
            "front_trunk": int(services.front_trunk_open), "rear_trunk": int(services.rear_trunk_open),
            "locked": int(services.locked), "alarm_armed": int(services.alarm_armed)}


def climate_values(services: VehicleServices) -> dict:
    return {"climate_on": int(services.climate_on), "ac_on": int(services.ac_on),
            "rear_defrost": int(services.rear_defrost), "fan_speed": services.fan_speed,
            "cabin_temp_c": services.cabin_temp_c, "outside_temp_c": services.outside_temp_c,
            "driver_temp_c": services.driver_temp_c, "passenger_temp_c": services.passenger_temp_c}


def energy_values(services: VehicleServices) -> dict:
    return {"battery_percent": services.battery_percent, "charge_limit_pct": services.charge_limit_pct,
            "charging": int(services.charging), "charge_power_kw": services.charge_power_kw}


def tyre_values(services: VehicleServices) -> dict:
    return {"tire_fl_bar": services.tire_fl_bar, "tire_fr_bar": services.tire_fr_bar,
            "tire_rl_bar": services.tire_rl_bar, "tire_rr_bar": services.tire_rr_bar}


def mode_values(services: VehicleServices) -> dict:
    return {"service_mode": int(services.service_mode), "developer_mode": int(services.developer_mode),
            "factory_mode": int(services.factory_mode), "transport_mode": int(services.transport_mode),
            "showroom_mode": int(services.showroom_mode), "dyno_mode": int(services.dyno_mode)}


def frame_values(sim: Simulation, services: VehicleServices, elapsed: float = 0) -> dict[str, dict]:
    return {"LAB_driveState": drive_values(sim), "LAB_steering": steering_values(sim),
            "LAB_lighting": lighting_values(sim, services, elapsed),
            "LAB_closures": closure_values(services), "LAB_climate": climate_values(services),
            "LAB_energy": energy_values(services), "LAB_tyres": tyre_values(services),
            "LAB_vehicleModes": mode_values(services)}


def state_patch(name: str, decoded: dict) -> dict:
    """Translate an accepted inbound frame into a VehicleServices patch."""
    if name not in INBOUND_SERVICES:
        return {}
    if name == "LAB_climate":
        return {"climate_on": bool(decoded["climate_on"]), "ac_on": bool(decoded["ac_on"]),
                "rear_defrost": bool(decoded["rear_defrost"]), "fan_speed": int(decoded["fan_speed"]),
                "driver_temp_c": round(decoded["driver_temp_c"], 1),
                "passenger_temp_c": round(decoded["passenger_temp_c"], 1)}
    return {"exterior_light_mode": decoded["light_mode"] if decoded["light_mode"] in ("Off", "Parking", "On", "Auto") else "Off",
            "high_beams": bool(decoded["high_beams"]), "ambient_dark": bool(decoded["ambient_dark"])}


def controls_patch(name: str, decoded: dict) -> dict:
    """Translate an accepted inbound frame into a Simulation patch.

    A frame carries physical quantities, so the pedal percentage cannot be
    recovered from a brake flag: only the pressed state is applied.
    """
    if name == "LAB_driveState":
        patch = {"gear": decoded["gear"] if decoded["gear"] in ("P", "R", "N", "D") else "P",
                 "speed_kph": round(decoded["speed_kph"], 1),
                 "throttle_pct": round(decoded["throttle_pct"], 1)}
        if not decoded["brake_pressed"]:
            patch["brake_pct"] = 0
        return patch
    if name == "LAB_steering":
        return {"steering_deg": round(decoded["steering_deg"], 1)}
    if name == "LAB_lighting":
        direction = {"Off": "off", "Left": "left", "Right": "right", "Both": "hazard"}
        return {"indicator": direction.get(decoded["indicator"], "off")}
    return {}


# Public database signals bound to the session state. Each takes a context
# (sim, services, lighting values) and returns a physical value or a value name;
# a name the loaded table does not define is skipped. Speeds are km/h and
# converted where a signal declares MPH.
_KPH = lambda c: c[0].speed_kph
_LATCH = lambda flag: "LATCH_OPENED" if flag else "LATCH_CLOSED"
_LIGHT = lambda flag: "LIGHT_ON" if flag else "LIGHT_OFF"
_STALK = {"left": "DOWN_1", "right": "UP_1"}
SIGNAL_BINDINGS = {
    "DI_gear": lambda c: f"DI_GEAR_{c[0].gear}",
    "DI_gearRequest": lambda c: f"DI_GEAR_{c[0].gear}",
    "DI_vehicleSpeed": _KPH, "ESP_vehicleSpeed": _KPH, "DI_uiSpeed": _KPH, "DI_digitalSpeed": _KPH,
    "DI_analogSpeed": _KPH, "ESP_wheelSpeedFrL": _KPH, "ESP_wheelSpeedFrR": _KPH,
    "ESP_wheelSpeedReL": _KPH, "ESP_wheelSpeedReR": _KPH,
    "DI_uiSpeedUnits": lambda c: "DI_SPEED_KPH",
    "DI_accelPedalPos": lambda c: c[0].throttle_pct,
    "DI_brakePedalState": lambda c: "ON" if c[0].brake_pct > 0 else "OFF",
    "DI_brakePedal": lambda c: "Applied" if c[0].brake_pct > 0 else "Not_applied",
    "IBST_driverBrakeApply": lambda c: "DRIVER_APPLYING_BRAKES" if c[0].brake_pct > 0 else "BRAKES_NOT_APPLIED",
    "VCLEFT_brakePressed": lambda c: int(c[0].brake_pct > 0),
    "SCCM_steeringAngle": lambda c: c[0].steering_deg, "StW_AnglHP": lambda c: c[0].steering_deg,
    "StW_Angl": lambda c: c[0].steering_deg,
    "SCCM_turnIndicatorStalkStatus": lambda c: _STALK.get(c[0].indicator, "IDLE"),
    "VCFRONT_turnSignalLeftStatus": lambda c: _LIGHT(c[2]["left_lamp"]),
    "VCFRONT_turnSignalRightStatus": lambda c: _LIGHT(c[2]["right_lamp"]),
    "BCFRONT_indicatorLeftStatus": lambda c: _LIGHT(c[2]["left_lamp"]),
    "BCFRONT_indicatorRightStatus": lambda c: _LIGHT(c[2]["right_lamp"]),
    "BC_indicatorLStatus": lambda c: "On" if c[2]["left_lamp"] else "Off",
    "BC_indicatorRStatus": lambda c: "On" if c[2]["right_lamp"] else "Off",
    "VCFRONT_indicatorLeftRequest": lambda c: "TURN_SIGNAL_ACTIVE_HIGH" if c[0].indicator in ("left", "hazard") else "TURN_SIGNAL_OFF",
    "VCFRONT_indicatorRightRequest": lambda c: "TURN_SIGNAL_ACTIVE_HIGH" if c[0].indicator in ("right", "hazard") else "TURN_SIGNAL_OFF",
    "VCFRONT_lowBeamLeftStatus": lambda c: _LIGHT(c[1].headlights),
    "VCFRONT_lowBeamRightStatus": lambda c: _LIGHT(c[1].headlights),
    "VCFRONT_highBeamLeftStatus": lambda c: _LIGHT(c[1].high_beams),
    "VCFRONT_highBeamRightStatus": lambda c: _LIGHT(c[1].high_beams),
    "VCLEFT_frontLatchStatus": lambda c: _LATCH(c[1].driver_door_open),
    "VCLEFT_rearLatchStatus": lambda c: _LATCH(c[1].rear_left_door_open),
    "VCRIGHT_frontLatchStatus": lambda c: _LATCH(c[1].passenger_door_open),
    "VCRIGHT_rearLatchStatus": lambda c: _LATCH(c[1].rear_right_door_open),
    "VCRIGHT_trunkLatchStatus": lambda c: _LATCH(c[1].rear_trunk_open),
    "MCU_LeftTempSetpoint_DegC": lambda c: c[1].driver_temp_c,
    "MCU_RightTempSetpoint_DegC": lambda c: c[1].passenger_temp_c,
    "GTW_ambientTemperature": lambda c: c[1].outside_temp_c,
}
_SPEEDS = {name for name, fn in SIGNAL_BINDINGS.items() if fn is _KPH}
_GEARS = {"DI_GEAR_P": "P", "DI_GEAR_R": "R", "DI_GEAR_N": "N", "DI_GEAR_D": "D"}
_LATCHES = {"VCLEFT_frontLatchStatus": "driver_door_open", "VCLEFT_rearLatchStatus": "rear_left_door_open",
            "VCRIGHT_frontLatchStatus": "passenger_door_open", "VCRIGHT_rearLatchStatus": "rear_right_door_open",
            "VCRIGHT_trunkLatchStatus": "rear_trunk_open"}


def _to_signal(signal, value):
    """Convert a bound value into what the signal encodes, or None to skip it."""
    if isinstance(value, str):
        return value if value in signal.choices else None
    if signal.name in _SPEEDS and signal.unit.upper() == "MPH":
        return value / 1.609344
    return value


def database_values(message, sim: Simulation, services: VehicleServices, elapsed: float = 0) -> dict:
    """Idle values the database declares, overlaid with the bound session state."""
    context = (sim, services, lighting_values(sim, services, elapsed))
    values = {}
    for signal in message.signals:
        value = signal.initial
        if signal.name in SIGNAL_BINDINGS:
            bound = _to_signal(signal, SIGNAL_BINDINGS[signal.name](context))
            value = bound if bound is not None else value
        if value is not None and (not isinstance(value, str) or value in signal.choices):
            values[signal.name] = value
    return values


def database_patches(message, decoded: dict) -> tuple[dict, dict]:
    """Turn an accepted public-database frame back into (controls, services) patches."""
    controls, services = {}, {}
    units = {signal.name: signal.unit for signal in message.signals}
    for name, value in decoded.items():
        if name in ("DI_gear",) and value in _GEARS:
            controls["gear"] = _GEARS[value]
        elif name in ("DI_vehicleSpeed", "ESP_vehicleSpeed") and isinstance(value, (int, float)):
            kph = value * 1.609344 if units[name].upper() == "MPH" else value
            controls["speed_kph"] = round(max(0.0, kph), 1)
        elif name == "DI_accelPedalPos" and isinstance(value, (int, float)):
            controls["throttle_pct"] = round(value, 1)
        elif name in ("SCCM_steeringAngle", "StW_AnglHP") and isinstance(value, (int, float)):
            controls["steering_deg"] = round(value, 1)
        elif name == "SCCM_turnIndicatorStalkStatus":
            controls["indicator"] = {"UP_1": "right", "UP_2": "right", "DOWN_1": "left", "DOWN_2": "left"}.get(value, "off")
        elif name in _LATCHES and value in ("LATCH_OPENED", "LATCH_CLOSED", "LATCH_AJAR"):
            services[_LATCHES[name]] = value != "LATCH_CLOSED"
        elif name == "MCU_LeftTempSetpoint_DegC" and isinstance(value, (int, float)):
            services["driver_temp_c"] = round(value, 1)
        elif name == "MCU_RightTempSetpoint_DegC" and isinstance(value, (int, float)):
            services["passenger_temp_c"] = round(value, 1)
    return controls, services


@dataclass
class PeriodicTransmitter:
    """Emit each periodic frame at its defined period, with a rolling counter.

    Lab frames take their values from frame_values; public-database frames from
    database_values. A multiplexed frame steps through its pages one per period.
    """
    messages: tuple = field(default_factory=lambda: can_database.MESSAGES)
    counters: dict = field(default_factory=dict)
    next_due: dict = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)

    @staticmethod
    def key(message) -> tuple:
        # Several buses carry a frame of the same name.
        return message.channel, message.identifier

    def due(self, now: float | None = None) -> list:
        now = time.monotonic() if now is None else now
        ready = []
        for message in self.messages:
            if not message.period_ms:
                continue
            deadline = self.next_due.get(self.key(message), now)
            if now >= deadline:
                self.next_due[self.key(message)] = max(now, deadline) + message.period_ms / 1000
                ready.append(message)
        return ready

    def build(self, message, values: dict) -> Frame:
        counter = self.counters.get(self.key(message), 0)
        self.counters[self.key(message)] = counter + 1
        pages = message.mux_values
        if message.multiplexer and pages:
            values = dict(values, **{message.multiplexer: pages[counter % len(pages)]})
        return message.encode(values, counter)

    def values(self, message, lab: dict, sim, services, elapsed) -> dict:
        if message.name in lab:
            return lab[message.name]
        return database_values(message, sim, services, elapsed)

    def tick(self, sim: Simulation, services: VehicleServices, now: float | None = None) -> list[Frame]:
        elapsed = (time.monotonic() if now is None else now) - self.started
        lab = frame_values(sim, services, elapsed)
        return [self.build(message, self.values(message, lab, sim, services, elapsed))
                for message in self.due(now)]


def snapshot(sim: Simulation, services: VehicleServices, messages=None) -> list[dict]:
    """One frame per periodic definition, for inspection in the UI or a test."""
    transmitter = PeriodicTransmitter()
    lab = frame_values(sim, services)
    return [transmitter.build(message, transmitter.values(message, lab, sim, services, 0)).as_dict()
            for message in (messages if messages is not None else can_database.MESSAGES) if message.period_ms]
