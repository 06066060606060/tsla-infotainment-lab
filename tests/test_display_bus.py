"""Bounded callback scheduling, timeouts, and isolated late replies."""
import sys
from types import SimpleNamespace

import pytest

from infotainment_lab.display_bus import call_many


class EventLoop:
    def __init__(self):
        self.callbacks = []
        self.deadlines = {}
        self.counter = 0
        self.batch_sizes = []

    def MainLoop(self):
        owner = self

        class Loop:
            def quit(self):
                self.done = True

            def run(self):
                self.done = False
                owner.batch_sizes.append(len(owner.callbacks))
                while owner.callbacks and not self.done:
                    owner.callbacks.pop(0)()
                if not self.done:
                    next(iter(owner.deadlines.values()))()

        return Loop()

    def timeout_add(self, milliseconds, callback):
        assert milliseconds > 0
        self.counter += 1
        self.deadlines[self.counter] = callback
        return self.counter

    def source_remove(self, identifier):
        del self.deadlines[identifier]


@pytest.fixture
def loop(monkeypatch):
    loop = EventLoop()
    monkeypatch.setitem(sys.modules, 'gi', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'gi.repository', SimpleNamespace(GLib=loop))
    return loop


def test_calls_are_bounded_and_replies_keep_field_identity(loop):
    def get(name, timeout, reply_handler, error_handler):
        loop.callbacks.insert(0, lambda: reply_handler(True, name + '-value'))

    interface = SimpleNamespace(DataGetValueRequest=get)
    args = {str(i): (str(i),) for i in range(81)}
    replies = call_many(interface, 'DataGetValueRequest', args)
    assert loop.batch_sizes == [32, 32, 17]
    assert replies == {name: (True, name + '-value') for name in args}
    assert not loop.deadlines


def test_deadline_and_late_reply_cannot_become_a_later_batch_result(loop):
    late = []

    def missing(name, timeout, reply_handler, error_handler):
        late.append(reply_handler)

    interface = SimpleNamespace(DataGetValueRequest=missing)
    with pytest.raises(TimeoutError):
        call_many(interface, 'DataGetValueRequest', {'speed': ('speed',)})
    assert not loop.deadlines

    def retry(name, timeout, reply_handler, error_handler):
        loop.callbacks.append(lambda: late[0](True, 'stale'))
        loop.callbacks.append(lambda: reply_handler(True, 'current'))

    interface.DataGetValueRequest = retry
    assert call_many(interface, 'DataGetValueRequest', {'speed': ('speed',)}) == {'speed': (True, 'current')}


def test_remote_error_propagates_without_inventing_a_reply(loop):
    def rejected(name, timeout, reply_handler, error_handler):
        loop.callbacks.append(lambda: error_handler(RuntimeError('disconnected')))

    with pytest.raises(RuntimeError, match='disconnected'):
        call_many(SimpleNamespace(DataGetValueRequest=rejected), 'DataGetValueRequest', {'a': ('a',)})
    assert not loop.deadlines
