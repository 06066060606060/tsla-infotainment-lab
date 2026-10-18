"""Display setting requests reach status values; no firmware or D-Bus needed.

The DataValue names here are fixtures. The router does not embed vendor names.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
from display_requests import (DroppedCalls, RequestRouter, load_routes, scan_request_names,  # noqa: E402
                              status_candidates)
from vehicle_services import DisplayWriter  # noqa: E402


class FakeDisplay:
    """A local DataValue store; names not in it are unsupported, like the firmware."""
    def __init__(self, values, enums=None):
        self.values = dict(values)
        self.enums = enums or {}
        self.writes = []

    def DataGetValueRequest(self, name, timeout=None):
        if name not in self.values:
            return False, ''
        value = self.values[name]
        return True, ('true' if value else 'false') if isinstance(value, bool) else str(value)

    def DataSetValueRequest(self, name, value, timeout=None):
        if name not in self.values or (name in self.enums and value not in self.enums[name]):
            return False
        self.writes.append((name, value))
        self.values[name] = value
        return True


def tap(display, router, writer, name, value):
    display.values[name] = value  # what QtCar does when the setting is touched
    return router.poll(writer)


def test_a_mode_request_is_accepted_into_its_paired_status_value():
    display = FakeDisplay({'GUI_driveProfileRequest': 'Sport', 'VAPI_driveProfile': 'Sport'},
                          enums={'VAPI_driveProfile': ('Chill', 'Sport', 'Ludicrous')})
    writer = DisplayWriter(display)
    router = RequestRouter(watched=['GUI_driveProfileRequest'])
    assert router.poll(writer) == {}  # the value present at connect is not a request
    assert tap(display, router, writer, 'GUI_driveProfileRequest', 'Ludicrous') == {
        'GUI_driveProfileRequest': {'VAPI_driveProfile': 'Ludicrous'}}
    assert display.values['VAPI_driveProfile'] == 'Ludicrous'
    assert router.report['GUI_driveProfileRequest']['result'] == 'accepted'
    assert router.accepted['GUI_driveProfileRequest'] == {'GUI_driveProfileRequest': 'Ludicrous',
                                                          'VAPI_driveProfile': 'Ludicrous'}
    assert router.poll(writer) == {}  # unchanged: accepted once


def test_explicit_route_maps_values_and_disables_pairing(tmp_path):
    (tmp_path / 'request-routes.json').write_text(json.dumps({
        'GUI_driveProfileRequest': {'status': 'VAPI_torqueMode', 'values': {'Ludicrous': 2}},
        'GUI_valetRequest': None, 'not a request': {'status': ['x']},
        'GUI_brokenRequest': {'status': 5}}))
    routes = load_routes(tmp_path / 'request-routes.json')
    assert routes == {'GUI_driveProfileRequest': {'status': ['VAPI_torqueMode'], 'values': {'Ludicrous': 2}},
                      'GUI_valetRequest': None}
    display = FakeDisplay({'GUI_driveProfileRequest': 'Sport', 'VAPI_torqueMode': 1,
                           'VAPI_driveProfile': 'Sport', 'GUI_valetRequest': False, 'VAPI_valet': False})
    writer = DisplayWriter(display)
    router = RequestRouter(watched=['GUI_driveProfileRequest', 'GUI_valetRequest'], routes=routes)
    assert router.names() == ['GUI_driveProfileRequest']
    router.poll(writer)
    tap(display, router, writer, 'GUI_driveProfileRequest', 'Ludicrous')
    assert display.values['VAPI_torqueMode'] == 2
    assert display.values['VAPI_driveProfile'] == 'Sport'  # the explicit route replaces pairing


def test_request_without_status_counterpart_is_logged_as_unrouted():
    display = FakeDisplay({'GUI_mysteryRequest': 0})
    writer = DisplayWriter(display)
    router = RequestRouter(watched=['GUI_mysteryRequest'])
    router.poll(writer)
    tap(display, router, writer, 'GUI_mysteryRequest', 3)
    assert router.report['GUI_mysteryRequest']['result'] == 'unrouted'
    assert router.log[-1]['request'] == 'GUI_mysteryRequest' and router.log[-1]['value'] == 3
    assert display.writes == [] and router.accepted == {}


def test_rejected_status_write_is_reported_and_owned_names_are_left_alone():
    display = FakeDisplay({'GUI_driveProfileRequest': 'Sport', 'VAPI_driveProfile': 'Sport',
                           'GUI_hvacOnRequest': False, 'VAPI_hvacOn': False},
                          enums={'VAPI_driveProfile': ('Sport',)})
    writer = DisplayWriter(display)
    router = RequestRouter(watched=['GUI_driveProfileRequest', 'GUI_hvacOnRequest'],
                           excluded={'GUI_hvacOnRequest'})
    router.poll(writer)
    tap(display, router, writer, 'GUI_driveProfileRequest', 'Ludicrous')
    display.values['GUI_hvacOnRequest'] = True
    router.poll(writer)
    assert router.report['GUI_driveProfileRequest']['result'] == 'rejected'
    assert 'GUI_driveProfileRequest' not in router.accepted
    assert 'GUI_hvacOnRequest' not in router.report and display.values['VAPI_hvacOn'] is False


def test_accepted_values_are_restored_when_the_display_restarts():
    router = RequestRouter(watched=['GUI_driveProfileRequest'], accepted={
        'GUI_driveProfileRequest': {'GUI_driveProfileRequest': 'Ludicrous', 'VAPI_driveProfile': 'Ludicrous'}})
    restarted = FakeDisplay({'GUI_driveProfileRequest': 'Sport', 'VAPI_driveProfile': 'Sport'})
    writer = DisplayWriter(restarted)
    router.restore(writer)
    assert restarted.values == {'GUI_driveProfileRequest': 'Ludicrous', 'VAPI_driveProfile': 'Ludicrous'}
    assert router.poll(writer) == {}  # our own restore is not a new request


def test_whole_numbers_read_back_as_text_are_written_as_integers():
    display = FakeDisplay({'GUI_levelRequest': 0, 'VAPI_level': 0})
    writer = DisplayWriter(display)
    router = RequestRouter(watched=['GUI_levelRequest'])
    router.poll(writer)
    tap(display, router, writer, 'GUI_levelRequest', 2)
    assert ('VAPI_level', 2) in display.writes and isinstance(display.values['VAPI_level'], int)


def test_status_candidates_only_for_request_names():
    assert status_candidates('GUI_driveProfileRequest')[:2] == ['VAPI_driveProfile', 'VAPI_driveProfileStatus']
    assert 'VAPI_isDriveProfile' in status_candidates('GUI_driveProfileRequest')
    assert status_candidates('VAPI_driveProfile') == status_candidates('GUI_Request') == []


def test_request_names_are_scanned_from_firmware_binaries(tmp_path):
    (tmp_path / 'bin').mkdir()
    (tmp_path / 'lib').mkdir()
    (tmp_path / 'bin/QtCar').write_bytes(b'\0GUI_driveProfileRequest\0xGUI_notOneRequestX\0GUI_seatRequest\0')
    (tmp_path / 'lib/libQtCarVehicle.so.1').write_bytes(b'\0GUI_trailerRequest\0VAPI_driveProfile\0LIGHT_fogLeft\0')
    (tmp_path / 'lib/libOther.so').write_bytes(b'\0GUI_ignoredRequest\0')
    assert scan_request_names(tmp_path) == (['GUI_driveProfileRequest', 'GUI_seatRequest', 'GUI_trailerRequest'],
                                            ['LIGHT_fogLeft', 'VAPI_driveProfile'])
    assert scan_request_names(tmp_path / 'missing') == ([], [])


def test_firmware_names_containing_the_stem_are_paired_by_kind():
    known = {'VAPI_frontFogLights', 'LIGHT_frontFogLeft', 'VAPI_frontFogLightsPresent', 'VAPI_frontFogLevel',
             'GUI_frontFogRequest', 'VAPI_rearFogLights'}
    candidates = status_candidates('GUI_frontFogRequest', known)
    assert candidates[8:] == ['LIGHT_frontFogLeft', 'VAPI_frontFogLevel', 'VAPI_frontFogLights']  # no config names
    display = FakeDisplay({'GUI_frontFogRequest': False, 'VAPI_frontFogLights': False, 'LIGHT_frontFogLeft': 'Off',
                           'VAPI_frontFogLevel': 0, 'VAPI_frontFogLightsPresent': True, 'VAPI_rearFogLights': False})
    writer = DisplayWriter(display)
    router = RequestRouter(watched=['GUI_frontFogRequest'], known=known)
    router.poll(writer)
    tap(display, router, writer, 'GUI_frontFogRequest', True)
    assert display.values['VAPI_frontFogLights'] is True and display.values['LIGHT_frontFogLeft'] == 'On'
    assert display.values['VAPI_frontFogLevel'] == 0 and display.values['VAPI_rearFogLights'] is False
    assert router.report['GUI_frontFogRequest']['result'] == 'accepted'


def test_refused_value_reports_what_the_display_holds_and_unrouted_lists_related_names():
    class Enum(FakeDisplay):
        def DataSetValueRequest(self, name, value, timeout=None):
            return True  # accepted by the setter, but the enum keeps its value
    display = Enum({'GUI_mirrorFoldRequest': 'Present', 'VAPI_mirrorFoldState': 'Unfolded', 'GUI_dragRequest': 'Off'})
    writer = DisplayWriter(display)
    router = RequestRouter(watched=['GUI_mirrorFoldRequest', 'GUI_dragRequest'], known={'VAPI_dragStripArmed'})
    router.poll(writer)
    tap(display, router, writer, 'GUI_mirrorFoldRequest', 'Retract')
    assert router.report['GUI_mirrorFoldRequest']['read_back'] == {'VAPI_mirrorFoldState': 'Unfolded'}
    tap(display, router, writer, 'GUI_dragRequest', 'On')
    assert router.report['GUI_dragRequest'] == {'value': 'On', 'status': {}, 'result': 'unrouted',
                                                'related': ['VAPI_dragStripArmed']}


def test_dropped_dbus_calls_are_counted_by_service_and_method():
    calls = DroppedCalls()
    lines = [
        'error time=1.0 sender=org.freedesktop.DBus -> destination=:1.5 error_name=org.freedesktop.DBus.Error.ServiceUnknown reply_serial=9',
        '   string "The name com.example.Vehicle was not provided by any .service files"',
        'error time=1.1 sender=:1.2 -> destination=:1.5 error_name=org.freedesktop.DBus.Error.UnknownMethod reply_serial=10',
        '   string "No such method \'setMode\' in interface \'com.example.Drive\' at object path \'/\' (signature \'s\')"',
        'error time=1.2 sender=:1.2 -> destination=:1.5 error_name=com.example.Busy reply_serial=11',
        '   string "busy"',
        'error time=1.25 sender=org.freedesktop.DBus -> destination=:1.5 error_name=org.freedesktop.DBus.Error.NameHasNoOwner reply_serial=13',
        '   string "Could not get owner of name \'com.example.Vehicle\': no such name"',
        'error time=1.3 sender=org.freedesktop.DBus -> destination=:1.5 error_name=org.freedesktop.DBus.Error.ServiceUnknown reply_serial=12',
        '   string "The name com.example.Vehicle was not provided by any .service files"',
    ]
    for index, line in enumerate(lines):
        calls.feed(line, float(index))
    counts = calls.snapshot()
    assert set(counts) == {'com.example.Vehicle', 'com.example.Drive.setMode'}
    assert counts['com.example.Vehicle']['count'] == 3 and counts['com.example.Vehicle']['error'] == 'ServiceUnknown'
    assert counts['com.example.Drive.setMode']['error'] == 'UnknownMethod'


def test_a_limited_poll_reads_one_window_and_still_covers_every_name():
    names = [f'GUI_setting{i}Request' for i in range(5)]
    display = FakeDisplay({name: 'Off' for name in names})
    reads = []
    get = display.DataGetValueRequest
    display.DataGetValueRequest = lambda name, timeout=None: reads.append(name) or get(name)
    writer = DisplayWriter(display)
    router = RequestRouter(watched=names)
    for _ in range(3):  # 3 windows of 2 cover all 5 names (wrapping), establishing baselines
        router.poll(writer, limit=2)
    assert len(reads) == 6 and set(reads) == set(names)
    display.values[names[4]] = 'On'
    changed = {}
    for _ in range(3):
        changed.update(router.poll(writer, limit=2))
    assert names[4] in changed  # a change is still picked up within one sweep
