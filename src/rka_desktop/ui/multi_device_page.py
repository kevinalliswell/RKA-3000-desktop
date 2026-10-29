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
    QTabWidget,
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
    """Diagnostic monitor. Real-device reads are manual and writes stay disabled."""

    def __init__(
        self, gateway: MultiDeviceGateway | None, poll_interval_ms: int = 500,
        unavailable_reason: str = "未配置真实设备只读诊断；请设置 DEVICE_PROFILE_PATH。",
        manual_only: bool = False,
    ) -> None:
        super().__init__()
        self._gateway = gateway
        self._channels = gateway.channels if gateway is not None else ()
        self._unavailable_reason = unavailable_reason
        self._manual_only = manual_only

        layout = QVBoxLayout(self)
        self.lbl_control_scope = QLabel(
            "设备诊断仅显示采集状态。原型中的 7 气体 / 6 MFC 控制、上限策略和类型互锁"
            "尚未完成真机映射与安全验证。"
        )
        self.lbl_control_scope.setWordWrap(True)
        layout.addWidget(self.lbl_control_scope)
        self.sections = QTabWidget()
        overview_page = QWidget()
        overview_layout = QVBoxLayout(overview_page)
        channels_page = QWidget()
        channels_layout = QVBoxLayout(channels_page)

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
        overview_layout.addWidget(temp_box)

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
        channels_layout.addWidget(mfc_box)

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
        overview_layout.addLayout(bottom)
        overview_layout.addStretch()

        topology_page = QWidget()
        topology_layout = QVBoxLayout(topology_page)
        topology_note = QLabel(
            "本机设备链路：温控仪（Modbus RTU）· MFC 总线（CPL RS-485）· "
            "电子天平（串口 ASCII）。当前通道表来自所选配置，"
            "与更新版原型的 N₂/Ar 共用通道定义尚未完成真机一致性核对。"
        )
        topology_note.setWordWrap(True)
        topology_layout.addWidget(topology_note)
        topology_layout.addStretch()

        diagnostics_page = QWidget()
        diagnostics_layout = QVBoxLayout(diagnostics_page)
        self.diagnostics_label = QLabel("等待设备快照")
        self.diagnostics_label.setWordWrap(True)
        diagnostics_layout.addWidget(self.diagnostics_label)
        self.btn_refresh_diagnostics = QPushButton("重新读取快照")
        diagnostics_layout.addWidget(self.btn_refresh_diagnostics)
        diagnostics_layout.addStretch()
        self.btn_refresh_diagnostics.clicked.connect(self.connect_and_refresh)

        self.sections.addTab(overview_page, "设备概览")
        self.sections.addTab(topology_page, "连接拓扑")
        self.sections.addTab(channels_page, "MFC 通道与量程")
        self.sections.addTab(diagnostics_page, "通信诊断")
        layout.addWidget(self.sections)

        self.btn_set_temp.clicked.connect(self._apply_temperature)
        self.btn_apply_flows.clicked.connect(self._apply_flows)
        self.btn_tare.clicked.connect(self._tare)

        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self.refresh)

    def set_diagnostics_only(self) -> None:
        """Keep the diagnostics destination read-only until control mapping is verified."""
        self.spin_temp.setEnabled(False)
        self.btn_set_temp.setEnabled(False)
        self.btn_apply_flows.setEnabled(False)
        self.btn_tare.setEnabled(False)
        for spin in self._sp_spins.values():
            spin.setEnabled(False)

    # --- lifecycle ---
    def start(self) -> None:
        if self._gateway is not None and self._gateway.is_connected and not self._manual_only:
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
        if self._gateway is None:
            self.lbl_status.setText(self._unavailable_reason)
            self.diagnostics_label.setText(self._unavailable_reason)
            return
        if not self._gateway.is_connected:
            self.lbl_status.setText("只读诊断未连接")
            self.diagnostics_label.setText("点击“重新读取快照”后连接现场设备；不会发送写入指令。")
            return
        self.update_from_snapshot(self._gateway.read_multi_snapshot())

    def connect_and_refresh(self) -> None:
        if self._gateway is None:
            self.refresh()
            return
        try:
            if self._manual_only or not self._gateway.is_connected:
                self._gateway.connect()
            self.refresh()
            self.start()
        except Exception as exc:  # noqa: BLE001 - report connection faults on diagnostics page
            self._timer.stop()
            self.lbl_status.setText("⚠ 只读诊断连接失败")
            self.diagnostics_label.setText(str(exc))

    def update_from_snapshot(self, snapshot: MultiDeviceSnapshot) -> None:
        temp = snapshot.temperatures_c[0]
        self.lbl_temp_pv.setText(
            f"实测 PV: {temp:.2f} ℃{'（旧值）' if 'temp' in snapshot.degraded_devices else ''}"
            if temp is not None else "实测 PV: -- ℃"
        )
        self.lbl_weight.setText(
            f"重量: {snapshot.weight_g:.3f} g{'（旧值）' if 'balance' in snapshot.degraded_devices else ''}"
            if snapshot.weight_g is not None else "重量: -- g"
        )
        for row, channel in enumerate(self._channels):
            flow = snapshot.mfc_flows_lpm.get(channel.address)
            suffix = " (旧值)" if f"mfc:{channel.address}" in snapshot.degraded_devices else ""
            self._set_cell(row, _COL_FLOW, f"{flow:.3f}{suffix}" if flow is not None else "--")
        if snapshot.degraded_devices:
            names = ", ".join(snapshot.degraded_devices)
            self.lbl_status.setText(f"⚠ 设备降级: {names}")
            self.lbl_status.setStyleSheet("color: #c0392b; font-weight: bold;")
        else:
            self.lbl_status.setText("全部设备正常")
            self.lbl_status.setStyleSheet("color: #27ae60;")
        device_names = ("temp", *(f"mfc:{channel.address}" for channel in self._channels), "balance")
        details = "\n".join(
            f"{name}：最近有效值 "
            f"{snapshot.last_success_at[name].astimezone().strftime('%H:%M:%S') if name in snapshot.last_success_at else '从未收到'}"
            f"；{snapshot.errors.get(name, '正常') if name in snapshot.degraded_devices else '正常'}"
            for name in device_names
        )
        self.diagnostics_label.setText(details)

    # --- helpers ---
    def _set_cell(self, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(Qt.ItemIsEnabled)
        self.mfc_table.setItem(row, col, item)
