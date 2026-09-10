"""Sources for the local RGB24 -> V4L2 camera pipeline."""
from pathlib import Path
import time

WIDTH, HEIGHT, FPS = 1280, 720, 24
FRAME_BYTES = WIDTH * HEIGHT * 3
LEGACY_FEED = '/tmp/tesla-sim/v4l2-back.rgb'


def source_config(mode, filename=None):
    if mode == 'replay':
        try:
            from .replay import replay_source
        except ImportError:
            from replay import replay_source
        return replay_source(filename)
    if mode not in ('pattern', 'video', 'raw', 'off'):
        raise ValueError('Choose a test pattern, local video or RGB pipeline feed.')
    config = {'mode': mode, 'path': '', 'changed_at': time.time()}
    if mode in ('video', 'raw'):
        path = Path(filename or (LEGACY_FEED if mode == 'raw' else '')).expanduser()
        if not path.is_absolute():
            raise ValueError('Choose an absolute local file path.')
        if path.exists() and not path.is_file():
            raise ValueError('The camera source must be a regular file.')
        if mode == 'video' and not path.is_file():
            raise ValueError('The selected video file is unavailable.')
        if mode == 'raw' and path.is_file() and path.stat().st_size != FRAME_BYTES:
            raise ValueError('This pipeline expects 1280 × 720 RGB24 frames (2,764,800 bytes).')
        config['path'] = str(path)
    return config


def camera_health(producer, consumer, running, now=None):
    now = time.time() if now is None else now
    result = dict(producer)
    fresh = running and producer.get('phase') == 'live' and 0 <= now - producer.get('frame_at', 0) < 3
    consumed = running and 0 <= now - consumer.get('updated_at', 0) < 3
    result.update(source_ready=fresh, firmware_receiving=bool(fresh and consumed),
                  consumed_frames=consumer.get('frames', 0), firmware_fps=consumer.get('fps', 0) if consumed else 0)
    if not running:
        result.update(phase='stopped', source_ready=False, firmware_receiving=False)
    elif producer.get('phase') == 'live' and not fresh:
        result.update(phase='waiting', detail='Waiting for fresh camera frames.')
    return result
