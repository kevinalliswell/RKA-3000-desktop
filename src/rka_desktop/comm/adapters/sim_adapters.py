from __future__ import annotations

from typing import Sequence

from rka_desktop.comm.config import MfcChannelConfig


class SimTemperatureAdapter:
    """Synthetic temperature controller: PV approaches SV by a fixed fraction per read."""

    def __init__(self, initial_c: float = 25.0, approach: float = 0.1) -> None:
        self._pv = float(initial_c)
        self._sv = float(initial_c)
        self._approach = approach
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def read_pv(self) -> float:
        self._pv += (self._sv - self._pv) * self._approach
        return round(self._pv, 3)

    def read_sv(self) -> float:
        return round(self._sv, 3)

    def write_sv(self, value: float) -> None:
        self._sv = float(value)


class SimMfcBusAdapter:
    """Synthetic 6-channel MFC bus: each PV approaches its SP per read."""

    def __init__(self, channels: Sequence[MfcChannelConfig], approach: float = 0.2) -> None:
        self._gas = {c.address: c.gas for c in channels}
        self._pv = {c.address: 0.0 for c in channels}
        self._sp = {c.address: 0.0 for c in channels}
        self._approach = approach
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def read_all_pv(self) -> dict[int, float]:
        for address in self._pv:
            self._pv[address] += (self._sp[address] - self._pv[address]) * self._approach
        return {address: round(value, 3) for address, value in self._pv.items()}

    def read_all_sp(self) -> dict[int, float]:
        return {address: round(value, 3) for address, value in self._sp.items()}

    def set_flow(self, address: int, lpm: float) -> None:
        if address not in self._sp:
            raise KeyError(f"unknown MFC address {address}")
        self._sp[address] = float(lpm)

    def gas_type(self, address: int) -> str:
        return self._gas[address]


class SimBalanceAdapter:
    """Synthetic balance: weight drifts down each read (mass loss), tare zeroes it."""

    def __init__(self, initial_g: float = 100.0, drift: float = 0.05) -> None:
        self._weight = float(initial_g)
        self._drift = drift
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def read_weight(self) -> float | None:
        self._weight = max(0.0, self._weight - self._drift)
        return round(self._weight, 3)

    def tare(self) -> bool:
        self._weight = 0.0
        return True
