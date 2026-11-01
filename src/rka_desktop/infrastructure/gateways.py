"""Implementations of the application ``ExperimentGateway`` port.

* ``PlcModbusGateway`` wraps the pre-migration ``ModbusRtuClient`` (contract_v1 register map):
  alarm/interlock/run-control words, per-step temperature and gas set-points via the PLC.
* ``MultiDeviceExperimentGateway`` wraps ``MultiDeviceGateway`` (TAIE + Azbil MFC bus + balance):
  gas via the MFC channels mapped by gas type, the temperature profile downloaded once to the
  TAIE program-curve registers, no PLC words (alarm/interlock stay 0).
"""

from __future__ import annotations

import logging
import math
from typing import Any

from rka_desktop.application.ports import GatewayCapabilities, RunControlFeedback
from rka_desktop.domain.entities import DeviceSnapshot, MultiDeviceSnapshot
from rka_desktop.domain.recipe import RecipeStep
from rka_desktop.infrastructure.comm.config import CommConfig, MfcChannelConfig
from rka_desktop.infrastructure.comm.exceptions import DeviceCommError
from rka_desktop.infrastructure.comm.multi_device_gateway import MultiDeviceGateway
from rka_desktop.infrastructure.comm.plc.modbus_client import ModbusRtuClient

logger = logging.getLogger(__name__)

TAIE_PROGRAM_SEGMENTS = 8
TAIE_MAX_TIME_RAW = 9999


class TemperatureProgramError(RuntimeError):
    pass


class PlcModbusGateway:
    capabilities = GatewayCapabilities(
        temperature_program=False, temperature_setpoint=True, run_control_word=True,
        alarm_words=True, multi_device_status=False, balance_tare=False,
    )

    def __init__(self, client: ModbusRtuClient) -> None:
        self._client = client
        self._last_gas: dict[str, float] = {"n2_lpm": 0.0, "h2_lpm": 0.0, "co_lpm": 0.0}
        self._last_temp: dict[str, float] = {"temperature_c": 0.0, "ramp_rate_cpm": 0.0}

    @property
    def client(self) -> ModbusRtuClient:
        return self._client

    def connect(self) -> bool:
        return self._client.connect()

    def close(self) -> None:
        self._client.close()

    def read_snapshot(self) -> DeviceSnapshot:
        return self._client.read_snapshot()

    def degraded_devices(self) -> tuple[str, ...]:
        return ()

    def _write_all(self) -> dict[str, float]:
        return self._client.apply_setpoints(
            temperature_c=self._last_temp["temperature_c"], ramp_rate_cpm=self._last_temp["ramp_rate_cpm"],
            n2_lpm=self._last_gas["n2_lpm"], h2_lpm=self._last_gas["h2_lpm"], co_lpm=self._last_gas["co_lpm"],
        )

    def apply_gas_setpoints(self, *, n2_lpm: float, h2_lpm: float, co_lpm: float) -> dict[str, float]:
        # The PLC map writes temperature and gas in one block; keep the last temperature values.
        self._last_gas = {"n2_lpm": float(n2_lpm), "h2_lpm": float(h2_lpm), "co_lpm": float(co_lpm)}
        return self._write_all()

    def apply_temperature_setpoint(self, *, temperature_c: float, ramp_rate_cpm: float) -> None:
        self._last_temp = {"temperature_c": float(temperature_c), "ramp_rate_cpm": float(ramp_rate_cpm)}
        self._write_all()

    def download_temperature_program(self, steps: list[RecipeStep]) -> dict[str, Any]:
        raise TemperatureProgramError("PLC 寄存器表没有温度程序段，无法下发温度程序")

    def issue_run_control(self, command: str) -> int:
        return self._client.issue_run_control(command)

    def evaluate_run_control_feedback(self, feedback_word: int) -> RunControlFeedback:
        status = self._client.evaluate_run_control_feedback(feedback_word)
        return RunControlFeedback(status.command, status.expected_word, status.feedback_word, status.is_consistent, status.message)

    def read_multi_snapshot(self) -> MultiDeviceSnapshot | None:
        return None

    def set_mfc_flow(self, address: int, lpm: float) -> None:
        raise DeviceCommError("PLC 通路不支持按 MFC 地址单独设定流量")

    def set_temperature_sv(self, celsius: float) -> None:
        self.apply_temperature_setpoint(temperature_c=celsius, ramp_rate_cpm=self._last_temp["ramp_rate_cpm"])

    def tare_balance(self) -> bool:
        raise DeviceCommError("PLC 通路不支持天平去皮")

    def describe(self) -> dict[str, Any]:
        return {
            "backend": "plc_modbus", "simulation": self._client.simulation_mode,
            "summary": f"PLC Modbus RTU {self._client.serial_port}@{self._client.baudrate} unit {self._client.unit_id}"
            if not self._client.simulation_mode else "PLC Modbus RTU（仿真）",
            "devices": [{"name": "plc", "label": "PLC 主控", "port": self._client.serial_port}],
            "mfc_channels": [],
        }


