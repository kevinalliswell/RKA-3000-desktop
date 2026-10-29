import time
from dataclasses import replace
from datetime import timedelta

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
    _gw, page = _build_page()
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
    assert "通讯在线 7/8" in page.lbl_status.text()
    assert "balance" in page.lbl_status.text()


def test_diagnostics_show_fresh_time_and_stale_value_after_failure():
    gw, page = _build_page()
    page.refresh()
    assert "最近有效值" in page.diagnostics_label.text()
    assert "mfc:1" in page.diagnostics_label.text()
    from rka_desktop.comm.exceptions import DeviceCommError

    def _boom() -> float:
        raise DeviceCommError("balance unplugged")

    gw._balance.read_weight = _boom  # type: ignore[assignment]
    page.refresh()
    assert "（旧值）" in page.lbl_weight.text()
    assert "balance unplugged" in page.diagnostics_label.text()


def test_background_scan_starts_periodic_health_checks_without_blocking_ui():
    app = _app()
    gw = MultiDeviceGateway.from_config(CommConfig())
    original_read = gw._temp.read_pv
    reads = []

    def _counted_read():
        reads.append(1)
        return original_read()

    gw._temp.read_pv = _counted_read
    page = MultiDevicePage(gw, real_device=True, health_interval_ms=50)
    assert not gw.is_connected
    page.start()
    assert not page._timer.isActive()
    page.connect_and_refresh()
    assert page._worker is not None
    deadline = time.monotonic() + 2
    while page._worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert page._worker is None
    assert page._timer.isActive()
    assert page.lbl_temp_link.text() == "通讯: 在线"
    assert page.lbl_balance_link.text() == "通讯: 在线"
    assert page.mfc_table.item(0, 5).text() == "在线"
    deadline = time.monotonic() + 2
    while len(reads) < 2 and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert len(reads) >= 2
    page.stop()
    gw.close()


def test_old_success_timestamp_is_not_reported_online():
    gw, page = _build_page()
    snapshot = gw.read_multi_snapshot()
    old = {name: moment - timedelta(minutes=3) for name, moment in snapshot.last_success_at.items()}
    page = MultiDevicePage(gw, real_device=True, health_interval_ms=30_000)
    page.update_from_snapshot(replace(snapshot, last_success_at=old))
    assert page.lbl_temp_link.text() == "通讯: 状态过期"
    assert "（旧值）" in page.lbl_weight.text()


def test_failed_scan_marks_all_last_values_offline():
    gw, page = _build_page()
    page.update_from_snapshot(gw.read_multi_snapshot())
    page._scan_failed("unexpected transport error")
    assert page.lbl_temp_link.text() == "通讯: 离线"
    assert "（旧值）" in page.lbl_temp_pv.text()
    assert "unexpected transport error" in page.diagnostics_label.text()


def test_unstable_balance_reading_is_distinct_from_disconnection():
    gw, page = _build_page()
    gw._balance.read_weight = lambda: None  # type: ignore[assignment]
    page.refresh()
    assert page.lbl_balance_link.text() == "通讯: 读数待稳定"
    assert "balance" in page.lbl_status.text()
