# Validation record

## Active Start/Stop Self-Driving UI simulation (2026-10-16)

- The user explicitly requested an active button and simulated engagement on
  click, superseding the earlier display-only scope. Added the default-off
  `fsd_ui_simulation` switch under Controls > Self-Driving simulation and enabled
  it for this local session.
- Tested image: `2026.26.6.5` ICE/MRB, Model 3 single display. Native build IDs:
  libQtCarGUI `6bad44bbbe10035e9e02d0a3c0624e273fce2d7b`;
  libQtCarUtils `f6f6a42bfb07d49901afbcc444d545b2c7885fb5`.
- The native panel factory is still enabled only within markup construction.
  Publication/visibility now waits until CenterDisplay::createViews completes.
  An earlier gray-button revision crashed intermittently during startup; the
  final deferred revision reached running on two successive ordinary restarts
  after removing temporary debugger/crash-trace instrumentation. Both returned
  Available, never automatically ActiveFsd.
- Live native readback: Start state Available, AP state Available, panel StartFsd.
  Inspected the blue native button. Actual mouse click on Start produced
  ActiveFsd, Start Unavailable and Stop Available; the displayed label became
  Stop Self-Driving. A second click returned AP/Start to Available. Gear remained
  P and native vehicle speed remained zero during that click cycle. No simulated
  motion or steering command was supplied.
- Turning the lab switch off restored the previous invalid AP input and native
  unavailable buttons; turning it on restored Available. Native Start button
  pressed remained false because the simulation handles controller methods
  locally rather than forwarding an engagement request. Diagnostic logs record
  enabled/engaged/stopped/disabled transitions; captures remain outside the repo.
- The adapter resolves enum labels from native maps and substitutes only four
  selected DV commits through native EventLocker/variant methods. GUI globals
  are resolved from the executable's canonical symbols (RTLD_DEFAULT). The
  native manager's poll function is not bypassed. Missing ABI/enums fail closed.
- Final targeted tests: 188 passed. Synthetic native lifecycle tests cover Start,
  Stop, repeated conflicting native writes, canonical executable DV symbols,
  arbitrary enum ordinals, valid/invalid snapshot restoration, unrelated fields,
  missing enum fallback, opt-out and zero forwarded requests while simulating.
  Preview, backend selection, schema, checkbox drafts, profile/readback, parked
  visualization and tire-card regressions passed alongside them. `git diff
  --check` passed. No physical vehicle, perception or autonomous controller was
  tested or provided.

## Native Start Self-Driving button display (2026-10-15)

- Follow-up to the initial investigation below. Traced the panel factory to
  `ClusterWindow::loadUIML`: the first capability check happens before the
  desktop's FSD profile writes become valid. The earlier process-wide capability
  override also affected managers with uninitialized AP input and was unsuitable.
- The replacement adapter limits the temporary panel capability to markup
  construction on that thread. All other calls delegate to the native helper.
  Visibility preview requires the native Start-from-panel query to permit it
  and FSD to be inactive. It preserves the native unavailable button state,
  charging/autopark outer guards and active FSD view.
- The supervisor opts in only for Model 3 single-display sessions with all three
  explicit selections true: full FSD feature, FSD control preference and Start
  from Park preference. The adapter requires no firmware patch or object offsets.
- Live `2026.26.6.5` ICE restart reached running. Native readback now reports
  `GUI_fsdPanelState=StartFsd`, Start button Unavailable, reason ReasonNone,
  `DAS_autopilotState` invalid and Start button pressed false. Inspected the
  main-screen capture: the native gray Start Self-Driving button is visible at
  the top left, with the parked 3D vehicle still rendered. Private captures stay
  outside the repository.
- Temporarily setting `GUI_fsdControlEnabled=false` hid the native panel (invalid
  state); restoring true returned StartFsd without changing AP state or pressing
  the button. Original true preference was restored. The native Start-from-Park
  checkbox is conditional on hardware; its helper remains authoritative.
- 182 focused Debian tests passed. Compiled fake-framework checks cover nested
  markup loading, restoration after construction, a simultaneous other-thread
  capability query, native fallback, required preferences, preservation of active
  views and missing-query behavior. Backend tests cover opt-in selection,
  malformed settings and S/X exclusion. Existing parked-viz, TPMS, configuration,
  service readback and panel checks passed alongside these tests.

## Start Self-Driving button: initial investigation (2026-10-15)

- The requested scope remains FSD menus/preferences without simulated driving
  engagement. Native `FEATURE_enableStartFsdFromPark` was already true, but
  `GUI_enableStartFsdFromPark` was false; the local explicit preference and the
  desktop's corresponding saved row are now true.
- Native feature values were observed returning to false after startup despite
  an earlier successful apply. The worker now periodically rechecks only six
  explicitly selected FSD UI inputs with cached readback verification. Focused
  tests cover late replacement, both batch and individual writes, removal of
  explicit selection and exclusion of commands/learned vehicle configuration.
- Final restart reached running on the local `2026.26.6.5` ICE image. Native
  readback confirmed full FSD feature, FSD map capability, FSD functions,
  FSD control preference and Start from Park preference true. Both CenterDisplay
  and TMServer reported the applicable overrides accepted.
