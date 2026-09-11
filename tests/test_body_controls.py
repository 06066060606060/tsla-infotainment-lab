import pytest
from infotainment_lab.vehicle_services import BodyRequestRouter, VehicleServices, display_values, decode_door_mask, decode_service_request


@pytest.mark.parametrize('field,mask', [
    ('driver_door_open', 1), ('passenger_door_open', 2), ('rear_left_door_open', 4),
    ('rear_right_door_open', 8), ('front_trunk_open', 16), ('rear_trunk_open', 32)])
def test_each_closure_has_its_own_native_position_bit(field, mask):
    opened = VehicleServices().patched({field: True})
    assert display_values(opened)[field]['VAPI_doorState'] == mask
    assert display_values(opened.patched({field: False}))[field]['VAPI_doorState'] == 0


def test_combined_doors_do_not_overwrite_one_another():
    model = VehicleServices().patched({'driver_door_open': True, 'rear_trunk_open': True})
    values = display_values(model)
    assert values['driver_door_open']['VAPI_doorState'] == values['rear_trunk_open']['VAPI_doorState'] == 33


def test_native_flag_names_read_back_as_a_mask_without_accepting_unknown_names():
    assert decode_door_mask('') == 0
    assert decode_door_mask('DriverFront|TrunkRear') == 33
    assert decode_door_mask('DriverFront|DriverFront') == 1
    assert decode_door_mask('<invalid>') is None
    assert decode_door_mask('DriverFront|Unknown') is None


@pytest.mark.parametrize('mode,dark,headlights', [
    ('Off', True, False), ('Parking', True, False), ('On', False, True),
    ('Auto', False, False), ('Auto', True, True)])
def test_light_modes_and_local_darkness(mode, dark, headlights):
    model = VehicleServices.parse({'exterior_light_mode': mode, 'ambient_dark': dark})
    assert model.headlights is headlights
    native = display_values(model)['exterior_light_mode']['GUI_lightSwitchRequest']
    assert native == ('ParkingLights' if mode == 'Parking' else mode)
    assert decode_service_request('exterior_light_mode', native) == mode
    assert display_values(model)['exterior_light_mode']['VAPI_parkingLights'] is (mode == 'Parking' or headlights)


def test_legacy_headlight_settings_and_manual_override():
    assert VehicleServices.parse({'headlights': True}).exterior_light_mode == 'On'
    auto = VehicleServices.parse({'exterior_light_mode': 'Auto', 'ambient_dark': True})
    assert auto.patched({'headlights': False}).exterior_light_mode == 'Off'
    assert auto.patched({'headlights': True}).exterior_light_mode == 'On'
    assert not auto.patched({'ambient_dark': False}).headlights
    with pytest.raises(ValueError):
        auto.patched({'exterior_light_mode': 'unrecognized'})


class NativeRequests:
    def __init__(self):
        self.values = {'GUI_rearTrunkRequest': 'None', 'GUI_lockRequest': 'None'}
        self.acknowledge = True

    def DataGetValueRequest(self, name, timeout):
        return name in self.values, self.values.get(name, '')

    def DataSetValueRequest(self, name, value, timeout):
        if self.acknowledge:
            self.values[name] = value
        return self.acknowledge


def test_native_trunk_toggle_is_consumed_once_even_if_acknowledgement_fails():
    interface, router, model = NativeRequests(), BodyRequestRouter(), VehicleServices()
    router.poll(interface, model)
    interface.values['GUI_rearTrunkRequest'] = 'Pressed'
    interface.acknowledge = False
    model = router.poll(interface, model)
    assert model.rear_trunk_open
    assert router.poll(interface, model).rear_trunk_open
    interface.acknowledge = True
    model = router.poll(interface, model)
    assert model.rear_trunk_open and interface.values['GUI_rearTrunkRequest'] == 'None'
    assert router.report['GUI_rearTrunkRequest'] == 'acknowledged'
    interface.values['GUI_rearTrunkRequest'] = 'Pressed'
    assert not router.poll(interface, model).rear_trunk_open


def test_stale_and_superseded_requests_do_not_move_a_closure():
    interface, router, model = NativeRequests(), BodyRequestRouter(), VehicleServices()
    interface.values['GUI_rearTrunkRequest'] = 'Pressed'
    assert not router.poll(interface, model).rear_trunk_open
    interface.values['GUI_rearTrunkRequest'] = 'Pressed'
    assert not router.poll(interface, model, desktop_changed=True).rear_trunk_open
    assert interface.values['GUI_rearTrunkRequest'] == 'None'


def test_local_lock_requests_and_unknown_requests():
    interface, router, model = NativeRequests(), BodyRequestRouter(), VehicleServices()
    router.poll(interface, model)
    interface.values['GUI_lockRequest'] = 'Lock'
    model = router.poll(interface, model)
    assert model.locked
    interface.values['GUI_lockRequest'] = 'Unlock'
    model = router.poll(interface, model)
    assert not model.locked
    interface.values['GUI_lockRequest'] = 'not-a-command'
    assert router.poll(interface, model) == model
    assert router.report['GUI_lockRequest'] == 'unsupported-request'
