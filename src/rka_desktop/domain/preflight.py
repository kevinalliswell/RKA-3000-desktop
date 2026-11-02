"""Preflight rules: sample information and the on-site checklist the operator attests to.

The checklist is an operator attestation recorded with the experiment; the software cannot
observe gas cylinder pressure or ventilation itself. Device freshness, recipe runnability and
alarm state are evaluated by the application from live data.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from rka_desktop.domain.gases import ExperimentType

MASS_TOLERANCE_PCT = 0.5
MAX_TEXT = 60


@dataclass(frozen=True)
class ChecklistItem:
    key: str
    label: str
    detail: str


SITE_CHECKLIST: tuple[ChecklistItem, ...] = (
    ChecklistItem("serial", "串口与设备自检通过", "温控器、MFC 总线、天平在 3 个采样周期内均有有效回读"),
    ChecklistItem("calibration", "温控器与 MFC 校准在有效期", "以实验室设备校准记录为准"),
    ChecklistItem("balance", "天平已去皮并放入样品", "读数稳定 ≥ 10 s，与输入质量偏差 ≤ 0.5%"),
    ChecklistItem("gas", "气瓶压力与管路已确认", "惰性气及本次工艺气瓶压力满足要求，管路无泄漏"),
    ChecklistItem("ventilation", "通风与可燃气报警器正常", "CO / 可燃气报警器自检通过，排风开启"),
    ChecklistItem("interlock", "炉门关闭、联锁复位", "超温与断气联锁均处于投用状态"),
)
CHECKLIST_KEYS = tuple(item.key for item in SITE_CHECKLIST)


class PreflightError(ValueError):
    pass


@dataclass(frozen=True)
class SampleInfo:
    name: str
    initial_mass_g: float
    tfe_pct: float
    feo_pct: float
    operator: str
    particle_size: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any, label: str, problems: list[str], *, required: bool) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if required and not text:
        problems.append(f"请填写{label}")
    elif len(text) > MAX_TEXT:
        problems.append(f"{label}不能超过 {MAX_TEXT} 字")
    return text[:MAX_TEXT]


def _num(value: Any, label: str, problems: list[str], *, low: float, high: float, low_inclusive: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        problems.append(f"{label}必须是数字")
        return 0.0
    number = float(value)
    ok = (number >= low if low_inclusive else number > low) and number <= high
    if not ok:
        problems.append(f"{label}须在 {'[' if low_inclusive else '('}{low:g}, {high:g}] 范围内")
    return number


def parse_sample(payload: Any, experiment_type: ExperimentType | None = None) -> tuple[SampleInfo | None, list[str]]:
    """Validate sample fields; returns the sample (or None) and the list of problems."""
    problems: list[str] = []
    if not isinstance(payload, dict):
        return None, ["请填写样品信息"]
    name = _text(payload.get("name"), "样品名称", problems, required=True)
    operator = _text(payload.get("operator"), "操作者", problems, required=True)
    particle = _text(payload.get("particle_size"), "粒径范围", problems, required=False)
    mass = _num(payload.get("initial_mass_g"), "初始质量", problems, low=0, high=10_000, low_inclusive=False)
    tfe = _num(payload.get("tfe_pct"), "TFe", problems, low=0, high=100, low_inclusive=False)
    feo = _num(payload.get("feo_pct", 0), "FeO", problems, low=0, high=100, low_inclusive=True)
    if experiment_type == ExperimentType.OXIDATION and not problems and feo <= 0:
        problems.append("氧化实验按 FeO → Fe₂O₃ 计算氧化度，FeO 须大于 0")
    if problems:
        return None, problems
    return SampleInfo(name=name, initial_mass_g=mass, tfe_pct=tfe, feo_pct=feo, operator=operator, particle_size=particle), []


def parse_checklist(payload: Any) -> dict[str, bool]:
    """Only known keys count; anything not explicitly ``true`` is unchecked."""
    raw = payload if isinstance(payload, dict) else {}
    return {key: raw.get(key) is True for key in CHECKLIST_KEYS}


def mass_deviation_pct(entered_g: float, balance_g: float | None) -> float | None:
    if balance_g is None or entered_g <= 0:
        return None
    return abs(balance_g - entered_g) / entered_g * 100.0
