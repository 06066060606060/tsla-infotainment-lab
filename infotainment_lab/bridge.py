"""Asynchronous UI-to-worker boundary, using argument arrays on every platform."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

BACKEND = Path(__file__).resolve().parent / "backend.py"


def wsl_path_argument(path, convert):
    """Keep explicit Linux pipeline paths; convert drive and UNC selections."""
    return path if path.startswith('/') and not path.startswith('//') else convert(path)


class Results(QObject):
    finished = Signal(str, dict)


# Short, frequent actions reuse a warm `backend.py serve` process instead of paying
# the interpreter start and imports (~75 ms) on every call. Long ones stay one-shot.
FAST = frozenset(('status', 'preview', 'camera-preview', 'debug', 'can', 'can-status', 'controls',
                  'steering', 'vehicle-services', 'vehicle-alerts', 'config-values', 'replay'))
IDLE, IDLE_LIMIT, IDLE_LOCK = [], 4, threading.Lock()


def warm_call(runner, tail, timeout, **options):
    """One reply line from an idle worker for this runner (or a new one); a worker that died while idle is retried once."""
    for attempt in range(2):
        with IDLE_LOCK:
            proc = next((p for p in IDLE if p.runner == runner and p.poll() is None), None)
            if proc: IDLE.remove(proc)
        fresh = proc is None
        if fresh:
            proc = subprocess.Popen([*runner, 'serve'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace', **options)
            proc.runner = runner
        timer = threading.Timer(timeout, proc.kill)
        timer.start()
        try:
            proc.stdin.write(json.dumps(tail) + '\n')
            proc.stdin.flush()
            line = proc.stdout.readline().replace('\x00', '').strip()
        except OSError:
            line = ''
        finally:
            timer.cancel()
        if line:
            with IDLE_LOCK:
                if len(IDLE) < IDLE_LIMIT: IDLE.append(proc); proc = None
            if proc: proc.kill()
            return line
        proc.kill()
        if fresh: break  # a new process that dies without answering was killed by the timer or is broken
    raise subprocess.TimeoutExpired(runner, timeout)


class Work(QRunnable):
    def __init__(self, action, arguments, distro, signals, epoch=0):
        super().__init__()
        self.action, self.arguments, self.distro, self.signals = action, arguments, distro, signals
        self.epoch = epoch

    def run(self):
        env = dict(os.environ)
        if getattr(sys, "frozen", False):
            if "LD_LIBRARY_PATH_ORIG" in env: env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
            else: env.pop("LD_LIBRARY_PATH", None)
        options = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if os.name == "nt": options["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            args = list(self.arguments)
            backend = str(BACKEND)
            runner = None
            if os.name == "nt":
                def linux_path(path):
                    answer = subprocess.run(["wsl.exe", "-d", self.distro, "--", "wslpath", "-a", "-u", path], timeout=30, **options)
                    converted = answer.stdout.replace("\x00", "").strip()
                    if answer.returncode or not converted:
                        detail = answer.stderr.replace("\x00", "").strip() or converted or "wslpath returned no path"
                        raise RuntimeError(
                            f"Cannot translate path for WSL ({self.distro}): {path}\n{detail[-1500:]}"
                        )
                    return converted
                backend = linux_path(backend)
                for flag in ('--path', '--vm-directory'):
                    if flag in args:
                        index = args.index(flag) + 1
                        args[index] = wsl_path_argument(args[index], linux_path)
                prefix = ["wsl.exe", "-d", self.distro]
                if self.action == "setup":
                    uid = subprocess.run([*prefix, "--", "id", "-u"], timeout=30, **options).stdout.strip()
                    if not uid.isdigit(): raise RuntimeError("WSL does not have a default desktop user.")
                    prefix += ["-u", "root"]
                    args += ["--uid", uid]
                runner = [*prefix, "--", "/usr/bin/python3", backend]
                argv = [*runner, self.action, *args]
            elif self.action == "setup":
                args += ["--uid", str(os.getuid())]
                if os.environ.get("WSL_DISTRO_NAME"):
                    argv = ["/mnt/c/Windows/System32/wsl.exe", "-d", os.environ["WSL_DISTRO_NAME"], "-u", "root", "--",
                            "/usr/bin/python3", backend, self.action, *args]
                else:
                    argv = ["pkexec", "/usr/bin/python3", backend, self.action, *args]
            else:
                runner = ["/usr/bin/python3", backend]
                argv = [*runner, self.action, *args]
            if runner and self.action in FAST:
                result = json.loads(warm_call(runner, [self.action, *args], 120, env=env,
                                              **({"creationflags": options["creationflags"]} if "creationflags" in options else {})))
            else:
                completed = subprocess.run(argv, timeout=2400 if self.action == 'setup' else 1200 if self.action in ("import", "qemu-check") else 120, **options)
                lines = completed.stdout.replace("\x00", "").strip().splitlines()
                result = json.loads(lines[-1]) if lines else {"ok": False, "error": completed.stderr.strip()[-2000:]}
            if not isinstance(result, dict): raise ValueError("Invalid worker response")
        except FileNotFoundError:
            result = {"ok": False, "error": "The Linux runtime is not available. Install WSL2 with Debian on Windows, or Python 3 and pkexec on Linux."}
        except subprocess.TimeoutExpired:
            result = {"ok": False, "error": "The operation timed out. Open Diagnostics to inspect the session before retrying."}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        result['_bridge_epoch'] = self.epoch
        self.signals.finished.emit(self.action, result)


class Bridge(QObject):
    finished = Signal(str, dict)

    def __init__(self, distro="Debian", parent=None):
        super().__init__(parent)
        self.distro = distro
        self.pool = QThreadPool(self)
        self.results = Results(self)
        self.pending = set()
        self.engine, self.vm_directory, self.epoch = 'native', '', 0
        self.results.finished.connect(self.complete)

    def complete(self, action, result):
        epoch = result.pop('_bridge_epoch', 0)
        if epoch != self.epoch:
            return
        self.pending.discard(action)
        self.finished.emit(action, result)

    def configure(self, engine, directory=''):
        if engine not in ('native', 'qemu'):
            raise ValueError('Choose native or QEMU mode.')
        if (engine, directory) != (self.engine, self.vm_directory):
            self.engine, self.vm_directory = engine, directory
            self.epoch += 1
            self.pending.clear()

    # Independent, short requests to the CAN service. Dropping one while another
    # is in flight lost the unlock challenge whenever a refresh was running.
    CONCURRENT = frozenset(('can', 'can-status'))

    def call(self, action, *arguments):
        if action in self.pending and action not in self.CONCURRENT: return False
        self.pending.add(action)
        arguments = [*arguments, '--engine', self.engine]
        if self.vm_directory:
            arguments += ['--vm-directory', self.vm_directory]
        self.pool.start(Work(action, arguments, self.distro, self.results, self.epoch))
        return True
