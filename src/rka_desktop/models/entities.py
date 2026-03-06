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
