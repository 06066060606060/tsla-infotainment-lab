"""Linux worker. The Windows GUI invokes it through WSL with argv, never a shell.

Every response is one JSON object. Long operations run off the GUI thread.
Firmware stays in a user-owned, read-only FUSE mount; only dependency setup
requires privilege. Runtime data never belongs to the source repository.
"""
from __future__ import annotations

import argparse
import base64
import errno
import io
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import pwd
import shutil
import subprocess
import sys
import time

from core import PACKAGE, atomic_json, load_json, profile_for, public_report, safe_id, sha256_file, validate_image
from simulation import Simulation
from camera_source import source_config, camera_health, FRAME_BYTES, WIDTH, HEIGHT
from browser import MODES, browser_url, media_health
from replay import replay_request, manual_takeover, controls_lock
import config_csv
import display_scale
from vehicle_services import VehicleServices, CAPABILITIES
from host_graphics import selection as graphics_selection

DATA = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "tsla-infotainment-lab"
UNIT = "tsla-infotainment-lab.service"
PACKAGES = ["squashfs-tools", "squashfuse", "fuse3", "gcc", "binutils", "libx11-dev", "python3-dbus", "python3-gi",
            "dbus-x11", "xserver-xephyr", "x11-utils", "xdotool", "mesa-utils", "pulseaudio-utils",
            "alsa-utils", "libasound2-plugins", "libnss3", "libgbm1", "libatk-bridge2.0-0", "pkexec",
            "libxkbcommon-x11-0", "libxcb-cursor0", "libegl1", "libgl1", "libglx-mesa0", "python3-pil", "ffmpeg",
            "apparmor", "apparmor-utils", "gstreamer1.0-tools", "gstreamer1.0-alsa", "gstreamer1.0-plugins-base",
            "gstreamer1.0-plugins-good"]
COMMANDS = ["unsquashfs", "squashfuse", "fusermount3", "gcc", "readelf", "Xephyr", "xdpyinfo",
            "xdotool", "glxinfo", "dbus-run-session", "systemd-run", "pactl", "ffmpeg", "ffprobe",
            "apparmor_parser", "aa-exec"]


def run(argv, *, timeout=30, check=True, env=None):
    result = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, env=env)
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()[-3000:]
        raise RuntimeError(detail or f"{argv[0]} exited with code {result.returncode}")
    return result


def systemctl(*args, check=False):
    return run(["systemctl", "--user", *args], check=check)


def probe() -> dict:
    missing = [c for c in COMMANDS if not shutil.which(c)]
    for module in ("dbus", "gi"):
        if importlib.util.find_spec(module) is None:
            missing.append("python3-" + module)
    if importlib.util.find_spec('PIL') is None:
        missing.append('python3-pil')
    display = bool(os.environ.get("DISPLAY"))
    if display and shutil.which("xdpyinfo"):
        display = run(["xdpyinfo"], timeout=8, check=False).returncode == 0
    is_wsl = "microsoft" in platform.release().lower()
    audio = bool(os.environ.get("PULSE_SERVER") or (Path("/run/user") / str(os.getuid()) / "pulse/native").exists())
    return {"platform": "Windows / WSL2" if is_wsl else "Linux / X11",
            "host_gpu_selection": graphics_selection() if is_wsl else {},
            "architecture": platform.machine(), "missing": missing, "display_available": display,
            "audio_available": audio, "systemd_available": bool(shutil.which("systemctl")) and systemctl("show-environment").returncode == 0,
            "fuse_available": os.access("/dev/fuse", os.R_OK | os.W_OK), "root_user": os.getuid() == 0,
            "runtime_ready": all(os.access(p, os.W_OK) for p in ('/opt/games/run/chromium-cache-files', '/opt/games/run/i2v')),
            "library": load_json(DATA / "library.json", []), "status": status()}


def read_image_text(image: Path, member: str, required=True) -> str:
    result = run(["unsquashfs", "-cat", image, member], timeout=30, check=False)
    if result.returncode and required:
        raise ValueError(f"The image is missing {member}.")
    text = result.stdout.strip()
    if len(text) > 200:
        raise ValueError("Unexpected firmware metadata length.")
    return text if result.returncode == 0 else ""


