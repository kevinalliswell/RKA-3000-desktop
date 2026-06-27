from rka_desktop.comm.adapters.sim_adapters import (
    SimBalanceAdapter,
    SimMfcBusAdapter,
    SimTemperatureAdapter,
)
from rka_desktop.comm.config import default_mfc_channels


def test_temperature_pv_approaches_setpoint():
    temp = SimTemperatureAdapter(initial_c=25.0, approach=0.1)
    temp.connect()
    temp.write_sv(900.0)
    assert temp.read_sv() == 900.0
    # one step: 25 + (900 - 25) * 0.1 == 112.5
    assert temp.read_pv() == 112.5


def test_mfc_pv_follows_setpoint_and_reports_gas():
    mfc = SimMfcBusAdapter(default_mfc_channels(), approach=0.2)
    mfc.connect()
    mfc.set_flow(2, 5.0)
    pv = mfc.read_all_pv()
    # one step on address 2: 0 + (5 - 0) * 0.2 == 1.0
    assert pv[2] == 1.0
    assert mfc.gas_type(2) == "N2"
    assert set(mfc.read_all_sp().keys()) == {1, 2, 3, 4, 5, 6}


def test_balance_drifts_and_tares():
    bal = SimBalanceAdapter(initial_g=100.0, drift=0.05)
    bal.connect()
    assert bal.read_weight() == 99.95
    assert bal.tare() is True
    assert bal.read_weight() == 0.0
