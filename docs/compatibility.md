# Compatibility

This matrix describes the current `main` branch (unreleased changes after
**0.5.1**) and the local configurations used for validation. An imported image's
build profile determines whether it can launch. The library can inspect images
beyond the exact launch profile.

Features added since 0.5.1 (Console, Vehicle config, Alerts, the Service Mode
panel, network isolation, Car off) were built and checked on the **native**
engine. They have not been validated inside the QEMU guest, and no
[validation record](VALIDATION.md) covers them yet.

## Host and firmware

| Component | Status |
| --- | --- |
| Windows 11 + WSL2 + Debian 13 + WSLg | Tested native Linux GUI and device runtime. |
| Physical x86_64 Linux | Launch path implemented; not validated on a separate physical host. Requires X11/XWayland, systemd user services and FUSE. |
| Optional native Windows control panel | Uses the same Debian WSL backend; this is not a Windows firmware runtime. |
| AMD Radeon / Mesa D3D12 | Observed accelerated renderer on the tested WSLg host. Other GPU configurations remain unverified. |
| Native fonts | Both Qt displays load Universal Sans from the selected firmware; Fontconfig uses an image-specific font directory and private cache. |
| `2026.26.6.1` Model S/X MCU2 (`modelsx_info2`) | Supported exact launch profile, with center display and instrument cluster. |
| Other Model S/X MCU2 builds | Launch on the **experimental** generic MCU2 profile (`mcu2-generic`), without a build-ID check. Used daily with 2026.8.3 on the native engine; no validation record and no QEMU validation. |
| Other ICE (MRB) builds | Experimental generic single-display profile (`ice-mrb-generic`); unverified. |
| Maps | A supplied NA image can be inspected/mounted. A street base map rendered after valid replay GPS, in a session without an offline map mounted. Offline NA imagery and routing remain unverified. |
| Locally built Debian 13 executable | Built and tested with glibc 2.41; older glibc versions remain unverified. Source launch is available; CI is configured for Ubuntu 22.04. |

The launch profile is recorded in the application's `profiles.json`:

| Binary | Accepted build ID |
| --- | --- |
| Center display | `6e5be629ea4c0546bc157c9ac6c5bd323b888ba7` |
| Instrument display | `b568abe1e320808c6131ae95bcffed7736762aae` |

The MCU2 visualization uses the supplied Godot application. Renderer information
comes from the actual host graphics stack. No frame-rate or input-latency guarantee
is made for other systems.

## Browser and desktop integration

| Feature | Verified scope | Limit |
| --- | --- | --- |
| Browser | HTTP/HTTPS pages inside the firmware center UI; pointer, keyboard, scrolling, WebGL and audio path | Web application behavior varies; not all sites are tested. |
| Card view | Native compact view, resizing and browser interaction; shares the visible Browser app/profile | Does not imply every firmware card application is implemented. |
| Theater | Firmware catalog and YouTube home page | Commercial streaming, DRM playback, account-dependent flows and all catalog apps remain unverified. |
| Dragging | Embedded page receives motion and a release; draggable tile and range slider exercised at native scale | No universal claim for every website gesture. |
| Audio | Firmware stream routing and volume/mute control on the host | Physical DSP, microphone/telephony and subjective playback quality are not modeled. |
| Native music card | Dedicated media web app, ChromiumApp, adapter and Spotify processes run; Spotify SDK reports connectivity | Native service security-context rejection still prevents Spotify login/playback. |
| Multiple windows | Center, instruments, panel and optional camera preview | Each firmware view remains a separate desktop window; the device overview is view-only. |

Clipboard integration is not included.

## Lab tools

| Feature | Verified scope | Limit |
| --- | --- | --- |
| Console | Shell in the running CID's read-only firmware root through a user namespace (native); SSH to `127.0.0.1:2222` with a lab-created ed25519 key, then the same root at `/firmware` (QEMU) | The QEMU path needs a guest image built with the SSH server. |
| Vehicle config | `Name,Value` CSV import, search, edit, apply with per-row firmware answer, export; personal data withheld; live readings listed only | Car-config values restart the firmware UI; see [vehicle configuration](vehicle-config.md). |
| Alerts | Config refusals, unknown keys and configuration restarts listed under Diagnostics | At most 100 alerts are kept. |
| Network isolation | Tesla-domain lookups fail in every firmware process and browser the lab starts (`native-netguard`, Chromium resolver rules) | Connections to literal IP addresses are not intercepted. |
| Full reset | Clears the lab's session, engine copy, mounts, library index and device settings; releases busy mounts lazily | Never touches firmware, map or QEMU guest files. |
| Display scaling on WSL | The panel follows the Windows display scale through Qt; the firmware draws the center and instrument displays at a larger window scale on a matching Xephyr screen or QEMU guest output, fitted to the desktop | Not checked against real firmware: QtCar window scales other than 0.6 and 1, and larger guest modes, are untested. QEMU needs a rebuilt guest image. |

