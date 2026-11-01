from dataclasses import dataclass, field
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
    ar_lpm: float = 0.0
    co2_lpm: float = 0.0
    ch4_lpm: float = 0.0
    o2_lpm: float = 0.0
    phase: str = "run"  # "run" while recipe steps execute, "purge" during safe disposal


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
    # Measured flow per gas key; backends that only know N2/H2/CO leave it empty.
    flows_lpm: dict[str, float] = field(default_factory=dict)
    # Set-point readback per gas key from the MFCs; None when the backend cannot read it back.
    setpoints_lpm: dict[str, float] | None = None

    def flows(self) -> dict[str, float]:
        if self.flows_lpm:
            return dict(self.flows_lpm)
        return {"N2": self.n2_lpm, "H2": self.h2_lpm, "CO": self.co_lpm}


@dataclass(frozen=True)
class MultiDeviceSnapshot:
    temperatures_c: tuple[float, ...]
    mfc_flows_lpm: dict[int, float]
    mfc_setpoints_lpm: dict[int, float]
    weight_g: float
    degraded_devices: tuple[str, ...]
