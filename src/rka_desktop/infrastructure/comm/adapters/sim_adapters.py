from __future__ import annotations

import time
from typing import Sequence

from rka_desktop.infrastructure.comm.config import MfcChannelConfig


class SimTemperatureAdapter:
    """Synthetic temperature controller.

    PV approaches SV by a fixed fraction per read. A downloaded program curve runs once the
    program group is selected (standing in for the operator pressing RUN on the panel): each
    segment ramps linearly from the previous SV to its SV over ``time_raw * segment_seconds``.
    When the curve ends the output is off and SV returns to ambient. Writing SV directly stops
    the program (set-point mode).
    """

    def __init__(self, initial_c: float = 25.0, approach: float = 0.1, *, segment_seconds: float = 60.0,
                 clock=time.monotonic) -> None:
        self._pv = float(initial_c)
        self._sv = float(initial_c)
        self._ambient = float(initial_c)
        self._approach = approach
        self._connected = False
        self._segment_seconds = float(segment_seconds)
        self._clock = clock
        self.program: dict[int, dict[int, tuple[float, int]]] = {}
        self.program_group = 0
        self._program_started: float | None = None

    def connect(self) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def _position(self) -> tuple[int, float] | None:
        """(1-based segment, SV) of the running curve, or None when no program runs."""
        if self._program_started is None:
            return None
        segments = [(number, value) for number, value in sorted(self.program.get(self.program_group, {}).items())
                    if value[1] or value[0]]
        elapsed = self._clock() - self._program_started
        previous = self._start_sv
        for number, (sv, time_raw) in segments:
            duration = time_raw * self._segment_seconds
            if elapsed < duration:
                return number, previous + (sv - previous) * (elapsed / duration)
            elapsed -= duration
            previous = sv
        self._program_started = None  # curve finished: output off
        self._sv = self._ambient
        return None

    def _program_sv(self) -> float | None:
        if self._program_started is None:
            return None
        position = self._position()
        return position[1] if position is not None else self._ambient

    def read_program_segment(self) -> int:
        """0 when no program runs (simulation convention), else the running segment."""
        position = self._position()
        return position[0] if position is not None else 0

    def read_pv(self) -> float:
        program_sv = self._program_sv()
        if program_sv is not None:
            self._sv = program_sv
        self._pv += (self._sv - self._pv) * self._approach
        return round(self._pv, 3)

    def read_sv(self) -> float:
        return round(self._sv, 3)

    def write_sv(self, value: float) -> None:
        self._program_started = None
        self._sv = float(value)

    def write_program_segment(self, group: int, segment: int, sv: float, time_raw: int) -> None:
        self.program.setdefault(int(group), {})[int(segment)] = (float(sv), int(time_raw))

    def select_program_group(self, group: int) -> None:
        self.program_group = int(group)
        self._start_sv = self._pv
        self._program_started = self._clock()


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

    def flows_by_gas(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for address, value in self._pv.items():
            gas = str(self._gas[address]).upper()
            totals[gas] = totals.get(gas, 0.0) + value
        return totals


class SimBalanceAdapter:
    """Synthetic balance.

    Without a flow source the weight drifts down by ``drift`` per read (legacy behaviour). With
    one, mass changes only while reacting gas flows: reducing gases (H2/CO/CH4) remove oxygen,
    O2 adds it, approaching ``capacity`` of the initial mass like a first-order reaction.
    """

    REDUCING = ("H2", "CO", "CH4")
    OXIDISING = ("O2",)

    def __init__(self, initial_g: float = 100.0, drift: float = 0.05, *, flow_source=None,
                 rate_per_lpm: float = 0.004, capacity: float = 0.25) -> None:
        self._initial = float(initial_g)
        self._weight = float(initial_g)
        self._drift = drift
        self._flow_source = flow_source
        self._rate = rate_per_lpm
        self._capacity = capacity
        self._reacted = 0.0  # fraction of capacity converted
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def read_weight(self) -> float | None:
        if self._flow_source is None:
            self._weight = max(0.0, self._weight - self._drift)
            return round(self._weight, 3)
        flows = self._flow_source()
        reducing = sum(value for gas, value in flows.items() if gas in self.REDUCING)
        oxidising = sum(value for gas, value in flows.items() if gas in self.OXIDISING)
        driving = reducing - oxidising
        if driving:
            self._reacted += self._rate * driving * ((1.0 - self._reacted) if driving > 0 else (1.0 + self._reacted))
            self._reacted = max(-1.0, min(1.0, self._reacted))
        self._weight = self._initial * (1.0 - self._capacity * self._reacted)
        return round(self._weight, 3)

    def tare(self) -> bool:
        self._weight = 0.0
        self._initial = 0.0
        return True
