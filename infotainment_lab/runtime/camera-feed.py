"""Feed the existing RGB24/V4L2 adapter from a pattern, clip or raw pipeline.

Only this session's files and decoder child are owned here. External pipeline
files are read without modification. Firmware reads the output through V4L2.
"""
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import atomic_json, load_json
from camera_source import WIDTH, HEIGHT, FPS, FRAME_BYTES
from replay import ReplayPlayer

try:
    TITLE_FONT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 28)
    SMALL_FONT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 22)
except OSError:
    TITLE_FONT = SMALL_FONT = ImageFont.load_default()


def atomic_bytes(path, data):
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_bytes(data)
    temporary.replace(path)


def pattern_frame(frame, steering=0):
    image = Image.new('RGB', (WIDTH, HEIGHT), '#101d27')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 245), fill='#304957')
    for i in range(-4, 9):
        draw.line((640, 240, i * 200 + frame * 3 % 200, HEIGHT), fill='#293c47', width=2)
    for i in range(6):
        y = 270 + (i * 85 + frame * 3) % 450
        draw.line((0, y, WIDTH, y), fill='#293c47', width=2)
    bend = steering / 540 * 190
    for side in (-1, 1):
        points = [(640 + side * (150 + t * 230) + bend * (1 - t)**2, 275 + 370 * t) for t in (n / 30 for n in range(31))]
        draw.line(points, fill='#65dfba', width=6)
    for t, color in ((.95, '#fb817a'), (.58, '#f2cf7d'), (.13, '#65dfba')):
        half = 150 + t * 230
        x = 640 + bend * (1 - t)**2
        draw.line((x-half, 275+370*t, x+half, 275+370*t), fill=color, width=6)
    draw.text((140, 42), 'SIMULATED CAMERA  |  LOCAL LAB', fill='#e3edf2', font=TITLE_FONT)
    draw.text((140, 664), f'Frame {frame:06d}    Steering {steering:+.0f} deg', fill='#a1bac8', font=SMALL_FONT)
    return image


