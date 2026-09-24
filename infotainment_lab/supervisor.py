"""Own the desktop session, its private bus, displays and ordinary user processes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import traceback

from core import atomic_json, load_json
from browser import MODES, browser_arguments, media_browser_arguments, media_webapp_arguments, odin_browser_arguments
from firmware_fonts import font_environment
from host_graphics import environment as graphics_environment
import config_csv
from display_graphics import probe_display, application_environment
from display_scale import scaled

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
children: dict[str, subprocess.Popen] = {}
outputs = []
stopping = False
restart_specs = {}
service_retries = {}
retry_after = {}
RECOVERABLE = {'spotify', 'media-adapter', 'media-webapp', 'chromium-media', 'display-link',
               'dv-server', 'odin-engine', 'service-ui', 'service-ui-relay', 'chromium-odin'}
# The Service Mode panel's backend and browser. Their backend needs vehicle
# identity the lab does not provide, so their exit must not mark the session degraded.
OPTIONAL = {'dv-server', 'odin-engine', 'service-ui', 'service-ui-relay', 'chromium-odin'}
# VAPI_carType values the firmware's libQtCarVAPI defines that keep-awake may also write.
LANGUAGE_SETTINGS = {'GUI_language', 'GUI_manualLanguage', 'GUI_locale'}
CAR_TYPES = ('ModelS', 'ModelS2', 'ModelX', 'Model3')


def prepare_service_sockets(path=Path('/tmp/dvaccess')):
    """The native publishers and subscribers share this fixed Unix directory."""
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('The native service socket directory must be a private directory owned by this Linux user.')


def check_media_ports():
    # These are fixed endpoints in the supplied media app. Do not accidentally
    # attach its browser to a different application's listener.
    for port in (4210, 4540, 9000, 9001, 9007, 9009):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(('127.0.0.1', port))
            except OSError as exc:
                raise RuntimeError(f'Media port {port} is already in use. Close the other local media session and retry.') from exc


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def service_ui_commands(odin: Path, state: Path, port: int = 8000) -> tuple[list, list, list]:
    """The backend inside its own network namespace, the host relay to its port,
    and the Odin engine stand-in its namespace's engine port is relayed to."""
    sock, engine = state / 'service-ui.sock', state / 'odin-engine.sock'
    script = RUNTIME / 'service-ui-netns.py'
    backend = ['unshare', '--map-current-user', '--keep-caps', '-n',
               '/usr/bin/python3', script, 'ns', sock, str(port), engine, '--', odin / 'service-ui']
    return (backend, ['/usr/bin/python3', script, 'host', sock, str(port)],
            ['/usr/bin/python3', RUNTIME / 'odin-engine.py', engine, odin])


def session_phase(elapsed: float, positioned: bool, components: dict) -> str:
    if any(value == 'exited' for name, value in components.items() if name not in OPTIONAL):
        return 'degraded'
    return 'running' if elapsed > 15 and positioned else 'starting'


def recover_services(now):
    for name, spec in tuple(restart_specs.items()):
        if children[name].poll() is None:
            continue
        count = service_retries.get(name, 0)
        if count >= 2:
            continue
        if name not in retry_after:
            retry_after[name] = now + 2 * (count + 1)
        elif now >= retry_after[name]:
            service_retries[name] = count + 1
            retry_after.pop(name)
            launch(name, *spec)


class ConfigurationRestart(RuntimeError):
    """The vendor app deliberately restarted after persisting first-run settings."""

    def __init__(self, message, names=(), display=''):
        super().__init__(message)
        self.names = list(names)
        self.display = display


def changed_dvs(tail: str) -> list:
    """The DataValues the firmware named in its last 'Restarting QtCar because of changed DVs' line."""
    found = re.findall(r'Restarting \w+ because of changed DVs:([^\n]*)', tail)
    if found:
        return re.findall(r'[A-Za-z][A-Za-z0-9_]*', found[-1])  # the firmware separates them with commas
    names = set(re.findall(r'\[CarConfigChangeListener\] INFO DV (\w+) reported changed', crash_shutdown(tail)))
    if re.search(r'restarting (reason|app because):? language changed', tail):
        # Imported language settings can disagree (GUI_language vs GUI_manualLanguage) and restart forever.
        names |= LANGUAGE_SETTINGS
    return sorted(names)