- The native Start button is still absent: state Unavailable, reason ReasonNone,
  panel invalid, `DAS_autopilotState` invalid, button pressed false and gear P.
  The native `AutopilotManager::poll` writes the button state from its missing
  controller feedback. A main-screen capture confirms no button; the private
  screenshot remains outside the repository.
- A display-only panel preview did not expose the button. Forcing the early
  panel capability caused startup SIGSEGV. Both experiments and their temporary
  diagnostics were removed, and the normal native layout was restored before
  the successful final restart. No availability or engagement is fabricated.
- Final focused Debian checks: 171 passed across configuration, vehicle-service
  readback, backend, panels, parked visualization and TPMS adapters. `git diff
  --check` passed. This validates the preference persistence fix; it does not
  establish a working Start button or an Autopilot controller.

## Local FSD regional message (2026-10-15)

- The native Self-Driving page displayed "FSD (Supervised) not supported in your
  region" with FSD selected. Traced the localization dependency to
  GUI_navVehicleCountry and GUI_isOnNavigationMap. The country helper calls
  GeoUtils::iso3LetterCountryToNumeric; the old profile's two-letter US is not
  the expected alpha-3 USA. Corrected the Model 3 profile's format and added
  focused coverage for that default and its config coercion.
- Applied session-only GUI_navVehicleCountry=USA and
  GUI_isOnNavigationMap=true, the latter an explicit simulated map-coverage
  input. A native screenshot of the same Self-Driving settings confirmed the
  regional message disappeared while FSD remained selected. No GPS writes,
  country-enum changes, binary patch or driving-engagement request were used.
- Synchronized the desktop's saved Model 3 rows before restarting the owned
  session. After restart, native readback confirmed USA, map coverage true,
  FSD preference true and derived FSD app availability true. Phase was running,
  host-state reported no errors, gear remained P and DAS_autopilotState remained
  invalid/unprovided. Map coverage is a simulated UI capability, not a
  driving-region claim. Focused config/backend/model/UI suite: 166 tests passed.

## Local Model 3 FSD menus (2026-10-15)

- Scope: menus and preferences only, as requested; no engaged-state simulation.
  Native `2026.26.6.5` ICE on Debian/WSL already read SelfDriving/FullFSD, but
  FEATURE_fullSelfDriving and GUI_enableFSDFunctions were false. The profile's
  ParkerPascal2_5 hardware also failed the HW3-or-higher menu requirement.
- Checked the exported native hardware enum and the menu dependencies. Set the
  session's VAPI_driverAssist override to TeslaAP3 and enabled the two flags.
  The native Self-Driving page then showed Full Self-Driving (Supervised) and
  FSD usage statistics. GUI_fsdAppAllowed became true without being forced.
- The option initially reported missing FSD navigation maps. For this menu-only
  exercise, explicitly simulated FEATURE_hasFullSelfDrivingNavMaps=true; this
  does not provide FSD maps or a driving stack. Only after that prerequisite did
  the native GUI_fsdControlEnabled preference accept true and retain it.
- Saved these five session overrides and synchronized the desktop's saved
  Model 3 rows. After another owned-session restart, native readback confirmed
  TeslaAP3, SelfDriving, FullFSD, all four feature/preference booleans true and
  derived GUI_fsdAppAllowed=true. The preference remained true on recheck;
  phase was running with no host-state errors. VAPI_shiftState remained P and
  DAS_autopilotState stayed invalid/unprovided. No engagement request was sent.
- Firmware files, account/subscription state, GPS position and region settings
  were not changed. This was a local configuration change with live readback;
  no implementation or new host regression tests were needed.

## Model 3 Park Assist simulation and Audio sources (2026-10-15)

- Native single-display ICE `2026.26.6.5` on Debian/WSL. The unavailable alert
  reported invalid/not-enabled PARK_status. The saved Valeo5 enum was invalid
  for this image (supported names include Valeo, Tesla and None); there was no
  ultrasonic telemetry producer. Added ten local adjustable PARK/USS distances,
  status and service/SDI health with normal readback, defaulting simulation off.
- The local session has simulation enabled, a valid Valeo USS configuration,
  FEATURE_parkAssistEnabled=true and GUI_useVisionParkAssist=false. Native
  PARK_status/USS_status read Enabled, PARK_service read None, PARK_sdiActive
  true and PARK_sdiNoise Nominal. At simulated zero-speed Drive, the display
  itself set GUI_parkAssistActivatable and GUI_parkAssistActive true. A native
  screenshot showed the top-down car and obstacle arcs, with 83.5 cm displayed
  as 33 inches. The test restored Park and the original distance settings.
- Live normal -> failure -> disabled -> recovered transitions read back
  Enabled -> TemporaryFailure -> Disabled -> Enabled. Failure cleared the
  front distance to -1; saved distances were restored on recovery. This is a
  local ultrasonic simulation, not physical CAN, vision perception or autopark.
- AudioControlsPanel::sourcePickerEnabled reads GUI_enableSourcePicker, which
  was false. Enabled it in the Model 3 profile and the current session; native
  readback was true and a screenshot confirmed the Sources section with
  individual switches for Radio, Bluetooth, Spotify, TuneIn and other services.
  Account authentication and audio playback were not validated by this change.
- Focused model/UI/backend/config/CAN regression suite: 213 tests passed.

## Local browser test page (2026-10-15)

