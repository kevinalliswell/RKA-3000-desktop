# Multi-Device Comm Layer + Release Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a simulation-first multi-device communication layer to RKA (6× Azbil MFC + 1 TAIE temperature controller + 1 electronic balance) using vendored protocol drivers behind RKA adapters, plug it into the existing acquisition flow via a `SnapshotSource` seam, and add single-source versioning + CHANGELOG + an upgraded release workflow.

**Architecture:** Vendored upstream drivers (`comm/_vendor/*`, pinned by commit) → RKA narrow `ports` (Protocols) → `real` + `sim` adapters → `MultiDeviceGateway` that implements `SnapshotSource` (`connect/close/read_snapshot`) and maps multi-device readings onto the legacy `DeviceSnapshot`. The existing `AcquisitionWorker` consumes it unchanged (only its type hint is widened). Release automation makes `rka_desktop.__version__` the single source of truth.

**Tech Stack:** Python 3.10+, PySide6, pyserial (already a dependency), pytest, GitHub Actions.

**Branch:** `feat/multi-device-comm-layer` (already created off `main`).

**Conventions:** English in code/comments/commits; Chinese allowed in user-facing strings. Conventional Commits. Tests live flat in `tests/` and import via `rka_desktop.*` (pytest `pythonpath=["src"]`). Run tests headless with `QT_QPA_PLATFORM=offscreen`.

---

## File Structure

```
src/rka_desktop/comm/
├── __init__.py                       # intentionally light (no heavy imports)
├── exceptions.py                     # DeviceCommError
├── config.py                         # MfcChannelConfig, CommConfig (+ default 6 channels)
├── ports.py                          # SnapshotSource, TemperaturePort, MfcBusPort, BalancePort
├── multi_device_gateway.py           # MultiDeviceSnapshot lives in models; gateway here
├── adapters/
│   ├── __init__.py
│   ├── sim_adapters.py               # SimTemperatureAdapter, SimMfcBusAdapter, SimBalanceAdapter
│   ├── azbil_mfc_adapter.py          # AzbilMfcAdapter (real)
│   ├── taie_temp_adapter.py          # TaieTempAdapter (real)
│   └── balance_adapter.py            # BalanceAdapter (real)
└── _vendor/
    ├── __init__.py
    ├── VENDOR.md
    ├── azbil_mfc/                     # trimmed copy @83ddc491 (MIT)
    ├── taie_temp/                     # trimmed copy @ab18b921 (Apache-2.0)
    └── balance_serial/                # trimmed copy @496b7b76 (no upstream LICENSE)

src/rka_desktop/models/entities.py    # + MultiDeviceSnapshot (additive)
src/rka_desktop/services/acquisition_service.py  # widen client type hint only
src/rka_desktop/__init__.py           # __version__ = "0.2.0" (single source)
pyproject.toml                        # dynamic version
scripts/release.py                    # bump helper
scripts/checks/verify_tag_version.py  # read version from package, not pyproject literal
scripts/checks/verify_version_sync.py # __version__ == CHANGELOG top
CHANGELOG.md                          # new (Keep a Changelog)
.github/workflows/release.yml         # extract changelog notes
.github/workflows/ci.yml              # + version-sync check

tests/comm/                           # new test dir for the comm layer
```

---

## Task 1: Vendor the three driver cores

**Files:**
- Create: `src/rka_desktop/comm/__init__.py`, `src/rka_desktop/comm/_vendor/__init__.py`, `src/rka_desktop/comm/_vendor/VENDOR.md`
- Create: `src/rka_desktop/comm/_vendor/azbil_mfc/*`, `.../taie_temp/*`, `.../balance_serial/*`
- Test: `tests/comm/test_vendor_imports.py`

- [ ] **Step 1: Create package markers**

```bash
mkdir -p src/rka_desktop/comm/_vendor src/rka_desktop/comm/adapters tests/comm
printf '"""RKA multi-device communication layer."""\n' > src/rka_desktop/comm/__init__.py
printf '"""Vendored upstream protocol drivers. See VENDOR.md for provenance."""\n' > src/rka_desktop/comm/_vendor/__init__.py
touch tests/comm/__init__.py
```

- [ ] **Step 2: Copy the azbil-mfc core at the pinned commit**

```bash
TMP=$(mktemp -d)
git clone --quiet https://github.com/kevinalliswell/azbil-mfc "$TMP/azbil"
git -C "$TMP/azbil" checkout --quiet 83ddc491
DST=src/rka_desktop/comm/_vendor/azbil_mfc
mkdir -p "$DST"
for m in bus client protocol constants registers exceptions device_catalog; do
  cp "$TMP/azbil/azbil_mfc/$m.py" "$DST/$m.py"
done
```

- [ ] **Step 3: Write a trimmed azbil `__init__.py` (only the copied modules)**

Create `src/rka_desktop/comm/_vendor/azbil_mfc/__init__.py`:

```python
"""Trimmed vendored copy of azbil_mfc (core CPL driver only).

Upstream: github.com/kevinalliswell/azbil-mfc @83ddc491 (MIT).
Dashboard/mixer/recipe/scheduler/safety modules were intentionally not vendored.
"""
from .bus import RS485Bus
from .client import MQVBusManager, MQVDevice, MQVStatus
from .constants import (
    COMM_8E1,
    COMM_8N2,
    DEFAULT_BAUDRATE,
    FULL_SCALE_COUNTS,
    MODE_CLOSE,
    MODE_CONTROL,
    MODE_OPEN,
)
from .exceptions import (
    CPLChecksumError,
    CPLConnectionError,
    CPLDeviceError,
    CPLError,
    CPLFrameError,
    CPLTimeoutError,
)
from .protocol import build_read_frame, build_write_frame, calculate_checksum, parse_response
from .registers import EEPROMAddress, RAMAddress

__all__ = [
    "RS485Bus",
    "MQVBusManager",
    "MQVDevice",
    "MQVStatus",
    "RAMAddress",
    "EEPROMAddress",
    "build_read_frame",
    "build_write_frame",
    "parse_response",
    "calculate_checksum",
    "CPLError",
    "CPLChecksumError",
    "CPLConnectionError",
    "CPLDeviceError",
    "CPLFrameError",
    "CPLTimeoutError",
    "COMM_8E1",
    "COMM_8N2",
    "DEFAULT_BAUDRATE",
    "MODE_CLOSE",
    "MODE_CONTROL",
    "MODE_OPEN",
    "FULL_SCALE_COUNTS",
]
```

