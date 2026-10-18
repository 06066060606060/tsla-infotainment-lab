import pytest

from infotainment_lab import config_csv, vehicle_options as vo


def test_values_round_trip_and_cover_car_config():
    values = vo.values('Model Y', 'PearlWhite', 'Crossflow19', 'TeslaAP4')
    assert vo.current(values) == ('Model Y', 'PearlWhite', 'Crossflow19', 'TeslaAP4')
    assert set(values) <= config_csv.car_config(single_display=True)  # a restart must not drop a key
    assert vo.current({}) == (None, None, None, None)


def test_default_wheels_and_profiles_use_listed_options():
    assert set(vo.DEFAULT_WHEEL.values()) <= set(vo.WHEELS)
    for model, wheel in vo.DEFAULT_WHEEL.items():
        assert vo.values(model, vo.PAINT[0], wheel, 'TeslaAP3')['VAPI_carType'] == vo.MODELS[model]['VAPI_carType']


@pytest.mark.parametrize('args', [('Model S', 'PearlWhite', 'Pinwheel18', 'TeslaAP3'), ('Model 3', 'Pink', 'Pinwheel18', 'TeslaAP3'),
                                  ('Model 3', 'PearlWhite', 'Nope', 'TeslaAP3'), ('Model 3', 'PearlWhite', 'Pinwheel18', 'AP9')])
def test_unknown_options_are_refused(args):
    with pytest.raises(ValueError):
        vo.values(*args)
