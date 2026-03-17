from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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


@dataclass
class MfcSnapshot:
    """单台 MQV 质量流量控制器的瞬时状态快照。"""
    channel_id: int          # 通道编号 1–6
    gas_label: str           # 气体标识，如 "H2"、"N2"
    pv_lpm: float            # 实际流量（L/min），NaN 表示读取失败
    sp_lpm: float            # 当前设定值（L/min）
    end_code: str = "00"     # 协议结束代码，"00"=正常
    error: Optional[str] = field(default=None)  # 通信错误描述，无错误时为 None