- [ ] **Step 4: Copy the taie-temp-controller core**

```bash
git clone --quiet https://github.com/kevinalliswell/taie-temp-controller "$TMP/taie"
git -C "$TMP/taie" checkout --quiet ab18b921
DST=src/rka_desktop/comm/_vendor/taie_temp
mkdir -p "$DST"
for m in controller modbus_rtu register_addresses __init__; do
  cp "$TMP/taie/src/taie_temp_controller/$m.py" "$DST/$m.py"
done
```

> Note: taie's stock `__init__.py` imports only from `.controller`, whose closure is `modbus_rtu` + `register_addresses` — all copied. No trimming required. Relative imports make the renamed `taie_temp/` directory work.

- [ ] **Step 5: Copy the balance-serial core**

```bash
git clone --quiet https://github.com/kevinalliswell/balance-serial "$TMP/bal"
git -C "$TMP/bal" checkout --quiet 496b7b76
DST=src/rka_desktop/comm/_vendor/balance_serial
mkdir -p "$DST/protocols"
for m in client factory models exceptions __init__; do
  cp "$TMP/bal/src/balance_serial/$m.py" "$DST/$m.py"
done
for m in __init__ base gs_cpa longteng; do
  cp "$TMP/bal/src/balance_serial/protocols/$m.py" "$DST/protocols/$m.py"
done
rm -rf "$TMP"
```

> Note: balance's stock `__init__.py` imports `client, factory, models, protocols.{base,gs_cpa,longteng}` — all copied. `device.py` is not imported by the public API and is intentionally omitted.

- [ ] **Step 6: Write `VENDOR.md`**

Create `src/rka_desktop/comm/_vendor/VENDOR.md`:

```markdown
# Vendored protocol drivers

These are pinned, trimmed copies of upstream protocol libraries. Do not edit them
in place — re-sync from upstream and re-apply trimming instead.

| Package | Upstream | Commit | License | Vendored modules | Omitted |
|---------|----------|--------|---------|------------------|---------|
| `azbil_mfc` | github.com/kevinalliswell/azbil-mfc | 83ddc491 | MIT | bus, client, protocol, constants, registers, exceptions, device_catalog, (trimmed) __init__ | dashboard/, mixer, recipe, scheduler, safety |
| `taie_temp` | github.com/kevinalliswell/taie-temp-controller | ab18b921 | Apache-2.0 | controller, modbus_rtu, register_addresses, __init__ | api, polling, acquisition |
| `balance_serial` | github.com/kevinalliswell/balance-serial | 496b7b76 | (no upstream LICENSE) | client, factory, models, exceptions, protocols/{base,gs_cpa,longteng}, __init__ | device, examples |

## Licensing note

`balance-serial` has no LICENSE file upstream. It is owned by the same owner as this
repository (kevinalliswell); vendoring here is under same-owner authorization. Recommend
adding an explicit LICENSE to the upstream repo. MIT (azbil) and Apache-2.0 (taie) require
retaining their license/notice text; their original LICENSE text is reproduced in
`azbil_mfc/` and `taie_temp/` headers/`LICENSE-*` as applicable.
```

- [ ] **Step 7: Write the vendored-import smoke test**

Create `tests/comm/test_vendor_imports.py`:

```python
"""The vendored driver cores must import with only their copied modules present."""


def test_azbil_public_api_imports():
    from rka_desktop.comm._vendor.azbil_mfc import (
        FULL_SCALE_COUNTS,
        MQVBusManager,
        MQVDevice,
        RS485Bus,
    )

    assert FULL_SCALE_COUNTS == 50000
    assert MQVBusManager is not None
    assert MQVDevice is not None
    assert RS485Bus is not None


def test_taie_public_api_imports():
    from rka_desktop.comm._vendor.taie_temp import (
        TaieTemperatureController,
        create_default_controller,
    )

    assert TaieTemperatureController is not None
    assert create_default_controller is not None


def test_balance_public_api_imports():
    from rka_desktop.comm._vendor.balance_serial import BalanceClient, create_protocol

    assert BalanceClient is not None
    assert create_protocol("gs_cpa") is not None
```

- [ ] **Step 8: Run the smoke test**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/comm/test_vendor_imports.py -v`
Expected: PASS (3 tests). If an `ImportError` names a module, that module was missed in the copy — copy it from the same upstream commit and re-run.

- [ ] **Step 9: Commit**

```bash
git add src/rka_desktop/comm/__init__.py src/rka_desktop/comm/_vendor tests/comm/__init__.py tests/comm/test_vendor_imports.py
git commit -m "chore(comm): vendor azbil-mfc/taie/balance core drivers"
```

---

## Task 2: Comm exceptions, ports, and config

**Files:**
- Create: `src/rka_desktop/comm/exceptions.py`, `src/rka_desktop/comm/ports.py`, `src/rka_desktop/comm/config.py`
- Test: `tests/comm/test_config.py`

- [ ] **Step 1: Write the config test (failing)**

Create `tests/comm/test_config.py`:

```python
from rka_desktop.comm.config import CommConfig, default_mfc_channels


def test_default_channels_have_six_unique_addresses():
    channels = default_mfc_channels()
    addresses = [c.address for c in channels]
    assert len(channels) == 6
    assert len(set(addresses)) == 6


def test_default_channels_cover_legacy_gases():
    gases = {c.gas for c in default_mfc_channels()}
    assert {"N2", "H2", "CO"}.issubset(gases)


