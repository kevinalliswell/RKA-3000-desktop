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
