"""MQV 系列质量流量控制器 — 6 通道串口客户端。

协议参考：references/MQV质量流量控制器通信协议.md

寄存器地址（协议地址，按地址首位区分存储区）：
  RAM  04B6H (1206) — SP 当前值（只读）
  RAM  04B7H (1207) — PV 当前值（实际流量）
  EEPROM 1131H (4401) — SP-0 设定值（可写）

量程换算：
  满量程计数值 = 10000 (0x2710)
  实际值 (L/min) = raw_count / 10000.0 * full_scale_lpm
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

from rka_desktop.core.mfc_protocol import (
    DeviceError,
    ProtocolError,
    build_read_frame,
    build_write_frame,
    parse_read_response,
    parse_write_response,
)
from rka_desktop.core.mfc_registers import (
    FULL_SCALE_COUNT as _FULL_SCALE_COUNT,
    EepromAddr,
    RamAddr,
    sp_eeprom_addr,
)
from rka_desktop.models.entities import MfcSnapshot

logger = logging.getLogger(__name__)

_RAM_SP_ADDR     = int(RamAddr.SP_CURRENT)
_EEPROM_SP0_ADDR = int(EepromAddr.SP_0)


@dataclass
class MfcChannelConfig:
    """单通道 MFC 配置。"""
    channel_id: int       # 1–6
    machine_addr: str     # 2 位十六进制字符串，如 "01"
    gas_label: str        # 气体标识，如 "H2"、"N2"
    full_scale_lpm: float  # 设备铭牌满量程（L/min）


# 默认 6 通道配置（机器地址需与设备拨码开关一致）
DEFAULT_CHANNEL_CONFIGS: list[MfcChannelConfig] = [
    MfcChannelConfig(channel_id=1, machine_addr="01", gas_label="H2",  full_scale_lpm=1.0),
    MfcChannelConfig(channel_id=2, machine_addr="02", gas_label="N2",  full_scale_lpm=10.0),
    MfcChannelConfig(channel_id=3, machine_addr="03", gas_label="CO",  full_scale_lpm=5.0),
    MfcChannelConfig(channel_id=4, machine_addr="04", gas_label="CO2", full_scale_lpm=5.0),
    MfcChannelConfig(channel_id=5, machine_addr="05", gas_label="Ar",  full_scale_lpm=5.0),
    MfcChannelConfig(channel_id=6, machine_addr="06", gas_label="CH4", full_scale_lpm=5.0),
]


class MfcClient:
    """管理 6 台 MQV 质量流量控制器的串口客户端。

    支持仿真模式（simulation_mode=True）和硬件模式。
    硬件模式依赖 pyserial；若未安装则退回仿真模式。
    """

    def __init__(
        self,
        serial_port: str,
        baudrate: int = 9600,
        channels: Optional[list[MfcChannelConfig]] = None,
        simulation_mode: bool = True,
        read_timeout: float = 0.5,
    ) -> None:
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.channels: list[MfcChannelConfig] = channels or DEFAULT_CHANNEL_CONFIGS
        self.simulation_mode = simulation_mode
        self.read_timeout = read_timeout
        self._serial: Optional[object] = None
        self._sim_counter = 0

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        if self.simulation_mode:
            logger.info("MfcClient: 仿真模式，无需串口连接。")
            return True
        try:
            import serial  # type: ignore[import-untyped]
        except ImportError:
            logger.error("pyserial 未安装，无法使用硬件模式，退回仿真模式。")
            self.simulation_mode = True
            return True

        try:
            self._serial = serial.Serial(
                port=self.serial_port,
                baudrate=self.baudrate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=self.read_timeout,
            )
            logger.info("MfcClient: 串口 %s 已打开。", self.serial_port)
            return True
        except Exception as exc:
            logger.error("MfcClient: 串口打开失败 — %s", exc)
            return False

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    # ------------------------------------------------------------------
    # 读取操作
    # ------------------------------------------------------------------

    def read_snapshot(self, channel: MfcChannelConfig) -> MfcSnapshot:
        """读取指定通道的 SP 与 PV 值，返回 MfcSnapshot。"""
        if self.simulation_mode:
            return self._sim_snapshot(channel)
        return self._hw_read_snapshot(channel)

    def read_all_snapshots(self) -> list[MfcSnapshot]:
        """依次读取全部 6 通道，返回快照列表。"""
        snapshots: list[MfcSnapshot] = []
        for ch in self.channels:
            try:
                snapshots.append(self.read_snapshot(ch))
            except Exception as exc:
                logger.error(
                    "MfcClient CH%d(%s): 读取失败 — %s", ch.channel_id, ch.gas_label, exc
                )
                snapshots.append(
                    MfcSnapshot(
                        channel_id=ch.channel_id,
                        gas_label=ch.gas_label,
                        pv_lpm=float("nan"),
                        sp_lpm=float("nan"),
                        end_code="--",
                        error=str(exc),
                    )
                )
        return snapshots

    # ------------------------------------------------------------------
    # 写入操作
    # ------------------------------------------------------------------

    def write_sp(self, channel: MfcChannelConfig, setpoint_lpm: float, sp_index: int = 0) -> str:
        """向 EEPROM 写入流量设定值，返回结束代码字符串。

        Args:
            channel:       目标通道配置。
            setpoint_lpm:  设定流量（L/min），需 ≤ channel.full_scale_lpm。
            sp_index:      SP 段索引，0–7，默认写 SP-0。

        Returns:
            结束代码字符串（"00" = 正常）。
        """
        if setpoint_lpm < 0 or setpoint_lpm > channel.full_scale_lpm:
            raise ValueError(
                f"设定值 {setpoint_lpm} L/min 超出通道 {channel.gas_label} 量程 "
                f"[0, {channel.full_scale_lpm}]"
            )
        raw_value = round(setpoint_lpm / channel.full_scale_lpm * _FULL_SCALE_COUNT)
        eeprom_addr = sp_eeprom_addr(sp_index)
        if self.simulation_mode:
            logger.info(
                "MfcClient SIM CH%d(%s): write SP-%d = %.3f L/min (raw=%d, addr=0x%04X)",
                channel.channel_id, channel.gas_label, sp_index, setpoint_lpm, raw_value, eeprom_addr,
            )
            return "00"
        return self._hw_write_sp(channel, raw_value, eeprom_addr)

    # ------------------------------------------------------------------
    # 仿真实现
    # ------------------------------------------------------------------

    def _sim_snapshot(self, channel: MfcChannelConfig) -> MfcSnapshot:
        self._sim_counter += 1
        base_ratio = 0.5 + 0.3 * abs(
            (self._sim_counter % 60 - 30) / 30.0
        )
        pv = round(channel.full_scale_lpm * base_ratio + random.uniform(-0.02, 0.02), 4)
        sp = round(channel.full_scale_lpm * 0.6, 4)
        return MfcSnapshot(
            channel_id=channel.channel_id,
            gas_label=channel.gas_label,
            pv_lpm=max(0.0, pv),
            sp_lpm=sp,
            end_code="00",
            error=None,
        )

    # ------------------------------------------------------------------
    # 硬件实现
    # ------------------------------------------------------------------

    def _hw_read_snapshot(self, channel: MfcChannelConfig) -> MfcSnapshot:
        """通过串口发送 RD 命令，读取 SP (04B6H) 与 PV (04B7H) 共 2 字。"""
        assert self._serial is not None, "串口未连接"
        frame = build_read_frame(channel.machine_addr, _RAM_SP_ADDR, count=2)
        response = self._transact(frame)
        words = parse_read_response(response, expected_count=2)
        sp_raw, pv_raw = words[0], words[1]
        scale = channel.full_scale_lpm / _FULL_SCALE_COUNT
        return MfcSnapshot(
            channel_id=channel.channel_id,
            gas_label=channel.gas_label,
            sp_lpm=round(sp_raw * scale, 4),
            pv_lpm=round(pv_raw * scale, 4),
            end_code="00",
            error=None,
        )

    def _hw_write_sp(self, channel: MfcChannelConfig, raw_value: int, eeprom_addr: int) -> str:
        assert self._serial is not None, "串口未连接"
        frame = build_write_frame(channel.machine_addr, eeprom_addr, raw_value)
        response = self._transact(frame)
        return parse_write_response(response)

    def _transact(self, frame: bytes) -> bytes:
        """发送一帧并接收应答，超时抛出 ProtocolError。"""
        ser = self._serial
        ser.reset_input_buffer()
        ser.write(frame)
        # 读取直到遇到 LF (0x0A) 或超时
        buf = bytearray()
        deadline = time.monotonic() + self.read_timeout * 2
        while time.monotonic() < deadline:
            byte = ser.read(1)
            if not byte:
                break
            buf.extend(byte)
            if byte[0] == 0x0A:
                break
        if not buf:
            raise ProtocolError("串口读取超时，未收到应答")
        return bytes(buf)
