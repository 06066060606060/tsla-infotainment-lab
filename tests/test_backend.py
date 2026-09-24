"""Linux worker boundaries with temporary files; no real firmware or services."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Linux worker uses distribution modules')
if os.name != 'nt':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
    import backend
    import supervisor


def test_staged_session_imports_without_source_checkout(tmp_path):
    import subprocess

    runtime = tmp_path / 'engine'
    backend.stage_runtime(runtime)
    # A packaged launcher may disappear before the user service starts. Import
    # from its persistent copy, with no checkout or inherited Python path.
    smoke = runtime / 'import_check.py'
    smoke.write_text('import supervisor, display_bus, simulation, replay, vehicle_services\n')
    env = {key: value for key, value in os.environ.items() if not key.startswith('PYTHON')}
    result = subprocess.run([sys.executable, '-E', str(smoke)], cwd=tmp_path,
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (runtime / 'profiles.json').is_file()
    assert (runtime / 'runtime/keep-awake.py').is_file()


def test_media_port_conflict_reports_the_port_without_starting_services(monkeypatch):
    import socket
    class BusyPort:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def setsockopt(self, *_): pass
        def bind(self, address):
            if address[1] == 9001:
                raise OSError('Address already in use')
    monkeypatch.setattr(socket, 'socket', lambda *_: BusyPort())
    with pytest.raises(RuntimeError, match='9001'):
        supervisor.check_media_ports()


def test_single_display_preflight_does_not_require_cluster(tmp_path):
    executable = tmp_path / 'usr/tesla/UI/bin/QtCar'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'\x7fELF\x02\x01' + bytes(12) + b'\x3e\x00')
    profile = {'experimental': True, 'single_display': True}
    backend.verify_builds(tmp_path, profile)
    executable.write_bytes(b'\x7fELF\x02\x01' + bytes(12) + b'\xb7\x00')
    with pytest.raises(ValueError, match='architecture'):
        backend.verify_builds(tmp_path, profile)


def test_native_service_directory_is_private_and_rejects_symlinks(tmp_path):
    private = tmp_path / 'dvaccess'
    supervisor.prepare_service_sockets(private)
    assert private.stat().st_mode & 0o777 == 0o700
    supervisor.prepare_service_sockets(private)
    linked = tmp_path / 'alias'
    linked.symlink_to(private, target_is_directory=True)
    with pytest.raises(RuntimeError, match='private directory'):
        supervisor.prepare_service_sockets(linked)
    private.chmod(0o755)
    with pytest.raises(RuntimeError, match='private directory'):
        supervisor.prepare_service_sockets(private)


def test_media_recovery_backs_off_and_stops_after_two_retries(monkeypatch):
    launches = []
    monkeypatch.setattr(supervisor, 'restart_specs', {'spotify': ('args', 'state', 'env')})
    monkeypatch.setattr(supervisor, 'children', {'spotify': SimpleNamespace(poll=lambda: 1)})
    monkeypatch.setattr(supervisor, 'service_retries', {})
    monkeypatch.setattr(supervisor, 'retry_after', {})
    monkeypatch.setattr(supervisor, 'launch', lambda *args: launches.append(args))
    for now in (0, 1, 2, 3, 6, 7, 20, 100):
        supervisor.recover_services(now)
    assert len(launches) == 2
    assert supervisor.service_retries == {'spotify': 2}


def test_changed_image_requires_reimport(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    image = tmp_path / 'original.mcu2'
    image.write_bytes(b'hsqs-data')
    item = {'id': 'a'*16, 'path': str(image), 'bytes': image.stat().st_size, 'mtime_ns': image.stat().st_mtime_ns}
    backend.atomic_json(tmp_path / 'library.json', [item])
    image.write_bytes(b'hsqs-changed-data')
    with pytest.raises(ValueError, match='changed after import'):
        backend.library_item(item['id'])


def test_mount_never_overlays_an_existing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    mount = tmp_path / 'mounts' / ('a'*16)
    mount.mkdir(parents=True)
    sentinel = mount / 'keep.txt'
    sentinel.write_text('preserve')
    with pytest.raises(RuntimeError, match='not empty'):
        backend.mounted_image({'id': 'a'*16, 'path': '/unused'})
    assert sentinel.read_text() == 'preserve'


def test_stop_is_idempotent_and_uses_only_owned_mounts(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    calls = []
    monkeypatch.setattr(backend, 'systemctl', lambda *a, **kw: calls.append(a) or SimpleNamespace(stdout='inactive', returncode=3))
    monkeypatch.setattr(backend, 'status', lambda: backend.load_json(tmp_path / 'session/status.json'))
    assert backend.stop()['phase'] == 'stopped'
    assert ('stop', backend.UNIT) not in calls


def test_build_check_rejects_executable_symlink_outside_mount(tmp_path):
    root = tmp_path / 'mount'
    binary = root / 'usr/tesla/UI/bin/QtCar'
    binary.parent.mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.write_bytes(b'not executable')
    binary.symlink_to(outside)
    with pytest.raises(ValueError, match='outside'):
        backend.verify_builds(root, {})


def test_only_recognized_configuration_kill_is_retried():
    log = '20:12:02.263\t[CarConfigChangeProcessRestarter] INFO Restarting QtCar because of changed DVs: GUI_centerDisplayModel, FEATURE_enableTeslaTtsService'
    assert supervisor.is_configuration_restart(-9, log)
    assert not supervisor.is_configuration_restart(1, log)
    assert not supervisor.is_configuration_restart(-9, 'Out of memory')
    # An imported UI language makes the center restart itself without the restarter tag.
    assert supervisor.is_configuration_restart(-9, '[ModelSCenterDisplay] INFO CID UI is restarting reason: language changed')
    assert supervisor.is_configuration_restart(-6, '[DriverDisplay] INFO restarting app because language changed\nterminate called')
    assert supervisor.changed_dvs('[ModelSCenterDisplay] INFO CID UI is restarting reason: language changed') == [
        'GUI_language', 'GUI_locale', 'GUI_manualLanguage']  # so the loop guard can drop a disagreeing import
    # A crash while the firmware shuts down for a car-config change is that restart, not a failure.
    teardown = ('[CarConfigChangeListener] INFO DV VAPI_carType reported changed.\n'
                '[TThreadManager] INFO Sending abort to (up to) 48 threads\nterminate called without an active exception')
    assert supervisor.is_configuration_restart(-6, teardown)
    assert supervisor.changed_dvs(teardown) == ['VAPI_carType']
    assert not supervisor.is_configuration_restart(-11, '[CarConfigChangeListener] INFO DV VAPI_trim reported changed.\nSegfault')


def test_restart_validates_image_before_stopping_working_session(monkeypatch):
    monkeypatch.setattr(backend, 'session_config', lambda **_: {'firmware_id': 'a'*16, 'firmware': '/x', 'maps': None})
    def changed(_):
        raise ValueError('Image changed')
    monkeypatch.setattr(backend, 'library_item', changed)
    stopped = []
    monkeypatch.setattr(backend, 'stop', lambda: stopped.append(True))
    with pytest.raises(ValueError, match='changed'):
        backend.restart()
    assert not stopped


def test_restart_recovers_a_failed_session(monkeypatch, tmp_path):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    (tmp_path / 'session').mkdir()
    (tmp_path / 'session/config.json').write_text('{"firmware": "/fw/a", "firmware_id": "a", "browser": true, "cluster": true}')
    monkeypatch.setattr(backend, 'systemctl', lambda *a: subprocess.CompletedProcess(a, 3, 'failed', ''))
    monkeypatch.setattr(backend, 'library_item', lambda _: None)
    monkeypatch.setattr(backend, 'stop', lambda: None)
    started = []
    monkeypatch.setattr(backend, 'start', lambda *a: started.append(a))
    backend.restart()
    assert started == [('a', None, True, True)]


def test_capture_rejects_a_display_outside_session_range(monkeypatch):
    monkeypatch.setattr(backend, 'session_config', lambda: {'center_display': 'remote-host:0', 'cluster': False})
    with pytest.raises(RuntimeError, match='not ready'):
        backend.capture_displays()


def test_rapid_volume_updates_preserve_pending_request_then_accept_native_feedback(tmp_path, monkeypatch):
    from infotainment_lab.steering import execute
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    state = tmp_path / 'session/vehicle-services.json'
    feedback = tmp_path / 'session/vehicle-services-feedback.json'
    backend.atomic_json(feedback, {'state': {'volume_pct': 30}})
    for _ in range(3):
        execute('volume_up', None, None, backend.vehicle_services_state, backend.set_vehicle_services)
    assert backend.load_json(state)['volume_pct'] == 45
    # Once the request is consumed, a subsequent native edit is authoritative.
    backend.atomic_json(feedback, {'state': {'volume_pct': 20}, 'config_mtime_ns': state.stat().st_mtime_ns})
    execute('volume_up', None, None, backend.vehicle_services_state, backend.set_vehicle_services)
    assert backend.load_json(state)['volume_pct'] == 25


def test_shared_desktop_layout_timeout_does_not_stop_the_session(monkeypatch):
    import subprocess
    def stalled(*args, **kwargs):
        raise subprocess.TimeoutExpired('xdotool', 2)
    monkeypatch.setattr(supervisor, 'command', stalled)
    assert supervisor.arrange_cluster({'DISPLAY': ':0.0'}) is False



def test_center_windows_are_kept_inside_the_screen():
    screen = (720, 1152)
    assert supervisor.center_target((0, 0, 720, 1152), screen, True) is None
    assert supervisor.center_target((40, 12, 720, 1152), screen, True) == (0, 0)
    # A later window placed in unscaled car coordinates is clamped into view.
    assert supervisor.center_target((600, 1500, 400, 300), screen, False) == (320, 852)
    assert supervisor.center_target((-50, 10, 400, 300), screen, False) == (0, 10)
    assert supervisor.center_target((100, 100, 400, 300), screen, False) is None


def test_arrange_center_moves_late_windows_and_ignores_browsers(monkeypatch):
    geometry = {'1': (0, 0, 720, 1152), '2': (0, 1920, 720, 400)}
    calls = []

    def fake(argv, env=None, check=True, timeout=15):
        calls.append(argv)
        out = ''
        if argv[1] == 'getdisplaygeometry':
            out = '720 1152'
        elif argv[1] == 'search':
            assert argv[-1] == '^QtCar$'
            out = '1\n2\n'
        elif argv[1] == 'getwindowgeometry':
            x, y, w, h = geometry[argv[-1]]
            out = f'WINDOW={argv[-1]}\nX={x}\nY={y}\nWIDTH={w}\nHEIGHT={h}\nSCREEN=0\n'
        return SimpleNamespace(stdout=out, returncode=0)

    monkeypatch.setattr(supervisor, 'command', fake)
    assert supervisor.arrange_center({'DISPLAY': ':19'}) is True
    moves = [argv for argv in calls if argv[1] in ('windowmove', 'set_window')]
    assert moves == [['xdotool', 'windowmove', '2', '0', '752']]
    calls.clear()
    geometry['1'] = (30, 30, 720, 1152)
    geometry['2'] = (0, 752, 720, 400)
    assert supervisor.arrange_center({'DISPLAY': ':19'}) is True
    moves = [argv for argv in calls if argv[1] in ('windowmove', 'set_window')]
    assert moves == [['xdotool', 'set_window', '--overrideredirect', '1', '1'],
                     ['xdotool', 'windowmove', '1', '0', '0']]


def test_center_layout_timeout_does_not_stop_the_session(monkeypatch):
    import subprocess
    def stalled(*args, **kwargs):
        raise subprocess.TimeoutExpired('xdotool', 2)
    monkeypatch.setattr(supervisor, 'command', stalled)
    assert supervisor.arrange_center({'DISPLAY': ':19'}) is False


def test_optional_service_mode_parts_do_not_degrade_the_session():
    running = {'center': 'running', 'host-state': 'running'}
    assert supervisor.session_phase(20, True, running) == 'running'
    assert supervisor.session_phase(5, True, running) == 'starting'
    assert supervisor.session_phase(20, True, dict(running, **{'service-ui': 'exited', 'chromium-odin': 'exited'})) == 'running'
    assert supervisor.session_phase(20, True, dict(running, spotify='exited')) == 'degraded'


def test_service_ui_port_probe():
    import socket
    with socket.socket() as held:
        held.bind(('127.0.0.1', 0))
        held.listen()
        assert supervisor.port_free(held.getsockname()[1]) is False


def test_launch_uses_the_requested_working_directory(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(supervisor.subprocess, 'Popen', lambda argv, **kw: seen.update(kw) or SimpleNamespace())
    monkeypatch.setattr(supervisor, 'restart_specs', {})
    supervisor.launch('service-ui', ['x'], tmp_path, {'TESLA_BIN': '/bin'}, cwd=tmp_path / 'odin')
    assert seen['cwd'] == str(tmp_path / 'odin')
    assert supervisor.restart_specs['service-ui'][3] == tmp_path / 'odin'
    supervisor.launch('media-webapp', ['x'], tmp_path, {'TESLA_BIN': '/bin'})
    assert seen['cwd'] == '/bin'
    for stream in supervisor.outputs:
        stream.close()
    supervisor.outputs.clear()
    supervisor.children.pop('service-ui', None); supervisor.children.pop('media-webapp', None)


def test_imported_refreshed_model_s_car_type_is_kept_by_the_state_writer():
    # A ModelS2 profile must not be fought by keep-awake writing ModelX every cycle.
    assert 'ModelS2' in supervisor.CAR_TYPES


def test_personal_values_are_refused_by_the_session_store(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    (tmp_path / 'session').mkdir()
    result = backend.set_config_values({'values': {'MEDIA_spotifyPassword': 'x', 'LOC_geoLat': 1.5, 'GUI_ok': True}})
    assert result == {'count': 1, 'rejected': ['MEDIA_spotifyPassword', 'LOC_geoLat']}

def test_a_model3_configuration_is_refused_on_the_sx_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    (tmp_path / 'session').mkdir()
    with pytest.raises(ValueError, match='Model 3'):
        backend.set_config_values({'values': {'VAPI_carType': 'Model3', 'GUI_ok': True}})
    assert not (tmp_path / 'session/config-values.json').exists()  # nothing from that import is stored
    (tmp_path / 'session/config.json').write_text('{"single_display": true}')
    assert backend.set_config_values({'values': {'VAPI_carType': 'Model3'}})['count'] == 1


def test_config_values_merge_and_refuse_only_the_bad_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    (tmp_path / 'session').mkdir()
    assert backend.set_config_values({'values': {'VAPI_a': True, 'APP_b': 3}}) == {'count': 2, 'rejected': []}
    blob = 'QUFB' * 600  # a 2.4 KB base64 setting such as GUI_homePlaceHistoryItem
    result = backend.set_config_values({'values': {'APP_b': 4.5, 'GUI_home': blob, 'bad name': 1, 'A_huge': 'x' * 70000, 'A_list': [1], 'A_none': None}})
    assert result['count'] == 3 and sorted(result['rejected']) == ['A_huge', 'A_list', 'A_none', 'bad name']
    stored = backend.load_json(tmp_path / 'session/config-values.json', {})
    assert stored == {'VAPI_a': True, 'APP_b': 4.5, 'GUI_home': blob}


def test_config_values_remove_names(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    (tmp_path / 'session').mkdir()
    backend.set_config_values({'values': {'A_x': 1, 'B_y': 2}})
    assert backend.set_config_values({'values': {'C_z': 3}, 'remove': ['A_x', 'Missing_1']}) == {'count': 2, 'rejected': []}
    assert backend.load_json(tmp_path / 'session/config-values.json', {}) == {'B_y': 2, 'C_z': 3}


LOG = ('12:26:38.464 [CarConfigChangeListener] INFO Changed DVs: VAPI_carType \n'
       '12:26:38.464 [CarConfigChangeProcessRestarter] INFO Restarting QtCar because of changed DVs: VAPI_carType GUI_x \n'
       '12:26:38.464 [] INFO killing app (pid: 32872)\n')


def test_supervisor_names_the_values_that_restarted_the_firmware():
    assert supervisor.changed_dvs(LOG) == ['VAPI_carType', 'GUI_x']
    comma = 'x [CarConfigChangeProcessRestarter] INFO Restarting QtCarCluster because of changed DVs: VAPI_trim, VAPI_wheelType, GUI_navigationEngine \n'
    assert supervisor.changed_dvs(comma) == ['VAPI_trim', 'VAPI_wheelType', 'GUI_navigationEngine']
    assert supervisor.changed_dvs('nothing here') == []


def test_supervisor_drops_an_override_that_keeps_restarting_the_firmware(tmp_path):
    import json
    (tmp_path / 'config-values.json').write_text('{"VAPI_carType": "ModelS", "GUI_ok": 1}')
    counts = {}
    for _ in range(2):  # one restart per display is how a new value normally settles
        assert supervisor.drop_conflicting_override(tmp_path, counts, ['VAPI_carType']) == []
    assert supervisor.drop_conflicting_override(tmp_path, counts, ['VAPI_carType']) == ['VAPI_carType']
    assert json.loads((tmp_path / 'config-values.json').read_text()) == {'GUI_ok': 1}
    assert json.loads((tmp_path / 'config-conflicts.json').read_text()) == ['VAPI_carType']


def test_supervisor_records_why_the_firmware_restarted(tmp_path):
    import json
    supervisor.record_restart(tmp_path, 'center', ['VAPI_trim'])
    for _ in range(3): supervisor.record_restart(tmp_path, 'instruments', [], ['GUI_x'], limit=2)
    history = json.loads((tmp_path / 'config-restarts.json').read_text())
    assert len(history) == 2 and history[-1]['display'] == 'instruments' and history[-1]['dropped'] == ['GUI_x']
    assert isinstance(history[-1]['at'], float)


def test_restart_allowance_gives_each_display_a_restart_per_override(tmp_path):
    assert supervisor.restart_allowance(tmp_path) == 0
    (tmp_path / 'config-values.json').write_text('{"A_x": 1, "B_y": 2, "C_z": 3}')
    assert supervisor.restart_allowance(tmp_path) == 6


def test_a_cluster_restart_is_a_configuration_restart_not_a_crash(tmp_path):
    cluster = '[CarConfigChangeProcessRestarter] INFO Restarting QtCarCluster because of changed DVs: VAPI_trim, VAPI_wheelType \n'
    assert supervisor.is_configuration_restart(-9, cluster)
    assert not supervisor.is_configuration_restart(-9, 'Restarting QtCarCluster because of changed DVs: VAPI_trim')  # needs the restarter tag
    supervisor.remember_car_config(tmp_path, ['VAPI_trim'])
    supervisor.remember_car_config(tmp_path, ['VAPI_trim', 'VAPI_x'])
    import json
    assert json.loads((tmp_path / 'car-config-learned.json').read_text()) == ['VAPI_trim', 'VAPI_x']


def test_car_config_overrides_are_folded_into_the_profile_the_runtime_reads(tmp_path):
    import json
    base = tmp_path / 'base.json'
    base.write_text(json.dumps({'name': 'x', 'signals': {'VAPI_carType': 'ModelX', 'VAPI_trim': 23}}))
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'config-values.json').write_text(json.dumps(
        {'VAPI_carType': 'ModelS', 'VAPI_packConfig': 75, 'GUI_language': 'English'}))  # a profile key, a known extra, a live setting
    target = supervisor.user_profile(state, base)
    signals = json.loads(target.read_text())['signals']
    assert signals == {'VAPI_carType': 'ModelS', 'VAPI_trim': 23, 'VAPI_packConfig': 75}  # live settings stay out of the profile
    assert json.loads(base.read_text())['signals']['VAPI_carType'] == 'ModelX'  # the shipped file is untouched
    (state / 'config-values.json').unlink()
    assert json.loads(supervisor.user_profile(state, base).read_text())['signals']['VAPI_carType'] == 'ModelX'


def test_a_model3_car_type_is_refused_in_the_dual_display_layout(tmp_path):
    import json
    base = tmp_path / 'base.json'
    base.write_text(json.dumps({'signals': {'VAPI_carType': 'ModelX'}}))
    (tmp_path / 'config-values.json').write_text(json.dumps({'VAPI_carType': 'Model3', 'VAPI_trim': 5}))
    assert json.loads(supervisor.user_profile(tmp_path, base).read_text())['signals']['VAPI_carType'] == 'ModelX'
    assert json.loads((tmp_path / 'config-values.json').read_text()) == {'VAPI_trim': 5}
    assert json.loads((tmp_path / 'config-conflicts.json').read_text()) == ['VAPI_carType']


def test_explicit_names_are_remembered_only_while_they_are_deliberate(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    (tmp_path / 'session').mkdir()
    explicit = lambda: backend.load_json(tmp_path / 'session/config-explicit.json', [])
    backend.set_config_values({'values': {'VAPI_a': 1, 'VAPI_b': 2}, 'explicit': ['VAPI_a']})
    assert explicit() == ['VAPI_a']
    backend.set_config_values({'values': {'VAPI_a': 3}})  # written again without the flag: the app's model is back in charge
    assert explicit() == []
    backend.set_config_values({'values': {'VAPI_b': 4}, 'explicit': ['VAPI_b']})
    backend.set_config_values({'values': {}, 'remove': ['VAPI_b']})
    assert explicit() == []


def test_factory_reset_clears_cache_but_keeps_user_files(tmp_path, monkeypatch):
    data, firmware = tmp_path / 'data', tmp_path / 'firmware.img'
    firmware.write_text('image')
    for name in ('session', 'engine', 'mounts/abc'):
        (data / name).mkdir(parents=True)
    (data / 'session/config-values.json').write_text('{}')
    (data / 'qemu').mkdir()
    (data / 'library.json').write_text('[]')
    monkeypatch.setattr(backend, 'DATA', data)
    monkeypatch.setattr(backend, 'stop', lambda: None)
    monkeypatch.setattr(backend, 'status', lambda: {'phase': 'stopped'})
    assert backend.factory_reset()['reset']
    assert not any((data / name).exists() for name in ('session', 'engine', 'mounts', 'library.json'))
    assert (data / 'qemu').is_dir() and firmware.read_text() == 'image'


def test_factory_reset_unmounts_a_held_image_lazily(tmp_path, monkeypatch):
    (tmp_path / 'mounts/abc').mkdir(parents=True)
    (tmp_path / 'session').mkdir()
    mounted, calls = {str(tmp_path / 'mounts/abc')}, []
    def fusermount(argv, **kw):
        calls.append([str(a) for a in argv])
        if '-z' in argv: mounted.discard(str(argv[-1]))  # plain -u fails as busy
        return SimpleNamespace(returncode=0 if '-z' in argv else 1, stdout='', stderr='')
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    monkeypatch.setattr(backend, 'run', fusermount)
    monkeypatch.setattr(backend, 'systemctl', lambda *a, **kw: SimpleNamespace(stdout='inactive', returncode=3))
    monkeypatch.setattr(backend, 'status', lambda: {'phase': 'stopped'})
    monkeypatch.setattr(backend.os.path, 'ismount', lambda path: str(path) in mounted)
    assert backend.factory_reset()['reset']
    assert [c[:3] for c in calls] == [['fusermount3', '-u', str(tmp_path / 'mounts/abc')], ['fusermount3', '-u', '-z']]
    assert not (tmp_path / 'mounts').exists() and not (tmp_path / 'session').exists()


def test_factory_reset_never_deletes_through_a_mount(tmp_path, monkeypatch):
    (tmp_path / 'mounts/abc').mkdir(parents=True)
    (tmp_path / 'session').mkdir()
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    monkeypatch.setattr(backend, 'stop', lambda: None)
    monkeypatch.setattr(backend, 'run', lambda argv, **kw: SimpleNamespace(returncode=1, stdout='', stderr='not permitted'))
    monkeypatch.setattr(backend.os.path, 'ismount', lambda path: True)
    with pytest.raises(RuntimeError, match='fusermount3 -uz'):
        backend.factory_reset()
    assert (tmp_path / 'session').is_dir()


def test_start_remounts_an_image_whose_fuse_daemon_died(tmp_path, monkeypatch):
    mount = tmp_path / 'mounts' / ('a' * 16)
    mount.mkdir(parents=True)
    state, calls = {'stale': True}, []
    def fake_run(argv, **kw):
        calls.append([str(a) for a in argv])
        if '-u' in argv: state['stale'] = False
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    monkeypatch.setattr(backend, 'run', fake_run)
    monkeypatch.setattr(backend, 'stale_mount', lambda path: state['stale'])
    assert backend.mounted_image({'id': 'a' * 16, 'path': '/firmware.img'}) == mount
    assert calls[0][:2] == ['fusermount3', '-u'] and calls[-1][0] == 'squashfuse'


def test_firmware_displays_and_screens_share_one_scale():
    assert supervisor.screen_geometry({}, 'center') == '720x1152'
    assert supervisor.screen_geometry({'display_scale': 1.5}, 'center') == '1080x1728'
    assert supervisor.screen_geometry({'display_scale': 1.5}, 'cluster') == '1920x720'
    assert supervisor.screen_geometry({'display_scale': 1.5, 'single_display': True}, 'center') == '2880x1800'
    assert supervisor.display_scale({'display_scale': 'junk'}) == 1.0
    assert supervisor.display_scale({'display_scale': 9}) == 1.0


def test_guest_center_mode_keeps_the_default_timing_and_adds_scaled_modes():
    import guest_session
    assert guest_session.center_mode(False, 1.0)[0] == '720x1152_lab'
    assert guest_session.center_mode(False, 1.0)[1][:2] == ['68.75', '720']
    assert guest_session.center_mode(True, 1.0) == ('1920x1200', None)
    name, modeline = guest_session.center_mode(False, 1.5)
    assert name == '1080x1728_lab'
    assert modeline[1] == '1080' and modeline[5] == '1728'


def test_setup_enables_the_apparmor_service_only_under_systemd(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(backend, 'run', lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(backend.shutil, 'which', lambda name: '/usr/bin/' + name)
    fstab = tmp_path / 'fstab'
    fstab.write_text('none /tmp tmpfs defaults 0 0\n')
    backend.keep_apparmor_loaded(tmp_path / 'missing', fstab, wsl=False)
    assert calls == [] and 'securityfs' not in fstab.read_text()
    backend.keep_apparmor_loaded(tmp_path, fstab, wsl=True)
    backend.keep_apparmor_loaded(tmp_path, fstab, wsl=True)
    assert calls == [['systemctl', 'enable', 'apparmor']] * 2
    assert fstab.read_text() == 'none /tmp tmpfs defaults 0 0\n' + backend.SECURITYFS


def test_unloaded_profile_starts_unconfined_with_a_warning(monkeypatch, capsys):
    monkeypatch.setattr(supervisor.shutil, 'which', lambda name: '/usr/bin/aa-exec')
    monkeypatch.setattr(supervisor, 'command', lambda argv, **kw: SimpleNamespace(returncode=1))
    assert supervisor.confined('/usr/tesla/UI/bin/QtCar', ['QtCar']) == ['QtCar']
    assert 'AppArmor profile /usr/tesla/UI/bin/QtCar is not loaded' in capsys.readouterr().out
