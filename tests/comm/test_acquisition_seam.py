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
