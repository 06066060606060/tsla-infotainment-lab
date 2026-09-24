from infotainment_lab import config_csv as c

SAMPLE = 'Name,Value\nAPP_fsd,0\nAUDIO_a2b,@invalid\nAPTRIAL_force,false\nVAPI_speed,1.5\n'


def names(rows, **filters):
    return [r['name'] for r in rows if c.matches(r, **filters)]


def test_parse_skips_header_and_invalid():
    rows, skipped, dupes = c.parse(SAMPLE)
    assert [r['name'] for r in rows] == ['APP_fsd', 'APTRIAL_force', 'VAPI_speed']
    assert (skipped, dupes) == (['AUDIO_a2b'], [])
    assert rows[0]['original'] == '0' and rows[0]['applied'] is None  # a new key waits for Apply


def test_filters():
    rows, *_ = c.parse(SAMPLE)
    assert names(rows, query='vapi') == ['VAPI_speed']
    rows[0]['value'] = '1'
    assert names(rows, changed_only=True) == ['APP_fsd']
    assert c.pending(rows) == 3  # every imported key is pending


def test_coerce_types():
    assert c.coerce('true') is True and c.coerce('False') is False
    assert c.coerce('0') == 0 and isinstance(c.coerce('0'), int)
    assert c.coerce('1.5') == 1.5
    assert c.coerce('SupportUnknown') == 'SupportUnknown'
    assert c.coerce('nan') == 'nan'


def test_export_roundtrip():
    rows, *_ = c.parse(SAMPLE)
    assert c.parse(c.export(rows))[0] == rows


def test_duplicate_names_are_removed_last_valid_value_wins():
    rows, invalid, dupes = c.parse('Name,Value\nGUI_x,1\nGUI_y,@invalid\nGUI_x,2\nGUI_y,7\nGUI_x,@invalid\nGUI_y,7\n')
    assert [(r['name'], r['value'], r['original'], r['applied']) for r in rows] == [('GUI_x', '2', '2', None), ('GUI_y', '7', '7', None)]
    assert invalid == ['GUI_y', 'GUI_x']
    assert dupes == [('GUI_x', '1', '2'), ('GUI_y', '7', '7')]



def test_repeated_live_telemetry_is_still_never_queued():
    # Joined dumps repeat every name; a changed POWER_* reading must not become a pending write,
    # or the display power state machine is driven with another car's values.
    rows, *_ = c.parse('Name,Value\nPOWER_centerDisplayState,274\nGUI_z,1\nPOWER_centerDisplayState,321\nGUI_z,2\n')
    power, gui = rows
    assert (power['value'], power['applied']) == ('321', '321') and not c.pending([power])
    assert (gui['value'], gui['applied']) == ('2', None)

def test_names_the_app_has_defaults_for_are_compared_against_them():
    defaults = c.profile_defaults()
    assert defaults['VAPI_europeVehicle'] == 'false' and defaults['VAPI_carType'] == 'ModelX'
    rows, *_ = c.parse('Name,Value\nVAPI_europeVehicle,true\nVAPI_other,1\nVAPI_carType,ModelX\nVAPI_europeVehicle,true\n', defaults)
    europe, other, car = rows
    assert (europe['value'], europe['original'], europe['applied']) == ('true', 'false', 'false')  # differs: shown as a change
    assert (car['value'], car['original'], car['applied']) == ('ModelX', 'ModelX', 'ModelX')  # same as the default: nothing to apply
    assert (other['value'], other['original'], other['applied']) == ('1', '1', None)
    assert c.pending(rows) == 2


def test_stray_headers_are_skipped_and_only_settings_are_queued_from_an_import():
    text = 'Name,Value\nGUI_lang,en\nDISP_centerDisplayPowered,false\nName,Value\nPOWER_gwState,321\nFEATURE_x,true\n'
    rows, *_ = c.parse(text)
    assert [r['name'] for r in rows] == ['GUI_lang', 'DISP_centerDisplayPowered', 'POWER_gwState', 'FEATURE_x']  # no key called "Name"
    applied = {r['name']: r['applied'] for r in rows}
    assert applied['GUI_lang'] is None and applied['FEATURE_x'] is None  # settings wait for Apply
    assert applied['DISP_centerDisplayPowered'] == 'false' and applied['POWER_gwState'] == '321'  # hardware mirrors are not sent
    assert c.pending(rows) == 2


def test_car_config_covers_the_profile_the_known_extras_and_what_was_learned():
    names = c.car_config(['VAPI_learned'])
    assert {'VAPI_carType', 'VAPI_packConfig', 'GUI_navigationEngine', 'VAPI_learned'} <= names
    assert 'GUI_language' not in names


def test_personal_values_are_withheld_and_never_listed():
    text = ('Name,Value\nMEDIA_spotifyPassword,x\nMEDIA_spotifyUsername,x\nGUI_PINToDrivePassword,1\nBLUETOOTH_pairingPin,1\n'
            'GUI_homeLocation,x\nGUI_homePlaceHistoryItem,QUFB\nLOC_geoLat,1.5\nNAV_vehicleLongitude,2.5\nCONN_cellIMEI,1\n'
            'LINK_wifiSsid,x\nWIFI_macAddress,x\nBLUETOOTH_address,x\nDISP_centerDisplaySerialNumber,x\nGUI_currentProfileName,x\n'
            'GUI_gloveboxPassword,1\nCAPI_summonDevicePublicKey,x\nGUI_x,1\nGUI_phoneContactsDisplayFormat,FirstNameFirst\n'
            'MEDIA_spotifyTokenExpirationUTCSecs,5\nMEDIA_spotifyPassword,y\n')
    withheld = []
    rows, *_ = c.parse(text, None, withheld)
    assert [r['name'] for r in rows] == ['GUI_x', 'GUI_phoneContactsDisplayFormat', 'MEDIA_spotifyTokenExpirationUTCSecs']
    assert len(withheld) == 16 and withheld[0] == 'MEDIA_spotifyPassword'


def test_live_display_state_is_listed_but_never_queued():
    rows, *_ = c.parse('Name,Value\nGUI_centerDisplayDeviceState,Ready\nPOWER_touchState,2\nGUI_ok,1\n')
    state, power, ok = rows
    assert state['applied'] == 'Ready' and power['applied'] == '2' and ok['applied'] is None


def test_a_model3_dump_is_refused_unless_the_image_is_single_display():
    rows, *_ = c.parse('Name,Value\nVAPI_carType,Model3\nGUI_ok,1\n')
    values = {row['name']: row['value'] for row in rows}
    assert 'Model 3' in c.unsupported_car(values, single_display=False)
    assert c.unsupported_car(values, single_display=True) == ''
    assert c.unsupported_car({'VAPI_carType': 'ModelS2'}, single_display=False) == ''
