"""Small, platform-independent helpers shared by the GUI and Linux worker."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

PACKAGE = Path(__file__).resolve().parent


def profiles() -> list[dict]:
    return json.loads((PACKAGE / "profiles.json").read_text(encoding="utf-8"))["profiles"]


def profile_for(version: str, variant: str) -> dict | None:
    return next((p for p in profiles() if p["version"] == version and p["variant"] == variant), None)


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_image(path: Path) -> Path:
    path = path.expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("Choose a firmware or map file, not a directory.")
    with path.open("rb") as stream:
        if stream.read(4) != b"hsqs":
            raise ValueError("This file is not a supported SquashFS image. Compressed update containers must be unpacked separately.")
    return path


def safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{16}", value):
        raise ValueError("Invalid library item identifier.")
    return value


def size_label(value: int) -> str:
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or suffix == "TiB":
            return f"{value:.1f} {suffix}"
        value /= 1024
    return str(value)


def public_report(status: dict, environment: dict) -> dict:
    """Export an allowlist: never include profiles, raw logs, paths or URLs."""
    return {
        "application": "tsla-infotainment-lab", "version": "0.4.2",
        "session": {k: status.get(k) for k in ("phase", "profile", "components", "renderer", "accelerated", "started_at")},
        "environment": {k: environment.get(k) for k in ("platform", "architecture", "missing", "display_available", "audio_available", "systemd_available")},
    }