def import_image(filename: str) -> dict:
    if not shutil.which("unsquashfs"):
        raise RuntimeError("Install the runtime dependencies before importing firmware.")
    image = validate_image(Path(filename))
    version = read_image_text(image, "etc/customer-version", required=False)
    if version:
        variant = read_image_text(image, "etc/product-variants")
        if not variant:
            product = read_image_text(image, "etc/product", required=False)
            platform_name = read_image_text(image, "etc/product-platform", required=False)
            variant = f"{product}_{platform_name}" if product and platform_name else "unknown"
        profile = profile_for(version, variant)
        kind = "firmware"
    else:
        version = read_image_text(image, "VERSION")
        engine = read_image_text(image, "NAVENGINE")
        if not version.startswith("NA-") or engine != "TeslaMaps":
            raise ValueError("This map format is not supported by the current map importer.")
        variant, profile, kind = "North America", None, "map"
    digest = sha256_file(image)
    item = {"id": digest[:16], "sha256": digest, "path": str(image), "filename": image.name,
            "bytes": image.stat().st_size, "mtime_ns": image.stat().st_mtime_ns,
            "version": version, "variant": variant, "kind": kind,
            "profile": profile["id"] if profile else None,
            "supported": bool(profile) or kind == "map", "imported_at": time.time()}
    library = load_json(DATA / "library.json", [])
    library = [entry for entry in library if entry["id"] != item["id"]] + [item]
    atomic_json(DATA / "library.json", library)
    return item


def library_item(identifier: str) -> dict:
    safe_id(identifier)
    item = next((entry for entry in load_json(DATA / "library.json", []) if entry["id"] == identifier), None)
    if not item:
        raise ValueError("Import this image again; it is not in the library.")
    image = validate_image(Path(item["path"]))
    info = image.stat()
    if info.st_size != item["bytes"] or info.st_mtime_ns != item["mtime_ns"]:
        raise ValueError("This image changed after import. Re-import it before starting.")
    return item


def release_mount(mount: Path) -> bool:
    """Unmount one of this application's own FUSE mounts; True once it is gone.

    A process that still has files open (a Console shell, a firmware process that
    outlived the service) makes a plain unmount fail as busy. The image is mounted
    read-only, so a lazy unmount is safe: the path detaches now and the FUSE daemon
    exits when the last of those processes lets go. A dead mount ("transport
    endpoint is not connected") is cleared the same way.
    """
    for flags in ([], ["-z"]):
        if not os.path.ismount(mount) and not stale_mount(mount):
            return True
        run(["fusermount3", "-u", *flags, mount], check=False)
    return not os.path.ismount(mount) and not stale_mount(mount)


def stale_mount(mount: Path) -> bool:
    try:
        os.stat(mount)
    except OSError as error:
        return error.errno == errno.ENOTCONN
    return False


def mounted_image(item: dict) -> Path:
    mount = DATA / "mounts" / safe_id(item["id"])
    if stale_mount(mount):  # left behind by a squashfuse that died; mount the image again
        release_mount(mount)
    mount.mkdir(parents=True, exist_ok=True)
    if not os.path.ismount(mount):
        if any(mount.iterdir()):
            raise RuntimeError("The firmware mount directory is not empty. No files were changed.")
        run(["squashfuse", "-o", "ro,nosuid,nodev", item["path"], mount], timeout=30)
    return mount


def verify_builds(root: Path, profile: dict):
    for name, key in (("QtCar", "center_build_id"), ("QtCarCluster", "cluster_build_id")):
        if name == "QtCarCluster" and profile.get("single_display"):
            continue
        executable = (root / "usr/tesla/UI/bin" / name).resolve(strict=True)
        if not executable.is_relative_to(root.resolve()):
            raise ValueError("Firmware executable resolves outside the read-only mount.")
        if profile.get("experimental"):
            with executable.open("rb") as stream:
                header = stream.read(20)
            if len(header) != 20 or header[:6] != b"\x7fELF\x02\x01" or header[18:20] != b"\x3e\x00":
                raise ValueError(f"{name} requires a different architecture; this launch profile needs x86_64 ELF.")
            continue
        notes = run(["readelf", "-n", executable]).stdout
        if profile[key] not in notes:
            raise ValueError(f"{name} does not match the tested build. A new compatibility profile is required.")


