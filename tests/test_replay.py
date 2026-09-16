import os
from pathlib import Path
import struct

import pytest

from infotainment_lab.core import atomic_json, load_json
from infotainment_lab import replay


def varint(value):
    output = bytearray()
    while value > 127:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


def field(number, value, wire=0):
    return varint((number << 3) | wire) + (struct.pack('<f', value) if wire == 5 else varint(value))


def sei_packet(payload):
    escaped, zeros = bytearray(), 0
    for byte in payload:
        if zeros >= 2 and byte <= 3:
            escaped.append(3)
            zeros = 0
        escaped.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    nal = b'\x06\x05\x00\x42\x42\x69' + escaped + b'\x80'
    return struct.pack('>I', len(nal)) + nal


def test_embedded_fields_preserve_recorded_metadata_and_six_controls():
    payload = b''.join((field(2, 1), field(3, 55), field(4, 10.0, 5),
                        field(5, 17.0, 5), field(6, -23.5, 5),
                        field(7, 1), field(8, 1), field(9, 1), field(10, 2),
                        field(11, 37.0, 5), field(13, 100.0, 5)))
    fields = list(replay.packet_metadata(sei_packet(payload)))[0]
    assert fields['frame_seq_no'] == 55
    assert fields['latitude_deg'] == 37
    assert fields['autopilot_state'] == 2
    controls = replay.sample_controls(replay.Sample(0, fields))
    assert controls == {'gear': 'D', 'speed_kph': 36, 'throttle_pct': 17,
                        'brake_pct': 100, 'steering_deg': -23.5, 'indicator': 'hazard'}
    assert 'autopilot_state' not in controls


def test_video_timestamps_handle_variable_frame_rate(tmp_path, monkeypatch):
    packets = [sei_packet(field(4, speed, 5) + field(3, index) + field(2, 1))
               for index, speed in enumerate((1., 2., 3.))]
    clip = tmp_path / 'recording.mp4'
    clip.write_bytes(b''.join(packets))
    offsets = [0, len(packets[0]), len(packets[0]) + len(packets[1])]
    monkeypatch.setattr(replay, 'probe_video', lambda _: (.2, 15))
    monkeypatch.setattr(replay, 'video_packets', lambda _: iter(zip((0, .0248, .1632), offsets, map(len, packets))))
    recording = replay.load_recording(clip)
    assert recording.sample_at(.13).fields['vehicle_speed_mps'] == 2
    assert recording.sample_at(.1632).fields['vehicle_speed_mps'] == 3
    assert recording.sample_at(-1).time_seconds == 0


def test_replay_requests_validate_playback_limits_and_local_source(tmp_path):
    clip = tmp_path / 'drive.mp4'
    clip.write_bytes(b'local test clip')
    config = replay.replay_source(clip, rate=2, loop=False)
    assert config['mode'] == 'replay' and config['rate'] == 2 and not config['loop']
    assert config['autoplay']
    assert not replay.replay_source(clip, autoplay=False)['autoplay']
    with pytest.raises(ValueError):
        replay.replay_source(clip, autoplay='false')
    assert replay.replay_request('seek', position_seconds=13.5)['position_seconds'] == 13.5
    for action in ('play', 'pause', 'manual'):
        assert replay.replay_request(action)['action'] == action
    for values in ({'rate': 3}, {'rate': float('nan')}, {'rate': True}):
        with pytest.raises(ValueError):
            replay.replay_request('rate', **values)
    with pytest.raises(ValueError):
        replay.replay_source('https://example.com/drive.mp4')
    with pytest.raises(ValueError):
        replay.replay_request('seek', position_seconds=-1)
    with pytest.raises(ValueError):
        replay.replay_request('play', position_seconds=0)


def test_own_incomplete_fixture_reports_bounds_without_partial_fields():
    with pytest.raises(ValueError, match='Incomplete'):
        replay.decode_metadata(field(4, 12.0, 5)[:-1])
    with pytest.raises(ValueError, match='64 bits'):
        replay.read_varint(b'\xff' * 10, 0)
    with pytest.raises(ValueError, match='finite'):
        replay.decode_metadata(field(4, float('nan'), 5))
    with pytest.raises(ValueError, match='too large'):
        replay.decode_metadata(bytes(replay.MAX_METADATA_BYTES + 1))


