"""Bounded PCM output that releases the desktop stream during digital silence."""
from __future__ import annotations

import os
import subprocess
import time


class DesktopPlayback:
    # 48 kHz, stereo, signed 16-bit PCM. Keep at most half a second queued.
    MAX_PENDING = 48000 * 2 * 2 // 2

    def __init__(self, server):
        self.server = server
        self.player = None
        self.draining = []
        self.pending = bytearray()
        self.last_signal = 0
        self.retry_at = 0
        self.written_bytes = 0
        self.dropped_bytes = 0
        self.detail = ''

    def _start(self, now):
        self.player = subprocess.Popen([
            'pacat', '--server=' + self.server, '--playback', '--raw',
            '--format=s16le', '--rate=48000', '--channels=2', '--latency-msec=120'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        os.set_blocking(self.player.stdin.fileno(), False)
        self.detail = ''

    def _finish(self, now, interrupted=False):
        if self.player is None:
            return
        self.player.stdin.close()
        if interrupted:
            self.player.terminate()
        self.draining.append((self.player, now + 2))
        self.player = None

    def _failed(self, now, detail):
        self.detail = detail
        self.dropped_bytes += len(self.pending)
        self.pending.clear()
        self._finish(now, interrupted=True)
        self.retry_at = now + 5

    def feed(self, data, now=None):
        now = time.monotonic() if now is None else now
        if self.player is not None and self.player.poll() is not None:
            self._failed(now, 'Desktop audio disconnected. Retrying the output connection.')
        signal = any(data)
        if signal:
            self.last_signal = now
            if self.player is None and now >= self.retry_at:
                self._start(now)
        if self.player is not None:
            if not signal and now - self.last_signal > 1:
                if not self.pending:
                    self._finish(now)
            else:
                self.pending.extend(data)
                if len(self.pending) > self.MAX_PENDING:
                    self._failed(now, 'Desktop audio is not consuming samples. Check desktop sound output.')
        elif signal:
            self.dropped_bytes += len(data)
        self.flush(now)

    def flush(self, now=None):
        now = time.monotonic() if now is None else now
        if self.player is not None and self.pending:
            try:
                count = os.write(self.player.stdin.fileno(), self.pending)
                del self.pending[:count]
                self.written_bytes += count
            except BlockingIOError:
                pass
            except BrokenPipeError:
                self._failed(now, 'Desktop audio disconnected. Retrying the output connection.')
        waiting = []
        for child, deadline in self.draining:
            if child.poll() is not None:
                continue
            if now >= deadline:
                child.kill()
                child.wait(timeout=2)
                self.detail = 'Desktop audio did not finish draining its output.'
            else:
                waiting.append((child, deadline))
        self.draining = waiting

    def close(self):
        self._finish(time.monotonic(), interrupted=True)
        for child, _ in self.draining:
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        self.draining.clear()
