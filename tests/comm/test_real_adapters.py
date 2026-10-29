from rka_desktop.comm._vendor.azbil_mfc.device_catalog import FlowScale
from rka_desktop.comm.adapters.azbil_mfc_adapter import AzbilMfcAdapter
from rka_desktop.comm.adapters.balance_adapter import BalanceAdapter
from rka_desktop.comm.adapters.taie_temp_adapter import TaieTempAdapter
from rka_desktop.comm.config import default_mfc_channels
from rka_desktop.comm.exceptions import DeviceCommError


class _FakeBusManager:
    """Stands in for azbil MQVBusManager with 0.01 L/min units."""

    def __init__(self) -> None:
        self.pv_counts = {1: 100, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
        self.sp_counts = {1: 0, 2: 250, 3: 0, 4: 0, 5: 0, 6: 0}
        self.written: list[tuple[int, int, int]] = []  # (address, sp_number, counts)
        self.bus = self
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.closed = True

    def get_device(self, address):
        manager = self

        class _Dev:
            def read_pv(self_inner) -> int:
                return manager.pv_counts[address]

            def read_sp(self_inner) -> int:
                return manager.sp_counts[address]

            def write_sp(self_inner, sp_number: int, value: int) -> None:
                manager.written.append((address, sp_number, value))

        return _Dev()

    def read_all_pv(self) -> dict[int, int]:
        return dict(self.pv_counts)

    def get_flow_scale(self, address, refresh=False):
        full_scale = default_mfc_channels()[address - 1].full_scale_lpm
        return FlowScale(int(full_scale * 100), 3, 1)


def test_azbil_counts_convert_to_lpm():
    channels = default_mfc_channels()  # address 1 == H2, full_scale 2.0 L/min
    adapter = AzbilMfcAdapter(_FakeBusManager(), channels)
    # Device full scale is 200 raw counts with 0.01 L/min precision.
    assert adapter.read_all_pv()[1] == 1.0
    assert adapter.gas_type(1) == "H2"


def test_azbil_set_flow_converts_lpm_to_counts():
    channels = default_mfc_channels()  # address 2 == N2, full_scale 5.0 L/min
    fake = _FakeBusManager()
    adapter = AzbilMfcAdapter(fake, channels, write_enabled=True)
    adapter.set_flow(2, 2.5)
    assert fake.written == [(2, 0, 250)]


def test_azbil_read_all_sp_converts_counts():
    channels = default_mfc_channels()  # address 2 == N2, full_scale 5.0
    adapter = AzbilMfcAdapter(_FakeBusManager(), channels)
    sp = adapter.read_all_sp()
    # address 2: 250 raw counts * 0.01 == 2.5 L/min
    assert sp[2] == 2.5
    assert set(sp.keys()) == {1, 2, 3, 4, 5, 6}


class _RaisingBusManager:
    bus = None

    def get_device(self, _address):
        raise OSError("bus down")


def test_azbil_read_all_pv_records_per_channel_errors():
    adapter = AzbilMfcAdapter(_RaisingBusManager(), default_mfc_channels())
    assert adapter.read_all_pv() == {}
    assert set(adapter.last_errors) == set(range(1, 7))


def test_mfc_partial_failure_and_scale_mismatch_do_not_corrupt_other_channels():
    fake = _FakeBusManager()
    fake.pv_counts.pop(2)
    original_scale = fake.get_flow_scale
    fake.get_flow_scale = lambda address, refresh=False: (
        FlowScale(900, 3, 1) if address == 3 else original_scale(address)
    )
    adapter = AzbilMfcAdapter(fake, default_mfc_channels())
    values = adapter.read_all_pv()
    assert 1 in values and 2 not in values and 3 not in values
    assert 2 in adapter.last_errors
    assert "differs" in adapter.last_errors[3]


def test_real_mfc_write_is_disabled_by_default():
    fake = _FakeBusManager()
    adapter = AzbilMfcAdapter(fake, default_mfc_channels())
    try:
        adapter.set_flow(2, 1.0)
    except DeviceCommError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("real MFC write must be disabled")
    assert fake.written == []


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
    adapter = TaieTempAdapter(_FakeController(), write_enabled=True)
    adapter.connect()
    assert adapter.read_pv() == 850.0
    adapter.write_sv(900.0)
    assert adapter.read_sv() == 900.0


class _RaisingController:
    def open(self) -> None: ...

    def close(self) -> None: ...

    def read_pv(self) -> float:
        raise OSError("temp down")

    def read_sv(self) -> float:
        return 0.0

    def write_sv(self, value: float) -> float:
        return value


def test_taie_read_pv_wraps_driver_errors():
    adapter = TaieTempAdapter(_RaisingController())
    try:
        adapter.read_pv()
    except DeviceCommError:
        return
    raise AssertionError("expected DeviceCommError")


def test_real_temperature_write_is_disabled_by_default():
    adapter = TaieTempAdapter(_FakeController())
    try:
        adapter.write_sv(900)
    except DeviceCommError as exc:
        assert "disabled" in str(exc)
        return
    raise AssertionError("real temperature write must be disabled")


class _FakeMessage:
    def __init__(self, weight):
        self.weight = weight
        self.kind = "reading"
        self.stable = True


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

    def send_tare_and_wait(self):
        class _Result:
            success = True

        return _Result()


def test_balance_adapter_reads_weight():
    adapter = BalanceAdapter(_FakeBalanceClient(weight=88.0))
    assert adapter.read_weight() == 88.0


def test_balance_adapter_tare_requires_zero_reading():
    adapter = BalanceAdapter(_FakeBalanceClient(), write_enabled=True)
    assert adapter.tare() is True


def test_balance_ack_alone_does_not_confirm_tare():
    fake = _FakeBalanceClient()
    fake.send_tare_and_wait = lambda: type("Result", (), {"success": False})()
    assert BalanceAdapter(fake, write_enabled=True).tare() is False


def test_balance_error_frame_is_not_a_weight():
    fake = _FakeBalanceClient()
    fake.read_message = lambda: type(
        "Error", (), {"kind": "error", "code": "E01", "raw": "E01"}
    )()
    try:
        BalanceAdapter(fake).read_weight()
    except DeviceCommError as exc:
        assert "E01" in str(exc)
    else:
        raise AssertionError("balance error frame must raise")


def test_balance_rejects_unstable_frames_and_real_tare_is_disabled():
    fake = _FakeBalanceClient()
    fake.read_message = lambda: type("Reading", (), {"kind": "reading", "stable": False, "weight": 88.0})()
    adapter = BalanceAdapter(fake)
    assert adapter.read_weight() is None
    try:
        adapter.tare()
    except DeviceCommError as exc:
        assert "disabled" in str(exc)
        return
    raise AssertionError("real tare must be disabled")


def test_balance_adapter_wraps_driver_errors():
    adapter = BalanceAdapter(_FakeBalanceClient(raises=True))
    try:
        adapter.read_weight()
    except DeviceCommError:
        return
    raise AssertionError("expected DeviceCommError")