- The browser landing URL comes from the owned `browser-page.py` worker, which
  serves `runtime/welcome.html` on a dynamically allocated loopback port. The
  source is staged into the local engine at session startup.
- Updated the page with a local HTTP check, viewport/pixel-ratio details and
  keyboard-event count, retaining local audio, generated video, drag, text input,
  scroll and WebGL checks. No third-party page assets are requested.
- JavaScript syntax checked with Node. The running server returned the new page
  at both `/` and `/welcome.html`, with HTML content type and `no-store` caching;
  an unknown path returned 404. The HTML was staged live without OS restart.
  The new page and its JavaScript/viewport details rendered in the native
  embedded browser. Audio output and all interactive checks were not retested.
- CAN source clarification: the native catalogue exposes ETH and the current
  capture contains Gateway TX/TX-request records. Host links contain no CAN/vcan
  interface; Body/Chassis/Party bus origins cannot be assigned from those IDs.
  Local vehicle-state IPC and the independent LAB CAN simulator are separate
  from captured native physical-bus traffic.

## Park expansion and ICE Service Mode startup (2026-10-15)

- Native single-display Model 3 ICE `2026.26.6.5`, Debian/WSL. The expanded-view
  preference already read back true. The native shift-state helper rejected the
  extended layout in Park. The desktop opt-in now permits the parked layout via
  public native state queries, preserves the track-mode exclusion and passes
  through the original result outside the opt-in. A rightward drag enlarged the
  vehicle view across the screen while native `VAPI_shiftState` still read P.
- Service Mode had no web backend process: this image moved `service-ui` and
  `service_ui` assets to `opt/diag`, while the launcher only checked `opt/odin`.
  Complete web bundles are now detected in either location. Odin engine assets
  stay separate; the current task catalogue contains 1,319 entries.
- Starting the correct backend exposed `Signal cracking unsupported on target`.
  Analysis traced its model selector to `/var/etc/jcanproduct`; that vehicle
  boot-generated file is absent on the desktop. A backend-only preload redirects
  its read-only opens to a private session file holding the selected generic
  model. Write attempts are refused and host files remain untouched. The native
  backend then attached to its namespace-local UDP input and connected to the
  local Odin stand-in, without changing token or gateway authorization.
- Live screenshots confirmed native Service Mode rendering Vehicle Info and its
  section list. Exit/re-entry loaded the panel again without a manual browser
  reload. The native service-mode and Park values were read back, and backend,
  browser, relay, data-value server and Odin processes remained running. Task-list
  requests reached the stand-in. Alerts and vehicle diagnostic operations remain
  unavailable as documented; no ECU operation was exercised.
- Automated checks: 157 passed. They cover both backend directory layouts, separate engine assets,
  private relays, platform-read redirection/write refusal, parked-layout opt-in,
  native pass-through and the track-mode exclusion. Screenshots, native binaries
  and session product data remain outside the repository. Other builds and QEMU
  execution of these changes remain unverified.

## Continuous local frame injection (2026-10-15)

- Replaced the desktop Lab gateway controls with FRAME INJECTION. The LAB
  simulator remains a separate CLI subsystem; opening this page does not
  start its periodic transmitter. The current native capture remains ETH-only,
  without a physical Party/Chassis/Body assignment.
- Focused automated checks: 197 passed across native catalogue, DBC, capture,
  injection, vehicle isolation, Qt panels, backend and existing CAN/gateway tests.
  Eleven separate appearance checks also passed after the table styling update.
  Synthetic fixtures cover selective bit preservation, signed/scaled/Motorola
  and exact 64-bit edits, invalid values, multiplex inactivity, confirmed-send
  filtering, fresh-event-only echo, applied-state acknowledgement, stopped-device
  rejection, restart disable and DBC changes. No proprietary fixtures were added.
- Live native Model 3 ICE 2026.26.6.5: a temporary UI_status rule overrode one
  selected signal. A receiver bound to the documented loopback gateway endpoint
  received six modified records as well as the original native records. Six
  successful echoes and zero skips were reported; all unselected payload bits
  matched the new source frame. API copies did not double-trigger echoes.
  Disabling the rule stopped its counter across a later observation. The
  temporary rule was deleted after validation.
- The Qt panel rendered its editable override grid, rule controls, destination
  and disabled state. Display pause continues polling applied injection status;
  the editor draft does not follow subsequently selected/new live frames.
- UDP receipt was verified by the temporary local receiver only. There is no
  gateway receive service, physical CAN forwarding, OS input/state mapping or
  automatic checksum repair. Rules are local-session configuration and remain
  outside diagnostic exports. Captures/screenshots stay outside the repository.

## Native OS gateway observation and DBC comparison (2026-10-15)

- Native Model 3 ICE `2026.26.6.5`, Debian/WSL. `QtCar`'s drive-critical
  SocketCAN input reported no device; there were no CAN/vcan host interfaces.
  The existing LAB gateway traffic was a state projection, not an OS capture.
- The supplied raw CSV examples have semicolon-separated timestamps, IDs,
  flags, DLC and bytes. Some contain merged/truncated rows; no traffic was
  reconstructed from them or replayed. The user selected OS observation only.
