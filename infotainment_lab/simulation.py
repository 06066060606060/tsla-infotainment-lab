"""Validated, local-only simulator state. No vehicle transport is implemented."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import math


@dataclass
class Simulation:
    gear: str = "P"
    speed_kph: float = 0
    throttle_pct: float = 0
    brake_pct: float = 0
    steering_deg: float = 0
    indicator: str = "off"

    @classmethod
    def parse(cls, value: dict) -> "Simulation":
        if not isinstance(value, dict) or set(value) - set(cls.__dataclass_fields__):
            raise ValueError("Unknown simulator field.")
        result = cls(**value)
        if result.gear not in ("P", "R", "N", "D"):
            raise ValueError("Gear must be P, R, N or D.")
        if result.indicator not in ("off", "left", "right", "hazard"):
            raise ValueError("Unknown indicator state.")
        for key, low, high in (("speed_kph", 0, 200), ("throttle_pct", 0, 100),
                               ("brake_pct", 0, 100), ("steering_deg", -540, 540)):
            number = float(getattr(result, key))
            if not math.isfinite(number) or not low <= number <= high:
                raise ValueError(f"{key} must be between {low} and {high}.")
            setattr(result, key, number)
        if result.gear == "P":
            result.speed_kph = 0
            result.throttle_pct = 0
        return result

    def as_dict(self) -> dict:
        return asdict(self)

    def turning_radius_m(self) -> float | None:
        road_wheel_angle = math.radians(self.steering_deg / 15)
        return None if abs(road_wheel_angle) < .001 else abs(2.96 / math.tan(road_wheel_angle))


# These are display telemetry inputs. Acceptance is checked per field at runtime;
# a stored simulator value is never presented as proof of firmware support.
SIGNALS = {
    "gear": "VAPI_shiftState", "speed_kph": "VAPI_vehicleSpeed",
    "throttle_pct": "VAPI_pedalPos", "brake_pct": "VAPI_brakePedal",
    "steering_deg": "VAPI_steeringAngle", "indicator": "VAPI_signalLeft",
}


def display_values(sim: Simulation) -> dict[str, dict]:
    """Translate UI units into the tested MCU2 display's local telemetry values.

    Brake exposes a pressed/released flag. Pedal percentage remains a test
    value; there is no drivetrain or longitudinal physics simulation.
    """
    return {
        'gear': {'VAPI_shiftState': sim.gear},
        'speed_kph': {'VAPI_vehicleSpeed': sim.speed_kph / 3.6, 'VAPI_displaySpeed': sim.speed_kph},
        'throttle_pct': {'VAPI_pedalPos': sim.throttle_pct},
        'brake_pct': {'VAPI_brakePedal': sim.brake_pct > 0},
        'steering_deg': {'VAPI_steeringAngle': sim.steering_deg},
        'indicator': {'VAPI_signalLeft': sim.indicator in ('left', 'hazard'),
                      'VAPI_signalRight': sim.indicator in ('right', 'hazard')},
    }
