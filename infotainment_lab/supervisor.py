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

from core import atomic_json, load_json
from browser import MODES, browser_arguments, media_browser_arguments
from firmware_fonts import font_environment
from host_graphics import environment as graphics_environment
from display_graphics import probe_display, application_environment

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
children: dict[str, subprocess.Popen] = {}
outputs = []
stopping = False
restart_specs = {}
service_retries = {}
retry_after = {}
RECOVERABLE = {'spotify', 'media-adapter', 'media-webapp', 'chromium-media', 'display-link'}


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


def is_configuration_restart(returncode: int, tail: str) -> bool:
    return (returncode == -9 and '[CarConfigChangeProcessRestarter]' in tail
            and 'Restarting QtCar because of changed DVs:' in tail)


def request_stop(*_):
    global stopping
    stopping = True


def launch(name: str, argv: list, state: Path, env: dict):
    stream = (state / (name + ".log")).open("w")
    outputs.append(stream)
    process = subprocess.Popen([str(v) for v in argv], stdout=stream, stderr=subprocess.STDOUT,
                               env=env, cwd=env.get("TESLA_BIN", str(state)), stdin=subprocess.DEVNULL)
    children[name] = process
    if name in RECOVERABLE:
        restart_specs[name] = (argv, state, env)
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
    for name in ("native-input", "native-compositor", "native-browser-input", "native-camera"):
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
    for name, display, size in (("center-display", config["center_display"], "1920x1200" if config.get("single_display") else "720x1152"),
                                 ("cluster-display", config["cluster_display"], "1280x480")):
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
    for attempt in range(3):
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
        if previous.get('configuration_restart') and attempt < 2:
            time.sleep(1)
            continue
        raise RuntimeError(previous.get("error", "The session stopped unexpectedly. Open Diagnostics for details."))


