import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
import gps_feed  # noqa: E402


def test_checksum_matches_the_nmea_reference_sentence():
    body = 'GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W'
    assert gps_feed.checksum(body) == '6A'


def test_fix_encodes_madrid_as_a_rated_3d_fix():
    when = datetime.datetime(2026, 10, 11, 12, 34, 56, tzinfo=datetime.timezone.utc)
    rmc, gga, gsa = gps_feed.fix_sentences(40.4168, -3.7038, when).splitlines()
    body, digest = rmc[1:].split('*')
    assert body.split(',')[:7] == ['GPRMC', '123456.00', 'A', '4025.0080', 'N', '00342.2280', 'W']
    assert digest.strip() == gps_feed.checksum(body)
    assert gga.split(',')[6] == '1' and gga.split(',')[7] == '08'  # GPS fix, eight satellites
    assert gsa.split(',')[2] == '3'  # 3D fix


def test_position_reads_the_session_vehicle_services(tmp_path):
    services = tmp_path / 'vehicle-services.json'
    assert gps_feed.position(tmp_path) is None
    services.write_text('{"latitude_deg": 40.4168, "longitude_deg": -3.7038}')
    assert gps_feed.position(tmp_path) == (40.4168, -3.7038)
    services.write_text('{"latitude_deg": null, "longitude_deg": null}')
    assert gps_feed.position(tmp_path) is None


def test_point_at_follows_the_track_and_holds_at_the_end():
    track = [(40.0, -3.0), (40.0, -2.99), (40.01, -2.99)]  # east, then north
    east = gps_feed.distance_m(track[0], track[1])
    lat, lon, course = gps_feed.point_at(track, east / 2)
    assert abs(lat - 40.0) < 1e-9 and abs(lon - (-3.0 + 0.005)) < 1e-6
    assert abs(course - 90) < 0.5  # heading east along the first leg
    lat, lon, course = gps_feed.point_at(track, 10**9)
    assert (lat, lon) == track[-1]
    assert abs(course - 0) < 0.5  # heading north at the end


def test_track_is_read_from_the_session_and_moves_the_fix(tmp_path):
    (tmp_path / 'gps-track.json').write_text('{"points": [[40.0, -3.0], [40.0, -2.99]]}')
    assert gps_feed.track(tmp_path) == [(40.0, -3.0), (40.0, -2.99)]
    when = datetime.datetime(2026, 10, 11, 12, 0, 0, tzinfo=datetime.timezone.utc)
    rmc = gps_feed.fix_sentences(40.0, -3.0, when, speed_mps=12.0, course=90.0).splitlines()[0]
    fields = rmc.split('*')[0].split(',')
    assert abs(float(fields[7]) - 12.0 * gps_feed.KNOTS_PER_MPS) < 0.1  # speed in knots
    assert float(fields[8]) == 90.0  # course over ground


def test_publish_position_moves_the_session_position_and_keeps_the_rest(tmp_path):
    services = tmp_path / 'vehicle-services.json'
    services.write_text('{"climate_on": true, "latitude_deg": 40.4168, "longitude_deg": -3.7038}')
    gps_feed.publish_position(tmp_path, 40.41, -3.70, 135.0)
    data = json.loads(services.read_text())
    assert (data['latitude_deg'], data['longitude_deg'], data['heading_deg']) == (40.41, -3.70, 135.0)
    assert data['climate_on'] is True
    assert not (tmp_path / 'vehicle-services.json.tmp').exists()


def test_track_speed_comes_from_the_track_file_with_a_default(tmp_path):
    assert gps_feed.track_speed(tmp_path) == gps_feed.TRACK_SPEED_MPS
    (tmp_path / 'gps-track.json').write_text('{"points": [[40.0, -3.0]], "speed_mps": 30}')
    assert gps_feed.track_speed(tmp_path) == 30.0
    (tmp_path / 'gps-track.json').write_text('{"points": [[40.0, -3.0]], "speed_mps": -4}')
    assert gps_feed.track_speed(tmp_path) == gps_feed.TRACK_SPEED_MPS