- Reading relocated exports from the selected `libQtCarCANData.so` recovered
  582 message definitions and 41,918 signal names, units and enumerations on
  its ETH channel. The supplied 2026 DBC matched all 582 message ID/name pairs
  and contained 41,912 signals. The six additional names are DI alert-log
  voltage fields; their bit layouts were not guessed. The 2021.24.4 DBC contains
  316 messages, of which 221 match current ID/name pairs. It was not merged
  automatically or selected in place of the current DBC.
- `QtCarVehicle`, absent from the previous launch, produced native gateway
  requests and successful UDP sends to `127.0.0.102:4321`. The real packet
  capture included `UI_status`, `UI_status2`, `UI_chargeRequest`, `UI_ethNm` and
  `UI_odo`. IDs, payload lengths and bytes were retained, with values and named
  states decoded from the selected DBC and current native enum metadata.
- Its publishers use private mounts and a private System V IPC namespace.
  Live namespace and socket-inode checks confirmed that the Vehicle publisher
  differs from the original socket. Display input sockets are linked through a
  read-only bind mount. The center's simulated vehicle-services readback stayed
  accepted. A first-run vehicle configuration restart recovered; a later warm
  session ran without that restart. The original 3D vehicle and display remained.
- The real Qt panel rendered raw records and a selected frame's signal/value/
  unit table. Bus/source and ID filters, display pause, CSV formatting and the
  absence of a LAB-service start are covered by panel checks. Confirmed UDP TX
  and unconfirmed gateway API requests have separate selectors. No raw Party,
  Chassis or Body frames or physical CAN delivery are claimed.
- Automated checks: 190 passed across native metadata, DBC, capture adapter,
  namespace boundaries, panel, backend and existing CAN/gateway tests. Fixtures
  contain only synthetic definitions. The compiled adapter check verifies
  unchanged native calls/errno and nonblocking behavior with a full capture
  queue. Firmware, DBCs, captured bytes and screenshots remain outside the repo.
- The partial current DBC has many overlapping alert/multiplex fields without
  usable selector conditions. These are omitted with a visible note rather
  than interpreted simultaneously. The live view is bounded and best effort;
  complete multiplex recovery, physical buses, other builds and QEMU execution
  remain unverified.

## Model 3 generated vehicle illustrations (2026-10-15)

- Native ICE `2026.26.6.5` on Debian/WSL with Intel UHD/D3D12: the firmware's
  separate `apviz-assetgen` mode was present but not started by the lab. Its
  default `/home/godot/.Tesla/data` path was also outside the owned session.
- The native path adapter now shares the generated cache between the UI and
  the owned renderer. A cold-cache start automatically completed generation
  in one attempt, producing the vendor success sentinel and day/night images.
  The actual tire card displayed the configured red Model 3 between all four
  2.9 bar readings. The native service settings also displayed its generated
  top-down illustration. The existing 3D vehicle and map remained visible.
- A subsequent restart reported ready with zero render attempts, confirming
  that the completed cache is reused without restarting the finite renderer.
- The worker watches native configuration identifiers, reuses completed files,
  bounds retries and runtime, and cleans up its child on shutdown. Synthetic
  checks cover cache misses, incomplete results, configuration changes, failed
  starts, stalled renderers and shutdown escalation. A compiled C/C++ fixture
  verifies Qt's returned-string ABI under global and Godot-local library loads.
- Asset, native tire-adapter, browser, backend, vehicle-services and core checks:
  144 passed. Generated images and native screenshots remain outside the repo;
  no source firmware or static substitute image was copied into the project.
  Other firmware builds and QEMU execution remain unverified.

## Panel 0.5.5: tire card and media window (2026-10-15)

- Native Model 3 ICE `2026.26.6.5`: the tire card's persistent spinner belonged
  to its decorative generated image, not its four pressure readings. The
  single-display session now opts into an exported-constructor adapter that
  disables that image's spinner only during TPMS card construction. Other
  loading indicators retain their original behavior. After restart, all four
  saved pressures appeared at 2.9 bar without the decorative spinner; the
  missing generated illustration remains absent.
- Media Chromium now uses the vendor service's `--disable-tab-strip`,
  `--disable-toolbar`, `--disable-location-bar` and `--disable-status-bubble`
  controls. Chromium app mode was rejected during validation because it
  bypassed the expected native window and D-Bus integration. The final window
  retained its `ChromiumApp` title and bus owner, and TuneIn's real catalogue
  rendered inside the center display without an address bar. Normal browser
  arguments retain their navigation UI. Streaming playback was not tested.
- Source and package metadata report 0.5.5; the desktop panel was reopened
  through `Launch-Linux.sh`. Native tire-adapter, browser, backend and
  vehicle-services checks: 111 passed. The compiled adapter check confirms
  that ordinary image spinners and sessions without the opt-in are unchanged.
  Native screenshots remain outside the repository. Other firmware and QEMU
  execution of these changes remain unverified.

## Model 3 expanded visualization and PARK telltale (2026-10-15)

- Native ICE `2026.26.6.5`: Drive read back correctly while parking-brake and
  amber fault fields were invalid. The simulation now sends the applied brake
  in P and a released brake in D/R/N, with an explicit normal amber telltale.
  After restart, Drive read back D/false/Off and the stale PARK label disappeared.
