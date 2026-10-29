from __future__ import annotations

import logging

from rka_desktop.comm.exceptions import DeviceCommError

logger = logging.getLogger(__name__)


class BalanceAdapter:
    """Real balance adapter wrapping a vendored BalanceClient."""

    def __init__(self, client, *, write_enabled: bool = False) -> None:
        self._client = client
        self._write_enabled = write_enabled

    @classmethod
    def from_config(cls, cfg) -> BalanceAdapter:
        from rka_desktop.comm._vendor.balance_serial import (
            BalanceClient,
            PortSettings,
            create_protocol,
        )

        settings = PortSettings(
            port=cfg.balance_port, baudrate=cfg.balance_baudrate,
            parity=cfg.balance_parity, stopbits=cfg.balance_stopbits,
            timeout=cfg.balance_timeout_s,
        )
        protocol = create_protocol(cfg.balance_protocol)
        return cls(BalanceClient(settings, protocol))

    def connect(self) -> None:
        try:
            self._client.open()
            self._client.initialize_device()
        except Exception as exc:
            raise DeviceCommError(f"balance open failed: {exc}") from exc

    def close(self) -> None:
        try:
            self._client.close()
        except Exception as exc:  # noqa: BLE001 - close must remain best effort
            logger.warning("balance close failed: %s", exc)

    def read_weight(self) -> float | None:
        try:
            message = self._client.read_message()
        except Exception as exc:
            raise DeviceCommError(f"balance read failed: {exc}") from exc
        if message is None:
            raise DeviceCommError("balance no response")
        if message.kind == "error":
            raise DeviceCommError(f"balance returned error {message.code or message.raw}")
        if message.kind == "unknown":
            raise DeviceCommError(f"balance invalid frame {message.raw}")
        if message.kind != "reading" or message.stable is not True:
            return None
        return message.weight

    def tare(self) -> bool:
        if not self._write_enabled:
            raise DeviceCommError("real balance tare is disabled pending field verification")
        try:
            result = self._client.send_tare_and_wait()
        except Exception as exc:
            raise DeviceCommError(f"balance tare failed: {exc}") from exc
        return bool(result.success)
