# AutomationApp availability in the local firmware

Investigation of the imported **2026.26.6.5 ICE/MRB** image and its running
native session. These findings are specific to that image, not all firmware
versions. No firmware binaries or runtime settings were changed for this check.

## Observed state

The running `com.tesla.CenterDisplay` service returned the following values via
`com.tesla.LocalDataValue.DataGetValueRequest`:

- `FEATURE_automationApp`: supported, `true`.
- `FEATURE_enableAutomationAppInTransportMode`: supported, `false`.
- `GUI_transportMode`, `GUI_factoryMode`, `GUI_valetMode`: supported, `false`.

AutomationApp is compiled into `/usr/tesla/UI/lib/libQtCarGUI.so.1.0.0`, with
automation UIML assets present in the image. It has no separate external-app
`app.conf`. The window constructor uses the internal name `automation`.

## Availability conditions

Symbol and disassembly inspection establishes these conditions:

- `VehicleUtils::hasAutomationApp()` returns true when the cached Qt setting
  `gui/force_has_automation_app` is true. Otherwise it requires both
  `VehicleUtils::chinaVehicle(false)` and `FEATURE_automationApp`.
- `AutomationAppWindow::appIsAllowed()` also requires
  `FEATURE_enableAutomationAppInTransportMode` when `GUI_transportMode` is true.
- `allowInValet()` and `allowInFactory()` return false.
- `appIsVisibleInLauncher()` returns true, but the separate
  `showInAppLauncher()` method returns false unconditionally in this image.
- `VehicleUtils::isAutomationServiceEnabled()` reads the setting
  `gui/force_disable_automation_service`, but returns false unconditionally in
  this image. Setting that key to false cannot enable this implementation.

The first availability override can be expressed as:

```ini
[gui]
force_has_automation_app=true
```

For native sessions, the launcher copies
`infotainment_lab/runtime/display-settings-mcu2.conf` into each display's
`.Tesla/car/settings.conf` at every start. Add the key to the existing `[gui]`
section of that source file for a persistent experiment. Changes to the generated
session copy are overwritten on restart. The setting is cached by the firmware,
so changing it while the display runs is insufficient.

This override addresses the regional availability check. It does not establish
launcher visibility or working automation execution. Enabling those paths would
require further work on a replacement library or an implementation providing the
missing behavior, followed by a runtime test.

The live display also exposes `CenterDisplayDbus.startApp(requestingAppName,
appName, deepLinkData)`. Its presence and the constructor name provide a route
to investigate direct opening of `automation`; no launch or successful execution
was tested during this investigation.

## Reproducing the static checks

Run `nm -D -C` and `objdump -d -C` on the library in the original mounted image.
The relevant ELF virtual addresses in this image are:

- `VehicleUtils::hasAutomationApp()`: `0x3717ae0`.
- `VehicleUtils::isAutomationServiceEnabled()`: `0x3717bb0`.
- `AutomationAppWindow::appIsAllowed() const`: `0x2decb10`.
- `AutomationAppWindow::showInAppLauncher()`: `0x2e09fa0`.
- `AutomationAppWindow::appIsVisibleInLauncher()`: `0x2e09f80`.

These are virtual addresses, not portable file offsets or patch instructions.
Check the actual library again for another imported image or replacement.