- The native expanded-visualization preference was disabled and the desktop
  had no service advertising the layout capability. The native support-setting
  override was ignored on this build. The mouse/input compatibility adapter now
  advertises the capability through the exported VehicleUtils function only
  when the supervisor opts in for a single-display Model 3 session. Other
  sessions delegate to firmware. Native gesture handling and state guards remain.
- With the preference enabled and saved, dragging the boundary right in D
  expanded the 3D viewport across the display. The reverse drag requested Normal
  and restored the map. Native pixels, field readback and zero control-feedback
  errors were checked; test controls were restored to Park.
- Core, backend, vehicle-services and replay checks: 129 passed. Other firmware
  builds and QEMU execution of the gesture remain unverified.

## Native tire pressure display (2026-10-15)

- The Model 3 ICE `2026.26.6.5` display had invalid native pressure fields:
  the four local pressure controls were stored but never sent to firmware.
- Tracing `PressureLabelView::init/pressureChanged` established the wheel mapping
  and bar input for both Conti and Tesla field families. Psi rendering calls
  `Units::convertBarToPSI`; the adapter therefore sends bar without preconversion.
- Distinct test values FL/FR/RL/RR = 2.6/2.7/2.8/2.9 read back on both native
  field families and appeared in the matching wheel positions: 2.6/2.7/2.8/2.9
  bar, then 38/39/41/42 psi. The original Psi preference was restored.
- Vehicle-services and panel checks: 90 passed, including distinct wheel
  mapping and boundary pressure values. Physical TPMS behavior is unverified.

## Native European routing and simulated GPS (2026-10-14)

- Native Debian/WSL, experimental Model 3 `2026.26.6.5` ICE/MRB, using the
  read-only `EU-2026.8-15742` TeslaMaps package. Valhalla 2.4.3 and QtCarTMServer
  started in the owned session. TCP listeners were confirmed on
  `127.0.0.1:8002` and `127.0.0.1:4400`; the native peer-profile match succeeded.
- The saved simulation was set to Toulouse (`43.6045, 1.4440`). Display and
  TeslaMaps GPS readback matched, including the aggregate coordinate. An
  initial route used an internal zero coordinate despite correct map position;
  feeding estimated latitude, longitude, heading and a fresh estimate timestamp
  corrected the localizer's routing origin.
- A native route to a nearby Toulouse test point transitioned from Calculating
  to Active, using the offline routing state machine and local Valhalla tiles.
  The displayed route included turn instructions and a blue path of about
  3.2 km. The check passed again after Restart with the automatic state writer
  and no GPS probe process. Temporary test destination settings were removed.
- Street/satellite imagery displayed Toulouse through Google network imagery.
  This does not establish offline basemap imagery, offline address search,
  traffic, NA routing, other firmware builds or QEMU operation. No source
  firmware, maps, GPS logs or native screenshots were added to the repository.
- Automated checks: 537 passed, 2 skipped across the complete test inventory.
  The 11 Qt theme tests ran separately (all passed) because applying a global
  stylesheet after the accumulated widget tests was excessively slow.

## European map import and mount (2026-10-14)

- A local `EU-2026.8-15742` TeslaMaps image (`.ssq`, 7,924,469,824 bytes)
  imported successfully after checksum calculation. Its multiline `VERSION`
  contains build details; the library stores only the release on the first line.
- A native SquashFUSE check read `VERSION`, `NAVENGINE=TeslaMaps` and the
  `tm/EU/valhalla` directory from the image. Mount options included `ro,nosuid,nodev`;
  the temporary verification mount was released afterward. The source image
  and its cartography were not modified or copied into the repository.
- Backend, core and panel checks: 121 passed, including synthetic EU/NA import
  metadata, unknown engines/regions and oversized metadata rejection.
- This initial check validated import and mounting. The later native routing
  check above records the additional integration results and remaining limits.

## Model 3 profile: native ICE smoke check (2026-10-13)

- A saved `GUI_splashScreenMode=true` reproduced a startup SIGSEGV under GDB
  in `DisplayStateManager::restartTimer(bool)`, called by `DataValue::dvConnect`
  during `CenterDisplay::initManagers`. Its active-state pointer was null.
  The guarded launch with the setting still true skipped that early callback
  and reached running. Then the mode was disabled with confirmed `false`
  readback and a saved override. Native guard and backend checks: 49 passed.

- Local image: `2026.26.6.5`, `ice_mrb`, x86_64; QtCar build ID
  `11d4442da8c13697dec15c89a8e0c4699c2bd135`. The existing
  `ice-mrb-generic` launch profile remains experimental; no validated
  compatibility profile was added.
- Native Debian/WSL session started with `UI_PLATFORM=M3`, `UI_VEHICLE=Model3`
  and `UI_TARGET=ICE`, a landscape center screen and no instrument cluster.
  Center, Godot visualization, media services and Chromium processes reported
  running. The corrected profile reached running with zero configuration
  restarts and all 33 startup values accepted by firmware readback.
- Direct D-Bus readback confirmed `VAPI_carType=Model3`, chassis label `3`,
  air suspension `None`, trim label `74`, restraints `NAM3`, four-wheel drive
  `false` and firmware version `2026.26.6.5`. The image's enum map distinguishes
  chassis label `3` (ordinal 2) from Model Y (ordinal 3). Numeric labels remain
  strings through CSV writes and display readback.