## Camera and recorded driving data

| Feature | Verified scope | Limit |
| --- | --- | --- |
| Camera source | Pattern, local H.264 video and existing 1280×720 RGB24 output through the native camera input | Only the native backup-camera view is validated. |
| Feed health | Independent fresh-source and actual V4L2-consumption measurements | An open producer alone does not mean the firmware is consuming frames. |
| Dashcam parser | Local H.264 MP4 with the project's embedded SEI telemetry fields and MP4 presentation timestamps | Maximum 8 GiB, two hours and 300,000 video packets per selected clip. |
| Playback | Pause, seek, rate, loop/end and manual ownership | One selected camera view at a time. |
| Shared driving data | Gear, speed, accelerator, brake, steering and signals follow the committed video frame | Brake is a pressed/released flag. Speed and pedals do not form a vehicle physics model. |
| Location | Valid recorded GPS/heading delivered to both local display services | Accuracy is the recording's; no real GPS hardware or live route engine is connected. |
| Recorded assistance state | Retained for inspection | Does not activate a driving-assistance controller. |

Generate a public sample from source with `python3 scripts/make-replay-demo.py`.
The resulting `build/replay-demo.mp4` contains 12 seconds and 288 embedded samples,
with synthetic graphics and no GPS location. It requires FFmpeg with libx264 and
drawtext. See [replay documentation](replay.md).

## Vehicle services and synchronization

| Domain | Local behavior | Limit |
| --- | --- | --- |
| Climate | Native requests, shared temperatures, fan, A/C and defrost request | Supplied state; no thermal or compressor physics. |
| Closures | Six independent door/trunk positions in both displays and the native 3D view; center lock/unlock and supported closure requests update the local model | No physical actuators; unsupported native request types are not executed. |
| Lights | Off, Parking, On and Auto with simulated ambient darkness; shared headlight/high-beam/parking indicators | No physical lamps. |
| Energy | Battery, charge limit, charging state and power; charging also sets `GTW_chargeState` and the charge-port cover and latch; power meter from -100 kW to +400 kW | No battery model or charging equipment. The kW unit of `VAPI_powerLevel`, `GTW_chargeState` `Charging` and the charge-port values are read from the firmware or parked-car exports, not yet observed on a running UI. |
| Audio | Shared volume/mute and host audio-stream control | Only the mounted firmware's streams are adjusted. |
| Navigation | Supplied GPS, heading, destination label and remaining trip metadata; street base map observed after valid replay GPS | Offline NA imagery, route computation and live traffic remain unverified. |
| Tires | Four editable local pressure values | Native TPMS units remain unverified; pressure is not injected. |
| Driving state | Same local inputs sent to both displays, with readback. Car off shifts to Park and turns off the power rails, driver present, accessory power and display keep-alive values | Does not recreate the complete vehicle IPC graph. The screens sleeping after Car off has not been observed on a running UI yet. |
| Preferences | Santa, supported theme/wheel and unit/audio preferences; center-owned playback metadata forwarded to instruments | The current default session reports 23 shared values; unsupported fields remain in diagnostics. |
| Service Mode | Native center entry through the normal access-code flow; enter/exit state forwarded to the instrument cluster; the firmware's Service panel (`chromium-odin` and `service-ui`) is started locally, with an Odin engine stand-in serving the image's task catalogue | Tasks never run (they report that no vehicle is attached); gateway-config values are placeholders. Functions needing a service token or vehicle identity, complete diagnostic gateway services and Service Mode Plus are not implemented. |
| Vehicle/cloud-only services | Capability report lists unavailable domains | Physical ECU/CAN, powertrain, cellular provisioning, accounts, phone keys, payments and remote services are not connected. |

“Applied” means the display read back the intended value. Unsupported, rejected,
partial and mismatched values remain distinct. See [service details](vehicle-services.md)
and the [validation record](VALIDATION.md).


## Pending changes

These are open and not part of `main`; this matrix will change when they land.

- **Full CSV import reset.** A full import would reset values left over from a previous CSV to defaults first; see [vehicle configuration](vehicle-config.md#pending).
