from __future__ import annotations

from rka_desktop.comm.exceptions import DeviceCommError


class BalanceAdapter:
    """Real balance adapter wrapping a vendored BalanceClient."""

    def __init__(self, client) -> None:
        self._client = client

    @classmethod
    def from_config(cls, cfg) -> "BalanceAdapter":
        from rka_desktop.comm._vendor.balance_serial import (
            BalanceClient,
            PortSettings,
            create_protocol,
        )

        settings = PortSettings(port=cfg.balance_port, baudrate=cfg.balance_baudrate)
        protocol = create_protocol(cfg.balance_protocol)
        return cls(BalanceClient(settings, protocol))

    def connect(self) -> None:
        try:
            self._client.open()
            self._client.initialize_device()
        except Exception as exc:  # noqa: BLE001
            raise DeviceCommError(f"balance open failed: {exc}") from exc

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass

    def read_weight(self) -> float | None:
        try:
            message = self._client.read_message()
        except Exception as exc:  # noqa: BLE001
            raise DeviceCommError(f"balance read failed: {exc}") from exc
        if message is None:
            return None
        return message.weight

    def tare(self) -> bool:
        try:
            result = self._client.send_tare_and_wait()
        except Exception as exc:  # noqa: BLE001
            raise DeviceCommError(f"balance tare failed: {exc}") from exc
        return bool(getattr(result, "ack_received", False))
