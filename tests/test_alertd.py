"""Vehicle alerts: the backend request file and the alertd stand-in that serves it (no D-Bus)."""
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Linux runtime worker')
ROOT = Path(__file__).resolve().parents[1] / 'infotainment_lab'
spec = importlib.util.spec_from_file_location('alertd', ROOT / 'runtime/alertd.py')
alertd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alertd)
if os.name != 'nt':
    sys.path.insert(0, str(ROOT))
    import backend


def test_raised_alerts_are_served_then_moved_to_recent_when_cleared(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    assert backend.set_vehicle_alerts({'set': ['BMS_w001_HW_Over_Current']}) == ['BMS_w001_HW_Over_Current']
    backend.set_vehicle_alerts({'clear_all': True})
    assert backend.set_vehicle_alerts({'set': ['VCFRONT_a097', 'APP_w288_trafficLightWarning']}) == \
        ['APP_w288_trafficLightWarning', 'VCFRONT_a097']
    with pytest.raises(ValueError, match='not an alert name'):
        backend.set_vehicle_alerts({'set': ['../etc']})
    alerts = alertd.Alerts()
    requested = alertd.read_requested(tmp_path / 'session/vehicle-alerts.json')
    assert alerts.sync(requested, 1000.0) == (['VCFRONT_a097', 'APP_w288_trafficLightWarning'], [])
    name, audiences, (seconds, nanos), payload = alerts.active_alerts()[0]
    assert (name, audiences, payload) == ('VCFRONT_a097', 7, {}) and seconds == int(requested[name])

    backend.set_vehicle_alerts({'clear': ['VCFRONT_a097']})
    assert alerts.sync(alertd.read_requested(tmp_path / 'session/vehicle-alerts.json'), 1005.5) == ([], ['VCFRONT_a097'])
    assert [a[0] for a in alerts.active_alerts()] == ['APP_w288_trafficLightWarning']
    assert alerts.recent_alerts() == [('VCFRONT_a097', 7, (seconds, nanos), (1005, 500000000), {})]

    assert backend.set_vehicle_alerts({'clear_all': True}) == []
    assert alerts.sync({}, 1006.0) == ([], ['APP_w288_trafficLightWarning'])
    assert alertd.read_requested(tmp_path / 'missing.json') == {}


def test_only_names_the_image_defines_can_be_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    lib = tmp_path / 'fw/usr/tesla/UI/lib/libQtCarAlerts.so.1.0.0'
    lib.parent.mkdir(parents=True)
    lib.write_bytes(b'\0BMS_w001_HW_Over_Current\0xBMS_d001_Internal_Batt_Failure\0')
    (tmp_path / 'session').mkdir()
    (tmp_path / 'session/config.json').write_text(json.dumps({'firmware': str(tmp_path / 'fw')}))
    assert backend.image_alert_names() == {'BMS_w001_HW_Over_Current'}  # a name must start at a boundary
    assert backend.set_vehicle_alerts({'set': ['BMS_w001_HW_Over_Current']}) == ['BMS_w001_HW_Over_Current']
    with pytest.raises(ValueError, match='not defined by this firmware image'):
        backend.set_vehicle_alerts({'set': ['DI_a175']})
    assert backend.set_vehicle_alerts({'clear': ['BMS_w001_HW_Over_Current']}) == []
