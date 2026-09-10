"""Asynchronous UI-to-worker boundary, using argument arrays on every platform."""
import json
import os
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

BACKEND = Path(__file__).resolve().parent / "backend.py"


def wsl_path_argument(path, convert):
    """Keep explicit Linux pipeline paths; convert drive and UNC selections."""
    return path if path.startswith('/') and not path.startswith('//') else convert(path)


class Results(QObject):
    finished = Signal(str, dict)


class Work(QRunnable):
    def __init__(self, action, arguments, distro, signals):
        super().__init__()
        self.action, self.arguments, self.distro, self.signals = action, arguments, distro, signals

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
            if os.name == "nt":
                def linux_path(path):
                    answer = subprocess.run(["wsl.exe", "-d", self.distro, "--", "wslpath", "-a", "-u", path], timeout=30, **options)
                    if answer.returncode: raise RuntimeError("WSL could not access the selected path.")
                    return answer.stdout.strip()
                backend = linux_path(backend)
                if "--path" in args:
                    index = args.index("--path") + 1
                    args[index] = wsl_path_argument(args[index], linux_path)
                prefix = ["wsl.exe", "-d", self.distro]
                if self.action == "setup":
                    uid = subprocess.run([*prefix, "--", "id", "-u"], timeout=30, **options).stdout.strip()
                    if not uid.isdigit(): raise RuntimeError("WSL does not have a default desktop user.")
                    prefix += ["-u", "root"]
                    args += ["--uid", uid]
                argv = [*prefix, "--", "/usr/bin/python3", backend, self.action, *args]
            elif self.action == "setup":
                args += ["--uid", str(os.getuid())]
                if os.environ.get("WSL_DISTRO_NAME"):
                    argv = ["/mnt/c/Windows/System32/wsl.exe", "-d", os.environ["WSL_DISTRO_NAME"], "-u", "root", "--",
                            "/usr/bin/python3", backend, self.action, *args]
                else:
                    argv = ["pkexec", "/usr/bin/python3", backend, self.action, *args]
            else:
                argv = ["/usr/bin/python3", backend, self.action, *args]
            completed = subprocess.run(argv, timeout=1200 if self.action in ("setup", "import") else 120, **options)
            lines = completed.stdout.replace("\x00", "").strip().splitlines()
            result = json.loads(lines[-1]) if lines else {"ok": False, "error": completed.stderr.strip()[-2000:]}
            if not isinstance(result, dict): raise ValueError("Invalid worker response")
        except FileNotFoundError:
            result = {"ok": False, "error": "The Linux runtime is not available. Install WSL2 with Debian on Windows, or Python 3 and pkexec on Linux."}
        except subprocess.TimeoutExpired:
            result = {"ok": False, "error": "The operation timed out. Open Diagnostics to inspect the session before retrying."}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        self.signals.finished.emit(self.action, result)


class Bridge(QObject):
    finished = Signal(str, dict)

    def __init__(self, distro="Debian", parent=None):
        super().__init__(parent)
        self.distro = distro
        self.pool = QThreadPool(self)
        self.results = Results(self)
        self.pending = set()
        self.results.finished.connect(self.complete)

    def complete(self, action, result):
        self.pending.discard(action)
        self.finished.emit(action, result)

    def call(self, action, *arguments):
        if action in self.pending: return False
        self.pending.add(action)
        self.pool.start(Work(action, arguments, self.distro, self.results))
        return True