def test_recorded_controls_obey_same_limits_as_manual_controls():
    sample = replay.Sample(0, {'gear_state': 0, 'vehicle_speed_mps': 100,
                               'accelerator_pedal_position': 110, 'steering_wheel_angle': -600})
    assert replay.sample_controls(sample) == {'gear': 'P', 'speed_kph': 0,
        'throttle_pct': 0, 'brake_pct': 0, 'steering_deg': -540, 'indicator': 'off'}


def test_reverse_negative_speed_is_not_discarded():
    sample = replay.Sample(0, {'gear_state': 2, 'vehicle_speed_mps': -2})
    assert replay.sample_controls(sample)['speed_kph'] == 7.2



def make_player(tmp_path, monkeypatch, autoplay=True, config=None):
    recording = replay.Recording(Path('/local/drive.mp4'), 60, 36,
        [replay.Sample(0, {'gear_state': 1, 'vehicle_speed_mps': 10})])
    monkeypatch.setattr(replay, 'load_recording', lambda _: recording)
    monkeypatch.setattr(replay.ReplayPlayer, 'restart', lambda self, position: setattr(self, 'position', min(60, position)))
    config = config or {'mode': 'replay', 'path': '/local/drive.mp4', 'rate': 1, 'loop': True,
                        'autoplay': autoplay, 'changed_at': replay.time.time()}
    atomic_json(tmp_path / 'camera-source.json', config)
    return replay.ReplayPlayer(tmp_path, config)


def test_pause_seek_rate_loop_and_resume_state_transitions(tmp_path, monkeypatch):
    player = make_player(tmp_path, monkeypatch)
    player.frame = b'frame'
    player.command(replay.replay_request('pause'))
    assert player.phase == 'paused'
    player.command(replay.replay_request('seek', position_seconds=12))
    assert player.phase == 'seeking-paused' and player.position == 12
    player.command(replay.replay_request('rate', rate=.5))
    player.command(replay.replay_request('loop', loop=False))
    assert player.rate == .5 and not player.loop
    player.command(replay.replay_request('play'))
    assert player.phase == 'playing'
    player.command(replay.replay_request('manual'))
    assert player.phase == 'manual'
    player.close()


def test_reopened_replay_preview_and_seek_leave_manual_inputs_untouched(tmp_path, monkeypatch):
    parked = replay.Simulation().as_dict()
    atomic_json(tmp_path / 'controls.json', parked)
    player = make_player(tmp_path, monkeypatch, autoplay=False)
    assert player.phase == 'seeking-ready' and not player.controls_active
    # A first decoded preview is available without granting input ownership.
    player.frame = b'preview'
    player.phase = 'ready'
    player.publish_controls()
    assert load_json(tmp_path / 'controls.json') == parked
    assert player.read_frame() == b'preview'
    for command in (replay.replay_request('pause'), replay.replay_request('seek', position_seconds=20),
                    replay.replay_request('rate', rate=2), replay.replay_request('loop', loop=False)):
        player.command(command)
        player.publish_controls()
        assert not player.controls_active
        assert load_json(tmp_path / 'controls.json') == parked
    status = load_json(tmp_path / 'replay-status.json')
    assert not status['controls_active'] and status['frame_ready']
    player.command(replay.replay_request('play'))
    assert player.controls_active and player.phase == 'playing'
    player.close()


@pytest.mark.skipif(os.name == 'nt', reason='Linux worker uses advisory flock')
def test_reopened_replay_claims_inputs_only_on_explicit_play(tmp_path, monkeypatch):
    parked = replay.Simulation().as_dict()
    atomic_json(tmp_path / 'controls.json', parked)
    player = make_player(tmp_path, monkeypatch, autoplay=False)
    player.frame = b'preview'
    player.phase = 'ready'
    player.publish_controls()
    assert load_json(tmp_path / 'controls.json') == parked
    player.command(replay.replay_request('play'))
    player.publish_controls()
    assert load_json(tmp_path / 'controls.json')['speed_kph'] == 36
    player.close()


