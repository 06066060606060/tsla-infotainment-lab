import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
import backend


def make_map(tmp_path, version, engine="TeslaMaps"):
    src = tmp_path / "src"
    src.mkdir()
    # The EU dump's VERSION is over 200 bytes: a release line, then tile builds.
    (src / "VERSION").write_text(version + "\n" + "valhalla_tiles_build\n" * 40)
    (src / "NAVENGINE").write_text(engine + "\n")
    image = tmp_path / f"{version}.ssq"
    subprocess.run(["mksquashfs", str(src), str(image), "-noappend", "-quiet"], check=True)
    return image


def test_eu_map_imports_with_europe_variant(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "DATA", tmp_path)
    item = backend.import_image(str(make_map(tmp_path, "EU-2026.8-15742")))
    assert (item["version"], item["variant"], item["kind"]) == ("EU-2026.8-15742", "Europe", "map")


def test_na_map_still_imports(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "DATA", tmp_path)
    item = backend.import_image(str(make_map(tmp_path, "NA-2022.28-14046")))
    assert item["variant"] == "North America"


def test_unknown_map_region_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "DATA", tmp_path)
    with pytest.raises(ValueError, match="TeslaMaps"):
        backend.import_image(str(make_map(tmp_path, "XX-2026.8-1")))