- This is a local simulator smoke check. QEMU execution of this profile,
  other ICE builds, cloud login/playback and vehicle hardware are unverified.
- Automated checks: 516 passed, 2 skipped in the full Linux/offscreen suite;
  the final configuration-draft changes passed all 48 panel tests afterward.

## Version 0.5.1: startup and display fixes (2026-09-16)

- Native Linux/WSL startup was failing before the supervisor loaded because the
  staging list omitted `display_graphics.py`. Staging now includes all top-level
  Python modules. A subprocess check imports the staged supervisor and display
  helpers from a temporary directory without the source checkout on its path.
- The running MCU2 native session opened both AMD D3D12-accelerated displays.
  Six Qt driving scenarios covered D/R/N/P, speed, throttle, brake, steering and
  indicators, with matching readback on both displays and no control errors.
- The same six scenarios passed on the QEMU MCU2 guest. Qt input to observed
  feedback ranged from 1.89 to 3.11 seconds, including guest-channel polling;
  this does not establish real-time input latency.
- Center-to-cluster and cluster-to-center Santa preference changes propagated
  in 129 ms and 190 ms respectively; the original preference was restored.
- Tracing the stalled QEMU center showed waits inside the Mesa DRI3/EGL buffer
  path while Xorg reported DPMS Monitor Off. Both private guest X servers now
  start with the screen-saver timeout disabled and without DPMS. After a desktop
  service restart, feedback remained fresh beyond the previous ten-minute idle
  trigger, with no display-link or control errors. Host power settings are unchanged.
- Buffered guest-agent reads handle fragmented large replies, preserve request
  IDs and response size limits, and flush each outgoing request. Live preview
  requests took about 524–527 ms versus 688–701 ms before the change.

## Version 0.5.0: Material desktop and QEMU (2026-09-16)

- Linux: 230 tests passed. Windows: 205 passed, 25 Linux-only checks skipped.
- The upper-left wordmark is removed in both wide and compact layouts. Native
  Qt screenshots were regenerated.
- MCU2 2026.26.6.1 runs on the replacement-kernel QEMU guest. Center, instrument
  and firmware Godot visualization renderers report AMD-backed VirGL. The
  instruments use VirtualGL with their independent X11 window.
- Qt stop/start released the old audio helper, created a helper owned by the new
  VM, and restored both accelerated previews. Embedded Chromium audio reached
  the host output monitor after restart with no output-queue drops.
- Two 30-second tones and a 120-second tone completed normally. The latter took
  119.605 seconds. Idle/resume was checked separately; extended streaming
  playback remains unverified.
- A 100 km/h input displays 100 km/h or 62 MPH according to the firmware's
  selected units. Hold/release, replay pause/seek and changing RGB input were
  checked against the running guest as described in the virtual desktop guide.
- ICE in QEMU, clean-machine guest preparation, long-session performance and
  full parity with the native runtime remain experimental. See
  [virtual-desktop.md](virtual-desktop.md) for the current scope.

## Version 0.4.2: Service Mode, fonts and display channels (2026-09-10)

- Linux: 154 tests passed. Windows: 134 passed, 20 Linux-specific checks skipped.
- The native compositor left `GL_UNPACK_ALIGNMENT=1` in Qt's shared context.
  Restoring its previous value after the 3D upload removed the diagonal/striped
  text corruption in the live center Software/Controls pages and cluster alerts.
  A compiled regression harness checks alignments 1, 2, 4 and 8, including upload errors.
- Both running Qt processes mapped Universal Sans font files from the selected
  firmware mount. A session-only Fontconfig configuration points to that image,
  its supplied font rules and a private cache. `fc-match` selected Universal Sans
  Text 530 for the named family.
  No font payload was copied into the repository or installed into host font folders.
  Fresh native captures show readable [center controls](screenshots/native-fonts-center.png)
  and [cluster warning text alongside the 3D car](screenshots/native-fonts-cluster.png).
- On the running MCU2 session, changing only the center's Santa field to 1 and
  then 0 produced matching instrument readbacks in both cases. The original
  value was restored. Shared-field polling reported 23 synchronized values and
  no field errors in the default session.
- The supervisor launches the supplied Spotify service, ChromiumAdapter,
  media-webapp-server and a separate ChromiumApp profile. The local HTTP service
  returned 200 and its WebSocket connection to the adapter was observed.
- Measured host connectivity is forwarded to the media services. Using the
  firmware's expected `online` Wi-Fi state changed the native Spotify SDK from
  None to Wireless, with `SPOTIFY_sdkHasConnectivity=true`; it remained true
  after a complete session restart.
- Automated checks cover Santa enable/disable and peer restart reconciliation,
  one-way playback metadata clearing, real exported wheel-action names,
  consecutive volume requests, hold cancellation, native indicator phases, media-port
  conflicts and bounded service recovery.
- After the desktop was unlocked, clicking Santa in the actual center window
  produced the sleigh, reindeer, tree, snowman and falling snow in the Windows
  instrument window. The wheel panel loaded. Volume + and Volume −
  changed the shared volume by five percentage points and restored it; a native
  instrument volume popup was captured alongside Santa.
  Switching Santa off in the center restored the ordinary car visualization.
