from __future__ import annotations

from typing import Sequence

from rka_desktop.comm.config import MfcChannelConfig
from rka_desktop.comm.exceptions import DeviceCommError

_FULL_SCALE_COUNTS = 50000  # azbil_mfc.constants.FULL_SCALE_COUNTS


class AzbilMfcAdapter:
    """Real MFC bus adapter wrapping a vendored MQVBusManager.

    PV/SP on the wire are raw counts (0..50000). We convert to/from L/min using each
    channel's configured full scale.
    """

    def __init__(self, bus_manager, channels: Sequence[MfcChannelConfig]) -> None:
        self._mgr = bus_manager
        self._channels = tuple(channels)
        self._full_scale = {c.address: c.full_scale_lpm for c in self._channels}
        self._gas = {c.address: c.gas for c in self._channels}

    @classmethod
    def from_config(cls, cfg) -> "AzbilMfcAdapter":
        from rka_desktop.comm._vendor.azbil_mfc import MQVBusManager, RS485Bus

        bus = RS485Bus(port=cfg.mfc_port, baudrate=cfg.mfc_baudrate)
        manager = MQVBusManager(bus)
        for channel in cfg.mfc_channels:
            manager.add_device(channel.address)
        return cls(manager, cfg.mfc_channels)

    def connect(self) -> None:
        try:
            self._mgr.bus.open()
        except Exception as exc:  # noqa: BLE001 - normalize driver errors
            raise DeviceCommError(f"MFC bus open failed: {exc}") from exc

    def close(self) -> None:
        try:
            self._mgr.bus.close()
        except Exception:  # noqa: BLE001
            pass

    def _counts_to_lpm(self, address: int, counts: int) -> float:
        return round(counts / _FULL_SCALE_COUNTS * self._full_scale[address], 3)

    def _lpm_to_counts(self, address: int, lpm: float) -> int:
        return int(round(lpm / self._full_scale[address] * _FULL_SCALE_COUNTS))

    def read_all_pv(self) -> dict[int, float]:
        try:
            raw = self._mgr.read_all_pv()
        except Exception as exc:  # noqa: BLE001
            raise DeviceCommError(f"MFC read_all_pv failed: {exc}") from exc
        return {addr: self._counts_to_lpm(addr, counts) for addr, counts in raw.items()}

    def read_all_sp(self) -> dict[int, float]:
        result: dict[int, float] = {}
        for channel in self._channels:
            device = self._mgr.get_device(channel.address)
            try:
                counts = device.read_sp()
            except Exception as exc:  # noqa: BLE001
                raise DeviceCommError(f"MFC {channel.address} read_sp failed: {exc}") from exc
            result[channel.address] = self._counts_to_lpm(channel.address, counts)
        return result

    def set_flow(self, address: int, lpm: float) -> None:
        device = self._mgr.get_device(address)
        if device is None:
            raise DeviceCommError(f"unknown MFC address {address}")
        try:
            device.write_sp(1, self._lpm_to_counts(address, lpm))
        except Exception as exc:  # noqa: BLE001
            raise DeviceCommError(f"MFC {address} write_sp failed: {exc}") from exc

    def gas_type(self, address: int) -> str:
        return self._gas[address]
