from __future__ import annotations

import logging
import random
from typing import Optional

from rka_desktop.core.device_map import SNAPSHOT_REGISTERS, build_snapshot
from rka_desktop.models.entities import DeviceSnapshot

logger = logging.getLogger(__name__)

try:
    from pymodbus.client import ModbusSerialClient
except Exception:  # pragma: no cover
    ModbusSerialClient = None  # type: ignore[assignment]


class ModbusClientError(RuntimeError):
    pass


class ModbusConnectError(ModbusClientError):
    pass


class ModbusReadError(ModbusClientError):
    pass


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
        self.last_error: ModbusClientError | None = None

    def connect(self) -> bool:
        self.last_error = None
        if self.simulation_mode:
            logger.info("Modbus in simulation mode.")
            return True

        if ModbusSerialClient is None:
            logger.error("pymodbus is not available, cannot run in hardware mode.")
            self.last_error = ModbusConnectError("pymodbus is not available, cannot run in hardware mode")
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
        if not ok:
            self.last_error = ModbusConnectError(f"failed to connect to serial device {self.serial_port}")
            return False
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
        values = {
            "temperature_c": round(base_t + random.uniform(-0.8, 0.8), 2),
            "weight_g": round(max(base_w, 10.0), 3),
            "pressure_mpa": round(0.02 + random.uniform(-0.001, 0.001), 4),
            "n2_lpm": round(4.5 + random.uniform(-0.1, 0.1), 2),
            "h2_lpm": round(1.2 + random.uniform(-0.05, 0.05), 2),
            "co_lpm": round(0.8 + random.uniform(-0.05, 0.05), 2),
            "alarm_word": alarm_word,
        }
        return build_snapshot(values)

    def _read_snapshot_hardware(self) -> DeviceSnapshot:
        if self._client is None:
            raise ModbusReadError("Modbus client is not connected")

        values = {}
        for field in SNAPSHOT_REGISTERS:
            registers = self._read_registers(field.address, field.count)
            values[field.name] = field.decode(registers)

        return build_snapshot(values)

    def _read_registers(self, address: int, count: int) -> list[int]:
        assert self._client is not None
        result = self._client.read_holding_registers(address=address, count=count, slave=self.unit_id)
        if result.isError():
            raise ModbusReadError(f"Modbus read error at address {hex(address)}")
        return [int(register) for register in result.registers]