@pytest.mark.skipif(os.name == 'nt', reason='Linux worker uses advisory flock')
def test_manual_takeover_prevents_late_replay_write_and_preserves_video(tmp_path, monkeypatch):
    player = make_player(tmp_path, monkeypatch)
    player.frame = b'frame'
    player.publish_controls()
    assert load_json(tmp_path / 'controls.json')['speed_kph'] == 36
    manual = replay.manual_takeover(tmp_path, {'gear': 'P'})
    player.publish_controls()  # in-flight caller after takeover must not restore D
    assert load_json(tmp_path / 'controls.json') == manual
    assert load_json(tmp_path / 'camera-source.json')['mode'] == 'replay'
    normal_video = {'mode': 'video', 'path': '/local/camera.mp4'}
    atomic_json(tmp_path / 'camera-source.json', normal_video)
    replay.manual_takeover(tmp_path, {'gear': 'R'})
    assert load_json(tmp_path / 'camera-source.json') == normal_video
    player.close()


@pytest.mark.skipif(os.name == 'nt', reason='Linux worker uses advisory flock')
def test_new_replay_ignores_takeover_request_from_previous_session(tmp_path, monkeypatch):
    replay.manual_takeover(tmp_path, {'gear': 'P'})
    player = make_player(tmp_path, monkeypatch)
    player.frame = b'frame'
    player.publish_controls()
    assert load_json(tmp_path / 'controls.json')['speed_kph'] == 36
    player.close()


@pytest.mark.skipif(os.name == 'nt', reason='Linux worker uses advisory flock')
def test_manual_input_after_selection_before_decoder_start_is_preserved(tmp_path, monkeypatch):
    config = {'mode': 'replay', 'path': '/local/drive.mp4', 'rate': 1, 'loop': True,
              'autoplay': True, 'changed_at': replay.time.time()}
    atomic_json(tmp_path / 'camera-source.json', config)
    manual = replay.manual_takeover(tmp_path, {'gear': 'R', 'speed_kph': 2})
    player = make_player(tmp_path, monkeypatch, config=config)
    player.frame = b'frame'
    player.publish_controls()  # even a late first frame cannot overwrite it
    assert load_json(tmp_path / 'controls.json') == manual
    player.command(load_json(tmp_path / 'replay-request.json'))
    assert player.phase == 'manual' and not player.controls_active
    player.close()


def test_new_pause_before_decoder_start_is_acknowledged(tmp_path, monkeypatch):
    config = {'mode': 'replay', 'path': '/local/drive.mp4', 'rate': 1, 'loop': True,
              'autoplay': True, 'changed_at': replay.time.time()}
    request = replay.replay_request('pause')
    atomic_json(tmp_path / 'replay-request.json', request)
    player = make_player(tmp_path, monkeypatch, config=config)
    player.command(request)
    assert player.phase == 'seeking-paused'
    assert player.last_request == request['id']
    player.close()


@pytest.mark.skipif(os.name == 'nt', reason='Linux worker uses advisory flock')
def test_takeover_waits_for_inflight_frame_then_owns_controls(tmp_path, monkeypatch):
    import threading
    player = make_player(tmp_path, monkeypatch)
    player.frame = b'frame'
    frame_writing, release_frame, manual_finished = (threading.Event() for _ in range(3))
    original_write = replay.atomic_json

    def delayed_write(path, value):
        if path.name == 'controls.json' and value['gear'] == 'D':
            frame_writing.set()
            assert release_frame.wait(3)
        original_write(path, value)

    def take_over():
        replay.manual_takeover(tmp_path, {'gear': 'P'})
        manual_finished.set()

    monkeypatch.setattr(replay, 'atomic_json', delayed_write)
    writing = threading.Thread(target=player.publish_controls)
    manual = threading.Thread(target=take_over)
    writing.start()
    assert frame_writing.wait(3)
    manual.start()
    assert not manual_finished.wait(.05)
    release_frame.set()
    writing.join(3)
    manual.join(3)
    assert manual_finished.is_set()
    player.publish_controls()
    assert load_json(tmp_path / 'controls.json')['gear'] == 'P'
    player.close()
