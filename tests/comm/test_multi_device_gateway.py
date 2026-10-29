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
    mfc.set_flow(2, 5.0)  # address 2 == N2; PV after one read = 5.0 * approach(0.2) = 1.0
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
    assert multi.temperatures_c == (None,)  # no fabricated zero before a first valid reading
    assert "temp" not in multi.last_success_at


def test_from_config_builds_sim_gateway():
    gw = MultiDeviceGateway.from_config(CommConfig(simulation_mode=True))
    assert gw.connect() is True
    assert isinstance(gw.read_snapshot(), DeviceSnapshot)


class _ToggleMfc:
    """MFC port fake that can be flipped to fail after first good read."""

    def __init__(self) -> None:
        self.fail = False
        self._pv = {a: 0.0 for a in range(1, 7)}
        self._pv[2] = 1.0
        self._sp = {a: 0.0 for a in range(1, 7)}

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def read_all_pv(self) -> dict[int, float]:
        if self.fail:
            raise DeviceCommError("mfc down")
        return dict(self._pv)

    def read_all_sp(self) -> dict[int, float]:
        if self.fail:
            raise DeviceCommError("mfc down")
        return dict(self._sp)

    def set_flow(self, address: int, lpm: float) -> None:
        self._sp[address] = lpm

    def gas_type(self, address: int) -> str:
        return "N2"


def test_degraded_mfc_keeps_last_flows():
    channels = default_mfc_channels()
    mfc = _ToggleMfc()
    gw = MultiDeviceGateway(SimTemperatureAdapter(), mfc, SimBalanceAdapter(), channels)
    gw.connect()
    first = gw.read_multi_snapshot()
    assert first.mfc_flows_lpm[2] == 1.0
    mfc.fail = True
    second = gw.read_multi_snapshot()
    assert "mfc:2" in second.degraded_devices
    assert second.mfc_flows_lpm[2] == 1.0  # last-good retained


def test_missing_one_mfc_channel_marks_only_that_channel_stale():
    channels = default_mfc_channels()
    mfc = _ToggleMfc()
    gw = MultiDeviceGateway(SimTemperatureAdapter(), mfc, SimBalanceAdapter(), channels)
    gw.connect()
    gw.read_multi_snapshot()
    mfc._pv.pop(2)
    snapshot = gw.read_multi_snapshot()
    assert snapshot.mfc_flows_lpm[2] == 1.0
    assert snapshot.degraded_devices == ("mfc:2",)
    assert "mfc:2" in snapshot.last_success_at


def test_first_failed_balance_read_has_no_fabricated_weight():
    channels = default_mfc_channels()
    balance = _ToggleBalance()
    balance.fail = True
    gw = MultiDeviceGateway(SimTemperatureAdapter(), SimMfcBusAdapter(channels), balance, channels)
    gw.connect()
    snapshot = gw.read_multi_snapshot()
    assert snapshot.weight_g is None
    assert "balance" in snapshot.degraded_devices


class _ToggleBalance:
    def __init__(self) -> None:
        self.fail = False

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def read_weight(self) -> float | None:
        if self.fail:
            raise DeviceCommError("balance down")
        return 42.0

    def tare(self) -> bool:
        return True


def test_degraded_balance_keeps_last_weight():
    channels = default_mfc_channels()
    bal = _ToggleBalance()
    gw = MultiDeviceGateway(SimTemperatureAdapter(), SimMfcBusAdapter(channels), bal, channels)
    gw.connect()
    first = gw.read_multi_snapshot()
    assert first.weight_g == 42.0
    bal.fail = True
    second = gw.read_multi_snapshot()
    assert "balance" in second.degraded_devices
    assert second.weight_g == 42.0


def test_connect_failure_is_isolated_and_retryable():
    channels = default_mfc_channels()
    closed = {"temp": False}

    class _OkTemp:
        def connect(self) -> None: ...

        def close(self) -> None:
            closed["temp"] = True

        def read_pv(self) -> float:
            return 0.0

        def read_sv(self) -> float:
            return 0.0

        def write_sv(self, value: float) -> None: ...

    class _FailingMfc:
        fail = True

        def connect(self) -> None:
            if self.fail:
                raise DeviceCommError("mfc connect fail")

        def close(self) -> None: ...

        def read_all_pv(self) -> dict[int, float]:
            return {address: 0.0 for address in range(1, 7)}

        def read_all_sp(self) -> dict[int, float]:
            return {address: 0.0 for address in range(1, 7)}

        def set_flow(self, address: int, lpm: float) -> None: ...

        def gas_type(self, address: int) -> str:
            return "N2"

    mfc = _FailingMfc()
    gw = MultiDeviceGateway(_OkTemp(), mfc, SimBalanceAdapter(), channels)
    assert gw.connect() is False
    first = gw.read_multi_snapshot()
    assert first.temperatures_c == (0.0,)
    assert first.weight_g is not None
    assert "mfc:1" in first.degraded_devices
    assert "mfc connect fail" in first.errors["mfc:1"]
    assert closed["temp"] is False
    mfc.fail = False
    assert gw.connect() is True
    second = gw.read_multi_snapshot()
    assert not any(name.startswith("mfc:") for name in second.degraded_devices)
    gw.close()
    assert closed["temp"] is True
