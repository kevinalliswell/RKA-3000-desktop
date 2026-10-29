from __future__ import annotations

import logging
from collections.abc import Sequence

from rka_desktop.comm.config import MfcChannelConfig
from rka_desktop.comm.exceptions import DeviceCommError

logger = logging.getLogger(__name__)


class AzbilMfcAdapter:
    """Real MFC bus adapter wrapping a vendored MQVBusManager.

    Engineering units come from live device scale metadata, never a fixed count range.
    """

    def __init__(self, bus_manager, channels: Sequence[MfcChannelConfig], *, write_enabled: bool = False) -> None:
        self._mgr = bus_manager
        self._channels = tuple(channels)
        self._full_scale = {c.address: c.full_scale_lpm for c in self._channels}
        self._gas = {c.address: c.gas for c in self._channels}
        self._scales = {}
        self.last_errors: dict[int, str] = {}
        self._write_enabled = write_enabled

    @classmethod
    def from_config(cls, cfg) -> AzbilMfcAdapter:
        from rka_desktop.comm._vendor.azbil_mfc import MQVBusManager, RS485Bus
        from rka_desktop.comm._vendor.azbil_mfc.constants import COMM_8E1, COMM_8N2

        bus = RS485Bus(
            port=cfg.mfc_port, baudrate=cfg.mfc_baudrate,
            comm_format=COMM_8E1 if cfg.mfc_format == "8E1" else COMM_8N2,
            timeout=cfg.mfc_timeout_s,
        )
        manager = MQVBusManager(bus)
        for channel in cfg.mfc_channels:
            manager.add_device(channel.address)
        return cls(manager, cfg.mfc_channels)

    def connect(self) -> None:
        try:
            self._scales.clear()
            self._mgr.bus.open()
        except Exception as exc:
            raise DeviceCommError(f"MFC bus open failed: {exc}") from exc

    def close(self) -> None:
        self._scales.clear()
        try:
            self._mgr.bus.close()
        except Exception as exc:  # noqa: BLE001 - close must remain best effort
            logger.warning("MFC bus close failed: %s", exc)

    def _scale(self, address: int):
        scale = self._scales.get(address)
        if scale is None:
            scale = self._mgr.get_flow_scale(address, refresh=True)
            if (scale is None or not 1 <= scale.full_scale_raw <= 0xFFFF
                    or not 1 <= scale.decimal_position <= 6
                    or scale.flow_unit_code not in (0, 1)):
                raise DeviceCommError(f"MFC {address} has no valid live flow scale")
            expected = self._full_scale[address]
            if abs(scale.max_flow_rate_lpm - expected) > max(expected * 0.02, 0.01):
                raise DeviceCommError(
                    f"MFC {address} live full scale {scale.max_flow_rate_lpm:g} L/min "
                    f"differs from profile {expected:g} L/min"
                )
            self._scales[address] = scale
        return scale

    def _counts_to_lpm(self, address: int, counts: int) -> float:
        return round(self._scale(address).raw_to_flow(counts), 3)

    def read_all_pv(self) -> dict[int, float]:
        self.last_errors = {}
        result: dict[int, float] = {}
        for channel in self._channels:
            try:
                device = self._mgr.get_device(channel.address)
                result[channel.address] = self._counts_to_lpm(channel.address, device.read_pv())
            except Exception as exc:  # noqa: BLE001 - preserve other channels
                self.last_errors[channel.address] = str(exc)
        return result

    def read_all_sp(self) -> dict[int, float]:
        result: dict[int, float] = {}
        for channel in self._channels:
            try:
                device = self._mgr.get_device(channel.address)
                counts = device.read_sp()
                result[channel.address] = self._counts_to_lpm(channel.address, counts)
            except Exception as exc:  # noqa: BLE001
                self.last_errors[channel.address] = str(exc)
        return result

    def set_flow(self, address: int, lpm: float) -> None:
        if not self._write_enabled:
            raise DeviceCommError("real MFC writes are disabled pending field verification")
        if address not in self._full_scale:
            raise DeviceCommError(f"unknown MFC address {address}")
        device = self._mgr.get_device(address)
        if device is None:
            raise DeviceCommError(f"unknown MFC address {address}")
        if not 0 <= lpm <= min(self._full_scale[address], self._scale(address).max_flow_rate_lpm):
            raise DeviceCommError(f"MFC {address} flow outside verified range")
        try:
            device.write_sp(0, self._scale(address).flow_to_raw(lpm))
        except Exception as exc:
            raise DeviceCommError(f"MFC {address} write_sp failed: {exc}") from exc

    def gas_type(self, address: int) -> str:
        return self._gas[address]
