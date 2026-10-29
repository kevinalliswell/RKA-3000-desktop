from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone

from rka_desktop.comm.config import CommConfig, MfcChannelConfig
from rka_desktop.comm.exceptions import DeviceCommError
from rka_desktop.comm.ports import BalancePort, MfcBusPort, TemperaturePort
from rka_desktop.models.entities import DeviceSnapshot, MultiDeviceSnapshot

logger = logging.getLogger(__name__)

_LEGACY_GASES = ("N2", "H2", "CO")


class MultiDeviceGateway:
    """Aggregates temperature + 6 MFCs + balance and exposes a legacy SnapshotSource.

    Before the first valid read, values remain absent. Later failures retain the last
    valid value with per-device stale status, error reason and last-success time.
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
        self._last_temp: float | None = None
        self._last_flows: dict[int, float] = {}
        self._last_sps: dict[int, float] = {}
        self._last_weight: float | None = None
        self._last_success_at: dict[str, datetime] = {}
        self._connected = False
        self._connected_devices: set[str] = set()
        self._connection_errors: dict[str, str] = {}
        self._gas_addr = self._resolve_gas_addresses()

    @classmethod
    def from_config(cls, cfg: CommConfig) -> MultiDeviceGateway:
        if cfg.simulation_mode:
            from rka_desktop.comm.adapters.sim_adapters import (
                SimBalanceAdapter,
                SimMfcBusAdapter,
                SimTemperatureAdapter,
            )

            temperature: TemperaturePort = SimTemperatureAdapter()
            mfc: MfcBusPort = SimMfcBusAdapter(cfg.mfc_channels)
            balance: BalancePort = SimBalanceAdapter()
        else:
            from rka_desktop.comm.adapters.azbil_mfc_adapter import AzbilMfcAdapter
            from rka_desktop.comm.adapters.balance_adapter import BalanceAdapter
            from rka_desktop.comm.adapters.taie_temp_adapter import TaieTempAdapter

            temperature = TaieTempAdapter.from_config(cfg)
            mfc = AzbilMfcAdapter.from_config(cfg)
            balance = BalanceAdapter.from_config(cfg)
        return cls(temperature, mfc, balance, cfg.mfc_channels)

    @property
    def is_connected(self) -> bool:
        return self._connected

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
        for name, device in (("temp", self._temp), ("mfc", self._mfc), ("balance", self._balance)):
            if name in self._connected_devices:
                continue
            try:
                device.connect()
            except Exception as exc:  # noqa: BLE001 - allow other devices to connect
                self._connection_errors[name] = str(exc)
                try:
                    device.close()
                except Exception as close_exc:  # noqa: BLE001
                    logger.warning("%s close after failed connect: %s", name, close_exc)
            else:
                self._connected_devices.add(name)
                self._connection_errors.pop(name, None)
        self._connected = True
        return not self._connection_errors

    def close(self) -> None:
        self._connected = False
        self._connected_devices.clear()
        self._connection_errors.clear()
        for device in (self._temp, self._mfc, self._balance):
            try:
                device.close()
            except Exception as exc:  # noqa: BLE001 - close all ports despite one failure
                logger.warning("device close failed: %s", exc)

    def _mark_disconnected(self, name: str, device, reason: str) -> None:
        self._connected_devices.discard(name)
        self._connection_errors[name] = reason
        try:
            device.close()
        except Exception as exc:  # noqa: BLE001 - preserve the read failure
            logger.warning("%s close after read failure: %s", name, exc)

    @property
    def channels(self) -> tuple[MfcChannelConfig, ...]:
        return self._channels

    def set_temperature_sv(self, celsius: float) -> None:
        self._temp.write_sv(float(celsius))

    def set_mfc_flow(self, address: int, lpm: float) -> None:
        self._mfc.set_flow(address, float(lpm))

    def tare_balance(self) -> bool:
        return self._balance.tare()

    def read_multi_snapshot(self) -> MultiDeviceSnapshot:
        degraded: list[str] = []
        errors: dict[str, str] = {}

        def fail(name: str, reason: str) -> None:
            if name not in degraded:
                degraded.append(name)
            errors.setdefault(name, reason)

        if "temp" not in self._connected_devices:
            fail("temp", self._connection_errors.get("temp", "temperature not connected"))
        else:
            try:
                self._last_temp = self._temp.read_pv()
                self._last_success_at["temp"] = datetime.now(timezone.utc)
            except DeviceCommError as exc:
                fail("temp", str(exc))
                self._mark_disconnected("temp", self._temp, str(exc))

        if "mfc" not in self._connected_devices:
            flows = {}
            for channel in self._channels:
                fail(f"mfc:{channel.address}", self._connection_errors.get("mfc", "MFC bus not connected"))
            setpoints = {}
            channel_errors = {}
        else:
            try:
                flows = self._mfc.read_all_pv()
                self._last_flows.update(flows)
                now = datetime.now(timezone.utc)
                for address in flows:
                    self._last_success_at[f"mfc:{address}"] = now
            except DeviceCommError as exc:
                flows = {}
                for channel in self._channels:
                    fail(f"mfc:{channel.address}", str(exc))
            try:
                setpoints = self._mfc.read_all_sp()
                self._last_sps.update(setpoints)
            except DeviceCommError as exc:
                setpoints = {}
                for channel in self._channels:
                    fail(f"mfc:{channel.address}", str(exc))
            channel_errors = getattr(self._mfc, "last_errors", {})
            if not flows and not setpoints:
                self._mark_disconnected("mfc", self._mfc, "no MFC channels responded")
        for channel in self._channels:
            address = channel.address
            if address not in flows or address not in setpoints or address in channel_errors:
                fail(f"mfc:{address}", channel_errors.get(address, "no fresh PV/SP response"))

        if "balance" not in self._connected_devices:
            fail("balance", self._connection_errors.get("balance", "balance not connected"))
        else:
            try:
                weight = self._balance.read_weight()
                if weight is not None:
                    self._last_weight = weight
                    self._last_success_at["balance"] = datetime.now(timezone.utc)
                else:
                    fail("balance", "no stable weight reading")
            except DeviceCommError as exc:
                fail("balance", str(exc))
                self._mark_disconnected("balance", self._balance, str(exc))

        return MultiDeviceSnapshot(
            temperatures_c=(round(self._last_temp, 3) if self._last_temp is not None else None,),
            mfc_flows_lpm=dict(self._last_flows),
            mfc_setpoints_lpm=dict(self._last_sps),
            weight_g=round(self._last_weight, 3) if self._last_weight is not None else None,
            degraded_devices=tuple(degraded),
            last_success_at=dict(self._last_success_at),
            errors=errors,
        )

    def read_snapshot(self) -> DeviceSnapshot:
        multi = self.read_multi_snapshot()

        def flow(gas: str) -> float:
            address = self._gas_addr.get(gas)
            if address is None:
                return 0.0
            return multi.mfc_flows_lpm.get(address, 0.0)

        return DeviceSnapshot(
            temperature_c=multi.temperatures_c[0] or 0.0,
            weight_g=multi.weight_g or 0.0,
            pressure_mpa=0.0,
            n2_lpm=flow("N2"),
            h2_lpm=flow("H2"),
            co_lpm=flow("CO"),
            alarm_word=0,
        )
