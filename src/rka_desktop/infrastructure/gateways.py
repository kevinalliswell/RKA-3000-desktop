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
from rka_desktop.domain.gases import GAS_BY_KEY, label, normalise_gas_key
from rka_desktop.domain.recipe import RecipeStep
from rka_desktop.infrastructure.comm.config import CommConfig, MfcChannelConfig
from rka_desktop.infrastructure.comm.exceptions import DeviceCommError
from rka_desktop.infrastructure.comm.multi_device_gateway import MultiDeviceGateway
from rka_desktop.infrastructure.comm.plc.modbus_client import ModbusRtuClient

logger = logging.getLogger(__name__)

TAIE_PROGRAM_SEGMENTS = 8
TAIE_MAX_TIME_RAW = 9999
# The PLC register map (contract_v1) carries N2/H2/CO only; ranges from the hardware specification.
PLC_GAS_LIMITS = {"N2": 20.0, "H2": 5.0, "CO": 5.0}


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
        snapshot = self._client.read_snapshot()
        snapshot.flows_lpm = {"N2": snapshot.n2_lpm, "H2": snapshot.h2_lpm, "CO": snapshot.co_lpm}
        return snapshot

    def degraded_devices(self) -> tuple[str, ...]:
        return ()

    def gas_device_limits(self) -> dict[str, float]:
        return dict(PLC_GAS_LIMITS)

    def max_program_steps(self) -> int | None:
        return None

    def read_gas_setpoints(self) -> dict[str, float] | None:
        return None

    def _write_all(self) -> dict[str, float]:
        return self._client.apply_setpoints(
            temperature_c=self._last_temp["temperature_c"], ramp_rate_cpm=self._last_temp["ramp_rate_cpm"],
            n2_lpm=self._last_gas["n2_lpm"], h2_lpm=self._last_gas["h2_lpm"], co_lpm=self._last_gas["co_lpm"],
        )

    def apply_gas_setpoints(self, flows: dict[str, float]) -> dict[str, float]:
        unsupported = [gas for gas, value in flows.items() if gas not in PLC_GAS_LIMITS and value > 0]
        if unsupported:
            raise DeviceCommError(f"PLC 寄存器表没有 {'/'.join(label(g) for g in unsupported)} 通道")
        # The PLC map writes temperature and gas in one block; keep the last temperature values.
        self._last_gas = {"n2_lpm": float(flows.get("N2", 0.0)), "h2_lpm": float(flows.get("H2", 0.0)),
                          "co_lpm": float(flows.get("CO", 0.0))}
        self._write_all()
        return {"N2": self._last_gas["n2_lpm"], "H2": self._last_gas["h2_lpm"], "CO": self._last_gas["co_lpm"]}

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
        alarm_words=False, multi_device_status=True, balance_tare=True, gas_setpoint_readback=True,
        program_position=True,
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
        self._full_scale: dict[str, float] = {}
        for channel in gateway.channels:
            gas = normalise_gas_key(channel.gas)
            if gas is not None and gas not in self._gas_addresses:
                self._gas_addresses[gas] = channel.address
                self._full_scale[gas] = float(channel.full_scale_lpm)

    @property
    def gateway(self) -> MultiDeviceGateway:
        return self._gateway

    def connect(self) -> bool:
        return self._gateway.connect()

    def close(self) -> None:
        self._gateway.close()

    def _by_gas(self, values: dict[int, float]) -> dict[str, float]:
        return {gas: values.get(address, 0.0) for gas, address in self._gas_addresses.items()}

    def read_snapshot(self) -> DeviceSnapshot:
        multi = self._gateway.read_multi_snapshot()
        self._last_degraded = multi.degraded_devices
        flows = self._by_gas(multi.mfc_flows_lpm)
        segment = None
        if "temp" not in multi.degraded_devices:
            try:
                segment = self._gateway.read_program_segment()
            except DeviceCommError:
                segment = None
        return DeviceSnapshot(
            temperature_c=multi.temperatures_c[0], weight_g=multi.weight_g, pressure_mpa=0.0,
            n2_lpm=flows.get("N2", 0.0), h2_lpm=flows.get("H2", 0.0), co_lpm=flows.get("CO", 0.0), alarm_word=0,
            flows_lpm=flows, setpoints_lpm=self._by_gas(multi.mfc_setpoints_lpm), program_segment=segment,
        )

    def degraded_devices(self) -> tuple[str, ...]:
        return self._last_degraded

    def gas_device_limits(self) -> dict[str, float]:
        return dict(self._full_scale)

    def max_program_steps(self) -> int | None:
        return TAIE_PROGRAM_SEGMENTS // 2

    def apply_gas_setpoints(self, flows: dict[str, float]) -> dict[str, float]:
        for gas, lpm in flows.items():
            if gas not in self._gas_addresses and lpm > 0:
                name = GAS_BY_KEY[gas].label if gas in GAS_BY_KEY else gas
                raise DeviceCommError(f"没有配置 {name} 的 MFC 通道，无法下发 {lpm:g} L/min")
        applied: dict[str, float] = {}
        for gas, address in self._gas_addresses.items():
            lpm = float(flows.get(gas, 0.0))
            self._gateway.set_mfc_flow(address, lpm)
            applied[gas] = lpm
        return applied

    def read_gas_setpoints(self) -> dict[str, float] | None:
        multi = self._gateway.read_multi_snapshot()
        self._last_degraded = multi.degraded_devices
        if "mfc" in multi.degraded_devices:
            return None
        return self._by_gas(multi.mfc_setpoints_lpm)

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
             "role": next((gas for gas, address in self._gas_addresses.items() if address == c.address), None),
             "label": label(normalise_gas_key(c.gas) or c.gas)}
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
                              balance_port: str, balance_protocol: str, balance_baudrate: int,
                              temp_segment_seconds: float = 60.0) -> CommConfig:
    return CommConfig(
        simulation_mode=simulation, temp_port=temp_port, temp_slave_id=temp_slave_id, temp_baudrate=temp_baudrate,
        mfc_port=mfc_port, mfc_baudrate=mfc_baudrate,
        mfc_channels=tuple(MfcChannelConfig(address, gas, full_scale) for address, gas, full_scale in mfc_channels),
        balance_port=balance_port, balance_protocol=balance_protocol, balance_baudrate=balance_baudrate,
        temp_segment_seconds=temp_segment_seconds,
    )