- A live Qt hold through the real backend increased native volume from 20% to
  35% during a 1.4-second press. Volume stayed at 35% after release and the
  original level was restored. Left, right, hazard and Off selections produced
  the expected steady direction and alternating lamp states on both displays.
  Lamp values were sampled twice to exclude reads straddling a phase transition.
  Selecting Hazards in the reopened desktop panel displayed both green
  arrows in the actual Windows instrument window; [native capture](screenshots/cluster-indicators.png).
- The supplied music web app includes Spotify, Apple Music, Amazon Music,
  Audible and other player assets. The bundled Chromium directory includes
  WidevineCdm; presence alone does not establish DRM playback. `ldd` found no
  unresolved libraries for SpotifyServer or ChromiumAdapter in their launch
  environment. A second audit, informed by the earlier Chromium research,
  found the actual policies under `etc/apparmor.compiled`. The Spotify,
  ChromiumAdapter, Chromium, media-webapp-server and QtCar policy blobs are
  nonempty. The empty `sandbox.d` entries do not establish missing policies.
  After an authorized WSL restart, AppArmor reports enabled. The unchanged
  Spotify policy loaded in a disposable policy namespace, which was then removed
  without attaching a task. Complete service confinement remains unresolved.
- The media browser now carries the vendor's secure-context declaration for
  its one loopback media origin and loads the supplied ChromiumApp policy path.
  An isolated test with the same firmware Chromium and a local HTML page
  reported `isSecureContext=false` and no EME API without the declaration;
  both became true with it. This establishes API availability, not successful
  CDM initialization, login or licensed playback. The firmware browser does
  not support the headless Ozone platform; this check used its normal X11 mode.
- Live checks verified each of the six closure position flags on both displays.
  The [native instrument capture](screenshots/cluster-doors.png) shows all four
  doors, the hood and the hatch open in the 3D view. Clicking Open for the rear
  trunk in the real center window opened it in the instrument window. Clicking
  Lock changed the native button to Unlock and the shared model to locked.
- Off, Parking, On and Auto/day/dark cases produced matching headlight states on
  both displays. The native parking mode uses the enum name ParkingLights;
  the desktop translates its Parking choice at that boundary. Clicking Off in
  the actual center changed both headlight and parking-light states to false.
- Both displays initially reported `VAPI_alarmStatus=<invalid>`. Native enum
  sampling established `0=Disarmed`, `1=Armed`, `2=PartialArmed`,
  `3=TriggeredFlash`, `4=Error`, `5=TriggeredNoFlash`, and `7=Default`.
  The local model now publishes `Disarmed` by default and both displays read it
  back. With the normal access-code flow, the center changed
  `GUI_serviceMode` from false to true and displayed its native red Service Mode
  frame. Forwarding that center-owned state made the instrument display render
  its native Service Mode overlay. See the clean [center capture](screenshots/service-mode-center.png)
  and [instrument capture](screenshots/service-mode-cluster.png). No access-code,
  gateway identity or authentication decision was patched.
- Spotify still failed in the real center window. Its native publishers first
  lacked `/tmp/dvaccess`; creating a user-owned private directory exposed the
  next failure: the center rejects SpotifyServer and ChromiumAdapterService
  peers with `[PEERSEC] Incorrect security profile`. The media app remains
  unavailable despite HTTP/WebSocket and SDK connectivity. The control panel
  now reports this distinction. No peer-identity check was patched or disabled.

## Version 0.4.0 baseline

Date: 2026-09-09. Host: Windows 11, WSL2 Debian 13, x86_64, AMD Radeon graphics via Mesa D3D12. Firmware: user-provided 2026.26.6.1 MCU2 / `modelsx_info2`. No firmware payload is included in this record.

## Automated checks

- Platform-independent input validation, image magic, path identifiers, profile selection, atomic state writes and diagnostic export allowlist.
- Qt queue completion ordering, language changes preserving controls, Park resetting visible speed controls, launch readiness, persistent errors, and saved launch options across language changes and reopen.
- Linux worker checks for changed images, nonempty mountpoints, executable symlinks escaping a mount, idempotent shutdown, restart validation before stop, and capture display restrictions.
- Configuration restart classification uses an observed vendor log message and excludes ordinary crashes.
- `scripts/qa-running-ui.py` drives the actual native widgets, waits for the live backend, submits gear D / 42 km/h / pedals / steering / left signal, and checks acknowledgements from both displays. It captures the rendered app and returns the simulator to Park.
- Linux and Windows directory bundles launch, query the WSL runtime, capture their real window, and exit using the packaging smoke-test option.

Version 0.4.0 passes 96 source tests on Debian. Windows passes 82 and skips 14 Linux checks. Tests cover replay clock and ownership transitions, manual input before decoder startup, concurrent manual takeover, per-field service readback, native speed units, preference reconciliation, GUI drafts and acknowledgements, and compiled X11/V4L2 adapters. The running-firmware checks below are separate from CI and use the locally supplied image.

## Observed behavior

