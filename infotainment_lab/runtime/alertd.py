"""Stand-in for the vehicle's alert daemon (alertd), for the Service Mode panel.

The firmware service-ui backend reads alerts from com.tesla.Alerts /Alerts on the
session's private bus and relays AlertSet/AlertCleared signals to the page; the
center display's QtCar polls the same service. On a vehicle the alerts come from
the ECUs. Here they are the names the desktop requested in vehicle-alerts.json
({name: epoch seconds when set}); nothing is read from or sent to a vehicle.

  alertd.py SESSION_DIR
"""
import json
from pathlib import Path
import sys
import time

MAX_RECENT = 100
# The uint16 service-ui and QtCar send is an audience bitmask (service-ui asks for 7, QtCar for 2).
# ponytail: every alert is served to every audience; filter by the image's alert metadata if that matters.
AUDIENCES = 7


def log(*parts):
    print(time.strftime('%H:%M:%S'), *parts, flush=True)


def stamp(seconds: float) -> tuple:
    """D-Bus (tu): seconds and nanoseconds since the epoch."""
    return int(seconds), int(seconds % 1 * 1e9)


class Alerts:
    def __init__(self):
        self.active = {}  # name -> set time
        self.recent = []  # (name, set time, cleared time), newest last

    def sync(self, requested: dict, now: float):
        """Apply the requested set; returns the names that were set and cleared."""
        requested = {str(k): float(v) for k, v in requested.items() if isinstance(v, (int, float))}
        cleared = [name for name in self.active if name not in requested]
        for name in cleared:
            self.recent = (self.recent + [(name, self.active.pop(name), now)])[-MAX_RECENT:]
        added = [name for name in requested if name not in self.active]
        self.active.update((name, requested[name]) for name in added)
        return added, cleared

    def active_alerts(self):
        return [(name, AUDIENCES, stamp(at), {}) for name, at in self.active.items()]

    def recent_alerts(self):
        return [(name, AUDIENCES, stamp(at), stamp(gone), {}) for name, at, gone in self.recent]


def read_requested(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def main(args):
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    path = Path(args[0]) / 'vehicle-alerts.json'
    alerts = Alerts()

    class Service(dbus.service.Object):
        @dbus.service.method('com.tesla.Alerts', in_signature='q', out_signature='a(sq(tu)a{ss})')
        def getActiveAlerts(self, audiences):
            return dbus.Array(alerts.active_alerts(), signature='(sq(tu)a{ss})')

        @dbus.service.method('com.tesla.Alerts', in_signature='q', out_signature='a(sq(tu)(tu)a{ss})')
        def getRecentAlerts(self, audiences):
            return dbus.Array(alerts.recent_alerts(), signature='(sq(tu)(tu)a{ss})')

        # Signal shapes as the image's alertd introspects them.
        @dbus.service.signal('com.tesla.Alerts', signature='(sq(tu)a{ss})')
        def AlertSet(self, alert):
            pass

        @dbus.service.signal('com.tesla.Alerts', signature='(sq(tu)(tu)a{ss})')
        def AlertCleared(self, alert):
            pass

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    name = dbus.service.BusName('com.tesla.Alerts', bus, do_not_queue=True)  # noqa: F841 - keeps the name owned
    service = Service(bus, '/Alerts')
    seen = [None]

    def poll():
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        if mtime != seen[0]:
            seen[0] = mtime
            now = time.time()
            added, cleared = alerts.sync(read_requested(path), now)
            empty = dbus.Dictionary({}, signature='ss')
            for alert in added:
                log('set', alert)
                service.AlertSet((alert, AUDIENCES, stamp(alerts.active[alert]), empty))
            for name, at, gone in alerts.recent[len(alerts.recent) - len(cleared):]:
                log('cleared', name)
                service.AlertCleared((name, AUDIENCES, stamp(at), stamp(gone), empty))
        return True

    poll()
    GLib.timeout_add(500, poll)
    log(f'alertd stand-in: serving {path}')
    GLib.MainLoop().run()


if __name__ == '__main__':
    main(sys.argv[1:])
