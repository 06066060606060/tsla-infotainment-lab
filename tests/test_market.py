from infotainment_lab import config_csv, market


def test_each_market_writes_the_same_keys_and_reads_back():
    assert set(market.EU) == set(market.NA)
    assert market.current(market.values(True)) == 'EU'
    assert market.current(market.values(False)) == 'NA'
    assert market.current({}) is None


def test_market_keys_apply_when_the_display_starts():
    # Each key must be a profile key or a car-config extra, or a restart would drop it.
    assert set(market.EU) <= config_csv.car_config()
