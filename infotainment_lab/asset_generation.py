"""Own the firmware's finite asset renderer and retain its generated cache."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time


def valid_identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value) is not None


def decode_identifier(raw):
    # The native interface sends string DVs unquoted; some adapters use JSON.
    value = str(raw)
    try:
        value = json.loads(value)
    except ValueError:
        pass
    return value if valid_identifier(value) else ''


def arguments(firmware):
    firmware = Path(firmware)
    ui = firmware / 'usr/tesla/UI'
    return [str(firmware / 'usr/bin/godot'), '--window-title', 'Asset Gen',
            '--position', '10000,0', '--main-pack', str(ui / 'assets/ap_visualization.zip'),
            '--resolution', '256x256', '--app', str(ui / 'lib/libApVizGodot.so'),
            '--audio-driver', 'Dummy', '--video-driver', 'GLES2',
            '--ip', '127.0.0.100', '--apviz-assetgen']


def ready(cache, identifier):
    if not valid_identifier(identifier):
        return False
    folder = Path(cache) / 'AssetGen' / identifier
    return all((folder / name).is_file() for name in
               ('success_sentinel', 'day/TrackMode.png', 'night/TrackMode.png'))


class Renderer:
    def __init__(self, firmware, cache, env, log, *, spawn=subprocess.Popen):
        self.argv, self.cache, self.env, self.log = arguments(firmware), Path(cache), env, Path(log)
        self.spawn = spawn
        self.process = self.stream = None
        self.identifier = ''
        self.attempts = 0
        self.started = self.retry_at = 0

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def tick(self, identifier, now):
        if self.process is not None:
            if self.process.poll() is None and now - self.started < 90:
                return 'generating'
            self.stop()
            self.retry_at = now + 30
        if not valid_identifier(identifier):
            return 'waiting-config'
        if identifier != self.identifier:
            self.identifier, self.attempts, self.retry_at = identifier, 0, 0
        if ready(self.cache, identifier):
            return 'ready'
        if self.attempts >= 2:
            return 'failed'
        if now < self.retry_at:
            return 'waiting-retry'
        self.attempts += 1
        self.started = now
        self.stream = self.log.open('w')
        try:
            self.process = self.spawn(self.argv, env=self.env, cwd=self.env['TESLA_HOME'],
                                      stdin=subprocess.DEVNULL, stdout=self.stream,
                                      stderr=subprocess.STDOUT)
        except OSError:
            self.stream.close()
            self.stream = None
            self.retry_at = now + 30
            return 'failed'
        return 'generating'


def main():
    import dbus
    from core import atomic_json
    from display_bus import connect

    state = Path(os.environ['TESLA_NATIVE_STATE'])
    cache = Path(os.environ['TESLA_NATIVE_ASSET_DATA'])
    bus = connect(os.environ['DBUS_SESSION_BUS_ADDRESS'])
    renderer = Renderer(os.environ['TESLA_FIRMWARE'], cache, dict(os.environ), state / 'assetgen-render.log')
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    previous_phase = None
    try:
        while not stopping:
            identifier = ''
            try:
                if bus.name_has_owner('com.tesla.CenterDisplay'):
                    interface = dbus.Interface(bus.get_object('com.tesla.CenterDisplay', '/LocalDataValue'),
                                               'com.tesla.LocalDataValue')
                    ok, raw = interface.DataGetValueRequest('GUI_assetGenIdentifier', timeout=1.5)
                    if ok:
                        identifier = decode_identifier(raw)
            except (dbus.DBusException, ValueError):
                pass
            phase = renderer.tick(identifier, time.monotonic())
            if phase != previous_phase:
                print(f'Asset generation: {phase} (attempts: {renderer.attempts})', flush=True)
                previous_phase = phase
            atomic_json(state / 'assetgen-status.json', {'state': phase, 'attempts': renderer.attempts})
            for _ in range(20):
                if stopping:
                    break
                time.sleep(.1)
    finally:
        renderer.stop()


if __name__ == '__main__':
    main()
