"""Local dashcam video and embedded telemetry on one decoded-frame clock.

The SEI field mapping follows this project's existing dashcam reader. Packet
presentation timestamps supply the clock, including variable-frame-rate clips.
Recorded location and assistance state are metadata, never vehicle commands.
"""
from __future__ import annotations

from bisect import bisect_right
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import queue
import select
import struct
import subprocess
import threading
import time
import uuid

try:
    from .core import atomic_json, load_json
    from .simulation import Simulation
except ImportError:  # staged Linux worker
    from core import atomic_json, load_json
    from simulation import Simulation

MAX_FILE_BYTES = 8 * 1024**3
MAX_PACKETS = 300_000
MAX_PACKET_BYTES = 16 * 1024**2
MAX_METADATA_BYTES = 65536
MAX_DURATION = 7200
WIDTH, HEIGHT, FPS = 1280, 720, 24
FRAME_BYTES = WIDTH * HEIGHT * 3

FIELDS = {
    1: 'version', 2: 'gear_state', 3: 'frame_seq_no', 4: 'vehicle_speed_mps',
    5: 'accelerator_pedal_position', 6: 'steering_wheel_angle',
    7: 'blinker_on_left', 8: 'blinker_on_right', 9: 'brake_applied',
    10: 'autopilot_state', 11: 'latitude_deg', 12: 'longitude_deg',
    13: 'heading_deg', 14: 'linear_acceleration_mps2_x',
    15: 'linear_acceleration_mps2_y', 16: 'linear_acceleration_mps2_z',
}
GEARS = {0: 'P', 1: 'D', 2: 'R', 3: 'N'}
RECORDED_FIELDS = ('frame_seq_no', 'latitude_deg', 'longitude_deg', 'heading_deg',
                   'linear_acceleration_mps2_x', 'linear_acceleration_mps2_y',
                   'linear_acceleration_mps2_z', 'autopilot_state')


def local_clip(filename):
    path = Path(filename).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise ValueError('Choose an available local dashcam MP4 file.')
    if path.suffix.lower() != '.mp4' or not 8 <= path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError('Choose an MP4 clip smaller than 8 GiB.')
    return path


def finite_number(value, low, high, label):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a number.')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be a number.') from None
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f'{label} must be between {low} and {high}.')
    return number


def replay_source(filename, rate=1.0, loop=True, autoplay=True):
    if not isinstance(loop, bool):
        raise ValueError('Loop must be enabled or disabled.')
    if not isinstance(autoplay, bool):
        raise ValueError('Autoplay must be enabled or disabled.')
    return {'mode': 'replay', 'path': str(local_clip(filename)),
            'rate': finite_number(rate, .25, 2, 'Playback rate'), 'loop': loop,
            'autoplay': autoplay, 'changed_at': time.time(), 'replay_id': uuid.uuid4().hex}


def replay_request(action, **values):
    allowed = {'play': (), 'pause': (), 'seek': ('position_seconds',),
               'rate': ('rate',), 'loop': ('loop',), 'manual': ()}
    if action not in allowed or set(values) != set(allowed[action]):
        raise ValueError('Choose play, pause, seek, rate, loop or manual takeover.')
    result = {'id': uuid.uuid4().hex, 'action': action, 'issued_at': time.time()}
    if action == 'seek':
        result['position_seconds'] = finite_number(values['position_seconds'], 0, MAX_DURATION, 'Position')
    if action == 'rate':
        result['rate'] = finite_number(values['rate'], .25, 2, 'Playback rate')
    if action == 'loop':
        if not isinstance(values['loop'], bool):
            raise ValueError('Loop must be enabled or disabled.')
        result['loop'] = values['loop']
    return result


@contextmanager
def controls_lock(state):
    """Serialize local Linux simulator writers, including manual takeover."""
    import fcntl
    path = Path(state) / 'controls.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def manual_takeover(state, controls=None):
    """Stop replay ownership and optionally write validated controls atomically.

    Ordinary video/raw/pattern sources remain selected. Any in-flight replay
    writer finishes before this returns, and later replay writes see the manual
    request under the same lock. A subsequent explicit Play can resume replay.
    """
    state = Path(state)
    checked = Simulation.parse(controls).as_dict() if controls is not None else None
    with controls_lock(state):
        request = replay_request('manual')
        atomic_json(state / 'replay-request.json', request)
        if checked is not None:
            atomic_json(state / 'controls.json', checked)
    return checked if checked is not None else request


def read_varint(data, cursor):
    result = 0
    for shift in range(0, 70, 7):
        if cursor >= len(data):
            raise ValueError('Incomplete embedded telemetry value.')
        byte = data[cursor]
        cursor += 1
        if shift == 63 and byte > 1:
            raise ValueError('Embedded telemetry integer exceeds 64 bits.')
        result |= (byte & 127) << shift
        if not byte & 128:
            return result, cursor
    raise ValueError('Embedded telemetry integer exceeds 64 bits.')


