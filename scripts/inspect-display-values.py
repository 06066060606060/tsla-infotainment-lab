"""Read the lab's private display metadata; useful when adding a profile."""
import json
from pathlib import Path
import dbus

state = Path.home() / '.local/share/tsla-infotainment-lab/session'
bus = dbus.bus.BusConnection((state / 'dbus-address').read_text().strip())
for service in ('com.tesla.CenterDisplay', 'com.tesla.ClusterDisplay'):
    iface = dbus.Interface(bus.get_object(service, '/LocalDataValue'), 'com.tesla.LocalDataValue')
    print(service)
    print(bus.get_object(service, '/LocalDataValue').Introspect(dbus_interface='org.freedesktop.DBus.Introspectable'))
    for name in ('VAPI_acceleratorPedal', 'VAPI_pedalPos', 'VAPI_brakePedal', 'VAPI_brakePos',
                 'VAPI_steeringAngle', 'VAPI_signalLeft', 'VAPI_signalRight', 'VAPI_turnSignalActive'):
        ok, value = iface.DataGetValueRequest(name, timeout=2)
        print(name, bool(ok), type(value).__name__, str(value))
