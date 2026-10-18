# Vehicle configuration

The **Vehicle config** page loads a `Name,Value` CSV, such as a configuration dump
from your own car, and writes its settings to the running displays as named
DataValues, the same way [vehicle services](vehicle-services.md) does. Parsing and
filtering live in `config_csv.py`; the page is `config_panel.py`.

The page starts from the lab's own defaults, the values the vehicle profile
(`runtime/vehicle-profile-model-x-mcu2.json` for S/X,
`runtime/vehicle-profile-model-3-mcu2.json` for single-display ICE/MRB) writes on
every display start. The firmware layout chooses the profile automatically.
Saved edits and drafts are separate for the two layouts. Legacy Model 3 edits
stored under the S/X settings key migrate to the Model 3 settings key.

The Model 3 profile is an experimental RWD simulator baseline, not a validated
hardware configuration. Its enum names were checked against the local
2026.26.6.5 ICE image. It uses chassis label `"3"` (ordinal 2; ordinal 3 is Model Y),
no air suspension, Model 3 restraints and wheels, and a rear-drive configuration.
Unsupported numeric hardware values were replaced with valid enum names, and
the unsupported backup-camera key was removed from the active defaults.
Previous local signals remain in `previous_local_signals` as reference metadata;
they are not written. The firmware version comes from the selected image unless
explicitly overridden. Hardware options may need adjustment for another build.
Profile writes distinguish accepted values from rejected or mismatched readbacks.

## Vehicle selector

**Controls > Vehicle** writes the same overrides without the CSV page: model (Model 3 or
Model Y, which also picks the matching profile), paint (`VAPI_exteriorColor`), wheels
(`VAPI_wheelType`) and Autopilot hardware (`VAPI_driverAssist`). Choosing a model selects
its stock wheel. Options live in `vehicle_options.py`. Apply confirms, saves to
`session/config-values.json` and restarts the device. The EU market switch sits on the same tab.

## Import

**Import CSV** reads the file and lists every row. Entries whose value is
`@invalid` carry no usable setting and are skipped. A name repeated in joined
exports is kept once, at its first position, with its last value; repeated
headers are ignored.

Only settings are queued for writing: names under the `FEATURE`, `GUI`, `VAPI`,
`APP`, `APTRIAL`, `GTW`, `OPTION` and `AUTONAVDEBUG` prefixes. Everything else in a
dump mirrors hardware or live telemetry and is listed for reference only.

Two kinds of values are never written, whatever their prefix:

- **Personal data.** Account logins, passwords and PINs, keys and certificates,
  device and network identifiers (IMEI, ICCID, MAC, SSID…), email, contacts and
  locations are never imported, stored or written. The import report counts how
  many were withheld, and the session store refuses them. Adding such a key by
  hand (for example `GUI_valetModePassword`) is refused with an alert.
- **Live readings.** `POWER_*` values and names ending in `DeviceState` are listed
  but never written. Another car's display power state would make the simulated
  display power-cycle.

A Model 3 configuration (`VAPI_carType` `Model3`) is refused on an image that has
only the Model S/X interface, because the center display would crash. `ModelS2`
is kept as written.

## Edit and apply

Search by name or value, show **Changed only**, edit values in place, **Add key**
or **Remove selected**. Changed rows show the app default in their tooltip.
**Apply** writes the changed values to the running displays, and each row shows
the firmware's answer: Applied, Not supported, Rejected or Mismatch. **Defaults**
returns every row to the vehicle-profile value, and **Export CSV** saves the
current table.

## Configuration restarts

The Model 3 lab profile enables `GUI_enableSourcePicker` by default. The native
Audio settings panel reads this boolean to show its Sources section; each source
has its own visibility switch. The default lives in
`infotainment_lab/runtime/vehicle-profile-model-3-mcu2.json`, while deliberate
local overrides are stored under `session/config-values.json` in the lab data
directory. This setting exposes the selector; it does not sign into a media
service or make a subscription available.

Some car-config values make the firmware restart its UI; a changed UI language is
the common case, and the firmware sometimes aborts or segfaults while it does so.
The supervisor treats these exits as configuration restarts rather than failures:

- Each restart is recorded in `session/config-restarts.json` (time, display, the
  values that changed, and values dropped after a loop; the latest 50 are kept),
  and the status banner names the values while the restart runs.
- Language settings that contradict each other, such as an English language with
  a Norwegian manual language, are dropped after three restarts instead of looping,
  and are listed as conflicts.
- If the restart allowance runs out, the failure names the values that kept the
  firmware restarting. Restart works again after a failed session.

## Alerts

Refusals, unknown keys and restarts appear under **Diagnostics › Alerts**, with a
warning icon and count on the Diagnostics sidebar entry, instead of modal
dialogs. One alert is listed per recorded restart, naming the display and up to
12 of its values (the tooltip has the full list); Apply-and-restart and values
reset after a restart loop are listed too. At most 100 alerts are kept. **Clear
all** empties the list and leaves the card in place.

## Pending

A full CSV import currently keeps values from a previously imported CSV that the
new file does not set. Resetting to defaults before a full import is being worked
on, together with the language and locale restart loop those leftovers can cause.

## Local FSD menus on the Model 3 ICE image

On the tested `2026.26.6.5` image, `SelfDriving` and `FullFSD` profile labels alone
do not expose all FSD settings. The local session uses these explicit overrides:

- `VAPI_driverAssist=TeslaAP3`: simulated AP3 hardware profile. The previous
  `ParkerPascal2_5` profile fails the native HW3-or-higher check.