def decode_metadata(payload):
    if len(payload) > MAX_METADATA_BYTES:
        raise ValueError('Embedded telemetry record is too large.')
    fields, cursor = {}, 0
    while cursor < len(payload):
        key, cursor = read_varint(payload, cursor)
        field, wire = key >> 3, key & 7
        if not field:
            raise ValueError('Invalid embedded telemetry field.')
        if wire == 0:
            value, cursor = read_varint(payload, cursor)
        elif wire in (1, 5):
            size, code = (8, '<d') if wire == 1 else (4, '<f')
            if cursor + size > len(payload):
                raise ValueError('Incomplete embedded telemetry number.')
            value = struct.unpack_from(code, payload, cursor)[0]
            cursor += size
            if not math.isfinite(value):
                raise ValueError('Embedded telemetry number must be finite.')
        elif wire == 2:
            size, cursor = read_varint(payload, cursor)
            if cursor + size > len(payload):
                raise ValueError('Incomplete embedded telemetry field.')
            cursor += size
            continue  # future text/binary fields are not display controls
        else:
            raise ValueError('Unsupported embedded telemetry encoding.')
        if field in FIELDS:
            fields[FIELDS[field]] = bool(value) if field in (7, 8, 9) else value
    return fields


def unescape_rbsp(data):
    output, zeros = bytearray(), 0
    for byte in data:
        if zeros >= 2 and byte == 3:
            zeros = 0
            continue
        output.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return bytes(output)


def packet_metadata(packet):
    """Read the project's Tesla SEI marker from length-prefixed H.264 NALs."""
    if len(packet) > MAX_PACKET_BYTES:
        raise ValueError('Dashcam video packet is too large.')
    cursor = 0
    while cursor + 4 <= len(packet):
        size = struct.unpack_from('>I', packet, cursor)[0]
        cursor += 4
        if size > len(packet) - cursor:
            raise ValueError('Incomplete dashcam video packet.')
        nal = packet[cursor:cursor + size]
        cursor += size
        if len(nal) < 5 or nal[0] & 31 != 6 or nal[1] != 5:
            continue
        # Existing recordings identify their user-data payload with 0x42...0x69.
        marker = 3
        while marker < min(len(nal) - 1, 64) and nal[marker] == 0x42:
            marker += 1
        if marker < len(nal) - 1 and nal[marker] == 0x69:
            if len(nal) - marker > MAX_METADATA_BYTES:
                raise ValueError('Embedded telemetry record is too large.')
            yield decode_metadata(unescape_rbsp(nal[marker + 1:-1]))


def probe_video(path):
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
        '-select_streams', 'v:0', '-show_entries', 'stream=codec_name,duration,avg_frame_rate',
        '-of', 'json', str(path)], check=True, capture_output=True, timeout=30)
    streams = json.loads(result.stdout).get('streams', [])
    if not streams or streams[0].get('codec_name') != 'h264':
        raise ValueError('This replay supports H.264 dashcam MP4 recordings.')
    info = streams[0]
    duration = finite_number(info.get('duration'), .001, MAX_DURATION, 'Clip duration')
    numerator, denominator = info.get('avg_frame_rate', '0/1').split('/')
    denominator = finite_number(denominator, 1, 10**12, 'Frame rate denominator')
    fps = float(numerator) / denominator
    if not math.isfinite(fps) or not .1 <= fps <= 240:
        raise ValueError('The dashcam frame rate is unavailable.')
    return duration, fps