def test_commconfig_defaults_to_simulation():
    cfg = CommConfig()
    assert cfg.simulation_mode is True
    assert len(cfg.mfc_channels) == 6
```

- [ ] **Step 2: Run it to verify failure**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/comm/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rka_desktop.comm.config'`

- [ ] **Step 3: Write `exceptions.py`**

Create `src/rka_desktop/comm/exceptions.py`:

```python
from __future__ import annotations


class DeviceCommError(RuntimeError):
    """Raised by a device adapter when a read/write to its device fails."""
```

- [ ] **Step 4: Write `config.py`**

Create `src/rka_desktop/comm/config.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MfcChannelConfig:
    address: int
    gas: str           # e.g. "H2", "N2", "CO", "CO2", "AR", "AIR"
    full_scale_lpm: float


def default_mfc_channels() -> tuple[MfcChannelConfig, ...]:
    """Six MFCs on one RS-485 bus. N2/H2/CO are unique so legacy mapping is deterministic."""
    return (
        MfcChannelConfig(address=1, gas="H2", full_scale_lpm=2.0),
        MfcChannelConfig(address=2, gas="N2", full_scale_lpm=5.0),
        MfcChannelConfig(address=3, gas="CO", full_scale_lpm=2.0),
        MfcChannelConfig(address=4, gas="CO2", full_scale_lpm=2.0),
        MfcChannelConfig(address=5, gas="AR", full_scale_lpm=5.0),
        MfcChannelConfig(address=6, gas="AIR", full_scale_lpm=5.0),
    )


@dataclass(frozen=True)
class CommConfig:
    simulation_mode: bool = True
    # TAIE temperature controller (Modbus RTU)
    temp_port: str = "/dev/tty.usbserial-temp"
    temp_slave_id: int = 1
    temp_baudrate: int = 19200
    # Azbil MFC RS-485 bus (CPL)
    mfc_port: str = "/dev/tty.usbserial-mfc"
    mfc_baudrate: int = 19200
    mfc_channels: tuple[MfcChannelConfig, ...] = field(default_factory=default_mfc_channels)
    # Electronic balance (serial ASCII)
    balance_port: str = "/dev/tty.usbserial-bal"
    balance_protocol: str = "gs_cpa"
    balance_baudrate: int = 9600
```

- [ ] **Step 5: Write `ports.py`**

Create `src/rka_desktop/comm/ports.py`:

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from rka_desktop.models.entities import DeviceSnapshot


@runtime_checkable
class SnapshotSource(Protocol):
    """A data source the AcquisitionWorker can poll. ModbusRtuClient already satisfies this."""

    def connect(self) -> bool: ...
    def close(self) -> None: ...
    def read_snapshot(self) -> DeviceSnapshot: ...


class TemperaturePort(Protocol):
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def read_pv(self) -> float: ...
    def read_sv(self) -> float: ...
    def write_sv(self, value: float) -> None: ...


class MfcBusPort(Protocol):
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def read_all_pv(self) -> dict[int, float]: ...     # {address: L/min}
    def read_all_sp(self) -> dict[int, float]: ...     # {address: L/min}
    def set_flow(self, address: int, lpm: float) -> None: ...
    def gas_type(self, address: int) -> str: ...


class BalancePort(Protocol):
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def read_weight(self) -> float | None: ...
    def tare(self) -> bool: ...
```

- [ ] **Step 6: Run the config test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/comm/test_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add src/rka_desktop/comm/exceptions.py src/rka_desktop/comm/config.py src/rka_desktop/comm/ports.py tests/comm/test_config.py
git commit -m "feat(comm): add device ports, comm config, and error type"
```

---

## Task 3: Simulation adapters

**Files:**
- Create: `src/rka_desktop/comm/adapters/__init__.py`, `src/rka_desktop/comm/adapters/sim_adapters.py`
- Test: `tests/comm/test_sim_adapters.py`

- [ ] **Step 1: Write the sim-adapter tests (failing)**

Create `tests/comm/test_sim_adapters.py`:

```python
from rka_desktop.comm.adapters.sim_adapters import (
    SimBalanceAdapter,
    SimMfcBusAdapter,
    SimTemperatureAdapter,
)
from rka_desktop.comm.config import default_mfc_channels


def test_temperature_pv_approaches_setpoint():
    temp = SimTemperatureAdapter(initial_c=25.0, approach=0.1)
    temp.connect()
    temp.write_sv(900.0)
    assert temp.read_sv() == 900.0
    # one step: 25 + (900 - 25) * 0.1 == 112.5
    assert temp.read_pv() == 112.5


def test_mfc_pv_follows_setpoint_and_reports_gas():
    mfc = SimMfcBusAdapter(default_mfc_channels(), approach=0.2)
    mfc.connect()
    mfc.set_flow(2, 5.0)
    pv = mfc.read_all_pv()
    # one step on address 2: 0 + (5 - 0) * 0.2 == 1.0
    assert pv[2] == 1.0
    assert mfc.gas_type(2) == "N2"
    assert set(mfc.read_all_sp().keys()) == {1, 2, 3, 4, 5, 6}


def test_balance_drifts_and_tares():
    bal = SimBalanceAdapter(initial_g=100.0, drift=0.05)
    bal.connect()
    assert bal.read_weight() == 99.95
    assert bal.tare() is True
    assert bal.read_weight() == 0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/comm/test_sim_adapters.py -v`
Expected: FAIL with `ModuleNotFoundError: ... sim_adapters`

- [ ] **Step 3: Implement the sim adapters**

Create `src/rka_desktop/comm/adapters/__init__.py`:

```python
"""Device adapters: real (driver-backed) and sim (synthetic, hardware-free)."""
```

Create `src/rka_desktop/comm/adapters/sim_adapters.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/comm/test_sim_adapters.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/rka_desktop/comm/adapters/__init__.py src/rka_desktop/comm/adapters/sim_adapters.py tests/comm/test_sim_adapters.py
git commit -m "feat(comm): add simulation device adapters"
```

---

## Task 4: Real (driver-backed) adapters

