from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rka_desktop.comm.multi_device_gateway import MultiDeviceGateway
from rka_desktop.models.entities import MultiDeviceSnapshot

# MFC table columns
_COL_ADDR = 0
_COL_GAS = 1
_COL_FULL_SCALE = 2
_COL_SETPOINT = 3
_COL_FLOW = 4
_MFC_HEADERS = ("地址", "气体", "满量程(L/min)", "设定(L/min)", "实测(L/min)")


class MultiDevicePage(QWidget):
    """Live monitor + control for the multi-device comm layer.

    Backed by a ``MultiDeviceGateway`` (simulation or real). Polls
    ``read_multi_snapshot`` on a timer and lets the operator drive the temperature
    setpoint, the six MFC flow setpoints, and the balance tare.
    """

    def __init__(self, gateway: MultiDeviceGateway, poll_interval_ms: int = 500) -> None:
        super().__init__()
        self._gateway = gateway
        self._channels = gateway.channels

        layout = QVBoxLayout(self)

        # --- Temperature group ---
        temp_box = QGroupBox("温控仪 (TAIE · Modbus RTU)")
        temp_row = QHBoxLayout(temp_box)
        self.lbl_temp_pv = QLabel("实测 PV: -- ℃")
        self.lbl_temp_sv = QLabel("设定 SV: -- ℃")
        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 1600.0)
        self.spin_temp.setDecimals(1)
        self.spin_temp.setValue(900.0)
        self.spin_temp.setSuffix(" ℃")
        self.btn_set_temp = QPushButton("设定温度")
        temp_row.addWidget(self.lbl_temp_pv)
        temp_row.addWidget(self.lbl_temp_sv)
        temp_row.addStretch()
        temp_row.addWidget(QLabel("目标:"))
        temp_row.addWidget(self.spin_temp)
        temp_row.addWidget(self.btn_set_temp)
        layout.addWidget(temp_box)

        # --- MFC group ---
        mfc_box = QGroupBox("质量流量计 (Azbil MFC × 6 · CPL RS-485)")
        mfc_layout = QVBoxLayout(mfc_box)
        self.mfc_table = QTableWidget(len(self._channels), len(_MFC_HEADERS))
        self.mfc_table.setHorizontalHeaderLabels(_MFC_HEADERS)
        self.mfc_table.verticalHeader().setVisible(False)
        self.mfc_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._sp_spins: dict[int, QDoubleSpinBox] = {}
        for row, channel in enumerate(self._channels):
            self._set_cell(row, _COL_ADDR, str(channel.address))
            self._set_cell(row, _COL_GAS, channel.gas)
            self._set_cell(row, _COL_FULL_SCALE, f"{channel.full_scale_lpm:.2f}")
            spin = QDoubleSpinBox()
            spin.setRange(0.0, channel.full_scale_lpm)
            spin.setDecimals(3)
            spin.setSingleStep(0.1)
            self._sp_spins[channel.address] = spin
            self.mfc_table.setCellWidget(row, _COL_SETPOINT, spin)
            self._set_cell(row, _COL_FLOW, "--")
        mfc_layout.addWidget(self.mfc_table)
        self.btn_apply_flows = QPushButton("下发全部流量设定")
        mfc_layout.addWidget(self.btn_apply_flows)
        layout.addWidget(mfc_box)

        # --- Balance + status ---
        bottom = QGridLayout()
        bal_box = QGroupBox("电子天平 (串口 ASCII)")
        bal_row = QHBoxLayout(bal_box)
        self.lbl_weight = QLabel("重量: -- g")
        self.btn_tare = QPushButton("去皮")
        bal_row.addWidget(self.lbl_weight)
        bal_row.addStretch()
        bal_row.addWidget(self.btn_tare)
        bottom.addWidget(bal_box, 0, 0)

        status_box = QGroupBox("链路状态")
        status_row = QHBoxLayout(status_box)
        self.lbl_status = QLabel("全部设备正常")
        status_row.addWidget(self.lbl_status)
        bottom.addWidget(status_box, 0, 1)
        layout.addLayout(bottom)

        self.btn_set_temp.clicked.connect(self._apply_temperature)
        self.btn_apply_flows.clicked.connect(self._apply_flows)
        self.btn_tare.clicked.connect(self._tare)

        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self.refresh)

    # --- lifecycle ---
    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    # --- control handlers ---
    def _apply_temperature(self) -> None:
        target = self.spin_temp.value()
        self._gateway.set_temperature_sv(target)
        self.lbl_temp_sv.setText(f"设定 SV: {target:.1f} ℃")

    def _apply_flows(self) -> None:
        for address, spin in self._sp_spins.items():
            self._gateway.set_mfc_flow(address, spin.value())

    def _tare(self) -> None:
        self._gateway.tare_balance()

    # --- polling / rendering ---
    def refresh(self) -> None:
        self.update_from_snapshot(self._gateway.read_multi_snapshot())

    def update_from_snapshot(self, snapshot: MultiDeviceSnapshot) -> None:
        self.lbl_temp_pv.setText(f"实测 PV: {snapshot.temperatures_c[0]:.2f} ℃")
        self.lbl_weight.setText(f"重量: {snapshot.weight_g:.3f} g")
        for row, channel in enumerate(self._channels):
            flow = snapshot.mfc_flows_lpm.get(channel.address, 0.0)
            self._set_cell(row, _COL_FLOW, f"{flow:.3f}")
        if snapshot.degraded_devices:
            names = ", ".join(snapshot.degraded_devices)
            self.lbl_status.setText(f"⚠ 设备降级: {names}（保持上次有效值）")
            self.lbl_status.setStyleSheet("color: #c0392b; font-weight: bold;")
        else:
            self.lbl_status.setText("全部设备正常")
            self.lbl_status.setStyleSheet("color: #27ae60;")

    # --- helpers ---
    def _set_cell(self, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(Qt.ItemIsEnabled)
        self.mfc_table.setItem(row, col, item)