def video_packets(path):
    """Stream bounded packet records; never hold ffprobe's complete output."""
    process = subprocess.Popen([
        'ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
        '-select_streams', 'v:0', '-show_packets', '-show_entries', 'packet=pts_time,pos,size',
        '-of', 'compact=p=0:nk=0', str(path)], stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    records = queue.Queue(maxsize=32)
    cancelled = threading.Event()

    def read():
        try:
            while not cancelled.is_set():
                line = process.stdout.readline(512)
                while not cancelled.is_set():
                    try:
                        records.put(line, timeout=.1)
                        break
                    except queue.Full:
                        pass
                if not line:
                    break
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline, count = time.monotonic() + 60, 0
    try:
        while True:
            try:
                line = records.get(timeout=max(.001, deadline - time.monotonic()))
            except queue.Empty:
                raise ValueError('Reading dashcam timestamps timed out.') from None
            if not line:
                break
            count += 1
            if len(line) >= 512 or count > MAX_PACKETS or time.monotonic() > deadline:
                raise ValueError('Dashcam timestamp index exceeds the replay limit.')
            fields = dict(part.split('=', 1) for part in line.decode('ascii').strip().split('|') if '=' in part)
            yield (finite_number(fields.get('pts_time'), 0, MAX_DURATION, 'Frame timestamp'),
                   int(fields['pos']), int(fields['size']))
        if process.wait(timeout=5):
            raise ValueError('Unable to read dashcam frame timestamps.')
    finally:
        cancelled.set()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        reader.join(timeout=2)
        process.stdout.close()


@dataclass(frozen=True)
class Sample:
    time_seconds: float
    fields: dict


@dataclass
class Recording:
    path: Path
    duration_seconds: float
    source_fps: float
    samples: list[Sample]

    def __post_init__(self):
        self.timestamps = [sample.time_seconds for sample in self.samples]

    def sample_at(self, position):
        index = bisect_right(self.timestamps, position) - 1
        return self.samples[max(0, index)]


def load_recording(filename):
    path = local_clip(filename)
    duration, fps = probe_video(path)
    samples = []
    file_size = path.stat().st_size
    with path.open('rb') as stream:
        for timestamp, offset, size in video_packets(path):
            if size < 4 or size > MAX_PACKET_BYTES or offset < 0 or offset + size > file_size:
                raise ValueError('Dashcam packet lies outside the recording.')
            stream.seek(offset)
            for fields in packet_metadata(stream.read(size)):
                if 'vehicle_speed_mps' in fields:
                    samples.append(Sample(timestamp, fields))
    if not samples:
        raise ValueError('No embedded driving telemetry was found in this clip.')
    samples.sort(key=lambda sample: sample.time_seconds)
    return Recording(path, duration, fps, samples)


def sample_controls(sample):
    fields = sample.fields
    left, right = fields.get('blinker_on_left', False), fields.get('blinker_on_right', False)
    # Display simulator limits apply equally to manual inputs and recorded data.
    return Simulation.parse({
        'gear': GEARS.get(fields.get('gear_state'), 'P'),
        'speed_kph': min(200, max(0, fields.get('vehicle_speed_mps', 0) * 3.6)),
        'throttle_pct': min(100, max(0, fields.get('accelerator_pedal_position', 0))),
        'brake_pct': 100 if fields.get('brake_applied', False) else 0,
        'steering_deg': min(540, max(-540, fields.get('steering_wheel_angle', 0))),
        'indicator': 'hazard' if left and right else 'left' if left else 'right' if right else 'off',
    }).as_dict()


class ReplayPlayer:
    """Called by the camera worker. Video progress is the telemetry authority."""
    def __init__(self, state, config, clock=time.monotonic):
        self.state, self.config, self.clock = Path(state), dict(config), clock
        self.rate = finite_number(config.get('rate', 1), .25, 2, 'Playback rate')
        self.loop = config.get('loop', True)
        self.controls_active = config.get('autoplay', True)
        if not isinstance(self.controls_active, bool):
            raise ValueError('Autoplay must be enabled or disabled.')
        self.phase, self.error = 'loading', ''
        self.position = self.frame_index = self.decoder_start = 0
        self.frames_decoded = 0
        self.process = self.log = None
        self.frame = None
        self.buffer = bytearray()
        initial = load_json(self.state / 'replay-request.json', {})
        source_time = config.get('changed_at', time.time())
        # Ignore commands belonging to the old selection, but retain a manual
        # input that arrived after selection and before this decoder started.
        newer_request = initial.get('issued_at', 0) >= source_time
        self.last_request = None if newer_request else initial.get('id')
        self.initial_request = self.last_request
        self.next_frame_at = self.clock()
        self.last_status_at = 0
        self.recording = None
        self.report(force=True)
        self.recording = load_recording(config['path'])
        self.restart(0)
        self.phase = 'playing' if self.controls_active else 'seeking-ready'

    def close_decoder(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process.stdout.close()
            self.process = None
        if self.log:
            self.log.close()
            self.log = None
        self.buffer.clear()

    def restart(self, position):
        self.close_decoder()
        self.decoder_start = min(max(0, position), max(0, self.recording.duration_seconds - 1 / FPS))
        self.frame_index = 0
        self.frame = None
        self.next_frame_at = self.clock()
        self.log = (self.state / 'replay-decoder.log').open('w')
        try:
            self.process = subprocess.Popen([
                'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-threads', '2',
                '-ss', f'{self.decoder_start:.6f}', '-protocol_whitelist', 'file,pipe', '-i', str(self.recording.path),
                '-an', '-sn', '-dn', '-vf',
                f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,fps={FPS}',
                '-threads', '2', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=self.log, bufsize=0)
        except OSError:
            self.close_decoder()
            raise

    def command(self, request):
        if not request or request.get('id') == self.last_request:
            return
        self.last_request = request.get('id')
        action = request.get('action')
        checked = replay_request(action, **{k: v for k, v in request.items() if k not in ('id', 'action', 'issued_at')})
        if action == 'manual':
            self.controls_active = False
            self.phase = 'manual'
            self.close_decoder()
        elif action == 'pause' and self.phase != 'manual':
            held = 'paused' if self.controls_active else 'ready'
            self.phase = held if self.frame is not None else 'seeking-' + held
        elif action == 'play':
            if self.phase in ('ended', 'manual'):
                self.restart(0 if self.phase == 'ended' else self.position)
            self.controls_active = True
            self.phase = 'playing'
            self.next_frame_at = self.clock()
        elif action == 'seek' and self.phase != 'manual':
            paused = self.phase not in ('playing', 'seeking-playing')
            self.restart(checked['position_seconds'])
            self.phase = ('seeking-ready' if not self.controls_active else
                          'seeking-paused' if paused else 'seeking-playing')
        elif action == 'rate':
            self.rate = checked['rate']
            self.next_frame_at = self.clock()
        elif action == 'loop':
            self.loop = checked['loop']
        self.report(force=True)

    def read_frame(self):
        self.command(load_json(self.state / 'replay-request.json', {}))
        if self.phase in ('manual', 'error'):
            self.report()
            return None
        if self.phase in ('ready', 'paused', 'ended') or self.clock() < self.next_frame_at:
            self.report()
            return self.frame
        deadline = self.clock() + .02
        while len(self.buffer) < FRAME_BYTES and self.clock() < deadline:
            if not select.select([self.process.stdout], [], [], .002)[0]:
                continue
            data = os.read(self.process.stdout.fileno(), min(65536, FRAME_BYTES - len(self.buffer)))
            if not data:
                if self.process.poll() is None:
                    break
                if self.process.returncode:
                    self.controls_active = False
                    self.phase, self.error = 'error', 'The dashcam decoder stopped. See replay-decoder.log.'
                    self.report(force=True)
                    return None
                if self.loop and self.phase == 'playing':
                    self.restart(0)
                else:
                    self.phase = 'ended'
                    self.report(force=True)
                return self.frame
            self.buffer.extend(data)
        if len(self.buffer) != FRAME_BYTES:
            self.report()
            return self.frame
        self.frame = bytes(self.buffer)
        self.buffer.clear()
        self.position = min(self.recording.duration_seconds, self.decoder_start + self.frame_index / FPS)
        self.frame_index += 1
        self.frames_decoded += 1
        # A slow decoder slows both displays and video instead of letting data run ahead.
        self.next_frame_at = max(self.next_frame_at + 1 / (FPS * self.rate), self.clock())
        if self.phase == 'seeking-paused':
            self.phase = 'paused'
        elif self.phase == 'seeking-playing':
            self.phase = 'playing'
        elif self.phase == 'seeking-ready':
            self.phase = 'ready'
        return self.frame

    def publish_controls(self):
        """Publish only after CameraFeed has committed this exact RGB frame."""
        if self.frame is not None and not self.controls_active:
            self.report(force=True)
            return
        if self.frame is None or self.phase not in ('playing', 'paused', 'seeking-paused', 'ended'):
            return
        with controls_lock(self.state):
            request = load_json(self.state / 'replay-request.json', {})
            current = load_json(self.state / 'camera-source.json', {})
            if ((request.get('action') == 'manual' and request.get('id') != self.initial_request)
                    or current != self.config):
                return
            atomic_json(self.state / 'controls.json', sample_controls(self.recording.sample_at(self.position)))
            self.report(force=True)

    def report(self, force=False):
        now = time.time()
        if not force and now - self.last_status_at < .2:
            return
        sample = self.recording.sample_at(self.position) if self.recording else None
        atomic_json(self.state / 'replay-status.json', {
            'phase': self.phase, 'position_seconds': round(self.position, 4),
            'duration_seconds': self.recording.duration_seconds if self.recording else 0,
            'rate': self.rate, 'loop': self.loop, 'source_name': Path(self.config['path']).name,
            'sample_count': len(self.recording.samples) if self.recording else 0,
            'telemetry_sample': sample_controls(sample) if sample else {},
            'recorded_metadata': {k: sample.fields[k] for k in RECORDED_FIELDS if k in sample.fields} if sample else {},
            'sample_time_seconds': sample.time_seconds if sample else None,
            'clock': 'decoded video frame / MP4 presentation timestamp',
            'request_id': self.last_request, 'error': self.error, 'updated_at': now,
            'frame_ready': self.frame is not None,
            'controls_active': self.controls_active,
            'replay_id': self.config.get('replay_id', ''),
            'decoded_frame_index': self.frame_index - 1 if self.frame is not None else None,
            'frames_decoded': self.frames_decoded,
        })
        self.last_status_at = now

    def close(self):
        self.close_decoder()
        self.controls_active = False
        if self.phase not in ('manual', 'error'):
            self.phase = 'stopped'
        self.report(force=True)