These wrap the vendored drivers. They take their underlying driver via the constructor (dependency injection) so the unit-conversion/mapping logic is unit-testable with a fake; a `from_config` classmethod builds the real driver. Hardware I/O itself is not unit-tested (covered later only by `compileall`).

**Files:**
- Create: `src/rka_desktop/comm/adapters/azbil_mfc_adapter.py`, `.../taie_temp_adapter.py`, `.../balance_adapter.py`
- Test: `tests/comm/test_real_adapters.py`

- [ ] **Step 1: Write the conversion/mapping tests with fakes (failing)**

Create `tests/comm/test_real_adapters.py`:

```python
from rka_desktop.comm.adapters.azbil_mfc_adapter import AzbilMfcAdapter
from rka_desktop.comm.adapters.balance_adapter import BalanceAdapter
from rka_desktop.comm.adapters.taie_temp_adapter import TaieTempAdapter
from rka_desktop.comm.config import default_mfc_channels
from rka_desktop.comm.exceptions import DeviceCommError


class _FakeBusManager:
    """Stands in for azbil MQVBusManager. PV/SP are in raw counts (0..FULL_SCALE_COUNTS)."""

    def __init__(self) -> None:
        self.pv_counts = {1: 25000, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
        self.written: list[tuple[int, int, int]] = []  # (address, sp_number, counts)
        self.bus = self

    opened = False
    closed = False

    def open(self) -> None:
        type(self).opened = True

    def close(self) -> None:
        type(self).closed = True

    def get_device(self, address):
        manager = self

        class _Dev:
            def read_pv(self_inner) -> int:
                return manager.pv_counts[address]

            def write_sp(self_inner, sp_number: int, value: int) -> None:
                manager.written.append((address, sp_number, value))

        return _Dev()

    def read_all_pv(self) -> dict[int, int]:
        return dict(self.pv_counts)


def test_azbil_counts_convert_to_lpm():
    channels = default_mfc_channels()  # address 1 == H2, full_scale 2.0 L/min
    adapter = AzbilMfcAdapter(_FakeBusManager(), channels)
    # 25000 / 50000 * 2.0 == 1.0 L/min
    assert adapter.read_all_pv()[1] == 1.0
    assert adapter.gas_type(1) == "H2"


def test_azbil_set_flow_converts_lpm_to_counts():
    channels = default_mfc_channels()  # address 2 == N2, full_scale 5.0 L/min
    fake = _FakeBusManager()
    adapter = AzbilMfcAdapter(fake, channels)
    adapter.set_flow(2, 2.5)  # 2.5 / 5.0 * 50000 == 25000 counts
    assert fake.written == [(2, 1, 25000)]


class _FakeController:
    def __init__(self) -> None:
        self._sv = 100.0

    def open(self) -> None: ...

    def close(self) -> None: ...

    def read_pv(self) -> float:
        return 850.0

    def read_sv(self) -> float:
        return self._sv

    def write_sv(self, value: float) -> float:
        self._sv = value
        return value


def test_taie_adapter_delegates():
    adapter = TaieTempAdapter(_FakeController())
    adapter.connect()
    assert adapter.read_pv() == 850.0
    adapter.write_sv(900.0)
    assert adapter.read_sv() == 900.0


class _FakeMessage:
    def __init__(self, weight):
        self.weight = weight


class _FakeBalanceClient:
    def __init__(self, weight=88.0, raises=False):
        self._weight = weight
        self._raises = raises

    def open(self) -> None: ...

    def initialize_device(self) -> None: ...

    def close(self) -> None: ...

    def read_message(self):
        if self._raises:
            raise OSError("port closed")
        return _FakeMessage(self._weight)


def test_balance_adapter_reads_weight():
    adapter = BalanceAdapter(_FakeBalanceClient(weight=88.0))
    assert adapter.read_weight() == 88.0


def test_balance_adapter_wraps_driver_errors():
    adapter = BalanceAdapter(_FakeBalanceClient(raises=True))
    try:
        adapter.read_weight()
    except DeviceCommError:
        return
    raise AssertionError("expected DeviceCommError")
```

- [ ] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/comm/test_real_adapters.py -v`
Expected: FAIL with `ModuleNotFoundError: ... azbil_mfc_adapter`

- [ ] **Step 3: Implement `azbil_mfc_adapter.py`**

Create `src/rka_desktop/comm/adapters/azbil_mfc_adapter.py`:

```python
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
```

> Note: the test's `_FakeBusManager` does not implement `read_sp`, so `read_all_sp` is exercised only by `MultiDeviceGateway` via the sim adapter in later tasks. The real path is covered by `compileall`.

- [ ] **Step 4: Implement `taie_temp_adapter.py`**

Create `src/rka_desktop/comm/adapters/taie_temp_adapter.py`:

```python
from __future__ import annotations

from rka_desktop.comm.exceptions import DeviceCommError


class TaieTempAdapter:
    """Real temperature adapter wrapping a vendored TaieTemperatureController."""

    def __init__(self, controller) -> None:
        self._ctrl = controller

    @classmethod
    def from_config(cls, cfg) -> "TaieTempAdapter":
        from rka_desktop.comm._vendor.taie_temp import create_default_controller

        controller = create_default_controller(
            port=cfg.temp_port,
            slave_id=cfg.temp_slave_id,
            baudrate=cfg.temp_baudrate,
        )
        return cls(controller)

    def connect(self) -> None:
        try:
            self._ctrl.open()
        except Exception as exc:  # noqa: BLE001
            raise DeviceCommError(f"temperature controller open failed: {exc}") from exc

    def close(self) -> None:
        try:
            self._ctrl.close()
        except Exception:  # noqa: BLE001
            pass

    def read_pv(self) -> float:
        try:
            return float(self._ctrl.read_pv())
        except Exception as exc:  # noqa: BLE001
            raise DeviceCommError(f"temperature read_pv failed: {exc}") from exc

    def read_sv(self) -> float:
        try:
            return float(self._ctrl.read_sv())
        except Exception as exc:  # noqa: BLE001
            raise DeviceCommError(f"temperature read_sv failed: {exc}") from exc

    def write_sv(self, value: float) -> None:
        try:
            self._ctrl.write_sv(float(value))
        except Exception as exc:  # noqa: BLE001
            raise DeviceCommError(f"temperature write_sv failed: {exc}") from exc
