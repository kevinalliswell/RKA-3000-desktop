"""Manual device access for the device page: status, MFC set-points, temperature SV, tare.

Every write is an operator-triggered, confirmed action and is refused while an experiment is
active (the run owns the devices; manual gas during a run goes through the runner's manual mode).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rka_desktop.application.ports import AuditStore, ExperimentGateway
from rka_desktop.domain.control import ConfirmationRequired
from rka_desktop.domain.recipe import MAX_FLOW_LPM, MAX_TARGET_TEMP_C


class DeviceBusy(ValueError):
    pass


class DeviceUnsupported(ValueError):
    pass


class DeviceService:
    def __init__(self, gateway: ExperimentGateway, audit: AuditStore, *, run_active: Callable[[], bool],
                 ensure_connected: Callable[[], bool]) -> None:
        self._gateway = gateway
        self._audit = audit
        self._run_active = run_active
        self._ensure_connected = ensure_connected

    def describe(self) -> dict[str, Any]:
        return {**self._gateway.describe(), "capabilities": self._gateway.capabilities.__dict__}

    def status(self) -> dict[str, Any]:
        if not self._gateway.capabilities.multi_device_status:
            return {"supported": False, "description": self.describe()}
        if not self._ensure_connected():
            return {"supported": True, "connected": False, "description": self.describe()}
        multi = self._gateway.read_multi_snapshot()
        assert multi is not None
        return {
            "supported": True, "connected": True,
            "temperature_c": multi.temperatures_c[0],
            "mfc": [{"address": address, "flow_lpm": flow, "setpoint_lpm": multi.mfc_setpoints_lpm.get(address, 0.0)}
                    for address, flow in sorted(multi.mfc_flows_lpm.items())],
            "weight_g": multi.weight_g,
            "degraded_devices": list(multi.degraded_devices),
            "description": self.describe(),
        }

    def _guard(self, confirmed: bool, what: str) -> None:
        if self._run_active():
            raise DeviceBusy("实验运行中，设备由实验流程控制；手动配气请在运行页切换到手动模式")
        if not confirmed:
            raise ConfirmationRequired(f"{what}需要确认")
        if not self._ensure_connected():
            raise DeviceBusy("设备未连接")

    def set_mfc_setpoints(self, setpoints: Any, *, confirmed: bool) -> dict[str, Any]:
        if not isinstance(setpoints, list) or not setpoints:
            raise ValueError("setpoints 必须是非空数组")
        parsed: list[tuple[int, float]] = []
        for item in setpoints:
            if not isinstance(item, dict) or type(item.get("address")) is not int:
                raise ValueError("每个设定必须包含整数 address")
            lpm = item.get("lpm")
            if isinstance(lpm, bool) or not isinstance(lpm, (int, float)) or not 0 <= lpm <= MAX_FLOW_LPM:
                raise ValueError(f"流量须在 0 到 {MAX_FLOW_LPM:g} L/min 之间")
            parsed.append((item["address"], float(lpm)))
        if not self._gateway.capabilities.multi_device_status:
            raise DeviceUnsupported("当前设备通路不支持按通道设定流量")
        self._guard(confirmed, "下发流量设定")
        for address, lpm in parsed:
            self._gateway.set_mfc_flow(address, lpm)
        self._audit.log_action("operator", "MANUAL_MFC_SET", ",".join(f"{a}={v:g}" for a, v in parsed))
        return self.status()

    def set_temperature(self, celsius: Any, *, confirmed: bool) -> dict[str, Any]:
        if isinstance(celsius, bool) or not isinstance(celsius, (int, float)) or not 0 <= celsius <= MAX_TARGET_TEMP_C:
            raise ValueError(f"温度设定须在 0 到 {MAX_TARGET_TEMP_C:g} ℃ 之间")
        if not self._gateway.capabilities.temperature_setpoint:
            raise DeviceUnsupported("当前设备通路不支持温度设定")
        self._guard(confirmed, "下发温度设定")
        self._gateway.set_temperature_sv(float(celsius))
        self._audit.log_action("operator", "MANUAL_TEMPERATURE_SET", f"{float(celsius):g}")
        return self.status()

    def tare(self, *, confirmed: bool) -> dict[str, Any]:
        if not self._gateway.capabilities.balance_tare:
            raise DeviceUnsupported("当前设备通路不支持天平去皮")
        self._guard(confirmed, "天平去皮")
        ok = self._gateway.tare_balance()
        self._audit.log_action("operator", "BALANCE_TARE", "ok" if ok else "no-ack")
        return {"ok": bool(ok), **self.status()}
