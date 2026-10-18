import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
import supervisor  # noqa: E402


def test_gps_manager_listens_for_the_lab_feed(tmp_path):
    profile, argv = supervisor.gps_manager_command(tmp_path)
    assert profile == '/usr/tesla/UI/bin/QtCarGpsManager'
    assert argv[0] == tmp_path / 'bin/QtCarGpsManager'
    assert argv[argv.index('--udpgps') + 1] == ':63277'