```

- [ ] **Step 5: Implement `balance_adapter.py`**

Create `src/rka_desktop/comm/adapters/balance_adapter.py`:

```python
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
```

> Note: `PortSettings` is exported from balance's `__init__.py` (confirmed in vendoring). `from_config` imports are lazy so the vendored serial code loads only in real mode.

- [ ] **Step 6: Run the real-adapter tests to verify pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/comm/test_real_adapters.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Commit**

```bash
git add src/rka_desktop/comm/adapters/azbil_mfc_adapter.py src/rka_desktop/comm/adapters/taie_temp_adapter.py src/rka_desktop/comm/adapters/balance_adapter.py tests/comm/test_real_adapters.py
git commit -m "feat(comm): add driver-backed real device adapters"
```

---

## Task 5: MultiDeviceSnapshot + MultiDeviceGateway

**Files:**
- Modify: `src/rka_desktop/models/entities.py` (append `MultiDeviceSnapshot`)
- Create: `src/rka_desktop/comm/multi_device_gateway.py`
- Test: `tests/comm/test_multi_device_gateway.py`

- [ ] **Step 1: Write the gateway tests (failing)**

Create `tests/comm/test_multi_device_gateway.py`:

```python
from rka_desktop.comm.adapters.sim_adapters import (
    SimBalanceAdapter,
    SimMfcBusAdapter,
    SimTemperatureAdapter,
)
from rka_desktop.comm.config import CommConfig, default_mfc_channels
from rka_desktop.comm.exceptions import DeviceCommError
from rka_desktop.comm.multi_device_gateway import MultiDeviceGateway
from rka_desktop.comm.ports import SnapshotSource
from rka_desktop.models.entities import DeviceSnapshot, MultiDeviceSnapshot


def _sim_gateway() -> MultiDeviceGateway:
    channels = default_mfc_channels()
    return MultiDeviceGateway(
        SimTemperatureAdapter(),
        SimMfcBusAdapter(channels),
        SimBalanceAdapter(),
        channels,
    )


def test_gateway_is_a_snapshot_source():
    gw = _sim_gateway()
    assert isinstance(gw, SnapshotSource)


def test_read_snapshot_returns_legacy_shape():
    gw = _sim_gateway()
    gw.connect()
    snap = gw.read_snapshot()
    assert isinstance(snap, DeviceSnapshot)
    assert snap.pressure_mpa == 0.0
    assert snap.alarm_word == 0


def test_read_multi_snapshot_maps_gases_by_type():
    channels = default_mfc_channels()
    mfc = SimMfcBusAdapter(channels)
    mfc.set_flow(2, 5.0)  # address 2 == N2
    gw = MultiDeviceGateway(SimTemperatureAdapter(), mfc, SimBalanceAdapter(), channels)
    gw.connect()
    snap = gw.read_snapshot()
    # N2 channel (address 2) stepped to 1.0; H2 (addr1) and CO (addr3) still 0.0
    assert snap.n2_lpm == 1.0
    assert snap.h2_lpm == 0.0
    assert snap.co_lpm == 0.0


def test_degraded_device_is_reported_and_last_value_held():
    class _BrokenTemp:
        def connect(self) -> None: ...

        def close(self) -> None: ...

        def read_pv(self) -> float:
            raise DeviceCommError("temp down")

        def read_sv(self) -> float:
            return 0.0

        def write_sv(self, value: float) -> None: ...

    channels = default_mfc_channels()
    gw = MultiDeviceGateway(_BrokenTemp(), SimMfcBusAdapter(channels), SimBalanceAdapter(), channels)
    gw.connect()
    multi = gw.read_multi_snapshot()
    assert isinstance(multi, MultiDeviceSnapshot)
    assert "temp" in multi.degraded_devices
    assert multi.temperatures_c == (0.0,)  # last-good fallback


def test_from_config_builds_sim_gateway():
    gw = MultiDeviceGateway.from_config(CommConfig(simulation_mode=True))
    assert gw.connect() is True
    assert isinstance(gw.read_snapshot(), DeviceSnapshot)
```

- [ ] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/comm/test_multi_device_gateway.py -v`
Expected: FAIL with `ImportError: cannot import name 'MultiDeviceSnapshot'`

- [ ] **Step 3: Append `MultiDeviceSnapshot` to `entities.py`**

Add to the end of `src/rka_desktop/models/entities.py`:

```python
@dataclass(frozen=True)
class MultiDeviceSnapshot:
    temperatures_c: tuple[float, ...]
    mfc_flows_lpm: dict[int, float]
    mfc_setpoints_lpm: dict[int, float]
    weight_g: float | None
    degraded_devices: tuple[str, ...]
```

- [ ] **Step 4: Implement `multi_device_gateway.py`**

Create `src/rka_desktop/comm/multi_device_gateway.py`:

```python
from __future__ import annotations

import logging
from typing import Sequence

from rka_desktop.comm.config import CommConfig, MfcChannelConfig
from rka_desktop.comm.exceptions import DeviceCommError
from rka_desktop.comm.ports import BalancePort, MfcBusPort, TemperaturePort
from rka_desktop.models.entities import DeviceSnapshot, MultiDeviceSnapshot

logger = logging.getLogger(__name__)

_LEGACY_GASES = ("N2", "H2", "CO")


class MultiDeviceGateway:
    """Aggregates temperature + 6 MFCs + balance and exposes a legacy SnapshotSource."""

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
        self._temp.connect()
        self._mfc.connect()
        self._balance.connect()
        return True

    def close(self) -> None:
        for device in (self._temp, self._mfc, self._balance):
            try:
                device.close()
            except Exception:  # noqa: BLE001
                pass

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
```

