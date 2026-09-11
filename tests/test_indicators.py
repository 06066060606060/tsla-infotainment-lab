import pytest
from infotainment_lab.simulation import indicator_values


@pytest.mark.parametrize('direction,active,left,right', [
    ('off', 'Off', False, False), ('left', 'Left', True, False),
    ('right', 'Right', False, True), ('hazard', 'Both', True, True)])
def test_direction_stays_active_while_lamps_blink_together(direction, active, left, right):
    frames = [indicator_values(direction, t) for t in (0, .399, .4, .799, .8)]
    for frame in frames:
        assert frame['VAPI_turnSignalActive'] == active
        assert frame['VAPI_signalLeft'] == left
        assert frame['VAPI_signalRight'] == right
    for index in (0, 1, 4):
        assert frames[index]['LIGHT_turnIndicatorLeft'] == ('On' if left else 'Off')
        assert frames[index]['LIGHT_turnIndicatorRight'] == ('On' if right else 'Off')
    for index in (2, 3):
        assert frames[index]['LIGHT_turnIndicatorLeft'] == frames[index]['LIGHT_turnIndicatorRight'] == 'Off'


def test_cancelling_indicators_clears_direction_and_lamps_immediately():
    for moment in (0, .25, .55):
        frame = indicator_values('off', moment)
        assert frame['VAPI_turnSignalActive'] == 'Off'
        assert frame['LIGHT_turnIndicatorLeft'] == frame['LIGHT_turnIndicatorRight'] == 'Off'