class CameraFeed:
    def __init__(self, state):
        self.state = state
        self.folder = state / 'camera'
        self.folder.mkdir(exist_ok=True)
        self.process = None
        self.output = None
        self.buffer = bytearray()
        self.current = None
        self.raw_stamp = None
        self.frames = 0
        self.frame_at = 0
        self.stopping = False
        self.report_at = 0
        self.last_count = 0
        self.rate = 0
        self.replay = None
        self.replay_error = ''

    def stop_decoder(self):
        if self.replay:
            self.replay.close()
            self.replay = None
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try: self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process.stdout.close()
            self.process = None
        if self.output:
            self.output.close()
            self.output = None
        self.buffer.clear()

    def change(self, config):
        self.stop_decoder()
        self.current = config
        self.raw_stamp = None
        self.frame_at = 0
        self.replay_error = ''
        if config['mode'] == 'replay':
            try:
                self.replay = ReplayPlayer(self.state, config)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                self.replay_error = str(exc)
                atomic_json(self.state / 'replay-status.json', {
                    'phase': 'error', 'error': self.replay_error, 'updated_at': time.time()})
                raise ValueError(self.replay_error) from exc
        if config['mode'] == 'video':
            self.output = (self.state / 'camera-decoder.log').open('w')
            self.process = subprocess.Popen([
                'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-threads', '2',
                '-re', '-stream_loop', '-1', '-protocol_whitelist', 'file,pipe', '-i', config['path'],
                '-an', '-sn', '-dn', '-vf', f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,fps={FPS}',
                '-threads', '2', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=self.output, bufsize=0)

    def read_frame(self):
        mode = self.current['mode']
        if mode == 'replay':
            if not self.replay:
                raise ValueError(self.replay_error or 'The dashcam replay is unavailable.')
            frame = self.replay.read_frame()
            if self.replay.phase == 'error':
                raise ValueError(self.replay.error)
            return frame
        if mode == 'pattern':
            controls = load_json(self.state / 'controls.json', {})
            return pattern_frame(self.frames, float(controls.get('steering_deg', 0))).tobytes()
        if mode == 'raw':
            path = Path(self.current['path'])
            info = path.stat()
            if info.st_size != FRAME_BYTES:
                raise ValueError('Expected 1280 × 720 RGB24 (2,764,800 bytes).')
            if not 0 <= time.time() - info.st_mtime < 3:
                raise ValueError('Pipeline frame is stale. Start your camera writer.')
            stamp = (info.st_ino, info.st_mtime_ns, info.st_size)
            if stamp == self.raw_stamp:
                return None
            with path.open('rb') as source:
                data = source.read(FRAME_BYTES + 1)
            if len(data) != FRAME_BYTES:
                return None
            self.raw_stamp = stamp
            return data
        if mode == 'video':
            if self.process.poll() is not None:
                raise ValueError('Video decoder stopped. Check the selected clip or camera decoder log.')
            deadline = time.monotonic() + .04
            while len(self.buffer) < FRAME_BYTES and time.monotonic() < deadline:
                if not select.select([self.process.stdout], [], [], .005)[0]:
                    continue
                data = os.read(self.process.stdout.fileno(), min(65536, FRAME_BYTES - len(self.buffer)))
                if not data: break
                self.buffer.extend(data)
            if len(self.buffer) == FRAME_BYTES:
                frame = bytes(self.buffer)
                self.buffer.clear()
                return frame
        return None

    def run(self):
        unavailable = False
        try:
            while not self.stopping:
                started = time.monotonic()
                config = load_json(self.state / 'camera-source.json', {'mode': 'pattern', 'path': ''})
                phase, detail = 'live', ''
                frame = None
                try:
                    if config != self.current:
                        self.change(config)
                    frame = self.read_frame()
                    if config['mode'] == 'off':
                        phase, detail = 'off', 'Camera feed stopped.'
                    elif config['mode'] == 'replay' and self.replay and self.replay.phase == 'manual':
                        phase, detail = 'off', 'Manual controls have taken over from the recording.'
                    elif (config['mode'] == 'replay' and self.replay
                          and self.replay.phase in ('paused', 'ended')
                          and self.replay.frame is not None):
                        phase = self.replay.phase
                        detail = 'Holding the last recorded frame.'
                    elif time.time() - self.frame_at > 3 and frame is None:
                        phase, detail = 'waiting', 'Waiting for camera frames.'
                except (OSError, ValueError) as exc:
                    phase, detail = 'waiting', str(exc)
                if frame is not None:
                    atomic_bytes(self.folder / 'back.rgb', frame)
                    if self.replay:
                        self.replay.publish_controls()
                    self.frames += 1
                    self.frame_at = time.time()
                    unavailable = False
                elif phase not in ('live', 'paused', 'ended') and not unavailable:
                    blank = Image.new('RGB', (WIDTH, HEIGHT), '#101d27')
                    ImageDraw.Draw(blank).text((440, 335), 'CAMERA FEED UNAVAILABLE', fill='#a8bcc8', font=TITLE_FONT)
                    atomic_bytes(self.folder / 'back.rgb', blank.tobytes())
                    unavailable = True
                now = time.time()
                if now - self.report_at >= 1:
                    self.rate = (self.frames - self.last_count) / max(.001, now - self.report_at) if self.report_at else 0
                    self.last_count, self.report_at = self.frames, now
                    atomic_json(self.state / 'camera-status.json', {
                        'phase': phase, 'mode': config['mode'], 'source_name': Path(config.get('path', '')).name,
                        'detail': detail, 'width': WIDTH, 'height': HEIGHT, 'fps': round(self.rate, 1),
                        'frames': self.frames, 'frame_at': self.frame_at, 'updated_at': now})
                if config['mode'] != 'video' or phase != 'live':
                    speed = max(1, self.replay.rate) if self.replay else 1
                    time.sleep(max(.001, 1 / (FPS * speed) - (time.monotonic() - started)))
        finally:
            self.stop_decoder()
            atomic_json(self.state / 'camera-status.json', {'phase': 'stopped', 'updated_at': time.time()})


if __name__ == '__main__':
    feed = CameraFeed(Path(os.environ['TESLA_NATIVE_STATE']))
    def stop(*_): feed.stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    feed.run()