def status() -> dict:
    record = load_json(DATA / "session/status.json", {"phase": "stopped", "components": {}})
    if shutil.which("systemctl"):
        active = systemctl("is-active", UNIT).stdout.strip()
        if active not in ("active", "activating") and record.get("phase") not in ("stopped", "failed"):
            record["phase"] = "stopped"
        record["service"] = active or "inactive"
    record["host"] = load_json(DATA / "session/host-status.json", {})
    record["display_link"] = load_json(DATA / "session/display-link.json", {})
    record["controls"] = load_json(DATA / "session/controls-feedback.json", {})
    record['replay'] = load_json(DATA / 'session/replay-status.json', {})
    record['vehicle_services'] = load_json(DATA / 'session/vehicle-services-feedback.json', {})
    record['config_values'] = dict(load_json(DATA / 'session/config-values-feedback.json', {}),
                                   conflicts=load_json(DATA / 'session/config-conflicts.json', []),
                                   restarts=load_json(DATA / 'session/config-restarts.json', []),
                                   car_config=load_json(DATA / 'session/car-config-learned.json', []))
    record['service_capabilities'] = CAPABILITIES
    try:
        with (DATA / 'session/center.log').open('rb') as source:
            source.seek(max(0, source.seek(0, 2) - 65536))
            media_log = source.read(65536).decode('utf-8', errors='replace')
    except OSError:
        media_log = ''
    record['media'] = media_health(record.get('components', {}), media_log)
    record['camera'] = camera_health(load_json(DATA / 'session/camera-status.json', {}),
                                     load_json(DATA / 'session/camera-consumer.json', {}),
                                     record.get('phase') in ('starting', 'running', 'degraded'))
    return record


def stage_runtime(destination: Path):
    """Keep session sources on Linux storage after a packaged launcher exits."""
    destination.mkdir(parents=True, exist_ok=True)
    for source in sorted(PACKAGE.glob('*.py')):
        shutil.copy2(source, destination / source.name)
    shutil.copy2(PACKAGE / 'profiles.json', destination / 'profiles.json')
    shutil.copytree(PACKAGE / 'runtime', destination / 'runtime', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))