- [ ] **Step 5: Run the gateway tests to verify pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/comm/test_multi_device_gateway.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add src/rka_desktop/models/entities.py src/rka_desktop/comm/multi_device_gateway.py tests/comm/test_multi_device_gateway.py
git commit -m "feat(comm): add MultiDeviceGateway and MultiDeviceSnapshot"
```

---

## Task 6: Wire the gateway into the acquisition seam

**Files:**
- Modify: `src/rka_desktop/services/acquisition_service.py` (widen the `client` type hint only)
- Test: `tests/comm/test_acquisition_seam.py`

- [ ] **Step 1: Write the seam test (failing)**

Create `tests/comm/test_acquisition_seam.py`:

```python
from rka_desktop.comm.config import CommConfig
from rka_desktop.comm.multi_device_gateway import MultiDeviceGateway
from rka_desktop.comm.ports import SnapshotSource
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.models.entities import DeviceSnapshot


def test_legacy_client_satisfies_snapshot_source():
    client = ModbusRtuClient(serial_port="sim", baudrate=9600, unit_id=1, simulation_mode=True)
    assert isinstance(client, SnapshotSource)


def test_gateway_drives_repeated_snapshots():
    gw = MultiDeviceGateway.from_config(CommConfig(simulation_mode=True))
    gw.connect()
    snapshots = [gw.read_snapshot() for _ in range(5)]
    assert len(snapshots) == 5
    assert all(isinstance(s, DeviceSnapshot) for s in snapshots)


def test_acquisition_worker_accepts_gateway_type():
    # The worker module must import without requiring a concrete ModbusRtuClient.
    import inspect

    from rka_desktop.services import acquisition_service

    source = inspect.getsource(acquisition_service)
    assert "SnapshotSource" in source  # type hint widened to the protocol
```

- [ ] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/comm/test_acquisition_seam.py -v`
Expected: FAIL on `test_acquisition_worker_accepts_gateway_type` (no `SnapshotSource` in source)

- [ ] **Step 3: Widen the `AcquisitionWorker` type hint**

In `src/rka_desktop/services/acquisition_service.py`:

Change the import line:
```python
from rka_desktop.core.modbus_client import ModbusRtuClient
```
to:
```python
from rka_desktop.comm.ports import SnapshotSource
```

Change the constructor parameter annotation:
```python
        client: ModbusRtuClient,
```
to:
```python
        client: SnapshotSource,
```

> The body only calls `client.read_snapshot()`, so no other change is needed. `ModbusRtuClient` still works because it structurally satisfies `SnapshotSource`.

- [ ] **Step 4: Run the seam tests to verify pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/comm/test_acquisition_seam.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the whole suite to confirm nothing regressed**

Run: `QT_QPA_PLATFORM=offscreen pytest -q`
Expected: PASS (all existing tests + new comm tests). In particular `tests/test_acquisition_service.py` still passes.

- [ ] **Step 6: Commit**

```bash
git add src/rka_desktop/services/acquisition_service.py tests/comm/test_acquisition_seam.py
git commit -m "feat(comm): consume gateway via SnapshotSource seam in acquisition"
```

---

## Task 7: Single-source version

**Files:**
- Modify: `src/rka_desktop/__init__.py` (`__version__` -> `0.2.0`)
- Modify: `pyproject.toml` (dynamic version)
- Modify: `scripts/checks/verify_tag_version.py` (read package version, not pyproject literal)
- Test: `tests/test_version_single_source.py`

- [ ] **Step 1: Write the version test (failing)**

Create `tests/test_version_single_source.py`:

```python
import re
from pathlib import Path

import rka_desktop


def test_package_version_is_bumped():
    assert rka_desktop.__version__ == "0.2.0"


def test_pyproject_uses_dynamic_version():
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert 'version = {attr = "rka_desktop.__version__"}' in text
    # No hardcoded literal project version remains.
    assert not re.search(r'^version\s*=\s*"\d', text, re.MULTILINE)
```

- [ ] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_version_single_source.py -v`
Expected: FAIL (version is `0.1.0`; pyproject still has literal version)

- [ ] **Step 3: Bump the package version**

Replace `src/rka_desktop/__init__.py` contents with:

```python
__all__ = ["__version__"]
__version__ = "0.2.0"
```

- [ ] **Step 4: Make `pyproject.toml` use a dynamic version**

In `pyproject.toml`, under `[project]`, replace:
```toml
version = "0.1.0"
```
with:
```toml
dynamic = ["version"]
```

Add a new section immediately after the `[build-system]` block (or anywhere top-level):
```toml
[tool.setuptools.dynamic]
version = {attr = "rka_desktop.__version__"}
```

- [ ] **Step 5: Update `verify_tag_version.py` to read the package version**

Replace the `read_project_version` function body in `scripts/checks/verify_tag_version.py` so it reads `__version__` from the package source (avoids importing dependencies):

```python
def read_project_version(_pyproject_path: Path) -> str:
    init_path = Path("src/rka_desktop/__init__.py")
    content = init_path.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not find __version__ in src/rka_desktop/__init__.py")
    return match.group(1)
```

> The function keeps its signature (called as `read_project_version(Path("pyproject.toml"))`) so `main()` is unchanged.

- [ ] **Step 6: Run the version test + an editable reinstall check**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_version_single_source.py -v`
Expected: PASS (2 tests)

Run: `pip install -e . >/dev/null 2>&1 && python -c "import rka_desktop, importlib.metadata as m; print(rka_desktop.__version__, m.version('rka-desktop'))"`
Expected: prints `0.2.0 0.2.0` (build backend resolves the dynamic version)

- [ ] **Step 7: Commit**

```bash
git add src/rka_desktop/__init__.py pyproject.toml scripts/checks/verify_tag_version.py tests/test_version_single_source.py
git commit -m "build(release): make rka_desktop.__version__ the single version source"
```

---

## Task 8: CHANGELOG + release bump script

**Files:**
- Create: `CHANGELOG.md`
- Create: `scripts/release.py`
- Create: `scripts/checks/verify_version_sync.py`
- Test: `tests/test_release_tooling.py`

