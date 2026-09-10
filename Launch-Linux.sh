#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/tsla-infotainment-lab"
mkdir -p "$STATE"
chmod 700 "$STATE"
# Retain the previous attempt and make failures available without a terminal.
if [[ -f "$STATE/launcher.log" ]]; then
    mv -- "$STATE/launcher.log" "$STATE/launcher.previous.log"
fi
exec > >(tee "$STATE/launcher.log") 2>&1
echo "Infotainment Lab startup: $(date --iso-8601=seconds)"
if [[ -n "${WSL_DISTRO_NAME:-}" && -S /mnt/wslg/runtime-dir/wayland-0 ]]; then
    export DISPLAY=:0
    export WAYLAND_DISPLAY=wayland-0
    export PULSE_SERVER=unix:/mnt/wslg/PulseServer
fi
if [[ -x "$HERE/InfotainmentLab" ]]; then
    exec "$HERE/InfotainmentLab" "$@"
fi
ENVIRONMENT="${XDG_DATA_HOME:-$HOME/.local/share}/tsla-infotainment-lab/ui-venv"
if [[ ! -x "$ENVIRONMENT/bin/python" ]]; then
    python3 -m venv "$ENVIRONMENT"
fi
if ! "$ENVIRONMENT/bin/python" -c 'import PySide6' 2>/dev/null; then
    "$ENVIRONMENT/bin/python" -m pip install 'PySide6==6.9.3'
fi
exec "$ENVIRONMENT/bin/python" "$HERE/run_app.py" "$@"
