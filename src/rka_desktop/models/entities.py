from dataclasses import dataclass
from datetime import datetime


@dataclass
class Measurement:
    experiment_id: int
    sampled_at: datetime
    temperature_c: float
    weight_g: float
    pressure_mpa: float
    n2_lpm: float
    h2_lpm: float
    co_lpm: float


@dataclass
class DeviceSnapshot:
    temperature_c: float
    weight_g: float
    pressure_mpa: float
    n2_lpm: float
    h2_lpm: float
    co_lpm: float
    alarm_word: int
    interlock_word: int = 0
    run_control_word: int = 0
    estop_status: int = 0


@dataclass(frozen=True)
class MultiDeviceSnapshot:
    temperatures_c: tuple[float, ...]
    mfc_flows_lpm: dict[int, float]
    mfc_setpoints_lpm: dict[int, float]
    weight_g: float
    degraded_devices: tuple[str, ...]