def crash_shutdown(tail: str) -> str:
    """The log after a car-config change began the display's own shutdown, or '' if none did."""
    change = tail.rfind('[CarConfigChangeListener] INFO DV ')
    return tail[change:] if change >= 0 and 'Sending abort to' in tail[change:] else ''


def remember_car_config(state, names):
    """Names the firmware restarted on are car config: they are only written at start from now on."""
    try:
        known = json.loads((state / 'car-config-learned.json').read_text())
    except (OSError, ValueError):
        known = []
    merged = sorted(set(known) | set(names))
    if merged != known: atomic_json(state / 'car-config-learned.json', merged)


def record_restart(state, display, names, dropped=(), limit=50):
    """Keep why the firmware restarted (config-restarts.json) so the desktop can say so in its alerts."""
    try:
        history = json.loads((state / 'config-restarts.json').read_text())
    except (OSError, ValueError):
        history = []
    if not isinstance(history, list): history = []
    history.append({'at': time.time(), 'display': display, 'names': list(names), 'dropped': list(dropped)})
    atomic_json(state / 'config-restarts.json', history[-limit:])


def drop_conflicting_override(state, counts, names, limit=3):
    """A value that restarts the firmware again and again is removed from the overrides.

    Each display restarts once for a new value, so two restarts are normal; the third is a loop.

    Returns the names dropped, and records them in config-conflicts.json for the desktop.
    """
    dropped = []
    for name in names:
        counts[name] = counts.get(name, 0) + 1
        if counts[name] >= limit: dropped.append(name)
    if dropped:
        try:
            values = json.loads((state / 'config-values.json').read_text())
        except (OSError, ValueError):
            values = {}
        if isinstance(values, dict) and any(name in values for name in dropped):
            atomic_json(state / 'config-values.json', {k: v for k, v in values.items() if k not in dropped})
        try:
            known = json.loads((state / 'config-conflicts.json').read_text())
        except (OSError, ValueError):
            known = []
        atomic_json(state / 'config-conflicts.json', sorted(set(known) | set(dropped)))
    return dropped


def user_profile(state, base_profile: Path) -> Path:
    """The vehicle profile with the saved car-config values folded in, as if the json had been edited.

    The profile is the one path the firmware is built around: it is written once when a display
    starts, as a coherent set. Writing the overrides through it, not as separate writers, is what works.
    """
    profile = json.loads(base_profile.read_text())
    signals = profile.setdefault('signals', {})
    def saved(name, default):
        try:
            value = json.loads((state / name).read_text())
        except (OSError, ValueError):
            return default
        return value if isinstance(value, type(default)) else default

    if saved('config-values.json', {}).get('VAPI_carType') == 'Model3':
        # This S/X layout has no Model 3 assets and the center segfaults; Model 3 needs single-display mode.
        drop_conflicting_override(state, {}, ['VAPI_carType'], limit=1)
    overrides, learned = saved('config-values.json', {}), saved('car-config-learned.json', [])
    car = set(signals) | config_csv.CAR_CONFIG_EXTRA | set(learned)
    signals.update({name: value for name, value in overrides.items() if name in car})
    target = state / 'vehicle-profile.json'
    atomic_json(target, profile)
    return target


def restart_allowance(state) -> int:
    """Each display restarts once per changed car-config value, so allow two more restarts per override."""
    try:
        values = json.loads((state / 'config-values.json').read_text())
        return min(80, 2 * len(values)) if isinstance(values, dict) else 0
    except (OSError, ValueError):
        return 0