def start(identifier: str, map_id: str | None, browser: bool, cluster: bool):
    if os.getuid() == 0:
        raise RuntimeError("Run the application as a normal desktop user, not root.")
    environment = probe()
    if environment["missing"]:
        raise RuntimeError("Install runtime dependencies: " + ", ".join(environment["missing"]))
    if environment['architecture'] != 'x86_64':
        raise RuntimeError('This firmware profile requires an x86_64 Linux system.')
    if not environment['runtime_ready']:
        raise RuntimeError('Use Prepare computer to set up the runtime folders, then start again.')
    if not environment['fuse_available']:
        raise RuntimeError('The desktop user cannot access /dev/fuse. Enable FUSE in this Linux environment.')
    if not environment["display_available"]:
        raise RuntimeError("No Linux display is available. On Windows, enable WSLg and update the host GPU driver. On Linux, open an X11 or XWayland desktop session.")
    if not environment["systemd_available"]:
        raise RuntimeError("The user service manager is unavailable. Enable systemd in this WSL distribution or sign into a Linux desktop session.")
    if systemctl("is-active", UNIT).returncode == 0:
        return status()
    # The vendor apps use fixed local IPC endpoints. Avoid colliding with an
    # unrelated existing research session instead of killing its processes.
    if run(["pgrep", "-x", "QtCar"], check=False).returncode == 0:
        raise RuntimeError("Another QtCar session is running. Stop it before starting Infotainment Lab.")
    item = library_item(identifier)
    profile = profile_for(item["version"], item["variant"])
    if item["kind"] != "firmware" or not profile:
        raise ValueError("This firmware has been identified but has no tested launch profile yet.")
    root = mounted_image(item)
    verify_builds(root, profile)
    if profile.get("single_display"):
        cluster = False
    if profile.get("experimental") and browser:
        for member in ("usr/tesla/UI/bin/SpotifyServer", "usr/tesla/UI/bin/ChromiumAdapter",
                       "usr/bin/media-webapp-server", "opt/media-webapp"):
            if not (root / member).exists():
                raise ValueError(f"Generic MCU2 media dependency missing: {member}. Disable browsers to try the display runtime.")
    maps = None
    if map_id:
        map_item = library_item(map_id)
        if map_item["kind"] != "map":
            raise ValueError("Select a map image for the map slot.")
        maps = str(mounted_image(map_item))
    session = DATA / "session"
    session.mkdir(parents=True, exist_ok=True)
    # Stage only our sources into stable Linux storage. A packaged Windows
    # application's temporary extraction directory must not own the session.
    runtime = DATA / "engine"
    stage_runtime(runtime)
    config = {"firmware": str(root), "single_display": bool(profile.get("single_display")), "firmware_version": item["version"], "firmware_id": identifier, "map_id": map_id, "state": str(session), "profile": profile["id"],
              "browser": browser, "cluster": cluster, "maps": maps,
              "display": os.environ.get("DISPLAY", ":0"), "pulse": os.environ.get("PULSE_SERVER", ""),
              "wsl": "microsoft" in platform.release().lower(),
              "display_scale": display_scale.firmware_scale(bool(profile.get("single_display")))}
    atomic_json(session / "config.json", config)
    atomic_json(session / 'controls.json', Simulation().as_dict())
    camera = load_json(session / 'camera-source.json', {})
    if camera.get('mode') == 'replay':
        camera.update(autoplay=False, changed_at=time.time())
        atomic_json(session / 'camera-source.json', camera)
    atomic_json(session / 'controls-feedback.json', {})
    atomic_json(session / 'config-values-feedback.json', {})
    atomic_json(session / 'config-conflicts.json', [])
    atomic_json(session / 'config-restarts.json', [])
    atomic_json(session / 'camera-consumer.json', {})
    atomic_json(session / 'camera-status.json', {'phase': 'starting'})
    atomic_json(session / "status.json", {"phase": "starting", "profile": profile["id"], "components": {}})
    systemctl("reset-failed", UNIT)
    extra_env = ['--setenv=XAUTHORITY=' + os.environ['XAUTHORITY']] if os.environ.get('XAUTHORITY') else []
    run(["systemd-run", "--user", "--unit=" + UNIT, "--collect", *extra_env, "--property=KillMode=control-group",
         "--property=TimeoutStopSec=8", "/usr/bin/python3", runtime / "supervisor.py", session / "config.json"])
    return status()


def session_config(require_active=True):
    if require_active and systemctl('is-active', UNIT).returncode != 0:
        raise RuntimeError('Start a session before using its display tools.')
    return load_json(DATA / 'session/config.json', {})


def set_camera(mode, filename=None):
    config = source_config(mode, filename)
    if mode == 'raw' and Path(config['path']).resolve() == (DATA / 'session/camera/back.rgb').resolve():
        raise ValueError('Select the upstream writer output, not this session\'s camera output.')
    with controls_lock(DATA / 'session'):
        atomic_json(DATA / 'session/camera-source.json', config)
        atomic_json(DATA / 'session/replay-request.json', replay_request('play' if mode == 'replay' else 'manual'))
    return config


def set_replay(payload):
    session_config()
    request = replay_request(**payload)
    if request['action'] == 'manual':
        return manual_takeover(DATA / 'session')
    if load_json(DATA / 'session/camera-source.json', {}).get('mode') != 'replay':
        raise ValueError('Choose a dashcam recording before using replay controls.')
    atomic_json(DATA / 'session/replay-request.json', request)
    return request


def vehicle_services_state():
    path = DATA / 'session/vehicle-services.json'
    feedback = load_json(DATA / 'session/vehicle-services-feedback.json', {})
    # Repeated wheel presses can arrive before the next feedback report. Keep
    # the latest request until the runtime acknowledges that file version.
    if path.exists() and feedback.get('config_mtime_ns') != path.stat().st_mtime_ns:
        return VehicleServices.parse(load_json(path, {})).as_dict()
    return VehicleServices.parse(feedback.get('state') or load_json(path, {})).as_dict()


def publish_can_state(**state):
    """Keep the CAN service's view in step with the desktop. Never fatal."""
    try:
        import can_service
        if can_service.running(can_service_state()):
            can_service.request(can_service_state(), {'action': 'state', **state}, timeout=1)
    except Exception:
        pass


