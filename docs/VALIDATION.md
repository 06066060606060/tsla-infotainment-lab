# Validation record

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
  Qt screenshots were regenerated in English and Simplified Chinese.
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
  its supplied CJK rules and a private cache. `fc-match` selected Universal Sans
  Text 530 for the named family and Noto Sans CJK SC for simplified Chinese.
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
  instrument window. The Chinese wheel panel loaded. Volume + and Volume −
  changed the shared volume by five percentage points and restored it; a native
  instrument volume popup was captured alongside Santa.
  Switching Santa off in the center restored the ordinary car visualization.
- A live Qt hold through the real backend increased native volume from 20% to
  35% during a 1.4-second press. Volume stayed at 35% after release and the
  original level was restored. Left, right, hazard and Off selections produced
  the expected steady direction and alternating lamp states on both displays.
  Lamp values were sampled twice to exclude reads straddling a phase transition.
  Selecting Hazards in the reopened Chinese desktop panel displayed both green
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
| Native launcher | [English](screenshots/workspace-en.png), [Mandarin](screenshots/workspace-zh.png), [packaged Linux](screenshots/packaged-linux.png), [optional Windows client](screenshots/packaged-windows.png). |
| Device tools | Live overview loaded both actual displays; Center/Cluster focus succeeded; Capture exported 720×1152 and 1280×480 PNGs; Restart and Stop/Start completed through native buttons. |
| Windows launch | Opened the installed desktop shortcut through Windows and observed the Linux GUI window. Opening it again kept the same primary process. The CMD entry point also completed its launch smoke test without error. |
| Window sizing | Reviewed at 1360×920 in English and Mandarin, and 1080×780 with scrollable content. |
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

Offline map images are identified and mounted, but their imagery and route computation are not validated. The observed street basemap after recorded GPS is a separate result. Side/front camera views have not been validated. Vehicle services cover the documented local model and known display fields; they do not implement every firmware service. Physical ECU/CAN, live driver assistance, account services, and payment systems are outside the implementation. Commercial streaming playback is not verified.

Reproduce the UI screenshots on your own running session with:

```bash
python scripts/qa-running-ui.py docs/screenshots
```

Add `--tools --cycle` to exercise display focus, screenshot export, restart and Stop/Start. These flags restart the local lab session. Add `--video /path/to/clip.mp4` to check the camera decoder and shared source preview. Open the firmware camera page to observe actual reception.

Use the GUI's Python environment for this command. Inspect images before publication; screenshots of a firmware browser can contain a local URL or personal content. The standalone capture tool captures actual X11 display pixels and does not redact them.
