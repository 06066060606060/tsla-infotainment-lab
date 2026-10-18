"""Bus profiles: which channels the service opens and which public signal
databases describe them.

The databases are downloaded at a pinned commit into the user's data directory
on first use and never enter this repository. opendbc is MIT licensed.
tesla_can_signals has no licence file, so it is only ever fetched to the user's
own machine, like a firmware image. A decoded value still proves only what the
lab encoded: these are community reverse-engineered layouts, not vendor data.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import urllib.request

import can_database

OPENDBC = "https://raw.githubusercontent.com/commaai/opendbc/28015820859e8ba4c53c11d1668a52068a5e5039/opendbc/dbc/"
TALAS9 = "https://raw.githubusercontent.com/talas9/tesla_can_signals/847fe2e0d9c921a8a8748f3b3cb80e9d235f449a/ModelS/"

# channel -> database files, in load order. A later file wins on a shared identifier
# but keeps an earlier cycle time: opendbc has fuller layouts, tesla_can_signals the periods.
PROFILES = {
    "lab": {"channels": ("veh", "ch", "party"), "files": {},
            "description": "The lab's own LAB_* frames."},
    "model3": {"channels": ("veh", "ch", "party"),
               "files": {"veh": (OPENDBC + "tesla_model3_vehicle.dbc",),
                         "party": (OPENDBC + "tesla_model3_party.dbc",)},
               "description": "Model 3 vehicle and party buses from opendbc; LAB_* frames fill the rest."},
    "models": {"channels": ("ch", "pt", "bdy", "bft", "obd", "ethbus"),
               "files": {"ch": (TALAS9 + "ModelS_CH.compact.json.json", OPENDBC + "tesla_can.dbc"),
                         "pt": (TALAS9 + "ModelS_PT.compact.json.json", OPENDBC + "tesla_powertrain.dbc"),
                         "bdy": (TALAS9 + "ModelS_BDY.compact.json.json",),
                         "bft": (TALAS9 + "ModelS_BFT.compact.json.json",),
                         "obd": (TALAS9 + "ModelS_OBDII.compact.json.json",),
                         "ethbus": (TALAS9 + "ModelS_ETH.compact.json.json",)},
               "description": "Model S/X buses from opendbc and tesla_can_signals, including the "
                             "gateway's ETH bus towards the MCU."},
}
MAX_CHANNELS = max(len(profile["channels"]) for profile in PROFILES.values())


def profile(name: str) -> dict:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown CAN profile {name!r}. Choose {', '.join(PROFILES)}.") from exc


def local_path(url: str, root: Path) -> Path:
    # The pinned commit is part of the URL, so a new pin never reuses an old file.
    source, commit = url.split("/")[4], url.split("/")[5]
    return Path(root) / source / commit / url.rsplit("/", 1)[1]


def fetch(name: str, root: Path, opener=urllib.request.urlopen) -> list[str]:
    """Download the profile's databases once. Returns the files it fetched."""
    fetched = []
    for urls in profile(name)["files"].values():
        for url in urls:
            path = local_path(url, root)
            if path.exists():
                continue
            with opener(url, timeout=60) as response:
                body = response.read()
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".part")
            temporary.write_bytes(body)
            temporary.replace(path)
            fetched.append(str(path))
    return fetched


def definitions(name: str, root: Path) -> tuple:
    """The profile's frame table: LAB_* frames on its channels, then its databases."""
    spec = profile(name)
    table = {key: m for key, m in can_database.index(can_database.MESSAGES).items()
             if m.channel in spec["channels"]}
    for channel, urls in spec["files"].items():
        for url in urls:
            path = local_path(url, root)
            if not path.exists():
                raise RuntimeError(f"{path.name} has not been downloaded. Start the service from the panel to fetch it.")
            for key, message in can_database.index(can_database.load(path, channel, period_ms=100)).items():
                earlier = table.get(key)
                if earlier and path.suffix == ".dbc" and not earlier.name.startswith("LAB_"):
                    message = replace(message, period_ms=earlier.period_ms)
                table[key] = message
    return tuple(table.values())
