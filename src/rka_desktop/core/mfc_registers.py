"""MQV 系列质量流量控制器寄存器地址映射表。

地址编码规则（协议帧 4 位十六进制地址字段）：
  0x0xxx → RAM 区（掉电丢失，读取实时值）
  0x1xxx → EEPROM 区（掉电保持，读写设定值）

可信度标注：
  [DOC]      — 协议文档图像中明确给出，已验证
  [TYPICAL]  — MQV 系列通用寄存器，使用前建议实机确认
  [RESERVED] — 预留，含义待查手册确认

参考：references/MQV质量流量控制器通信协议.md
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


# ---------------------------------------------------------------------------
# RAM 寄存器（0x0xxx，只读为主，实时值）
# ---------------------------------------------------------------------------

class RamAddr(IntEnum):
    # --- 实时测量值 [DOC] ---
    SP_CURRENT    = 0x04B6  # 当前使用中的 SP 值（RAM 镜像）
    PV            = 0x04B7  # 实际流量测量值（Process Value）

    # --- 控制输出 [TYPICAL] ---
    MV            = 0x04B8  # 操作量输出值（Manipulated Variable，0–10000）

    # --- 状态与报警 [TYPICAL] ---
    ALARM_STATUS  = 0x04B9  # 报警状态字（bit 映射见 AlarmBit）
    DEVICE_STATUS = 0x04BA  # 设备状态字（bit 映射见 DeviceStatusBit）

    # --- 量程信息 [TYPICAL] ---
    RANGE_HIGH    = 0x04BC  # 量程上限（与满量程计数 10000 对应）
    RANGE_LOW     = 0x04BD  # 量程下限（通常为 0）


# ---------------------------------------------------------------------------
# EEPROM 寄存器（0x1xxx，可读写，掉电保持）
# ---------------------------------------------------------------------------

class EepromAddr(IntEnum):
    # --- 多段流量设定值 SP-0 ~ SP-7 [DOC/TYPICAL] ---
    SP_0          = 0x1131  # 设定流量 SP-0（[DOC] 文档明确给出）
    SP_1          = 0x1132  # 设定流量 SP-1  [TYPICAL]
    SP_2          = 0x1133  # 设定流量 SP-2  [TYPICAL]
    SP_3          = 0x1134  # 设定流量 SP-3  [TYPICAL]
    SP_4          = 0x1135  # 设定流量 SP-4  [TYPICAL]
    SP_5          = 0x1136  # 设定流量 SP-5  [TYPICAL]
    SP_6          = 0x1137  # 设定流量 SP-6  [TYPICAL]
    SP_7          = 0x1138  # 设定流量 SP-7  [TYPICAL]

    # --- 报警阈值 [TYPICAL] ---
    ALARM_HIGH    = 0x1141  # 流量高报警阈值
    ALARM_LOW     = 0x1142  # 流量低报警阈值

    # --- 通信参数 [TYPICAL] ---
    MACHINE_ADDR  = 0x1200  # 机器地址（需重启生效）
    BAUD_RATE     = 0x1201  # 波特率代码（0=2400,1=4800,2=9600,3=19200）

    # --- 设备信息（只读 EEPROM）[TYPICAL] ---
    FULL_SCALE    = 0x1300  # 出厂满量程（计数值，通常为 10000）
    MODEL_CODE    = 0x1310  # 型号代码   [RESERVED]
    SERIAL_NO     = 0x1320  # 序列号低位 [RESERVED]


# ---------------------------------------------------------------------------
# 协议常量
# ---------------------------------------------------------------------------

FULL_SCALE_COUNT = 10000
"""满量程计数基准值。实际流量 = raw / FULL_SCALE_COUNT × full_scale_lpm。"""


# ---------------------------------------------------------------------------
# 报警状态位定义（RamAddr.ALARM_STATUS bit mask）[TYPICAL]
# ---------------------------------------------------------------------------

class AlarmBit(IntEnum):
    FLOW_HIGH      = 0x0001  # 流量高报警
    FLOW_LOW       = 0x0002  # 流量低报警
    SENSOR_FAIL    = 0x0004  # 传感器故障
    VALVE_FAIL     = 0x0008  # 阀门故障
    COMM_ERROR     = 0x0010  # 通信异常
    POWER_FAIL     = 0x0020  # 电源异常


# ---------------------------------------------------------------------------
# 设备状态位定义（RamAddr.DEVICE_STATUS bit mask）[TYPICAL]
# ---------------------------------------------------------------------------

class DeviceStatusBit(IntEnum):
    RUNNING        = 0x0001  # 设备运行中
    ALARM_ACTIVE   = 0x0002  # 有未清除报警
    EXTERNAL_SP    = 0x0004  # 外部切换输入激活（通讯写 SP 受限）
    WARMING_UP     = 0x0008  # 预热中


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def sp_eeprom_addr(index: int) -> int:
    """返回第 index 段（0–7）SP 的 EEPROM 地址。"""
    if not 0 <= index <= 7:
        raise ValueError(f"SP 段索引必须在 0–7 范围内，传入 {index}")
    return int(EepromAddr.SP_0) + index


@dataclass(frozen=True)
class RegisterInfo:
    """寄存器元信息，供调试与日志使用。"""
    addr: int
    name: str
    area: str        # "RAM" 或 "EEPROM"
    access: str      # "R" / "RW"
    note: str
    confirmed: bool  # True=文档明确，False=TYPICAL


REGISTER_MAP: list[RegisterInfo] = [
    # RAM
    RegisterInfo(0x04B6, "SP_CURRENT",    "RAM",    "R",  "当前使用中的 SP 值",          True),
    RegisterInfo(0x04B7, "PV",            "RAM",    "R",  "实际流量测量值",              True),
    RegisterInfo(0x04B8, "MV",            "RAM",    "R",  "操作量输出值 0–10000",        False),
    RegisterInfo(0x04B9, "ALARM_STATUS",  "RAM",    "R",  "报警状态字 (见 AlarmBit)",    False),
    RegisterInfo(0x04BA, "DEVICE_STATUS", "RAM",    "R",  "设备状态字 (见 DeviceStatusBit)", False),
    RegisterInfo(0x04BC, "RANGE_HIGH",    "RAM",    "R",  "量程上限",                    False),
    RegisterInfo(0x04BD, "RANGE_LOW",     "RAM",    "R",  "量程下限",                    False),
    # EEPROM
    RegisterInfo(0x1131, "SP_0",          "EEPROM", "RW", "设定流量 SP-0",               True),
    RegisterInfo(0x1132, "SP_1",          "EEPROM", "RW", "设定流量 SP-1",               False),
    RegisterInfo(0x1133, "SP_2",          "EEPROM", "RW", "设定流量 SP-2",               False),
    RegisterInfo(0x1134, "SP_3",          "EEPROM", "RW", "设定流量 SP-3",               False),
    RegisterInfo(0x1135, "SP_4",          "EEPROM", "RW", "设定流量 SP-4",               False),
    RegisterInfo(0x1136, "SP_5",          "EEPROM", "RW", "设定流量 SP-5",               False),
    RegisterInfo(0x1137, "SP_6",          "EEPROM", "RW", "设定流量 SP-6",               False),
    RegisterInfo(0x1138, "SP_7",          "EEPROM", "RW", "设定流量 SP-7",               False),
    RegisterInfo(0x1141, "ALARM_HIGH",    "EEPROM", "RW", "流量高报警阈值",              False),
    RegisterInfo(0x1142, "ALARM_LOW",     "EEPROM", "RW", "流量低报警阈值",              False),
    RegisterInfo(0x1200, "MACHINE_ADDR",  "EEPROM", "RW", "机器地址（重启生效）",        False),
    RegisterInfo(0x1201, "BAUD_RATE",     "EEPROM", "RW", "波特率代码",                  False),
    RegisterInfo(0x1300, "FULL_SCALE",    "EEPROM", "R",  "出厂满量程计数值",            False),
]