def build_taie_segments(steps: list[RecipeStep], *, time_unit: str = "min") -> list[dict[str, Any]]:
    """Map recipe steps to TAIE program-curve segments (ramp segment + hold segment per step).

    A TAIE segment is (target SV, time). The controller ramps from the previous SV to the
    segment SV over the segment time, so each recipe step becomes a ramp segment
    (time = |ΔT| / ramp rate) followed by a hold segment at the same SV. The time unit of the
    ``TMx`` registers must be confirmed on the instrument; ``time_unit`` records the assumption.
    """
    if not steps:
        raise TemperatureProgramError("配方没有步骤")
    if len(steps) * 2 > TAIE_PROGRAM_SEGMENTS:
        raise TemperatureProgramError(
            f"温度程序最多 {TAIE_PROGRAM_SEGMENTS} 段（{TAIE_PROGRAM_SEGMENTS // 2} 个配方步骤），当前配方有 {len(steps)} 步"
        )
    scale = 60.0 if time_unit == "min" else 1.0
    segments: list[dict[str, Any]] = []
    previous_sv: float | None = None
    for step in steps:
        delta = abs(step.target_temp_c - previous_sv) if previous_sv is not None else 0.0
        ramp_seconds = (delta / step.ramp_rate_cpm) * 60.0 if step.ramp_rate_cpm > 0 and delta > 0 else 0.0
        for kind, seconds in (("ramp", ramp_seconds), ("hold", float(step.hold_seconds))):
            raw = int(math.ceil(seconds / scale)) if seconds > 0 else 0
            if raw > TAIE_MAX_TIME_RAW:
                raise TemperatureProgramError(f"第 {step.step_no} 步{ '升温' if kind == 'ramp' else '保温' }时间超出仪表段时间上限")
            segments.append({"segment": len(segments) + 1, "step_no": step.step_no, "kind": kind,
                             "sv": float(step.target_temp_c), "time_raw": raw, "time_unit": time_unit})
        previous_sv = step.target_temp_c
    return segments


