from __future__ import annotations

import logging
import random
from typing import Optional

from rka_desktop.models.entities import DeviceSnapshot

logger = logging.getLogger(__name__)

try:
    from pymodbus.client import ModbusSerialClient
except Exception:  # pragma: no cover
    ModbusSerialClient = None  # type: ignore[assignment]


class ModbusRtuClient:
    def __init__(
        self,
        serial_port: str,
        baudrate: int,
        unit_id: int,
        simulation_mode: bool = True,
    ) -> None:
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.unit_id = unit_id
        self.simulation_mode = simulation_mode
        self._client: Optional[object] = None
        self._sim_counter = 0

    def connect(self) -> bool:
        if self.simulation_mode:
            logger.info("Modbus in simulation mode.")
            return True

        if ModbusSerialClient is None:
            logger.error("pymodbus is not available, cannot run in hardware mode.")
            return False

        self._client = ModbusSerialClient(
            port=self.serial_port,
            baudrate=self.baudrate,
            parity="N",
            stopbits=1,
            bytesize=8,
            timeout=0.5,
        )
        ok = bool(self._client.connect())
        logger.info("Modbus connect %s", "ok" if ok else "failed")
        return ok

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def read_snapshot(self) -> DeviceSnapshot:
        if self.simulation_mode:
            return self._read_snapshot_simulated()
        return self._read_snapshot_hardware()

    def _read_snapshot_simulated(self) -> DeviceSnapshot:
        self._sim_counter += 1
        base_t = 800 + (self._sim_counter % 120) * 0.3
        base_w = 95 - (self._sim_counter % 500) * 0.01
        alarm_word = 0x0002 if 120 <= (self._sim_counter % 180) <= 135 else 0
        return DeviceSnapshot(
            temperature_c=round(base_t + random.uniform(-0.8, 0.8), 2),
            weight_g=round(max(base_w, 10.0), 3),
            pressure_mpa=round(0.02 + random.uniform(-0.001, 0.001), 4),
            n2_lpm=round(4.5 + random.uniform(-0.1, 0.1), 2),
            h2_lpm=round(1.2 + random.uniform(-0.05, 0.05), 2),
            co_lpm=round(0.8 + random.uniform(-0.05, 0.05), 2),
            alarm_word=alarm_word,
        )

    def _read_snapshot_hardware(self) -> DeviceSnapshot:
        if self._client is None:
            raise RuntimeError("Modbus client is not connected")

        # 实机联调时按最终寄存器映射替换这里的地址与缩放系数。
        temp = self._read_u16(0x0001) / 10.0
        weight_raw_high = self._read_u16(0x0010)
        weight_raw_low = self._read_u16(0x0011)
        weight = ((weight_raw_high << 16) | weight_raw_low) / 1000.0
        pressure = self._read_u16(0x0040) / 1000.0
        n2 = self._read_u16(0x0020) / 100.0
        h2 = self._read_u16(0x0021) / 100.0
        co = self._read_u16(0x0022) / 100.0
        alarm = self._read_u16(0x0050)

        return DeviceSnapshot(
            temperature_c=temp,
            weight_g=weight,
            pressure_mpa=pressure,
            n2_lpm=n2,
            h2_lpm=h2,
            co_lpm=co,
            alarm_word=alarm,
        )

    def _read_u16(self, address: int) -> int:
        assert self._client is not None
        result = self._client.read_holding_registers(address=address, count=1, slave=self.unit_id)
        if result.isError():
            raise RuntimeError(f"Modbus read error at address {hex(address)}")
        return int(result.registers[0])