def is_configuration_restart(returncode: int, tail: str) -> bool:
    # The center restarts as QtCar and the cluster as QtCarCluster; both are deliberate.
    # An imported UI language restarts both too ("CID UI is restarting reason: language changed",
    # "restarting app because language changed").
    # The firmware kills itself for these, but sometimes crashes while tearing its threads down first.
    return returncode in (-9, -6, -11) and (
        ('[CarConfigChangeProcessRestarter]' in tail
         and re.search(r'Restarting QtCar\w* because of changed DVs:', tail) is not None)
        or re.search(r'UI is restarting reason:|restarting app because', tail) is not None
        or crash_shutdown(tail) != '')


def request_stop(*_):
    global stopping
    stopping = True


def launch(name: str, argv: list, state: Path, env: dict, cwd=None):
    stream = (state / (name + ".log")).open("w")
    outputs.append(stream)
    process = subprocess.Popen([str(v) for v in argv], stdout=stream, stderr=subprocess.STDOUT,
                               env=env, cwd=str(cwd or env.get("TESLA_BIN", state)), stdin=subprocess.DEVNULL)
    children[name] = process
    if name in RECOVERABLE:
        restart_specs[name] = (argv, state, env, cwd)
    return process


def command(argv, env=None, check=True, timeout=15):
    result = subprocess.run([str(v) for v in argv], capture_output=True, text=True,
                            errors="replace", timeout=timeout, env=env)
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[-2500:])
    return result


def confined(profile: str, argv: list) -> list:
    """Attach the AppArmor peer name expected by the local firmware services."""
    aa_exec = shutil.which("aa-exec")
    if not aa_exec:
        return argv
    probe = command([aa_exec, "-p", profile, "--", "/bin/true"], check=False)
    if probe.returncode:
        # Unconfined peers are rejected by the firmware's PEERSEC checks (media card, Service Mode panel).
        print(f"AppArmor profile {profile} is not loaded; starting it unconfined. "
              "Rerun Runtime Setup or `sudo apparmor_parser -r /etc/apparmor.d/tsla-infotainment-lab-media`.", flush=True)
        return argv
    return [aa_exec, "-p", profile, "--", *argv]


