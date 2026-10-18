"""The Vehicle selector: model, paint, wheels and driver-assist hardware as one set of car-config overrides.

Names are the enum labels in the 2026.26.6.1 ICE image's `libSharedProto` (ExteriorColor, WheelType,
DriverAssist). Model 3 and Model Y follow their lab profiles in runtime/vehicle-profile-model-*-mcu2.json.
"""

MODELS = {
    'Model 3': {'VAPI_carType': 'Model3', 'VAPI_chassisType': '3', 'VAPI_restraintsHardwareType': 'NAM3',
                'GUI_carTypeFullName': 'Model 3'},
    'Model Y': {'VAPI_carType': 'ModelY', 'VAPI_chassisType': 'Y', 'VAPI_restraintsHardwareType': 'NAMY',
                'GUI_carTypeFullName': 'Model Y'},
}
DEFAULT_WHEEL = {'Model 3': 'Pinwheel18', 'Model Y': 'Crossflow19'}

PAINT = ('PearlWhite', 'SolidBlack', 'DiamondBlack', 'MidnightSilver', 'SilverMetallic', 'Quicksilver',
         'StealthGrey', 'DeepBlue', 'MarineBlue', 'CoastalBlue', 'GlacierBlue', 'FrostBlue', 'UltraRed',
         'RedMulticoat', 'MidnightCherryRed', 'SilkroadSilver')
WHEELS = ('Pinwheel18', 'Pinwheel18CapKit', 'PinwheelRefresh18', 'Glider18', 'Apollo19', 'Apollo19CapKit',
          'Apollo19MetallicShadow', 'Stiletto19', 'StilettoRefresh19', 'Gemini19Square', 'Gemini19Staggered',
          'ZeroG19Gunpowder', 'Helix19', 'Crossflow19', 'Wishbone19Staggered', 'MachinaV219', 'Stiletto20',
          'Stiletto20DarkStaggered', 'Stiletto20DarkSquare', 'Induction20Black', 'ZeroG20Gunpowder',
          'Wishbone20Staggered', 'HelixV220', 'HelixV220Dark', 'Uberhelix20', 'UberTurbine20Gunpowder',
          'UberTurbine21Black')
# VAPI_driverAssist label -> what it is. GTW_dasHw is left alone: the firmware cannot supply it (see the changelog).
AUTOPILOT = {'MonoCam': 'HW1 (Mobileye)', 'ParkerPascal': 'HW2', 'ParkerPascal2_5': 'HW2.5',
             'TeslaAP3': 'HW3', 'TeslaAP4': 'HW4'}


def values(model, paint, wheel, autopilot):
    """Every key is written, so switching back restores the previous model's identity."""
    if model not in MODELS or paint not in PAINT or wheel not in WHEELS or autopilot not in AUTOPILOT:
        raise ValueError('Unknown vehicle option.')
    return {**MODELS[model], 'VAPI_exteriorColor': paint, 'VAPI_wheelType': wheel, 'VAPI_driverAssist': autopilot}


def current(overrides):
    """(model, paint, wheel, autopilot) from the saved overrides; None where nothing is saved."""
    model = next((name for name, keys in MODELS.items() if keys['VAPI_carType'] == overrides.get('VAPI_carType')), None)
    return (model, overrides.get('VAPI_exteriorColor'), overrides.get('VAPI_wheelType'), overrides.get('VAPI_driverAssist'))
