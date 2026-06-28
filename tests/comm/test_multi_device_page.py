import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from rka_desktop.comm.config import CommConfig
from rka_desktop.comm.multi_device_gateway import MultiDeviceGateway
from rka_desktop.ui.multi_device_page import MultiDevicePage


def _app():
    return QApplication.instance() or QApplication([])


def _build_page():
    _app()
    gw = MultiDeviceGateway.from_config(CommConfig(simulation_mode=True))
    gw.connect()
    return gw, MultiDevicePage(gw)


def test_page_renders_six_mfc_rows():
    _gw, page = _build_page()
    assert page.mfc_table.rowCount() == 6
    # gas labels come from the configured channels
    assert page.mfc_table.item(0, 1).text() == "H2"
    assert page.mfc_table.item(1, 1).text() == "N2"


def test_controls_drive_live_readings():
    gw, page = _build_page()
    # Operator sets a temperature target and an N2 flow, then applies.
    page.spin_temp.setValue(900.0)
    page._apply_temperature()
    page._sp_spins[2].setValue(4.0)  # address 2 == N2
    page._apply_flows()

    # Poll several times; PV should climb toward the setpoints.
    for _ in range(6):
        page.refresh()

    n2_flow = float(page.mfc_table.item(1, 4).text())  # row 1 == address 2, col 4 == 实测
    assert n2_flow > 1.0
    assert "℃" in page.lbl_temp_pv.text()
    assert page.lbl_temp_pv.text() != "实测 PV: -- ℃"


def test_degraded_status_is_surfaced():
    gw, page = _build_page()
    from rka_desktop.comm.exceptions import DeviceCommError

    def _boom() -> float:
        raise DeviceCommError("balance unplugged")

    gw._balance.read_weight = _boom  # type: ignore[assignment]
    page.refresh()
    assert "降级" in page.lbl_status.text()
    assert "balance" in page.lbl_status.text()
