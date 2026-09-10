# Changelog

## 0.4.0 — 2026-09-09

- Added native Browser, Card view and Theater controls with separate Chromium runtime profiles.
- Corrected embedded pointer coordinates, drag capture, wheel delivery and physical keyboard routing.
- Connected embedded dashcam driving data to the same clock as the camera video, with pause, seek, playback speed, looping and manual takeover. Reopening a session holds the preview in Park until Play.
- Added local climate, body, lights, energy, audio and navigation controls with per-field firmware readback. Both displays share driving data and reconcile supported preferences in either direction.
- Added bilingual control pages, replay and X11 integration tests, and a generator for a clearly labelled public demo recording.

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
- Corrected desktop application identity and simplified compatibility wording in both READMEs.

## 0.2.0 — 2026-09-09

- Emulator-style device manager with searchable firmware entries and per-device launch preferences.
- Actual center and instrument display captures in a five-second overview.
- Native toolbar for display focus, restart, PNG capture, controls and camera.
- Preflight launch gating, guided setup, persistent errors and busy indicators.
- Scrollable layouts, keyboard shortcuts, matching English/Mandarin documentation and refreshed screenshots.

## 0.1.0 — 2026-09-09

- Native Qt workbench with English and Mandarin interfaces.
- Local firmware library with drag and drop, build checks and read-only mounts.
- Standalone MCU2 center/instrument session with AMD WSLg graphics and embedded Chromium.
- Private display simulator for gear, speed, pedals, steering and turn signals.
- Camera pattern/local video preview, process diagnostics and sanitized report export.
- Native Linux and optional Windows/WSL packaging.

Known gaps at 0.1.0: firmware camera integration, map routing/imagery, theater/card browser modes, embedded drag/clipboard behavior, and complete vehicle-service emulation. See the READMEs for the current scope.