| Check | Evidence / result |
| --- | --- |
| Native launcher | [English](screenshots/workspace-en.png), [packaged Linux](screenshots/packaged-linux.png), [optional Windows client](screenshots/packaged-windows.png). |
| Device tools | Live overview loaded both actual displays; Center/Cluster focus succeeded; Capture exported 720×1152 and 1280×480 PNGs; Restart and Stop/Start completed through native buttons. |
| Windows launch | Opened the installed desktop shortcut through Windows and observed the Linux GUI window. Opening it again kept the same primary process. The CMD entry point also completed its launch smoke test without error. |
| Window sizing | Reviewed at 1360×920 and 1080×780 with scrollable content. |
| Graphics | `D3D12 (AMD Radeon(TM) Graphics)` with hardware acceleration reported by the nested display. |
| Instrument visualization | Actual parked Model S 3D display; [screenshot](screenshots/cluster.png). |
| Simulator | [Control panel](screenshots/simulator-en.png) and [per-display acknowledgements](screenshots/simulation-proof.json). Display-speed and vehicle-speed fields use different units. |
| Chromium | Selected Browser from the firmware's launcher; website opened inside the center display; [screenshot](screenshots/center.png). |
| Browser input | Typed `lab` into the local test page; clicked a website link and browser Back; wheel scrolling reached “End of scroll test.” |
| Browser graphics | Test page reported ANGLE / D3D12 / AMD Radeon WebGL. |
| Browser audio | The two-second test tone appeared on the WSLg PulseAudio monitor: 311,422 signed 16-bit samples, peak 156, RMS approximately 81.97. This verifies output routing, not subjective fidelity or latency. |
| Shutdown | Owned service and displays stop; firmware FUSE mounts unmount. Repeated stop succeeds. |
| Fresh profiles | Recognized first-run configuration restart recovered automatically; the next session reached Running with `configuration_restarts: 1`. |
| Camera | Pattern and generated H.264 MP4 rendered by the firmware's native camera page at approximately 24 source fps. Firmware logs showed `CameraStream` entering OPEN and receiving its first valid frame. [Firmware capture](screenshots/firmware-camera.png). |
| Existing camera pipeline | The original `tesla-camera-raw-writer.py` produced a frame accepted by the new RGB/V4L2 path. After it stopped, health changed to waiting and firmware reception became false. The upstream file was preserved. |
| Camera lifecycle | Stop feed, pattern recovery, camera-page close and Reverse reopening verified. The source remained ready while the firmware camera page was closed; recent frame consumption resumed after selecting R. |
| Browser card and theater | Browser minimized into the stock center-display card. Theater catalog opened through the native app launcher, and its YouTube page loaded over the Internet. This does not establish commercial DRM playback. [Embedded browser](screenshots/embedded-browser.png), [Theater](screenshots/theater.png). |
| Embedded dragging | Real browser slider moved from 20 to 85; draggable tile reported 14 motion events and one release; locally generated video played inside the browser. Isolated X11 tests additionally cover offscreen coordinates, release outside the viewport and resize cancellation. |
| Physical keyboard | The public Qt4 event-dispatcher filter delivered physical keyboard events to the embedded Chromium view. Ctrl+A selected its text field. Isolated X11 tests cover modifiers, prior-filter chaining and key release on focus loss. Clipboard integration is not included. |
| Local vehicle services | Driver/passenger temperature, fan, cabin temperature, battery 57%, charging at 11 kW and light indicators read back on both displays. Native climate changes fed the shared model and the other display. Settings were restored afterward, including battery 50%. |
| Preference synchronization | Units changed center → instruments and instruments → center. Eight populated preferences synchronized in the tested default state; registered but unset and unsupported values are reported separately. Unsupported fields are cached until display-owner changes. |
| Recorded drive | All four supplied recordings parsed. The rear clip contains 2,117 embedded samples across about 60 seconds. Real firmware camera consumption measured about 24.4 fps. Both displays accepted all six driving-control groups. Pause, seek to 15 s, resume, and manual takeover to Park passed. |
| Replay location | Recorded GPS entered the local display services; the center display rendered a street basemap after a valid fix. No offline map was selected for this check. Private recording, location and screenshots remain outside the repository. |
| Reopen behavior | A persisted replay decodes one preview frame and stays in Park until explicit Play. Seeking the preview does not claim driving controls. Verified with a real FFmpeg/camera worker and covered by ownership tests. |

## Remaining gaps

Physical Linux hardware, non-AMD GPUs, other firmware builds, and an actual GitHub-hosted CI run have not been tested. No FPS or input-latency guarantee is made. The UI remains responsive during worker operations; 3D composition uses a compatibility texture upload and can be expensive. Driving-mode visualization layout still needs broader validation.

European offline route computation and native guidance have been verified on the experimental Model 3 ICE session. Street imagery remains network-dependent; offline address search, NA routing and other map/firmware combinations are unverified. Side/front camera views have not been validated. Vehicle services cover the documented local model and known display fields; they do not implement every firmware service. Physical ECU/CAN, live driver assistance, account services, and payment systems are outside the implementation. Commercial streaming playback is not verified.

Reproduce the UI screenshots on your own running session with:

```bash
python scripts/qa-running-ui.py docs/screenshots
```

Add `--tools --cycle` to exercise display focus, screenshot export, restart and Stop/Start. These flags restart the local lab session. Add `--video /path/to/clip.mp4` to check the camera decoder and shared source preview. Open the firmware camera page to observe actual reception.

Use the GUI's Python environment for this command. Inspect images before publication; screenshots of a firmware browser can contain a local URL or personal content. The standalone capture tool captures actual X11 display pixels and does not redact them.
