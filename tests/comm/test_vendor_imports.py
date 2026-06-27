"""The vendored driver cores must import with only their copied modules present."""


def test_azbil_public_api_imports():
    from rka_desktop.comm._vendor.azbil_mfc import (
        FULL_SCALE_COUNTS,
        MQVBusManager,
        MQVDevice,
        RS485Bus,
    )

    assert FULL_SCALE_COUNTS == 50000
    assert MQVBusManager is not None
    assert MQVDevice is not None
    assert RS485Bus is not None


def test_taie_public_api_imports():
    from rka_desktop.comm._vendor.taie_temp import (
        TaieTemperatureController,
        create_default_controller,
    )

    assert TaieTemperatureController is not None
    assert create_default_controller is not None


def test_balance_public_api_imports():
    from rka_desktop.comm._vendor.balance_serial import BalanceClient, create_protocol

    assert BalanceClient is not None
    assert create_protocol("gs_cpa") is not None
