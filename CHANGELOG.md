# Changelog

## Unreleased — Console, vehicle config and Service Mode

- Fixed the Service Mode panel reloading forever after a WSL restart. Runtime Setup now enables the AppArmor service and, on WSL, mounts securityfs at boot, so the lab's profiles are loaded again at every boot; without them `QtCarDvServer` rejects QtCar, the panel never learns that Service Mode is on and its watchdog keeps reloading it. A process that starts without its profile is now logged by name.
- **Display scaling on WSL.** The lab reads the Windows display scale and draws at that size instead of 100%. The panel scales through Qt. The center and instrument displays start the firmware at a larger window scale (`--window 0.9` instead of `0.6` at 150%) on a matching larger Xephyr screen or QEMU guest output, so text stays sharp and touches stay aligned; the size is reduced to fit the desktop. QEMU mode needs a rebuilt guest image. `INFOTAINMENT_LAB_SCALE` overrides the factor. The WSLg fractional-scaling setting suggested earlier blurred windows and enlarged the cursor; `python3 -m infotainment_lab.display_scale --disable-wslg-scaling` removes it.
- **Alerts instead of popups.** Refused or unknown configuration keys now raise an alert listed under Diagnostics › Alerts, with a warning icon and count on the Diagnostics sidebar entry, instead of a modal dialog. Adding a personal key by hand (for example `GUI_valetModePassword`) is refused right away with an alert naming the reason.
- **Alerts say why the firmware restarted.** Each car-config restart is recorded (`config-restarts.json`) and listed as an alert naming the display and the values it restarted for; Apply-and-restart and values reset after a restart loop are listed too, and the status banner names the values while the restart runs. The Alerts card stays in place with an empty state after Clear all, and alerts are plain rows that scroll with the page instead of a nested list.
- **Firmware cannot reach Tesla.** Names under `tesla.com`, `teslamotors.com`, `tesla.services` and `tesla.cn` no longer resolve for any firmware process or browser the lab starts. A preloaded shim (`native-netguard`) makes those lookups fail in QtCar, the cluster, Spotify, the media adapter, the data-value server, the visualization and `media-webapp-server`, and each log records `netguard: blocked lookup of …`. Chromium refuses the same domains through its resolver rules. The local `firmware-media` names still map to loopback. Other traffic, such as Google Maps tiles, is unchanged. Connections to literal IP addresses are not intercepted.
- **Power meter in kW.** The Drive tab power meter now spans -100 kW (regen) to +400 kW (drive) in 1 kW steps and writes that kW value to `VAPI_powerLevel`, instead of a -1 to 1 level.
- **Vehicle controls in tabs.** Drive, Wheel buttons and the vehicle-service groups now share one tab bar instead of stacked sections. The power meter (`VAPI_powerLevel`) is a slider on the Drive tab.
- **Car off is not Park.** Car off now also clears `VAPI_driverPresent` and `VAPI_vehicleInAccessoryPlus`, which keep-awake used to force on; Park leaves them on. Charging also sets the charge-port cover and latch (`Engaged`) values. Enum values are read from the firmware libraries, not yet observed on a running UI; check the per-field firmware response.
- **Charging sets the gateway charge state.** The Charging control now also writes `GTW_chargeState` (`Charging`, or `Disconnected` when off), which the lab never set before. Idle values come from parked-car exports; `Charging` itself is not yet observed on a running UI, so check the per-field firmware response.
- **Car off lets the screens sleep.** keep-awake no longer forces `GUI_enableDisplayKeepAlive`, `VAPI_icLCDOn` and `VAPI_icBacklightOn` on every two seconds; they now follow Car off with the other power values, so the firmware sees the car as off instead of being held awake. Car off also shifts to Park and zeroes speed and accelerator, and the Drive feedback line reports the firmware's response for these values as Power.
- **Full reset.** A Full reset button on the Device page, next to QEMU boot check, stops the session and deletes the cached session, engine copy, mount points, library index and saved device settings, like a first import. Firmware, map and QEMU guest files are never touched.
- Fixed Full reset stopping with "A firmware image is still mounted" when a Console shell or leftover process held the mount. Stop and Full reset now unmount the image themselves, lazily if it is busy (safe because it is read-only), and Full reset still never deletes through a mount it could not release. Starting after the FUSE daemon died clears the dead mount and mounts the image again.
- Fixed `pip install -e '.[dev]'` failing on two top-level packages; only `infotainment_lab` is packaged.
- **Documentation.** The README and its links now point to this repository and cover the Console, Vehicle config, Alerts, Service Mode, network isolation, Car off and the power meter. A new [vehicle configuration guide](docs/vehicle-config.md) describes imports, restarts and alerts, and the [compatibility matrix](docs/compatibility.md) is brought up to date.
- **A Console tab.** A terminal on a real pty, with Tab completion, history, Ctrl+C and a blinking caret. On the native Linux/WSL engine it opens a shell inside the running CID's firmware root (read-only, through a user namespace). On the QEMU engine it connects over SSH to the guest through a loopback-only forward (`127.0.0.1:2222`).
- Fixed the QEMU Console opening a plain login on the Debian guest instead of the CID. Connect now enters the firmware image mounted at `/firmware` in the guest (read-only, through a user namespace), as the native engine does; if the image is not mounted it says so and leaves you in the guest shell.
- **One-click SSH key.** Set up SSH key (or the first Connect) creates a lab-owned ed25519 key and authorizes it in the running guest through the guest agent, then confirms it. Guest images built with `scripts/build-virtual-guest.py` include an SSH server with key-only login; older images need a rebuild.
- Works from Windows through WSL2: key setup runs as a backend action and the shell runs inside the distribution.
- **A new configuration import starts from the defaults.** Importing a CSV replaces the previous configuration instead of merging with it: keys the old file set that the new one lacks are removed, and default keys it lacks go back to their default value, so Apply writes those resets too. Values already applied with the same value are not sent again. Editing a value or adding a key by hand still changes only that key.
- **Configuration imports withhold personal data.** Account logins, passwords and PINs, keys, device and network identifiers, and locations in a vehicle dump are never imported, stored or written; the import report lists how many were withheld and the session store refuses them. Live display and power state is listed but never written.
- Fixed a configuration import driving the displays with another car's live readings. Dumps that repeat each name (joined exports) turned telemetry such as `POWER_centerDisplayState` into pending writes, which kept the center display power-cycling. Repeated live values are now listed only, like single ones.
- Fixed vehicle dumps crashing the session. A dump that sets another UI language makes the firmware restart itself, and it sometimes aborts or segfaults while doing so; these are now handled as configuration restarts. Language settings that contradict each other (for example English language with a Norwegian manual language) are dropped after three restarts instead of looping, and are listed as conflicts. A Model 3 configuration (`VAPI_carType` `Model3`) can no longer be imported for an image with only the Model S/X interface: the import is refused with a message instead of crashing the center display. Restart also works again after a session has failed.
- A `ModelS2` (refreshed Model S) `VAPI_carType` is kept by the session's state writer instead of being reset to the default.
- **Service Mode panel (experimental).** The Service card no longer waits for a browser that was never started: the lab now runs the firmware's own `service-ui` backend and its `chromium-odin` window, as the vehicle does. The backend runs in its own unprivileged network namespace, which gives it the vehicle-network address it requires without changing the host network; its page is relayed to `localhost:8000`, and the firmware's `QtCarDvServer` supplies its vehicle values. Rerun Runtime Setup (or reload the AppArmor profile) so SpotifyServer and ChromiumAdapter accept the data-value server. Its token and identity checks are unchanged, and no diagnostic engine or vehicle link is provided, so functions that need them stay unavailable.
- **Service Mode task catalogue (experimental).** The Service panel now has an Odin engine to talk to: a lab stand-in (`runtime/odin-engine.py`) answers the firmware `service-ui` backend's D-Bus calls (`com.tesla.Odin`) and engine websocket. The panel lists the image's own task catalogue (691 tasks on the 2026.8.3 MCU2 image), gateway-config names, maintenance options and an empty service history. Running a task always ends as a routine error that says no vehicle is attached; config values are placeholders and read-only. The firmware `service-ui` itself is unchanged.
- Fixed the native media card loading forever when the firmware's `media-webapp-server` rejected a flag (such as `-secondary_port`) and exited. The lab now reads the server's `-h` output and passes only the flags that firmware defines.
- Fixed the native Service Mode interface opening outside the center screen. The center window was positioned only once at startup; the supervisor now checks every two seconds, pins the main window to the origin and moves any later firmware window (Service Mode, dialogs) back inside the screen. Browser windows are untouched.