- `FEATURE_fullSelfDriving=true`: expose the FSD feature in Self-Driving settings.
- `GUI_enableFSDFunctions=true`: enable the FSD functions preference.
- `FEATURE_hasFullSelfDrivingNavMaps=true`: simulated map-availability capability
  for this UI exercise. This flag does not install or validate FSD navigation
  maps; the separate local TeslaMaps bundle still supplies ordinary map/routing.
- `GUI_fsdControlEnabled=true`: select the FSD settings mode after the capability
  prerequisites are present. This is a preference, not a driving engagement.

The existing `VAPI_autopilot=SelfDriving`, `VAPI_autopilotBase=SelfDriving` and
`GUI_autopilotConfigType=FullFSD` values are retained. Overrides live in
`session/config-values.json`; the desktop's saved Model 3 rows must agree so
reopening the panel does not resend an older preference. The native
`GUI_fsdAppAllowed` flag is derived by the OS rather than forced.

With the separate Self-Driving UI simulation disabled, the menu setup injects
no `DAS_autopilotState` or autonomous control requests. Calibration, perception
and the FSD driving computer are not implemented by this menu setup.
Firmware binaries, account credentials and subscriptions are unchanged.

### Start Self-Driving button

The local session also selects `GUI_enableStartFsdFromPark=true`. The tested
image already exposes `FEATURE_enableStartFsdFromPark=true`; enabling that
capability alone does not select the driver's preference or supply controller
feedback.

The worker rechecks six explicitly selected UI simulation inputs every two
seconds: `FEATURE_fullSelfDriving`, `FEATURE_hasFullSelfDrivingNavMaps`,
`GUI_enableFSDFunctions`, `GUI_fsdControlEnabled`,
`GUI_enableStartFsdFromPark` and `GUI_isOnNavigationMap`. Cached values are read
back, so a late firmware reset is repaired rather than incorrectly reported as
still applied. Removing an explicit override stops enforcing it. Vehicle
configuration fields and driving commands are excluded from this refresh.

For a single-display Model 3 session, the supervisor enables a native panel
preview only when `FEATURE_fullSelfDriving`, `GUI_fsdControlEnabled` and
`GUI_enableStartFsdFromPark` are all explicitly true. It sets the session-only
`TESLA_NATIVE_FSD_PANEL_PREVIEW=1` environment flag; S/X sessions retain the
native layout. Removing any of these explicit selections disables the adapter
on the next device restart.

The `native-fsd.c` adapter prepares the native FSD panel inside
`ClusterWindow::loadUIML` before the late desktop profile inputs arrive. Its
temporary layout capability applies only to that markup-construction context
and thread; all other `hasFsdPanel` calls retain their native results. The view
can then show an unavailable Start button when the native Start-from-panel
preference allows it and FSD is inactive. Native charging/autopark panel guards
and the active FSD view remain authoritative. Missing public state queries
leave the visibility preview disabled.

In the tested session, `AutopilotManager::poll` still publishes
`GUI_startFsdButtonState=Unavailable` and
`GUI_startFsdButtonUnavailableReason=ReasonNone` without controller feedback.
With simulation disabled, the panel reads `GUI_fsdPanelState=StartFsd` and
renders the native gray button. Visibility is deferred until
`CenterDisplay::createViews` has completed; profile callbacks during construction
cannot expose the partially initialized panel.

### Optional Self-Driving UI simulation

Under **Controls > Self-Driving simulation**, **Enable Self-Driving UI
simulation** selects the local `fsd_ui_simulation` vehicle-service flag. It is
off by default. The configured Model 3 session in this validation has explicitly
enabled it at the user's request.

Once the FSD panel layout is ready, the switch applies immediately:

- Enabled and disengaged: native button Available, AP state Available.
- Click **Start Self-Driving**: native AP state ActiveFsd, Stop button Available.
- Click **Stop Self-Driving**: return to Available.
- Disable the simulation: restore the previous AP value/validity and native
  button availability. A device restart always begins disengaged.

The adapter resolves enum values from the running image's native maps. Only
the opted-in Start state, Stop state, Start unavailability reason and AP state
are substituted before their native EventLocker commits. Observers therefore
do not alternate between native unavailable feedback and simulated availability.
The native manager continues its normal work. Start/Stop controller requests
are handled locally while this simulation is enabled; no controller request is
forwarded. The tested Qt4 constructors/destructors own the opaque value/locker
storage, without accessing DataValue object offsets. Missing ABI functions or
enum names leave simulation disabled with a diagnostic message.

This changes interface state only. It supplies no perception, steering, speed,
gear changes, FSD route execution or physical CAN controller.

### Local FSD region simulation

The native `isCarLocalizedToCountryList` check reads `GUI_navVehicleCountry` as
an ISO alpha-3 string through `GeoUtils::iso3LetterCountryToNumeric`, and also
requires `GUI_isOnNavigationMap=true`. The previous Model 3 default `US` used
the wrong format for that particular GUI field; its corrected default is `USA`.
The separate `VAPI_countryCode` enum still uses `US` and is not changed.

For the local FSD menu exercise, the session explicitly stores:

```json
"GUI_navVehicleCountry": "USA",
"GUI_isOnNavigationMap": true
```

The second value deliberately simulates navigation-map coverage. These values
remove the native Self-Driving page's regional warning without changing GPS
coordinates, the mounted EU map or firmware binaries. They are simulator UI
inputs, not proof that a real driving region or FSD map has been approved.
To stop forcing map coverage, remove the `GUI_isOnNavigationMap` override in
Vehicle config and restart the owned device. The ISO alpha-3 format correction
can remain.
