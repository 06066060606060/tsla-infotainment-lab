"""Send the simulated vehicle position to the firmware's GPS manager as NMEA sentences.

QtCarGpsManager listens for NMEA on UDP and publishes the fix that navigation uses.
The position comes from the session's vehicle-services.json, so the lab's location
controls drive navigation the same way the firmware's GPS hardware would. When the
session has a gps-track.json (a road polyline, [[lat, lon], ...]), the position moves
along that track at a fixed speed, so the firmware can map-match a moving vehicle.
"""
import datetime
import json
import math
import socket
import sys
import time
from pathlib import Path

TRACK_SPEED_MPS = 12.0  # about 43 km/h along the track
KNOTS_PER_MPS = 1.943844


def checksum(body: str) -> str:
    value = 0
    for char in body:
        value ^= ord(char)
    return f'{value:02X}'


def coordinate(value: float, degree_digits: int) -> str:
    degrees = int(abs(value))
    return f'{degrees:0{degree_digits}d}{(abs(value) - degrees) * 60:07.4f}'


def sentence(body: str) -> str:
    return f'${body}*{checksum(body)}\r\n'


def fix_sentences(lat: float, lon: float, when: datetime.datetime, speed_mps: float = 0.0, course: float = 0.0) -> str:
    """RMC, GGA and GSA for a valid 3D fix at lat/lon (decimal degrees) at UTC time `when`.

    The firmware's estimator rejects a fix it cannot rate: GGA gives the quality and satellite
    count, GSA the fix type, so RMC alone resets the position to the firmware default.
    """
    ns, ew = ('N' if lat >= 0 else 'S'), ('E' if lon >= 0 else 'W')
    time = f'{when:%H%M%S}.00'
    rmc_body = (f'GPRMC,{time},A,{coordinate(lat, 2)},{ns},{coordinate(lon, 3)},{ew},'
                f'{speed_mps * KNOTS_PER_MPS:.1f},{course:.1f},{when:%d%m%y},,,A')
    gga_body = f'GPGGA,{time},{coordinate(lat, 2)},{ns},{coordinate(lon, 3)},{ew},1,08,1.0,10.0,M,0.0,M,,'
    gsa_body = 'GPGSA,A,3,01,02,03,04,05,06,07,08,,,,,1.0,1.0,1.0'
    return ''.join(sentence(body) for body in (rmc_body, gga_body, gsa_body))


def distance_m(a, b) -> float:
    """Great-circle distance in metres between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def bearing(a, b) -> float:
    """Initial bearing in degrees, clockwise from north, from a to b."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return math.degrees(math.atan2(y, x)) % 360


def point_at(points, distance: float):
    """(lat, lon, course) after `distance` metres along the track; holds the last point at the end."""
    remaining = distance
    for a, b in zip(points, points[1:]):
        step = distance_m(a, b)
        if step > 0 and remaining <= step:
            fraction = remaining / step
            lat = a[0] + (b[0] - a[0]) * fraction
            lon = a[1] + (b[1] - a[1]) * fraction
            return lat, lon, bearing(a, b)
        remaining -= step
    if len(points) < 2:
        return points[0][0], points[0][1], 0.0
    return points[-1][0], points[-1][1], bearing(points[-2], points[-1])


def track(state: Path):
    try:
        points = json.loads((state / 'gps-track.json').read_text())['points']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return [tuple(point) for point in points] if points else None


def track_speed(state: Path) -> float:
    """The track's speed in m/s; gps-track.json may set speed_mps, otherwise the default applies."""
    try:
        speed = float(json.loads((state / 'gps-track.json').read_text()).get('speed_mps', TRACK_SPEED_MPS))
    except (OSError, ValueError, TypeError, AttributeError):
        return TRACK_SPEED_MPS
    return speed if speed > 0 else TRACK_SPEED_MPS


def position(state: Path):
    try:
        data = json.loads((state / 'vehicle-services.json').read_text())
    except (OSError, ValueError):
        return None
    lat, lon = data.get('latitude_deg'), data.get('longitude_deg')
    return (lat, lon) if lat is not None and lon is not None else None


def publish_position(state: Path, lat: float, lon: float, course: float) -> None:
    """Write the moving position into the session's vehicle services, so the displays and map follow it."""
    path = state / 'vehicle-services.json'
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return
    data.update(latitude_deg=lat, longitude_deg=lon, heading_deg=course)
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(data))
    temporary.replace(path)


def main(argv):
    state, host, port = Path(argv[1]), argv[2], int(argv[3])
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    started = time.monotonic()
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        points = track(state)
        if points:
            speed = track_speed(state)
            lat, lon, course = point_at(points, speed * (time.monotonic() - started))
            moving = (lat, lon) != points[-1]
            sock.sendto(fix_sentences(lat, lon, now, speed if moving else 0.0, course).encode('ascii'), (host, port))
            publish_position(state, lat, lon, course)
        else:
            fix = position(state)
            if fix:
                sock.sendto(fix_sentences(*fix, now).encode('ascii'), (host, port))
        time.sleep(1)


if __name__ == '__main__':
    main(sys.argv)
