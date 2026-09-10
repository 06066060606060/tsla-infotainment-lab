"""Local vehicle display model and deterministic preference reconciliation.

Only the desktop session's DataValue interfaces consume these values. The model
does not contain an ECU, radio, account, charging-station, or vehicle transport.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass
class VehicleServices:
    climate_on: bool = True
    cabin_temp_c: float = 22
    outside_temp_c: float = 20
    driver_temp_c: float = 21
    passenger_temp_c: float = 21
    fan_speed: int = 1
    ac_on: bool = False
    rear_defrost: bool = False
    driver_door_open: bool = False
    passenger_door_open: bool = False
    rear_left_door_open: bool = False
    rear_right_door_open: bool = False
    front_trunk_open: bool = False
    rear_trunk_open: bool = False
    locked: bool = False
    headlights: bool = False
    high_beams: bool = False
    battery_percent: float = 50
    charge_limit_pct: float = 80
    charging: bool = False
    charge_power_kw: float = 7.2
    volume_pct: float = 40
    muted: bool = False
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    heading_deg: float | None = None
    nav_destination: str = ""
    nav_distance_km: float = 0
    nav_eta_min: float = 0
    tire_fl_bar: float = 2.9
    tire_fr_bar: float = 2.9
    tire_rl_bar: float = 2.9
    tire_rr_bar: float = 2.9

    @classmethod
    def parse(cls, value: dict) -> "VehicleServices":
        if not isinstance(value, dict) or set(value) - set(FIELD_SPECS):
            raise ValueError("Unknown vehicle service field.")
        result = cls(**value)
        for name, spec in FIELD_SPECS.items():
            raw = getattr(result, name)
            if raw is None and spec.get("nullable"):
                continue
            if spec["type"] == "bool":
                if type(raw) is not bool:
                    raise ValueError(f"{name} must be true or false.")
            elif spec["type"] == "str":
                if not isinstance(raw, str) or len(raw) > 160 or any(ord(c) < 32 for c in raw):
                    raise ValueError(f"{name} must be a single line of at most 160 characters.")
            else:
                if isinstance(raw, bool):
                    raise ValueError(f"{name} must be a number.")
                try:
                    number = float(raw)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{name} must be a number.") from exc
                if not math.isfinite(number) or not spec["min"] <= number <= spec["max"]:
                    raise ValueError(f"{name} must be between {spec['min']} and {spec['max']}.")
                if spec["type"] == "int" and number != int(number):
                    raise ValueError(f"{name} must be a whole number.")
                setattr(result, name, int(number) if spec["type"] == "int" else number)
        if (result.latitude_deg is None) != (result.longitude_deg is None):
            raise ValueError("Latitude and longitude must be supplied together.")
        return result

    def as_dict(self) -> dict:
        return asdict(self)

    def patched(self, patch: dict) -> "VehicleServices":
        if not isinstance(patch, dict):
            raise ValueError("Vehicle service changes must be an object.")
        return self.parse(self.as_dict() | patch)


def _field(group, label, zh, kind="float", low=0, high=100, **extra):
    return {"group": group, "label": label, "label_zh": zh, "type": kind,
            "min": low, "max": high, **extra}


FIELD_SPECS = {
    "climate_on": _field("climate", "Climate power", "空调电源", "bool"),
    "cabin_temp_c": _field("climate", "Cabin temperature (°C)", "车内温度 (°C)", low=-40, high=70),
    "outside_temp_c": _field("climate", "Outside temperature (°C)", "室外温度 (°C)", low=-50, high=70),
    "driver_temp_c": _field("climate", "Driver temperature (°C)", "主驾设定温度 (°C)", low=15, high=30),
    "passenger_temp_c": _field("climate", "Passenger temperature (°C)", "副驾设定温度 (°C)", low=15, high=30),
    "fan_speed": _field("climate", "Fan speed", "风速", "int", 0, 10),
    "ac_on": _field("climate", "A/C", "制冷", "bool"),
    "rear_defrost": _field("climate", "Rear defrost request", "后窗除霜请求", "bool"),
    "driver_door_open": _field("closures", "Driver door open", "主驾车门打开", "bool"),
    "passenger_door_open": _field("closures", "Passenger door open", "副驾车门打开", "bool"),
    "rear_left_door_open": _field("closures", "Rear left door open", "左后车门打开", "bool"),
    "rear_right_door_open": _field("closures", "Rear right door open", "右后车门打开", "bool"),
    "front_trunk_open": _field("closures", "Front trunk open", "前备箱打开", "bool"),
    "rear_trunk_open": _field("closures", "Rear trunk open", "后备箱打开", "bool"),
    "locked": _field("closures", "Doors locked", "车门锁定", "bool"),
    "headlights": _field("lights", "Headlights", "前照灯", "bool"),
    "high_beams": _field("lights", "High beams", "远光灯", "bool"),
    "battery_percent": _field("energy", "Battery (%)", "电量 (%)"),
    "charge_limit_pct": _field("energy", "Charge limit (%)", "充电上限 (%)", low=50, high=100),
    "charging": _field("energy", "Charging", "充电中", "bool"),
    "charge_power_kw": _field("energy", "Charging power (kW)", "充电功率 (kW)", low=0, high=350),
    "volume_pct": _field("audio", "Volume (%)", "音量 (%)"),
    "muted": _field("audio", "Mute", "静音", "bool"),
    "latitude_deg": _field("navigation", "Latitude", "纬度", low=-90, high=90, nullable=True),
    "longitude_deg": _field("navigation", "Longitude", "经度", low=-180, high=180, nullable=True),
    "heading_deg": _field("navigation", "Heading (°)", "航向 (°)", low=0, high=360, nullable=True),
    "nav_destination": _field("navigation", "Destination label", "目的地名称", "str"),
    "nav_distance_km": _field("navigation", "Distance remaining (km)", "剩余距离 (km)", low=0, high=50000),
    "nav_eta_min": _field("navigation", "Time remaining (min)", "剩余时间 (min)", low=0, high=100000),
    **{f"tire_{wheel}_bar": _field("tires", f"{label} pressure (bar)", f"{zh}胎压 (bar)", low=0, high=5)
       for wheel, label, zh in (("fl", "Front left", "左前"), ("fr", "Front right", "右前"),
                               ("rl", "Rear left", "左后"), ("rr", "Rear right", "右后"))},
}

CAPABILITIES = {
    "climate": {"mode": "local-display", "detail": "Climate requests and temperature/fan telemetry; no thermal physics."},
    "closures": {"mode": "local-display", "detail": "Door/trunk open indicators and lock status; individual 3D latch animation is unverified."},
    "lights": {"mode": "local-display", "detail": "Headlight/high-beam indicators and lighting telemetry."},
    "energy": {"mode": "local-display", "detail": "Battery and charging telemetry; no battery or charging-station model."},
    "audio": {"mode": "host-backed", "detail": "Volume and mute for firmware audio streams on the host."},
    "navigation": {"mode": "local-display", "detail": "GPS, heading, destination and remaining trip metadata; offline NA imagery, route computation and live traffic remain unverified."},
    "tires": {"mode": "local-model", "detail": "Pressure values are stored locally; native TPMS units have not been verified."},
    "vehicle_hardware": {"mode": "unavailable", "detail": "Physical ECU/CAN, powertrain, charging equipment and vehicle sensors are not connected."},
    "account_services": {"mode": "unavailable", "detail": "Tesla account, phone key, cellular provisioning, payments and cloud-only services are not emulated."},
    "driver_assistance": {"mode": "recorded-metadata", "detail": "Dashcam ADAS state can be inspected as recorded metadata; no driving-assistance controller runs."},
}


def display_values(model: VehicleServices, volume_max: float = 10.333) -> dict[str, dict]:
    """Return only observed desktop fields; workers check support and readback."""
    v = model
    open_door = any((v.driver_door_open, v.passenger_door_open, v.rear_left_door_open, v.rear_right_door_open))
    result = {
        "climate_on": {"GUI_hvacOnRequest": v.climate_on, "GUI_hvacOnRequestForIC": v.climate_on,
                       "VAPI_hvacRailOn": v.climate_on, "HVAC_powerState": "On" if v.climate_on else "Off"},
        "cabin_temp_c": {"HVAC_insideTemp": v.cabin_temp_c, "HVAC_insideTempValid": True},
        "outside_temp_c": {"HVAC_outsideTemp": v.outside_temp_c, "HVAC_outsideTempForIC": v.outside_temp_c},
        "driver_temp_c": {"GUI_hvacLeftTempRequest": v.driver_temp_c, "GUI_hvacLeftTempRequestForIC": v.driver_temp_c,
                          "HVAC_driverTempStatus": v.driver_temp_c},
        "passenger_temp_c": {"GUI_hvacRightTempRequest": v.passenger_temp_c, "GUI_hvacRightTempRequestForIC": v.passenger_temp_c,
                             "HVAC_passengerTempStatus": v.passenger_temp_c},
        "fan_speed": {"GUI_hvacFanSpeedRequest": v.fan_speed, "GUI_hvacFanSpeedRequestForIC": v.fan_speed,
                      "HVAC_fanStatus": v.fan_speed if v.climate_on else 0},
        "ac_on": {"GUI_hvacACOnRequest": v.ac_on, "HVAC_aconStatus": v.ac_on and v.climate_on},
        "rear_defrost": {"GUI_hvacRearDefrostRequest": v.rear_defrost},
        "driver_door_open": {"VAPI_driverDoorAlert": v.driver_door_open, "VAPI_doorAlert": open_door},
        "passenger_door_open": {"VAPI_doorAlert": open_door},
        "rear_left_door_open": {"VAPI_doorAlert": open_door},
        "rear_right_door_open": {"VAPI_doorAlert": open_door},
        "front_trunk_open": {"VAPI_frontTrunkAlert": v.front_trunk_open},
        "rear_trunk_open": {"VAPI_rearTrunkAlert": v.rear_trunk_open},
        "locked": {name: v.locked for name in ("VAPI_isLocked", "VAPI_frontDriverDoorLocked", "VAPI_frontPassengerDoorLocked",
                                               "VAPI_rearDriverDoorLocked", "VAPI_rearPassengerDoorLocked", "VAPI_trunkLocked")},
        "headlights": {"VAPI_headLights": v.headlights, "VAPI_telltaleHeadlights": v.headlights,
                       "LIGHT_headlightLeft": "On" if v.headlights else "Off", "LIGHT_headlightRight": "On" if v.headlights else "Off"},
        "high_beams": {"VAPI_highBeamLights": v.high_beams, "LIGHT_highBeamLeft": "On" if v.high_beams else "Off",
                       "LIGHT_highBeamRight": "On" if v.high_beams else "Off"},
        "battery_percent": {"VAPI_batteryLevel": v.battery_percent, "VAPI_usableBatteryLevel": v.battery_percent},
        "charge_limit_pct": {"GUI_chargeLimitRequest": v.charge_limit_pct},
        "charging": {"VAPI_isCharging": v.charging, "GUI_chargeSessionActive": v.charging},
        "charge_power_kw": {"VAPI_chargerPower": v.charge_power_kw if v.charging else 0.0},
        "volume_pct": {"GUI_audioVolume": v.volume_pct / 100 * volume_max},
        "muted": {"GUI_muteAudioRequest": v.muted},
        "nav_destination": {"GUI_navDestinationLocationName": v.nav_destination},
        "nav_distance_km": {"GUI_navMilesToNextDestination": v.nav_distance_km / 1.609344},
        "nav_eta_min": {"GUI_navSecondsToNextDestination": v.nav_eta_min * 60},
        **{name: {} for name in ("tire_fl_bar", "tire_fr_bar", "tire_rl_bar", "tire_rr_bar")},
    }
    if v.latitude_deg is not None and v.longitude_deg is not None:
        result["latitude_deg"] = {"LOC_geoLat": v.latitude_deg, "NAV_vehicleLatitude": v.latitude_deg, "LOC_geoValidFix": True}
        result["longitude_deg"] = {"LOC_geoLon": v.longitude_deg, "NAV_vehicleLongitude": v.longitude_deg}
    else:
        result["latitude_deg"] = {"LOC_geoValidFix": False}
        result["longitude_deg"] = {}
    if v.heading_deg is not None:
        result["heading_deg"] = {"LOC_geoHdg": v.heading_deg % 360}
    return result


# Native UI changes to these request fields update the local model. They are
# observed, never used as authority to send requests to physical services.
REQUEST_FIELDS = {
    "climate_on": "GUI_hvacOnRequest", "driver_temp_c": "GUI_hvacLeftTempRequest",
    "passenger_temp_c": "GUI_hvacRightTempRequest", "fan_speed": "GUI_hvacFanSpeedRequest",
    "ac_on": "GUI_hvacACOnRequest", "rear_defrost": "GUI_hvacRearDefrostRequest",
    "charge_limit_pct": "GUI_chargeLimitRequest", "muted": "GUI_muteAudioRequest",
    "volume_pct": "GUI_audioVolume",
}

PREFERENCES = (
    "GUI_distanceUnits", "GUI_temperatureUnits", "GUI_chargeUnits", "GUI_tirePressureUnits",
    "GUI_audioVolume", "GUI_muteAudioRequest", "GUI_navAudioVolume", "GUI_responseAudioVolume",
    "GUI_timeZoneId", "GUI_timeZoneOffset", "GUI_clockFormat", "GUI_timeFormat",
)


def decode_value(raw):
    text = str(raw)
    if text in ("", "<invalid>"):
        return None
    if text in ("true", "false"):
        return text == "true"
    try:
        number = float(text)
        return number if math.isfinite(number) else None
    except ValueError:
        return text


def equivalent(left, right) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        # This interface renders floating values with three fractional digits.
        # Allow only half that final digit (plus floating arithmetic noise).
        return abs(left - right) <= .0005000001
    return left == right


class PreferenceSync:
    """Reconcile changes from either display; center wins simultaneous conflicts."""
    def __init__(self):
        self.baseline = {}

    def choose(self, name, center, cluster, restarted=()):
        if equivalent(center, cluster):
            self.baseline[name] = center
            return None, center, False
        if center is None:
            return "cluster", cluster, False
        if cluster is None:
            return "center", center, False
        if "cluster" in restarted and "center" not in restarted:
            return "center", center, False
        if "center" in restarted and "cluster" not in restarted:
            return "cluster", cluster, False
        if name not in self.baseline:
            return "center", center, False
        old = self.baseline[name]
        center_changed, cluster_changed = not equivalent(center, old), not equivalent(cluster, old)
        if cluster_changed and not center_changed:
            return "cluster", cluster, False
        return "center", center, center_changed and cluster_changed

    def accepted(self, name, value):
        self.baseline[name] = value


def speed_display_values(speed_kph: float, distance_units: str) -> dict:
    metric = distance_units == "Kilometers"
    # The MCU2 display-speed DV is an integer. Supply the intended rounded
    # speed explicitly; its vehicle-speed DV keeps the precise m/s value.
    displayed = speed_kph if metric else speed_kph / 1.609344
    return {"VAPI_vehicleSpeed": speed_kph / 3.6,
            "VAPI_displaySpeed": int(math.floor(displayed + .5))}


def replay_location(status: dict, request: dict, now: float) -> VehicleServices | None:
    """Select GPS belonging to an already committed, currently owned video frame."""
    try:
        if (status.get("phase") not in ("playing", "paused", "ended")
                or status.get("frame_ready") is not True
                or not 0 <= now - float(status.get("updated_at", 0)) <= 1
                or (request.get("action") == "manual" and request.get("id") != status.get("request_id"))):
            return None
        metadata = status.get("recorded_metadata") or {}
        return VehicleServices.parse({key: metadata.get(key)
                                      for key in ("latitude_deg", "longitude_deg", "heading_deg")})
    except (ValueError, TypeError, AttributeError):
        return None


class DisplayWriter:
    """Apply changed values and report what the display actually read back.

    The small adapter is independent of dbus-python so ordinary fake display
    tests exercise rejected fields and reconnects without launching firmware.
    """
    def __init__(self, interface, typed=lambda value: value):
        self.interface = interface
        self.typed = typed
        self.cache = {}
        self.supported = {}
        self.feedback = {}

    def read(self, name):
        if self.supported.get(name) is False:
            return False, None
        ok, raw = self.interface.DataGetValueRequest(name, timeout=.3)
        self.supported[name] = bool(ok)
        if not ok:
            return False, None
        return bool(ok), "" if ok and str(raw) == "" else decode_value(raw)

    def apply(self, groups, verify_cached=False):
        report, details = {}, {}
        for field, values in groups.items():
            statuses = {}
            for name, requested in values.items():
                if self.supported.get(name) is False:
                    statuses[name] = "unsupported"
                    continue
                if name in self.cache and equivalent(self.cache[name], requested) and not verify_cached:
                    statuses[name] = "accepted"
                    continue
                ok, actual = self.read(name)
                self.supported[name] = ok
                if not ok:
                    statuses[name] = "unsupported"
                    continue
                if not equivalent(actual, requested):
                    if not self.interface.DataSetValueRequest(name, self.typed(requested), timeout=.3):
                        statuses[name] = "rejected"
                        continue
                    ok, actual = self.read(name)
                status = "accepted" if ok and equivalent(actual, requested) else "mismatch"
                statuses[name] = status
                if status == "accepted":
                    self.cache[name] = requested
                else:
                    self.cache.pop(name, None)
            details[field] = statuses
            kinds = set(statuses.values())
            report[field] = ("local-model" if not kinds else "accepted" if kinds == {"accepted"}
                             else "partial" if "accepted" in kinds else sorted(kinds)[0])
        self.feedback = report
        return report, details