def set_vehicle_services(payload):
    result = VehicleServices.parse(vehicle_services_state()).patched(payload).as_dict()
    atomic_json(DATA / 'session/vehicle-services.json', result)
    publish_can_state(vehicle_services=result)
    return result


MAX_CONFIG_VALUE = 65536  # some settings are base64 blobs of a few KB (GUI_homePlaceHistoryItem is 2.3 KB)


def set_config_values(payload):
    """Merge named DataValue overrides for the runtime to write to the displays.

    One bad entry never fails the rest: the valid ones are stored and the names that were
    not stored come back in `rejected`.
    """
    path = DATA / 'session/config-values.json'
    values = load_json(path, {})
    explicit_path = DATA / 'session/config-explicit.json'
    explicit = set(load_json(explicit_path, []))
    refused = config_csv.unsupported_car(payload.get('values', {}), load_json(DATA / 'session/config.json', {}).get('single_display'))
    if refused:
        raise ValueError(refused)
    rejected = []
    for name in payload.get('remove', []):
        values.pop(str(name), None)
        explicit.discard(str(name))
    for name, value in payload.get('values', {}).items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,127}', str(name)) or config_csv.private(str(name)):
            rejected.append(str(name)[:60])
        elif isinstance(value, bool) or isinstance(value, (int, float)) or (isinstance(value, str) and len(value) <= MAX_CONFIG_VALUE):
            values[name] = value
            (explicit.add if name in payload.get('explicit', []) else explicit.discard)(name)
        else:
            rejected.append(name)
    atomic_json(path, values)
    atomic_json(explicit_path, sorted(explicit & values.keys()))
    return {'count': len(values), 'rejected': rejected}


def can_service_state() -> Path:
    path = DATA / 'session'
    path.mkdir(parents=True, exist_ok=True)
    return path


def can_start(backend_choice='auto', create=False, port=20200, restart=False):
    """Start the CAN and gateway service as an ordinary user process."""
    import can_service

    state = can_service_state()
    if can_service.running(state):
        status = can_service.request(state, {'action': 'status'})
        if status.get('revision') == can_service.SERVICE_REVISION and not restart:
            return dict(status, already_running=True)
        # A service started before an update keeps running its old code, so the
        # panel would report stale behaviour. Replace it.
        try:
            can_service.request(state, {'action': 'stop'}, timeout=2)
        except Exception:
            pass
        for _ in range(50):
            if not can_service.running(state):
                break
            time.sleep(.1)
        else:
            raise RuntimeError('The previous CAN service did not stop. End that process, then start again.')
    log = (state / 'can-gateway.log').open('a')
    process = subprocess.Popen([sys.executable, str(PACKAGE / 'can_service.py'), '--state', str(state),
                               '--backend', backend_choice, '--bridge-port', str(int(port)),
                               *(['--create-interfaces'] if create else [])],
                              stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                              cwd=str(PACKAGE))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('The CAN gateway service exited during startup. Open Diagnostics for its log.')
        if can_service.running(state):
            return dict(can_service.request(state, {'action': 'status'}), pid=process.pid)
        time.sleep(.2)
    process.terminate()
    raise RuntimeError('The CAN gateway service did not become ready in time.')


def can_call(payload):
    import can_service

    if not isinstance(payload, dict):
        raise ValueError('CAN requests must be an object.')
    return can_service.request(can_service_state(), payload)


def can_status():
    import can_service

    state = can_service_state()
    if not can_service.running(state):
        from can_bus import backend_report
        return {'service': 'stopped', 'environment': backend_report()}
    return can_service.request(state, {'action': 'status'})


def can_setup(names=('vcan0', 'vcan1', 'vcan2')):
    """Create the virtual CAN interfaces once. This is the only privileged step."""
    from can_bus import create_vcan, vcan_supported

    if os.geteuid() != 0:
        raise RuntimeError('Creating virtual CAN interfaces needs an administrator. The service itself runs without root.')
    if not vcan_supported():
        raise RuntimeError('This kernel does not expose SocketCAN. The software CAN hub needs no setup.')
    run(['modprobe', 'vcan'], check=False)
    return {'interfaces': [create_vcan(name) for name in names]}