def cleanup():
    for child in reversed(list(children.values())):
        if child.poll() is None:
            child.terminate()
    deadline = time.monotonic() + 5
    for child in children.values():
        try:
            child.wait(timeout=max(.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            child.kill()
    for stream in outputs:
        stream.close()


def outer(config: dict, config_path: Path):
    state = Path(config["state"])
    env = dict(os.environ, DISPLAY=config["display"])
    if config["pulse"]:
        env["PULSE_SERVER"] = config["pulse"]
    if config["wsl"]:
        env.update(GALLIUM_DRIVER="d3d12", MESA_LOADER_DRIVER_OVERRIDE="d3d12")
        env = graphics_environment(env, is_wsl=True)
    for name in ("native-netguard", "native-input", "native-compositor", "native-browser-input", "native-camera"):
        argv = ["gcc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", RUNTIME / (name + ".c"),
                "-o", state / (name + ".so"), "-ldl"]
        if name == "native-browser-input": argv += ["-lX11"]
        command(argv, timeout=90)
    provided = config.get("display_backend") == "provided"
    if provided:
        displays = [config.get("center_display", "")]
        if config["cluster"]:
            displays.append(config.get("cluster_display", ""))
        if any(not re.fullmatch(r":\d+\.\d+", value) for value in displays):
            raise ValueError("Provide local X11 screens for the firmware displays.")
        if len(set(displays)) != len(displays) and not config.get("shared_desktop"):
            raise ValueError("Distinct screens are required unless shared desktop is selected.")
    else:
        slots = [n for n in range(19, 60) if not Path(f"/tmp/.X11-unix/X{n}").exists() and not Path(f"/tmp/.X{n}-lock").exists()]
        if len(slots) < 2:
            raise RuntimeError("No free X11 display slots are available.")
        config["center_display"], config["cluster_display"] = f":{slots[0]}", f":{slots[1]}"
    for name, display, size in (("center-display", config["center_display"], screen_geometry(config, "center")),
                                 ("cluster-display", config["cluster_display"], screen_geometry(config, "cluster"))):
        if name == "cluster-display" and not config["cluster"]: continue
        if not provided:
            launch(name, ["Xephyr", display, "-screen", size, "-noreset", "-nolisten", "tcp", "-glamor",
                          "-title", "Infotainment Lab | " + ("Center" if name.startswith("center") else "Instruments")], state, env)
        for _ in range(60):
            if stopping: return
            if command(["xdpyinfo", "-display", display], env=env, check=False, timeout=2).returncode == 0: break
            time.sleep(.2)
        else: raise RuntimeError("The Linux GUI display did not start. Check WSLg or your X11 desktop.")
    config['display_graphics'] = {}
    for name in ('center', 'cluster') if config['cluster'] else ('center',):
        render_display = (config['center_display'] if name == 'cluster' and
                          config.get('cluster_gpu_offload') else None)
        info, gpu = probe_display(dict(env, DISPLAY=config[name + '_display']),
                                  render_display=render_display)
        (state / ('graphics.log' if name == 'center' else 'graphics-cluster.log')).write_text(gpu)
        config['display_graphics'][name] = info
    config.update(config['display_graphics']['center'])
    atomic_json(config_path, config)
    attempt, restart_counts = -1, {}
    while True:
        attempt += 1
        config['configuration_restarts'] = attempt
        atomic_json(config_path, config)
        bus = launch("private-bus", ["dbus-run-session", "--", "/usr/bin/python3", __file__, config_path, "--session"], state, env)
        while not stopping and bus.poll() is None:
            if any(p.poll() is not None for name, p in children.items() if name.endswith("display")):
                raise RuntimeError("A display window was closed. The session has been stopped.")
            time.sleep(.5)
        if stopping or not bus.returncode:
            return
        previous = json.loads((state / "status.json").read_text())
        if previous.get('configuration_restart'):
            names = previous.get('changed_dvs', [])
            if attempt >= 2 + restart_allowance(state):
                record_restart(state, previous.get('restarted_display', ''), names)
                raise RuntimeError('The firmware kept restarting its UI' + (' because of ' + ', '.join(names) if names else '') + '.')
            remember_car_config(state, names)
            dropped = drop_conflicting_override(state, restart_counts, names)
            record_restart(state, previous.get('restarted_display', ''), names, dropped)
            time.sleep(1)
            continue
        raise RuntimeError(previous.get("error", "The session stopped unexpectedly. Open Diagnostics for details."))


def display_scale(config):
    """Factor by which the firmware draws larger than its lab default (see display_scale.py)."""
    try:
        value = float(config.get("display_scale", 1))
    except (TypeError, ValueError):
        return 1.0
    return value if 1 <= value <= 4 else 1.0


def screen_geometry(config, name):
    """The X screen size for one firmware display, as WxH."""
    base = (1920, 1200) if name == "center" and config.get("single_display") else (720, 1152) if name == "center" else (1280, 480)
    return "%dx%d" % scaled(base, display_scale(config))


def arrange_cluster(env, scale=1.0):
    """A slow display must not turn a cosmetic layout update into session death."""
    try:
        windows = command(["xdotool", "search", "--onlyvisible", "--name", "^QtCarCluster$"],
                          env=env, check=False, timeout=2).stdout.split()
        for wid in windows:
            geometry = command(["xdotool", "getwindowgeometry", "--shell", wid],
                               env=env, check=False, timeout=2).stdout
            width, left = scaled((1280, 736), scale)
            if f"WIDTH={width}\n" in geometry and (f"X={left}\n" not in geometry or "Y=0\n" not in geometry):
                command(["xdotool", "set_window", "--overrideredirect", "1", wid], env=env, timeout=2)
                command(["xdotool", "windowmove", wid, str(left), "0"], env=env, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def _geometry(env, wid):
    text = command(["xdotool", "getwindowgeometry", "--shell", wid], env=env, check=False, timeout=2).stdout
    values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    return tuple(int(values.get(key, 0)) for key in ("X", "Y", "WIDTH", "HEIGHT"))


def center_target(window, screen, main):
    """Where a center window belongs, or None when it already fits the screen.

    The main window is pinned to the origin. Later windows (Service Mode, dialogs)
    are placed by the firmware in its unscaled car coordinates and can land past
    the smaller desktop screen, so they are clamped back inside it."""
    x, y, width, height = window
    screen_width, screen_height = screen
    if main:
        return None if (x, y) == (0, 0) else (0, 0)
    target = (max(0, min(x, screen_width - width)), max(0, min(y, screen_height - height)))
    return None if target == (x, y) else target


def arrange_center(env):
    """Keep every firmware center window on screen, not just the first one.

    Returns True when the main window is at the origin. Matches QtCar by
    window name or class; the off-screen composited browser windows are untouched."""
    try:
        size = command(["xdotool", "getdisplaygeometry"], env=env, check=False, timeout=2).stdout.split()
        if len(size) != 2:
            return False
        screen = (int(size[0]), int(size[1]))
        windows, found = [], []
        for field in ("--name", "--class"):
            for wid in command(["xdotool", "search", "--onlyvisible", field, "^QtCar$"],
                               env=env, check=False, timeout=2).stdout.split():
                if wid not in found:
                    found.append(wid)
        for wid in found:
            geometry = _geometry(env, wid)
            if geometry[2] > 200 and geometry[3] > 200:
                windows.append((wid, geometry))
        if not windows:
            return False
        main = max(windows, key=lambda item: item[1][2] * item[1][3])[0]
        for wid, geometry in windows:
            target = center_target(geometry, screen, wid == main)
            if target is None:
                continue
            if wid == main:
                command(["xdotool", "set_window", "--overrideredirect", "1", wid], env=env, timeout=2)
            else:
                print(f"Moving center window {wid} from {geometry[0]},{geometry[1]} into view", flush=True)
            command(["xdotool", "windowmove", wid, str(target[0]), str(target[1])], env=env, timeout=2)
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError):
        return False
    return True


def session(config: dict):
    state, firmware = Path(config["state"]), Path(config["firmware"])
    if config['browser']:
        check_media_ports()
    prepare_service_sockets()
    ui = firmware / "usr/tesla/UI"
    scale = display_scale(config)
    base = dict(os.environ, TESLA_NATIVE_STATE=str(state), TESLA_FIRMWARE=str(firmware),
                TESLA_NATIVE_CAR_TYPE="ModelX", TESLA_NATIVE_STATE_DELAY="0.2",
                TESLA_NATIVE_VEHICLE_PROFILE=str(user_profile(state, RUNTIME / "vehicle-profile-model-x-mcu2.json")),
                TESLA_NATIVE_TITLE="Infotainment Lab | Center", TESLA_HOST_DISPLAY=config["display"],
                TESLA_DV_SERVICES="com.tesla.CenterDisplay" + (",com.tesla.ClusterDisplay" if config["cluster"] else ""))
    if config.get("display_backend") == "provided":
        base["TESLA_EXTERNAL_DISPLAY"] = "1"
    base["DBUS_SYSTEM_BUS_ADDRESS"] = base["DBUS_SESSION_BUS_ADDRESS"]
    car_type = json.loads(Path(base["TESLA_NATIVE_VEHICLE_PROFILE"]).read_text()).get("signals", {}).get("VAPI_carType")
    if car_type in CAR_TYPES:
        base["TESLA_NATIVE_CAR_TYPE"] = car_type  # the keep-awake writer must agree with the profile
    if config.get("single_display"):
        base["TESLA_NATIVE_CAR_TYPE"] = "Model3"
        base["TESLA_NATIVE_VEHICLE_PROFILE"] = ""
    (state / "dbus-address").write_text(base["DBUS_SESSION_BUS_ADDRESS"])
    shutil.copyfile(RUNTIME / "audio-wslg.conf", state / "audio.conf")
    base["ALSA_CONFIG_PATH"] = str(state / "audio.conf")
    base.update(font_environment(firmware, state))
    for home in ("center-home", "cluster-home", "apviz-home"):
        for folder in ("car", "data", "logs"):
            (state / home / ".Tesla" / folder).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(RUNTIME / "display-settings-mcu2.conf", state / home / ".Tesla/car/settings.conf")
    launch("host-state", ["/usr/bin/python3", RUNTIME / "keep-awake.py"], state, base)
    launch("camera-feed", ["/usr/bin/python3", RUNTIME / "camera-feed.py"], state, base)
    if config['browser']:
        launch('browser-page', ['/usr/bin/python3', RUNTIME / 'browser-page.py'], state, base)
    gui = dict(base, UI_PLATFORM="SX", UI_VEHICLE="ModelX", UI_TARGET="ICE", TESLA_HOME=str(ui),
               TESLA_BIN=str(ui / "bin"), TESLA_LIB=str(ui / "lib"), QT_PLUGIN_PATH=str(firmware / "usr/lib/qt/plugins"),
               QT_X11_NO_MITSHM="1", QT_NO_GLIB="1", EGL_PLATFORM="x11",
               LD_LIBRARY_PATH=f"{ui}/lib:{ui}/bin:{firmware}/usr/lib/engines-3:{firmware}/usr/lib/lmms:/usr/lib/x86_64-linux-gnu:{firmware}/usr/lib",
               TESLA_FORCE_NATIVE_APVIZ="1", TESLA_NATIVE_APVIZ_CPU_UPLOAD="1", TESLA_NATIVE_APVIZ_REFRESH_MS="33", TESLA_NATIVE_APVIZ_TRACE="0")
    guard = f"{state}/native-netguard.so"  # Tesla's domains never resolve for firmware processes
    preloads = f"{guard}:{state}/native-input.so:{state}/native-compositor.so"
    if config.get("single_display"):
        gui.update(UI_PLATFORM="M3", UI_VEHICLE="Model3", UI_TARGET="MCU")
    addresses = ["--cid", "127.0.0.100", "--ic", "127.0.0.101", "--gw", "127.0.0.102", "--ap", "127.0.0.103"]
    if config['browser']:
        for name, executable in (('spotify', 'SpotifyServer'), ('media-adapter', 'ChromiumAdapter')):
            home = state / (name + '-home')
            (home / '.Tesla/data').mkdir(parents=True, exist_ok=True, mode=0o700)
            launch(name, confined(f'/usr/tesla/UI/bin/{executable}',
                                  [ui / 'bin' / executable, '--gw', '127.0.0.102']), state,
                   dict(gui, HOME=str(home), DISPLAY=config['center_display'], LD_PRELOAD=guard))
        server = firmware / 'usr/bin/media-webapp-server'
        try:
            probe = command([server, '-h'], check=False, timeout=10)
            usage = probe.stdout + probe.stderr
        except (OSError, subprocess.SubprocessError):
            usage = ''
        argv, dropped = media_webapp_arguments(firmware, config.get('firmware_version', '2026.26.6.1'), usage)
        if dropped:
            print('media-webapp-server does not define ' + ', '.join('-' + name for name in dropped) + '; omitted', flush=True)
        # Go's own resolver would bypass the preload; cgo resolution goes through libc.
        launch('media-webapp', argv, state, dict(base, LD_PRELOAD=guard, GODEBUG='netdns=cgo'))
    odin = firmware / 'opt/odin'
    service_ui = bool(config['browser']) and (odin / 'service-ui').is_file() and (odin / 'service_ui/index.html').is_file()
    if service_ui and not all(shutil.which(tool) for tool in ('unshare', 'setpriv', 'ip')):
        print('unshare, setpriv or ip is missing; the Service Mode panel will stay unavailable.', flush=True)
        service_ui = False
    if service_ui and not port_free(8000):
        print('Port 8000 is in use; the Service Mode panel will stay unavailable.', flush=True)
        service_ui = False
    if service_ui:
        # The firmware's data-value server publishes the peer-to-peer channels the
        # Service Mode backend reads vehicle values from (/tmp/dbus_dvaccess).
        prepare_service_sockets(Path('/tmp/dbus_dvaccess'))
        dv_home = state / 'dvserver-home'
        (dv_home / '.Tesla/data').mkdir(parents=True, exist_ok=True, mode=0o700)
        launch('dv-server', confined('/usr/tesla/UI/bin/QtCarDvServer', [ui / 'bin/QtCarDvServer']), state,
               dict(gui, HOME=str(dv_home), LD_PRELOAD=guard))
        # The firmware's own Service Mode backend serves the panel on localhost:8000.
        # It keeps its own token and identity checks; none are supplied or bypassed.
        home = state / 'service-ui-home'
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        backend, relay, engine = service_ui_commands(odin, state)
        # Stands in for the vehicle's odin-engine: the task catalogue and configs from the image, no diagnostics.
        launch('odin-engine', engine, state, base)
        launch('service-ui', backend, state, dict(base, HOME=str(home)), cwd=odin)
        launch('service-ui-relay', relay, state, base)
    launch("center", confined("/usr/tesla/UI/bin/QtCar",
                     [ui / "bin/QtCar", "-graphicssystem", "raster" if config.get("single_display") else "opengl", "--touch", "mouse", "--window", "%g" % ((1 if config.get("single_display") else .6) * scale),
                      "--size", "1920x1200" if config.get("single_display") else "1200x1920", "--rotate", "0", "--rate", "60", "--fps", "5", *addresses,
                      "--ip", "127.0.0.100", "--udp", "127.0.0.100:20101", "--udphp", "127.0.0.100:31415", "--udptx", ":4321"]), state,
           dict(gui, DISPLAY=config["center_display"], HOME=str(state / "center-home"),
                TESLA_V4L2_CAMERA_SHIM="1", TESLA_ADAS_CAMERA_SIM="0", TESLA_V4L2_TRACE="0",
                TESLA_CAMERA_CONSUMER_STATUS=str(state / 'camera-consumer.json'),
                TESLA_V4L2_FRAME_FILE=str(state / 'camera/back.rgb'), TESLA_V4L2_CAMERA_FPS="24",
                LD_PRELOAD=preloads + f":{state}/native-browser-input.so:{state}/native-camera.so"))
    if config["cluster"]:
        launch("instruments", confined("/usr/tesla/UI/bin/QtCarCluster",
                              [ui / "bin/QtCarCluster", "-graphicssystem", "opengl", "--isic", "--window", "%g" % scale,
                              "--size", "1280x480", "--rotate", "0", "--rate", "48", "--fps", "5", *addresses,
                              "--ip", "127.0.0.101", "--udp", "127.0.0.101:20101", "--udphp", "127.0.0.101:31415"]), state,
               application_environment(config, 'cluster',
                   dict(gui, DISPLAY=config["cluster_display"], HOME=str(state / "cluster-home"), LD_PRELOAD=preloads)))
    started = time.time()
    positioned = False
    layout_checked = center_checked = 0
    browser_started, viz_started, link_started, media_started = set(), False, False, False
    browser_retries = {mode: 0 for mode in MODES}
    while not stopping:
        elapsed = time.time() - started
        for name in ("center", "instruments", "host-state"):
            if name in children and children[name].poll() is not None:
                tail = (state / (name + '.log')).read_text(errors='replace')[-64000:]  # a restart logs a burst of value pushes after its marker
                if is_configuration_restart(children[name].returncode, tail):
                    raise ConfigurationRestart('Applying initial firmware display settings…', changed_dvs(tail), name)
                raise RuntimeError(f"{name} exited with code {children[name].returncode}. Open Diagnostics to inspect its log.")
        if elapsed > 4 and elapsed > center_checked + 2:
            center_checked = elapsed
            positioned = arrange_center(dict(base, DISPLAY=config["center_display"])) or positioned
        if config.get("shared_desktop") and config["cluster"] and elapsed > layout_checked + 2:
            layout_checked = elapsed
            xenv = dict(base, DISPLAY=config["cluster_display"])
            arrange_cluster(xenv, scale)
        if config["cluster"] and elapsed > 4 and not link_started:
            launch("display-link", ["/usr/bin/python3", RUNTIME / "display-link.py"], state, base)
            link_started = True
        if config["browser"] and elapsed > 6:
            browser_env = dict(base, DISPLAY=config["center_display"], LD_LIBRARY_PATH=str(firmware / "usr/lib/tesla-chromium"))
            if not media_started:
                launch('chromium-media', media_browser_arguments(firmware, state, RUNTIME), state, browser_env)
                if service_ui:
                    launch('chromium-odin', odin_browser_arguments(firmware, state), state, browser_env)
                media_started = True
            for mode in MODES:
                name = 'chromium' if mode == 'browser' else 'chromium-' + mode
                if mode in browser_started and children[name].poll() is not None and browser_retries[mode] < 2:
                    browser_retries[mode] += 1
                    browser_started.remove(mode)
                if mode not in browser_started:
                    argv = browser_arguments(firmware, state, RUNTIME, mode)
                    argv[-1] = load_json(state / 'browser-page.json', {}).get('url', argv[-1])
                    launch(name, argv, state, browser_env)
                    browser_started.add(mode)
        if (config["cluster"] or config.get("single_display")) and elapsed > 12 and not viz_started:
            viz_env = dict(gui, DISPLAY=config["center_display"] if config.get("single_display") else config["cluster_display"], HOME=str(state / "apviz-home"),
                           LD_LIBRARY_PATH=f"{ui}/lib:/usr/lib/x86_64-linux-gnu:{firmware}/usr/lib",
                           LD_PRELOAD=f"{guard}:/usr/lib/x86_64-linux-gnu/libGL.so.1:/usr/lib/x86_64-linux-gnu/libGLX.so.0:/usr/lib/x86_64-linux-gnu/libOpenGL.so.0:/usr/lib/x86_64-linux-gnu/libEGL.so.1")
            viz_env = application_environment(config, 'center' if config.get('single_display') else 'cluster', viz_env)
            launch("visualization", [firmware / "usr/bin/godot", "--main-pack", ui / "assets/ap_visualization.zip",
                                     "--resolution", "%dx%d" % scaled((740, 1100) if config.get("single_display") else (600, 480), scale), "--app", ui / "lib/libApVizGodot.so", "--audio-driver", "Dummy",
                                     "--video-driver", "GLES2", "--glmsaa", "0", "--ip", "127.0.0.100" if config.get("single_display") else "127.0.0.101"], state, viz_env)
            viz_started = True
        recover_services(time.monotonic())
        components = {name: ("running" if process.poll() is None else "exited") for name, process in children.items()}
        phase = session_phase(elapsed, positioned, components)
        atomic_json(state / "status.json", {"phase": phase, "profile": config["profile"], "started_at": started,
                    "renderer": config["renderer"], "accelerated": config["accelerated"], "components": components,
                    "display_graphics": config.get('display_graphics', {}), "updated_at": time.time(),
                    "map_mounted": bool(config["maps"]), "browser_restarts": browser_retries,
                    "service_restarts": service_retries,
                    "configuration_restarts": config.get('configuration_restarts', 0)})
        time.sleep(1)


def main():
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    path = Path(sys.argv[1])
    config = json.loads(path.read_text())
    try:
        if "--session" in sys.argv: session(config)
        else: outer(config, path)
    except Exception as exc:
        traceback.print_exc()
        print(str(exc), file=sys.stderr, flush=True)
        atomic_json(Path(config["state"]) / "status.json", {
            "phase": "starting" if isinstance(exc, ConfigurationRestart) else "failed",
            "error": str(exc), "configuration_restart": isinstance(exc, ConfigurationRestart),
            "changed_dvs": getattr(exc, "names", []), "restarted_display": getattr(exc, "display", ""),
            "components": {}})
        return 1
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
