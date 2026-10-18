# Local vehicle services and display synchronization

## Self-Driving interface simulation

Controls > Self-Driving simulation contains the default-off
`fsd_ui_simulation` switch. On the configured Model 3 ICE image, it makes the
native Start button available and handles Start/Stop as local display-state
transitions. A click selects ActiveFsd; Stop returns to Available. Speed, gear
and steering remain under manual/replay control. This provides no autonomous
driving controller or perception.

The native FSD menu and Start-from-Park settings must first be enabled and the
device restarted to prepare the panel. After that, the simulation switch takes
effect immediately. Disabling it restores the previous AP value/validity;
restarting always begins disengaged. The adapter fails closed when its required
native methods or enum names are absent. See [the configuration guide](vehicle-config.md#optional-self-driving-ui-simulation)
for the exact opt-in and [validation record](VALIDATION.md) for live evidence.

## Shared model

The Services page supplies a shared local vehicle model to the center and
instrument displays. Both displays receive the same battery, climate and
driving state. Native climate and audio controls feed changes back into this
model, so changing temperature or volume inside the firmware updates the
desktop controls as well.

The model is a desktop simulation. It does not communicate with a vehicle.

Car-config values from a vehicle dump are handled on the separate
[Vehicle config](vehicle-config.md) page.

| Domain | Local behavior | Practical limit |
| --- | --- | --- |
| Climate | Power, driver/passenger set points, cabin/outside temperature, fan, A/C and rear defrost request | Temperatures are supplied values; no thermal physics or compressor is running. |
| Closures | Individual positions for all four doors and both trunks, native Open/Lock/Unlock requests, and shared lock status | Native instrument 3D opening/closing is verified. Physical latches and powered-actuator timing are not modeled. |
| Lights | Off, Parking, On and Auto, headlight/high-beam and parking-light indicators | Auto uses the local Dark outside input. No physical lamps are controlled. |
| Energy | Battery percentage, charging state (session flags, `GTW_chargeState` `Charging`/`Disconnected`, charge-port cover and latch), charging power and charge limit | Charging does not increment the battery automatically. `GTW_chargeState` `Charging` is not yet observed on a running UI. |
| Audio | Volume and mute synchronize across the two displays and firmware audio streams | Only audio streams whose executable belongs to the mounted firmware are changed. |
| Navigation | Supplied GPS, heading, destination label, remaining distance and time; street base map observed after valid replay GPS | Offline NA imagery, route computation and live traffic remain unverified. |
| Tire pressures | Four editable simulated pressures, delivered to native Conti/Tesla TPMS display fields in bar | The firmware formats Bar/Psi according to the user's preference. Physical sensors, calibration and warning logic are not emulated. |
| Dashcam | Fresh GPS/heading follow the decoded video frame, alongside the six driving controls | Recorded driver-assistance and acceleration values remain metadata. |

Physical ECU/CAN services, drivetrain controllers, cellular provisioning, Tesla
accounts, phone keys, charging equipment, payments and cloud-only services are
not connected. Their status is listed as unavailable in the capability report.

## Delivery and acknowledgements

The backend validates changes with `VehicleServices.parse()` and atomically
writes `session/vehicle-services.json`. The runtime consumes new file versions,
applies existing fields on each private display, and reads the values back.
`session/vehicle-services-feedback.json` contains:

- `state` and `requested`: the current shared model, including accepted native
  climate/audio request changes.
- `firmware`: an acknowledgement for each field and display.
- `signals`: the individual native fields behind those acknowledgements.
- `source`: `desktop`, `native-ui` or initial `defaults`.
- `gps_source`, `capabilities`, `errors` and `updated_at`.
- `body_requests`: consumption and acknowledgement of native momentary requests.

The native display's door-position flags are supplied together, so changing one
door preserves the remaining doors. Its named readback is converted to the same
mask for verification. Momentary native requests are consumed once and reset
to None; a failed acknowledgement is retried without toggling a trunk again.
Pending commands from before connection are cleared without executing them.

Exterior-light mode synchronizes from the native selector and desktop panel.
The legacy Headlights checkbox is a manual override selecting On or Off. In
Auto, Dark outside determines whether the headlights and parking lights are on.

## Service Mode

The desktop Services page applies edits as they are made; there is no Apply
button. Its Modes tab has switches for Developer mode (`GUI_developerMode`),
Service mode (`GUI_serviceMode`) and Factory mode (`GUI_factoryMode`), plus
Transport mode (`GUI_transportMode` and `MCU_transportModeOn`), Showroom mode
(`GUI_showroomMode` and `MCU_showroomModeOn`) and Dyno test mode (`VAPI_dynoMode`).
Transport mode is verified on the 2026.8.3 MCU2 image; the showroom and dyno
names come from that image's QtCar strings. Each switch shows the firmware's own
response (Applied, or Local only when a display does not accept the name).
Native Service panel changes to `GUI_transportMode` update the switch. The local model publishes
`VAPI_alarmStatus=Disarmed` by default because an invalid alarm state causes the
native access-code dialog to reject entry. The Doors page can select Armed for
alarm-state UI testing. Both values remain inside this application's private
display services; no command is sent to vehicle hardware.

Native Service Mode entry was verified in the running MCU2 center display. Use
Controls → Software, hold MODEL for two seconds and enter the public service code
in the native prompt; exit through the native Exit Service Mode control. Enter
and exit state is center-owned and forwarded to the instrument display. This is
the touchscreen procedure in
[Tesla's Model S service manual](https://service.tesla.com/docs/ModelS/ServiceManual/en-au/air/GUID-0DC534D7-A4B8-417F-8E42-DF1560E970C2.html).

The Service card is the firmware's own web panel. QtCar embeds a Chromium
window titled `ChromiumOdin` that loads `http://localhost:8000`, served by the
firmware backend `/opt/diag/service-ui` on newer ICE images, or
`/opt/odin/service-ui` on older images (the vehicle's `chromium-odin` and
`service-ui` services). When Browser support is enabled and port 8000 is free,
the lab starts both from the mounted image with the vehicle's window, D-Bus and
policy settings. The backend aborts unless it can bind the center's
vehicle-network address `192.168.90.100`. Rather than add that address to the
host, where it would capture traffic for a real 192.168.90.x network, the lab
runs the backend in its own network namespace (`unshare --map-current-user
--keep-caps -n`, no root, as the desktop user and without capabilities) and
relays `127.0.0.1:8000` to it through `session/service-ui.sock`
(`runtime/service-ui-netns.py`). It reads vehicle values from the firmware's
data-value server, `QtCarDvServer`, which the lab starts under its firmware
peer name with a private `/tmp/dbus_dvaccess` directory. The backend keeps its own token,
factory-gated and identity checks; the lab supplies no credentials and no
CAN-over-Ethernet link, so functions that need them report their own
unavailable state. Newer backends also read `/var/etc/jcanproduct`, normally
created during vehicle boot. The lab writes the selected profile's generic
model name into `session/service-ui-home/jcanproduct`; a backend-only preload
redirects read-only opens of that one path. It neither creates host `/var/etc`
files nor changes credentials. Odin task assets remain under `opt/odin` even
when the web backend moved to `opt/diag`.

The vehicle's Odin diagnostic engine is replaced by a stand-in,
`runtime/odin-engine.py`. The backend reaches the engine two ways: D-Bus calls to
`com.tesla.Odin` `/Odin` on the session bus (`GetRunningTasks`,
`ServiceUIListTask`, `ServiceUIExecute`) and a websocket on `127.0.0.1:8080`
inside its namespace (`list_configs`, `read_service_history`,
`read_maintenance_history_options`), which the namespace wrapper relays to
`session/odin-engine.sock`. Results go back over that websocket as
`request_finished` messages. The stand-in answers from the image: the task
catalogue (`odin_bundle/.../task_data.py`), gateway-config names from the
engine's allowlist with placeholder, read-only values, and the localized
maintenance options. The service history is empty. Every task run, and every
other engine command, finishes with exit code 2 ("Routine Error") and the
message that no vehicle is attached. It runs no diagnostics, reaches no ECU and
performs no authentication or security access.

When the lab's CAN service is running, a task is first offered to its emulated
gateway as a `LAB_gatewayRequest` (`0x641` on `party`; byte 0 is `0x31`, bytes
1–4 the CRC-32 of the task name), so it shows up in the CAN trace. The gateway
passes it only while unlocked and in Service Mode, and the task's error says
which: `GATEWAY_REFUSED` with the gateway's reason, or `NO_ECU` when the request
crossed the gateway and nothing answered. Without the CAN service the error is
`NO_VEHICLE`, as before. See [the gateway's Service Mode link](can-gateway.md#service-mode).

The vehicle's alert daemon is replaced by `runtime/alertd.py`, which owns
`com.tesla.Alerts` `/Alerts` on the session bus. Services › Alerts (backend action
`vehicle-alerts`) writes the raised names to `session/vehicle-alerts.json`; the
stand-in answers `getActiveAlerts(q)` with `a(sq(tu)a{ss})` and `getRecentAlerts(q)`
with `a(sq(tu)(tu)a{ss})` (name, audience mask, set and cleared times, empty payload)
and emits `AlertSet` `(sq(tu)a{ss})` and `AlertCleared` `(sq(tu)(tu)a{ss})` when the
file changes, the shapes the image's own `alertd` (2026.8.3) introspects. That
daemon is not run: it learns alerts only from vehicle CAN, so it never had any. The page's **Alerts & DTCs** tool is gated by the `FEATURE_enableSUIAlertsPanel`
data value, which keep-awake keeps `true` on `QtCarDvServer` (the displays pick
it up from there without a UI restart); raised alerts are listed there and also
appear as counts and health dots on the sections the image's
`service_ui/static/assets/alerts.json` maps them to. `service-ui` subscribes to
the signals once, so after an `alertd` restart only a page reload shows changes.

None of these processes marks the session degraded when it exits; see
`dv-server.log`, `odin-engine.log`, `alertd.log`, `service-ui.log`, `service-ui-relay.log` and
`chromium-odin.log`.

Verified on the MCU2 center display: the native Service Mode panel renders its
Vehicle Info, Tools, Driver Assist, Infotainment, High Voltage, Low Voltage and
Thermal sections. Vehicle Info reads Firmware from `VAPI_carVersionString`
(the image's own version, written at each display start), Autopilot Hardware
from `GTW_dasHw` (from an imported config or a Vehicle config value; "None" without one) and Odometer
from `VAPI_odometer` in miles (the Odometer control on the Energy tab). VIN stays
empty and the CAN Viewer is locked. The Odin engine protocol was verified
against the firmware `service-ui` binary: the task catalogue, configs, maintenance
options, service history and the no-vehicle task result reach the page.

This fixes the native UI precondition without changing its access-code or
authentication logic. The red `NO GATEWAY SYSTEM / GTW LOCKED` status is expected:
complete diagnostic gateway routines and Service Mode Plus are not implemented.

During replay, the service model retains manually entered location values.
The active recording's GPS/heading are in `replay-status.json`, and `gps_source`
identifies which input is being delivered. Take over from replay before using
manual location changes to drive the display.

`accepted` means the native DataValue interface read back the requested value.
It does not prove a physical service or every animation is implemented.
`partial`, `unsupported`, `rejected` and `mismatch` retain the distinction between
stored simulator values and native display support. `local-model` identifies
values that are intentionally stored only in the desktop model.

The driving worker checks changed controls every 50 ms. Unchanged frames make
no control bus calls; periodic verification detects overwritten values and
display restarts. Host Internet and disk measurements run separately every
30 seconds. The control feedback records the target tick and measured apply
duration so a slow desktop can be diagnosed without assuming a fixed frame rate.

## Other display setting requests

Settings without a field in the model above (for example an acceleration or
drive mode) are requested by the center display as a `GUI_<name>Request`
DataValue. On a vehicle a module answers on a status value the UI binds to; in
the lab nothing did, so the choice snapped back or had no effect.
`display_requests.py` now answers them:

1. At session start keep-awake scans the image's `QtCar` and `libQtCar*.so`
   for `GUI_*Request` names (cached in `session/display-request-names.json`).
2. Every 0.5 s it reads those names on the center display. A change after
   connecting is a request; a value already present at connect is not.
3. The request is written to its status values and read back. Without a route
   the status values are the names the display actually exposes among
   `VAPI_<name>`, `VAPI_<name>Status`, `VAPI_<name>State`, `GUI_<name>`,
   `GUI_<name>Status`, `GUI_<name>State`, `VAPI_is<Name>` and `VAPI_<name>Active`,
   then up to eight other `VAPI_`, `GUI_` or `LIGHT_` names in the image that
   contain `<name>` (configuration, presence and fault names are skipped). Only a
   status of the request's kind is paired; a flag also pairs with an `On`/`Off`
   lamp state.
4. Accepted values are written again when the center display restarts.

Names the model, vehicle profile or a configuration override already own are
never touched. An explicit route in `session/request-routes.json` replaces the
pairing, maps request values to status values, or disables a request:

```json
{
  "GUI_exampleModeRequest": {"status": ["VAPI_exampleMode"], "values": {"2": "Fast"}},
  "GUI_ignoredRequest": null
}
```

`session/display-requests-feedback.json` lists each request with its result
(`accepted`, `partial`, `rejected` or `unrouted`), the last 50 requests, and
`dropped_calls`: D-Bus errors on the private bus (`ServiceUnknown`,
`UnknownMethod` and similar), counted by service or method, from `dbus-monitor`.
A refused status write lists the value the display kept (`read_back`), which
names the value it expects; an `unrouted` request lists the related names in the
image (`related`). Either, or a dropped call, names what to route next. Status value
names are matched, not taken from a vendor table, so check the result on the
running UI.

## Power meter and Car off

The Drive tab's power meter writes `VAPI_powerLevel` in kW, from -100 (regen) to
+400 (drive) in 1 kW steps; `VehicleServices.parse` rejects values outside that range.
The kW unit is inferred from the firmware, not yet verified on a running UI.

**Car off** is not Park. It shifts to Park, zeroes speed and accelerator, and
sets the power rails, `VAPI_driverPresent`, `VAPI_vehicleInAccessoryPlus`,
`GUI_enableDisplayKeepAlive`, `VAPI_icLCDOn` and `VAPI_icBacklightOn` to off, so
the firmware can sleep its screens. `keep-awake.py` no longer forces the last
three on. Selecting a gear turns the car back on. The Drive feedback line reports
the firmware's answer for these values as Power. Enum values were read from the
firmware libraries and have not yet been observed on a running UI.

## Two-display preferences

Distance, temperature, charge and tire-pressure units, volume/mute, navigation
and response volume, timezone and available clock-format fields synchronize in
both directions. A change on either display updates its peer. If both displays
change the same field between polls, the center display wins; the report marks
the conflict. A restarted display receives its live peer's values.

The source update adds Santa mode (`GUI_HoHoHoMode`), its cheer setting,
supported day/theme options and steering-wheel preferences. Santa is mirrored
both when enabled and disabled. Playback title, artist, album, elapsed/duration,
source and status travel from center to instruments. The instruments cannot
overwrite the player's state; empty metadata clears the previous text. A failed
field is reported separately and does not stop the remaining channels.

The Controls page provides native media and instrument-panel button actions.
Consecutive volume presses use the latest pending request until the worker
acknowledges its file version, so rapid presses do not reuse stale feedback.
Volume buttons repeat after a 450 ms hold and then every 180 ms, subject to
backend completion. The UI does not queue repeats behind a pending request.
Release, pointer leave, focus loss, hiding or disabling the button cancels
repetition. Other actions fire once per press to avoid repeatedly toggling mute.
An accepted button command does not assert that a logged-out player started
playing or that a physical steering-wheel switch was connected.

Turn signals publish both intent booleans and the native `VAPI_turnSignalActive`
enum (`Off`, `Left`, `Right`, `Both`). The two `LIGHT_turnIndicator*` fields use
`On`/`Off` values with a shared monotonic clock: 400 ms on, 400 ms off. The active
direction remains selected throughout blinking. These fields are delivered to
both displays; individual D-Bus writes are not an atomic multi-display update.

`session/display-link.json` records each field's source, both observed values,
delivery/readback result, connected displays and routed audio streams. Unsupported
clock-format fields are listed explicitly instead of being counted as synchronized.

Driving speed is supplied in km/h through the desktop API. The native vehicle
speed remains metres per second; the displayed number follows each display's
Miles or Kilometers preference and is explicitly rounded to the native integer
display-speed field. Floating readback allows only half of the interface's
final rendered decimal digit.

## Validation

On the local `2026.26.6.1` MCU2 session, both native displays read back changed
driver/passenger temperature, fan speed, cabin temperature, battery percentage,
charging state/power and the headlight telltale. A native climate request updated
the shared model and the other display. Distance-unit changes propagated in both
directions. The check restored the original model and kept the simulator parked.

Eight preference fields have populated values in this session. The two timezone
fields are registered but initially unset; the two clock-format names are absent.
Absent fields are queried once per display process, then cached until that
display restarts. This avoids repeatedly adding unsupported-field messages to
the firmware logs.


## Model 3 expanded parked visualization

On native single-display Model 3 sessions, drag the boundary between the vehicle
and map right to expand the 3D view. Drag left to restore the regular map layout.
`GUI_expandFsdVisualizationEnable` must be enabled. The desktop input adapter
advertises the layout capability and allows the parked layout using the native
`VehicleUtils::isCarParked` query; it does not change the simulated gear or
parking-brake values. Track mode remains excluded. Other sessions keep the
firmware's own layout decision. This is a desktop visualization feature.

## Simulated Park Assist

Controls > Vehicle services > Park Assist provides an opt-in ultrasonic simulation
with five front and five rear distances, each from 0 to 250 cm. Values retain
one decimal place. The native display converts them to its selected distance
units. The failure switch changes the native status to TemporaryFailure;
turning simulation off sets Disabled. Both cases clear obstacle distances to
the native negative/unavailable value and mark the simulated sensor interface
inactive. Re-enabling a healthy simulation restores the saved distances.

For the tested Model 3 ICE image, Vehicle config must have
`FEATURE_parkAssistEnabled=true`, `VAPI_parkAssist=Valeo` or `Tesla`, and
`GUI_useVisionParkAssist=false`. Apply configuration changes and restart the
device if the panel requests it. `Valeo5` is not a valid named enum on this build.
Vision mode requires perception data that this ultrasonic simulation does not
produce. The native display still decides when Park Assist is visible according
to gear and distance; no GUI activation flag is forced by the simulator.

The worker publishes local processed PARK and PARK_USS distances, status,
service and sensor-interface health with normal per-field readback. It does
not generate physical CAN traffic, camera perception or steering commands.