def open_browser(mode, url=None):
    import dbus
    config = session_config()
    if not config.get('browser'): raise RuntimeError('Enable Chromium when starting this device.')
    if mode not in MODES: raise ValueError('Unknown browser view.')
    address = (DATA / 'session/dbus-address').read_text().strip()
    bus = dbus.bus.BusConnection(address)
    center = dbus.Interface(bus.get_object('com.tesla.CenterDisplayDbus', '/CenterDisplayDbus'), 'com.tesla.CenterDisplayDbus')
    target = browser_url(url) if url else load_json(DATA / 'session/browser-page.json', {}).get('url')
    if not target: raise RuntimeError('The local browser page is still starting.')
    if mode == 'theater':
        center.startApp('browser', 'theater', '', signature='sss', timeout=5)
    else:
        center.openUrl(target, timeout=5)
        center.maximizeAppWindow('browser', mode != 'card', timeout=5)
    focus_display('center')
    return {'mode': mode, 'requested': True}


def steering_button(action):
    import dbus
    from steering import execute
    config = session_config()
    bus = dbus.bus.BusConnection((DATA / 'session/dbus-address').read_text().strip())
    center = dbus.Interface(bus.get_object('com.tesla.CenterDisplay', '/CenterDisplayDbus'), 'com.tesla.CenterDisplayDbus')
    cluster = (dbus.Interface(bus.get_object('com.tesla.ClusterDisplay', '/ClusterDisplayDbus'),
                              'com.tesla.ClusterDisplayDbus') if config.get('cluster') else None)
    return execute(action, center, cluster, vehicle_services_state, set_vehicle_services)


def camera_preview():
    from PIL import Image
    session_config()
    path = DATA / 'session/camera/back.rgb'
    if not path.exists():
        return {'image': ''}
    with path.open('rb') as source:
        data = source.read(FRAME_BYTES + 1)
    if len(data) != FRAME_BYTES:
        return {'image': ''}
    frame = Image.frombytes('RGB', (WIDTH, HEIGHT), data)
    frame.thumbnail((800, 450))
    stream = io.BytesIO()
    frame.save(stream, format='JPEG', quality=80)
    return {'image': base64.b64encode(stream.getvalue()).decode('ascii')}


def capture_displays(preview=False):
    config = session_config()
    displays = {}
    for name in ('center', 'cluster'):
        if name == 'cluster' and not config.get('cluster'):
            continue
        display = config.get(name + '_display', '')
        pattern = r':[01]\.0' if config.get('display_backend') == 'provided' else r':(?:19|[2-5][0-9])'
        if not re.fullmatch(pattern, display):
            raise RuntimeError('The session display is not ready yet.')
        displays[name] = display
    from PIL import ImageGrab
    images = {}
    for name, display in displays.items():
        frame = ImageGrab.grab(xdisplay=display)
        if preview:
            frame.thumbnail((700, 600))
        stream = io.BytesIO()
        frame.save(stream, format='PNG')
        images[name] = base64.b64encode(stream.getvalue()).decode('ascii')
    return {'images': images, 'captured_at': time.time()}


def focus_display(name):
    config = session_config()
    if name not in ('center', 'cluster'):
        raise ValueError('Unknown display.')
    if name == 'cluster' and not config.get('cluster'):
        raise RuntimeError('The instrument display is disabled for this session.')
    if config.get('display_backend') == 'provided':
        # The host raises the owning QEMU window; no Xephyr window exists here.
        return {'display': name, 'guest': True}
    title = 'Infotainment Lab | ' + ('Center' if name == 'center' else 'Instruments')
    env = dict(os.environ, DISPLAY=config['display'])
    matches = run(['xdotool', 'search', '--onlyvisible', '--name', '^' + re.escape(title)], env=env, check=False).stdout.split()
    if not matches:
        raise RuntimeError('The display window is not ready. Wait for startup to finish.')
    for identifier in matches:
        if identifier.isdigit():
            run(['xdotool', 'windowraise', identifier], env=env)
            run(['xdotool', 'windowfocus', identifier], env=env, check=False)
    return {'display': name}


