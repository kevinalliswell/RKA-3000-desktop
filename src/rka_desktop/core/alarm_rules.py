from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlarmDefinition:
    bit_mask: int
    code: str
    level: str
    message: str
    interlock: bool


DEFAULT_ALARM_DEFINITIONS: tuple[AlarmDefinition, ...] = (
    AlarmDefinition(0x0001, "ALM-0001", "CRITICAL", "温度采集异常", True),
    AlarmDefinition(0x0002, "ALM-0002", "CRITICAL", "炉温超限", True),
    AlarmDefinition(0x0004, "ALM-0004", "HIGH", "气路压力异常", True),
    AlarmDefinition(0x0008, "ALM-0008", "HIGH", "过程气体流量偏差", True),
    AlarmDefinition(0x0010, "ALM-0010", "MEDIUM", "称重信号异常", False),
    AlarmDefinition(0x0020, "ALM-0020", "MEDIUM", "通信质量告警", False),
)


def decode_alarm_word(alarm_word: int) -> list[AlarmDefinition]:
    active = [definition for definition in DEFAULT_ALARM_DEFINITIONS if alarm_word & definition.bit_mask]
    known_mask = 0
    for definition in active:
        known_mask |= definition.bit_mask

    unknown_mask = alarm_word & ~known_mask
    bit = 1
    while unknown_mask:
        if unknown_mask & bit:
            active.append(
                AlarmDefinition(
                    bit_mask=bit,
                    code=f"ALM-{bit:04X}",
                    level="HIGH",
                    message=f"未定义报警位 {bit:#06x}",
                    interlock=True,
                )
            )
            unknown_mask &= ~bit
        bit <<= 1

    active.sort(key=lambda item: item.bit_mask)
    return active


def alarm_text_from_word(alarm_word: int) -> str:
    if alarm_word == 0:
        return "正常"

    active = decode_alarm_word(alarm_word)
    if not active:
        return f"报警字: {alarm_word}"

    preview = " / ".join(definition.message for definition in active[:3])
    if len(active) > 3:
        preview += f" 等 {len(active)} 项"
    return preview


def has_interlock_alarm(alarm_word: int) -> bool:
    return any(definition.interlock for definition in decode_alarm_word(alarm_word))
