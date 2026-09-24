# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Infotainment Lab: a native Qt (PySide6) control panel that runs a user-supplied, read-only Tesla firmware image as a local desktop session (native Xephyr/systemd mode or a QEMU guest). It is not a vehicle tool; the CAN/gateway subsystem is a behavioural model with project-authored `LAB_*` frames and no vendor keys or protocol. Firmware, maps, recordings and credentials must never enter the repo. Tests must not need proprietary files, GPU, root or a real CAN interface.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q                                   # full suite
python -m pytest -q tests/test_gateway.py::test_name  # single test
QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q   # what CI runs on Linux (needs xvfb, gcc, ffmpeg for input/media tests)
python scripts/build.py                               # PyInstaller bundle into dist/ (build on the target OS)
bash Launch-Linux.sh                                  # run from source (creates ui-venv, installs PySide6); logs to ~/.local/state/tsla-infotainment-lab/launcher.log
```

No linter is configured. Python 3.11+, PySide6 pinned to 6.9.3.

## Architecture

Read `docs/ARCHITECTURE.md` for the full picture; the essentials:

- **Two-process split.** The Qt GUI (`application.py`, `workspace.py`, `lab_panels.py`, `presentation.py`) never touches the firmware directly. `bridge.py` runs blocking commands in a Qt thread pool by invoking the **backend under `/usr/bin/python3`** (in WSL on Windows), so distro packages such as dbus-python stay outside the GUI's Qt venv. Backend code (`backend.py`, `supervisor.py`, `runtime/*.py`) therefore uses flat imports (`import backend`) and must not import Qt.
- **Session ownership.** `backend.py` copies `runtime/` sources to `~/.local/share/tsla-infotainment-lab/engine/` and starts one owned systemd user service; `supervisor.py` launches nested X11 displays, a private D-Bus and the firmware processes from the firmware UI directory (cwd matters: assets use relative paths). Closing the panel leaves the session running.
- **State via JSON files** under `session/` (`controls.json`, `vehicle-services.json`, `*-feedback.json`, `replay-*.json`…). The GUI/backend write requested state atomically; `runtime/keep-awake.py` polls and applies changed values to the displays with readback. A successful setter alone is never treated as proof a value applied. Validation lives in `simulation.py` and `vehicle_services.py`.
- **`runtime/`** holds adapters shipped into the session: Python workers (`keep-awake`, `display-link`, `camera-feed`, `browser-page`) and C shims (`native-*.c`) loaded into the firmware's Qt/X11 processes. Firmware files are never modified.
- **Camera/replay.** `camera-feed.py` produces 1280×720 RGB24 frames; `replay.py` parses SEI telemetry from dashcam MP4s and shares one PTS-driven clock with the picture. Manual takeover and replay share an advisory lock.
- **QEMU mode.** `qemu_*.py` and `virtual_*.py`/`guest_*.py` manage a Debian guest with a replacement kernel; `guest_bridge.py` re-runs the same backend `ACTIONS` inside the guest (new actions must be added to its `ACTIONS` set).
- **CAN/gateway.** `can_frames` (packing, CRC-8) → `can_bus` (SocketCAN `vcan0-2`, else in-process software hub) → `gateway` (routes, allowlists, HMAC unlock, rate limit, loopback Ethernet bridge) → `can_service` (loop + Unix control socket, one JSON request per connection); `vehicle_can.py` projects `Simulation`/`VehicleServices` onto periodic frames and accepted writes flow back into the same state. See `docs/can-gateway.md`.

## Conventions

- User-facing text, code, comments and docs are English only; do not add other languages.
- Use structured subprocess argument arrays, never shell strings.
- Changes to privileged setup, file ownership, diagnostic exports or process cleanup need focused tests. Diagnostic exports use an allowlist.
- New compatibility profiles (`profiles.json`) need exact version/build-ID evidence and a validation record (`docs/VALIDATION.md`); keep incomplete features visibly marked.
- Update `CHANGELOG.md` for user-visible changes.
