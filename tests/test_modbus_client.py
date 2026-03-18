from rka_desktop.core.modbus_client import ModbusConnectError, ModbusReadError, ModbusRtuClient
from rka_desktop.core.registers import RegisterField


class _FakeResponse:
    def __init__(self, registers, is_error=False):
        self.registers = registers
        self._is_error = is_error

    def isError(self):
        return self._is_error


class _FakeSerialClient:
    def __init__(self, register_map):
        self._register_map = register_map

    def read_holding_registers(self, address, count, slave):
        if address not in self._register_map:
            return _FakeResponse([], is_error=True)
        registers = self._register_map[address]
        return _FakeResponse(registers[:count], is_error=False)

    def close(self):
        return None


def test_register_field_decodes_scaled_u16():
    field = RegisterField(name="temperature_c", address=0x0001, scale=10.0)
    assert field.decode([9150]) == 915.0


def test_register_field_decodes_signed_int32():
    field = RegisterField(name="weight_g", address=0x0010, count=2, scale=1000.0, signed=True)
    assert field.decode([0x0001, 0x86A0]) == 100.0


def test_simulation_mode_returns_snapshot():
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)
    snapshot = client.read_snapshot()
    assert snapshot.temperature_c > 0
    assert snapshot.weight_g > 0
    assert isinstance(snapshot.alarm_word, int)


def test_hardware_snapshot_uses_register_map():
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=False)
    client._client = _FakeSerialClient(
        {
            0x0001: [9150],
            0x0010: [0x0001, 0x86A0],
            0x0040: [20],
            0x0020: [450],
            0x0021: [120],
            0x0022: [80],
            0x0050: [2],
        }
    )

    snapshot = client.read_snapshot()

    assert snapshot.temperature_c == 915.0
    assert snapshot.weight_g == 100.0
    assert snapshot.pressure_mpa == 0.02
    assert snapshot.n2_lpm == 4.5
    assert snapshot.h2_lpm == 1.2
    assert snapshot.co_lpm == 0.8
    assert snapshot.alarm_word == 2


def test_hardware_read_raises_classified_error():
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=False)
    client._client = _FakeSerialClient({})

    try:
        client.read_snapshot()
    except ModbusReadError:
        assert True
    else:
        assert False, "expected ModbusReadError"


def test_connect_sets_classified_error_when_driver_missing(monkeypatch):
    import rka_desktop.core.modbus_client as modbus_module

    monkeypatch.setattr(modbus_module, "ModbusSerialClient", None)
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=False)

    assert client.connect() is False
    assert isinstance(client.last_error, ModbusConnectError)