## Unreleased — CAN channels and gateway emulation

- **A local CAN service.** The vehicle's own channel names — VEH, CHASSIS and PARTY — over SocketCAN `vcan` interfaces, with a software hub fallback when the kernel module or privileges are missing. Frames are traced per channel and decoded against a frame table.
- **An emulated vehicle gateway.** Per-direction routes with identifier filters, writes from the infotainment side locked by default behind a local HMAC handshake, checksum validation and a rate limit. Accepted climate and lighting requests feed back into vehicle services.
- **A CAN & gateway panel.** Start the service, watch the lock state and per-channel counters, unlock, send a frame through the gateway or straight onto a channel, and read recent frames with decoded signals.
- **Frame definitions and a `.dbc` reader.** The built-in `LAB_*` layouts carry the existing simulator and vehicle-service state; your own database can replace them at runtime.
- The gateway models behaviour only. It contains no vendor protocol, key, certificate or authentication scheme, and reaches no vehicle.

## 0.5.1 — 2026-09-16 · Startup and display fixes

- Fixed a startup error that could close the native Linux/WSL session before either screen appeared.
- Batched display updates so driving inputs and shared preferences spend less time waiting on the center and instrument screens.
- Fixed QEMU screen power management stalling the center display after about ten minutes without mouse or keyboard input.
- Reduced the time large QEMU previews occupy the control connection. Failed display updates now report an error and retry instead of retaining a successful status.