def restart():
    # A failed session is inactive but keeps its config, so Restart still works after a crash.
    config = session_config(require_active=False)
    if not config.get('firmware'):
        raise RuntimeError('Start a session first.')
    identifier = config.get('firmware_id') or Path(config['firmware']).name
    map_id = config.get('map_id') or (Path(config['maps']).name if config.get('maps') else None)
    library_item(identifier)
    if map_id:
        library_item(map_id)
    stop()
    return start(identifier, map_id, config['browser'], config['cluster'])


def stop():
    if systemctl('is-active', UNIT).stdout.strip() in ('active', 'activating', 'deactivating'):
        systemctl("stop", UNIT, check=True)
    atomic_json(DATA / "session/status.json", {"phase": "stopped", "components": {}})
    # Unmount only this application's own FUSE mounts, after its clients stop.
    for mount in (DATA / "mounts").glob("*"):
        release_mount(mount)
    return status()


def factory_reset():
    """Drop every cached artefact so the next start behaves like a first import.

    Removes the session state, the copied engine, FUSE mount points and the
    library index. The user's firmware, map and QEMU guest files are untouched.
    """
    stop()  # also releases the image mounts, lazily when something still holds them
    # Never delete through a mount: rmtree would walk into the firmware image.
    held = [m.name for m in (DATA / "mounts").glob("*") if not release_mount(m)]
    if held:
        raise RuntimeError("The firmware image could not be unmounted (fusermount3 refused it), so nothing was deleted. "
                           f"Run `fusermount3 -uz {DATA / 'mounts' / held[0]}` or restart WSL, then try Full reset again.")
    for name in ("session", "engine", "mounts"):
        target = DATA / name
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)
    (DATA / "library.json").unlink(missing_ok=True)
    return {"reset": True, "status": status()}


SECURITYFS = "securityfs /sys/kernel/security securityfs defaults 0 0\n"


def keep_apparmor_loaded(systemd=Path("/run/systemd/system"), fstab=Path("/etc/fstab"), wsl=None):
    """Have the AppArmor service reload the profiles after every reboot or `wsl --shutdown`.

    WSL does not mount securityfs at boot, and apparmor.service refuses to start without it.
    """
    if wsl is None:
        wsl = "microsoft" in platform.release().lower()
    if wsl and not fstab.is_symlink() and "securityfs" not in (fstab.read_text() if fstab.exists() else ""):
        with fstab.open("a") as file:
            file.write(SECURITYFS)
    if systemd.is_dir() and shutil.which("systemctl"):
        run(["systemctl", "enable", "apparmor"], check=False)


