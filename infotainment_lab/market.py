"""The market switch: the car's EU or North American settings as one set of DataValue overrides.

Values follow the formats the firmware reports: alpha-2 country codes for VAPI_countryCode and
alpha-3 for GUI_navVehicleCountry, and the region as a name. The car model and trim are not part
of the switch.
"""

EU = {
    'VAPI_europeVehicle': True,
    'VAPI_countryCode': 'ES',
    'VAPI_priorCountryCode': 'ES',
    'GUI_navVehicleCountry': 'ESP',
    'VAPI_navigationMapRegion': 'EU',
    'GUI_applyEceR79': True,
    'GUI_distanceUnits': 'Kilometers',
    'GUI_temperatureUnits': 'Celsius',
    'GUI_tirePressureUnits': 'Bar',
    'GUI_language': 'English',
    'GUI_locale': 'en_GB',
    'GUI_manualLanguage': 'English',
}

NA = {
    'VAPI_europeVehicle': False,
    'VAPI_countryCode': 'US',
    'VAPI_priorCountryCode': 'US',
    'GUI_navVehicleCountry': 'USA',
    'VAPI_navigationMapRegion': 'USCanada',
    'GUI_applyEceR79': False,
    'GUI_distanceUnits': 'Miles',
    'GUI_temperatureUnits': 'Fahrenheit',
    'GUI_tirePressureUnits': 'Psi',
    'GUI_language': 'English',
    'GUI_locale': 'en_US',
    'GUI_manualLanguage': 'English',
}


def values(eu):
    """The full set for one market. Every key is written, so switching back restores the North American values."""
    return dict(EU if eu else NA)


def current(overrides):
    """'EU' or 'NA' from the saved overrides, or None when no market has been set."""
    if 'VAPI_europeVehicle' not in overrides:
        return None
    return 'EU' if overrides['VAPI_europeVehicle'] in (True, 'true') else 'NA'