## 0.5.0 — 2026-09-16 · Material desktop & QEMU

- **A redesigned Qt interface.** Material 3 styling, light and dark themes, three accent colors, and compact navigation for smaller windows. Appearance and language settings are saved between sessions. The logo in the upper-left corner is gone.
- **QEMU in the device manager.** Choose a guest directory, start or stop the VM, preview both screens, and open the center or instrument window from the toolbar. The Debian guest uses a replacement Linux kernel and mounts your firmware read-only.
- **GPU acceleration on both screens.** The MCU2 desktop uses VirGL, with VirtualGL sharing the GPU with the separate instrument window.
- **Controls in one place.** Driving inputs, steering-wheel buttons, browser cards, camera feeds, and dashcam replay are available from the Qt panel in QEMU mode.
- **Smoother WSLg audio.** Buffered output handles playback, releases the desktop stream during silence, and reconnects when sound resumes.
- **Small fixes that help day to day.** Correct MPH/km/h labels, accurate gear feedback, and a held camera frame when replay is paused or finishes.

## 0.4.4 — 2026-09-10

- Fixed the native media card remaining at `Audio Initializing` by publishing `GUI_audioReady=true`, a valid `Base` audio type and a cleared Service Mode audio-reset state to both displays.
- Starts QtCar, QtCarCluster, SpotifyServer and ChromiumAdapter with the AppArmor peer names required by the firmware.
- Added persistent Debian/WSL AppArmor policy installation to Runtime Setup and verified successful SpotifyServer and ChromiumAdapter peer matches after restart.
- Native media health now reaches `services-running`; WSLg volume and mute routing remain connected to both displays.
- Added the GStreamer playback runtime and firmware ALSA aliases used by Toybox and chime fallbacks, including `fart`, so enabling audio readiness no longer exposes a missing playback executable or device.
- Connected replay motion to native ApViz with signed speed, playback gear, road-wheel angle and calculated yaw rate; Model X steering and forward/reverse animation now follow the committed camera frame, with the firmware road-wheel convention applied to reverse-camera guide lines.

## 0.4.3 — 2026-09-10

- Added a persistent Model X MCU2 vehicle profile and applies it to both display services whenever they start.
- Selected the newest meaningful values exposed by the 2026.26.6.1 services: P100D trim, Tesla adaptive suspension, TeslaAP3 driver assistance, permanent-magnet front drive unit, SEMCO backup camera, Valeo5 park assist, Model X radar placement, fold-flat restraints and 21-inch Twin Turbine wheels.
- Added per-signal application results to runtime feedback, so unsupported or rejected profile values are visible instead of silently ignored.
- Connected exterior color, interior trim and dual-motor state to the native 3D ego model; the model now receives the same profile as both displays.
- Verified all 32 profile signals on both center and instrument displays after a clean runtime restart.

