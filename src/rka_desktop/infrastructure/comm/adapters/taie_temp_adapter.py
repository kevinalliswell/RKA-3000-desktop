from __future__ import annotations

from rka_desktop.infrastructure.comm.exceptions import DeviceCommError


class TaieTempAdapter:
    """Real temperature adapter wrapping a vendored TaieTemperatureController."""

    def __init__(self, controller) -> None:
        self._ctrl = controller

    @classmethod
    def from_config(cls, cfg) -> "TaieTempAdapter":
        from rka_desktop.infrastructure.comm._vendor.taie_temp import create_default_controller

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

    def write_program_segment(self, group: int, segment: int, sv: float, time_raw: int) -> None:
        try:
            self._ctrl.write_program_curve_segment(group=group, segment=segment, sv=float(sv), duration_raw=int(time_raw))
        except Exception as exc:  # noqa: BLE001
            raise DeviceCommError(f"temperature program segment {group}/{segment} write failed: {exc}") from exc

    def select_program_group(self, group: int) -> None:
        try:
            self._ctrl.write_program_group(int(group))
        except Exception as exc:  # noqa: BLE001
            raise DeviceCommError(f"temperature program group select failed: {exc}") from exc