class MultiDeviceExperimentGateway:
    capabilities = GatewayCapabilities(
        temperature_program=True, temperature_setpoint=True, run_control_word=False,
        alarm_words=False, multi_device_status=True, balance_tare=True,
    )

    def __init__(self, gateway: MultiDeviceGateway, *, program_group: int = 0, time_unit: str = "min",
                 simulation: bool = True, description: dict[str, Any] | None = None) -> None:
        self._gateway = gateway
        self._program_group = program_group
        self._time_unit = time_unit
        self._simulation = simulation
        self._description = description or {}
        self._last_degraded: tuple[str, ...] = ()
        self._gas_addresses: dict[str, int] = {}
        for channel in gateway.channels:
            gas = channel.gas.upper()
            if gas in ("N2", "H2", "CO") and gas not in self._gas_addresses:
                self._gas_addresses[gas] = channel.address

    @property
    def gateway(self) -> MultiDeviceGateway:
        return self._gateway

    def connect(self) -> bool:
        return self._gateway.connect()

    def close(self) -> None:
        self._gateway.close()

    def read_snapshot(self) -> DeviceSnapshot:
        multi = self._gateway.read_multi_snapshot()
        self._last_degraded = multi.degraded_devices

        def flow(gas: str) -> float:
            address = self._gas_addresses.get(gas)
            return multi.mfc_flows_lpm.get(address, 0.0) if address is not None else 0.0

        return DeviceSnapshot(
            temperature_c=multi.temperatures_c[0], weight_g=multi.weight_g, pressure_mpa=0.0,
            n2_lpm=flow("N2"), h2_lpm=flow("H2"), co_lpm=flow("CO"), alarm_word=0,
        )

    def degraded_devices(self) -> tuple[str, ...]:
        return self._last_degraded

    def apply_gas_setpoints(self, *, n2_lpm: float, h2_lpm: float, co_lpm: float) -> dict[str, float]:
        requested = {"N2": float(n2_lpm), "H2": float(h2_lpm), "CO": float(co_lpm)}
        applied: dict[str, float] = {}
        for gas, lpm in requested.items():
            address = self._gas_addresses.get(gas)
            if address is None:
                if lpm > 0:
                    raise DeviceCommError(f"没有配置 {gas} 的 MFC 通道，无法下发 {lpm:g} L/min")
                continue
            self._gateway.set_mfc_flow(address, lpm)
            applied[f"{gas.lower()}_lpm"] = lpm
        return applied

    def apply_temperature_setpoint(self, *, temperature_c: float, ramp_rate_cpm: float) -> None:
        self._gateway.set_temperature_sv(temperature_c)

    def download_temperature_program(self, steps: list[RecipeStep]) -> dict[str, Any]:
        segments = build_taie_segments(steps, time_unit=self._time_unit)
        writer = getattr(self._gateway, "write_program_segment", None)
        if writer is None:
            raise TemperatureProgramError("温控仪适配器不支持程序段写入")
        for segment in segments:
            writer(self._program_group, segment["segment"], segment["sv"], segment["time_raw"])
        # Unused trailing segments are zeroed so a shorter recipe never inherits a previous curve.
        for index in range(len(segments) + 1, TAIE_PROGRAM_SEGMENTS + 1):
            writer(self._program_group, index, 0.0, 0)
        selector = getattr(self._gateway, "select_program_group", None)
        if selector is not None:
            selector(self._program_group)
        return {
            "group": self._program_group, "segments": len(segments), "time_unit": self._time_unit,
            "curve": segments, "remote_start": False,
            "message": f"温度程序已下发到仪表程序组 {self._program_group}（{len(segments)} 段）。仪表不支持远程启动，请在面板上启动该程序。",
        }

    def issue_run_control(self, command: str) -> int:
        raise DeviceCommError("多设备通路没有 PLC 运行控制字")

    def evaluate_run_control_feedback(self, feedback_word: int) -> RunControlFeedback:
        return RunControlFeedback(None, 0, feedback_word, True, "控制反馈: 不适用")

    def read_multi_snapshot(self) -> MultiDeviceSnapshot | None:
        multi = self._gateway.read_multi_snapshot()
        self._last_degraded = multi.degraded_devices
        return multi

    def set_mfc_flow(self, address: int, lpm: float) -> None:
        self._gateway.set_mfc_flow(address, lpm)

    def set_temperature_sv(self, celsius: float) -> None:
        self._gateway.set_temperature_sv(celsius)

    def tare_balance(self) -> bool:
        return self._gateway.tare_balance()

    def describe(self) -> dict[str, Any]:
        channels = [
            {"address": c.address, "gas": c.gas, "full_scale_lpm": c.full_scale_lpm,
             "role": next((gas for gas, address in self._gas_addresses.items() if address == c.address), None)}
            for c in self._gateway.channels
        ]
        return {
            "backend": "multi_device", "simulation": self._simulation,
            "summary": "TAIE 温控仪 + Azbil MFC × %d + 电子天平%s" % (len(channels), "（仿真）" if self._simulation else ""),
            "devices": self._description.get("devices", []),
            "mfc_channels": channels,
            "temperature_program": {"group": self._program_group, "time_unit": self._time_unit,
                                    "max_steps": TAIE_PROGRAM_SEGMENTS // 2},
        }


def comm_config_from_settings(*, simulation: bool, temp_port: str, temp_slave_id: int, temp_baudrate: int,
                              mfc_port: str, mfc_baudrate: int, mfc_channels: list[tuple[int, str, float]],
                              balance_port: str, balance_protocol: str, balance_baudrate: int) -> CommConfig:
    return CommConfig(
        simulation_mode=simulation, temp_port=temp_port, temp_slave_id=temp_slave_id, temp_baudrate=temp_baudrate,
        mfc_port=mfc_port, mfc_baudrate=mfc_baudrate,
        mfc_channels=tuple(MfcChannelConfig(address, gas, full_scale) for address, gas, full_scale in mfc_channels),
        balance_port=balance_port, balance_protocol=balance_protocol, balance_baudrate=balance_baudrate,
    )