## 0.4.2 — 2026-09-10

- Added a local vehicle-alarm state and publishes the firmware's native `VAPI_alarmStatus` as `Disarmed` by default. The previous invalid value blocked the normal Service Mode access-code flow.
- Confirmed the real MCU2 center display enters Service Mode after entering the normal code; no access-code, gateway or authentication check is patched.
- Made Service Mode a center-owned display channel. The instrument cluster receives enter/exit state and renders its native Service Mode overlay.
- Added a vehicle-alarm toggle to the Doors page for armed-state UI testing. It affects only this application's private display services and never sends a disarm request to vehicle hardware.
- Full diagnostic gateway services and Service Mode Plus remain unavailable in the local lab.

## 0.4.1 — 2026-09-10

- Fixed striped and scrambled native text by restoring OpenGL unpack alignment after each 3D texture upload, including failed uploads.
- Resolve center, cluster and firmware browser fonts from the selected image, with a private font cache. No firmware fonts are bundled or installed into the host.
- Added steering-wheel volume hold/repeat with release and focus-loss cancellation; corrected shared left/right/hazard indicator phases.
- Connected six door/trunk position flags to both displays and the native 3D view. Center lock/unlock and supported closure requests update the local model.
- Added Off, Parking, On and Auto light modes, a simulated dark environment, and consistent manual-light controls.
- Expanded Santa/theme/wheel preference synchronization and center-to-cluster playback metadata. Added native media process recovery, connection diagnostics and the scoped media-browser environment.
- Updated setup instructions: users must supply their own compatible Firmware Dump. Firmware, extraction tools and dump/export tutorials are not provided.
- Still unresolved: native Spotify login/playback and complete media-service confinement. Service Mode manual entry remains unverified. This update does not add physical vehicle or cloud services.

## 0.4.0 — 2026-09-09

- Added native Browser, Card view and Theater controls with separate Chromium runtime profiles.
- Corrected embedded pointer coordinates, drag capture, wheel delivery and physical keyboard routing.
- Connected embedded dashcam driving data to the same clock as the camera video, with pause, seek, playback speed, looping and manual takeover. Reopening a session holds the preview in Park until Play.
- Added local climate, body, lights, energy, audio and navigation controls with per-field firmware readback. Both displays share driving data and reconcile supported preferences in either direction.
- Added control pages, replay and X11 integration tests, and a generator for a clearly labelled public demo recording.

## 0.3.0 — 2026-09-09

- Connected the existing RGB24/V4L2 pipeline to the firmware's native backup-camera view.
- Camera source controls for a steering-linked pattern, looping local video and an existing writer output.
- Measured producer and firmware frame consumption, stale-source handling and stop/recovery controls.
- Shared source preview and separate window; camera playback continues with the device when the control panel closes.
- Verified 24 fps pattern/video input, original writer compatibility, and Reverse opening the firmware camera.

## 0.2.1 — 2026-09-09

- Double-click Windows launcher for the native Linux GUI, included with the Linux bundle.
- Direct WSLg desktop and Start-menu shortcut installer, startup logs and visible launch errors.
- Reopening the application activates its existing control panel; smaller windows can scroll.
- Corrected desktop application identity and simplified compatibility wording in the README.

## 0.2.0 — 2026-09-09

- Emulator-style device manager with searchable firmware entries and per-device launch preferences.
- Actual center and instrument display captures in a five-second overview.
- Native toolbar for display focus, restart, PNG capture, controls and camera.
- Preflight launch gating, guided setup, persistent errors and busy indicators.
- Scrollable layouts, keyboard shortcuts, matching documentation and refreshed screenshots.

## 0.1.0 — 2026-09-09

- Native Qt workbench.
- Local firmware library with drag and drop, build checks and read-only mounts.
- Standalone MCU2 center/instrument session with AMD WSLg graphics and embedded Chromium.
- Private display simulator for gear, speed, pedals, steering and turn signals.
- Camera pattern/local video preview, process diagnostics and sanitized report export.
- Native Linux and optional Windows/WSL packaging.

Known gaps at 0.1.0: firmware camera integration, map routing/imagery, theater/card browser modes, embedded drag/clipboard behavior, and complete vehicle-service emulation. See the READMEs for the current scope.
