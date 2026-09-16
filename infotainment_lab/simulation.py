"""Validated, local-only simulator state. No vehicle transport is implemented."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import math

STEERING_RATIO = 14.8
WHEELBASE_M = 2.96


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
        road_wheel_angle = math.radians(self.steering_deg / STEERING_RATIO)
        return None if abs(road_wheel_angle) < .001 else abs(WHEELBASE_M / math.tan(road_wheel_angle))


# These are display telemetry inputs. Acceptance is checked per field at runtime;
# a stored simulator value is never presented as proof of firmware support.
SIGNALS = {
    "gear": "VAPI_shiftState", "speed_kph": "VAPI_vehicleSpeed",
    "throttle_pct": "VAPI_pedalPos", "brake_pct": "VAPI_brakePedal",
    "steering_deg": "VAPI_steeringAngle", "indicator": "VAPI_turnSignalActive",
}


def indicator_values(direction: str, elapsed_seconds: float = 0) -> dict:
    active = {'off': 'Off', 'left': 'Left', 'right': 'Right', 'hazard': 'Both'}[direction]
    left, right = direction in ('left', 'hazard'), direction in ('right', 'hazard')
    illuminated = int(max(0, elapsed_seconds) / .4) % 2 == 0
    return {'VAPI_signalLeft': left, 'VAPI_signalRight': right,
            'VAPI_turnSignalActive': active,
            'LIGHT_turnIndicatorLeft': 'On' if left and illuminated else 'Off',
            'LIGHT_turnIndicatorRight': 'On' if right and illuminated else 'Off'}


def display_values(sim: Simulation) -> dict[str, dict]:
    """Translate UI units into the tested MCU2 display's local telemetry values.

    Brake exposes a pressed/released flag. Pedal percentage remains a test
    value; there is no drivetrain or longitudinal physics simulation.
    """
    speed_mps = sim.speed_kph / 3.6
    signed_speed = -speed_mps if sim.gear == 'R' else speed_mps
    # MCU2 ApViz consumes road-wheel angle and yaw rate independently from the
    # steering-wheel widget. The 14.8:1 ratio and inverted firmware-model axis
    # match the validated TeslaCam 3D presentation pipeline; ApViz expects yaw
    # in rad/s.
    # Camera guide lines read VAPI_steeringAngle, not VAPI_roadWheelAngle.
    # Convert the native camera input separately; retain the recorded angle
    # in LOC_playbackSteeringAngle and in the desktop controls.
    road_wheel_deg = max(-36.0, min(36.0, -sim.steering_deg / STEERING_RATIO))
    yaw_rate = signed_speed / WHEELBASE_M * math.tan(math.radians(road_wheel_deg))
    return {
        'gear': {'VAPI_shiftState': sim.gear, 'LOC_playbackShiftState': sim.gear,
                 'VAPI_vehicleDirection': 1 if sim.gear == 'R' else 0},
        'speed_kph': {'VAPI_vehicleSpeed': speed_mps, 'VAPI_signedVehicleSpeed': signed_speed,
                      'VAPI_displaySpeed': sim.speed_kph,
                      'LOC_playbackGPS_vehicleSpeed': speed_mps},
        'throttle_pct': {'VAPI_pedalPos': sim.throttle_pct},
        'brake_pct': {'VAPI_brakePedal': sim.brake_pct > 0},
        'steering_deg': {'VAPI_steeringAngle': -sim.steering_deg,
                         'LOC_playbackSteeringAngle': sim.steering_deg,
                         'VAPI_roadWheelAngle': road_wheel_deg,
                         'VAPI_rearRoadWheelAngle': 0.0,
                         'VAPI_yawRate': yaw_rate,
                         'LOC_playbackYawRate': yaw_rate,
                         'LOC_playbackGPS_yawRate': yaw_rate},
        'indicator': indicator_values(sim.indicator),
    }
