from __future__ import annotations

import logging
import random
from typing import Optional

from rka_desktop.core.device_map import DeviceMap, get_device_map
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


class ModbusWriteError(ModbusClientError):
    pass


class ModbusRtuClient:
    def __init__(
        self,
        serial_port: str,
        baudrate: int,
        unit_id: int,
        device_map: DeviceMap | None = None,
        simulation_mode: bool = True,
    ) -> None:
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.unit_id = unit_id
        self.device_map = device_map or get_device_map()
        self.simulation_mode = simulation_mode
        self._client: Optional[object] = None
        self._sim_counter = 0
        self._sim_interlock_word = 0
        self.last_error: ModbusClientError | None = None
        self.last_applied_setpoints: dict[str, float] | None = None
        self.last_run_control_command: str | None = None
        self.last_run_control_word: int = 0

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

    def apply_setpoints(
        self,
        *,
        temperature_c: float,
        ramp_rate_cpm: float,
        n2_lpm: float,
        h2_lpm: float,
        co_lpm: float,
    ) -> dict[str, float]:
        values = {
            "temperature_setpoint_c": float(temperature_c),
            "ramp_rate_setpoint_cpm": float(ramp_rate_cpm),
            "n2_setpoint_lpm": float(n2_lpm),
            "h2_setpoint_lpm": float(h2_lpm),
            "co_setpoint_lpm": float(co_lpm),
        }

        if self.simulation_mode:
            self.last_applied_setpoints = values
            self.last_error = None
            logger.info("Applied simulated setpoints: %s", values)
            return values

        previous_values = dict(self.last_applied_setpoints) if self.last_applied_setpoints is not None else None
        try:
            self._write_setpoint_values(values)
        except ModbusWriteError as exc:
            rollback_error: ModbusWriteError | None = None
            if previous_values is not None:
                try:
                    self._write_setpoint_values(previous_values)
                    logger.warning("Setpoint write failed, rolled back to previous values")
                except ModbusWriteError as rollback_exc:
                    rollback_error = rollback_exc

            if rollback_error is not None:
                self.last_error = ModbusWriteError(f"{exc}; rollback failed: {rollback_error}")
            elif previous_values is not None:
                self.last_error = ModbusWriteError(f"{exc}; rollback applied")
            else:
                self.last_error = exc
            raise self.last_error from exc

        self.last_applied_setpoints = values
        self.last_error = None
        logger.info("Applied hardware setpoints: %s", values)
        return values

    def issue_run_control(self, command: str) -> int:
        if command not in self.device_map.run_control_commands:
            raise ModbusWriteError(f"Unknown run control command: {command}")

        word = int(self.device_map.run_control_commands[command])
        if self.simulation_mode:
            if command == "reset" and self._sim_counter % 180 not in range(120, 136):
                self._sim_interlock_word = 0
            self.last_run_control_command = command
            self.last_run_control_word = word
            self.last_error = None
            logger.info("Applied simulated run control command: %s (%s)", command, hex(word))
            return word

        try:
            self._write_register(self.device_map.run_control_word_field.address, word)
            self._write_register(self.device_map.run_control_word_field.address, 0)
        except ModbusWriteError as exc:
            self.last_error = exc
            raise

        self.last_run_control_command = command
        self.last_run_control_word = word
        self.last_error = None
        logger.info("Applied hardware run control command: %s (%s)", command, hex(word))
        return word

    def _read_snapshot_simulated(self) -> DeviceSnapshot:
        self._sim_counter += 1
        base_t = 800 + (self._sim_counter % 120) * 0.3
        base_w = 95 - (self._sim_counter % 500) * 0.01
        alarm_word = 0x0002 if 120 <= (self._sim_counter % 180) <= 135 else 0
        if alarm_word:
            self._sim_interlock_word |= alarm_word
        values = {
            "temperature_c": round(base_t + random.uniform(-0.8, 0.8), 2),
            "weight_g": round(max(base_w, 10.0), 3),
            "pressure_mpa": round(0.02 + random.uniform(-0.001, 0.001), 4),
            "n2_lpm": round(4.5 + random.uniform(-0.1, 0.1), 2),
            "h2_lpm": round(1.2 + random.uniform(-0.05, 0.05), 2),
            "co_lpm": round(0.8 + random.uniform(-0.05, 0.05), 2),
            "alarm_word": alarm_word,
            "interlock_word": self._sim_interlock_word,
            "run_control_word": self.last_run_control_word,
            "estop_status": 1 if self._sim_interlock_word & 0x0010 else 0,
        }
        return self.device_map.build_snapshot(values)

    def _read_snapshot_hardware(self) -> DeviceSnapshot:
        if self._client is None:
            raise ModbusReadError("Modbus client is not connected")

        values = {}
        for field in self.device_map.snapshot_registers:
            registers = self._read_registers(field.address, field.count)
            values[field.name] = field.decode(registers)

        return self.device_map.build_snapshot(values)

    def _read_registers(self, address: int, count: int) -> list[int]:
        assert self._client is not None
        result = self._client.read_holding_registers(address=address, count=count, slave=self.unit_id)
        if result.isError():
            raise ModbusReadError(f"Modbus read error at address {hex(address)}")
        return [int(register) for register in result.registers]

    def _write_register(self, address: int, value: int) -> None:
        if self._client is None:
            raise ModbusWriteError("Modbus client is not connected")

        result = self._client.write_register(address=address, value=value, slave=self.unit_id)
        if result.isError():
            raise ModbusWriteError(f"Modbus write error at address {hex(address)}")

    def _write_setpoint_values(self, values: dict[str, float]) -> None:
        for field_name, field in self.device_map.setpoint_fields.items():
            self._write_register(field.address, field.encode(values[field_name])[0])
