from infotainment_lab.places import PLACES
from infotainment_lab.vehicle_services import FIELD_SPECS


def test_places_fit_the_latitude_and_longitude_fields():
    lat, lon = FIELD_SPECS['latitude_deg'], FIELD_SPECS['longitude_deg']
    assert {region for region, *_ in PLACES} == {'EU', 'US'}
    for _, _, la, lo in PLACES:
        assert lat['min'] <= la <= lat['max'] and lon['min'] <= lo <= lon['max']
