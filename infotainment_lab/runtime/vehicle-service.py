"""Stand-in for the vehicle service's data-value endpoint (com.tesla.VehicleService).

The firmware's data-value client sends some values, such as the HVAC power state and
the VAPI rail state, to com.tesla.VehicleService /LocalDataValue. Nothing in the lab
runs QtCarVehicle to own that name, so each push fails with "Proxy does not exist".
This owns the name and answers the two calls get-local-dv and set-local-dv make.
Reads and writes go to the center display, as com.tesla.Debug's do, so the displays
keep the values the firmware pushes.

  vehicle-service.py
"""
import sys
import time


def log(*parts):
    print(time.strftime('%H:%M:%S'), *parts, flush=True)


def main(args):
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    name = dbus.service.BusName('com.tesla.VehicleService', bus, do_not_queue=True)  # noqa: F841 - keeps the name owned

    def center():
        return dbus.Interface(bus.get_object('com.tesla.CenterDisplay', '/LocalDataValue', introspect=False),
                              'com.tesla.LocalDataValue')

    class LocalDataValue(dbus.service.Object):
        @dbus.service.method('com.tesla.LocalDataValue', in_signature='s', out_signature='bv')
        def DataGetValueRequest(self, data_value):
            return center().DataGetValueRequest(str(data_value), timeout=1)

        @dbus.service.method('com.tesla.LocalDataValue', in_signature='sv', out_signature='b')
        def DataSetValueRequest(self, data_value, value):
            log('set', data_value, value)
            return bool(center().DataSetValueRequest(str(data_value), value, timeout=1))

    service = LocalDataValue(bus, '/LocalDataValue')  # noqa: F841 - keeps the object exported
    log('vehicle-service stand-in: forwarding to com.tesla.CenterDisplay')
    GLib.MainLoop().run()


if __name__ == '__main__':
    main(sys.argv[1:])
