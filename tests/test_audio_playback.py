from infotainment_lab.audio_playback import DesktopPlayback
from infotainment_lab import audio_playback


class Input:
    closed = False
    def fileno(self):
        return 50
    def close(self):
        self.closed = True


class Player:
    def __init__(self):
        self.stdin = Input()
        self.code = None
    def poll(self):
        return self.code
    def terminate(self):
        self.code = -15
    def kill(self):
        self.code = -9
    def wait(self, timeout):
        return self.code


def players(monkeypatch):
    created = []
    def spawn(*args, **kwargs):
        child = Player()
        created.append(child)
        return child
    monkeypatch.setattr(audio_playback.subprocess, 'Popen', spawn)
    # These tests exercise queue logic without opening a Linux audio pipe.
    monkeypatch.setattr(audio_playback.os, 'set_blocking', lambda *_: None, raising=False)
    return created


def test_silence_releases_output_and_later_sound_uses_a_new_stream(monkeypatch):
    created = players(monkeypatch)
    monkeypatch.setattr(audio_playback.os, 'write', lambda fd, data: len(data))
    output = DesktopPlayback('unix:/desktop/audio')
    output.feed(bytes(40), now=1)
    assert created == []
    output.feed(b'\x10\0\x10\0', now=2)
    assert len(created) == 1
    output.feed(bytes(40), now=2.5)
    assert output.player is created[0]
    output.feed(bytes(40), now=3.1)
    assert output.player is None and created[0].stdin.closed
    created[0].code = 0
    output.feed(b'\x10\0\x10\0', now=8)
    assert output.player is created[1] and output.dropped_bytes == 0
    output.close()


def test_partial_writes_keep_the_unwritten_samples(monkeypatch):
    players(monkeypatch)
    writes = []
    def partial(fd, data):
        writes.append(bytes(data[:4]))
        return min(4, len(data))
    monkeypatch.setattr(audio_playback.os, 'write', partial)
    output = DesktopPlayback('unix:/desktop/audio')
    output.feed(b'abcdefgh', now=1)
    assert output.pending == b'efgh'
    output.flush(now=1.1)
    assert b''.join(writes) == b'abcdefgh' and not output.pending
    output.close()


def test_blocked_desktop_cannot_accumulate_unbounded_audio_or_freeze_vm(monkeypatch):
    created = players(monkeypatch)
    def blocked(*_):
        raise BlockingIOError()
    monkeypatch.setattr(audio_playback.os, 'write', blocked)
    output = DesktopPlayback('unix:/desktop/audio')
    output.feed(b'\1' * output.MAX_PENDING, now=1)
    output.feed(b'\1' * 4, now=1.1)
    assert not output.pending and output.player is None
    assert output.detail and output.dropped_bytes == output.MAX_PENDING + 4
    output.feed(b'\1' * 4, now=2)
    assert len(created) == 1  # Retry delay avoids continuously spawning players.
    output.close()
