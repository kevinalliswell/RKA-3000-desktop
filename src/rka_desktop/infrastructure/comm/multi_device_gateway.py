from __future__ import annotations

import logging
from typing import Sequence

from rka_desktop.domain.entities import DeviceSnapshot, MultiDeviceSnapshot
from rka_desktop.infrastructure.comm.config import CommConfig, MfcChannelConfig
from rka_desktop.infrastructure.comm.exceptions import DeviceCommError
from rka_desktop.infrastructure.comm.ports import BalancePort, MfcBusPort, TemperaturePort

logger = logging.getLogger(__name__)

_LEGACY_GASES = ("N2", "H2", "CO")


class MultiDeviceGateway:
    """Aggregates temperature + 6 MFCs + balance and exposes a legacy SnapshotSource.

    Last-good values default to 0.0 before the first successful read, so a 0.0 reading
    on a cold or fully-degraded poll is ambiguous; callers should consult
    ``MultiDeviceSnapshot.degraded_devices`` to distinguish a real zero from a fallback.
    """

    def __init__(
        self,
        temperature: TemperaturePort,
        mfc: MfcBusPort,
        balance: BalancePort,
        channels: Sequence[MfcChannelConfig],
    ) -> None:
        self._temp = temperature
        self._mfc = mfc
        self._balance = balance
        self._channels = tuple(channels)
        self._last_temp = 0.0
        self._last_flows = {c.address: 0.0 for c in self._channels}
        self._last_sps = {c.address: 0.0 for c in self._channels}
        self._last_weight = 0.0
        self._gas_addr = self._resolve_gas_addresses()

    @classmethod
    def from_config(cls, cfg: CommConfig) -> "MultiDeviceGateway":
        if cfg.simulation_mode:
            from rka_desktop.infrastructure.comm.adapters.sim_adapters import (
                SimBalanceAdapter,
                SimMfcBusAdapter,
                SimTemperatureAdapter,
            )

            temperature: TemperaturePort = SimTemperatureAdapter(segment_seconds=cfg.temp_segment_seconds)
            sim_mfc = SimMfcBusAdapter(cfg.mfc_channels)
            mfc: MfcBusPort = sim_mfc
            balance: BalancePort = SimBalanceAdapter(initial_g=50.0, flow_source=sim_mfc.flows_by_gas)
        else:
            from rka_desktop.infrastructure.comm.adapters.azbil_mfc_adapter import AzbilMfcAdapter
            from rka_desktop.infrastructure.comm.adapters.balance_adapter import BalanceAdapter
            from rka_desktop.infrastructure.comm.adapters.taie_temp_adapter import TaieTempAdapter

            temperature = TaieTempAdapter.from_config(cfg)
            mfc = AzbilMfcAdapter.from_config(cfg)
            balance = BalanceAdapter.from_config(cfg)
        return cls(temperature, mfc, balance, cfg.mfc_channels)

    def _resolve_gas_addresses(self) -> dict[str, int | None]:
        result: dict[str, int | None] = {gas: None for gas in _LEGACY_GASES}
        for channel in self._channels:
            gas = channel.gas.upper()
            if gas in result and result[gas] is None:
                result[gas] = channel.address
        for gas, address in result.items():
            if address is None:
                logger.warning("no MFC channel configured for legacy gas %s", gas)
        return result

    def connect(self) -> bool:
        try:
            self._temp.connect()
            self._mfc.connect()
            self._balance.connect()
        except Exception:  # noqa: BLE001 - best-effort teardown then re-raise
            self.close()
            raise
        return True

    def close(self) -> None:
        for device in (self._temp, self._mfc, self._balance):
            try:
                device.close()
            except Exception:  # noqa: BLE001
                pass

    @property
    def channels(self) -> tuple[MfcChannelConfig, ...]:
        return self._channels

    def set_temperature_sv(self, celsius: float) -> None:
        self._temp.write_sv(float(celsius))

    def set_mfc_flow(self, address: int, lpm: float) -> None:
        self._mfc.set_flow(address, float(lpm))

    def write_program_segment(self, group: int, segment: int, sv: float, time_raw: int) -> None:
        """Write one TAIE program-curve segment; adapters without program support raise."""
        writer = getattr(self._temp, "write_program_segment", None)
        if writer is None:
            raise DeviceCommError("温控仪适配器不支持程序段写入")
        writer(int(group), int(segment), float(sv), int(time_raw))

    def select_program_group(self, group: int) -> None:
        selector = getattr(self._temp, "select_program_group", None)
        if selector is None:
            raise DeviceCommError("温控仪适配器不支持选择程序组")
        selector(int(group))

    def tare_balance(self) -> bool:
        return self._balance.tare()

    def read_multi_snapshot(self) -> MultiDeviceSnapshot:
        degraded: list[str] = []

        try:
            self._last_temp = self._temp.read_pv()
        except DeviceCommError:
            degraded.append("temp")

        try:
            self._last_flows.update(self._mfc.read_all_pv())
            self._last_sps.update(self._mfc.read_all_sp())
        except DeviceCommError:
            degraded.append("mfc")

        try:
            weight = self._balance.read_weight()
            if weight is not None:
                self._last_weight = weight
        except DeviceCommError:
            degraded.append("balance")

        return MultiDeviceSnapshot(
            temperatures_c=(round(self._last_temp, 3),),
            mfc_flows_lpm=dict(self._last_flows),
            mfc_setpoints_lpm=dict(self._last_sps),
            weight_g=round(self._last_weight, 3),
            degraded_devices=tuple(degraded),
        )

    def read_snapshot(self) -> DeviceSnapshot:
        multi = self.read_multi_snapshot()

        def flow(gas: str) -> float:
            address = self._gas_addr.get(gas)
            if address is None:
                return 0.0
            return multi.mfc_flows_lpm.get(address, 0.0)

        return DeviceSnapshot(
            temperature_c=multi.temperatures_c[0],
            weight_g=multi.weight_g or 0.0,
            pressure_mpa=0.0,
            n2_lpm=flow("N2"),
            h2_lpm=flow("H2"),
            co_lpm=flow("CO"),
            alarm_word=0,
        )
