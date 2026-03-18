from rka_desktop.core.device_map import get_device_map


def test_contract_v1_device_map_contains_formal_registers():
    device_map = get_device_map("contract_v1")
    snapshot_addresses = {field.address for field in device_map.snapshot_registers}

    assert device_map.name == "contract_v1"
    assert 0x0050 in snapshot_addresses
    assert 0x0051 in snapshot_addresses
    assert 0x0060 in snapshot_addresses
    assert 0x0061 in snapshot_addresses
    assert device_map.setpoint_fields["temperature_setpoint_c"].address == 0x0002
    assert device_map.setpoint_fields["n2_setpoint_lpm"].address == 0x0030
