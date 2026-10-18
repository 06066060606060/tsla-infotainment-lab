import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infotainment_lab'))
import vehicle_services  # noqa: E402


def test_the_center_route_wins_over_the_cluster_copy():
    sync = vehicle_services.PreferenceSync()
    assert sync.choose('NAV_nextTurnDirection', 'Left', 'Right') == ('center', 'Left', False)
    assert sync.choose('NAV_nextTurnDirection', 'Left', 'Left') == (None, 'Left', False)


def test_the_cluster_never_overrides_the_center_turn_list():
    sync = vehicle_services.PreferenceSync()
    assert sync.choose('GUI_turnByTurnJson', None, '{"turns": []}') == (None, None, False)


def test_navigation_is_not_a_cluster_preference():
    assert set(vehicle_services.NAVIGATION_CHANNELS).isdisjoint(vehicle_services.PREFERENCES)