- [ ] **Step 1: Write the release-tooling test (failing)**

Create `tests/test_release_tooling.py`:

```python
import subprocess
import sys
from pathlib import Path


def test_changelog_top_version_matches_package():
    import rka_desktop

    text = Path("CHANGELOG.md").read_text(encoding="utf-8")
    # First "## [x.y.z]" heading after Unreleased must equal the package version.
    import re

    versions = re.findall(r"^##\s*\[(\d+\.\d+\.\d+)\]", text, re.MULTILINE)
    assert versions, "no released version section found in CHANGELOG"
    assert versions[0] == rka_desktop.__version__


def test_verify_version_sync_passes():
    result = subprocess.run(
        [sys.executable, "scripts/checks/verify_version_sync.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_release_script_extract_notes():
    result = subprocess.run(
        [sys.executable, "scripts/release.py", "notes", "0.2.0"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "multi-device" in result.stdout.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_release_tooling.py -v`
Expected: FAIL (no CHANGELOG.md / scripts)

- [ ] **Step 3: Write `CHANGELOG.md`**

Create `CHANGELOG.md`:

```markdown
# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-06-27

### Added
- Simulation-first multi-device communication layer (`rka_desktop.comm`): vendored Azbil
  MFC (6 channels, CPL), TAIE temperature controller (Modbus RTU), and electronic balance
  (gs_cpa/longteng) drivers behind narrow RKA ports.
- `MultiDeviceGateway` implementing the `SnapshotSource` seam, mapping multi-device
  readings onto the legacy `DeviceSnapshot` (N2/H2/CO selected by gas type) and exposing a
  richer `MultiDeviceSnapshot`.
- Simulation adapters for all three device types (hardware-free, deterministic) with tests.

### Changed
- `AcquisitionWorker` now accepts any `SnapshotSource` (the legacy `ModbusRtuClient` still
  works unchanged).
- Version is now single-sourced from `rka_desktop.__version__`; `pyproject.toml` reads it
  dynamically.

### Build
- Added `CHANGELOG.md`, `scripts/release.py` bump/notes helper, and a version-sync CI check.
- `release.yml` now publishes the matching CHANGELOG section as release notes.
```

- [ ] **Step 4: Write `scripts/checks/verify_version_sync.py`**

Create `scripts/checks/verify_version_sync.py`:

```python
from __future__ import annotations

import re
import sys
from pathlib import Path


def read_package_version() -> str:
    content = Path("src/rka_desktop/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not find __version__ in src/rka_desktop/__init__.py")
    return match.group(1)


def read_changelog_top_version() -> str:
    content = Path("CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"^##\s*\[(\d+\.\d+\.\d+)\]", content, re.MULTILINE)
    if not versions:
        raise RuntimeError("No released version section found in CHANGELOG.md")
    return versions[0]


def main() -> int:
    package = read_package_version()
    changelog = read_changelog_top_version()
    if package != changelog:
        raise RuntimeError(
            f"Version mismatch: __version__={package} but CHANGELOG top={changelog}"
        )
    print(f"version sync ok: package={package}, changelog={changelog}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
```

- [ ] **Step 5: Write `scripts/release.py`**

Create `scripts/release.py`:

```python
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

INIT_PATH = Path("src/rka_desktop/__init__.py")
CHANGELOG_PATH = Path("CHANGELOG.md")


def read_version() -> str:
    content = INIT_PATH.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not find __version__")
    return match.group(1)


def write_version(new_version: str) -> None:
    content = INIT_PATH.read_text(encoding="utf-8")
    content = re.sub(
        r'^__version__\s*=\s*"[^"]+"',
        f'__version__ = "{new_version}"',
        content,
        flags=re.MULTILINE,
    )
    INIT_PATH.write_text(content, encoding="utf-8")


def extract_notes(version: str) -> str:
    content = CHANGELOG_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^##\s*\[{re.escape(version)}\][^\n]*\n(.*?)(?=^##\s*\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        raise RuntimeError(f"No CHANGELOG section for version {version}")
    return match.group(1).strip()


def promote_unreleased(version: str) -> None:
    """Move [Unreleased] content into a new dated [version] section."""
    content = CHANGELOG_PATH.read_text(encoding="utf-8")
    today = date.today().isoformat()
    new_block = f"## [Unreleased]\n\n## [{version}] - {today}\n"
    content = re.sub(r"^##\s*\[Unreleased\]\s*\n", new_block, content, count=1, flags=re.MULTILINE)
    CHANGELOG_PATH.write_text(content, encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="RKA release helper")
    sub = parser.add_subparsers(dest="command", required=True)

    bump = sub.add_parser("bump", help="set version and promote Unreleased")
    bump.add_argument("version")

    notes = sub.add_parser("notes", help="print CHANGELOG notes for a version")
    notes.add_argument("version")

    sub.add_parser("current", help="print the current version")

    args = parser.parse_args(argv)

    if args.command == "current":
        print(read_version())
    elif args.command == "notes":
        print(extract_notes(args.version))
    elif args.command == "bump":
        write_version(args.version)
        promote_unreleased(args.version)
        print(f"bumped to {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 6: Run the release-tooling tests to verify pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_release_tooling.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add CHANGELOG.md scripts/release.py scripts/checks/verify_version_sync.py tests/test_release_tooling.py
git commit -m "build(release): add CHANGELOG, release bump/notes script, version-sync check"
```

---

## Task 9: Upgrade the CI and release workflows

**Files:**
- Modify: `.github/workflows/release.yml` (extract CHANGELOG notes)
- Modify: `.github/workflows/ci.yml` (run the version-sync check)

- [ ] **Step 1: Add the version-sync check to CI**

In `.github/workflows/ci.yml`, after the `Compile sources` step, append:

```yaml
      - name: Verify version sync
        run: python scripts/checks/verify_version_sync.py
```

- [ ] **Step 2: Upgrade `release.yml` to publish CHANGELOG notes**

