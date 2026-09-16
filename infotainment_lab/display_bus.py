"""Bounded asynchronous calls on the local desktop display bus.

The firmware exposes individual value methods. Send a small group before
waiting for replies so each field does not cost a separate rendered frame.
No firmware method or wire protocol is added by this adapter.
"""


def connect(address):
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop

    return dbus.bus.BusConnection(address, mainloop=DBusGMainLoop())


def call_many(interface, method, arguments, timeout=.3):
    """Return replies keyed by field; a transport failure is never unsupported.

    A batch has at most 32 outstanding calls. Late callbacks only touch their
    own closed batch, and the next iteration can retry a failed operation.
    Call from the owning process thread, outside an existing GLib main loop.
    """
    from gi.repository import GLib

    results = {}
    items = list(arguments.items())
    for offset in range(0, len(items), 32):
        chunk = items[offset:offset + 32]
        loop = GLib.MainLoop()
        pending = {name for name, _ in chunk}
        replies, failures = {}, []
        closed = False

        def finish(name, values=None, error=None):
            if closed or name not in pending:
                return
            pending.remove(name)
            if error is not None:
                failures.append(error)
            else:
                replies[name] = values
            if not pending:
                loop.quit()

        def expired():
            failures.append(TimeoutError('The local display batch did not reply in time.'))
            loop.quit()
            return True  # Removed in finally, including the deadline case.

        deadline = GLib.timeout_add(max(1, int((timeout + .1) * 1000)), expired)
        try:
            for name, args in chunk:
                getattr(interface, method)(
                    *args, timeout=timeout,
                    reply_handler=lambda *values, name=name: finish(name, values),
                    error_handler=lambda error, name=name: finish(name, error=error))
            if pending:
                loop.run()
            if failures:
                raise failures[0]
            results.update(replies)
        finally:
            closed = True
            GLib.source_remove(deadline)
    return results
