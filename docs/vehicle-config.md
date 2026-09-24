# Vehicle configuration

The **Vehicle config** page loads a `Name,Value` CSV, such as a configuration dump
from your own car, and writes its settings to the running displays as named
DataValues, the same way [vehicle services](vehicle-services.md) does. Parsing and
filtering live in `config_csv.py`; the page is `config_panel.py`.

The page starts from the lab's own defaults, the values the vehicle profile
(`runtime/vehicle-profile-model-x-mcu2.json`) writes on every display start.

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
