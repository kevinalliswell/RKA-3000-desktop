from rka_desktop.comm.adapters.azbil_mfc_adapter import AzbilMfcAdapter
from rka_desktop.comm.adapters.balance_adapter import BalanceAdapter
from rka_desktop.comm.adapters.taie_temp_adapter import TaieTempAdapter
from rka_desktop.comm.config import default_mfc_channels
from rka_desktop.comm.exceptions import DeviceCommError


class _FakeBusManager:
    """Stands in for azbil MQVBusManager. PV/SP are in raw counts (0..FULL_SCALE_COUNTS)."""

    def __init__(self) -> None:
        self.pv_counts = {1: 25000, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
        self.sp_counts = {1: 0, 2: 25000, 3: 0, 4: 0, 5: 0, 6: 0}
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


def test_azbil_read_all_sp_converts_counts():
    channels = default_mfc_channels()  # address 2 == N2, full_scale 5.0
    adapter = AzbilMfcAdapter(_FakeBusManager(), channels)
    sp = adapter.read_all_sp()
    # address 2: 25000 / 50000 * 5.0 == 2.5 L/min
    assert sp[2] == 2.5
    assert set(sp.keys()) == {1, 2, 3, 4, 5, 6}


class _RaisingBusManager:
    bus = None

    def read_all_pv(self):
        raise OSError("bus down")


def test_azbil_read_all_pv_wraps_driver_errors():
    adapter = AzbilMfcAdapter(_RaisingBusManager(), default_mfc_channels())
    try:
        adapter.read_all_pv()
    except DeviceCommError:
        return
    raise AssertionError("expected DeviceCommError")


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

    def send_tare_and_wait(self):
        class _Result:
            ack_received = True

        return _Result()


def test_balance_adapter_reads_weight():
    adapter = BalanceAdapter(_FakeBalanceClient(weight=88.0))
    assert adapter.read_weight() == 88.0


def test_balance_adapter_tare_returns_ack():
    adapter = BalanceAdapter(_FakeBalanceClient())
    assert adapter.tare() is True


def test_balance_adapter_wraps_driver_errors():
    adapter = BalanceAdapter(_FakeBalanceClient(raises=True))
    try:
        adapter.read_weight()
    except DeviceCommError:
        return
    raise AssertionError("expected DeviceCommError")
