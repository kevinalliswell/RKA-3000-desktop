from rka_desktop.core.modbus_client import ModbusConnectError, ModbusReadError, ModbusRtuClient, ModbusWriteError
from rka_desktop.core.registers import RegisterField


class _FakeResponse:
    def __init__(self, registers, is_error=False):
        self.registers = registers
        self._is_error = is_error

    def isError(self):
        return self._is_error


class _FakeSerialClient:
    def __init__(self, register_map, fail_addresses=None):
        self._register_map = register_map
        self._fail_counts = {address: 1 for address in (fail_addresses or [])}
        self.writes = []

    def read_holding_registers(self, address, count, slave):
        if address not in self._register_map:
            return _FakeResponse([], is_error=True)
        registers = self._register_map[address]
        return _FakeResponse(registers[:count], is_error=False)

    def write_register(self, address, value, slave):
        self.writes.append((address, value, slave))
        is_error = self._fail_counts.get(address, 0) > 0
        if is_error:
            self._fail_counts[address] -= 1
        return _FakeResponse([], is_error=is_error)

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
            0x0051: [1],
            0x0060: [1],
            0x0061: [0],
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
    assert snapshot.interlock_word == 1
    assert snapshot.run_control_word == 1
    assert snapshot.estop_status == 0


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


def test_register_field_encodes_scaled_u16():
    field = RegisterField(name="temperature_setpoint_c", address=0x0002, scale=10.0)
    assert field.encode(915.0) == [9150]


def test_simulation_mode_applies_setpoints():
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)
    applied = client.apply_setpoints(
        temperature_c=900.0,
        ramp_rate_cpm=10.0,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
    )

    assert applied["temperature_setpoint_c"] == 900.0
    assert client.last_applied_setpoints == applied


def test_simulation_mode_applies_run_control_command():
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)
    word = client.issue_run_control("start")

    assert word == 0x0001
    assert client.last_run_control_command == "start"
    assert client.last_run_control_word == 0x0001


def test_hardware_mode_applies_setpoints_to_registers():
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=3, simulation_mode=False)
    fake = _FakeSerialClient({})
    client._client = fake

    client.apply_setpoints(
        temperature_c=900.0,
        ramp_rate_cpm=10.0,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
    )

    assert fake.writes == [
        (0x0002, 9000, 3),
        (0x0003, 100, 3),
        (0x0030, 400, 3),
        (0x0031, 100, 3),
        (0x0032, 50, 3),
    ]


def test_hardware_mode_pulses_run_control_word():
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=3, simulation_mode=False)
    fake = _FakeSerialClient({})
    client._client = fake

    word = client.issue_run_control("reset")

    assert word == 0x0010
    assert fake.writes == [
        (0x0060, 0x0010, 3),
        (0x0060, 0, 3),
    ]


def test_hardware_mode_rolls_back_previous_setpoints_on_write_failure():
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=3, simulation_mode=False)
    fake = _FakeSerialClient({}, fail_addresses={0x0031})
    client._client = fake
    client.last_applied_setpoints = {
        "temperature_setpoint_c": 850.0,
        "ramp_rate_setpoint_cpm": 8.0,
        "n2_setpoint_lpm": 3.5,
        "h2_setpoint_lpm": 0.8,
        "co_setpoint_lpm": 0.3,
    }

    try:
        client.apply_setpoints(
            temperature_c=900.0,
            ramp_rate_cpm=10.0,
            n2_lpm=4.0,
            h2_lpm=1.0,
            co_lpm=0.5,
        )
    except ModbusWriteError as exc:
        assert "rollback applied" in str(exc)
    else:
        assert False, "expected ModbusWriteError"

    assert client.last_applied_setpoints["temperature_setpoint_c"] == 850.0
    assert fake.writes == [
        (0x0002, 9000, 3),
        (0x0003, 100, 3),
        (0x0030, 400, 3),
        (0x0031, 100, 3),
        (0x0002, 8500, 3),
        (0x0003, 80, 3),
        (0x0030, 350, 3),
        (0x0031, 80, 3),
        (0x0032, 30, 3),
    ]