def arrange_cluster(env):
    """A slow display must not turn a cosmetic layout update into session death."""
    try:
        windows = command(["xdotool", "search", "--onlyvisible", "--name", "^QtCarCluster$"],
                          env=env, check=False, timeout=2).stdout.split()
        for wid in windows:
            geometry = command(["xdotool", "getwindowgeometry", "--shell", wid],
                               env=env, check=False, timeout=2).stdout
            if "WIDTH=1280\n" in geometry and ("X=736\n" not in geometry or "Y=0\n" not in geometry):
                command(["xdotool", "set_window", "--overrideredirect", "1", wid], env=env, timeout=2)
                command(["xdotool", "windowmove", wid, "736", "0"], env=env, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def session(config: dict):
    state, firmware = Path(config["state"]), Path(config["firmware"])
    if config['browser']:
        check_media_ports()
    prepare_service_sockets()
    ui = firmware / "usr/tesla/UI"
    base = dict(os.environ, TESLA_NATIVE_STATE=str(state), TESLA_FIRMWARE=str(firmware),
                TESLA_NATIVE_CAR_TYPE="ModelX", TESLA_NATIVE_STATE_DELAY="0.2",
                TESLA_NATIVE_VEHICLE_PROFILE=str(RUNTIME / "vehicle-profile-model-x-mcu2.json"),
                TESLA_NATIVE_TITLE="Infotainment Lab | Center", TESLA_HOST_DISPLAY=config["display"],
                TESLA_DV_SERVICES="com.tesla.CenterDisplay" + (",com.tesla.ClusterDisplay" if config["cluster"] else ""))
    if config.get("display_backend") == "provided":
        base["TESLA_EXTERNAL_DISPLAY"] = "1"
    base["DBUS_SYSTEM_BUS_ADDRESS"] = base["DBUS_SESSION_BUS_ADDRESS"]
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
    preloads = f"{state}/native-input.so:{state}/native-compositor.so"
    if config.get("single_display"):
        gui.update(UI_PLATFORM="M3", UI_VEHICLE="Model3", UI_TARGET="MCU")
    addresses = ["--cid", "127.0.0.100", "--ic", "127.0.0.101", "--gw", "127.0.0.102", "--ap", "127.0.0.103"]
    if config['browser']:
        for name, executable in (('spotify', 'SpotifyServer'), ('media-adapter', 'ChromiumAdapter')):
            home = state / (name + '-home')
            (home / '.Tesla/data').mkdir(parents=True, exist_ok=True, mode=0o700)
            launch(name, confined(f'/usr/tesla/UI/bin/{executable}',
                                  [ui / 'bin' / executable, '--gw', '127.0.0.102']), state,
                   dict(gui, HOME=str(home), DISPLAY=config['center_display']))
        launch('media-webapp', [firmware / 'usr/bin/media-webapp-server', '-bind=127.0.0.1',
                               '-port=9000', '-secondary_port=9007', '-tertiary_port=9009',
                               '-platform_type=intel', '-chassis_type=mx',
                               '-firmware_version=' + config.get('firmware_version', '2026.26.6.1'), '-cache_exp_secs=900',
                               '-oauth_reverse_proxy=https://activate.apple.com/',
                               '-qq_music_api_reverse_proxy=https://qplaycloud.y.qq.com/rpc_proxy/fcgi-bin/music_open_api.fcg',
                               '-qq_music_report_reverse_proxy=https://stat.y.qq.com/open/fcgi-bin/music_monitor_api.fcg',
                               '-dir=' + str(firmware / 'opt/media-webapp')],
               state, base)
    launch("center", confined("/usr/tesla/UI/bin/QtCar",
                     [ui / "bin/QtCar", "-graphicssystem", "raster" if config.get("single_display") else "opengl", "--touch", "mouse", "--window", "1" if config.get("single_display") else "0.6",
                      "--size", "1920x1200" if config.get("single_display") else "1200x1920", "--rotate", "0", "--rate", "60", "--fps", "5", *addresses,
                      "--ip", "127.0.0.100", "--udp", "127.0.0.100:20101", "--udphp", "127.0.0.100:31415", "--udptx", ":4321"]), state,
           dict(gui, DISPLAY=config["center_display"], HOME=str(state / "center-home"),
                TESLA_V4L2_CAMERA_SHIM="1", TESLA_ADAS_CAMERA_SIM="0", TESLA_V4L2_TRACE="0",
                TESLA_CAMERA_CONSUMER_STATUS=str(state / 'camera-consumer.json'),
                TESLA_V4L2_FRAME_FILE=str(state / 'camera/back.rgb'), TESLA_V4L2_CAMERA_FPS="24",
                LD_PRELOAD=preloads + f":{state}/native-browser-input.so:{state}/native-camera.so"))
    if config["cluster"]:
        launch("instruments", confined("/usr/tesla/UI/bin/QtCarCluster",
                              [ui / "bin/QtCarCluster", "-graphicssystem", "opengl", "--isic", "--window", "1",
                              "--size", "1280x480", "--rotate", "0", "--rate", "48", "--fps", "5", *addresses,
                              "--ip", "127.0.0.101", "--udp", "127.0.0.101:20101", "--udphp", "127.0.0.101:31415"]), state,
               application_environment(config, 'cluster',
                   dict(gui, DISPLAY=config["cluster_display"], HOME=str(state / "cluster-home"), LD_PRELOAD=preloads)))
    started = time.time()
    positioned = False
    layout_checked = 0
    browser_started, viz_started, link_started, media_started = set(), False, False, False
    browser_retries = {mode: 0 for mode in MODES}
    while not stopping:
        elapsed = time.time() - started
        for name in ("center", "instruments", "host-state"):
            if name in children and children[name].poll() is not None:
                tail = (state / (name + '.log')).read_text(errors='replace')[-16000:]
                if is_configuration_restart(children[name].returncode, tail):
                    raise ConfigurationRestart('Applying initial firmware display settings…')
                raise RuntimeError(f"{name} exited with code {children[name].returncode}. Open Diagnostics to inspect its log.")
        if not positioned and elapsed > 4:
            xenv = dict(base, DISPLAY=config["center_display"])
            for wid in command(["xdotool", "search", "--onlyvisible", "--name", "^QtCar$"], env=xenv, check=False).stdout.split():
                geometry = command(["xdotool", "getwindowgeometry", "--shell", wid], env=xenv).stdout
                width = next((int(line[6:]) for line in geometry.splitlines() if line.startswith("WIDTH=")), 0)
                if width > 200:
                    command(["xdotool", "set_window", "--overrideredirect", "1", wid], env=xenv)
                    command(["xdotool", "windowmove", wid, "0", "0"], env=xenv)
                    positioned = True
        if config.get("shared_desktop") and config["cluster"] and elapsed > layout_checked + 2:
            layout_checked = elapsed
            xenv = dict(base, DISPLAY=config["cluster_display"])
            arrange_cluster(xenv)
        if config["cluster"] and elapsed > 4 and not link_started:
            launch("display-link", ["/usr/bin/python3", RUNTIME / "display-link.py"], state, base)
            link_started = True
        if config["browser"] and elapsed > 6:
            browser_env = dict(base, DISPLAY=config["center_display"], LD_LIBRARY_PATH=str(firmware / "usr/lib/tesla-chromium"))
            if not media_started:
                launch('chromium-media', media_browser_arguments(firmware, state, RUNTIME), state, browser_env)
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
                           LD_PRELOAD="/usr/lib/x86_64-linux-gnu/libGL.so.1:/usr/lib/x86_64-linux-gnu/libGLX.so.0:/usr/lib/x86_64-linux-gnu/libOpenGL.so.0:/usr/lib/x86_64-linux-gnu/libEGL.so.1")
            viz_env = application_environment(config, 'center' if config.get('single_display') else 'cluster', viz_env)
            launch("visualization", [firmware / "usr/bin/godot", "--main-pack", ui / "assets/ap_visualization.zip",
                                     "--resolution", "740x1100" if config.get("single_display") else "600x480", "--app", ui / "lib/libApVizGodot.so", "--audio-driver", "Dummy",
                                     "--video-driver", "GLES2", "--glmsaa", "0", "--ip", "127.0.0.100" if config.get("single_display") else "127.0.0.101"], state, viz_env)
            viz_started = True
        recover_services(time.monotonic())
        components = {name: ("running" if process.poll() is None else "exited") for name, process in children.items()}
        phase = "running" if elapsed > 15 and positioned else "starting"
        if any(value == "exited" for value in components.values()): phase = "degraded"
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
        print(str(exc), file=sys.stderr, flush=True)
        atomic_json(Path(config["state"]) / "status.json", {
            "phase": "starting" if isinstance(exc, ConfigurationRestart) else "failed",
            "error": str(exc), "configuration_restart": isinstance(exc, ConfigurationRestart), "components": {}})
        return 1
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