def setup(uid: int):
    if os.geteuid() != 0:
        raise RuntimeError("Dependency setup needs an administrator. The infotainment session itself runs without root.")
    owner = pwd.getpwuid(uid)
    if uid < 1000:
        raise ValueError("Choose a normal desktop user for runtime ownership.")
    run(["apt-get", "update"], timeout=300)
    run(["apt-get", "install", "-y", *PACKAGES], timeout=900)
    policy_source = PACKAGE / "runtime/media-apparmor.profile"
    policy_target = Path("/etc/apparmor.d/tsla-infotainment-lab-media")
    if policy_target.is_symlink():
        raise RuntimeError("The media AppArmor policy path is a symbolic link; automatic setup has left it unchanged.")
    shutil.copyfile(policy_source, policy_target)
    policy_target.chmod(0o644)
    if Path("/sys/module/apparmor/parameters/enabled").read_text().strip().upper() == "Y":
        run(["apparmor_parser", "-r", policy_target])
    keep_apparmor_loaded()
    for name in ("/run/chromium", "/run/chromium/policies", "/run/chromium/policies/chromium", "/run/chromium/policies/chromium-card", "/run/chromium/policies/chromium-fullscreen", "/opt/games/run", "/opt/games/run/chromium-cache-files", "/opt/games/run/i2v"):
        path = Path(name)
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise RuntimeError("A runtime directory is a symbolic link; automatic setup has left it unchanged.")
        if not path.exists():
            path.mkdir(parents=True, mode=0o755)
            os.chown(path, owner.pw_uid, owner.pw_gid)
    return {"installed": True, "media_profiles": "installed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("probe", "import", "start", "stop", "status", "setup", "report", "logs", "controls", "preview", "capture", "focus", "restart", "camera", "camera-preview", "replay", "vehicle-services", "config-values", "browser", "steering", "can", "can-start", "can-status", "can-setup", "factory-reset", "qemu-check", "ssh-key", "qemu-start", "qemu-status", "qemu-stop"))
    parser.add_argument('--button')
    parser.add_argument('--can-backend', choices=('auto', 'socketcan', 'software'), default='auto')
    parser.add_argument('--bridge-port', type=int, default=20200)
    parser.add_argument('--create-interfaces', action='store_true')
    parser.add_argument('--engine', choices=('native', 'qemu'), default='native')
    parser.add_argument('--vm-directory')
    parser.add_argument('--source', choices=('pattern', 'video', 'raw', 'off', 'replay'), default='pattern')
    parser.add_argument('--mode', choices=tuple(MODES), default='browser')
    parser.add_argument('--url')
    parser.add_argument('--display', choices=('center', 'cluster'), default='center')
    parser.add_argument("--path")
    parser.add_argument("--id")
    parser.add_argument("--map-id")
    parser.add_argument("--uid", type=int, default=1000)
    parser.add_argument("--payload", default="{}")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-cluster", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--internet", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == 'ssh-key' and args.engine != 'qemu':
            raise ValueError('The SSH console needs the virtual-hardware (QEMU) engine.')
        if args.engine == 'qemu' and args.action not in ('import', 'factory-reset', 'qemu-check', 'qemu-start', 'qemu-status', 'qemu-stop'):
            sys.path.insert(0, str(PACKAGE.parent))
            from infotainment_lab.virtual_control import dispatch
            result = dispatch(args, sys.modules[__name__])
        elif args.action == "probe": result = probe()
        elif args.action == "import": result = import_image(args.path or "")
        elif args.action == 'qemu-check':
            from qemu_boot import boot_check
            item = library_item(args.id or '')
            if item['kind'] != 'firmware':
                raise ValueError('Select a firmware image for the QEMU boot check.')
            result = boot_check(Path(item['path']), DATA / 'qemu' / item['id'])
        elif args.action in ('qemu-start', 'qemu-status', 'qemu-stop'):
            from qemu_runtime import start as vm_start, status as vm_status, shutdown as vm_shutdown
            item = library_item(args.id or '')
            if item['kind'] != 'firmware':
                raise ValueError('Select a firmware image for the VM.')
            directory = DATA / 'qemu' / item['id']
            if args.action == 'qemu-start':
                result = vm_start(directory, graphics=not args.headless, internet=args.internet)
            elif args.action == 'qemu-status':
                result = vm_status(directory)
            else:
                result = vm_shutdown(directory)
        elif args.action == "start": result = start(args.id or "", args.map_id, not args.no_browser, not args.no_cluster)
        elif args.action == "stop": result = stop()
        elif args.action == "status": result = status()
        elif args.action == "factory-reset": result = factory_reset()
        elif args.action == "setup": result = setup(args.uid)
        elif args.action == 'restart': result = restart()
        elif args.action == 'camera': result = set_camera(args.source, args.path)
        elif args.action == 'camera-preview': result = camera_preview()
        elif args.action == 'replay': result = set_replay(json.loads(args.payload))
        elif args.action == 'vehicle-services': result = set_vehicle_services(json.loads(args.payload))
        elif args.action == 'config-values': result = set_config_values(json.loads(args.payload))
        elif args.action == 'browser': result = open_browser(args.mode, args.url)
        elif args.action == 'steering': result = steering_button(args.button)
        elif args.action == 'can': result = can_call(json.loads(args.payload))
        elif args.action == 'can-start':
            result = can_start(args.can_backend, args.create_interfaces, args.bridge_port)
        elif args.action == 'can-status': result = can_status()
        elif args.action == 'can-setup': result = can_setup()
        elif args.action in ('preview', 'capture'): result = capture_displays(args.action == 'preview')
        elif args.action == 'focus': result = focus_display(args.display)
        elif args.action == "report": result = public_report(status(), probe())
        elif args.action == "controls":
            result = Simulation.parse(json.loads(args.payload)).as_dict()
            publish_can_state(simulation=result)
            result = manual_takeover(DATA / 'session', result)
        else:
            result = {"logs": {p.name: p.read_text(errors="replace")[-12000:] for p in (DATA / "session").glob("*.log") if p.stat().st_size < 100_000_000}}
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
