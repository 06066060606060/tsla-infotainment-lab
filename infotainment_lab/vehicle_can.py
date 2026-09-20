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

# Frames whose content the gateway is allowed to feed back into local state.
INBOUND = {"LAB_climate", "LAB_lighting"}


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


def frame_values(sim: Simulation, services: VehicleServices, elapsed: float = 0) -> dict[str, dict]:
    return {"LAB_driveState": drive_values(sim), "LAB_steering": steering_values(sim),
            "LAB_lighting": lighting_values(sim, services, elapsed),
            "LAB_closures": closure_values(services), "LAB_climate": climate_values(services),
            "LAB_energy": energy_values(services), "LAB_tyres": tyre_values(services)}


def state_patch(name: str, decoded: dict) -> dict:
    """Translate an accepted inbound frame into a VehicleServices patch."""
    if name not in INBOUND:
        return {}
    if name == "LAB_climate":
        return {"climate_on": bool(decoded["climate_on"]), "ac_on": bool(decoded["ac_on"]),
                "rear_defrost": bool(decoded["rear_defrost"]), "fan_speed": int(decoded["fan_speed"]),
                "driver_temp_c": round(decoded["driver_temp_c"], 1),
                "passenger_temp_c": round(decoded["passenger_temp_c"], 1)}
    return {"exterior_light_mode": decoded["light_mode"] if decoded["light_mode"] in ("Off", "Parking", "On", "Auto") else "Off",
            "high_beams": bool(decoded["high_beams"]), "ambient_dark": bool(decoded["ambient_dark"])}


@dataclass
class PeriodicTransmitter:
    """Emit each lab frame at its defined period, with a rolling counter."""
    messages: tuple = field(default_factory=lambda: can_database.MESSAGES)
    counters: dict = field(default_factory=dict)
    next_due: dict = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)

    def due(self, now: float | None = None) -> list:
        now = time.monotonic() if now is None else now
        ready = []
        for message in self.messages:
            if not message.period_ms:
                continue
            deadline = self.next_due.get(message.name, now)
            if now >= deadline:
                self.next_due[message.name] = max(now, deadline) + message.period_ms / 1000
                ready.append(message)
        return ready

    def build(self, message, values: dict) -> Frame:
        counter = self.counters.get(message.name, 0)
        self.counters[message.name] = (counter + 1) & 0x0F
        return message.encode(values, counter)

    def tick(self, sim: Simulation, services: VehicleServices, now: float | None = None) -> list[Frame]:
        elapsed = (time.monotonic() if now is None else now) - self.started
        values = frame_values(sim, services, elapsed)
        return [self.build(message, values[message.name])
                for message in self.due(now) if message.name in values]


def snapshot(sim: Simulation, services: VehicleServices) -> list[dict]:
    """One frame per definition, for inspection in the UI or a test."""
    transmitter = PeriodicTransmitter()
    values = frame_values(sim, services)
    return [transmitter.build(message, values[message.name]).as_dict()
            for message in can_database.MESSAGES if message.name in values]