In `.github/workflows/release.yml`, replace the `Create GitHub Release` step (the
`softprops/action-gh-release@v2` step with `generate_release_notes: true`) with:

```yaml
      - name: Extract release notes
        env:
          GITHUB_REF_NAME: ${{ github.ref_name }}
        run: |
          VERSION="${GITHUB_REF_NAME#v}"
          python scripts/release.py notes "$VERSION" > RELEASE_NOTES.md
          cat RELEASE_NOTES.md

      - name: Verify version sync
        run: python scripts/checks/verify_version_sync.py

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          body_path: RELEASE_NOTES.md
```

- [ ] **Step 3: Lint the workflow YAML locally**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"`
Expected: prints `yaml ok` (if PyYAML is unavailable, run `pip install pyyaml` first)

- [ ] **Step 4: Dry-run the notes extraction exactly as the workflow will**

Run: `VERSION=0.2.0; python scripts/release.py notes "$VERSION" | head -5`
Expected: prints the `### Added` notes for 0.2.0 (non-empty)

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/release.yml
git commit -m "ci: run version-sync check and publish CHANGELOG release notes"
```

---

## Task 10: README reconcile + full verification

**Files:**
- Modify: `README.md` (version wording references the single source)
- Test: full suite

- [ ] **Step 1: Reconcile the README version wording**

In `README.md`, the capability section currently reads `## 2. 当前能力（v1.1.0）`. Change the
heading to remove the stale hardcoded version and point at the changelog:

Replace:
```markdown
## 2. 当前能力（v1.1.0）
```
with:
```markdown
## 2. 当前能力

> 版本以 `rka_desktop.__version__`（当前 0.2.0）为准，变更详见 [CHANGELOG.md](CHANGELOG.md)。
```

Add one bullet to the capability list documenting the new layer:
```markdown
- 新增仿真优先的多设备通讯层（6× Azbil MFC + TAIE 温控 + 电子天平），经 `MultiDeviceGateway` 以 `SnapshotSource` 接入现有采集链路
```

- [ ] **Step 2: Run the complete test suite headless**

Run: `QT_QPA_PLATFORM=offscreen pytest -q`
Expected: PASS (all tests; no failures, no errors)

- [ ] **Step 3: Compile all sources (matches CI)**

Run: `python -m compileall src tests scripts`
Expected: no errors

- [ ] **Step 4: Run both repo checks the way CI/release will**

Run: `python scripts/checks/verify_version_sync.py`
Expected: `version sync ok: package=0.2.0, changelog=0.2.0`

Run: `GITHUB_REF_NAME=v0.2.0 python scripts/checks/verify_tag_version.py`
Expected: `version check ok: tag=0.2.0, ...`

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: reconcile README version wording with single source"
```

- [ ] **Step 6: Push the branch and open the PR**

```bash
git push -u origin feat/multi-device-comm-layer
gh pr create --base main --head feat/multi-device-comm-layer \
  --title "feat(comm): simulation-first multi-device comm layer + release automation" \
  --body "$(cat <<'EOF'
## Summary
Adds a simulation-first multi-device communication layer to RKA and supporting release automation.

- Vendored, commit-pinned protocol drivers under `src/rka_desktop/comm/_vendor/` (azbil-mfc MIT @83ddc491, taie Apache-2.0 @ab18b921, balance-serial @496b7b76 — see `_vendor/VENDOR.md`).
- RKA narrow `ports` + `real`/`sim` adapters for 6× MFC, TAIE temperature controller, and electronic balance.
- `MultiDeviceGateway` implements the `SnapshotSource` seam and maps onto the legacy `DeviceSnapshot` (N2/H2/CO by gas type); richer data via `MultiDeviceSnapshot`.
- `AcquisitionWorker` consumes the gateway unchanged (type hint widened to `SnapshotSource`).
- Single-source versioning (`rka_desktop.__version__`), `CHANGELOG.md`, `scripts/release.py`, version-sync CI check, and an upgraded `release.yml` that publishes CHANGELOG notes. Version bumped to 0.2.0.

## Scope / non-scope
- In scope: comm layer working fully in **simulation** with tests; no hardware required to merge.
- Out of scope (follow-up): DB schema/UI reshape for multi-device, real-device commissioning, exponential-backoff reconnect.

## Testing
- `QT_QPA_PLATFORM=offscreen pytest -q` — all green.
- `python -m compileall src tests scripts` — clean.
- `python scripts/checks/verify_version_sync.py` and `verify_tag_version.py` — pass.

## Provenance / licensing
- balance-serial has no upstream LICENSE; vendored under same-owner authorization (noted in `_vendor/VENDOR.md`).

Design spec: `docs/superpowers/specs/2026-06-27-multi-device-comm-layer-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
Expected: PR created against `kevinalliswell/RKA-3000-desktop:main`.

---

## Self-Review notes (for the implementer)

- **Spec coverage:** Every spec section maps to a task — vendoring+VENDOR.md (T1), ports/config/exceptions (T2), sim adapters (T3), real adapters (T4), gateway+MultiDeviceSnapshot+legacy mapping (T5), SnapshotSource seam (T6), single-source version (T7), CHANGELOG+release script (T8), workflows (T9), README+PR (T10).
- **Degraded behavior:** Implemented in `MultiDeviceGateway.read_multi_snapshot` and tested in T5 Step 1.
- **Type consistency:** Port method names (`read_pv`, `read_sv`, `write_sv`, `read_all_pv`, `read_all_sp`, `set_flow`, `gas_type`, `read_weight`, `tare`, `connect`, `close`, `read_snapshot`) are used identically across adapters (T3/T4), gateway (T5), and tests. `MultiDeviceSnapshot` fields (`temperatures_c`, `mfc_flows_lpm`, `mfc_setpoints_lpm`, `weight_g`, `degraded_devices`) match between `entities.py` (T5 Step 3) and the gateway/tests.
- **No literal project version left:** T7 test asserts the regex finds no `^version = "…"` literal once dynamic.
```
