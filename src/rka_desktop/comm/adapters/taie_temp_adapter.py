from __future__ import annotations

import logging

from rka_desktop.comm.exceptions import DeviceCommError

logger = logging.getLogger(__name__)


class TaieTempAdapter:
    """Real temperature adapter wrapping a vendored TaieTemperatureController."""

    def __init__(self, controller, *, write_enabled: bool = False) -> None:
        self._ctrl = controller
        self._write_enabled = write_enabled

    @classmethod
    def from_config(cls, cfg) -> TaieTempAdapter:
        from rka_desktop.comm._vendor.taie_temp import TaieTemperatureController
        from rka_desktop.comm._vendor.taie_temp.modbus_rtu import SerialSettings

        controller = TaieTemperatureController(
            slave_id=cfg.temp_slave_id,
            settings=SerialSettings(
                port=cfg.temp_port, baudrate=cfg.temp_baudrate,
                parity=cfg.temp_parity, stopbits=cfg.temp_stopbits,
                timeout=cfg.temp_timeout_s,
            ),
            read_attempts=1,
        )
        return cls(controller)

    def connect(self) -> None:
        try:
            self._ctrl.open()
        except Exception as exc:
            raise DeviceCommError(f"temperature controller open failed: {exc}") from exc

    def close(self) -> None:
        try:
            self._ctrl.close()
        except Exception as exc:  # noqa: BLE001 - close must remain best effort
            logger.warning("temperature controller close failed: %s", exc)

    def read_pv(self) -> float:
        try:
            return float(self._ctrl.read_pv())
        except Exception as exc:
            raise DeviceCommError(f"temperature read_pv failed: {exc}") from exc

    def read_sv(self) -> float:
        try:
            return float(self._ctrl.read_sv())
        except Exception as exc:
            raise DeviceCommError(f"temperature read_sv failed: {exc}") from exc

    def write_sv(self, value: float) -> None:
        if not self._write_enabled:
            raise DeviceCommError("real temperature writes are disabled pending field verification")
        try:
            self._ctrl.write_sv(float(value))
        except Exception as exc:
            raise DeviceCommError(f"temperature write_sv failed: {exc}") from exc
