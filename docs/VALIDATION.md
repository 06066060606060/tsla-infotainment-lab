# Validation record

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
